from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.mcp.enrollment import McpEnrollmentService
from aidn_hypervisor.operator_access import DashboardAccessService
from aidn_hypervisor.operator_access_api import build_operator_access_router
from aidn_hypervisor.secrets import FileSecretManager

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

    def probe_provider_instance(self, provider_instance_id: str) -> dict:
        self.calls.append(("probe", provider_instance_id))
        return {"provider_instance_id": provider_instance_id, "healthy": True}

    def discover_provider_models(self, provider_instance_id: str) -> list[dict]:
        self.calls.append(("discover", provider_instance_id))
        return [{"model_deployment_id": "md-test"}]

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
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 204

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
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 204

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
    assert invalidated == [credential_id]
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
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 204
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
    app = build_app()
    client = TestClient(app)
    client.headers.update(_BROWSER_HEADERS)

    pairing = app.state.dashboard_access_service.create_pairing(ttl_seconds=60)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 204
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

    pairing = access.create_pairing(ttl_seconds=600)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 204

    assert client.post("/operators/dashboard/access/operations/bundles/bundle-a/enable").json()["enabled"] is True
    assert client.post("/operators/dashboard/access/operations/bundles/bundle-a/retry").json()["status"] == "retried"
    attached = client.post(
        "/operators/dashboard/access/operations/providers/attach",
        json={"plugin_id": "ollama", "display_name": "Local Ollama", "configuration": {"base_url": "http://127.0.0.1:11434"}},
    )
    assert attached.status_code == 201
    assert attached.json()["provider_instance_id"] == "pi-test"
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


def test_validator_boundary_permits_only_paired_dashboard_operations() -> None:
    from aidn_hypervisor.main import _is_validator_consensus_write_path

    assert _is_validator_consensus_write_path(
        "/operators/dashboard/access/operations/bundles/bundle-a/enable", "POST"
    )
    assert _is_validator_consensus_write_path(
        "/operators/dashboard/access/operations/wallet/create", "POST"
    )
    assert not _is_validator_consensus_write_path("/operators/dashboard/access/operations/unknown", "POST")
