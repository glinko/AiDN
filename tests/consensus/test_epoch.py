"""M7-S6: Epoch management — RFC-0047 §23."""

from __future__ import annotations

import pytest

from aidn_hypervisor.consensus.epoch import (
    EpochConfig,
    EpochService,
    EpochState,
    EpochStatus,
)

# ── EpochConfig ──────────────────────────────────────────────────────


def test_epoch_config_defaults() -> None:
    cfg = EpochConfig()
    assert cfg.blocks_per_epoch == 100
    assert cfg.tasks_per_epoch == 5
    assert cfg.rotation_fraction == 0.1


def test_epoch_config_custom() -> None:
    cfg = EpochConfig(blocks_per_epoch=200, tasks_per_epoch=10, rotation_fraction=0.2)
    assert cfg.blocks_per_epoch == 200
    assert cfg.tasks_per_epoch == 10
    assert cfg.rotation_fraction == 0.2


def test_epoch_config_frozen() -> None:
    cfg = EpochConfig()
    with pytest.raises(Exception):
        cfg.blocks_per_epoch = 50  # type: ignore


# ── EpochState ───────────────────────────────────────────────────────


def test_epoch_state_creation() -> None:
    state = EpochState(
        current_epoch=1,
        start_block=100,
        end_block=200,
        status=EpochStatus.ACTIVE,
        blocks_processed=0,
        tasks_completed=0,
    )
    assert state.current_epoch == 1
    assert state.start_block == 100
    assert state.end_block == 200
    assert state.status == EpochStatus.ACTIVE


def test_epoch_is_complete_true() -> None:
    state = EpochState(
        start_block=0,
        end_block=100,
        blocks_processed=100,
    )
    assert state.is_complete() is True


def test_epoch_is_complete_false() -> None:
    state = EpochState(
        start_block=0,
        end_block=100,
        blocks_processed=50,
    )
    assert state.is_complete() is False


def test_epoch_progress_zero() -> None:
    state = EpochState(
        start_block=0,
        end_block=100,
        blocks_processed=0,
    )
    assert state.progress() == 0.0


def test_epoch_progress_halfway() -> None:
    state = EpochState(
        start_block=0,
        end_block=100,
        blocks_processed=50,
    )
    assert state.progress() == 0.5


def test_epoch_progress_complete() -> None:
    state = EpochState(
        start_block=0,
        end_block=100,
        blocks_processed=100,
    )
    assert state.progress() == 1.0


def test_epoch_progress_over() -> None:
    state = EpochState(
        start_block=0,
        end_block=100,
        blocks_processed=150,
    )
    assert state.progress() == 1.0


def test_epoch_zero_blocks() -> None:
    state = EpochState(
        start_block=100,
        end_block=100,
        blocks_processed=0,
    )
    assert state.is_complete() is True
    assert state.progress() == 0.0


# ── EpochService ─────────────────────────────────────────────────────


def test_epoch_service_initialize() -> None:
    svc = EpochService()
    svc.initialize(start_block=0)
    cur = svc.get_current()
    assert cur.current_epoch == 0
    assert cur.start_block == 0
    assert cur.end_block == 100
    assert cur.status == EpochStatus.ACTIVE


def test_epoch_service_custom_config() -> None:
    cfg = EpochConfig(blocks_per_epoch=50)
    svc = EpochService(config=cfg)
    svc.initialize(start_block=10)
    cur = svc.get_current()
    assert cur.end_block == 60


def test_epoch_process_block_no_transition() -> None:
    svc = EpochService()
    svc.initialize(start_block=0)
    triggered = svc.process_block()
    assert triggered is False
    cur = svc.get_current()
    assert cur.blocks_processed == 1


def test_epoch_transition_on_complete() -> None:
    svc = EpochService(config=EpochConfig(blocks_per_epoch=3))
    svc.initialize(start_block=0)
    svc.process_block()
    svc.process_block()
    triggered = svc.process_block()
    assert triggered is True


def test_epoch_multiple_transitions() -> None:
    svc = EpochService(config=EpochConfig(blocks_per_epoch=2))
    svc.initialize(start_block=0)
    svc.process_block()
    svc.process_block()  # triggers epoch 0→1
    svc.process_block()
    svc.process_block()  # triggers epoch 1→2
    cur = svc.get_current()
    assert cur.current_epoch == 2


def test_epoch_history() -> None:
    svc = EpochService(config=EpochConfig(blocks_per_epoch=2))
    svc.initialize(start_block=0)
    svc.process_block()
    svc.process_block()  # finalize epoch 0
    history = svc.get_history()
    assert len(history) == 1
    assert history[0].current_epoch == 0
    assert history[0].status == EpochStatus.FINALIZED


def test_epoch_status_changes() -> None:
    svc = EpochService(config=EpochConfig(blocks_per_epoch=1))
    svc.initialize(start_block=0)
    assert svc.get_current().status == EpochStatus.ACTIVE
    svc.process_block()
    assert svc.get_current().status == EpochStatus.ACTIVE  # new epoch
    assert svc.get_history()[0].status == EpochStatus.FINALIZED


def test_epoch_current_copy() -> None:
    svc = EpochService()
    svc.initialize(start_block=0)
    s1 = svc.get_current()
    s2 = svc.get_current()
    assert s1 is not s2


def test_epoch_schedule_tasks() -> None:
    svc = EpochService()
    svc.schedule_epoch_tasks(epoch=0, tasks=["task-a", "task-b"])
    assert svc.get_epoch_tasks(0) == ["task-a", "task-b"]


def test_epoch_get_tasks_unknown() -> None:
    svc = EpochService()
    assert svc.get_epoch_tasks(99) == []
