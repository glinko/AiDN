from pydantic import BaseModel, Field

from aidn_hypervisor.domain.models import AllocationRequest, TaskRequest
from aidn_hypervisor.domain.types import TaskStatus
from aidn_hypervisor.endpoints.state import (
    EndpointConfigurationSnapshotRecord,
    EndpointManifestSnapshot,
)
from aidn_hypervisor.wallet_models import WalletQuote


class TaskSnapshot(BaseModel):
    task_id: str
    priority: int
    enqueue_index: int
    created_at: str
    status: TaskStatus
    request: TaskRequest
    bundle_id: str | None = None
    result: dict | None = None
    recovery_reason: str | None = None


class RuntimeSnapshot(BaseModel):
    runtime_id: str
    command: list[str]
    status: str
    bundle_id: str | None = None
    health_status: str = "unknown"
    last_error: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class BundleStateSnapshot(BaseModel):
    bundle_id: str
    failure_streak: int = 0
    cooldown_until: float | None = None
    cooldown_reason: str | None = None
    drain_mode: bool = False
    drain_reason: str | None = None


class JournalEvent(BaseModel):
    timestamp: str
    event_type: str
    message: str
    task_id: str | None = None
    bundle_id: str | None = None
    runtime_id: str | None = None
    details: dict = Field(default_factory=dict)


class AllocationSnapshot(BaseModel):
    allocation_id: str
    request: AllocationRequest
    bundle_id: str
    runtime_id: str | None = None
    endpoint: str | None = None
    status: str
    created_at: str
    expires_at: str
    reservation_id: str | None = None
    reason: str | None = None


class ModelInstallSnapshot(BaseModel):
    install_id: str
    provider_type: str
    model_id: str
    source_url: str
    target_path: str
    requested_by: str
    status: str
    bundle_id: str | None = None
    last_error: str | None = None


class WalletUsageSnapshot(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    owner_id: str
    node_id: str
    operator_id: str
    task_id: str | None = None
    allocation_id: str | None = None
    bundle_id: str
    workload_type: str
    measurement_kind: str
    measurement_source: str
    source: str
    occurred_at: str
    quote: WalletQuote


class WalletAllocationSnapshot(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    allocation_id: str
    owner_id: str
    node_id: str
    operator_id: str
    bundle_id: str
    workload_type: str
    status: str
    settlement_status: str
    occurred_at: str
    grace_expires_at: str | None = None
    closed_at: str | None = None
    reopened_at: str | None = None
    reopen_reason: str | None = None
    reopen_count: int = Field(default=0, ge=0)
    dispute_id: str | None = None
    dispute_opened_at: str | None = None
    dispute_reason: str | None = None
    dispute_status: str = "none"
    dispute_opened_by: str | None = None
    dispute_resolved_at: str | None = None
    dispute_resolution: str | None = None
    dispute_resolution_reason: str | None = None
    usage_event_count: int = Field(ge=0)
    usage_total_q: float = Field(ge=0.0)


class WalletAllocationActivationSnapshot(BaseModel):
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
    activation_source: str
    lease_seconds: int = Field(ge=1)
    occurred_at: str


class WalletAllocationDisputeSnapshot(BaseModel):
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
    event_type: str
    occurred_at: str
    reason: str | None = None
    opened_by: str | None = None
    resolution: str | None = None
    resolution_reason: str | None = None


class HypervisorStateSnapshot(BaseModel):
    tasks: list[TaskSnapshot] = Field(default_factory=list)
    runtimes: list[RuntimeSnapshot] = Field(default_factory=list)
    bundle_states: list[BundleStateSnapshot] = Field(default_factory=list)
    allocations: list[AllocationSnapshot] = Field(default_factory=list)
    model_installs: list[ModelInstallSnapshot] = Field(default_factory=list)
    endpoints: list[EndpointManifestSnapshot] = Field(default_factory=list)
    endpoint_configuration_snapshots: list[EndpointConfigurationSnapshotRecord] = Field(
        default_factory=list
    )
    operator_requests_policy: dict[str, bool | str] = Field(
        default_factory=lambda: {
            "allow_spillover": False,
            "dispatch_strategy": "local_first",
            "ready_endpoint_only": True,
        }
    )
    wallet_usage_events: list[WalletUsageSnapshot] = Field(default_factory=list)
    wallet_allocation_events: list[WalletAllocationSnapshot] = Field(default_factory=list)
    wallet_allocation_activation_events: list[WalletAllocationActivationSnapshot] = Field(
        default_factory=list
    )
    wallet_allocation_dispute_events: list[WalletAllocationDisputeSnapshot] = Field(
        default_factory=list
    )
    events: list[JournalEvent] = Field(default_factory=list)
