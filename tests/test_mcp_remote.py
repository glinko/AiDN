from __future__ import annotations

import os
import stat
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile
from aidn_hypervisor.mcp import (
    ControlSession,
    McpPersistentStateStore,
    McpRemoteGateway,
    McpRemoteTlsConfig,
    McpRemoteTlsMaterializer,
    McpRemoteTlsRotationWatcher,
    McpRemoteTlsSecretConfig,
    build_mcp_remote_router,
    build_mcp_server,
)
from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.secrets import FileSecretManager
from aidn_hypervisor.service import HypervisorService

AGENT_TOKEN = "agent-transport-secret"
OPERATOR_TOKEN = "operator-admin-secret"


def _service() -> HypervisorService:
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    return HypervisorService(
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
        runtimes=ProviderProcessManager(),
    )


def _session(*scopes: str, approval_policy: dict[str, str] | None = None) -> ControlSession:
    return ControlSession(
        control_session_id="acs-remote-test",
        agent_identity="agent:remote-test",
        operator_identity="operator:remote-test",
        scopes=frozenset(scopes),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        approval_policy=approval_policy or {"bundle_activate": "AUTO"},
    )


def _client(
    tmp_path,
    *,
    scopes: tuple[str, ...],
    approval_policy: dict[str, str] | None = None,
    operator_token: str | None = OPERATOR_TOKEN,
    require_tls: bool = False,
) -> tuple[TestClient, McpRemoteGateway]:
    store = McpPersistentStateStore(tmp_path / "mcp-control-state.json")
    server = build_mcp_server(
        _service(),
        session=_session(*scopes, approval_policy=approval_policy),
        mcp_state_store=store,
    )
    gateway = McpRemoteGateway(
        server.control,
        agent_token=AGENT_TOKEN,
        operator_token=operator_token,
        require_tls=require_tls,
    )
    app = FastAPI()
    app.include_router(build_mcp_remote_router(gateway))
    return TestClient(app), gateway


def _client_with_credentials(tmp_path, credentials: McpCredentialStore) -> tuple[TestClient, McpRemoteGateway]:
    store = McpPersistentStateStore(tmp_path / "mcp-control-state.json")
    server = build_mcp_server(
        _service(),
        session=_session("CAPABILITIES:READ"),
        mcp_state_store=store,
    )
    gateway = McpRemoteGateway(
        server.control,
        agent_token=None,
        credential_resolver=credentials,
    )
    app = FastAPI()
    app.include_router(build_mcp_remote_router(gateway))
    return TestClient(app), gateway


def _headers(token: str = AGENT_TOKEN, session_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if session_id is not None:
        headers["Mcp-Session-Id"] = session_id
    return headers


def _initialize(
    client: TestClient,
    token: str = AGENT_TOKEN,
    protocol_version: str = "2025-06-18",
) -> str:
    response = client.post(
        "/mcp",
        headers=_headers(token),
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "remote-test", "version": "0.1"},
            },
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["protocolVersion"] == protocol_version
    session_id = response.headers["Mcp-Session-Id"]
    initialized = client.post(
        "/mcp",
        headers=_headers(token, session_id=session_id),
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert initialized.status_code == 202
    return session_id


def test_remote_gateway_accepts_hermes_latest_handshake_version(tmp_path) -> None:
    client, _gateway = _client(tmp_path, scopes=("CAPABILITIES:READ",))
    session_id = _initialize(client, protocol_version="2025-11-25")

    response = client.post(
        "/mcp",
        headers=_headers(session_id=session_id),
        json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
    )
    assert response.status_code == 200
    assert response.json()["result"] == {}


def test_revocation_rejects_credential_and_closes_transport_sessions(tmp_path) -> None:
    credentials = McpCredentialStore(
        secret_manager=FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    )
    issued = credentials.create_credential(label="agent", scopes=("CAPABILITIES:READ",))
    client, gateway = _client_with_credentials(tmp_path, credentials)
    session_id = _initialize(client, issued.token or "")

    gateway.invalidate_credential_sessions(issued.credential_id)

    closed = client.post(
        "/mcp",
        headers=_headers(issued.token or "", session_id=session_id),
        json={"jsonrpc": "2.0", "id": 3, "method": "ping"},
    )
    assert closed.status_code == 404
    assert credentials.revoke_credential(issued.credential_id) is True
    assert client.post("/mcp", headers=_headers(issued.token or ""), json={}).status_code == 401


def test_credential_scopes_filter_tools_and_take_effect_after_session_reconnect(tmp_path) -> None:
    credentials = McpCredentialStore(
        secret_manager=FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    )
    issued = credentials.create_credential(label="read-only agent", scopes=("NODE:READ",))
    client, gateway = _client_with_credentials(tmp_path, credentials)
    session_id = _initialize(client, issued.token or "")

    listed = client.post(
        "/mcp",
        headers=_headers(issued.token or "", session_id=session_id),
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    names = {tool["name"] for tool in listed.json()["result"]["tools"]}
    assert names == {"aidn.capabilities.get", "aidn.node.status", "aidn.node.health"}
    assert "aidn.bundle.activate" not in names
    capabilities_response = client.post(
        "/mcp",
        headers=_headers(issued.token or "", session_id=session_id),
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "aidn.capabilities.get", "arguments": {}},
        },
    )
    assert capabilities_response.status_code == 200
    capabilities = capabilities_response.json()["result"]["structuredContent"]
    assert "aidn.bundle.activate" not in capabilities["implemented_tools"]

    credentials.update_scopes(issued.credential_id, scopes=("NODE:READ", "BUNDLE:ACTIVATE"))
    gateway.invalidate_credential_sessions(issued.credential_id)
    closed = client.post(
        "/mcp",
        headers=_headers(issued.token or "", session_id=session_id),
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
    )
    assert closed.status_code == 404

    refreshed_session = _initialize(client, issued.token or "")
    refreshed = client.post(
        "/mcp",
        headers=_headers(issued.token or "", session_id=refreshed_session),
        json={"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}},
    )
    refreshed_names = {tool["name"] for tool in refreshed.json()["result"]["tools"]}
    assert "aidn.bundle.activate" in refreshed_names
    policy = _tool_call(
        client, refreshed_session, "aidn.capabilities.get", {}, token=issued.token or ""
    )["structuredContent"]["control_session"]["approval_policy"]
    assert policy["bundle_activate"] == "OPERATOR_CONFIRMATION"

    credentials.update_scopes(
        issued.credential_id,
        scopes=("NODE:READ", "BUNDLE:ACTIVATE"),
        auto_approved_scopes=("BUNDLE:ACTIVATE",),
    )
    gateway.invalidate_credential_sessions(issued.credential_id)
    automatic_session = _initialize(client, issued.token or "")
    policy = _tool_call(
        client, automatic_session, "aidn.capabilities.get", {}, token=issued.token or ""
    )["structuredContent"]["control_session"]["approval_policy"]
    assert policy["bundle_activate"] == "AUTO"


def test_credential_effective_policy_is_consistent_across_mcp_reads(tmp_path) -> None:
    credentials = McpCredentialStore(
        secret_manager=FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    )
    issued = credentials.create_credential(
        label="retire agent",
        scopes=("CAPABILITIES:READ", "SCHEDULER:READ", "BUNDLE:RETIRE"),
        auto_approved_scopes=("BUNDLE:RETIRE",),
    )
    client, _gateway = _client_with_credentials(tmp_path, credentials)
    session_id = _initialize(client, issued.token or "")

    capabilities = _tool_call(
        client, session_id, "aidn.capabilities.get", {}, token=issued.token or ""
    )["structuredContent"]
    policy = _tool_call(
        client, session_id, "aidn.policy.get", {}, token=issued.token or ""
    )["structuredContent"]

    assert capabilities["effective_approval_policy"]["bundle_retire"] == "AUTO"
    assert capabilities["control_session"]["approval_policy"]["bundle_retire"] == "AUTO"
    assert policy["approval_policy"]["bundle_retire"] == "AUTO"
    assert policy["effective_approval_policy"]["bundle_retire"] == "AUTO"


def test_credential_restricted_retire_reports_approval_required_without_internal_error(tmp_path) -> None:
    credentials = McpCredentialStore(
        secret_manager=FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    )
    issued = credentials.create_credential(
        label="restricted retire agent",
        scopes=("CAPABILITIES:READ", "BUNDLE:READ", "BUNDLE:RETIRE"),
    )
    client, _gateway = _client_with_credentials(tmp_path, credentials)
    session_id = _initialize(client, issued.token or "")

    request = {
        "bundle_id": "bundle-a",
        "mode": "plan",
        "request_id": "remote-restricted-retire",
        "idempotency_key": "remote-restricted-retire-idem",
    }
    plan = _tool_call(client, session_id, "aidn.bundle.retire", request, token=issued.token or "")
    plan_payload = plan["structuredContent"]
    assert plan_payload["requires_approval"] is True

    denied = _tool_call(
        client,
        session_id,
        "aidn.bundle.retire",
        {**request, "mode": "apply", "plan_hash": plan_payload["plan_hash"]},
        token=issued.token or "",
    )
    error = denied["structuredContent"]["error"]
    assert denied["isError"] is True
    assert error["code"] == "MCP_APPROVAL_REQUIRED"
    assert error["details"]["approval_mode"] == "OPERATOR_CONFIRMATION"


def _tool_call(
    client: TestClient,
    session_id: str,
    name: str,
    arguments: dict,
    *,
    token: str = AGENT_TOKEN,
) -> dict:
    response = client.post(
        "/mcp",
        headers=_headers(token, session_id=session_id),
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200
    return response.json()["result"]


def test_remote_gateway_requires_bearer_token_and_binds_transport_session(tmp_path) -> None:
    client, _gateway = _client(tmp_path, scopes=("CAPABILITIES:READ",))

    assert client.post("/mcp", json={}).status_code == 401
    assert client.post("/mcp", headers=_headers("wrong"), json={}).status_code == 401

    session_id = _initialize(client)
    listed = client.post(
        "/mcp",
        headers=_headers(session_id=session_id),
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
    )
    assert listed.status_code == 200
    assert listed.json()["result"]["tools"][0]["name"] == "aidn.capabilities.get"

    assert client.post(
        "/mcp",
        headers=_headers(),
        json={"jsonrpc": "2.0", "id": 4, "method": "ping"},
    ).status_code == 400
    assert client.post(
        "/mcp",
        headers=_headers(session_id="mcp-unknown"),
        json={"jsonrpc": "2.0", "id": 5, "method": "ping"},
    ).status_code == 404

    closed = client.delete("/mcp", headers=_headers(session_id=session_id))
    assert closed.status_code == 204
    assert client.post(
        "/mcp",
        headers=_headers(session_id=session_id),
        json={"jsonrpc": "2.0", "id": 6, "method": "ping"},
    ).status_code == 404


def test_remote_operator_approval_is_separate_from_agent_token(tmp_path) -> None:
    client, _gateway = _client(
        tmp_path,
        scopes=("BUNDLE:ACTIVATE",),
        approval_policy={"bundle_activate": "OPERATOR_CONFIRMATION"},
    )
    session_id = _initialize(client)
    request = {
        "bundle_id": "bundle-a",
        "mode": "plan",
        "request_id": "remote-approval-request",
        "idempotency_key": "remote-approval-idem",
    }
    plan = _tool_call(client, session_id, "aidn.bundle.activate", request)["structuredContent"]
    denied = _tool_call(
        client,
        session_id,
        "aidn.bundle.activate",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )
    assert denied["structuredContent"]["error"]["code"] == "MCP_APPROVAL_REQUIRED"

    wrong_token = client.post(
        "/mcp/operator/approve",
        headers=_headers(AGENT_TOKEN),
        json={"plan_hash": plan["plan_hash"], "approval_reference": "operator-confirmed"},
    )
    assert wrong_token.status_code == 401
    approved = client.post(
        "/mcp/operator/approve",
        headers=_headers(OPERATOR_TOKEN),
        json={"plan_hash": plan["plan_hash"], "approval_reference": "operator-confirmed"},
    )
    assert approved.status_code == 200
    assert approved.json()["result"]["approved"] is True

    applied = _tool_call(
        client,
        session_id,
        "aidn.bundle.activate",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )
    assert applied["structuredContent"]["status"] == "activated"


def test_remote_emergency_stop_freezes_agent_mutations_and_can_be_cleared(tmp_path) -> None:
    client, gateway = _client(tmp_path, scopes=("CAPABILITIES:READ", "BUNDLE:ACTIVATE"))
    session_id = _initialize(client)
    request = {
        "bundle_id": "bundle-a",
        "mode": "plan",
        "request_id": "remote-stop-request",
        "idempotency_key": "remote-stop-idem",
    }
    plan = _tool_call(client, session_id, "aidn.bundle.activate", request)["structuredContent"]

    activated = client.post(
        "/mcp/operator/emergency-stop",
        headers=_headers(OPERATOR_TOKEN),
        json={"reason": "operator test stop", "reference": "incident-remote-1"},
    )
    assert activated.status_code == 200
    assert activated.json()["result"]["active"] is True
    assert gateway.control.emergency_stop_active is True

    frozen = _tool_call(
        client,
        session_id,
        "aidn.bundle.activate",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )
    assert frozen["structuredContent"]["error"]["code"] == "MCP_PERMISSION_DENIED"

    cleared = client.post(
        "/mcp/operator/emergency-stop/clear",
        headers=_headers(OPERATOR_TOKEN),
        json={"reason": "operator test clear", "reference": "incident-remote-1-resolved"},
    )
    assert cleared.status_code == 200
    assert cleared.json()["result"]["active"] is False
    applied = _tool_call(
        client,
        session_id,
        "aidn.bundle.activate",
        {**request, "mode": "apply", "plan_hash": plan["plan_hash"]},
    )
    assert applied["structuredContent"]["status"] == "activated"


def test_remote_gateway_rejects_browser_origin_and_persists_emergency_stop(tmp_path) -> None:
    client, gateway = _client(tmp_path, scopes=("CAPABILITIES:READ",))
    browser = client.post(
        "/mcp",
        headers={**_headers(), "Origin": "https://untrusted.example"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert browser.status_code == 403

    stopped = client.post(
        "/mcp/operator/emergency-stop",
        headers=_headers(OPERATOR_TOKEN),
        json={"reason": "persisted test stop", "reference": "incident-persisted"},
    )
    assert stopped.status_code == 200
    assert gateway.control.emergency_stop_status()["reference"] == "incident-persisted"

    store = McpPersistentStateStore(tmp_path / "mcp-control-state.json")
    restarted = build_mcp_server(
        _service(),
        session=_session("CAPABILITIES:READ"),
        mcp_state_store=store,
    )
    assert restarted.control.emergency_stop_active is True
    assert restarted.control.emergency_stop_status()["reason"] == "persisted test stop"


def test_remote_gateway_requires_distinct_agent_and_operator_tokens(tmp_path) -> None:
    with pytest.raises(ValueError, match="must be different"):
        _client(tmp_path, scopes=("CAPABILITIES:READ",), operator_token=AGENT_TOKEN)


def test_remote_gateway_requires_https_before_accepting_bearer_tokens(tmp_path) -> None:
    client, _gateway = _client(
        tmp_path,
        scopes=("CAPABILITIES:READ",),
        require_tls=True,
    )

    response = client.post(
        "/mcp",
        headers=_headers(),
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 426
    assert response.json()["error"]["code"] == "MCP_REMOTE_TLS_REQUIRED"


def _write_tls_material(tmp_path: Path) -> McpRemoteTlsConfig:
    ca_key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AiDN test CA")])
    now = datetime.now(UTC)
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    server_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(server_name)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    ca_file = tmp_path / "ca.pem"
    certificate_file = tmp_path / "server.pem"
    private_key_file = tmp_path / "server-key.pem"
    ca_file.write_bytes(ca_certificate.public_bytes(serialization.Encoding.PEM))
    certificate_file.write_bytes(server_certificate.public_bytes(serialization.Encoding.PEM))
    private_key_file.write_bytes(
        server_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    private_key_file.chmod(0o600)
    return McpRemoteTlsConfig(
        certificate_file=certificate_file,
        private_key_file=private_key_file,
        certificate_authority_file=ca_file,
    )


def test_production_tls_config_requires_client_certificate_and_tls12(tmp_path) -> None:
    import uvicorn

    tls_config = _write_tls_material(tmp_path)
    options = tls_config.uvicorn_options()
    context = options["ssl_context_factory"](
        type(
            "UvicornConfig",
            (),
            {
                "ssl_certfile": str(tls_config.certificate_file),
                "ssl_keyfile": str(tls_config.private_key_file),
                "ssl_ca_certs": str(tls_config.certificate_authority_file),
            },
        )(),
        lambda: None,
    )
    assert options["ssl_cert_reqs"] == 2
    assert context.minimum_version.name == "TLSv1_2"
    assert context.verify_mode.name == "CERT_REQUIRED"

    uvicorn_config = uvicorn.Config(
        lambda: FastAPI(),
        factory=True,
        **options,
    )
    uvicorn_config.load()
    assert uvicorn_config.loaded_app is not None


def test_secret_manager_tls_materializer_rotates_only_after_valid_bundle(tmp_path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first = _write_tls_material(first_dir)
    second = _write_tls_material(second_dir)
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    secret_config = McpRemoteTlsSecretConfig(
        certificate_handle="secret://mcp/tls/certificate",
        private_key_handle="secret://mcp/tls/private-key",
        certificate_authority_handle="secret://mcp/tls/ca",
    )
    manager.put_many(
        {
            secret_config.certificate_handle: first.certificate_file.read_bytes(),
            secret_config.private_key_handle: first.private_key_file.read_bytes(),
            secret_config.certificate_authority_handle: first.certificate_authority_file.read_bytes(),
        }
    )
    materializer = McpRemoteTlsMaterializer(
        secret_manager=manager,
        secret_config=secret_config,
    )
    current = materializer.materialize()
    current_private_key_mode = (
        stat.S_IMODE(current.private_key_file.stat().st_mode) if os.name != "nt" else None
    )
    rotated = threading.Event()

    def accept_rotation() -> bool:
        materializer.materialize()
        rotated.set()
        return True

    watcher = McpRemoteTlsRotationWatcher(
        secret_manager=manager,
        secret_config=secret_config,
        on_rotation=accept_rotation,
        interval_seconds=0.01,
    )
    watcher.start()
    try:
        manager.put_many(
            {
                secret_config.certificate_handle: second.certificate_file.read_bytes(),
                secret_config.private_key_handle: second.private_key_file.read_bytes(),
                secret_config.certificate_authority_handle: second.certificate_authority_file.read_bytes(),
            }
        )
        assert rotated.wait(2)
    finally:
        watcher.stop()
        materializer.close()

    assert watcher.rotation_detected is True
    assert current.certificate_file != second.certificate_file
    assert not current.certificate_file.exists()
    if os.name != "nt":
        assert current_private_key_mode == 0o600
