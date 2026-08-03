"""Append-only ECO-0007 cancellation of unvested reward portions."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_adjustments import DevelopmentRewardStateSnapshot
from aidn_hypervisor.reward.development_distribution import canonical_hash

DEVELOPMENT_REWARD_CANCELLATION_VERSION = "eco-0007-reward-cancellation.v1"
CancellationReason = Literal[
    "ORDINARY_DEFECT",
    "CRITICAL_DEFECT",
    "SECURITY_DEFECT",
    "INTENTIONAL_GAMING",
    "DUPLICATE_REWARD",
    "INVALID_ATTESTATION",
    "CHALLENGE_RESOLUTION",
]


def development_reward_cancellation_id(
    *,
    source_snapshot_id: str,
    cancellation_sequence: int,
    previous_cancellation_id: str | None,
    reason: str,
    cancelled_unpaid_maturity_stage_one_q_atoms: int,
    cancelled_unpaid_maturity_stage_two_q_atoms: int,
    cancelled_unclaimed_q_atoms: int,
) -> str:
    """Derive a semantic identity independent of an envelope operation ID."""

    return canonical_hash(
        {
            "cancellation_version": DEVELOPMENT_REWARD_CANCELLATION_VERSION,
            "source_snapshot_id": source_snapshot_id,
            "cancellation_sequence": cancellation_sequence,
            "previous_cancellation_id": previous_cancellation_id,
            "reason": reason,
            "cancelled_unpaid_maturity_stage_one_q_atoms": cancelled_unpaid_maturity_stage_one_q_atoms,
            "cancelled_unpaid_maturity_stage_two_q_atoms": cancelled_unpaid_maturity_stage_two_q_atoms,
            "cancelled_unclaimed_q_atoms": cancelled_unclaimed_q_atoms,
        }
    )


class DevelopmentRewardCancellationRecord(BaseModel, frozen=True):
    """Immutable return of unpaid reward liability to the development pool."""

    cancellation_version: str = DEVELOPMENT_REWARD_CANCELLATION_VERSION
    cancellation_id: str = Field(min_length=1)
    cancellation_operation_id: str = Field(min_length=1)
    source_snapshot_id: str = Field(min_length=1)
    source_snapshot_hash: str = Field(min_length=1)
    source_evidence_root: str = Field(min_length=1)
    reward_id: str = Field(min_length=1)
    contribution_id: str = Field(min_length=1)
    cancellation_sequence: int = Field(ge=1)
    previous_cancellation_id: str | None = None
    cancellation_epoch: int = Field(ge=0)
    reason: CancellationReason
    paid_before_q_atoms: int = Field(ge=0)
    paid_after_q_atoms: int = Field(ge=0)
    unpaid_immediate_before_q_atoms: int = Field(ge=0)
    unpaid_immediate_after_q_atoms: int = Field(ge=0)
    unpaid_maturity_stage_one_before_q_atoms: int = Field(ge=0)
    unpaid_maturity_stage_one_after_q_atoms: int = Field(ge=0)
    unpaid_maturity_stage_two_before_q_atoms: int = Field(ge=0)
    unpaid_maturity_stage_two_after_q_atoms: int = Field(ge=0)
    unclaimed_before_q_atoms: int = Field(ge=0)
    unclaimed_after_q_atoms: int = Field(ge=0)
    cancelled_before_q_atoms: int = Field(ge=0)
    cancelled_after_q_atoms: int = Field(ge=0)
    reward_liability_before_q_atoms: int = Field(gt=0)
    reward_liability_after_q_atoms: int = Field(ge=0)
    cancelled_unpaid_maturity_stage_one_q_atoms: int = Field(ge=0)
    cancelled_unpaid_maturity_stage_two_q_atoms: int = Field(ge=0)
    cancelled_unclaimed_q_atoms: int = Field(ge=0)
    cancelled_q_atoms: int = Field(gt=0)
    returned_to_pool_q_atoms: int = Field(gt=0)
    state: Literal["CANCELLED_UNVESTED"] = "CANCELLED_UNVESTED"
    record_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_record(self) -> DevelopmentRewardCancellationRecord:
        if self.cancellation_version != DEVELOPMENT_REWARD_CANCELLATION_VERSION:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_VERSION_INVALID")
        if not self.cancellation_operation_id.strip():
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_OPERATION_INVALID")
        cancelled = (
            self.cancelled_unpaid_maturity_stage_one_q_atoms
            + self.cancelled_unpaid_maturity_stage_two_q_atoms
            + self.cancelled_unclaimed_q_atoms
        )
        if self.cancelled_q_atoms != cancelled:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_AMOUNT_INVALID")
        if self.returned_to_pool_q_atoms != self.cancelled_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_RETURN_INVALID")
        if self.paid_after_q_atoms != self.paid_before_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_PAID_HISTORY_MUTATION")
        if self.unpaid_immediate_after_q_atoms != self.unpaid_immediate_before_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_IMMEDIATE_MUTATION")
        if self.unpaid_maturity_stage_one_after_q_atoms != (
            self.unpaid_maturity_stage_one_before_q_atoms
            - self.cancelled_unpaid_maturity_stage_one_q_atoms
        ):
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_STAGE_ONE_INVALID")
        if self.unpaid_maturity_stage_two_after_q_atoms != (
            self.unpaid_maturity_stage_two_before_q_atoms
            - self.cancelled_unpaid_maturity_stage_two_q_atoms
        ):
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_STAGE_TWO_INVALID")
        if self.unclaimed_after_q_atoms != self.unclaimed_before_q_atoms - self.cancelled_unclaimed_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_UNCLAIMED_INVALID")
        if self.cancelled_after_q_atoms != self.cancelled_before_q_atoms + self.cancelled_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_CANCELLED_BALANCE_INVALID")
        expected_before = (
            self.paid_before_q_atoms
            + self.unpaid_immediate_before_q_atoms
            + self.unpaid_maturity_stage_one_before_q_atoms
            + self.unpaid_maturity_stage_two_before_q_atoms
            + self.unclaimed_before_q_atoms
        )
        expected_after = (
            self.paid_after_q_atoms
            + self.unpaid_immediate_after_q_atoms
            + self.unpaid_maturity_stage_one_after_q_atoms
            + self.unpaid_maturity_stage_two_after_q_atoms
            + self.unclaimed_after_q_atoms
        )
        if self.reward_liability_before_q_atoms != expected_before:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_CONSERVATION_INVALID")
        if self.reward_liability_after_q_atoms != expected_after:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_CONSERVATION_INVALID")
        if self.reward_liability_before_q_atoms - self.reward_liability_after_q_atoms != self.returned_to_pool_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_RETURN_CONSERVATION_INVALID")
        expected_id = development_reward_cancellation_id(
            source_snapshot_id=self.source_snapshot_id,
            cancellation_sequence=self.cancellation_sequence,
            previous_cancellation_id=self.previous_cancellation_id,
            reason=self.reason,
            cancelled_unpaid_maturity_stage_one_q_atoms=self.cancelled_unpaid_maturity_stage_one_q_atoms,
            cancelled_unpaid_maturity_stage_two_q_atoms=self.cancelled_unpaid_maturity_stage_two_q_atoms,
            cancelled_unclaimed_q_atoms=self.cancelled_unclaimed_q_atoms,
        )
        if self.cancellation_id != expected_id:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_ID_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"record_hash"})

    def verify_integrity(self) -> bool:
        try:
            type(self).model_validate(self.model_dump(mode="json"))
        except ValueError:
            return False
        return self.record_hash == canonical_hash(self.unsigned_payload())


def validate_cancellation_history(
    source: DevelopmentRewardStateSnapshot,
    records: Sequence[DevelopmentRewardCancellationRecord],
) -> tuple[DevelopmentRewardCancellationRecord, ...]:
    """Validate a cancellation chain and reject duplicate/conflicting events."""

    by_id: dict[str, DevelopmentRewardCancellationRecord] = {}
    for record in records:
        if not record.verify_integrity():
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_RECORD_INVALID")
        existing = by_id.get(record.cancellation_id)
        if existing is not None:
            if existing.record_hash == record.record_hash:
                raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_DUPLICATE")
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_CONFLICT")
        if record.source_snapshot_id != source.snapshot_id:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_SOURCE_MISMATCH")
        if record.source_snapshot_hash != source.snapshot_hash:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_SOURCE_HASH_MISMATCH")
        if record.source_evidence_root != source.source_evidence_root:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_EVIDENCE_MISMATCH")
        if record.reward_id != source.reward_id or record.contribution_id != source.contribution_id:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_REWARD_MISMATCH")
        by_id[record.cancellation_id] = record

    ordered = tuple(sorted(by_id.values(), key=lambda item: item.cancellation_sequence))
    previous_id: str | None = None
    for expected_sequence, record in enumerate(ordered, start=1):
        if record.cancellation_sequence != expected_sequence:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_SEQUENCE_INVALID")
        if record.previous_cancellation_id != previous_id:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_CHAIN_INVALID")
        previous_id = record.cancellation_id

    stage_one = sum(item.cancelled_unpaid_maturity_stage_one_q_atoms for item in ordered)
    stage_two = sum(item.cancelled_unpaid_maturity_stage_two_q_atoms for item in ordered)
    unclaimed = sum(item.cancelled_unclaimed_q_atoms for item in ordered)
    if stage_one > source.unpaid_maturity_stage_one_q_atoms:
        raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_STAGE_ONE_OVERPAID")
    if stage_two > source.unpaid_maturity_stage_two_q_atoms:
        raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_STAGE_TWO_OVERPAID")
    if unclaimed > source.unclaimed_q_atoms:
        raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_UNCLAIMED_OVERPAID")
    expected_stage_one = source.unpaid_maturity_stage_one_q_atoms
    expected_stage_two = source.unpaid_maturity_stage_two_q_atoms
    expected_unclaimed = source.unclaimed_q_atoms
    expected_cancelled = source.cancelled_q_atoms
    for record in ordered:
        if record.paid_before_q_atoms != source.paid_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_PAID_HISTORY_MUTATION")
        if record.unpaid_immediate_before_q_atoms != source.unpaid_immediate_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_IMMEDIATE_MUTATION")
        if record.unpaid_maturity_stage_one_before_q_atoms != expected_stage_one:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_CHAIN_CONSERVATION_INVALID")
        if record.unpaid_maturity_stage_two_before_q_atoms != expected_stage_two:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_CHAIN_CONSERVATION_INVALID")
        if record.unclaimed_before_q_atoms != expected_unclaimed:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_CHAIN_CONSERVATION_INVALID")
        if record.cancelled_before_q_atoms != expected_cancelled:
            raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_CHAIN_CONSERVATION_INVALID")
        expected_stage_one = record.unpaid_maturity_stage_one_after_q_atoms
        expected_stage_two = record.unpaid_maturity_stage_two_after_q_atoms
        expected_unclaimed = record.unclaimed_after_q_atoms
        expected_cancelled = record.cancelled_after_q_atoms
    return ordered


def build_development_reward_cancellation(
    *,
    source: DevelopmentRewardStateSnapshot,
    cancellation_operation_id: str,
    cancellation_epoch: int,
    reason: CancellationReason,
    cancelled_unpaid_maturity_stage_one_q_atoms: int = 0,
    cancelled_unpaid_maturity_stage_two_q_atoms: int = 0,
    cancelled_unclaimed_q_atoms: int = 0,
    previous_cancellations: Sequence[DevelopmentRewardCancellationRecord] = (),
) -> DevelopmentRewardCancellationRecord:
    """Build one bounded cancellation against the current unpaid buckets."""

    if not source.verify_integrity():
        raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_INVALID")
    if cancellation_epoch < 0:
        raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_EPOCH_INVALID")
    amounts = (
        cancelled_unpaid_maturity_stage_one_q_atoms,
        cancelled_unpaid_maturity_stage_two_q_atoms,
        cancelled_unclaimed_q_atoms,
    )
    if any(amount < 0 for amount in amounts):
        raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_NEGATIVE_AMOUNT")
    previous = validate_cancellation_history(source, previous_cancellations)
    stage_one_cancelled = sum(item.cancelled_unpaid_maturity_stage_one_q_atoms for item in previous)
    stage_two_cancelled = sum(item.cancelled_unpaid_maturity_stage_two_q_atoms for item in previous)
    unclaimed_cancelled = sum(item.cancelled_unclaimed_q_atoms for item in previous)
    stage_one_before = source.unpaid_maturity_stage_one_q_atoms - stage_one_cancelled
    stage_two_before = source.unpaid_maturity_stage_two_q_atoms - stage_two_cancelled
    unclaimed_before = source.unclaimed_q_atoms - unclaimed_cancelled
    if cancelled_unpaid_maturity_stage_one_q_atoms > stage_one_before:
        raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_STAGE_ONE_OVERPAID")
    if cancelled_unpaid_maturity_stage_two_q_atoms > stage_two_before:
        raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_STAGE_TWO_OVERPAID")
    if cancelled_unclaimed_q_atoms > unclaimed_before:
        raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_UNCLAIMED_OVERPAID")
    cancelled = sum(amounts)
    if cancelled <= 0:
        raise ValueError("DEVELOPMENT_REWARD_CANCELLATION_AMOUNT_REQUIRED")
    sequence = len(previous) + 1
    previous_id = previous[-1].cancellation_id if previous else None
    cancelled_before = source.cancelled_q_atoms + sum(item.cancelled_q_atoms for item in previous)
    liability_before = (
        source.paid_q_atoms
        + source.unpaid_immediate_q_atoms
        + stage_one_before
        + stage_two_before
        + unclaimed_before
    )
    payload = {
        "cancellation_version": DEVELOPMENT_REWARD_CANCELLATION_VERSION,
        "cancellation_id": development_reward_cancellation_id(
            source_snapshot_id=source.snapshot_id,
            cancellation_sequence=sequence,
            previous_cancellation_id=previous_id,
            reason=reason,
            cancelled_unpaid_maturity_stage_one_q_atoms=cancelled_unpaid_maturity_stage_one_q_atoms,
            cancelled_unpaid_maturity_stage_two_q_atoms=cancelled_unpaid_maturity_stage_two_q_atoms,
            cancelled_unclaimed_q_atoms=cancelled_unclaimed_q_atoms,
        ),
        "cancellation_operation_id": cancellation_operation_id,
        "source_snapshot_id": source.snapshot_id,
        "source_snapshot_hash": source.snapshot_hash,
        "source_evidence_root": source.source_evidence_root,
        "reward_id": source.reward_id,
        "contribution_id": source.contribution_id,
        "cancellation_sequence": sequence,
        "previous_cancellation_id": previous_id,
        "cancellation_epoch": cancellation_epoch,
        "reason": reason,
        "paid_before_q_atoms": source.paid_q_atoms,
        "paid_after_q_atoms": source.paid_q_atoms,
        "unpaid_immediate_before_q_atoms": source.unpaid_immediate_q_atoms,
        "unpaid_immediate_after_q_atoms": source.unpaid_immediate_q_atoms,
        "unpaid_maturity_stage_one_before_q_atoms": stage_one_before,
        "unpaid_maturity_stage_one_after_q_atoms": stage_one_before - cancelled_unpaid_maturity_stage_one_q_atoms,
        "unpaid_maturity_stage_two_before_q_atoms": stage_two_before,
        "unpaid_maturity_stage_two_after_q_atoms": stage_two_before - cancelled_unpaid_maturity_stage_two_q_atoms,
        "unclaimed_before_q_atoms": unclaimed_before,
        "unclaimed_after_q_atoms": unclaimed_before - cancelled_unclaimed_q_atoms,
        "cancelled_before_q_atoms": cancelled_before,
        "cancelled_after_q_atoms": cancelled_before + cancelled,
        "reward_liability_before_q_atoms": liability_before,
        "reward_liability_after_q_atoms": liability_before - cancelled,
        "cancelled_unpaid_maturity_stage_one_q_atoms": cancelled_unpaid_maturity_stage_one_q_atoms,
        "cancelled_unpaid_maturity_stage_two_q_atoms": cancelled_unpaid_maturity_stage_two_q_atoms,
        "cancelled_unclaimed_q_atoms": cancelled_unclaimed_q_atoms,
        "cancelled_q_atoms": cancelled,
        "returned_to_pool_q_atoms": cancelled,
        "state": "CANCELLED_UNVESTED",
    }
    return DevelopmentRewardCancellationRecord(
        **payload,
        record_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_REWARD_CANCELLATION_VERSION",
    "CancellationReason",
    "DevelopmentRewardCancellationRecord",
    "build_development_reward_cancellation",
    "development_reward_cancellation_id",
    "validate_cancellation_history",
]
