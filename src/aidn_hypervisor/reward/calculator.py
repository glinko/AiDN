"""M11-S4: Reward Calculator — weight, quality factors, distribution."""

from __future__ import annotations

from math import floor

from aidn_hypervisor.reward.models import (
    MIN_REWARD_Q_ATOMS,
    RewardCalculation,
    ServicePool,
)


class RewardCalculator:
    """Calculates individual rewards with quality factors.

    Reward Formula (ECO-0004 §9):
        RawWeight(i) = WorkUnits(i) × QualityFactor(i)
        QualityFactor(i) = MaturityFactor × HealthFactor
                         × DutyProofFactor × ReliabilityFactor

    Maturity Formula (ECO-0004 §12):
        MaturityFactor(n) = 1 - 0.9^n  (n = qualifying epochs)
    """

    def calculate(
        self,
        *,
        participant_id: str,
        epoch: int,
        service_pool: ServicePool,
        work_units: float,
        qualifying_epochs: int,
        health_score: float,
        has_duty_proof: bool,
        reliability_score: float,
    ) -> RewardCalculation:
        """Calculate reward for a participant.

        Args:
            participant_id: Participant identifier.
            epoch: Current epoch.
            service_pool: Service pool for the reward.
            work_units: Raw work units completed.
            qualifying_epochs: Number of epochs with qualifying participation.
            health_score: Service health (0.0-1.0).
            has_duty_proof: Whether duty proof was provided.
            reliability_score: Reliability metric (0.0-1.0).

        Returns:
            RewardCalculation with all factors and final reward.
        """
        # Maturity factor: 1 - 0.9^n
        maturity = self._maturity_factor(qualifying_epochs)

        # Health factor: clamped to [0, 1]
        health = max(0.0, min(1.0, health_score))

        # Duty proof factor: binary
        duty_proof = 1.0 if has_duty_proof else 0.0

        # Reliability factor: clamped to [0, 1]
        reliability = max(0.0, min(1.0, reliability_score))

        # Quality factor = product of sub-factors
        quality = maturity * health * duty_proof * reliability

        # Raw weight
        raw = work_units * quality

        return RewardCalculation(
            epoch=epoch,
            participant_id=participant_id,
            service_pool=service_pool,
            raw_weight=round(raw, 6),
            quality_factor=round(quality, 6),
            maturity_factor=round(maturity, 6),
            health_factor=round(health, 6),
            duty_proof_factor=duty_proof,
            reliability_factor=round(reliability, 6),
            final_reward=0,  # set by pool allocator
        )

    def apply_pool_share(
        self,
        calculation: RewardCalculation,
        pool_budget: int,
        total_weight: float,
    ) -> RewardCalculation:
        """Apply proportional pool share to get final reward.

        Args:
            calculation: Pre-calculated reward.
            pool_budget: Total budget for the pool.
            total_weight: Sum of all participant weights in the pool.

        Returns:
            Updated RewardCalculation with final_reward set.
        """
        if total_weight == 0:
            final = 0
        else:
            share = calculation.effective_weight / total_weight
            final = floor(pool_budget * share)

        # Enforce minimum reward threshold
        if 0 < final < MIN_REWARD_Q_ATOMS:
            final = 0

        return calculation.model_copy(update={"final_reward": final})

    @staticmethod
    def _maturity_factor(n: int) -> float:
        """Calculate maturity factor: 1 - 0.9^n."""
        if n <= 0:
            return 0.0
        return 1.0 - (0.9 ** n)
