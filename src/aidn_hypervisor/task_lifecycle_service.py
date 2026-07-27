"""Task submission, queue progression, and task-read lifecycle services."""

from __future__ import annotations

from aidn_hypervisor.domain.models import TaskRequest

_CANCELLABLE_TASK_STATUSES = {"queued", "admitted", "starting"}
_ACTIVE_EXECUTION_STATUSES = {"admitted", "starting", "running"}
_TERMINAL_FAILED_STATUSES = {"failed"}
_TERMINAL_COMPLETED_STATUSES = {"completed"}


class TaskLifecycleService:
    """Own the task lifecycle while keeping HypervisorService as its facade."""

    def __init__(self, host) -> None:
        self._host = host

    def submit(self, request: TaskRequest):
        effective_request = self._host._task_request_with_allocation_context(request)
        effective_request = self._host._task_request_with_endpoint_context(effective_request)
        bundle = self._host.scheduler.select_bundle(effective_request, self._host.bundles)
        task = self._host.queue.enqueue(effective_request)
        self._host._selected_bundles[task.task_id] = bundle.bundle_id
        self._host.record_event(
            event_type="task.submitted",
            message="task accepted into queue",
            task_id=task.task_id,
            bundle_id=bundle.bundle_id,
            details={
                "task_type": effective_request.task_type,
                "mode": effective_request.mode,
            },
        )
        self.process_pending()
        return task

    def selected_bundle_id(self, task_id: str) -> str | None:
        return self._host._selected_bundles.get(task_id)

    def task_result(self, task_id: str) -> dict | None:
        return self._host._task_results.get(task_id)

    def task_recovery_reason(self, task_id: str) -> str | None:
        return self._host._runtime_boundary.task_recovery_reason(task_id)

    def task_proxy_trace(self, task_id: str) -> dict | None:
        result = self.task_result(task_id) or {}
        proxy_result = result.get("proxy") if isinstance(result, dict) else None
        dispatch_event = next(
            (event for event in reversed(self.task_history(task_id)) if event.event_type == "task.proxy_dispatched"),
            None,
        )
        if proxy_result is None and dispatch_event is None:
            return None
        task = self._host.queue.get(task_id)
        details = dispatch_event.details if dispatch_event is not None else {}
        return {
            "strategy": "proxy",
            "status": task.status,
            "remote_task_id": self._proxy_value(proxy_result, details, "remote_task_id"),
            "remote_endpoint_id": self._proxy_value(proxy_result, details, "remote_endpoint_id"),
            "remote_node_id": self._proxy_value(proxy_result, details, "remote_node_id"),
            "source_base_url": self._proxy_value(proxy_result, details, "source_base_url"),
            "dispatched_at": dispatch_event.timestamp if dispatch_event is not None else None,
        }

    @staticmethod
    def _proxy_value(proxy_result: object, details: dict, key: str) -> str | None:
        if isinstance(proxy_result, dict) and proxy_result.get(key) is not None:
            return str(proxy_result[key])
        value = details.get(key)
        return str(value) if value is not None else None

    def task_history(self, task_id: str):
        return [event for event in self._host._events if event.task_id == task_id]

    def cancel_task(self, task_id: str):
        task = self._host.queue.get(task_id)
        if task.status not in _CANCELLABLE_TASK_STATUSES:
            raise ValueError(f"Task is not cancellable: {task_id}")
        cancelled_task = self._host.queue.transition_status(task_id, "cancelled")
        self._host.record_event(
            event_type="task.cancelled",
            message="task cancelled before execution",
            task_id=task_id,
            bundle_id=self.selected_bundle_id(task_id),
        )
        self.process_pending()
        return cancelled_task

    def process_pending(self) -> dict[str, int]:
        if self._host.resources is None or not self._host._has_plugins():
            summary = self.queue_summary()
            self._host._persist_state()
            return summary

        while True:
            progressed = False
            admission_plan = self._host._pending_task_plan()
            self._host._runtime_boundary._record_admission_events(admission_plan)
            for item in admission_plan:
                task_id = str(item["task_id"])
                task_before = self._host.queue.get(task_id)
                if task_before.status != "queued":
                    continue
                previous_status = task_before.status
                try:
                    result = self._host._attempt_task(task_id)
                    current_status = self._host.queue.get(task_id).status
                    if result or current_status != previous_status:
                        progressed = True
                except Exception:
                    if self._host.queue.get(task_id).status != previous_status:
                        progressed = True
                    continue
            if not progressed:
                break
        summary = self.queue_summary()
        self._host._persist_state()
        return summary

    def queue_summary(self) -> dict[str, int]:
        summary = {"queued": 0, "active": 0, "completed": 0, "failed": 0}
        for task in self._host.queue.snapshot():
            if task.status == "queued":
                summary["queued"] += 1
            elif task.status in _ACTIVE_EXECUTION_STATUSES:
                summary["active"] += 1
            elif task.status in _TERMINAL_COMPLETED_STATUSES:
                summary["completed"] += 1
            elif task.status in _TERMINAL_FAILED_STATUSES:
                summary["failed"] += 1
        return summary
