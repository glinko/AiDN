"""Consensus-bound ECO-0007 reward reserve records.

This record reserves a calculated reward against an existing development-pool
allocation. It is not a Wallet transfer and it does not mint Q; payment stages
consume the reserve in later, separately enabled transitions.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import (
    DevelopmentRewardSchedule,
    canonical_hash,
)

DEVELOPMENT_REWARD_RESERVE_VERSION = "eco-0007-reward-reserve.v1"


class DevelopmentRewardReserve(BaseModel, frozen=True):
    """Immutable reservation of one calculated reward schedule."""

    reserve_version: str = DEVELOPMENT_REWARD_RESERVE_VERSION
    reserve_id: str = Field(min_length=1)
    pool_allocation_id: str = Field(min_length=1)
    pool_allocation_operation_id: str = Field(min_length=1)
    calculation_operation_id: str = Field(min_length=1)
    calculation_commitment_id: str = Field(min_length=1)
    calculation_root: str = Field(min_length=1)
    reward_id: str = Field(min_length=1)
    contribution_id: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    schedule_hash: str = Field(min_length=1)
    gross_reward_q_atoms: int = Field(gt=0)
    immediate_amount_q_atoms: int = Field(ge=0)
    maturity_stage_one_amount_q_atoms: int = Field(ge=0)
    maturity_stage_two_amount_q_atoms: int = Field(ge=0)
    reserved_q_atoms: int = Field(gt=0)
    remaining_q_atoms: int = Field(ge=0)
    state: Literal["RESERVED"] = "RESERVED"
    reserve_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_reserve_invariants(self) -> DevelopmentRewardReserve:
        if self.reserve_version != DEVELOPMENT_REWARD_RESERVE_VERSION:
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_VERSION_INVALID")
        if self.reserved_q_atoms != self.gross_reward_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_AMOUNT_MISMATCH")
        if self.remaining_q_atoms != self.reserved_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_REMAINING_INVALID")
        if self.gross_reward_q_atoms != (
            self.immediate_amount_q_atoms
            + self.maturity_stage_one_amount_q_atoms
            + self.maturity_stage_two_amount_q_atoms
        ):
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_SCHEDULE_TOTAL_INVALID")
        expected_id = development_reward_reserve_id(
            pool_allocation_id=self.pool_allocation_id,
            reward_id=self.reward_id,
            schedule_hash=self.schedule_hash,
        )
        if self.reserve_id != expected_id:
            raise ValueError("DEVELOPMENT_REWARD_RESERVE_ID_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"reserve_hash"})

    def verify_integrity(self) -> bool:
        return self.reserve_hash == canonical_hash(self.unsigned_payload())


def development_reward_reserve_id(
    *,
    pool_allocation_id: str,
    reward_id: str,
    schedule_hash: str,
) -> str:
    """Derive a stable identity for one reward under one pool allocation."""

    return canonical_hash(
        {
            "reserve_version": DEVELOPMENT_REWARD_RESERVE_VERSION,
            "pool_allocation_id": pool_allocation_id,
            "reward_id": reward_id,
            "schedule_hash": schedule_hash,
        }
    )


def build_development_reward_reserve(
    *,
    pool_allocation_id: str,
    pool_allocation_operation_id: str,
    calculation_operation_id: str,
    calculation_commitment_id: str,
    calculation_root: str,
    schedule: DevelopmentRewardSchedule,
) -> DevelopmentRewardReserve:
    """Build a full, stage-aware reserve from the accepted schedule."""

    schedule_payload = schedule.model_dump(mode="json", exclude={"schedule_hash"})
    if schedule.schedule_hash != canonical_hash(schedule_payload):
        raise ValueError("DEVELOPMENT_REWARD_RESERVE_SCHEDULE_HASH_INVALID")
    if schedule.gross_reward_q_atoms <= 0:
        raise ValueError("DEVELOPMENT_REWARD_RESERVE_AMOUNT_INVALID")
    payload = {
        "reserve_version": DEVELOPMENT_REWARD_RESERVE_VERSION,
        "pool_allocation_id": pool_allocation_id,
        "pool_allocation_operation_id": pool_allocation_operation_id,
        "calculation_operation_id": calculation_operation_id,
        "calculation_commitment_id": calculation_commitment_id,
        "calculation_root": calculation_root,
        "reward_id": schedule.reward_id,
        "contribution_id": schedule.contribution_id,
        "epoch": schedule.distribution_epoch,
        "schedule_hash": schedule.schedule_hash,
        "gross_reward_q_atoms": schedule.gross_reward_q_atoms,
        "immediate_amount_q_atoms": schedule.immediate_amount_q_atoms,
        "maturity_stage_one_amount_q_atoms": schedule.maturity_stage_one_amount_q_atoms,
        "maturity_stage_two_amount_q_atoms": schedule.maturity_stage_two_amount_q_atoms,
        "reserved_q_atoms": schedule.gross_reward_q_atoms,
        "remaining_q_atoms": schedule.gross_reward_q_atoms,
        "state": "RESERVED",
    }
    reserve_id = development_reward_reserve_id(
        pool_allocation_id=pool_allocation_id,
        reward_id=schedule.reward_id,
        schedule_hash=schedule.schedule_hash,
    )
    payload["reserve_id"] = reserve_id
    return DevelopmentRewardReserve(
        **payload,
        reserve_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_REWARD_RESERVE_VERSION",
    "DevelopmentRewardReserve",
    "build_development_reward_reserve",
    "development_reward_reserve_id",
]
