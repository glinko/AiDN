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
    "hybrid",
]
UsageAvailability = Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE", "NOT_APPLICABLE"]
UsageAuthority = Literal[
    "AUTHORITATIVE_PROVIDER",
    "DETERMINISTIC_LOCAL",
    "OBSERVABLE_LOCAL",
    "ESTIMATED",
]
UnavailableValuePolicy = Literal[
    "REQUEST_REJECTED_BEFORE_EXECUTION",
    "FIXED_FALLBACK",
    "OBSERVABLE_FALLBACK",
    "PARTIAL_CHARGE",
    "ZERO_VARIABLE_COMPONENT",
    "FORCED_SETTLEMENT_REVIEW",
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


def _canonical_dict_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _hash_dict(payload: dict) -> str:
    return f"sha256:{sha256(_canonical_dict_json(payload).encode('utf-8')).hexdigest()}"


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
    required_authority: UsageAuthority | None = None
    unavailable_value_policy: UnavailableValuePolicy | None = None


class UsageSourceReference(BaseModel):
    source_type: Literal[
        "PROVIDER_USAGE_RESPONSE",
        "LOCAL_METER",
        "TOKENIZER",
        "RUNTIME_COUNTER",
        "HYPERVISOR_OBSERVATION",
        "ARTIFACT_MANIFEST",
        "STATISTICAL_ESTIMATE",
    ]
    source_id: str = Field(min_length=1)
    source_version: str | None = None
    source_hash: str | None = None
    observation_boundary: str | None = None


class UsageDimensionEvidence(BaseModel):
    dimension_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    availability: UsageAvailability
    authority: UsageAuthority | None = None
    value: AccountingValue = None
    cumulative: bool = True
    billing_eligible: bool = False
    source_reference: UsageSourceReference | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_measurement(self):
        if self.availability in {"UNAVAILABLE", "NOT_APPLICABLE"}:
            if self.value is not None or self.authority is not None:
                raise ValueError(
                    "unavailable or not-applicable Usage has no value or authority"
                )
        elif self.value is None or self.authority is None:
            raise ValueError("available or partial Usage requires value and authority")
        if self.authority == "AUTHORITATIVE_PROVIDER" and (
            self.source_reference is None
            or self.source_reference.source_type != "PROVIDER_USAGE_RESPONSE"
        ):
            raise ValueError(
                "AUTHORITATIVE_PROVIDER Usage requires Provider usage source"
            )
        return self


class RuntimeUsageProfileDimension(BaseModel):
    dimension_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    expected_availability: UsageAvailability
    authority: UsageAuthority | None = None
    cumulative: bool = True
    request_scoped: bool = True
    session_scoped: bool = False
    billing_eligible: bool = False
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_expected_authority(self):
        if self.expected_availability in {"UNAVAILABLE", "NOT_APPLICABLE"}:
            if self.authority is not None:
                raise ValueError("unavailable profile dimension has no authority")
        elif self.authority is None:
            raise ValueError("available profile dimension requires authority")
        return self


class RuntimeUsageProfile(BaseModel):
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    adapter_version: str | None = None
    dimensions: list[RuntimeUsageProfileDimension] = Field(default_factory=list)
    provider_attempt_reporting: bool = True
    retry_reporting: bool = True
    profile_version: str = Field(default="usage-profile.v1", min_length=1)
    profile_hash: str | None = None

    @model_validator(mode="after")
    def _populate_profile_hash(self):
        # The Runtime Configuration commits to this hash. Excluding the explicit
        # back-reference avoids an impossible Configuration/Profile hash cycle.
        payload = self.model_dump(
            mode="json",
            exclude={"profile_hash", "runtime_configuration_hash"},
        )
        expected = _hash_dict(payload)
        if self.profile_hash is None:
            self.profile_hash = expected
        elif self.profile_hash != expected:
            raise ValueError("profile_hash does not match Runtime Usage Profile")
        return self

    def dimension(self, dimension_id: str) -> RuntimeUsageProfileDimension | None:
        return next(
            (item for item in self.dimensions if item.dimension_id == dimension_id),
            None,
        )


class AccountingContract(BaseModel):
    accounting_contract_id: str | None = None
    accounting_mode: AccountingMode | None = None
    contract_version: str = Field(min_length=1)
    capability_id: str | None = None
    endpoint_id: str | None = None
    advertisement_id: str | None = None
    pricing_version: str = Field(min_length=1)
    pricing_policy_reference: str | None = None
    billable_units: list[AccountingUnitContract] = Field(default_factory=list)
    checkpoint_policy: str = Field(min_length=1)
    maximum_unreported_usage: float | None = Field(default=None, ge=0.0)
    maximum_request_charge: float | None = Field(default=None, ge=0.0)
    failure_pricing_policy: str = Field(
        default="reject_unpriced_usage",
        min_length=1,
    )
    unavailable_value_policy: UnavailableValuePolicy = (
        "REQUEST_REJECTED_BEFORE_EXECUTION"
    )
    partial_value_policy: str = "REQUIRE_EXPLICIT_CONTRACT_RULE"
    retry_policy: str = "UNDECLARED_RETRIES_NON_BILLABLE"
    cancellation_policy: str = "CHARGE_ACCEPTED_USAGE_TO_TERMINAL_BOUNDARY"
    maximum_session_charge: float | None = Field(default=None, ge=0.0)
    registry_object_id: str | None = None
    registry_object_version: str = "acctobj.v1"
    registry_namespace: str = "usage"
    payload_hash: str | None = None
    payload_encoding: str = "canonical_json"

    @model_validator(mode="after")
    def _populate_registry_object_metadata(self):
        payload = {
            "accounting_mode": self.accounting_mode,
            "contract_version": self.contract_version,
            "capability_id": self.capability_id,
            "endpoint_id": self.endpoint_id,
            "advertisement_id": self.advertisement_id,
            "pricing_version": self.pricing_version,
            "pricing_policy_reference": self.pricing_policy_reference,
            "billable_units": [
                unit.model_dump(mode="json") for unit in self.billable_units
            ],
            "checkpoint_policy": self.checkpoint_policy,
            "maximum_unreported_usage": self.maximum_unreported_usage,
            "maximum_request_charge": self.maximum_request_charge,
            "failure_pricing_policy": self.failure_pricing_policy,
            "unavailable_value_policy": self.unavailable_value_policy,
            "partial_value_policy": self.partial_value_policy,
            "retry_policy": self.retry_policy,
            "cancellation_policy": self.cancellation_policy,
            "maximum_session_charge": self.maximum_session_charge,
        }
        expected_payload_hash = _hash_dict(payload)
        object_identity_payload = {
            "object_type": "accounting_contract",
            "registry_object_version": self.registry_object_version,
            "payload_hash": expected_payload_hash,
        }
        expected_registry_object_id = _hash_dict(object_identity_payload)
        if self.payload_encoding != "canonical_json":
            raise ValueError("payload_encoding must be canonical_json")
        if self.payload_hash is None:
            self.payload_hash = expected_payload_hash
        elif self.payload_hash != expected_payload_hash:
            raise ValueError("payload_hash does not match canonical accounting contract payload")
        if self.registry_object_id is None:
            self.registry_object_id = expected_registry_object_id
        elif self.registry_object_id != expected_registry_object_id:
            raise ValueError(
                "registry_object_id does not match canonical accounting contract identity"
            )
        if self.accounting_contract_id is None:
            self.accounting_contract_id = self.registry_object_id
        return self

    def compatibility_errors(self, profile: RuntimeUsageProfile) -> list[str]:
        errors: list[str] = []
        for unit in self.billable_units:
            if unit.mode == "fixed_price":
                continue
            dimension = profile.dimension(unit.unit)
            policy = unit.unavailable_value_policy or self.unavailable_value_policy
            if dimension is None:
                if policy == "REQUEST_REJECTED_BEFORE_EXECUTION":
                    errors.append(f"required Usage dimension is undeclared: {unit.unit}")
                continue
            if (
                dimension.expected_availability in {"UNAVAILABLE", "NOT_APPLICABLE"}
                and policy == "REQUEST_REJECTED_BEFORE_EXECUTION"
            ):
                errors.append(f"required Usage dimension is unavailable: {unit.unit}")
            if (
                unit.required_authority is not None
                and dimension.authority != unit.required_authority
            ):
                errors.append(f"Usage authority mismatch: {unit.unit}")
        return errors

    def calculate_charge(
        self,
        dimensions: list[UsageDimensionEvidence],
        *,
        request_charge_ceiling: float,
    ) -> float:
        by_id = {item.dimension_id: item for item in dimensions}
        charge = 0.0
        for unit in self.billable_units:
            if unit.mode == "fixed_price":
                charge += unit.price
                continue
            dimension = by_id.get(unit.unit)
            policy = unit.unavailable_value_policy or self.unavailable_value_policy
            if dimension is None or dimension.availability in {
                "UNAVAILABLE",
                "NOT_APPLICABLE",
            }:
                if policy == "ZERO_VARIABLE_COMPONENT":
                    continue
                raise ValueError(f"required Usage dimension is unavailable: {unit.unit}")
            if dimension.availability == "PARTIAL" and self.partial_value_policy == (
                "REQUIRE_EXPLICIT_CONTRACT_RULE"
            ):
                raise ValueError(f"partial Usage has no accounting rule: {unit.unit}")
            if not dimension.billing_eligible:
                raise ValueError(f"Usage dimension is not billing eligible: {unit.unit}")
            if not isinstance(dimension.value, (int, float)) or isinstance(
                dimension.value, bool
            ):
                raise ValueError(f"Usage dimension is not numeric: {unit.unit}")
            charge += float(dimension.value) * unit.price
        maximum = request_charge_ceiling
        if self.maximum_request_charge is not None:
            maximum = min(maximum, self.maximum_request_charge)
        if charge > maximum:
            raise ValueError("calculated charge exceeds Request Charge Ceiling")
        return charge


class UsageCheckpoint(BaseModel):
    checkpoint_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    usage_report_id: str = Field(min_length=1)
    usage_report_hash: str = Field(min_length=1)
    usage_sequence: int = Field(ge=1)
    calculated_charge: float = Field(ge=0.0)
    current_session_exposure: float = Field(ge=0.0)
    remaining_deposit: float = Field(ge=0.0)
    accounting_contract_hash: str = Field(min_length=1)
    checkpoint_sequence: int = Field(ge=1)
    created_at: str = Field(min_length=1)
    provider_signature: str = Field(min_length=1)


class UsageCorrection(BaseModel):
    correction_id: str = Field(min_length=1)
    corrected_usage_report_id: str = Field(min_length=1)
    correction_reason: str = Field(min_length=1)
    corrected_dimensions: list[UsageDimensionEvidence]
    previous_chain_head: str = Field(min_length=1)
    resulting_chain_head: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    authorized_signature: str = Field(min_length=1)


class UsageDispute(BaseModel):
    dispute_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    disputed_usage_report_ids: list[str] = Field(default_factory=list)
    disputed_checkpoint_ids: list[str] = Field(default_factory=list)
    dispute_class: Literal[
        "DIMENSION_VALUE",
        "DIMENSION_AUTHORITY",
        "MISSING_USAGE",
        "DUPLICATE_USAGE",
        "RETRY_BILLING",
        "FAILURE_BILLING",
        "CANCELLATION_BILLING",
        "ACCOUNTING_CONTRACT",
        "CHARGE_CEILING",
        "USAGE_CHAIN_CONFLICT",
    ]
    claimed_error: str = Field(min_length=1)
    evidence_references: list[str] = Field(default_factory=list)
    opened_at: str = Field(min_length=1)
    claimant_signature: str = Field(min_length=1)


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
    last_report_id: str | None = None
    last_report_sequence: int | None = Field(default=None, ge=1)
    last_report_hash: str | None = None
    last_ack_sequence: int | None = Field(default=None, ge=1)
    last_ack_hash: str | None = None
    last_accepted_report_sequence: int | None = Field(default=None, ge=1)
    last_accepted_report_id: str | None = None
    last_accepted_report_hash: str | None = None
    accounting_contract_hash: str | None = None
    last_accepted_usage_charged_q: float = Field(default=0.0, ge=0.0)
    mismatch_open: bool = False
    ack_deadline_at: str | None = None

    @model_validator(mode="after")
    def _validate_checkpoint(self):
        if self.last_report_hash is not None and self.last_report_sequence is None:
            raise ValueError("last_report_hash requires last_report_sequence")
        if self.last_report_id is not None and self.last_report_sequence is None:
            raise ValueError("last_report_id requires last_report_sequence")
        if self.last_accepted_report_hash is not None and self.last_accepted_report_sequence is None:
            raise ValueError("last_accepted_report_hash requires last_accepted_report_sequence")
        if (
            self.last_accepted_report_id is not None
            and self.last_accepted_report_sequence is None
        ):
            raise ValueError("last_accepted_report_id requires last_accepted_report_sequence")
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
