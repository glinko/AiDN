"""M11-S4: Service Pool Manager — unit tests."""

from __future__ import annotations

from aidn_hypervisor.reward.models import (
    BASE_EMISSION_Q_ATOMS,
    RewardCalculation,
    ServicePool,
)
from aidn_hypervisor.reward.pools import ServicePoolManager


class TestBudgetAllocation:
    def test_default_shares(self):
        mgr = ServicePoolManager()
        budget = mgr.allocate_budget(epoch=1)
        assert budget.consensus_pool > 0
        assert budget.registry_pool > 0
        assert budget.validation_pool > 0
        assert budget.faucet_pool > 0

    def test_total_equals_budget(self):
        mgr = ServicePoolManager()
        budget = mgr.allocate_budget(epoch=1)
        assert budget.pool_total == budget.total_budget

    def test_with_recyclable(self):
        mgr = ServicePoolManager()
        budget = mgr.allocate_budget(epoch=2, recyclable=100_000_000)
        assert budget.total_budget == BASE_EMISSION_Q_ATOMS + 100_000_000


class TestDiversityFactor:
    def test_full_diversity(self):
        mgr = ServicePoolManager()
        df = mgr.calculate_diversity(
            ServicePool.CONSENSUS,
            independent_group_count=5,
            budget=1_500_000_000,
        )
        assert df.factor == 1.0
        assert df.distributable_budget == df.nominal_budget

    def test_low_diversity(self):
        mgr = ServicePoolManager()
        df = mgr.calculate_diversity(
            ServicePool.CONSENSUS,
            independent_group_count=2,
            budget=1_500_000_000,
        )
        assert df.factor == 0.4  # 2/5
        assert df.distributable_budget < df.nominal_budget

    def test_over_target(self):
        mgr = ServicePoolManager()
        df = mgr.calculate_diversity(
            ServicePool.CONSENSUS,
            independent_group_count=10,
            budget=1_500_000_000,
        )
        # Capped at 1.0
        assert df.factor == 1.0


class TestConcentration:
    def test_within_cap(self):
        mgr = ServicePoolManager()
        gc = mgr.check_concentration(
            "kcg-1",
            ServicePool.CONSENSUS,
            group_share=0.3,
            group_reward=450_000_000,
        )
        assert gc.is_capped is False

    def test_exceeds_cap(self):
        mgr = ServicePoolManager()
        gc = mgr.check_concentration(
            "kcg-1",
            ServicePool.CONSENSUS,
            group_share=0.9,
            group_reward=1_350_000_000,
        )
        assert gc.is_capped is True
        assert gc.capped_amount > 0


class TestPoolDistribution:
    def _make_calc(self, pid: str, weight: float) -> RewardCalculation:
        return RewardCalculation(
            epoch=1,
            participant_id=pid,
            service_pool=ServicePool.CONSENSUS,
            raw_weight=weight,
            quality_factor=1.0,
            maturity_factor=1.0,
            health_factor=1.0,
            duty_proof_factor=1.0,
            reliability_factor=1.0,
            final_reward=0,
        )

    def test_single_participant(self):
        mgr = ServicePoolManager()
        mgr.add_participant(
            ServicePool.CONSENSUS, self._make_calc("s1", 100.0)
        )
        results = mgr.distribute_pool(
            ServicePool.CONSENSUS, 1_000_000_000
        )
        assert len(results) == 1
        assert results[0].final_reward == 1_000_000_000

    def test_proportional_two(self):
        mgr = ServicePoolManager()
        mgr.add_participant(
            ServicePool.CONSENSUS, self._make_calc("s1", 70.0)
        )
        mgr.add_participant(
            ServicePool.CONSENSUS, self._make_calc("s2", 30.0)
        )
        results = mgr.distribute_pool(
            ServicePool.CONSENSUS, 1_000_000_000
        )
        # s1 should get ~70%, s2 ~30%
        s1_reward = next(r.final_reward for r in results if r.participant_id == "s1")
        s2_reward = next(r.final_reward for r in results if r.participant_id == "s2")
        assert s1_reward > s2_reward

    def test_empty_pool(self):
        mgr = ServicePoolManager()
        results = mgr.distribute_pool(
            ServicePool.CONSENSUS, 1_000_000_000
        )
        assert len(results) == 0

    def test_diversity_reduces_budget(self):
        mgr = ServicePoolManager()
        mgr.add_participant(
            ServicePool.CONSENSUS, self._make_calc("s1", 100.0)
        )
        results = mgr.distribute_pool(
            ServicePool.CONSENSUS, 1_000_000_000, diversity_factor=0.5
        )
        total = sum(r.final_reward for r in results)
        assert total <= 500_000_000

    def test_clear_participants(self):
        mgr = ServicePoolManager()
        mgr.add_participant(
            ServicePool.CONSENSUS, self._make_calc("s1", 100.0)
        )
        mgr.clear_participants()
        assert len(mgr.get_pool_participants(ServicePool.CONSENSUS)) == 0

    def test_pool_total_reward(self):
        mgr = ServicePoolManager()
        mgr.add_participant(
            ServicePool.CONSENSUS, self._make_calc("s1", 100.0)
        )
        mgr.distribute_pool(ServicePool.CONSENSUS, 1_000_000_000)
        total = mgr.get_pool_total_reward(ServicePool.CONSENSUS)
        assert total == 1_000_000_000
