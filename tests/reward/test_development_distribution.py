from types import SimpleNamespace

import pytest

from aidn_hypervisor.reward.development_distribution import (
    Q_ATOMS_PER_Q,
    DevelopmentContributionInput,
    DevelopmentPoolInput,
    DevelopmentRewardCalculator,
    DevelopmentRewardPolicy,
    DevelopmentRoleInput,
    contribution_input_from_attestation,
)

BASE_EMISSION = 5_000_000_000


def _pool(**overrides):
    values = {
        "epoch": 20,
        "distributable_epoch_emission_q_atoms": BASE_EMISSION,
    }
    values.update(overrides)
    return DevelopmentPoolInput(**values)


def _contribution(
    contribution_id: str,
    *,
    units_milli: int,
    contributor_id: str | None = None,
    wallet_address: str | None = "q1wallet",
    role_bps: int = 10_000,
    group: str | None = None,
):
    contributor_id = contributor_id or f"contributor-{contribution_id}"
    return DevelopmentContributionInput(
        contribution_id=contribution_id,
        contribution_epoch=10,
        contribution_units_milli=units_milli,
        contribution_group_id=group,
        contribution_class="CODE",
        role_allocations=[
            DevelopmentRoleInput(
                contributor_id=contributor_id,
                role="AUTHOR",
                allocation_basis_points=role_bps,
                wallet_address=wallet_address,
            )
        ],
    )


def test_low_demand_keeps_uncommitted_pool_as_carryover():
    calculation = DevelopmentRewardCalculator().calculate(
        _pool(),
        [_contribution("small", units_milli=10_000)],
    )

    # 5% of 5000Q = 250Q; 15% security and 5% documentation are reserved.
    assert calculation.pool.base_allocation_q_atoms == 250_000_000
    assert calculation.pool.available_contribution_budget_q_atoms == 200_000_000
    assert calculation.allocations[0].accepted_reward_q_atoms == 10_000_000
    assert calculation.pool.carryover_out_q_atoms == 190_000_000
    assert calculation.pool.returned_to_emission_reserve_q_atoms == 0
    assert calculation.total_accounted_q_atoms == calculation.pool.pool_in_q_atoms
    assert calculation.verify_integrity()

    schedule = calculation.schedules[0]
    assert schedule.immediate_amount_q_atoms == 4_000_000
    assert schedule.maturity_stage_one_amount_q_atoms == 3_000_000
    assert schedule.maturity_stage_two_amount_q_atoms == 3_000_000


def test_oversubscribed_demand_normalizes_deterministically():
    contributions = [_contribution(f"c-{index}", units_milli=100_000) for index in range(6)]
    calculator = DevelopmentRewardCalculator()
    first = calculator.calculate(_pool(), contributions)
    second = calculator.calculate(_pool(), reversed(contributions))

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.nominal_demand_q_atoms == 300_000_000
    assert first.target_contribution_budget_q_atoms == 200_000_000
    assert first.normalization_factor_millionths == 666_666
    assert sum(item.accepted_reward_q_atoms for item in first.allocations) == 200_000_000
    assert first.pool.carryover_out_q_atoms == 0


def test_contributor_cap_defers_excess_instead_of_redistributing_it():
    contributions = [
        _contribution(
            "a",
            units_milli=100_000,
            contributor_id="same-contributor",
        ),
        _contribution(
            "b",
            units_milli=100_000,
            contributor_id="same-contributor",
        ),
    ]
    calculation = DevelopmentRewardCalculator().calculate(_pool(), contributions)

    # Base=250Q, automatic contributor cap=35%=87.5Q.
    assert calculation.accepted_gross_reward_q_atoms == 87_500_000
    assert calculation.contributor_cap_overflow_q_atoms == 12_500_000
    assert calculation.pool.carryover_out_q_atoms == 112_500_000
    assert sum(item.accepted_reward_q_atoms for item in calculation.allocations) == 87_500_000


def test_contribution_group_shares_one_logical_cap():
    fragmented = [
        _contribution(
            f"fragment-{index}",
            units_milli=100_000,
            contributor_id=f"fragment-contributor-{index}",
            group="logical-feature",
        )
        for index in range(4)
    ]
    calculation = DevelopmentRewardCalculator().calculate(_pool(), fragmented)

    # Four PRs in one logical group cannot create four independent 20% caps.
    assert calculation.nominal_demand_q_atoms == 50_000_000
    assert calculation.accepted_gross_reward_q_atoms == 50_000_000
    assert calculation.group_cap_overflow_q_atoms == 150_000_000
    assert calculation.pool.carryover_out_q_atoms == 150_000_000


def test_unclaimed_wallet_is_recorded_without_a_payment_side_effect():
    calculation = DevelopmentRewardCalculator().calculate(
        _pool(),
        [_contribution("unclaimed", units_milli=10_000, wallet_address=None)],
    )

    assert calculation.unclaimed_scheduled_q_atoms == 10_000_000
    assert calculation.payments
    assert {payment.state for payment in calculation.payments} == {"UNCLAIMED"}
    assert all(payment.wallet_address is None for payment in calculation.payments)


def test_reserved_maturity_and_bounty_reduce_available_budget():
    calculation = DevelopmentRewardCalculator().calculate(
        _pool(
            maturity_reserve_in_q_atoms=20_000_000,
            approved_bounty_reservations_q_atoms=30_000_000,
        ),
        [_contribution("work", units_milli=100_000)],
    )

    assert calculation.pool.available_contribution_budget_q_atoms == 150_000_000
    assert calculation.pool.maturity_reserve_out_q_atoms == 50_000_000
    assert calculation.total_accounted_q_atoms == calculation.pool.pool_in_q_atoms


def test_bounty_and_exceptional_caps_require_explicit_input():
    with pytest.raises(ValueError, match="DEVELOPMENT_BOUNTY_RESERVATION_REQUIRED"):
        DevelopmentRewardCalculator().calculate(
            _pool(),
            [_contribution("bounty", units_milli=100_000).model_copy(update={"bounty_cap_q_atoms": 100_000_000})],
        )

    calculation = DevelopmentRewardCalculator().calculate(
        _pool(approved_bounty_reservations_q_atoms=100_000_000),
        [_contribution("exceptional", units_milli=100_000).model_copy(update={"exceptional_cap_q_atoms": 100_000_000})],
    )
    assert calculation.allocations[0].contribution_cap_q_atoms == 100_000_000


def test_invalid_pool_reserve_and_invalid_policy_are_rejected():
    with pytest.raises(ValueError, match="DEVELOPMENT_VESTING_SHARES_INVALID"):
        DevelopmentRewardPolicy(
            immediate_reward_share_bps=4_000,
            maturity_stage_one_share_bps=4_000,
            maturity_stage_two_share_bps=1_000,
        )

    with pytest.raises(ValueError, match="DEVELOPMENT_POOL_INSUFFICIENT"):
        DevelopmentRewardCalculator().calculate(
            _pool(
                maturity_reserve_in_q_atoms=200_000_000,
                approved_bounty_reservations_q_atoms=100_000_000,
            ),
            [],
        )


def test_nominal_rate_uses_milli_cu_without_float():
    policy = DevelopmentRewardPolicy(nominal_q_per_cu_q_atoms=Q_ATOMS_PER_Q)
    calculation = DevelopmentRewardCalculator(policy).calculate(
        _pool(),
        [_contribution("one-cu", units_milli=1_000)],
    )
    assert calculation.allocations[0].nominal_reward_q_atoms == Q_ATOMS_PER_Q


def test_non_finalized_attestation_cannot_enter_economic_simulation():
    with pytest.raises(ValueError, match="DEVELOPMENT_CONTRIBUTION_NOT_FINALIZED"):
        contribution_input_from_attestation(
            SimpleNamespace(eligibility_state="ELIGIBLE"),
            wallet_by_contributor={},
        )
