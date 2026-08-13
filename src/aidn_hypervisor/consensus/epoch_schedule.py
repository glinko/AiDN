"""Versioned canonical-time epoch schedule for the live consensus boundary."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict, Field, model_validator

EPOCH_SCHEDULE_VERSION = "aidn.epoch-schedule.v1"


def _parse_timestamp(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an RFC3339 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _schedule_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(
        (EPOCH_SCHEDULE_VERSION + ":" + canonical).encode("utf-8")
    ).hexdigest()


class EpochBoundary(BaseModel):
    """Deterministic boundary observation for the currently open epoch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_epoch: int = Field(ge=0)
    active_start_time: str
    scheduled_end_time: str
    boundary_reached: bool
    closing_epoch: int | None = Field(default=None, ge=0)
    opening_epoch: int | None = Field(default=None, ge=0)


class EpochSchedule(BaseModel):
    """A versioned schedule anchored to canonical genesis time."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = EPOCH_SCHEDULE_VERSION
    genesis_start_time: str = Field(min_length=1)
    epoch_duration_seconds: int = Field(gt=0)
    parameter_version: str = Field(min_length=1)
    task_set_version: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    schedule_hash: str

    @model_validator(mode="after")
    def validate_schedule(self) -> EpochSchedule:
        if self.schema_version != EPOCH_SCHEDULE_VERSION:
            raise ValueError("epoch schedule schema version is unsupported")
        _parse_timestamp(self.genesis_start_time, field_name="genesis_start_time")
        if self.schedule_hash != _schedule_hash(self.unsigned_payload()):
            raise ValueError("epoch schedule hash does not match payload")
        return self

    def unsigned_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"schedule_hash"})

    def boundary_for(
        self,
        *,
        active_epoch: int,
        active_start_time: str,
        block_time: str,
    ) -> EpochBoundary:
        if isinstance(active_epoch, bool) or active_epoch < 0:
            raise ValueError("active epoch is invalid")
        start = _parse_timestamp(active_start_time, field_name="active_start_time")
        current = _parse_timestamp(block_time, field_name="block_time")
        scheduled_end = start + timedelta(seconds=self.epoch_duration_seconds)
        reached = current >= scheduled_end
        return EpochBoundary(
            active_epoch=active_epoch,
            active_start_time=start.isoformat().replace("+00:00", "Z"),
            scheduled_end_time=scheduled_end.isoformat().replace("+00:00", "Z"),
            boundary_reached=reached,
            closing_epoch=active_epoch if reached else None,
            opening_epoch=active_epoch + 1 if reached else None,
        )


def build_epoch_schedule(
    *,
    genesis_start_time: str,
    epoch_duration_seconds: int,
    parameter_version: str,
    task_set_version: str,
    protocol_version: str,
) -> EpochSchedule:
    """Build a hash-bound schedule from governance/configuration inputs."""
    values: dict[str, object] = {
        "schema_version": EPOCH_SCHEDULE_VERSION,
        "genesis_start_time": genesis_start_time,
        "epoch_duration_seconds": epoch_duration_seconds,
        "parameter_version": parameter_version,
        "task_set_version": task_set_version,
        "protocol_version": protocol_version,
    }
    values["schedule_hash"] = _schedule_hash(values)
    return EpochSchedule.model_validate(values)


__all__ = [
    "EPOCH_SCHEDULE_VERSION",
    "EpochBoundary",
    "EpochSchedule",
    "build_epoch_schedule",
]
