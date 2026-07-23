from __future__ import annotations

import time
from datetime import datetime

from aidn_hypervisor.domain.models import BundleConfig, TaskRequest
from aidn_hypervisor.queue import QueuedTask

_AGING_PRIORITY_STEP = 10
_AGING_PRIORITY_INTERVAL_SECONDS = 60
_AGING_PRIORITY_MAX_BONUS = 100


class AdmissionPlanningService:
    """Admission planning, queue diagnostics, and fairness helpers."""

    def __init__(self, host) -> None:
        self._host = host

    def queue_diagnostics(self) -> list[dict[str, str]]:
        diagnostics: list[dict[str, str]] = []
        for task in self._host.queue.snapshot():
            if task.status != "queued":
                continue
            diagnostics.append(self._host._diagnose_queued_task(task.task_id))
        return diagnostics

    def admission_telemetry(self) -> list[dict[str, int | str]]:
        return self.pending_task_plan()

    def pending_task_order(self) -> list[str]:
        return [item["task_id"] for item in self.pending_task_plan()]

    def record_admission_events(self, admission_plan: list[dict[str, int | str]]) -> None:
        for item in admission_plan:
            self._host.record_event(
                event_type="admission.selected",
                message="task selected for admission attempt",
                task_id=str(item["task_id"]),
                bundle_id=str(item["bundle_id"]),
                details={
                    "base_priority": item["base_priority"],
                    "aging_bonus": item["aging_bonus"],
                    "effective_priority": item["effective_priority"],
                    "fair_share_round": item["fair_share_round"],
                    "admission_rank": item["admission_rank"],
                    "selection_reason": item["selection_reason"],
                },
            )

    def pending_task_plan(self) -> list[dict[str, int | str]]:
        queued_tasks = [task for task in self._host.queue.snapshot() if task.status == "queued"]
        if not queued_tasks:
            return []

        tasks_by_bundle: dict[str, list[QueuedTask]] = {}
        for task in queued_tasks:
            bundle_id = self._host.selected_bundle_id(task.task_id) or ""
            tasks_by_bundle.setdefault(bundle_id, []).append(task)

        for bundle_id in tasks_by_bundle:
            tasks_by_bundle[bundle_id].sort(
                key=lambda task: (
                    -self.effective_task_priority(task),
                    task.enqueue_index,
                )
            )

        bundle_dispatch_counts = {bundle_id: 0 for bundle_id in tasks_by_bundle}
        admission_plan: list[dict[str, int | str]] = []
        while tasks_by_bundle:
            min_dispatch_count = min(
                bundle_dispatch_counts[bundle_id] for bundle_id in tasks_by_bundle
            )
            dispatch_candidates = [
                bundle_id
                for bundle_id in tasks_by_bundle
                if bundle_dispatch_counts[bundle_id] == min_dispatch_count
            ]
            next_bundle_id = min(
                dispatch_candidates,
                key=lambda bundle_id: (
                    -self.effective_task_priority(tasks_by_bundle[bundle_id][0]),
                    tasks_by_bundle[bundle_id][0].enqueue_index,
                ),
            )
            selection_reason = self.selection_reason(
                tasks_by_bundle=tasks_by_bundle,
                dispatch_candidates=dispatch_candidates,
                next_bundle_id=next_bundle_id,
            )
            next_task = tasks_by_bundle[next_bundle_id].pop(0)
            aging_bonus = self.aging_bonus(next_task)
            admission_plan.append(
                {
                    "task_id": next_task.task_id,
                    "bundle_id": self._host.selected_bundle_id(next_task.task_id) or "",
                    "base_priority": next_task.priority,
                    "aging_bonus": aging_bonus,
                    "effective_priority": next_task.priority + aging_bonus,
                    "fair_share_round": min_dispatch_count,
                    "admission_rank": len(admission_plan) + 1,
                    "selection_reason": selection_reason,
                }
            )
            bundle_dispatch_counts[next_bundle_id] += 1
            if not tasks_by_bundle[next_bundle_id]:
                del tasks_by_bundle[next_bundle_id]
        return admission_plan

    def effective_task_priority(self, task: QueuedTask) -> int:
        return task.priority + self.aging_bonus(task)

    def aging_bonus(self, task: QueuedTask) -> int:
        try:
            created_at = datetime.fromisoformat(task.created_at)
        except ValueError:
            return 0
        waiting_seconds = max(0.0, time.time() - created_at.timestamp())
        return min(
            _AGING_PRIORITY_MAX_BONUS,
            int(waiting_seconds // _AGING_PRIORITY_INTERVAL_SECONDS)
            * _AGING_PRIORITY_STEP,
        )

    def selection_reason(
        self,
        *,
        tasks_by_bundle: dict[str, list[QueuedTask]],
        dispatch_candidates: list[str],
        next_bundle_id: str,
    ) -> str:
        if len(tasks_by_bundle) == 1:
            return "only_remaining_bundle"
        if len(dispatch_candidates) == 1:
            return "lowest_dispatch_count"

        max_priority = max(
            self.effective_task_priority(tasks_by_bundle[bundle_id][0])
            for bundle_id in dispatch_candidates
        )
        highest_priority_candidates = [
            bundle_id
            for bundle_id in dispatch_candidates
            if self.effective_task_priority(tasks_by_bundle[bundle_id][0]) == max_priority
        ]
        if len(highest_priority_candidates) == 1:
            return "highest_effective_priority"
        if next_bundle_id in highest_priority_candidates:
            return "fifo_tiebreak"
        return "highest_effective_priority"

    def evict_idle_runtimes_for_task(
        self,
        *,
        task: TaskRequest,
        requested_bundle: BundleConfig,
        cpu: float,
        ram_mb: int,
        vram_mb: int,
    ) -> None:
        for bundle in self._host._eviction_candidates(waiting_task=task):
            if bundle.bundle_id == requested_bundle.bundle_id:
                continue
            if self._host._runtime_for_bundle(bundle.bundle_id) is None:
                continue
            if self._host._active_bundle_task_count(bundle.bundle_id) > 0:
                continue

            self._host._stop_runtime_for_bundle(bundle)
            if self._host.resources.can_fit(cpu, ram_mb, vram_mb):
                return
