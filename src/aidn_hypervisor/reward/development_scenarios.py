"""Deterministic, non-emitting ECO-0007 launch simulation scenarios."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from aidn_hypervisor.reward.development_distribution import (
    BASIS_POINTS,
    DevelopmentContributionInput,
    DevelopmentPoolInput,
    DevelopmentRewardCalculation,
    DevelopmentRewardCalculator,
    DevelopmentRewardPolicy,
    DevelopmentRoleInput,
    canonical_hash,
)

DEFAULT_DISTRIBUTABLE_EPOCH_EMISSION_Q_ATOMS = 5_000_000_000
DEVELOPMENT_LAUNCH_SIMULATION_VERSION = "eco-0007-launch-matrix.v1"


class DevelopmentScenarioCase(BaseModel, frozen=True):
    """One deterministic input profile from the ECO-0007 launch checklist."""

    scenario_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    pool: DevelopmentPoolInput
    policy: DevelopmentRewardPolicy
    contributions: list[DevelopmentContributionInput] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)


class DevelopmentScenarioResult(BaseModel, frozen=True):
    """Auditable result for one scenario; it never represents a payment."""

    scenario_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_hash: str = Field(min_length=1)
    calculation: DevelopmentRewardCalculation
    invariant_checks: dict[str, bool]
    observations: list[str] = Field(default_factory=list)
    passed: bool
    result_hash: str = Field(min_length=1)

    def verify_integrity(self) -> bool:
        payload = self.model_dump(mode="json", exclude={"result_hash"})
        return self.result_hash == canonical_hash(payload) and self.calculation.verify_integrity()


class DevelopmentLaunchSimulationReport(BaseModel, frozen=True):
    """Complete ECO-0007 launch matrix report with an explicit non-emitting flag."""

    simulation_version: str = DEVELOPMENT_LAUNCH_SIMULATION_VERSION
    simulation_only: Literal[True] = True
    emits_q: Literal[False] = False
    ledger_writes: Literal[False] = False
    scenarios: list[DevelopmentScenarioResult] = Field(min_length=1)
    all_invariants_passed: bool
    report_root: str = Field(min_length=1)

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"report_root"})

    def verify_integrity(self) -> bool:
        return self.report_root == canonical_hash(self.unsigned_payload()) and all(
            scenario.verify_integrity() for scenario in self.scenarios
        )


def _contribution(
    contribution_id: str,
    *,
    units_milli: int,
    contributor_id: str,
    contribution_class: str = "CODE",
    group: str | None = None,
    wallet_address: str | None = "q1scenario",
    roles: Sequence[DevelopmentRoleInput] | None = None,
) -> DevelopmentContributionInput:
    role_allocations = (
        list(roles)
        if roles is not None
        else [
            DevelopmentRoleInput(
                contributor_id=contributor_id,
                role="AUTHOR",
                allocation_basis_points=BASIS_POINTS,
                wallet_address=wallet_address,
            )
        ]
    )
    return DevelopmentContributionInput(
        contribution_id=contribution_id,
        contribution_epoch=10,
        contribution_units_milli=units_milli,
        contribution_group_id=group,
        contribution_class=contribution_class,
        role_allocations=role_allocations,
    )


def _pool(
    *,
    epoch: int = 20,
    carryover_in_q_atoms: int = 0,
    maturity_reserve_in_q_atoms: int = 0,
    approved_bounty_reservations_q_atoms: int = 0,
    returned_unclaimed_rewards_q_atoms: int = 0,
) -> DevelopmentPoolInput:
    return DevelopmentPoolInput(
        epoch=epoch,
        distributable_epoch_emission_q_atoms=DEFAULT_DISTRIBUTABLE_EPOCH_EMISSION_Q_ATOMS,
        carryover_in_q_atoms=carryover_in_q_atoms,
        maturity_reserve_in_q_atoms=maturity_reserve_in_q_atoms,
        approved_bounty_reservations_q_atoms=approved_bounty_reservations_q_atoms,
        returned_unclaimed_rewards_q_atoms=returned_unclaimed_rewards_q_atoms,
    )


def launch_simulation_cases() -> list[DevelopmentScenarioCase]:
    """Build the mandatory pre-activation economic simulation matrix."""

    default_policy = DevelopmentRewardPolicy()
    cases = [
        DevelopmentScenarioCase(
            scenario_id="low-contribution-volume",
            description="One small accepted contribution leaves most of the budget as carryover.",
            pool=_pool(),
            policy=default_policy,
            contributions=[_contribution("small", units_milli=10_000, contributor_id="alice")],
            observations=["low-demand-epoch", "carryover-preserved"],
        ),
        DevelopmentScenarioCase(
            scenario_id="dominant-contributor",
            description="One contributor submits several useful contributions and reaches the epoch cap.",
            pool=_pool(),
            policy=default_policy,
            contributions=[
                _contribution(
                    f"dominant-{index}",
                    units_milli=100_000,
                    contributor_id="dominant-contributor",
                )
                for index in range(4)
            ],
            observations=["contributor-cap", "excess-carried-forward"],
        ),
        DevelopmentScenarioCase(
            scenario_id="many-small-contributors",
            description="Many independent small contributions compete without exceeding individual caps.",
            pool=_pool(),
            policy=default_policy,
            contributions=[
                _contribution(
                    f"small-{index:02d}",
                    units_milli=10_000,
                    contributor_id=f"small-contributor-{index:02d}",
                )
                for index in range(24)
            ],
            observations=["many-contributors", "oversubscribed"],
        ),
        DevelopmentScenarioCase(
            scenario_id="very-large-pr",
            description="A very large PR is bounded by the ordinary per-contribution cap.",
            pool=_pool(),
            policy=default_policy,
            contributions=[
                _contribution(
                    "very-large",
                    units_milli=10_000_000,
                    contributor_id="large-change-author",
                )
            ],
            observations=["sublinear-demand-proxy", "ordinary-contribution-cap"],
        ),
        DevelopmentScenarioCase(
            scenario_id="pr-fragmentation",
            description="Several PRs in one logical group share one cap.",
            pool=_pool(),
            policy=default_policy,
            contributions=[
                _contribution(
                    f"fragment-{index}",
                    units_milli=100_000,
                    contributor_id=f"fragment-contributor-{index}",
                    group="logical-feature",
                )
                for index in range(4)
            ],
            observations=["contribution-group", "anti-splitting"],
        ),
        DevelopmentScenarioCase(
            scenario_id="reviewer-allocation-control-group",
            description="Substantive reviewer shares are allocated, while a known reviewer group is capped.",
            pool=_pool(),
            policy=DevelopmentRewardPolicy(known_control_group_epoch_cap_bps=1_000),
            contributions=[
                _contribution(
                    f"reviewed-{index}",
                    units_milli=100_000,
                    contributor_id=f"reviewed-author-{index}",
                    roles=[
                        DevelopmentRoleInput(
                            contributor_id=f"reviewed-author-{index}",
                            role="AUTHOR",
                            allocation_basis_points=7_000,
                            wallet_address=f"q1author{index}",
                        ),
                        DevelopmentRoleInput(
                            contributor_id="shared-reviewer",
                            role="PRIMARY_REVIEWER",
                            allocation_basis_points=3_000,
                            wallet_address="q1reviewer",
                            known_control_group="reviewer-cluster",
                        ),
                    ],
                )
                for index in range(4)
            ],
            observations=["review-allocation", "known-control-group-cap", "collusion-signal"],
        ),
        DevelopmentScenarioCase(
            scenario_id="high-security-reserve",
            description="A security-heavy epoch leaves a deliberately small ordinary contribution budget.",
            pool=_pool(),
            policy=DevelopmentRewardPolicy(
                security_pool_share_bps=8_000,
                documentation_pool_share_bps=500,
            ),
            contributions=[
                _contribution(
                    "security-fix",
                    units_milli=100_000,
                    contributor_id="security-author",
                    contribution_class="SECURITY",
                )
            ],
            observations=["security-reserve-priority", "reduced-ordinary-budget"],
        ),
        DevelopmentScenarioCase(
            scenario_id="inactive-epoch",
            description="No eligible contributions are submitted; the uncommitted budget remains accounted for.",
            pool=_pool(epoch=21),
            policy=default_policy,
            contributions=[],
            observations=["zero-demand-epoch", "no-forced-distribution"],
        ),
        DevelopmentScenarioCase(
            scenario_id="oversubscribed-pool",
            description="Demand exceeds the available pool and receives deterministic normalization.",
            pool=_pool(),
            policy=default_policy,
            contributions=[
                _contribution(
                    f"oversubscribed-{index}",
                    units_milli=100_000,
                    contributor_id=f"oversubscribed-contributor-{index}",
                )
                for index in range(8)
            ],
            observations=["oversubscribed", "largest-remainder-normalization"],
        ),
        DevelopmentScenarioCase(
            scenario_id="high-carryover",
            description="Carryover reaches the configured cap and excess returns explicitly to the reserve.",
            pool=_pool(carryover_in_q_atoms=1_500_000_000),
            policy=default_policy,
            contributions=[],
            observations=["carryover-cap", "returned-to-emission-reserve"],
        ),
        DevelopmentScenarioCase(
            scenario_id="returned-unclaimed-rewards",
            description="Returned unclaimed Q is accounted for without changing contribution attribution.",
            pool=_pool(returned_unclaimed_rewards_q_atoms=25_000_000),
            policy=default_policy,
            contributions=[
                _contribution(
                    "returned-reward-follow-up",
                    units_milli=10_000,
                    contributor_id="follow-up-author",
                )
            ],
            observations=["returned-reward-input", "pool-conservation"],
        ),
    ]
    return cases


def _input_hash(case: DevelopmentScenarioCase) -> str:
    return canonical_hash(
        {
            "scenario_id": case.scenario_id,
            "description": case.description,
            "pool": case.pool.model_dump(mode="json"),
            "policy": case.policy.model_dump(mode="json"),
            "contributions": [item.model_dump(mode="json") for item in case.contributions],
            "observations": case.observations,
        }
    )


def _invariant_checks(
    case: DevelopmentScenarioCase,
    calculation: DevelopmentRewardCalculation,
) -> dict[str, bool]:
    allocations = calculation.allocations
    schedules = calculation.schedules
    accepted = sum(item.accepted_reward_q_atoms for item in allocations)
    scheduled = sum(item.gross_reward_q_atoms for item in schedules)
    return {
        "calculation_integrity": calculation.verify_integrity(),
        "pool_conservation": calculation.total_accounted_q_atoms == calculation.pool.pool_in_q_atoms,
        "allocation_conservation": accepted == calculation.accepted_gross_reward_q_atoms,
        "schedule_conservation": scheduled == calculation.accepted_gross_reward_q_atoms,
        "budget_bound": calculation.accepted_gross_reward_q_atoms
        <= calculation.target_contribution_budget_q_atoms
        <= calculation.pool.available_contribution_budget_q_atoms,
        "contribution_caps": all(
            item.capped_nominal_reward_q_atoms <= item.contribution_cap_q_atoms for item in allocations
        ),
        "accepted_not_above_normalized": all(
            item.accepted_reward_q_atoms <= item.normalized_reward_q_atoms for item in allocations
        ),
        "carryover_bound": calculation.pool.carryover_out_q_atoms <= calculation.pool.carryover_limit_q_atoms,
        "scenario_epoch_valid": all(item.contribution_epoch <= case.pool.epoch for item in case.contributions),
        "fixed_point_only": all(
            isinstance(value, int)
            for value in (
                calculation.pool.pool_in_q_atoms,
                calculation.nominal_demand_q_atoms,
                calculation.accepted_gross_reward_q_atoms,
            )
        ),
    }


def run_launch_simulation_matrix() -> DevelopmentLaunchSimulationReport:
    """Run all mandatory ECO-0007 launch scenarios without Ledger access."""

    results: list[DevelopmentScenarioResult] = []
    for case in launch_simulation_cases():
        calculation = DevelopmentRewardCalculator(case.policy).calculate(case.pool, case.contributions)
        invariant_checks = _invariant_checks(case, calculation)
        result_payload = {
            "scenario_id": case.scenario_id,
            "description": case.description,
            "input_hash": _input_hash(case),
            "calculation": calculation.model_dump(mode="json"),
            "invariant_checks": invariant_checks,
            "observations": case.observations,
            "passed": all(invariant_checks.values()),
        }
        results.append(
            DevelopmentScenarioResult(
                **result_payload,
                result_hash=canonical_hash(result_payload),
            )
        )

    all_invariants_passed = all(item.passed for item in results)
    report_payload = {
        "simulation_version": DEVELOPMENT_LAUNCH_SIMULATION_VERSION,
        "simulation_only": True,
        "emits_q": False,
        "ledger_writes": False,
        "scenarios": [item.model_dump(mode="json") for item in results],
        "all_invariants_passed": all_invariants_passed,
    }
    return DevelopmentLaunchSimulationReport(
        **report_payload,
        report_root=canonical_hash(report_payload),
    )


__all__ = [
    "DEFAULT_DISTRIBUTABLE_EPOCH_EMISSION_Q_ATOMS",
    "DEVELOPMENT_LAUNCH_SIMULATION_VERSION",
    "DevelopmentLaunchSimulationReport",
    "DevelopmentScenarioCase",
    "DevelopmentScenarioResult",
    "launch_simulation_cases",
    "run_launch_simulation_matrix",
]
