from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.service import (
    ConsensusMode,
    ConsensusService,
    ConsensusServiceConfig,
)
from aidn_hypervisor.domain.models import NodeCapacity, TaskRequest
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.main import build_app
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.runtime_protocol.models import (
    RuntimeExecuteRequest,
    RuntimeRequestRecord,
    RuntimeUsageReport,
    canonical_hash,
)
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.session_failure.models import RecoveryWindowConfig
from aidn_hypervisor.session_failure.service import SessionFailureHandler
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore


class _Transport:
    def broadcast_tx_sync(self, transaction: bytes, *, timeout_seconds: int) -> dict:
        del timeout_seconds
        return {
            "result": {
                "code": 0,
                "hash": hashlib.sha256(transaction).hexdigest().upper(),
            }
        }


class _FinalitySource:
    def __init__(self, chain_id: str) -> None:
        self.chain_id = chain_id
        self.evidence: dict[str, ConsensusFinalityEvidence] = {}

    def finality_evidence(self, operation_id: str):
        return self.evidence.get(operation_id)

    def finalize(self, operation_id: str, height: int) -> None:
        self.evidence[operation_id] = ConsensusFinalityEvidence(
            operation_id=operation_id,
            chain_id=self.chain_id,
            block_height=height,
            block_id=f"block-{height}",
            app_hash=f"app-{height}",
            commit_hash=f"commit-{height}",
            finalized_at="2030-01-01T00:00:00Z",
            verifier_id="test-finality-source",
        )


def _context(*, open_session: bool = True) -> tuple[
    HypervisorService,
    TestClient,
    dict,
    dict,
    ConsensusService,
    _FinalitySource,
]:
    chain_id = "aidn-testnet-1"
    source = _FinalitySource(chain_id)
    consensus = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.NON_VALIDATOR,
            chain_id=chain_id,
        ),
        submission_transport=_Transport(),
    )
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    hypervisor = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=2048)),
        plugins=plugins,
        registry_service=RegistryService(),
        consensus_service=consensus,
        consensus_finality_source=source,
    )
    endpoint_service = EndpointService(EndpointStore())
    failure_handler = SessionFailureHandler(
        recovery_config=RecoveryWindowConfig(
            consumer_reconnect_timeout_seconds=60,
            provider_reconnect_timeout_seconds=60,
        )
    )
    session_service = SessionService(
        SessionStore(),
        failure_handler=failure_handler,
        recovery_config=failure_handler.recovery_config,
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            session_service=session_service,
            consensus_service=consensus,
        )
    )
    endpoint = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-endpoint",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Consensus fixed price endpoint",
            "model_class": "llm.chat",
        },
    ).json()["data"]["endpoint"]
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer", amount_q_atoms=1_000)
    session = None
    if open_session:
        session = client.post(
            f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions",
            json={
                "client_wallet": "wallet-consumer",
                "deposit_q_atoms": 1_000,
                "fixed_price_q_atoms": 900,
                "network_fee_reserve_q_atoms": 100,
            },
        ).json()["data"]["session"]
    return hypervisor, client, endpoint, session, consensus, source


def _force(client: TestClient, endpoint: dict, session: dict):
    return client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions/"
        f"{session['session_id']}/force-finalize",
        json={
            "reason": "ENDPOINT_UNAVAILABLE",
            "force_after": "2026-07-18T12:01:00+00:00",
            "now": "2026-07-18T12:01:00+00:00",
            "consensus_sender_sequence": 1,
            "consensus_lock_signatures": ["sig-lock"],
            "consensus_failure_signatures": ["sig-failure"],
            "consensus_initiator_wallet": "wallet-endpoint",
            "consensus_initiator_signature": "sig-force",
            "consensus_observed_at": "2026-07-18T12:01:00+00:00",
        },
    )


def _seed_cooperative_runtime_evidence(
    hypervisor: HypervisorService,
    *,
    endpoint: dict,
    session: dict,
    request_id: str = "request-consensus-cooperative",
) -> str:
    payload = {"prompt": "consensus settlement"}
    request = RuntimeExecuteRequest(
        runtime_id="runtime-consensus",
        runtime_generation=1,
        runtime_configuration_hash="runtime-consensus-config",
        route_generation=1,
        endpoint_id=endpoint["endpoint_id"],
        endpoint_configuration_hash=endpoint["configuration_hash"],
        session_id=session["session_id"],
        session_contract_hash=session["session_contract_hash"],
        request_id=request_id,
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="capability-definition-consensus",
        request_payload_hash=canonical_hash(payload),
        request_payload=payload,
        request_charge_ceiling=0.0009,
        accounting_contract_hash=session["accounting_contract_hash"],
        idempotency_key=f"idempotency-{request_id}",
        request_deadline="2030-01-01T00:30:00+00:00",
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
        created_at="2030-01-01T00:00:05Z",
        runtime_signature="runtime-consensus-signature",
    )
    hypervisor.runtime_protocol_store.requests[request_id] = RuntimeRequestRecord(
        request_id=request_id,
        runtime_id=request.runtime_id,
        runtime_generation=request.runtime_generation,
        route_generation=request.route_generation,
        request_hash=request.semantic_hash(),
        request=request,
        request_state="COMPLETED",
        admission_state="ACCEPTED",
        accepted_at="2030-01-01T00:00:01Z",
        terminal_result_hash="sha256:consensus-result",
        terminal_final_usage_report_id=final_usage.usage_report_id,
        updated_at="2030-01-01T00:00:05Z",
    )
    hypervisor.runtime_protocol_store.usage_reports[final_usage.usage_report_id] = (
        final_usage
    )
    return request_id


def test_consensus_cooperative_finalize_persists_pending_envelopes_and_waits_for_finality():
    hypervisor, client, endpoint, session, consensus, source = _context()
    request_id = _seed_cooperative_runtime_evidence(
        hypervisor,
        endpoint=endpoint,
        session=session,
    )
    finalize_path = (
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions/"
        f"{session['session_id']}/finalize"
    )

    first = client.post(
        finalize_path,
        json={
            "request_id": request_id,
            "consumer_signature": "consumer-cooperative-signature",
            "accepted_at": "2030-01-01T00:01:00Z",
        },
    )
    assert first.status_code == 200
    assert first.json()["data"]["status"] == "CONSENSUS_PENDING"
    assert first.json()["data"]["consensus"]["blocked_on"] == "ready"
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 0
    assert len(hypervisor._pending_consensus_envelopes) == 1

    ready_id = first.json()["data"]["consensus"]["canonical_operation_ids"]["ready"]
    source.finalize(ready_id, height=40)
    second = client.post(
        finalize_path,
        json={
            "request_id": request_id,
            "consumer_signature": "consumer-cooperative-signature",
            "accepted_at": "2030-01-01T00:02:00Z",
        },
    )
    assert second.status_code == 200
    assert second.json()["data"]["consensus"]["blocked_on"] == "proposal"
    assert second.json()["data"]["consensus"]["canonical_operation_ids"]["ready"] == ready_id
    proposal_id = second.json()["data"]["consensus"]["canonical_operation_ids"]["proposal"]
    source.finalize(proposal_id, height=41)

    third = client.post(
        finalize_path,
        json={
            "request_id": request_id,
            "consumer_signature": "consumer-cooperative-signature",
            "accepted_at": "2030-01-01T00:03:00Z",
        },
    )
    assert third.status_code == 200
    assert third.json()["data"]["consensus"]["blocked_on"] == "acceptance"
    acceptance_id = third.json()["data"]["consensus"]["canonical_operation_ids"]["acceptance"]
    source.finalize(acceptance_id, height=42)

    fourth = client.post(
        finalize_path,
        json={
            "request_id": request_id,
            "consumer_signature": "consumer-cooperative-signature",
            "accepted_at": "2030-01-01T00:04:00Z",
        },
    )
    assert fourth.status_code == 200
    assert fourth.json()["data"]["consensus"]["blocked_on"] == "finalize"
    finalize_id = fourth.json()["data"]["consensus"]["canonical_operation_ids"]["finalize"]
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 0
    source.finalize(finalize_id, height=43)

    final = client.post(
        finalize_path,
        json={
            "request_id": request_id,
            "consumer_signature": "consumer-cooperative-signature",
            "accepted_at": "2030-01-01T00:05:00Z",
        },
    )
    assert final.status_code == 200
    assert final.json()["data"]["status"] == "FINALIZED"
    assert final.json()["data"]["session"]["status"] == "closed"
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 900
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 100
    assert hypervisor._pending_consensus_envelopes == {}
    assert consensus.get_submission(finalize_id).status.value == "finalized"


def test_consensus_force_finalize_applies_local_economics_only_after_finality():
    hypervisor, client, endpoint, session, consensus, source = _context()

    first = _force(client, endpoint, session)
    assert first.status_code == 202
    assert first.json()["data"]["status"] == "CONSENSUS_PENDING"
    assert first.json()["data"]["consensus"]["blocked_on"] == "lock"
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 0
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 0
    assert hypervisor.session_service.store.get_session(session["session_id"]).status == "active"

    lock_id = first.json()["data"]["consensus"]["canonical_operation_ids"]["lock"]
    source.finalize(lock_id, 10)
    second = _force(client, endpoint, session)
    assert second.status_code == 202
    assert second.json()["data"]["consensus"]["blocked_on"] == "failure"
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 0

    failure_id = second.json()["data"]["consensus"]["canonical_operation_ids"]["failure"]
    source.finalize(failure_id, 11)
    third = _force(client, endpoint, session)
    assert third.status_code == 202
    assert third.json()["data"]["consensus"]["blocked_on"] == "force"
    assert hypervisor.session_service.store.get_session(session["session_id"]).status == "active"

    force_id = third.json()["data"]["consensus"]["canonical_operation_ids"]["force"]
    source.finalize(force_id, 12)
    final = _force(client, endpoint, session)
    assert final.status_code == 200
    assert final.json()["data"]["status"] == "FINALIZED"
    assert final.json()["data"]["session"]["status"] == "force_settled"
    assert hypervisor.wallet_q_atom_balance("wallet-consumer") == 1_000
    assert hypervisor.wallet_q_atom_balance("wallet-endpoint") == 0
    assert consensus.get_submission(force_id).status.value == "finalized"


def test_validator_hypervisor_requires_canonical_open_authentication():
    hypervisor, client, endpoint, _session, _consensus, _source = _context(
        open_session=False
    )
    hypervisor.consensus_service.config.mode = ConsensusMode.VALIDATOR
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer-2", amount_q_atoms=1_000)

    response = client.post(
        f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions",
        json={
            "client_wallet": "wallet-consumer-2",
            "deposit_q_atoms": 1_000,
            "fixed_price_q_atoms": 900,
            "network_fee_reserve_q_atoms": 100,
        },
    )

    assert response.status_code == 409
    assert "canonical sender sequence" in response.json()["error"]["message"]
    assert hypervisor.wallet_q_atom_balance("wallet-consumer-2") == 1_000
    assert hypervisor.session_service.store.list_sessions() == []


def test_validator_http_writes_are_rejected_outside_consensus_session_open():
    hypervisor, client, _endpoint, _session, _consensus, _source = _context(
        open_session=False
    )
    hypervisor.consensus_service.config.mode = ConsensusMode.VALIDATOR
    operations_before = hypervisor.ledger_operation_service.snapshot_operations()

    response = client.post(
        "/operators/wallet/bootstrap/create",
        json={"label": "must use consensus"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "validator_consensus_required"
    assert hypervisor.owner_wallet_state()["configured"] is False
    assert hypervisor.ledger_operation_service.snapshot_operations() == operations_before
    assert client.get("/operators/wallet/bootstrap").status_code == 200


def test_validator_force_projections_do_not_enter_canonical_operation_log():
    hypervisor, client, endpoint, session, _consensus, _source = _context()
    hypervisor.consensus_service.config.mode = ConsensusMode.VALIDATOR
    operations_before = hypervisor.ledger_operation_service.snapshot_operations()

    response = _force(client, endpoint, session)

    assert response.status_code == 202
    assert response.json()["data"]["consensus"]["blocked_on"] == "lock"
    assert hypervisor.ledger_operation_service.snapshot_operations() == operations_before
    pending_types = {
        operation["operation_type"]
        for operation in hypervisor._pending_consensus_operations.values()
    }
    assert pending_types == {"SESSION_FAILURE_EVIDENCE", "SESSION_FORCE_SETTLE"}


def test_staged_consensus_operation_does_not_mutate_ledger_state() -> None:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:consumer", amount_q_atoms=25)
    before = {
        "operations": ledger.snapshot_operations(),
        "wallet_sequences": ledger.snapshot_wallet_sequences(),
        "settlement_state": ledger.snapshot_settlement_state(),
        "consensus_state": ledger.snapshot_consensus_state(),
    }

    staged = ledger.stage_operation(
        operation_type="SESSION_FAILURE_EVIDENCE",
        origin_type="protocol",
        fee_class="protocol_sponsored",
        initiator_id="session:staged",
        payload={"session_id": "session:staged", "failure_class": "ENDPOINT_FAILURE"},
        evidence_references=[],
        signatures=[],
    )

    assert staged["operation_type"] == "SESSION_FAILURE_EVIDENCE"
    assert before == {
        "operations": ledger.snapshot_operations(),
        "wallet_sequences": ledger.snapshot_wallet_sequences(),
        "settlement_state": ledger.snapshot_settlement_state(),
        "consensus_state": ledger.snapshot_consensus_state(),
    }


def test_validator_session_open_resumes_after_canonical_funding_finality():
    hypervisor, client, endpoint, _session, consensus, source = _context(
        open_session=False
    )
    hypervisor.consensus_service.config.mode = ConsensusMode.VALIDATOR
    hypervisor.credit_wallet_q_atoms(wallet_id="wallet-consumer-2", amount_q_atoms=1_000)

    open_path = f"/api/v1/endpoints/{endpoint['endpoint_id']}/mvp-sessions"
    open_payload = {
        "client_wallet": "wallet-consumer-2",
        "deposit_q_atoms": 1_000,
        "fixed_price_q_atoms": 900,
        "network_fee_reserve_q_atoms": 100,
        "consensus_sender_sequence": 2,
        "consensus_lock_signatures": ["sig-lock"],
    }
    pending = client.post(open_path, json=open_payload)

    assert pending.status_code == 202
    pending_payload = pending.json()["data"]
    assert pending_payload["status"] == "CONSENSUS_PENDING"
    pending_session = pending_payload["session"]
    assert pending_session["canonical_funding_status"] == "PENDING_FINALITY"
    assert hypervisor.wallet_q_atom_balance("wallet-consumer-2") == 1_000

    with pytest.raises(ValueError, match="awaiting canonical funding finality"):
        hypervisor._validate_task_session(
            hypervisor.endpoint_service.get_endpoint(endpoint["endpoint_id"]).endpoint,
            TaskRequest(
                task_type="chat",
                payload={"prompt": "blocked until lock finality"},
                constraints={"session_id": pending_session["session_id"]},
            ),
        )

    stored = hypervisor.session_service.store.get_session(pending_session["session_id"])
    envelope = LedgerOperationEnvelope.model_validate(
        stored.canonical_funding_submission["envelope"]
    )
    assert envelope.operation_id == stored.canonical_funding_operation_id
    assert not any(
        operation["operation_id"] == envelope.operation_id
        for operation in hypervisor.ledger_operation_service.snapshot_operations()
    )

    hypervisor.ledger_operation_service.apply_consensus_session_escrow_lock(envelope)
    source.finalize(envelope.operation_id, 20)

    resumed = client.post(
        open_path,
        json={
            **{key: value for key, value in open_payload.items() if not key.startswith("consensus_")},
            "session_id": pending_session["session_id"],
        },
    )

    assert resumed.status_code == 201
    resumed_payload = resumed.json()["data"]
    assert resumed_payload["session"]["canonical_funding_status"] == "FINALIZED"
    assert resumed_payload["consensus"]["status"] == "finalized"
    assert resumed_payload["consensus"]["canonical_operation_id"] == envelope.operation_id
    assert hypervisor.wallet_q_atom_balance("wallet-consumer-2") == 0
    assert (
        hypervisor.get_session_funding_account(pending_session["session_id"])
        .funding_state
        == "LOCKED"
    )

    hypervisor._validate_task_session(
        hypervisor.endpoint_service.get_endpoint(endpoint["endpoint_id"]).endpoint,
        TaskRequest(
            task_type="chat",
            payload={"prompt": "funding is final"},
            constraints={"session_id": pending_session["session_id"]},
        ),
    )
    assert consensus.get_submission(envelope.operation_id).status.value == "finalized"
