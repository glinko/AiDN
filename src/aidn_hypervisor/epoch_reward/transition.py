"""M11-S5: Epoch Transition Engine — evidence freeze, reward calc, mint."""

from __future__ import annotations

from aidn_hypervisor.epoch_reward.models import (
    EmissionRecord,
    EpochTransitionRecord,
    EpochTransitionState,
)
from aidn_hypervisor.epoch_reward.recycling import RecyclingEngine
from aidn_hypervisor.reward.models import (
    BASE_EMISSION_Q_ATOMS,
    EpochRewardBudget,
)
from aidn_hypervisor.reward.pools import ServicePoolManager


class EpochTransitionEngine:
    """Orchestrates epoch transition: evidence freeze → reward calc → mint.

    Transition pipeline (ECO-0005 §8):
    1. Freeze evidence for the epoch
    2. Calculate recyclable Q
    3. Allocate budget to pools
    4. Distribute rewards
    5. Generate mint operations
    6. Execute mint
    7. Record emission
    """

    def __init__(
        self,
        pool_manager: ServicePoolManager,
        recycling_engine: RecyclingEngine,
        base_emission: int = BASE_EMISSION_Q_ATOMS,
    ) -> None:
        self._pool_manager = pool_manager
        self._recycling = recycling_engine
        self._base_emission = base_emission

        # Transition state per epoch
        self._transitions: dict[int, EpochTransitionRecord] = {}
        # Emission records
        self._emissions: dict[int, EmissionRecord] = {}

    def begin_transition(self, epoch: int) -> EpochTransitionRecord:
        """Begin an epoch transition.

        Args:
            epoch: Epoch number.

        Returns:
            EpochTransitionRecord tracking the transition.
        """
        record = EpochTransitionRecord(
            epoch=epoch,
            started_at_epoch=epoch,
            state=EpochTransitionState.IN_PROGRESS,
            budget=EmissionRecord(
                epoch=epoch,
                base_emission=self._base_emission,
                recyclable_amount=0,
                total_budget=self._base_emission,
            ),
        )
        self._transitions[epoch] = record
        return record

    def freeze_evidence(self, epoch: int) -> EpochTransitionRecord | None:
        """Step 2: Freeze evidence for the epoch.

        Args:
            epoch: Epoch number.

        Returns:
            Updated transition record.
        """
        record = self._transitions.get(epoch)
        if record is None:
            return None

        return record.model_copy(
            update={"state": EpochTransitionState.EVIDENCE_FROZEN}
        )

    def calculate_budget(
        self, epoch: int
    ) -> EpochRewardBudget | None:
        """Step 3: Calculate epoch budget with recyclable Q.

        Args:
            epoch: Epoch number.

        Returns:
            EpochRewardBudget with pool allocations.
        """
        # First recycle eligible records
        self._recycling.recycle_eligible(epoch)
        recyclable = self._recycling.get_total_recycled()

        budget = self._pool_manager.allocate_budget(
            epoch=epoch,
            base_emission=self._base_emission,
            recyclable=recyclable,
        )

        # Update transition record with budget
        record = self._transitions.get(epoch)
        if record is not None:
            updated_budget = record.budget.model_copy(
                update={
                    "recyclable_amount": recyclable,
                    "total_budget": self._base_emission + recyclable,
                }
            )
            self._transitions[epoch] = record.model_copy(
                update={
                    "state": EpochTransitionState.REWARDS_CALCULATED,
                    "budget": updated_budget,
                }
            )

        return budget

    def record_emission(
        self,
        epoch: int,
        consensus_allocated: int,
        registry_allocated: int,
        validation_allocated: int,
        faucet_allocated: int,
        total_minted: int,
    ) -> EmissionRecord | None:
        """Record final emission for the epoch.

        Args:
            epoch: Epoch number.
            consensus_allocated: Q allocated to consensus pool.
            registry_allocated: Q allocated to registry pool.
            validation_allocated: Q allocated to validation pool.
            faucet_allocated: Q allocated to faucet pool.
            total_minted: Total Q actually minted.

        Returns:
            EmissionRecord.
        """
        record = self._transitions.get(epoch)
        if record is None:
            return None

        budget = record.budget
        unused_base = budget.base_emission - total_minted
        unused_base = max(0, unused_base)

        emission = EmissionRecord(
            epoch=epoch,
            base_emission=budget.base_emission,
            recyclable_amount=budget.recyclable_amount,
            total_budget=budget.total_budget,
            consensus_allocated=consensus_allocated,
            registry_allocated=registry_allocated,
            validation_allocated=validation_allocated,
            faucet_allocated=faucet_allocated,
            total_minted=total_minted,
            unused_base=unused_base,
            unused_recyclable=max(
                0, budget.recyclable_amount - (total_minted - unused_base)
            ),
        )

        self._emissions[epoch] = emission

        # Update transition to complete
        self._transitions[epoch] = record.model_copy(
            update={
                "state": EpochTransitionState.COMPLETE,
                "budget": emission,
            }
        )

        return emission

    def complete_transition(self, epoch: int) -> EpochTransitionRecord | None:
        """Mark transition as complete.

        Args:
            epoch: Epoch number.

        Returns:
            Final transition record.
        """
        record = self._transitions.get(epoch)
        if record is None:
            return None

        return record.model_copy(
            update={"state": EpochTransitionState.COMPLETE}
        )

    def fail_transition(
        self, epoch: int, reason: str
    ) -> EpochTransitionRecord | None:
        """Mark transition as failed.

        Args:
            epoch: Epoch number.
            reason: Failure reason.

        Returns:
            Failed transition record.
        """
        record = self._transitions.get(epoch)
        if record is None:
            return None

        return record.model_copy(
            update={
                "state": EpochTransitionState.FAILED,
                "notes": {"failure_reason": reason},
            }
        )

    def get_transition(
        self, epoch: int
    ) -> EpochTransitionRecord | None:
        """Get transition record for an epoch."""
        return self._transitions.get(epoch)

    def get_emission(self, epoch: int) -> EmissionRecord | None:
        """Get emission record for an epoch."""
        return self._emissions.get(epoch)

    @property
    def recycling_engine(self) -> RecyclingEngine:
        """Access the recycling engine."""
        return self._recycling
