"""RFC-0047 §10 — Admission validation for Ledger Operations."""

import json
from collections.abc import Callable
from datetime import UTC, datetime

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
        signature_verifier: Callable[[LedgerOperationEnvelope], bool] | None = None,
        require_signature_for_origins: frozenset[str] = frozenset(),
    ):
        self.current_time = current_time
        self._finalized_ids = finalized_operation_ids or set()
        self._wallet_sequences = wallet_sequences or {}
        self._max_payload_bytes = max_payload_bytes
        self._max_evidence_refs = max_evidence_refs
        self._max_signatures = max_signatures
        self._signature_verifier = signature_verifier
        self._require_signature_for_origins = require_signature_for_origins

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
        if envelope.expires_at:
            try:
                expires_at = _parse_timestamp(envelope.expires_at)
                current_time = _parse_timestamp(self.current_time)
            except ValueError:
                return AdmissionResult(
                    admitted=False,
                    reason="invalid_expiration",
                    operation_id=envelope.operation_id,
                )
            if expires_at < current_time:
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

        if (
            envelope.origin_type in self._require_signature_for_origins
            and not envelope.signatures
        ):
            return AdmissionResult(
                admitted=False,
                reason="signature_required",
                operation_id=envelope.operation_id,
            )
        if (
            self._signature_verifier is not None
            and envelope.signatures
            and not self._signature_verifier(envelope)
        ):
            return AdmissionResult(
                admitted=False,
                reason="signature_invalid",
                operation_id=envelope.operation_id,
            )

        return AdmissionResult(admitted=True, operation_id=envelope.operation_id)

    def record_finalized(self, operation_id: str) -> None:
        """Mark an operation ID as finalized (for duplicate detection)."""
        self._finalized_ids.add(operation_id)

    def discard_finalized(self, operation_id: str) -> None:
        """Drop one non-canonical in-memory replay-cache entry.

        Callers must first prove that the canonical Ledger replay registry does
        not contain this ID. This is used only to repair process-local state
        after a controlled chain reset; it never changes the Ledger.
        """

        self._finalized_ids.discard(operation_id)

    def advance_wallet_sequence(self, wallet_id: str) -> int:
        """Advance and return the next sequence for a wallet."""
        current = self._wallet_sequences.get(wallet_id, 1)
        next_seq = current + 1
        self._wallet_sequences[wallet_id] = next_seq
        return next_seq

    def snapshot_state(self) -> dict[str, object]:
        """Capture mutable admission state for block rollback."""
        return {
            "finalized_ids": set(self._finalized_ids),
            "wallet_sequences": dict(self._wallet_sequences),
        }

    def restore_state(self, state: dict[str, object]) -> None:
        """Restore mutable admission state after a failed block."""
        self._finalized_ids = set(state.get("finalized_ids", set()))
        self._wallet_sequences = dict(state.get("wallet_sequences", {}))


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(UTC)
