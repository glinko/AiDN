"""Canonical, integer-only Endpoint pricing contracts."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aidn_hypervisor.accounting.models import (
    AccountingMode,
    UnavailableValuePolicy,
    UsageAuthority,
)

Q_ATOMS_PER_Q = 1_000_000

BillingDimension = Literal[
    "request_count",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "text_input_characters",
    "audio_input_milliseconds",
    "audio_output_milliseconds",
    "image_input_count",
    "image_output_count",
    "image_input_pixels",
    "image_output_pixels",
    "image_input_tokens",
    "image_output_tokens",
    "video_input_milliseconds",
    "video_output_milliseconds",
    "idle_milliseconds",
]
RateKind = Literal["fixed", "metered"]
RoundingMode = Literal["DOWN", "UP", "HALF_EVEN"]
RateQualifierValue = str | int | bool


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


class RateComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(min_length=1, max_length=128)
    dimension: BillingDimension
    kind: RateKind = "metered"
    unit_price_q_atoms: int = Field(ge=0)
    unit_divisor: int = Field(default=1, ge=1)
    source_value_scale: int = Field(default=1, ge=1)
    rounding: RoundingMode = "DOWN"
    accounting_mode: AccountingMode = "observable"
    measurement_source: str = Field(default="runtime_usage", min_length=1)
    verification_method: str = Field(default="usage_evidence", min_length=1)
    required_authority: UsageAuthority | None = None
    unavailable_value_policy: UnavailableValuePolicy = (
        "REQUEST_REJECTED_BEFORE_EXECUTION"
    )
    qualifiers: dict[str, RateQualifierValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_kind(self):
        if self.kind == "fixed":
            if self.dimension != "request_count":
                raise ValueError("fixed Rate components must use request_count")
            if self.unit_divisor != 1 or self.source_value_scale != 1:
                raise ValueError("fixed Rate components cannot scale or divide Usage")
            if self.accounting_mode != "fixed_price":
                raise ValueError("fixed Rate components require fixed_price accounting")
            if self.required_authority is not None:
                raise ValueError("fixed Rate components cannot require Usage authority")
        elif self.accounting_mode == "fixed_price":
            raise ValueError("metered Rate components cannot use fixed_price accounting")
        return self

    def identity(self) -> tuple[str, tuple[tuple[str, RateQualifierValue], ...]]:
        return self.dimension, tuple(sorted(self.qualifiers.items()))


class RateCardV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["pricing.v2"] = "pricing.v2"
    currency: Literal["Q_ATOM"] = "Q_ATOM"
    components: list[RateComponent] = Field(default_factory=list)
    minimum_charge_q_atoms: int = Field(default=0, ge=0)
    rate_card_hash: str | None = None

    @model_validator(mode="after")
    def _validate_and_hash(self):
        component_ids = [item.component_id for item in self.components]
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("Rate component IDs must be unique")
        identities = [item.identity() for item in self.components]
        if len(identities) != len(set(identities)):
            raise ValueError("Rate dimensions and qualifiers must be unique")
        payload = self.model_dump(mode="json", exclude={"rate_card_hash"})
        expected = _canonical_hash(payload)
        if self.rate_card_hash is None:
            self.rate_card_hash = expected
        elif self.rate_card_hash != expected:
            raise ValueError("rate_card_hash does not match canonical Rate Card")
        return self
