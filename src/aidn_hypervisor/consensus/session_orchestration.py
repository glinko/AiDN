"""Ordered consensus orchestration for Session failure operations.

The local Ledger can create an auditable projection before the network sees
it.  This module is the narrow bridge that submits the corresponding
canonical envelopes in dependency order and refuses to advance on admission
alone.  A verified finality source is therefore part of the enabled-network
path, not an optional success signal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from aidn_hypervisor.consensus.finality import ConsensusFinalitySource
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.projection import (
    build_session_escrow_lock_envelope,
    build_session_failure_evidence_envelope,
    build_session_force_settle_envelope,
)
from aidn_hypervisor.consensus.service import (
    ConsensusService,
    SubmissionRecord,
    SubmissionStatus,
)


@dataclass(frozen=True)
class ConsensusSessionChainResult:
    """Serializable status of one ordered Session operation chain."""

    status: str
    blocked_on: str | None
    local_operation_ids: dict[str, str]
    canonical_operation_ids: dict[str, str]
    submissions: dict[str, dict]

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "blocked_on": self.blocked_on,
            "local_operation_ids": dict(self.local_operation_ids),
            "canonical_operation_ids": dict(self.canonical_operation_ids),
            "submissions": {
                stage: dict(record) for stage, record in self.submissions.items()
            },
        }


def _operation_id(operation: Mapping[str, object], *, stage: str) -> str:
    value = operation.get("operation_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"local {stage} operation_id is required")
    return value


def _session_id(operation: Mapping[str, object], *, stage: str) -> str:
    payload = operation.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError(f"local {stage} payload is invalid")
    value = payload.get("session_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"local {stage} session_id is required")
    return value


def _failure_root(operation: Mapping[str, object], *, stage: str) -> str:
    payload = operation.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError(f"local {stage} payload is invalid")
    value = payload.get("failure_evidence_root")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"local {stage} failure_evidence_root is required")
    return value


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


class ConsensusSessionOperationOrchestrator:
    """Submit escrow, failure evidence and Forced Settlement in order.

    The method is deliberately resumable.  Calling it again with the same
    local records and canonical inputs reuses the deterministic envelope IDs
    and lets ``ConsensusService`` return its existing submission records.
    """

    def __init__(
        self,
        consensus_service: ConsensusService,
        *,
        finality_source: ConsensusFinalitySource | None = None,
    ) -> None:
        self._consensus = consensus_service
        self._finality_source = finality_source

    def submit_failure_chain(
        self,
        *,
        local_lock_operation: Mapping[str, object],
        funding: Mapping[str, object] | object,
        sender_sequence: int,
        lock_signatures: Sequence[str],
        local_failure_operation: Mapping[str, object],
        failure_signatures: Sequence[str],
        local_force_operation: Mapping[str, object],
        initiator_wallet: str,
        initiator_signature: str,
        observed_at: str,
        transition: Mapping[str, object],
        force_signatures: Sequence[str] | None = None,
    ) -> dict:
        """Advance the canonical failure chain as far as verified finality allows.

        The dependency order is strict:

        ``SESSION_ESCROW_LOCK`` -> ``SESSION_FAILURE_EVIDENCE`` ->
        ``SESSION_FORCE_SETTLE``.

        ``broadcast_tx_sync`` admission is never treated as finality.  When
        the network is enabled without a verified finality source, the result
        remains ``awaiting_verified_finality`` and dependent operations are
        not submitted.
        """
        local_ids = {
            "lock": _operation_id(local_lock_operation, stage="escrow lock"),
            "failure": _operation_id(local_failure_operation, stage="failure evidence"),
            "force": _operation_id(local_force_operation, stage="Forced Settlement"),
        }
        session_ids = {
            _session_id(local_lock_operation, stage="escrow lock"),
            _session_id(local_failure_operation, stage="failure evidence"),
            _session_id(local_force_operation, stage="Forced Settlement"),
        }
        funding_session_id = getattr(funding, "session_id", None)
        if isinstance(funding, Mapping):
            funding_session_id = funding.get("session_id")
        if (
            len(session_ids) != 1
            or not isinstance(funding_session_id, str)
            or funding_session_id not in session_ids
        ):
            raise ValueError("consensus Session operation bindings are inconsistent")
        if _failure_root(local_failure_operation, stage="failure evidence") != _failure_root(
            local_force_operation,
            stage="Forced Settlement",
        ):
            raise ValueError("consensus failure evidence roots are inconsistent")
        canonical_ids: dict[str, str] = {}
        submissions: dict[str, dict] = {}

        lock_envelope = build_session_escrow_lock_envelope(
            local_lock_operation,
            funding=funding,
            sender_sequence=sender_sequence,
            signatures=lock_signatures,
        )
        canonical_ids["lock"] = lock_envelope.operation_id
        lock_record, lock_final = self._submit_and_reconcile(lock_envelope)
        submissions["lock"] = _submission_dict(lock_record)
        if not lock_final:
            return ConsensusSessionChainResult(
                status=self._blocked_status(lock_record),
                blocked_on="lock",
                local_operation_ids=local_ids,
                canonical_operation_ids=canonical_ids,
                submissions=submissions,
            ).as_dict()

        failure_envelope = build_session_failure_evidence_envelope(
            local_failure_operation,
            signatures=failure_signatures,
        )
        canonical_ids["failure"] = failure_envelope.operation_id
        failure_record, failure_final = self._submit_and_reconcile(failure_envelope)
        submissions["failure"] = _submission_dict(failure_record)
        if not failure_final:
            return ConsensusSessionChainResult(
                status=self._blocked_status(failure_record),
                blocked_on="failure",
                local_operation_ids=local_ids,
                canonical_operation_ids=canonical_ids,
                submissions=submissions,
            ).as_dict()

        force_envelope = build_session_force_settle_envelope(
            local_force_operation,
            funding_lock_operation_id=lock_envelope.operation_id,
            failure_evidence_operation_id=failure_envelope.operation_id,
            initiator_wallet=initiator_wallet,
            initiator_signature=initiator_signature,
            observed_at=observed_at,
            transition=transition,
            signatures=force_signatures or [initiator_signature],
        )
        canonical_ids["force"] = force_envelope.operation_id
        force_record, force_final = self._submit_and_reconcile(force_envelope)
        submissions["force"] = _submission_dict(force_record)
        return ConsensusSessionChainResult(
            status="finalized" if force_final else self._blocked_status(force_record),
            blocked_on=None if force_final else "force",
            local_operation_ids=local_ids,
            canonical_operation_ids=canonical_ids,
            submissions=submissions,
        ).as_dict()

    def _submit_and_reconcile(
        self,
        envelope: LedgerOperationEnvelope,
    ) -> tuple[SubmissionRecord, bool]:
        # A recovered canonical operation may already be finalized while the
        # local submission index is stale or records an earlier CheckTx error.
        # Verify external finality before rebroadcasting: wallet sequence
        # validation can reject an already-finalized transaction even though
        # replaying it is otherwise idempotent.
        existing = self._consensus.get_submission(envelope.operation_id)
        if existing is None:
            record = self._consensus.restore_submission(envelope)
        else:
            record = existing
        if self._finality_source is not None:
            reconciled = self._consensus.reconcile_finality(
                envelope.operation_id,
                finality_source=self._finality_source,
            )
            if reconciled is not None:
                record = reconciled
                return record, record.status == SubmissionStatus.FINALIZED
        record = self._consensus.submit_operation(envelope, retry_existing=True)
        if (
            record.status in {SubmissionStatus.ADMITTED, SubmissionStatus.INCLUDED}
            and self._finality_source is not None
        ):
            reconciled = self._consensus.reconcile_finality(
                envelope.operation_id,
                finality_source=self._finality_source,
            )
            if reconciled is not None:
                record = reconciled
        finalized = record.status == SubmissionStatus.FINALIZED
        return record, finalized

    @staticmethod
    def _blocked_status(record: SubmissionRecord) -> str:
        if record.status == SubmissionStatus.FAILED:
            return "failed"
        return "awaiting_verified_finality"
