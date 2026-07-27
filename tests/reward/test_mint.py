"""M11-S4: Mint Generator — unit tests."""

from __future__ import annotations

from aidn_hypervisor.reward.mint import MintGenerator
from aidn_hypervisor.reward.models import (
    BASE_EMISSION_Q_ATOMS,
    MintRecipient,
    MintStatus,
    RewardCalculation,
    ServicePool,
)


class TestMintGeneration:
    def test_generate(self):
        gen = MintGenerator()
        mint = gen.generate(
            epoch=1,
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
        assert mint.epoch == 1
        assert mint.recipient_count == 1
        assert mint.total_minted == 500_000
        assert mint.status == MintStatus.PENDING

    def test_deterministic_id(self):
        gen = MintGenerator()
        m1 = gen.generate(
            epoch=1,
            base_emission=BASE_EMISSION_Q_ATOMS,
            recyclable_amount=0,
            recipients=[],
        )
        m2 = gen.generate(
            epoch=1,
            base_emission=BASE_EMISSION_Q_ATOMS,
            recyclable_amount=0,
            recipients=[],
        )
        assert m1.mint_id == m2.mint_id

    def test_different_epoch_different_id(self):
        gen = MintGenerator()
        m1 = gen.generate(
            epoch=1,
            base_emission=BASE_EMISSION_Q_ATOMS,
            recyclable_amount=0,
            recipients=[],
        )
        m2 = gen.generate(
            epoch=2,
            base_emission=BASE_EMISSION_Q_ATOMS,
            recyclable_amount=0,
            recipients=[],
        )
        assert m1.mint_id != m2.mint_id

    def test_pool_tracking(self):
        gen = MintGenerator()
        mint = gen.generate(
            epoch=1,
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
                    amount=200_000,
                    service_pool=ServicePool.REGISTRY,
                ),
            ],
        )
        assert mint.consensus_pool_used == 300_000
        assert mint.registry_pool_used == 200_000


class TestRecipientBuilding:
    def _make_calc(
        self, pid: str, pool: ServicePool, reward: int
    ) -> RewardCalculation:
        return RewardCalculation(
            epoch=1,
            participant_id=pid,
            service_pool=pool,
            raw_weight=10.0,
            quality_factor=1.0,
            maturity_factor=1.0,
            health_factor=1.0,
            duty_proof_factor=1.0,
            reliability_factor=1.0,
            final_reward=reward,
        )

    def test_build_recipients(self):
        gen = MintGenerator()
        calcs = [
            self._make_calc("s1", ServicePool.CONSENSUS, 500_000),
            self._make_calc("s2", ServicePool.REGISTRY, 300_000),
        ]
        wallet_map = {"s1": "0xW1", "s2": "0xW2"}
        recipients = gen.build_recipients(calcs, wallet_map)
        assert len(recipients) == 2

    def test_skips_zero_reward(self):
        gen = MintGenerator()
        calcs = [
            self._make_calc("s1", ServicePool.CONSENSUS, 500_000),
            self._make_calc("s2", ServicePool.CONSENSUS, 0),
        ]
        wallet_map = {"s1": "0xW1", "s2": "0xW2"}
        recipients = gen.build_recipients(calcs, wallet_map)
        assert len(recipients) == 1

    def test_skips_missing_wallet(self):
        gen = MintGenerator()
        calcs = [
            self._make_calc("s1", ServicePool.CONSENSUS, 500_000),
            self._make_calc("s2", ServicePool.CONSENSUS, 300_000),
        ]
        wallet_map = {"s1": "0xW1"}  # s2 has no wallet
        recipients = gen.build_recipients(calcs, wallet_map)
        assert len(recipients) == 1


class TestMintExecution:
    def test_execute(self):
        gen = MintGenerator()
        mint = gen.generate(
            epoch=1,
            base_emission=BASE_EMISSION_Q_ATOMS,
            recyclable_amount=0,
            recipients=[],
        )
        executed = gen.execute(mint)
        assert executed.status == MintStatus.EXECUTED

    def test_fail(self):
        gen = MintGenerator()
        mint = gen.generate(
            epoch=1,
            base_emission=BASE_EMISSION_Q_ATOMS,
            recyclable_amount=0,
            recipients=[],
        )
        failed = gen.fail(mint)
        assert failed.status == MintStatus.FAILED
