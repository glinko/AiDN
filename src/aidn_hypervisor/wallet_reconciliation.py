"""Recovery for consensus-backed Wallet transfer envelopes.

Pending envelopes are durable intent, while the ConsensusService submission
index is intentionally in-memory.  A process restart must therefore restore
the exact submission identity, check verified finality, and only then retry the
same transaction.  This module deliberately never creates a replacement
envelope or changes its operation ID.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
    from aidn_hypervisor.service import HypervisorService


_RETRYABLE_SUBMISSION_STATES = {"pending"}


def reconcile_pending_wallet_transfers(
    service: HypervisorService,
    *,
    operation_ids: Iterable[str] | None = None,
    rebroadcast: bool = True,
) -> list[dict]:
    """Restore, finalize, or rebroadcast durable Wallet transfer envelopes.

    The function is safe to call at startup, from a dashboard refresh, and
    immediately after a submit.  Verified consensus finality always wins over
    local submission state.  If finality is unavailable, the exact envelope is
    rebroadcast idempotently; a failed retry remains persisted for diagnostics.
    """
    consensus = getattr(service, "consensus_service", None)
    if consensus is None or not getattr(consensus, "is_enabled", False):
        return []

    selected_ids = set(operation_ids) if operation_ids is not None else None
    reports: list[dict] = []
    for envelope in service.list_pending_consensus_envelopes():
        if envelope.operation_type != "WALLET_TRANSFER":
            continue
        if selected_ids is not None and envelope.operation_id not in selected_ids:
            continue
        reports.append(_reconcile_one(service, consensus, envelope, rebroadcast=rebroadcast))
    return reports


def _reconcile_one(
    service,
    consensus,
    envelope: LedgerOperationEnvelope,
    *,
    rebroadcast: bool,
) -> dict:
    operation_id = envelope.operation_id
    try:
        # A local canonical operation is enough to remove a stale durable
        # envelope.  This is the validator/local-ABCI recovery path.
        if service.ledger_operation_service.get_operation(operation_id) is not None:
            _discard(service, operation_id)
            return {"operation_id": operation_id, "status": "local_projection_finalized"}

        # Reconstruct the exact transaction hash before consulting finality.
        # Without this, a restart looks like NOT_SUBMITTED even when the
        # transaction was already accepted or included by CometBFT.
        consensus.restore_submission(envelope)
        finality = service.ledger_operation_finality(operation_id)
        if finality.get("consensus_finalized"):
            return _materialize_finalized(service, envelope, finality)

        submission = consensus.get_submission(operation_id)
        if rebroadcast and (
            submission is None or submission.status.value in _RETRYABLE_SUBMISSION_STATES
        ):
            # retry_existing preserves operation_id, sequence, signature and
            # transaction bytes.  It cannot create a second transfer.
            submission = consensus.submit_operation(envelope, retry_existing=True)

        finality = service.ledger_operation_finality(operation_id)
        if finality.get("consensus_finalized"):
            return _materialize_finalized(service, envelope, finality)

        status = submission.status.value
        report = {
            "operation_id": operation_id,
            "status": status,
            "submission_status": status,
            "finality": finality,
        }
        if submission.error:
            report["error"] = submission.error
        return report
    except Exception as error:
        # Recovery must not prevent the node from starting or hide the exact
        # envelope.  The Wallet UI will show the diagnostic and the next
        # refresh can retry after the external consensus service recovers.
        return {
            "operation_id": operation_id,
            "status": "recovery_error",
            "error": str(error) or error.__class__.__name__,
        }


def _materialize_finalized(service, envelope, finality: dict) -> dict:
    operation_id = envelope.operation_id
    record = service.ledger_operation_service.apply_consensus_wallet_transfer(envelope)
    service._persist_state()
    _discard(service, operation_id)
    return {
        "operation_id": operation_id,
        "status": "consensus_finalized",
        "finality": finality,
        "record": record,
    }


def _discard(service, operation_id: str) -> None:
    service.discard_pending_consensus_envelopes(operation_id)
    service.discard_pending_consensus_operations(operation_id)
