from fastapi.testclient import TestClient

from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.main import build_app


def _client() -> TestClient:
    endpoint_service = EndpointService(EndpointStore())
    return TestClient(build_app(endpoint_service=endpoint_service))


def test_create_endpoint_api_returns_enveloped_response() -> None:
    response = _client().post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Operator STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
        },
    )

    body = response.json()

    assert response.status_code == 201
    assert body["data"]["endpoint"]["status"] == "created"
    assert body["error"] is None
    assert body["correlation_id"]


def test_patch_endpoint_runtime_rotates_configuration_hash() -> None:
    client = _client()
    created = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Operator STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
        },
    ).json()["data"]["endpoint"]

    updated = client.patch(
        f"/api/v1/endpoints/{created['endpoint_id']}",
        json={"runtime": {"streaming": True, "timeout": 45}},
    ).json()["data"]["endpoint"]

    assert updated["configuration_hash"] != created["configuration_hash"]


def test_patch_endpoint_can_publish_without_auto_enabling_validation() -> None:
    client = _client()
    created = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Operator STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
        },
    ).json()["data"]["endpoint"]

    body = client.patch(
        f"/api/v1/endpoints/{created['endpoint_id']}",
        json={
            "publication": {
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
                "discoverable": True,
                "accepts_external_requests": True,
                "validation": "disabled",
            }
        },
    ).json()

    assert body["data"]["endpoint"]["publication"]["discoverable"] is True
    assert body["data"]["endpoint"]["publication"]["visibility"] == "shared"
    assert body["data"]["endpoint"]["publication"]["shared_with_wallet_ids"] == [
        "wallet-a"
    ]
    assert body["data"]["endpoint"]["validation"]["enabled"] is False


def test_create_endpoint_api_accepts_shared_wallet_allowlist() -> None:
    response = _client().post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Shared STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
            "publication": {
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a", "wallet-b"],
            },
        },
    )

    body = response.json()

    assert response.status_code == 201
    assert body["data"]["endpoint"]["publication"]["visibility"] == "shared"
    assert body["data"]["endpoint"]["publication"]["shared_with_wallet_ids"] == [
        "wallet-a",
        "wallet-b",
    ]
