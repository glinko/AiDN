"""Runtime protocol boundary service — runtime lifecycle operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aidn_hypervisor.service import HypervisorService


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
