"""Canonical cooperative Settlement orchestration.

This module is the network boundary for ordinary cooperative Settlement.  A
local Hypervisor may evaluate a Settlement, but it must submit the immutable
readiness, proposal, acceptance, and finalization envelopes in order and wait
for verified finality before applying any missing local projection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from aidn_hypervisor.consensus.cometbft import cometbft_transaction_hash
from aidn_hypervisor.consensus.finality import ConsensusFinalitySource
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.projection import (
    build_session_settlement_accept_envelope,
    build_session_settlement_finalize_envelope,
    build_session_settlement_propose_envelope,
    build_session_settlement_ready_envelope,
)
from aidn_hypervisor.consensus.service import (
    ConsensusService,
    SubmissionRecord,
    SubmissionStatus,
)
from aidn_hypervisor.settlement.models import (
    SessionFundingAccount,
    SessionSettlementAcceptance,
    SessionSettlementProposal,
    SettlementEvaluation,
    SettlementReadyCommitment,
)


def _submission_dict(record: SubmissionRecord) -> dict:
    return {
        "operation_id": record.operation_id,
        "status": record.status.value,
        "submitted_at": record.submitted_at,
        "admitted_at": record.admitted_at,
        "included_at": record.included_at,
        "finalized_at": record.finalized_at,
        "block_height": record.block_height,
        "transaction_hash": record.transaction_hash,
        "retry_count": record.retry_count,
        "error": record.error,
    }


@dataclass(frozen=True)
class ConsensusSettlementResult:
    """Serializable progress of one ordered cooperative Settlement."""

    status: str
    blocked_on: str | None
    canonical_operation_ids: dict[str, str]
    submissions: dict[str, dict]

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "blocked_on": self.blocked_on,
            "canonical_operation_ids": dict(self.canonical_operation_ids),
            "submissions": {
                stage: dict(record) for stage, record in self.submissions.items()
            },
        }


class ConsensusSettlementOperationOrchestrator:
    """Submit and locally reconcile the canonical cooperative Settlement chain."""

    def __init__(
        self,
        consensus_service: ConsensusService,
        ledger_service,
        *,
        finality_source: ConsensusFinalitySource | None = None,
        pending_envelope_store=None,
    ) -> None:
        self._consensus = consensus_service
        self._ledger = ledger_service
        self._finality_source = finality_source
        self._pending_envelope_store = pending_envelope_store

    def submit_cooperative_settlement(
        self,
        *,
        evaluation: SettlementEvaluation,
        acceptance: SessionSettlementAcceptance,
        created_at: str | None = None,
        signatures: Sequence[str] | None = None,
    ) -> dict:
        """Advance Settlement as far as verified finality permits.

        The method is safe to call repeatedly.  It reuses submitted envelopes
        by semantic identity and applies a canonical envelope locally only if
        the validator/observer has not already projected it through ABCI.
        """
        proposal = SessionSettlementProposal.model_validate(evaluation.proposal)
        typed_acceptance = SessionSettlementAcceptance.model_validate(acceptance)
        if (
            typed_acceptance.settlement_id != proposal.settlement_id
            or typed_acceptance.session_id != proposal.session_id
            or typed_acceptance.settlement_input_root != proposal.settlement_input_root
        ):
            raise ValueError("Settlement acceptance does not match proposal")

        if (
            self._ledger.get_settlement_transition_hash(proposal.settlement_id)
            == evaluation.transition.transition_hash
        ):
            return ConsensusSettlementResult(
                status="finalized",
                blocked_on=None,
                canonical_operation_ids=self._existing_operation_ids(
                    proposal=proposal,
                    acceptance=typed_acceptance,
                    transition_hash=evaluation.transition.transition_hash,
                ),
                submissions={},
            ).as_dict()

        funding = self._ledger.get_session_funding_account(proposal.session_id)
        funding = SessionFundingAccount.model_validate(funding)
        predecessor = self._ledger.get_funding_predecessor_operation(
            proposal.session_id
        )
        if predecessor is None:
            raise ValueError("canonical Settlement requires a Funding predecessor")
        predecessor_id = self._required_operation_id(predecessor, "Funding predecessor")
        settlement_time = created_at or typed_acceptance.accepted_at
        authorization_signatures = list(signatures or [typed_acceptance.consumer_signature])
        if typed_acceptance.consumer_signature not in authorization_signatures:
            authorization_signatures.append(typed_acceptance.consumer_signature)

        ready = self._ready_commitment(
            evaluation=evaluation,
            funding=funding,
            ready_at=settlement_time,
        )
        ready_envelope = self._resolve_envelope(
            "SESSION_SETTLEMENT_READY_COMMIT",
            predicate=lambda item: (
                item.payload.get("session_id") == proposal.session_id
                and isinstance(item.payload.get("ready"), dict)
                and self._readiness_matches_retry(item.payload["ready"], ready)
            ),
            conflict_predicate=lambda item: item.initiator_id == proposal.session_id,
            builder=lambda: build_session_settlement_ready_envelope(
                ready=ready,
                funding_predecessor_operation_id=predecessor_id,
                fee_payer=funding.consumer_funding_account,
                created_at=settlement_time,
                signatures=authorization_signatures,
            ),
        )

        canonical_ids: dict[str, str] = {"ready": ready_envelope.operation_id}
        submissions: dict[str, dict] = {}
        ready_record, ready_final = self._submit_and_reconcile(ready_envelope)
        submissions["ready"] = _submission_dict(ready_record)
        if not ready_final:
            return ConsensusSettlementResult(
                status=self._blocked_status(ready_record),
                blocked_on="ready",
                canonical_operation_ids=canonical_ids,
                submissions=submissions,
            ).as_dict()
        self._apply_if_missing(
            ready_envelope,
            self._ledger.apply_consensus_settlement_ready_commit,
        )

        proposal_envelope = self._resolve_envelope(
            "SESSION_SETTLEMENT_PROPOSE",
            predicate=lambda item: self._proposal_matches_retry(
                item.payload, proposal
            ),
            conflict_predicate=lambda item: item.initiator_id == proposal.session_id,
            builder=lambda: build_session_settlement_propose_envelope(
                proposal=proposal,
                funding=funding,
                funding_predecessor_operation_id=predecessor_id,
                settlement_ready_operation_id=ready_envelope.operation_id,
                created_at=settlement_time,
                signatures=authorization_signatures,
            ),
        )
        canonical_ids["proposal"] = proposal_envelope.operation_id
        proposal_record, proposal_final = self._submit_and_reconcile(proposal_envelope)
        submissions["proposal"] = _submission_dict(proposal_record)
        if not proposal_final:
            return ConsensusSettlementResult(
                status=self._blocked_status(proposal_record),
                blocked_on="proposal",
                canonical_operation_ids=canonical_ids,
                submissions=submissions,
            ).as_dict()
        self._apply_if_missing(
            proposal_envelope,
            self._ledger.apply_consensus_settlement_propose,
        )

        acceptance_envelope = self._resolve_envelope(
            "SESSION_SETTLEMENT_ACCEPT",
            predicate=lambda item: (
                isinstance(item.payload.get("acceptance"), dict)
                and self._acceptance_matches_retry(
                    item.payload["acceptance"], typed_acceptance
                )
            ),
            conflict_predicate=lambda item: item.initiator_id == proposal.session_id,
            builder=lambda: build_session_settlement_accept_envelope(
                acceptance=typed_acceptance,
                proposal_operation_id=proposal_envelope.operation_id,
                consumer_wallet=funding.consumer_funding_account,
                created_at=typed_acceptance.accepted_at,
                signatures=authorization_signatures,
            ),
        )
        canonical_ids["acceptance"] = acceptance_envelope.operation_id
        acceptance_record, acceptance_final = self._submit_and_reconcile(
            acceptance_envelope
        )
        submissions["acceptance"] = _submission_dict(acceptance_record)
        if not acceptance_final:
            return ConsensusSettlementResult(
                status=self._blocked_status(acceptance_record),
                blocked_on="acceptance",
                canonical_operation_ids=canonical_ids,
                submissions=submissions,
            ).as_dict()
        self._apply_if_missing(
            acceptance_envelope,
            self._ledger.apply_consensus_settlement_accept,
        )
        # A reconnect may rebuild the caller's acceptance with a new
        # accepted_at.  Once an acceptance envelope exists, its signed
        # payload is the canonical object that finalization must reference.
        canonical_acceptance_payload = acceptance_envelope.payload.get("acceptance")
        if not isinstance(canonical_acceptance_payload, dict):
            raise ValueError("Settlement acceptance envelope is incomplete")
        typed_acceptance = SessionSettlementAcceptance.model_validate(
            canonical_acceptance_payload
        )

        finalize_envelope = self._resolve_envelope(
            "SESSION_SETTLEMENT_FINALIZE",
            predicate=lambda item: (
                isinstance(item.payload.get("transition"), dict)
                and item.payload["transition"].get("transition_hash")
                == evaluation.transition.transition_hash
            ),
            conflict_predicate=lambda item: item.initiator_id == proposal.session_id,
            builder=lambda: build_session_settlement_finalize_envelope(
                proposal=proposal,
                acceptance=typed_acceptance,
                transition=evaluation.transition,
                proposal_operation_id=proposal_envelope.operation_id,
                acceptance_operation_id=acceptance_envelope.operation_id,
                consumer_wallet=funding.consumer_funding_account,
                created_at=settlement_time,
                signatures=authorization_signatures,
            ),
        )
        canonical_ids["finalize"] = finalize_envelope.operation_id
        finalize_record, finalize_final = self._submit_and_reconcile(finalize_envelope)
        submissions["finalize"] = _submission_dict(finalize_record)
        if not finalize_final:
            return ConsensusSettlementResult(
                status=self._blocked_status(finalize_record),
                blocked_on="finalize",
                canonical_operation_ids=canonical_ids,
                submissions=submissions,
            ).as_dict()
        self._apply_if_missing(
            finalize_envelope,
            self._ledger.apply_consensus_settlement_finalize,
        )
        return ConsensusSettlementResult(
            status="finalized",
            blocked_on=None,
            canonical_operation_ids=canonical_ids,
            submissions=submissions,
        ).as_dict()

    def _ready_commitment(
        self,
        *,
        evaluation: SettlementEvaluation,
        funding: SessionFundingAccount,
        ready_at: str,
    ) -> SettlementReadyCommitment:
        current = self._ledger.find_settlement_ready_commitment(funding.session_id)
        candidate = SettlementReadyCommitment(
            session_id=evaluation.input_set.session_id,
            settlement_sequence=evaluation.proposal.settlement_sequence,
            session_contract_hash=evaluation.input_set.session_contract_hash,
            effective_terms_hash=evaluation.input_set.effective_terms_hash,
            funding_state_reference=evaluation.input_set.funding_state_reference,
            endpoint_payment_beneficiary=evaluation.input_set.endpoint_payment_beneficiary,
            consumer_refund_beneficiary=evaluation.input_set.consumer_refund_beneficiary,
            request_settlement_root=evaluation.input_set.request_settlement_root,
            usage_chain_root=evaluation.input_set.usage_chain_root,
            checkpoint_root=evaluation.input_set.checkpoint_root,
            settlement_input_root=evaluation.input_set.settlement_input_root,
            session_close_reference=evaluation.input_set.session_close_reference,
            ready_at=current.ready_at if current is not None else ready_at,
        )
        if current is not None and current != candidate:
            raise ValueError("conflicting Settlement readiness commitment")
        if candidate.session_id != funding.session_id:
            raise ValueError("Settlement readiness and funding sessions differ")
        return candidate

    def _resolve_envelope(
        self,
        operation_type: str,
        *,
        predicate,
        conflict_predicate=None,
        builder,
    ) -> LedgerOperationEnvelope:
        existing = self._find_local_envelope(operation_type, predicate)
        if existing is not None:
            return existing
        if self._pending_envelope_store is not None:
            existing = self._pending_envelope_store.find_pending_consensus_envelope(
                operation_type=operation_type,
                predicate=predicate,
            )
            if existing is not None:
                return existing
            if conflict_predicate is not None:
                list_pending = getattr(
                    self._pending_envelope_store,
                    "list_pending_consensus_envelopes",
                    None,
                )
                if list_pending is not None:
                    for pending in list_pending():
                        if (
                            pending.operation_type == operation_type
                            and conflict_predicate(pending)
                        ):
                            raise ValueError(
                                "conflicting pending consensus envelope for "
                                f"{operation_type}: {pending.operation_id}"
                            )
        existing = self._consensus.find_submitted_envelope(
            operation_type,
            predicate=predicate,
        )
        return existing if existing is not None else builder()

    def _find_local_envelope(self, operation_type: str, predicate):
        for operation in reversed(self._ledger.snapshot_operations()):
            if operation.get("operation_type") != operation_type:
                continue
            try:
                envelope = LedgerOperationEnvelope.model_validate(operation)
            except ValueError:
                continue
            if predicate(envelope):
                return envelope
        return None

    @staticmethod
    def _acceptance_matches_retry(
        payload: Mapping[str, object],
        acceptance: SessionSettlementAcceptance,
    ) -> bool:
        """Match a retry without making accepted_at part of semantic identity."""
        return all(
            payload.get(field_name) == expected
            for field_name, expected in {
                "settlement_id": acceptance.settlement_id,
                "session_id": acceptance.session_id,
                "settlement_input_root": acceptance.settlement_input_root,
                "accepted_endpoint_payment_q_atoms": (
                    acceptance.accepted_endpoint_payment_q_atoms
                ),
                "accepted_consumer_refund_q_atoms": (
                    acceptance.accepted_consumer_refund_q_atoms
                ),
                "accepted_network_fees_q_atoms": (
                    acceptance.accepted_network_fees_q_atoms
                ),
                "consumer_signature": acceptance.consumer_signature,
            }.items()
        )

    @staticmethod
    def _readiness_matches_retry(
        payload: Mapping[str, object],
        ready: SettlementReadyCommitment,
    ) -> bool:
        """Match readiness retries without making creation time identity-bearing."""
        comparable = ready.model_dump(
            mode="json",
            exclude={"ready_at", "commitment_hash"},
        )
        return all(payload.get(field_name) == expected for field_name, expected in comparable.items())

    @staticmethod
    def _proposal_matches_retry(
        payload: Mapping[str, object],
        proposal: SessionSettlementProposal,
    ) -> bool:
        """Match a proposal by its canonical identity, not envelope time."""
        proposal_payload = payload.get("proposal")
        return (
            isinstance(proposal_payload, dict)
            and proposal_payload.get("settlement_id") == proposal.settlement_id
            and proposal_payload.get("session_id") == proposal.session_id
            and proposal_payload.get("settlement_input_root")
            == proposal.settlement_input_root
        )

    def _existing_operation_ids(
        self,
        *,
        proposal: SessionSettlementProposal,
        acceptance: SessionSettlementAcceptance,
        transition_hash: str | None,
    ) -> dict[str, str]:
        predicates = {
            "ready": lambda item: (
                item.payload.get("session_id") == proposal.session_id
                and isinstance(item.payload.get("ready"), dict)
                and self._readiness_matches_retry(
                    item.payload["ready"],
                    SettlementReadyCommitment.model_validate(item.payload["ready"]),
                )
            ),
            "proposal": lambda item: self._proposal_matches_retry(
                item.payload, proposal
            ),
            "acceptance": lambda item: (
                isinstance(item.payload.get("acceptance"), dict)
                and self._acceptance_matches_retry(
                    item.payload["acceptance"], acceptance
                )
            ),
            "finalize": lambda item: (
                isinstance(item.payload.get("transition"), dict)
                and item.payload["transition"].get("transition_hash") == transition_hash
            ),
        }
        operation_types = {
            "ready": "SESSION_SETTLEMENT_READY_COMMIT",
            "proposal": "SESSION_SETTLEMENT_PROPOSE",
            "acceptance": "SESSION_SETTLEMENT_ACCEPT",
            "finalize": "SESSION_SETTLEMENT_FINALIZE",
        }
        return {
            stage: envelope.operation_id
            for stage, operation_type in operation_types.items()
            if (envelope := self._find_local_envelope(operation_type, predicates[stage]))
            is not None
        }

    def _submit_and_reconcile(
        self,
        envelope: LedgerOperationEnvelope,
    ) -> tuple[SubmissionRecord, bool]:
        local = self._find_local_envelope(
            envelope.operation_type,
            lambda item: item.operation_id == envelope.operation_id,
        )
        if local is not None:
            self._discard_pending(envelope.operation_id)
            record = self._consensus.get_submission(envelope.operation_id)
            if record is None:
                record = SubmissionRecord(
                    operation_id=envelope.operation_id,
                    status=SubmissionStatus.FINALIZED,
                    transaction_hash=cometbft_transaction_hash(envelope.canonical_bytes()),
                )
            return record, True

        self._stage_pending(envelope)
        record = self._consensus.submit_operation(envelope)
        if record.status != SubmissionStatus.FINALIZED and self._finality_source is not None:
            reconciled = self._consensus.reconcile_finality(
                envelope.operation_id,
                finality_source=self._finality_source,
            )
            if reconciled is not None:
                record = reconciled
        return record, record.status == SubmissionStatus.FINALIZED

    def _apply_if_missing(self, envelope: LedgerOperationEnvelope, apply):
        if self._find_local_envelope(
            envelope.operation_type,
            lambda item: item.operation_id == envelope.operation_id,
        ) is not None:
            self._discard_pending(envelope.operation_id)
            return
        apply(envelope)
        self._discard_pending(envelope.operation_id)

    def _stage_pending(self, envelope: LedgerOperationEnvelope) -> None:
        if self._pending_envelope_store is not None:
            self._pending_envelope_store.stage_pending_consensus_envelope(envelope)

    def _discard_pending(self, *operation_ids: str) -> None:
        if self._pending_envelope_store is not None:
            self._pending_envelope_store.discard_pending_consensus_envelopes(
                *operation_ids
            )

    @staticmethod
    def _required_operation_id(operation: Mapping[str, object], label: str) -> str:
        operation_id = operation.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError(f"{label} operation_id is invalid")
        return operation_id

    @staticmethod
    def _blocked_status(record: SubmissionRecord) -> str:
        if record.status == SubmissionStatus.FAILED:
            return "failed"
        return "awaiting_verified_finality"
