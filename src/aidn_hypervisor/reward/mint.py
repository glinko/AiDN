"""M11-S4: Mint Generator — deterministic mint operations."""

from __future__ import annotations

import hashlib

from aidn_hypervisor.reward.models import (
    MintOperation,
    MintRecipient,
    MintStatus,
    RewardCalculation,
    ServicePool,
)


class MintGenerator:
    """Generates deterministic mint operations for epoch rewards."""

    def generate(
        self,
        *,
        epoch: int,
        base_emission: int,
        recyclable_amount: int,
        recipients: list[MintRecipient],
        metadata: dict | None = None,
    ) -> MintOperation:
        """Generate a mint operation.

        Args:
            epoch: Current epoch.
            base_emission: Base emission in q-atoms.
            recyclable_amount: Recyclable Q.
            recipients: List of recipients with amounts.
            metadata: Optional metadata.

        Returns:
            MintOperation ready for execution.
        """
        mint_id = self._generate_mint_id(epoch)
        total = sum(r.amount for r in recipients)

        # Track per-pool usage
        pool_usage: dict[ServicePool, int] = {
            ServicePool.CONSENSUS: 0,
            ServicePool.REGISTRY: 0,
            ServicePool.VALIDATION: 0,
            ServicePool.FAUCET: 0,
        }
        for r in recipients:
            pool_usage[r.service_pool] += r.amount

        return MintOperation(
            mint_id=mint_id,
            epoch=epoch,
            total_minted=total,
            base_emission=base_emission,
            recyclable_amount=recyclable_amount,
            recipients=recipients,
            consensus_pool_used=pool_usage[ServicePool.CONSENSUS],
            registry_pool_used=pool_usage[ServicePool.REGISTRY],
            validation_pool_used=pool_usage[ServicePool.VALIDATION],
            faucet_pool_used=pool_usage[ServicePool.FAUCET],
            metadata=metadata or {},
        )

    def build_recipients(
        self,
        calculations: list[RewardCalculation],
        wallet_map: dict[str, str],
    ) -> list[MintRecipient]:
        """Build mint recipients from reward calculations.

        Args:
            calculations: List of reward calculations.
            wallet_map: Mapping of participant_id → wallet address.

        Returns:
            List of MintRecipients.
        """
        recipients: list[MintRecipient] = []
        for calc in calculations:
            if calc.final_reward <= 0:
                continue
            wallet = wallet_map.get(calc.participant_id, "")
            if not wallet:
                continue
            recipients.append(
                MintRecipient(
                    participant_id=calc.participant_id,
                    wallet=wallet,
                    amount=calc.final_reward,
                    service_pool=calc.service_pool,
                )
            )
        return recipients

    def execute(self, mint: MintOperation) -> MintOperation:
        """Mark a mint operation as executed."""
        return mint.model_copy(update={"status": MintStatus.EXECUTED})

    def fail(self, mint: MintOperation) -> MintOperation:
        """Mark a mint operation as failed."""
        return mint.model_copy(update={"status": MintStatus.FAILED})

    # ── Internal ───────────────────────────────────────────────

    @staticmethod
    def _generate_mint_id(epoch: int) -> str:
        """Generate deterministic mint ID."""
        raw = f"mint:{epoch}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
