"""Production-bound ECO-0007 contribution reward batches.

The calculator and the activation gate already provide deterministic reward
evidence. This module adds the deployment binding that is needed before an
operator may submit that evidence as a real consensus batch: network and
chain identity, the exact authorized operation scope, and bounded batch size.

The resulting object is still a plan, not a direct mint instruction. Wallet
credits happen only when the ordered envelopes are accepted and finalized by
the canonical consensus path.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_activation import (
    DevelopmentRewardActivationApproval,
    development_reward_policy_hash,
    verify_development_reward_activation_approval,
)
from aidn_hypervisor.reward.development_contribution_service import (
    DevelopmentRewardOperationPlan,
)
from aidn_hypervisor.reward.development_distribution import (
    DevelopmentRewardPolicy,
    canonical_hash,
)

DEVELOPMENT_REWARD_PRODUCTION_PROFILE_VERSION = "eco-0007-production-profile.v1"
DEVELOPMENT_REWARD_PRODUCTION_BATCH_VERSION = "eco-0007-production-batch.v1"

PRODUCTION_REWARD_OPERATION_TYPES = (
    "DEVELOPMENT_REWARD_CALCULATE",
    "DEVELOPMENT_POOL_ALLOCATE",
    "DEVELOPMENT_REWARD_RESERVE",
    "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
    "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
)


class DevelopmentRewardProductionProfile(BaseModel, frozen=True):
    """A future-effective, deployment-specific ECO-0007 execution profile."""

    profile_version: str = DEVELOPMENT_REWARD_PRODUCTION_PROFILE_VERSION
    profile_id: str = Field(min_length=1)
    network_id: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    effective_epoch: int = Field(ge=0)
    pool_id: str = "GENERAL_DEVELOPMENT"
    policy: DevelopmentRewardPolicy
    policy_hash: str = Field(min_length=1)
    activation_id: str = Field(min_length=1)
    activation_approval_hash: str = Field(min_length=1)
    authorized_operation_types: list[str] = Field(min_length=1)
    max_batch_q_atoms: int = Field(gt=0)
    max_contributions: int = Field(gt=0)
    max_operations: int = Field(gt=0)
    state: Literal["ACTIVE"] = "ACTIVE"
    profile_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_profile(self) -> DevelopmentRewardProductionProfile:
        if self.profile_version != DEVELOPMENT_REWARD_PRODUCTION_PROFILE_VERSION:
            raise ValueError("DEVELOPMENT_PRODUCTION_PROFILE_VERSION_INVALID")
        if not self.pool_id.strip():
            raise ValueError("DEVELOPMENT_PRODUCTION_POOL_ID_INVALID")
        if self.policy_hash != development_reward_policy_hash(self.policy):
            raise ValueError("DEVELOPMENT_PRODUCTION_POLICY_HASH_INVALID")
        operation_types = [item.strip() for item in self.authorized_operation_types]
        if any(not item for item in operation_types) or len(set(operation_types)) != len(operation_types):
            raise ValueError("DEVELOPMENT_PRODUCTION_OPERATION_SCOPE_INVALID")
        if any(item not in operation_types for item in PRODUCTION_REWARD_OPERATION_TYPES):
            raise ValueError("DEVELOPMENT_PRODUCTION_OPERATION_SCOPE_INCOMPLETE")
        if self.max_operations < self.max_contributions + 2:
            raise ValueError("DEVELOPMENT_PRODUCTION_OPERATION_CAP_INVALID")
        expected_id = development_reward_production_profile_id(
            network_id=self.network_id,
            chain_id=self.chain_id,
            effective_epoch=self.effective_epoch,
            pool_id=self.pool_id,
            policy_hash=self.policy_hash,
            activation_id=self.activation_id,
            activation_approval_hash=self.activation_approval_hash,
            authorized_operation_types=operation_types,
            max_batch_q_atoms=self.max_batch_q_atoms,
            max_contributions=self.max_contributions,
            max_operations=self.max_operations,
        )
        if self.profile_id != expected_id:
            raise ValueError("DEVELOPMENT_PRODUCTION_PROFILE_ID_INVALID")
        if self.profile_hash != development_reward_production_profile_hash(self):
            raise ValueError("DEVELOPMENT_PRODUCTION_PROFILE_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"profile_hash"})

    def verify_integrity(self) -> bool:
        return self.profile_hash == development_reward_production_profile_hash(self)


class DevelopmentRewardProductionBatch(BaseModel, frozen=True):
    """A complete, bounded consensus plan for one production reward batch."""

    batch_version: str = DEVELOPMENT_REWARD_PRODUCTION_BATCH_VERSION
    batch_id: str = Field(min_length=1)
    mode: Literal["PRODUCTION_CONSENSUS_PLAN"] = "PRODUCTION_CONSENSUS_PLAN"
    network_id: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    pool_id: str = Field(min_length=1)
    source_epoch_transition_operation_id: str = Field(min_length=1)
    pool_budget_reference: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    profile_hash: str = Field(min_length=1)
    activation_id: str = Field(min_length=1)
    activation_approval_hash: str = Field(min_length=1)
    plan: DevelopmentRewardOperationPlan
    accepted_reward_q_atoms: int = Field(ge=0)
    immediate_payment_q_atoms: int = Field(ge=0)
    unclaimed_stage_q_atoms: int = Field(ge=0)
    reserved_maturity_q_atoms: int = Field(ge=0)
    contributor_count: int = Field(ge=0)
    payout_operation_count: int = Field(ge=0)
    batch_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_batch(self) -> DevelopmentRewardProductionBatch:
        if self.batch_version != DEVELOPMENT_REWARD_PRODUCTION_BATCH_VERSION:
            raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_VERSION_INVALID")
        if self.plan.mode != "CONSENSUS_GATED":
            raise ValueError("DEVELOPMENT_PRODUCTION_PLAN_MODE_INVALID")
        if self.plan.epoch != self.epoch:
            raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_EPOCH_INVALID")
        commitment = self.plan.commitment
        if commitment.activation_state != "ACTIVATION_VERIFIED":
            raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_ACTIVATION_REQUIRED")
        if commitment.activation_id != self.activation_id:
            raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_ACTIVATION_MISMATCH")
        if commitment.activation_approval_hash != self.activation_approval_hash:
            raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_APPROVAL_MISMATCH")
        if self.plan.envelopes[0].operation_type != "DEVELOPMENT_REWARD_CALCULATE":
            raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_CALCULATION_FIRST_REQUIRED")
        operation_ids = [item.operation_id for item in self.plan.envelopes]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_OPERATION_DUPLICATE")
        expected_hash = development_reward_production_batch_hash(self)
        if self.batch_hash != expected_hash:
            raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"batch_hash"})

    def verify_integrity(self) -> bool:
        return self.batch_hash == development_reward_production_batch_hash(self)


def development_reward_production_profile_id(
    *,
    network_id: str,
    chain_id: str,
    effective_epoch: int,
    pool_id: str,
    policy_hash: str,
    activation_id: str,
    activation_approval_hash: str,
    authorized_operation_types: list[str],
    max_batch_q_atoms: int,
    max_contributions: int,
    max_operations: int,
) -> str:
    return canonical_hash(
        {
            "profile_version": DEVELOPMENT_REWARD_PRODUCTION_PROFILE_VERSION,
            "network_id": network_id,
            "chain_id": chain_id,
            "effective_epoch": effective_epoch,
            "pool_id": pool_id,
            "policy_hash": policy_hash,
            "activation_id": activation_id,
            "activation_approval_hash": activation_approval_hash,
            "authorized_operation_types": sorted(authorized_operation_types),
            "max_batch_q_atoms": max_batch_q_atoms,
            "max_contributions": max_contributions,
            "max_operations": max_operations,
        }
    )


def development_reward_production_profile_hash(
    profile: DevelopmentRewardProductionProfile,
) -> str:
    return canonical_hash(profile.unsigned_payload())


def build_development_reward_production_profile(
    *,
    network_id: str,
    chain_id: str,
    effective_epoch: int,
    activation_approval: DevelopmentRewardActivationApproval,
    policy: DevelopmentRewardPolicy,
    max_batch_q_atoms: int,
    max_contributions: int,
    max_operations: int,
    pool_id: str = "GENERAL_DEVELOPMENT",
) -> DevelopmentRewardProductionProfile:
    """Derive a production profile from the exact signed activation approval."""

    verify_development_reward_activation_approval(activation_approval)
    policy_hash = development_reward_policy_hash(policy)
    if activation_approval.policy_hash != policy_hash:
        raise ValueError("DEVELOPMENT_PRODUCTION_POLICY_ACTIVATION_MISMATCH")
    if effective_epoch < activation_approval.effective_epoch:
        raise ValueError("DEVELOPMENT_PRODUCTION_EFFECTIVE_EPOCH_INVALID")
    if activation_approval.economic_effect_profile != "DEVELOPMENT_PAYMENTS":
        raise ValueError("DEVELOPMENT_PRODUCTION_PAYMENT_SCOPE_REQUIRED")
    operation_types = sorted(activation_approval.authorized_operation_types)
    profile_id = development_reward_production_profile_id(
        network_id=network_id,
        chain_id=chain_id,
        effective_epoch=effective_epoch,
        pool_id=pool_id,
        policy_hash=policy_hash,
        activation_id=activation_approval.activation_id,
        activation_approval_hash=activation_approval.approval_hash or "",
        authorized_operation_types=operation_types,
        max_batch_q_atoms=max_batch_q_atoms,
        max_contributions=max_contributions,
        max_operations=max_operations,
    )
    payload = {
        "profile_version": DEVELOPMENT_REWARD_PRODUCTION_PROFILE_VERSION,
        "profile_id": profile_id,
        "network_id": network_id,
        "chain_id": chain_id,
        "effective_epoch": effective_epoch,
        "pool_id": pool_id,
        "policy": policy.model_dump(mode="json"),
        "policy_hash": policy_hash,
        "activation_id": activation_approval.activation_id,
        "activation_approval_hash": activation_approval.approval_hash or "",
        "authorized_operation_types": operation_types,
        "max_batch_q_atoms": max_batch_q_atoms,
        "max_contributions": max_contributions,
        "max_operations": max_operations,
        "state": "ACTIVE",
    }
    return DevelopmentRewardProductionProfile(
        **payload,
        profile_hash=canonical_hash(payload),
    )


def development_reward_production_batch_hash(
    batch: DevelopmentRewardProductionBatch,
) -> str:
    return canonical_hash(batch.unsigned_payload())


def build_development_reward_production_batch(
    *,
    profile: DevelopmentRewardProductionProfile,
    activation_approval: DevelopmentRewardActivationApproval,
    plan: DevelopmentRewardOperationPlan,
    source_epoch_transition_operation_id: str,
    pool_budget_reference: str,
) -> DevelopmentRewardProductionBatch:
    """Bind one consensus plan to a production network and bounded profile."""

    if not profile.verify_integrity():
        raise ValueError("DEVELOPMENT_PRODUCTION_PROFILE_HASH_INVALID")
    verify_development_reward_activation_approval(activation_approval)
    if activation_approval.activation_id != profile.activation_id:
        raise ValueError("DEVELOPMENT_PRODUCTION_ACTIVATION_ID_MISMATCH")
    if activation_approval.approval_hash != profile.activation_approval_hash:
        raise ValueError("DEVELOPMENT_PRODUCTION_ACTIVATION_HASH_MISMATCH")
    if plan.epoch < profile.effective_epoch:
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_BEFORE_EFFECTIVE_EPOCH")
    if plan.commitment.policy_hash != profile.policy_hash:
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_POLICY_MISMATCH")
    if plan.commitment.activation_id != profile.activation_id:
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_ACTIVATION_MISMATCH")
    if plan.commitment.activation_approval_hash != profile.activation_approval_hash:
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_APPROVAL_MISMATCH")
    if len(plan.envelopes) > profile.max_operations:
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_OPERATION_CAP_EXCEEDED")
    allowed = set(profile.authorized_operation_types)
    if any(item.operation_type not in allowed for item in plan.envelopes):
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_OPERATION_NOT_AUTHORIZED")
    if any(
        item.payload.get("source_epoch_transition_operation_id") not in {None, source_epoch_transition_operation_id}
        for item in plan.envelopes
    ):
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_EPOCH_SOURCE_MISMATCH")
    if len(plan.envelopes) < 2 or plan.envelopes[1].operation_type != "DEVELOPMENT_POOL_ALLOCATE":
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_ALLOCATION_REQUIRED")
    allocation_payload = plan.envelopes[1].payload.get("pool_allocation") or {}
    if allocation_payload.get("pool_id") != profile.pool_id:
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_POOL_MISMATCH")
    if allocation_payload.get("epoch") != plan.epoch:
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_ALLOCATION_EPOCH_MISMATCH")
    if plan.envelopes[1].payload.get("pool_budget_reference") != pool_budget_reference:
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_BUDGET_REFERENCE_MISMATCH")

    calculation_envelope = plan.envelopes[0]
    calculation_payload = calculation_envelope.payload.get("calculation") or {}
    accepted_reward = int(calculation_payload.get("accepted_gross_reward_q_atoms", 0))
    if accepted_reward <= 0 or len(plan.envelopes) < 2:
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_NO_PAYOUT")
    if accepted_reward > profile.max_batch_q_atoms:
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_AMOUNT_CAP_EXCEEDED")
    if len(calculation_payload.get("allocations") or []) > profile.max_contributions:
        raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_CONTRIBUTION_CAP_EXCEEDED")

    immediate = 0
    unclaimed = 0
    maturity = 0
    payout_operations = 0
    for envelope in plan.envelopes:
        amount = int(envelope.payload.get("amount_q_atoms") or 0)
        if envelope.operation_type == "DEVELOPMENT_REWARD_PAY_IMMEDIATE":
            immediate += amount
            payout_operations += 1
        elif envelope.operation_type == "DEVELOPMENT_REWARD_MARK_UNCLAIMED":
            unclaimed += amount
            payout_operations += 1
        elif envelope.operation_type == "DEVELOPMENT_REWARD_RESERVE":
            reserve = envelope.payload.get("reward_reserve") or {}
            maturity += int(reserve.get("maturity_stage_one_amount_q_atoms", 0))
            maturity += int(reserve.get("maturity_stage_two_amount_q_atoms", 0))
    contributor_ids = {
        str(item.get("contributor_id"))
        for item in (calculation_payload.get("payments") or [])
        if item.get("contributor_id")
    }
    payload = {
        "batch_version": DEVELOPMENT_REWARD_PRODUCTION_BATCH_VERSION,
        "batch_id": "pending",
        "mode": "PRODUCTION_CONSENSUS_PLAN",
        "network_id": profile.network_id,
        "chain_id": profile.chain_id,
        "epoch": plan.epoch,
        "pool_id": profile.pool_id,
        "source_epoch_transition_operation_id": source_epoch_transition_operation_id,
        "pool_budget_reference": pool_budget_reference,
        "profile_id": profile.profile_id,
        "profile_hash": profile.profile_hash,
        "activation_id": profile.activation_id,
        "activation_approval_hash": profile.activation_approval_hash,
        "plan": plan.model_dump(mode="json"),
        "accepted_reward_q_atoms": accepted_reward,
        "immediate_payment_q_atoms": immediate,
        "unclaimed_stage_q_atoms": unclaimed,
        "reserved_maturity_q_atoms": maturity,
        "contributor_count": len(contributor_ids),
        "payout_operation_count": payout_operations,
    }
    batch_id = canonical_hash(
        {
            "batch_version": DEVELOPMENT_REWARD_PRODUCTION_BATCH_VERSION,
            "network_id": profile.network_id,
            "chain_id": profile.chain_id,
            "epoch": plan.epoch,
            "profile_hash": profile.profile_hash,
            "plan_hash": plan.plan_hash,
            "source_epoch_transition_operation_id": source_epoch_transition_operation_id,
            "pool_budget_reference": pool_budget_reference,
        }
    )
    payload["batch_id"] = batch_id
    return DevelopmentRewardProductionBatch(
        **payload,
        batch_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_REWARD_PRODUCTION_BATCH_VERSION",
    "DEVELOPMENT_REWARD_PRODUCTION_PROFILE_VERSION",
    "PRODUCTION_REWARD_OPERATION_TYPES",
    "DevelopmentRewardProductionBatch",
    "DevelopmentRewardProductionProfile",
    "build_development_reward_production_batch",
    "build_development_reward_production_profile",
    "development_reward_production_batch_hash",
    "development_reward_production_profile_hash",
    "development_reward_production_profile_id",
]
