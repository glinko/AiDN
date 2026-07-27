"""M11-S4: Reward models — unit tests."""

from __future__ import annotations

from aidn_hypervisor.reward.models import (
    BASE_EMISSION_Q_ATOMS,
    DiversityFactor,
    EpochRewardBudget,
    GroupConcentration,
    MintOperation,
    MintRecipient,
    MintStatus,
    PoolConfig,
    RewardCalculation,
    ServicePool,
)

# ── Constants ─────────────────────────────────────────────────────

class TestConstants:
    def test_base_emission(self):
        assert BASE_EMISSION_Q_ATOMS == 5_000_000_000


# ── Enums ─────────────────────────────────────────────────────────

class TestServicePool:
    def test_all_pools(self):
        pools = [
            ServicePool.CONSENSUS,
            ServicePool.REGISTRY,
            ServicePool.VALIDATION,
            ServicePool.FAUCET,
        ]
        assert len(pools) == 4

    def test_from_string(self):
        assert ServicePool("consensus") == ServicePool.CONSENSUS


class TestMintStatus:
    def test_all_statuses(self):
        assert len(MintStatus) == 3
        assert MintStatus.PENDING.value == "pending"


# ── PoolConfig ───────────────────────────────────────────────────

class TestPoolConfig:
    def test_defaults(self):
        cfg = PoolConfig()
        assert cfg.consensus_share == 0.30
        assert cfg.registry_share == 0.30
        assert cfg.validation_share == 0.30
        assert cfg.faucet_share == 0.10

    def test_shares_sum_to_one(self):
        cfg = PoolConfig()
        assert abs(cfg.shares_sum - 1.0) < 1e-9


# ── RewardCalculation ───────────────────────────────────────────

class TestRewardCalculation:
    def test_effective_weight(self):
        calc = RewardCalculation(
            epoch=1,
            participant_id="s1",
            service_pool=ServicePool.CONSENSUS,
            raw_weight=10.0,
            quality_factor=0.8,
            maturity_factor=0.9,
            health_factor=1.0,
            duty_proof_factor=1.0,
            reliability_factor=0.9,
            final_reward=500_000,
        )
        assert calc.effective_weight == 8.0

    def test_zero_quality(self):
        calc = RewardCalculation(
            epoch=1,
            participant_id="s1",
            service_pool=ServicePool.CONSENSUS,
            raw_weight=10.0,
            quality_factor=0.0,
            maturity_factor=0.0,
            health_factor=1.0,
            duty_proof_factor=0.0,
            reliability_factor=1.0,
            final_reward=0,
        )
        assert calc.effective_weight == 0.0


# ── DiversityFactor ─────────────────────────────────────────────

class TestDiversityFactor:
    def test_full_diversity(self):
        df = DiversityFactor(
            service_pool=ServicePool.CONSENSUS,
            independent_group_count=5,
            target_independent_groups=5,
            factor=1.0,
            nominal_budget=1_500_000_000,
            distributable_budget=1_500_000_000,
        )
        assert df.factor == 1.0

    def test_low_diversity(self):
        df = DiversityFactor(
            service_pool=ServicePool.CONSENSUS,
            independent_group_count=2,
            target_independent_groups=5,
            factor=0.4,
            nominal_budget=1_500_000_000,
            distributable_budget=600_000_000,
        )
        assert df.factor == 0.4
        assert df.distributable_budget < df.nominal_budget


# ── GroupConcentration ─────────────────────────────────────────

class TestGroupConcentration:
    def test_not_capped(self):
        gc = GroupConcentration(
            group_id="kcg-1",
            service_pool=ServicePool.CONSENSUS,
            group_share=0.3,
            max_allowed_share=0.8,
            is_capped=False,
        )
        assert gc.capped_amount == 0

    def test_capped(self):
        gc = GroupConcentration(
            group_id="kcg-1",
            service_pool=ServicePool.CONSENSUS,
            group_share=0.9,
            max_allowed_share=0.8,
            is_capped=True,
            capped_amount=100_000,
            redistributed_amount=100_000,
        )
        assert gc.is_capped is True


# ── MintRecipient ───────────────────────────────────────────────

class TestMintRecipient:
    def test_create(self):
        r = MintRecipient(
            participant_id="s1",
            wallet="0xW1",
            amount=500_000,
            service_pool=ServicePool.CONSENSUS,
        )
        assert r.amount == 500_000


# ── MintOperation ──────────────────────────────────────────────

class TestMintOperation:
    def test_create(self):
        mint = MintOperation(
            mint_id="m-1",
            epoch=1,
            total_minted=1_000_000,
            base_emission=BASE_EMISSION_Q_ATOMS,
            recyclable_amount=0,
            recipients=[
                MintRecipient(
                    participant_id="s1",
                    wallet="0xW1",
                    amount=500_000,
                    service_pool=ServicePool.CONSENSUS,
                )
            ],
        )
        assert mint.recipient_count == 1
        assert mint.total_allocated == 500_000
        assert mint.status == MintStatus.PENDING

    def test_total_allocated(self):
        mint = MintOperation(
            mint_id="m-1",
            epoch=1,
            total_minted=1_000_000,
            base_emission=BASE_EMISSION_Q_ATOMS,
            recyclable_amount=0,
            recipients=[
                MintRecipient(
                    participant_id="s1",
                    wallet="0xW1",
                    amount=300_000,
                    service_pool=ServicePool.CONSENSUS,
                ),
                MintRecipient(
                    participant_id="s2",
                    wallet="0xW2",
                    amount=700_000,
                    service_pool=ServicePool.REGISTRY,
                ),
            ],
        )
        assert mint.total_allocated == 1_000_000
        assert mint.recipient_count == 2


# ── EpochRewardBudget ──────────────────────────────────────────

class TestEpochRewardBudget:
    def test_create(self):
        budget = EpochRewardBudget(
            epoch=1,
            base_emission=BASE_EMISSION_Q_ATOMS,
            recyclable_amount=0,
            consensus_pool=1_500_000_000,
            registry_pool=1_500_000_000,
            validation_pool=1_500_000_000,
            faucet_pool=500_000_000,
        )
        assert budget.total_budget == BASE_EMISSION_Q_ATOMS

    def test_with_recyclable(self):
        budget = EpochRewardBudget(
            epoch=2,
            base_emission=BASE_EMISSION_Q_ATOMS,
            recyclable_amount=100_000_000,
            consensus_pool=1_530_000_000,
            registry_pool=1_530_000_000,
            validation_pool=1_530_000_000,
            faucet_pool=530_000_000,
        )
        assert budget.total_budget == BASE_EMISSION_Q_ATOMS + 100_000_000
