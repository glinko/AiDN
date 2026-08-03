from __future__ import annotations

import hashlib
from typing import Any

import pytest

from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.service import (
    ConsensusMode,
    ConsensusService,
    ConsensusServiceConfig,
)
from aidn_hypervisor.consensus.settlement_orchestration import (
    ConsensusSettlementOperationOrchestrator,
)
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.settlement.models import (
    RequestSettlementInput,
    SessionFundingAccount,
    SessionSettlementAcceptance,
    SettlementAccountingTerms,
    SettlementChargeComponent,
)
from aidn_hypervisor.settlement.service import SettlementEngine


class _SubmissionTransport:
    def broadcast_tx_sync(self, transaction: bytes, *, timeout_seconds: int) -> dict[str, Any]:
        del timeout_seconds
        return {
            "result": {
                "code": 0,
                "hash": hashlib.sha256(transaction).hexdigest().upper(),
            }
        }


class _DuplicateSubmissionTransport:
    def broadcast_tx_sync(self, transaction: bytes, *, timeout_seconds: int) -> dict[str, Any]:
        del transaction, timeout_seconds
        return {"result": {"code": 1, "log": "transaction already exists"}}


class _FinalitySource:
    def __init__(self, chain_id: str) -> None:
        self.chain_id = chain_id
        self.evidence: dict[str, ConsensusFinalityEvidence] = {}

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        return self.evidence.get(operation_id)

    def finalize(self, operation_id: str, *, height: int) -> None:
        self.evidence[operation_id] = ConsensusFinalityEvidence(
            operation_id=operation_id,
            chain_id=self.chain_id,
            block_height=height,
            block_id=f"block-{height}",
            app_hash=f"app-{height}",
            commit_hash=f"commit-{height}",
            finalized_at="2030-01-01T00:00:00Z",
            verifier_id="test-quorum",
        )


class _PendingEnvelopeStore:
    """Small durable-store substitute for process-restart orchestration tests."""

    def __init__(self, state: dict[str, dict] | None = None) -> None:
        self._envelopes = {
            operation_id: dict(payload)
            for operation_id, payload in (state or {}).items()
        }

    def stage_pending_consensus_envelope(self, envelope: LedgerOperationEnvelope) -> dict:
        payload = envelope.model_dump(mode="json")
        existing = self._envelopes.get(envelope.operation_id)
        if existing is not None and existing != payload:
            raise ValueError("conflicting pending consensus envelope")
        self._envelopes[envelope.operation_id] = payload
        return dict(payload)

    def find_pending_consensus_envelope(self, *, operation_type: str, predicate):
        for payload in reversed(list(self._envelopes.values())):
            envelope = LedgerOperationEnvelope.model_validate(payload)
            if envelope.operation_type == operation_type and predicate(envelope):
                return envelope
        return None

    def list_pending_consensus_envelopes(self) -> list[LedgerOperationEnvelope]:
        return [
            LedgerOperationEnvelope.model_validate(payload)
            for payload in self._envelopes.values()
        ]

    def discard_pending_consensus_envelopes(self, *operation_ids: str) -> None:
        for operation_id in operation_ids:
            self._envelopes.pop(operation_id, None)

    def snapshot(self) -> dict[str, dict]:
        return {operation_id: dict(payload) for operation_id, payload in self._envelopes.items()}


def _fixture() -> tuple[
    LedgerOperationService,
    ConsensusSettlementOperationOrchestrator,
    Any,
    SessionSettlementAcceptance,
]:
    ledger = LedgerOperationService()
    funding = SessionFundingAccount(
        session_id="session-consensus-settlement-1",
        session_contract_hash="sha256:session-contract",
        funding_class="ESCROW_PREPAID",
        consumer_funding_account="wallet:consumer",
        endpoint_payment_beneficiary="wallet:endpoint",
        consumer_refund_beneficiary="wallet:consumer",
        total_locked_amount_q_atoms=100,
        endpoint_payment_reserve_q_atoms=100,
        network_fee_reserve_q_atoms=0,
        unsettled_payment_reserve_q_atoms=100,
        unsettled_fee_reserve_q_atoms=0,
    )
    ledger.credit_wallet_q_atoms(wallet_id="wallet:consumer", amount_q_atoms=100)
    locked = ledger.lock_session_funding(funding, created_at="2030-01-01T00:00:00Z")
    request = RequestSettlementInput(
        session_id=locked.session_id,
        request_id="request-consensus-settlement-1",
        request_charge_ceiling_q_atoms=100,
        accounting_contract_hash="sha256:contract",
        terminal_state="COMPLETED",
        result_reference="sha256:result",
        final_usage_report_id="usage-1",
        final_usage_report_hash="sha256:usage-1",
        usage_sequence=1,
        dimensions=[],
    )
    terms = SettlementAccountingTerms(
        accounting_contract_hash="sha256:contract",
        accounting_mode="fixed_price",
        components=[
            SettlementChargeComponent(
                component_id="fixed",
                fixed_amount_q_atoms=100,
            )
        ],
    )
    evaluation = SettlementEngine().evaluate_session(
        funding=locked,
        session_contract_hash="sha256:session-contract",
        effective_terms_hash="sha256:effective-terms",
        request_inputs=[request],
        terms_by_hash={"sha256:contract": terms},
        maximum_session_charge_q_atoms=100,
        actual_network_fees_q_atoms=0,
        session_close_reference="sha256:close",
    )
    acceptance = SessionSettlementAcceptance(
        settlement_id=evaluation.proposal.settlement_id,
        session_id=evaluation.proposal.session_id,
        settlement_input_root=evaluation.proposal.settlement_input_root,
        accepted_endpoint_payment_q_atoms=100,
        accepted_consumer_refund_q_atoms=0,
        accepted_network_fees_q_atoms=0,
        consumer_signature="consumer-signature",
        accepted_at="2030-01-01T00:01:00Z",
    )
    consensus = ConsensusService(ConsensusServiceConfig(mode=ConsensusMode.DISABLED))
    return (
        ledger,
        ConsensusSettlementOperationOrchestrator(consensus, ledger),
        evaluation,
        acceptance,
    )


def test_disabled_consensus_runs_and_replays_cooperative_settlement() -> None:
    ledger, orchestrator, evaluation, acceptance = _fixture()

    first = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance,
    )
    repeated = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance,
    )

    assert first["status"] == "finalized"
    assert repeated["status"] == "finalized"
    assert set(first["canonical_operation_ids"]) == {
        "ready",
        "proposal",
        "acceptance",
        "finalize",
    }
    assert ledger.get_session_funding_account(
        evaluation.proposal.session_id
    ).funding_state == "RELEASED"
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 100
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 0
    assert [item["operation_type"] for item in ledger.list_operations()] == [
        "SESSION_ESCROW_LOCK",
        "SESSION_SETTLEMENT_READY_COMMIT",
        "SESSION_SETTLEMENT_PROPOSE",
        "SESSION_SETTLEMENT_ACCEPT",
        "SESSION_SETTLEMENT_FINALIZE",
    ]


def test_enabled_consensus_advances_only_after_verified_finality() -> None:
    ledger, _, evaluation, acceptance = _fixture()
    source = _FinalitySource("aidn-testnet-1")
    consensus = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.NON_VALIDATOR,
            chain_id="aidn-testnet-1",
        ),
        submission_transport=_SubmissionTransport(),
    )
    orchestrator = ConsensusSettlementOperationOrchestrator(
        consensus,
        ledger,
        finality_source=source,
    )

    result = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance,
    )
    assert result["status"] == "awaiting_verified_finality"
    assert result["blocked_on"] == "ready"
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 0

    source.finalize(result["canonical_operation_ids"]["ready"], height=10)
    result = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance,
    )
    assert result["blocked_on"] == "proposal"

    source.finalize(result["canonical_operation_ids"]["proposal"], height=11)
    result = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance,
    )
    assert result["blocked_on"] == "acceptance"

    source.finalize(result["canonical_operation_ids"]["acceptance"], height=12)
    result = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance,
    )
    assert result["blocked_on"] == "finalize"
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 0

    source.finalize(result["canonical_operation_ids"]["finalize"], height=13)
    result = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance,
    )

    assert result["status"] == "finalized"
    assert result["blocked_on"] is None
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 100
    assert ledger.wallet_q_atom_balance("wallet:consumer") == 0


def test_acceptance_retry_reuses_canonical_signed_payload() -> None:
    ledger, _, evaluation, acceptance = _fixture()
    source = _FinalitySource("aidn-testnet-1")
    consensus = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.NON_VALIDATOR,
            chain_id="aidn-testnet-1",
        ),
        submission_transport=_SubmissionTransport(),
    )
    orchestrator = ConsensusSettlementOperationOrchestrator(
        consensus,
        ledger,
        finality_source=source,
    )

    pending = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance,
    )
    source.finalize(pending["canonical_operation_ids"]["ready"], height=20)
    pending = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance.model_copy(
            update={"accepted_at": "2030-01-01T00:02:00Z", "acceptance_hash": None}
        ),
    )
    source.finalize(pending["canonical_operation_ids"]["proposal"], height=21)
    pending = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance.model_copy(
            update={"accepted_at": "2030-01-01T00:03:00Z", "acceptance_hash": None}
        ),
    )

    assert pending["blocked_on"] == "acceptance"
    canonical_acceptance_id = pending["canonical_operation_ids"]["acceptance"]
    source.finalize(canonical_acceptance_id, height=22)
    pending = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance.model_copy(
            update={"accepted_at": "2030-01-01T00:04:00Z", "acceptance_hash": None}
        ),
    )

    assert pending["blocked_on"] == "finalize"
    assert pending["canonical_operation_ids"]["acceptance"] == canonical_acceptance_id
    source.finalize(pending["canonical_operation_ids"]["finalize"], height=23)
    final = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance.model_copy(
            update={"accepted_at": "2030-01-01T00:05:00Z", "acceptance_hash": None}
        ),
    )

    assert final["status"] == "finalized"
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 100


def test_settlement_restarts_reuse_durable_pending_envelopes() -> None:
    ledger, _, evaluation, acceptance = _fixture()
    source = _FinalitySource("aidn-testnet-1")
    pending_store = _PendingEnvelopeStore()

    def orchestrator(
        store: _PendingEnvelopeStore,
        transport: _SubmissionTransport | _DuplicateSubmissionTransport | None = None,
    ):
        consensus = ConsensusService(
            ConsensusServiceConfig(
                mode=ConsensusMode.NON_VALIDATOR,
                chain_id="aidn-testnet-1",
            ),
            submission_transport=transport or _SubmissionTransport(),
        )
        return ConsensusSettlementOperationOrchestrator(
            consensus,
            ledger,
            finality_source=source,
            pending_envelope_store=store,
        )

    first = orchestrator(pending_store).submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance,
        created_at="2030-01-01T00:00:00Z",
    )
    ready_id = first["canonical_operation_ids"]["ready"]
    source.finalize(ready_id, height=30)

    pending_store = _PendingEnvelopeStore(pending_store.snapshot())
    second = orchestrator(
        pending_store,
        transport=_DuplicateSubmissionTransport(),
    ).submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance.model_copy(
            update={"accepted_at": "2030-01-01T00:01:00Z", "acceptance_hash": None}
        ),
        created_at="2030-01-01T00:01:00Z",
    )
    assert second["blocked_on"] == "proposal"
    assert second["canonical_operation_ids"]["ready"] == ready_id
    proposal_id = second["canonical_operation_ids"]["proposal"]
    source.finalize(proposal_id, height=31)

    pending_store = _PendingEnvelopeStore(pending_store.snapshot())
    third = orchestrator(pending_store).submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance.model_copy(
            update={"accepted_at": "2030-01-01T00:02:00Z", "acceptance_hash": None}
        ),
        created_at="2030-01-01T00:02:00Z",
    )
    assert third["blocked_on"] == "acceptance"
    assert third["canonical_operation_ids"]["proposal"] == proposal_id
    acceptance_id = third["canonical_operation_ids"]["acceptance"]
    source.finalize(acceptance_id, height=32)

    pending_store = _PendingEnvelopeStore(pending_store.snapshot())
    fourth = orchestrator(pending_store).submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance.model_copy(
            update={"accepted_at": "2030-01-01T00:03:00Z", "acceptance_hash": None}
        ),
        created_at="2030-01-01T00:03:00Z",
    )
    assert fourth["blocked_on"] == "finalize"
    finalize_id = fourth["canonical_operation_ids"]["finalize"]
    source.finalize(finalize_id, height=33)

    pending_store = _PendingEnvelopeStore(pending_store.snapshot())
    final = orchestrator(pending_store).submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance.model_copy(
            update={"accepted_at": "2030-01-01T00:04:00Z", "acceptance_hash": None}
        ),
        created_at="2030-01-01T00:04:00Z",
    )

    assert final["status"] == "finalized"
    assert final["canonical_operation_ids"]["finalize"] == finalize_id
    assert pending_store.snapshot() == {}
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 100


def test_conflicting_pending_settlement_fails_closed() -> None:
    ledger, _, evaluation, acceptance = _fixture()
    source = _FinalitySource("aidn-testnet-1")
    pending_store = _PendingEnvelopeStore()
    consensus = ConsensusService(
        ConsensusServiceConfig(
            mode=ConsensusMode.NON_VALIDATOR,
            chain_id="aidn-testnet-1",
        ),
        submission_transport=_SubmissionTransport(),
    )
    orchestrator = ConsensusSettlementOperationOrchestrator(
        consensus,
        ledger,
        finality_source=source,
        pending_envelope_store=pending_store,
    )

    first = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance,
    )
    source.finalize(first["canonical_operation_ids"]["ready"], height=40)
    second = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=acceptance,
    )
    source.finalize(second["canonical_operation_ids"]["proposal"], height=41)

    changed_acceptance = acceptance.model_copy(
        update={
            "accepted_endpoint_payment_q_atoms": 99,
            "accepted_consumer_refund_q_atoms": 1,
            "acceptance_hash": None,
        }
    )
    third = orchestrator.submit_cooperative_settlement(
        evaluation=evaluation,
        acceptance=changed_acceptance,
    )
    pending_acceptance_id = third["canonical_operation_ids"]["acceptance"]
    assert third["blocked_on"] == "acceptance"

    conflicting_acceptance = changed_acceptance.model_copy(
        update={
            "accepted_endpoint_payment_q_atoms": 98,
            "accepted_consumer_refund_q_atoms": 2,
            "acceptance_hash": None,
        }
    )
    with pytest.raises(
        ValueError,
        match="conflicting pending consensus envelope for SESSION_SETTLEMENT_ACCEPT",
    ):
        orchestrator.submit_cooperative_settlement(
            evaluation=evaluation,
            acceptance=conflicting_acceptance,
        )

    assert list(pending_store.snapshot()) == [pending_acceptance_id]
    assert ledger.wallet_q_atom_balance("wallet:endpoint") == 0
