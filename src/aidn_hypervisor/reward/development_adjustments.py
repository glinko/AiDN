"""Shared immutable source state for ECO-0007 reward adjustments.

The cancellation and correction records are deliberately domain-only objects.
They bind to an accepted reward schedule and an evidence root, but do not
submit a Ledger operation or mutate a live balance.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import (
    DevelopmentRewardSchedule,
    canonical_hash,
)

DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_VERSION = "eco-0007-reward-adjustment-source.v1"


def development_reward_source_evidence_root(
    *,
    schedule_hash: str,
    source_commitment_id: str,
    source_record_hashes: Sequence[str],
) -> str:
    """Return the deterministic root for the records supporting a snapshot."""

    return canonical_hash(
        {
            "source_version": DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_VERSION,
            "schedule_hash": schedule_hash,
            "source_commitment_id": source_commitment_id,
            "source_record_hashes": sorted(source_record_hashes),
        }
    )


def development_reward_state_snapshot_id(
    *,
    reward_id: str,
    contribution_id: str,
    schedule_hash: str,
    source_commitment_id: str,
    source_evidence_root: str,
    gross_reward_q_atoms: int,
    authorized_max_reward_q_atoms: int,
    paid_q_atoms: int,
    unpaid_immediate_q_atoms: int,
    unpaid_maturity_stage_one_q_atoms: int,
    unpaid_maturity_stage_two_q_atoms: int,
    unclaimed_q_atoms: int,
    cancelled_q_atoms: int,
) -> str:
    """Derive a stable identity for one source balance snapshot."""

    return canonical_hash(
        {
            "source_version": DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_VERSION,
            "reward_id": reward_id,
            "contribution_id": contribution_id,
            "schedule_hash": schedule_hash,
            "source_commitment_id": source_commitment_id,
            "source_evidence_root": source_evidence_root,
            "gross_reward_q_atoms": gross_reward_q_atoms,
            "authorized_max_reward_q_atoms": authorized_max_reward_q_atoms,
            "paid_q_atoms": paid_q_atoms,
            "unpaid_immediate_q_atoms": unpaid_immediate_q_atoms,
            "unpaid_maturity_stage_one_q_atoms": unpaid_maturity_stage_one_q_atoms,
            "unpaid_maturity_stage_two_q_atoms": unpaid_maturity_stage_two_q_atoms,
            "unclaimed_q_atoms": unclaimed_q_atoms,
            "cancelled_q_atoms": cancelled_q_atoms,
        }
    )


class DevelopmentRewardStateSnapshot(BaseModel, frozen=True):
    """Immutable, source-bound reward state used by adjustment builders.

    ``paid_q_atoms`` and ``unpaid_immediate_q_atoms`` are intentionally
    separate from the cancellable buckets.  This makes it impossible for a
    cancellation or correction built from this object to erase paid history
    or an unpaid immediate stage by accident.
    """

    source_version: str = DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_VERSION
    snapshot_id: str = Field(min_length=1)
    reward_id: str = Field(min_length=1)
    contribution_id: str = Field(min_length=1)
    schedule_hash: str = Field(min_length=1)
    source_commitment_id: str = Field(min_length=1)
    source_record_hashes: tuple[str, ...] = Field(min_length=1)
    source_evidence_root: str = Field(min_length=1)
    gross_reward_q_atoms: int = Field(gt=0)
    authorized_max_reward_q_atoms: int = Field(ge=0)
    paid_q_atoms: int = Field(ge=0)
    unpaid_immediate_q_atoms: int = Field(ge=0)
    unpaid_maturity_stage_one_q_atoms: int = Field(ge=0)
    unpaid_maturity_stage_two_q_atoms: int = Field(ge=0)
    unclaimed_q_atoms: int = Field(ge=0)
    cancelled_q_atoms: int = Field(ge=0)
    snapshot_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_snapshot(self) -> DevelopmentRewardStateSnapshot:
        if self.source_version != DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_VERSION:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_VERSION_INVALID")
        if any(not value.strip() for value in self.source_record_hashes):
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_RECORD_INVALID")
        if len(set(self.source_record_hashes)) != len(self.source_record_hashes):
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_RECORD_DUPLICATE")
        expected_evidence_root = development_reward_source_evidence_root(
            schedule_hash=self.schedule_hash,
            source_commitment_id=self.source_commitment_id,
            source_record_hashes=self.source_record_hashes,
        )
        if self.source_evidence_root != expected_evidence_root:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_ROOT_INVALID")
        if self.authorized_max_reward_q_atoms < self.gross_reward_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_AUTHORIZED_CAP_INVALID")
        accounted = (
            self.paid_q_atoms
            + self.unpaid_immediate_q_atoms
            + self.unpaid_maturity_stage_one_q_atoms
            + self.unpaid_maturity_stage_two_q_atoms
            + self.unclaimed_q_atoms
            + self.cancelled_q_atoms
        )
        if accounted != self.gross_reward_q_atoms:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_CONSERVATION_INVALID")
        expected_id = development_reward_state_snapshot_id(
            reward_id=self.reward_id,
            contribution_id=self.contribution_id,
            schedule_hash=self.schedule_hash,
            source_commitment_id=self.source_commitment_id,
            source_evidence_root=self.source_evidence_root,
            gross_reward_q_atoms=self.gross_reward_q_atoms,
            authorized_max_reward_q_atoms=self.authorized_max_reward_q_atoms,
            paid_q_atoms=self.paid_q_atoms,
            unpaid_immediate_q_atoms=self.unpaid_immediate_q_atoms,
            unpaid_maturity_stage_one_q_atoms=self.unpaid_maturity_stage_one_q_atoms,
            unpaid_maturity_stage_two_q_atoms=self.unpaid_maturity_stage_two_q_atoms,
            unclaimed_q_atoms=self.unclaimed_q_atoms,
            cancelled_q_atoms=self.cancelled_q_atoms,
        )
        if self.snapshot_id != expected_id:
            raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_ID_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"snapshot_hash"})

    def verify_integrity(self) -> bool:
        try:
            type(self).model_validate(self.model_dump(mode="json"))
        except ValueError:
            return False
        return self.snapshot_hash == canonical_hash(self.unsigned_payload())

    @property
    def reward_liability_q_atoms(self) -> int:
        """Amount still represented by paid or potentially payable buckets."""

        return self.gross_reward_q_atoms - self.cancelled_q_atoms

    @property
    def cancellable_q_atoms(self) -> int:
        return (
            self.unpaid_maturity_stage_one_q_atoms
            + self.unpaid_maturity_stage_two_q_atoms
            + self.unclaimed_q_atoms
        )


def build_development_reward_state_snapshot(
    *,
    schedule: DevelopmentRewardSchedule,
    source_commitment_id: str,
    source_record_hashes: Sequence[str],
    paid_q_atoms: int,
    unpaid_immediate_q_atoms: int,
    unpaid_maturity_stage_one_q_atoms: int,
    unpaid_maturity_stage_two_q_atoms: int,
    unclaimed_q_atoms: int,
    cancelled_q_atoms: int = 0,
    authorized_max_reward_q_atoms: int | None = None,
) -> DevelopmentRewardStateSnapshot:
    """Build a source snapshot and verify it against an accepted schedule."""

    schedule_payload = schedule.model_dump(mode="json", exclude={"schedule_hash"})
    if schedule.schedule_hash != canonical_hash(schedule_payload):
        raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SCHEDULE_HASH_INVALID")
    if not source_commitment_id.strip():
        raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_COMMITMENT_INVALID")
    if any(not value.strip() for value in source_record_hashes):
        raise ValueError("DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_RECORD_INVALID")
    authorized_max = (
        schedule.gross_reward_q_atoms
        if authorized_max_reward_q_atoms is None
        else authorized_max_reward_q_atoms
    )
    source_evidence_root = development_reward_source_evidence_root(
        schedule_hash=schedule.schedule_hash,
        source_commitment_id=source_commitment_id,
        source_record_hashes=source_record_hashes,
    )
    payload = {
        "source_version": DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_VERSION,
        "reward_id": schedule.reward_id,
        "contribution_id": schedule.contribution_id,
        "schedule_hash": schedule.schedule_hash,
        "source_commitment_id": source_commitment_id,
        "source_record_hashes": tuple(source_record_hashes),
        "source_evidence_root": source_evidence_root,
        "gross_reward_q_atoms": schedule.gross_reward_q_atoms,
        "authorized_max_reward_q_atoms": authorized_max,
        "paid_q_atoms": paid_q_atoms,
        "unpaid_immediate_q_atoms": unpaid_immediate_q_atoms,
        "unpaid_maturity_stage_one_q_atoms": unpaid_maturity_stage_one_q_atoms,
        "unpaid_maturity_stage_two_q_atoms": unpaid_maturity_stage_two_q_atoms,
        "unclaimed_q_atoms": unclaimed_q_atoms,
        "cancelled_q_atoms": cancelled_q_atoms,
    }
    snapshot_id = development_reward_state_snapshot_id(
        reward_id=schedule.reward_id,
        contribution_id=schedule.contribution_id,
        schedule_hash=schedule.schedule_hash,
        source_commitment_id=source_commitment_id,
        source_evidence_root=source_evidence_root,
        gross_reward_q_atoms=schedule.gross_reward_q_atoms,
        authorized_max_reward_q_atoms=authorized_max,
        paid_q_atoms=paid_q_atoms,
        unpaid_immediate_q_atoms=unpaid_immediate_q_atoms,
        unpaid_maturity_stage_one_q_atoms=unpaid_maturity_stage_one_q_atoms,
        unpaid_maturity_stage_two_q_atoms=unpaid_maturity_stage_two_q_atoms,
        unclaimed_q_atoms=unclaimed_q_atoms,
        cancelled_q_atoms=cancelled_q_atoms,
    )
    return DevelopmentRewardStateSnapshot(
        **payload,
        snapshot_id=snapshot_id,
        snapshot_hash=canonical_hash(payload | {"snapshot_id": snapshot_id}),
    )


__all__ = [
    "DEVELOPMENT_REWARD_ADJUSTMENT_SOURCE_VERSION",
    "DevelopmentRewardStateSnapshot",
    "build_development_reward_state_snapshot",
    "development_reward_source_evidence_root",
    "development_reward_state_snapshot_id",
]
