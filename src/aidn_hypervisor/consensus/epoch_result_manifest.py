"""Immutable RFC-0048 epoch result manifest committed through consensus."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EPOCH_RESULT_MANIFEST_LEGACY_VERSION = "aidn.epoch-result-manifest.v1"
EPOCH_RESULT_MANIFEST_VERSION = "aidn.epoch-result-manifest.v2"
EPOCH_RESULT_MANIFEST_OPERATION = "EPOCH_RESULT_MANIFEST_COMMIT"


def _manifest_hash(payload: dict[str, object]) -> str:
    version = payload.get("manifest_version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("epoch result manifest version is required")
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(
        (version + ":" + encoded).encode("utf-8")
    ).hexdigest()


class EpochResultManifest(BaseModel):
    """Hash-bound evidence roots for one completed Epoch Engine run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: str = EPOCH_RESULT_MANIFEST_VERSION
    manifest_state: Literal["FINALIZED"] = "FINALIZED"
    epoch_number: int = Field(ge=0)
    start_height: int = Field(ge=1)
    closing_height: int = Field(ge=1)
    start_time: str = Field(min_length=1)
    closing_time: str = Field(min_length=1)
    closing_block_hash: str | None = None
    closing_state_root: str | None = None
    source_app_hash: str | None = None
    protocol_version: str = Field(min_length=1)
    parameter_version: str = Field(min_length=1)
    task_set_version: str = Field(min_length=1)
    epoch_schedule_version: str = Field(min_length=1)
    epoch_schedule_hash: str = Field(min_length=1)
    scheduled_end_time: str = Field(min_length=1)
    frozen_evidence_root: str = Field(min_length=1)
    participant_snapshot_root: str = Field(min_length=1)
    service_snapshot_root: str = Field(min_length=1)
    task_result_root: str = Field(min_length=1)
    eligibility_root: str = Field(min_length=1)
    reputation_root: str = Field(min_length=1)
    penalty_root: str = Field(min_length=1)
    recycle_root: str = Field(min_length=1)
    reward_authorization_root: str = Field(min_length=1)
    reward_result_root: str = Field(min_length=1)
    faucet_root: str = Field(min_length=1)
    validator_set_update_root: str = Field(min_length=1)
    # These fields bridge the RFC-0048 manifest to RFC-0059's transition
    # payload, which already requires an explicit reward calculation and next
    # parameter root.
    reward_calculation_root: str = Field(min_length=1)
    next_protocol_parameters_hash: str = Field(min_length=1)
    pool_budgets: dict[str, int] = Field(default_factory=dict)
    pool_budget_references: dict[str, str] = Field(default_factory=dict)
    next_epoch_reference: str = Field(min_length=1)
    previous_epoch_result_hash: str | None = None
    manifest_hash: str

    @model_validator(mode="after")
    def validate_manifest(self) -> EpochResultManifest:
        if self.manifest_version not in {
            EPOCH_RESULT_MANIFEST_LEGACY_VERSION,
            EPOCH_RESULT_MANIFEST_VERSION,
        }:
            raise ValueError("epoch result manifest version is unsupported")
        if self.manifest_version == EPOCH_RESULT_MANIFEST_VERSION and any(
            value in (None, "")
            for value in (
                self.closing_block_hash,
                self.closing_state_root,
                self.source_app_hash,
            )
        ):
            raise ValueError("epoch result manifest historical commitment is incomplete")
        if self.closing_height < self.start_height:
            raise ValueError("epoch result manifest closing height precedes start height")
        if set(self.pool_budgets) != set(self.pool_budget_references):
            raise ValueError("every epoch result pool budget must have one canonical reference")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.pool_budgets.values()
        ):
            raise ValueError("epoch result pool budgets must be non-negative integers")
        if self.manifest_hash != _manifest_hash(self.unsigned_payload()):
            raise ValueError("epoch result manifest hash does not match payload")
        return self

    def unsigned_payload(self) -> dict[str, object]:
        payload = self.model_dump(mode="json", exclude={"manifest_hash"})
        if self.manifest_version == EPOCH_RESULT_MANIFEST_LEGACY_VERSION:
            for field in ("closing_block_hash", "closing_state_root", "source_app_hash"):
                if payload.get(field) is None:
                    payload.pop(field, None)
        return payload


def build_epoch_result_manifest(**values: object) -> EpochResultManifest:
    """Build a deterministic manifest and calculate its immutable hash."""
    payload = {
        "manifest_version": EPOCH_RESULT_MANIFEST_VERSION,
        **values,
    }
    payload.setdefault("manifest_state", "FINALIZED")
    payload.setdefault("previous_epoch_result_hash", None)
    payload.pop("manifest_hash", None)
    payload["manifest_hash"] = _manifest_hash(
        payload
    )
    return EpochResultManifest.model_validate(payload)


__all__ = [
    "EPOCH_RESULT_MANIFEST_OPERATION",
    "EPOCH_RESULT_MANIFEST_LEGACY_VERSION",
    "EPOCH_RESULT_MANIFEST_VERSION",
    "EpochResultManifest",
    "build_epoch_result_manifest",
]
