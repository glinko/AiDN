"""Append-only ECO-0007 reward corrections over unpaid balances."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_adjustments import DevelopmentRewardStateSnapshot
from aidn_hypervisor.reward.development_distribution import canonical_hash

DEVELOPMENT_REWARD_CORRECTION_VERSION = "eco-0007-reward-correction.v1"
CorrectionReason = Literal[
    "ATTRIBUTION_ERROR",
    "ARITHMETIC_ERROR",
    "DUPLICATE_REWARD",
    "INVALID_ATTESTATION",
    "WALLET_BINDING_ERROR",
    "CHALLENGE_RESOLUTION",
    "PROTOCOL_MIGRATION",
]


def development_reward_correction_id(
    *,
    source_snapshot_id: str,
    correction_sequence: int,
    previous_correction_id: str | None,
    reason: str,
    authorization_reference: str,
    delta_unpaid_maturity_stage_one_q_atoms: int,
    delta_unpaid_maturity_stage_two_q_atoms: int,
    delta_unclaimed_q_atoms: int,
) -> str:
    """Derive a stable semantic identity independent of envelope metadata."""

    return canonical_hash(
        {
            "correction_version": DEVELOPMENT_REWARD_CORRECTION_VERSION,
            "source_snapshot_id": source_snapshot_id,
            "correction_sequence": correction_sequence,
            "previous_correction_id": previous_correction_id,
            "reason": reason,
            "authorization_reference": authorization_reference,
            "delta_unpaid_maturity_stage_one_q_atoms": delta_unpaid_maturity_stage_one_q_atoms,
            "delta_unpaid_maturity_stage_two_q_atoms": delta_unpaid_maturity_stage_two_q_atoms,
            "delta_unclaimed_q_atoms": delta_unclaimed_q_atoms,
        }
    )


class DevelopmentRewardCorrectionRecord(BaseModel, frozen=True):
    """Immutable append-only correction that never rewrites paid history."""

    correction_version: str = DEVELOPMENT_REWARD_CORRECTION_VERSION
    correction_id: str = Field(min_length=1)
    correction_operation_id: str = Field(min_length=1)
    source_snapshot_id: str = Field(min_length=1)
    source_snapshot_hash: str = Field(min_length=1)
    source_evidence_root: str = Field(min_length=1)
    reward_id: str = Field(min_length=1)
    contribution_id: str = Field(min_length=1)
    correction_sequence: int = Field(ge=1)
    previous_correction_id: str | None = None
    correction_epoch: int = Field(ge=0)
    reason: CorrectionReason
    authorization_reference: str = Field(min_length=1)
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
    reward_liability_before_q_atoms: int = Field(gt=0)
    reward_liability_after_q_atoms: int = Field(ge=0)
    delta_unpaid_maturity_stage_one_q_atoms: int
    delta_unpaid_maturity_stage_two_q_atoms: int
    delta_unclaimed_q_atoms: int
    correction_delta_q_atoms: int
    returned_to_pool_q_atoms: int = Field(ge=0)
    additional_reserved_q_atoms: int = Field(ge=0)
    state: Literal["CORRECTED"] = "CORRECTED"
    record_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_record(self) -> DevelopmentRewardCorrectionRecord:
        if self.correction_version != DEVELOPMENT_REWARD_CORRECTION_VERSION:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_VERSION_INVALID")
        if not self.correction_operation_id.strip() or not self.authorization_reference.strip():
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_AUTHORIZATION_INVALID")
        if self.paid_after_q_atoms != self.paid_before_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_PAID_HISTORY_MUTATION")
        if self.unpaid_immediate_after_q_atoms != self.unpaid_immediate_before_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_IMMEDIATE_MUTATION")
        expected_delta = (
            self.delta_unpaid_maturity_stage_one_q_atoms
            + self.delta_unpaid_maturity_stage_two_q_atoms
            + self.delta_unclaimed_q_atoms
        )
        if self.correction_delta_q_atoms != expected_delta:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_DELTA_INVALID")
        if self.unpaid_maturity_stage_one_after_q_atoms != (
            self.unpaid_maturity_stage_one_before_q_atoms
            + self.delta_unpaid_maturity_stage_one_q_atoms
        ):
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_STAGE_ONE_INVALID")
        if self.unpaid_maturity_stage_two_after_q_atoms != (
            self.unpaid_maturity_stage_two_before_q_atoms
            + self.delta_unpaid_maturity_stage_two_q_atoms
        ):
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_STAGE_TWO_INVALID")
        if self.unclaimed_after_q_atoms != self.unclaimed_before_q_atoms + self.delta_unclaimed_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_UNCLAIMED_INVALID")
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
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_CONSERVATION_INVALID")
        if self.reward_liability_after_q_atoms != expected_after:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_CONSERVATION_INVALID")
        if self.correction_delta_q_atoms != (
            self.additional_reserved_q_atoms - self.returned_to_pool_q_atoms
        ):
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_POOL_DELTA_INVALID")
        if self.reward_liability_after_q_atoms + self.returned_to_pool_q_atoms != (
            self.reward_liability_before_q_atoms + self.additional_reserved_q_atoms
        ):
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_CONSERVATION_INVALID")
        if self.correction_delta_q_atoms == 0:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_DELTA_ZERO")
        expected_id = development_reward_correction_id(
            source_snapshot_id=self.source_snapshot_id,
            correction_sequence=self.correction_sequence,
            previous_correction_id=self.previous_correction_id,
            reason=self.reason,
            authorization_reference=self.authorization_reference,
            delta_unpaid_maturity_stage_one_q_atoms=self.delta_unpaid_maturity_stage_one_q_atoms,
            delta_unpaid_maturity_stage_two_q_atoms=self.delta_unpaid_maturity_stage_two_q_atoms,
            delta_unclaimed_q_atoms=self.delta_unclaimed_q_atoms,
        )
        if self.correction_id != expected_id:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_ID_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"record_hash"})

    def verify_integrity(self) -> bool:
        try:
            type(self).model_validate(self.model_dump(mode="json"))
        except ValueError:
            return False
        return self.record_hash == canonical_hash(self.unsigned_payload())


def validate_reward_correction_history(
    source: DevelopmentRewardStateSnapshot,
    records: Sequence[DevelopmentRewardCorrectionRecord],
) -> tuple[DevelopmentRewardCorrectionRecord, ...]:
    """Validate ordering, source binding, duplicate identity and conservation."""

    by_id: dict[str, DevelopmentRewardCorrectionRecord] = {}
    for record in records:
        if not record.verify_integrity():
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_RECORD_INVALID")
        existing = by_id.get(record.correction_id)
        if existing is not None:
            if existing.record_hash == record.record_hash:
                raise ValueError("DEVELOPMENT_REWARD_CORRECTION_DUPLICATE")
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_CONFLICT")
        if record.source_snapshot_id != source.snapshot_id:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_SOURCE_MISMATCH")
        if record.source_snapshot_hash != source.snapshot_hash:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_SOURCE_HASH_MISMATCH")
        if record.source_evidence_root != source.source_evidence_root:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_EVIDENCE_MISMATCH")
        if record.reward_id != source.reward_id or record.contribution_id != source.contribution_id:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_REWARD_MISMATCH")
        by_id[record.correction_id] = record

    ordered = tuple(sorted(by_id.values(), key=lambda item: item.correction_sequence))
    previous_id: str | None = None
    expected_stage_one = source.unpaid_maturity_stage_one_q_atoms
    expected_stage_two = source.unpaid_maturity_stage_two_q_atoms
    expected_unclaimed = source.unclaimed_q_atoms
    for expected_sequence, record in enumerate(ordered, start=1):
        if record.correction_sequence != expected_sequence:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_SEQUENCE_INVALID")
        if record.previous_correction_id != previous_id:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_CHAIN_INVALID")
        if record.paid_before_q_atoms != source.paid_q_atoms or record.paid_after_q_atoms != source.paid_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_PAID_HISTORY_MUTATION")
        if (
            record.unpaid_immediate_before_q_atoms != source.unpaid_immediate_q_atoms
            or record.unpaid_immediate_after_q_atoms != source.unpaid_immediate_q_atoms
        ):
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_IMMEDIATE_MUTATION")
        if record.unpaid_maturity_stage_one_before_q_atoms != expected_stage_one:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_CHAIN_CONSERVATION_INVALID")
        if record.unpaid_maturity_stage_two_before_q_atoms != expected_stage_two:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_CHAIN_CONSERVATION_INVALID")
        if record.unclaimed_before_q_atoms != expected_unclaimed:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_CHAIN_CONSERVATION_INVALID")
        if record.reward_liability_after_q_atoms > source.authorized_max_reward_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_CORRECTION_OVERPAID_DELTA")
        expected_stage_one = record.unpaid_maturity_stage_one_after_q_atoms
        expected_stage_two = record.unpaid_maturity_stage_two_after_q_atoms
        expected_unclaimed = record.unclaimed_after_q_atoms
        previous_id = record.correction_id
    return ordered


def build_development_reward_correction(
    *,
    source: DevelopmentRewardStateSnapshot,
    correction_operation_id: str,
    correction_epoch: int,
    reason: CorrectionReason,
    authorization_reference: str,
    delta_unpaid_maturity_stage_one_q_atoms: int = 0,
    delta_unpaid_maturity_stage_two_q_atoms: int = 0,
    delta_unclaimed_q_atoms: int = 0,
    previous_corrections: Sequence[DevelopmentRewardCorrectionRecord] = (),
) -> DevelopmentRewardCorrectionRecord:
    """Build a bounded correction over unpaid maturity/unclaimed liability."""

    if not source.verify_integrity():
        raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_INVALID")
    if correction_epoch < 0:
        raise ValueError("DEVELOPMENT_REWARD_CORRECTION_EPOCH_INVALID")
    previous = validate_reward_correction_history(source, previous_corrections)
    stage_one_before = source.unpaid_maturity_stage_one_q_atoms + sum(
        item.delta_unpaid_maturity_stage_one_q_atoms for item in previous
    )
    stage_two_before = source.unpaid_maturity_stage_two_q_atoms + sum(
        item.delta_unpaid_maturity_stage_two_q_atoms for item in previous
    )
    unclaimed_before = source.unclaimed_q_atoms + sum(item.delta_unclaimed_q_atoms for item in previous)
    if stage_one_before < 0 or stage_two_before < 0 or unclaimed_before < 0:
        raise ValueError("DEVELOPMENT_REWARD_CORRECTION_NEGATIVE_BALANCE")
    stage_one_after = stage_one_before + delta_unpaid_maturity_stage_one_q_atoms
    stage_two_after = stage_two_before + delta_unpaid_maturity_stage_two_q_atoms
    unclaimed_after = unclaimed_before + delta_unclaimed_q_atoms
    if min(stage_one_after, stage_two_after, unclaimed_after) < 0:
        raise ValueError("DEVELOPMENT_REWARD_CORRECTION_NEGATIVE_DELTA_EXCEEDS_UNPAID")
    delta = (
        delta_unpaid_maturity_stage_one_q_atoms
        + delta_unpaid_maturity_stage_two_q_atoms
        + delta_unclaimed_q_atoms
    )
    if delta == 0:
        raise ValueError("DEVELOPMENT_REWARD_CORRECTION_DELTA_ZERO")
    liability_before = (
        source.paid_q_atoms
        + source.unpaid_immediate_q_atoms
        + stage_one_before
        + stage_two_before
        + unclaimed_before
    )
    liability_after = (
        source.paid_q_atoms
        + source.unpaid_immediate_q_atoms
        + stage_one_after
        + stage_two_after
        + unclaimed_after
    )
    if liability_after > source.authorized_max_reward_q_atoms:
        raise ValueError("DEVELOPMENT_REWARD_CORRECTION_OVERPAID_DELTA")
    sequence = len(previous) + 1
    previous_id = previous[-1].correction_id if previous else None
    returned = max(0, -delta)
    additional = max(0, delta)
    payload = {
        "correction_version": DEVELOPMENT_REWARD_CORRECTION_VERSION,
        "correction_id": development_reward_correction_id(
            source_snapshot_id=source.snapshot_id,
            correction_sequence=sequence,
            previous_correction_id=previous_id,
            reason=reason,
            authorization_reference=authorization_reference,
            delta_unpaid_maturity_stage_one_q_atoms=delta_unpaid_maturity_stage_one_q_atoms,
            delta_unpaid_maturity_stage_two_q_atoms=delta_unpaid_maturity_stage_two_q_atoms,
            delta_unclaimed_q_atoms=delta_unclaimed_q_atoms,
        ),
        "correction_operation_id": correction_operation_id,
        "source_snapshot_id": source.snapshot_id,
        "source_snapshot_hash": source.snapshot_hash,
        "source_evidence_root": source.source_evidence_root,
        "reward_id": source.reward_id,
        "contribution_id": source.contribution_id,
        "correction_sequence": sequence,
        "previous_correction_id": previous_id,
        "correction_epoch": correction_epoch,
        "reason": reason,
        "authorization_reference": authorization_reference,
        "paid_before_q_atoms": source.paid_q_atoms,
        "paid_after_q_atoms": source.paid_q_atoms,
        "unpaid_immediate_before_q_atoms": source.unpaid_immediate_q_atoms,
        "unpaid_immediate_after_q_atoms": source.unpaid_immediate_q_atoms,
        "unpaid_maturity_stage_one_before_q_atoms": stage_one_before,
        "unpaid_maturity_stage_one_after_q_atoms": stage_one_after,
        "unpaid_maturity_stage_two_before_q_atoms": stage_two_before,
        "unpaid_maturity_stage_two_after_q_atoms": stage_two_after,
        "unclaimed_before_q_atoms": unclaimed_before,
        "unclaimed_after_q_atoms": unclaimed_after,
        "reward_liability_before_q_atoms": liability_before,
        "reward_liability_after_q_atoms": liability_after,
        "delta_unpaid_maturity_stage_one_q_atoms": delta_unpaid_maturity_stage_one_q_atoms,
        "delta_unpaid_maturity_stage_two_q_atoms": delta_unpaid_maturity_stage_two_q_atoms,
        "delta_unclaimed_q_atoms": delta_unclaimed_q_atoms,
        "correction_delta_q_atoms": delta,
        "returned_to_pool_q_atoms": returned,
        "additional_reserved_q_atoms": additional,
        "state": "CORRECTED",
    }
    return DevelopmentRewardCorrectionRecord(
        **payload,
        record_hash=canonical_hash(payload),
    )


__all__ = [
    "DEVELOPMENT_REWARD_CORRECTION_VERSION",
    "CorrectionReason",
    "DevelopmentRewardCorrectionRecord",
    "build_development_reward_correction",
    "development_reward_correction_id",
    "validate_reward_correction_history",
]
