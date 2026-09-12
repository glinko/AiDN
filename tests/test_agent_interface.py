from __future__ import annotations

import os
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidn_hypervisor.agent_interface import AgentInterfaceStore, PresentationRequest
from aidn_hypervisor.api import build_api_router
from aidn_hypervisor.bundle_hash import bundle_config_hash
from aidn_hypervisor.endpoints.models import CreateEndpointCommand, UpdateEndpointCommand
from aidn_hypervisor.mcp import McpRemoteGateway, build_mcp_remote_router
from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.runtime_parameter_policy import default_runtime_parameter_policy
from aidn_hypervisor.secrets import FileSecretManager
from tests.test_mcp_remote import _headers
from tests.test_mcp_remote import _initialize as initialize_remote
from tests.test_mcp_server import _call, _endpoint_server, _initialize


def setup_frame(*, approval=False, scopes=None):
    server = _endpoint_server(
        *(scopes or ("CHAT:WRITE", "ENDPOINT:READ", "ENDPOINT:WRITE", "BUNDLE:READ", "NODE:READ", "AUDIT:READ")),
        approval_policy={"endpoint_write": "OPERATOR_CONFIRMATION" if approval else "AUTO"},
    )
    _initialize(server)
    control = server.control
    bundle = control.service.bundle_config()[0].model_copy(
        update={"provider_type": "llama.cpp", "runtime_parameter_policy": default_runtime_parameter_policy("llama.cpp")}
    )
    control.service.bundle_config = lambda: [bundle]
    control.service.bundle_for_runtime_binding = lambda _id: bundle
    endpoint = control.endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-test",
            bundle_id=bundle.bundle_id,
            bundle_hash=bundle_config_hash(bundle),
            runtime_binding_id="rtb-a",
            display_name="LLM",
            model_class="llm_text",
            capabilities=["llm_text"],
            runtime_parameter_policy=default_runtime_parameter_policy("llama.cpp"),
        )
    ).endpoint
    channel = control.service.agent_channel
    channel.connect("agent:test")
    channel.send("Покажи настройки llama.cpp", request_id="request-read", surface_id="surface-a")
    read = _call(
        server, "aidn.ui.read", {"request_id": "request-read", "kind": "endpoint", "target_id": endpoint.endpoint_id}
    )
    assert not read["isError"], read
    source = read["structuredContent"]
    present = _call(
        server,
        "aidn.ui.present",
        {
            "request_id": "request-read",
            "document": {
                "document_id": "llama-settings",
                "title": "Настройки llama.cpp",
                "blocks": [
                    {"type": "text", "text": "Параметры запросов к endpoint."},
                    {
                        "type": "fields",
                        "source_id": source["source_id"],
                        "field_ids": [
                            "display_name",
                            "local_agent_use",
                            "parameter.temperature",
                            "parameter.context_length",
                        ],
                    },
                ],
            },
        },
    )
    assert not present["isError"], present
    return server, source, present["structuredContent"]["document"]


def change_for(source, document, proposed):
    values = {field["id"]: field["value"] for field in source["fields"]}
    return {
        "kind": "form_change",
        "document_id": document["document_id"],
        "document_revision": document["revision"],
        "source_id": source["source_id"],
        "source_revision": source["revision"],
        "current": {key: values[key] for key in proposed},
        "proposed": proposed,
    }


def submit(server, source, document, proposed, request_id="request-change"):
    return server.control.service.agent_channel.send(
        "Примени изменения",
        request_id=request_id,
        surface_id="surface-a",
        interaction=change_for(source, document, proposed),
    )


def apply(server, intent_id="request-change"):
    args = {"intent_id": intent_id, "request_id": intent_id, "idempotency_key": intent_id, "mode": "plan"}
    plan = _call(server, "aidn.ui.apply", args)
    if plan["isError"]:
        return plan
    if plan["structuredContent"].get("state") == "APPLIED":
        return plan
    return _call(
        server, "aidn.ui.apply", {**args, "mode": "apply", "plan_hash": plan["structuredContent"]["plan_hash"]}
    )


def test_real_mcp_field_edit_is_only_applied_by_agent_and_verified_in_same_frame():
    server, source, document = setup_frame()
    channel = server.control.service.agent_channel
    assert all("data" not in block for block in document["blocks"])
    before = server.control.endpoint_service.get_endpoint(source["target_id"]).endpoint
    submit(server, source, document, {"parameter.temperature": 0.4})
    assert server.control.endpoint_service.get_endpoint(source["target_id"]).endpoint == before
    inbox = _call(server, "aidn.event.inbox")["structuredContent"]
    event = next(item for item in inbox["items"] if item["payload"].get("ui", {}).get("intent_id") == "request-change")
    assert event["payload"]["ui"]["diff"] == [{"path": "parameter.temperature", "from": 0.7, "to": 0.4}]
    applied = apply(server)
    assert not applied["isError"], applied
    assert applied["structuredContent"]["verified"] is True
    after = server.control.endpoint_service.get_endpoint(source["target_id"]).endpoint
    assert after.runtime_parameter_policy["temperature"].value == 0.4
    updated = channel.status("surface-a")["interface"]["documents"][0]
    assert updated["document_id"] == document["document_id"]
    assert updated["revision"] == document["revision"] + 1
    assert (
        next(field for field in updated["blocks"][1]["fields"] if field["id"] == "parameter.temperature")["value"]
        == 0.4
    )
    assert channel.status("surface-b")["interface"]["documents"] == []


def test_local_access_uses_real_endpoint_service_and_does_not_rotate_publication_hash():
    server, source, document = setup_frame()
    before = server.control.endpoint_service.get_endpoint(source["target_id"]).endpoint
    submit(server, source, document, {"local_agent_use": True})
    assert not apply(server)["isError"]
    after = server.control.endpoint_service.get_endpoint(source["target_id"]).endpoint
    assert after.local_agent_use is True
    assert after.configuration_hash == before.configuration_hash


@pytest.mark.parametrize(
    "proposed",
    [
        {"parameter.context_length": 8000},
        {"status": "running"},
        {"parameter.temperature": 7},
        {"parameter.temperature": "0.4"},
        {"local_agent_use": 1},
    ],
)
def test_invalid_readonly_and_wrong_typed_changes_never_reach_mcp(proposed):
    server, source, document = setup_frame()
    with pytest.raises(ValueError):
        submit(server, source, document, proposed)
    assert server.control.service.agent_channel.status("surface-a")["interface"]["intents"] == []


def test_stale_node_state_and_forged_original_value_are_rejected():
    server, source, document = setup_frame()
    channel = server.control.service.agent_channel
    change = change_for(source, document, {"display_name": "New"})
    change["current"]["display_name"] = "Invented original"
    with pytest.raises(ValueError, match="Original"):
        channel.send("apply", request_id="forged", surface_id="surface-a", interaction=change)
    submit(server, source, document, {"display_name": "New"})
    server.control.endpoint_service.update_endpoint(
        UpdateEndpointCommand(endpoint_id=source["target_id"], display_name="Changed elsewhere")
    )
    assert apply(server)["isError"] is True
    assert (
        server.control.endpoint_service.get_endpoint(source["target_id"]).endpoint.display_name == "Changed elsewhere"
    )


def test_duplicate_delivery_is_idempotent_and_persists_with_conversation():
    server, source, document = setup_frame()
    first = submit(server, source, document, {"display_name": "New"})
    assert submit(server, source, document, {"display_name": "New"}) == first
    assert not apply(server)["isError"]
    channel = server.control.service.agent_channel
    snapshot = channel.snapshot_state()
    channel.restore_state(deepcopy(snapshot))
    assert apply(server)["structuredContent"]["verified"] is True
    assert len(channel.status("surface-a")["interface"]["intents"]) == 1
    assert len([item for item in channel.status()["messages"] if item["request_id"] == "request-change"]) == 1
    assert len([item for item in server.control.endpoint_service.list_endpoints() if item.display_name == "New"]) == 1


def test_cross_surface_agent_and_unknown_component_are_rejected():
    server, source, document = setup_frame()
    channel = server.control.service.agent_channel
    channel.send("other", request_id="other", surface_id="surface-b")
    assert _call(
        server,
        "aidn.ui.present",
        {
            "request_id": "other",
            "document": {
                "document_id": "steal",
                "title": "other",
                "blocks": [{"type": "fields", "source_id": source["source_id"]}],
            },
        },
    )["isError"]
    assert _call(
        server,
        "aidn.ui.present",
        {
            "request_id": "request-read",
            "document": {
                "document_id": "unsafe",
                "title": "unsafe",
                "blocks": [{"type": "html", "html": "<script>alert(1)</script>"}],
            },
        },
    )["isError"]
    channel.connect("agent:other")
    assert _call(
        server, "aidn.ui.read", {"request_id": "request-read", "kind": "endpoint", "target_id": source["target_id"]}
    )["isError"]
    assert channel.status("surface-a")["interface"]["documents"] == []


def test_read_only_credential_and_mcp_approval_remain_authoritative():
    server, source, document = setup_frame(scopes=("CHAT:WRITE", "ENDPOINT:READ"))
    assert not any(field["editable"] for field in source["fields"])
    assert _call(
        server, "aidn.ui.apply", {"intent_id": "fake", "mode": "plan", "request_id": "fake", "idempotency_key": "fake"}
    )["isError"]
    server, source, document = setup_frame(approval=True)
    submit(server, source, document, {"display_name": "New"})
    denied = apply(server)
    assert denied["isError"]
    assert denied["structuredContent"]["error"]["code"] == "MCP_APPROVAL_REQUIRED"
    assert server.control.endpoint_service.get_endpoint(source["target_id"]).endpoint.display_name == "LLM"


def test_scene_is_not_visible_until_agent_explicitly_publishes_it():
    server, _, _ = setup_frame()
    scene = _call(server, "aidn.ui.read", {"request_id": "request-read", "kind": "scene"})
    assert not scene["isError"], scene
    assert server.control.service.agent_channel.status("surface-a")["interface"]["scene"] is None
    published = _call(
        server,
        "aidn.ui.present",
        {"request_id": "request-read", "scene_source_id": scene["structuredContent"]["source_id"]},
    )
    assert not published["isError"], published
    payload = server.control.service.agent_channel.status("surface-a")["interface"]["scene"]["data"]
    assert payload["endpoints"]["items"][0]["display_name"] == "LLM"
    assert "configuration" not in payload["endpoints"]["items"][0]


def test_source_and_document_storage_is_bounded():
    store = AgentInterfaceStore(lambda: None)
    for index in range(70):
        store.register_source(surface_id="a", kind="provider", target_id="p", source_revision=str(index), fields=[])
    assert len(store.sources) == 64
    for index in range(12):
        store.present(
            PresentationRequest.model_validate(
                {
                    "request_id": "r",
                    "document": {
                        "document_id": "d-" + str(index),
                        "title": "Text",
                        "blocks": [{"type": "text", "text": "Hello"}],
                    },
                }
            ),
            surface_id="a",
        )
    assert len(store.documents) == 8


def test_correlated_reply_cannot_be_replayed_as_another_requests_answer():
    server, _, _ = setup_frame()
    reply = _call(server, "aidn.operator.chat.reply", {"request_id": "request-read", "text": "Готово"})
    assert not reply["isError"]
    assert reply["structuredContent"]["request_id"] == "request-read"
    assert reply["structuredContent"]["surface_id"] == "surface-a"
    assert _call(server, "aidn.operator.chat.reply", {"request_id": "unknown", "text": "Готово"})["isError"]


def test_http_form_transport_records_intent_but_cannot_apply_or_forge_a_change():
    server, source, document = setup_frame()
    app = FastAPI()
    app.include_router(build_api_router(server.control.service))
    client = TestClient(app)
    payload = {
        "text": "Примени изменение",
        "request_id": "http-change",
        "surface_id": "surface-a",
        "interaction": change_for(source, document, {"parameter.temperature": 0.3}),
    }
    result = client.post("/operators/dashboard/agent-channel/messages", json=payload)
    assert result.status_code == 200
    assert client.post("/operators/dashboard/agent-channel/messages", json=payload).json() == result.json()
    assert (
        server.control.endpoint_service.get_endpoint(source["target_id"])
        .endpoint.runtime_parameter_policy["temperature"]
        .value
        == 0.7
    )
    status = client.get("/operators/dashboard/agent-channel", params={"surface_id": "surface-a"}).json()
    assert status["interface"]["intents"][0]["state"] == "PROPOSED"
    forged = deepcopy(payload)
    forged["request_id"] = "http-forged"
    forged["interaction"]["current"]["parameter.temperature"] = 1.8
    assert client.post("/operators/dashboard/agent-channel/messages", json=forged).status_code == 409
    assert (
        client.post("/operators/dashboard/agent-channel/messages", json={**payload, "apply": True}).status_code == 422
    )
    assert (
        client.get("/operators/dashboard/agent-channel", params={"surface_id": "other"}).json()["interface"][
            "documents"
        ]
        == []
    )


def test_remote_reader_uses_credential_identity_and_never_inherits_operator_write_scope(tmp_path):
    server, source, _ = setup_frame()
    credentials = McpCredentialStore(
        secret_manager=FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    )
    credential = credentials.create_credential(label="spatial reader", scopes=("CHAT:WRITE", "ENDPOINT:READ"))
    channel = server.control.service.agent_channel
    channel.connect("mcp-credential:" + credential.credential_id)
    channel.send("Покажи endpoint", request_id="remote-read", surface_id="remote-surface")
    gateway = McpRemoteGateway(server.control, agent_token=None, credential_resolver=credentials)
    app = FastAPI()
    app.include_router(build_mcp_remote_router(gateway))
    client = TestClient(app)
    token = credential.token or ""
    session_id = initialize_remote(client, token)
    headers = _headers(token, session_id)

    def call(name, arguments):
        response = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": name, "arguments": arguments}},
        )
        assert response.status_code == 200
        return response.json()["result"]

    read = call("aidn.ui.read", {"request_id": "remote-read", "kind": "endpoint", "target_id": source["target_id"]})
    assert not read["isError"], read
    assert not any(field["editable"] for field in read["structuredContent"]["fields"])
    presented = call(
        "aidn.ui.present",
        {
            "request_id": "remote-read",
            "document": {
                "document_id": "remote-doc",
                "title": "Endpoint",
                "blocks": [{"type": "fields", "source_id": read["structuredContent"]["source_id"]}],
            },
        },
    )
    assert not presented["isError"], presented
    assert channel.status("remote-surface")["interface"]["documents"][0]["document_id"] == "remote-doc"
    assert call(
        "aidn.ui.apply", {"intent_id": "remote-read", "mode": "plan", "request_id": "x", "idempotency_key": "x"}
    )["isError"]


def test_numeric_parameter_type_survives_an_integral_value():
    server, source, document = setup_frame()
    submit(server, source, document, {"parameter.temperature": 0})
    result = apply(server)
    assert not result["isError"], result
    next_source = result["structuredContent"]["source"]
    field = next(item for item in next_source["fields"] if item["id"] == "parameter.temperature")
    assert field["type"] == "number"
    next_document = server.control.service.agent_channel.status("surface-a")["interface"]["documents"][0]
    submit(server, next_source, next_document, {"parameter.temperature": 0.6}, request_id="fractional-change")
    assert not apply(server, "fractional-change")["isError"]


def test_installation_plan_is_presented_as_editable_form_and_confirmation_is_verified(tmp_path, monkeypatch):
    plan_path = tmp_path / "installation-plan.json"
    monkeypatch.setenv("AIDN_INSTALLATION_PLAN_PATH", str(plan_path))
    server = _endpoint_server(
        "CHAT:WRITE",
        "NODE:READ",
        "STEWARD:EXECUTE",
        "ENDPOINT:READ",
        "ENDPOINT:WRITE",
    )
    _initialize(server)
    service = server.control.service
    service.prepare_installation_plan(
        provider="llama.cpp",
        model_id="org/model",
        model_source="hf://org/model/model.gguf",
        endpoint_action="start",
        runtime_policy={
            "context_length": {"requested": 131072, "fallbacks": [65536, 32768], "on_exhausted": "notify"}
        },
    )
    channel = service.agent_channel
    channel.connect("agent:test")
    channel.send("Установи модель", request_id="installation-request", surface_id="surface-a")
    source_result = _call(
        server,
        "aidn.ui.read",
        {"request_id": "installation-request", "kind": "installation"},
    )
    assert not source_result["isError"], source_result
    source = source_result["structuredContent"]
    fields = {item["id"]: item for item in source["fields"]}
    assert fields["runtime.context_length.requested"]["value"] == "131072"
    assert fields["runtime.context_length.fallback_65536"]["editable"] is True
    assert fields["workflow.confirm_installation"]["value"] is False
    presented = _call(
        server,
        "aidn.ui.present",
        {
            "request_id": "installation-request",
            "document": {
                "document_id": "installation-questionnaire",
                "title": "Установка модели",
                "blocks": [
                    {"type": "text", "text": "Проверьте рекомендуемые значения и подтвердите раскатку."},
                    {"type": "fields", "source_id": source["source_id"], "title": "Параметры"},
                ],
            },
        },
    )
    assert not presented["isError"], presented
    document = presented["structuredContent"]["document"]
    values = {item["id"]: item["value"] for item in source["fields"]}
    proposed = {
        "runtime.context_length.requested": "65536",
        "publication.pricing": "paid",
        "publication.tariff.unit_price_q_atoms": 3_000_000,
        "workflow.confirm_installation": True,
    }
    interaction = {
        "kind": "form_change",
        "document_id": document["document_id"],
        "document_revision": document["revision"],
        "source_id": source["source_id"],
        "source_revision": source["revision"],
        "current": {key: values[key] for key in proposed},
        "proposed": proposed,
    }
    channel.send(
        "Подтверждаю установку",
        request_id="installation-confirmation",
        surface_id="surface-a",
        interaction=interaction,
    )
    planned = _call(
        server,
        "aidn.ui.apply",
        {
            "intent_id": "installation-confirmation",
            "mode": "plan",
            "request_id": "installation-confirmation-plan",
            "idempotency_key": "installation-confirmation-plan",
        },
    )
    assert not planned["isError"], planned
    applied = _call(
        server,
        "aidn.ui.apply",
        {
            "intent_id": "installation-confirmation",
            "mode": "apply",
            "request_id": "installation-confirmation-plan",
            "idempotency_key": "installation-confirmation-apply",
            "plan_hash": planned["structuredContent"]["plan_hash"],
        },
    )
    assert not applied["isError"], applied
    result = applied["structuredContent"]
    assert result["verified"] is True
    assert result["installation_confirmed"] is True
    assert result["installation"]["publication_policy"]["pricing"] == "paid"
    assert result["installation"]["runtime_policy"]["context_length"]["requested"] == 65536
    assert result["installation"]["replacement_policy"]["mode"] == "parallel"
    refreshed = channel.status("surface-a")["interface"]["documents"][0]
    assert next(field for field in refreshed["blocks"][1]["fields"] if field["id"] == "workflow.confirm_installation")["value"] is False
