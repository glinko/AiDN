from __future__ import annotations

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.domain.models import AllocationRequest
from aidn_hypervisor.economics.models import (
    EpochRewardBudget,
    FaucetClaim,
    RecyclableRemoval,
)
from aidn_hypervisor.endpoints.state import (
    EndpointConfigurationSnapshotRecord,
    EndpointManifestSnapshot,
)
from aidn_hypervisor.ledger.models import LedgerOperationRecord
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore
from aidn_hypervisor.queue import QueuedTask
from aidn_hypervisor.state import (
    AllocationSnapshot,
    BundleStateSnapshot,
    EndpointSessionSnapshot,
    HypervisorStateSnapshot,
    LockedDepositSnapshot,
    ModelInstallSnapshot,
    OperatorOnboardingSnapshot,
    OwnerWalletSnapshot,
    ProxySessionBindingSnapshot,
    RuntimeSnapshot,
    TaskSnapshot,
    WalletAllocationActivationSnapshot,
    WalletAllocationCorrectionSnapshot,
    WalletAllocationDisputeSnapshot,
    WalletAllocationSnapshot,
    WalletLedgerSnapshot,
    WalletSessionSnapshot,
    WalletUsageSnapshot,
)

_ACTIVE_EXECUTION_STATUSES = {"admitted", "starting", "running"}


class SnapshotStateService:
    """Snapshot persistence and restart recovery orchestration."""

    def __init__(self, host) -> None:
        self._host = host

    def snapshot_state(self) -> HypervisorStateSnapshot:
        endpoint_service = getattr(self._host, "endpoint_service", None)
        endpoint_store = getattr(endpoint_service, "store", None)
        session_service = getattr(self._host, "session_service", None)
        session_store = getattr(session_service, "store", None)
        failure_handler = getattr(session_service, "failure_handler", None)
        persisted_snapshot = (
            self._host.state_store.load()
            if self._host.state_store is not None and hasattr(self._host.state_store, "load")
            else None
        )
        return HypervisorStateSnapshot(
            tasks=[
                TaskSnapshot(
                    task_id=task.task_id,
                    priority=task.priority,
                    enqueue_index=task.enqueue_index,
                    created_at=task.created_at,
                    status=task.status,
                    request=task.request.model_copy(deep=True),
                    bundle_id=self._host.selected_bundle_id(task.task_id),
                    result=self._host._task_results.get(task.task_id),
                    recovery_reason=self._host.task_recovery_reason(task.task_id),
                )
                for task in self._host.queue.snapshot()
            ],
            runtimes=[
                RuntimeSnapshot(
                    runtime_id=runtime.runtime_id,
                    command=list(runtime.command),
                    status=runtime.status,
                    bundle_id=runtime.bundle_id,
                    health_status=runtime.health_status,
                    last_error=runtime.last_error,
                    metadata=dict(runtime.metadata),
                )
                for runtime in self._host.list_runtimes()
            ],
            bundle_states=[
                BundleStateSnapshot(**self._host._current_bundle_state(bundle.bundle_id))
                for bundle in self._host.bundles
                if self._host._bundle_state_is_non_default(bundle.bundle_id)
            ],
            allocations=[
                AllocationSnapshot(
                    allocation_id=allocation["allocation_id"],
                    request=AllocationRequest(**allocation["request"]),
                    bundle_id=allocation["bundle_id"],
                    runtime_id=allocation["runtime_id"],
                    endpoint=allocation["endpoint"],
                    status=allocation["status"],
                    created_at=allocation["created_at"],
                    expires_at=allocation["expires_at"],
                    reservation_id=allocation.get("reservation_id"),
                    reason=allocation.get("reason"),
                )
                for allocation in self._host._allocations.values()
            ],
            model_installs=[ModelInstallSnapshot(**job) for job in self._host._model_installs.values()],
            plugin_releases=[
                release.model_copy(deep=True) for release in self._host.provider_inventory.list_plugin_releases()
            ],
            installed_plugins=[
                installed_plugin.model_copy(deep=True)
                for installed_plugin in self._host.provider_inventory.list_installed_plugins()
            ],
            provider_instances=[
                instance.model_copy(deep=True) for instance in self._host.provider_inventory.list_provider_instances()
            ],
            model_deployments=[
                deployment.model_copy(deep=True)
                for deployment in self._host.provider_inventory.list_model_deployments()
            ],
            runtime_bindings=[
                binding.model_copy(deep=True) for binding in self._host.provider_inventory.list_runtime_bindings()
            ],
            provider_artifact_materializations=[
                materialization.model_copy(deep=True)
                for materialization in self._host.provider_inventory.list_artifact_materializations()
            ],
            provider_installation_approvals=[
                approval.model_copy(deep=True)
                for approval in self._host.provider_inventory.list_installation_approvals()
            ],
            provider_installation_jobs=[
                job.model_copy(deep=True) for job in self._host.provider_inventory.list_installation_jobs()
            ],
            plugin_host_connections=self._host.provider_inventory.plugin_host_connection_store.snapshot(),
            runtime_protocol_connections=list(self._host.runtime_protocol_store.connections.values()),
            runtime_protocol_ready_states=list(self._host.runtime_protocol_store.ready_states.values()),
            runtime_protocol_health_records=list(self._host.runtime_protocol_store.health_records.values()),
            runtime_protocol_capacity_records=list(self._host.runtime_protocol_store.capacity_records.values()),
            runtime_protocol_messages=list(self._host.runtime_protocol_store.messages.values()),
            runtime_protocol_sequences=dict(self._host.runtime_protocol_store.runtime_sequences),
            runtime_protocol_requests=list(self._host.runtime_protocol_store.requests.values()),
            runtime_protocol_cancellations=list(self._host.runtime_protocol_store.cancellations.values()),
            runtime_protocol_cancellation_results=list(self._host.runtime_protocol_store.cancellation_results.values()),
            runtime_protocol_results=list(self._host.runtime_protocol_store.results.values()),
            runtime_protocol_streams=list(self._host.runtime_protocol_store.streams.values()),
            runtime_protocol_stream_chunks=[
                chunk
                for chunks in self._host.runtime_protocol_store.stream_chunks.values()
                for chunk in chunks.values()
            ],
            runtime_protocol_stream_closes=list(self._host.runtime_protocol_store.stream_closes.values()),
            runtime_protocol_artifacts=list(self._host.runtime_protocol_store.artifacts.values()),
            runtime_protocol_state_checkpoints=list(self._host.runtime_protocol_store.state_checkpoints.values()),
            runtime_protocol_recovery_states=list(self._host.runtime_protocol_store.recovery_states.values()),
            runtime_protocol_usage_reports=list(self._host.runtime_protocol_store.usage_reports.values()),
            runtime_protocol_usage_acks=list(self._host.runtime_protocol_store.usage_acks.values()),
            runtime_protocol_usage_conflicts=list(self._host.runtime_protocol_store.usage_conflicts.values()),
            runtime_protocol_recovery_plans=list(self._host.runtime_protocol_store.recovery_plans.values()),
            runtime_protocol_recovery_results=list(self._host.runtime_protocol_store.recovery_results.values()),
            runtime_protocol_drain_requests=list(self._host.runtime_protocol_store.drain_requests.values()),
            runtime_protocol_drain_statuses=list(self._host.runtime_protocol_store.drain_statuses.values()),
            runtime_protocol_drain_completes=list(self._host.runtime_protocol_store.drain_completes.values()),
            runtime_protocol_shutdowns=list(self._host.runtime_protocol_store.shutdowns.values()),
            operator_requests_policy=dict(self._host._operator_requests_policy),
            owner_wallet=(
                OwnerWalletSnapshot(**self._host._owner_wallet) if self._host._owner_wallet is not None else None
            ),
            operator_onboarding=(
                OperatorOnboardingSnapshot(**self._host._operator_onboarding)
                if self._host._operator_onboarding is not None
                else None
            ),
            wallet_usage_events=[WalletUsageSnapshot(**event) for event in self._host._wallet_usage_events],
            wallet_session_events=[WalletSessionSnapshot(**event) for event in self._host._wallet_session_events],
            wallet_ledger_events=[WalletLedgerSnapshot(**event) for event in self._host._wallet_ledger_events],
            wallet_economics_events=[WalletLedgerSnapshot(**event) for event in self._host._wallet_economics_events],
            wallet_allocation_activation_events=[
                WalletAllocationActivationSnapshot(**event) for event in self._host._wallet_allocation_activation_events
            ],
            wallet_allocation_dispute_events=[
                WalletAllocationDisputeSnapshot(**event) for event in self._host._wallet_allocation_dispute_events
            ],
            wallet_allocation_correction_events=[
                WalletAllocationCorrectionSnapshot(**event) for event in self._host._wallet_allocation_correction_events
            ],
            wallet_allocation_events=[
                WalletAllocationSnapshot(**event) for event in self._host._wallet_allocation_events
            ],
            recyclable_removals=[RecyclableRemoval(**event) for event in self._host._recyclable_removals],
            faucet_claims=[FaucetClaim(**event) for event in self._host._faucet_claims],
            epoch_reward_budgets=[EpochRewardBudget(**event) for event in self._host._epoch_reward_budgets],
            endpoints=(
                [
                    EndpointManifestSnapshot.model_validate(item.model_dump(mode="json"))
                    for item in endpoint_store.list_manifests()
                ]
                if endpoint_store is not None
                else (
                    [item.model_copy(deep=True) for item in persisted_snapshot.endpoints]
                    if persisted_snapshot is not None
                    else []
                )
            ),
            wallet_identities=list(self._host._wallet_identities.values()),
            consumed_wallet_authorization_nonces=sorted(self._host._consumed_wallet_authorization_nonces),
            endpoint_configuration_snapshots=(
                [
                    EndpointConfigurationSnapshotRecord.model_validate(item.model_dump(mode="json"))
                    for item in endpoint_store.list_all_configuration_snapshots()
                ]
                if endpoint_store is not None and hasattr(endpoint_store, "list_all_configuration_snapshots")
                else (
                    [item.model_copy(deep=True) for item in persisted_snapshot.endpoint_configuration_snapshots]
                    if persisted_snapshot is not None
                    else []
                )
            ),
            endpoint_sessions=(
                [
                    EndpointSessionSnapshot.model_validate(item.model_dump(mode="json"))
                    for item in session_store.list_sessions()
                ]
                if session_store is not None
                else (
                    [item.model_copy(deep=True) for item in persisted_snapshot.endpoint_sessions]
                    if persisted_snapshot is not None
                    else []
                )
            ),
            locked_deposits=(
                [
                    LockedDepositSnapshot.model_validate(item.model_dump(mode="json"))
                    for item in session_store.list_deposits()
                ]
                if session_store is not None and hasattr(session_store, "list_deposits")
                else (
                    [item.model_copy(deep=True) for item in persisted_snapshot.locked_deposits]
                    if persisted_snapshot is not None
                    else []
                )
            ),
            proxy_session_bindings=(
                [
                    ProxySessionBindingSnapshot.model_validate(item.model_dump(mode="json"))
                    for item in session_store.list_proxy_session_bindings()
                ]
                if session_store is not None and hasattr(session_store, "list_proxy_session_bindings")
                else (
                    [item.model_copy(deep=True) for item in persisted_snapshot.proxy_session_bindings]
                    if persisted_snapshot is not None
                    else []
                )
            ),
            session_failure_evidence=(
                failure_handler.snapshot_evidence()
                if failure_handler is not None
                else (
                    [item.model_copy(deep=True) for item in persisted_snapshot.session_failure_evidence]
                    if persisted_snapshot is not None
                    else []
                )
            ),
            session_failure_reports=(
                failure_handler.snapshot_reports()
                if failure_handler is not None
                else (
                    [item.model_copy(deep=True) for item in persisted_snapshot.session_failure_reports]
                    if persisted_snapshot is not None
                    else []
                )
            ),
            ledger_operations=self._host.list_ledger_operations(),
            pending_consensus_operations=[
                LedgerOperationRecord.model_validate(item) for item in self._host._pending_consensus_operations.values()
            ],
            pending_consensus_envelopes=[
                LedgerOperationEnvelope.model_validate(item)
                for item in self._host._pending_consensus_envelopes.values()
            ],
            pending_owner_wallet_bootstraps=[
                dict(item) for item in self._host._pending_owner_wallet_bootstraps
            ],
            wallet_operation_sequences=self._host._ledger_operation_service.snapshot_wallet_sequences(),
            **self._host._ledger_operation_service.snapshot_settlement_state(),
            events=[event.model_copy(deep=True) for event in self._host._events],
        )

    def restore_state(self, snapshot: HypervisorStateSnapshot) -> dict[str, int]:
        self._host._selected_bundles = {}
        self._host._task_results = {}
        self._host._task_recovery_reasons = {}
        self._host._allocations = {}
        self._host._model_installs = {}
        self._host._operator_requests_policy = dict(snapshot.operator_requests_policy)
        self._host._owner_wallet = (
            snapshot.owner_wallet.model_dump(mode="json") if snapshot.owner_wallet is not None else None
        )
        self._host._operator_onboarding = (
            snapshot.operator_onboarding.model_dump(mode="json") if snapshot.operator_onboarding is not None else None
        )
        self._host._wallet_usage_events = []
        self._host._wallet_session_events = []
        self._host._wallet_ledger_events = []
        self._host._wallet_economics_events = []
        self._host._recyclable_removals = []
        self._host._faucet_claims = []
        self._host._epoch_reward_budgets = []
        self._host._wallet_allocation_activation_events = []
        self._host._wallet_allocation_dispute_events = []
        self._host._wallet_allocation_correction_events = []
        self._host._wallet_allocation_events = []
        self._host._ledger_operation_service.restore(
            operations=[event.model_dump(mode="json") for event in snapshot.ledger_operations],
            wallet_sequences=dict(snapshot.wallet_operation_sequences),
            wallet_q_atom_balances=dict(snapshot.wallet_q_atom_balances),
            recyclable_q_atoms=int(snapshot.recyclable_q_atoms),
            burned_q_atoms=int(snapshot.burned_q_atoms),
            stake_records=[dict(item) for item in snapshot.stake_records],
            participant_suspensions=[dict(item) for item in snapshot.participant_suspensions],
            session_funding_accounts=[item.model_dump(mode="json") for item in snapshot.session_funding_accounts],
            settlement_proposals=[item.model_dump(mode="json") for item in snapshot.settlement_proposals],
            settlement_acceptances=[item.model_dump(mode="json") for item in snapshot.settlement_acceptances],
            session_checkpoints=[item.model_dump(mode="json") for item in snapshot.session_checkpoints],
            settlement_disputes=[item.model_dump(mode="json") for item in snapshot.settlement_disputes],
            settlement_corrections=[item.model_dump(mode="json") for item in snapshot.settlement_corrections],
            settlement_transition_hashes=dict(snapshot.settlement_transition_hashes),
            development_pool_allocations=[dict(item) for item in snapshot.development_pool_allocations],
            development_pool_carryovers=[dict(item) for item in snapshot.development_pool_carryovers],
            development_bounty_states=[dict(item) for item in snapshot.development_bounty_states],
            development_reward_reserves=[dict(item) for item in snapshot.development_reward_reserves],
            development_reward_payment_records=[dict(item) for item in snapshot.development_reward_payment_records],
            development_reward_unclaimed_records=[dict(item) for item in snapshot.development_reward_unclaimed_records],
            development_reward_claim_records=[dict(item) for item in snapshot.development_reward_claim_records],
            development_reward_expiry_records=[dict(item) for item in snapshot.development_reward_expiry_records],
            development_reward_finalized_commitments=[
                dict(item) for item in snapshot.development_reward_finalized_commitments
            ],
            development_reward_adjustment_snapshots=[
                dict(item) for item in snapshot.development_reward_adjustment_snapshots
            ],
            development_reward_cancellations=[dict(item) for item in snapshot.development_reward_cancellations],
            development_reward_corrections=[dict(item) for item in snapshot.development_reward_corrections],
        )
        self._host._pending_consensus_operations = {
            item.operation_id: item.model_dump(mode="json") for item in snapshot.pending_consensus_operations
        }
        self._host._pending_consensus_envelopes = {
            item.operation_id: item.model_dump(mode="json") for item in snapshot.pending_consensus_envelopes
        }
        self._host._pending_owner_wallet_bootstraps = [
            dict(item) for item in snapshot.pending_owner_wallet_bootstraps
        ]
        self._host._wallet_identities = {item["wallet_id"]: dict(item) for item in snapshot.wallet_identities}
        self._host._consumed_wallet_authorization_nonces = set(snapshot.consumed_wallet_authorization_nonces)
        self._host._bundle_states = {state.bundle_id: state.model_dump(mode="json") for state in snapshot.bundle_states}
        self._host._events = [event.model_copy(deep=True) for event in snapshot.events]
        session_service = getattr(self._host, "session_service", None)
        failure_handler = getattr(session_service, "failure_handler", None)
        if failure_handler is not None:
            failure_handler.restore_evidence(
                evidence=snapshot.session_failure_evidence,
                reports=snapshot.session_failure_reports,
            )
        for allocation in snapshot.allocations:
            self._host._allocations[allocation.allocation_id] = {
                "allocation_id": allocation.allocation_id,
                "request": allocation.request.model_dump(mode="json"),
                "workload_type": allocation.request.workload_type,
                "bundle_id": allocation.bundle_id,
                "runtime_id": allocation.runtime_id,
                "endpoint": allocation.endpoint,
                "status": allocation.status,
                "created_at": allocation.created_at,
                "expires_at": allocation.expires_at,
                "reservation_id": allocation.reservation_id,
                "reason": allocation.reason,
            }
        for job in snapshot.model_installs:
            self._host._model_installs[job.install_id] = job.model_dump(mode="json")
        installation_executor = getattr(
            self._host.provider_inventory,
            "installation_executor",
            None,
        )
        self._host.provider_inventory = ProviderInventoryService(
            plugins=self._host.plugins,
            store=InMemoryProviderInventoryStore(),
            installation_executor=installation_executor,
            package_store=self._host._plugin_package_store,
            plugin_host_connections=[item.model_dump(mode="json") for item in snapshot.plugin_host_connections],
        )
        for release in snapshot.plugin_releases:
            self._host.provider_inventory.store.save_plugin_release(release)
        for installed_plugin in snapshot.installed_plugins:
            self._host.provider_inventory.store.save_installed_plugin(installed_plugin)
        for instance in snapshot.provider_instances:
            self._host.provider_inventory.store.save_provider_instance(instance)
        for deployment in snapshot.model_deployments:
            self._host.provider_inventory.store.save_model_deployment(deployment)
        for binding in snapshot.runtime_bindings:
            self._host.provider_inventory.store.save_runtime_binding(binding)
        # Compatibility Bundles are derived from Runtime Bindings and must be
        # rebuilt after restart. They are intentionally not treated as an
        # independent source of truth: Provider configuration plus the
        # persisted binding is the durable input for this projection.
        for binding in snapshot.runtime_bindings:
            self._host._replace_bundle(
                self._host.provider_inventory.bundle_config_for_runtime_binding(
                    binding.runtime_binding_id
                )
            )
        self._host._persist_bundle_config_if_available()
        for materialization in snapshot.provider_artifact_materializations:
            self._host.provider_inventory.store.save_artifact_materialization(materialization)
        for approval in snapshot.provider_installation_approvals:
            self._host.provider_inventory.store.save_installation_approval(approval)
        for job in snapshot.provider_installation_jobs:
            self._host.provider_inventory.store.save_installation_job(job)
        self._host.runtime_protocol_store.restore(snapshot)
        self._restore_wallet_sequences(snapshot)

        restored_tasks: list[QueuedTask] = []
        for task in snapshot.tasks:
            restored_status = self.restored_task_status(task)
            restored_tasks.append(
                QueuedTask(
                    priority=task.priority,
                    enqueue_index=task.enqueue_index,
                    created_at=task.created_at,
                    task_id=task.task_id,
                    request=task.request.model_copy(deep=True),
                    status=restored_status,
                )
            )
            if task.bundle_id is not None:
                self._host._selected_bundles[task.task_id] = task.bundle_id
            if task.recovery_reason is not None:
                self._host._task_recovery_reasons[task.task_id] = task.recovery_reason
            if task.status in _ACTIVE_EXECUTION_STATUSES:
                recovery_reason = self.recovery_reason_for_task(task)
                self._host._task_recovery_reasons[task.task_id] = recovery_reason
                self._host.record_event(
                    event_type="task.recovered",
                    message=self.recovery_message(recovery_reason),
                    task_id=task.task_id,
                    bundle_id=task.bundle_id,
                    details={
                        "previous_status": task.status,
                        "restored_status": restored_status,
                        "recovery_reason": recovery_reason,
                    },
                )
            if restored_status == "completed" and task.result is not None:
                self._host._task_results[task.task_id] = dict(task.result)

        self._host.queue.restore(restored_tasks)
        self.restore_runtimes(snapshot.runtimes)
        summary = self._host.queue_summary()
        self._host._persist_state()
        return summary

    def restored_task_status(self, task) -> str:
        if task.status not in _ACTIVE_EXECUTION_STATUSES:
            return task.status
        if self.can_retry_after_restart(task):
            return "queued"
        return "failed"

    def recovery_reason_for_task(self, task) -> str:
        if self.can_retry_after_restart(task):
            return "restart_retry_queued"
        return "restart_failed_unknown_inflight"

    def recovery_message(self, recovery_reason: str) -> str:
        if recovery_reason == "restart_retry_queued":
            return "in-flight task requeued during restart recovery"
        return "unknown in-flight task failed during restart recovery"

    def can_retry_after_restart(self, task) -> bool:
        if not task.request.constraints.get("retry_on_restart"):
            return False
        if task.bundle_id is None:
            return False
        try:
            bundle = self._host._get_bundle(task.bundle_id)
            plugin = self._host._get_plugin(bundle.plugin_id)
        except KeyError:
            return False
        return plugin.supports_restart_retry(task.request, bundle)

    def restore_runtimes(self, runtimes: list[RuntimeSnapshot]) -> None:
        self.clear_runtime_reservations()
        recovered_runtimes: list[RuntimeHandle] = []

        for runtime in runtimes:
            if runtime.status != "running" or runtime.bundle_id is None:
                continue

            try:
                bundle = self._host._get_bundle(runtime.bundle_id)
                plugin = self._host._get_plugin(bundle.plugin_id)
            except KeyError:
                continue

            recovered_runtime = RuntimeHandle(
                runtime_id=runtime.runtime_id,
                command=list(runtime.command),
                status=runtime.status,
                bundle_id=runtime.bundle_id,
                health_status=runtime.health_status,
                last_error=runtime.last_error,
                metadata=dict(runtime.metadata),
            )
            if self._host._bundle_in_cooldown(runtime.bundle_id):
                recovered_runtime.health_status = "cooldown"
                recovered_runtime.last_error = self._host._current_bundle_state(runtime.bundle_id)["cooldown_reason"]
                recovered_runtimes.append(recovered_runtime)
                continue
            if not self._host._health_check_with_retry(
                plugin,
                recovered_runtime,
                runtime.bundle_id,
            ):
                self._host.record_event(
                    event_type="runtime.recovery_skipped",
                    message="runtime health check failed during restart recovery",
                    bundle_id=runtime.bundle_id,
                    runtime_id=runtime.runtime_id,
                )
                continue

            profile = bundle.resource_profile
            if self._host.resources is not None and not self._host.resources.can_fit(
                profile.steady_cpu,
                profile.steady_ram_mb,
                profile.steady_vram_mb,
            ):
                self._host.record_event(
                    event_type="runtime.recovery_skipped",
                    message="runtime recovery skipped due to insufficient resources",
                    bundle_id=runtime.bundle_id,
                    runtime_id=runtime.runtime_id,
                )
                continue

            recovered_runtime.health_status = "healthy"
            recovered_runtime.last_error = None
            if self._host.resources is not None:
                self._host._reserve_runtime_residency(
                    bundle.bundle_id,
                    cpu=profile.steady_cpu,
                    ram_mb=profile.steady_ram_mb,
                    vram_mb=profile.steady_vram_mb,
                )
            self._host.record_event(
                event_type="runtime.recovered",
                message="runtime reconnected during restart recovery",
                bundle_id=runtime.bundle_id,
                runtime_id=runtime.runtime_id,
            )
            recovered_runtimes.append(recovered_runtime)

        self.replace_runtimes(recovered_runtimes)

    def clear_runtime_reservations(self) -> None:
        if self._host.resources is None:
            self._host._runtime_reservations.clear()
            return

        for reservation_id in list(self._host._runtime_reservations):
            self._host.resources.release(reservation_id)
        self._host._runtime_reservations.clear()

    def replace_runtimes(self, runtimes: list[RuntimeHandle]) -> None:
        if hasattr(self._host.runtimes, "replace_runtimes"):
            self._host.runtimes.replace_runtimes(runtimes)
            return
        self._host.runtimes = list(runtimes)

    def _restore_wallet_sequences(self, snapshot: HypervisorStateSnapshot) -> None:
        self._host._wallet_usage_events = [event.model_dump(mode="json") for event in snapshot.wallet_usage_events]
        self._host._next_wallet_usage_sequence = (
            max((event["sequence_id"] for event in self._host._wallet_usage_events), default=0) + 1
        )
        self._host._wallet_session_events = [event.model_dump(mode="json") for event in snapshot.wallet_session_events]
        self._host._next_wallet_session_sequence = (
            max(
                (event["sequence_id"] for event in self._host._wallet_session_events),
                default=0,
            )
            + 1
        )
        self._host._wallet_ledger_events = [event.model_dump(mode="json") for event in snapshot.wallet_ledger_events]
        self._host._next_wallet_ledger_sequence = (
            max(
                (event["sequence_id"] for event in self._host._wallet_ledger_events),
                default=0,
            )
            + 1
        )
        self._host._wallet_economics_events = [
            event.model_dump(mode="json") for event in snapshot.wallet_economics_events
        ]
        self._host._next_wallet_economics_sequence = (
            max(
                (event["sequence_id"] for event in self._host._wallet_economics_events),
                default=0,
            )
            + 1
        )
        self._host._recyclable_removals = [event.model_dump(mode="json") for event in snapshot.recyclable_removals]
        self._host._next_recyclable_removal_sequence = (
            max(
                (event["sequence_id"] for event in self._host._recyclable_removals),
                default=0,
            )
            + 1
        )
        self._host._faucet_claims = [event.model_dump(mode="json") for event in snapshot.faucet_claims]
        self._host._next_faucet_claim_sequence = (
            max((event["sequence_id"] for event in self._host._faucet_claims), default=0) + 1
        )
        self._host._epoch_reward_budgets = [event.model_dump(mode="json") for event in snapshot.epoch_reward_budgets]
        self._host._wallet_allocation_activation_events = [
            event.model_dump(mode="json") for event in snapshot.wallet_allocation_activation_events
        ]
        self._host._next_wallet_allocation_activation_sequence = (
            max(
                (event["sequence_id"] for event in self._host._wallet_allocation_activation_events),
                default=0,
            )
            + 1
        )
        self._host._wallet_allocation_dispute_events = [
            event.model_dump(mode="json") for event in snapshot.wallet_allocation_dispute_events
        ]
        self._host._next_wallet_allocation_dispute_sequence = (
            max(
                (event["sequence_id"] for event in self._host._wallet_allocation_dispute_events),
                default=0,
            )
            + 1
        )
        self._host._wallet_allocation_correction_events = [
            event.model_dump(mode="json") for event in snapshot.wallet_allocation_correction_events
        ]
        self._host._next_wallet_allocation_correction_sequence = (
            max(
                (event["sequence_id"] for event in self._host._wallet_allocation_correction_events),
                default=0,
            )
            + 1
        )
        self._host._wallet_allocation_events = [
            event.model_dump(mode="json") for event in snapshot.wallet_allocation_events
        ]
        self._host._next_wallet_allocation_sequence = (
            max(
                (event["sequence_id"] for event in self._host._wallet_allocation_events),
                default=0,
            )
            + 1
        )
