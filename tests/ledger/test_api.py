from fastapi.testclient import TestClient

from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.main import build_app
from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


def _service() -> HypervisorService:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        node_id="node-a",
        operator_id="operator-a",
    )
    session_service = SessionService(
        SessionStore(),
        event_recorder=service.record_event,
        operation_recorder=service.record_ledger_operation,
    )
    service.session_service = session_service
    return service


def test_operator_ledger_operations_endpoint_returns_canonical_operations() -> None:
    service = _service()
    service.record_ledger_operation(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        fee_class="standard",
        initiator_id="wallet-1",
        sender_wallet="wallet-1",
        fee_payer="wallet-1",
        payload={"recipient_wallet": "wallet-2", "amount": 5.0},
        created_at="2026-07-11T00:00:00+00:00",
    )
    client = TestClient(build_app(service=service, session_service=service.session_service))

    response = client.get("/operators/ledger/operations")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["operation_type"] == "WALLET_TRANSFER"
    assert body[0]["sender_sequence"] == 1


def test_operator_ledger_operations_export_supports_sequence_cursor() -> None:
    service = _service()
    service.record_ledger_operation(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        fee_class="standard",
        initiator_id="wallet-1",
        sender_wallet="wallet-1",
        fee_payer="wallet-1",
        payload={"recipient_wallet": "wallet-2", "amount": 5.0},
        created_at="2026-07-11T00:00:00+00:00",
    )
    second = service.record_ledger_operation(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        fee_class="standard",
        initiator_id="wallet-1",
        sender_wallet="wallet-1",
        fee_payer="wallet-1",
        payload={"recipient_wallet": "wallet-3", "amount": 6.0},
        created_at="2026-07-11T00:01:00+00:00",
    )
    client = TestClient(build_app(service=service, session_service=service.session_service))

    response = client.get("/operators/ledger/operations/export", params={"after_sequence": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["items"][0]["operation_id"] == second["operation_id"]
    assert body["cursor_status"] == "ok"


def test_validation_request_api_records_ledger_operation() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    validation_service = ValidationService(ValidationStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Validated Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            validation_service=validation_service,
            session_service=service.session_service,
        )
    )

    request_response = client.post(
        f"/api/v1/endpoints/{created.endpoint.endpoint_id}/request-validation"
    )
    ledger_response = client.get("/operators/ledger/operations")

    assert request_response.status_code == 200
    assert ledger_response.status_code == 200
    body = ledger_response.json()
    assert body[-1]["operation_type"] == "VALIDATION_REQUEST"
    assert body[-1]["payload"]["endpoint_id"] == created.endpoint.endpoint_id


def test_endpoint_create_and_patch_api_record_ledger_operations() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=service.session_service,
        )
    )

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
    )
    endpoint_id = created.json()["data"]["endpoint"]["endpoint_id"]
    updated = client.patch(
        f"/api/v1/endpoints/{endpoint_id}",
        json={"runtime": {"streaming": True, "timeout": 45}},
    )
    ledger_response = client.get("/operators/ledger/operations")

    assert created.status_code == 201
    assert updated.status_code == 200
    assert ledger_response.status_code == 200
    body = ledger_response.json()
    assert body[-2]["operation_type"] == "ENDPOINT_PUBLISH"
    assert body[-2]["payload"]["endpoint_id"] == endpoint_id
    assert body[-1]["operation_type"] == "ENDPOINT_UPDATE"
    assert body[-1]["payload"]["endpoint_id"] == endpoint_id


def test_endpoint_publication_api_records_advertisement_operations() -> None:
    service = _service()
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
            session_service=service.session_service,
        )
    )

    created = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": service.owner_wallet_state()["wallet_id"],
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Operator STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
        },
    )
    endpoint_id = created.json()["data"]["endpoint"]["endpoint_id"]
    publish = client.post(f"/api/v1/endpoints/{endpoint_id}/publish-configuration")
    revoke = client.post(f"/api/v1/endpoints/{endpoint_id}/revoke-publication")
    ledger_response = client.get("/operators/ledger/operations")

    assert publish.status_code == 200
    assert revoke.status_code == 200
    assert ledger_response.status_code == 200
    body = ledger_response.json()
    assert body[-2]["operation_type"] == "ADVERTISEMENT_PUBLISH"
    assert body[-2]["payload"]["resource_id"] == endpoint_id
    assert body[-1]["operation_type"] == "ADVERTISEMENT_WITHDRAW"
    assert body[-1]["payload"]["resource_id"] == endpoint_id
