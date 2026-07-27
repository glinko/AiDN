"""M11-S5: Faucet Engine — Faucet allocation with anti-Sybil constraints."""

from __future__ import annotations

from aidn_hypervisor.epoch_reward.models import (
    FaucetAllocation,
    FaucetRecipient,
)


class FaucetEngine:
    """Manages Faucet pool allocation with anti-Sybil constraints.

    ECO-0005 §12: Faucet receives 10% of epoch budget.
    Constraints:
    - Per-wallet limit per epoch
    - Per-KCG limit per epoch
    - Epoch cooldown (cannot claim consecutive epochs)
    """

    def __init__(
        self,
        per_wallet_limit: int = 100_000_000,  # 100Q
        per_kcg_limit: int = 500_000_000,  # 500Q
        cooldown_epochs: int = 1,
    ) -> None:
        self._per_wallet_limit = per_wallet_limit
        self._per_kcg_limit = per_kcg_limit
        self._cooldown = cooldown_epochs
        # wallet → last epoch claimed
        self._last_claimed: dict[str, int] = {}
        # kcg_id → total allocated this epoch
        self._kcg_allocated: dict[str, int] = {}

    def allocate(
        self,
        epoch: int,
        budget: int,
        requests: list[tuple[str, str | None]],  # (wallet, kcg_id)
    ) -> FaucetAllocation:
        """Allocate faucet budget to requests.

        Args:
            epoch: Current epoch.
            budget: Total faucet budget.
            requests: List of (wallet, kcg_id) pairs in priority order.

        Returns:
            FaucetAllocation with per-recipient amounts.
        """
        # Reset KCG tracking for this epoch
        self._kcg_allocated.clear()

        remaining = budget
        allocations: list[FaucetRecipient] = []

        for wallet, kcg_id in requests:
            if remaining <= 0:
                break

            # Check cooldown
            last_claimed = self._last_claimed.get(wallet, -999)
            if (epoch - last_claimed) <= self._cooldown:
                continue

            # Per-wallet limit
            wallet_amount = min(remaining, self._per_wallet_limit)

            # Per-KCG limit
            if kcg_id is not None:
                kcg_used = self._kcg_allocated.get(kcg_id, 0)
                kcg_remaining = self._per_kcg_limit - kcg_used
                wallet_amount = min(wallet_amount, kcg_remaining)

            if wallet_amount <= 0:
                continue

            allocations.append(
                FaucetRecipient(
                    wallet=wallet,
                    amount=wallet_amount,
                    kcg_id=kcg_id,
                )
            )

            remaining -= wallet_amount
            self._last_claimed[wallet] = epoch

            if kcg_id is not None:
                self._kcg_allocated[kcg_id] = (
                    self._kcg_allocated.get(kcg_id, 0) + wallet_amount
                )

        total_allocated = sum(a.amount for a in allocations)

        return FaucetAllocation(
            epoch=epoch,
            total_faucet_budget=budget,
            allocated_amount=total_allocated,
            unallocated_amount=budget - total_allocated,
            per_wallet_limit=self._per_wallet_limit,
            per_kcg_limit=self._per_kcg_limit,
            cooldown_epochs=self._cooldown,
            allocations=allocations,
        )

    def can_claim(self, wallet: str, epoch: int) -> bool:
        """Check if a wallet can claim from the faucet this epoch."""
        last_claimed = self._last_claimed.get(wallet, -999)
        return (epoch - last_claimed) > self._cooldown

    def get_wallet_history(self, wallet: str) -> list[int]:
        """Get epochs when a wallet claimed."""
        # Simplified: return last claimed epoch
        last = self._last_claimed.get(wallet)
        if last is None:
            return []
        return [last]
