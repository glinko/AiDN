import json
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field, model_validator

AccountingMode = Literal[
    "deterministic",
    "observable",
    "provider_metered",
    "fixed_price",
    "proxy_opaque",
]
VerificationStatus = Literal[
    "verified",
    "accepted_unverified",
    "statistically_plausible",
    "mismatch",
    "unable_to_verify",
    "unable_to_verify_upstream_usage",
]
AccountingValue = int | float | str | bool | None


def _canonical_json(payload: BaseModel) -> str:
    return json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def usage_report_hash(report: "UsageReport") -> str:
    return f"sha256:{sha256(_canonical_json(report).encode('utf-8')).hexdigest()}"


def usage_acknowledgement_hash(ack: "UsageAcknowledgement") -> str:
    return f"sha256:{sha256(_canonical_json(ack).encode('utf-8')).hexdigest()}"


class AccountingUnitContract(BaseModel):
    unit: str = Field(min_length=1)
    mode: AccountingMode
    price: float = Field(ge=0.0)
    measurement_source: str = Field(min_length=1)
    verification_method: str = Field(min_length=1)
    tolerance: str | None = None
    rounding: str | None = None


class AccountingContract(BaseModel):
    contract_version: str = Field(min_length=1)
    capability_id: str | None = None
    pricing_version: str = Field(min_length=1)
    billable_units: list[AccountingUnitContract] = Field(default_factory=list)
    checkpoint_policy: str = Field(min_length=1)
    maximum_unreported_usage: float | None = Field(default=None, ge=0.0)
    maximum_request_charge: float | None = Field(default=None, ge=0.0)
    failure_pricing_policy: str = Field(
        default="reject_unpriced_usage",
        min_length=1,
    )


class UsageReport(BaseModel):
    report_id: str = Field(min_length=1)
    report_version: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    endpoint_id: str = Field(min_length=1)
    capability_id: str | None = None
    pricing_version: str = Field(min_length=1)
    accounting_contract_version: str = Field(min_length=1)
    accounting_modes: dict[str, AccountingMode] = Field(default_factory=dict)
    sequence: int = Field(ge=1)
    cumulative_usage: dict[str, AccountingValue] = Field(default_factory=dict)
    request_usage: list[dict] = Field(default_factory=list)
    measurement_sources: dict[str, str] = Field(default_factory=dict)
    estimated_usage: dict[str, AccountingValue] = Field(default_factory=dict)
    previous_report_hash: str | None = None
    created_at: str = Field(min_length=1)
    signature: str = Field(min_length=1)


class UsageAcknowledgement(BaseModel):
    session_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    provider_report_hash: str = Field(min_length=1)
    verification_status: VerificationStatus
    consumer_measurements: dict[str, AccountingValue] = Field(default_factory=dict)
    observations: dict[str, AccountingValue] = Field(default_factory=dict)
    signature: str = Field(min_length=1)


class SessionAccountingCheckpoint(BaseModel):
    last_report_sequence: int | None = Field(default=None, ge=1)
    last_report_hash: str | None = None
    last_ack_sequence: int | None = Field(default=None, ge=1)
    last_ack_hash: str | None = None
    last_accepted_report_sequence: int | None = Field(default=None, ge=1)
    last_accepted_report_hash: str | None = None
    last_accepted_usage_charged_q: float = Field(default=0.0, ge=0.0)
    mismatch_open: bool = False
    ack_deadline_at: str | None = None

    @model_validator(mode="after")
    def _validate_checkpoint(self):
        if self.last_report_hash is not None and self.last_report_sequence is None:
            raise ValueError("last_report_hash requires last_report_sequence")
        if self.last_accepted_report_hash is not None and self.last_accepted_report_sequence is None:
            raise ValueError("last_accepted_report_hash requires last_accepted_report_sequence")
        if self.last_ack_hash is not None and self.last_ack_sequence is None:
            raise ValueError("last_ack_hash requires last_ack_sequence")
        if (
            self.last_report_sequence is not None
            and self.last_accepted_report_sequence is not None
            and self.last_accepted_report_sequence > self.last_report_sequence
        ):
            raise ValueError("last_accepted_report_sequence cannot exceed last_report_sequence")
        if (
            self.last_report_sequence is not None
            and self.last_ack_sequence is not None
            and self.last_ack_sequence > self.last_report_sequence
        ):
            raise ValueError("last_ack_sequence cannot exceed last_report_sequence")
        return self
