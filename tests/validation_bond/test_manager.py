"""M11-S2: Validation Bond Manager — unit tests."""

from __future__ import annotations

import pytest

from aidn_hypervisor.validation_bond.manager import (
    BondInsufficientFunds,
    BondInvalidTransition,
    BondNotFoundError,
    ValidationBondManager,
)
from aidn_hypervisor.validation_bond.models import (
    RECOVERY_DECAY_FACTOR,
    VALIDATION_BOND_Q_ATOMS,
    BondEventType,
    BondStatus,
)
from aidn_hypervisor.validation_bond.store import BondStore

# ── Helpers ────────────────────────────────────────────────────────

def _make_manager() -> ValidationBondManager:
    return ValidationBondManager(store=BondStore())


# ── Lock ───────────────────────────────────────────────────────────

class TestLockBond:
    def test_lock_default_amount(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(
            endpoint_id="ep1",
            operator_wallet="0xW1",
        )
        assert bond.initial_amount == VALIDATION_BOND_Q_ATOMS
        assert bond.remaining_amount == VALIDATION_BOND_Q_ATOMS
        assert bond.status == BondStatus.LOCKED
        assert len(bond.events) == 1
        assert bond.events[0].event_type == BondEventType.LOCK

    def test_lock_custom_amount(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(
            endpoint_id="ep1",
            operator_wallet="0xW1",
            amount=1_000_000_000,
        )
        assert bond.initial_amount == 1_000_000_000

    def test_lock_insufficient_funds(self):
        mgr = _make_manager()
        with pytest.raises(BondInsufficientFunds):
            mgr.lock_bond(
                endpoint_id="ep1",
                operator_wallet="0xW1",
                amount=100,
            )

    def test_lock_duplicate_endpoint(self):
        mgr = _make_manager()
        mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        with pytest.raises(BondInvalidTransition):
            mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW2")

    def test_lock_after_terminal_ok(self):
        """Re-locking after forfeit should work."""
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.forfeit_bond(bond.bond_id, reason="test")
        # Should allow re-locking on same endpoint after terminal
        bond2 = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        assert bond2.bond_id != bond.bond_id

    def test_lock_creates_audit_event(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(
            endpoint_id="ep1",
            operator_wallet="0xW1",
            epoch=5,
        )
        assert bond.events[0].epoch == 5
        assert bond.events[0].amount_delta == VALIDATION_BOND_Q_ATOMS


# ── Activate ──────────────────────────────────────────────────────

class TestActivateBond:
    def test_activate_locked_bond(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        activated = mgr.activate_bond(bond.bond_id)
        assert activated.status == BondStatus.ACTIVE

    def test_activate_not_found(self):
        mgr = _make_manager()
        with pytest.raises(BondNotFoundError):
            mgr.activate_bond("nonexistent")

    def test_activate_already_active(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.activate_bond(bond.bond_id)
        with pytest.raises(BondInvalidTransition):
            mgr.activate_bond(bond.bond_id)

    def test_activate_forfeited_fails(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.forfeit_bond(bond.bond_id, reason="test")
        with pytest.raises(BondInvalidTransition):
            mgr.activate_bond(bond.bond_id)


# ── Recovery ──────────────────────────────────────────────────────

class TestRecoverStep:
    def test_single_recovery_step(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.activate_bond(bond.bond_id)
        recovered = mgr.recover_step(bond.bond_id)

        assert recovered.status == BondStatus.RECOVERING
        expected_recovery = int(
            VALIDATION_BOND_Q_ATOMS * RECOVERY_DECAY_FACTOR
        )
        assert recovered.recovery_count == 1
        assert recovered.recovered_total == expected_recovery
        assert recovered.remaining_amount == VALIDATION_BOND_Q_ATOMS - expected_recovery

    def test_multiple_recovery_steps(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.activate_bond(bond.bond_id)

        prev_remaining = VALIDATION_BOND_Q_ATOMS
        for i in range(5):
            recovered = mgr.recover_step(bond.bond_id)
            assert recovered.remaining_amount < prev_remaining
            assert recovered.recovery_count == i + 1
            prev_remaining = recovered.remaining_amount

    def test_recovery_from_active_auto_transitions(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.activate_bond(bond.bond_id)
        recovered = mgr.recover_step(bond.bond_id)
        assert recovered.status == BondStatus.RECOVERING

    def test_recovery_on_locked_fails(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        with pytest.raises(BondInvalidTransition):
            mgr.recover_step(bond.bond_id)

    def test_recovery_on_forfeited_fails(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.activate_bond(bond.bond_id)
        mgr.forfeit_bond(bond.bond_id, reason="test")
        with pytest.raises(BondInvalidTransition):
            mgr.recover_step(bond.bond_id)

    def test_recovery_not_found(self):
        mgr = _make_manager()
        with pytest.raises(BondNotFoundError):
            mgr.recover_step("nonexistent")

    def test_recovery_eventually_reaches_terminal(self):
        """Repeated recovery should eventually reach RECOVERED."""
        mgr = _make_manager()
        mgr._min_bond = 1  # override for fast terminal test
        bond = mgr.lock_bond(
            endpoint_id="ep1",
            operator_wallet="0xW1",
            amount=100,  # small amount to reach zero quickly
        )
        mgr.activate_bond(bond.bond_id)

        for _ in range(20):
            current = mgr.get_bond(bond.bond_id)
            if current and current.is_terminal:
                break
            mgr.recover_step(bond.bond_id)

        current = mgr.get_bond(bond.bond_id)
        assert current is not None
        assert current.status == BondStatus.RECOVERED
        assert current.remaining_amount == 0


# ── Forfeit ───────────────────────────────────────────────────────

class TestForfeitBond:
    def test_forfeit_active_bond(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.activate_bond(bond.bond_id)
        forfeited = mgr.forfeit_bond(bond.bond_id, reason="slasher")
        assert forfeited.status == BondStatus.FORFEITED
        assert len(forfeited.forfeit_records) == 1
        assert forfeited.forfeit_records[0].reason == "slasher"

    def test_forfeit_locked_bond(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        forfeited = mgr.forfeit_bond(bond.bond_id, reason="early_exit")
        assert forfeited.status == BondStatus.FORFEITED

    def test_forfeit_already_forfeited(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.forfeit_bond(bond.bond_id, reason="r1")
        with pytest.raises(BondInvalidTransition):
            mgr.forfeit_bond(bond.bond_id, reason="r2")

    def test_forfeit_not_found(self):
        mgr = _make_manager()
        with pytest.raises(BondNotFoundError):
            mgr.forfeit_bond("nonexistent", reason="test")

    def test_forfeit_records_remaining(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.activate_bond(bond.bond_id)
        # Partial recovery first
        mgr.recover_step(bond.bond_id)
        current = mgr.get_bond(bond.bond_id)
        partial_remaining = current.remaining_amount if current else 0

        forfeited = mgr.forfeit_bond(bond.bond_id, reason="test")
        assert forfeited.forfeit_records[0].forfeited_amount == partial_remaining


# ── Refund ────────────────────────────────────────────────────────

class TestRefundBond:
    def test_refund_forfeited_bond(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.forfeit_bond(bond.bond_id, reason="test")
        refunded = mgr.refund_bond(bond.bond_id)
        assert refunded is not None

    def test_refund_recovered_bond(self):
        mgr = _make_manager()
        mgr._min_bond = 1  # override for fast terminal test
        bond = mgr.lock_bond(
            endpoint_id="ep1",
            operator_wallet="0xW1",
            amount=100,
        )
        mgr.activate_bond(bond.bond_id)
        # Recover fully
        for _ in range(20):
            current = mgr.get_bond(bond.bond_id)
            if current and current.is_terminal:
                break
            mgr.recover_step(bond.bond_id)

        refunded = mgr.refund_bond(bond.bond_id)
        assert refunded is not None

    def test_refund_active_fails(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.activate_bond(bond.bond_id)
        with pytest.raises(BondInvalidTransition):
            mgr.refund_bond(bond.bond_id)

    def test_refund_not_found(self):
        mgr = _make_manager()
        with pytest.raises(BondNotFoundError):
            mgr.refund_bond("nonexistent")


# ── Queries ───────────────────────────────────────────────────────

class TestManagerQueries:
    def test_get_bond(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        found = mgr.get_bond(bond.bond_id)
        assert found is not None
        assert found.bond_id == bond.bond_id

    def test_get_bond_for_endpoint(self):
        mgr = _make_manager()
        bond = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        found = mgr.get_bond_for_endpoint("ep1")
        assert found is not None
        assert found.endpoint_id == "ep1"

    def test_get_bonds_for_wallet(self):
        mgr = _make_manager()
        mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        mgr.lock_bond(endpoint_id="ep2", operator_wallet="0xW1")
        bonds = mgr.get_bonds_for_wallet("0xW1")
        assert len(bonds) == 2

    def test_get_active_bonds(self):
        mgr = _make_manager()
        b1 = mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        b2 = mgr.lock_bond(endpoint_id="ep2", operator_wallet="0xW2")
        mgr.activate_bond(b1.bond_id)
        # b2 still locked
        active = mgr.get_active_bonds()
        assert len(active) == 1
        assert active[0].bond_id == b1.bond_id

    def test_get_total_locked(self):
        mgr = _make_manager()
        mgr.lock_bond(endpoint_id="ep1", operator_wallet="0xW1")
        b2 = mgr.lock_bond(endpoint_id="ep2", operator_wallet="0xW2")
        mgr.activate_bond(b2.bond_id)
        total = mgr.get_total_locked()
        # Only active bonds count; b1 is locked (not active)
        assert total == VALIDATION_BOND_Q_ATOMS

    def test_store_accessible(self):
        mgr = _make_manager()
        assert mgr.store is not None
