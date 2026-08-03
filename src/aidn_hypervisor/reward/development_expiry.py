"""Consensus-bound ECO-0007 expiry returns for unclaimed reward stages.

An expiry return preserves the original unclaimed record and creates an
append-only accounting record that releases the stage back to carryover. It
does not credit a Wallet and does not mint Q.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import DevelopmentRole, canonical_hash
from aidn_hypervisor.reward.development_unclaimed import DevelopmentRewardUnclaimedRecord

DEVELOPMENT_REWARD_EXPIRY_VERSION = "eco-0007-reward-expiry.v1"


class DevelopmentRewardExpiryRecord(BaseModel, frozen=True):
    """Immutable record returning one expired unclaimed stage to carryover."""

    expiry_version: str = DEVELOPMENT_REWARD_EXPIRY_VERSION
    expiry_id: str = Field(min_length=1)
    expiry_operation_id: str = Field(min_length=1)
    unclaimed_id: str = Field(min_length=1)
    unclaimed_operation_id: str = Field(min_length=1)
    reserve_id: str = Field(min_length=1)
    reserve_operation_id: str = Field(min_length=1)
    pool_allocation_id: str = Field(min_length=1)
    pool_allocation_operation_id: str = Field(min_length=1)
    calculation_operation_id: str = Field(min_length=1)
    source_epoch_transition_operation_id: str = Field(min_length=1)
    calculation_commitment_id: str = Field(min_length=1)
    calculation_root: str = Field(min_length=1)
    reward_id: str = Field(min_length=1)
    contribution_id: str = Field(min_length=1)
    contributor_id: str = Field(min_length=1)
    role: DevelopmentRole
    payment_hash: str = Field(min_length=1)
    payment_stage: Literal["IMMEDIATE", "MATURITY_STAGE_ONE", "MATURITY_STAGE_TWO"]
    amount_q_atoms: int = Field(gt=0)
    distribution_epoch: int = Field(ge=0)
    claim_expiration_epoch: int = Field(gt=0)
    expiry_epoch: int = Field(ge=0)
    return_destination: Literal["CARRYOVER"] = "CARRYOVER"
    reserve_remaining_q_atoms: int = Field(ge=0)
    pool_remaining_q_atoms: int = Field(ge=0)
    state: Literal["EXPIRED_RETURNED"] = "EXPIRED_RETURNED"
    record_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_record_invariants(self) -> DevelopmentRewardExpiryRecord:
        if self.expiry_version != DEVELOPMENT_REWARD_EXPIRY_VERSION:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_VERSION_INVALID")
        if self.expiry_epoch <= self.claim_expiration_epoch:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_NOT_REACHED")
        expected_id = development_reward_expiry_id(
            unclaimed_id=self.unclaimed_id,
            return_destination=self.return_destination,
        )
        if self.expiry_id != expected_id:
            raise ValueError("DEVELOPMENT_REWARD_EXPIRY_ID_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"record_hash"})

    def verify_integrity(self) -> bool:
        return self.record_hash == canonical_hash(self.unsigned_payload())


def development_reward_expiry_id(
    *,
    unclaimed_id: str,
    return_destination: str = "CARRYOVER",
) -> str:
    """Derive one stable return identity for an unclaimed stage."""

    return canonical_hash(
        {
            "expiry_version": DEVELOPMENT_REWARD_EXPIRY_VERSION,
            "unclaimed_id": unclaimed_id,
            "return_destination": return_destination,
        }
    )


def build_development_reward_expiry_record(
    *,
    unclaimed: DevelopmentRewardUnclaimedRecord,
    expiry_operation_id: str,
    unclaimed_operation_id: str,
    source_epoch_transition_operation_id: str,
    expiry_epoch: int,
    reserve_remaining_q_atoms: int,
    pool_remaining_q_atoms: int,
    return_destination: Literal["CARRYOVER"] = "CARRYOVER",
) -> DevelopmentRewardExpiryRecord:
    """Build a deterministic expiry return from an immutable unclaimed stage."""

    if unclaimed.state != "UNCLAIMED":
        raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_STATE_INVALID")
    if expiry_epoch <= unclaimed.claim_expiration_epoch:
        raise ValueError("DEVELOPMENT_REWARD_EXPIRY_NOT_REACHED")
    if reserve_remaining_q_atoms < 0 or pool_remaining_q_atoms < 0:
        raise ValueError("DEVELOPMENT_REWARD_EXPIRY_REMAINING_INVALID")

    expiry_id = development_reward_expiry_id(
        unclaimed_id=unclaimed.unclaimed_id,
        return_destination=return_destination,
    )
    payload = {
        "expiry_version": DEVELOPMENT_REWARD_EXPIRY_VERSION,
        "expiry_id": expiry_id,
        "expiry_operation_id": expiry_operation_id,
        "unclaimed_id": unclaimed.unclaimed_id,
        "unclaimed_operation_id": unclaimed_operation_id,
        "reserve_id": unclaimed.reserve_id,
        "reserve_operation_id": unclaimed.reserve_operation_id,
        "pool_allocation_id": unclaimed.pool_allocation_id,
        "pool_allocation_operation_id": unclaimed.pool_allocation_operation_id,
        "calculation_operation_id": unclaimed.calculation_operation_id,
        "source_epoch_transition_operation_id": source_epoch_transition_operation_id,
        "calculation_commitment_id": unclaimed.calculation_commitment_id,
        "calculation_root": unclaimed.calculation_root,
        "reward_id": unclaimed.reward_id,
        "contribution_id": unclaimed.contribution_id,
        "contributor_id": unclaimed.contributor_id,
        "role": unclaimed.role,
        "payment_hash": unclaimed.payment_hash,
        "payment_stage": unclaimed.payment_stage,
        "amount_q_atoms": unclaimed.amount_q_atoms,
        "distribution_epoch": unclaimed.distribution_epoch,
        "claim_expiration_epoch": unclaimed.claim_expiration_epoch,
        "expiry_epoch": expiry_epoch,
        "return_destination": return_destination,
        "reserve_remaining_q_atoms": reserve_remaining_q_atoms,
        "pool_remaining_q_atoms": pool_remaining_q_atoms,
        "state": "EXPIRED_RETURNED",
    }
    return DevelopmentRewardExpiryRecord(
        **payload,
        record_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_REWARD_EXPIRY_VERSION",
    "DevelopmentRewardExpiryRecord",
    "build_development_reward_expiry_record",
    "development_reward_expiry_id",
]
