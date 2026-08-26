"""Non-emitting ECO-0007 Development Pool simulation.

The calculator consumes finalized RFC-0068 evidence and produces an
epoch-scoped, hash-bound distribution proposal. It never touches a Wallet,
Ledger, mint operation, or reward balance.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.contributions.models import ContributionAttestation

DEVELOPMENT_REWARD_CALCULATION_VERSION = "eco-0007-simulation.v1"
Q_ATOMS_PER_Q = 1_000_000
MILLI_CU_PER_CU = 1_000
BASIS_POINTS = 10_000
MILLIONTHS = 1_000_000

DevelopmentRole = Literal[
    "AUTHOR",
    "COAUTHOR",
    "ISSUE_DESIGNER",
    "SPECIFICATION_AUTHOR",
    "PRIMARY_REVIEWER",
    "SECONDARY_REVIEWER",
    "SECURITY_REVIEWER",
    "TEST_AUTHOR",
    "RELEASE_INTEGRATOR",
]


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(f"{DEVELOPMENT_REWARD_CALCULATION_VERSION}:".encode() + payload).hexdigest()


class DevelopmentRewardPolicy(BaseModel, frozen=True):
    """Governance parameters for the simulation profile, expressed as integers."""

    policy_version: str = DEVELOPMENT_REWARD_CALCULATION_VERSION
    development_share_bps: int = Field(default=6_000, ge=0, le=BASIS_POINTS)
    security_pool_share_bps: int = Field(default=1_500, ge=0, le=BASIS_POINTS)
    documentation_pool_share_bps: int = Field(default=500, ge=0, le=BASIS_POINTS)
    nominal_q_per_cu_q_atoms: int = Field(default=Q_ATOMS_PER_Q, ge=0)
    ordinary_per_contribution_cap_bps: int = Field(
        default=2_000,
        ge=0,
        le=BASIS_POINTS,
    )
    automatic_contributor_epoch_cap_bps: int = Field(
        default=3_500,
        ge=0,
        le=BASIS_POINTS,
    )
    known_control_group_epoch_cap_bps: int | None = Field(
        default=None,
        ge=0,
        le=BASIS_POINTS,
    )
    immediate_reward_share_bps: int = Field(default=4_000, ge=0, le=BASIS_POINTS)
    maturity_stage_one_share_bps: int = Field(default=3_000, ge=0, le=BASIS_POINTS)
    maturity_stage_two_share_bps: int = Field(default=3_000, ge=0, le=BASIS_POINTS)
    maturity_stage_one_epochs: int = Field(default=4, ge=1)
    maturity_stage_two_epochs: int = Field(default=12, ge=1)
    claim_window_epochs: int = Field(default=12, ge=1)
    minimum_contribution_reward_q_atoms: int = Field(default=10_000, ge=0)
    maximum_development_carryover_epochs: int = Field(default=6, ge=1)

    @model_validator(mode="after")
    def validate_profile(self) -> DevelopmentRewardPolicy:
        if (
            self.immediate_reward_share_bps + self.maturity_stage_one_share_bps + self.maturity_stage_two_share_bps
            != BASIS_POINTS
        ):
            raise ValueError("DEVELOPMENT_VESTING_SHARES_INVALID")
        if self.security_pool_share_bps + self.documentation_pool_share_bps > BASIS_POINTS:
            raise ValueError("DEVELOPMENT_CLASS_RESERVES_INVALID")
        if self.maturity_stage_two_epochs <= self.maturity_stage_one_epochs:
            raise ValueError("DEVELOPMENT_MATURITY_BOUNDARIES_INVALID")
        return self


class DevelopmentPoolInput(BaseModel, frozen=True):
    epoch: int = Field(ge=0)
    distributable_epoch_emission_q_atoms: int = Field(ge=0)
    carryover_in_q_atoms: int = Field(default=0, ge=0)
    dedicated_development_grants_q_atoms: int = Field(default=0, ge=0)
    returned_unclaimed_rewards_q_atoms: int = Field(default=0, ge=0)
    returned_cancelled_rewards_q_atoms: int = Field(default=0, ge=0)
    maturity_reserve_in_q_atoms: int = Field(default=0, ge=0)
    approved_bounty_reservations_q_atoms: int = Field(default=0, ge=0)


class DevelopmentPoolState(BaseModel, frozen=True):
    epoch: int = Field(ge=0)
    base_allocation_q_atoms: int = Field(ge=0)
    pool_in_q_atoms: int = Field(ge=0)
    security_reserve_q_atoms: int = Field(ge=0)
    documentation_reserve_q_atoms: int = Field(ge=0)
    maturity_reserve_in_q_atoms: int = Field(ge=0)
    maturity_reserve_out_q_atoms: int = Field(ge=0)
    approved_bounty_reserve_q_atoms: int = Field(ge=0)
    available_contribution_budget_q_atoms: int = Field(ge=0)
    carryover_limit_q_atoms: int = Field(ge=0)
    carryover_out_q_atoms: int = Field(ge=0)
    returned_to_emission_reserve_q_atoms: int = Field(ge=0)
    pool_hash: str = Field(min_length=1)


class DevelopmentRoleInput(BaseModel, frozen=True):
    contributor_id: str = Field(min_length=1)
    role: DevelopmentRole
    allocation_basis_points: int = Field(ge=0, le=BASIS_POINTS)
    wallet_address: str | None = None
    known_control_group: str | None = None


class DevelopmentContributionInput(BaseModel, frozen=True):
    contribution_id: str = Field(min_length=1)
    contribution_epoch: int = Field(ge=0)
    contribution_units_milli: int = Field(ge=0)
    contribution_group_id: str | None = None
    contribution_class: str = Field(min_length=1)
    role_allocations: list[DevelopmentRoleInput] = Field(min_length=1)
    eligibility_state: Literal["FINALIZED"] = "FINALIZED"
    challenge_closed: bool = True
    bounty_cap_q_atoms: int | None = Field(default=None, ge=0)
    exceptional_cap_q_atoms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_roles(self) -> DevelopmentContributionInput:
        total = sum(item.allocation_basis_points for item in self.role_allocations)
        if total > BASIS_POINTS:
            raise ValueError("DEVELOPMENT_ROLE_ALLOCATION_INVALID")
        identities = {(item.contributor_id, item.role) for item in self.role_allocations}
        if len(identities) != len(self.role_allocations):
            raise ValueError("DEVELOPMENT_ROLE_ALLOCATION_DUPLICATE")
        if not self.challenge_closed:
            raise ValueError("DEVELOPMENT_CONTRIBUTION_CHALLENGE_OPEN")
        return self


class DevelopmentRoleReward(BaseModel, frozen=True):
    contribution_id: str = Field(min_length=1)
    contributor_id: str = Field(min_length=1)
    role: DevelopmentRole
    allocation_basis_points: int = Field(ge=0, le=BASIS_POINTS)
    desired_gross_q_atoms: int = Field(ge=0)
    accepted_gross_q_atoms: int = Field(ge=0)
    cap_overflow_q_atoms: int = Field(ge=0)
    wallet_address: str | None = None
    known_control_group: str | None = None
    immediate_q_atoms: int = Field(ge=0)
    maturity_stage_one_q_atoms: int = Field(ge=0)
    maturity_stage_two_q_atoms: int = Field(ge=0)
    wallet_state: Literal["VERIFIED", "UNCLAIMED"]


class DevelopmentRewardAllocation(BaseModel, frozen=True):
    contribution_id: str = Field(min_length=1)
    contribution_group_id: str | None = None
    contribution_units_milli: int = Field(ge=0)
    nominal_reward_q_atoms: int = Field(ge=0)
    contribution_cap_q_atoms: int = Field(ge=0)
    capped_nominal_reward_q_atoms: int = Field(ge=0)
    normalized_reward_q_atoms: int = Field(ge=0)
    accepted_reward_q_atoms: int = Field(ge=0)
    role_unallocated_q_atoms: int = Field(ge=0)
    group_cap_overflow_q_atoms: int = Field(ge=0)
    contributor_cap_overflow_q_atoms: int = Field(ge=0)
    minimum_threshold_excluded: bool
    role_rewards: list[DevelopmentRoleReward] = Field(default_factory=list)
    allocation_hash: str = Field(min_length=1)


class DevelopmentRewardSchedule(BaseModel, frozen=True):
    reward_id: str = Field(min_length=1)
    contribution_id: str = Field(min_length=1)
    contribution_epoch: int = Field(ge=0)
    distribution_epoch: int = Field(ge=0)
    gross_reward_q_atoms: int = Field(ge=0)
    immediate_amount_q_atoms: int = Field(ge=0)
    maturity_stage_one_amount_q_atoms: int = Field(ge=0)
    maturity_stage_two_amount_q_atoms: int = Field(ge=0)
    immediate_epoch: int = Field(ge=0)
    maturity_stage_one_epoch: int = Field(ge=0)
    maturity_stage_two_epoch: int = Field(ge=0)
    schedule_hash: str = Field(min_length=1)


class DevelopmentRewardPayment(BaseModel, frozen=True):
    reward_id: str = Field(min_length=1)
    contribution_id: str = Field(min_length=1)
    contributor_id: str = Field(min_length=1)
    role: DevelopmentRole
    wallet_address: str | None = None
    payment_stage: Literal[
        "IMMEDIATE",
        "MATURITY_STAGE_ONE",
        "MATURITY_STAGE_TWO",
    ]
    amount_q_atoms: int = Field(ge=0)
    state: Literal["PAYABLE", "RESERVED", "UNCLAIMED"]
    payment_hash: str = Field(min_length=1)


class DevelopmentRewardCalculation(BaseModel, frozen=True):
    calculation_version: str = DEVELOPMENT_REWARD_CALCULATION_VERSION
    epoch: int = Field(ge=0)
    policy: DevelopmentRewardPolicy
    pool: DevelopmentPoolState
    nominal_demand_q_atoms: int = Field(ge=0)
    target_contribution_budget_q_atoms: int = Field(ge=0)
    normalization_factor_millionths: int = Field(ge=0, le=MILLIONTHS)
    allocations: list[DevelopmentRewardAllocation] = Field(default_factory=list)
    schedules: list[DevelopmentRewardSchedule] = Field(default_factory=list)
    payments: list[DevelopmentRewardPayment] = Field(default_factory=list)
    accepted_gross_reward_q_atoms: int = Field(ge=0)
    immediate_scheduled_q_atoms: int = Field(ge=0)
    maturity_scheduled_q_atoms: int = Field(ge=0)
    unclaimed_scheduled_q_atoms: int = Field(ge=0)
    role_unallocated_q_atoms: int = Field(ge=0)
    group_cap_overflow_q_atoms: int = Field(ge=0)
    contributor_cap_overflow_q_atoms: int = Field(ge=0)
    calculation_root: str = Field(min_length=1)

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"calculation_root"})

    def verify_integrity(self) -> bool:
        return self.calculation_root == canonical_hash(self.unsigned_payload())

    @property
    def total_accounted_q_atoms(self) -> int:
        return (
            self.pool.security_reserve_q_atoms
            + self.pool.documentation_reserve_q_atoms
            + self.pool.approved_bounty_reserve_q_atoms
            + self.pool.maturity_reserve_in_q_atoms
            + self.accepted_gross_reward_q_atoms
            + self.pool.carryover_out_q_atoms
            + self.pool.returned_to_emission_reserve_q_atoms
        )


def contribution_input_from_attestation(
    attestation: ContributionAttestation,
    *,
    wallet_by_contributor: dict[str, str | None],
    control_group_by_contributor: dict[str, str | None] | None = None,
    bounty_cap_q_atoms: int | None = None,
    exceptional_cap_q_atoms: int | None = None,
) -> DevelopmentContributionInput:
    """Convert a finalized RFC-0068 attestation into ECO-0007 input."""

    if attestation.eligibility_state != "FINALIZED":
        raise ValueError("DEVELOPMENT_CONTRIBUTION_NOT_FINALIZED")
    groups = control_group_by_contributor or {}
    return DevelopmentContributionInput(
        contribution_id=attestation.contribution_id,
        contribution_epoch=attestation.contribution_epoch,
        contribution_units_milli=attestation.contribution_units_milli,
        contribution_group_id=attestation.contribution_group_id,
        contribution_class=attestation.contribution_class,
        role_allocations=[
            DevelopmentRoleInput(
                contributor_id=item.contributor_id,
                role=item.role,
                allocation_basis_points=item.allocation_basis_points,
                wallet_address=wallet_by_contributor.get(item.contributor_id),
                known_control_group=groups.get(item.contributor_id),
            )
            for item in attestation.role_allocations
        ],
        eligibility_state="FINALIZED",
        challenge_closed=True,
        bounty_cap_q_atoms=bounty_cap_q_atoms,
        exceptional_cap_q_atoms=exceptional_cap_q_atoms,
    )


def _largest_remainder(
    total: int,
    weights: dict[str, int],
) -> tuple[dict[str, int], int]:
    if total < 0:
        raise ValueError("DEVELOPMENT_ALLOCATION_TOTAL_INVALID")
    ordered = {key: int(weights[key]) for key in sorted(weights) if int(weights[key]) > 0}
    allocations = dict.fromkeys(sorted(weights), 0)
    weight_total = sum(ordered.values())
    if not ordered or weight_total <= 0:
        return allocations, total
    remainders: dict[str, int] = {}
    allocated = 0
    for key, weight in ordered.items():
        numerator = total * weight
        allocations[key] = numerator // weight_total
        remainders[key] = numerator % weight_total
        allocated += allocations[key]
    remaining = total - allocated
    for key in sorted(ordered, key=lambda item: (-remainders[item], item)):
        if remaining <= 0:
            break
        allocations[key] += 1
        remaining -= 1
    return allocations, remaining


class DevelopmentRewardCalculator:
    """Calculate an ECO-0007 proposal without authorizing a payment."""

    def __init__(self, policy: DevelopmentRewardPolicy | None = None) -> None:
        self.policy = policy or DevelopmentRewardPolicy()

    def calculate(
        self,
        pool_input: DevelopmentPoolInput,
        contributions: Sequence[DevelopmentContributionInput] | Iterable[DevelopmentContributionInput],
    ) -> DevelopmentRewardCalculation:
        ordered = sorted(contributions, key=lambda item: item.contribution_id)
        seen: set[str] = set()
        for item in ordered:
            if item.contribution_id in seen:
                raise ValueError("DEVELOPMENT_CONTRIBUTION_DUPLICATE")
            seen.add(item.contribution_id)
            if item.contribution_epoch > pool_input.epoch:
                raise ValueError("DEVELOPMENT_CONTRIBUTION_EPOCH_INVALID")
            if item.eligibility_state != "FINALIZED":
                raise ValueError("DEVELOPMENT_CONTRIBUTION_NOT_FINALIZED")
            if not item.challenge_closed:
                raise ValueError("DEVELOPMENT_CONTRIBUTION_CHALLENGE_OPEN")

        base_allocation = (
            pool_input.distributable_epoch_emission_q_atoms * self.policy.development_share_bps
        ) // BASIS_POINTS
        pool_in = (
            base_allocation
            + pool_input.carryover_in_q_atoms
            + pool_input.dedicated_development_grants_q_atoms
            + pool_input.returned_unclaimed_rewards_q_atoms
            + pool_input.returned_cancelled_rewards_q_atoms
        )
        security_reserve = (base_allocation * self.policy.security_pool_share_bps) // BASIS_POINTS
        documentation_reserve = (base_allocation * self.policy.documentation_pool_share_bps) // BASIS_POINTS
        reserved_before_contributions = (
            security_reserve
            + documentation_reserve
            + pool_input.maturity_reserve_in_q_atoms
            + pool_input.approved_bounty_reservations_q_atoms
        )
        if reserved_before_contributions > pool_in:
            raise ValueError("DEVELOPMENT_POOL_INSUFFICIENT")
        available = pool_in - reserved_before_contributions
        ordinary_cap = (base_allocation * self.policy.ordinary_per_contribution_cap_bps) // BASIS_POINTS

        nominal_by_id: dict[str, int] = {}
        cap_by_id: dict[str, int] = {}
        contribution_capped_by_id: dict[str, int] = {}
        minimum_excluded_by_id: dict[str, bool] = {}
        for item in ordered:
            if item.bounty_cap_q_atoms is not None and pool_input.approved_bounty_reservations_q_atoms <= 0:
                raise ValueError("DEVELOPMENT_BOUNTY_RESERVATION_REQUIRED")
            nominal = (item.contribution_units_milli * self.policy.nominal_q_per_cu_q_atoms) // MILLI_CU_PER_CU
            cap = ordinary_cap
            if item.bounty_cap_q_atoms is not None:
                cap = item.bounty_cap_q_atoms
            if item.exceptional_cap_q_atoms is not None:
                cap = (
                    min(cap, item.exceptional_cap_q_atoms)
                    if item.bounty_cap_q_atoms is not None
                    else item.exceptional_cap_q_atoms
                )
            capped = min(nominal, cap)
            minimum_excluded = capped > 0 and capped < self.policy.minimum_contribution_reward_q_atoms
            if minimum_excluded:
                capped = 0
            nominal_by_id[item.contribution_id] = nominal
            cap_by_id[item.contribution_id] = cap
            contribution_capped_by_id[item.contribution_id] = capped
            minimum_excluded_by_id[item.contribution_id] = minimum_excluded

        # A Contribution Group is one logical deliverable. Its members share
        # one cap so PR fragmentation cannot manufacture additional demand.
        capped_by_id = dict(contribution_capped_by_id)
        group_cap_overflow_by_id: dict[str, int] = {item.contribution_id: 0 for item in ordered}
        grouped_ids: dict[str, list[str]] = {}
        for item in ordered:
            if item.contribution_group_id is not None:
                grouped_ids.setdefault(item.contribution_group_id, []).append(item.contribution_id)
        for _group_id, contribution_ids in sorted(grouped_ids.items()):
            group_cap = max(cap_by_id[contribution_id] for contribution_id in contribution_ids)
            group_weights = {
                contribution_id: contribution_capped_by_id[contribution_id] for contribution_id in contribution_ids
            }
            group_target = min(group_cap, sum(group_weights.values()))
            group_allocations, _ = _largest_remainder(group_target, group_weights)
            for contribution_id in contribution_ids:
                capped_by_id[contribution_id] = group_allocations[contribution_id]
                group_cap_overflow_by_id[contribution_id] = (
                    contribution_capped_by_id[contribution_id] - group_allocations[contribution_id]
                )

        nominal_demand = sum(capped_by_id.values())
        target_budget = min(available, nominal_demand)
        normalized_by_id, _ = _largest_remainder(
            target_budget,
            capped_by_id,
        )
        normalization_factor = (target_budget * MILLIONTHS) // nominal_demand if nominal_demand > 0 else 0

        role_desired: dict[str, list[tuple[DevelopmentRoleInput, int]]] = {}
        role_unallocated_by_id: dict[str, int] = {}
        for item in ordered:
            normalized = normalized_by_id[item.contribution_id]
            role_total_bps = sum(role.allocation_basis_points for role in item.role_allocations)
            role_budget = (normalized * role_total_bps) // BASIS_POINTS
            role_weights = {
                f"{role.contributor_id}:{role.role}": role.allocation_basis_points for role in item.role_allocations
            }
            role_amounts, _ = _largest_remainder(role_budget, role_weights)
            role_desired[item.contribution_id] = [
                (
                    role,
                    role_amounts[f"{role.contributor_id}:{role.role}"],
                )
                for role in item.role_allocations
            ]
            role_unallocated_by_id[item.contribution_id] = normalized - role_budget

        contributor_used: dict[str, int] = {}
        group_used: dict[str, int] = {}
        contributor_cap = (base_allocation * self.policy.automatic_contributor_epoch_cap_bps) // BASIS_POINTS
        group_cap = (
            (base_allocation * self.policy.known_control_group_epoch_cap_bps) // BASIS_POINTS
            if self.policy.known_control_group_epoch_cap_bps is not None
            else None
        )
        role_rewards_by_id: dict[str, list[DevelopmentRoleReward]] = {item.contribution_id: [] for item in ordered}
        cap_overflow_by_id: dict[str, int] = {item.contribution_id: 0 for item in ordered}
        for contribution_id in sorted(role_desired):
            entries = sorted(
                role_desired[contribution_id],
                key=lambda item: (item[0].contributor_id, item[0].role),
            )
            for role, desired in entries:
                group = role.known_control_group
                contributor_remaining = max(
                    0,
                    contributor_cap - contributor_used.get(role.contributor_id, 0),
                )
                group_remaining = (
                    max(0, group_cap - group_used.get(group, 0))
                    if group is not None and group_cap is not None
                    else desired
                )
                accepted = min(desired, contributor_remaining, group_remaining)
                overflow = desired - accepted
                contributor_used[role.contributor_id] = contributor_used.get(role.contributor_id, 0) + accepted
                if group is not None:
                    group_used[group] = group_used.get(group, 0) + accepted
                cap_overflow_by_id[contribution_id] += overflow
                immediate = (accepted * self.policy.immediate_reward_share_bps) // BASIS_POINTS
                stage_one = (accepted * self.policy.maturity_stage_one_share_bps) // BASIS_POINTS
                stage_two = accepted - immediate - stage_one
                role_rewards_by_id[contribution_id].append(
                    DevelopmentRoleReward(
                        contribution_id=contribution_id,
                        contributor_id=role.contributor_id,
                        role=role.role,
                        allocation_basis_points=role.allocation_basis_points,
                        desired_gross_q_atoms=desired,
                        accepted_gross_q_atoms=accepted,
                        cap_overflow_q_atoms=overflow,
                        wallet_address=role.wallet_address,
                        known_control_group=group,
                        immediate_q_atoms=immediate,
                        maturity_stage_one_q_atoms=stage_one,
                        maturity_stage_two_q_atoms=stage_two,
                        wallet_state=("VERIFIED" if role.wallet_address else "UNCLAIMED"),
                    )
                )

        allocations: list[DevelopmentRewardAllocation] = []
        schedules: list[DevelopmentRewardSchedule] = []
        payments: list[DevelopmentRewardPayment] = []
        accepted_total = immediate_total = maturity_total = unclaimed_total = 0
        role_unallocated_total = sum(role_unallocated_by_id.values())
        group_cap_overflow_total = sum(group_cap_overflow_by_id.values())
        cap_overflow_total = sum(cap_overflow_by_id.values())
        for item in ordered:
            role_rewards = role_rewards_by_id[item.contribution_id]
            accepted = sum(role.accepted_gross_q_atoms for role in role_rewards)
            immediate = sum(role.immediate_q_atoms for role in role_rewards)
            stage_one = sum(role.maturity_stage_one_q_atoms for role in role_rewards)
            stage_two = sum(role.maturity_stage_two_q_atoms for role in role_rewards)
            accepted_total += accepted
            immediate_total += immediate
            maturity_total += stage_one + stage_two
            reward_id = canonical_hash(
                {
                    "contribution_id": item.contribution_id,
                    "distribution_epoch": pool_input.epoch,
                }
            )
            schedule_payload = {
                "reward_id": reward_id,
                "contribution_id": item.contribution_id,
                "contribution_epoch": item.contribution_epoch,
                "distribution_epoch": pool_input.epoch,
                "gross_reward_q_atoms": accepted,
                "immediate_amount_q_atoms": immediate,
                "maturity_stage_one_amount_q_atoms": stage_one,
                "maturity_stage_two_amount_q_atoms": stage_two,
                "immediate_epoch": pool_input.epoch,
                "maturity_stage_one_epoch": item.contribution_epoch + self.policy.maturity_stage_one_epochs,
                "maturity_stage_two_epoch": item.contribution_epoch + self.policy.maturity_stage_two_epochs,
            }
            schedules.append(
                DevelopmentRewardSchedule(
                    **schedule_payload,
                    schedule_hash=canonical_hash(schedule_payload),
                )
            )
            for role in role_rewards:
                if role.wallet_state == "UNCLAIMED":
                    unclaimed_total += (
                        role.immediate_q_atoms + role.maturity_stage_one_q_atoms + role.maturity_stage_two_q_atoms
                    )
                for stage, amount, state in (
                    (
                        "IMMEDIATE",
                        role.immediate_q_atoms,
                        "UNCLAIMED" if role.wallet_state == "UNCLAIMED" else "PAYABLE",
                    ),
                    (
                        "MATURITY_STAGE_ONE",
                        role.maturity_stage_one_q_atoms,
                        "UNCLAIMED" if role.wallet_state == "UNCLAIMED" else "RESERVED",
                    ),
                    (
                        "MATURITY_STAGE_TWO",
                        role.maturity_stage_two_q_atoms,
                        "UNCLAIMED" if role.wallet_state == "UNCLAIMED" else "RESERVED",
                    ),
                ):
                    payment_payload = {
                        "reward_id": reward_id,
                        "contribution_id": item.contribution_id,
                        "contributor_id": role.contributor_id,
                        "role": role.role,
                        "wallet_address": role.wallet_address,
                        "payment_stage": stage,
                        "amount_q_atoms": amount,
                        "state": state,
                    }
                    payments.append(
                        DevelopmentRewardPayment(
                            **payment_payload,
                            payment_hash=canonical_hash(payment_payload),
                        )
                    )
            allocation_payload = {
                "contribution_id": item.contribution_id,
                "contribution_group_id": item.contribution_group_id,
                "contribution_units_milli": item.contribution_units_milli,
                "nominal_reward_q_atoms": nominal_by_id[item.contribution_id],
                "contribution_cap_q_atoms": cap_by_id[item.contribution_id],
                "capped_nominal_reward_q_atoms": capped_by_id[item.contribution_id],
                "normalized_reward_q_atoms": normalized_by_id[item.contribution_id],
                "accepted_reward_q_atoms": accepted,
                "role_unallocated_q_atoms": role_unallocated_by_id[item.contribution_id],
                "group_cap_overflow_q_atoms": group_cap_overflow_by_id[item.contribution_id],
                "contributor_cap_overflow_q_atoms": cap_overflow_by_id[item.contribution_id],
                "minimum_threshold_excluded": minimum_excluded_by_id[item.contribution_id],
                "role_rewards": [role.model_dump(mode="json") for role in role_rewards],
            }
            allocations.append(
                DevelopmentRewardAllocation(
                    **allocation_payload,
                    allocation_hash=canonical_hash(allocation_payload),
                )
            )

        carryover_candidate = max(0, available - accepted_total)
        carryover_limit = base_allocation * self.policy.maximum_development_carryover_epochs
        carryover_out = min(carryover_candidate, carryover_limit)
        returned_to_reserve = carryover_candidate - carryover_out
        maturity_out = pool_input.maturity_reserve_in_q_atoms + maturity_total
        pool_payload = {
            "epoch": pool_input.epoch,
            "base_allocation_q_atoms": base_allocation,
            "pool_in_q_atoms": pool_in,
            "security_reserve_q_atoms": security_reserve,
            "documentation_reserve_q_atoms": documentation_reserve,
            "maturity_reserve_in_q_atoms": pool_input.maturity_reserve_in_q_atoms,
            "maturity_reserve_out_q_atoms": maturity_out,
            "approved_bounty_reserve_q_atoms": pool_input.approved_bounty_reservations_q_atoms,
            "available_contribution_budget_q_atoms": available,
            "carryover_limit_q_atoms": carryover_limit,
            "carryover_out_q_atoms": carryover_out,
            "returned_to_emission_reserve_q_atoms": returned_to_reserve,
        }
        pool = DevelopmentPoolState(
            **pool_payload,
            pool_hash=canonical_hash(pool_payload),
        )
        calculation_payload = {
            "calculation_version": DEVELOPMENT_REWARD_CALCULATION_VERSION,
            "epoch": pool_input.epoch,
            "policy": self.policy.model_dump(mode="json"),
            "pool": pool.model_dump(mode="json"),
            "nominal_demand_q_atoms": nominal_demand,
            "target_contribution_budget_q_atoms": target_budget,
            "normalization_factor_millionths": normalization_factor,
            "allocations": [item.model_dump(mode="json") for item in allocations],
            "schedules": [item.model_dump(mode="json") for item in schedules],
            "payments": [item.model_dump(mode="json") for item in payments],
            "accepted_gross_reward_q_atoms": accepted_total,
            "immediate_scheduled_q_atoms": immediate_total,
            "maturity_scheduled_q_atoms": maturity_total,
            "unclaimed_scheduled_q_atoms": unclaimed_total,
            "role_unallocated_q_atoms": role_unallocated_total,
            "group_cap_overflow_q_atoms": group_cap_overflow_total,
            "contributor_cap_overflow_q_atoms": cap_overflow_total,
        }
        return DevelopmentRewardCalculation(
            **calculation_payload,
            calculation_root=canonical_hash(calculation_payload),
        )


__all__ = [
    "BASIS_POINTS",
    "DEVELOPMENT_REWARD_CALCULATION_VERSION",
    "DevelopmentContributionInput",
    "DevelopmentPoolInput",
    "DevelopmentPoolState",
    "DevelopmentRewardAllocation",
    "DevelopmentRewardCalculator",
    "DevelopmentRewardPayment",
    "DevelopmentRewardPolicy",
    "DevelopmentRewardCalculation",
    "DevelopmentRewardSchedule",
    "DevelopmentRoleInput",
    "DevelopmentRoleReward",
    "Q_ATOMS_PER_Q",
    "canonical_hash",
    "contribution_input_from_attestation",
]
