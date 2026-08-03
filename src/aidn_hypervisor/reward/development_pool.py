"""Consensus-bound ECO-0007 development-pool allocation records.

The allocation is a reservation of an already authorized epoch budget. It is
not a mint and it does not credit a contributor wallet. Reward reservations
and payment stages consume this record in later, separately enabled
transitions.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import canonical_hash

DEVELOPMENT_POOL_ALLOCATION_VERSION = "eco-0007-pool-allocation.v1"
DEVELOPMENT_POOL_ID = "GENERAL_DEVELOPMENT"


class DevelopmentPoolAllocation(BaseModel, frozen=True):
    """Immutable accounting record for one epoch development-pool reserve."""

    allocation_version: str = DEVELOPMENT_POOL_ALLOCATION_VERSION
    allocation_id: str = Field(min_length=1)
    pool_id: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    calculation_operation_id: str = Field(min_length=1)
    calculation_commitment_id: str = Field(min_length=1)
    calculation_root: str = Field(min_length=1)
    source_epoch_transition_operation_id: str = Field(min_length=1)
    source_pool_budget_reference: str = Field(min_length=1)
    authorized_budget_q_atoms: int = Field(gt=0)
    allocated_q_atoms: int = Field(gt=0)
    remaining_q_atoms: int = Field(ge=0)
    state: Literal["ALLOCATED"] = "ALLOCATED"
    allocation_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_allocation_invariants(self) -> DevelopmentPoolAllocation:
        if self.allocation_version != DEVELOPMENT_POOL_ALLOCATION_VERSION:
            raise ValueError("DEVELOPMENT_POOL_ALLOCATION_VERSION_INVALID")
        if self.authorized_budget_q_atoms != self.allocated_q_atoms:
            raise ValueError("DEVELOPMENT_POOL_ALLOCATION_BUDGET_MISMATCH")
        if self.remaining_q_atoms != self.allocated_q_atoms:
            raise ValueError("DEVELOPMENT_POOL_ALLOCATION_REMAINING_INVALID")
        expected_id = development_pool_allocation_id(
            pool_id=self.pool_id,
            epoch=self.epoch,
            calculation_operation_id=self.calculation_operation_id,
            calculation_root=self.calculation_root,
            source_epoch_transition_operation_id=self.source_epoch_transition_operation_id,
            source_pool_budget_reference=self.source_pool_budget_reference,
            allocated_q_atoms=self.allocated_q_atoms,
        )
        if self.allocation_id != expected_id:
            raise ValueError("DEVELOPMENT_POOL_ALLOCATION_ID_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"allocation_hash"})

    def verify_integrity(self) -> bool:
        return self.allocation_hash == canonical_hash(self.unsigned_payload())


def development_pool_allocation_id(
    *,
    pool_id: str,
    epoch: int,
    calculation_operation_id: str,
    calculation_root: str,
    source_epoch_transition_operation_id: str,
    source_pool_budget_reference: str,
    allocated_q_atoms: int,
) -> str:
    """Derive the stable identity for one source-bound allocation."""

    return canonical_hash(
        {
            "allocation_version": DEVELOPMENT_POOL_ALLOCATION_VERSION,
            "pool_id": pool_id,
            "epoch": epoch,
            "calculation_operation_id": calculation_operation_id,
            "calculation_root": calculation_root,
            "source_epoch_transition_operation_id": source_epoch_transition_operation_id,
            "source_pool_budget_reference": source_pool_budget_reference,
            "allocated_q_atoms": allocated_q_atoms,
        }
    )


def build_development_pool_allocation(
    *,
    pool_id: str,
    epoch: int,
    calculation_operation_id: str,
    calculation_commitment_id: str,
    calculation_root: str,
    source_epoch_transition_operation_id: str,
    source_pool_budget_reference: str,
    authorized_budget_q_atoms: int,
    allocated_q_atoms: int,
) -> DevelopmentPoolAllocation:
    """Build a deterministic allocation with all budget still available."""

    if authorized_budget_q_atoms <= 0 or allocated_q_atoms <= 0:
        raise ValueError("DEVELOPMENT_POOL_ALLOCATION_AMOUNT_INVALID")
    if allocated_q_atoms != authorized_budget_q_atoms:
        raise ValueError("DEVELOPMENT_POOL_ALLOCATION_BUDGET_MISMATCH")
    allocation_id = development_pool_allocation_id(
        pool_id=pool_id,
        epoch=epoch,
        calculation_operation_id=calculation_operation_id,
        calculation_root=calculation_root,
        source_epoch_transition_operation_id=source_epoch_transition_operation_id,
        source_pool_budget_reference=source_pool_budget_reference,
        allocated_q_atoms=allocated_q_atoms,
    )
    payload = {
        "allocation_version": DEVELOPMENT_POOL_ALLOCATION_VERSION,
        "allocation_id": allocation_id,
        "pool_id": pool_id,
        "epoch": epoch,
        "calculation_operation_id": calculation_operation_id,
        "calculation_commitment_id": calculation_commitment_id,
        "calculation_root": calculation_root,
        "source_epoch_transition_operation_id": source_epoch_transition_operation_id,
        "source_pool_budget_reference": source_pool_budget_reference,
        "authorized_budget_q_atoms": authorized_budget_q_atoms,
        "allocated_q_atoms": allocated_q_atoms,
        "remaining_q_atoms": allocated_q_atoms,
        "state": "ALLOCATED",
    }
    return DevelopmentPoolAllocation(
        **payload,
        allocation_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_POOL_ALLOCATION_VERSION",
    "DEVELOPMENT_POOL_ID",
    "DevelopmentPoolAllocation",
    "build_development_pool_allocation",
    "development_pool_allocation_id",
]
