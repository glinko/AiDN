import hashlib
import json
import time
from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import uuid4

from aidn_hypervisor.admission_planning_service import AdmissionPlanningService
from aidn_hypervisor.allocation_catalog_service import AllocationCatalogService
from aidn_hypervisor.allocation_lifecycle_service import AllocationLifecycleService
from aidn_hypervisor.bundle_runtime_policy_service import BundleRuntimePolicyService
from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.domain.models import AllocationRequest, BundleConfig, TaskRequest
from aidn_hypervisor.economics.models import (
    EpochRewardPoolShares,
)
from aidn_hypervisor.endpoint_execution_context_service import (
    EndpointExecutionContextService,
)
from aidn_hypervisor.escalation_service import EscalationTaskService
from aidn_hypervisor.event_bus import (
    CanonicalEventEnvelope,
    EventDataClass,
    EventSeverity,
    InternalEventBus,
)
from aidn_hypervisor.event_projection_service import EventProjectionService
from aidn_hypervisor.event_store import EventStore
from aidn_hypervisor.hook_dispatcher import (
    HookDefinition,
    HookDeliveryRecord,
    HookDeliveryState,
    HookDispatcher,
)
from aidn_hypervisor.hypervisor_integration_service import (
    HypervisorIntegrationService,
)
from aidn_hypervisor.installation_onboarding import (
    build_installation_workflow_projection,
    prepare_assisted_installation_review,
    read_installation_plan,
    update_installation_plan,
)
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.lifecycle_manager import LifecycleManager, ResetManager
from aidn_hypervisor.model_install_service import ModelInstallService
from aidn_hypervisor.mvp_session_economics_service import MvpSessionEconomicsService
from aidn_hypervisor.network_projection_service import NetworkProjectionService
from aidn_hypervisor.operator_application_service import OperatorApplicationService
from aidn_hypervisor.operator_read_models import OperatorReadModelService
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.provider_installation_service import ProviderInstallationService
from aidn_hypervisor.provider_inventory_application_service import (
    ProviderInventoryApplicationService,
)
from aidn_hypervisor.providers.package_store import PluginPackageStore
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore
from aidn_hypervisor.queue import InMemoryTaskQueue, QueuedTask
from aidn_hypervisor.reasoning_adapters import (
    ReasoningAdapterError,
    ReasoningAdapterRegistry,
    ReasoningInvocation,
)
from aidn_hypervisor.reasoning_router import (
    ReasoningProvider,
    ReasoningProviderRegistry,
    ReasoningRouter,
    ReasoningRouteRequest,
)
from aidn_hypervisor.registry_models import (
    RegistryPricing,
    RegistryRating,
)
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.remote_transport_service import RemoteTransportService
from aidn_hypervisor.resident_agent_service import ResidentAgentService
from aidn_hypervisor.resident_inference_adapter import ResidentInferenceAdapter
from aidn_hypervisor.resident_worker import ResidentWorker
from aidn_hypervisor.resources import ResourceAdmissionError
from aidn_hypervisor.runtime_execution_service import RuntimeExecutionService
from aidn_hypervisor.runtime_port_allocator import RuntimePortAllocationError
from aidn_hypervisor.runtime_protocol import RuntimeProtocolBoundaryService
from aidn_hypervisor.runtime_protocol.models import RuntimeRequestRecord
from aidn_hypervisor.runtime_protocol.store import RuntimeProtocolStore
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.sessions.models import ProxySessionBinding
from aidn_hypervisor.settlement.models import (
    SessionFundingAccount,
)
from aidn_hypervisor.settlement_application_service import SettlementApplicationService
from aidn_hypervisor.snapshot_state_service import SnapshotStateService
from aidn_hypervisor.state import (
    HypervisorStateSnapshot,
    JournalEvent,
    RuntimeSnapshot,
    TaskSnapshot,
)
from aidn_hypervisor.steward_event_intelligence import (
    StewardEventBatch,
    StewardEventIntelligence,
    compose_event_summary_messages,
)
from aidn_hypervisor.steward_model_profile import (
    get_steward_model_profile,
    steward_chat_parameters,
)
from aidn_hypervisor.steward_prompt import (
    STEWARD_PROMPT_ID,
    STEWARD_PROMPT_VERSION,
    build_safe_steward_context,
    compose_steward_prompt,
    read_steward_operating_brief,
    update_steward_operating_brief,
)
from aidn_hypervisor.steward_safety import (
    build_steward_decision,
    classify_steward_request,
    deterministic_steward_summary,
    steward_output_matches_language,
    validate_steward_output,
)
from aidn_hypervisor.task_execution_service import TaskExecutionService
from aidn_hypervisor.task_lifecycle_service import TaskLifecycleService
from aidn_hypervisor.task_usage_accounting_service import TaskUsageAccountingService
from aidn_hypervisor.wallet_allocation_service import WalletAllocationService
from aidn_hypervisor.wallet_application_service import WalletApplicationService
from aidn_hypervisor.wallet_economics_service import WalletEconomicsService
from aidn_hypervisor.wallet_models import WalletUsageMeasurement

Q_ATOMS_PER_Q = 1_000_000

_DEFAULT_OPERATOR_REQUESTS_POLICY = {
    "allow_spillover": False,
    "dispatch_strategy": "local_first",
    "ready_endpoint_only": True,
}
_DEFAULT_EPOCH_REWARD_POOL_SHARES = {
    "contribution": 0.6,
    "consensus": 0.12,
    "registry": 0.12,
    "validation": 0.12,
    "faucet": 0.04,
}


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _parse_iso_timestamp(value: object) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


class AllocationUnavailableError(ValueError):
    def __init__(
        self,
        *,
        reason: str,
        message: str,
        bundle_id: str | None,
        retryable: bool,
        retry_after_seconds: int | None = None,
        next_attempt_at: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.bundle_id = bundle_id
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.next_attempt_at = next_attempt_at

    def as_detail(self) -> dict[str, str | bool | None]:
        detail = {
            "reason": self.reason,
            "retryable": self.retryable,
            "bundle_id": self.bundle_id,
            "message": self.message,
        }
        if self.retry_after_seconds is not None:
            detail["retry_after_seconds"] = self.retry_after_seconds
        if self.next_attempt_at is not None:
            detail["next_attempt_at"] = self.next_attempt_at
        return detail


class HypervisorService:
    def __init__(
        self,
        queue: InMemoryTaskQueue,
        scheduler: Scheduler,
        resources=None,
        bundles=None,
        plugins=None,
        runtimes=None,
        state_store=None,
        bundle_registry=None,
        model_store=None,
        max_active_allocations_per_owner: int = 2,
        max_pending_allocations_per_owner: int = 4,
        node_id: str = "node-local",
        operator_id: str = "operator-local",
        base_url: str = "http://127.0.0.1:8000",
        can_host_custom_model: bool = False,
        pricing: dict | None = None,
        rating: dict | None = None,
        heartbeat_ttl_seconds: int = 30,
        wallet_usage_retention_limit: int | None = None,
        wallet_allocation_grace_period_seconds: int = 300,
        base_emission_q: float = 5000.0,
        epoch_reward_pool_shares: dict | None = None,
        provider_inventory=None,
        provider_installation_executor=None,
        plugin_package_store: PluginPackageStore | None = None,
        plugin_host_secret_manager=None,
        runtime_protocol_store=None,
        registry_service: RegistryService | None = None,
        consensus_service=None,
        consensus_finality_source=None,
        canonical_wallet_balance_provider=None,
        canonical_wallet_identity_provider=None,
        canonical_wallet_sequence_provider=None,
    ) -> None:
        # Provider broker workers and managed-process callbacks may persist
        # concurrently with an API request.  Serialize snapshot writes so a
        # slower worker cannot overwrite a newer durable job/runtime state.
        self._persistence_lock = RLock()
        self.queue = queue
        self.scheduler = scheduler
        self.resources = resources
        self.bundles = bundles or []
        self.plugins = plugins or []
        self.runtimes = runtimes or []
        self.state_store = state_store
        self.bundle_registry = bundle_registry
        self.model_store = model_store
        self._plugin_package_store = plugin_package_store
        self.provider_inventory = provider_inventory or ProviderInventoryService(
            plugins=self.plugins,
            store=InMemoryProviderInventoryStore(),
            installation_executor=provider_installation_executor,
            package_store=plugin_package_store,
            plugin_host_secret_manager=plugin_host_secret_manager,
        )
        self.registry_service = registry_service
        self.consensus_service = consensus_service
        self.consensus_finality_source = consensus_finality_source
        self.canonical_wallet_balance_provider = canonical_wallet_balance_provider
        self.canonical_wallet_identity_provider = canonical_wallet_identity_provider
        self.canonical_wallet_sequence_provider = canonical_wallet_sequence_provider
        if consensus_finality_source is not None:
            self.bind_consensus_finality_source(consensus_finality_source)
        self.runtime_protocol_store = runtime_protocol_store or RuntimeProtocolStore(
            state_store
        )
        self._plugin_host_listeners: list[object] = []
        self.max_active_allocations_per_owner = max_active_allocations_per_owner
        self.max_pending_allocations_per_owner = max_pending_allocations_per_owner
        self.node_id = node_id
        self.operator_id = operator_id
        self.base_url = base_url
        self.can_host_custom_model = can_host_custom_model
        self.pricing = pricing or {
            "unit": "q_per_1kk_tokens",
            "input": 0,
            "output": 0,
            "fixed_request": None,
        }
        self.rating = rating or {
            "score": 0.0,
            "tier": "unrated",
            "updated_at": datetime.now(UTC).isoformat(),
        }
        self.heartbeat_ttl_seconds = heartbeat_ttl_seconds
        self.wallet_usage_retention_limit = (
            max(1, int(wallet_usage_retention_limit))
            if wallet_usage_retention_limit is not None
            else None
        )
        self.wallet_allocation_grace_period_seconds = max(
            0, int(wallet_allocation_grace_period_seconds)
        )
        self.base_emission_q = float(base_emission_q)
        self.epoch_reward_pool_shares = EpochRewardPoolShares(
            **(epoch_reward_pool_shares or _DEFAULT_EPOCH_REWARD_POOL_SHARES)
        )
        self._selected_bundles: dict[str, str] = {}
        self._task_results: dict[str, dict] = {}
        self._task_recovery_reasons: dict[str, str] = {}
        self._allocations: dict[str, dict] = {}
        self._model_installs: dict[str, dict] = {}
        self._operator_requests_policy = dict(_DEFAULT_OPERATOR_REQUESTS_POLICY)
        self._owner_wallet: dict | None = None
        self._wallet_identities: dict[str, dict] = {}
        self._consumed_wallet_authorization_nonces: set[str] = set()
        self._operator_onboarding: dict | None = None
        self._runtime_reservations: set[str] = set()
        # RFC-0074/IMP-0002 durable lifecycle operation and tombstone stores.
        # They are intentionally plain JSON records so older state stores can
        # load a snapshot without importing a newer object model.
        self._lifecycle_operations: dict[str, dict] = {}
        self._lifecycle_tombstones: dict[str, dict] = {}
        self._lifecycle_states: dict[str, dict] = {}
        self._lifecycle_maintenance_state = "ENABLED"
        self._lifecycle_lock = RLock()
        self._bundle_states: dict[str, dict] = {}
        self._wallet_usage_events: list[dict] = []
        self._next_wallet_usage_sequence = 1
        self._wallet_session_events: list[dict] = []
        self._next_wallet_session_sequence = 1
        self._wallet_ledger_events: list[dict] = []
        self._next_wallet_ledger_sequence = 1
        self._wallet_economics_events: list[dict] = []
        self._next_wallet_economics_sequence = 1
        self._recyclable_removals: list[dict] = []
        self._next_recyclable_removal_sequence = 1
        self._faucet_claims: list[dict] = []
        self._next_faucet_claim_sequence = 1
        self._epoch_reward_budgets: list[dict] = []
        self._wallet_allocation_activation_events: list[dict] = []
        self._next_wallet_allocation_activation_sequence = 1
        self._wallet_allocation_dispute_events: list[dict] = []
        self._next_wallet_allocation_dispute_sequence = 1
        self._wallet_allocation_events: list[dict] = []
        self._next_wallet_allocation_sequence = 1
        self._wallet_allocation_correction_events: list[dict] = []
        self._next_wallet_allocation_correction_sequence = 1
        # Track allocation_ids that must be auto-held due to strict-accounting blocks
        self._wallet_strict_held_allocations: set[str] = set()
        self._ledger_operation_service = LedgerOperationService()
        # Pending consensus projections are local correlation records. They are
        # persisted for retry, but never enter the canonical Ledger operation log.
        self._pending_consensus_operations: dict[str, dict] = {}
        # Unlike the projection records above, these are the exact immutable
        # network envelopes needed to retry an admitted operation after restart.
        self._pending_consensus_envelopes: dict[str, dict] = {}
        # Wallet bootstrap keeps private material local while the public bind
        # transaction is waiting for canonical consensus finality.
        self._pending_owner_wallet_bootstraps: list[dict] = []
        self._mvp_session_economics_service = MvpSessionEconomicsService(self)
        self._wallet_economics_service = WalletEconomicsService(self)
        self._wallet_allocation_service = WalletAllocationService(self)
        self._wallet_application_service = WalletApplicationService(self)
        self._network_projection_service = NetworkProjectionService(self)
        self._provider_installation_service = ProviderInstallationService(self)
        self._runtime_execution_service = RuntimeExecutionService(self)
        self._remote_transport_service = RemoteTransportService(self)
        self._task_execution_service = TaskExecutionService(self)
        self._task_lifecycle_service = TaskLifecycleService(self)
        self._task_usage_accounting_service = TaskUsageAccountingService(self)
        self._endpoint_execution_context_service = EndpointExecutionContextService(self)
        self._allocation_lifecycle_service = AllocationLifecycleService(self)
        self._allocation_catalog_service = AllocationCatalogService(self)
        self._admission_planning_service = AdmissionPlanningService(self)
        self._model_install_service = ModelInstallService(self)
        self._bundle_runtime_policy_service = BundleRuntimePolicyService(self)
        self._snapshot_state_service = SnapshotStateService(self)
        self._event_projection_service = EventProjectionService(self)
        self._integration_service = HypervisorIntegrationService(self)
        self._operator_application_service = OperatorApplicationService(self)
        self._provider_inventory_application_service = (
            ProviderInventoryApplicationService(self)
        )
        self._scheduler_reconciliation_service = None

        self._settlement_application_service = SettlementApplicationService(self)
        self.operator_read_models = OperatorReadModelService(self)
        self._events: list[JournalEvent] = []
        consensus_config = getattr(self.consensus_service, "config", None)
        event_network_id = (
            getattr(self, "network_id", None)
            or getattr(consensus_config, "network_id", None)
            or getattr(consensus_config, "chain_id", None)
            or "local"
        )
        self._event_bus = InternalEventBus(
            hypervisor_id=self.node_id,
            network_id=str(event_network_id),
        )
        self._event_store = EventStore(
            self._event_bus,
            on_change=self._persist_state,
        )
        self._steward_event_intelligence = StewardEventIntelligence(
            on_change=self._persist_state,
        )
        self._steward_event_intelligence.bind_event_bus(self._event_bus)
        self._hook_dispatcher = HookDispatcher(
            self._event_bus,
            self._event_store,
            on_change=self._persist_state,
        )
        self._resident_agent_service = ResidentAgentService(
            node_id=self.node_id,
            enabled=True,
            on_change=self._persist_state,
            context_provider=self._resident_context_payload,
        )
        self._resident_agent_service.bind_event_bus(self._event_bus)
        self._reasoning_provider_registry = ReasoningProviderRegistry()
        self._reasoning_adapter_registry = ReasoningAdapterRegistry()
        self._reasoning_router = ReasoningRouter(
            self._reasoning_provider_registry,
            resource_admission=(
                self.resources.admission_report
                if self.resources is not None and hasattr(self.resources, "admission_report")
                else None
            ),
        )
        self._escalation_task_service = EscalationTaskService(
            on_change=self._persist_state,
        )
        bind_installation_job_callback = getattr(
            self.provider_inventory,
            "set_installation_job_update_callback",
            None,
        )
        if callable(bind_installation_job_callback):
            bind_installation_job_callback(self._persist_state)
        self._runtime_boundary = RuntimeProtocolBoundaryService(self)
        self._resident_inference_adapter = ResidentInferenceAdapter(
            node_id=self.node_id,
            resources=self.resources,
            runtimes=self.runtimes,
            plugin_resolver=self._get_plugin,
            on_change=self._persist_state,
            on_resource_change=lambda _reason: self.reconcile_scheduler(trigger="resident_inference"),
        )
        self._resident_agent_service.bind_inference_adapter(self._resident_inference_adapter)
        self._reasoning_adapter_registry.register(
            "resident-local",
            lambda _provider, invocation: self.invoke_resident_inference(
                invocation.prompt,
                timeout_seconds=invocation.timeout_seconds,
                stream=invocation.stream,
                **dict(invocation.parameters or {}),
            ),
        )
        # The worker is constructed disabled and is started by the application
        # lifespan only when the operator explicitly enables the Steward.
        self._resident_worker = ResidentWorker(self, enabled=False)
        self.lifecycle_manager = LifecycleManager(self)
        self.reset_manager = ResetManager(self.lifecycle_manager)
        # Managed child processes can change state without an API request.
        # Let the process manager persist those transitions so another shared
        # state-store writer cannot reintroduce an old runtime snapshot.
        bind_runtime_callback = getattr(
            self.runtimes,
            "set_runtime_state_change_callback",
            None,
        )
        if callable(bind_runtime_callback):
            bind_runtime_callback(self._on_runtime_state_change)

    def bind_consensus_finality_source(self, consensus_finality_source) -> None:
        """Bind one verified finality source to the Hypervisor and Registry."""
        if (
            self.consensus_finality_source is not None
            and self.consensus_finality_source is not consensus_finality_source
        ):
            raise ValueError("Hypervisor is already bound to another consensus finality source")
        self.consensus_finality_source = consensus_finality_source
        if self.registry_service is not None:
            self.registry_service.bind_consensus_finality_source(consensus_finality_source)

    @property
    def pricing(self) -> dict:
        return self._pricing.model_dump(mode="json")

    @pricing.setter
    def pricing(self, value: RegistryPricing | dict) -> None:
        if isinstance(value, RegistryPricing):
            self._pricing = value
            return
        self._pricing = RegistryPricing(**value)

    @property
    def rating(self) -> dict:
        return self._rating.model_dump(mode="json")

    @rating.setter
    def rating(self, value: RegistryRating | dict) -> None:
        if isinstance(value, RegistryRating):
            self._rating = value
            return
        self._rating = RegistryRating(**value)

    def submit(self, request: TaskRequest):
        return self._task_lifecycle_facade().submit(request)

    def selected_bundle_id(self, task_id: str) -> str | None:
        return self._task_lifecycle_facade().selected_bundle_id(task_id)

    def task_result(self, task_id: str) -> dict | None:
        return self._task_lifecycle_facade().task_result(task_id)

    def task_recovery_reason(self, task_id: str) -> str | None:
        return self._task_lifecycle_facade().task_recovery_reason(task_id)

    def task_proxy_trace(self, task_id: str) -> dict | None:
        return self._task_lifecycle_facade().task_proxy_trace(task_id)

    def event_journal(self, *, limit: int | None = None) -> list[JournalEvent]:
        events = list(self._events)
        if limit is None or limit >= len(events):
            return events
        return events[-limit:]

    def canonical_event_journal(
        self, *, limit: int | None = None
    ) -> list[CanonicalEventEnvelope]:
        """Return events after RFC-0072 normalisation and redaction."""

        return self._event_store.events(limit=limit)

    def canonical_event_query(
        self,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        event_types: set[str] | None = None,
        resource_id: str | None = None,
    ) -> dict:
        return self._event_store.query(
            after_sequence=after_sequence,
            limit=limit,
            event_types=event_types,
            resource_id=resource_id,
        )

    def event_inbox(
        self,
        agent_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._event_store.inbox(
            agent_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    @property
    def resident_agent(self) -> ResidentAgentService:
        return self._resident_agent_service

    @property
    def resident_worker(self) -> ResidentWorker:
        return self._resident_worker

    def configure_resident_worker(
        self,
        *,
        enabled: bool,
        interval_seconds: float | None = None,
    ) -> dict:
        """Configure the always-on worker without starting model inference."""

        if self._resident_worker.running:
            self._resident_worker.stop()
        self._resident_worker.enabled = bool(enabled)
        if interval_seconds is not None:
            self._resident_worker.interval_seconds = max(
                1.0, min(300.0, float(interval_seconds))
            )
        return self._resident_worker.status()

    def start_resident_worker(self) -> dict:
        return self._resident_worker.start()

    def stop_resident_worker(self) -> dict:
        return self._resident_worker.stop()

    def _resident_context_payload(self) -> dict:
        """Small, non-secret context projection for the local Steward."""

        try:
            resources = self.operator_dashboard_resources()
        except Exception:
            resources = {}
        try:
            providers = self.list_provider_instances()
        except Exception:
            providers = []
        bundles = []
        for item in self.bundles or []:
            if isinstance(item, dict):
                bundle_id = item.get("bundle_id")
            else:
                bundle_id = getattr(item, "bundle_id", None)
            if bundle_id:
                bundles.append(str(bundle_id))
        return {
            "node_id": self.node_id,
            "base_url": self.base_url,
            "resources": resources,
            "providers": providers[:32] if isinstance(providers, list) else [],
            "bundles": bundles[:64],
            "queue": self.queue_summary(),
        }

    def resident_agent_status(self) -> dict:
        payload = self._resident_agent_service.status()
        payload["worker"] = self._resident_worker.status()
        payload["event_intelligence"] = self._steward_event_intelligence.status()
        return payload

    def resident_agent_context(self) -> dict:
        return self._resident_agent_service.context_snapshot()

    @property
    def steward_event_intelligence(self) -> StewardEventIntelligence:
        """Expose the bounded, advisory event intelligence pipeline."""

        return self._steward_event_intelligence

    def resident_event_intelligence_status(self) -> dict:
        return self._steward_event_intelligence.status()

    def resident_event_intelligence_process(self, *, use_local_model: bool = False) -> dict | None:
        """Summarize one bounded event batch without changing authoritative state.

        Local model use is opt-in because a deterministic summary is already
        sufficient for the dashboard and must remain available while the
        Resident runtime is stopped or unhealthy.
        """

        summarizer = None
        if use_local_model:
            status = self.resident_inference_status()
            if str(status.get("state") or "").upper() == "RUNNING":
                summarizer = self._summarize_resident_event_batch
        return self._steward_event_intelligence.process_once(
            summarizer=summarizer,
        )

    def _summarize_resident_event_batch(self, batch: StewardEventBatch) -> dict | None:
        """Ask the local model for advisory prose, never for policy decisions."""

        messages = compose_event_summary_messages(batch)
        model_profile = get_steward_model_profile()
        inference_parameters = steward_chat_parameters(model_profile.profile_id)
        inference_parameters["max_tokens"] = 128
        inference_parameters["messages"] = messages
        inference_parameters["stop"] = ["</SYSTEM>", "```"]
        result = self._resident_inference_adapter.infer(
            "Summarize the canonical event batch as JSON.",
            **inference_parameters,
        )
        output = str(result.get("output_text") or "").strip()
        if output.startswith("```"):
            output = output.strip("`").strip()
            if output.lower().startswith("json"):
                output = output[4:].lstrip()
        try:
            value = json.loads(output)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def resident_agent_decide(self, goal: str, **kwargs) -> dict:
        return self._resident_agent_service.decide(goal, **kwargs)

    def set_resident_agent_enabled(self, enabled: bool) -> dict:
        return self._resident_agent_service.set_enabled(bool(enabled))

    def reasoning_provider_list(self) -> dict:
        try:
            inference = self.resident_inference_status()
            state = str(inference.get("state") or "NOT_CONFIGURED")
            execution = inference.get("execution") if isinstance(inference, dict) else {}
            requested = execution.get("requested_resources") if isinstance(execution, dict) else {}
            self._reasoning_provider_registry.register(
                ReasoningProvider(
                    provider_id="resident-local",
                    kind="LOCAL_RESIDENT",
                    model_id=str(inference.get("model_path") or "resident-steward"),
                    capabilities=("general", "diagnostic", "control", "planning"),
                    context_limit=int(execution.get("context_limit") or 4096) if isinstance(execution, dict) else 4096,
                    allowed_data_classes=("PUBLIC", "OPERATOR", "SENSITIVE"),
                    latency_ms=100 if state == "RUNNING" else 500,
                    cost_q_atoms=0,
                    required_cpu=float((requested or {}).get("cpu", 0) or 0),
                    required_ram_mb=int((requested or {}).get("ram_mb", 0) or 0),
                    required_vram_mb=int((requested or {}).get("vram_mb", 0) or 0),
                    available=state in {"RUNNING", "READY_TO_START"},
                    enabled=self._resident_agent_service.enabled,
                    trusted=True,
                    priority=100,
                ),
                replace=True,
            )
        except Exception:
            pass
        return {"generated_at": datetime.now(UTC).isoformat(), "registry": self._reasoning_provider_registry.as_payload(), "policy": {"local_first": True, "external_default": False, "execution_started": False}}

    def reasoning_provider_register(self, payload: dict) -> dict:
        provider = self._reasoning_provider_registry.register(payload)
        self._persist_state()
        return {"registered": True, "provider": provider.as_payload()}

    def reasoning_route(self, payload: dict, *, budget_remaining_q_atoms: int | None = None) -> dict:
        self.reasoning_provider_list()
        values = dict(payload or {})
        if budget_remaining_q_atoms is not None and "budget_remaining_q_atoms" not in values:
            values["budget_remaining_q_atoms"] = budget_remaining_q_atoms
        return self._reasoning_router.route(ReasoningRouteRequest.from_mapping(values))

    def reasoning_invoke(
        self,
        prompt: str,
        *,
        route: dict | None = None,
        timeout_seconds: float = 90.0,
        stream: bool = False,
        parameters: dict | None = None,
    ) -> dict:
        """Route and invoke one Intelligence Provider as two explicit steps."""

        decision = self.reasoning_route(dict(route or {}))
        selected = decision.get("selected_provider")
        if not isinstance(selected, dict):
            raise ReasoningAdapterError(
                "no eligible reasoning provider",
                details={"code": "REASONING_ROUTE_UNAVAILABLE", "decision": decision},
            )
        provider = self._reasoning_provider_registry.get(str(selected.get("provider_id") or ""))
        if provider is None:
            raise ReasoningAdapterError("selected reasoning provider disappeared", details={"code": "REASONING_PROVIDER_NOT_FOUND"})
        result = self._reasoning_adapter_registry.invoke(
            provider,
            ReasoningInvocation(
                prompt=prompt,
                timeout_seconds=timeout_seconds,
                stream=stream,
                parameters=parameters,
            ),
        )
        result["routing"] = {"decision_id": decision.get("decision_id"), "provider_id": provider.provider_id}
        return result

    def resident_inference_status(self) -> dict:
        return self._resident_inference_adapter.refresh(persist=False)

    def prepare_resident_inference(self, **kwargs) -> dict:
        payload = self._resident_inference_adapter.prepare(**kwargs)
        model_path = payload.get("model_path")
        if model_path:
            self._resident_agent_service.configure_model(
                model_path=str(model_path),
                model_repo=payload.get("provider_type"),
                persist=False,
            )
        self._persist_state()
        return payload

    def start_resident_inference(self) -> dict:
        if not self._resident_agent_service.enabled:
            raise ValueError("Resident Steward is disabled")
        return self._resident_inference_adapter.start()

    def stop_resident_inference(self) -> dict:
        return self._resident_inference_adapter.stop()

    def invoke_resident_inference(self, prompt: str, **parameters) -> dict:
        return self._resident_inference_adapter.infer(prompt, **parameters)

    def resident_steward_prompt(self) -> dict:
        """Return the operator-editable explanation brief for the Resident Steward."""

        return read_steward_operating_brief()

    def update_resident_steward_prompt(
        self,
        text: str,
        *,
        expected_sha256: str | None = None,
    ) -> dict:
        """Update the Steward brief without changing immutable safety rules."""

        return update_steward_operating_brief(
            text,
            expected_sha256=expected_sha256,
        )

    def resident_steward_chat(self, message: str, **parameters) -> dict:
        """Invoke the local Steward with versioned rules and secret-free state."""

        model_profile = get_steward_model_profile()
        event_intelligence = getattr(self, "_steward_event_intelligence", None)
        advisory = (
            event_intelligence.latest_advisory()
            if event_intelligence is not None
            else None
        )
        inference_parameters = dict(parameters)
        diagnostic_snapshot = inference_parameters.pop("diagnostic_snapshot", None)
        if diagnostic_snapshot is not None and not isinstance(diagnostic_snapshot, dict):
            raise ValueError("diagnostic_snapshot must be an object")
        context = build_safe_steward_context(
            installation_plan=self.installation_plan(),
            node_identity=self.node_identity(),
            wallet_state=self.owner_wallet_state(),
            inference_state=self.resident_inference_status(),
            event_intelligence=advisory,
            diagnostic_snapshot=diagnostic_snapshot,
            steward_action_policy=self.resident_agent_action_policy(),
        )
        operating_brief = self.resident_steward_prompt()
        invocation = compose_steward_prompt(
            message,
            context,
            no_think_suffix=model_profile.enable_thinking is False,
            operating_brief=str(operating_brief["text"]),
            operating_brief_sha256=str(operating_brief["sha256"]),
        )
        guard = classify_steward_request(message)
        decision = build_steward_decision(
            message,
            guard=guard,
            diagnostic_snapshot=context.get("diagnostic_snapshot"),
        )
        fallback = (
            "I cannot confirm that a state change occurred. The observed "
            "Hypervisor state is authoritative; review the next listed step "
            "before taking action."
        )
        deterministic_summary = deterministic_steward_summary(
            message,
            decision=decision,
            diagnostic_snapshot=context.get("diagnostic_snapshot"),
            context=context,
        )

        # High-risk requests never reach the local model. This keeps a small
        # or compromised model from turning a chat message into an action and
        # makes the refusal deterministic across providers.
        if guard.blocked:
            status = self.resident_inference_status()
            validation = validate_steward_output(
                guard.response or fallback,
                fallback=fallback,
            )
            return {
                "ok": True,
                "task_type": "llm_text.generate",
                "model_id": status.get("model_path"),
                "output_text": validation.output_text,
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "fixed_request_count": 0,
                    "measurement_kind": "deterministic_guard",
                    "measurement_source": "steward_safety",
                },
                "response_mode": "deterministic_guard",
                "provider_error": None,
                "safety": {
                    "guard": guard.as_payload(),
                    "validation": validation.as_payload(),
                },
                "decision": decision.as_payload(),
                "prompt": {
                    "id": invocation["prompt_id"],
                    "version": invocation["prompt_version"],
                    "operating_brief_sha256": invocation["operating_brief_sha256"],
                },
                "model_profile": model_profile.as_payload(),
                "context": context,
                "suggested_questions": invocation["suggested_questions"],
            }

        # Known status and diagnostic requests do not need to wait for a local
        # model. The deterministic layer already owns tool selection and can
        # answer from the bounded snapshot immediately. The SLM remains
        # available for open-ended explanation when no reviewed route exists.
        if context.get("diagnostic_snapshot") or decision.tool is not None:
            status = self.resident_inference_status()
            validation = validate_steward_output(
                deterministic_summary,
                fallback=fallback,
            )
            return {
                "ok": True,
                "task_type": "llm_text.generate",
                "model_id": status.get("model_path"),
                "output_text": validation.output_text,
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "fixed_request_count": 0,
                    "measurement_kind": "deterministic_route",
                    "measurement_source": "steward_safety",
                },
                "response_mode": "deterministic_route",
                "provider_error": None,
                "safety": {
                    "guard": guard.as_payload(),
                    "validation": validation.as_payload(),
                },
                "decision": decision.as_payload(),
                "prompt": {
                    "id": invocation["prompt_id"],
                    "version": invocation["prompt_version"],
                    "operating_brief_sha256": invocation["operating_brief_sha256"],
                },
                "model_profile": model_profile.as_payload(),
                "context": context,
                "suggested_questions": invocation["suggested_questions"],
            }

        # Keep the default Dashboard interaction bounded on CPU-only nodes.
        # Operators can still override this through the explicit parameters
        # object. The role-separated messages let instruction-tuned models
        # apply their reviewed chat template instead of treating the context
        # and operator text as one undifferentiated completion prompt.
        profile_parameters = steward_chat_parameters(model_profile.profile_id)
        # The prompt and role-separated messages are control-plane material;
        # callers may tune decoding, but cannot replace the reviewed context
        # with an arbitrary provider payload.
        inference_parameters.pop("prompt", None)
        inference_parameters.pop("messages", None)
        for name, value in profile_parameters.items():
            inference_parameters.setdefault(name, value)
        chat_template_kwargs = inference_parameters.get("chat_template_kwargs")
        chat_template_kwargs = (
            dict(chat_template_kwargs) if isinstance(chat_template_kwargs, dict) else {}
        )
        if model_profile.enable_thinking is not None:
            chat_template_kwargs["enable_thinking"] = model_profile.enable_thinking
        else:
            chat_template_kwargs.pop("enable_thinking", None)
        if chat_template_kwargs:
            inference_parameters["chat_template_kwargs"] = chat_template_kwargs
        else:
            inference_parameters.pop("chat_template_kwargs", None)
        inference_parameters["messages"] = invocation["messages"]
        inference_parameters["tools"] = self._resident_steward_tool_definitions()
        inference_parameters["tool_choice"] = "auto"
        inference_parameters["parallel_tool_calls"] = False
        inference_parameters.setdefault("stop", ["</STEWARD_RESPONSE>", "</SYSTEM>"])
        # A local SLM is advisory, not an availability dependency. Bound both
        # the adapter wait and provider transport, then return deterministic
        # evidence if the model cannot answer in the reviewed latency budget.
        inference_parameters["provider_timeout_seconds"] = model_profile.request_timeout_seconds
        inference_parameters["timeout_seconds"] = model_profile.request_timeout_seconds + 1.0
        response_mode = "model_augmented"
        provider_error = None
        try:
            result = self._resident_inference_adapter.infer(
                invocation["rendered_prompt"],
                **inference_parameters,
            )
        except ValueError as error:
            status = self.resident_inference_status()
            details = getattr(error, "details", {})
            provider_error = {
                "code": str(details.get("code") or getattr(error, "code", "INFERENCE_PROVIDER_ERROR")),
                "message": str(error)[:256],
            }
            result = {
                "ok": True,
                "task_type": "llm_text.generate",
                "model_id": status.get("model_path"),
                "output_text": deterministic_summary,
                "usage": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "measurement_kind": "deterministic_fallback",
                    "measurement_source": "steward_safety",
                },
            }
            response_mode = "deterministic_fallback"
        action_outcome = self._resident_steward_apply_tool_calls(
            result.get("tool_calls"),
        ) if response_mode == "model_augmented" else None
        if action_outcome is not None:
            result["steward_action"] = action_outcome
            operator_text = self._resident_steward_action_message(
                action_outcome,
                operator_message=message,
            )
            action_outcome["message"] = operator_text
        validation = validate_steward_output(
            result.get("output_text"),
            fallback=fallback,
        )
        if action_outcome is None:
            operator_text = validation.output_text
        if response_mode == "model_augmented" and not steward_output_matches_language(
            message,
            operator_text,
        ):
            operator_text = deterministic_summary
            response_mode = "deterministic_language_fallback"
        return {
            **result,
            "output_text": operator_text,
            "response_mode": response_mode,
            "provider_error": provider_error,
            "safety": {
                "guard": guard.as_payload(),
                "validation": validation.as_payload(),
            },
            "decision": decision.as_payload(),
            "prompt": {
                "id": invocation["prompt_id"],
                "version": invocation["prompt_version"],
                "operating_brief_sha256": invocation["operating_brief_sha256"],
            },
            "model_profile": model_profile.as_payload(),
            "context": context,
            "suggested_questions": invocation["suggested_questions"],
        }

    @staticmethod
    def _resident_steward_tool_definitions() -> list[dict[str, Any]]:
        """One narrow tool: the model may select, never invent, an action."""

        return [{
            "type": "function",
            "function": {
                "name": "aidn.steward.execute_action",
                "description": "Run one reviewed Hypervisor action only when its exact target is available in node context.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "action": {"type": "string", "enum": ["provider.health_check", "runtime.drain", "runtime.restart", "runtime.stop"]},
                        "target_id": {"type": "string", "minLength": 1},
                    },
                    "required": ["action", "target_id"],
                },
            },
        }]

    @staticmethod
    def _resident_steward_action_message(
        outcome: dict[str, Any],
        *,
        operator_message: str,
    ) -> str:
        """Render a definite local action state when the model used a tool."""

        plan = outcome.get("plan") if isinstance(outcome.get("plan"), dict) else {}
        action = str(plan.get("action") or "requested action")
        target = str(plan.get("target_id") or "selected target")
        status = str(outcome.get("status") or "UNKNOWN").upper()
        russian = any("\u0400" <= char <= "\u04ff" for char in str(operator_message))
        if russian:
            if status == "APPROVAL_REQUIRED":
                return f"Действие {action} для {target} готово. Нажмите «Подтвердить и выполнить», чтобы запустить его."
            if status == "COMPLETED":
                return f"Steward выполнил действие {action} для {target}; результат проверен Hypervisor."
            if status == "DENIED":
                return f"Действие {action} для {target} запрещено текущей политикой; изменений не было."
            return f"Действие {action} для {target}: {status.lower()}."
        if status == "APPROVAL_REQUIRED":
            return f"{action} for {target} is ready. Choose Approve & run to execute this exact action."
        if status == "COMPLETED":
            return f"Steward completed {action} for {target}; Hypervisor verified the result."
        if status == "DENIED":
            return f"{action} for {target} is denied by the current policy; no change was made."
        return f"{action} for {target}: {status.lower()}."

    def _resident_steward_apply_tool_calls(self, tool_calls: Any) -> dict[str, Any] | None:
        """Apply at most one typed model tool call through the existing policy.

        The model supplies only an action choice and target.  Policy lookup,
        planning, approval, dispatch and observed verification remain local.
        """

        if not isinstance(tool_calls, list) or not tool_calls:
            return None
        call = tool_calls[0] if isinstance(tool_calls[0], dict) else {}
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        if str(function.get("name") or "") != "aidn.steward.execute_action":
            return None
        raw_args = function.get("arguments")
        try:
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"status": "DENIED", "message": "Steward returned an invalid action request; no change was made."}
        action = str(arguments.get("action") or "").strip()
        target_id = str(arguments.get("target_id") or "").strip()
        if not action or not target_id:
            return {"status": "DENIED", "message": "Steward did not identify a valid action target; no change was made."}
        try:
            planned = self.resident_agent_execute_action(action, target_id=target_id, mode="plan")
        except ValueError as error:
            return {"status": "DENIED", "message": f"{error}. Change the action policy to allow it."}
        plan = planned.get("plan") if isinstance(planned.get("plan"), dict) else {}
        if plan.get("requires_approval"):
            return {
                "status": "APPROVAL_REQUIRED",
                "plan": plan,
                "message": f"{action} for {target_id} is ready. Choose Approve & run to execute this exact action.",
            }
        applied = self.resident_agent_execute_action(
            action,
            target_id=target_id,
            mode="apply",
            plan_hash=plan.get("plan_hash"),
        )
        status = str(applied.get("status") or "UNKNOWN")
        return {
            "status": status,
            "result": applied,
            "message": f"{action} for {target_id}: {status.lower()}.",
        }

    def prepare_resident_model(self, **kwargs) -> dict:
        """Download and verify a Steward artifact without starting inference."""

        return self._resident_inference_adapter.prepare_model(**kwargs)

    def verify_resident_model(self, model_path: str, **kwargs) -> dict:
        return self._resident_inference_adapter.verify_model(model_path, **kwargs)

    def start_resident_inference_from_install(self, install_id: str) -> dict:
        job = self._model_installs.get(str(install_id))
        if not job:
            raise ValueError("model install was not found")
        return self.prepare_resident_inference(
            model_path=str(job.get("target_path") or ""),
            provider_type=str(job.get("provider_type") or "llama.cpp"),
            profile=str(job.get("resident_execution_profile") or "CPU_RESIDENT"),
            **(job.get("resident_resource_request") or {}),
        ) | {"execution": self.start_resident_inference().get("execution", {})}

    def prepare_resident_inference_from_install(self, install_id: str, *, persist: bool = True) -> dict:
        job = self._model_installs.get(str(install_id))
        if not job:
            raise ValueError("model install was not found")
        payload = self.prepare_resident_inference(
            model_path=str(job.get("target_path") or ""),
            provider_type=str(job.get("provider_type") or "llama.cpp"),
            profile=str(job.get("resident_execution_profile") or "CPU_RESIDENT"),
            persist=persist,
            **(job.get("resident_resource_request") or {}),
        )
        job["resident_adapter_status"] = "READY_TO_START"
        job["resident_adapter_error"] = None
        if persist:
            self._persist_state()
        return payload

    def resident_agent_guard_action(self, action: str, **kwargs) -> dict:
        payload = self._resident_agent_service.guard_action(action, **kwargs)
        try:
            self.record_event(
                event_type="aidn.steward.action_guarded" if payload.get("allowed") else "aidn.steward.action_blocked",
                message=str(payload.get("reason") or "Resident action guard evaluated"),
                details={"action_id": payload.get("action_id"), "action": payload.get("action"), "target_id": payload.get("target_id"), "code": payload.get("code"), "claim_only": True},
                source="resident-agent",
                severity="NOTICE" if payload.get("allowed") else "WARNING",
                resource_type="steward_action",
                resource_id=str(payload.get("action_id") or "steward-action"),
                correlation_id=(payload.get("lineage") or {}).get("correlation_id"),
                causation_id=(payload.get("lineage") or {}).get("causation_id"),
            )
        except Exception:
            pass
        return payload

    def resident_agent_action_policy(self) -> dict:
        return self._resident_agent_service.action_policy()

    def configure_resident_agent_action_policy(self, *, auto_actions=None, approval_actions=None, max_actions_per_hour=None, test_unrestricted=None) -> dict:
        return self._resident_agent_service.configure_action_policy(
            auto_actions=auto_actions,
            approval_actions=approval_actions,
            max_actions_per_hour=max_actions_per_hour,
            test_unrestricted=test_unrestricted,
        )

    def _resident_agent_action_plan(self, action: str, target_id: str, **kwargs) -> dict:
        policy = self.resident_agent_action_policy()
        item = next((entry for entry in policy.get("catalog", []) if entry.get("action") == str(action)), None)
        if not item or item.get("guard_only"):
            raise ValueError("Resident Steward action is not executable")
        mode = "AUTO" if policy.get("test_unrestricted") or action in policy.get("auto_actions", []) else "OPERATOR_CONFIRMATION" if action in policy.get("approval_actions", []) else "DISABLED"
        if mode == "DISABLED":
            raise ValueError("Resident Steward action is disabled by policy")
        lineage = self._resident_agent_service._lineage(
            event_id=kwargs.get("event_id"), event_type=kwargs.get("event_type"),
            correlation_id=kwargs.get("correlation_id"), causation_id=kwargs.get("causation_id"),
        )
        body = {"action": str(action), "target_id": str(target_id), "target_type": item.get("target_type"), "action_class": item.get("class"), "policy_mode": mode, "requires_approval": mode == "OPERATOR_CONFIRMATION", "lineage": lineage, "automation_depth": int(kwargs.get("automation_depth", 0) or 0), "changes": [item.get("label", action)], "authority": "hypervisor_service"}
        plan_hash = _canonical_hash(body)
        return {"plan_id": f"steward-plan-{plan_hash.removeprefix('sha256:')[:24]}", "plan_hash": plan_hash, **body}

    def resident_agent_execute_action(self, action: str, *, target_id: str, mode: str = "plan", plan_hash=None, approval_reference=None, **kwargs) -> dict:
        normalized = str(mode or "plan").lower()
        if normalized not in {"plan", "apply"}:
            raise ValueError("Resident Steward actions require mode=plan or mode=apply")
        target = str(target_id or "").strip()
        if not target:
            raise ValueError("target_id is required")
        plan = self._resident_agent_action_plan(str(action), target, **kwargs)
        if normalized == "plan":
            return {"status": "PLAN_CREATED", "plan": plan}
        if str(plan_hash or "") != plan["plan_hash"]:
            raise ValueError("Resident Steward action plan changed; refresh before applying")
        if plan["requires_approval"] and not str(approval_reference or "").strip():
            return {"status": "APPROVAL_REQUIRED", "code": "STEWARD_APPROVAL_REQUIRED", "plan": plan}
        guard = self.resident_agent_guard_action(str(action), target_id=target, **kwargs)
        if not guard.get("allowed"):
            return {"status": "BLOCKED", "code": guard.get("code"), "plan": plan, "guard": guard}
        action_id = str(guard.get("action_id"))
        try:
            self.record_event(event_type="aidn.steward.action_started", message=f"Resident Steward started {action}", details={"action_id": action_id, "action": action, "target_id": target, "plan_hash": plan["plan_hash"]}, source="resident-agent", resource_type="steward_action", resource_id=action_id)
            if action == "provider.health_check":
                result = dict(self.probe_provider_instance(target))
            elif action == "runtime.drain":
                result = dict(self.drain_runtime(target))
            elif action == "runtime.restart":
                result = dict(self.restart_runtime(target))
            elif action == "runtime.stop":
                result = dict(self.force_stop_runtime(target))
            else:
                raise ValueError("Resident Steward action has no dispatcher")
            verification = {"ok": True, "observed": result}
            if action.startswith("runtime."):
                try:
                    verification["observed"] = self.runtime_readiness(target, force=True)
                except Exception as error:
                    verification = {"ok": False, "error": str(error)[:512], "observed": result}
            payload = {"status": "COMPLETED", "action_id": action_id, "plan": plan, "guard": guard, "result": result, "verification": verification}
            self._resident_agent_service.record_action_result(action_id=action_id, action=str(action), target_id=target, status="COMPLETED", result=payload, persist=False)
            self.record_event(event_type="aidn.steward.action_completed", message=f"Resident Steward completed {action}", details={"action_id": action_id, "action": action, "target_id": target, "verification": verification}, source="resident-agent", severity="INFO" if verification.get("ok") else "WARNING", resource_type="steward_action", resource_id=action_id, requires_action=not bool(verification.get("ok")))
            return payload
        except Exception as error:
            failure = {"status": "FAILED", "action_id": action_id, "plan": plan, "guard": guard, "code": "STEWARD_ACTION_FAILED", "error": str(error)[:1024]}
            self._resident_agent_service.record_action_result(action_id=action_id, action=str(action), target_id=target, status="FAILED", error=str(error)[:1024], result=failure, persist=False)
            self.record_event(event_type="aidn.steward.action_failed", message=f"Resident Steward failed {action}", details={"action_id": action_id, "action": action, "target_id": target, "error": str(error)[:512]}, source="resident-agent", severity="ERROR", resource_type="steward_action", resource_id=action_id, requires_action=True)
            return failure

    def escalation_task_create(self, payload: dict, *, owner_id=None, control_session_id=None, budget_remaining_q_atoms=None) -> dict:
        values = dict(payload or {})
        route = dict(values.get("route") or {})
        route.setdefault("capability", "general")
        route.setdefault("complexity", "COMPLEX")
        route.setdefault("data_class", str(values.get("data_class") or "OPERATOR"))
        route.setdefault("minimum_context", 4096)
        decision = self.reasoning_route(route, budget_remaining_q_atoms=budget_remaining_q_atoms)
        return self._escalation_task_service.create(
            goal=values.get("goal"), task_class=values.get("task_class", "REASONING_ESCALATION"), data_class=values.get("data_class", "OPERATOR"), route_decision=decision,
            context=values.get("context") or self.resident_agent_context(), postconditions=values.get("postconditions"), idempotency_key=values.get("idempotency_key"), owner_id=owner_id, control_session_id=control_session_id, correlation_id=values.get("correlation_id"), causation_id=values.get("causation_id"), expires_in_seconds=values.get("expires_in_seconds", 86400),
        )

    def escalation_task_list(self, *, state=None, limit=100) -> list[dict]:
        return self._escalation_task_service.list(state=state, limit=limit)

    def escalation_task_get(self, task_id: str) -> dict:
        return self._escalation_task_service.get(task_id)

    def escalation_task_set_plan(self, task_id: str, plan: dict, *, idempotency_key: str, requires_operator_approval=None) -> dict:
        return self._escalation_task_service.set_plan(task_id, plan, idempotency_key=idempotency_key, requires_operator_approval=requires_operator_approval)

    def escalation_task_approve(self, task_id: str, *, plan_hash: str, approval_reference: str, approver_id: str) -> dict:
        return self._escalation_task_service.approve(task_id, plan_hash=plan_hash, approval_reference=approval_reference, approver_id=approver_id)

    def escalation_task_verify(self, task_id: str, *, observed: dict) -> dict:
        return self._escalation_task_service.verify(task_id, observed=observed)

    def escalation_task_cancel(self, task_id: str, *, reason: str = "cancelled") -> dict:
        return self._escalation_task_service.cancel(task_id, reason=reason)

    def escalation_tasks_snapshot(self) -> list[dict]:
        return self._escalation_task_service.snapshot_state()

    def restore_escalation_tasks(self, snapshot) -> None:
        self._escalation_task_service.restore_state(snapshot)

    def reasoning_provider_registry_snapshot(self) -> dict:
        return self._reasoning_provider_registry.snapshot_state()

    def restore_reasoning_provider_registry(self, snapshot) -> None:
        self._reasoning_provider_registry.restore_state(snapshot)

    def acknowledge_event_inbox(
        self,
        agent_id: str,
        event_ids: list[str],
    ) -> dict:
        return self._event_store.acknowledge(agent_id, event_ids)

    def create_hook(self, **kwargs) -> HookDefinition:
        return self._hook_dispatcher.create_hook(**kwargs)

    def list_hooks(self, *, owner_operator_id: str | None = None) -> list[HookDefinition]:
        return self._hook_dispatcher.list_hooks(owner_operator_id=owner_operator_id)

    def get_hook(self, hook_id: str) -> HookDefinition:
        return self._hook_dispatcher.get_hook(hook_id)

    def update_hook(self, hook_id: str, **updates) -> HookDefinition:
        return self._hook_dispatcher.update_hook(hook_id, **updates)

    def delete_hook(self, hook_id: str) -> bool:
        return self._hook_dispatcher.delete_hook(hook_id)

    def test_hook(self, hook_id: str) -> dict:
        return self._hook_dispatcher.test_hook(hook_id)

    def hook_deliveries(
        self,
        *,
        hook_id: str | None = None,
        status: HookDeliveryState | None = None,
        limit: int = 100,
    ) -> list[HookDeliveryRecord]:
        return self._hook_dispatcher.list_deliveries(
            hook_id=hook_id,
            status=status,
            limit=limit,
        )

    def hook_dead_letters(self, *, limit: int = 100) -> list[HookDeliveryRecord]:
        return self._hook_dispatcher.dead_letters(limit=limit)

    def retry_hook_dead_letter(self, delivery_id: str) -> HookDeliveryRecord:
        return self._hook_dispatcher.retry_dead_letter(delivery_id)

    def replay_hook_event(
        self,
        event_id: str,
        *,
        owner_operator_id: str | None = None,
        target_agent_id: str | None = None,
    ) -> list[HookDeliveryRecord]:
        return self._hook_dispatcher.replay_event(
            event_id,
            owner_operator_id=owner_operator_id,
            target_agent_id=target_agent_id,
        )

    def hook_dispatch_metrics(self) -> dict:
        return self._hook_dispatcher.metrics()

    @property
    def event_store(self) -> EventStore:
        """Expose durable event state to API and Hook adapters."""

        return self._event_store

    @property
    def event_bus(self) -> InternalEventBus:
        """Expose the local bus for local Hook dispatch composition."""

        return self._event_bus

    @property
    def hook_dispatcher(self) -> HookDispatcher:
        """Expose RFC-0072 Hook delivery state to API and MCP adapters."""

        return self._hook_dispatcher

    def list_wallet_usage_events(self, *, limit: int | None = None) -> list[dict]:
        return self._wallet_application_facade().list_wallet_usage_events(limit=limit)

    def list_wallet_session_events(self, *, limit: int | None = None) -> list[dict]:
        return self._wallet_application_facade().list_wallet_session_events(limit=limit)

    def list_wallet_ledger_events(self, *, limit: int | None = None) -> list[dict]:
        return self._wallet_application_facade().list_wallet_ledger_events(limit=limit)

    def list_ledger_operations(self, *, limit: int | None = None) -> list[dict]:
        return self._settlement_application_facade().list_ledger_operations(limit=limit)

    def ledger_operation_finality(self, operation_id: str) -> dict:
        finality_source = self.consensus_finality_source
        if finality_source is not None:
            try:
                evidence = finality_source.finality_evidence(operation_id)
            except Exception:
                evidence = None
            if (
                isinstance(evidence, ConsensusFinalityEvidence)
                and evidence.operation_id == operation_id
            ):
                consensus = self.consensus_service
                if consensus is not None and getattr(consensus, "is_enabled", False):
                    if evidence.chain_id != consensus.config.chain_id:
                        evidence = None
                    else:
                        try:
                            consensus.reconcile_finality(
                                operation_id,
                                finality_source=finality_source,
                            )
                        except Exception:
                            evidence = None
            if (
                isinstance(evidence, ConsensusFinalityEvidence)
                and evidence.operation_id == operation_id
            ):
                return {
                    "status": "consensus_finalized",
                    "consensus_finalized": True,
                    "block_height": evidence.block_height,
                    "finality_evidence": evidence.model_dump(),
                }
        consensus = self.consensus_service
        if consensus is None or not getattr(consensus, "is_enabled", False):
            return {
                "status": "local_only",
                "consensus_finalized": False,
                "finality_evidence": None,
            }
        submission = consensus.get_submission(operation_id)
        if submission is None:
            return {
                "status": "not_submitted",
                "consensus_finalized": False,
                "finality_evidence": None,
            }
        status = submission.status.value
        return {
            "status": "locally_observed_finalized" if status == "finalized" else status,
            "consensus_finalized": False,
            "block_height": submission.block_height,
            "finality_evidence": None,
        }

    @property
    def ledger_operation_service(self) -> LedgerOperationService:
        """Expose the canonical ledger dependency for application composition."""
        return self._ledger_operation_service

    def stage_consensus_operation(self, operation: dict) -> dict:
        operation_id = operation.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("pending consensus operation ID is invalid")
        existing = self._pending_consensus_operations.get(operation_id)
        if existing is not None:
            if existing != operation:
                raise ValueError("conflicting pending consensus operation")
            return deepcopy(existing)
        self._pending_consensus_operations[operation_id] = deepcopy(operation)
        self._persist_state()
        return deepcopy(operation)

    def stage_pending_consensus_envelope(
        self, envelope: LedgerOperationEnvelope | dict
    ) -> dict:
        """Persist one exact consensus envelope before network submission."""
        typed = LedgerOperationEnvelope.model_validate(envelope)
        operation_id = typed.operation_id
        payload = typed.model_dump(mode="json")
        existing = self._pending_consensus_envelopes.get(operation_id)
        if existing is not None:
            if existing != payload:
                raise ValueError("conflicting pending consensus envelope")
            return deepcopy(existing)
        self._pending_consensus_envelopes[operation_id] = deepcopy(payload)
        self._persist_state()
        return deepcopy(payload)

    def get_pending_consensus_envelope(
        self, operation_id: str
    ) -> LedgerOperationEnvelope | None:
        """Return the exact persisted envelope for one pending operation."""
        payload = self._pending_consensus_envelopes.get(operation_id)
        if payload is None:
            return None
        return LedgerOperationEnvelope.model_validate(deepcopy(payload))

    def find_pending_consensus_envelope(
        self,
        *,
        operation_type: str,
        predicate=None,
    ) -> LedgerOperationEnvelope | None:
        """Find a persisted envelope by operation type and semantic predicate."""
        for payload in reversed(list(self._pending_consensus_envelopes.values())):
            try:
                envelope = LedgerOperationEnvelope.model_validate(deepcopy(payload))
            except ValueError:
                continue
            if envelope.operation_type != operation_type:
                continue
            if predicate is None or predicate(envelope):
                return envelope
        return None

    def list_pending_consensus_envelopes(self) -> list[LedgerOperationEnvelope]:
        """Return all pending envelopes for conflict-aware recovery checks."""
        envelopes: list[LedgerOperationEnvelope] = []
        for payload in self._pending_consensus_envelopes.values():
            try:
                envelopes.append(LedgerOperationEnvelope.model_validate(deepcopy(payload)))
            except ValueError:
                continue
        return envelopes

    def discard_pending_consensus_envelopes(self, *operation_ids: str) -> None:
        """Remove envelopes once their canonical projections are local."""
        changed = False
        for operation_id in operation_ids:
            changed = (
                self._pending_consensus_envelopes.pop(operation_id, None) is not None
                or changed
            )
        if changed:
            self._persist_state()

    def get_local_consensus_operation(self, operation_id: str) -> dict | None:
        operation = self._ledger_operation_service.get_operation(operation_id)
        if operation is not None:
            return operation
        pending = self._pending_consensus_operations.get(operation_id)
        return deepcopy(pending) if pending is not None else None

    def find_pending_consensus_operation(
        self,
        *,
        operation_type: str,
        payload_fields: dict[str, object],
    ) -> dict | None:
        for operation in reversed(list(self._pending_consensus_operations.values())):
            if operation.get("operation_type") != operation_type:
                continue
            payload = operation.get("payload")
            if isinstance(payload, dict) and all(
                payload.get(key) == value for key, value in payload_fields.items()
            ):
                return deepcopy(operation)
        return None

    def discard_pending_consensus_operations(self, *operation_ids: str) -> None:
        changed = False
        for operation_id in operation_ids:
            changed = self._pending_consensus_operations.pop(operation_id, None) is not None or changed
        if changed:
            self._persist_state()

    def export_ledger_operations(
        self,
        *,
        after_operation_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._settlement_application_facade().export_ledger_operations(
            after_operation_id=after_operation_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def wallet_next_operation_sequence(self, wallet_id: str) -> int:
        return self._settlement_application_facade().wallet_next_operation_sequence(
            wallet_id
        )

    def wallet_q_atom_balance(self, wallet_id: str) -> int:
        return self._settlement_application_facade().wallet_q_atom_balance(wallet_id)

    def wallet_balance_read_model(self, wallet_id: str) -> dict:
        """Return the best available wallet balance without relabelling local state.

        Non-validator nodes keep a local Ledger projection for operational
        recovery, but it cannot be presented as canonical when a remote
        quorum source is configured.
        """
        local_balance = self.wallet_q_atom_balance(wallet_id)
        provider = self.canonical_wallet_balance_provider
        if provider is None:
            return {
                "q_atoms": local_balance,
                "source": "consensus_projection"
                if bool(self.consensus_service and self.consensus_service.is_validator)
                else "local_projection",
                "error": None,
            }
        try:
            return {
                "q_atoms": int(provider(wallet_id)),
                "source": "remote_consensus_quorum",
                "error": None,
            }
        except Exception as error:
            return {
                "q_atoms": local_balance,
                "source": "local_projection_unverified",
                "error": f"{type(error).__name__}: {error}",
            }

    def wallet_identity_read_model(self, wallet_id: str) -> dict:
        """Return a Wallet identity without representing a stale local copy as canonical."""
        local_identity = self.resolve_wallet_identity(wallet_id)
        provider = self.canonical_wallet_identity_provider
        if provider is None:
            # An external-RPC non-validator has a live ConsensusService but
            # may not have the optional multi-RPC finality config.  Prefer the
            # active CometBFT ABCI read in that case; otherwise a local wallet
            # projection can incorrectly claim that identity registration has
            # already finalized on the remote chain.
            consensus = self.consensus_service
            query_identity = getattr(consensus, "query_wallet_identity", None)
            if consensus is not None and bool(getattr(consensus, "is_enabled", False)) and callable(query_identity):
                try:
                    return {
                        "identity": query_identity(wallet_id),
                        "source": "consensus_rpc",
                        "error": None,
                    }
                except Exception as error:
                    return {
                        "identity": local_identity,
                        "source": "local_projection_unverified",
                        "error": f"{type(error).__name__}: {error}",
                    }
            return {
                "identity": local_identity,
                "source": "consensus_projection"
                if bool(self.consensus_service and self.consensus_service.is_validator)
                else "local_projection",
                "error": None,
            }
        try:
            return {
                "identity": provider(wallet_id),
                "source": "remote_consensus_quorum",
                "error": None,
            }
        except Exception as error:
            return {
                "identity": local_identity,
                "source": "local_projection_unverified",
                "error": f"{type(error).__name__}: {error}",
            }

    def get_session_funding_account(self, session_id: str) -> SessionFundingAccount:
        return self._settlement_application_facade().get_session_funding_account(
            session_id
        )

    def credit_wallet_q_atoms(self, *, wallet_id: str, amount_q_atoms: int) -> int:
        return self._settlement_application_facade().credit_wallet_q_atoms(
            wallet_id=wallet_id,
            amount_q_atoms=amount_q_atoms,
        )

    def lock_session_funding(self, funding, *, created_at: str | None = None):
        return self._settlement_application_facade().lock_session_funding(
            funding,
            created_at=created_at,
        )

    def apply_settlement_evaluation(self, evaluation, *, created_at: str | None = None):
        return self._settlement_application_facade().apply_settlement_evaluation(
            evaluation,
            created_at=created_at,
        )

    def propose_settlement(self, evaluation, *, created_at: str | None = None):
        return self._settlement_application_facade().propose_settlement(
            evaluation,
            created_at=created_at,
        )

    def accept_settlement(self, acceptance, *, created_at: str | None = None):
        return self._settlement_application_facade().accept_settlement(
            acceptance,
            created_at=created_at,
        )

    def submit_consensus_cooperative_settlement(
        self,
        evaluation,
        acceptance,
        *,
        created_at: str | None = None,
        signatures: list[str] | None = None,
    ):
        return self._settlement_application_facade().submit_consensus_cooperative_settlement(
            evaluation,
            acceptance,
            created_at=created_at,
            signatures=signatures,
        )

    def finalize_accepted_settlement(self, evaluation, *, created_at: str | None = None):
        return self._settlement_application_facade().finalize_accepted_settlement(
            evaluation,
            created_at=created_at,
        )

    def force_finalize_fixed_price_settlement(self, evaluation, **kwargs):
        return self._settlement_application_facade().force_finalize_fixed_price_settlement(
            evaluation,
            **kwargs,
        )

    def prepare_force_settlement_operation(self, evaluation, **kwargs):
        return self._settlement_application_facade().prepare_force_settlement_operation(
            evaluation,
            **kwargs,
        )

    def apply_prepared_force_settlement(
        self,
        evaluation,
        *,
        force_operation_id: str,
        created_at: str | None = None,
    ):
        return self._settlement_application_facade().apply_prepared_force_settlement(
            evaluation,
            force_operation_id=force_operation_id,
            created_at=created_at,
        )

    def open_mvp_fixed_price_session(
        self,
        *,
        session_service,
        endpoint,
        client_wallet: str,
        deposit_q_atoms: int,
        fixed_price_q_atoms: int,
        network_fee_reserve_q_atoms: int = 0,
        accounting_contract: dict | None = None,
        consumer_authorization_public_key: str | None = None,
        consumer_authorization: dict | None = None,
        require_wallet_authorization: bool = False,
        session_id: str | None = None,
        consensus_sender_sequence: int | None = None,
        consensus_lock_signatures: list[str] | None = None,
    ):
        return self._settlement_application_facade().open_mvp_fixed_price_session(
            session_service=session_service,
            endpoint=endpoint,
            client_wallet=client_wallet,
            deposit_q_atoms=deposit_q_atoms,
            fixed_price_q_atoms=fixed_price_q_atoms,
            network_fee_reserve_q_atoms=network_fee_reserve_q_atoms,
            accounting_contract=accounting_contract,
            consumer_authorization_public_key=consumer_authorization_public_key,
            consumer_authorization=consumer_authorization,
            require_wallet_authorization=require_wallet_authorization,
            session_id=session_id,
            consensus_sender_sequence=consensus_sender_sequence,
            consensus_lock_signatures=consensus_lock_signatures,
        )

    def build_mvp_fixed_price_settlement_evaluation(
        self,
        *,
        session_service,
        session_id: str,
        request_id: str,
        actual_network_fees_q_atoms: int = 0,
        settlement_sequence: int = 1,
        proposal_expiration: str | None = None,
    ):
        return self._settlement_application_facade().build_mvp_fixed_price_settlement_evaluation(
            session_service=session_service,
            session_id=session_id,
            request_id=request_id,
            actual_network_fees_q_atoms=actual_network_fees_q_atoms,
            settlement_sequence=settlement_sequence,
            proposal_expiration=proposal_expiration,
        )

    def build_mvp_endpoint_unavailable_refund_evaluation(
        self,
        *,
        session_service,
        session_id: str,
        actual_network_fees_q_atoms: int = 0,
        settlement_sequence: int = 1,
        proposal_expiration: str | None = None,
    ):
        return self._settlement_application_facade().build_mvp_endpoint_unavailable_refund_evaluation(
            session_service=session_service,
            session_id=session_id,
            actual_network_fees_q_atoms=actual_network_fees_q_atoms,
            settlement_sequence=settlement_sequence,
            proposal_expiration=proposal_expiration,
        )

    def finalize_mvp_fixed_price_session(
        self,
        *,
        session_service,
        session_id: str,
        request_id: str,
        consumer_signature: str,
        actual_network_fees_q_atoms: int = 0,
        settlement_sequence: int = 1,
        proposal_expiration: str | None = None,
        accepted_at: str | None = None,
    ):
        return self._settlement_application_facade().finalize_mvp_fixed_price_session(
            session_service=session_service,
            session_id=session_id,
            request_id=request_id,
            consumer_signature=consumer_signature,
            actual_network_fees_q_atoms=actual_network_fees_q_atoms,
            settlement_sequence=settlement_sequence,
            proposal_expiration=proposal_expiration,
            accepted_at=accepted_at,
        )

    def force_finalize_mvp_fixed_price_session(
        self,
        *,
        session_service,
        session_id: str,
        reason: str,
        force_after: str,
        request_id: str | None = None,
        now: str | None = None,
        actual_network_fees_q_atoms: int = 0,
        settlement_sequence: int = 1,
        consensus_sender_sequence: int | None = None,
        consensus_lock_signatures: list[str] | None = None,
        consensus_failure_signatures: list[str] | None = None,
        consensus_initiator_wallet: str | None = None,
        consensus_initiator_signature: str | None = None,
        consensus_observed_at: str | None = None,
        consensus_force_signatures: list[str] | None = None,
    ):
        return self._settlement_application_facade().force_finalize_mvp_fixed_price_session(
            session_service=session_service,
            session_id=session_id,
            reason=reason,
            force_after=force_after,
            request_id=request_id,
            now=now,
            actual_network_fees_q_atoms=actual_network_fees_q_atoms,
            settlement_sequence=settlement_sequence,
            consensus_sender_sequence=consensus_sender_sequence,
            consensus_lock_signatures=consensus_lock_signatures,
            consensus_failure_signatures=consensus_failure_signatures,
            consensus_initiator_wallet=consensus_initiator_wallet,
            consensus_initiator_signature=consensus_initiator_signature,
            consensus_observed_at=consensus_observed_at,
            consensus_force_signatures=consensus_force_signatures,
        )

    def commit_session_failure_evidence(
        self,
        *,
        session_id: str,
        failure_class: str,
        failure_evidence_root: str,
        details: str | None = None,
        created_at: str | None = None,
    ) -> dict:
        return self._settlement_application_facade().commit_session_failure_evidence(
            session_id=session_id,
            failure_class=failure_class,
            failure_evidence_root=failure_evidence_root,
            details=details,
            created_at=created_at,
        )

    def submit_consensus_session_failure_chain(self, **kwargs):
        """Advance local Session failure evidence through canonical consensus."""
        return self._settlement_application_facade().submit_consensus_session_failure_chain(
            **kwargs
        )

    def record_ledger_operation(
        self,
        *,
        operation_type: str,
        origin_type: str,
        fee_class: str,
        initiator_id: str | None = None,
        sender_wallet: str | None = None,
        fee_payer: str | None = None,
        payload: dict | None = None,
        created_at: str | None = None,
        expires_at: str | None = None,
        target_epoch: str | None = None,
        evidence_references: list[str] | None = None,
        signatures: list[str] | None = None,
        emitted_events: list[str] | None = None,
        expected_sequence: int | None = None,
        operation_version: str = "0.1",
    ) -> dict:
        return self._settlement_application_facade().record_ledger_operation(
            operation_type=operation_type,
            origin_type=origin_type,
            fee_class=fee_class,
            initiator_id=initiator_id,
            sender_wallet=sender_wallet,
            fee_payer=fee_payer,
            payload=payload,
            created_at=created_at,
            expires_at=expires_at,
            target_epoch=target_epoch,
            evidence_references=evidence_references,
            signatures=signatures,
            emitted_events=emitted_events,
            expected_sequence=expected_sequence,
            operation_version=operation_version,
        )

    def list_recyclable_removals(self) -> list[dict]:
        return self._wallet_application_facade().list_recyclable_removals()

    def list_faucet_claims(self) -> list[dict]:
        return self._wallet_application_facade().list_faucet_claims()

    def list_epoch_reward_budgets(self) -> list[dict]:
        return self._wallet_application_facade().list_epoch_reward_budgets()

    def get_faucet_claim_preview(self) -> dict:
        return self._wallet_application_facade().get_faucet_claim_preview()

    def get_wallet_economics_summary(self, *, recent_limit: int = 10) -> dict:
        return self._wallet_application_facade().get_wallet_economics_summary(
            recent_limit=recent_limit
        )

    def claim_faucet_share(self) -> dict:
        return self._wallet_application_facade().claim_faucet_share()

    def list_wallet_allocation_events(self, *, limit: int | None = None) -> list[dict]:
        return self._wallet_application_facade().list_wallet_allocation_events(
            limit=limit
        )

    def list_wallet_allocation_activation_events(
        self, *, limit: int | None = None
    ) -> list[dict]:
        return self._wallet_application_facade().list_wallet_allocation_activation_events(
            limit=limit
        )

    def list_wallet_allocation_dispute_events(
        self, *, limit: int | None = None
    ) -> list[dict]:
        return self._wallet_application_facade().list_wallet_allocation_dispute_events(
            limit=limit
        )

    def export_wallet_usage_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._wallet_application_facade().export_wallet_usage_events(
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_session_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._wallet_application_facade().export_wallet_session_events(
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_ledger_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._wallet_application_facade().export_wallet_ledger_events(
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_economics_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._wallet_application_facade().export_wallet_economics_events(
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_allocation_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._wallet_application_facade().export_wallet_allocation_events(
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_allocation_activation_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._wallet_application_facade().export_wallet_allocation_activation_events(
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_allocation_dispute_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._wallet_application_facade().export_wallet_allocation_dispute_events(
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def _append_wallet_ledger_event(
        self,
        *,
        stream: str,
        source_event: dict,
        event_type: str,
        owner_id: str,
        task_id: str | None = None,
        allocation_id: str | None = None,
        session_id: str | None = None,
        endpoint_id: str | None = None,
        bundle_id: str | None = None,
        workload_type: str | None = None,
        status: str | None = None,
        settlement_status: str | None = None,
        amount_q: float = 0.0,
    ) -> dict:
        return self._wallet_economics_service.append_wallet_ledger_event(
            stream=stream,
            source_event=source_event,
            event_type=event_type,
            owner_id=owner_id,
            task_id=task_id,
            allocation_id=allocation_id,
            session_id=session_id,
            endpoint_id=endpoint_id,
            bundle_id=bundle_id,
            workload_type=workload_type,
            status=status,
            settlement_status=settlement_status,
            amount_q=amount_q,
        )

    def _append_wallet_economics_event(
        self,
        *,
        event_type: str,
        occurred_at: str,
        owner_id: str,
        status: str | None = None,
        amount_q: float = 0.0,
        payload: dict,
    ) -> dict:
        return self._wallet_economics_service.append_wallet_economics_event(
            event_type=event_type,
            occurred_at=occurred_at,
            owner_id=owner_id,
            status=status,
            amount_q=amount_q,
            payload=payload,
        )

    def record_recyclable_removal(
        self,
        *,
        category: str,
        amount_q: float,
        owner_id: str,
        source_event_type: str,
        source_reference: str,
        source_epoch_id: str | None = None,
        removed_at: str | None = None,
    ) -> dict:
        return self._wallet_economics_service.record_recyclable_removal(
            category=category,
            amount_q=amount_q,
            owner_id=owner_id,
            source_event_type=source_event_type,
            source_reference=source_reference,
            source_epoch_id=source_epoch_id,
            removed_at=removed_at,
        )

    def derive_epoch_reward_budget(
        self,
        *,
        epoch_id: str,
        source_epoch_id: str,
        recycle_backlog_q: float = 0.0,
        faucet_carryover_q: float = 0.0,
        active_hypervisor_count: int = 0,
    ) -> dict:
        return self._wallet_economics_service.derive_epoch_reward_budget(
            epoch_id=epoch_id,
            source_epoch_id=source_epoch_id,
            recycle_backlog_q=recycle_backlog_q,
            faucet_carryover_q=faucet_carryover_q,
            active_hypervisor_count=active_hypervisor_count,
        )

    def reopen_wallet_allocation_event(
        self, event_id: str, *, reason: str | None = None
    ) -> dict:
        return self._wallet_application_facade().reopen_wallet_allocation_event(
            event_id,
            reason=reason,
        )

    def dispute_wallet_allocation_event(self, event_id: str, *, reason: str) -> dict:
        return self._wallet_application_facade().dispute_wallet_allocation_event(
            event_id,
            reason=reason,
        )

    def resolve_wallet_allocation_dispute(
        self,
        event_id: str,
        *,
        resolution: str,
        reason: str | None = None,
    ) -> dict:
        return self._wallet_application_facade().resolve_wallet_allocation_dispute(
            event_id,
            resolution=resolution,
            reason=reason,
        )

    def hold_wallet_allocation_event(self, event_id: str, *, reason: str) -> dict:
        return self._wallet_application_facade().hold_wallet_allocation_event(
            event_id,
            reason=reason,
        )

    def release_wallet_allocation_event(
        self,
        event_id: str,
        *,
        reason: str,
        target_status: str = "closed",
    ) -> dict:
        return self._wallet_application_facade().release_wallet_allocation_event(
            event_id,
            reason=reason,
            target_status=target_status,
        )

    def apply_wallet_allocation_correction(
        self,
        event_id: str,
        *,
        reason: str,
        effective_usage_total_q: float,
        annotations: dict | None = None,
        resolution_note: str | None = None,
    ) -> dict:
        return self._wallet_application_facade().apply_wallet_allocation_correction(
            event_id,
            reason=reason,
            effective_usage_total_q=effective_usage_total_q,
            annotations=annotations,
            resolution_note=resolution_note,
        )

    def list_wallet_allocation_correction_events(
        self, *, limit: int | None = None
    ) -> list[dict]:
        return self._wallet_application_facade().list_wallet_allocation_correction_events(
            limit=limit
        )

    def export_wallet_allocation_correction_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._wallet_application_facade().export_wallet_allocation_correction_events(
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def _export_wallet_event_stream(
        self,
        events: list[dict],
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._wallet_economics_service.export_wallet_event_stream(
            events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def task_history(self, task_id: str) -> list[JournalEvent]:
        return self._task_lifecycle_facade().task_history(task_id)

    def quote_wallet_usage(
        self,
        *,
        input_tokens: int | None,
        cached_input_tokens: int | None = None,
        output_tokens: int | None = None,
        fixed_request_count: int = 1,
        audio_input_seconds: float | None = None,
        audio_input_milliseconds: int | None = None,
    ) -> dict:
        return self._wallet_application_facade().quote_wallet_usage(
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            fixed_request_count=fixed_request_count,
            audio_input_seconds=audio_input_seconds,
            audio_input_milliseconds=audio_input_milliseconds,
        )

    def record_wallet_usage(
        self,
        *,
        owner_id: str,
        bundle_id: str,
        workload_type: str,
        task_id: str | None = None,
        allocation_id: str | None = None,
        input_tokens: int | None,
        cached_input_tokens: int | None = None,
        output_tokens: int | None = None,
        fixed_request_count: int = 1,
        audio_input_seconds: float | None = None,
        audio_input_milliseconds: int | None = None,
        measurement_kind: str = "exact",
        measurement_source: str = "manual",
        source: str = "manual",
    ) -> dict:
        return self._wallet_application_facade().record_wallet_usage(
            owner_id=owner_id,
            bundle_id=bundle_id,
            workload_type=workload_type,
            task_id=task_id,
            allocation_id=allocation_id,
            input_tokens=input_tokens,
            cached_input_tokens=cached_input_tokens,
            output_tokens=output_tokens,
            fixed_request_count=fixed_request_count,
            audio_input_seconds=audio_input_seconds,
            audio_input_milliseconds=audio_input_milliseconds,
            measurement_kind=measurement_kind,
            measurement_source=measurement_source,
            source=source,
        )

    def _record_wallet_allocation_event(self, allocation: dict, *, status: str) -> dict:
        return self._wallet_allocation_service.record_wallet_allocation_event(
            allocation,
            status=status,
        )

    def _record_wallet_allocation_activation_hook(
        self, allocation: dict, *, activation_source: str
    ) -> None:
        self._wallet_allocation_service.record_wallet_allocation_activation_hook(
            allocation,
            activation_source=activation_source,
        )

    def _reconcile_wallet_allocation_events(self) -> None:
        self._wallet_allocation_service.reconcile_wallet_allocation_events()

    def list_allocations(self) -> list[dict]:
        return self._allocation_lifecycle_facade().list_allocations()

    def get_allocation(self, allocation_id: str) -> dict:
        return self._allocation_lifecycle_facade().get_allocation(allocation_id)

    def reconcile_allocation(self, allocation_id: str) -> dict:
        return self._allocation_lifecycle_facade().reconcile_allocation(allocation_id)

    def create_allocation(self, request: AllocationRequest) -> dict:
        return self._allocation_lifecycle_facade().create_allocation(request)

    def release_allocation(self, allocation_id: str) -> dict:
        return self._allocation_lifecycle_facade().release_allocation(allocation_id)

    def capability_inventory(self) -> list[dict]:
        self.refresh_runtime_health()
        return [
            {
                "bundle_id": bundle.bundle_id,
                "workload_type": bundle.workload_type,
                "enabled": bundle.enabled,
                "status": self._bundle_inventory_status(bundle),
                "endpoint": bundle.endpoint,
            }
            for bundle in self.bundles
        ]

    def node_advertisement(self, *, heartbeat_at: str | None = None) -> dict:
        return self._network_projection_service.node_advertisement(
            heartbeat_at=heartbeat_at
        )

    def _node_advertisement_status(
        self,
        *,
        heartbeat_at: str,
        heartbeat_ttl_seconds: int,
    ) -> str:
        return self._network_projection_service.node_advertisement_status(
            heartbeat_at=heartbeat_at,
            heartbeat_ttl_seconds=heartbeat_ttl_seconds,
        )

    def _publication_sync_status(
        self,
        *,
        local_configuration_hash: str | None,
        published_configuration_hash: str | None,
    ) -> str:
        return self._network_projection_service.publication_sync_status(
            local_configuration_hash=local_configuration_hash,
            published_configuration_hash=published_configuration_hash,
        )

    def _validation_summary_for(
        self,
        *,
        endpoint_id: str,
        configuration_hash: str | None,
    ) -> dict | None:
        return self._network_projection_service.validation_summary_for(
            endpoint_id=endpoint_id,
            configuration_hash=configuration_hash,
        )

    def _operational_reputation_stats(self) -> dict[str, int]:
        return self._network_projection_service.operational_reputation_stats()

    def capability_catalog(
        self,
        *,
        owner_id: str,
        workload_type: str | None = None,
        bundle_id: str | None = None,
        include_disabled: bool = False,
    ) -> dict:
        return self._network_projection_service.capability_catalog(
            owner_id=owner_id,
            workload_type=workload_type,
            bundle_id=bundle_id,
            include_disabled=include_disabled,
        )

    def owner_wallet_state(self) -> dict:
        return self._operator_application_facade().owner_wallet_state()

    def owner_wallet_private_key(self) -> str:
        return self._operator_application_facade().owner_wallet_private_key()

    def node_identity(self) -> dict:
        return self._operator_application_facade().node_identity()

    def registry_enabled(self) -> bool:
        return self._operator_application_facade().registry_enabled()

    def validation_enabled(self) -> bool:
        return self._operator_application_facade().validation_enabled()

    def canonical_overlay_inventory(self) -> dict:
        return self._operator_application_facade().canonical_overlay_inventory()

    def configure_owner_wallet(
        self,
        *,
        mode: str,
        label: str | None = None,
        private_key: str | None = None,
    ) -> dict:
        return self._operator_application_facade().configure_owner_wallet(
            mode=mode,
            label=label,
            private_key=private_key,
        )

    def operator_onboarding_state(self) -> dict:
        return self._operator_application_facade().operator_onboarding_state()

    def sync_operator_onboarding_state(
        self,
        *,
        endpoint_items: list[dict],
        last_workspace: str | None = None,
    ) -> dict:
        return self._operator_application_facade().sync_operator_onboarding_state(
            endpoint_items=endpoint_items,
            last_workspace=last_workspace,
        )

    def operator_dashboard_home(self) -> dict:
        return self._operator_application_facade().operator_dashboard_home()

    def operator_dashboard_fleet(self) -> dict:
        return self._operator_application_facade().operator_dashboard_fleet()

    def operator_dashboard_resources(self) -> dict:
        """Return the bounded Resource Broker projection used by the dashboard.

        Resource admission remains authoritative in the broker.  This is a
        read-only view, deliberately kept on the service façade so the API,
        Resident Steward and Dashboard receive the same current state.
        """

        from aidn_hypervisor.resource_broker_read_models import (
            build_resource_broker_dashboard_payload,
        )

        return build_resource_broker_dashboard_payload(service=self)

    def operator_dashboard_endpoints(self) -> dict:
        return self._operator_application_facade().operator_dashboard_endpoints()

    def operator_requests_policy(self) -> dict[str, bool | str]:
        return self._operator_application_facade().operator_requests_policy()

    def update_operator_requests_policy(
        self,
        *,
        allow_spillover: bool,
        dispatch_strategy: str,
        ready_endpoint_only: bool,
    ) -> dict[str, bool | str]:
        return self._operator_application_facade().update_operator_requests_policy(
            allow_spillover=allow_spillover,
            dispatch_strategy=dispatch_strategy,
            ready_endpoint_only=ready_endpoint_only,
        )

    def operator_dashboard_requests(
        self,
        *,
        market_candidates: list[dict] | None = None,
    ) -> dict:
        return self._operator_application_facade().operator_dashboard_requests(
            market_candidates=market_candidates,
        )

    def request_model_install(
        self,
        *,
        provider_type: str,
        model_id: str,
        source_url: str,
        requested_by: str,
        expected_sha256: str | None = None,
        expected_bytes: int | None = None,
        runtime_parameter_policy: dict | None = None,
        resident_adapter_requested: bool = False,
        resident_execution_profile: str | None = None,
        resident_resource_request: dict | None = None,
        resident_fallback_enabled: bool = True,
    ) -> dict:
        return self._model_install_facade().request_model_install(
            provider_type=provider_type,
            model_id=model_id,
            source_url=source_url,
            requested_by=requested_by,
            expected_sha256=expected_sha256,
            expected_bytes=expected_bytes,
            runtime_parameter_policy=runtime_parameter_policy,
            resident_adapter_requested=resident_adapter_requested,
            resident_execution_profile=resident_execution_profile,
            resident_resource_request=resident_resource_request,
            resident_fallback_enabled=resident_fallback_enabled,
        )

    def list_model_installs(self) -> list[dict]:
        return self._model_install_facade().list_model_installs()

    def process_model_installs(
        self,
        *,
        limit: int | None = None,
        install_id: str | None = None,
    ) -> list[dict]:
        return self._model_install_facade().process_model_installs(
            limit=limit,
            install_id=install_id,
        )

    def attach_provider_instance(
        self,
        *,
        plugin_id: str,
        display_name: str,
        configuration: dict,
    ) -> dict:
        return self._provider_installation_facade().attach_provider_instance(
            plugin_id=plugin_id,
            display_name=display_name,
            configuration=configuration,
        )

    def detach_provider_instance(self, provider_instance_id: str) -> dict:
        return self._provider_installation_facade().detach_provider_instance(
            provider_instance_id,
        )

    def list_provider_instances(self) -> list[dict]:
        return self._provider_installation_facade().list_provider_instances()

    def list_model_deployments(self) -> list[dict]:
        return self._provider_installation_facade().list_model_deployments()

    def list_runtime_bindings(self) -> list[dict]:
        return self._runtime_boundary.list_runtime_bindings()

    def build_provider_installation_plan(
        self,
        *,
        plugin_id: str,
        configuration: dict,
    ) -> dict:
        return self._provider_installation_facade().build_provider_installation_plan(
            plugin_id=plugin_id,
            configuration=configuration,
        )

    def installation_plan(self) -> dict:
        """Return the bounded plan plus a read-only state-machine projection.

        The persisted plan is operator intent; the workflow projection joins it
        with current provider/model/Bundle/Endpoint read models.  Keeping this
        aggregation on the service façade gives the dashboard and Resident
        Steward one source of truth after restarts.
        """

        plan = read_installation_plan()
        if not plan.get("available"):
            return plan

        def _dump(item) -> dict:
            if isinstance(item, dict):
                return dict(item)
            model_dump = getattr(item, "model_dump", None)
            if callable(model_dump):
                return dict(model_dump(mode="json"))
            return {}

        endpoint_service = getattr(self, "endpoint_service", None)
        endpoint_items = (
            [_dump(item) for item in endpoint_service.list_endpoints()]
            if endpoint_service is not None
            else []
        )
        bundle_items = [_dump(item) for item in self.bundle_config()]
        try:
            provider_installation_jobs = self.list_provider_installation_jobs()
        except AttributeError:
            # Minimal test/fallback inventories may expose provider instances
            # without the optional durable installation-job read model.
            provider_installation_jobs = []
        try:
            provider_installation_approvals = self.list_provider_installation_approvals()
        except AttributeError:
            provider_installation_approvals = []
        workflow = build_installation_workflow_projection(
            plan,
            provider_instances=self.list_provider_instances(),
            provider_installation_jobs=provider_installation_jobs,
            provider_installation_approvals=provider_installation_approvals,
            model_installs=self.list_model_installs(),
            bundles=bundle_items,
            endpoints=endpoint_items,
        )
        wallet = self.owner_wallet_state()
        public_key = str(wallet.get("public_key") or "")
        completion_report = {
            "generated_at": workflow.get("checked_at"),
            "node": {
                "node_id": self.node_id,
                "operator_id": self.operator_id,
                "base_url": self.base_url,
            },
            "wallet": {
                "configured": bool(wallet.get("configured")),
                "wallet_id": wallet.get("wallet_id"),
                "public_key": public_key or None,
                "public_key_fingerprint": (
                    f"sha256:{hashlib.sha256(public_key.encode('utf-8')).hexdigest()[:16]}"
                    if public_key
                    else None
                ),
                "private_key": "NOT_EXPOSED",
            },
            "installation": {
                "mode": plan.get("mode"),
                "provider": plan.get("provider"),
                "model_id": (plan.get("model") or {}).get("id") if isinstance(plan.get("model"), dict) else None,
                "workflow_status": workflow.get("status"),
            },
            "security": {
                "secret_material_included": False,
                "message": "Private keys and recovery seeds are never returned by the Dashboard API.",
            },
        }
        event_intelligence = getattr(self, "_steward_event_intelligence", None)
        steward_context = build_safe_steward_context(
            installation_plan={**plan, "workflow": workflow},
            node_identity=self.node_identity(),
            wallet_state=wallet,
            inference_state=self.resident_inference_status(),
            event_intelligence=(
                event_intelligence.latest_advisory()
                if event_intelligence is not None
                else None
            ),
        )
        return {
            **plan,
            "workflow": workflow,
            "completion_report": completion_report,
            "steward_handoff": {
                "ready": str(self.resident_inference_status().get("state") or "").upper() == "RUNNING",
                "welcome": "I am your local Resident Steward. I can explain the observed node state and guide the next reviewed setup step.",
                "suggested_questions": compose_steward_prompt("Summarize the next safe step.", steward_context)["suggested_questions"],
                "prompt": {"id": STEWARD_PROMPT_ID, "version": STEWARD_PROMPT_VERSION},
            },
        }

    def apply_installation_plan(
        self,
        *,
        plan_hash: str,
        actor: str = "operator",
        idempotency_key: str | None = None,
        action: str = "prepare_review",
    ) -> dict:
        """Prepare the next approved assisted-installation lifecycle step.

        The prepared review is durable in ``installation-plan.json``.  It is
        deliberately not a generic installer: provider installation still
        follows its own approval, model download its own queue, and endpoint
        publication its validation/policy boundary.
        """

        if action not in {
            "prepare_review",
            "prepare_assisted_installation_review",
            "apply_provider_installation",
            "request_model_install",
            "process_model_install",
            "create_bundle",
            "create_private_endpoint",
            "forecast_private_endpoint",
            "start_private_endpoint",
        }:
            raise ValueError(f"unsupported installation plan action: {action}")
        if action in {"prepare_review", "prepare_assisted_installation_review"}:
            result = prepare_assisted_installation_review(
                None,
                expected_hash=plan_hash,
                actor=actor,
                idempotency_key=idempotency_key,
                provider_plan_builder=lambda plugin_id, configuration: self.build_provider_installation_plan(
                    plugin_id=plugin_id,
                    configuration=configuration,
                ),
            )
        elif action == "request_model_install":
            result = self._request_model_from_installation_plan(
                plan_hash=plan_hash,
                actor=actor,
                idempotency_key=idempotency_key,
            )
        elif action == "apply_provider_installation":
            result = self._apply_provider_from_installation_plan(
                plan_hash=plan_hash,
                actor=actor,
                idempotency_key=idempotency_key,
            )
        elif action == "process_model_install":
            result = self._process_model_from_installation_plan(
                plan_hash=plan_hash,
                actor=actor,
                idempotency_key=idempotency_key,
            )
        elif action == "create_bundle":
            result = self._create_bundle_from_installation_plan(
                plan_hash=plan_hash,
                actor=actor,
                idempotency_key=idempotency_key,
            )
        elif action == "create_private_endpoint":
            result = self._create_private_endpoint_from_installation_plan(
                plan_hash=plan_hash,
                actor=actor,
                idempotency_key=idempotency_key,
            )
        elif action == "forecast_private_endpoint":
            result = self._forecast_private_endpoint_from_installation_plan(
                plan_hash=plan_hash,
                actor=actor,
                idempotency_key=idempotency_key,
            )
        else:
            result = self._start_private_endpoint_from_installation_plan(
                plan_hash=plan_hash,
                actor=actor,
                idempotency_key=idempotency_key,
            )
        event_type_by_action = {
            "prepare_review": "installation.plan.review_prepared",
            "prepare_assisted_installation_review": "installation.plan.review_prepared",
            "apply_provider_installation": "installation.plan.provider_installation_applied",
            "request_model_install": "installation.plan.model_requested",
            "process_model_install": "installation.plan.model_processed",
            "create_bundle": "installation.plan.bundle_created",
            "create_private_endpoint": "installation.plan.endpoint_created",
            "forecast_private_endpoint": "installation.plan.endpoint_forecasted",
            "start_private_endpoint": "installation.plan.endpoint_started",
        }
        message_by_action = {
            "prepare_review": "AI-assisted installation plan prepared for provider review",
            "prepare_assisted_installation_review": "AI-assisted installation plan prepared for provider review",
            "apply_provider_installation": "AI-assisted installation plan applied the reviewed provider installation",
            "request_model_install": "AI-assisted installation plan queued a model installation",
            "process_model_install": "AI-assisted installation plan processed and verified the selected model",
            "create_bundle": "AI-assisted installation plan created a local Bundle",
            "create_private_endpoint": "AI-assisted installation plan created a private Endpoint",
            "forecast_private_endpoint": "AI-assisted installation plan checked private Endpoint resource admission",
            "start_private_endpoint": "AI-assisted installation plan started a private Endpoint",
        }
        self.record_event(
            event_type=event_type_by_action[action],
            message=message_by_action[action],
            details={
                "operation_id": result.get("operation_id"),
                "status": result.get("status"),
                "next_action": result.get("next_action"),
            },
        )
        self._persist_state()
        return result

    def _apply_provider_from_installation_plan(
        self,
        *,
        plan_hash: str,
        actor: str,
        idempotency_key: str | None,
    ) -> dict:
        """Apply only an operator-approved provider installation for this plan.

        The terminal wizard never stores provider secrets or configuration in
        the assisted plan.  Instead, the operator approves the reviewed
        provider plan through the normal Provider UI; this step finds that
        exact approval by its bound provider-plan hash and submits the durable
        broker job.  An agent can resume/observe the job, but cannot invent an
        approval or bypass the existing package, permission and sandbox checks.
        """

        current = read_installation_plan()
        if not current.get("available"):
            raise ValueError(str(current.get("reason") or "installation plan is unavailable"))
        if current.get("integrity") != "verified":
            raise ValueError(str(current.get("reason") or "installation plan integrity is not verified"))
        if str(current.get("plan_hash")) != str(plan_hash):
            raise ValueError("installation plan changed; refresh before applying")
        if current.get("mode") != "ai_assisted":
            raise ValueError("only an AI-assisted installation plan can apply a provider")

        application = current.get("application")
        application = dict(application) if isinstance(application, dict) else {}
        provider_application = application.get("provider")
        provider_application = (
            dict(provider_application) if isinstance(provider_application, dict) else {}
        )
        provider_id = str(current.get("provider") or "skip")
        if provider_id == "skip":
            raise ValueError("the assisted plan does not select a provider")

        existing_job_id = str(provider_application.get("job_id") or "")
        existing_status = str(provider_application.get("status") or "").upper()
        if idempotency_key and provider_application.get("idempotency_key") == idempotency_key and existing_job_id:
            return {
                **current,
                "operation_id": provider_application.get("operation_id"),
                "job": self.get_provider_installation_job(existing_job_id),
                "workflow": self.installation_plan().get("workflow"),
            }
        if existing_job_id and existing_status in {"QUEUED", "RUNNING", "PROCESSING"}:
            return {
                **current,
                "operation_id": provider_application.get("operation_id"),
                "job": self.get_provider_installation_job(existing_job_id),
                "workflow": self.installation_plan().get("workflow"),
            }

        reviewed_plan = provider_application.get("installation_plan")
        reviewed_plan = reviewed_plan if isinstance(reviewed_plan, dict) else {}
        provider_plan_hash = str(reviewed_plan.get("plan_hash") or "")
        if not provider_plan_hash:
            raise ValueError("provider review is missing a plan hash; prepare the assisted review again")

        approvals = self.list_provider_installation_approvals()
        approval = next(
            (
                item
                for item in reversed(approvals)
                if str(item.get("plugin_id") or "") == provider_id
                and str(item.get("plan_hash") or "") == provider_plan_hash
                and str(item.get("status") or "").upper() == "APPROVED"
            ),
            None,
        )
        if approval is None:
            raise ValueError(
                "operator approval is required for the reviewed provider plan before installation"
            )

        approval_id = str(approval.get("approval_id") or "")
        if not approval_id:
            raise ValueError("provider approval is missing its approval id")
        operation_id = str(provider_application.get("operation_id") or f"provider-install-{uuid4().hex}")
        job = self.apply_provider_installation_approval(
            approval_id,
            wait_for_completion=False,
        )
        job = dict(job or {})
        job_id = str(job.get("job_id") or "")
        if not job_id:
            raise ValueError("provider installation did not return a durable job id")
        provider_application.update(
            {
                "plugin_id": provider_id,
                "approval_id": approval_id,
                "job_id": job_id,
                "plan_hash": provider_plan_hash,
                "status": str(job.get("status") or "QUEUED").upper(),
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "submitted_at": datetime.now(UTC).isoformat(),
                "actor": actor,
                "last_error": job.get("error_message"),
            }
        )
        application["provider"] = provider_application
        status = "PROVIDER_INSTALL_QUEUED"
        next_action = "wait_provider_installation"
        if str(job.get("status") or "").upper() in {"FAILED", "ERROR", "CANCELLED"}:
            status = "PROVIDER_INSTALL_FAILED"
            next_action = "inspect_provider_installation"
        updated = update_installation_plan(
            None,
            expected_hash=plan_hash,
            status=status,
            application=application,
            next_action=next_action,
        )
        updated["operation_id"] = operation_id
        updated["job"] = job
        updated["workflow"] = self.installation_plan().get("workflow")
        return updated

    def _request_model_from_installation_plan(
        self,
        *,
        plan_hash: str,
        actor: str,
        idempotency_key: str | None,
    ) -> dict:
        """Queue the selected model after provider readiness is observed.

        This is the second explicit step of assisted setup.  It never processes
        the queue inline: the normal model-install worker remains responsible
        for downloads, progress, retries and artifact validation.
        """

        current = read_installation_plan()
        if not current.get("available"):
            raise ValueError(str(current.get("reason") or "installation plan is unavailable"))
        if current.get("integrity") != "verified":
            raise ValueError(str(current.get("reason") or "installation plan integrity is not verified"))
        if str(current.get("plan_hash")) != str(plan_hash):
            raise ValueError("installation plan changed; refresh before applying")
        if current.get("mode") != "ai_assisted":
            raise ValueError("only an AI-assisted installation plan can request a model")

        model = current.get("model") if isinstance(current.get("model"), dict) else {}
        provider_type = str(current.get("provider") or "skip")
        model_id = str(model.get("id") or "skip")
        if provider_type == "skip" or model_id == "skip":
            raise ValueError("the assisted plan does not select a provider and model")
        provider_ready = any(
            str(item.get("plugin_id") or item.get("provider_type") or "") == provider_type
            and str(item.get("status") or "").upper() not in {"FAILED", "DISABLED"}
            for item in self.list_provider_instances()
        )
        if not provider_ready:
            raise ValueError("selected provider is not attached; approve and apply provider installation first")

        application = current.get("application")
        application = dict(application) if isinstance(application, dict) else {}
        existing_model = application.get("model")
        existing_model = dict(existing_model) if isinstance(existing_model, dict) else {}
        if (
            idempotency_key
            and existing_model.get("idempotency_key") == idempotency_key
            and existing_model.get("install_id")
        ):
            return {**current, "operation_id": existing_model.get("operation_id"), "workflow": self.installation_plan().get("workflow")}

        source_url = str(model.get("source") or "")
        if not source_url:
            if provider_type in {"vllm", "ollama"}:
                source_url = model_id
            else:
                raise ValueError("the selected model has no concrete source URL")
        operation_id = f"model-install-{uuid4().hex}"
        install = self.request_model_install(
            provider_type=provider_type,
            model_id=model_id,
            source_url=source_url,
            requested_by=actor,
            expected_sha256=model.get("expected_sha256"),
            expected_bytes=model.get("expected_bytes"),
        )
        application["model"] = {
            "id": model_id,
            "source": source_url,
            **(
                {
                    "expected_sha256": model.get("expected_sha256"),
                    "expected_bytes": model.get("expected_bytes"),
                }
                if model.get("expected_sha256") is not None
                else {}
            ),
            "install_id": install["install_id"],
            "operation_id": operation_id,
            "idempotency_key": idempotency_key,
            "status": "QUEUED",
            "requested_at": datetime.now(UTC).isoformat(),
        }
        updated = update_installation_plan(
            None,
            expected_hash=plan_hash,
            status="MODEL_INSTALL_QUEUED",
            application=application,
            next_action="wait_model_install",
        )
        updated["operation_id"] = operation_id
        updated["workflow"] = self.installation_plan().get("workflow")
        return updated

    def _process_model_from_installation_plan(
        self,
        *,
        plan_hash: str,
        actor: str,
        idempotency_key: str | None,
    ) -> dict:
        """Materialize only the model selected by the assisted plan.

        The ordinary model worker remains the owner of download, checksum and
        provider-specific preparation.  This wrapper supplies the missing
        plan-bound control-plane step: a Steward or operator can explicitly
        start that worker for the selected install, without accidentally
        processing an unrelated queued model on the node.
        """

        current = read_installation_plan()
        if not current.get("available"):
            raise ValueError(str(current.get("reason") or "installation plan is unavailable"))
        if current.get("integrity") != "verified":
            raise ValueError(str(current.get("reason") or "installation plan integrity is not verified"))
        if str(current.get("plan_hash")) != str(plan_hash):
            raise ValueError("installation plan changed; refresh before applying")
        if current.get("mode") != "ai_assisted":
            raise ValueError("only an AI-assisted installation plan can process a model")

        application = current.get("application")
        application = dict(application) if isinstance(application, dict) else {}
        model_application = application.get("model")
        model_application = (
            dict(model_application) if isinstance(model_application, dict) else {}
        )
        install_id = str(model_application.get("install_id") or "")
        if not install_id:
            raise ValueError("request the selected model before processing it")

        install = next(
            (
                item
                for item in self.list_model_installs()
                if str(item.get("install_id") or "") == install_id
            ),
            None,
        )
        if install is None:
            raise ValueError(f"selected model install is unavailable: {install_id}")

        existing_key = model_application.get("processing_idempotency_key")
        if (
            idempotency_key
            and existing_key == idempotency_key
            and str(install.get("status") or "").lower() in {"completed", "failed"}
        ):
            return {
                **current,
                "operation_id": model_application.get("processing_operation_id"),
                "workflow": self.installation_plan().get("workflow"),
            }

        operation_id = str(
            model_application.get("processing_operation_id")
            or f"model-process-{uuid4().hex}"
        )
        status_before = str(install.get("status") or "").lower()
        if status_before == "queued":
            self.process_model_installs(install_id=install_id, limit=1)
            install = next(
                item
                for item in self.list_model_installs()
                if str(item.get("install_id") or "") == install_id
            )

        status = str(install.get("status") or "").lower()
        model_application.update(
            {
                "status": status.upper() or "UNKNOWN",
                "processing_operation_id": operation_id,
                "processing_idempotency_key": idempotency_key,
                "processed_at": datetime.now(UTC).isoformat(),
                "last_error": install.get("last_error"),
                "actor": actor,
            }
        )
        application["model"] = model_application
        if status in {"completed", "registered"}:
            plan_status = "MODEL_INSTALL_COMPLETED"
            next_action = "create_bundle"
        elif status == "failed":
            plan_status = "MODEL_INSTALL_FAILED"
            next_action = "inspect_model_install"
        elif status == "running":
            plan_status = "MODEL_INSTALL_RUNNING"
            next_action = "wait_model_install"
        else:
            plan_status = "MODEL_INSTALL_QUEUED"
            next_action = "process_model_install"
        updated = update_installation_plan(
            None,
            expected_hash=plan_hash,
            status=plan_status,
            application=application,
            next_action=next_action,
        )
        updated["operation_id"] = operation_id
        updated["workflow"] = self.installation_plan().get("workflow")
        return updated

    def _create_private_endpoint_from_installation_plan(
        self,
        *,
        plan_hash: str,
        actor: str,
        idempotency_key: str | None,
    ) -> dict:
        """Create an owner-only Endpoint without publishing it."""

        current = read_installation_plan()
        if not current.get("available"):
            raise ValueError(str(current.get("reason") or "installation plan is unavailable"))
        if current.get("integrity") != "verified":
            raise ValueError(str(current.get("reason") or "installation plan integrity is not verified"))
        if str(current.get("plan_hash")) != str(plan_hash):
            raise ValueError("installation plan changed; refresh before applying")
        application = current.get("application")
        application = dict(application) if isinstance(application, dict) else {}
        existing_endpoint = application.get("endpoint")
        existing_endpoint = dict(existing_endpoint) if isinstance(existing_endpoint, dict) else {}
        if existing_endpoint.get("endpoint_id") and (
            not idempotency_key or existing_endpoint.get("idempotency_key") == idempotency_key
        ):
            return {**current, "operation_id": existing_endpoint.get("operation_id"), "workflow": self.installation_plan().get("workflow")}

        bundle_application = application.get("bundle")
        bundle_application = dict(bundle_application) if isinstance(bundle_application, dict) else {}
        bundle_id = str(bundle_application.get("bundle_id") or "")
        if not bundle_id:
            raise ValueError("create a Bundle before creating a private Endpoint")
        bundle = next((item for item in self.bundle_config() if item.bundle_id == bundle_id), None)
        if bundle is None:
            raise ValueError(f"Bundle is not available: {bundle_id}")
        endpoint_application_service = getattr(self, "endpoint_application_service", None)
        if endpoint_application_service is None:
            raise ValueError("Endpoint application service is not configured")
        wallet = self.owner_wallet_state()
        if not wallet.get("configured") or not wallet.get("wallet_id"):
            raise ValueError("Owner wallet must be configured before creating an Endpoint")
        model_id = str(bundle.model_id or current.get("model", {}).get("id") or "model")
        runtime_policy = {
            key: (
                value.model_dump(mode="json", by_alias=True)
                if hasattr(value, "model_dump")
                else dict(value)
                if isinstance(value, dict)
                else value
            )
            for key, value in bundle.runtime_parameter_policy.items()
        }
        result = endpoint_application_service.create_endpoint(
            {
                "owner_wallet": wallet["wallet_id"],
                "bundle_id": bundle.bundle_id,
                "bundle_hash": bundle.bundle_hash,
                "display_name": f"{model_id} (local)",
                "model_class": bundle.workload_type,
                "capabilities": [bundle.workload_type],
                "runtime_parameter_policy": runtime_policy,
                "publication": {
                    "visibility": "private",
                    "discoverable": False,
                    "validation": "disabled",
                    "accepts_external_requests": False,
                },
            }
        )
        endpoint_payload = result.get("payload", {}).get("endpoint", {})
        endpoint_id = str(endpoint_payload.get("endpoint_id") or "")
        if not endpoint_id:
            raise ValueError("Endpoint creation returned no endpoint id")
        operation_id = f"endpoint-install-{uuid4().hex}"
        application["endpoint"] = {
            "endpoint_id": endpoint_id,
            "bundle_id": bundle.bundle_id,
            "status": "CREATED",
            "visibility": "private",
            "discoverable": False,
            "operation_id": operation_id,
            "idempotency_key": idempotency_key,
            "created_at": datetime.now(UTC).isoformat(),
            "actor": actor,
        }
        updated = update_installation_plan(
            None,
            expected_hash=plan_hash,
            status="PRIVATE_ENDPOINT_CREATED",
            application=application,
            next_action="forecast_private_endpoint",
        )
        updated["operation_id"] = operation_id
        updated["workflow"] = self.installation_plan().get("workflow")
        return updated

    def _forecast_private_endpoint_from_installation_plan(
        self,
        *,
        plan_hash: str,
        actor: str,
        idempotency_key: str | None,
    ) -> dict:
        """Forecast Bundle activation without reserving or starting resources.

        The forecast is deliberately a separate assisted-installation step.
        It gives the operator/Steward a bounded explanation before the
        mutating activation call, while ``start_bundle`` remains the final
        authoritative admission check for races and changed hardware state.
        """

        current = read_installation_plan()
        if not current.get("available"):
            raise ValueError(str(current.get("reason") or "installation plan is unavailable"))
        if current.get("integrity") != "verified":
            raise ValueError(str(current.get("reason") or "installation plan integrity is not verified"))
        if str(current.get("plan_hash")) != str(plan_hash):
            raise ValueError("installation plan changed; refresh before applying")
        application = current.get("application")
        application = dict(application) if isinstance(application, dict) else {}
        endpoint = application.get("endpoint")
        endpoint = endpoint if isinstance(endpoint, dict) else {}
        bundle = application.get("bundle")
        bundle = bundle if isinstance(bundle, dict) else {}
        bundle_id = str(bundle.get("bundle_id") or "")
        if not endpoint.get("endpoint_id") or not bundle_id:
            raise ValueError("create a private Endpoint before forecasting its resources")

        previous = application.get("forecast")
        previous = previous if isinstance(previous, dict) else {}
        if idempotency_key and previous.get("idempotency_key") == idempotency_key:
            return {**current, "operation_id": previous.get("operation_id"), "workflow": self.installation_plan().get("workflow")}

        resources = getattr(self, "resources", None)
        forecast: dict[str, object]
        operation_id = f"endpoint-forecast-{uuid4().hex}"
        if resources is None or not callable(getattr(resources, "forecast", None)):
            forecast = {
                "decision": "UNKNOWN",
                "retryable": True,
                "reason": "resource_broker_unavailable",
            }
        else:
            bundle_config = self._get_bundle(bundle_id)
            plugin = self._get_plugin(bundle_config.plugin_id)
            estimate = plugin.estimate_resources(
                TaskRequest(
                    task_type="runtime_activation",
                    payload={},
                    constraints={"bundle_id": bundle_id},
                ),
                bundle_config,
                None,
            )
            startup = estimate.get("startup_transient", {})
            startup = startup if isinstance(startup, dict) else {}
            resident = estimate.get("runtime_resident", {})
            resident = resident if isinstance(resident, dict) else {}
            required = {
                "cpu": float(startup.get("cpu", 0.0) or 0.0) + float(resident.get("cpu", 0.0) or 0.0),
                "ram_mb": int(startup.get("ram_mb", 0) or 0) + int(resident.get("ram_mb", 0) or 0),
                "vram_mb": int(startup.get("vram_mb", 0) or 0) + int(resident.get("vram_mb", 0) or 0),
            }
            forecast = dict(resources.forecast(**required))
            forecast["bundle_id"] = bundle_id
            forecast["estimate"] = {
                "startup_transient": dict(startup),
                "runtime_resident": dict(resident),
            }
        forecast.update(
            {
                "bundle_id": bundle_id,
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "actor": actor,
                "checked_at": datetime.now(UTC).isoformat(),
            }
        )
        application["forecast"] = forecast
        decision = str(forecast.get("decision") or "UNKNOWN").upper()
        if decision == "ADMIT":
            status = "PRIVATE_ENDPOINT_ADMISSION_READY"
            next_action = "start_private_endpoint"
        else:
            status = "PRIVATE_ENDPOINT_RESOURCE_WAIT" if decision == "RESOURCE_WAIT" else "PRIVATE_ENDPOINT_ADMISSION_UNKNOWN"
            next_action = "forecast_private_endpoint"
        updated = update_installation_plan(
            None,
            expected_hash=plan_hash,
            status=status,
            application=application,
            next_action=next_action,
        )
        updated["operation_id"] = operation_id
        updated["workflow"] = self.installation_plan().get("workflow")
        return updated

    def _start_private_endpoint_from_installation_plan(
        self,
        *,
        plan_hash: str,
        actor: str,
        idempotency_key: str | None,
    ) -> dict:
        """Start the selected private Bundle through admission and readiness."""

        current = read_installation_plan()
        if not current.get("available"):
            raise ValueError(str(current.get("reason") or "installation plan is unavailable"))
        if current.get("integrity") != "verified":
            raise ValueError(str(current.get("reason") or "installation plan integrity is not verified"))
        if str(current.get("plan_hash")) != str(plan_hash):
            raise ValueError("installation plan changed; refresh before applying")
        application = current.get("application")
        application = dict(application) if isinstance(application, dict) else {}
        endpoint = application.get("endpoint")
        endpoint = dict(endpoint) if isinstance(endpoint, dict) else {}
        bundle = application.get("bundle")
        bundle = dict(bundle) if isinstance(bundle, dict) else {}
        bundle_id = str(bundle.get("bundle_id") or "")
        if not endpoint.get("endpoint_id") or not bundle_id:
            raise ValueError("create a private Endpoint before starting it")
        forecast = application.get("forecast")
        forecast = forecast if isinstance(forecast, dict) else {}
        if str(forecast.get("decision") or "").upper() != "ADMIT":
            raise ValueError("forecast private Endpoint resources before starting it")
        existing_runtime = application.get("runtime")
        existing_runtime = existing_runtime if isinstance(existing_runtime, dict) else {}
        if existing_runtime.get("runtime_id") and (
            not idempotency_key or existing_runtime.get("idempotency_key") == idempotency_key
        ):
            return {**current, "operation_id": existing_runtime.get("operation_id"), "workflow": self.installation_plan().get("workflow")}
        try:
            runtime = self.start_bundle(bundle_id, reserve_resources=True)
        except (ResourceAdmissionError, RuntimePortAllocationError) as error:
            details = dict(getattr(error, "details", {}) or {})
            application["forecast"] = {
                **forecast,
                **details,
                "decision": "RESOURCE_WAIT",
                "retryable": True,
                "reason": (
                    "resource_state_changed_before_activation"
                    if isinstance(error, ResourceAdmissionError)
                    else "runtime_port_unavailable"
                ),
                "checked_at": datetime.now(UTC).isoformat(),
            }
            updated = update_installation_plan(
                None,
                expected_hash=plan_hash,
                status="PRIVATE_ENDPOINT_RESOURCE_WAIT",
                application=application,
                next_action="forecast_private_endpoint",
            )
            updated["workflow"] = self.installation_plan().get("workflow")
            return updated
        readiness = self.runtime_readiness(runtime.runtime_id, force=True)
        operation_id = f"endpoint-start-{uuid4().hex}"
        application["runtime"] = {
            "runtime_id": runtime.runtime_id,
            "status": runtime.status,
            "readiness": readiness.get("readiness"),
            "operation_id": operation_id,
            "idempotency_key": idempotency_key,
            "started_at": datetime.now(UTC).isoformat(),
            "actor": actor,
        }
        readiness_status = str((readiness.get("readiness") or {}).get("status") or "UNKNOWN")
        status = "PRIVATE_ENDPOINT_READY" if readiness_status == "READY" else "PRIVATE_ENDPOINT_NOT_READY"
        next_action = "continue_in_dashboard" if readiness_status == "READY" else "inspect_endpoint_readiness"
        updated = update_installation_plan(
            None,
            expected_hash=plan_hash,
            status=status,
            application=application,
            next_action=next_action,
        )
        updated["operation_id"] = operation_id
        updated["workflow"] = self.installation_plan().get("workflow")
        return updated

    def _create_bundle_from_installation_plan(
        self,
        *,
        plan_hash: str,
        actor: str,
        idempotency_key: str | None,
    ) -> dict:
        """Register a local Bundle after the model-install job is complete."""

        current = read_installation_plan()
        if not current.get("available"):
            raise ValueError(str(current.get("reason") or "installation plan is unavailable"))
        if current.get("integrity") != "verified":
            raise ValueError(str(current.get("reason") or "installation plan integrity is not verified"))
        if str(current.get("plan_hash")) != str(plan_hash):
            raise ValueError("installation plan changed; refresh before applying")
        if current.get("mode") != "ai_assisted":
            raise ValueError("only an AI-assisted installation plan can create a Bundle")
        application = current.get("application")
        application = dict(application) if isinstance(application, dict) else {}
        existing_bundle = application.get("bundle")
        existing_bundle = dict(existing_bundle) if isinstance(existing_bundle, dict) else {}
        if existing_bundle.get("bundle_id") and (
            not idempotency_key or existing_bundle.get("idempotency_key") == idempotency_key
        ):
            return {**current, "operation_id": existing_bundle.get("operation_id"), "workflow": self.installation_plan().get("workflow")}
        model_application = application.get("model")
        model_application = dict(model_application) if isinstance(model_application, dict) else {}
        install_id = str(model_application.get("install_id") or "")
        if not install_id:
            raise ValueError("model install must be requested before creating a Bundle")
        install = next(
            (item for item in self.list_model_installs() if str(item.get("install_id")) == install_id),
            None,
        )
        if install is None or str(install.get("status") or "").lower() != "completed":
            raise ValueError("model install is not completed; process and verify it before creating a Bundle")
        operation_id = f"bundle-install-{uuid4().hex}"
        bundle_id = f"bundle-steward-{install_id}"[:128]
        bundle = self.register_bundle_from_install(
            install_id=install_id,
            bundle_id=bundle_id,
            workload_type="llm_text",
            endpoint="http://127.0.0.1:8080",
        )
        application["bundle"] = {
            "bundle_id": bundle["bundle_id"],
            "bundle_hash": bundle.get("bundle_hash"),
            "endpoint": bundle.get("endpoint"),
            "status": "READY",
            "operation_id": operation_id,
            "idempotency_key": idempotency_key,
            "created_at": datetime.now(UTC).isoformat(),
            "actor": actor,
        }
        updated = update_installation_plan(
            None,
            expected_hash=plan_hash,
            status="BUNDLE_CREATED",
            application=application,
            next_action="create_private_endpoint",
        )
        updated["operation_id"] = operation_id
        updated["workflow"] = self.installation_plan().get("workflow")
        return updated

    def approve_provider_installation_plan(
        self,
        plugin_id: str,
        configuration: dict,
        approved_permissions: list[str] | None = None,
        upgrade_acknowledged: bool = False,
        selected_secret_handles: list[dict] | None = None,
        operator_note: str | None = None,
    ) -> dict:
        return self._provider_installation_facade().approve_provider_installation_plan(
            plugin_id=plugin_id,
            configuration=configuration,
            approved_permissions=approved_permissions,
            upgrade_acknowledged=upgrade_acknowledged,
            selected_secret_handles=selected_secret_handles,
            operator_note=operator_note,
        )

    def run_provider_installation_diagnostics(
        self,
        plugin_id: str,
        configuration: dict,
        approved_permissions: list[str] | None = None,
        upgrade_acknowledged: bool = False,
        selected_secret_handles: list[dict] | None = None,
    ) -> dict:
        return self._provider_installation_facade().run_provider_installation_diagnostics(
            plugin_id=plugin_id,
            configuration=configuration,
            approved_permissions=approved_permissions,
            upgrade_acknowledged=upgrade_acknowledged,
            selected_secret_handles=selected_secret_handles,
        )

    def apply_provider_installation_approval(
        self,
        approval_id: str,
        *,
        wait_for_completion: bool = True,
    ) -> dict:
        return self._provider_installation_facade().apply_provider_installation_approval(
            approval_id,
            wait_for_completion=wait_for_completion,
        )

    def install_provider_runtime(
        self,
        *,
        plugin_id: str,
        configuration: dict,
        operator_note: str | None = None,
        upgrade_acknowledged: bool = False,
        wait_for_completion: bool = True,
    ) -> dict:
        return self._provider_installation_facade().install_provider_runtime(
            plugin_id=plugin_id,
            configuration=configuration,
            operator_note=operator_note,
            upgrade_acknowledged=upgrade_acknowledged,
            wait_for_completion=wait_for_completion,
        )

    def change_provider_runtime(
        self,
        *,
        plugin_id: str,
        configuration: dict,
        operator_note: str | None = None,
        upgrade_acknowledged: bool = False,
        wait_for_completion: bool = True,
    ) -> dict:
        return self._provider_installation_facade().change_provider_runtime(
            plugin_id=plugin_id,
            configuration=configuration,
            operator_note=operator_note,
            upgrade_acknowledged=upgrade_acknowledged,
            wait_for_completion=wait_for_completion,
        )

    def remove_provider_runtime(self, *, plugin_id: str) -> dict:
        return self._provider_installation_facade().remove_provider_runtime(
            plugin_id=plugin_id
        )

    def rollback_provider_installation_job(self, job_id: str) -> dict:
        return self._provider_installation_facade().rollback_provider_installation_job(
            job_id
        )

    def list_provider_installation_approvals(self) -> list[dict]:
        return self._provider_installation_facade().list_provider_installation_approvals()

    def list_provider_plugin_releases(self) -> list[dict]:
        return self._provider_installation_facade().list_provider_plugin_releases()

    def provider_plugin_registry_objects(self) -> list[dict]:
        return self._provider_installation_facade().provider_plugin_registry_objects()

    def publish_provider_plugin_releases_to_registry(self, registry_service) -> list[dict]:
        """Persist public immutable Release metadata without exposing local installs."""
        return self._provider_installation_facade().publish_provider_plugin_releases_to_registry(
            registry_service
        )

    def import_provider_plugin_registry_objects(self, records: list[dict]) -> list[dict]:
        return self._provider_installation_facade().import_provider_plugin_registry_objects(records)

    def reconcile_provider_plugin_releases_from_registry(
        self,
        registry_service,
        *,
        limit: int = 500,
    ) -> dict:
        return self._provider_installation_facade().reconcile_provider_plugin_releases_from_registry(
            registry_service,
            limit=limit,
        )

    def bind_provider_plugin_directory_replication(self, registry_replicator) -> None:
        self._provider_installation_facade().bind_provider_plugin_directory_replication(
            registry_replicator
        )

    def sync_provider_plugin_directory_from_peer(
        self,
        *,
        peer_base_url: str,
        limit: int = 500,
        expected_node_id: str | None = None,
        expected_operator_id: str | None = None,
        expected_owner_wallet_id: str | None = None,
        expected_public_key: str | None = None,
    ) -> dict:
        return self._provider_installation_facade().sync_provider_plugin_directory_from_peer(
            peer_base_url=peer_base_url,
            limit=limit,
            expected_node_id=expected_node_id,
            expected_operator_id=expected_operator_id,
            expected_owner_wallet_id=expected_owner_wallet_id,
            expected_public_key=expected_public_key,
        )

    def provider_plugin_directory_sync_state(self, *, limit: int = 500) -> dict:
        return self._provider_installation_facade().provider_plugin_directory_sync_state(
            limit=limit
        )

    def list_installed_provider_plugins(self) -> list[dict]:
        return self._provider_installation_facade().list_installed_provider_plugins()

    def register_provider_plugin_release(
        self,
        *,
        manifest: dict,
        source_reference: str | None = None,
        release_status: str = "AVAILABLE",
    ) -> dict:
        return self._provider_installation_facade().register_provider_plugin_release(
            manifest=manifest,
            source_reference=source_reference,
            release_status=release_status,
        )

    def revoke_provider_plugin_release(self, *, release_id: str, reason: str) -> dict:
        return self._provider_installation_facade().revoke_provider_plugin_release(
            release_id=release_id, reason=reason
        )

    def install_provider_plugin_release(
        self,
        *,
        release_id: str,
        granted_permissions: list[str] | None = None,
        installation_source: str = "PACKAGE",
    ) -> dict:
        return self._provider_installation_facade().install_provider_plugin_release(
            release_id=release_id,
            granted_permissions=granted_permissions,
            installation_source=installation_source,
        )

    def acquire_provider_plugin_package(self, *, release_id: str) -> str:
        return self._provider_installation_facade().acquire_provider_plugin_package(
            release_id=release_id
        )

    def list_provider_installation_jobs(self) -> list[dict]:
        return self._provider_installation_facade().list_provider_installation_jobs()

    def get_provider_installation_job(self, job_id: str) -> dict:
        return self._provider_installation_facade().get_provider_installation_job(job_id)

    def cancel_provider_installation_job(self, job_id: str) -> dict:
        return self._provider_installation_facade().cancel_provider_installation_job(job_id)

    def plugin_host_local_ingress(self):
        """Return the install-scoped Plugin Host control ingress for local transports."""
        return self._provider_installation_facade().plugin_host_local_ingress()

    def plugin_host_launch_environment(self, *, installed_plugin_id: str) -> dict[str, str]:
        return self._provider_installation_facade().plugin_host_launch_environment(
            installed_plugin_id=installed_plugin_id
        )

    def start_plugin_host_process(
        self,
        *,
        installed_plugin_id: str,
        command: list[str] | None = None,
    ):
        return self._provider_installation_facade().start_plugin_host_process(
            installed_plugin_id=installed_plugin_id,
            command=command,
        )

    def start_windows_plugin_host_listener(self, *, address: str, authkey: bytes):
        return self._provider_installation_facade().start_windows_plugin_host_listener(
            address=address,
            authkey=authkey,
        )

    def start_unix_plugin_host_listener(self, *, address: str):
        return self._provider_installation_facade().start_unix_plugin_host_listener(
            address=address,
        )

    def stop_plugin_host_listeners(self) -> None:
        self._provider_installation_facade().stop_plugin_host_listeners()

    def plugin_host_status(self) -> dict:
        return self._provider_installation_facade().plugin_host_status()

    def register_wallet_identity(
        self,
        *,
        wallet_id: str,
        public_key: str,
        registration_nonce: str,
        signature: str,
    ) -> dict:
        return self._provider_inventory_application_facade().register_wallet_identity(
            wallet_id=wallet_id,
            public_key=public_key,
            registration_nonce=registration_nonce,
            signature=signature,
        )

    def wallet_identity(self, wallet_id: str) -> dict | None:
        return self._provider_inventory_application_facade().wallet_identity(wallet_id)

    def resolve_wallet_identity(self, wallet_id: str) -> dict | None:
        return self._provider_inventory_application_facade().resolve_wallet_identity(
            wallet_id
        )

    def list_wallet_identities(self) -> list[dict]:
        return self._provider_inventory_application_facade().list_wallet_identities()

    def list_provider_installation_artifacts(self) -> dict:
        return self._provider_inventory_application_facade().list_provider_installation_artifacts()

    def stage_provider_installation_artifact(
        self,
        *,
        relative_path: str,
        content_bytes: bytes,
    ) -> dict:
        return self._provider_inventory_application_facade().stage_provider_installation_artifact(
            relative_path=relative_path,
            content_bytes=content_bytes,
        )

    def delete_provider_installation_artifact(self, *, relative_path: str) -> dict:
        return self._provider_inventory_application_facade().delete_provider_installation_artifact(
            relative_path=relative_path
        )

    def extract_provider_installation_artifact_archive(
        self,
        *,
        archive_relative_path: str,
        destination_directory: str,
    ) -> dict:
        return self._provider_inventory_application_facade().extract_provider_installation_artifact_archive(
            archive_relative_path=archive_relative_path,
            destination_directory=destination_directory,
        )

    def list_model_artifacts(self) -> dict:
        return self._provider_inventory_application_facade().list_model_artifacts()

    def promote_provider_installation_artifact_to_model_store(
        self,
        *,
        relative_path: str,
    ) -> dict:
        return self._provider_inventory_application_facade().promote_provider_installation_artifact_to_model_store(
            relative_path=relative_path,
        )

    def delete_model_artifact(self, *, artifact_id: str) -> dict:
        return self._provider_inventory_application_facade().delete_model_artifact(
            artifact_id=artifact_id
        )

    def list_model_artifact_sets(self) -> list[dict]:
        return self._provider_inventory_application_facade().list_model_artifact_sets()

    def create_model_artifact_set(self, *, display_name: str, files: list[dict]) -> dict:
        return self._provider_inventory_application_facade().create_model_artifact_set(
            display_name=display_name,
            files=files,
        )

    def delete_model_artifact_set(self, *, artifact_set_id: str) -> dict:
        return self._provider_inventory_application_facade().delete_model_artifact_set(
            artifact_set_id=artifact_set_id
        )

    def bind_model_artifact_set(
        self,
        *,
        model_deployment_id: str,
        artifact_set_id: str,
    ) -> dict:
        return self._provider_inventory_application_facade().bind_model_artifact_set(
            model_deployment_id=model_deployment_id,
            artifact_set_id=artifact_set_id,
        )

    def collect_model_artifact_garbage(self) -> dict:
        return self._provider_inventory_application_facade().collect_model_artifact_garbage()

    def materialize_model_artifact_set(
        self, *, provider_instance_id: str, artifact_set_id: str, destination: str
    ) -> dict:
        return self._provider_inventory_application_facade().materialize_model_artifact_set(
            provider_instance_id=provider_instance_id,
            artifact_set_id=artifact_set_id,
            destination=destination,
        )

    def list_model_artifact_materializations(self) -> list[dict]:
        return self._provider_inventory_application_facade().list_model_artifact_materializations()

    def discover_provider_models(self, provider_instance_id: str) -> list[dict]:
        return self._provider_inventory_application_facade().discover_provider_models(
            provider_instance_id
        )

    def probe_provider_instance(self, provider_instance_id: str) -> dict:
        return self._provider_inventory_application_facade().probe_provider_instance(
            provider_instance_id
        )

    def create_runtime_binding(
        self,
        *,
        model_deployment_id: str,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> dict:
        return self._runtime_boundary.create_runtime_binding(
            model_deployment_id=model_deployment_id,
            capability_id=capability_id,
            capability_version=capability_version,
            capability_definition_hash=capability_definition_hash,
        )

    def bundle_for_runtime_binding(self, runtime_binding_id: str) -> BundleConfig:
        return self._runtime_boundary.bundle_for_runtime_binding(runtime_binding_id)

    def bundle_hash_for_runtime_binding(self, runtime_binding_id: str) -> str:
        return self._runtime_boundary.bundle_hash_for_runtime_binding(runtime_binding_id)

    def runtime_binding_endpoint_admission(
        self,
        runtime_binding_id: str,
        endpoint_payload: dict | None = None,
    ) -> dict:
        return self._runtime_boundary.runtime_binding_endpoint_admission(
            runtime_binding_id,
            endpoint_payload=endpoint_payload,
        )

    def mark_model_install_completed(self, install_id: str) -> dict:
        return self._provider_inventory_application_facade().mark_model_install_completed(
            install_id
        )

    def register_bundle_from_install(
        self,
        *,
        install_id: str,
        bundle_id: str,
        workload_type: str,
        endpoint: str,
        runtime_parameter_policy: dict | None = None,
    ) -> dict:
        return self._provider_inventory_application_facade().register_bundle_from_install(
            install_id=install_id,
            bundle_id=bundle_id,
            workload_type=workload_type,
            endpoint=endpoint,
            runtime_parameter_policy=runtime_parameter_policy,
        )

    def get_runtime(self, runtime_id: str) -> RuntimeHandle:
        return self._runtime_boundary.get_runtime(runtime_id)

    def runtime_history(self, runtime_id: str) -> list[JournalEvent]:
        return self._runtime_boundary.runtime_history(runtime_id)

    def bundle_state(self, bundle_id: str) -> dict:
        return self._runtime_boundary._bundle_runtime_policy_facade().bundle_state(bundle_id)

    def record_event(
        self,
        *,
        event_type: str,
        message: str,
        task_id: str | None = None,
        bundle_id: str | None = None,
        runtime_id: str | None = None,
        details: dict | None = None,
        source: str | None = None,
        severity: EventSeverity | str | None = None,
        data_class: EventDataClass | str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        resource_revision: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        requires_attention: bool | None = None,
        requires_action: bool | None = None,
    ) -> JournalEvent:
        return self._event_projection_facade().record_event(
            event_type=event_type,
            message=message,
            task_id=task_id,
            bundle_id=bundle_id,
            runtime_id=runtime_id,
            details=details,
            source=source,
            severity=severity,
            data_class=data_class,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_revision=resource_revision,
            correlation_id=correlation_id,
            causation_id=causation_id,
            requires_attention=requires_attention,
            requires_action=requires_action,
        )

    def bind_validation_service(self, validation_service) -> None:
        self._integration_facade().bind_validation_service(validation_service)

    def bind_external_services(
        self,
        *,
        registry_service=None,
        endpoint_service=None,
        endpoint_publication_service=None,
        remote_endpoint_service=None,
        session_service=None,
        validation_service=None,
    ) -> None:
        self._integration_facade().bind_external_services(
            registry_service=registry_service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=endpoint_publication_service,
            remote_endpoint_service=remote_endpoint_service,
            session_service=session_service,
            validation_service=validation_service,
        )

    def _record_wallet_session_event_from_journal(self, event: JournalEvent) -> bool:
        return self._event_projection_facade().record_wallet_session_event_from_journal(
            event
        )

    def _record_wallet_validation_event_from_journal(self, event: JournalEvent) -> bool:
        return self._event_projection_facade().record_wallet_validation_event_from_journal(
            event
        )

    def snapshot_state(self) -> HypervisorStateSnapshot:
        return self._snapshot_state_facade().snapshot_state()

    def restore_state(self, snapshot: HypervisorStateSnapshot) -> dict[str, int]:
        return self._snapshot_state_facade().restore_state(snapshot)

    def get_task(self, task_id: str):
        return self.queue.get(task_id)

    def bundle_config(self) -> list[BundleConfig]:
        return self._runtime_boundary._bundle_runtime_policy_facade().bundle_config()

    def replace_bundle_config(self, bundles: list[BundleConfig]) -> int:
        return self._runtime_boundary._bundle_runtime_policy_facade().replace_bundle_config(bundles)

    def create_bundle_revision(
        self,
        *,
        source_bundle_id: str,
        bundle_id: str,
        overrides: dict | None = None,
        enabled: bool = False,
    ) -> dict:
        return self._runtime_boundary._bundle_runtime_policy_facade().create_bundle_revision(
            source_bundle_id=source_bundle_id,
            bundle_id=bundle_id,
            overrides=overrides,
            enabled=enabled,
        )

    def reload_bundle_config(self) -> int:
        return self._runtime_boundary._bundle_runtime_policy_facade().reload_bundle_config()

    def reset_bundle_cooldown(self, bundle_id: str) -> dict:
        return self._runtime_boundary._bundle_runtime_policy_facade().reset_bundle_cooldown(bundle_id)

    def retry_bundle(self, bundle_id: str) -> dict[str, int]:
        return self._runtime_boundary._bundle_runtime_policy_facade().retry_bundle(bundle_id)

    def set_bundle_enabled(self, bundle_id: str, enabled: bool) -> dict[str, str | bool]:
        result = self._runtime_boundary._bundle_runtime_policy_facade().set_bundle_enabled(
            bundle_id,
            enabled,
        )
        self.reconcile_scheduler(trigger="bundle_enabled" if enabled else "bundle_disabled")
        return result

    def drain_runtime(self, runtime_id: str) -> dict[str, str | bool]:
        result = self._runtime_boundary.drain_runtime(runtime_id)
        self.reconcile_scheduler(trigger="operator_runtime_drain")
        return result

    def force_stop_runtime(self, runtime_id: str) -> dict[str, str]:
        result = self._runtime_boundary.force_stop_runtime(runtime_id)
        self.reconcile_scheduler(trigger="operator_runtime_stop")
        return result

    def set_runtime_pinned_warm(
        self,
        runtime_id: str,
        pinned: bool,
    ) -> dict[str, str | bool]:
        result = self._runtime_boundary.set_runtime_pinned_warm(runtime_id, pinned)
        # A pin changes the eviction candidate set, so re-run the same global
        # reconciliation used by every other operator Runtime control.
        self.reconcile_scheduler(
            trigger="operator_runtime_pin" if pinned else "operator_runtime_unpin"
        )
        return result

    # RFC-0074/IMP-0002 lifecycle boundary.  Callers should use these
    # facades instead of deleting Provider/Bundle/Endpoint state directly.
    def lifecycle_removal_plan(self, object_type: str, object_id: str, **kwargs) -> dict:
        return self.lifecycle_manager.removal_plan(object_type, object_id, **kwargs)

    def apply_lifecycle_removal(self, plan_id: str, plan_hash: str, **kwargs) -> dict:
        return self.lifecycle_manager.apply_removal(plan_id, plan_hash, **kwargs)

    def lifecycle_transition_plan(self, object_type: str, object_id: str, action: str, **kwargs) -> dict:
        return self.lifecycle_manager.transition_plan(object_type, object_id, action, **kwargs)

    def apply_lifecycle_transition(self, transition_id: str, plan_hash: str, **kwargs) -> dict:
        return self.lifecycle_manager.apply_transition(transition_id, plan_hash, **kwargs)

    def lifecycle_tombstones(self) -> list[dict]:
        return self.lifecycle_manager.list_tombstones()

    def lifecycle_tombstone(self, object_type: str, object_id: str) -> dict:
        return self.lifecycle_manager.get_tombstone(object_type, object_id)

    def runtime_reset_plan(self, **kwargs) -> dict:
        return self.reset_manager.plan("runtime", **kwargs)

    def apply_runtime_reset(self, reset_id: str, plan_hash: str, **kwargs) -> dict:
        return self.reset_manager.apply(reset_id, plan_hash, **kwargs)

    @property
    def lifecycle_maintenance_state(self) -> str:
        return self._lifecycle_maintenance_state

    def restart_runtime(self, runtime_id: str) -> dict[str, str]:
        return self._runtime_boundary.restart_runtime(runtime_id)

    def cancel_task(self, task_id: str):
        return self._task_lifecycle_facade().cancel_task(task_id)

    def start_bundle(
        self,
        bundle_id: str,
        *,
        reserve_resources: bool = True,
    ) -> RuntimeHandle:
        runtime = self._runtime_boundary._bundle_runtime_policy_facade().start_bundle(
            bundle_id,
            reserve_resources=reserve_resources,
        )
        if reserve_resources:
            self.reconcile_scheduler(trigger="operator_runtime_start")
        return runtime

    def stop_bundle(self, bundle_id: str) -> dict[str, str]:
        return self._runtime_boundary._bundle_runtime_policy_facade().stop_bundle(bundle_id)

    def list_runtimes(self) -> list[RuntimeHandle]:
        return self._runtime_boundary.list_runtimes()

    def refresh_runtime_health(
        self,
        bundle_id: str | None = None,
        *,
        force: bool = False,
    ) -> list[RuntimeHandle]:
        """Return runtime state reconciled with live provider processes."""

        return self._runtime_boundary._bundle_runtime_policy_facade().refresh_runtime_health(
            bundle_id,
            force=force,
        )

    def runtime_readiness(self, runtime_id: str, *, force: bool = True) -> dict:
        """Return the canonical process/provider readiness projection."""

        return self._runtime_boundary._bundle_runtime_policy_facade().runtime_readiness(
            runtime_id,
            force=force,
        )

    def runtime_operations(self) -> dict:
        """Return live runtime readiness and Provider Broker job progress."""

        from aidn_hypervisor.runtime_operations_read_models import (
            build_runtime_operations_payload,
        )

        return build_runtime_operations_payload(service=self)

    def process_pending(self) -> dict[str, int]:
        return self._task_lifecycle_facade().process_pending()

    def reconcile_scheduler(
        self,
        *,
        trigger: str = "manual",
        max_cycles: int = 128,
    ) -> dict:
        """Re-evaluate all eligible endpoint queues and runtime placements."""

        return self._runtime_boundary.reconcile_scheduler(
            trigger=trigger,
            max_cycles=max_cycles,
        )

    def queue_summary(self) -> dict[str, int]:
        return self._task_lifecycle_facade().queue_summary()

    def queue_diagnostics(self) -> list[dict[str, str]]:
        return self._runtime_boundary._admission_planning_facade().queue_diagnostics()

    def scheduler_candidates(self, *, limit: int = 200) -> list[dict]:
        """Return the read-only fit-aware candidate projection."""

        return self._runtime_boundary.scheduler_candidates(limit=limit)

    def scheduler_explain_decision(self, task_id: str) -> dict:
        """Explain the current queue/admission decision for one task."""

        return self._runtime_boundary.scheduler_explain_decision(task_id)

    def scheduler_status(self, *, candidate_limit: int = 200) -> dict:
        """Return the read-only Resource Broker/Scheduler status projection."""

        return self._runtime_boundary.scheduler_status(candidate_limit=candidate_limit)

    def _get_bundle(self, bundle_id: str) -> BundleConfig:
        return self._runtime_boundary._bundle_runtime_policy_facade().get_bundle(bundle_id)

    def _get_plugin(self, plugin_id: str):
        if hasattr(self.plugins, "get"):
            return self.plugins.get(plugin_id)

        for plugin in self.plugins or []:
            if plugin.plugin_id == plugin_id:
                return plugin
        raise KeyError(plugin_id)

    def _runtime_for_bundle(self, bundle_id: str) -> RuntimeHandle | None:
        return self._runtime_boundary._runtime_for_bundle(bundle_id)

    def _filtered_catalog_bundles(
        self,
        *,
        workload_type: str | None,
        bundle_id: str | None,
        include_disabled: bool,
    ) -> list[BundleConfig]:
        return self._allocation_catalog_facade().filtered_catalog_bundles(
            workload_type=workload_type,
            bundle_id=bundle_id,
            include_disabled=include_disabled,
        )

    def _catalog_entry(self, bundle: BundleConfig, *, owner_id: str) -> dict:
        return self._allocation_catalog_facade().catalog_entry(
            bundle,
            owner_id=owner_id,
        )

    def _operator_dashboard_bundle_entry(self, bundle: BundleConfig) -> dict:
        return self._allocation_catalog_facade().operator_dashboard_bundle_entry(bundle)

    def _operator_dashboard_task_entry(self, task: QueuedTask) -> dict:
        return self.operator_read_models._task_entry(task)

    def _task_terminal_timestamp(self, task_id: str) -> str | None:
        return self.operator_read_models.task_terminal_timestamp(task_id)

    def _operator_spillover_preview(self, market_candidates: list[dict]) -> list[dict]:
        return self.operator_read_models.spillover_preview(market_candidates)

    def _operator_candidate_price(self, candidate: dict) -> float:
        return self.operator_read_models.candidate_price(candidate)

    def _operator_candidate_rating(self, candidate: dict) -> float:
        return self.operator_read_models.candidate_rating(candidate)

    def _operator_balanced_candidate_score(self, candidate: dict) -> float:
        return self.operator_read_models.balanced_candidate_score(candidate)

    def _operator_dashboard_bootstrap(self, fleet: dict) -> dict:
        return self.operator_read_models.bootstrap(fleet)

    def _operator_dashboard_install_status(self, status: str) -> str:
        return self.operator_read_models.install_status(status)

    def _catalog_endpoint(
        self,
        bundle: BundleConfig,
        runtime: RuntimeHandle | None,
    ) -> str | None:
        return self._allocation_catalog_facade().catalog_endpoint(bundle, runtime)

    def _catalog_required_resources(
        self,
        bundle: BundleConfig,
        runtime: RuntimeHandle | None,
    ) -> dict[str, float | int]:
        return self._allocation_catalog_facade().catalog_required_resources(
            bundle,
            runtime,
        )

    def _catalog_fit(
        self,
        required: dict[str, float | int],
    ) -> dict[str, float | int | bool]:
        return self._allocation_catalog_facade().catalog_fit(required)

    def _select_allocation_bundle(self, request: AllocationRequest) -> BundleConfig:
        return self._allocation_catalog_facade().select_allocation_bundle(request)

    def _allocation_unavailability(
        self,
        *,
        bundle: BundleConfig,
        runtime: RuntimeHandle | None,
    ) -> dict[str, str | bool] | None:
        return self._allocation_catalog_facade().allocation_unavailability(
            bundle=bundle,
            runtime=runtime,
        )

    def _reserve_allocation_residency(
        self,
        *,
        allocation_id: str,
        bundle: BundleConfig,
        runtime: RuntimeHandle | None,
    ) -> str | None:
        return self._allocation_catalog_facade().reserve_allocation_residency(
            allocation_id=allocation_id,
            bundle=bundle,
            runtime=runtime,
        )

    def _bundle_has_active_allocation_reservation(self, bundle_id: str) -> bool:
        return self._allocation_catalog_facade().bundle_has_active_allocation_reservation(
            bundle_id
        )

    def _release_allocation_resources(self, allocation: dict) -> None:
        self._allocation_catalog_facade().release_allocation_resources(allocation)

    def _owner_allocation_count(self, owner_id: str, *, status: str) -> int:
        return self._allocation_catalog_facade().owner_allocation_count(
            owner_id,
            status=status,
        )

    def _owner_quota_unavailability(
        self,
        *,
        owner_id: str,
        status: str,
        bundle_id: str,
    ) -> dict[str, str | bool | int | None] | None:
        return self._allocation_catalog_facade().owner_quota_unavailability(
            owner_id=owner_id,
            status=status,
            bundle_id=bundle_id,
        )

    def _cleanup_expired_allocations(self) -> None:
        self._allocation_catalog_facade().cleanup_expired_allocations()

    def _public_allocation(self, allocation: dict) -> dict:
        return self._allocation_catalog_facade().public_allocation(allocation)

    def _create_pending_allocation(
        self,
        *,
        request: AllocationRequest,
        bundle: BundleConfig,
        reason: str,
    ) -> dict:
        return self._allocation_catalog_facade().create_pending_allocation(
            request=request,
            bundle=bundle,
            reason=reason,
        )

    def _reconcile_pending_allocations(self) -> bool:
        return self._allocation_catalog_facade().reconcile_pending_allocations()

    def _allocation_retry_hint(
        self,
        *,
        bundle_id: str,
        reason: str,
    ) -> dict[str, int | str]:
        return self._allocation_catalog_facade().allocation_retry_hint(
            bundle_id=bundle_id,
            reason=reason,
        )

    def _bundle_inventory_status(self, bundle: BundleConfig) -> str:
        return self._runtime_boundary._bundle_runtime_policy_facade().bundle_inventory_status(bundle)

    def _bundle_registry_status(self, bundle: BundleConfig) -> str:
        return self._runtime_boundary._bundle_runtime_policy_facade().bundle_registry_status(bundle)

    def _attempt_task(self, task_id: str) -> bool:
        return self._task_execution_facade().attempt_task(task_id)

    def _reserve_runtime_residency(
        self, bundle_id: str, *, cpu: float, ram_mb: int, vram_mb: int
    ) -> None:
        self._runtime_boundary._reserve_runtime_residency(
            bundle_id,
            cpu=cpu,
            ram_mb=ram_mb,
            vram_mb=vram_mb,
        )

    def _release_runtime_reservation(self, bundle_id: str) -> None:
        self._runtime_boundary._release_runtime_reservation(bundle_id)

    def _stop_runtime_for_bundle(
        self,
        bundle: BundleConfig,
        *,
        reason: str = "operator",
    ) -> None:
        self._runtime_boundary._stop_runtime_for_bundle(bundle, reason=reason)

    def _runtime_reservation_id(self, bundle_id: str) -> str:
        return self._runtime_boundary._runtime_reservation_id(bundle_id)

    def _current_bundle_state(self, bundle_id: str) -> dict:
        return self._runtime_boundary._bundle_runtime_policy_facade().current_bundle_state(bundle_id)

    def _bundle_state_is_non_default(self, bundle_id: str) -> bool:
        return self._runtime_boundary._bundle_runtime_policy_facade().bundle_state_is_non_default(
            bundle_id
        )

    def _set_bundle_state(
        self,
        bundle_id: str,
        *,
        failure_streak: int,
        cooldown_until: float | None,
        cooldown_reason: str | None,
        drain_mode: bool,
        drain_reason: str | None,
    ) -> dict:
        return self._runtime_boundary._bundle_runtime_policy_facade().set_bundle_state(
            bundle_id,
            failure_streak=failure_streak,
            cooldown_until=cooldown_until,
            cooldown_reason=cooldown_reason,
            drain_mode=drain_mode,
            drain_reason=drain_reason,
        )

    def _register_bundle_failure(
        self,
        *,
        bundle_id: str,
        plugin,
        runtime: RuntimeHandle | None,
        reason: str,
    ) -> None:
        self._runtime_boundary._bundle_runtime_policy_facade().register_bundle_failure(
            bundle_id=bundle_id,
            plugin=plugin,
            runtime=runtime,
            reason=reason,
        )

    def _register_bundle_success(
        self,
        bundle_id: str,
        runtime: RuntimeHandle | None = None,
    ) -> None:
        self._runtime_boundary._bundle_runtime_policy_facade().register_bundle_success(
            bundle_id,
            runtime=runtime,
        )

    def _bundle_in_cooldown(self, bundle_id: str) -> bool:
        return self._runtime_boundary._bundle_runtime_policy_facade().bundle_in_cooldown(bundle_id)

    def _health_check_with_retry(
        self,
        plugin,
        runtime: RuntimeHandle,
        bundle_id: str,
    ) -> bool:
        return self._task_execution_facade().health_check_with_retry(
            plugin,
            runtime,
            bundle_id,
        )

    def _invoke_with_retry(
        self,
        plugin,
        bundle: BundleConfig,
        task: TaskRequest,
        runtime: RuntimeHandle,
        endpoint_manifest=None,
    ) -> dict:
        return self._task_execution_facade().invoke_with_retry(
            plugin,
            bundle,
            task,
            runtime,
            endpoint_manifest=endpoint_manifest,
        )

    def _record_mvp_runtime_evidence_for_completed_task(
        self,
        *,
        task_id: str,
        bundle: BundleConfig,
        task: TaskRequest,
        runtime: RuntimeHandle | None,
    ) -> RuntimeRequestRecord | None:
        return self._runtime_boundary._record_mvp_runtime_evidence_for_completed_task(
            task_id=task_id,
            bundle=bundle,
            task=task,
            runtime=runtime,
        )

    def _auto_record_wallet_usage_for_task(
        self,
        *,
        task_id: str,
        bundle: BundleConfig,
        task: TaskRequest,
    ) -> None:
        self._task_usage_accounting_facade().auto_record_wallet_usage_for_task(
            task_id=task_id,
            bundle=bundle,
            task=task,
        )

    def _record_session_usage_charge_for_task(
        self,
        *,
        task_id: str,
        task: TaskRequest,
        amount_q_atoms: int,
    ):
        return self._task_usage_accounting_facade().record_session_usage_charge_for_task(
            task_id=task_id,
            task=task,
            amount_q_atoms=amount_q_atoms,
        )

    def _provider_usage_contract_for_bundle(self, bundle: BundleConfig) -> dict:
        return self._task_usage_accounting_facade().provider_usage_contract_for_bundle(
            bundle
        )

    def _build_session_accounting_view(self, session) -> dict:
        return self._task_usage_accounting_facade().build_session_accounting_view(session)

    def _attach_usage_report_to_task_result(
        self,
        *,
        task_id: str,
        task: TaskRequest,
        measurement: WalletUsageMeasurement,
    ):
        return self._task_usage_accounting_facade().attach_usage_report_to_task_result(
            task_id=task_id,
            task=task,
            measurement=measurement,
        )

    def _record_session_usage_acknowledgement_for_task(
        self,
        *,
        task_id: str,
        task: TaskRequest,
        usage_report: dict | None,
        session_charge_result,
    ) -> None:
        self._task_usage_accounting_facade().record_session_usage_acknowledgement_for_task(
            task_id=task_id,
            task=task,
            usage_report=usage_report,
            session_charge_result=session_charge_result,
        )

    def accounting_contract_for_endpoint(self, endpoint) -> dict:
        return self._task_usage_accounting_facade().accounting_contract_for_endpoint(
            endpoint
        )

    def _mark_task_wallet_accounting_blocked(
        self,
        *,
        task_id: str,
        bundle_id: str,
        owner_id: str,
        reason: str,
        source: str = "task_auto",
        validation_errors=None,
    ) -> None:
        self._task_usage_accounting_facade().mark_task_wallet_accounting_blocked(
            task_id=task_id,
            bundle_id=bundle_id,
            owner_id=owner_id,
            reason=reason,
            source=source,
            validation_errors=validation_errors,
        )

    def _record_wallet_usage_skipped(
        self,
        *,
        task_id: str,
        bundle_id: str,
        owner_id: str,
        source: str,
        reason: str,
        strict_accounting: bool,
        validation_errors=None,
    ) -> None:
        self._task_usage_accounting_facade().record_wallet_usage_skipped(
            task_id=task_id,
            bundle_id=bundle_id,
            owner_id=owner_id,
            source=source,
            reason=reason,
            strict_accounting=strict_accounting,
            validation_errors=validation_errors,
        )

    def _wallet_usage_attribution_for_task(
        self,
        task: TaskRequest,
    ) -> tuple[str | None, str | None]:
        return self._task_usage_accounting_facade().wallet_usage_attribution_for_task(task)

    def _task_request_with_endpoint_context(self, request: TaskRequest) -> TaskRequest:
        return self._endpoint_execution_context_facade().task_request_with_endpoint_context(request)

    def _endpoint_requires_session(self, manifest) -> bool:
        return self._endpoint_execution_context_facade().endpoint_requires_session(manifest)

    def _validate_task_session(self, manifest, request: TaskRequest) -> None:
        self._endpoint_execution_context_facade().validate_task_session(manifest, request)

    def _touch_task_session(self, request: TaskRequest) -> None:
        self._runtime_boundary._runtime_execution_facade().touch_task_session(request)

    def _endpoint_manifest_for_request(self, request: TaskRequest):
        return self._runtime_boundary._runtime_execution_facade().endpoint_manifest_for_request(request)

    def _record_session_runtime_terminal_evidence(
        self,
        *,
        session_service,
        session,
        endpoint_manifest,
        result,
    ) -> None:
        self._runtime_boundary._record_session_runtime_terminal_evidence(
            session_service=session_service,
            session=session,
            endpoint_manifest=endpoint_manifest,
            result=result,
        )

    def close_endpoint_session(self, session_id: str):
        return self._runtime_boundary._runtime_execution_facade().close_endpoint_session(session_id)

    def propagate_proxy_session_close(self, session_id: str) -> None:
        self._runtime_boundary._runtime_execution_facade().propagate_proxy_session_close(session_id)

    def _close_remote_proxy_session_binding(
        self,
        session_service,
        binding: ProxySessionBinding,
    ) -> None:
        self._runtime_boundary._runtime_execution_facade().close_remote_proxy_session_binding(
            session_service,
            binding,
        )

    def _proxy_target_requires_remote_session(self, endpoint_manifest) -> bool:
        return self._runtime_boundary._runtime_execution_facade().proxy_target_requires_remote_session(
            endpoint_manifest
        )

    def _ensure_proxy_session_binding(self, endpoint_manifest, task_request: TaskRequest):
        return self._runtime_boundary._runtime_execution_facade().ensure_proxy_session_binding(
            endpoint_manifest,
            task_request,
        )

    def _attempt_proxy_task(self, task_id: str, task: QueuedTask, bundle: BundleConfig, endpoint_manifest) -> bool:
        return self._runtime_boundary._runtime_execution_facade().attempt_proxy_task(
            task_id,
            task,
            bundle,
            endpoint_manifest,
        )

    def _invoke_proxy_endpoint(self, endpoint_manifest, task_request: TaskRequest) -> dict:
        return self._runtime_boundary._runtime_execution_facade().invoke_proxy_endpoint(
            endpoint_manifest,
            task_request,
        )

    def _remote_request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
    ) -> dict:
        return self._remote_transport_facade().remote_request_json(
            method,
            url,
            payload,
        )

    def _default_remote_request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
    ) -> dict:
        return self._remote_transport_facade().default_remote_request_json(
            method,
            url,
            payload,
        )

    def _task_request_with_allocation_context(self, request: TaskRequest) -> TaskRequest:
        return self._endpoint_execution_context_facade().task_request_with_allocation_context(request)

    def _restored_task_status(self, task: TaskSnapshot) -> str:
        return self._snapshot_state_facade().restored_task_status(task)

    def _can_retry_after_restart(self, task: TaskSnapshot) -> bool:
        return self._snapshot_state_facade().can_retry_after_restart(task)

    def _restore_runtimes(self, runtimes: list[RuntimeSnapshot]) -> None:
        self._runtime_boundary._restore_runtimes(runtimes)

    def _clear_runtime_reservations(self) -> None:
        self._runtime_boundary._clear_runtime_reservations()

    def _replace_runtimes(self, runtimes: list[RuntimeHandle]) -> None:
        self._runtime_boundary._replace_runtimes(runtimes)

    def _on_runtime_state_change(self, runtime: RuntimeHandle) -> None:
        """Persist process exits and wake the global scheduler after release."""

        self._persist_state(runtime)
        if runtime.status != "stopped":
            return
        # A watcher runs on a daemon thread.  Scheduler failures must never
        # escape into that thread; the next API/MCP reconciliation remains a
        # safe retry path if an external provider is still settling.
        try:
            self.reconcile_scheduler(trigger="runtime_exit")
        except Exception:
            return

    def _persist_state(self, _runtime: RuntimeHandle | None = None) -> None:
        """Persist the current snapshot.

        ``ProviderProcessManager`` invokes the callback with the runtime that
        changed.  A failed child must release its residency reservation before
        the snapshot is written; otherwise a dead runtime can keep VRAM/RAM
        reserved forever and block the next activation.
        """
        if _runtime is not None and _runtime.status == "stopped" and _runtime.bundle_id:
            self._release_runtime_reservation(_runtime.bundle_id)
        if self.state_store is None:
            return
        with self._persistence_lock:
            self.state_store.save(self.snapshot_state())

    def _provider_installation_facade(self) -> ProviderInstallationService:
        facade = getattr(self, "_provider_installation_service", None)
        if facade is None:
            facade = ProviderInstallationService(self)
            self._provider_installation_service = facade
        return facade

    def _task_execution_facade(self) -> TaskExecutionService:
        facade = getattr(self, "_task_execution_service", None)
        if facade is None:
            facade = TaskExecutionService(self)
            self._task_execution_service = facade
        return facade

    def _task_lifecycle_facade(self) -> TaskLifecycleService:
        facade = getattr(self, "_task_lifecycle_service", None)
        if facade is None:
            facade = TaskLifecycleService(self)
            self._task_lifecycle_service = facade
        return facade

    def _endpoint_execution_context_facade(self) -> EndpointExecutionContextService:
        facade = getattr(self, "_endpoint_execution_context_service", None)
        if facade is None:
            facade = EndpointExecutionContextService(self)
            self._endpoint_execution_context_service = facade
        return facade

    def _task_usage_accounting_facade(self) -> TaskUsageAccountingService:
        facade = getattr(self, "_task_usage_accounting_service", None)
        if facade is None:
            facade = TaskUsageAccountingService(self)
            self._task_usage_accounting_service = facade
        return facade

    def _snapshot_state_facade(self) -> SnapshotStateService:
        facade = getattr(self, "_snapshot_state_service", None)
        if facade is None:
            facade = SnapshotStateService(self)
            self._snapshot_state_service = facade
        return facade

    def _remote_transport_facade(self) -> RemoteTransportService:
        facade = getattr(self, "_remote_transport_service", None)
        if facade is None:
            facade = RemoteTransportService(self)
            self._remote_transport_service = facade
        return facade

    def _allocation_lifecycle_facade(self) -> AllocationLifecycleService:
        facade = getattr(self, "_allocation_lifecycle_service", None)
        if facade is None:
            facade = AllocationLifecycleService(self)
            self._allocation_lifecycle_service = facade
        return facade

    def _allocation_catalog_facade(self) -> AllocationCatalogService:
        facade = getattr(self, "_allocation_catalog_service", None)
        if facade is None:
            facade = AllocationCatalogService(self)
            self._allocation_catalog_service = facade
        return facade

    def _model_install_facade(self) -> ModelInstallService:
        facade = getattr(self, "_model_install_service", None)
        if facade is None:
            facade = ModelInstallService(self)
            self._model_install_service = facade
        return facade

    def _operator_application_facade(self) -> OperatorApplicationService:
        facade = getattr(self, "_operator_application_service", None)
        if facade is None:
            facade = OperatorApplicationService(self)
            self._operator_application_service = facade
        return facade

    def _event_projection_facade(self) -> EventProjectionService:
        facade = getattr(self, "_event_projection_service", None)
        if facade is None:
            facade = EventProjectionService(self)
            self._event_projection_service = facade
        return facade

    def _integration_facade(self) -> HypervisorIntegrationService:
        facade = getattr(self, "_integration_service", None)
        if facade is None:
            facade = HypervisorIntegrationService(self)
            self._integration_service = facade
        return facade

    def _provider_inventory_application_facade(
        self,
    ) -> ProviderInventoryApplicationService:
        facade = getattr(self, "_provider_inventory_application_service", None)
        if facade is None:
            facade = ProviderInventoryApplicationService(self)
            self._provider_inventory_application_service = facade
        return facade

    def _wallet_application_facade(self) -> WalletApplicationService:
        facade = getattr(self, "_wallet_application_service", None)
        if facade is None:
            facade = WalletApplicationService(self)
            self._wallet_application_service = facade
        return facade

    def _settlement_application_facade(self) -> SettlementApplicationService:
        facade = getattr(self, "_settlement_application_service", None)
        if facade is None:
            facade = SettlementApplicationService(self)
            self._settlement_application_service = facade
        return facade

    def _allocation_unavailable_error(self, **kwargs) -> AllocationUnavailableError:
        return AllocationUnavailableError(**kwargs)

    def _wallet_allocation_now(self) -> float:
        return time.time()

    def _current_time_seconds(self) -> float:
        return time.time()

    def _retry_sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def _prune_wallet_usage_events(self) -> None:
        self._wallet_economics_service.prune_wallet_usage_events()

    def _replace_bundle(self, updated_bundle: BundleConfig) -> None:
        self._runtime_boundary._bundle_runtime_policy_facade().replace_bundle(updated_bundle)

    def _persist_bundle_config_if_available(self) -> None:
        self._runtime_boundary._bundle_runtime_policy_facade().persist_bundle_config_if_available()

    def _require_bundle_registry(self):
        return self._runtime_boundary._bundle_runtime_policy_facade().require_bundle_registry()

    def _validate_bundles(self, bundles: list[BundleConfig]) -> None:
        self._runtime_boundary._bundle_runtime_policy_facade().validate_bundles(bundles)

    def _has_plugins(self) -> bool:
        if hasattr(self.plugins, "list"):
            return bool(self.plugins.list())
        return bool(self.plugins)

    def _active_bundle_task_count(
        self, bundle_id: str, *, exclude_task_id: str | None = None
    ) -> int:
        return self._runtime_boundary._bundle_runtime_policy_facade().active_bundle_task_count(
            bundle_id,
            exclude_task_id=exclude_task_id,
        )

    def _pending_task_order(self) -> list[str]:
        return self._runtime_boundary._admission_planning_facade().pending_task_order()

    def _pending_task_plan(self) -> list[dict[str, int | str]]:
        return self._runtime_boundary._admission_planning_facade().pending_task_plan()

    def _effective_task_priority(self, task: QueuedTask) -> int:
        return self._runtime_boundary._admission_planning_facade().effective_task_priority(task)

    def _aging_bonus(self, task: QueuedTask) -> int:
        return self._runtime_boundary._admission_planning_facade().aging_bonus(task)

    def _selection_reason(
        self,
        *,
        tasks_by_bundle: dict[str, list[QueuedTask]],
        dispatch_candidates: list[str],
        next_bundle_id: str,
    ) -> str:
        return self._runtime_boundary._admission_planning_facade().selection_reason(
            tasks_by_bundle=tasks_by_bundle,
            dispatch_candidates=dispatch_candidates,
            next_bundle_id=next_bundle_id,
        )

    def _eviction_candidates(self, *, waiting_task: TaskRequest) -> list[BundleConfig]:
        return self._runtime_boundary._bundle_runtime_policy_facade().eviction_candidates(
            waiting_task=waiting_task
        )

    def _diagnose_queued_task(self, task_id: str) -> dict[str, str]:
        return self._runtime_boundary._bundle_runtime_policy_facade().diagnose_queued_task(task_id)

    def _eviction_blocked(
        self,
        waiting_task: TaskRequest,
        requested_bundle: BundleConfig,
    ) -> bool:
        return self._runtime_boundary._bundle_runtime_policy_facade().eviction_blocked(
            waiting_task,
            requested_bundle,
        )
