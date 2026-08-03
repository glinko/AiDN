"""Deterministic Registry reward aggregation for one protocol Epoch.

This module is intentionally separate from the legacy float-based reward
calculator.  Registry duty evidence is already fixed-point and finalized;
this boundary only aggregates that evidence into a bounded calculation.  It
does not authorize or mint Q.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence

from pydantic import BaseModel, Field

from aidn_hypervisor.registry.duty import FIXED_POINT_SCALE, RegistryRewardInput

REGISTRY_REWARD_CALCULATION_VERSION = "registry-reward-calculation.v1"
DEFAULT_REGISTRY_TARGET_INDEPENDENT_GROUPS = 5
DEFAULT_MINIMUM_GROUP_SHARE_CAP_MILLIONTHS = 200_000


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _effective_group_id(item: RegistryRewardInput) -> str:
    """Use the beneficiary as the conservative fallback when KCG is absent."""
    return item.known_control_group_id or f"beneficiary:{item.reward_beneficiary}"


def _allocate_weighted(
    total: int,
    weights: dict[str, int],
    *,
    cap: int | None = None,
) -> tuple[dict[str, int], int]:
    """Allocate integer atoms proportionally, optionally applying a hard cap.

    Capped groups are fixed first and the remainder is redistributed among the
    still-active groups.  Largest remainders and lexical identifiers make the
    result independent of input order.  Any atom that cannot be assigned
    without violating a cap remains unallocated.
    """
    if total < 0:
        raise ValueError("allocation total must be non-negative")
    if cap is not None and cap < 0:
        raise ValueError("allocation cap must be non-negative")

    positive = {key: int(value) for key, value in weights.items() if int(value) > 0}
    allocations = dict.fromkeys(sorted(weights), 0)
    remaining = int(total)
    active = dict(sorted(positive.items()))

    while active and remaining > 0:
        total_weight = sum(active.values())
        provisional = {
            key: (remaining * weight) // total_weight
            for key, weight in active.items()
        }
        capped_keys = (
            [key for key, value in provisional.items() if cap is not None and value > cap]
            if cap is not None
            else []
        )
        if capped_keys:
            for key in sorted(capped_keys):
                assert cap is not None
                allocations[key] += cap
                remaining -= cap
                del active[key]
            continue

        remainders = {
            key: (remaining * active[key]) % total_weight
            for key in active
        }
        for key, value in provisional.items():
            allocations[key] += value
        remaining -= sum(provisional.values())

        for key in sorted(remainders, key=lambda item: (-remainders[item], item)):
            if remaining <= 0:
                break
            if cap is not None and allocations[key] >= cap:
                continue
            allocations[key] += 1
            remaining -= 1
        break

    return allocations, remaining


class RegistryRewardAllocation(BaseModel, frozen=True):
    """One immutable beneficiary allocation within a Registry calculation."""

    service_id: str = Field(min_length=1)
    reward_beneficiary: str = Field(min_length=1)
    effective_group_id: str = Field(min_length=1)
    raw_weight_millionths: int = Field(ge=0)
    group_raw_weight_millionths: int = Field(ge=0)
    group_allocated_q_atoms: int = Field(ge=0)
    group_cap_q_atoms: int = Field(ge=0)
    group_cap_applied: bool
    allocated_q_atoms: int = Field(ge=0)
    evidence_id: str = Field(min_length=1)
    evidence_hash: str = Field(min_length=1)
    eligibility_snapshot_id: str = Field(min_length=1)
    finalized_operation_id: str = Field(min_length=1)


class RegistryRewardCalculation(BaseModel, frozen=True):
    """Epoch-scoped Registry calculation, before consensus-authorized minting."""

    calculation_version: str = REGISTRY_REWARD_CALCULATION_VERSION
    epoch: int = Field(ge=0)
    pool_id: str = "registry"
    pool_budget_reference: str = Field(min_length=1)
    nominal_pool_budget_q_atoms: int = Field(ge=0)
    independent_group_count: int = Field(ge=0)
    target_independent_groups: int = Field(gt=0)
    diversity_factor_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    distributable_pool_q_atoms: int = Field(ge=0)
    minimum_group_share_cap_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    maximum_group_share_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    maximum_group_share_q_atoms: int = Field(ge=0)
    total_raw_weight_millionths: int = Field(ge=0)
    allocations: list[RegistryRewardAllocation] = Field(default_factory=list)
    unallocated_distributable_q_atoms: int = Field(ge=0)
    unused_pool_q_atoms: int = Field(ge=0)
    calculation_root: str = Field(min_length=1)

    def unsigned_payload(self) -> dict:
        return self.model_dump(mode="json", exclude={"calculation_root"})

    def verify_integrity(self) -> bool:
        return self.calculation_root == _digest(self.unsigned_payload())

    def reward_id_for(self, allocation: RegistryRewardAllocation) -> str:
        if allocation not in self.allocations:
            raise ValueError("allocation does not belong to this calculation")
        return _digest(
            {
                "calculation_root": self.calculation_root,
                "calculation_version": self.calculation_version,
                "epoch": self.epoch,
                "pool_id": self.pool_id,
                "service_id": allocation.service_id,
                "allocated_q_atoms": allocation.allocated_q_atoms,
            }
        )


class RegistryEpochRewardCalculator:
    """Calculate the bounded Registry pool from finalized reward inputs."""

    def __init__(
        self,
        *,
        target_independent_groups: int = DEFAULT_REGISTRY_TARGET_INDEPENDENT_GROUPS,
        minimum_group_share_cap_millionths: int = DEFAULT_MINIMUM_GROUP_SHARE_CAP_MILLIONTHS,
        calculation_version: str = REGISTRY_REWARD_CALCULATION_VERSION,
    ) -> None:
        if target_independent_groups <= 0:
            raise ValueError("target independent groups must be positive")
        if not 0 <= minimum_group_share_cap_millionths <= FIXED_POINT_SCALE:
            raise ValueError("minimum group share cap is outside fixed-point bounds")
        if not calculation_version.strip():
            raise ValueError("calculation version is required")
        self._target_independent_groups = int(target_independent_groups)
        self._minimum_group_share_cap_millionths = int(minimum_group_share_cap_millionths)
        self._calculation_version = calculation_version

    def calculate(
        self,
        inputs: Sequence[RegistryRewardInput] | Iterable[RegistryRewardInput],
        *,
        epoch: int,
        nominal_pool_budget_q_atoms: int,
        pool_budget_reference: str,
    ) -> RegistryRewardCalculation:
        if epoch < 0:
            raise ValueError("epoch must be non-negative")
        if nominal_pool_budget_q_atoms < 0:
            raise ValueError("nominal pool budget must be non-negative")
        if not pool_budget_reference.strip():
            raise ValueError("pool budget reference is required")

        ordered_inputs = sorted(inputs, key=lambda item: item.service_id)
        seen_services: set[str] = set()
        for item in ordered_inputs:
            if item.service_id in seen_services:
                raise ValueError(f"duplicate service in reward inputs: {item.service_id}")
            seen_services.add(item.service_id)
            if item.epoch != epoch:
                raise ValueError(f"epoch mismatch for service: {item.service_id}")
            if item.reward_pool != "registry":
                raise ValueError(f"unsupported reward pool for service: {item.service_id}")

        group_members: dict[str, list[RegistryRewardInput]] = {}
        group_weights: dict[str, int] = {}
        for item in ordered_inputs:
            group_id = _effective_group_id(item)
            group_members.setdefault(group_id, []).append(item)
            group_weights[group_id] = group_weights.get(group_id, 0) + item.raw_weight_millionths

        independent_group_count = len(group_members)
        diversity_factor = min(
            FIXED_POINT_SCALE,
            (independent_group_count * FIXED_POINT_SCALE) // self._target_independent_groups,
        )
        distributable = (
            nominal_pool_budget_q_atoms * diversity_factor
        ) // FIXED_POINT_SCALE
        maximum_group_share = (
            max(
                FIXED_POINT_SCALE // independent_group_count,
                self._minimum_group_share_cap_millionths,
            )
            if independent_group_count
            else 0
        )
        maximum_group_share_q_atoms = (
            distributable * maximum_group_share
        ) // FIXED_POINT_SCALE

        group_allocations, _ = _allocate_weighted(
            distributable,
            group_weights,
            cap=maximum_group_share_q_atoms if group_members else None,
        )
        total_raw_weight = sum(item.raw_weight_millionths for item in ordered_inputs)
        allocations: list[RegistryRewardAllocation] = []
        for group_id in sorted(group_members):
            members = group_members[group_id]
            group_amount = group_allocations.get(group_id, 0)
            member_weights = {item.service_id: item.raw_weight_millionths for item in members}
            member_allocations, _ = _allocate_weighted(group_amount, member_weights)
            group_cap_applied = (
                total_raw_weight > 0
                and group_amount < (distributable * group_weights[group_id]) // total_raw_weight
            )
            for item in members:
                allocations.append(
                    RegistryRewardAllocation(
                        service_id=item.service_id,
                        reward_beneficiary=item.reward_beneficiary,
                        effective_group_id=group_id,
                        raw_weight_millionths=item.raw_weight_millionths,
                        group_raw_weight_millionths=group_weights[group_id],
                        group_allocated_q_atoms=group_amount,
                        group_cap_q_atoms=maximum_group_share_q_atoms,
                        group_cap_applied=group_cap_applied,
                        allocated_q_atoms=member_allocations.get(item.service_id, 0),
                        evidence_id=item.evidence_id,
                        evidence_hash=item.evidence_hash,
                        eligibility_snapshot_id=item.eligibility_snapshot_id,
                        finalized_operation_id=item.finalized_operation_id,
                    )
                )

        allocations.sort(key=lambda item: item.service_id)
        allocated_total = sum(item.allocated_q_atoms for item in allocations)
        payload = {
            "calculation_version": self._calculation_version,
            "epoch": epoch,
            "pool_id": "registry",
            "pool_budget_reference": pool_budget_reference,
            "nominal_pool_budget_q_atoms": nominal_pool_budget_q_atoms,
            "independent_group_count": independent_group_count,
            "target_independent_groups": self._target_independent_groups,
            "diversity_factor_millionths": diversity_factor,
            "distributable_pool_q_atoms": distributable,
            "minimum_group_share_cap_millionths": self._minimum_group_share_cap_millionths,
            "maximum_group_share_millionths": maximum_group_share,
            "maximum_group_share_q_atoms": maximum_group_share_q_atoms,
            "total_raw_weight_millionths": total_raw_weight,
            "allocations": [item.model_dump(mode="json") for item in allocations],
            "unallocated_distributable_q_atoms": distributable - allocated_total,
            "unused_pool_q_atoms": nominal_pool_budget_q_atoms - allocated_total,
        }
        return RegistryRewardCalculation(
            calculation_version=self._calculation_version,
            epoch=epoch,
            pool_id="registry",
            pool_budget_reference=pool_budget_reference,
            nominal_pool_budget_q_atoms=nominal_pool_budget_q_atoms,
            independent_group_count=independent_group_count,
            target_independent_groups=self._target_independent_groups,
            diversity_factor_millionths=diversity_factor,
            distributable_pool_q_atoms=distributable,
            minimum_group_share_cap_millionths=self._minimum_group_share_cap_millionths,
            maximum_group_share_millionths=maximum_group_share,
            maximum_group_share_q_atoms=maximum_group_share_q_atoms,
            total_raw_weight_millionths=total_raw_weight,
            allocations=allocations,
            unallocated_distributable_q_atoms=distributable - allocated_total,
            unused_pool_q_atoms=nominal_pool_budget_q_atoms - allocated_total,
            calculation_root=_digest(payload),
        )


__all__ = [
    "DEFAULT_MINIMUM_GROUP_SHARE_CAP_MILLIONTHS",
    "DEFAULT_REGISTRY_TARGET_INDEPENDENT_GROUPS",
    "REGISTRY_REWARD_CALCULATION_VERSION",
    "RegistryEpochRewardCalculator",
    "RegistryRewardAllocation",
    "RegistryRewardCalculation",
]
