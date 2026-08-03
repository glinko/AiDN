import pytest
from pydantic import ValidationError

from aidn_hypervisor.reward.development_adjustments import (
    DevelopmentRewardStateSnapshot,
    build_development_reward_state_snapshot,
)
from aidn_hypervisor.reward.development_cancellation import (
    DevelopmentRewardCancellationRecord,
    build_development_reward_cancellation,
    validate_cancellation_history,
)
from aidn_hypervisor.reward.development_correction import (
    DevelopmentRewardCorrectionRecord,
    build_development_reward_correction,
    validate_reward_correction_history,
)
from aidn_hypervisor.reward.development_distribution import (
    DevelopmentRewardSchedule,
    canonical_hash,
)


def _schedule(*, reward_id: str = "reward-1") -> DevelopmentRewardSchedule:
    payload = {
        "reward_id": reward_id,
        "contribution_id": "contribution-1",
        "contribution_epoch": 1,
        "distribution_epoch": 2,
        "gross_reward_q_atoms": 100,
        "immediate_amount_q_atoms": 40,
        "maturity_stage_one_amount_q_atoms": 30,
        "maturity_stage_two_amount_q_atoms": 30,
        "immediate_epoch": 2,
        "maturity_stage_one_epoch": 6,
        "maturity_stage_two_epoch": 14,
    }
    return DevelopmentRewardSchedule(**payload, schedule_hash=canonical_hash(payload))


def _source(*, authorized_max_reward_q_atoms: int = 100) -> DevelopmentRewardStateSnapshot:
    return build_development_reward_state_snapshot(
        schedule=_schedule(),
        source_commitment_id="commitment-1",
        source_record_hashes=("reserve-record-1", "payment-record-1"),
        paid_q_atoms=20,
        unpaid_immediate_q_atoms=10,
        unpaid_maturity_stage_one_q_atoms=25,
        unpaid_maturity_stage_two_q_atoms=30,
        unclaimed_q_atoms=15,
        authorized_max_reward_q_atoms=authorized_max_reward_q_atoms,
    )


def _record_with_changed_operation(
    record: DevelopmentRewardCancellationRecord | DevelopmentRewardCorrectionRecord,
    operation_id: str,
):
    payload = record.model_dump(mode="json", exclude={"record_hash"})
    operation_field = (
        "cancellation_operation_id"
        if isinstance(record, DevelopmentRewardCancellationRecord)
        else "correction_operation_id"
    )
    payload[operation_field] = operation_id
    return type(record)(**payload, record_hash=canonical_hash(payload))


def test_source_snapshot_is_immutable_and_conservative():
    source = _source()

    assert source.verify_integrity()
    assert source.reward_liability_q_atoms == 100
    assert source.cancellable_q_atoms == 70
    with pytest.raises(ValidationError):
        source.paid_q_atoms = 21


def test_cancellation_only_returns_unpaid_maturity_and_unclaimed():
    source = _source()

    cancellation = build_development_reward_cancellation(
        source=source,
        cancellation_operation_id="cancel-op-1",
        cancellation_epoch=20,
        reason="ORDINARY_DEFECT",
        cancelled_unpaid_maturity_stage_one_q_atoms=5,
        cancelled_unclaimed_q_atoms=7,
    )

    assert cancellation.state == "CANCELLED_UNVESTED"
    assert cancellation.cancelled_q_atoms == 12
    assert cancellation.returned_to_pool_q_atoms == 12
    assert cancellation.paid_before_q_atoms == cancellation.paid_after_q_atoms == source.paid_q_atoms
    assert cancellation.unpaid_immediate_before_q_atoms == cancellation.unpaid_immediate_after_q_atoms == 10
    assert cancellation.reward_liability_before_q_atoms == 100
    assert cancellation.reward_liability_after_q_atoms == 88
    assert cancellation.verify_integrity()


def test_cancellation_history_rejects_duplicate_and_conflicting_semantic_events():
    source = _source()
    cancellation = build_development_reward_cancellation(
        source=source,
        cancellation_operation_id="cancel-op-1",
        cancellation_epoch=20,
        reason="CRITICAL_DEFECT",
        cancelled_unpaid_maturity_stage_two_q_atoms=4,
    )
    conflicting = _record_with_changed_operation(cancellation, "cancel-op-other")

    with pytest.raises(ValueError, match="DEVELOPMENT_REWARD_CANCELLATION_DUPLICATE"):
        validate_cancellation_history(source, [cancellation, cancellation])
    with pytest.raises(ValueError, match="DEVELOPMENT_REWARD_CANCELLATION_CONFLICT"):
        validate_cancellation_history(source, [cancellation, conflicting])


def test_cancellation_cannot_cancel_more_than_the_remaining_unpaid_bucket():
    source = _source()
    first = build_development_reward_cancellation(
        source=source,
        cancellation_operation_id="cancel-op-1",
        cancellation_epoch=20,
        reason="INTENTIONAL_GAMING",
        cancelled_unpaid_maturity_stage_one_q_atoms=25,
    )

    with pytest.raises(ValueError, match="DEVELOPMENT_REWARD_CANCELLATION_STAGE_ONE_OVERPAID"):
        build_development_reward_cancellation(
            source=source,
            cancellation_operation_id="cancel-op-2",
            cancellation_epoch=21,
            reason="INTENTIONAL_GAMING",
            cancelled_unpaid_maturity_stage_one_q_atoms=1,
            previous_cancellations=[first],
        )


def test_correction_is_append_only_and_conservation_aware():
    source = _source(authorized_max_reward_q_atoms=110)
    first = build_development_reward_correction(
        source=source,
        correction_operation_id="correction-op-1",
        correction_epoch=20,
        reason="ARITHMETIC_ERROR",
        authorization_reference="auth-1",
        delta_unpaid_maturity_stage_one_q_atoms=-5,
        delta_unclaimed_q_atoms=-3,
    )
    second = build_development_reward_correction(
        source=source,
        correction_operation_id="correction-op-2",
        correction_epoch=21,
        reason="ATTRIBUTION_ERROR",
        authorization_reference="auth-2",
        delta_unpaid_maturity_stage_two_q_atoms=4,
        previous_corrections=[first],
    )

    assert first.correction_delta_q_atoms == -8
    assert first.returned_to_pool_q_atoms == 8
    assert first.additional_reserved_q_atoms == 0
    assert second.previous_correction_id == first.correction_id
    assert second.correction_delta_q_atoms == 4
    assert second.additional_reserved_q_atoms == 4
    assert second.returned_to_pool_q_atoms == 0
    assert second.paid_before_q_atoms == second.paid_after_q_atoms == source.paid_q_atoms
    assert second.reward_liability_after_q_atoms + second.returned_to_pool_q_atoms == (
        second.reward_liability_before_q_atoms + second.additional_reserved_q_atoms
    )
    assert validate_reward_correction_history(source, [first, second]) == (first, second)


def test_correction_history_rejects_duplicate_and_conflicting_events():
    source = _source()
    correction = build_development_reward_correction(
        source=source,
        correction_operation_id="correction-op-1",
        correction_epoch=20,
        reason="DUPLICATE_REWARD",
        authorization_reference="auth-1",
        delta_unclaimed_q_atoms=-2,
    )
    conflicting = _record_with_changed_operation(correction, "correction-op-other")

    with pytest.raises(ValueError, match="DEVELOPMENT_REWARD_CORRECTION_DUPLICATE"):
        validate_reward_correction_history(source, [correction, correction])
    with pytest.raises(ValueError, match="DEVELOPMENT_REWARD_CORRECTION_CONFLICT"):
        validate_reward_correction_history(source, [correction, conflicting])


def test_correction_rejects_negative_delta_beyond_unpaid_and_overpaid_positive_delta():
    source = _source(authorized_max_reward_q_atoms=105)

    with pytest.raises(ValueError, match="DEVELOPMENT_REWARD_CORRECTION_NEGATIVE_DELTA_EXCEEDS_UNPAID"):
        build_development_reward_correction(
            source=source,
            correction_operation_id="correction-op-negative",
            correction_epoch=20,
            reason="CHALLENGE_RESOLUTION",
            authorization_reference="auth-negative",
            delta_unpaid_maturity_stage_one_q_atoms=-26,
        )

    with pytest.raises(ValueError, match="DEVELOPMENT_REWARD_CORRECTION_OVERPAID_DELTA"):
        build_development_reward_correction(
            source=source,
            correction_operation_id="correction-op-positive",
            correction_epoch=20,
            reason="ATTRIBUTION_ERROR",
            authorization_reference="auth-positive",
            delta_unclaimed_q_atoms=6,
        )


def test_correction_record_cannot_mutate_paid_history_or_break_conservation():
    source = _source()
    correction = build_development_reward_correction(
        source=source,
        correction_operation_id="correction-op-1",
        correction_epoch=20,
        reason="WALLET_BINDING_ERROR",
        authorization_reference="auth-1",
        delta_unclaimed_q_atoms=-1,
    )
    payload = correction.model_dump(mode="json", exclude={"record_hash"})
    payload["paid_after_q_atoms"] = payload["paid_before_q_atoms"] + 1
    with pytest.raises(ValueError, match="DEVELOPMENT_REWARD_CORRECTION_PAID_HISTORY_MUTATION"):
        DevelopmentRewardCorrectionRecord(**payload, record_hash=canonical_hash(payload))
