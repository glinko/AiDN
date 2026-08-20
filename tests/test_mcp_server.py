from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidn_hypervisor.bundle_hash import bundle_config_hash
from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.mcp import (
    ControlSession,
    DelegatedBudget,
    McpPersistenceError,
    McpPersistentStateStore,
    McpRemoteGateway,
    build_mcp_remote_router,
    build_mcp_server,
)
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


def _service(*, runtime: bool = False) -> HypervisorService:
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    runtimes = ProviderProcessManager()
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(
                cpu_cores=8,
                ram_mb=16_384,
                gpu_devices=["gpu0"],
                vram_mb={"gpu0": 8_192},
            )
        ),
        bundles=[
            BundleConfig(
                bundle_id="bundle-a",
                plugin_id="fake-managed",
                provider_type="fake",
                workload_type="llm_text",
                model_id="model-a",
                launch_mode="managed_process",
                device_affinity="cpu",
                resource_profile=ResourceProfile(),
                warm_policy="auto",
            )
        ],
        plugins=plugins,
        runtimes=runtimes,
    )
    if runtime:
        service.start_bundle("bundle-a")
    return service


def _session(*scopes: str, approval_policy: dict[str, str] | None = None) -> ControlSession:
    return ControlSession(
        control_session_id="acs-test",
        agent_identity="agent:test",
        operator_identity="operator:test",
        scopes=frozenset(scopes),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        budget=DelegatedBudget(
            budget_id="budget-test",
            max_total_atoms=10_000,
            max_per_operation_atoms=1_000,
            remaining_atoms=10_000,
        ),
        approval_policy=approval_policy or {"bundle_activate": "AUTO"},
    )


def _server(
    *scopes: str,
    approval_policy: dict[str, str] | None = None,
    mcp_state_store: McpPersistentStateStore | None = None,
    runtime: bool = False,
):
    return build_mcp_server(
        _service(runtime=runtime),
        session=_session(*scopes, approval_policy=approval_policy),
        mcp_state_store=mcp_state_store,
    )


def _endpoint_server(*scopes: str, approval_policy: dict[str, str] | None = None):
    service = _service()
    bundle = service.bundle_config()[0]
    service.bundle_for_runtime_binding = lambda _runtime_binding_id: bundle
    service.bundle_hash_for_runtime_binding = lambda _runtime_binding_id: bundle_config_hash(bundle)
    service.list_runtime_bindings = lambda: [
        {
            "runtime_binding_id": "rtb-a",
            "capability_id": "llm_text",
            "status": "ready",
            "operational_state": "READY",
        }
    ]
    service.runtime_binding_endpoint_admission = lambda _runtime_binding_id, endpoint_payload=None: {
        "ready": True,
        "blockers": [],
        "warnings": [],
        "dimensions": {},
    }
    service.owner_wallet_state = lambda: {
        "configured": True,
        "wallet_id": "wallet-test",
        "public_key": None,
    }
    service.owner_wallet_private_key = lambda: None
    service.sync_operator_onboarding_state = lambda **_kwargs: None
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    return build_mcp_server(
        service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=publication_service,
        session=_session(*scopes, approval_policy=approval_policy),
    )


def _call(server, name: str, arguments: dict | None = None) -> dict:
    result = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    )
    assert result is not None
    return result["result"]


def _initialize(server) -> None:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "0.1"},
            },
        }
    )
    assert response["result"]["protocolVersion"] == "2025-06-18"
    assert server.handle_message(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}
    ) is None


def test_mcp_initialize_and_tools_are_scope_filtered() -> None:
    server = _server("CAPABILITIES:READ", "NODE:READ", "BUNDLE:READ")

    _initialize(server)
    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}
    )

    names = {item["name"] for item in response["result"]["tools"]}
    assert "aidn.capabilities.get" in names
    assert "aidn.node.status" in names
    assert "aidn.bundle.list" in names
    assert "aidn.bundle.activate" not in names


def test_mcp_resource_broker_and_scheduler_read_models_are_scope_visible() -> None:
    server = _server("RESOURCES:READ", "SCHEDULER:READ")
    _initialize(server)

    response = server.handle_message(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}
    )
    names = {item["name"] for item in response["result"]["tools"]}
    assert {
        "aidn.resources.status",
        "aidn.resources.forecast",
        "aidn.resources.leases",
        "aidn.resource_broker.status",
        "aidn.resource_broker.forecast",
        "aidn.scheduler.status",
        "aidn.scheduler.queues",
        "aidn.scheduler.candidates",
    } <= names

    forecast = _call(server, "aidn.resources.forecast", {"vram_mb": 9000})
    assert forecast["structuredContent"]["decision"] == "RESOURCE_WAIT"
    assert forecast["structuredContent"]["shortfall"]["vram_mb"] == 808

    leases = _call(server, "aidn.resources.leases")
    assert leases["structuredContent"]["items"] == []
    scheduler = _call(server, "aidn.scheduler.status")
    assert scheduler["structuredContent"]["queue"]["queued_tasks"] == 0
    assert _call(server, "aidn.resource_broker.explain_denial", {"vram_mb": 9000})[
        "structuredContent"
    ]["decision"] == "RESOURCE_WAIT"

    resources = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "resources/read",
            "params": {"uri": "aidn://scheduler/candidates"},
        }
    )
    assert resources["result"]["contents"][0]["mimeType"] == "application/json"


def test_mcp_scheduler_reconcile_is_plan_apply_and_scope_gated() -> None:
    server = _server("SCHEDULER:WRITE")
    _initialize(server)

    listed = server.handle_message(
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}}
    )
    assert "aidn.scheduler.reconcile" in {
        item["name"] for item in listed["result"]["tools"]
    }

    request = {
        "mode": "plan",
        "request_id": "request-reconcile",
        "idempotency_key": "idem-reconcile",
        "trigger": "agent-test",
        "max_cycles": 4,
    }
    plan = _call(server, "aidn.scheduler.reconcile", request)["structuredContent"]
    result = _call(
        server,
        "aidn.scheduler.reconcile",
        {
            **request,
            "mode": "apply",
            "plan_hash": plan["plan_hash"],
        },
    )["structuredContent"]

    assert result["status"] == "stable"
    assert result["trigger"] == "agent-test"
    assert result["plan"]["plan_hash"] == plan["plan_hash"]


def test_mcp_initialize_accepts_hermes_latest_handshake_version() -> None:
    server = _server("CAPABILITIES:READ")
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "hermes", "version": "0.20.3"},
            },
        }
    )

    assert response["result"]["protocolVersion"] == "2025-11-25"


def test_mcp_default_web_session_can_use_an_explicit_persisted_identity(monkeypatch) -> None:
    monkeypatch.setenv("AIDN_MCP_CONTROL_SESSION_ID", "acs-explicit-web")
    server = build_mcp_server(_service())

    assert server.control.session.control_session_id == "acs-explicit-web"


def test_mcp_resources_read_existing_operator_state_without_private_keys() -> None:
    server = _server("NODE:READ", "BUNDLE:READ", "CAPABILITIES:READ")
    _initialize(server)

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "resources/read",
            "params": {"uri": "aidn://node/status"},
        }
    )

    assert response["result"]["contents"][0]["mimeType"] == "application/json"
    payload = json.loads(response["result"]["contents"][0]["text"])
    assert payload["node"]["node_id"] == "node-local"
    assert "private_key" not in json.dumps(payload)


def test_mcp_node_status_uses_current_endpoint_publication_read_model() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-test",
            bundle_id="bundle-a",
            bundle_hash="bundle-a-hash",
            display_name="Local model",
            model_class="llm.text",
            capabilities=["llm_text.generate"],
        )
    )
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet="wallet-test",
        node_id=service.node_id,
        wallet_private_key="test-private-key",
    )

    # Reproduce the stale persisted state that previously leaked through
    # aidn.node.status even though the endpoint publication was already live.
    service.sync_operator_onboarding_state(
        endpoint_items=[{"publication_status": "configured"}]
    )
    server = build_mcp_server(
        service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=publication_service,
        session=_session("NODE:READ"),
    )
    _initialize(server)

    result = _call(server, "aidn.node.status")

    assert result["isError"] is False
    payload = result["structuredContent"]
    assert payload["onboarding"]["completed"] is True
    assert payload["onboarding"]["current_step"] == "operate"
    assert payload["bundles"][0]["publish_status"] == "published"


def test_mcp_bundle_get_reconciles_live_provider_health() -> None:
    service = _service()
    service.start_bundle("bundle-a")
    server = build_mcp_server(
        service,
        session=_session("BUNDLE:READ"),
    )
    _initialize(server)

    result = _call(server, "aidn.bundle.get", {"bundle_id": "bundle-a"})

    assert result["isError"] is False
    runtime = result["structuredContent"]["runtime"]
    assert runtime["status"] == "running"
    assert runtime["health_status"] == "healthy"


def test_mcp_permission_denial_is_a_tool_error() -> None:
    server = _server("BUNDLE:READ")
    _initialize(server)

    result = _call(
        server,
        "aidn.bundle.activate",
        {
            "bundle_id": "bundle-a",
            "mode": "plan",
            "request_id": "request-1",
            "idempotency_key": "idem-1",
        },
    )

    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "MCP_PERMISSION_DENIED"


def test_mcp_endpoint_write_scope_exposes_create_and_publish_tools() -> None:
    server = _server("ENDPOINT:READ")
    _initialize(server)
    read_only_names = {
        item["name"]
        for item in server.handle_message(
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}}
        )["result"]["tools"]
    }
    assert "aidn.endpoint.list" in read_only_names
    assert "aidn.endpoint.create" not in read_only_names
    assert "aidn.endpoint.publish" not in read_only_names

    writable = _server("ENDPOINT:READ", "ENDPOINT:WRITE")
    _initialize(writable)
    writable_names = {
        item["name"]
        for item in writable.handle_message(
            {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}}
        )["result"]["tools"]
    }
    assert {"aidn.endpoint.create", "aidn.endpoint.publish"}.issubset(writable_names)


def test_mcp_agent_can_create_and_publish_endpoint_with_operator_approval() -> None:
    server = _endpoint_server(
        "ENDPOINT:READ",
        "ENDPOINT:WRITE",
        approval_policy={"endpoint_write": "OPERATOR_CONFIRMATION"},
    )
    _initialize(server)
    create_request = {
        "runtime_binding_id": "rtb-a",
        "bundle_id": "bundle-a",
        "display_name": "Agent endpoint",
        "publication": {
            "visibility": "public",
            "discoverable": True,
            "accepts_external_requests": True,
        },
        "local_agent_use": True,
        "mode": "plan",
        "request_id": "endpoint-create-request",
        "idempotency_key": "endpoint-create-idem",
    }
    create_plan = _call(server, "aidn.endpoint.create", create_request)["structuredContent"]
    assert create_plan["requires_approval"] is True
    denied_create = _call(
        server,
        "aidn.endpoint.create",
        {**create_request, "mode": "apply", "plan_hash": create_plan["plan_hash"]},
    )
    assert denied_create["structuredContent"]["error"]["code"] == "MCP_APPROVAL_REQUIRED"
    server.control.approve_plan(
        create_plan["plan_hash"],
        approval_reference="operator-endpoint-create",
        approver_identity="operator:test",
    )
    created = _call(
        server,
        "aidn.endpoint.create",
        {**create_request, "mode": "apply", "plan_hash": create_plan["plan_hash"]},
    )["structuredContent"]
    endpoint = created["endpoint"]
    assert created["status"] == "created"
    assert endpoint["local_agent_use"] is True

    publish_request = {
        "endpoint_id": endpoint["endpoint_id"],
        "mode": "plan",
        "request_id": "endpoint-publish-request",
        "idempotency_key": "endpoint-publish-idem",
    }
    publish_plan = _call(server, "aidn.endpoint.publish", publish_request)["structuredContent"]
    assert publish_plan["requires_approval"] is True
    denied_publish = _call(
        server,
        "aidn.endpoint.publish",
        {**publish_request, "mode": "apply", "plan_hash": publish_plan["plan_hash"]},
    )
    assert denied_publish["structuredContent"]["error"]["code"] == "MCP_APPROVAL_REQUIRED"
    server.control.approve_plan(
        publish_plan["plan_hash"],
        approval_reference="operator-endpoint-publish",
        approver_identity="operator:test",
    )
    published = _call(
        server,
        "aidn.endpoint.publish",
        {**publish_request, "mode": "apply", "plan_hash": publish_plan["plan_hash"]},
    )["structuredContent"]
    assert published["status"] == "FINALIZED"
    assert published["publication"]["endpoint_id"] == endpoint["endpoint_id"]


def test_mcp_unexpected_hypervisor_error_is_sanitized_and_audited() -> None:
    server = _server("SCHEDULER:READ")
    _initialize(server)
    server.control.service.operator_requests_policy = lambda: (_ for _ in ()).throw(
        RuntimeError("secret backend details")
    )

    result = _call(server, "aidn.policy.get")

    assert result["isError"] is True
    error = result["structuredContent"]["error"]
    assert error["code"] == "MCP_INTERNAL_ERROR"
    assert error["details"] == {"exception_type": "RuntimeError"}
    assert "secret backend details" not in json.dumps(result)
    audit = server.control.audit.query()["items"]
    assert audit[-1]["result"] == "MCP_INTERNAL_ERROR"


def test_mcp_bundle_activation_uses_plan_hash_and_idempotency() -> None:
    server = _server("BUNDLE:READ", "BUNDLE:ACTIVATE", "AUDIT:READ")
    _initialize(server)
    request = {
        "bundle_id": "bundle-a",
        "mode": "plan",
        "request_id": "request-activate",
        "idempotency_key": "idem-activate",
    }

    plan_result = _call(server, "aidn.bundle.activate", request)
    plan = plan_result["structuredContent"]
    assert plan["plan_hash"].startswith("sha256:")
    assert plan["changes"] == ["start runtime for Bundle bundle-a"]

    apply_result = _call(
        server,
        "aidn.bundle.activate",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )
    assert apply_result["structuredContent"]["status"] == "activated"
    assert apply_result["structuredContent"]["audit_event_id"] == "mcp-audit-2"

    duplicate = _call(
        server,
        "aidn.bundle.activate",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )
    assert duplicate["structuredContent"] == apply_result["structuredContent"]

    conflict = _call(
        server,
        "aidn.bundle.activate",
        {
            **request,
            "mode": "apply",
            "bundle_id": "missing-bundle",
            "plan_hash": plan["plan_hash"],
        },
    )
    assert conflict["isError"] is True
    assert conflict["structuredContent"]["error"]["code"] == "MCP_IDEMPOTENCY_CONFLICT"


def test_mcp_runtime_file_not_found_is_reported_as_stable_domain_error() -> None:
    server = _server("BUNDLE:READ", "BUNDLE:ACTIVATE", "AUDIT:READ")
    _initialize(server)
    request = {
        "bundle_id": "bundle-a",
        "mode": "plan",
        "request_id": "request-runtime-missing",
        "idempotency_key": "idem-runtime-missing",
    }
    plan = _call(server, "aidn.bundle.activate", request)["structuredContent"]

    def missing_runtime(_bundle_id: str):
        raise FileNotFoundError(2, "No such file or directory", "llama-server")

    server.control.service.start_bundle = missing_runtime
    result = _call(
        server,
        "aidn.bundle.activate",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )

    assert result["isError"] is True
    error = result["structuredContent"]["error"]
    assert error["code"] == "MCP_RUNTIME_ARTIFACT_NOT_FOUND"
    assert error["details"] == {"missing_path": "llama-server"}


def test_mcp_disruptive_mutation_requires_approved_plan() -> None:
    server = build_mcp_server(
        _service(runtime=True),
        session=_session(
            "BUNDLE:READ",
            "BUNDLE:RETIRE",
            approval_policy={"bundle_retire": "OPERATOR_CONFIRMATION"},
        ),
    )
    _initialize(server)
    request = {
        "bundle_id": "bundle-a",
        "mode": "plan",
        "request_id": "request-retire",
        "idempotency_key": "idem-retire",
    }
    plan = _call(server, "aidn.bundle.retire", request)["structuredContent"]
    result = _call(
        server,
        "aidn.bundle.retire",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "MCP_APPROVAL_REQUIRED"


def test_mcp_bundle_retire_is_idempotent_when_runtime_is_already_stopped() -> None:
    server = _server(
        "BUNDLE:READ",
        "BUNDLE:RETIRE",
        approval_policy={"bundle_retire": "AUTO"},
    )
    _initialize(server)
    request = {
        "bundle_id": "bundle-a",
        "mode": "plan",
        "request_id": "request-retire-stopped",
        "idempotency_key": "idem-retire-stopped",
    }
    plan = _call(server, "aidn.bundle.retire", request)["structuredContent"]

    result = _call(
        server,
        "aidn.bundle.retire",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )

    assert result["isError"] is False
    payload = result["structuredContent"]
    assert payload["status"] == "retired"
    assert payload["runtime"] == {"bundle_id": "bundle-a", "status": "already_stopped"}
    assert payload["bundle"]["enabled"] is False


def test_mcp_policy_and_capabilities_expose_the_same_effective_approval_policy() -> None:
    server = _server(
        "CAPABILITIES:READ",
        "SCHEDULER:READ",
        approval_policy={
            "bundle_activate": "AUTO",
            "bundle_retire": "OPERATOR_CONFIRMATION",
        },
    )
    _initialize(server)

    capabilities = _call(server, "aidn.capabilities.get")["structuredContent"]
    policy = _call(server, "aidn.policy.get")["structuredContent"]

    expected = {
        "bundle_activate": "AUTO",
        "bundle_retire": "OPERATOR_CONFIRMATION",
    }
    assert capabilities["effective_approval_policy"] == expected
    assert capabilities["control_session"]["approval_policy"] == expected
    assert policy["approval_policy"] == expected
    assert policy["effective_approval_policy"] == expected


def test_mcp_provider_attach_requires_plan_and_operator_approval() -> None:
    server = _server(
        "PROVIDER:READ",
        "PROVIDER:WRITE",
        approval_policy={"provider_attach": "OPERATOR_CONFIRMATION"},
    )
    _initialize(server)
    request = {
        "plugin_id": "fake-managed",
        "display_name": "Test Provider",
        "configuration": {"base_url": "http://127.0.0.1:9999"},
        "mode": "plan",
        "request_id": "request-provider-attach",
        "idempotency_key": "idem-provider-attach",
    }
    plan = _call(server, "aidn.provider.attach", request)["structuredContent"]
    assert plan["changes"] == [
        "attach one existing Provider endpoint",
        "bind it to Plugin fake-managed",
    ]

    denied = _call(
        server,
        "aidn.provider.attach",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )
    assert denied["structuredContent"]["error"]["code"] == "MCP_APPROVAL_REQUIRED"

    server.control.approve_plan(
        plan["plan_hash"],
        approval_reference="operator-provider-attach-test",
        approver_identity="operator:test",
    )
    applied = _call(
        server,
        "aidn.provider.attach",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )
    assert applied["structuredContent"]["status"] == "attached"
    assert applied["structuredContent"]["provider_instance"]["plugin_id"] == "fake-managed"


def test_mcp_stdio_emits_only_json_rpc_responses() -> None:
    server = _server("CAPABILITIES:READ")
    input_stream = io.StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-03-26"},
            }
        )
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"
        + json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "aidn.capabilities.get", "arguments": {}},
            }
        )
        + "\n"
    )
    output_stream = io.StringIO()

    server.run_stdio(stdin=input_stream, stdout=output_stream)

    responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert len(responses) == 2
    assert responses[0]["result"]["protocolVersion"] == "2025-03-26"
    assert responses[1]["result"]["structuredContent"]["spec_version"] == "MCP-0001/0.1"


def test_mcp_state_persists_audit_plans_and_idempotency_across_restart(tmp_path) -> None:
    store = McpPersistentStateStore(tmp_path / "mcp-control-state.json")
    server = _server(
        "BUNDLE:READ",
        "BUNDLE:ACTIVATE",
        "AUDIT:READ",
        mcp_state_store=store,
    )
    _initialize(server)
    request = {
        "bundle_id": "bundle-a",
        "mode": "plan",
        "request_id": "request-persisted",
        "idempotency_key": "idem-persisted",
    }
    plan = _call(server, "aidn.bundle.activate", request)["structuredContent"]
    applied = _call(
        server,
        "aidn.bundle.activate",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )["structuredContent"]
    head = server.control.audit.query()["head_hash"]

    restarted = _server(
        "BUNDLE:READ",
        "BUNDLE:ACTIVATE",
        "AUDIT:READ",
        mcp_state_store=store,
    )
    _initialize(restarted)
    duplicate = _call(
        restarted,
        "aidn.bundle.activate",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )

    assert duplicate["structuredContent"] == applied
    assert restarted.control.audit.query()["head_hash"] == head
    persisted = json.loads((tmp_path / "mcp-control-state.json").read_text(encoding="utf-8"))
    assert persisted["schema_version"] == 1
    assert persisted["sessions"]["acs-test"]["control_session_id"] == "acs-test"
    assert len(persisted["audit_events"]) == 2
    assert len(persisted["idempotency"]) == 1


def test_mcp_operator_approval_survives_restart_without_agent_self_approval(tmp_path) -> None:
    store = McpPersistentStateStore(tmp_path / "mcp-control-state.json")
    policy = {"bundle_activate": "OPERATOR_CONFIRMATION"}
    server = _server(
        "BUNDLE:ACTIVATE",
        approval_policy=policy,
        mcp_state_store=store,
    )
    _initialize(server)
    request = {
        "bundle_id": "bundle-a",
        "mode": "plan",
        "request_id": "request-approval",
        "idempotency_key": "idem-approval",
    }
    plan = _call(server, "aidn.bundle.activate", request)["structuredContent"]
    denied = _call(
        server,
        "aidn.bundle.activate",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )
    assert denied["structuredContent"]["error"]["code"] == "MCP_APPROVAL_REQUIRED"

    approval = server.control.approve_plan(
        plan["plan_hash"],
        approval_reference="operator-local-confirmation-1",
        approver_identity="operator:test",
    )
    assert approval["approved"] is True

    restarted = _server(
        "BUNDLE:ACTIVATE",
        approval_policy=policy,
        mcp_state_store=store,
    )
    _initialize(restarted)
    applied = _call(
        restarted,
        "aidn.bundle.activate",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )

    assert applied["structuredContent"]["status"] == "activated"
    assert restarted.control.audit.query()["items"][-1]["event_type"] == "MCP_TOOL_APPLIED"


def test_remote_gateway_renews_expired_control_session_after_bearer_authentication() -> None:
    session = _session("NODE:READ")
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    server = build_mcp_server(
        _service(),
        session=session,
        control_session_auto_renew=True,
        control_session_ttl_seconds=60,
    )
    gateway = McpRemoteGateway(server.control, agent_token="agent-secret")
    app = FastAPI()
    app.include_router(build_mcp_remote_router(gateway))
    client = TestClient(app)
    headers = {"Authorization": "Bearer agent-secret"}

    initialize = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        },
    )
    assert initialize.status_code == 200
    transport_session_id = initialize.headers["mcp-session-id"]
    client.post(
        "/mcp",
        headers={**headers, "Mcp-Session-Id": transport_session_id},
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )

    health = client.post(
        "/mcp",
        headers={**headers, "Mcp-Session-Id": transport_session_id},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "aidn.node.health", "arguments": {}},
        },
    )
    assert health.status_code == 200
    assert health.json()["result"]["isError"] is False
    assert server.control.session.expires_at > datetime.now(UTC)
    assert server.control.audit.query()["items"][-1]["event_type"] == "MCP_CONTROL_SESSION_RENEWED"


def test_remote_gateway_stateless_control_session_uses_bearer_as_revocation_boundary() -> None:
    session = _session("NODE:READ")
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    server = build_mcp_server(
        _service(),
        session=session,
        control_session_stateless=True,
    )
    gateway = McpRemoteGateway(server.control, agent_token="agent-secret")
    app = FastAPI()
    app.include_router(build_mcp_remote_router(gateway))
    client = TestClient(app)
    headers = {"Authorization": "Bearer agent-secret"}

    initialize = client.post(
        "/mcp",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        },
    )
    assert initialize.status_code == 200
    transport_session_id = initialize.headers["mcp-session-id"]
    initialized = client.post(
        "/mcp",
        headers={**headers, "Mcp-Session-Id": transport_session_id},
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert initialized.status_code == 202

    health = client.post(
        "/mcp",
        headers={**headers, "Mcp-Session-Id": transport_session_id},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "aidn.node.health", "arguments": {}},
        },
    )
    assert health.status_code == 200
    assert health.json()["result"]["isError"] is False
    assert server.control.session.expires_at is None


def test_mcp_corrupt_persisted_audit_chain_fails_closed(tmp_path) -> None:
    state_path = tmp_path / "mcp-control-state.json"
    store = McpPersistentStateStore(state_path)
    server = _server(
        "BUNDLE:ACTIVATE",
        mcp_state_store=store,
    )
    _initialize(server)
    _call(
        server,
        "aidn.bundle.activate",
        {
            "bundle_id": "bundle-a",
            "mode": "plan",
            "request_id": "request-corrupt",
            "idempotency_key": "idem-corrupt",
        },
    )
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    persisted["audit_events"][0]["event_hash"] = "sha256:tampered"
    state_path.write_text(json.dumps(persisted), encoding="utf-8")

    with pytest.raises(McpPersistenceError):
        _server("BUNDLE:ACTIVATE", mcp_state_store=store)


def test_mcp_persistence_migrates_new_restrictive_approval_defaults(tmp_path) -> None:
    state_path = tmp_path / "mcp-control-state.json"
    store = McpPersistentStateStore(state_path)
    _server(
        "PROVIDER:READ",
        approval_policy={"bundle_activate": "AUTO", "bundle_retire": "OPERATOR_CONFIRMATION"},
        mcp_state_store=store,
    )

    migrated = _server(
        "PROVIDER:READ",
        approval_policy={
            "bundle_activate": "AUTO",
            "bundle_retire": "OPERATOR_CONFIRMATION",
            "provider_attach": "OPERATOR_CONFIRMATION",
        },
        mcp_state_store=store,
    )

    assert migrated.control.session.approval_policy["provider_attach"] == "OPERATOR_CONFIRMATION"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["sessions"]["acs-test"]["approval_policy"]["provider_attach"] == (
        "OPERATOR_CONFIRMATION"
    )
