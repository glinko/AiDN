from pydantic import BaseModel, Field

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.dispatcher.models import (
    DeadLetterRecord,
    DeliveryRecord,
    DispatcherReplayRecord,
    DispatcherRoute,
    NetworkMessage,
)
from aidn_hypervisor.domain.models import AllocationRequest, TaskRequest
from aidn_hypervisor.domain.types import TaskStatus
from aidn_hypervisor.economics.models import (
    EpochRewardBudget,
    FaucetClaim,
    RecyclableRemoval,
)
from aidn_hypervisor.endpoint_publications.models import PublishedEndpointConfiguration
from aidn_hypervisor.endpoints.state import (
    EndpointConfigurationSnapshotRecord,
    EndpointManifestSnapshot,
)
from aidn_hypervisor.ledger.models import LedgerOperationRecord
from aidn_hypervisor.plugins.host import PluginHostConnection
from aidn_hypervisor.providers.models import (
    InstalledPlugin,
    ModelDeployment,
    PluginRelease,
    ProviderArtifactMaterialization,
    ProviderInstallationApproval,
    ProviderInstallationJob,
    ProviderInstance,
    RuntimeBinding,
)
from aidn_hypervisor.remote_endpoints.models import RemoteEndpointReference
from aidn_hypervisor.runtime_protocol.models import (
    RuntimeArtifactDeclare,
    RuntimeCancellationRecord,
    RuntimeCancelResult,
    RuntimeCapacity,
    RuntimeConnection,
    RuntimeDrainComplete,
    RuntimeDrainRequest,
    RuntimeDrainStatus,
    RuntimeHealth,
    RuntimeMessage,
    RuntimeReady,
    RuntimeRecoveryPlan,
    RuntimeRecoveryResult,
    RuntimeRecoveryState,
    RuntimeRequestRecord,
    RuntimeResult,
    RuntimeShutdown,
    RuntimeStateCheckpoint,
    RuntimeStreamChunk,
    RuntimeStreamClose,
    RuntimeStreamOpen,
    RuntimeUsageAck,
    RuntimeUsageConflict,
    RuntimeUsageReport,
)
from aidn_hypervisor.session_failure.models import (
    FailureEvidenceRecord,
    FailureReport,
)
from aidn_hypervisor.sessions.models import (
    EndpointSession,
    LockedDeposit,
    ProxySessionBinding,
)
from aidn_hypervisor.settlement.models import (
    SessionFundingAccount,
    SessionSettlementAcceptance,
    SessionSettlementProposal,
    SessionUsageCheckpoint,
    SettlementCorrection,
    SettlementDispute,
)
from aidn_hypervisor.validation.models import (
    ValidationAssignment,
    ValidationAuthorization,
    ValidationBond,
    ValidationEpoch,
    ValidationReport,
    ValidationReportCommitment,
    ValidationReportCustodyChallenge,
    ValidationReportCustodyCheckTask,
    ValidationReportCustodyObject,
    ValidationReportCustodyRetirement,
    ValidationReportCustodyState,
    ValidationReportStorageFailure,
    ValidationReportStorageReceipt,
    ValidationReportTransferReplay,
    ValidationRequest,
    ValidationStatusSnapshot,
    ValidationValidatorEntry,
    ValidationValidatorKeyBinding,
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
    hold_reason: str | None = None
    hold_source: str | None = None
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
    dispute_status: str = "none"
    dispute_opened_by: str | None = None
    dispute_resolved_at: str | None = None
    dispute_resolution: str | None = None
    dispute_resolution_reason: str | None = None
    usage_event_count: int = Field(ge=0)
    base_usage_total_q: float = Field(ge=0.0)
    effective_usage_total_q: float = Field(ge=0.0)
    correction_count: int = Field(default=0, ge=0)


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


class WalletAllocationCorrectionSnapshot(BaseModel):
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


class WalletSessionSnapshot(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    session_id: str
    endpoint_id: str
    owner_id: str
    provider_wallet: str
    node_id: str
    operator_id: str
    event_type: str
    occurred_at: str
    task_id: str | None = None
    status: str
    settlement_status: str = "open"
    locked_q: float = Field(ge=0.0)
    charged_q: float = Field(ge=0.0)
    refunded_q: float = Field(ge=0.0)
    remaining_q: float = Field(ge=0.0)
    usage_charged_q: float = Field(ge=0.0)
    idle_fee_charged_q: float = Field(ge=0.0)
    minimum_session_fee_q: float = Field(ge=0.0)
    network_fee_q: float = Field(ge=0.0)
    close_reason: str | None = None


class WalletLedgerSnapshot(BaseModel):
    sequence_id: int = Field(ge=1)
    event_id: str
    stream: str
    stream_event_id: str
    stream_sequence_id: int = Field(ge=1)
    event_type: str
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


class OwnerWalletSnapshot(BaseModel):
    wallet_id: str
    public_key: str
    private_key: str
    label: str | None = None
    created_at: str
    imported: bool = False


class OperatorOnboardingStepSnapshot(BaseModel):
    key: str
    status: str
    label: str
    workspace: str
    completed_at: str | None = None


class OperatorOnboardingSnapshot(BaseModel):
    completed: bool = False
    completed_at: str | None = None
    completed_via: str | None = None
    current_step: str = "configure_wallet"
    last_workspace: str = "home"
    transition_history: list[str] = Field(default_factory=list)
    steps: list[OperatorOnboardingStepSnapshot] = Field(default_factory=list)


class EndpointSessionSnapshot(EndpointSession):
    pass


class LockedDepositSnapshot(LockedDeposit):
    pass


class ProxySessionBindingSnapshot(ProxySessionBinding):
    pass


class HypervisorStateSnapshot(BaseModel):
    tasks: list[TaskSnapshot] = Field(default_factory=list)
    runtimes: list[RuntimeSnapshot] = Field(default_factory=list)
    bundle_states: list[BundleStateSnapshot] = Field(default_factory=list)
    allocations: list[AllocationSnapshot] = Field(default_factory=list)
    model_installs: list[ModelInstallSnapshot] = Field(default_factory=list)
    plugin_releases: list[PluginRelease] = Field(default_factory=list)
    installed_plugins: list[InstalledPlugin] = Field(default_factory=list)
    provider_instances: list[ProviderInstance] = Field(default_factory=list)
    model_deployments: list[ModelDeployment] = Field(default_factory=list)
    runtime_bindings: list[RuntimeBinding] = Field(default_factory=list)
    provider_artifact_materializations: list[ProviderArtifactMaterialization] = Field(default_factory=list)
    provider_installation_approvals: list[ProviderInstallationApproval] = Field(default_factory=list)
    provider_installation_jobs: list[ProviderInstallationJob] = Field(default_factory=list)
    plugin_host_connections: list[PluginHostConnection] = Field(default_factory=list)
    dispatcher_routes: list[DispatcherRoute] = Field(default_factory=list)
    dispatcher_queued_messages: list[NetworkMessage] = Field(default_factory=list)
    dispatcher_delivery_records: list[DeliveryRecord] = Field(default_factory=list)
    dispatcher_replay_records: list[DispatcherReplayRecord] = Field(default_factory=list)
    dispatcher_dead_letters: list[DeadLetterRecord] = Field(default_factory=list)
    runtime_protocol_connections: list[RuntimeConnection] = Field(default_factory=list)
    runtime_protocol_ready_states: list[RuntimeReady] = Field(default_factory=list)
    runtime_protocol_health_records: list[RuntimeHealth] = Field(default_factory=list)
    runtime_protocol_capacity_records: list[RuntimeCapacity] = Field(default_factory=list)
    runtime_protocol_messages: list[RuntimeMessage] = Field(default_factory=list)
    runtime_protocol_sequences: dict[str, int] = Field(default_factory=dict)
    runtime_protocol_requests: list[RuntimeRequestRecord] = Field(default_factory=list)
    runtime_protocol_cancellations: list[RuntimeCancellationRecord] = Field(default_factory=list)
    runtime_protocol_cancellation_results: list[RuntimeCancelResult] = Field(default_factory=list)
    runtime_protocol_results: list[RuntimeResult] = Field(default_factory=list)
    runtime_protocol_streams: list[RuntimeStreamOpen] = Field(default_factory=list)
    runtime_protocol_stream_chunks: list[RuntimeStreamChunk] = Field(default_factory=list)
    runtime_protocol_stream_closes: list[RuntimeStreamClose] = Field(default_factory=list)
    runtime_protocol_artifacts: list[RuntimeArtifactDeclare] = Field(default_factory=list)
    runtime_protocol_state_checkpoints: list[RuntimeStateCheckpoint] = Field(default_factory=list)
    runtime_protocol_recovery_states: list[RuntimeRecoveryState] = Field(default_factory=list)
    runtime_protocol_usage_reports: list[RuntimeUsageReport] = Field(default_factory=list)
    runtime_protocol_usage_acks: list[RuntimeUsageAck] = Field(default_factory=list)
    runtime_protocol_usage_conflicts: list[RuntimeUsageConflict] = Field(default_factory=list)
    runtime_protocol_recovery_plans: list[RuntimeRecoveryPlan] = Field(default_factory=list)
    runtime_protocol_recovery_results: list[RuntimeRecoveryResult] = Field(default_factory=list)
    runtime_protocol_drain_requests: list[RuntimeDrainRequest] = Field(default_factory=list)
    runtime_protocol_drain_statuses: list[RuntimeDrainStatus] = Field(default_factory=list)
    runtime_protocol_drain_completes: list[RuntimeDrainComplete] = Field(default_factory=list)
    runtime_protocol_shutdowns: list[RuntimeShutdown] = Field(default_factory=list)
    validation_requests: list[ValidationRequest] = Field(default_factory=list)
    validation_bonds: list[ValidationBond] = Field(default_factory=list)
    validation_reports: list[ValidationReport] = Field(default_factory=list)
    validation_report_commitments: list[ValidationReportCommitment] = Field(default_factory=list)
    validation_report_storage_receipts: list[ValidationReportStorageReceipt] = Field(default_factory=list)
    validation_report_storage_failures: list[ValidationReportStorageFailure] = Field(default_factory=list)
    validation_report_transfer_replays: list[ValidationReportTransferReplay] = Field(default_factory=list)
    validation_report_custody_states: list[ValidationReportCustodyState] = Field(default_factory=list)
    validation_report_custody_challenges: list[ValidationReportCustodyChallenge] = Field(default_factory=list)
    validation_report_custody_tasks: list[ValidationReportCustodyCheckTask] = Field(default_factory=list)
    validation_report_custody_retirings: list[ValidationReportCustodyRetirement] = Field(default_factory=list)
    validation_report_custody_objects: list[ValidationReportCustodyObject] = Field(default_factory=list)
    validation_status_snapshots: list[ValidationStatusSnapshot] = Field(default_factory=list)
    validation_epochs: list[ValidationEpoch] = Field(default_factory=list)
    validation_validator_entries: list[ValidationValidatorEntry] = Field(default_factory=list)
    validation_validator_key_bindings: list[ValidationValidatorKeyBinding] = Field(default_factory=list)
    validation_assignments: list[ValidationAssignment] = Field(default_factory=list)
    validation_authorizations: list[ValidationAuthorization] = Field(default_factory=list)
    operator_requests_policy: dict[str, bool | str] = Field(
        default_factory=lambda: {
            "allow_spillover": False,
            "dispatch_strategy": "local_first",
            "ready_endpoint_only": True,
        }
    )
    wallet_usage_events: list[WalletUsageSnapshot] = Field(default_factory=list)
    wallet_session_events: list[WalletSessionSnapshot] = Field(default_factory=list)
    wallet_ledger_events: list[WalletLedgerSnapshot] = Field(default_factory=list)
    wallet_economics_events: list[WalletLedgerSnapshot] = Field(default_factory=list)
    wallet_allocation_events: list[WalletAllocationSnapshot] = Field(default_factory=list)
    wallet_allocation_activation_events: list[WalletAllocationActivationSnapshot] = Field(default_factory=list)
    wallet_allocation_dispute_events: list[WalletAllocationDisputeSnapshot] = Field(default_factory=list)
    wallet_allocation_correction_events: list[WalletAllocationCorrectionSnapshot] = Field(default_factory=list)
    recyclable_removals: list[RecyclableRemoval] = Field(default_factory=list)
    faucet_claims: list[FaucetClaim] = Field(default_factory=list)
    epoch_reward_budgets: list[EpochRewardBudget] = Field(default_factory=list)
    owner_wallet: OwnerWalletSnapshot | None = None
    wallet_identities: list[dict] = Field(default_factory=list)
    consumed_wallet_authorization_nonces: list[str] = Field(default_factory=list)
    operator_onboarding: OperatorOnboardingSnapshot | None = None
    endpoints: list[EndpointManifestSnapshot] = Field(default_factory=list)
    endpoint_configuration_snapshots: list[EndpointConfigurationSnapshotRecord] = Field(default_factory=list)
    endpoint_publications: list[PublishedEndpointConfiguration] = Field(default_factory=list)
    remote_endpoints: list[RemoteEndpointReference] = Field(default_factory=list)
    endpoint_sessions: list[EndpointSessionSnapshot] = Field(default_factory=list)
    locked_deposits: list[LockedDepositSnapshot] = Field(default_factory=list)
    proxy_session_bindings: list[ProxySessionBindingSnapshot] = Field(default_factory=list)
    session_failure_evidence: list[FailureEvidenceRecord] = Field(default_factory=list)
    session_failure_reports: list[FailureReport] = Field(default_factory=list)
    ledger_operations: list[LedgerOperationRecord] = Field(default_factory=list)
    pending_consensus_operations: list[LedgerOperationRecord] = Field(default_factory=list)
    pending_consensus_envelopes: list[LedgerOperationEnvelope] = Field(default_factory=list)
    wallet_operation_sequences: dict[str, int] = Field(default_factory=dict)
    wallet_q_atom_balances: dict[str, int] = Field(default_factory=dict)
    recyclable_q_atoms: int = 0
    burned_q_atoms: int = 0
    stake_records: list[dict] = Field(default_factory=list)
    participant_suspensions: list[dict] = Field(default_factory=list)
    session_funding_accounts: list[SessionFundingAccount] = Field(default_factory=list)
    settlement_proposals: list[SessionSettlementProposal] = Field(default_factory=list)
    settlement_acceptances: list[SessionSettlementAcceptance] = Field(default_factory=list)
    session_checkpoints: list[SessionUsageCheckpoint] = Field(default_factory=list)
    settlement_disputes: list[SettlementDispute] = Field(default_factory=list)
    settlement_corrections: list[SettlementCorrection] = Field(default_factory=list)
    settlement_transition_hashes: dict[str, str] = Field(default_factory=dict)
    development_pool_allocations: list[dict] = Field(default_factory=list)
    development_pool_carryovers: list[dict] = Field(default_factory=list)
    development_bounty_states: list[dict] = Field(default_factory=list)
    development_reward_reserves: list[dict] = Field(default_factory=list)
    development_reward_payment_records: list[dict] = Field(default_factory=list)
    development_reward_unclaimed_records: list[dict] = Field(default_factory=list)
    development_reward_claim_records: list[dict] = Field(default_factory=list)
    development_reward_expiry_records: list[dict] = Field(default_factory=list)
    development_reward_finalized_commitments: list[dict] = Field(default_factory=list)
    development_reward_adjustment_snapshots: list[dict] = Field(default_factory=list)
    development_reward_cancellations: list[dict] = Field(default_factory=list)
    development_reward_corrections: list[dict] = Field(default_factory=list)
    events: list[JournalEvent] = Field(default_factory=list)
