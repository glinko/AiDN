"""RFC-0047 §10 — Admission validation for Ledger Operations."""

import json

from pydantic import BaseModel

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope


class AdmissionResult(BaseModel):
    admitted: bool
    reason: str | None = None
    operation_id: str | None = None


class AdmissionValidator:
    """RFC-0047 §10 — Admission validation for Ledger Operations."""

    def __init__(
        self,
        *,
        current_time: str,
        finalized_operation_ids: set[str] | None = None,
        wallet_sequences: dict[str, int] | None = None,
        max_payload_bytes: int = 65536,
        max_evidence_refs: int = 16,
        max_signatures: int = 8,
    ):
        self.current_time = current_time
        self._finalized_ids = finalized_operation_ids or set()
        self._wallet_sequences = wallet_sequences or {}
        self._max_payload_bytes = max_payload_bytes
        self._max_evidence_refs = max_evidence_refs
        self._max_signatures = max_signatures

    def validate(self, envelope: LedgerOperationEnvelope) -> AdmissionResult:
        """Full admission validation chain."""
        # 1. duplicate check
        if envelope.operation_id in self._finalized_ids:
            return AdmissionResult(
                admitted=False,
                reason="duplicate_operation_id",
                operation_id=envelope.operation_id,
            )

        # 2. sender sequence validation
        if envelope.sender_wallet and envelope.sender_sequence is not None:
            expected = self._wallet_sequences.get(envelope.sender_wallet, 1)
            if envelope.sender_sequence != expected:
                return AdmissionResult(
                    admitted=False,
                    reason="invalid_sender_sequence",
                    operation_id=envelope.operation_id,
                )

        # 3. expiry check
        if envelope.expires_at and envelope.expires_at < self.current_time:
            return AdmissionResult(
                admitted=False,
                reason="operation_expired",
                operation_id=envelope.operation_id,
            )

        # 4. payload size
        payload_bytes = len(json.dumps(envelope.payload).encode("utf-8"))
        if payload_bytes > self._max_payload_bytes:
            return AdmissionResult(
                admitted=False,
                reason="payload_too_large",
                operation_id=envelope.operation_id,
            )

        # 5. evidence ref limit
        if len(envelope.evidence_references) > self._max_evidence_refs:
            return AdmissionResult(
                admitted=False,
                reason="too_many_evidence_refs",
                operation_id=envelope.operation_id,
            )

        # 6. signature limit
        if len(envelope.signatures) > self._max_signatures:
            return AdmissionResult(
                admitted=False,
                reason="too_many_signatures",
                operation_id=envelope.operation_id,
            )

        return AdmissionResult(admitted=True, operation_id=envelope.operation_id)

    def record_finalized(self, operation_id: str) -> None:
        """Mark an operation ID as finalized (for duplicate detection)."""
        self._finalized_ids.add(operation_id)

    def advance_wallet_sequence(self, wallet_id: str) -> int:
        """Advance and return the next sequence for a wallet."""
        current = self._wallet_sequences.get(wallet_id, 0)
        next_seq = current + 1
        self._wallet_sequences[wallet_id] = next_seq
        return next_seq
