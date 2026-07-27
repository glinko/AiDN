"""M11-S5: Recycling Engine — unit tests."""

from __future__ import annotations

from aidn_hypervisor.epoch_reward.models import (
    RecyclingSource,
    RecyclingStatus,
)
from aidn_hypervisor.epoch_reward.recycling import RecyclingEngine


class TestAddSource:
    def test_add_bond_forfeit(self):
        engine = RecyclingEngine()
        record = engine.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        assert record.amount == 500_000_000
        assert record.status == RecyclingStatus.PENDING

    def test_add_multiple(self):
        engine = RecyclingEngine()
        engine.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        engine.add_source(RecyclingSource.VALIDATOR_PENALTY, 200_000_000, 2)
        assert engine.record_count == 2

    def test_pending_amount(self):
        engine = RecyclingEngine(max_recycle_lag=3)
        engine.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        engine.add_source(RecyclingSource.BOND_FORFEIT, 300_000_000, 2)
        assert engine.get_pending_amount(3) == 800_000_000


class TestRecycle:
    def test_recycle_eligible(self):
        engine = RecyclingEngine(max_recycle_lag=3)
        engine.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        recycled = engine.recycle_eligible(3)
        assert len(recycled) == 1
        assert recycled[0].status == RecyclingStatus.RECYCLED

    def test_recycle_multiple(self):
        engine = RecyclingEngine(max_recycle_lag=5)
        engine.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        engine.add_source(RecyclingSource.VALIDATOR_PENALTY, 200_000_000, 2)
        recycled = engine.recycle_eligible(5)
        assert len(recycled) == 2

    def test_total_recycled(self):
        engine = RecyclingEngine(max_recycle_lag=3)
        engine.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        engine.add_source(RecyclingSource.BOND_FORFEIT, 300_000_000, 2)
        engine.recycle_eligible(3)
        assert engine.get_total_recycled() == 800_000_000


class TestExpire:
    def test_expire_overdue(self):
        engine = RecyclingEngine(max_recycle_lag=3)
        engine.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        expired = engine.expire_overdue(5)
        assert len(expired) == 1
        assert expired[0].status == RecyclingStatus.EXPIRED

    def test_no_expire_within_window(self):
        engine = RecyclingEngine(max_recycle_lag=5)
        engine.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        expired = engine.expire_overdue(4)
        assert len(expired) == 0

    def test_backlog_decreases_on_expire(self):
        engine = RecyclingEngine(max_recycle_lag=3)
        engine.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        assert engine.get_backlog() == 500_000_000
        engine.expire_overdue(5)
        assert engine.get_backlog() == 0


class TestQueries:
    def test_records_by_source(self):
        engine = RecyclingEngine()
        engine.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        engine.add_source(RecyclingSource.VALIDATOR_PENALTY, 200_000_000, 2)
        bond_records = engine.get_records_by_source(RecyclingSource.BOND_FORFEIT)
        assert len(bond_records) == 1

    def test_records_for_epoch(self):
        engine = RecyclingEngine()
        engine.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        engine.add_source(RecyclingSource.BOND_FORFEIT, 300_000_000, 2)
        epoch1 = engine.get_records_for_epoch(1)
        assert len(epoch1) == 1

    def test_backlog(self):
        engine = RecyclingEngine()
        engine.add_source(RecyclingSource.BOND_FORFEIT, 500_000_000, 1)
        engine.add_source(RecyclingSource.BOND_FORFEIT, 300_000_000, 2)
        assert engine.get_backlog() == 800_000_000
