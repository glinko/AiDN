import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator


RuntimeConnectionState = Literal[
    "CONNECTING",
    "HELLO_EXCHANGING",
    "IDENTITY_VERIFYING",
    "VERSION_NEGOTIATING",
    "CONFIGURATION_VERIFYING",
    "STATE_RECONCILING",
    "READY",
    "REJECTED",
    "RECOVERING",
    "QUARANTINED",
    "DRAINING",
    "CLOSED",
]
RuntimeAdmissionState = Literal[
    "ACCEPTED",
    "QUEUED",
    "REJECTED",
    "BACKPRESSURED",
    "TEMPORARILY_UNAVAILABLE",
    "RECOVERY_REQUIRED",
]
RuntimeRequestState = Literal[
    "SUBMITTED",
    "ACCEPTED",
    "QUEUED",
    "EXECUTING",
    "COMPLETED",
    "PARTIAL",
    "CANCEL_REQUESTED",
    "CANCELLED",
    "FAILED",
    "EXPIRED",
    "RECOVERING",
    "UNRECOVERABLE",
]
UsageAuthority = Literal[
    "AUTHORITATIVE_PROVIDER",
    "DETERMINISTIC_LOCAL",
    "OBSERVABLE_LOCAL",
    "ESTIMATED",
    "UNAVAILABLE",
]
UsageAvailability = Literal["AVAILABLE", "UNAVAILABLE"]
UsageAckStatus = Literal[
    "ACCEPTED",
    "DUPLICATE",
    "REJECTED",
    "CONFLICT",
    "OUT_OF_SEQUENCE",
]


def canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class RuntimeHello(BaseModel):
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    instance_id: str = Field(min_length=1)
    runtime_configuration_hash: str = Field(min_length=1)
    capability_id: str = Field(min_length=1)
    supported_capability_versions: list[str] = Field(min_length=1)
    supported_definition_hashes: list[str] = Field(min_length=1)
    supported_runtime_protocol_versions: list[str] = Field(min_length=1)
    supported_runtime_features: list[str] = Field(default_factory=list)
    adapter_id: str | None = None
    adapter_version: str | None = None
    last_runtime_event_sequence: int = Field(default=0, ge=0)
    last_hypervisor_command_sequence: int = Field(default=0, ge=0)
    recovery_state_available: bool = False
    runtime_nonce: str = Field(min_length=1)
    runtime_challenge: str = Field(min_length=1)
    runtime_signature: str = Field(min_length=1)


class HypervisorRuntimeHello(BaseModel):
    handshake_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    accepted_runtime_generation: int = Field(ge=1)
    accepted_runtime_configuration_hash: str = Field(min_length=1)
    runtime_binding_hash: str = Field(min_length=1)
    selected_runtime_protocol_version: str = Field(min_length=1)
    selected_capability_version: str = Field(min_length=1)
    selected_capability_definition_hash: str = Field(min_length=1)
    route_generation: int = Field(ge=1)
    granted_route_scope: dict
    network_revision: str = Field(min_length=1)
    hypervisor_command_sequence: int = Field(ge=0)
    runtime_challenge_response: str = Field(min_length=1)
    hypervisor_challenge: str = Field(min_length=1)
    recovery_directive: Literal["NONE", "RECONCILE"]
    hypervisor_signature: str = Field(min_length=1)


class RuntimeHelloComplete(BaseModel):
    handshake_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    route_generation: int = Field(ge=1)
    hypervisor_challenge_response: str = Field(min_length=1)
    current_operational_state: str = Field(min_length=1)
    current_health_reference: str | None = None
    current_capacity_reference: str | None = None
    runtime_signature: str = Field(min_length=1)


class RuntimeConnection(BaseModel):
    runtime_connection_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    runtime_binding_hash: str = Field(min_length=1)
    instance_id: str = Field(min_length=1)
    route_generation: int = Field(ge=1)
    selected_runtime_protocol_version: str = Field(min_length=1)
    connection_state: RuntimeConnectionState
    established_at: str = Field(min_length=1)
    expires_at: str = Field(min_length=1)


class RuntimeMessage(BaseModel):
    runtime_message_id: str = Field(min_length=1)
    runtime_message_type: str = Field(min_length=1)
    runtime_message_version: str = "1.0"
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    route_generation: int = Field(ge=1)
    runtime_connection_id: str = Field(min_length=1)
    session_id: str | None = None
    request_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    runtime_sequence: int = Field(ge=1)
    created_at: str = Field(min_length=1)
    expiration: str = Field(min_length=1)
    payload_hash: str = Field(min_length=1)
    payload: dict
    authentication: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_payload_hash(self):
        if canonical_hash(self.payload) != self.payload_hash:
            raise ValueError("payload_hash does not match Runtime payload")
        return self


class RuntimeExecuteRequest(BaseModel):
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    route_generation: int = Field(ge=1)
    endpoint_id: str = Field(min_length=1)
    endpoint_configuration_hash: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    session_contract_hash: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    capability_id: str = Field(min_length=1)
    capability_version: str = Field(min_length=1)
    capability_definition_hash: str = Field(min_length=1)
    required_features: list[str] = Field(default_factory=list)
    optional_features: list[str] = Field(default_factory=list)
    request_payload_hash: str = Field(min_length=1)
    request_payload_encoding: str = "CANONICAL_JSON"
    request_payload: dict | None = None
    request_payload_reference: str | None = None
    state_reference: dict | None = None
    input_limits: dict = Field(default_factory=dict)
    output_limits: dict = Field(default_factory=dict)
    artifact_limits: dict = Field(default_factory=dict)
    request_charge_ceiling: float = Field(ge=0.0)
    accounting_contract_hash: str = Field(min_length=1)
    side_effect_authorizations: list[dict] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1)
    request_deadline: str = Field(min_length=1)
    trace_context: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_payload_location(self):
        locations = [self.request_payload is not None, self.request_payload_reference is not None]
        if sum(locations) != 1:
            raise ValueError("exactly one Request payload location is required")
        if self.request_payload is not None:
            if canonical_hash(self.request_payload) != self.request_payload_hash:
                raise ValueError("request_payload_hash does not match Request payload")
        return self

    def semantic_hash(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))


class RuntimeRequestRecord(BaseModel):
    request_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    route_generation: int = Field(ge=1)
    request_hash: str = Field(min_length=1)
    request: RuntimeExecuteRequest
    request_state: RuntimeRequestState
    admission_state: RuntimeAdmissionState | None = None
    runtime_request_handle: str | None = None
    accepted_at: str | None = None
    terminal_result_hash: str | None = None
    updated_at: str = Field(min_length=1)


class RuntimeRequestAccept(BaseModel):
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    route_generation: int = Field(ge=1)
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    admission_state: RuntimeAdmissionState
    runtime_request_handle: str | None = None
    accepted_capability_definition_hash: str = Field(min_length=1)
    accepted_features: list[str] = Field(default_factory=list)
    accepted_at: str = Field(min_length=1)
    queue_position: int | None = Field(default=None, ge=0)
    queue_estimate: float | None = Field(default=None, ge=0.0)
    progress_authority: str = "UNKNOWN"
    state_reference: dict | None = None
    diagnostic_reference: str | None = None


class RuntimeUsageDimension(BaseModel):
    dimension_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    value: int | float | str | None = None
    availability: UsageAvailability
    authority: UsageAuthority
    cumulative: bool = True
    billable_eligible: bool = False
    source_reference: str | None = None
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_availability(self):
        if self.availability == "UNAVAILABLE":
            if self.authority != "UNAVAILABLE" or self.value is not None:
                raise ValueError("unavailable Usage must have no value and UNAVAILABLE authority")
        elif self.authority == "UNAVAILABLE" or self.value is None:
            raise ValueError("available Usage requires a value and non-UNAVAILABLE authority")
        return self


class RuntimeUsageReport(BaseModel):
    usage_report_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    endpoint_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    usage_sequence: int = Field(ge=1)
    previous_usage_report_hash: str | None = None
    dimensions: list[RuntimeUsageDimension] = Field(default_factory=list)
    provider_attempts: int = Field(default=1, ge=0)
    cumulative: bool = True
    terminal: bool = False
    observed_at: str = Field(min_length=1)
    report_hash: str | None = None
    runtime_signature: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_report_hash(self):
        payload = self.model_dump(mode="json", exclude={"report_hash", "runtime_signature"})
        expected = canonical_hash(payload)
        if self.report_hash is None:
            self.report_hash = expected
        elif self.report_hash != expected:
            raise ValueError("report_hash does not match Runtime Usage Report")
        return self


class RuntimeUsageAck(BaseModel):
    usage_report_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    status: UsageAckStatus
    accepted_usage_sequence: int | None = Field(default=None, ge=1)
    accepted_report_hash: str | None = None
    rejection_code: str | None = None
    acknowledged_at: str = Field(min_length=1)


class RuntimeRecoveryState(BaseModel):
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    route_generation: int = Field(ge=1)
    instance_id: str = Field(min_length=1)
    active_requests: list[str] = Field(default_factory=list)
    terminal_requests: list[str] = Field(default_factory=list)
    recoverable_requests: list[dict] = Field(default_factory=list)
    unrecoverable_requests: list[str] = Field(default_factory=list)
    active_streams: list[dict] = Field(default_factory=list)
    usage_chain_heads: dict[str, str] = Field(default_factory=dict)
    state_references: list[dict] = Field(default_factory=list)
    artifact_references: list[dict] = Field(default_factory=list)
    last_runtime_event_sequence: int = Field(default=0, ge=0)
    last_hypervisor_command_sequence: int = Field(default=0, ge=0)
    recovery_state_hash: str | None = None

    @model_validator(mode="after")
    def _validate_state_hash(self):
        payload = self.model_dump(mode="json", exclude={"recovery_state_hash"})
        expected = canonical_hash(payload)
        if self.recovery_state_hash is None:
            self.recovery_state_hash = expected
        elif self.recovery_state_hash != expected:
            raise ValueError("recovery_state_hash does not match Runtime recovery state")
        return self


class RuntimeRecoveryPlan(BaseModel):
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    route_generation: int = Field(ge=1)
    plan_id: str = Field(min_length=1)
    request_directives: dict[str, str] = Field(default_factory=dict)
    stream_directives: dict[str, str] = Field(default_factory=dict)
    state_directives: dict[str, str] = Field(default_factory=dict)
    plan_hash: str | None = None
    issued_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_plan_hash(self):
        payload = self.model_dump(mode="json", exclude={"plan_hash"})
        expected = canonical_hash(payload)
        if self.plan_hash is None:
            self.plan_hash = expected
        elif self.plan_hash != expected:
            raise ValueError("plan_hash does not match Runtime Recovery Plan")
        return self


class RuntimeRecoveryResult(BaseModel):
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    route_generation: int = Field(ge=1)
    plan_id: str = Field(min_length=1)
    request_results: dict[str, str] = Field(default_factory=dict)
    stream_results: dict[str, str] = Field(default_factory=dict)
    state_results: dict[str, str] = Field(default_factory=dict)
    remaining_conflicts: list[str] = Field(default_factory=list)
    completed_at: str = Field(min_length=1)
    result_hash: str | None = None

    @model_validator(mode="after")
    def _validate_result_hash(self):
        payload = self.model_dump(mode="json", exclude={"result_hash"})
        expected = canonical_hash(payload)
        if self.result_hash is None:
            self.result_hash = expected
        elif self.result_hash != expected:
            raise ValueError("result_hash does not match Runtime Recovery Result")
        return self
