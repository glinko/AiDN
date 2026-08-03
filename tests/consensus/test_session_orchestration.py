from __future__ import annotations

import hashlib
from typing import Any

from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.consensus.service import (
    ConsensusMode,
    ConsensusService,
    ConsensusServiceConfig,
)
from aidn_hypervisor.consensus.session_orchestration import (
    ConsensusSessionOperationOrchestrator,
)
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.settlement.models import (
    AtomicSettlementTransition,
    SessionFundingAccount,
)


class _SubmissionTransport:
    def broadcast_tx_sync(self, transaction: bytes, *, timeout_seconds: int) -> dict[str, Any]:
        del timeout_seconds
        return {
            "result": {
                "code": 0,
                "hash": hashlib.sha256(transaction).hexdigest().upper(),
            }
        }


class _FinalitySource:
    def __init__(self) -> None:
        self.evidence: dict[str, ConsensusFinalityEvidence] = {}

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        return self.evidence.get(operation_id)

    def finalize(self, operation_id: str, *, height: int) -> None:
        self.evidence[operation_id] = ConsensusFinalityEvidence(
            operation_id=operation_id,
            chain_id="aidn-testnet-1",
            block_height=height,
            block_id=f"block-{height}",
            app_hash=f"app-{height}",
            commit_hash=f"commit-{height}",
            finalized_at="2030-01-01T00:00:00Z",
            verifier_id="test-quorum",
        )


def _fixture() -> tuple[
    dict[str, object],
    SessionFundingAccount,
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    ledger = LedgerOperationService()
    ledger.credit_wallet_q_atoms(wallet_id="wallet:consumer", amount_q_atoms=2_000)
    funding = SessionFundingAccount(
        session_id="session-orchestration-1",
        session_contract_hash="sha256:session-contract",
        funding_class="ESCROW_PREPAID",
        consumer_funding_account="wallet:consumer",
        endpoint_payment_beneficiary="wallet:endpoint",
        consumer_refund_beneficiary="wallet:consumer",
        total_locked_amount_q_atoms=1_100,
        endpoint_payment_reserve_q_atoms=1_000,
        network_fee_reserve_q_atoms=100,
        unsettled_payment_reserve_q_atoms=1_000,
        unsettled_fee_reserve_q_atoms=100,
    )
    ledger.lock_session_funding(funding)
    lock = ledger.snapshot_operations()[0]
    failure = ledger.commit_session_failure_evidence(
        session_id=funding.session_id,
        failure_class="ENDPOINT_FAILURE",
        failure_evidence_root="sha256:failure-evidence",
    )
    force = ledger.record_operation(
        operation_type="SESSION_FORCE_SETTLE",
        origin_type="evidence_triggered",
        fee_class="session",
        initiator_id=funding.session_id,
        fee_payer=funding.consumer_funding_account,
        payload={
            "session_id": funding.session_id,
            "failure_class": "ENDPOINT_UNAVAILABLE",
            "failure_evidence_root": "sha256:failure-evidence",
            "settlement_id": "settlement-orchestration-1",
            "requested_payment_q_atoms": 0,
            "requested_refund_q_atoms": 1_100,
        },
        evidence_references=["sha256:failure-evidence"],
        created_at="2030-01-01T00:00:00Z",
    )
    transition = AtomicSettlementTransition(
        session_id=funding.session_id,
        settlement_id="settlement-orchestration-1",
        endpoint_payment_beneficiary=funding.endpoint_payment_beneficiary,
        consumer_refund_beneficiary=funding.consumer_refund_beneficiary,
        previously_released_to_endpoint_q_atoms=0,
        previously_refunded_to_consumer_q_atoms=0,
        previously_consumed_network_fees_q_atoms=0,
        credit_endpoint_q_atoms=0,
        credit_consumer_q_atoms=1_100,
        consume_network_fees_q_atoms=0,
        retain_dispute_reserve_q_atoms=0,
        total_locked_amount_q_atoms=1_100,
    )
    return lock, funding, failure, force, transition.model_dump(mode="json")


def test_disabled_consensus_runs_the_full_failure_chain() -> None:
    lock, funding, failure, force, transition = _fixture()
    consensus = ConsensusService(ConsensusServiceConfig(mode=ConsensusMode.DISABLED))

    result = ConsensusSessionOperationOrchestrator(consensus).submit_failure_chain(
        local_lock_operation=lock,
        funding=funding,
        sender_sequence=1,
        lock_signatures=["ed25519:consumer-lock"],
        local_failure_operation=failure,
        failure_signatures=["ed25519:operator"],
        local_force_operation=force,
        initiator_wallet="wallet:consumer",
        initiator_signature="ed25519:consumer-force",
        observed_at="2030-01-01T02:00:00Z",
        transition=transition,
    )

    assert result["status"] == "finalized"
    assert set(result["canonical_operation_ids"]) == {"lock", "failure", "force"}
    assert all(item["status"] == "finalized" for item in result["submissions"].values())


def test_enabled_consensus_does_not_advance_on_admission_only() -> None:
    lock, funding, failure, force, transition = _fixture()
    consensus = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.NON_VALIDATOR,
            chain_id="aidn-testnet-1",
        ),
        submission_transport=_SubmissionTransport(),
    )
    source = _FinalitySource()
    orchestrator = ConsensusSessionOperationOrchestrator(consensus)

    result = orchestrator.submit_failure_chain(
        local_lock_operation=lock,
        funding=funding,
        sender_sequence=1,
        lock_signatures=["ed25519:consumer-lock"],
        local_failure_operation=failure,
        failure_signatures=["ed25519:operator"],
        local_force_operation=force,
        initiator_wallet="wallet:consumer",
        initiator_signature="ed25519:consumer-force",
        observed_at="2030-01-01T02:00:00Z",
        transition=transition,
    )
    assert result["status"] == "awaiting_verified_finality"
    assert result["blocked_on"] == "lock"
    assert set(result["canonical_operation_ids"]) == {"lock"}

    lock_id = result["canonical_operation_ids"]["lock"]
    source.finalize(lock_id, height=10)
    orchestrator = ConsensusSessionOperationOrchestrator(
        consensus,
        finality_source=source,
    )
    result = orchestrator.submit_failure_chain(
        local_lock_operation=lock,
        funding=funding,
        sender_sequence=1,
        lock_signatures=["ed25519:consumer-lock"],
        local_failure_operation=failure,
        failure_signatures=["ed25519:operator"],
        local_force_operation=force,
        initiator_wallet="wallet:consumer",
        initiator_signature="ed25519:consumer-force",
        observed_at="2030-01-01T02:00:00Z",
        transition=transition,
    )
    assert result["status"] == "awaiting_verified_finality"
    assert result["blocked_on"] == "failure"

    failure_id = result["canonical_operation_ids"]["failure"]
    source.finalize(failure_id, height=11)
    result = orchestrator.submit_failure_chain(
        local_lock_operation=lock,
        funding=funding,
        sender_sequence=1,
        lock_signatures=["ed25519:consumer-lock"],
        local_failure_operation=failure,
        failure_signatures=["ed25519:operator"],
        local_force_operation=force,
        initiator_wallet="wallet:consumer",
        initiator_signature="ed25519:consumer-force",
        observed_at="2030-01-01T02:00:00Z",
        transition=transition,
    )
    assert result["status"] == "awaiting_verified_finality"
    assert result["blocked_on"] == "force"

    force_id = result["canonical_operation_ids"]["force"]
    source.finalize(force_id, height=12)
    result = orchestrator.submit_failure_chain(
        local_lock_operation=lock,
        funding=funding,
        sender_sequence=1,
        lock_signatures=["ed25519:consumer-lock"],
        local_failure_operation=failure,
        failure_signatures=["ed25519:operator"],
        local_force_operation=force,
        initiator_wallet="wallet:consumer",
        initiator_signature="ed25519:consumer-force",
        observed_at="2030-01-01T02:00:00Z",
        transition=transition,
    )
    assert result["status"] == "finalized"
    assert result["blocked_on"] is None
