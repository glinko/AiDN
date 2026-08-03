"""Bounded ECO-0007 development-pool carryover domain records.

This module models the accounting boundary between two pool epochs.  It is
deliberately independent from Ledger and consensus integration: a carryover
record only proves how one source pool's uncommitted amount was split between
the next pool and the emission reserve.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import canonical_hash

DEVELOPMENT_POOL_CARRYOVER_VERSION = "eco-0007-pool-carryover.v1"
DEVELOPMENT_CARRYOVER_LEDGER_VERSION = "eco-0007-pool-carryover-ledger.v1"


class DevelopmentPoolCarryoverRecord(BaseModel, frozen=True):
    """Immutable split of one source pool's uncommitted balance."""

    carryover_version: str = DEVELOPMENT_POOL_CARRYOVER_VERSION
    carryover_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    source_pool_id: str = Field(min_length=1)
    target_pool_id: str = Field(min_length=1)
    source_epoch: int = Field(ge=0)
    target_epoch: int = Field(ge=0)
    source_pool_reference: str = Field(min_length=1)
    target_pool_reference: str = Field(min_length=1)
    source_pool_q_atoms: int = Field(gt=0)
    committed_q_atoms: int = Field(ge=0)
    uncommitted_q_atoms: int = Field(ge=0)
    carryover_limit_q_atoms: int = Field(ge=0)
    carried_q_atoms: int = Field(gt=0)
    returned_to_emission_reserve_q_atoms: int = Field(ge=0)
    state: Literal["CARRIED"] = "CARRIED"
    record_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_record_invariants(self) -> DevelopmentPoolCarryoverRecord:
        if self.carryover_version != DEVELOPMENT_POOL_CARRYOVER_VERSION:
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_VERSION_INVALID")
        if self.source_pool_id != self.target_pool_id:
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_POOL_MISMATCH")
        if self.target_epoch <= self.source_epoch:
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_EPOCH_INVALID")
        if self.source_pool_q_atoms != self.committed_q_atoms + self.uncommitted_q_atoms:
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_SOURCE_CONSERVATION_INVALID")
        if self.uncommitted_q_atoms != (
            self.carried_q_atoms + self.returned_to_emission_reserve_q_atoms
        ):
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_SPLIT_INVALID")
        if self.carried_q_atoms > self.carryover_limit_q_atoms:
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_CAP_EXCEEDED")
        expected_id = development_pool_carryover_id(
            source_pool_id=self.source_pool_id,
            target_pool_id=self.target_pool_id,
            source_epoch=self.source_epoch,
            target_epoch=self.target_epoch,
            source_pool_reference=self.source_pool_reference,
            target_pool_reference=self.target_pool_reference,
            carried_q_atoms=self.carried_q_atoms,
        )
        if self.carryover_id != expected_id:
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_ID_INVALID")
        if self.record_hash != canonical_hash(self.unsigned_payload()):
            raise ValueError("DEVELOPMENT_POOL_CARRYOVER_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"record_hash"})

    def verify_integrity(self) -> bool:
        return self.record_hash == canonical_hash(self.unsigned_payload())

    @property
    def source_conservation_q_atoms(self) -> int:
        """Return the amount fully accounted for by this source transition."""

        return (
            self.committed_q_atoms
            + self.carried_q_atoms
            + self.returned_to_emission_reserve_q_atoms
        )


def development_pool_carryover_id(
    *,
    source_pool_id: str,
    target_pool_id: str,
    source_epoch: int,
    target_epoch: int,
    source_pool_reference: str,
    target_pool_reference: str,
    carried_q_atoms: int,
) -> str:
    """Derive the natural identity of one source-to-target carryover split."""

    return canonical_hash(
        {
            "carryover_version": DEVELOPMENT_POOL_CARRYOVER_VERSION,
            "source_pool_id": source_pool_id,
            "target_pool_id": target_pool_id,
            "source_epoch": source_epoch,
            "target_epoch": target_epoch,
            "source_pool_reference": source_pool_reference,
            "target_pool_reference": target_pool_reference,
            "carried_q_atoms": carried_q_atoms,
        }
    )


def build_development_pool_carryover(
    *,
    operation_id: str,
    source_pool_id: str,
    target_pool_id: str,
    source_epoch: int,
    target_epoch: int,
    source_pool_reference: str,
    target_pool_reference: str,
    source_pool_q_atoms: int,
    committed_q_atoms: int,
    uncommitted_q_atoms: int,
    carryover_limit_q_atoms: int,
    carried_q_atoms: int,
    returned_to_emission_reserve_q_atoms: int,
) -> DevelopmentPoolCarryoverRecord:
    """Build a source-bound carryover record after checking arithmetic."""

    if not operation_id.strip():
        raise ValueError("DEVELOPMENT_POOL_CARRYOVER_OPERATION_INVALID")
    if source_pool_q_atoms <= 0:
        raise ValueError("DEVELOPMENT_POOL_CARRYOVER_SOURCE_AMOUNT_INVALID")
    if min(committed_q_atoms, uncommitted_q_atoms, carryover_limit_q_atoms) < 0:
        raise ValueError("DEVELOPMENT_POOL_CARRYOVER_AMOUNT_INVALID")
    if carried_q_atoms <= 0:
        raise ValueError("DEVELOPMENT_POOL_CARRYOVER_AMOUNT_INVALID")
    if returned_to_emission_reserve_q_atoms < 0:
        raise ValueError("DEVELOPMENT_POOL_CARRYOVER_AMOUNT_INVALID")
    if source_pool_q_atoms != committed_q_atoms + uncommitted_q_atoms:
        raise ValueError("DEVELOPMENT_POOL_CARRYOVER_SOURCE_CONSERVATION_INVALID")
    if uncommitted_q_atoms != carried_q_atoms + returned_to_emission_reserve_q_atoms:
        raise ValueError("DEVELOPMENT_POOL_CARRYOVER_SPLIT_INVALID")
    if carried_q_atoms > carryover_limit_q_atoms:
        raise ValueError("DEVELOPMENT_POOL_CARRYOVER_CAP_EXCEEDED")

    carryover_id = development_pool_carryover_id(
        source_pool_id=source_pool_id,
        target_pool_id=target_pool_id,
        source_epoch=source_epoch,
        target_epoch=target_epoch,
        source_pool_reference=source_pool_reference,
        target_pool_reference=target_pool_reference,
        carried_q_atoms=carried_q_atoms,
    )
    payload = {
        "carryover_version": DEVELOPMENT_POOL_CARRYOVER_VERSION,
        "carryover_id": carryover_id,
        "operation_id": operation_id,
        "source_pool_id": source_pool_id,
        "target_pool_id": target_pool_id,
        "source_epoch": source_epoch,
        "target_epoch": target_epoch,
        "source_pool_reference": source_pool_reference,
        "target_pool_reference": target_pool_reference,
        "source_pool_q_atoms": source_pool_q_atoms,
        "committed_q_atoms": committed_q_atoms,
        "uncommitted_q_atoms": uncommitted_q_atoms,
        "carryover_limit_q_atoms": carryover_limit_q_atoms,
        "carried_q_atoms": carried_q_atoms,
        "returned_to_emission_reserve_q_atoms": returned_to_emission_reserve_q_atoms,
        "state": "CARRIED",
    }
    return DevelopmentPoolCarryoverRecord(
        **payload,
        record_hash=canonical_hash(payload),
    )


def _carryover_ledger_payload(
    records: tuple[DevelopmentPoolCarryoverRecord, ...],
) -> dict[str, Any]:
    return {
        "ledger_version": DEVELOPMENT_CARRYOVER_LEDGER_VERSION,
        "records": [record.model_dump(mode="json") for record in records],
    }


class DevelopmentCarryoverLedger(BaseModel, frozen=True):
    """Immutable append-only registry with replay and natural-key checks."""

    ledger_version: str = DEVELOPMENT_CARRYOVER_LEDGER_VERSION
    records: tuple[DevelopmentPoolCarryoverRecord, ...] = ()
    ledger_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_ledger_invariants(self) -> DevelopmentCarryoverLedger:
        if self.ledger_version != DEVELOPMENT_CARRYOVER_LEDGER_VERSION:
            raise ValueError("DEVELOPMENT_CARRYOVER_LEDGER_VERSION_INVALID")
        seen_ids: set[str] = set()
        seen_operations: set[str] = set()
        seen_natural_keys: set[tuple[str, int, str, int, str, str]] = set()
        for record in self.records:
            if not record.verify_integrity():
                raise ValueError("DEVELOPMENT_POOL_CARRYOVER_HASH_INVALID")
            if record.carryover_id in seen_ids:
                raise ValueError("DEVELOPMENT_POOL_CARRYOVER_DUPLICATE")
            if record.operation_id in seen_operations:
                raise ValueError("DEVELOPMENT_POOL_CARRYOVER_OPERATION_CONFLICT")
            natural_key = (
                record.source_pool_id,
                record.source_epoch,
                record.target_pool_id,
                record.target_epoch,
                record.source_pool_reference,
                record.target_pool_reference,
            )
            if natural_key in seen_natural_keys:
                raise ValueError("DEVELOPMENT_POOL_CARRYOVER_CONFLICT")
            seen_ids.add(record.carryover_id)
            seen_operations.add(record.operation_id)
            seen_natural_keys.add(natural_key)
        if self.ledger_hash != canonical_hash(self.unsigned_payload()):
            raise ValueError("DEVELOPMENT_CARRYOVER_LEDGER_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return _carryover_ledger_payload(self.records)

    def verify_integrity(self) -> bool:
        return self.ledger_hash == canonical_hash(self.unsigned_payload())

    def append(self, record: DevelopmentPoolCarryoverRecord) -> DevelopmentCarryoverLedger:
        """Append a record, treating an identical retry as a no-op."""

        for existing in self.records:
            if existing.carryover_id == record.carryover_id:
                if existing.record_hash == record.record_hash:
                    return self
                raise ValueError("DEVELOPMENT_POOL_CARRYOVER_CONFLICT")
            if existing.operation_id == record.operation_id:
                if existing.record_hash == record.record_hash:
                    return self
                raise ValueError("DEVELOPMENT_POOL_CARRYOVER_OPERATION_CONFLICT")
            existing_key = (
                existing.source_pool_id,
                existing.source_epoch,
                existing.target_pool_id,
                existing.target_epoch,
                existing.source_pool_reference,
                existing.target_pool_reference,
            )
            record_key = (
                record.source_pool_id,
                record.source_epoch,
                record.target_pool_id,
                record.target_epoch,
                record.source_pool_reference,
                record.target_pool_reference,
            )
            if existing_key == record_key:
                raise ValueError("DEVELOPMENT_POOL_CARRYOVER_CONFLICT")
        records = tuple(sorted((*self.records, record), key=lambda item: item.carryover_id))
        return build_development_carryover_ledger(records)


def build_development_carryover_ledger(
    records: tuple[DevelopmentPoolCarryoverRecord, ...] = (),
) -> DevelopmentCarryoverLedger:
    """Build a validated immutable carryover ledger snapshot."""

    ordered = tuple(sorted(records, key=lambda item: item.carryover_id))
    payload = _carryover_ledger_payload(ordered)
    return DevelopmentCarryoverLedger(
        records=ordered,
        ledger_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_CARRYOVER_LEDGER_VERSION",
    "DEVELOPMENT_POOL_CARRYOVER_VERSION",
    "DevelopmentCarryoverLedger",
    "DevelopmentPoolCarryoverRecord",
    "build_development_carryover_ledger",
    "build_development_pool_carryover",
    "development_pool_carryover_id",
]
