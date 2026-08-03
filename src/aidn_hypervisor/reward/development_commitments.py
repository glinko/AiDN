"""Non-emitting canonical commitments for ECO-0007 evidence."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from aidn_hypervisor.reward.development_activation import (
    DevelopmentRewardActivationApproval,
    DevelopmentRewardActivationGate,
    development_reward_policy_hash,
)
from aidn_hypervisor.reward.development_distribution import (
    DEVELOPMENT_REWARD_CALCULATION_VERSION,
    DevelopmentRewardCalculation,
    canonical_hash,
)

DEVELOPMENT_REWARD_COMMITMENT_VERSION = "eco-0007-commitment.v1"


class DevelopmentRewardCommitment(BaseModel, frozen=True):
    """Compact evidence commitment; it carries no transfer authority."""

    commitment_version: str = DEVELOPMENT_REWARD_COMMITMENT_VERSION
    commitment_id: str = Field(min_length=1)
    simulation_only: Literal[True] = True
    emits_q: Literal[False] = False
    ledger_writes: Literal[False] = False
    activation_state: Literal["SIMULATION_ONLY", "ACTIVATION_VERIFIED"]
    activation_id: str | None = None
    activation_approval_hash: str | None = None
    policy_hash: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    calculation_root: str = Field(min_length=1)
    pool_hash: str = Field(min_length=1)
    allocation_root: str = Field(min_length=1)
    schedule_root: str = Field(min_length=1)
    payment_state_root: str = Field(min_length=1)
    accepted_gross_reward_q_atoms: int = Field(ge=0)
    unclaimed_scheduled_q_atoms: int = Field(ge=0)
    commitment_hash: str = Field(min_length=1)

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"commitment_hash"})

    def verify_integrity(self) -> bool:
        return self.commitment_hash == canonical_hash(self.unsigned_payload())


def _root(items: list[dict[str, Any]]) -> str:
    return canonical_hash(items)


def build_development_reward_commitment(
    calculation: DevelopmentRewardCalculation,
    *,
    activation_approval: DevelopmentRewardActivationApproval | None = None,
    current_epoch: int | None = None,
) -> DevelopmentRewardCommitment:
    """Build a deterministic evidence commitment without touching economic state."""

    if calculation.calculation_version != DEVELOPMENT_REWARD_CALCULATION_VERSION:
        raise ValueError("DEVELOPMENT_COMMITMENT_CALCULATION_VERSION_INVALID")
    if not calculation.verify_integrity():
        raise ValueError("DEVELOPMENT_COMMITMENT_CALCULATION_INVALID")

    policy_hash = development_reward_policy_hash(calculation.policy)
    activation_state: Literal["SIMULATION_ONLY", "ACTIVATION_VERIFIED"] = "SIMULATION_ONLY"
    activation_id: str | None = None
    activation_approval_hash: str | None = None
    if activation_approval is not None:
        if current_epoch is None:
            raise ValueError("DEVELOPMENT_COMMITMENT_CURRENT_EPOCH_REQUIRED")
        decision = DevelopmentRewardActivationGate.assert_active(
            calculation=calculation,
            approval=activation_approval,
            current_epoch=current_epoch,
        )
        activation_state = "ACTIVATION_VERIFIED"
        activation_id = decision.activation_id
        activation_approval_hash = activation_approval.approval_hash

    allocation_root = _root([item.model_dump(mode="json") for item in calculation.allocations])
    schedule_root = _root([item.model_dump(mode="json") for item in calculation.schedules])
    payment_state_root = _root([item.model_dump(mode="json") for item in calculation.payments])
    identity_payload = {
        "commitment_version": DEVELOPMENT_REWARD_COMMITMENT_VERSION,
        "policy_hash": policy_hash,
        "epoch": calculation.epoch,
        "calculation_root": calculation.calculation_root,
        "pool_hash": calculation.pool.pool_hash,
        "allocation_root": allocation_root,
        "schedule_root": schedule_root,
        "payment_state_root": payment_state_root,
        "activation_id": activation_id,
        "activation_approval_hash": activation_approval_hash,
    }
    commitment_id = canonical_hash(identity_payload)
    payload = {
        "commitment_version": DEVELOPMENT_REWARD_COMMITMENT_VERSION,
        "commitment_id": commitment_id,
        "simulation_only": True,
        "emits_q": False,
        "ledger_writes": False,
        "activation_state": activation_state,
        "activation_id": activation_id,
        "activation_approval_hash": activation_approval_hash,
        "policy_hash": policy_hash,
        "epoch": calculation.epoch,
        "calculation_root": calculation.calculation_root,
        "pool_hash": calculation.pool.pool_hash,
        "allocation_root": allocation_root,
        "schedule_root": schedule_root,
        "payment_state_root": payment_state_root,
        "accepted_gross_reward_q_atoms": calculation.accepted_gross_reward_q_atoms,
        "unclaimed_scheduled_q_atoms": calculation.unclaimed_scheduled_q_atoms,
    }
    return DevelopmentRewardCommitment(
        **payload,
        commitment_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_REWARD_COMMITMENT_VERSION",
    "DevelopmentRewardCommitment",
    "build_development_reward_commitment",
]
