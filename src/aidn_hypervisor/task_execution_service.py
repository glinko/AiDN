from __future__ import annotations

from aidn_hypervisor.domain.models import BundleConfig, TaskRequest
from aidn_hypervisor.process_manager import RuntimeHandle


class TaskExecutionService:
    """Local bundle/runtime execution orchestration for HypervisorService."""

    def __init__(self, host) -> None:
        self._host = host

    def attempt_task(self, task_id: str) -> bool:
        task = self._host.queue.get(task_id)
        bundle_id = self._host.selected_bundle_id(task_id)
        if bundle_id is None:
            return False

        bundle = self._host._get_bundle(bundle_id)
        if not bundle.enabled:
            return False
        endpoint_manifest = self._host._endpoint_manifest_for_request(task.request)
        if (
            endpoint_manifest is not None
            and endpoint_manifest.execution_strategy == "proxy"
            and endpoint_manifest.proxy_target is not None
        ):
            return self._host._attempt_proxy_task(
                task_id,
                task,
                bundle,
                endpoint_manifest,
            )
        if self._host._runtime_boundary._uses_approved_runtime(endpoint_manifest):
            return self._host._runtime_boundary._attempt_approved_runtime_task(
                task_id,
                task,
                bundle,
                endpoint_manifest,
            )
        plugin = self._host._get_plugin(bundle.plugin_id)
        runtime = self._host._runtime_for_bundle(bundle.bundle_id)

        if self._host._current_bundle_state(bundle.bundle_id)["drain_mode"]:
            return False
        if self._host._bundle_in_cooldown(bundle.bundle_id):
            if runtime is not None:
                runtime.health_status = "cooldown"
                runtime.last_error = self._host._current_bundle_state(bundle.bundle_id)[
                    "cooldown_reason"
                ]
            return False

        if runtime is not None and not self.health_check_with_retry(
            plugin,
            runtime,
            bundle.bundle_id,
        ):
            self._host._register_bundle_failure(
                bundle_id=bundle.bundle_id,
                plugin=plugin,
                runtime=runtime,
                reason=runtime.last_error
                or f"Runtime health check failed: {bundle.bundle_id}",
            )
            self._host._stop_runtime_for_bundle(bundle)
            runtime = None
        if runtime is not None:
            runtime.status = "running"
        estimate = plugin.estimate_resources(task.request, bundle, runtime)
        concurrency_limit = estimate.get("concurrency_limit")
        effective_concurrency_limit = bundle.max_parallel_requests
        if concurrency_limit is not None:
            effective_concurrency_limit = min(
                bundle.max_parallel_requests,
                concurrency_limit,
            )
        active_tasks = self._host._active_bundle_task_count(
            bundle.bundle_id,
            exclude_task_id=task_id,
        )
        if active_tasks >= effective_concurrency_limit:
            return False

        startup = estimate.get("startup_transient", {})
        resident = estimate.get("runtime_resident", {})
        request = estimate.get("request_active", {})

        startup_cpu = startup.get("cpu", 0.0)
        startup_ram = startup.get("ram_mb", 0)
        startup_vram = startup.get("vram_mb", 0)
        resident_cpu = resident.get("cpu", 0.0)
        resident_ram = resident.get("ram_mb", 0)
        resident_vram = resident.get("vram_mb", 0)
        request_cpu = request.get("cpu", 0.0)
        request_ram = request.get("ram_mb", 0)
        request_vram = request.get("vram_mb", 0)

        needed_cpu = request_cpu + (0.0 if runtime else startup_cpu + resident_cpu)
        needed_ram = request_ram + (0 if runtime else startup_ram + resident_ram)
        needed_vram = request_vram + (0 if runtime else startup_vram + resident_vram)
        if not self._host.resources.can_fit(needed_cpu, needed_ram, needed_vram):
            self._host._runtime_boundary._evict_idle_runtimes_for_task(
                task=task,
                requested_bundle=bundle,
                cpu=needed_cpu,
                ram_mb=needed_ram,
                vram_mb=needed_vram,
            )
        if not self._host.resources.can_fit(needed_cpu, needed_ram, needed_vram):
            return False

        startup_reservation_id = f"startup:{task_id}"
        request_reservation_id = f"request:{task_id}"
        started_runtime = False
        entered_running = False
        self._host.queue.transition_status(task_id, "admitted")

        try:
            if runtime is None:
                if startup_cpu or startup_ram or startup_vram:
                    self._host.resources.reserve(
                        startup_reservation_id,
                        cpu=startup_cpu,
                        ram_mb=startup_ram,
                        vram_mb=startup_vram,
                    )

                self._host.queue.transition_status(task_id, "starting")
                runtime = self._host.start_bundle(bundle.bundle_id)
                started_runtime = True
                if startup_cpu or startup_ram or startup_vram:
                    self._host.resources.release(startup_reservation_id)

                self._host._reserve_runtime_residency(
                    bundle.bundle_id,
                    cpu=resident_cpu,
                    ram_mb=resident_ram,
                    vram_mb=resident_vram,
                )
                runtime.status = "running"
                runtime.health_status = "healthy"
                runtime.last_error = None
                if not self.health_check_with_retry(
                    plugin,
                    runtime,
                    bundle.bundle_id,
                ):
                    self._host._register_bundle_failure(
                        bundle_id=bundle.bundle_id,
                        plugin=plugin,
                        runtime=runtime,
                        reason=runtime.last_error
                        or f"Runtime health check failed: {bundle.bundle_id}",
                    )
                    raise RuntimeError(runtime.last_error or bundle.bundle_id)

            if request_cpu or request_ram or request_vram:
                self._host.resources.reserve(
                    request_reservation_id,
                    cpu=request_cpu,
                    ram_mb=request_ram,
                    vram_mb=request_vram,
                )

            self._host.queue.transition_status(task_id, "running")
            entered_running = True
            self._host._touch_task_session(task.request)
            self._host._task_results[task_id] = self.invoke_with_retry(
                plugin,
                bundle,
                task.request,
                runtime,
            )
            self._host._register_bundle_success(bundle.bundle_id, runtime)
            runtime.health_status = "healthy"
            runtime.last_error = None
            self._host.queue.transition_status(task_id, "completed")
            self._host.record_event(
                event_type="task.completed",
                message="task completed successfully",
                task_id=task_id,
                bundle_id=bundle.bundle_id,
                runtime_id=runtime.runtime_id if runtime is not None else None,
            )
            self._host._record_mvp_runtime_evidence_for_completed_task(
                task_id=task_id,
                bundle=bundle,
                task=task.request,
                runtime=runtime,
            )
            self._host._auto_record_wallet_usage_for_task(
                task_id=task_id,
                bundle=bundle,
                task=task.request,
            )
            return True
        except Exception as error:
            self._host.queue.transition_status(task_id, "failed")
            if runtime is not None:
                runtime.last_error = str(error)
            self._host.record_event(
                event_type="task.failed",
                message=str(error),
                task_id=task_id,
                bundle_id=bundle.bundle_id,
                runtime_id=runtime.runtime_id if runtime is not None else None,
            )
            if started_runtime and not entered_running and runtime is not None:
                self._host._stop_runtime_for_bundle(bundle)
            raise
        finally:
            self._host.resources.release(startup_reservation_id)
            self._host.resources.release(request_reservation_id)
            if runtime is not None and bundle.warm_policy == "never":
                self._host._stop_runtime_for_bundle(bundle)

    def health_check_with_retry(
        self,
        plugin,
        runtime: RuntimeHandle,
        bundle_id: str,
    ) -> bool:
        policy = self.retry_policy_for(plugin, "health_check")
        for attempt in range(1, policy["max_attempts"] + 1):
            if plugin.health_check(runtime):
                runtime.health_status = "healthy"
                runtime.last_error = None
                return True
            if attempt < policy["max_attempts"]:
                self._host._retry_sleep(policy["backoff_seconds"])

        runtime.health_status = "unhealthy"
        runtime.last_error = (
            f"Runtime health check failed after {policy['max_attempts']} attempts: "
            f"{bundle_id}"
        )
        return False

    def invoke_with_retry(
        self,
        plugin,
        bundle: BundleConfig,
        task: TaskRequest,
        runtime: RuntimeHandle,
    ) -> dict:
        policy = self.retry_policy_for(plugin, "invoke")
        retry_exceptions = policy["retry_exceptions"]
        last_error: Exception | None = None

        for attempt in range(1, policy["max_attempts"] + 1):
            try:
                return plugin.invoke(task, runtime)
            except Exception as error:
                last_error = error
                retryable = isinstance(error, retry_exceptions)
                if not retryable or attempt >= policy["max_attempts"]:
                    if retryable:
                        runtime.health_status = "unhealthy"
                        runtime.last_error = str(error)
                        self._host._register_bundle_failure(
                            bundle_id=bundle.bundle_id,
                            plugin=plugin,
                            runtime=runtime,
                            reason=str(error),
                        )
                    raise
                self._host._retry_sleep(policy["backoff_seconds"])

        if last_error is None:
            raise RuntimeError("invoke failed without an error")
        raise last_error

    def retry_policy_for(self, plugin, operation: str) -> dict:
        policy = plugin.retry_policy()
        operation_policy = dict(policy.get(operation, {}))
        retry_exceptions = tuple(
            operation_policy.get("retry_exceptions", (RuntimeError,))
        )
        return {
            "max_attempts": max(1, int(operation_policy.get("max_attempts", 1))),
            "backoff_seconds": max(
                0.0,
                float(operation_policy.get("backoff_seconds", 0.0)),
            ),
            "retry_exceptions": retry_exceptions,
        }
