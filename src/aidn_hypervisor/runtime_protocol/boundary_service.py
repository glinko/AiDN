"""Runtime protocol boundary service — runtime lifecycle operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aidn_hypervisor.domain.models import BundleConfig, TaskRequest
    from aidn_hypervisor.process_manager import RuntimeHandle
    from aidn_hypervisor.queue import QueuedTask
    from aidn_hypervisor.runtime_protocol.models import RuntimeRequestRecord
    from aidn_hypervisor.service import HypervisorService
    from aidn_hypervisor.state import JournalEvent, RuntimeSnapshot, TaskSnapshot

from aidn_hypervisor.admission_planning_service import AdmissionPlanningService
from aidn_hypervisor.bundle_runtime_policy_service import BundleRuntimePolicyService
from aidn_hypervisor.runtime_execution_service import RuntimeExecutionService


class RuntimeProtocolBoundaryService:
    """Boundary service for runtime lifecycle operations (drain, force-stop, restart).

    Delegates to ``HypervisorService._bundle_runtime_policy_facade()`` for the
    actual work, keeping the hypervisor top-level class lean.
    """

    def __init__(self, hypervisor: HypervisorService) -> None:
        self._hv = hypervisor

    # ------------------------------------------------------------------
    # Public lifecycle methods
    # ------------------------------------------------------------------

    def drain_runtime(self, runtime_id: str) -> dict[str, str | bool]:
        return self._bundle_runtime_policy_facade().drain_runtime(runtime_id)

    def force_stop_runtime(self, runtime_id: str) -> dict[str, str]:
        return self._bundle_runtime_policy_facade().force_stop_runtime(runtime_id)

    def restart_runtime(self, runtime_id: str) -> dict[str, str]:
        return self._bundle_runtime_policy_facade().restart_runtime(runtime_id)

    def get_runtime(self, runtime_id: str) -> RuntimeHandle:
        return self._bundle_runtime_policy_facade().get_runtime(runtime_id)

    def runtime_history(self, runtime_id: str) -> list[JournalEvent]:
        return self._bundle_runtime_policy_facade().runtime_history(runtime_id)

    def list_runtimes(self) -> list:
        return self._bundle_runtime_policy_facade().list_runtimes()

    def list_runtime_bindings(self) -> list[dict]:
        return self._hv._provider_installation_facade().list_runtime_bindings()

    def create_runtime_binding(
        self,
        *,
        model_deployment_id: str,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> dict:
        return self._hv._provider_inventory_application_facade().create_runtime_binding(
            model_deployment_id=model_deployment_id,
            capability_id=capability_id,
            capability_version=capability_version,
            capability_definition_hash=capability_definition_hash,
        )

    def bundle_for_runtime_binding(self, runtime_binding_id: str) -> BundleConfig:
        return self._hv._provider_inventory_application_facade().bundle_for_runtime_binding(
            runtime_binding_id
        )

    def bundle_hash_for_runtime_binding(self, runtime_binding_id: str) -> str:
        return self._hv._provider_inventory_application_facade().bundle_hash_for_runtime_binding(
            runtime_binding_id
        )

    def runtime_binding_endpoint_admission(
        self,
        runtime_binding_id: str,
        endpoint_payload: dict | None = None,
    ) -> dict:
        return self._hv._provider_inventory_application_facade().runtime_binding_endpoint_admission(
            runtime_binding_id,
            endpoint_payload=endpoint_payload,
        )

    # ------------------------------------------------------------------
    # Runtime residency helpers
    # ------------------------------------------------------------------

    def _runtime_for_bundle(self, bundle_id: str) -> RuntimeHandle | None:
        return self._bundle_runtime_policy_facade().runtime_for_bundle(bundle_id)

    def _runtime_reservation_id(self, bundle_id: str) -> str:
        return self._bundle_runtime_policy_facade().runtime_reservation_id(bundle_id)

    def _reserve_runtime_residency(
        self, bundle_id: str, *, cpu: float, ram_mb: int, vram_mb: int
    ) -> None:
        self._bundle_runtime_policy_facade().reserve_runtime_residency(
            bundle_id,
            cpu=cpu,
            ram_mb=ram_mb,
            vram_mb=vram_mb,
        )

    def _release_runtime_reservation(self, bundle_id: str) -> None:
        self._bundle_runtime_policy_facade().release_runtime_reservation(bundle_id)

    # ------------------------------------------------------------------
    # Runtime lifecycle helpers
    # ------------------------------------------------------------------

    def _stop_runtime_for_bundle(self, bundle: BundleConfig) -> None:
        self._bundle_runtime_policy_facade().stop_runtime_for_bundle(bundle)

    def _clear_runtime_reservations(self) -> None:
        self._hv._snapshot_state_facade().clear_runtime_reservations()

    def _replace_runtimes(self, runtimes: list[RuntimeHandle]) -> None:
        self._hv._snapshot_state_facade().replace_runtimes(runtimes)

    def _restore_runtimes(self, runtimes: list[RuntimeSnapshot]) -> None:
        self._hv._snapshot_state_facade().restore_runtimes(runtimes)

    # ------------------------------------------------------------------
    # Runtime evidence recording
    # ------------------------------------------------------------------

    def _record_mvp_runtime_evidence_for_completed_task(
        self,
        *,
        task_id: str,
        bundle: BundleConfig,
        task: TaskRequest,
        runtime: RuntimeHandle | None,
    ) -> RuntimeRequestRecord | None:
        return self._runtime_execution_facade().record_mvp_runtime_evidence_for_completed_task(
            task_id=task_id,
            bundle=bundle,
            task=task,
            runtime=runtime,
        )

    def _record_session_runtime_terminal_evidence(
        self,
        *,
        session_service: object,
        session: object,
        endpoint_manifest: object,
        result: object,
    ) -> None:
        self._runtime_execution_facade().record_session_runtime_terminal_evidence(
            session_service=session_service,
            session=session,
            endpoint_manifest=endpoint_manifest,
            result=result,
        )

    # ------------------------------------------------------------------
    # Approved llama.cpp runtime helpers
    # ------------------------------------------------------------------

    def _uses_approved_llamacpp_runtime(self, endpoint_manifest) -> bool:
        return self._runtime_execution_facade().uses_approved_llamacpp_runtime(
            endpoint_manifest
        )

    def _attempt_approved_runtime_task(
        self,
        task_id: str,
        task: QueuedTask,
        bundle: BundleConfig,
        endpoint_manifest,
    ) -> bool:
        return self._runtime_execution_facade().attempt_approved_runtime_task(
            task_id,
            task,
            bundle,
            endpoint_manifest,
        )

    # ------------------------------------------------------------------
    # Task recovery reason helpers
    # ------------------------------------------------------------------

    def task_recovery_reason(self, task_id: str) -> str | None:
        return self._hv._task_recovery_reasons.get(task_id)

    def _recovery_reason_for_task(self, task: TaskSnapshot) -> str:
        return self._hv._snapshot_state_facade().recovery_reason_for_task(task)

    def _recovery_message(self, recovery_reason: str) -> str:
        return self._hv._snapshot_state_facade().recovery_message(recovery_reason)

    # ------------------------------------------------------------------
    # Runtime endpoint resolution
    # ------------------------------------------------------------------

    def _resolve_runtime_endpoint(
        self,
        bundle: BundleConfig,
        runtime: RuntimeHandle,
    ) -> str:
        return self._hv._allocation_catalog_facade().resolve_runtime_endpoint(
            bundle, runtime
        )

    # ------------------------------------------------------------------
    # Facade accessors (lazy-initialized service instances)
    # ------------------------------------------------------------------

    def _runtime_execution_facade(self) -> RuntimeExecutionService:
        facade = getattr(self._hv, "_runtime_execution_service", None)
        if facade is None:
            facade = RuntimeExecutionService(self._hv)
            self._hv._runtime_execution_service = facade
        return facade

    def _admission_planning_facade(self) -> AdmissionPlanningService:
        facade = getattr(self._hv, "_admission_planning_service", None)
        if facade is None:
            facade = AdmissionPlanningService(self._hv)
            self._hv._admission_planning_service = facade
        return facade

    def _bundle_runtime_policy_facade(self) -> BundleRuntimePolicyService:
        facade = getattr(self._hv, "_bundle_runtime_policy_service", None)
        if facade is None:
            facade = BundleRuntimePolicyService(self._hv)
            self._hv._bundle_runtime_policy_service = facade
        return facade

    # ------------------------------------------------------------------
    # Admission telemetry
    # ------------------------------------------------------------------

    def admission_telemetry(self) -> list[dict[str, int | str]]:
        return self._admission_planning_facade().admission_telemetry()

    # ------------------------------------------------------------------
    # Runtime active task count
    # ------------------------------------------------------------------

    def runtime_active_task_count(self, bundle_id: str) -> int:
        return self._bundle_runtime_policy_facade().runtime_active_task_count(bundle_id)

    # ------------------------------------------------------------------
    # Admission event recording
    # ------------------------------------------------------------------

    def _record_admission_events(self, admission_plan: list[dict[str, int | str]]) -> None:
        self._admission_planning_facade().record_admission_events(admission_plan)

    # ------------------------------------------------------------------
    # Idle runtime eviction for task admission
    # ------------------------------------------------------------------

    def _evict_idle_runtimes_for_task(
        self,
        *,
        task: TaskRequest,
        requested_bundle: BundleConfig,
        cpu: float,
        ram_mb: int,
        vram_mb: int,
    ) -> None:
        self._admission_planning_facade().evict_idle_runtimes_for_task(
            task=task,
            requested_bundle=requested_bundle,
            cpu=cpu,
            ram_mb=ram_mb,
            vram_mb=vram_mb,
        )
