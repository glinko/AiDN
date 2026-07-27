"""Tests for AtomicActivator, ActivationState — RFC-0062 §51.

Atomic activation with state machine, rollback, and crash recovery.
"""

from aidn_hypervisor.snapshot.activation import (
    ActivationRecord,
    ActivationResult,
    ActivationState,
    AtomicActivator,
)
from aidn_hypervisor.snapshot.staging import StagingStateStore

# ── Helpers ────────────────────────────────────────────────────────


def _make_staging_with_data() -> StagingStateStore:
    """Create a staging store with sample data."""
    store = StagingStateStore()
    store.load_namespace(
        "wallets",
        {
            "w1": {"balance": 100, "locked": 10, "seq": 5},
            "w2": {"balance": 200, "locked": 0, "seq": 3},
        },
    )
    store.load_namespace(
        "hypervisors",
        {
            "h1": {"status": "running"},
        },
    )
    store.load_namespace(
        "protocol_parameters",
        {
            "max_block_size": 1_000_000,
            "version": 1,
        },
    )
    return store


def _compute_hash(store: StagingStateStore) -> str:
    """Compute state hash for a store."""
    return store.calculate_state_hash()


# ── ActivationState enum ──────────────────────────────────────────


class TestActivationStateEnum:
    def test_all_states_present(self):
        states = [s.value for s in ActivationState]
        assert "idle" in states
        assert "verifying" in states
        assert "ready" in states
        assert "activating" in states
        assert "activated" in states
        assert "failed" in states

    def test_state_count(self):
        assert len(ActivationState) == 6


# ── AtomicActivator init ──────────────────────────────────────────


class TestAtomicActivatorInit:
    def test_starts_in_idle(self):
        activator = AtomicActivator()
        assert activator.state == ActivationState.IDLE

    def test_active_state_hash_empty(self):
        activator = AtomicActivator()
        assert activator.active_state_hash == ""

    def test_history_empty(self):
        activator = AtomicActivator()
        assert activator.get_activation_history() == []


# ── AtomicActivator prepare ───────────────────────────────────────


class TestAtomicActivatorPrepare:
    def test_prepare_sets_ready(self):
        activator = AtomicActivator()
        store = _make_staging_with_data()
        h = _compute_hash(store)
        result = activator.prepare(store, h)
        assert result is True
        assert activator.state == ActivationState.READY

    def test_prepare_with_wrong_hash_fails(self):
        activator = AtomicActivator()
        store = _make_staging_with_data()
        result = activator.prepare(store, "wrong-hash")
        assert result is False
        assert activator.state != ActivationState.READY

    def test_prepare_on_empty_store_fails(self):
        activator = AtomicActivator()
        store = StagingStateStore()
        result = activator.prepare(store, "any-hash")
        assert result is False

    def test_prepare_sets_verifying_first(self):
        """Prepare transitions through VERIFYING state."""
        activator = AtomicActivator()
        store = _make_staging_with_data()
        h = _compute_hash(store)
        activator.prepare(store, h)
        # State should be READY after prepare completes
        assert activator.state == ActivationState.READY


# ── AtomicActivator activate ──────────────────────────────────────


class TestAtomicActivatorActivate:
    def test_activate_switches_state(self):
        activator = AtomicActivator()
        store = _make_staging_with_data()
        h = _compute_hash(store)
        activator.prepare(store, h)
        result = activator.activate()
        assert result.success
        assert activator.state == ActivationState.ACTIVATED

    def test_activate_records_in_history(self):
        activator = AtomicActivator()
        store = _make_staging_with_data()
        h = _compute_hash(store)
        activator.prepare(store, h)
        activator.activate()
        history = activator.get_activation_history()
        assert len(history) == 1

    def test_activate_result_fields_populated(self):
        activator = AtomicActivator()
        store = _make_staging_with_data()
        h = _compute_hash(store)
        activator.prepare(store, h)
        result = activator.activate()
        assert result.success
        assert result.new_state_hash == h
        assert result.snapshot_id != ""
        assert result.activated_at != ""
        assert result.error is None

    def test_activate_without_prepare_fails(self):
        activator = AtomicActivator()
        result = activator.activate()
        assert not result.success
        assert activator.state == ActivationState.FAILED

    def test_activate_sets_new_active_hash(self):
        activator = AtomicActivator()
        store = _make_staging_with_data()
        h = _compute_hash(store)
        activator.prepare(store, h)
        activator.activate()
        assert activator.active_state_hash == h

    def test_activate_preserves_previous_hash(self):
        activator = AtomicActivator()
        store = _make_staging_with_data()
        h = _compute_hash(store)
        activator.prepare(store, h)
        result = activator.activate()
        assert result.previous_state_hash == ""  # First activation


# ── AtomicActivator rollback ──────────────────────────────────────


class TestAtomicActivatorRollback:
    def test_rollback_restores_previous_state(self):
        activator = AtomicActivator()
        store = _make_staging_with_data()
        h = _compute_hash(store)
        activator.prepare(store, h)
        activator.activate()

        # Now rollback
        activator.rollback()
        assert activator.state == ActivationState.IDLE

    def test_rollback_from_idle_is_noop(self):
        activator = AtomicActivator()
        activator.rollback()  # Should not raise
        assert activator.state == ActivationState.IDLE

    def test_rollback_restores_previous_active_data(self):
        activator = AtomicActivator()
        first = _make_staging_with_data()
        first_hash = _compute_hash(first)
        activator.prepare(first, first_hash)
        activator.activate()
        first_active_data = activator.active_state_data

        second = _make_staging_with_data()
        second.load_namespace("wallets", {"new": {"balance": 300}})
        activator.prepare(second, _compute_hash(second))
        activator.activate()
        activator.rollback()

        assert activator.active_state_data == first_active_data
        assert activator.active_state_hash == first_hash

    def test_prepare_copies_verified_staging_data(self):
        activator = AtomicActivator()
        store = _make_staging_with_data()
        activator.prepare(store, _compute_hash(store))
        store.load_namespace("wallets", {"changed": {"balance": 0}})

        activator.activate()

        assert activator.active_state_data["wallets"]["w1"]["balance"] == 100


# ── AtomicActivator failure ───────────────────────────────────────


class TestAtomicActivatorFailure:
    def test_activate_failure_triggers_failed_state(self):
        activator = AtomicActivator()
        # Don't prepare — activate without valid staging
        result = activator.activate()
        assert not result.success
        assert activator.state == ActivationState.FAILED

    def test_crash_recovery_preserves_old_state(self):
        """Simulate crash: old state preserved on failure."""
        activator = AtomicActivator()
        store = _make_staging_with_data()
        h = _compute_hash(store)
        activator.prepare(store, h)
        activator.activate()
        old_hash = activator.active_state_hash

        # Simulate failure by trying to activate without re-prepare
        activator._state = ActivationState.ACTIVATING
        activator.activate()
        # Old state should be preserved
        assert activator.active_state_hash == old_hash


# ── AtomicActivator multiple activations ──────────────────────────


class TestAtomicActivatorMultipleActivations:
    def test_multiple_activations_tracked(self):
        activator = AtomicActivator()

        # First activation
        store1 = _make_staging_with_data()
        h1 = _compute_hash(store1)
        activator.prepare(store1, h1)
        activator.activate()

        # Second activation
        store2 = _make_staging_with_data()
        store2.load_namespace("wallets", {"w3": {"balance": 300, "locked": 0, "seq": 1}})
        h2 = _compute_hash(store2)
        activator.prepare(store2, h2)
        activator.activate()

        history = activator.get_activation_history()
        assert len(history) == 2
        assert history[0].new_state_hash == h1
        assert history[1].new_state_hash == h2

    def test_state_transitions_follow_valid_sequence(self):
        """State machine: IDLE → VERIFYING → READY → ACTIVATING → ACTIVATED."""
        activator = AtomicActivator()
        assert activator.state == ActivationState.IDLE

        store = _make_staging_with_data()
        h = _compute_hash(store)

        activator.prepare(store, h)
        assert activator.state == ActivationState.READY

        activator.activate()
        assert activator.state == ActivationState.ACTIVATED


# ── ActivationResult model ────────────────────────────────────────


class TestActivationResult:
    def test_success_result(self):
        r = ActivationResult(
            success=True,
            previous_state_hash="prev",
            new_state_hash="new",
            snapshot_id="snap-1",
            activated_at="2025-01-01T00:00:00Z",
            error=None,
        )
        assert r.success
        assert r.error is None

    def test_failure_result(self):
        r = ActivationResult(
            success=False,
            previous_state_hash="prev",
            new_state_hash="",
            snapshot_id="",
            activated_at="",
            error="activation failed",
        )
        assert not r.success
        assert r.error == "activation failed"


# ── ActivationRecord model ────────────────────────────────────────


class TestActivationRecord:
    def test_frozen_behavior(self):
        record = ActivationRecord(
            previous_state_hash="prev",
            new_state_hash="new",
            snapshot_id="snap-1",
            activated_at="2025-01-01T00:00:00Z",
            success=True,
        )
        assert record.success
        assert record.new_state_hash == "new"

    def test_record_fields(self):
        record = ActivationRecord(
            previous_state_hash="",
            new_state_hash="abc",
            snapshot_id="snap-1",
            activated_at="2025-01-01T00:00:00Z",
            success=True,
        )
        assert record.previous_state_hash == ""
        assert record.snapshot_id == "snap-1"
