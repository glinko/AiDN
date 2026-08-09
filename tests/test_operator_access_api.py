from __future__ import annotations

import base64
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.mcp.enrollment import McpEnrollmentService
from aidn_hypervisor.operator_access import DashboardAccessService
from aidn_hypervisor.operator_access_api import build_operator_access_router
from aidn_hypervisor.secrets import FileSecretManager


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
    public_key = base64.urlsafe_b64encode(X25519PrivateKey.generate().public_key().public_bytes_raw()).rstrip(b"=").decode("ascii")

    created = client.post("/operators/dashboard/access/agent-enrollment/requests", json={
        "label": "remote-agent",
        "encryption_public_key": public_key,
    })
    assert created.status_code == 201
    assert client.post(f"/operators/dashboard/access/enrollment-requests/{created.json()['request_id']}/approve").status_code == 401

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

    pairing = app.state.dashboard_access_service.create_pairing(ttl_seconds=60)
    assert client.post("/operators/dashboard/access/pair", json={"code": pairing.code}).status_code == 204
    status = client.get("/operators/dashboard/access/status")
    assert status.status_code == 200
    assert status.json()["enabled"] is True
    assert status.json()["credentials"][0]["label"] == "Legacy MCP agent token"
