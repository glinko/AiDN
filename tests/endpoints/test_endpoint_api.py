from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.main import build_app
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.runtime_protocol.models import (
    RuntimeExecuteRequest,
    RuntimeRequestRecord,
    RuntimeUsageConflict,
    RuntimeUsageReport,
    canonical_hash,
)
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore
from aidn_hypervisor.settlement.models import SessionSettlementAcceptance
from aidn_hypervisor.settlement.signing import settlement_acceptance_signing_payload
from aidn_hypervisor.wallet_identity import (
    session_open_authorization_payload,
    wallet_identity_registration_payload,
)


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


def _mvp_api_context(consumer_authorization_public_key: str | None = None):
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
    session_payload = {
        "client_wallet": "wallet-consumer",
        "deposit_q_atoms": 1_000,
        "fixed_price_q_atoms": 900,
        "network_fee_reserve_q_atoms": 100,
    }
    if consumer_authorization_public_key is not None:
        session_payload["consumer_authorization_public_key"] = consumer_authorization_public_key
    session = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions",
        json=session_payload,
    ).json()["data"]["session"]
    return hypervisor, client, endpoint, session


def _mvp_persistent_api_context(tmp_path):
    state_store = FileStateStore(tmp_path / "hypervisor-state.json")
    hypervisor = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        state_store=state_store,
    )
    endpoint_service = EndpointService(EndpointStore(state_store))
    session_service = SessionService(SessionStore(state_store))
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
            "display_name": "Persistent fixed price endpoint",
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
    return state_store, hypervisor, client, endpoint, session


def _mvp_executable_api_context(*, open_session: bool = True):
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    hypervisor = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=2048)),
        bundles=[
            BundleConfig(
                bundle_id="bundle-a",
                plugin_id="fake-managed",
                provider_type="fake",
                workload_type="llm_text",
                model_id="fake-model",
                launch_mode="managed_process",
                device_affinity="cpu",
                resource_profile=ResourceProfile(),
                warm_policy="auto",
                priority_class=50,
                enabled=True,
            )
        ],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
    )
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
            "display_name": "Executable fixed price endpoint",
            "model_class": "llm.chat",
            "capabilities": ["llm.chat"],
        },
    ).json()["data"]["endpoint"]
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=1_000)
    session = None
    if open_session:
        session_payload = {
            "client_wallet": "wallet-consumer",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
        }
        session = client.post(
            f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions",
            json=session_payload,
        ).json()["data"]["session"]
    return hypervisor, client, endpoint, session


def _restored_mvp_api_context(state_store: FileStateStore):
    hypervisor = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        state_store=state_store,
    )
    hypervisor.restore_state(state_store.load())
    endpoint_service = EndpointService(EndpointStore(state_store))
    session_service = SessionService(SessionStore(state_store))
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )
    return hypervisor, client, endpoint_service, session_service


def _seed_terminal_runtime_evidence(
    hypervisor: HypervisorService,
    *,
    endpoint: dict,
    session: dict,
    request_id: str = "request-1",
    include_final_usage: bool = True,
) -> tuple[RuntimeExecuteRequest, RuntimeUsageReport]:
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
        request_id=request_id,
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="capability-definition-1",
        request_payload_hash=canonical_hash(payload),
        request_payload=payload,
        request_charge_ceiling=0.0009,
        accounting_contract_hash=session["accounting_contract_hash"],
        idempotency_key=f"idempotency-{request_id}",
        request_deadline="2026-07-18T12:30:00+00:00",
    )
    final_usage = RuntimeUsageReport(
        usage_report_id=f"usage-final-{request_id}",
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
    if include_final_usage:
        hypervisor.runtime_protocol_store.usage_reports[final_usage.usage_report_id] = (
            final_usage
        )
    hypervisor.runtime_protocol_store.flush()
    return request, final_usage


def _finalize_mvp_session(client: TestClient, *, endpoint: dict, session: dict, request_id: str):
    return client.post(
        (
            f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions/"
            f"{session['session_id']}/finalize"
        ),
        json={
            "request_id": request_id,
            "consumer_signature": "consumer-signed",
        },
    )


def _force_finalize_mvp_session(
    client: TestClient,
    *,
    endpoint: dict,
    session: dict,
    reason: str,
    force_after: str,
    now: str,
    request_id: str | None = None,
):
    payload = {
        "reason": reason,
        "force_after": force_after,
        "now": now,
    }
    if request_id is not None:
        payload["request_id"] = request_id
    return client.post(
        (
            f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions/"
            f"{session['session_id']}/force-finalize"
        ),
        json=payload,
    )


def _ledger_operation_count(hypervisor: HypervisorService, operation_type: str) -> int:
    return sum(
        1
        for item in hypervisor.list_ledger_operations()
        if item["operation_type"] == operation_type
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


def test_open_public_mvp_fixed_price_session_requires_wallet_bound_authorization() -> None:
    hypervisor = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    operator_wallet_id = hypervisor.owner_wallet_state()["wallet_id"]
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
            session_service=SessionService(SessionStore()),
        )
    )
    endpoint = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": operator_wallet_id,
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Public fixed price endpoint",
            "model_class": "llm.chat",
            "publication": {
                "visibility": "public",
                "discoverable": True,
                "accepts_external_requests": True,
            },
            "pricing": {"billing_unit": "request", "fixed_price": 0.0009},
        },
    ).json()["data"]["endpoint"]
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=1_000)

    consumer_key = Ed25519PrivateKey.generate()
    consumer_public_key = (
        f"ed25519:{consumer_key.public_key().public_bytes_raw().hex()}"
    )
    consumer_nonce = "consumer-registration"
    consumer_signature = consumer_key.sign(
        wallet_identity_registration_payload(
            wallet_id="wallet-consumer",
            public_key=consumer_public_key,
            registration_nonce=consumer_nonce,
        )
    ).hex()
    registered_consumer = client.post(
        "/wallets/identity",
        json={
            "wallet_id": "wallet-consumer",
            "public_key": consumer_public_key,
            "registration_nonce": consumer_nonce,
            "signature": f"ed25519:{consumer_signature}",
        },
    )

    operator_key = Ed25519PrivateKey.generate()
    operator_public_key = (
        f"ed25519:{operator_key.public_key().public_bytes_raw().hex()}"
    )
    operator_nonce = "operator-registration"
    operator_signature = operator_key.sign(
        wallet_identity_registration_payload(
            wallet_id=operator_wallet_id,
            public_key=operator_public_key,
            registration_nonce=operator_nonce,
        )
    ).hex()
    registered_operator = client.post(
        "/wallets/identity",
        json={
            "wallet_id": operator_wallet_id,
            "public_key": operator_public_key,
            "registration_nonce": operator_nonce,
            "signature": f"ed25519:{operator_signature}",
        },
    )
    published = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/publish-configuration"
    )

    authorization_nonce = "public-session-nonce"
    expires_at = "2030-01-01T00:00:00+00:00"
    authorization_signature = consumer_key.sign(
        session_open_authorization_payload(
            wallet_id="wallet-consumer",
            endpoint_id=endpoint["endpoint_id"],
            endpoint_configuration_hash=endpoint["configuration_hash"],
            deposit_q_atoms=1_000,
            fixed_price_q_atoms=900,
            network_fee_reserve_q_atoms=100,
            nonce=authorization_nonce,
            expires_at=expires_at,
        )
    ).hex()

    response = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/public-mvp-sessions",
        json={
            "client_wallet": "wallet-consumer",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
            "consumer_authorization": {
                "nonce": authorization_nonce,
                "expires_at": expires_at,
                "signature": f"ed25519:{authorization_signature}",
            },
        },
    )
    body = response.json()

    assert registered_consumer.status_code == 201
    assert registered_operator.status_code == 201
    assert published.status_code == 200
    assert response.status_code == 201
    assert (
        body["data"]["session"]["consumer_authorization_public_key"]
        == consumer_public_key
    )
    assert body["data"]["session"]["endpoint_payment_beneficiary"] == operator_wallet_id
    assert body["data"]["funding"]["funding_state"] == "LOCKED"
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 0

    mismatched_nonce = "public-session-price-mismatch"
    mismatched_signature = consumer_key.sign(
        session_open_authorization_payload(
            wallet_id="wallet-consumer",
            endpoint_id=endpoint["endpoint_id"],
            endpoint_configuration_hash=endpoint["configuration_hash"],
            deposit_q_atoms=1_000,
            fixed_price_q_atoms=901,
            network_fee_reserve_q_atoms=99,
            nonce=mismatched_nonce,
            expires_at=expires_at,
        )
    ).hex()
    mismatched = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/public-mvp-sessions",
        json={
            "client_wallet": "wallet-consumer",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 901,
            "network_fee_reserve_q_atoms": 99,
            "consumer_authorization": {
                "nonce": mismatched_nonce,
                "expires_at": expires_at,
                "signature": f"ed25519:{mismatched_signature}",
            },
        },
    )
    assert mismatched.status_code == 409
    assert "fixed price must match" in mismatched.json()["error"]["message"]


def test_open_public_mvp_fixed_price_session_returns_endpoint_not_found() -> None:
    hypervisor = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=EndpointService(EndpointStore()),
            session_service=SessionService(SessionStore()),
        )
    )

    response = client.post(
        "/api/v1/endpoints/missing-endpoint/public-mvp-sessions",
        json={
            "client_wallet": "wallet-consumer",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
            "consumer_authorization": {
                "nonce": "nonce",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "signature": "ed25519:" + "00" * 64,
            },
        },
    )
    body = response.json()

    assert response.status_code == 404
    assert body["error"]["code"] == "endpoint_not_found"


def test_open_public_mvp_fixed_price_session_rejects_unpublished_endpoint() -> None:
    hypervisor = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
            session_service=SessionService(SessionStore()),
        )
    )
    endpoint = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-operator",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Unpublished endpoint",
            "model_class": "llm.chat",
        },
    ).json()["data"]["endpoint"]
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=1_000)

    consumer_key = Ed25519PrivateKey.generate()
    consumer_public_key = (
        f"ed25519:{consumer_key.public_key().public_bytes_raw().hex()}"
    )
    consumer_signature = consumer_key.sign(
        wallet_identity_registration_payload(
            wallet_id="wallet-consumer",
            public_key=consumer_public_key,
            registration_nonce="consumer-registration",
        )
    ).hex()
    operator_key = Ed25519PrivateKey.generate()
    operator_public_key = (
        f"ed25519:{operator_key.public_key().public_bytes_raw().hex()}"
    )
    operator_signature = operator_key.sign(
        wallet_identity_registration_payload(
            wallet_id="wallet-operator",
            public_key=operator_public_key,
            registration_nonce="operator-registration",
        )
    ).hex()
    assert client.post(
        "/wallets/identity",
        json={
            "wallet_id": "wallet-consumer",
            "public_key": consumer_public_key,
            "registration_nonce": "consumer-registration",
            "signature": f"ed25519:{consumer_signature}",
        },
    ).status_code == 201
    assert client.post(
        "/wallets/identity",
        json={
            "wallet_id": "wallet-operator",
            "public_key": operator_public_key,
            "registration_nonce": "operator-registration",
            "signature": f"ed25519:{operator_signature}",
        },
    ).status_code == 201
    authorization_signature = consumer_key.sign(
        session_open_authorization_payload(
            wallet_id="wallet-consumer",
            endpoint_id=endpoint["endpoint_id"],
            endpoint_configuration_hash=endpoint["configuration_hash"],
            deposit_q_atoms=1_000,
            fixed_price_q_atoms=900,
            network_fee_reserve_q_atoms=100,
            nonce="unpublished-session",
            expires_at="2030-01-01T00:00:00+00:00",
        )
    ).hex()

    response = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/public-mvp-sessions",
        json={
            "client_wallet": "wallet-consumer",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
            "consumer_authorization": {
                "nonce": "unpublished-session",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "signature": f"ed25519:{authorization_signature}",
            },
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "public_mvp_session_open_rejected"
    assert "currently published" in response.json()["error"]["message"]


def test_open_public_mvp_fixed_price_session_rejects_revoked_endpoint() -> None:
    hypervisor = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    operator_wallet_id = hypervisor.owner_wallet_state()["wallet_id"]
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
            session_service=SessionService(SessionStore()),
        )
    )
    endpoint = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": operator_wallet_id,
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Revoked endpoint",
            "model_class": "llm.chat",
            "publication": {
                "visibility": "public",
                "discoverable": True,
                "accepts_external_requests": True,
            },
            "pricing": {"billing_unit": "request", "fixed_price": 0.0009},
        },
    ).json()["data"]["endpoint"]
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=1_000)
    consumer_key = Ed25519PrivateKey.generate()
    operator_key = Ed25519PrivateKey.generate()
    consumer_public_key = (
        f"ed25519:{consumer_key.public_key().public_bytes_raw().hex()}"
    )
    operator_public_key = (
        f"ed25519:{operator_key.public_key().public_bytes_raw().hex()}"
    )
    assert client.post(
        "/wallets/identity",
        json={
            "wallet_id": "wallet-consumer",
            "public_key": consumer_public_key,
            "registration_nonce": "consumer-registration",
            "signature": "ed25519:"
            + consumer_key.sign(
                wallet_identity_registration_payload(
                    wallet_id="wallet-consumer",
                    public_key=consumer_public_key,
                    registration_nonce="consumer-registration",
                )
            ).hex(),
        },
    ).status_code == 201
    assert client.post(
        "/wallets/identity",
        json={
            "wallet_id": operator_wallet_id,
            "public_key": operator_public_key,
            "registration_nonce": "operator-registration",
            "signature": "ed25519:"
                + operator_key.sign(
                    wallet_identity_registration_payload(
                        wallet_id=operator_wallet_id,
                        public_key=operator_public_key,
                        registration_nonce="operator-registration",
                    )
            ).hex(),
        },
    ).status_code == 201
    assert client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/publish-configuration"
    ).status_code == 200
    assert client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/revoke-publication"
    ).status_code == 200
    authorization_signature = consumer_key.sign(
        session_open_authorization_payload(
            wallet_id="wallet-consumer",
            endpoint_id=endpoint["endpoint_id"],
            endpoint_configuration_hash=endpoint["configuration_hash"],
            deposit_q_atoms=1_000,
            fixed_price_q_atoms=900,
            network_fee_reserve_q_atoms=100,
            nonce="revoked-session",
            expires_at="2030-01-01T00:00:00+00:00",
        )
    ).hex()

    response = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/public-mvp-sessions",
        json={
            "client_wallet": "wallet-consumer",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
            "consumer_authorization": {
                "nonce": "revoked-session",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "signature": f"ed25519:{authorization_signature}",
            },
        },
    )

    assert response.status_code == 409
    assert "currently published" in response.json()["error"]["message"]


def test_open_public_mvp_fixed_price_session_rejects_drifted_publication() -> None:
    hypervisor = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    operator_wallet_id = hypervisor.owner_wallet_state()["wallet_id"]
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
            session_service=SessionService(SessionStore()),
        )
    )
    endpoint = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": operator_wallet_id,
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Drifted endpoint",
            "model_class": "llm.chat",
            "publication": {
                "visibility": "public",
                "discoverable": True,
                "accepts_external_requests": True,
            },
            "pricing": {"billing_unit": "request", "fixed_price": 0.0009},
        },
    ).json()["data"]["endpoint"]
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=1_000)
    consumer_key = Ed25519PrivateKey.generate()
    operator_key = Ed25519PrivateKey.generate()
    consumer_public_key = (
        f"ed25519:{consumer_key.public_key().public_bytes_raw().hex()}"
    )
    operator_public_key = (
        f"ed25519:{operator_key.public_key().public_bytes_raw().hex()}"
    )
    assert client.post(
        "/wallets/identity",
        json={
            "wallet_id": "wallet-consumer",
            "public_key": consumer_public_key,
            "registration_nonce": "consumer-registration",
            "signature": "ed25519:"
            + consumer_key.sign(
                wallet_identity_registration_payload(
                    wallet_id="wallet-consumer",
                    public_key=consumer_public_key,
                    registration_nonce="consumer-registration",
                )
            ).hex(),
        },
    ).status_code == 201
    assert client.post(
        "/wallets/identity",
        json={
            "wallet_id": operator_wallet_id,
            "public_key": operator_public_key,
            "registration_nonce": "operator-registration",
            "signature": "ed25519:"
                + operator_key.sign(
                    wallet_identity_registration_payload(
                        wallet_id=operator_wallet_id,
                        public_key=operator_public_key,
                        registration_nonce="operator-registration",
                    )
            ).hex(),
        },
    ).status_code == 201
    assert client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/publish-configuration"
    ).status_code == 200
    updated = client.patch(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}",
        json={"runtime": {"streaming": True, "timeout": 45}},
    )
    assert updated.status_code == 200
    drifted_endpoint = updated.json()["data"]["endpoint"]
    authorization_signature = consumer_key.sign(
        session_open_authorization_payload(
            wallet_id="wallet-consumer",
            endpoint_id=drifted_endpoint["endpoint_id"],
            endpoint_configuration_hash=drifted_endpoint["configuration_hash"],
            deposit_q_atoms=1_000,
            fixed_price_q_atoms=900,
            network_fee_reserve_q_atoms=100,
            nonce="drifted-session",
            expires_at="2030-01-01T00:00:00+00:00",
        )
    ).hex()

    response = client.post(
        f"/api/v1/endpoints/{drifted_endpoint['endpoint_id']}/public-mvp-sessions",
        json={
            "client_wallet": "wallet-consumer",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
            "consumer_authorization": {
                "nonce": "drifted-session",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "signature": f"ed25519:{authorization_signature}",
            },
        },
    )

    assert response.status_code == 409
    assert "match the current published configuration" in response.json()["error"]["message"]


def test_open_public_mvp_fixed_price_session_accepts_registry_backed_wallet_identities(
) -> None:
    hypervisor = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    session_service = SessionService(SessionStore())
    registry = RegistryService()
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    operator_wallet_id = hypervisor.owner_wallet_state()["wallet_id"]
    client = TestClient(
        build_app(
            service=hypervisor,
            registry_service=registry,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
            session_service=session_service,
        )
    )
    endpoint = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": operator_wallet_id,
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Registry-backed identity endpoint",
            "model_class": "llm.chat",
            "publication": {
                "visibility": "public",
                "discoverable": True,
                "accepts_external_requests": True,
            },
            "pricing": {"billing_unit": "request", "fixed_price": 0.0009},
        },
    ).json()["data"]["endpoint"]
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=1_000)
    consumer_key = Ed25519PrivateKey.generate()
    operator_key = Ed25519PrivateKey.generate()
    consumer_public_key = (
        f"ed25519:{consumer_key.public_key().public_bytes_raw().hex()}"
    )
    operator_public_key = (
        f"ed25519:{operator_key.public_key().public_bytes_raw().hex()}"
    )
    assert client.post(
        "/wallets/identity",
        json={
            "wallet_id": "wallet-consumer",
            "public_key": consumer_public_key,
            "registration_nonce": "consumer-registry-backed",
            "signature": "ed25519:"
            + consumer_key.sign(
                wallet_identity_registration_payload(
                    wallet_id="wallet-consumer",
                    public_key=consumer_public_key,
                    registration_nonce="consumer-registry-backed",
                )
            ).hex(),
        },
    ).status_code == 201
    assert client.post(
        "/wallets/identity",
        json={
            "wallet_id": operator_wallet_id,
            "public_key": operator_public_key,
            "registration_nonce": "operator-registry-backed",
            "signature": "ed25519:"
            + operator_key.sign(
                wallet_identity_registration_payload(
                    wallet_id=operator_wallet_id,
                    public_key=operator_public_key,
                    registration_nonce="operator-registry-backed",
                )
            ).hex(),
        },
    ).status_code == 201
    assert client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/publish-configuration"
    ).status_code == 200
    hypervisor._wallet_identities.clear()
    authorization_signature = consumer_key.sign(
        session_open_authorization_payload(
            wallet_id="wallet-consumer",
            endpoint_id=endpoint["endpoint_id"],
            endpoint_configuration_hash=endpoint["configuration_hash"],
            deposit_q_atoms=1_000,
            fixed_price_q_atoms=900,
            network_fee_reserve_q_atoms=100,
            nonce="registry-backed-session",
            expires_at="2030-01-01T00:00:00+00:00",
        )
    ).hex()

    response = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/public-mvp-sessions",
        json={
            "client_wallet": "wallet-consumer",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
            "consumer_authorization": {
                "nonce": "registry-backed-session",
                "expires_at": "2030-01-01T00:00:00+00:00",
                "signature": f"ed25519:{authorization_signature}",
            },
        },
    )

    assert response.status_code == 201
    body = response.json()["data"]
    assert body["session"]["client_wallet"] == "wallet-consumer"
    assert body["funding"]["endpoint_payment_reserve_q_atoms"] == 900


def test_finalize_mvp_fixed_price_session_uses_runtime_evidence_over_api() -> None:
    hypervisor, client, endpoint, session = _mvp_api_context()
    request, _ = _seed_terminal_runtime_evidence(
        hypervisor,
        endpoint=endpoint,
        session=session,
    )

    response = _finalize_mvp_session(
        client,
        endpoint=endpoint,
        session=session,
        request_id=request.request_id,
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


def test_mvp_settlement_preview_accepts_consumer_ed25519_signature() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = f"ed25519:{private_key.public_key().public_bytes_raw().hex()}"
    hypervisor, client, endpoint, session = _mvp_api_context(public_key)
    request, _ = _seed_terminal_runtime_evidence(
        hypervisor, endpoint=endpoint, session=session
    )
    accepted_at = "2026-07-21T12:00:00+00:00"
    preview = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions/"
        f"{session['session_id']}/settlement-preview",
        json={"request_id": request.request_id, "accepted_at": accepted_at},
    )

    assert preview.status_code == 200
    payload = preview.json()["data"]["acceptance_payload"]
    unsigned = SessionSettlementAcceptance(
        **payload,
        consumer_signature="ed25519:" + "00" * 64,
    )
    signature = private_key.sign(settlement_acceptance_signing_payload(unsigned)).hex()
    finalized = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions/"
        f"{session['session_id']}/finalize",
        json={
            "request_id": request.request_id,
            "consumer_signature": f"ed25519:{signature}",
            "accepted_at": accepted_at,
        },
    )

    assert finalized.status_code == 200
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 900


def test_mvp_fixed_price_session_executes_task_and_finalizes_from_runtime_evidence() -> None:
    hypervisor, client, endpoint, session = _mvp_executable_api_context()

    task_response = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {
                "endpoint_id": endpoint["endpoint_id"],
                "session_id": session["session_id"],
            },
        },
    )
    task_body = task_response.json()
    request_id = task_body["task_id"]
    task_detail = client.get(f"/tasks/{request_id}").json()
    runtime_record = hypervisor.runtime_protocol_store.requests[request_id]
    final_usage = hypervisor.runtime_protocol_store.usage_reports[
        runtime_record.terminal_final_usage_report_id
    ]

    finalize_response = _finalize_mvp_session(
        client,
        endpoint=endpoint,
        session=session,
        request_id=request_id,
    )
    finalize_body = finalize_response.json()

    assert task_response.status_code == 202
    assert task_detail["status"] == "completed"
    assert task_detail["result"]["ok"] is True
    assert runtime_record.request_state == "COMPLETED"
    assert runtime_record.admission_state == "ACCEPTED"
    assert runtime_record.request.session_id == session["session_id"]
    assert final_usage.report_type == "FINAL"
    assert final_usage.terminal is True
    assert final_usage.request_state == "COMPLETED"
    assert finalize_response.status_code == 200
    assert finalize_body["data"]["proposal"]["final_endpoint_payment_q_atoms"] == 900
    assert finalize_body["data"]["proposal"]["consumer_fee_refund_q_atoms"] == 100
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 900
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 100


def test_mvp_paid_smoke_opens_executes_and_auto_finalizes() -> None:
    hypervisor, client, endpoint, _ = _mvp_executable_api_context(open_session=False)

    response = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-paid-smoke",
        json={
            "client_wallet": "wallet-consumer",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
            "task_type": "llm_text.generate",
            "payload": {"prompt": "smoke"},
        },
    )
    body = response.json()["data"]

    assert response.status_code == 201
    assert body["task"]["status"] == "completed"
    assert body["runtime_evidence"]["request"]["request_state"] == "COMPLETED"
    assert body["runtime_evidence"]["final_usage"]["report_type"] == "FINAL"
    assert body["settlement_readiness"]["ready"] is True
    assert body["settlement_readiness"]["proposal"]["final_endpoint_payment_q_atoms"] == 900
    assert body["finalized"]["funding"]["funding_state"] == "RELEASED"
    assert body["finalized"]["session"]["status"] == "closed"
    assert body["finalized"]["deposit"]["status"] == "released"
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 900
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 100


def test_mvp_paid_smoke_can_return_readiness_without_finalizing() -> None:
    hypervisor, client, endpoint, _ = _mvp_executable_api_context(open_session=False)

    response = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-paid-smoke",
        json={
            "client_wallet": "wallet-consumer",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
            "task_type": "llm_text.generate",
            "payload": {"prompt": "readiness only"},
            "request_id": "request-smoke-manual",
            "auto_finalize": False,
        },
    )
    body = response.json()["data"]
    session = body["session"]

    assert response.status_code == 201
    assert body["finalized"] is None
    assert body["settlement_readiness"]["ready"] is True
    assert body["settlement_readiness"]["proposal"]["final_endpoint_payment_q_atoms"] == 900
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 0
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 0

    finalize_response = _finalize_mvp_session(
        client,
        endpoint=endpoint,
        session=session,
        request_id="request-smoke-manual",
    )

    assert finalize_response.status_code == 200
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 900
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 100


def test_mvp_fixed_price_session_rejects_second_runtime_request() -> None:
    hypervisor, client, endpoint, session = _mvp_executable_api_context()
    first = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "first"},
            "constraints": {
                "endpoint_id": endpoint["endpoint_id"],
                "session_id": session["session_id"],
            },
        },
    )
    second = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "second"},
            "constraints": {
                "endpoint_id": endpoint["endpoint_id"],
                "session_id": session["session_id"],
            },
        },
    )

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"] == (
        "MVP-0001 supports exactly one Runtime Request per Session"
    )
    assert len(
        [
            item
            for item in hypervisor.runtime_protocol_store.requests.values()
            if item.request.session_id == session["session_id"]
        ]
    ) == 1


def test_finalize_mvp_fixed_price_session_rejects_missing_final_usage() -> None:
    hypervisor, client, endpoint, session = _mvp_api_context()
    request, _ = _seed_terminal_runtime_evidence(
        hypervisor,
        endpoint=endpoint,
        session=session,
        include_final_usage=False,
    )

    response = _finalize_mvp_session(
        client,
        endpoint=endpoint,
        session=session,
        request_id=request.request_id,
    )
    body = response.json()

    assert response.status_code == 409
    assert body["error"]["code"] == "mvp_session_finalize_rejected"
    assert "Final Usage Report is missing" in body["error"]["message"]
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 0
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 0


def test_finalize_mvp_fixed_price_session_rejects_usage_conflict() -> None:
    hypervisor, client, endpoint, session = _mvp_api_context()
    request, final_usage = _seed_terminal_runtime_evidence(
        hypervisor,
        endpoint=endpoint,
        session=session,
    )
    conflict = RuntimeUsageConflict(
        usage_report_id=final_usage.usage_report_id,
        runtime_id=request.runtime_id,
        session_id=session["session_id"],
        request_id=request.request_id,
        usage_sequence=final_usage.usage_sequence,
        accepted_report_hash="sha256:accepted",
        conflicting_report_hash=final_usage.report_hash,
        conflict_type="CHAIN",
        observed_at="2026-07-18T12:00:06+00:00",
    )
    hypervisor.runtime_protocol_store.usage_conflicts[conflict.conflict_id] = conflict

    response = _finalize_mvp_session(
        client,
        endpoint=endpoint,
        session=session,
        request_id=request.request_id,
    )
    body = response.json()

    assert response.status_code == 409
    assert body["error"]["code"] == "mvp_session_finalize_rejected"
    assert "undisputed Runtime evidence" in body["error"]["message"]
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 0
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 0


def test_finalize_mvp_fixed_price_session_rejects_wrong_endpoint_path() -> None:
    hypervisor, client, endpoint, session = _mvp_api_context()
    request, _ = _seed_terminal_runtime_evidence(
        hypervisor,
        endpoint=endpoint,
        session=session,
    )
    other_endpoint = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-other",
            "bundle_id": "bundle-b",
            "bundle_hash": "bundle-hash-b",
            "display_name": "Other endpoint",
            "model_class": "llm.chat",
        },
    ).json()["data"]["endpoint"]

    response = _finalize_mvp_session(
        client,
        endpoint=other_endpoint,
        session=session,
        request_id=request.request_id,
    )
    body = response.json()

    assert response.status_code == 409
    assert body["error"]["code"] == "mvp_session_endpoint_mismatch"
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 0


def test_finalize_mvp_fixed_price_session_duplicate_does_not_double_pay() -> None:
    hypervisor, client, endpoint, session = _mvp_api_context()
    request, _ = _seed_terminal_runtime_evidence(
        hypervisor,
        endpoint=endpoint,
        session=session,
    )

    first = _finalize_mvp_session(
        client,
        endpoint=endpoint,
        session=session,
        request_id=request.request_id,
    )
    second = _finalize_mvp_session(
        client,
        endpoint=endpoint,
        session=session,
        request_id=request.request_id,
    )
    body = second.json()

    assert first.status_code == 200
    assert second.status_code == 409
    assert body["error"]["code"] == "mvp_session_finalize_rejected"
    assert "already finalized" in body["error"]["message"]
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 900
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 100


def test_finalize_mvp_fixed_price_session_survives_restore_without_double_pay(
    tmp_path,
) -> None:
    state_store, hypervisor, client, endpoint, session = _mvp_persistent_api_context(
        tmp_path
    )
    request, final_usage = _seed_terminal_runtime_evidence(
        hypervisor,
        endpoint=endpoint,
        session=session,
    )

    response = _finalize_mvp_session(
        client,
        endpoint=endpoint,
        session=session,
        request_id=request.request_id,
    )
    assert response.status_code == 200

    restored, restored_client, _, restored_session_service = _restored_mvp_api_context(
        state_store
    )
    funding = restored.get_session_funding_account(session["session_id"])
    restored_request = restored.runtime_protocol_store.requests[request.request_id]
    restored_usage = restored.runtime_protocol_store.usage_reports[
        final_usage.usage_report_id
    ]
    restored_session = restored_session_service.store.get_session(session["session_id"])
    restored_deposit = restored_session_service.store.get_deposit_for_session(
        session["session_id"]
    )
    finalize_operations = _ledger_operation_count(
        restored, "SESSION_SETTLEMENT_FINALIZE"
    )

    assert funding.funding_state == "RELEASED"
    assert restored.wallet_q_atom_balance("wallet-endpoint") == 900
    assert restored.wallet_q_atom_balance("wallet-consumer") == 100
    assert restored_request.terminal_final_usage_report_id == final_usage.usage_report_id
    assert restored_usage.report_hash == final_usage.report_hash
    assert restored_session.status == "closed"
    assert restored_deposit.status == "released"
    assert finalize_operations == 1

    duplicate = _finalize_mvp_session(
        restored_client,
        endpoint=endpoint,
        session=session,
        request_id=request.request_id,
    )

    assert duplicate.status_code == 409
    assert "already finalized" in duplicate.json()["error"]["message"]
    assert restored.wallet_q_atom_balance("wallet-endpoint") == 900
    assert restored.wallet_q_atom_balance("wallet-consumer") == 100
    assert (
        _ledger_operation_count(restored, "SESSION_SETTLEMENT_FINALIZE")
        == finalize_operations
    )


def test_force_finalize_mvp_endpoint_unavailable_refunds_after_timeout() -> None:
    hypervisor, client, endpoint, session = _mvp_api_context()

    early = _force_finalize_mvp_session(
        client,
        endpoint=endpoint,
        session=session,
        reason="ENDPOINT_UNAVAILABLE",
        force_after="2026-07-18T12:01:00+00:00",
        now="2026-07-18T12:00:59+00:00",
    )
    response = _force_finalize_mvp_session(
        client,
        endpoint=endpoint,
        session=session,
        reason="ENDPOINT_UNAVAILABLE",
        force_after="2026-07-18T12:01:00+00:00",
        now="2026-07-18T12:01:00+00:00",
    )
    body = response.json()

    assert early.status_code == 409
    assert "timeout" in early.json()["error"]["message"]
    assert response.status_code == 200
    assert body["data"]["proposal"]["final_endpoint_payment_q_atoms"] == 0
    assert body["data"]["proposal"]["consumer_payment_refund_q_atoms"] == 900
    assert body["data"]["proposal"]["consumer_fee_refund_q_atoms"] == 100
    assert body["data"]["settlement"]["no_request"] is True
    assert body["data"]["session"]["status"] == "closed"
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 0
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 1_000


def test_force_finalize_mvp_endpoint_unavailable_survives_restore_without_double_refund(
    tmp_path,
) -> None:
    state_store, _, client, endpoint, session = _mvp_persistent_api_context(tmp_path)

    response = _force_finalize_mvp_session(
        client,
        endpoint=endpoint,
        session=session,
        reason="ENDPOINT_UNAVAILABLE",
        force_after="2026-07-18T12:01:00+00:00",
        now="2026-07-18T12:01:00+00:00",
    )
    assert response.status_code == 200

    restored, restored_client, _, restored_session_service = _restored_mvp_api_context(
        state_store
    )
    funding = restored.get_session_funding_account(session["session_id"])
    forced_operations = _ledger_operation_count(restored, "SESSION_FORCED_SETTLEMENT")
    restored_session = restored_session_service.store.get_session(session["session_id"])
    restored_deposit = restored_session_service.store.get_deposit_for_session(
        session["session_id"]
    )

    assert funding.funding_state == "RELEASED"
    assert restored.wallet_q_atom_balance("wallet-endpoint") == 0
    assert restored.wallet_q_atom_balance("wallet-consumer") == 1_000
    assert restored_session.status == "closed"
    assert restored_deposit.status == "released"
    assert forced_operations == 1

    duplicate = _force_finalize_mvp_session(
        restored_client,
        endpoint=endpoint,
        session=session,
        reason="ENDPOINT_UNAVAILABLE",
        force_after="2026-07-18T12:01:00+00:00",
        now="2026-07-18T12:02:00+00:00",
    )

    assert duplicate.status_code == 409
    assert "already finalized" in duplicate.json()["error"]["message"]
    assert restored.wallet_q_atom_balance("wallet-endpoint") == 0
    assert restored.wallet_q_atom_balance("wallet-consumer") == 1_000
    assert (
        _ledger_operation_count(restored, "SESSION_FORCED_SETTLEMENT")
        == forced_operations
    )


def test_force_finalize_mvp_completed_fixed_price_pays_after_consumer_timeout() -> None:
    hypervisor, client, endpoint, session = _mvp_api_context()
    request, _ = _seed_terminal_runtime_evidence(
        hypervisor,
        endpoint=endpoint,
        session=session,
    )

    response = _force_finalize_mvp_session(
        client,
        endpoint=endpoint,
        session=session,
        reason="CONSUMER_TIMEOUT_AFTER_COMPLETED_FIXED_PRICE",
        force_after="2026-07-18T12:01:00+00:00",
        now="2026-07-18T12:01:00+00:00",
        request_id=request.request_id,
    )
    body = response.json()

    assert response.status_code == 200
    assert body["data"]["proposal"]["final_endpoint_payment_q_atoms"] == 900
    assert body["data"]["proposal"]["consumer_fee_refund_q_atoms"] == 100
    assert body["data"]["funding"]["funding_state"] == "RELEASED"
    assert body["data"]["session"]["close_reason"] == (
        "forced_consumer_timeout_after_completed_fixed_price"
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
    hypervisor.runtime_binding_endpoint_admission = (  # type: ignore[attr-defined]
        lambda runtime_binding_id, endpoint_payload=None: {
            "runtime_binding_id": runtime_binding_id,
            "ready": True,
            "blockers": [],
            "warnings": [],
            "dimensions": {},
        }
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
    assert body["data"]["endpoint"]["runtime_binding_id"] == "rtb-1"


def test_create_endpoint_route_rejects_runtime_binding_admission_blocker() -> None:
    hypervisor = HypervisorService(queue=InMemoryTaskQueue(), scheduler=Scheduler())
    hypervisor.runtime_binding_endpoint_admission = (  # type: ignore[attr-defined]
        lambda runtime_binding_id, endpoint_payload=None: {
            "runtime_binding_id": runtime_binding_id,
            "ready": False,
            "blockers": [
                {
                    "code": "RUNTIME_BINDING_NOT_READY",
                    "message": "Runtime Binding must be ready before creating an Endpoint draft.",
                }
            ],
            "warnings": [],
            "dimensions": {
                "runtime_binding": {
                    "ready": False,
                    "status": "disabled",
                    "operational_state": "STOPPED",
                }
            },
        }
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

    assert response.status_code == 409
    assert body["error"]["code"] == "endpoint_admission_blocked"
    assert body["error"]["details"]["blockers"][0]["code"] == (
        "RUNTIME_BINDING_NOT_READY"
    )


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
