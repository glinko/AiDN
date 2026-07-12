import pytest
from pydantic import ValidationError

from aidn_hypervisor.economics.models import (
    EpochRewardBudget,
    EpochRewardPoolShares,
    RecyclableRemoval,
)


def test_epoch_reward_pool_shares_must_sum_to_one() -> None:
    with pytest.raises(ValidationError):
        EpochRewardPoolShares(
            consensus=0.3,
            registry=0.3,
            validation=0.3,
            faucet=0.2,
        )


def test_epoch_reward_budget_derives_pool_allocations_from_authorized_budget() -> None:
    budget = EpochRewardBudget(
        epoch_id="epoch-11",
        base_emission_q=5000.0,
        eligible_removed_q=500.0,
        recycle_backlog_q=125.0,
        faucet_carryover_q=40.0,
        active_hypervisor_count=20,
        pool_shares=EpochRewardPoolShares(
            consensus=0.3,
            registry=0.3,
            validation=0.3,
            faucet=0.1,
        ),
    )

    assert budget.recyclable_amount_q == 625.0
    assert budget.total_authorized_q == 5625.0
    assert budget.consensus_budget_q == 1687.5
    assert budget.registry_budget_q == 1687.5
    assert budget.validation_budget_q == 1687.5
    assert budget.faucet_budget_q == 602.5
    assert budget.faucet_share_q == 30.125


def test_recyclable_removal_accepts_validation_bond_forfeiture_metadata() -> None:
    removal = RecyclableRemoval(
        sequence_id=1,
        removal_id="removal-1",
        category="validation_bond_forfeiture",
        amount_q=500.0,
        owner_id="wallet-1",
        removed_at="2026-07-10T00:00:00+00:00",
        source_event_type="validation_bond_forfeited",
        source_reference="bond-1",
        source_epoch_id="epoch-10",
    )

    assert removal.category == "validation_bond_forfeiture"
    assert removal.source_epoch_id == "epoch-10"
