import hashlib
import json
import time
from copy import deepcopy
from datetime import UTC, datetime

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
from aidn_hypervisor.event_projection_service import EventProjectionService
from aidn_hypervisor.hypervisor_integration_service import (
    HypervisorIntegrationService,
)
from aidn_hypervisor.ledger.service import LedgerOperationService
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
from aidn_hypervisor.registry_models import (
    RegistryPricing,
    RegistryRating,
)
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.remote_transport_service import RemoteTransportService
from aidn_hypervisor.runtime_execution_service import RuntimeExecutionService
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
    "consensus": 0.3,
    "registry": 0.3,
    "validation": 0.3,
    "faucet": 0.1,
}


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


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
        plugin_package_store: PluginPackageStore | None = None,
        plugin_host_secret_manager=None,
        runtime_protocol_store=None,
        registry_service: RegistryService | None = None,
        consensus_service=None,
        consensus_finality_source=None,
        canonical_wallet_balance_provider=None,
    ) -> None:
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
            package_store=plugin_package_store,
            plugin_host_secret_manager=plugin_host_secret_manager,
        )
        self.registry_service = registry_service
        self.consensus_service = consensus_service
        self.consensus_finality_source = consensus_finality_source
        self.canonical_wallet_balance_provider = canonical_wallet_balance_provider
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

        self._settlement_application_service = SettlementApplicationService(self)
        self.operator_read_models = OperatorReadModelService(self)
        self._events: list[JournalEvent] = []
        self._runtime_boundary = RuntimeProtocolBoundaryService(self)

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
        output_tokens: int | None,
        fixed_request_count: int = 1,
        audio_input_seconds: float | None = None,
    ) -> dict:
        return self._wallet_application_facade().quote_wallet_usage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            fixed_request_count=fixed_request_count,
            audio_input_seconds=audio_input_seconds,
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
        output_tokens: int | None,
        fixed_request_count: int = 1,
        audio_input_seconds: float | None = None,
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
            output_tokens=output_tokens,
            fixed_request_count=fixed_request_count,
            audio_input_seconds=audio_input_seconds,
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
    ) -> dict:
        return self._model_install_facade().request_model_install(
            provider_type=provider_type,
            model_id=model_id,
            source_url=source_url,
            requested_by=requested_by,
        )

    def list_model_installs(self) -> list[dict]:
        return self._model_install_facade().list_model_installs()

    def process_model_installs(self, *, limit: int | None = None) -> list[dict]:
        return self._model_install_facade().process_model_installs(limit=limit)

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

    def apply_provider_installation_approval(self, approval_id: str) -> dict:
        return self._provider_installation_facade().apply_provider_installation_approval(
            approval_id
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
    ) -> dict:
        return self._provider_inventory_application_facade().register_bundle_from_install(
            install_id=install_id,
            bundle_id=bundle_id,
            workload_type=workload_type,
            endpoint=endpoint,
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
    ) -> JournalEvent:
        return self._event_projection_facade().record_event(
            event_type=event_type,
            message=message,
            task_id=task_id,
            bundle_id=bundle_id,
            runtime_id=runtime_id,
            details=details,
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
        return self._runtime_boundary._bundle_runtime_policy_facade().set_bundle_enabled(
            bundle_id,
            enabled,
        )

    def drain_runtime(self, runtime_id: str) -> dict[str, str | bool]:
        return self._runtime_boundary.drain_runtime(runtime_id)

    def force_stop_runtime(self, runtime_id: str) -> dict[str, str]:
        return self._runtime_boundary.force_stop_runtime(runtime_id)

    def restart_runtime(self, runtime_id: str) -> dict[str, str]:
        return self._runtime_boundary.restart_runtime(runtime_id)

    def cancel_task(self, task_id: str):
        return self._task_lifecycle_facade().cancel_task(task_id)

    def start_bundle(self, bundle_id: str) -> RuntimeHandle:
        return self._runtime_boundary._bundle_runtime_policy_facade().start_bundle(bundle_id)

    def stop_bundle(self, bundle_id: str) -> dict[str, str]:
        return self._runtime_boundary._bundle_runtime_policy_facade().stop_bundle(bundle_id)

    def list_runtimes(self) -> list[RuntimeHandle]:
        return self._runtime_boundary.list_runtimes()

    def process_pending(self) -> dict[str, int]:
        return self._task_lifecycle_facade().process_pending()

    def queue_summary(self) -> dict[str, int]:
        return self._task_lifecycle_facade().queue_summary()

    def queue_diagnostics(self) -> list[dict[str, str]]:
        return self._runtime_boundary._admission_planning_facade().queue_diagnostics()

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

    def _reconcile_pending_allocations(self) -> None:
        self._allocation_catalog_facade().reconcile_pending_allocations()

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

    def _stop_runtime_for_bundle(self, bundle: BundleConfig) -> None:
        self._runtime_boundary._stop_runtime_for_bundle(bundle)

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
    ) -> dict:
        return self._task_execution_facade().invoke_with_retry(
            plugin,
            bundle,
            task,
            runtime,
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
        amount_q: float,
    ):
        return self._task_usage_accounting_facade().record_session_usage_charge_for_task(
            task_id=task_id,
            task=task,
            amount_q=amount_q,
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

    def _persist_state(self) -> None:
        if self.state_store is None:
            return
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
