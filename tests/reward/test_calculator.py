"""M11-S4: Reward Calculator — unit tests."""

from __future__ import annotations

from aidn_hypervisor.reward.calculator import RewardCalculator
from aidn_hypervisor.reward.models import ServicePool


class TestMaturityFactor:
    def test_zero_epochs(self):
        calc = RewardCalculator()
        r = calc.calculate(
            participant_id="s1",
            epoch=1,
            service_pool=ServicePool.CONSENSUS,
            work_units=10.0,
            qualifying_epochs=0,
            health_score=1.0,
            has_duty_proof=True,
            reliability_score=1.0,
        )
        # maturity = 0 → quality = 0 → effective_weight = 0
        assert r.maturity_factor == 0.0
        assert r.effective_weight == 0.0

    def test_one_epoch(self):
        calc = RewardCalculator()
        r = calc.calculate(
            participant_id="s1",
            epoch=2,
            service_pool=ServicePool.CONSENSUS,
            work_units=10.0,
            qualifying_epochs=1,
            health_score=1.0,
            has_duty_proof=True,
            reliability_score=1.0,
        )
        # maturity = 1 - 0.9^1 = 0.1
        assert abs(r.maturity_factor - 0.1) < 1e-5

    def test_ten_epochs(self):
        calc = RewardCalculator()
        r = calc.calculate(
            participant_id="s1",
            epoch=11,
            service_pool=ServicePool.CONSENSUS,
            work_units=10.0,
            qualifying_epochs=10,
            health_score=1.0,
            has_duty_proof=True,
            reliability_score=1.0,
        )
        # maturity = 1 - 0.9^10 ≈ 0.6513
        assert abs(r.maturity_factor - 0.651322) < 0.01

    def test_high_epochs(self):
        calc = RewardCalculator()
        r = calc.calculate(
            participant_id="s1",
            epoch=100,
            service_pool=ServicePool.CONSENSUS,
            work_units=10.0,
            qualifying_epochs=50,
            health_score=1.0,
            has_duty_proof=True,
            reliability_score=1.0,
        )
        # maturity ≈ 1.0 for large n
        assert r.maturity_factor > 0.99


class TestQualityFactors:
    def test_no_duty_proof_zero_quality(self):
        calc = RewardCalculator()
        r = calc.calculate(
            participant_id="s1",
            epoch=10,
            service_pool=ServicePool.CONSENSUS,
            work_units=10.0,
            qualifying_epochs=20,
            health_score=1.0,
            has_duty_proof=False,
            reliability_score=1.0,
        )
        # duty_proof_factor = 0 → quality = 0
        assert r.quality_factor == 0.0
        assert r.effective_weight == 0.0

    def test_low_health(self):
        calc = RewardCalculator()
        r = calc.calculate(
            participant_id="s1",
            epoch=10,
            service_pool=ServicePool.CONSENSUS,
            work_units=10.0,
            qualifying_epochs=20,
            health_score=0.5,
            has_duty_proof=True,
            reliability_score=1.0,
        )
        assert r.health_factor == 0.5

    def test_low_reliability(self):
        calc = RewardCalculator()
        r = calc.calculate(
            participant_id="s1",
            epoch=10,
            service_pool=ServicePool.CONSENSUS,
            work_units=10.0,
            qualifying_epochs=20,
            health_score=1.0,
            has_duty_proof=True,
            reliability_score=0.3,
        )
        assert r.reliability_factor == 0.3

    def test_all_factors_max(self):
        calc = RewardCalculator()
        r = calc.calculate(
            participant_id="s1",
            epoch=100,
            service_pool=ServicePool.CONSENSUS,
            work_units=100.0,
            qualifying_epochs=100,
            health_score=1.0,
            has_duty_proof=True,
            reliability_score=1.0,
        )
        # All factors ≈ 1.0 → effective_weight ≈ 100
        assert r.effective_weight > 95.0


class TestPoolShare:
    def test_proportional_distribution(self):
        calc = RewardCalculator()
        # Participant with weight 10 out of total 100
        r = calc.calculate(
            participant_id="s1",
            epoch=1,
            service_pool=ServicePool.CONSENSUS,
            work_units=10.0,
            qualifying_epochs=20,
            health_score=1.0,
            has_duty_proof=True,
            reliability_score=1.0,
        )
        updated = calc.apply_pool_share(r, 1_000_000_000, 100.0)
        # Should get ~10% of budget
        assert updated.final_reward > 0

    def test_zero_total_weight(self):
        calc = RewardCalculator()
        r = calc.calculate(
            participant_id="s1",
            epoch=1,
            service_pool=ServicePool.CONSENSUS,
            work_units=10.0,
            qualifying_epochs=20,
            health_score=1.0,
            has_duty_proof=True,
            reliability_score=1.0,
        )
        updated = calc.apply_pool_share(r, 1_000_000_000, 0.0)
        assert updated.final_reward == 0

    def test_below_minimum_becomes_zero(self):
        calc = RewardCalculator()
        r = calc.calculate(
            participant_id="s1",
            epoch=1,
            service_pool=ServicePool.CONSENSUS,
            work_units=0.001,
            qualifying_epochs=1,
            health_score=1.0,
            has_duty_proof=True,
            reliability_score=1.0,
        )
        updated = calc.apply_pool_share(r, 100, 100.0)
        # tiny share → below min → becomes 0
        assert updated.final_reward == 0
