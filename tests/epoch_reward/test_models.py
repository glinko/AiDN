"""M11-S5: Epoch reward models — unit tests."""

from __future__ import annotations

from aidn_hypervisor.epoch_reward.models import (
    EmissionRecord,
    EpochTransitionRecord,
    EpochTransitionState,
    FaucetAllocation,
    FaucetRecipient,
    RecyclableRecord,
    RecyclingSource,
    RecyclingStatus,
)


class TestRecyclingSource:
    def test_all_sources(self):
        assert len(RecyclingSource) == 5


class TestRecyclingStatus:
    def test_all_statuses(self):
        assert len(RecyclingStatus) == 3


class TestRecyclableRecord:
    def test_create(self):
        r = RecyclableRecord(
            source=RecyclingSource.BOND_FORFEIT,
            amount=500_000_000,
            epoch_removed=5,
        )
        assert r.status == RecyclingStatus.PENDING
        assert r.epoch_recycled is None

    def test_recycled(self):
        r = RecyclableRecord(
            source=RecyclingSource.BOND_FORFEIT,
            amount=500_000_000,
            epoch_removed=5,
            epoch_recycled=8,
            status=RecyclingStatus.RECYCLED,
        )
        assert r.status == RecyclingStatus.RECYCLED


class TestFaucetAllocation:
    def test_create(self):
        fa = FaucetAllocation(
            epoch=1,
            total_faucet_budget=500_000_000,
            allocated_amount=300_000_000,
            unallocated_amount=200_000_000,
            per_wallet_limit=100_000_000,
            per_kcg_limit=500_000_000,
        )
        assert fa.unallocated_amount == 200_000_000

    def test_with_recipients(self):
        fa = FaucetAllocation(
            epoch=1,
            total_faucet_budget=500_000_000,
            allocated_amount=200_000_000,
            unallocated_amount=300_000_000,
            per_wallet_limit=100_000_000,
            per_kcg_limit=500_000_000,
            allocations=[
                FaucetRecipient(wallet="0xW1", amount=100_000_000),
                FaucetRecipient(wallet="0xW2", amount=100_000_000),
            ],
        )
        assert len(fa.allocations) == 2


class TestEmissionRecord:
    def test_create(self):
        er = EmissionRecord(
            epoch=1,
            base_emission=5_000_000_000,
            recyclable_amount=0,
            total_budget=5_000_000_000,
            consensus_allocated=1_500_000_000,
            registry_allocated=1_500_000_000,
            validation_allocated=1_500_000_000,
            faucet_allocated=500_000_000,
            total_minted=5_000_000_000,
            unused_base=0,
            unused_recyclable=0,
        )
        assert er.total_minted == er.total_budget


class TestEpochTransitionRecord:
    def test_create(self):
        from aidn_hypervisor.epoch_reward.models import EmissionRecord

        tr = EpochTransitionRecord(
            epoch=1,
            started_at_epoch=1,
            state=EpochTransitionState.IN_PROGRESS,
            budget=EmissionRecord(
                epoch=1,
                base_emission=5_000_000_000,
                recyclable_amount=0,
                total_budget=5_000_000_000,
                consensus_allocated=0,
                registry_allocated=0,
                validation_allocated=0,
                faucet_allocated=0,
                total_minted=0,
                unused_base=0,
                unused_recyclable=0,
            ),
        )
        assert tr.state == EpochTransitionState.IN_PROGRESS
