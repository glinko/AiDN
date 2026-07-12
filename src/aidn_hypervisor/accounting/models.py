from typing import Literal

from pydantic import BaseModel, Field

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
