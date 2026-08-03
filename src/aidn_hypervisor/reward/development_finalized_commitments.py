"""Auditable finalized commitments for live ECO-0007 reward state.

The original calculation commitment is deliberately simulation-only. This
module adds the later, non-emitting commitment that closes a set of finalized
reserve and reward evidence records without minting or transferring Q.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import canonical_hash

DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_VERSION = "eco-0007-finalized-commitment.v1"


def _validate_operation_ids(values: list[str], field_name: str) -> list[str]:
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ValueError(f"DEVELOPMENT_REWARD_FINALIZED_{field_name.upper()}_INVALID")
    if len(set(values)) != len(values):
        raise ValueError(f"DEVELOPMENT_REWARD_FINALIZED_{field_name.upper()}_DUPLICATE")
    return values


class DevelopmentRewardFinalizedCommitment(BaseModel, frozen=True):
    """Immutable commitment to the exact finalized reward evidence set."""

    commitment_version: str = DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_VERSION
    finalized_commitment_id: str = Field(min_length=1)
    finalized_operation_id: str = Field(min_length=1)
    calculation_operation_id: str = Field(min_length=1)
    calculation_commitment_id: str = Field(min_length=1)
    calculation_root: str = Field(min_length=1)
    pool_allocation_id: str = Field(min_length=1)
    pool_allocation_operation_id: str = Field(min_length=1)
    source_epoch_transition_operation_id: str = Field(min_length=1)
    reserve_operation_ids: list[str] = Field(min_length=1)
    payment_operation_ids: list[str] = Field(default_factory=list)
    unclaimed_operation_ids: list[str] = Field(default_factory=list)
    claim_operation_ids: list[str] = Field(default_factory=list)
    expiry_operation_ids: list[str] = Field(default_factory=list)
    source_operation_root: str = Field(min_length=1)
    reserve_root: str = Field(min_length=1)
    payment_root: str = Field(min_length=1)
    unclaimed_root: str = Field(min_length=1)
    claim_root: str = Field(min_length=1)
    expiry_root: str = Field(min_length=1)
    finalization_epoch: int = Field(ge=0)
    state: Literal["FINALIZED"] = "FINALIZED"
    record_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_record_invariants(self) -> DevelopmentRewardFinalizedCommitment:
        if self.commitment_version != DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_VERSION:
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_VERSION_INVALID")
        _validate_operation_ids(self.reserve_operation_ids, "reserve_operation_ids")
        for field_name in (
            "payment_operation_ids",
            "unclaimed_operation_ids",
            "claim_operation_ids",
            "expiry_operation_ids",
        ):
            _validate_operation_ids(getattr(self, field_name), field_name)
        all_source_ids = [
            self.calculation_operation_id,
            self.pool_allocation_operation_id,
            self.source_epoch_transition_operation_id,
            *self.reserve_operation_ids,
            *self.payment_operation_ids,
            *self.unclaimed_operation_ids,
            *self.claim_operation_ids,
            *self.expiry_operation_ids,
        ]
        if len(set(all_source_ids)) != len(all_source_ids):
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_SOURCE_OPERATION_DUPLICATE")
        expected_id = development_reward_finalized_commitment_id(
            calculation_operation_id=self.calculation_operation_id,
            calculation_commitment_id=self.calculation_commitment_id,
            calculation_root=self.calculation_root,
            pool_allocation_id=self.pool_allocation_id,
            pool_allocation_operation_id=self.pool_allocation_operation_id,
            source_epoch_transition_operation_id=self.source_epoch_transition_operation_id,
            reserve_operation_ids=self.reserve_operation_ids,
            payment_operation_ids=self.payment_operation_ids,
            unclaimed_operation_ids=self.unclaimed_operation_ids,
            claim_operation_ids=self.claim_operation_ids,
            expiry_operation_ids=self.expiry_operation_ids,
            source_operation_root=self.source_operation_root,
            reserve_root=self.reserve_root,
            payment_root=self.payment_root,
            unclaimed_root=self.unclaimed_root,
            claim_root=self.claim_root,
            expiry_root=self.expiry_root,
            finalization_epoch=self.finalization_epoch,
        )
        if self.finalized_commitment_id != expected_id:
            raise ValueError("DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_ID_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"record_hash"})

    def verify_integrity(self) -> bool:
        return self.record_hash == canonical_hash(self.unsigned_payload())


def development_reward_finalized_commitment_id(
    *,
    calculation_operation_id: str,
    calculation_commitment_id: str,
    calculation_root: str,
    pool_allocation_id: str,
    pool_allocation_operation_id: str,
    source_epoch_transition_operation_id: str,
    reserve_operation_ids: list[str],
    payment_operation_ids: list[str],
    unclaimed_operation_ids: list[str],
    claim_operation_ids: list[str],
    expiry_operation_ids: list[str],
    source_operation_root: str,
    reserve_root: str,
    payment_root: str,
    unclaimed_root: str,
    claim_root: str,
    expiry_root: str,
    finalization_epoch: int,
) -> str:
    """Derive a stable identity independent of the envelope operation ID."""

    return canonical_hash(
        {
            "commitment_version": DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_VERSION,
            "calculation_operation_id": calculation_operation_id,
            "calculation_commitment_id": calculation_commitment_id,
            "calculation_root": calculation_root,
            "pool_allocation_id": pool_allocation_id,
            "pool_allocation_operation_id": pool_allocation_operation_id,
            "source_epoch_transition_operation_id": source_epoch_transition_operation_id,
            "reserve_operation_ids": sorted(reserve_operation_ids),
            "payment_operation_ids": sorted(payment_operation_ids),
            "unclaimed_operation_ids": sorted(unclaimed_operation_ids),
            "claim_operation_ids": sorted(claim_operation_ids),
            "expiry_operation_ids": sorted(expiry_operation_ids),
            "source_operation_root": source_operation_root,
            "reserve_root": reserve_root,
            "payment_root": payment_root,
            "unclaimed_root": unclaimed_root,
            "claim_root": claim_root,
            "expiry_root": expiry_root,
            "finalization_epoch": finalization_epoch,
        }
    )


def build_development_reward_finalized_commitment(
    *,
    finalized_operation_id: str,
    calculation_operation_id: str,
    calculation_commitment_id: str,
    calculation_root: str,
    pool_allocation_id: str,
    pool_allocation_operation_id: str,
    source_epoch_transition_operation_id: str,
    reserve_operation_ids: list[str],
    payment_operation_ids: list[str],
    unclaimed_operation_ids: list[str],
    claim_operation_ids: list[str],
    expiry_operation_ids: list[str],
    source_operation_root: str,
    reserve_root: str,
    payment_root: str,
    unclaimed_root: str,
    claim_root: str,
    expiry_root: str,
    finalization_epoch: int,
) -> DevelopmentRewardFinalizedCommitment:
    """Build the record after the consensus envelope ID is known."""

    payload = {
        "commitment_version": DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_VERSION,
        "finalized_commitment_id": development_reward_finalized_commitment_id(
            calculation_operation_id=calculation_operation_id,
            calculation_commitment_id=calculation_commitment_id,
            calculation_root=calculation_root,
            pool_allocation_id=pool_allocation_id,
            pool_allocation_operation_id=pool_allocation_operation_id,
            source_epoch_transition_operation_id=source_epoch_transition_operation_id,
            reserve_operation_ids=reserve_operation_ids,
            payment_operation_ids=payment_operation_ids,
            unclaimed_operation_ids=unclaimed_operation_ids,
            claim_operation_ids=claim_operation_ids,
            expiry_operation_ids=expiry_operation_ids,
            source_operation_root=source_operation_root,
            reserve_root=reserve_root,
            payment_root=payment_root,
            unclaimed_root=unclaimed_root,
            claim_root=claim_root,
            expiry_root=expiry_root,
            finalization_epoch=finalization_epoch,
        ),
        "finalized_operation_id": finalized_operation_id,
        "calculation_operation_id": calculation_operation_id,
        "calculation_commitment_id": calculation_commitment_id,
        "calculation_root": calculation_root,
        "pool_allocation_id": pool_allocation_id,
        "pool_allocation_operation_id": pool_allocation_operation_id,
        "source_epoch_transition_operation_id": source_epoch_transition_operation_id,
        "reserve_operation_ids": list(reserve_operation_ids),
        "payment_operation_ids": list(payment_operation_ids),
        "unclaimed_operation_ids": list(unclaimed_operation_ids),
        "claim_operation_ids": list(claim_operation_ids),
        "expiry_operation_ids": list(expiry_operation_ids),
        "source_operation_root": source_operation_root,
        "reserve_root": reserve_root,
        "payment_root": payment_root,
        "unclaimed_root": unclaimed_root,
        "claim_root": claim_root,
        "expiry_root": expiry_root,
        "finalization_epoch": finalization_epoch,
        "state": "FINALIZED",
    }
    return DevelopmentRewardFinalizedCommitment(
        **payload,
        record_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_REWARD_FINALIZED_COMMITMENT_VERSION",
    "DevelopmentRewardFinalizedCommitment",
    "build_development_reward_finalized_commitment",
    "development_reward_finalized_commitment_id",
]
