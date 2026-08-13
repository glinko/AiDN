from __future__ import annotations

import pytest

from aidn_hypervisor.consensus.epoch_schedule import EpochSchedule, build_epoch_schedule


def _schedule() -> EpochSchedule:
    return build_epoch_schedule(
        genesis_start_time="2030-01-01T00:00:00Z",
        epoch_duration_seconds=60,
        parameter_version="params-v1",
        task_set_version="tasks-v1",
        protocol_version="0.1",
    )


def test_schedule_is_hash_bound() -> None:
    schedule = _schedule()
    assert schedule.schedule_hash.startswith("sha256:")
    assert EpochSchedule.model_validate(schedule.model_dump(mode="json")) == schedule


def test_boundary_is_not_reached_before_scheduled_end() -> None:
    boundary = _schedule().boundary_for(
        active_epoch=0,
        active_start_time="2030-01-01T00:00:00Z",
        block_time="2030-01-01T00:00:59Z",
    )
    assert boundary.boundary_reached is False
    assert boundary.closing_epoch is None


def test_boundary_is_reached_at_scheduled_end() -> None:
    boundary = _schedule().boundary_for(
        active_epoch=4,
        active_start_time="2030-01-01T00:05:00Z",
        block_time="2030-01-01T00:06:00Z",
    )
    assert boundary.boundary_reached is True
    assert boundary.closing_epoch == 4
    assert boundary.opening_epoch == 5


def test_schedule_rejects_unsigned_hash_tampering() -> None:
    schedule = _schedule()
    with pytest.raises(ValueError, match="hash does not match"):
        EpochSchedule.model_validate(
            {
                **schedule.model_dump(mode="json"),
                "epoch_duration_seconds": 120,
            }
        )
