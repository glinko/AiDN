"""Consensus-bound ECO-0007 unclaimed reward records.

An unclaimed record preserves a calculated reward stage when the contribution
has no verified Wallet. It does not transfer Q or reduce the source reserve;
the later claim transition will consume this record explicitly.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import (
    DevelopmentRewardPayment,
    DevelopmentRole,
    canonical_hash,
)

DEVELOPMENT_REWARD_UNCLAIMED_VERSION = "eco-0007-reward-unclaimed.v1"


class DevelopmentRewardUnclaimedRecord(BaseModel, frozen=True):
    """Immutable record of one reward stage awaiting Wallet binding."""

    unclaimed_version: str = DEVELOPMENT_REWARD_UNCLAIMED_VERSION
    unclaimed_id: str = Field(min_length=1)
    reserve_id: str = Field(min_length=1)
    reserve_operation_id: str = Field(min_length=1)
    pool_allocation_id: str = Field(min_length=1)
    pool_allocation_operation_id: str = Field(min_length=1)
    calculation_operation_id: str = Field(min_length=1)
    calculation_commitment_id: str = Field(min_length=1)
    calculation_root: str = Field(min_length=1)
    reward_id: str = Field(min_length=1)
    contribution_id: str = Field(min_length=1)
    contributor_id: str = Field(min_length=1)
    role: DevelopmentRole
    payment_hash: str = Field(min_length=1)
    payment_stage: Literal[
        "IMMEDIATE",
        "MATURITY_STAGE_ONE",
        "MATURITY_STAGE_TWO",
    ]
    amount_q_atoms: int = Field(gt=0)
    distribution_epoch: int = Field(ge=0)
    claim_expiration_epoch: int = Field(gt=0)
    state: Literal["UNCLAIMED"] = "UNCLAIMED"
    record_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_record_invariants(self) -> DevelopmentRewardUnclaimedRecord:
        if self.unclaimed_version != DEVELOPMENT_REWARD_UNCLAIMED_VERSION:
            raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_VERSION_INVALID")
        expected_id = development_reward_unclaimed_id(
            reserve_id=self.reserve_id,
            payment_hash=self.payment_hash,
            payment_stage=self.payment_stage,
        )
        if self.unclaimed_id != expected_id:
            raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_ID_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"record_hash"})

    def verify_integrity(self) -> bool:
        return self.record_hash == canonical_hash(self.unsigned_payload())


def development_reward_unclaimed_id(
    *,
    reserve_id: str,
    payment_hash: str,
    payment_stage: str,
) -> str:
    """Derive a stable identity for one unclaimed stage."""

    return canonical_hash(
        {
            "unclaimed_version": DEVELOPMENT_REWARD_UNCLAIMED_VERSION,
            "reserve_id": reserve_id,
            "payment_hash": payment_hash,
            "payment_stage": payment_stage,
        }
    )


def build_development_reward_unclaimed_record(
    *,
    reserve_id: str,
    reserve_operation_id: str,
    pool_allocation_id: str,
    pool_allocation_operation_id: str,
    calculation_operation_id: str,
    calculation_commitment_id: str,
    calculation_root: str,
    payment: DevelopmentRewardPayment,
    distribution_epoch: int,
    claim_expiration_epoch: int,
) -> DevelopmentRewardUnclaimedRecord:
    """Build a deterministic unclaimed record from an UNCLAIMED stage."""

    if payment.state != "UNCLAIMED":
        raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_STATE_INVALID")
    if payment.wallet_address is not None:
        raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_WALLET_INVALID")
    if payment.amount_q_atoms <= 0:
        raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_AMOUNT_INVALID")
    if distribution_epoch < 0:
        raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_EPOCH_INVALID")
    if claim_expiration_epoch <= 0:
        raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_EXPIRATION_INVALID")
    if payment.payment_hash != canonical_hash(
        payment.model_dump(mode="json", exclude={"payment_hash"})
    ):
        raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_HASH_INVALID")

    unclaimed_id = development_reward_unclaimed_id(
        reserve_id=reserve_id,
        payment_hash=payment.payment_hash,
        payment_stage=payment.payment_stage,
    )
    payload = {
        "unclaimed_version": DEVELOPMENT_REWARD_UNCLAIMED_VERSION,
        "unclaimed_id": unclaimed_id,
        "reserve_id": reserve_id,
        "reserve_operation_id": reserve_operation_id,
        "pool_allocation_id": pool_allocation_id,
        "pool_allocation_operation_id": pool_allocation_operation_id,
        "calculation_operation_id": calculation_operation_id,
        "calculation_commitment_id": calculation_commitment_id,
        "calculation_root": calculation_root,
        "reward_id": payment.reward_id,
        "contribution_id": payment.contribution_id,
        "contributor_id": payment.contributor_id,
        "role": payment.role,
        "payment_hash": payment.payment_hash,
        "payment_stage": payment.payment_stage,
        "amount_q_atoms": payment.amount_q_atoms,
        "distribution_epoch": distribution_epoch,
        "claim_expiration_epoch": claim_expiration_epoch,
        "state": "UNCLAIMED",
    }
    return DevelopmentRewardUnclaimedRecord(
        **payload,
        record_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_REWARD_UNCLAIMED_VERSION",
    "DevelopmentRewardUnclaimedRecord",
    "build_development_reward_unclaimed_record",
    "development_reward_unclaimed_id",
]
