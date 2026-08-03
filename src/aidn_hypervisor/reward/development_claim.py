"""Consensus-bound ECO-0007 Wallet claims for unclaimed reward stages.

The claim record consumes one previously recorded unclaimed stage. Wallet
ownership is carried as an RFC-0068 signed binding proof, while the original
unclaimed record remains immutable evidence in Ledger state.
"""

from __future__ import annotations

from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.contributions.models import canonical_hash as contribution_canonical_hash
from aidn_hypervisor.contributions.service import contributor_wallet_binding_payload
from aidn_hypervisor.reward.development_distribution import DevelopmentRole, canonical_hash
from aidn_hypervisor.reward.development_unclaimed import DevelopmentRewardUnclaimedRecord

DEVELOPMENT_REWARD_CLAIM_VERSION = "eco-0007-reward-claim.v1"


def _decode_ed25519(value: str, *, size: int, error_code: str) -> bytes:
    if not value.startswith("ed25519:"):
        raise ValueError(error_code)
    try:
        decoded = bytes.fromhex(value.removeprefix("ed25519:"))
    except ValueError as error:
        raise ValueError(error_code) from error
    if len(decoded) != size:
        raise ValueError(error_code)
    return decoded


class DevelopmentRewardWalletBindingProof(BaseModel, frozen=True):
    """RFC-0068 Wallet binding evidence accepted by a reward claim."""

    binding_id: str = Field(min_length=1)
    contributor_id: str = Field(min_length=1)
    source_platform_account: str = Field(min_length=1)
    wallet_address: str = Field(min_length=1)
    wallet_public_key: str = Field(min_length=1)
    challenge_id: str = Field(min_length=1)
    challenge_hash: str = Field(min_length=1)
    wallet_signature: str = Field(min_length=1)
    source_platform_confirmation_hash: str = Field(min_length=1)
    valid_from: str = Field(min_length=1)
    binding_version: int = Field(gt=0)
    binding_hash: str = Field(min_length=1)

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"binding_id", "binding_hash"})

    def verify_integrity(self) -> bool:
        expected_hash = contribution_canonical_hash(self.unsigned_payload())
        return self.binding_id == expected_hash and self.binding_hash == expected_hash

    def verify_signature(self) -> None:
        if not self.verify_integrity():
            raise ValueError("DEVELOPMENT_REWARD_WALLET_BINDING_INVALID")
        payload = contributor_wallet_binding_payload(
            contributor_id=self.contributor_id,
            source_platform_account=self.source_platform_account,
            wallet_address=self.wallet_address,
            wallet_public_key=self.wallet_public_key,
            challenge_id=self.challenge_id,
            challenge_hash=self.challenge_hash,
            binding_version=self.binding_version,
        )
        try:
            public_key = Ed25519PublicKey.from_public_bytes(
                _decode_ed25519(
                    self.wallet_public_key,
                    size=32,
                    error_code="DEVELOPMENT_REWARD_WALLET_PUBLIC_KEY_INVALID",
                )
            )
            signature = _decode_ed25519(
                self.wallet_signature,
                size=64,
                error_code="DEVELOPMENT_REWARD_WALLET_SIGNATURE_INVALID",
            )
            public_key.verify(signature, payload)
        except (InvalidSignature, TypeError, ValueError) as error:
            if isinstance(error, ValueError) and str(error).startswith("DEVELOPMENT_REWARD_"):
                raise
            raise ValueError("DEVELOPMENT_REWARD_WALLET_SIGNATURE_INVALID") from error


class DevelopmentRewardClaimRecord(BaseModel, frozen=True):
    """Immutable record consuming one unclaimed reward stage."""

    claim_version: str = DEVELOPMENT_REWARD_CLAIM_VERSION
    claim_id: str = Field(min_length=1)
    claim_operation_id: str = Field(min_length=1)
    unclaimed_id: str = Field(min_length=1)
    unclaimed_operation_id: str = Field(min_length=1)
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
    payment_stage: Literal["IMMEDIATE", "MATURITY_STAGE_ONE", "MATURITY_STAGE_TWO"]
    amount_q_atoms: int = Field(gt=0)
    claim_epoch: int = Field(ge=0)
    claim_expiration_epoch: int = Field(gt=0)
    wallet_address: str = Field(min_length=1)
    wallet_binding_id: str = Field(min_length=1)
    wallet_binding_hash: str = Field(min_length=1)
    wallet_binding_version: int = Field(gt=0)
    reserve_remaining_q_atoms: int = Field(ge=0)
    pool_remaining_q_atoms: int = Field(ge=0)
    state: Literal["CLAIMED"] = "CLAIMED"
    record_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_record_invariants(self) -> DevelopmentRewardClaimRecord:
        if self.claim_version != DEVELOPMENT_REWARD_CLAIM_VERSION:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_VERSION_INVALID")
        if self.claim_epoch > self.claim_expiration_epoch:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_EPOCH_INVALID")
        expected_id = development_reward_claim_id(
            unclaimed_id=self.unclaimed_id,
            wallet_binding_id=self.wallet_binding_id,
            claim_epoch=self.claim_epoch,
        )
        if self.claim_id != expected_id:
            raise ValueError("DEVELOPMENT_REWARD_CLAIM_ID_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"record_hash"})

    def verify_integrity(self) -> bool:
        return self.record_hash == canonical_hash(self.unsigned_payload())


def development_reward_claim_id(
    *,
    unclaimed_id: str,
    wallet_binding_id: str,
    claim_epoch: int,
) -> str:
    """Derive a stable identity for one Wallet claim attempt."""

    return canonical_hash(
        {
            "claim_version": DEVELOPMENT_REWARD_CLAIM_VERSION,
            "unclaimed_id": unclaimed_id,
            "wallet_binding_id": wallet_binding_id,
            "claim_epoch": claim_epoch,
        }
    )


def build_development_reward_claim_record(
    *,
    unclaimed: DevelopmentRewardUnclaimedRecord,
    claim_operation_id: str,
    unclaimed_operation_id: str,
    binding: DevelopmentRewardWalletBindingProof,
    claim_epoch: int,
    reserve_remaining_q_atoms: int,
    pool_remaining_q_atoms: int,
) -> DevelopmentRewardClaimRecord:
    """Build a deterministic claim record from an unclaimed stage and binding."""

    if unclaimed.state != "UNCLAIMED":
        raise ValueError("DEVELOPMENT_REWARD_UNCLAIMED_STATE_INVALID")
    if claim_epoch < unclaimed.distribution_epoch:
        raise ValueError("DEVELOPMENT_REWARD_CLAIM_EPOCH_INVALID")
    if claim_epoch > unclaimed.claim_expiration_epoch:
        raise ValueError("DEVELOPMENT_CLAIM_WINDOW_EXPIRED")
    if binding.contributor_id != unclaimed.contributor_id:
        raise ValueError("DEVELOPMENT_REWARD_WALLET_BINDING_CONTRIBUTOR_MISMATCH")
    if binding.wallet_address == "":
        raise ValueError("DEVELOPMENT_REWARD_WALLET_BINDING_INVALID")
    if reserve_remaining_q_atoms < 0 or pool_remaining_q_atoms < 0:
        raise ValueError("DEVELOPMENT_REWARD_CLAIM_REMAINING_INVALID")

    claim_id = development_reward_claim_id(
        unclaimed_id=unclaimed.unclaimed_id,
        wallet_binding_id=binding.binding_id,
        claim_epoch=claim_epoch,
    )
    payload = {
        "claim_version": DEVELOPMENT_REWARD_CLAIM_VERSION,
        "claim_id": claim_id,
        "claim_operation_id": claim_operation_id,
        "unclaimed_id": unclaimed.unclaimed_id,
        "unclaimed_operation_id": unclaimed_operation_id,
        "reserve_id": unclaimed.reserve_id,
        "reserve_operation_id": unclaimed.reserve_operation_id,
        "pool_allocation_id": unclaimed.pool_allocation_id,
        "pool_allocation_operation_id": unclaimed.pool_allocation_operation_id,
        "calculation_operation_id": unclaimed.calculation_operation_id,
        "calculation_commitment_id": unclaimed.calculation_commitment_id,
        "calculation_root": unclaimed.calculation_root,
        "reward_id": unclaimed.reward_id,
        "contribution_id": unclaimed.contribution_id,
        "contributor_id": unclaimed.contributor_id,
        "role": unclaimed.role,
        "payment_hash": unclaimed.payment_hash,
        "payment_stage": unclaimed.payment_stage,
        "amount_q_atoms": unclaimed.amount_q_atoms,
        "claim_epoch": claim_epoch,
        "claim_expiration_epoch": unclaimed.claim_expiration_epoch,
        "wallet_address": binding.wallet_address,
        "wallet_binding_id": binding.binding_id,
        "wallet_binding_hash": binding.binding_hash,
        "wallet_binding_version": binding.binding_version,
        "reserve_remaining_q_atoms": reserve_remaining_q_atoms,
        "pool_remaining_q_atoms": pool_remaining_q_atoms,
        "state": "CLAIMED",
    }
    return DevelopmentRewardClaimRecord(
        **payload,
        record_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_REWARD_CLAIM_VERSION",
    "DevelopmentRewardClaimRecord",
    "DevelopmentRewardWalletBindingProof",
    "build_development_reward_claim_record",
    "development_reward_claim_id",
]
