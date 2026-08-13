"""Canonical readiness evidence for an ``EPOCH_TRANSITION``.

The report is deliberately read-only.  It exposes the roots that can be
observed from the current ABCI state and names every missing Epoch Engine
input.  It must not manufacture task, eligibility or reward roots from
unrelated Ledger data.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EPOCH_TRANSITION_INPUT_REPORT_VERSION = "aidn.epoch-transition-inputs.v1"
EPOCH_TRANSITION_INPUTS_NOT_READY = "EPOCH_TRANSITION_INPUTS_NOT_READY"


def _canonical_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(
        (EPOCH_TRANSITION_INPUT_REPORT_VERSION + ":" + encoded).encode("utf-8")
    ).hexdigest()
    return "sha256:" + digest


class EpochTransitionInputReport(BaseModel):
    """Hash-bound availability report for one closing chain state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = EPOCH_TRANSITION_INPUT_REPORT_VERSION
    status: Literal["READY", "BLOCKED"]
    closing_epoch: int | None = Field(default=None, ge=0)
    opening_epoch: int | None = Field(default=None, ge=0)
    closing_height: int | None = Field(default=None, ge=1)
    closing_block_hash: str | None = None
    closing_state_root: str | None = None
    epoch_task_result_root: str | None = None
    eligibility_snapshot_root: str | None = None
    reward_calculation_root: str | None = None
    next_protocol_parameters_hash: str | None = None
    pool_budgets: dict[str, int] = Field(default_factory=dict)
    pool_budget_references: dict[str, str] = Field(default_factory=dict)
    source_app_hash: str | None = None
    epoch_schedule_version: str | None = None
    epoch_schedule_hash: str | None = None
    epoch_schedule_commit_operation_id: str | None = None
    epoch_schedule_commit_sequence_id: int | None = Field(default=None, ge=1)
    epoch_schedule_commit_record_digest: str | None = None
    canonical_block_time: str | None = None
    scheduled_end_time: str | None = None
    epoch_boundary_reached: bool = False
    epoch_result_manifest_hash: str | None = None
    epoch_result_manifest_operation_id: str | None = None
    missing_inputs: list[str] = Field(default_factory=list)
    reason_code: str | None = None
    report_hash: str

    @model_validator(mode="after")
    def validate_report(self) -> EpochTransitionInputReport:
        if self.schema_version != EPOCH_TRANSITION_INPUT_REPORT_VERSION:
            raise ValueError("epoch transition input report schema version is unsupported")
        for name in (
            "closing_block_hash",
            "closing_state_root",
            "epoch_task_result_root",
            "eligibility_snapshot_root",
            "reward_calculation_root",
            "next_protocol_parameters_hash",
            "source_app_hash",
            "epoch_schedule_version",
            "epoch_schedule_hash",
            "epoch_schedule_commit_operation_id",
            "epoch_schedule_commit_record_digest",
            "canonical_block_time",
            "scheduled_end_time",
            "epoch_result_manifest_hash",
            "epoch_result_manifest_operation_id",
        ):
            value = getattr(self, name)
            if value is not None and not value.strip():
                raise ValueError(f"{name} must not be empty")
        if self.opening_epoch is not None and self.closing_epoch is not None:
            if self.opening_epoch != self.closing_epoch + 1:
                raise ValueError("opening epoch must immediately follow closing epoch")
        schedule_reference_fields = {
            "epoch_schedule_commit_sequence_id",
            "epoch_schedule_commit_record_digest",
        }
        supplied_schedule_reference_fields = schedule_reference_fields & {
            name for name in schedule_reference_fields if getattr(self, name) is not None
        }
        if self.epoch_schedule_commit_operation_id:
            if supplied_schedule_reference_fields != schedule_reference_fields:
                raise ValueError("epoch schedule finality reference is incomplete")
        elif supplied_schedule_reference_fields:
            raise ValueError("epoch schedule finality reference requires an operation ID")
        if set(self.pool_budgets) - set(self.pool_budget_references):
            raise ValueError("every pool budget must have a canonical reference")
        if any(isinstance(value, bool) or value < 0 for value in self.pool_budgets.values()):
            raise ValueError("pool budgets must be non-negative integers")
        if self.status == "READY":
            required = (
                "closing_epoch",
                "opening_epoch",
                "closing_height",
                "closing_block_hash",
                "closing_state_root",
                "epoch_task_result_root",
                "eligibility_snapshot_root",
                "reward_calculation_root",
                "next_protocol_parameters_hash",
                "source_app_hash",
                "epoch_schedule_version",
                "epoch_schedule_hash",
                "canonical_block_time",
                "scheduled_end_time",
            )
            missing = [name for name in required if getattr(self, name) in (None, "")]
            if (
                missing
                or self.missing_inputs
                or not self.pool_budgets
                or not self.epoch_boundary_reached
            ):
                raise ValueError("READY epoch transition input report is incomplete")
            if self.reason_code is not None:
                raise ValueError("READY epoch transition input report cannot have a reason")
        elif not self.missing_inputs:
            raise ValueError("BLOCKED epoch transition input report must name missing inputs")
        else:
            if self.reason_code is None:
                raise ValueError("BLOCKED epoch transition input report must have a reason")
        if self.report_hash != _canonical_hash(self.unsigned_payload()):
            raise ValueError("epoch transition input report hash does not match payload")
        return self

    def unsigned_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"report_hash"})

    def transition_payload(self, *, protocol_authority_policy_hash: str) -> dict[str, object]:
        """Return the Ledger payload only when every input is available."""
        if self.status != "READY":
            raise ValueError(EPOCH_TRANSITION_INPUTS_NOT_READY)
        payload = {
            "closing_epoch": self.closing_epoch,
            "opening_epoch": self.opening_epoch,
            "closing_height": self.closing_height,
            "closing_block_hash": self.closing_block_hash,
            "closing_state_root": self.closing_state_root,
            "source_app_hash": self.source_app_hash,
            "epoch_task_result_root": self.epoch_task_result_root,
            "eligibility_snapshot_root": self.eligibility_snapshot_root,
            "reward_calculation_root": self.reward_calculation_root,
            "next_protocol_parameters_hash": self.next_protocol_parameters_hash,
            "pool_budgets": dict(self.pool_budgets),
            "pool_budget_references": dict(self.pool_budget_references),
            "epoch_schedule_version": self.epoch_schedule_version,
            "epoch_schedule_hash": self.epoch_schedule_hash,
            "canonical_block_time": self.canonical_block_time,
            "scheduled_end_time": self.scheduled_end_time,
            "next_epoch_start_time": self.scheduled_end_time,
            "protocol_authority_policy_hash": protocol_authority_policy_hash,
        }
        if self.epoch_schedule_commit_operation_id:
            if (
                self.epoch_schedule_commit_sequence_id is None
                or not self.epoch_schedule_commit_record_digest
            ):
                raise ValueError("epoch schedule finality reference is incomplete")
            payload.update(
                {
                    "epoch_schedule_commit_operation_id": self.epoch_schedule_commit_operation_id,
                    "epoch_schedule_commit_sequence_id": self.epoch_schedule_commit_sequence_id,
                    "epoch_schedule_commit_record_digest": self.epoch_schedule_commit_record_digest,
                }
            )
        if self.epoch_result_manifest_hash and self.epoch_result_manifest_operation_id:
            payload.update(
                {
                    "epoch_result_manifest_hash": self.epoch_result_manifest_hash,
                    "epoch_result_manifest_operation_id": self.epoch_result_manifest_operation_id,
                }
            )
        return payload


def build_epoch_transition_input_report(
    *,
    closing_epoch: int | None = None,
    opening_epoch: int | None = None,
    closing_height: int | None = None,
    closing_block_hash: str | None = None,
    closing_state_root: str | None = None,
    source_app_hash: str | None = None,
    epoch_task_result_root: str | None = None,
    eligibility_snapshot_root: str | None = None,
    reward_calculation_root: str | None = None,
    next_protocol_parameters_hash: str | None = None,
    pool_budgets: Mapping[str, int] | None = None,
    pool_budget_references: Mapping[str, str] | None = None,
    epoch_schedule_version: str | None = None,
    epoch_schedule_hash: str | None = None,
    epoch_schedule_commit_operation_id: str | None = None,
    epoch_schedule_commit_sequence_id: int | None = None,
    epoch_schedule_commit_record_digest: str | None = None,
    canonical_block_time: str | None = None,
    scheduled_end_time: str | None = None,
    epoch_boundary_reached: bool = False,
    epoch_result_manifest_hash: str | None = None,
    epoch_result_manifest_operation_id: str | None = None,
    additional_missing_inputs: tuple[str, ...] = (),
) -> EpochTransitionInputReport:
    """Build a deterministic READY/BLOCKED report from observed inputs."""
    budgets = dict(pool_budgets or {})
    references = dict(pool_budget_references or {})
    values: dict[str, object] = {
        "schema_version": EPOCH_TRANSITION_INPUT_REPORT_VERSION,
        "closing_epoch": closing_epoch,
        "opening_epoch": opening_epoch,
        "closing_height": closing_height,
        "closing_block_hash": closing_block_hash,
        "closing_state_root": closing_state_root,
        "source_app_hash": source_app_hash,
        "epoch_task_result_root": epoch_task_result_root,
        "eligibility_snapshot_root": eligibility_snapshot_root,
        "reward_calculation_root": reward_calculation_root,
        "next_protocol_parameters_hash": next_protocol_parameters_hash,
        "pool_budgets": budgets,
        "pool_budget_references": references,
        "epoch_schedule_version": epoch_schedule_version,
        "epoch_schedule_hash": epoch_schedule_hash,
        "epoch_schedule_commit_operation_id": epoch_schedule_commit_operation_id,
        "epoch_schedule_commit_sequence_id": epoch_schedule_commit_sequence_id,
        "epoch_schedule_commit_record_digest": epoch_schedule_commit_record_digest,
        "canonical_block_time": canonical_block_time,
        "scheduled_end_time": scheduled_end_time,
        "epoch_boundary_reached": epoch_boundary_reached,
        "epoch_result_manifest_hash": epoch_result_manifest_hash,
        "epoch_result_manifest_operation_id": epoch_result_manifest_operation_id,
    }
    required = (
        "closing_epoch",
        "opening_epoch",
        "closing_height",
        "closing_block_hash",
        "closing_state_root",
        "epoch_task_result_root",
        "eligibility_snapshot_root",
        "reward_calculation_root",
        "next_protocol_parameters_hash",
        "source_app_hash",
        "epoch_schedule_version",
        "epoch_schedule_hash",
        "canonical_block_time",
        "scheduled_end_time",
    )
    missing = [name for name in required if values[name] in (None, "")]
    missing.extend(
        f"pool_budget_reference:{pool_id}"
        for pool_id in sorted(set(budgets) - set(references))
    )
    missing.extend(str(item) for item in additional_missing_inputs if str(item).strip())
    if not budgets:
        missing.append("pool_budgets")
    if not epoch_boundary_reached:
        missing.append("epoch_boundary")
    missing = list(dict.fromkeys(missing))
    status: Literal["READY", "BLOCKED"] = "READY" if not missing else "BLOCKED"
    report_values = {
        **values,
        "status": status,
        "missing_inputs": missing,
        "reason_code": None if status == "READY" else EPOCH_TRANSITION_INPUTS_NOT_READY,
    }
    report_values["report_hash"] = _canonical_hash(report_values)
    return EpochTransitionInputReport.model_validate(report_values)


__all__ = [
    "EPOCH_TRANSITION_INPUT_REPORT_VERSION",
    "EPOCH_TRANSITION_INPUTS_NOT_READY",
    "EpochTransitionInputReport",
    "build_epoch_transition_input_report",
]
