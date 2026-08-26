from typing import Literal

from pydantic import BaseModel, Field

from aidn_hypervisor.registry_models import RegistryPricing


class WalletQuoteRequest(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    fixed_request_count: int = Field(default=1, ge=0)
    audio_input_seconds: float | None = Field(default=None, ge=0.0)


class WalletQuoteCharges(BaseModel):
    input_q: float = Field(ge=0.0)
    output_q: float = Field(ge=0.0)
    fixed_q: float = Field(ge=0.0)
    audio_input_q: float | None = Field(default=None, ge=0.0)
    total_q: float = Field(ge=0.0)


class WalletQuote(BaseModel):
    pricing: RegistryPricing
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    fixed_request_count: int = Field(default=1, ge=0)
    audio_input_seconds: float | None = Field(default=None, ge=0.0)
    charges: WalletQuoteCharges


class WalletUsageMeasurement(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    fixed_request_count: int = Field(default=1, ge=0)
    audio_input_milliseconds: int | None = Field(default=None, ge=0)
    audio_input_seconds: float | None = Field(default=None, ge=0.0)
    audio_output_milliseconds: int | None = Field(default=None, ge=0)
    text_input_characters: int | None = Field(default=None, ge=0)
    input_bytes: int | None = Field(default=None, ge=0)
    input_media_type: str | None = Field(default=None, min_length=1)
    input_artifact_sha256: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    output_bytes: int | None = Field(default=None, ge=0)
    output_media_type: str | None = Field(default=None, min_length=1)
    output_artifact_sha256: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    measurement_kind: Literal["exact", "estimated"]
    measurement_source: str = Field(min_length=1)


class WalletUsageRecordRequest(WalletUsageMeasurement):
    owner_id: str
    allocation_id: str | None = None
    bundle_id: str
    workload_type: str
    measurement_kind: Literal["exact", "estimated"] = "exact"
    measurement_source: str = "manual"
    source: str = "manual"


class WalletAllocationReopenRequest(BaseModel):
    reason: str | None = Field(default=None, min_length=1)


class WalletAllocationDisputeRequest(BaseModel):
    reason: str = Field(min_length=1)


class WalletAllocationDisputeResolveRequest(BaseModel):
    resolution: Literal["accepted", "rejected", "withdrawn"]
    reason: str | None = Field(default=None, min_length=1)


class WalletAllocationHoldRequest(BaseModel):
    reason: str = Field(min_length=1)


class WalletAllocationReleaseRequest(BaseModel):
    reason: str = Field(min_length=1)
    target_status: Literal["grace", "closed"]


class WalletAllocationCorrectionRequest(BaseModel):
    reason: str = Field(min_length=1)
    effective_usage_total_q: float = Field(ge=0.0)
    annotations: dict = Field(default_factory=dict)
    resolution_note: str | None = None
    release_after_apply: bool = False
    release_target_status: Literal["grace", "closed"] | None = None


class WalletAllocationCorrectionEvent(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    correction_id: str
    allocation_event_id: str
    allocation_id: str
    owner_id: str
    node_id: str
    operator_id: str
    bundle_id: str
    workload_type: str
    occurred_at: str
    created_by: str
    reason: str
    base_usage_total_q: float = Field(ge=0.0)
    effective_usage_total_q_before: float = Field(ge=0.0)
    effective_usage_total_q_after: float = Field(ge=0.0)
    delta_q: float
    annotations: dict = Field(default_factory=dict)
    resolution_note: str | None = None


class WalletUsageEvent(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    owner_id: str
    node_id: str
    operator_id: str
    task_id: str | None = None
    allocation_id: str | None = None
    bundle_id: str
    workload_type: str
    measurement_kind: Literal["exact", "estimated"]
    measurement_source: str
    source: str
    occurred_at: str
    quote: WalletQuote


class WalletAllocationActivationEvent(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    allocation_id: str
    owner_id: str
    node_id: str
    operator_id: str
    bundle_id: str
    workload_type: str
    runtime_id: str | None = None
    endpoint: str | None = None
    activation_source: Literal["create", "pending_reconcile"]
    lease_seconds: int = Field(ge=1)
    occurred_at: str


class WalletAllocationDisputeEvent(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    dispute_id: str
    allocation_event_id: str
    allocation_id: str
    owner_id: str
    node_id: str
    operator_id: str
    bundle_id: str
    workload_type: str
    event_type: Literal["opened", "resolved"]
    occurred_at: str
    reason: str | None = None
    opened_by: str | None = None
    resolution: Literal["accepted", "rejected", "withdrawn"] | None = None
    resolution_reason: str | None = None


class WalletAllocationEvent(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    allocation_id: str
    owner_id: str
    node_id: str
    operator_id: str
    bundle_id: str
    workload_type: str
    status: Literal["released", "expired"]
    settlement_status: Literal["grace", "hold", "closed"]
    occurred_at: str
    hold_reason: str | None = None
    hold_source: Literal["manual", "dispute", "strict_accounting", "system"] | None = None
    hold_started_at: str | None = None
    hold_released_at: str | None = None
    grace_expires_at: str | None = None
    closed_at: str | None = None
    reopened_at: str | None = None
    reopen_reason: str | None = None
    reopen_count: int = Field(default=0, ge=0)
    dispute_id: str | None = None
    dispute_opened_at: str | None = None
    dispute_reason: str | None = None
    dispute_status: Literal["none", "open", "resolved"] = "none"
    dispute_opened_by: str | None = None
    dispute_resolved_at: str | None = None
    dispute_resolution: Literal["accepted", "rejected", "withdrawn"] | None = None
    dispute_resolution_reason: str | None = None
    usage_event_count: int = Field(ge=0)
    base_usage_total_q: float = Field(ge=0.0)
    effective_usage_total_q: float = Field(ge=0.0)
    correction_count: int = Field(default=0, ge=0)


class WalletSessionEvent(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    session_id: str
    endpoint_id: str
    owner_id: str
    provider_wallet: str
    node_id: str
    operator_id: str
    event_type: Literal["deposit_locked", "usage_charged", "settled"]
    occurred_at: str
    task_id: str | None = None
    status: str
    settlement_status: Literal["open", "closed"] = "open"
    locked_q: float = Field(ge=0.0)
    charged_q: float = Field(ge=0.0)
    refunded_q: float = Field(ge=0.0)
    remaining_q: float = Field(ge=0.0)
    usage_charged_q: float = Field(ge=0.0)
    idle_fee_charged_q: float = Field(ge=0.0)
    minimum_session_fee_q: float = Field(ge=0.0)
    network_fee_q: float = Field(ge=0.0)
    close_reason: str | None = None


class WalletLedgerEvent(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    stream: Literal[
        "usage",
        "session",
        "allocation",
        "allocation_activation",
        "allocation_dispute",
        "validation",
        "economics",
    ]
    stream_event_id: str
    stream_sequence_id: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    occurred_at: str
    owner_id: str
    node_id: str
    operator_id: str
    task_id: str | None = None
    allocation_id: str | None = None
    session_id: str | None = None
    endpoint_id: str | None = None
    bundle_id: str | None = None
    workload_type: str | None = None
    status: str | None = None
    settlement_status: str | None = None
    amount_q: float = Field(default=0.0, ge=0.0)
    payload: dict = Field(default_factory=dict)
