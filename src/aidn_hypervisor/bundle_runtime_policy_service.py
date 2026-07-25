from __future__ import annotations

import time

from aidn_hypervisor.domain.models import BundleConfig, TaskRequest
from aidn_hypervisor.process_manager import RuntimeHandle

_ACTIVE_EXECUTION_STATUSES = {"admitted", "starting", "running"}


class BundleRuntimePolicyService:
    """Bundle configuration, runtime lifecycle, and cooldown policy facade."""

    def __init__(self, host) -> None:
        self._host = host

    def get_runtime(self, runtime_id: str) -> RuntimeHandle:
        for runtime in self.list_runtimes():
            if runtime.runtime_id == runtime_id:
                return runtime
        raise KeyError(runtime_id)

    def runtime_history(self, runtime_id: str):
        return [event for event in self._host._events if event.runtime_id == runtime_id]

    def bundle_state(self, bundle_id: str) -> dict:
        return dict(self.current_bundle_state(bundle_id))

    def bundle_config(self) -> list[BundleConfig]:
        return [bundle.model_copy(deep=True) for bundle in self._host.bundles]

    def replace_bundle_config(self, bundles: list[BundleConfig]) -> int:
        registry = self.require_bundle_registry()
        self.validate_bundles(bundles)
        registry.save(bundles)
        self._host.bundles = [bundle.model_copy(deep=True) for bundle in bundles]
        self._host.record_event(
            event_type="bundles.replaced",
            message="bundle configuration replaced by operator",
            details={"bundle_count": len(self._host.bundles)},
        )
        self._host._persist_state()
        return len(self._host.bundles)

    def reload_bundle_config(self) -> int:
        registry = self.require_bundle_registry()
        self._host.bundles = registry.load(self._host.plugins)
        self._host.record_event(
            event_type="bundles.reloaded",
            message="bundle configuration reloaded from registry",
            details={"bundle_count": len(self._host.bundles)},
        )
        self._host._persist_state()
        return len(self._host.bundles)

    def reset_bundle_cooldown(self, bundle_id: str) -> dict:
        bundle = self.get_bundle(bundle_id)
        runtime = self.runtime_for_bundle(bundle.bundle_id)
        self.set_bundle_state(
            bundle.bundle_id,
            failure_streak=0,
            cooldown_until=None,
            cooldown_reason=None,
            drain_mode=self.current_bundle_state(bundle.bundle_id)["drain_mode"],
            drain_reason=self.current_bundle_state(bundle.bundle_id)["drain_reason"],
        )
        if runtime is not None and runtime.health_status == "cooldown":
            runtime.health_status = "healthy"
            runtime.last_error = None
        self._host.record_event(
            event_type="bundle.cooldown_reset",
            message="bundle cooldown reset by operator",
            bundle_id=bundle.bundle_id,
            runtime_id=runtime.runtime_id if runtime is not None else None,
        )
        self._host._persist_state()
        return {
            "bundle_id": bundle.bundle_id,
            "status": "ready",
            "cooldown_until": None,
            "cooldown_reason": None,
            "failure_streak": 0,
        }

    def retry_bundle(self, bundle_id: str) -> dict[str, int]:
        self.reset_bundle_cooldown(bundle_id)
        self._host.record_event(
            event_type="bundle.retry_requested",
            message="bundle retry requested by operator",
            bundle_id=bundle_id,
        )
        return self._host.process_pending()

    def set_bundle_enabled(self, bundle_id: str, enabled: bool) -> dict[str, str | bool]:
        bundle = self.get_bundle(bundle_id)
        self.replace_bundle(bundle.model_copy(update={"enabled": enabled}))
        self.persist_bundle_config_if_available()
        self._host.record_event(
            event_type="bundle.enabled" if enabled else "bundle.disabled",
            message=("bundle enabled by operator" if enabled else "bundle disabled by operator"),
            bundle_id=bundle_id,
        )
        self._host._persist_state()
        return {
            "bundle_id": bundle_id,
            "enabled": enabled,
            "status": "enabled" if enabled else "disabled",
        }

    def drain_runtime(self, runtime_id: str) -> dict[str, str | bool]:
        runtime = self.get_runtime(runtime_id)
        bundle_id = runtime.bundle_id
        if bundle_id is None:
            raise KeyError(runtime_id)
        state = self.current_bundle_state(bundle_id)
        self.set_bundle_state(
            bundle_id,
            failure_streak=state["failure_streak"],
            cooldown_until=state["cooldown_until"],
            cooldown_reason=state["cooldown_reason"],
            drain_mode=True,
            drain_reason="operator_requested",
        )
        self._host.record_event(
            event_type="runtime.draining",
            message="runtime drain requested by operator",
            bundle_id=bundle_id,
            runtime_id=runtime_id,
        )
        self._host._persist_state()
        return {
            "runtime_id": runtime_id,
            "bundle_id": bundle_id,
            "drain_mode": True,
            "status": "draining",
        }

    def force_stop_runtime(self, runtime_id: str) -> dict[str, str]:
        runtime = self.get_runtime(runtime_id)
        bundle_id = runtime.bundle_id
        if bundle_id is None:
            raise KeyError(runtime_id)
        bundle = self.get_bundle(bundle_id)
        self.stop_runtime_for_bundle(bundle)
        self._host.record_event(
            event_type="runtime.force_stopped",
            message="runtime force-stopped by operator",
            bundle_id=bundle_id,
            runtime_id=runtime_id,
        )
        self._host._persist_state()
        return {
            "runtime_id": runtime_id,
            "bundle_id": bundle_id,
            "status": "force_stopped",
        }

    def restart_runtime(self, runtime_id: str) -> dict[str, str]:
        runtime = self.get_runtime(runtime_id)
        bundle_id = runtime.bundle_id
        if bundle_id is None:
            raise KeyError(runtime_id)
        bundle = self.get_bundle(bundle_id)
        if not bundle.enabled:
            raise ValueError(f"Bundle is disabled: {bundle_id}")
        if self.bundle_in_cooldown(bundle_id):
            raise ValueError(f"Bundle is in cooldown: {bundle_id}")

        state = self.current_bundle_state(bundle_id)
        self.set_bundle_state(
            bundle_id,
            failure_streak=state["failure_streak"],
            cooldown_until=state["cooldown_until"],
            cooldown_reason=state["cooldown_reason"],
            drain_mode=False,
            drain_reason=None,
        )
        self.stop_runtime_for_bundle(bundle)
        restarted = self.start_bundle(bundle_id)
        self._host.record_event(
            event_type="runtime.restarted",
            message="runtime restarted by operator",
            bundle_id=bundle_id,
            runtime_id=restarted.runtime_id,
        )
        self._host.process_pending()
        return {
            "runtime_id": restarted.runtime_id,
            "bundle_id": bundle_id,
            "status": "restarted",
        }

    def start_bundle(self, bundle_id: str) -> RuntimeHandle:
        bundle = self.get_bundle(bundle_id)
        if not bundle.enabled:
            raise ValueError(f"Bundle is disabled: {bundle_id}")
        if self.runtime_for_bundle(bundle_id) is not None:
            raise ValueError(f"Bundle already has an active runtime: {bundle_id}")

        plugin = self._host._get_plugin(bundle.plugin_id)
        launch_spec = dict(plugin.build_launch_spec(bundle))
        launch_spec["bundle_id"] = bundle.bundle_id
        launch_spec["launch_mode"] = bundle.launch_mode

        if hasattr(self._host.runtimes, "start_runtime"):
            runtime = self._host.runtimes.start_runtime(launch_spec)
            self._host.record_event(
                event_type="runtime.started",
                message="runtime started",
                bundle_id=bundle.bundle_id,
                runtime_id=runtime.runtime_id,
            )
            self._host._persist_state()
            return runtime

        handle = RuntimeHandle(
            runtime_id=f"rt-{len(self._host.runtimes) + 1}",
            command=launch_spec["command"],
            status="starting",
            bundle_id=bundle.bundle_id,
            metadata=dict(launch_spec.get("metadata", {})),
        )
        self._host.runtimes.append(handle)
        self._host.record_event(
            event_type="runtime.started",
            message="runtime started",
            bundle_id=bundle.bundle_id,
            runtime_id=handle.runtime_id,
        )
        self._host._persist_state()
        return handle

    def stop_bundle(self, bundle_id: str) -> dict[str, str]:
        bundle = self.get_bundle(bundle_id)
        runtime = self.runtime_for_bundle(bundle_id)
        if runtime is None:
            raise KeyError(bundle_id)

        plugin = self._host._get_plugin(bundle.plugin_id)
        plugin.stop(runtime)

        if hasattr(self._host.runtimes, "stop_runtime"):
            self._host.runtimes.stop_runtime(runtime.runtime_id)
        else:
            self._host.runtimes = [
                item for item in self._host.runtimes if item.runtime_id != runtime.runtime_id
            ]

        self.release_runtime_reservation(bundle.bundle_id)
        self._host.record_event(
            event_type="runtime.stopped",
            message="runtime stopped by operator",
            bundle_id=bundle.bundle_id,
            runtime_id=runtime.runtime_id,
        )
        self._host.process_pending()
        return {"bundle_id": bundle.bundle_id, "status": "stopped"}

    def list_runtimes(self) -> list[RuntimeHandle]:
        if hasattr(self._host.runtimes, "list_runtimes"):
            return list(self._host.runtimes.list_runtimes())
        return list(self._host.runtimes or [])

    def get_bundle(self, bundle_id: str) -> BundleConfig:
        for bundle in self._host.bundles:
            if bundle.bundle_id == bundle_id:
                return bundle
        raise KeyError(bundle_id)

    def runtime_for_bundle(self, bundle_id: str) -> RuntimeHandle | None:
        for runtime in self.list_runtimes():
            if runtime.bundle_id == bundle_id:
                return runtime
        return None

    def bundle_inventory_status(self, bundle: BundleConfig) -> str:
        if not bundle.enabled:
            return "disabled"
        if self.current_bundle_state(bundle.bundle_id)["cooldown_until"] is not None:
            return "cooldown"
        if self.current_bundle_state(bundle.bundle_id)["drain_mode"]:
            return "draining"
        runtime = self.runtime_for_bundle(bundle.bundle_id)
        if runtime is None:
            return "stopped"
        return runtime.status

    def bundle_registry_status(self, bundle: BundleConfig) -> str:
        status = self.bundle_inventory_status(bundle)
        if status == "stopped" and bundle.enabled:
            return "ready"
        return status

    def stop_runtime_for_bundle(self, bundle: BundleConfig) -> None:
        runtime = self.runtime_for_bundle(bundle.bundle_id)
        if runtime is None:
            return

        plugin = self._host._get_plugin(bundle.plugin_id)
        plugin.stop(runtime)
        if hasattr(self._host.runtimes, "stop_runtime"):
            self._host.runtimes.stop_runtime(runtime.runtime_id)
        else:
            self._host.runtimes = [
                item for item in self._host.runtimes if item.runtime_id != runtime.runtime_id
            ]
        self.release_runtime_reservation(bundle.bundle_id)

    def current_bundle_state(self, bundle_id: str) -> dict:
        state = self._host._bundle_states.get(bundle_id)
        if state is None:
            return {
                "bundle_id": bundle_id,
                "failure_streak": 0,
                "cooldown_until": None,
                "cooldown_reason": None,
                "drain_mode": False,
                "drain_reason": None,
            }
        return {
            "bundle_id": bundle_id,
            "failure_streak": int(state.get("failure_streak", 0)),
            "cooldown_until": state.get("cooldown_until"),
            "cooldown_reason": state.get("cooldown_reason"),
            "drain_mode": bool(state.get("drain_mode", False)),
            "drain_reason": state.get("drain_reason"),
        }

    def bundle_state_is_non_default(self, bundle_id: str) -> bool:
        state = self.current_bundle_state(bundle_id)
        return bool(
            state["failure_streak"]
            or state["cooldown_until"] is not None
            or state["cooldown_reason"] is not None
            or state["drain_mode"]
            or state["drain_reason"] is not None
        )

    def set_bundle_state(
        self,
        bundle_id: str,
        *,
        failure_streak: int,
        cooldown_until: float | None,
        cooldown_reason: str | None,
        drain_mode: bool,
        drain_reason: str | None,
    ) -> dict:
        state = {
            "bundle_id": bundle_id,
            "failure_streak": failure_streak,
            "cooldown_until": cooldown_until,
            "cooldown_reason": cooldown_reason,
            "drain_mode": drain_mode,
            "drain_reason": drain_reason,
        }
        if self._bundle_state_is_empty(state):
            self._host._bundle_states.pop(bundle_id, None)
            return self.current_bundle_state(bundle_id)
        self._host._bundle_states[bundle_id] = state
        return dict(state)

    def register_bundle_failure(
        self,
        *,
        bundle_id: str,
        plugin,
        runtime: RuntimeHandle | None,
        reason: str,
    ) -> None:
        policy = self._host._circuit_breaker_policy_for(plugin)
        if policy["failure_threshold"] <= 0:
            return

        state = self.current_bundle_state(bundle_id)
        failure_streak = state["failure_streak"] + 1
        cooldown_until = state["cooldown_until"]
        cooldown_reason = reason
        if (
            failure_streak >= policy["failure_threshold"]
            and policy["cooldown_seconds"] > 0.0
        ):
            cooldown_until = time.time() + policy["cooldown_seconds"]
            if runtime is not None:
                runtime.health_status = "cooldown"
                runtime.last_error = reason
            self._host.record_event(
                event_type="bundle.cooldown_started",
                message="bundle entered provider cooldown",
                bundle_id=bundle_id,
                runtime_id=runtime.runtime_id if runtime is not None else None,
                details={
                    "failure_streak": failure_streak,
                    "cooldown_until": cooldown_until,
                    "cooldown_reason": cooldown_reason,
                },
            )
        self.set_bundle_state(
            bundle_id,
            failure_streak=failure_streak,
            cooldown_until=cooldown_until,
            cooldown_reason=cooldown_reason,
            drain_mode=state["drain_mode"],
            drain_reason=state["drain_reason"],
        )

    def register_bundle_success(
        self,
        bundle_id: str,
        runtime: RuntimeHandle | None = None,
    ) -> None:
        if not self.bundle_state_is_non_default(bundle_id):
            return
        had_cooldown = self.current_bundle_state(bundle_id)["cooldown_until"] is not None
        self.set_bundle_state(
            bundle_id,
            failure_streak=0,
            cooldown_until=None,
            cooldown_reason=None,
            drain_mode=self.current_bundle_state(bundle_id)["drain_mode"],
            drain_reason=self.current_bundle_state(bundle_id)["drain_reason"],
        )
        if had_cooldown:
            self._host.record_event(
                event_type="bundle.cooldown_cleared",
                message="bundle provider cooldown cleared",
                bundle_id=bundle_id,
                runtime_id=runtime.runtime_id if runtime is not None else None,
            )

    def bundle_in_cooldown(self, bundle_id: str) -> bool:
        state = self.current_bundle_state(bundle_id)
        cooldown_until = state["cooldown_until"]
        if cooldown_until is None:
            return False
        if cooldown_until <= time.time():
            self.set_bundle_state(
                bundle_id,
                failure_streak=0,
                cooldown_until=None,
                cooldown_reason=None,
                drain_mode=state["drain_mode"],
                drain_reason=state["drain_reason"],
            )
            self._host.record_event(
                event_type="bundle.cooldown_expired",
                message="bundle provider cooldown expired",
                bundle_id=bundle_id,
            )
            return False
        return True

    def replace_bundle(self, updated_bundle: BundleConfig) -> None:
        replaced = False
        bundles: list[BundleConfig] = []
        for bundle in self._host.bundles:
            if bundle.bundle_id == updated_bundle.bundle_id:
                bundles.append(updated_bundle)
                replaced = True
            else:
                bundles.append(bundle)
        if not replaced:
            bundles.append(updated_bundle)
        self._host.bundles = bundles

    def persist_bundle_config_if_available(self) -> None:
        if self._host.bundle_registry is None:
            return
        self._host.bundle_registry.save(self._host.bundles)

    def require_bundle_registry(self):
        if self._host.bundle_registry is None:
            raise ValueError("Bundle registry is not configured")
        return self._host.bundle_registry

    def validate_bundles(self, bundles: list[BundleConfig]) -> None:
        for bundle in bundles:
            plugin = self._host._get_plugin(bundle.plugin_id)
            plugin.validate_bundle(bundle)

    def active_bundle_task_count(
        self,
        bundle_id: str,
        *,
        exclude_task_id: str | None = None,
    ) -> int:
        count = 0
        for task in self._host.queue.snapshot():
            if exclude_task_id is not None and task.task_id == exclude_task_id:
                continue
            if task.status not in _ACTIVE_EXECUTION_STATUSES:
                continue
            if self._host.selected_bundle_id(task.task_id) == bundle_id:
                count += 1
        return count

    def runtime_active_task_count(self, bundle_id: str) -> int:
        return self.active_bundle_task_count(bundle_id)

    def runtime_reservation_id(self, bundle_id: str) -> str:
        return f"runtime:{bundle_id}"

    def reserve_runtime_residency(
        self, bundle_id: str, *, cpu: float, ram_mb: int, vram_mb: int
    ) -> None:
        reservation_id = self.runtime_reservation_id(bundle_id)
        if reservation_id in self._host._runtime_reservations:
            return
        if cpu or ram_mb or vram_mb:
            self._host.resources.reserve(
                reservation_id,
                cpu=cpu,
                ram_mb=ram_mb,
                vram_mb=vram_mb,
            )
        self._host._runtime_reservations.add(reservation_id)

    def release_runtime_reservation(self, bundle_id: str) -> None:
        reservation_id = self.runtime_reservation_id(bundle_id)
        self._host.resources.release(reservation_id)
        self._host._runtime_reservations.discard(reservation_id)

    def diagnose_queued_task(self, task_id: str) -> dict[str, str]:
        task = self._host.queue.get(task_id)
        bundle_id = self._host.selected_bundle_id(task_id)
        if bundle_id is None:
            return {"task_id": task_id, "bundle_id": "", "reason": "unrouted"}

        bundle = self.get_bundle(bundle_id)
        if not bundle.enabled:
            return {
                "task_id": task_id,
                "bundle_id": bundle.bundle_id,
                "reason": "bundle_disabled",
            }
        plugin = self._host._get_plugin(bundle.plugin_id)
        runtime = self.runtime_for_bundle(bundle.bundle_id)
        if self.current_bundle_state(bundle.bundle_id)["drain_mode"]:
            return {
                "task_id": task_id,
                "bundle_id": bundle.bundle_id,
                "reason": "runtime_draining",
            }
        if self.bundle_in_cooldown(bundle.bundle_id):
            return {
                "task_id": task_id,
                "bundle_id": bundle.bundle_id,
                "reason": "provider_cooldown",
            }
        if runtime is not None and not plugin.health_check(runtime):
            runtime = None

        estimate = plugin.estimate_resources(task.request, bundle, runtime)
        concurrency_limit = estimate.get("concurrency_limit")
        effective_concurrency_limit = bundle.max_parallel_requests
        if concurrency_limit is not None:
            effective_concurrency_limit = min(
                bundle.max_parallel_requests,
                concurrency_limit,
            )
        active_tasks = self.active_bundle_task_count(
            bundle.bundle_id,
            exclude_task_id=task_id,
        )
        if active_tasks >= effective_concurrency_limit:
            return {
                "task_id": task_id,
                "bundle_id": bundle.bundle_id,
                "reason": "concurrency_limit",
            }

        startup = estimate.get("startup_transient", {})
        resident = estimate.get("runtime_resident", {})
        request = estimate.get("request_active", {})
        needed_cpu = request.get("cpu", 0.0) + (
            0.0 if runtime else startup.get("cpu", 0.0) + resident.get("cpu", 0.0)
        )
        needed_ram = request.get("ram_mb", 0) + (
            0 if runtime else startup.get("ram_mb", 0) + resident.get("ram_mb", 0)
        )
        needed_vram = request.get("vram_mb", 0) + (
            0 if runtime else startup.get("vram_mb", 0) + resident.get("vram_mb", 0)
        )

        if self._host.resources.can_fit(needed_cpu, needed_ram, needed_vram):
            reason = "ready"
        elif self.eviction_blocked(task.request, bundle):
            reason = "eviction_policy_blocked"
        else:
            reason = "insufficient_resources"

        return {
            "task_id": task_id,
            "bundle_id": bundle.bundle_id,
            "reason": reason,
        }

    def eviction_candidates(self, *, waiting_task: TaskRequest) -> list[BundleConfig]:
        auto_bundles = [bundle for bundle in self._host.bundles if bundle.warm_policy == "auto"]
        always_bundles = [
            bundle
            for bundle in self._host.bundles
            if bundle.warm_policy == "always"
            and waiting_task.priority > bundle.priority_class
        ]
        return auto_bundles + always_bundles

    def eviction_blocked(
        self,
        waiting_task: TaskRequest,
        requested_bundle: BundleConfig,
    ) -> bool:
        if self._host.resources is None:
            return False

        has_auto_runtime = False
        has_blocking_always_runtime = False
        for bundle in self._host.bundles:
            if bundle.bundle_id == requested_bundle.bundle_id:
                continue
            if self.runtime_for_bundle(bundle.bundle_id) is None:
                continue
            if self.active_bundle_task_count(bundle.bundle_id) > 0:
                continue

            if bundle.warm_policy == "auto":
                has_auto_runtime = True
            elif (
                bundle.warm_policy == "always"
                and waiting_task.priority <= bundle.priority_class
            ):
                has_blocking_always_runtime = True

        return has_blocking_always_runtime and not has_auto_runtime

    def _bundle_state_is_empty(self, state: dict) -> bool:
        return (
            not state["failure_streak"]
            and state["cooldown_until"] is None
            and state["cooldown_reason"] is None
            and not state["drain_mode"]
            and state["drain_reason"] is None
        )
