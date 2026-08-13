"""One-time, authority-gated recovery activation for a late initial schedule.

This is deliberately not a mutable schedule edit.  It preserves the original
schedule hash and records the only allowed recovery: establishing Epoch 0's
effective start before any result manifest or transition exists.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field, model_validator

EPOCH_SCHEDULE_REBASE_VERSION = "aidn.epoch-schedule-rebase.v1"
EPOCH_SCHEDULE_REBASE_OPERATION = "EPOCH_SCHEDULE_REBASE"
CONTROLLED_LOCALNET_LATE_INITIAL_SCHEDULE = "CONTROLLED_LOCALNET_LATE_INITIAL_SCHEDULE"


def _hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256((EPOCH_SCHEDULE_REBASE_VERSION + ":" + encoded).encode("utf-8")).hexdigest()


class EpochScheduleRebase(BaseModel):
    """Immutable activation boundary for a schedule committed after its start."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = EPOCH_SCHEDULE_REBASE_VERSION
    schedule_hash: str = Field(min_length=1)
    effective_epoch_zero_start_time: str = Field(min_length=1)
    reason_code: str = CONTROLLED_LOCALNET_LATE_INITIAL_SCHEDULE
    recovery_profile: str = "controlled-localnet"
    rebase_hash: str

    @model_validator(mode="after")
    def validate_rebase(self) -> EpochScheduleRebase:
        if self.schema_version != EPOCH_SCHEDULE_REBASE_VERSION:
            raise ValueError("epoch schedule rebase schema version is unsupported")
        if self.reason_code != CONTROLLED_LOCALNET_LATE_INITIAL_SCHEDULE:
            raise ValueError("epoch schedule rebase reason is unsupported")
        if self.recovery_profile != "controlled-localnet":
            raise ValueError("epoch schedule rebase recovery profile is unsupported")
        from aidn_hypervisor.consensus.epoch_schedule import _parse_timestamp

        _parse_timestamp(
            self.effective_epoch_zero_start_time,
            field_name="effective_epoch_zero_start_time",
        )
        if self.rebase_hash != _hash(self.unsigned_payload()):
            raise ValueError("epoch schedule rebase hash does not match payload")
        return self

    def unsigned_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"rebase_hash"})


def build_epoch_schedule_rebase(**values: object) -> EpochScheduleRebase:
    payload = {
        "schema_version": EPOCH_SCHEDULE_REBASE_VERSION,
        "reason_code": CONTROLLED_LOCALNET_LATE_INITIAL_SCHEDULE,
        "recovery_profile": "controlled-localnet",
        **values,
    }
    payload.pop("rebase_hash", None)
    payload["rebase_hash"] = _hash(payload)
    return EpochScheduleRebase.model_validate(payload)


__all__ = [
    "CONTROLLED_LOCALNET_LATE_INITIAL_SCHEDULE",
    "EPOCH_SCHEDULE_REBASE_OPERATION",
    "EPOCH_SCHEDULE_REBASE_VERSION",
    "EpochScheduleRebase",
    "build_epoch_schedule_rebase",
]
