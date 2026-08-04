from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope

_DRILL_PATH = Path(__file__).parents[2] / "tools" / "verify-cometbft-multivalidator-devnet.py"
_DRILL_SPEC = importlib.util.spec_from_file_location("multivalidator_drill", _DRILL_PATH)
assert _DRILL_SPEC is not None and _DRILL_SPEC.loader is not None
_DRILL = importlib.util.module_from_spec(_DRILL_SPEC)
_DRILL_SPEC.loader.exec_module(_DRILL)


def _envelopes() -> list[LedgerOperationEnvelope]:
    rows = (
        _DRILL._failure_chain_transactions()
        + _DRILL._session_lifecycle_transactions()
        + _DRILL._reputation_profile_transactions()
    )
    return [
        LedgerOperationEnvelope.model_validate(json.loads(transaction))
        for _stage, _session_id, transaction in rows
    ]


def test_multivalidator_drill_covers_failure_and_session_lifecycle_chains() -> None:
    envelopes = _envelopes()

    assert [envelope.operation_type for envelope in envelopes] == [
        "SESSION_ESCROW_LOCK",
        "SESSION_FAILURE_EVIDENCE",
        "SESSION_FORCE_SETTLE",
        "SESSION_ESCROW_LOCK",
        "SESSION_OPEN",
        "SESSION_ACCEPT",
        "SERVICE_VERIFICATION_COMMIT",
        "REPUTATION_PROFILE_UPDATE",
    ]
    assert len({envelope.initiator_id for envelope in envelopes[:6]}) == 3
    assert envelopes[0].initiator_id == envelopes[1].initiator_id == envelopes[2].initiator_id
    assert envelopes[3].initiator_id == envelopes[4].initiator_id
    assert envelopes[5].initiator_id != envelopes[3].initiator_id

    lifecycle_lock, lifecycle_open, lifecycle_accept = envelopes[3:6]
    assert lifecycle_lock.sender_wallet == "wallet:acceptance-consumer"
    assert lifecycle_lock.sender_sequence == 2
    assert lifecycle_open.sender_wallet == "wallet:acceptance-consumer"
    assert lifecycle_open.sender_sequence == 3
    assert lifecycle_accept.sender_wallet == "wallet:acceptance-endpoint"
    assert lifecycle_accept.sender_sequence == 1
    assert lifecycle_open.payload["funding_lock_operation_id"] == lifecycle_lock.operation_id
    assert lifecycle_lock.operation_id in lifecycle_open.evidence_references
    assert lifecycle_open.operation_id == lifecycle_accept.payload["session_open_operation_id"]
    assert lifecycle_open.operation_id in lifecycle_accept.evidence_references

    verification, profile = envelopes[6:]
    assert verification.payload["verification_report_id"]
    assert profile.payload["object_type"] == "reputation_profile"
    assert verification.operation_id in profile.evidence_references
    assert profile.payload["effective_epoch"] == 7
    assert profile.payload["formula_version"] == "reputation.v1"


def test_multivalidator_convergence_accepts_matching_fresh_statuses() -> None:
    statuses = [
        {"rpc_url": "http://validator-0", "height": 12, "app_hash": "AA", "catching_up": False},
        {"rpc_url": "http://validator-1", "height": 12, "app_hash": "AA", "catching_up": False},
        {"rpc_url": "http://validator-2", "height": 12, "app_hash": "AA", "catching_up": False},
    ]

    assert _DRILL._converged_status(statuses, greater_than=11) == (12, "AA")


def test_multivalidator_convergence_rejects_divergent_or_stale_statuses() -> None:
    matching = [
        {"rpc_url": "http://validator-0", "height": 12, "app_hash": "AA", "catching_up": False},
        {"rpc_url": "http://validator-1", "height": 12, "app_hash": "AA", "catching_up": False},
    ]

    assert _DRILL._converged_status(
        [*matching[:-1], {**matching[1], "height": 11}], greater_than=10
    ) is None
    assert _DRILL._converged_status(
        [*matching[:-1], {**matching[1], "app_hash": "BB"}], greater_than=10
    ) is None
    assert _DRILL._converged_status(matching, greater_than=12) is None
    assert _DRILL._converged_status(
        [*matching[:-1], {**matching[1], "catching_up": True}], greater_than=10
    ) is None


def test_multivalidator_drill_supports_reduced_disposable_escrow() -> None:
    failure = _DRILL._failure_chain_transactions(total_locked_amount_q_atoms=500)
    lifecycle = _DRILL._session_lifecycle_transactions(total_locked_amount_q_atoms=150)

    failure_lock = LedgerOperationEnvelope.model_validate(json.loads(failure[0][2]))
    failure_force = LedgerOperationEnvelope.model_validate(json.loads(failure[2][2]))
    lifecycle_lock = LedgerOperationEnvelope.model_validate(json.loads(lifecycle[0][2]))

    assert failure_lock.payload["total_locked_amount_q_atoms"] == 500
    assert failure_force.payload["requested_refund_q_atoms"] == 500
    assert lifecycle_lock.payload["total_locked_amount_q_atoms"] == 150
