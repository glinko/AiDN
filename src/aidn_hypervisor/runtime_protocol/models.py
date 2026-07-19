import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.accounting.models import UsageDimensionEvidence


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
UsageAckStatus = Literal[
    "ACCEPTED",
    "DUPLICATE",
    "REJECTED",
    "CONFLICT",
    "OUT_OF_SEQUENCE",
    "PENDING_REVIEW",
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


class RuntimeReadinessDimensions(BaseModel):
    process_ready: bool
    adapter_ready: bool
    provider_ready: bool
    model_ready: bool
    capability_ready: bool
    usage_reporting_ready: bool
    route_ready: bool
    recovery_ready: bool

    def is_ready(self) -> bool:
        return all(self.model_dump().values())


class RuntimeReady(BaseModel):
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    route_generation: int = Field(ge=1)
    operational_state: str = Field(min_length=1)
    readiness_dimensions: RuntimeReadinessDimensions
    capability_definition_hash: str = Field(min_length=1)
    supported_features: list[str] = Field(default_factory=list)
    usage_profile_hash: str | None = None
    health_reference: str | None = None
    capacity_reference: str | None = None
    ready_at: str = Field(min_length=1)
    runtime_signature: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_ready_dimensions(self):
        if self.operational_state == "READY" and not self.readiness_dimensions.is_ready():
            raise ValueError("READY Runtime requires every readiness dimension")
        return self


class RuntimeHealth(BaseModel):
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    route_generation: int = Field(ge=1)
    health_sequence: int = Field(ge=1)
    overall_state: str = Field(min_length=1)
    runtime_process_health: str = Field(min_length=1)
    adapter_health: str = Field(min_length=1)
    provider_health: str = Field(min_length=1)
    model_health: str = Field(min_length=1)
    capability_health: str = Field(min_length=1)
    resource_health: str = Field(min_length=1)
    usage_reporting_health: str = Field(min_length=1)
    recovery_health: str = Field(min_length=1)
    route_health: str = Field(min_length=1)
    observed_at: str = Field(min_length=1)
    valid_until: str = Field(min_length=1)
    diagnostic_references: list[str] = Field(default_factory=list)
    runtime_signature: str = Field(min_length=1)


class RuntimeCapacity(BaseModel):
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    route_generation: int = Field(ge=1)
    capacity_sequence: int = Field(ge=1)
    maximum_concurrent_requests: int = Field(ge=0)
    active_requests: int = Field(ge=0)
    queued_requests: int = Field(ge=0)
    maximum_queue_depth: int = Field(ge=0)
    maximum_active_sessions: int = Field(ge=0)
    active_sessions: int = Field(ge=0)
    maximum_input_size: int | None = Field(default=None, ge=0)
    maximum_output_size: int | None = Field(default=None, ge=0)
    maximum_artifact_size: int | None = Field(default=None, ge=0)
    temporary_capacity_factor: float = Field(default=1.0, ge=0.0)
    observed_at: str = Field(min_length=1)
    valid_until: str = Field(min_length=1)
    runtime_signature: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_capacity_bounds(self):
        if self.active_requests > self.maximum_concurrent_requests:
            raise ValueError("active_requests cannot exceed maximum_concurrent_requests")
        if self.queued_requests > self.maximum_queue_depth:
            raise ValueError("queued_requests cannot exceed maximum_queue_depth")
        if self.active_sessions > self.maximum_active_sessions:
            raise ValueError("active_sessions cannot exceed maximum_active_sessions")
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
    terminal_final_usage_report_id: str | None = None
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


class RuntimeCancelRequest(BaseModel):
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    route_generation: int = Field(ge=1)
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    cancellation_id: str = Field(min_length=1)
    cancellation_reason: str = Field(min_length=1)
    requested_terminal_state: Literal["CANCELLED"] = "CANCELLED"
    requested_at: str = Field(min_length=1)
    deadline: str = Field(min_length=1)
    authorization_reference: str | None = None
    hypervisor_signature: str = Field(min_length=1)
    cancellation_hash: str | None = None

    @model_validator(mode="after")
    def _validate_cancellation_hash(self):
        payload = self.model_dump(mode="json", exclude={"cancellation_hash"})
        expected = canonical_hash(payload)
        if self.cancellation_hash is None:
            self.cancellation_hash = expected
        elif self.cancellation_hash != expected:
            raise ValueError("cancellation_hash does not match Runtime Cancel Request")
        return self


class RuntimeCancellationRecord(BaseModel):
    cancellation: RuntimeCancelRequest
    request_state_before_cancel: RuntimeRequestState
    updated_at: str = Field(min_length=1)


class RuntimeCancelResult(BaseModel):
    cancellation_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    route_generation: int = Field(ge=1)
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    cancellation_state: Literal[
        "CANCELLED",
        "CANCELLATION_PENDING",
        "CANCELLATION_TOO_LATE",
        "CANCELLATION_UNSUPPORTED",
        "ALREADY_TERMINAL",
        "FAILED",
    ]
    provider_execution_state: str = Field(min_length=1)
    output_stopped: bool
    provider_confirmed_stopped: bool
    side_effect_state: str = Field(min_length=1)
    terminal_usage_report_id: str | None = None
    terminal_result_reference: str | None = None
    observed_at: str = Field(min_length=1)
    runtime_signature: str = Field(min_length=1)
    cancellation_result_hash: str | None = None

    @model_validator(mode="after")
    def _validate_cancellation_result(self):
        if self.cancellation_state == "CANCELLED" and not self.output_stopped:
            raise ValueError("confirmed cancellation requires output_stopped")
        if self.provider_confirmed_stopped and not self.output_stopped:
            raise ValueError("provider stop confirmation requires output_stopped")
        payload = self.model_dump(mode="json", exclude={"cancellation_result_hash"})
        expected = canonical_hash(payload)
        if self.cancellation_result_hash is None:
            self.cancellation_result_hash = expected
        elif self.cancellation_result_hash != expected:
            raise ValueError("cancellation_result_hash does not match Runtime Cancel Result")
        return self


class RuntimeResult(BaseModel):
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    route_generation: int = Field(ge=1)
    endpoint_id: str = Field(min_length=1)
    endpoint_configuration_hash: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    terminal_state: Literal[
        "COMPLETED",
        "PARTIAL",
        "CANCELLED",
        "FAILED",
        "EXPIRED",
        "UNRECOVERABLE",
    ]
    result_payload_hash: str | None = None
    result_payload: dict | None = None
    result_reference: str | None = None
    stream_roots: list[str] = Field(default_factory=list)
    artifact_references: list[dict] = Field(default_factory=list)
    state_reference: dict | None = None
    final_usage_report_id: str = Field(min_length=1)
    provider_attempt_count: int = Field(default=0, ge=0)
    completed_at: str = Field(min_length=1)
    runtime_signature: str = Field(min_length=1)
    result_hash: str | None = None

    @model_validator(mode="after")
    def _validate_result(self):
        if self.result_payload is not None:
            expected = canonical_hash(self.result_payload)
            if self.result_payload_hash is None:
                self.result_payload_hash = expected
            elif self.result_payload_hash != expected:
                raise ValueError("result_payload_hash does not match Result payload")
        elif self.result_payload_hash is not None:
            raise ValueError("result_payload_hash requires inline Result payload")
        if self.terminal_state in {"COMPLETED", "PARTIAL"} and not any(
            (
                self.result_payload is not None,
                self.result_reference is not None,
                self.stream_roots,
                self.artifact_references,
            )
        ):
            raise ValueError("successful Result requires output evidence")
        payload = self.model_dump(mode="json", exclude={"result_hash"})
        expected_hash = canonical_hash(payload)
        if self.result_hash is None:
            self.result_hash = expected_hash
        elif self.result_hash != expected_hash:
            raise ValueError("result_hash does not match Runtime Result")
        return self


class RuntimeUsageDimension(UsageDimensionEvidence):
    """RFC-0054 wire projection of the RFC-0051 Usage dimension."""


class RuntimeProviderAttempt(BaseModel):
    attempt_id: str = Field(min_length=1)
    provider_reference: str | None = None
    provider_model_reference: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    terminal_state: str = Field(min_length=1)
    usage_dimensions: list[RuntimeUsageDimension] = Field(default_factory=list)
    billable: bool = False
    retry_reason: str | None = None


class RuntimeUsageReport(BaseModel):
    usage_report_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    runtime_generation: int = Field(ge=1)
    runtime_configuration_hash: str = Field(min_length=1)
    endpoint_id: str = Field(min_length=1)
    endpoint_configuration_hash: str | None = None
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    accounting_contract_hash: str | None = None
    report_type: Literal[
        "INTERIM",
        "CHECKPOINT",
        "FINAL",
        "CORRECTION",
        "RECOVERY",
        "DIAGNOSTIC",
    ] = "INTERIM"
    usage_sequence: int = Field(ge=1)
    previous_usage_report_hash: str | None = None
    dimensions: list[RuntimeUsageDimension] = Field(default_factory=list)
    provider_attempts: list[RuntimeProviderAttempt] = Field(default_factory=list)
    provider_attempt_count: int = Field(default=0, ge=0)
    request_state: str | None = None
    cumulative: bool = True
    terminal: bool = False
    observed_from: str | None = None
    observed_to: str | None = None
    limitations: list[str] = Field(default_factory=list)
    created_at: str = Field(min_length=1)
    observed_at: str | None = None
    report_hash: str | None = None
    runtime_signature: str = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def _normalize_compatibility_fields(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        observed_at = normalized.get("observed_at")
        normalized.setdefault("created_at", observed_at)
        normalized.setdefault("observed_at", normalized.get("created_at"))
        attempts = normalized.get("provider_attempts")
        if isinstance(attempts, int):
            normalized["provider_attempt_count"] = attempts
            normalized["provider_attempts"] = []
        return normalized

    @model_validator(mode="after")
    def _validate_report_hash(self):
        terminal_states = {
            "COMPLETED",
            "PARTIAL",
            "CANCELLED",
            "FAILED",
            "EXPIRED",
            "UNRECOVERABLE",
        }
        if self.terminal:
            if self.report_type != "FINAL" or self.request_state not in terminal_states:
                raise ValueError("terminal Usage requires FINAL report and terminal Request state")
        elif self.report_type == "FINAL":
            raise ValueError("FINAL Usage Report must be terminal")
        if self.provider_attempt_count < len(self.provider_attempts):
            raise ValueError("provider_attempt_count cannot be less than attempt records")
        payload = self.model_dump(mode="json", exclude={"report_hash", "runtime_signature"})
        expected = canonical_hash(payload)
        if self.report_hash is None:
            self.report_hash = expected
        elif self.report_hash != expected:
            raise ValueError("report_hash does not match Runtime Usage Report")
        return self


class RuntimeUsageAck(BaseModel):
    usage_acknowledgment_id: str | None = None
    usage_report_id: str = Field(min_length=1)
    session_id: str | None = None
    request_id: str = Field(min_length=1)
    status: UsageAckStatus
    accepted_usage_sequence: int | None = Field(default=None, ge=1)
    accepted_report_hash: str | None = None
    rejection_code: str | None = None
    acknowledged_at: str = Field(min_length=1)
    hypervisor_signature: str | None = None

    @model_validator(mode="after")
    def _populate_acknowledgment_id(self):
        payload = self.model_dump(
            mode="json",
            exclude={"usage_acknowledgment_id", "hypervisor_signature"},
        )
        expected = canonical_hash(payload)
        if self.usage_acknowledgment_id is None:
            self.usage_acknowledgment_id = expected
        elif self.usage_acknowledgment_id != expected:
            raise ValueError("usage_acknowledgment_id does not match acknowledgment")
        return self


class RuntimeUsageConflict(BaseModel):
    conflict_id: str | None = None
    usage_report_id: str = Field(min_length=1)
    runtime_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    usage_sequence: int = Field(ge=1)
    accepted_report_hash: str | None = None
    conflicting_report_hash: str = Field(min_length=1)
    conflict_type: Literal["CONTENT", "SEQUENCE", "CHAIN"]
    observed_at: str = Field(min_length=1)

    @model_validator(mode="after")
    def _populate_conflict_id(self):
        payload = self.model_dump(mode="json", exclude={"conflict_id"})
        expected = canonical_hash(payload)
        if self.conflict_id is None:
            self.conflict_id = expected
        elif self.conflict_id != expected:
            raise ValueError("conflict_id does not match Usage conflict evidence")
        return self


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
