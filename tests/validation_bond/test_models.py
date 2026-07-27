"""M11-S2: Validation Bond models — unit tests."""

from __future__ import annotations

import pytest

from aidn_hypervisor.validation_bond.models import (
    RECOVERY_DECAY_FACTOR,
    VALIDATION_BOND_Q_ATOMS,
    BondEvent,
    BondEventType,
    BondForfeitRecord,
    BondRecoveryRecord,
    BondStatus,
    ValidationBond,
)

# ── Constants ──────────────────────────────────────────────────────

SAMPLE_BOND_ID = "bond-001"
SAMPLE_ENDPOINT = "ep-001"
SAMPLE_WALLET = "0xWALLET"
NOW = "2026-07-26T22:00:00+00:00"


def _make_bond(
    status: BondStatus = BondStatus.LOCKED,
    remaining: int | None = None,
    recovery_records: list[BondRecoveryRecord] | None = None,
    forfeit_records: list[BondForfeitRecord] | None = None,
) -> ValidationBond:
    return ValidationBond(
        bond_id=SAMPLE_BOND_ID,
        endpoint_id=SAMPLE_ENDPOINT,
        operator_wallet=SAMPLE_WALLET,
        initial_amount=VALIDATION_BOND_Q_ATOMS,
        remaining_amount=remaining if remaining is not None else VALIDATION_BOND_Q_ATOMS,
        status=status,
        created_at=NOW,
        recovery_records=recovery_records or [],
        forfeit_records=forfeit_records or [],
    )


# ── Enum tests ─────────────────────────────────────────────────────

class TestBondStatus:
    def test_has_all_states(self):
        states = [
            BondStatus.LOCKED,
            BondStatus.ACTIVE,
            BondStatus.RECOVERING,
            BondStatus.FORFEITED,
            BondStatus.RECOVERED,
        ]
        assert len(states) == 5
        assert BondStatus.LOCKED.value == "locked"
        assert BondStatus.ACTIVE.value == "active"
        assert BondStatus.RECOVERING.value == "recovering"
        assert BondStatus.FORFEITED.value == "forfeited"
        assert BondStatus.RECOVERED.value == "recovered"

    def test_from_string(self):
        assert BondStatus("locked") == BondStatus.LOCKED
        assert BondStatus("active") == BondStatus.ACTIVE


class TestBondEventType:
    def test_has_all_types(self):
        types = [
            BondEventType.LOCK,
            BondEventType.ACTIVATE,
            BondEventType.RECOVER,
            BondEventType.FORFEIT,
            BondEventType.REFUND,
        ]
        assert len(types) == 5


# ── Constants ──────────────────────────────────────────────────────

class TestConstants:
    def test_validation_bond_amount(self):
        assert VALIDATION_BOND_Q_ATOMS == 500_000_000

    def test_recovery_decay_factor(self):
        assert RECOVERY_DECAY_FACTOR == 0.5


# ── Recovery Record ────────────────────────────────────────────────

class TestBondRecoveryRecord:
    def test_create(self):
        record = BondRecoveryRecord(
            recovery_id="rec-1",
            bond_id=SAMPLE_BOND_ID,
            recovery_amount=250_000_000,
            remaining_after=250_000_000,
            step_number=1,
            epoch=1,
            timestamp=NOW,
        )
        assert record.step_number == 1
        assert record.recovery_percentage == 50.0

    def test_recovery_percentage_zero_remaining(self):
        record = BondRecoveryRecord(
            recovery_id="rec-2",
            bond_id=SAMPLE_BOND_ID,
            recovery_amount=100,
            remaining_after=0,
            step_number=1,
            epoch=1,
            timestamp=NOW,
        )
        assert record.recovery_percentage == 100.0

    def test_recovery_percentage_edge_case(self):
        """When remaining_after + recovery_amount == 0."""
        record = BondRecoveryRecord(
            recovery_id="rec-3",
            bond_id=SAMPLE_BOND_ID,
            recovery_amount=0,
            remaining_after=0,
            step_number=1,
            epoch=1,
            timestamp=NOW,
        )
        assert record.recovery_percentage == 0.0

    def test_frozen(self):
        record = BondRecoveryRecord(
            recovery_id="rec-4",
            bond_id=SAMPLE_BOND_ID,
            recovery_amount=100,
            remaining_after=200,
            step_number=1,
            epoch=1,
            timestamp=NOW,
        )
        with pytest.raises(Exception):
            record.recovery_amount = 999  # type: ignore


# ── Forfeit Record ────────────────────────────────────────────────

class TestBondForfeitRecord:
    def test_create(self):
        record = BondForfeitRecord(
            forfeit_id="f-1",
            bond_id=SAMPLE_BOND_ID,
            forfeited_amount=500_000_000,
            reason="validation_failure",
            epoch=5,
            timestamp=NOW,
        )
        assert record.forfeited_amount == 500_000_000
        assert record.reason == "validation_failure"

    def test_frozen(self):
        record = BondForfeitRecord(
            forfeit_id="f-2",
            bond_id=SAMPLE_BOND_ID,
            forfeited_amount=100,
            reason="test",
            epoch=1,
            timestamp=NOW,
        )
        with pytest.raises(Exception):
            record.reason = "changed"  # type: ignore


# ── Bond Event ────────────────────────────────────────────────────

class TestBondEvent:
    def test_create(self):
        event = BondEvent(
            event_id="evt-1",
            bond_id=SAMPLE_BOND_ID,
            event_type=BondEventType.LOCK,
            amount_delta=500_000_000,
            epoch=0,
            timestamp=NOW,
        )
        assert event.amount_delta == 500_000_000

    def test_negative_delta(self):
        event = BondEvent(
            event_id="evt-2",
            bond_id=SAMPLE_BOND_ID,
            event_type=BondEventType.RECOVER,
            amount_delta=-250_000_000,
            epoch=1,
            timestamp=NOW,
        )
        assert event.amount_delta == -250_000_000

    def test_default_metadata(self):
        event = BondEvent(
            event_id="evt-3",
            bond_id=SAMPLE_BOND_ID,
            event_type=BondEventType.LOCK,
            amount_delta=0,
            epoch=0,
            timestamp=NOW,
        )
        assert event.metadata == {}

    def test_custom_metadata(self):
        event = BondEvent(
            event_id="evt-4",
            bond_id=SAMPLE_BOND_ID,
            event_type=BondEventType.LOCK,
            amount_delta=0,
            epoch=0,
            timestamp=NOW,
            metadata={"note": "test"},
        )
        assert event.metadata["note"] == "test"


# ── Validation Bond ───────────────────────────────────────────────

class TestValidationBond:
    def test_default_creation(self):
        bond = ValidationBond(
            bond_id=SAMPLE_BOND_ID,
            endpoint_id=SAMPLE_ENDPOINT,
            operator_wallet=SAMPLE_WALLET,
            created_at=NOW,
        )
        assert bond.initial_amount == VALIDATION_BOND_Q_ATOMS
        assert bond.remaining_amount == VALIDATION_BOND_Q_ATOMS
        assert bond.status == BondStatus.LOCKED
        assert bond.recovery_count == 0

    def test_custom_amount(self):
        bond = ValidationBond(
            bond_id=SAMPLE_BOND_ID,
            endpoint_id=SAMPLE_ENDPOINT,
            operator_wallet=SAMPLE_WALLET,
            initial_amount=1_000_000_000,
            remaining_amount=1_000_000_000,
            created_at=NOW,
        )
        assert bond.initial_amount == 1_000_000_000

    # ── Computed fields ────────────────────────────────────────

    def test_forfeited_total_empty(self):
        bond = _make_bond()
        assert bond.forfeited_total == 0

    def test_forfeited_total_with_records(self):
        records = [
            BondForfeitRecord(
                forfeit_id="f1",
                bond_id=SAMPLE_BOND_ID,
                forfeited_amount=300_000_000,
                reason="r1",
                epoch=1,
                timestamp=NOW,
            ),
            BondForfeitRecord(
                forfeit_id="f2",
                bond_id=SAMPLE_BOND_ID,
                forfeited_amount=200_000_000,
                reason="r2",
                epoch=2,
                timestamp=NOW,
            ),
        ]
        bond = _make_bond(forfeit_records=records)
        assert bond.forfeited_total == 500_000_000

    def test_recovered_total_empty(self):
        bond = _make_bond()
        assert bond.recovered_total == 0

    def test_recovered_total_with_records(self):
        records = [
            BondRecoveryRecord(
                recovery_id="r1",
                bond_id=SAMPLE_BOND_ID,
                recovery_amount=250_000_000,
                remaining_after=250_000_000,
                step_number=1,
                epoch=1,
                timestamp=NOW,
            ),
        ]
        bond = _make_bond(recovery_records=records)
        assert bond.recovered_total == 250_000_000

    # ── is_active ──────────────────────────────────────────────

    def test_is_active_locked(self):
        bond = _make_bond(status=BondStatus.LOCKED)
        assert bond.is_active is False

    def test_is_active_active(self):
        bond = _make_bond(status=BondStatus.ACTIVE)
        assert bond.is_active is True

    def test_is_active_recovering(self):
        bond = _make_bond(status=BondStatus.RECOVERING)
        assert bond.is_active is True

    def test_is_active_forfeited(self):
        bond = _make_bond(status=BondStatus.FORFEITED)
        assert bond.is_active is False

    def test_is_active_recovered(self):
        bond = _make_bond(status=BondStatus.RECOVERED)
        assert bond.is_active is False

    # ── is_terminal ────────────────────────────────────────────

    def test_is_terminal_locked(self):
        bond = _make_bond(status=BondStatus.LOCKED)
        assert bond.is_terminal is False

    def test_is_terminal_active(self):
        bond = _make_bond(status=BondStatus.ACTIVE)
        assert bond.is_terminal is False

    def test_is_terminal_forfeited(self):
        bond = _make_bond(status=BondStatus.FORFEITED)
        assert bond.is_terminal is True

    def test_is_terminal_recovered(self):
        bond = _make_bond(status=BondStatus.RECOVERED)
        assert bond.is_terminal is True

    # ── bond_health ────────────────────────────────────────────

    def test_health_full(self):
        bond = _make_bond()
        assert bond.bond_health == 1.0

    def test_health_half(self):
        bond = _make_bond(remaining=250_000_000)
        assert bond.bond_health == 0.5

    def test_health_zero(self):
        bond = _make_bond(remaining=0)
        assert bond.bond_health == 0.0

    def test_health_zero_initial(self):
        bond = ValidationBond(
            bond_id=SAMPLE_BOND_ID,
            endpoint_id=SAMPLE_ENDPOINT,
            operator_wallet=SAMPLE_WALLET,
            initial_amount=0,
            remaining_amount=0,
            created_at=NOW,
        )
        assert bond.bond_health == 0.0

    # ── State transitions ─────────────────────────────────────

    def test_activate_from_locked(self):
        bond = _make_bond(status=BondStatus.LOCKED)
        activated = bond.activate()
        assert activated.status == BondStatus.ACTIVE
        assert len(activated.events) == 1

    def test_activate_fails_from_active(self):
        bond = _make_bond(status=BondStatus.ACTIVE)
        with pytest.raises(ValueError, match="Cannot activate"):
            bond.activate()

    def test_activate_fails_from_forfeited(self):
        bond = _make_bond(status=BondStatus.FORFEITED)
        with pytest.raises(ValueError, match="Cannot activate"):
            bond.activate()

    def test_start_recovery_from_active(self):
        bond = _make_bond(status=BondStatus.ACTIVE)
        recovering = bond.start_recovery()
        assert recovering.status == BondStatus.RECOVERING

    def test_start_recovery_from_recovering(self):
        bond = _make_bond(status=BondStatus.RECOVERING)
        still_recovering = bond.start_recovery()
        assert still_recovering.status == BondStatus.RECOVERING

    def test_start_recovery_fails_from_locked(self):
        bond = _make_bond(status=BondStatus.LOCKED)
        with pytest.raises(ValueError, match="Cannot start recovery"):
            bond.start_recovery()

    def test_start_recovery_fails_from_forfeited(self):
        bond = _make_bond(status=BondStatus.FORFEITED)
        with pytest.raises(ValueError, match="Cannot start recovery"):
            bond.start_recovery()

    # ── Frozen model ──────────────────────────────────────────

    def test_frozen(self):
        bond = _make_bond()
        with pytest.raises(Exception):
            bond.status = BondStatus.ACTIVE  # type: ignore

    def test_model_copy_works(self):
        bond = _make_bond()
        updated = bond.model_copy(update={"status": BondStatus.ACTIVE})
        assert updated.status == BondStatus.ACTIVE
        assert bond.status == BondStatus.LOCKED  # original unchanged
