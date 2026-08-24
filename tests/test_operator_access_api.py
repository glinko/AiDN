from __future__ import annotations

import base64
import os
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidn_hypervisor.config import write_operator_config
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.dashboard_network_access import DashboardNetworkAccessService
from aidn_hypervisor.endpoints.models import EndpointManifest
from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.mcp.enrollment import McpEnrollmentService
from aidn_hypervisor.operator_access import DashboardAccessService
from aidn_hypervisor.operator_access_api import build_operator_access_router
from aidn_hypervisor.operator_config_service import OperatorConfigService
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.secrets import FileSecretManager
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.wallet_identity import wallet_identity_registration_payload
from aidn_hypervisor.wallet_read_models import build_operator_wallet_payload

_BROWSER_HEADERS = {"X-AiDN-Browser-Key": "browser-key-for-api-tests-000000000000000000000000000000000000000"}


class _OperationResources:
    def __init__(self) -> None:
        self.capacity = None
        self.probe = None

    def replace_capacity(self, capacity, *, probe) -> None:
        self.capacity = capacity
        self.probe = probe

    def summary(self) -> dict:
        return {"probe": self.probe}


class _OperationService:
    def __init__(self) -> None:
        self.resources = _OperationResources()
        self.calls: list[tuple] = []

    def set_bundle_enabled(self, bundle_id: str, enabled: bool) -> dict:
        self.calls.append(("bundle", bundle_id, enabled))
        return {"bundle_id": bundle_id, "enabled": enabled}

    def retry_bundle(self, bundle_id: str) -> dict:
        self.calls.append(("retry", bundle_id))
        return {"bundle_id": bundle_id, "runtime_status": "running"}

    def reset_bundle_cooldown(self, bundle_id: str) -> dict:
        self.calls.append(("reset", bundle_id))
        return {"bundle_id": bundle_id, "cooldown": "reset"}

    def attach_provider_instance(self, **payload) -> dict:
        self.calls.append(("attach", payload))
        return {"provider_instance_id": "pi-test", **payload}

    def detach_provider_instance(self, provider_instance_id: str) -> dict:
        self.calls.append(("detach", provider_instance_id))
        return {"provider_instance_id": provider_instance_id, "status": "DETACHED"}

    def build_provider_installation_plan(self, *, plugin_id: str, configuration: dict) -> dict:
        self.calls.append(("provider-plan", plugin_id, configuration))
        return {
            "plugin_id": plugin_id,
            "required_permissions": [{"permission_id": "host.package_manager"}],
        }

    def approve_provider_installation_plan(self, **payload) -> dict:
        self.calls.append(("provider-approval", payload))
        return {"approval_id": "pia-test", **payload}

    def apply_provider_installation_approval(self, approval_id: str) -> dict:
        self.calls.append(("provider-apply", approval_id))
        return {
            "approval_id": approval_id,
            "job_id": "pij-test",
            "status": "SUCCEEDED",
            "provider_instance_id": "pi-test",
        }

    def install_provider_runtime(self, **payload) -> dict:
        self.calls.append(("provider-runtime-install", payload))
        return {"plugin_id": payload["plugin_id"], "status": "SUCCEEDED", "provider_instance_id": "pi-test"}

    def change_provider_runtime(self, **payload) -> dict:
        self.calls.append(("provider-runtime-change", payload))
        return {"plugin_id": payload["plugin_id"], "status": "SUCCEEDED", "provider_instance_id": "pi-test"}

    def remove_provider_runtime(self, **payload) -> dict:
        self.calls.append(("provider-runtime-remove", payload))
        return {"plugin_id": payload["plugin_id"], "status": "REMOVED"}

    def probe_provider_instance(self, provider_instance_id: str) -> dict:
        self.calls.append(("probe", provider_instance_id))
        return {"provider_instance_id": provider_instance_id, "healthy": True}

    def discover_provider_models(self, provider_instance_id: str) -> list[dict]:
        self.calls.append(("discover", provider_instance_id))
        return [{"model_deployment_id": "md-test"}]

    def request_model_install(self, **payload) -> dict:
        self.calls.append(("install", payload))
        return {"install_id": "install-test", "status": "queued", **payload}

    def process_model_installs(self) -> list[dict]:
        self.calls.append(("process-installs",))
        return [{"install_id": "install-test", "status": "completed"}]

    def register_bundle_from_install(self, **payload) -> dict:
        self.calls.append(("register-bundle", payload))
        return {"bundle_id": payload["bundle_id"], "revision": 1}

    def create_model_artifact_set(self, **payload) -> dict:
        self.calls.append(("artifact-set", payload))
        return {"artifact_set_id": "set-test", **payload}

    def bind_model_artifact_set(self, **payload) -> dict:
        self.calls.append(("bind-artifact-set", payload))
        return {"model_deployment_id": payload["model_deployment_id"], **payload}

    def materialize_model_artifact_set(self, **payload) -> dict:
        self.calls.append(("materialize-artifact-set", payload))
        return {"status": "READY", **payload}

    def create_runtime_binding(self, **payload) -> dict:
        self.calls.append(("runtime-binding", payload))
        return {"runtime_binding_id": "rtb-test", **payload}

    def create_bundle_revision(self, **payload) -> dict:
        self.calls.append(("bundle-revision", payload))
        return {"bundle_id": payload["bundle_id"], "revision": 2}

    def configure_owner_wallet(self, *, mode: str, label: str | None = None, private_key: str | None = None) -> dict:
        self.calls.append(("wallet", mode, label, private_key))
        return {
            "wallet": {"configured": True, "wallet_id": "wallet-test", "label": label},
            "private_key": "ed25519:new-key" if mode == "create" else None,
        }


def test_credential_mutation_requires_pairing_and_reveals_only_new_value(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    enrollment = McpEnrollmentService(
        secret_manager=manager,
        credential_store=credentials,
    )
    app = FastAPI()
    app.include_router(
        build_operator_access_router(
            access_service=access,
            credential_store=credentials,
            allow_insecure_lan=True,
            enrollment_service=enrollment,
        )
    )
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)

    assert client.post(
        "/operators/dashboard/access/credentials",
        json={"label": "agent", "scopes": ["NODE:READ"]},
    ).status_code == 401

    pairing = access.create_pairing(ttl_seconds=600)
    pairing_response = client.post("/operators/dashboard/access/pair", json={"code": pairing.code})
    assert pairing_response.status_code == 200
    assert pairing_response.json()["status"] == "paired"
    assert pairing_response.headers["cache-control"] == "no-store"
    assert "aidn_dashboard_access=" in pairing_response.headers["set-cookie"]

    created = client.post(
        "/operators/dashboard/access/credentials",
        json={"label": "agent", "scopes": ["NODE:READ"]},
    )
    assert created.status_code == 201
    assert created.json()["token"]

    status = client.get("/operators/dashboard/access/status")
    assert status.status_code == 200
    assert "token" not in status.text

    rotated = client.post(f"/operators/dashboard/access/credentials/{created.json()['credential_id']}/rotate")
    assert rotated.status_code == 201
    assert rotated.json()["token"]

    revoked = client.delete(f"/operators/dashboard/access/credentials/{rotated.json()['credential_id']}")
    assert revoked.status_code == 204
    assert client.post("/operators/dashboard/access/logout").status_code == 204


def test_inference_token_requires_local_agent_opt_in(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    endpoint = EndpointManifest(
        endpoint_id="ep-private-agent",
        owner_wallet="wallet-test",
        created_at="2026-08-16T00:00:00Z",
        bundle_id="bundle-qwen",
        bundle_hash="sha256:bundle",
        runtime_binding_id="rtb-qwen",
        configuration_hash="sha256:config",
        display_name="Private Qwen",
        model_class="llm_text",
        local_agent_use=False,
    )

    class EndpointStub:
        def get_endpoint(self, endpoint_id: str):
            if endpoint_id != endpoint.endpoint_id:
                raise KeyError(endpoint_id)
            return SimpleNamespace(endpoint=endpoint)

    class HypervisorStub:
        def owner_wallet_state(self):
            return {"configured": True, "wallet_id": endpoint.owner_wallet}

    app = FastAPI()
    app.include_router(
        build_operator_access_router(
            access_service=access,
            credential_store=credentials,
            allow_insecure_lan=True,
            hypervisor_service=HypervisorStub(),
            endpoint_service=EndpointStub(),
        )
    )
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)
    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200

    rejected = client.post(
        "/operators/dashboard/access/inference-credentials",
        json={"label": "OpenClaw", "endpoint_id": endpoint.endpoint_id},
    )

    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "INFERENCE_CREDENTIAL_REJECTED"
    assert "Local Agent Use" in rejected.json()["error"]["message"]


def test_inference_token_accepts_openai_chat_runtime_binding(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    endpoint = EndpointManifest(
        endpoint_id="ep-private-chat-agent",
        owner_wallet="wallet-test",
        created_at="2026-08-16T00:00:00Z",
        bundle_id="bundle-qwen",
        bundle_hash="sha256:bundle",
        runtime_binding_id="rtb-qwen",
        configuration_hash="sha256:config",
        display_name="Private Qwen chat",
        model_class="llm.chat",
        local_agent_use=True,
    )

    class EndpointStub:
        def get_endpoint(self, endpoint_id: str):
            if endpoint_id != endpoint.endpoint_id:
                raise KeyError(endpoint_id)
            return SimpleNamespace(endpoint=endpoint)

    class HypervisorStub:
        def owner_wallet_state(self):
            return {"configured": True, "wallet_id": endpoint.owner_wallet}

    app = FastAPI()
    app.include_router(
        build_operator_access_router(
            access_service=access,
            credential_store=credentials,
            allow_insecure_lan=True,
            hypervisor_service=HypervisorStub(),
            endpoint_service=EndpointStub(),
        )
    )
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)
    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200

    issued = client.post(
        "/operators/dashboard/access/inference-credentials",
        json={"label": "Hermes", "endpoint_id": endpoint.endpoint_id},
    )

    assert issued.status_code == 201
    assert issued.json()["token"]


def test_disabling_local_agent_use_revokes_endpoint_tokens_without_rotating_config(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    endpoint = EndpointManifest(
        endpoint_id="ep-private-agent",
        owner_wallet="wallet-test",
        created_at="2026-08-16T00:00:00Z",
        bundle_id="bundle-qwen",
        bundle_hash="sha256:bundle",
        runtime_binding_id="rtb-qwen",
        configuration_hash="sha256:config",
        display_name="Private Qwen",
        model_class="llm_text",
        local_agent_use=True,
    )

    class EndpointStub:
        def get_endpoint(self, endpoint_id: str):
            if endpoint_id != endpoint.endpoint_id:
                raise KeyError(endpoint_id)
            return SimpleNamespace(endpoint=endpoint)

        def set_local_agent_use(self, endpoint_id: str, *, enabled: bool):
            nonlocal endpoint
            if endpoint_id != endpoint.endpoint_id:
                raise KeyError(endpoint_id)
            endpoint = endpoint.model_copy(update={"local_agent_use": enabled})
            return SimpleNamespace(endpoint=endpoint)

    class SessionStub:
        def __init__(self) -> None:
            self.closed: list[str] = []

        def close_session(self, session_id: str) -> None:
            self.closed.append(session_id)

    issued = credentials.create_inference_credential(
        label="OpenClaw",
        endpoint_id=endpoint.endpoint_id,
        owner_wallet=endpoint.owner_wallet,
    )
    credentials.bind_inference_session(issued.credential_id, "session-agent")
    sessions = SessionStub()
    app = FastAPI()
    app.include_router(
        build_operator_access_router(
            access_service=access,
            credential_store=credentials,
            allow_insecure_lan=True,
            endpoint_service=EndpointStub(),
            session_service=sessions,
        )
    )
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)
    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200

    response = client.post(
        f"/operators/dashboard/access/operations/endpoints/{endpoint.endpoint_id}/local-agent-use",
        json={"enabled": False},
    )

    assert response.status_code == 200
    assert response.json()["endpoint"]["configuration_hash"] == "sha256:config"
    assert response.json()["revoked_inference_credential_ids"] == [issued.credential_id]
    assert sessions.closed == ["session-agent"]
    assert credentials.list_inference_credentials()[0].state == "revoked"


def test_dashboard_network_access_is_pair_bound_and_limited_to_loopback_or_lan(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    network = DashboardNetworkAccessService(
        path=tmp_path / "hypervisor-bind-host",
        current_host="127.0.0.1",
        restart_on_change=False,
    )
    app = FastAPI()
    app.include_router(build_operator_access_router(
        access_service=access,
        credential_store=credentials,
        allow_insecure_lan=True,
        network_access_service=network,
    ))
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)

    assert client.post("/operators/dashboard/access/operations/network", json={"mode": "lan"}).status_code == 401
    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200

    initial = client.get("/operators/dashboard/access/status")
    assert initial.json()["network_access"]["effective_mode"] == "loopback"
    changed = client.post("/operators/dashboard/access/operations/network", json={"mode": "lan"})
    assert changed.status_code == 200
    assert changed.json()["configured_host"] == "0.0.0.0"
    assert changed.json()["restart_required"] is True
    assert (tmp_path / "hypervisor-bind-host").read_text(encoding="utf-8").strip() == "0.0.0.0"
    assert client.post("/operators/dashboard/access/operations/network", json={"mode": "public"}).status_code == 422


def test_operator_config_editor_is_pair_bound_validated_and_concurrency_safe(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    config_path = tmp_path / "operator-config.toml"
    write_operator_config(config_path, {"AIDN_HYPERVISOR_API_PORT": "8766"})
    restarts: list[bool] = []
    config = OperatorConfigService(
        path=config_path,
        environ={},
        restart_callback=lambda: restarts.append(True) or True,
        restart_supported=True,
    )
    app = FastAPI()
    app.include_router(
        build_operator_access_router(
            access_service=access,
            credential_store=credentials,
            allow_insecure_lan=True,
            config_service=config,
        )
    )
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)

    assert client.get("/operators/dashboard/access/config").status_code == 401
    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200

    initial = client.get("/operators/dashboard/access/config")
    assert initial.status_code == 200
    assert initial.json()["format"] == "toml"
    assert "AIDN_HYPERVISOR_API_PORT" in initial.json()["text"]
    invalid = client.post(
        "/operators/dashboard/access/config/validate",
        json={"text": '[env]\nAIDN_HYPERVISOR_API_PORT = "not-a-port"\n'},
    )
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False

    edited = '[env]\nAIDN_HYPERVISOR_API_PORT = "9000"\n'
    saved = client.put(
        "/operators/dashboard/access/config",
        json={"text": edited, "expected_sha256": initial.json()["sha256"]},
    )
    assert saved.status_code == 200
    assert saved.json()["changed_keys"] == ["AIDN_HYPERVISOR_API_PORT"]
    applied = client.post(
        "/operators/dashboard/access/config/apply",
        json={"text": edited, "expected_sha256": saved.json()["sha256"]},
    )
    assert applied.status_code == 202
    assert applied.json()["restart_scheduled"] is True
    assert restarts == [True]

    conflict = client.put(
        "/operators/dashboard/access/config",
        json={"text": edited, "expected_sha256": initial.json()["sha256"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "DASHBOARD_CONFIG_CONFLICT"


def test_paired_operator_can_list_and_update_only_known_agent_permissions(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    invalidated: list[str] = []
    app = FastAPI()
    app.include_router(build_operator_access_router(
        access_service=access,
        credential_store=credentials,
        allow_insecure_lan=True,
        invalidate_credential_sessions=invalidated.append,
    ))
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)
    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200

    catalog = client.get("/operators/dashboard/access/permission-catalog")
    assert catalog.status_code == 200
    assert any(item["scope"] == "BUNDLE:ACTIVATE" for item in catalog.json()["items"])
    assert "BUNDLE:ACTIVATE" in catalog.json()["full_control_auto_approved_scopes"]

    created = client.post(
        "/operators/dashboard/access/credentials",
        json={"label": "agent", "scopes": ["NODE:READ"]},
    )
    assert created.status_code == 201
    credential_id = created.json()["credential_id"]
    updated = client.put(
        f"/operators/dashboard/access/credentials/{credential_id}/scopes",
        json={
            "scopes": ["NODE:READ", "BUNDLE:ACTIVATE"],
            "auto_approved_scopes": ["BUNDLE:ACTIVATE"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["scopes"] == ["BUNDLE:ACTIVATE", "NODE:READ"]
    assert updated.json()["auto_approved_scopes"] == ["BUNDLE:ACTIVATE"]
    # Scope updates are live and deliberately keep the transport session. The
    # gateway re-resolves the bearer credential on the next request, so only
    # revoke/rotate operations should invalidate sessions.
    assert invalidated == []
    assert client.put(
        f"/operators/dashboard/access/credentials/{credential_id}/scopes",
        json={"scopes": ["*"]},
    ).status_code == 422
    assert client.put(
        f"/operators/dashboard/access/credentials/{credential_id}/scopes",
        json={"scopes": ["NODE:READ"], "auto_approved_scopes": ["BUNDLE:ACTIVATE"]},
    ).status_code == 422
    assert client.put(
        f"/operators/dashboard/access/credentials/{credential_id}/scopes",
        json={"scopes": ["NODE:READ"], "auto_approved_scopes": ["NODE:READ"]},
    ).status_code == 422


def test_agent_enrollment_is_approved_only_by_a_paired_dashboard(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    enrollment = McpEnrollmentService(secret_manager=manager, credential_store=credentials)
    app = FastAPI()
    app.include_router(build_operator_access_router(
        access_service=access,
        credential_store=credentials,
        enrollment_service=enrollment,
        allow_insecure_lan=True,
    ))
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)
    public_key = (
        base64.urlsafe_b64encode(
            X25519PrivateKey.generate().public_key().public_bytes_raw()
        )
        .rstrip(b"=")
        .decode("ascii")
    )

    created = client.post("/operators/dashboard/access/agent-enrollment/requests", json={
        "label": "remote-agent",
        "encryption_public_key": public_key,
    })
    assert created.status_code == 201
    approval_url = f"/operators/dashboard/access/enrollment-requests/{created.json()['request_id']}/approve"
    assert client.post(approval_url).status_code == 401

    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200
    approved = client.post(f"/operators/dashboard/access/enrollment-requests/{created.json()['request_id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["state"] == "approved"

    retrieved = client.get(
        f"/operators/dashboard/access/agent-enrollment/requests/{created.json()['request_id']}",
        headers={"X-AiDN-Enrollment-Secret": created.json()["retrieval_secret"]},
    )
    assert retrieved.status_code == 200
    assert "ciphertext" in retrieved.json()["credential"]
    assert "token" not in retrieved.text


def test_build_app_wires_secret_backed_access_management(monkeypatch, tmp_path) -> None:
    from aidn_hypervisor.main import build_app

    monkeypatch.setenv("AIDN_STATE_STORE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("AIDN_MCP_REMOTE_ENABLED", "true")
    monkeypatch.setenv("AIDN_MCP_REMOTE_TOKEN", "legacy-token")
    monkeypatch.setenv("AIDN_SECRET_MANAGER_PATH", str(tmp_path / "secrets.json"))
    monkeypatch.setenv("AIDN_SECRET_MANAGER_MASTER_KEY", base64.b64encode(os.urandom(32)).decode("ascii"))
    monkeypatch.setenv("AIDN_DASHBOARD_ACCESS_ALLOW_INSECURE_LAN", "true")
    monkeypatch.setenv("AIDN_HYPERVISOR_BUNDLES_PATH", str(tmp_path / "bundles.json"))
    app = build_app()
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)

    pairing = app.state.dashboard_access_service.create_pairing(ttl_seconds=60)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200
    status = client.get("/operators/dashboard/access/status")
    assert status.status_code == 200
    assert status.json()["enabled"] is True
    assert status.json()["credentials"][0]["label"] == "Legacy MCP agent token"


def test_paired_dashboard_operations_require_pairing_and_call_bounded_service(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    service = _OperationService()
    app = FastAPI()
    app.include_router(build_operator_access_router(
        access_service=access,
        credential_store=credentials,
        allow_insecure_lan=True,
        hypervisor_service=service,
    ))
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)

    assert client.post("/operators/dashboard/access/operations/bundles/bundle-a/enable").status_code == 401
    assert client.post(
        "/operators/dashboard/access/operations/provider-plugins/ollama/install",
        json={"configuration": {"endpoint": "http://127.0.0.1:11434"}},
    ).status_code == 401

    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200

    assert client.post("/operators/dashboard/access/operations/bundles/bundle-a/enable").json()["enabled"] is True
    assert client.post("/operators/dashboard/access/operations/bundles/bundle-a/retry").json()["status"] == "retried"
    attached = client.post(
        "/operators/dashboard/access/operations/providers/attach",
        json={"plugin_id": "ollama", "display_name": "Local Ollama", "configuration": {"base_url": "http://127.0.0.1:11434"}},
    )
    assert attached.status_code == 201
    assert attached.json()["provider_instance_id"] == "pi-test"
    detached = client.post(
        "/operators/dashboard/access/operations/providers/pi-test/detach",
    )
    assert detached.status_code == 200
    assert detached.json() == {"provider_instance_id": "pi-test", "status": "DETACHED"}
    installed = client.post(
        "/operators/dashboard/access/operations/provider-plugins/ollama/install",
        json={"configuration": {"endpoint": "http://127.0.0.1:11434"}},
    )
    assert installed.status_code == 200
    assert installed.json()["status"] == "SUCCEEDED"
    assert (
        "provider-runtime-install",
        {
            "plugin_id": "ollama",
            "configuration": {"endpoint": "http://127.0.0.1:11434"},
            "operator_note": "Paired Dashboard one-click runtime installation",
            "upgrade_acknowledged": False,
            "wait_for_completion": True,
        },
    ) in service.calls
    lifecycle_install = client.post(
        "/operators/dashboard/access/operations/provider-plugins/ollama/runtime/install",
        json={"configuration": {"endpoint": "http://127.0.0.1:11434"}, "upgrade_acknowledged": True},
    )
    assert lifecycle_install.status_code == 200
    assert lifecycle_install.json()["status"] == "SUCCEEDED"
    lifecycle_change = client.post(
        "/operators/dashboard/access/operations/provider-plugins/ollama/runtime/change",
        json={"configuration": {"endpoint": "http://127.0.0.1:11435"}, "upgrade_acknowledged": True},
    )
    assert lifecycle_change.status_code == 200
    lifecycle_remove = client.post(
        "/operators/dashboard/access/operations/provider-plugins/ollama/runtime/remove",
        json={"configuration": {}},
    )
    assert lifecycle_remove.status_code == 200
    assert [call[0] for call in service.calls if call[0].startswith("provider-runtime-")] == [
        "provider-runtime-install",
        "provider-runtime-install",
        "provider-runtime-change",
        "provider-runtime-remove",
    ]
    runtime_calls = [call for call in service.calls if call[0].startswith("provider-runtime-")]
    assert runtime_calls[1][1]["upgrade_acknowledged"] is True
    assert runtime_calls[2][1]["upgrade_acknowledged"] is True
    wallet = client.post(
        "/operators/dashboard/access/operations/wallet/create",
        json={"label": "Primary"},
    )
    assert wallet.status_code == 200
    assert wallet.json()["private_key"] == "ed25519:new-key"
    imported = client.post(
        "/operators/dashboard/access/operations/wallet/import",
        json={"label": "Imported", "private_key": "ed25519:existing"},
    )
    assert imported.status_code == 200
    assert imported.json()["private_key"] is None
    assert client.post("/operators/dashboard/access/operations/providers/pi-test/probe").json()["healthy"] is True
    discovered = client.post("/operators/dashboard/access/operations/providers/pi-test/discover-models")
    assert discovered.json()["items"][0]["model_deployment_id"] == "md-test"
    assert client.post("/operators/dashboard/access/operations/bundles/bundle-a/unknown").status_code == 422


def test_wallet_transfer_preview_is_read_only_and_submit_updates_local_ledger(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        node_id="wallet-transfer-node",
    )
    service.configure_owner_wallet(mode="create", label="Primary")
    sender_wallet = service.owner_wallet_state()["wallet_id"]
    service.credit_wallet_q_atoms(wallet_id=sender_wallet, amount_q_atoms=2_000_000)
    app = FastAPI()
    app.include_router(
        build_operator_access_router(
            access_service=access,
            credential_store=credentials,
            allow_insecure_lan=True,
            hypervisor_service=service,
        )
    )
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)

    assert client.post(
        "/operators/dashboard/access/operations/wallet/transfer/preview",
        json={"recipient_wallet": "wallet-recipient", "amount_q_atoms": 1_250_000},
    ).status_code == 401

    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200

    preview = client.post(
        "/operators/dashboard/access/operations/wallet/transfer/preview",
        json={"recipient_wallet": "wallet-recipient", "amount_q_atoms": 1_250_000, "memo": "smoke"},
    )
    assert preview.status_code == 200
    assert preview.json()["status"] == "PREVIEW"
    assert preview.json()["network_fee_q_atoms"] == 10_000
    assert preview.json()["total_debit_q_atoms"] == 1_260_000
    assert preview.json()["sufficient_balance"] is True
    assert service.wallet_q_atom_balance(sender_wallet) == 2_000_000
    assert service.wallet_q_atom_balance("wallet-recipient") == 0
    assert service.ledger_operation_service.wallet_next_sequence(sender_wallet) == 1

    submitted = client.post(
        "/operators/dashboard/access/operations/wallet/transfer",
        json={"recipient_wallet": "wallet-recipient", "amount_q_atoms": 1_250_000, "memo": "smoke"},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "FINALIZED"
    assert submitted.json()["operation_id"]
    assert service.wallet_q_atom_balance(sender_wallet) == 740_000
    assert service.wallet_q_atom_balance("wallet-recipient") == 1_250_000


def test_wallet_transfer_rejects_self_transfer_and_insufficient_balance(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    service = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    service.configure_owner_wallet(mode="create", label="Primary")
    sender_wallet = service.owner_wallet_state()["wallet_id"]
    app = FastAPI()
    app.include_router(
        build_operator_access_router(
            access_service=access,
            credential_store=credentials,
            allow_insecure_lan=True,
            hypervisor_service=service,
        )
    )
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)
    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200

    self_transfer = client.post(
        "/operators/dashboard/access/operations/wallet/transfer/preview",
        json={"recipient_wallet": sender_wallet, "amount_q_atoms": 1},
    )
    assert self_transfer.status_code == 409
    assert "differ" in self_transfer.json()["error"]["message"]

    insufficient = client.post(
        "/operators/dashboard/access/operations/wallet/transfer",
        json={"recipient_wallet": "wallet-recipient", "amount_q_atoms": 1},
    )
    assert insufficient.status_code == 409
    assert "insufficient" in insufficient.json()["error"]["message"]


def test_wallet_transfer_pending_state_is_visible_without_local_debit(tmp_path) -> None:
    class PendingConsensus:
        is_enabled = True
        is_validator = False

        def __init__(self) -> None:
            self.submissions = {}

        def query_wallet_next_sequence(self, wallet_id: str) -> int:
            return 1

        def get_submission(self, operation_id: str):
            return self.submissions.get(operation_id)

        def submit_operation(self, envelope, *, retry_existing: bool):
            submission = SimpleNamespace(
                status=SimpleNamespace(value="pending"),
                error=None,
                block_height=None,
            )
            self.submissions[envelope.operation_id] = submission
            return submission

    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    service = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    service.configure_owner_wallet(mode="create", label="Primary")
    sender_wallet = service.owner_wallet_state()["wallet_id"]
    service.credit_wallet_q_atoms(wallet_id=sender_wallet, amount_q_atoms=2_000_000)
    service.consensus_service = PendingConsensus()
    app = FastAPI()
    app.include_router(
        build_operator_access_router(
            access_service=access,
            credential_store=credentials,
            allow_insecure_lan=True,
            hypervisor_service=service,
        )
    )
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)
    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200

    submitted = client.post(
        "/operators/dashboard/access/operations/wallet/transfer",
        json={"recipient_wallet": "wallet-recipient", "amount_q_atoms": 250_000},
    )
    assert submitted.status_code == 202
    assert submitted.json()["status"] == "CONSENSUS_PENDING"
    assert service.wallet_q_atom_balance(sender_wallet) == 2_000_000

    read_model = build_operator_wallet_payload(service)
    assert read_model["wallet_state"]["pending_operation_count"] == 1
    assert read_model["pending_operations"][0]["recipient_wallet"] == "wallet-recipient"
    assert read_model["ledger_operations"] == []


def test_wallet_identity_registration_lifecycle_is_visible_in_read_model() -> None:
    class IdentityConsensus:
        is_enabled = True
        is_validator = False

        def __init__(self) -> None:
            self.submissions = {}

        def get_submission(self, operation_id: str):
            return self.submissions.get(operation_id)

    service = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    service.configure_owner_wallet(mode="create", label="Primary")
    wallet_id = service.owner_wallet_state()["wallet_id"]
    consensus = IdentityConsensus()
    service.consensus_service = consensus
    envelope = LedgerOperationEnvelope(
        operation_type="WALLET_IDENTITY_REGISTER",
        origin_type="wallet",
        initiator_id=wallet_id,
        sender_wallet=wallet_id,
        sender_sequence=1,
        fee_payer=wallet_id,
        fee_class="onboarding_exempt",
        created_at="2026-01-01T00:00:00+00:00",
        payload={"wallet_id": wallet_id},
    )
    service.stage_pending_consensus_envelope(envelope)
    consensus.submissions[envelope.operation_id] = SimpleNamespace(
        status=SimpleNamespace(value="pending"),
        error=None,
        block_height=None,
    )

    pending = build_operator_wallet_payload(service)
    assert pending["wallet_state"]["identity_registration_state"] == "pending"
    assert pending["wallet_state"]["identity_operation"]["operation_id"] == envelope.operation_id
    assert pending["wallet_state"]["identity_operation"]["error"] is None

    consensus.submissions[envelope.operation_id] = SimpleNamespace(
        status=SimpleNamespace(value="failed"),
        error="consensus rejected the identity registration",
        block_height=None,
    )
    rejected = build_operator_wallet_payload(service)
    assert rejected["wallet_state"]["identity_registration_state"] == "rejected"
    assert rejected["wallet_state"]["identity_operation"]["error"] == (
        "consensus rejected the identity registration"
    )

    identity_key = Ed25519PrivateKey.generate()
    public_key = "ed25519:" + identity_key.public_key().public_bytes(
        Encoding.Raw,
        PublicFormat.Raw,
    ).hex()
    registration_nonce = "nonce-1"
    signature = "ed25519:" + identity_key.sign(
        wallet_identity_registration_payload(
            wallet_id=wallet_id,
            public_key=public_key,
            registration_nonce=registration_nonce,
        )
    ).hex()
    service.register_wallet_identity(
        wallet_id=wallet_id,
        public_key=public_key,
        registration_nonce=registration_nonce,
        signature=signature,
    )
    registered = build_operator_wallet_payload(service)
    assert registered["wallet_state"]["identity_registration_state"] == "registered"
    assert registered["wallet_state"]["identity_operation"] is None
    assert registered["wallet_state"]["identity_operations"]


def test_paired_dashboard_model_and_bundle_lifecycle_operations_are_bounded(tmp_path) -> None:
    manager = FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    credentials = McpCredentialStore(secret_manager=manager)
    access = DashboardAccessService(store=credentials)
    service = _OperationService()
    app = FastAPI()
    app.include_router(build_operator_access_router(
        access_service=access,
        credential_store=credentials,
        allow_insecure_lan=True,
        hypervisor_service=service,
    ))
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)

    assert client.post(
        "/operators/dashboard/access/operations/models/install",
        json={"provider_type": "whisper", "model_id": "small", "source_url": "file:///tmp/model.bin"},
    ).status_code == 401

    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 200

    assert client.post(
        "/operators/dashboard/access/operations/models/install",
        json={"provider_type": "whisper", "model_id": "small", "source_url": "file:///tmp/model.bin"},
    ).status_code == 202
    assert client.post("/operators/dashboard/access/operations/models/install/process").status_code == 200
    assert client.post(
        "/operators/dashboard/access/operations/models/install-test/register-bundle",
        json={"bundle_id": "bundle-small", "workload_type": "speech_to_text", "endpoint": "http://127.0.0.1:9000"},
    ).status_code == 201
    assert client.post(
        "/operators/dashboard/access/operations/model-artifact-sets",
        json={"display_name": "Whisper files", "files": [{"relative_path": "model.bin", "artifact_id": "a1"}]},
    ).status_code == 201
    assert client.post(
        "/operators/dashboard/access/operations/model-deployments/md-test/artifact-set",
        json={"artifact_set_id": "set-test"},
    ).status_code == 200
    assert client.post(
        "/operators/dashboard/access/operations/provider-instances/pi-test/artifact-sets/materialize",
        json={"artifact_set_id": "set-test", "destination": "/var/lib/aidn/models/small"},
    ).status_code == 200
    assert client.post(
        "/operators/dashboard/access/operations/model-deployments/md-test/runtime-bindings",
        json={"capability_id": "speech.stt", "capability_version": "1.0.0", "capability_definition_hash": "sha256:stt"},
    ).status_code == 201
    assert client.post(
        "/operators/dashboard/access/operations/bundles/bundle-small/revisions",
        json={"bundle_id": "bundle-small-v2", "overrides": {"priority_class": 90}},
    ).status_code == 201
    assert [call[0] for call in service.calls[-8:]] == [
        "install",
        "process-installs",
        "register-bundle",
        "artifact-set",
        "bind-artifact-set",
        "materialize-artifact-set",
        "runtime-binding",
        "bundle-revision",
    ]


def test_validator_boundary_permits_only_paired_dashboard_operations() -> None:
    from aidn_hypervisor.main import _is_validator_consensus_write_path

    assert _is_validator_consensus_write_path(
        "/operators/dashboard/access/operations/bundles/bundle-a/enable", "POST"
    )
    assert _is_validator_consensus_write_path(
        "/operators/dashboard/access/operations/wallet/create", "POST"
    )
    assert _is_validator_consensus_write_path(
        "/operators/dashboard/access/operations/wallet/transfer/preview", "POST"
    )
    assert _is_validator_consensus_write_path(
        "/operators/dashboard/access/operations/wallet/transfer", "POST"
    )
    assert _is_validator_consensus_write_path(
        "/operators/dashboard/access/operations/models/install", "POST"
    )
    assert _is_validator_consensus_write_path(
        "/operators/dashboard/access/operations/model-deployments/md-1/runtime-bindings", "POST"
    )
    assert _is_validator_consensus_write_path(
        "/operators/dashboard/access/operations/endpoints/ep-1/publish", "POST"
    )
    assert not _is_validator_consensus_write_path("/operators/dashboard/access/operations/unknown", "POST")
