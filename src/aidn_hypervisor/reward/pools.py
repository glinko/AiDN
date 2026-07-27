"""M11-S4: Service Pool Manager — budget allocation, diversity, concentration."""

from __future__ import annotations

from math import floor

from aidn_hypervisor.reward.calculator import RewardCalculator
from aidn_hypervisor.reward.models import (
    BASE_EMISSION_Q_ATOMS,
    DiversityFactor,
    EpochRewardBudget,
    GroupConcentration,
    PoolConfig,
    RewardCalculation,
    ServicePool,
)


class ServicePoolManager:
    """Manages service pool budgets and distribution.

    Handles:
    - Budget allocation from base emission + recyclable Q
    - Diversity factor calculation
    - Group concentration caps
    - Proportional distribution within pools
    """

    def __init__(self, config: PoolConfig | None = None) -> None:
        self._config = config or PoolConfig()
        self._calculator = RewardCalculator()

        # pool → list of RewardCalculation
        self._pool_participants: dict[ServicePool, list[RewardCalculation]] = {
            p: [] for p in ServicePool
        }

    def allocate_budget(
        self,
        epoch: int,
        base_emission: int = BASE_EMISSION_Q_ATOMS,
        recyclable: int = 0,
    ) -> EpochRewardBudget:
        """Allocate epoch budget across service pools.

        Args:
            epoch: Current epoch number.
            base_emission: Base emission in q-atoms.
            recyclable: Recyclable Q from previous epochs.

        Returns:
            EpochRewardBudget with pool allocations.
        """
        total = base_emission + recyclable

        consensus = floor(total * self._config.consensus_share)
        registry = floor(total * self._config.registry_share)
        validation = floor(total * self._config.validation_share)
        # Faucet gets the remainder to avoid rounding loss
        faucet = total - consensus - registry - validation

        return EpochRewardBudget(
            epoch=epoch,
            base_emission=base_emission,
            recyclable_amount=recyclable,
            consensus_pool=consensus,
            registry_pool=registry,
            validation_pool=validation,
            faucet_pool=faucet,
        )

    def add_participant(
        self, pool: ServicePool, calculation: RewardCalculation
    ) -> None:
        """Add a participant's reward calculation to a pool."""
        self._pool_participants[pool].append(calculation)

    def clear_participants(self) -> None:
        """Clear all participants from all pools."""
        for pool in self._pool_participants:
            self._pool_participants[pool] = []

    def calculate_diversity(
        self,
        pool: ServicePool,
        independent_group_count: int,
        budget: int,
    ) -> DiversityFactor:
        """Calculate diversity factor for a pool.

        DiversityFactor = min(1, IndependentGroupCount / TargetIndependentGroups)

        Args:
            pool: Service pool.
            independent_group_count: Number of independent KCGs in pool.
            budget: Nominal budget for the pool.

        Returns:
            DiversityFactor with adjusted budget.
        """
        target = self._get_target_groups(pool)
        factor = min(1.0, independent_group_count / target)
        distributable = floor(budget * factor)

        return DiversityFactor(
            service_pool=pool,
            independent_group_count=independent_group_count,
            target_independent_groups=target,
            factor=round(factor, 6),
            nominal_budget=budget,
            distributable_budget=distributable,
        )

    def check_concentration(
        self,
        group_id: str,
        pool: ServicePool,
        group_share: float,
        group_reward: int,
    ) -> GroupConcentration:
        """Check if a group exceeds concentration cap.

        MaximumGroupShare = max(1 / IndependentGroupCount, MinimumGroupShareCap)

        Args:
            group_id: KCG group ID.
            pool: Service pool.
            group_share: Group's share of the pool (0-1).
            group_reward: Total reward claimed by the group.

        Returns:
            GroupConcentration with cap info.
        """
        max_share = 1.0 - self._config.minimum_group_share_cap
        is_capped = group_share > max_share

        capped_amount = 0
        redistributed = 0

        if is_capped:
            capped_amount = floor(group_reward * (group_share - max_share))
            redistributed = capped_amount

        return GroupConcentration(
            group_id=group_id,
            service_pool=pool,
            group_share=round(group_share, 6),
            max_allowed_share=round(max_share, 6),
            is_capped=is_capped,
            capped_amount=capped_amount,
            redistributed_amount=redistributed,
        )

    def distribute_pool(
        self,
        pool: ServicePool,
        budget: int,
        diversity_factor: float = 1.0,
    ) -> list[RewardCalculation]:
        """Distribute pool budget to participants proportionally.

        Args:
            pool: Service pool.
            budget: Total budget for the pool.
            diversity_factor: Pre-calculated diversity factor.

        Returns:
            List of updated RewardCalculations with final rewards.
        """
        participants = self._pool_participants.get(pool, [])
        if not participants:
            return []

        distributable = floor(budget * diversity_factor)
        total_weight = sum(p.effective_weight for p in participants)

        results: list[RewardCalculation] = []
        for p in participants:
            updated = self._calculator.apply_pool_share(
                p, distributable, total_weight
            )
            results.append(updated)

        # Update stored participants with final rewards
        self._pool_participants[pool] = results
        return results

    def get_pool_total_reward(self, pool: ServicePool) -> int:
        """Get total reward allocated in a pool."""
        return sum(
            p.final_reward
            for p in self._pool_participants.get(pool, [])
        )

    def get_pool_participants(
        self, pool: ServicePool
    ) -> list[RewardCalculation]:
        """Get all participants in a pool."""
        return list(self._pool_participants.get(pool, []))

    # ── Internal ───────────────────────────────────────────────

    def _get_target_groups(self, pool: ServicePool) -> int:
        """Get target independent groups for a pool."""
        targets = {
            ServicePool.CONSENSUS: self._config.target_consensus_groups,
            ServicePool.REGISTRY: self._config.target_registry_groups,
            ServicePool.VALIDATION: self._config.target_validation_groups,
        }
        return targets.get(pool, 5)
