from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.operator_access import DashboardAccessService
from aidn_hypervisor.operator_access_api import build_operator_access_router
from aidn_hypervisor.secrets import FileSecretManager


def test_credential_mutation_requires_pairing_and_reveals_only_new_value(tmp_path) -> None:
    credentials = McpCredentialStore(
        secret_manager=FileSecretManager(path=tmp_path / "secrets.json", master_key=os.urandom(32))
    )
    access = DashboardAccessService(store=credentials)
    app = FastAPI()
    app.include_router(
        build_operator_access_router(
            access_service=access,
            credential_store=credentials,
            allow_insecure_lan=True,
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
