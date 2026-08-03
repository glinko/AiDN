"""Consensus-bound ECO-0007 development reward payment records.

The payment record is materialized after a payment envelope is accepted. It
is deliberately separate from ``REWARD_MINT`` and carries the source-bound
pool and reserve balances observed by the Ledger.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import (
    DevelopmentRewardPayment,
    DevelopmentRole,
    canonical_hash,
)

DEVELOPMENT_REWARD_PAYMENT_VERSION = "eco-0007-reward-payment.v1"


class DevelopmentRewardPaymentRecord(BaseModel, frozen=True):
    """Immutable record of one paid contribution-reward stage."""

    payment_version: str = DEVELOPMENT_REWARD_PAYMENT_VERSION
    payment_id: str = Field(min_length=1)
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
    wallet_address: str = Field(min_length=1)
    payment_hash: str = Field(min_length=1)
    payment_stage: Literal["IMMEDIATE", "MATURITY_STAGE_ONE", "MATURITY_STAGE_TWO"] = "IMMEDIATE"
    amount_q_atoms: int = Field(gt=0)
    reserve_remaining_q_atoms: int = Field(ge=0)
    pool_remaining_q_atoms: int = Field(ge=0)
    state: Literal["PAID"] = "PAID"
    record_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_record_invariants(self) -> DevelopmentRewardPaymentRecord:
        if self.payment_version != DEVELOPMENT_REWARD_PAYMENT_VERSION:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_VERSION_INVALID")
        expected_id = development_reward_payment_id(
            reserve_id=self.reserve_id,
            payment_hash=self.payment_hash,
            payment_stage=self.payment_stage,
        )
        if self.payment_id != expected_id:
            raise ValueError("DEVELOPMENT_REWARD_PAYMENT_ID_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"record_hash"})

    def verify_integrity(self) -> bool:
        return self.record_hash == canonical_hash(self.unsigned_payload())


def development_reward_payment_id(
    *,
    reserve_id: str,
    payment_hash: str,
    payment_stage: str,
) -> str:
    """Derive a stable semantic identity independent of envelope metadata."""

    return canonical_hash(
        {
            "payment_version": DEVELOPMENT_REWARD_PAYMENT_VERSION,
            "reserve_id": reserve_id,
            "payment_hash": payment_hash,
            "payment_stage": payment_stage,
        }
    )


def build_development_reward_payment_record(
    *,
    reserve_id: str,
    reserve_operation_id: str,
    pool_allocation_id: str,
    pool_allocation_operation_id: str,
    calculation_operation_id: str,
    calculation_commitment_id: str,
    calculation_root: str,
    payment: DevelopmentRewardPayment,
    reserve_remaining_q_atoms: int,
    pool_remaining_q_atoms: int,
) -> DevelopmentRewardPaymentRecord:
    """Build a deterministic payment record from a calculated payable item."""

    if payment.payment_stage not in {"IMMEDIATE", "MATURITY_STAGE_ONE", "MATURITY_STAGE_TWO"}:
        raise ValueError("DEVELOPMENT_REWARD_PAYMENT_STAGE_INVALID")
    if payment.state not in {"PAYABLE", "RESERVED"}:
        raise ValueError("DEVELOPMENT_REWARD_PAYMENT_NOT_PAYABLE")
    if not payment.wallet_address:
        raise ValueError("DEVELOPMENT_REWARD_PAYMENT_WALLET_UNAVAILABLE")
    if payment.payment_hash != canonical_hash(
        payment.model_dump(mode="json", exclude={"payment_hash"})
    ):
        raise ValueError("DEVELOPMENT_REWARD_PAYMENT_HASH_INVALID")
    if reserve_remaining_q_atoms < 0 or pool_remaining_q_atoms < 0:
        raise ValueError("DEVELOPMENT_REWARD_PAYMENT_REMAINING_INVALID")

    payment_id = development_reward_payment_id(
        reserve_id=reserve_id,
        payment_hash=payment.payment_hash,
        payment_stage=payment.payment_stage,
    )
    payload = {
        "payment_version": DEVELOPMENT_REWARD_PAYMENT_VERSION,
        "payment_id": payment_id,
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
        "wallet_address": payment.wallet_address,
        "payment_hash": payment.payment_hash,
        "payment_stage": payment.payment_stage,
        "amount_q_atoms": payment.amount_q_atoms,
        "reserve_remaining_q_atoms": reserve_remaining_q_atoms,
        "pool_remaining_q_atoms": pool_remaining_q_atoms,
        "state": "PAID",
    }
    return DevelopmentRewardPaymentRecord(
        **payload,
        record_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_REWARD_PAYMENT_VERSION",
    "DevelopmentRewardPaymentRecord",
    "build_development_reward_payment_record",
    "development_reward_payment_id",
]
