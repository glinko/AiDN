from __future__ import annotations

import pytest

from aidn_hypervisor.consensus.validator_duty import (
    DutyClassification,
    ValidatorDutyEvidence,
    ValidatorDutyPolicy,
    build_participant_suspension_envelope,
    evaluate_unbonding_release,
    evaluate_validator_duty,
)


def _evidence(
    *,
    epoch: int = 10,
    signed_votes: int = 90,
    consecutive_below_retention_epochs: int = 0,
    exit_requested: bool = False,
) -> ValidatorDutyEvidence:
    return ValidatorDutyEvidence(
        node_id="node-1",
        epoch=epoch,
        expected_votes=100,
        signed_votes=signed_votes,
        consecutive_below_retention_epochs=consecutive_below_retention_epochs,
        exit_requested=exit_requested,
        evidence_root="sha256:duty-evidence",
    )


def test_duty_boundaries_are_integer_and_contractual() -> None:
    policy = ValidatorDutyPolicy()

    normal = evaluate_validator_duty(_evidence(signed_votes=90), policy=policy)
    minor = evaluate_validator_duty(_evidence(signed_votes=80), policy=policy)
    major = evaluate_validator_duty(_evidence(signed_votes=67), policy=policy)
    below_retention = evaluate_validator_duty(
        _evidence(signed_votes=66, consecutive_below_retention_epochs=1),
        policy=policy,
    )

    assert normal.participation_bps == 9_000
    assert normal.classification == DutyClassification.NORMAL
    assert normal.reward_eligible is True
    assert normal.retention_eligible is True
    assert minor.classification == DutyClassification.MINOR_DOWNTIME
    assert minor.reward_eligible is True
    assert major.classification == DutyClassification.MAJOR_DOWNTIME
    assert major.retention_eligible is True
    assert below_retention.classification == DutyClassification.MAJOR_DOWNTIME
    assert below_retention.reward_eligible is False
    assert below_retention.retention_eligible is False


def test_persistent_downtime_requires_three_consecutive_epochs() -> None:
    decision = evaluate_validator_duty(
        _evidence(signed_votes=66, consecutive_below_retention_epochs=3),
    )

    assert decision.classification == DutyClassification.PERSISTENT_DOWNTIME
    assert decision.remove_from_active_set is True
    assert decision.suspension_until_epoch == 17
    assert decision.reward_eligible is False
    assert decision.retention_eligible is False
    assert decision.slash_authorized is False


def test_zero_participation_without_exit_is_abandonment_not_slash() -> None:
    decision = evaluate_validator_duty(_evidence(signed_votes=0))

    assert decision.classification == DutyClassification.CONSENSUS_ABANDONMENT
    assert decision.remove_from_active_set is True
    assert decision.suspension_until_epoch == 24
    assert decision.slash_authorized is False


def test_zero_participation_with_exit_request_is_not_abandonment() -> None:
    decision = evaluate_validator_duty(
        _evidence(signed_votes=0, exit_requested=True),
    )

    assert decision.classification == DutyClassification.PERSISTENT_DOWNTIME
    assert decision.suspension_until_epoch == 17


def test_persistent_duty_builds_evidence_bound_suspension_operation() -> None:
    decision = evaluate_validator_duty(
        _evidence(signed_votes=66, consecutive_below_retention_epochs=3),
    )

    envelope = build_participant_suspension_envelope(
        decision,
        evidence_operation_id="evidence-operation-1",
        created_at="2030-01-01T00:00:00Z",
    )

    assert envelope.operation_type == "PARTICIPANT_SUSPEND"
    assert envelope.origin_type == "evidence_triggered"
    assert envelope.target_epoch == "10"
    assert envelope.payload["target_id"] == "node-1"
    assert envelope.payload["effective_epoch"] == 10
    assert envelope.payload["minimum_recovery_epoch"] == 17
    assert envelope.payload["reason_code"] == "PERSISTENT_DOWNTIME"
    assert envelope.payload["evidence_operation_id"] == "evidence-operation-1"
    assert envelope.evidence_references == [
        "evidence-operation-1",
        "sha256:duty-evidence",
    ]


def test_non_removing_duty_cannot_emit_suspension_operation() -> None:
    decision = evaluate_validator_duty(_evidence(signed_votes=90))

    with pytest.raises(ValueError, match="does not require suspension"):
        build_participant_suspension_envelope(
            decision,
            evidence_operation_id="evidence-operation-1",
            created_at="2030-01-01T00:00:00Z",
        )


def test_unbonding_requires_full_period_and_clean_obligations() -> None:
    waiting = evaluate_unbonding_release(
        request_epoch=10,
        current_epoch=23,
        unresolved_misconduct=False,
        obligations_complete=True,
    )
    misconduct_block = evaluate_unbonding_release(
        request_epoch=10,
        current_epoch=24,
        unresolved_misconduct=True,
        obligations_complete=True,
    )
    released = evaluate_unbonding_release(
        request_epoch=10,
        current_epoch=24,
        unresolved_misconduct=False,
        obligations_complete=True,
    )

    assert waiting.completion_epoch == 24
    assert waiting.releasable is False
    assert misconduct_block.releasable is False
    assert released.releasable is True
    assert released.state == "RELEASED"


def test_unbonding_rejects_invalid_epoch_and_vote_evidence() -> None:
    with pytest.raises(ValueError, match="expected_votes"):
        ValidatorDutyEvidence(
            node_id="node-1",
            epoch=1,
            expected_votes=0,
            signed_votes=0,
            evidence_root="sha256:evidence",
        )

    with pytest.raises(ValueError, match="signed_votes"):
        ValidatorDutyEvidence(
            node_id="node-1",
            epoch=1,
            expected_votes=10,
            signed_votes=11,
            evidence_root="sha256:evidence",
        )

    with pytest.raises(ValueError, match="current_epoch"):
        evaluate_unbonding_release(
            request_epoch=10,
            current_epoch=9,
            unresolved_misconduct=False,
            obligations_complete=True,
        )
