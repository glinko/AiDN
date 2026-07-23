"""Runtime protocol boundary service — runtime lifecycle operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aidn_hypervisor.service import HypervisorService
    from aidn_hypervisor.domain.models import BundleConfig


class RuntimeProtocolBoundaryService:
    """Boundary service for runtime lifecycle operations (drain, force-stop, restart).

    Delegates to ``HypervisorService._bundle_runtime_policy_facade()`` for the
    actual work, keeping the hypervisor top-level class lean.
    """

    def __init__(self, hypervisor: "HypervisorService") -> None:
        self._hv = hypervisor

    # ------------------------------------------------------------------
    # Public lifecycle methods
    # ------------------------------------------------------------------

    def drain_runtime(self, runtime_id: str) -> dict[str, str | bool]:
        return self._hv._bundle_runtime_policy_facade().drain_runtime(runtime_id)

    def force_stop_runtime(self, runtime_id: str) -> dict[str, str]:
        return self._hv._bundle_runtime_policy_facade().force_stop_runtime(runtime_id)

    def restart_runtime(self, runtime_id: str) -> dict[str, str]:
        return self._hv._bundle_runtime_policy_facade().restart_runtime(runtime_id)

    def list_runtimes(self) -> list:
        return self._hv._bundle_runtime_policy_facade().list_runtimes()

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
