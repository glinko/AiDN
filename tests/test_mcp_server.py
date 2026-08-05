from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile
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
