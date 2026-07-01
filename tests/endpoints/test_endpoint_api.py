from fastapi.testclient import TestClient

from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.main import build_app
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore


def _client() -> TestClient:
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    return TestClient(
        build_app(endpoint_service=endpoint_service, session_service=session_service)
    )


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


def test_create_endpoint_api_returns_session_policy() -> None:
    response = _client().post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Paid STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
            "session": {
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 2,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        },
    )

    body = response.json()

    assert response.status_code == 201
    assert body["data"]["endpoint"]["session"]["minimum_deposit"] == 10.0
    assert body["data"]["endpoint"]["session"]["queue_policy"] == "busy"


def test_open_endpoint_session_api_returns_active_session() -> None:
    client = _client()
    endpoint = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-provider",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Paid STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
            "session": {
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        },
    ).json()["data"]["endpoint"]

    response = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/sessions",
        json={"client_wallet": "wallet-client", "deposit_q": 10.0},
    )

    body = response.json()

    assert response.status_code == 201
    assert body["data"]["session"]["endpoint_id"] == endpoint["endpoint_id"]
    assert body["data"]["session"]["status"] == "active"
    assert body["data"]["deposit"]["locked_q"] == 10.0


def test_close_endpoint_session_api_closes_session() -> None:
    client = _client()
    endpoint = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-provider",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Paid STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
            "session": {
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        },
    ).json()["data"]["endpoint"]
    created = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/sessions",
        json={"client_wallet": "wallet-client", "deposit_q": 10.0},
    ).json()["data"]["session"]

    response = client.post(f"/api/v1/sessions/{created['session_id']}/close")

    body = response.json()

    assert response.status_code == 200
    assert body["data"]["session"]["status"] == "closed"
    assert body["data"]["deposit"]["status"] == "released"
