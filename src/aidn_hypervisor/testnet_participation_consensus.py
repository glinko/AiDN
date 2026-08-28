"""Consensus adapter for the Testnet Participation payout runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aidn_hypervisor.consensus.finality import ConsensusFinalitySource
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.testnet_participation_payout import ParticipationTransferSubmission


class ConsensusParticipationTransferSubmitter:
    """Submit and reconcile exact Treasury transfers against verified finality.

    This adapter is intentionally thin. It owns no key, creates no replacement
    envelope and does not infer finality from mempool admission.  A caller must
    supply a verified finality source and a canonical treasury-balance reader.
    """

    def __init__(
        self,
        *,
        consensus_service: Any,
        finality_source: ConsensusFinalitySource,
        canonical_balance_q_atoms: Callable[[str], int],
    ) -> None:
        self.consensus_service = consensus_service
        self.finality_source = finality_source
        self.canonical_balance_q_atoms = canonical_balance_q_atoms

    def next_sender_sequence(self, wallet_id: str) -> int:
        query = getattr(self.consensus_service, "query_wallet_next_sequence", None)
        if not callable(query):
            raise ValueError("PARTICIPATION_TREASURY_SEQUENCE_QUERY_UNAVAILABLE")
        sequence = query(wallet_id)
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("PARTICIPATION_TREASURY_SEQUENCE_UNAVAILABLE")
        return sequence

    def treasury_balance_q_atoms(self, wallet_id: str) -> int:
        balance = self.canonical_balance_q_atoms(wallet_id)
        if isinstance(balance, bool) or not isinstance(balance, int) or balance < 0:
            raise ValueError("PARTICIPATION_TREASURY_BALANCE_INVALID")
        return balance

    def submit_transfer(
        self, envelope: LedgerOperationEnvelope
    ) -> ParticipationTransferSubmission:
        self._validate_transfer(envelope)
        record = self.consensus_service.submit_operation(envelope)
        return self._result(envelope, record)

    def reconcile_transfer(
        self, envelope: LedgerOperationEnvelope
    ) -> ParticipationTransferSubmission:
        self._validate_transfer(envelope)
        final = self._verified_finality(envelope)
        if final is not None:
            mark_included = getattr(self.consensus_service, "mark_included", None)
            mark_finalized = getattr(self.consensus_service, "mark_finalized", None)
            if callable(mark_included):
                mark_included(envelope.operation_id, final.block_height)
            if callable(mark_finalized):
                mark_finalized(envelope.operation_id, final.block_height)
            return ParticipationTransferSubmission(
                operation_id=envelope.operation_id,
                status="FINALIZED",
                detail=f"finalized at height {final.block_height}",
            )
        restore = getattr(self.consensus_service, "restore_submission", None)
        if not callable(restore):
            raise ValueError("PARTICIPATION_TREASURY_RECONCILIATION_UNAVAILABLE")
        restore(envelope)
        record = self.consensus_service.submit_operation(envelope, retry_existing=True)
        return self._result(envelope, record)

    def _result(
        self,
        envelope: LedgerOperationEnvelope,
        record: Any,
    ) -> ParticipationTransferSubmission:
        if self._verified_finality(envelope) is not None:
            return ParticipationTransferSubmission(
                operation_id=envelope.operation_id,
                status="FINALIZED",
            )
        status = str(getattr(getattr(record, "status", None), "value", "")).lower()
        if status == "finalized":
            return ParticipationTransferSubmission(
                operation_id=envelope.operation_id,
                status="FINALIZED",
            )
        if status == "failed":
            return ParticipationTransferSubmission(
                operation_id=envelope.operation_id,
                status="REJECTED",
                detail=str(getattr(record, "error", None) or "consensus submission failed"),
            )
        return ParticipationTransferSubmission(
            operation_id=envelope.operation_id,
            status="ADMITTED",
            detail=status or "submission pending",
        )

    def _verified_finality(self, envelope: LedgerOperationEnvelope):
        try:
            finality = self.finality_source.finality_evidence(envelope.operation_id)
        except Exception:
            return None
        configured_chain = str(getattr(getattr(self.consensus_service, "config", None), "chain_id", ""))
        if (
            finality is None
            or finality.operation_id != envelope.operation_id
            or finality.operation_type != "WALLET_TRANSFER"
            or not configured_chain
            or finality.chain_id != configured_chain
        ):
            return None
        return finality

    @staticmethod
    def _validate_transfer(envelope: LedgerOperationEnvelope) -> None:
        if envelope.operation_type != "WALLET_TRANSFER":
            raise ValueError("PARTICIPATION_PAYOUT_TRANSFER_TYPE_INVALID")


__all__ = ["ConsensusParticipationTransferSubmitter"]
