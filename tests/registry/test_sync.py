"""Tests for registry/sync — Sync Modes + Controller (RFC-0061 §§41-46)."""

from __future__ import annotations

import pytest

from aidn_hypervisor.registry import ImmutableObjectStore, RegistryObjectEnvelope
from aidn_hypervisor.registry.sync import (
    SyncController,
    SyncMode,
    SyncState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_envelope(
    object_id: str | None = None,
    object_type: str = "test",
    payload: dict | None = None,
    created_epoch: int | None = None,
) -> RegistryObjectEnvelope:
    return RegistryObjectEnvelope.create(
        object_type=object_type,
        payload=payload or {"data": "test"},
        object_id=object_id,
        created_epoch=created_epoch,
    )


def _make_store() -> ImmutableObjectStore:
    return ImmutableObjectStore()


def _make_controller(store: ImmutableObjectStore | None = None) -> SyncController:
    return SyncController(store or _make_store())


# ---------------------------------------------------------------------------
# SyncMode enum
# ---------------------------------------------------------------------------


def test_sync_mode_enum():
    """SyncMode has all expected values."""
    assert SyncMode.INITIAL == "initial"
    assert SyncMode.CATCH_UP == "catch_up"
    assert SyncMode.LIVE == "live"
    assert SyncMode.REPAIR == "repair"
    assert SyncMode.ARCHIVE == "archive"


# ---------------------------------------------------------------------------
# SyncState model
# ---------------------------------------------------------------------------


def test_sync_state_creation():
    """SyncState creates with defaults."""
    s = SyncState()
    assert s.mode == SyncMode.INITIAL
    assert s.peer_id == ""
    assert s.objects_synced == 0
    assert s.bytes_synced == 0
    assert s.current_epoch == 0
    assert s.target_epoch == 0
    assert s.progress == 0.0
    assert s.error is None
    assert s.completed is False


def test_sync_state_model():
    """SyncState is a proper Pydantic model."""
    s = SyncState(
        mode=SyncMode.CATCH_UP,
        peer_id="peer-1",
        current_epoch=5,
        target_epoch=10,
        progress=0.5,
    )
    assert s.mode == SyncMode.CATCH_UP
    assert s.peer_id == "peer-1"
    assert s.current_epoch == 5
    assert s.target_epoch == 10
    assert s.progress == 0.5


# ---------------------------------------------------------------------------
# SyncController init
# ---------------------------------------------------------------------------


def test_sync_controller_init():
    """Controller initializes with default state."""
    ctrl = _make_controller()
    s = ctrl.state
    assert s.mode == SyncMode.INITIAL
    assert s.completed is False


def test_sync_controller_engine():
    """Controller exposes its replication engine."""
    ctrl = _make_controller()
    assert ctrl.engine is not None
    assert ctrl.engine.active_transfers == 0


# ---------------------------------------------------------------------------
# §42 — Initial sync
# ---------------------------------------------------------------------------


def test_start_initial_sync():
    """Start initial sync sets correct state."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="genesis-peer", target_epoch=100)

    s = ctrl.state
    assert s.mode == SyncMode.INITIAL
    assert s.peer_id == "genesis-peer"
    assert s.target_epoch == 100
    assert s.current_epoch == 0


# ---------------------------------------------------------------------------
# §43 — Catch-up sync
# ---------------------------------------------------------------------------


def test_start_catch_up_sync():
    """Start catch-up sync from a specific epoch."""
    ctrl = _make_controller()
    ctrl.start_catch_up_sync(peer_id="peer-a", from_epoch=50, target_epoch=100)

    s = ctrl.state
    assert s.mode == SyncMode.CATCH_UP
    assert s.peer_id == "peer-a"
    assert s.current_epoch == 50
    assert s.target_epoch == 100


# ---------------------------------------------------------------------------
# §44 — Live sync
# ---------------------------------------------------------------------------


def test_start_live_sync():
    """Start live replication mode."""
    ctrl = _make_controller()
    ctrl.start_live_sync(peer_id="live-peer")

    s = ctrl.state
    assert s.mode == SyncMode.LIVE
    assert s.peer_id == "live-peer"
    assert s.target_epoch == 0


# ---------------------------------------------------------------------------
# §45 — Repair sync
# ---------------------------------------------------------------------------


def test_start_repair_sync():
    """Start repair sync for detected gaps."""
    ctrl = _make_controller()
    ctrl.start_repair_sync(peer_id="repair-peer", missing_object_ids=["obj-1"])

    s = ctrl.state
    assert s.mode == SyncMode.REPAIR
    assert s.peer_id == "repair-peer"


def test_repair_sync_mode():
    """Repair sync mode is set correctly."""
    ctrl = _make_controller()
    ctrl.start_repair_sync(peer_id="repair-peer")
    assert ctrl.state.mode == SyncMode.REPAIR


# ---------------------------------------------------------------------------
# Epoch sync
# ---------------------------------------------------------------------------


def test_sync_epoch():
    """Sync a single epoch of objects."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=5)

    envs = [
        _make_envelope(object_id="e1", created_epoch=1),
        _make_envelope(object_id="e2", created_epoch=1),
    ]
    ok = ctrl.sync_epoch(epoch=1, objects=envs)
    assert ok is True

    s = ctrl.state
    assert s.current_epoch == 1
    assert s.objects_synced == 2


def test_sync_epoch_objects():
    """Synced objects are stored in the store."""
    ctrl = _make_controller()
    envs = [_make_envelope(object_id="obj-1", created_epoch=1)]
    ctrl.sync_epoch(epoch=1, objects=envs)

    assert ctrl._store.has("obj-1")


def test_sync_epoch_updates_progress():
    """Progress updates as epochs are synced."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=10)

    envs = [_make_envelope(object_id="e1", created_epoch=5)]
    ctrl.sync_epoch(epoch=5, objects=envs)

    s = ctrl.state
    assert 0.0 < s.progress <= 1.0


def test_sync_epoch_completes():
    """Syncing to target epoch marks sync as complete."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=3)

    for epoch in range(1, 4):
        envs = [_make_envelope(object_id=f"e{epoch}", created_epoch=epoch)]
        ctrl.sync_epoch(epoch=epoch, objects=envs)

    assert ctrl.state.completed is True


def test_sync_epoch_empty():
    """Syncing an epoch with no valid objects still works."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=5)

    ok = ctrl.sync_epoch(epoch=1, objects=[])
    assert ok is True
    assert ctrl.state.objects_synced == 0


def test_sync_epoch_empty_dicts():
    """Syncing dicts (not envelopes) skips them gracefully."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=5)

    ok = ctrl.sync_epoch(epoch=1, objects=[{"key": "value"}])
    assert ok is True
    assert ctrl.state.objects_synced == 0


def test_sync_bytes_counted():
    """Bytes are counted correctly during epoch sync."""
    ctrl = _make_controller()
    env = _make_envelope(object_id="big-obj", created_epoch=1)
    ctrl.sync_epoch(epoch=1, objects=[env])

    s = ctrl.state
    assert s.bytes_synced == env.content_size


def test_sync_multiple_epochs():
    """Sync multiple epochs sequentially."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=5)

    for epoch in range(1, 6):
        envs = [_make_envelope(object_id=f"e{epoch}", created_epoch=epoch)]
        ctrl.sync_epoch(epoch=epoch, objects=envs)

    s = ctrl.state
    assert s.current_epoch == 5
    assert s.objects_synced == 5
    assert s.completed is True


def test_catch_up_progression():
    """Catch-up sync progresses from from_epoch to target."""
    ctrl = _make_controller()
    ctrl.start_catch_up_sync(peer_id="peer-a", from_epoch=10, target_epoch=15)

    for epoch in range(11, 16):
        envs = [_make_envelope(object_id=f"e{epoch}", created_epoch=epoch)]
        ctrl.sync_epoch(epoch=epoch, objects=envs)

    assert ctrl.state.completed is True
    assert ctrl.state.current_epoch == 15


# ---------------------------------------------------------------------------
# Sync completion
# ---------------------------------------------------------------------------


def test_record_sync_complete():
    """Manually record sync completion."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=10)
    ctrl.record_sync_complete()

    assert ctrl.state.completed is True
    history = ctrl.get_sync_history()
    assert len(history) >= 1


# ---------------------------------------------------------------------------
# Sync history
# ---------------------------------------------------------------------------


def test_get_sync_history():
    """Sync history accumulates completed snapshots."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=2)

    ctrl.sync_epoch(epoch=1, objects=[_make_envelope(object_id="e1", created_epoch=1)])
    ctrl.sync_epoch(epoch=2, objects=[_make_envelope(object_id="e2", created_epoch=2)])

    history = ctrl.get_sync_history()
    assert len(history) >= 1


def test_sync_history_preserved():
    """History entries are independent copies."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=1)
    ctrl.sync_epoch(epoch=1, objects=[_make_envelope(object_id="e1", created_epoch=1)])

    # Modify state after history was recorded
    ctrl._state.objects_synced = 999

    history = ctrl.get_sync_history()
    assert len(history) >= 1
    # History entry should have original count
    assert history[0].objects_synced != 999


# ---------------------------------------------------------------------------
# Switch to live
# ---------------------------------------------------------------------------


def test_switch_to_live():
    """Switch from initial to live mode."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=10)

    ctrl.sync_epoch(epoch=5, objects=[_make_envelope(object_id="e5", created_epoch=5)])

    ctrl.switch_to_live()

    s = ctrl.state
    assert s.mode == SyncMode.LIVE
    assert s.peer_id == "peer-a"


def test_initial_sync_to_live():
    """Full flow: initial sync → switch to live."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=3)

    for epoch in range(1, 4):
        ctrl.sync_epoch(epoch=epoch, objects=[_make_envelope(object_id=f"e{epoch}", created_epoch=epoch)])

    ctrl.switch_to_live()
    assert ctrl.state.mode == SyncMode.LIVE
    assert ctrl.state.current_epoch == 3


def test_switch_to_live_preserves_counts():
    """Switching to live preserves synced counts."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=5)

    for epoch in range(1, 6):
        ctrl.sync_epoch(epoch=epoch, objects=[_make_envelope(object_id=f"e{epoch}", created_epoch=epoch)])

    ctrl.switch_to_live()

    s = ctrl.state
    assert s.objects_synced == 5
    assert s.bytes_synced > 0


# ---------------------------------------------------------------------------
# Lag calculations
# ---------------------------------------------------------------------------


def test_get_lag():
    """Lag is target - current epoch."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=10)
    ctrl.sync_epoch(epoch=3, objects=[])

    assert ctrl.get_lag() == 7


def test_get_lag_zero():
    """Lag is zero when target is 0 (live mode)."""
    ctrl = _make_controller()
    ctrl.start_live_sync(peer_id="live-peer")
    assert ctrl.get_lag() == 0


# ---------------------------------------------------------------------------
# Sync state copy
# ---------------------------------------------------------------------------


def test_sync_state_copy():
    """State property returns a copy, not the internal reference."""
    ctrl = _make_controller()
    ctrl.start_initial_sync(peer_id="peer-a", target_epoch=10)

    s1 = ctrl.state
    s1.peer_id = "modified"

    s2 = ctrl.state
    assert s2.peer_id == "peer-a"  # internal state unchanged
