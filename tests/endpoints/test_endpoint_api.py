from fastapi.testclient import TestClient

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.main import build_app
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.runtime_protocol.models import (
    RuntimeExecuteRequest,
    RuntimeRequestRecord,
    RuntimeUsageReport,
    canonical_hash,
)
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore


def _client() -> TestClient:
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    return TestClient(
        build_app(endpoint_service=endpoint_service, session_service=session_service)
    )


def _runtime_binding_bundle(bundle_id: str) -> BundleConfig:
    return BundleConfig(
        bundle_id=bundle_id,
        plugin_id="fake-managed",
        provider_type="fake",
        workload_type="llm.chat",
        model_id="qwen3:14b",
        launch_mode="managed_process",
        device_affinity="cpu",
        resource_profile=ResourceProfile(),
        warm_policy="auto",
        priority_class=50,
        enabled=True,
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


def test_open_mvp_fixed_price_session_locks_canonical_escrow() -> None:
    hypervisor = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    endpoint_service = EndpointService(EndpointStore())
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            session_service=SessionService(SessionStore()),
        )
    )
    endpoint = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-endpoint",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Fixed price endpoint",
            "model_class": "llm.chat",
        },
    ).json()["data"]["endpoint"]
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=1_000)

    response = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions",
        json={
            "client_wallet": "wallet-consumer",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
        },
    )
    body = response.json()

    assert response.status_code == 201
    assert body["data"]["session"]["economic_profile"] == "MVP-0001"
    assert body["data"]["session"]["canonical_funding_state_hash"]
    assert body["data"]["funding"]["total_locked_amount_q_atoms"] == 1_000
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 0


def test_finalize_mvp_fixed_price_session_uses_runtime_evidence_over_api() -> None:
    hypervisor = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )
    endpoint = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-endpoint",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Fixed price endpoint",
            "model_class": "llm.chat",
        },
    ).json()["data"]["endpoint"]
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=1_000)
    session = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions",
        json={
            "client_wallet": "wallet-consumer",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
        },
    ).json()["data"]["session"]
    payload = {"prompt": "hello"}
    request = RuntimeExecuteRequest(
        runtime_id="runtime-1",
        runtime_generation=1,
        runtime_configuration_hash="runtime-config-1",
        route_generation=1,
        endpoint_id=endpoint["endpoint_id"],
        endpoint_configuration_hash=endpoint["configuration_hash"],
        session_id=session["session_id"],
        session_contract_hash=session["session_contract_hash"],
        request_id="request-1",
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="capability-definition-1",
        request_payload_hash=canonical_hash(payload),
        request_payload=payload,
        request_charge_ceiling=0.0009,
        accounting_contract_hash=session["accounting_contract_hash"],
        idempotency_key="idempotency-request-1",
        request_deadline="2026-07-18T12:30:00+00:00",
    )
    final_usage = RuntimeUsageReport(
        usage_report_id="usage-final-1",
        runtime_id=request.runtime_id,
        runtime_generation=request.runtime_generation,
        runtime_configuration_hash=request.runtime_configuration_hash,
        endpoint_id=request.endpoint_id,
        endpoint_configuration_hash=request.endpoint_configuration_hash,
        session_id=session["session_id"],
        request_id=request.request_id,
        accounting_contract_hash=session["accounting_contract_hash"],
        report_type="FINAL",
        usage_sequence=1,
        request_state="COMPLETED",
        terminal=True,
        created_at="2026-07-18T12:00:05+00:00",
        runtime_signature="runtime-signed",
    )
    hypervisor.runtime_protocol_store.requests[request.request_id] = (
        RuntimeRequestRecord(
            request_id=request.request_id,
            runtime_id=request.runtime_id,
            runtime_generation=request.runtime_generation,
            route_generation=request.route_generation,
            request_hash=request.semantic_hash(),
            request=request,
            request_state="COMPLETED",
            admission_state="ACCEPTED",
            accepted_at="2026-07-18T12:00:01+00:00",
            terminal_result_hash="sha256:result-final-1",
            terminal_final_usage_report_id=final_usage.usage_report_id,
            updated_at="2026-07-18T12:00:05+00:00",
        )
    )
    hypervisor.runtime_protocol_store.usage_reports[final_usage.usage_report_id] = (
        final_usage
    )

    response = client.post(
        (
            f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions/"
            f"{session['session_id']}/finalize"
        ),
        json={
            "request_id": request.request_id,
            "consumer_signature": "consumer-signed",
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert body["data"]["proposal"]["final_endpoint_payment_q_atoms"] == 900
    assert body["data"]["proposal"]["consumer_fee_refund_q_atoms"] == 100
    assert body["data"]["funding"]["funding_state"] == "RELEASED"
    assert body["data"]["session"]["status"] == "closed"
    assert body["data"]["deposit"]["status"] == "released"
    assert body["data"]["settlement"]["settlement_evidence_root"] == (
        body["data"]["proposal"]["settlement_input_root"]
    )
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 900
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 100


def test_create_endpoint_route_accepts_runtime_binding_id() -> None:
    hypervisor = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    hypervisor.bundle_for_runtime_binding = (  # type: ignore[attr-defined]
        lambda runtime_binding_id: _runtime_binding_bundle(f"bundle-{runtime_binding_id}")
    )
    hypervisor.bundle_hash_for_runtime_binding = (  # type: ignore[attr-defined]
        lambda runtime_binding_id: f"bundle-hash-{runtime_binding_id}"
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=EndpointService(EndpointStore()),
            session_service=SessionService(SessionStore()),
        )
    )

    response = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-a",
            "runtime_binding_id": "rtb-1",
            "display_name": "Local Qwen",
            "model_class": "llm.chat",
            "capabilities": ["llm.chat"],
        },
    )

    body = response.json()

    assert response.status_code == 201
    assert body["data"]["endpoint"]["bundle_id"] == "bundle-rtb-1"
    assert body["data"]["endpoint"]["bundle_hash"] == "bundle-hash-rtb-1"


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
    assert body["data"]["settlement"]["charged_q"] == 2.01
    assert body["data"]["settlement"]["network_fee_q"] == 0.01
    assert body["data"]["settlement"]["refunded_q"] == 7.99
