"""M11-S5: Faucet Engine — unit tests."""

from __future__ import annotations

from aidn_hypervisor.epoch_reward.faucet import FaucetEngine


class TestFaucetAllocation:
    def test_single_request(self):
        engine = FaucetEngine(per_wallet_limit=100_000_000)
        result = engine.allocate(
            epoch=1,
            budget=500_000_000,
            requests=[("0xW1", None)],
        )
        assert len(result.allocations) == 1
        assert result.allocations[0].amount == 100_000_000

    def test_multiple_requests(self):
        engine = FaucetEngine(per_wallet_limit=100_000_000)
        result = engine.allocate(
            epoch=1,
            budget=500_000_000,
            requests=[
                ("0xW1", None),
                ("0xW2", None),
                ("0xW3", None),
            ],
        )
        assert len(result.allocations) == 3
        assert result.allocated_amount == 300_000_000

    def test_budget_exhausted(self):
        engine = FaucetEngine(per_wallet_limit=200_000_000)
        result = engine.allocate(
            epoch=1,
            budget=300_000_000,
            requests=[
                ("0xW1", None),
                ("0xW2", None),
                ("0xW3", None),
            ],
        )
        assert result.allocated_amount == 300_000_000
        assert result.unallocated_amount == 0

    def test_cooldown_blocks(self):
        engine = FaucetEngine(per_wallet_limit=100_000_000, cooldown_epochs=1)
        # Claim in epoch 1
        engine.allocate(
            epoch=1,
            budget=500_000_000,
            requests=[("0xW1", None)],
        )
        # Try to claim in epoch 2 (cooldown)
        result = engine.allocate(
            epoch=2,
            budget=500_000_000,
            requests=[("0xW1", None)],
        )
        assert len(result.allocations) == 0

    def test_cooldown_expires(self):
        engine = FaucetEngine(per_wallet_limit=100_000_000, cooldown_epochs=1)
        engine.allocate(
            epoch=1,
            budget=500_000_000,
            requests=[("0xW1", None)],
        )
        # Epoch 3: cooldown expired
        result = engine.allocate(
            epoch=3,
            budget=500_000_000,
            requests=[("0xW1", None)],
        )
        assert len(result.allocations) == 1

    def test_per_kcg_limit(self):
        engine = FaucetEngine(
            per_wallet_limit=200_000_000,
            per_kcg_limit=300_000_000,
        )
        result = engine.allocate(
            epoch=1,
            budget=500_000_000,
            requests=[
                ("0xW1", "kcg-1"),
                ("0xW2", "kcg-1"),
                ("0xW3", "kcg-1"),
            ],
        )
        # Total for kcg-1 capped at 300M
        assert result.allocated_amount <= 300_000_000

    def test_can_claim(self):
        engine = FaucetEngine(cooldown_epochs=1)
        assert engine.can_claim("0xW1", 1) is True

    def test_cannot_claim_during_cooldown(self):
        engine = FaucetEngine(cooldown_epochs=2)
        engine.allocate(
            epoch=1,
            budget=500_000_000,
            requests=[("0xW1", None)],
        )
        assert engine.can_claim("0xW1", 2) is False
        assert engine.can_claim("0xW1", 3) is False
        assert engine.can_claim("0xW1", 4) is True
