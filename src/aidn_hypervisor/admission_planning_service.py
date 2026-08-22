from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from aidn_hypervisor.domain.models import BundleConfig, TaskRequest
from aidn_hypervisor.runtime_instance_manager import evaluate_runtime_eviction
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

    def scheduler_candidates(self, *, limit: int = 200) -> list[dict[str, Any]]:
        """Project the current head candidate from every independent queue.

        This is a read-only view of the admission problem.  It deliberately
        does not change task status, evict a runtime, or reserve resources.
        The execution path remains the authority that performs those actions;
        this projection gives an operator or agent the same fit/queue facts
        before asking it to act.
        """

        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("scheduler candidate limit must be an integer")
        limit = max(1, min(limit, 500))

        queued_tasks = [
            task for task in self._host.queue.snapshot() if task.status == "queued"
        ]
        if not queued_tasks:
            return []

        plan_by_task = {
            str(item["task_id"]): item for item in self.pending_task_plan()
        }
        grouped = self._group_queued_tasks(queued_tasks)

        heads: list[tuple[str, QueuedTask]] = []
        for queue_key, tasks in grouped.items():
            # _group_queued_tasks sorts each queue according to its policy,
            # so the first item is the only admissible head.  In particular,
            # a newer high-priority request must not jump an older request on
            # the same Endpoint queue.
            heads.append((queue_key, tasks[0]))

        heads.sort(
            key=lambda item: (
                int(plan_by_task.get(item[1].task_id, {}).get("admission_rank", 10**9)),
                item[1].enqueue_index,
            )
        )
        candidates: list[dict[str, Any]] = []
        for queue_key, task in heads[:limit]:
            candidates.append(
                self._candidate_for_task(
                    task,
                    queue_key=queue_key,
                    queue_depth=len(grouped[queue_key]),
                    queue_policy=self._queue_policy(queue_key),
                    plan=plan_by_task.get(task.task_id),
                )
            )
        return candidates

    def scheduler_status(self, *, candidate_limit: int = 200) -> dict[str, Any]:
        """Return a compact scheduler read model for dashboards and agents."""

        candidates = self.scheduler_candidates(limit=candidate_limit)
        counts: dict[str, int] = {}
        for candidate in candidates:
            status = str(candidate["status"])
            counts[status] = counts.get(status, 0) + 1

        queued = [
            task for task in self._host.queue.snapshot() if task.status == "queued"
        ]
        queue_keys = {self._queue_key(task) for task in queued}
        resources = self._host.resources
        return {
            "policy": self._host.operator_requests_policy(),
            "queue": {
                "summary": self._host.queue_summary(),
                "queued_tasks": len(queued),
                "independent_queues": len(queue_keys),
            },
            "candidates": {
                "total": len(candidates),
                "by_status": counts,
                "items": candidates,
                "limit": candidate_limit,
            },
            "resources": (
                {
                    "summary": resources.summary(),
                    "leases": resources.lease_snapshot(),
                }
                if resources is not None
                else {"available": False}
            ),
            "reconciliation": dict(
                getattr(self._host, "_scheduler_reconciliation_state", {})
            ),
        }

    def scheduler_explain_decision(self, task_id: str) -> dict[str, Any]:
        """Explain the current admission decision for one queued task.

        The scheduler read model intentionally exposes only queue heads.  An
        agent still needs a stable way to answer "why is *this* request not
        running?", including when it is behind another request on the same
        Endpoint queue.  This method is read-only and reuses the exact queue
        ordering and candidate projection used by reconciliation.
        """

        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("scheduler decision task_id must be a non-empty string")
        task_id = task_id.strip()
        try:
            task = self._host.queue.get(task_id)
        except KeyError as error:
            raise KeyError(task_id) from error

        queued_tasks = [
            item for item in self._host.queue.snapshot() if item.status == "queued"
        ]
        queue_key = self._queue_key(task)
        grouped = self._group_queued_tasks(queued_tasks)
        queue_items = grouped.get(queue_key, [])
        queue_position = next(
            (index + 1 for index, item in enumerate(queue_items) if item.task_id == task_id),
            None,
        )
        queue_depth = len(queue_items)
        plan_by_task = {
            str(item["task_id"]): item for item in self.pending_task_plan()
        }

        candidate = next(
            (
                item
                for item in self.scheduler_candidates(limit=500)
                if str(item.get("task_id")) == task_id
            ),
            None,
        )
        if candidate is None and task.status == "queued" and queue_items:
            head = queue_items[0]
            blocker = next(
                (
                    item
                    for item in self.scheduler_candidates(limit=500)
                    if str(item.get("task_id")) == head.task_id
                ),
                None,
            )
            queue_label = "Endpoint" if self._queue_policy(queue_key) == "fifo" else "Bundle"
            explanation = {
                "decision": "WAITING_FOR_QUEUE",
                "reason": "head_of_line",
                "summary": (
                    f"The request is queued behind the current {queue_label} queue head; "
                    "the head must complete or leave the queue before this request "
                    "can be admitted."
                ),
                "next_actions": ["inspect the queue head", "wait for the head to complete"],
                "task": {
                    "task_id": task.task_id,
                    "status": task.status,
                    "priority": task.priority,
                    "created_at": task.created_at,
                },
                "queue": {
                    "queue_key": queue_key,
                    "policy": self._queue_policy(queue_key),
                    "depth": queue_depth,
                    "position": queue_position,
                    "head_task_id": head.task_id,
                },
                "blocker": blocker
                or {
                    "task_id": head.task_id,
                    "status": "QUEUED",
                    "reason": "head_candidate_not_projectable",
                },
            }
            return explanation

        if candidate is None:
            # A terminal task is still useful to explain: it may have just
            # completed between two agent reads and should not look like a
            # missing scheduler record.
            return {
                "decision": "NOT_QUEUED",
                "reason": "task_not_queued",
                "summary": f"The task is no longer queued (status: {task.status}).",
                "next_actions": [],
                "task": {
                    "task_id": task.task_id,
                    "status": task.status,
                    "priority": task.priority,
                    "created_at": task.created_at,
                },
                "queue": {
                    "queue_key": queue_key,
                    "policy": self._queue_policy(queue_key),
                    "depth": queue_depth,
                    "position": queue_position,
                },
            }

        status = str(candidate.get("status", "UNKNOWN"))
        decision, summary, next_actions = self._decision_summary(candidate)
        factors: list[dict[str, Any]] = [
            {
                "name": "queue_order",
                "value": {
                    "policy": candidate.get("queue_policy"),
                    "depth": candidate.get("queue_depth"),
                    "position": candidate.get("queue_position"),
                    "head_of_line": candidate.get("head_of_line"),
                },
            },
            {
                "name": "priority",
                "value": {
                    "base": candidate.get("base_priority"),
                    "aging_bonus": candidate.get("aging_bonus"),
                    "effective": candidate.get("effective_priority"),
                    "admission_rank": candidate.get("admission_rank"),
                },
            },
        ]
        for name in (
            "runtime_path",
            "runtime_id",
            "runtime_status",
            "required",
            "free",
            "shortfall",
            "concurrency",
            "resource",
            "estimate_confidence",
            "estimate_breakdown",
            "estimate_assumptions",
            "eviction_candidates",
        ):
            if name in candidate and candidate[name] is not None:
                factors.append({"name": name, "value": candidate[name]})

        return {
            "decision": decision,
            "reason": candidate.get("reason"),
            "summary": summary,
            "next_actions": next_actions,
            "task": {
                "task_id": task.task_id,
                "status": task.status,
                "priority": task.priority,
                "created_at": task.created_at,
            },
            "queue": {
                "queue_key": candidate.get("queue_key"),
                "policy": candidate.get("queue_policy"),
                "depth": candidate.get("queue_depth"),
                "position": candidate.get("queue_position"),
                "head_of_line": candidate.get("head_of_line"),
            },
            "candidate": candidate,
            "factors": factors,
            "selection": {
                "selection_reason": candidate.get("selection_reason"),
                "plan": plan_by_task.get(task_id),
            },
        }

    @staticmethod
    def _decision_summary(candidate: dict[str, Any]) -> tuple[str, str, list[str]]:
        status = str(candidate.get("status", "UNKNOWN"))
        reason = str(candidate.get("reason", "unknown"))
        summaries = {
            "RUNNABLE": (
                "ADMIT",
                "The request fits the current admission constraints and is eligible to run.",
                ["admit the request through the normal scheduler"],
            ),
            "RESOURCE_WAIT": (
                "WAITING_FOR_RESOURCES",
                "The request cannot fit in current allocatable resources.",
                ["wait for capacity", "inspect eviction_candidates before changing policy"],
            ),
            "CONCURRENCY_WAIT": (
                "WAITING_FOR_CONCURRENCY",
                "The runtime has reached its configured concurrent-request limit.",
                ["wait for an active request to complete"],
            ),
            "BLOCKED": (
                "BLOCKED",
                f"The request is blocked by the bundle/runtime policy ({reason}).",
                ["inspect the bundle and runtime policy"],
            ),
            "ESTIMATE_UNAVAILABLE": (
                "WAITING_FOR_ESTIMATE",
                "The provider could not produce a safe resource estimate.",
                ["provide a ResourceProfile or inspect the provider error"],
            ),
            "UNROUTED": (
                "UNROUTED",
                "The request has no usable Bundle routing target.",
                ["select an enabled Bundle or Endpoint"],
            ),
        }
        return summaries.get(
            status,
            (
                status,
                f"The scheduler reported status {status} ({reason}).",
                ["inspect the candidate read model"],
            ),
        )

    def _queue_key(self, task: QueuedTask) -> str:
        constraints = task.request.constraints
        endpoint_id = constraints.get("endpoint_id") if isinstance(constraints, dict) else None
        if isinstance(endpoint_id, str) and endpoint_id.strip():
            return f"endpoint:{endpoint_id.strip()}"
        bundle_id = self._host.selected_bundle_id(task.task_id)
        if bundle_id:
            return f"bundle:{bundle_id}"
        return f"task:{task.task_id}"

    @staticmethod
    def _queue_policy(queue_key: str) -> str:
        """Return the scheduling policy for a canonical local queue key."""

        return "fifo" if queue_key.startswith("endpoint:") else "fair_share"

    def _group_queued_tasks(
        self,
        queued_tasks: list[QueuedTask],
    ) -> dict[str, list[QueuedTask]]:
        """Partition queued work into independent queues and order each one.

        Endpoint queues are deliberately FIFO.  Requests routed only by a
        Bundle retain the historical priority/aging ordering used by the
        fair-share planner.  Keeping this rule in one helper prevents the
        read model and the execution scheduler from selecting different
        queue heads.
        """

        grouped: dict[str, list[QueuedTask]] = {}
        for task in queued_tasks:
            grouped.setdefault(self._queue_key(task), []).append(task)
        for queue_key, tasks in grouped.items():
            if self._queue_policy(queue_key) == "fifo":
                tasks.sort(key=lambda item: item.enqueue_index)
            else:
                tasks.sort(
                    key=lambda item: (
                        -self.effective_task_priority(item),
                        item.enqueue_index,
                    )
                )
        return grouped

    def _candidate_for_task(
        self,
        task: QueuedTask,
        *,
        queue_key: str,
        queue_depth: int,
        queue_policy: str,
        plan: dict[str, Any] | None,
    ) -> dict[str, Any]:
        bundle_id = self._host.selected_bundle_id(task.task_id)
        endpoint_id = (
            task.request.constraints.get("endpoint_id")
            if isinstance(task.request.constraints, dict)
            else None
        )
        candidate: dict[str, Any] = {
            "task_id": task.task_id,
            "queue_key": queue_key,
            "queue_depth": queue_depth,
            "queue_position": 1,
            "head_of_line": True,
            "queue_policy": queue_policy,
            "endpoint_id": endpoint_id if isinstance(endpoint_id, str) else None,
            "bundle_id": bundle_id or "",
            "status": "UNROUTED" if bundle_id is None else "ESTIMATE_UNAVAILABLE",
            "reason": "unrouted" if bundle_id is None else "estimate_unavailable",
            "runtime_id": None,
            "runtime_status": None,
            "runtime_path": "cold",
            "base_priority": task.priority,
            "aging_bonus": self.aging_bonus(task),
            "effective_priority": self.effective_task_priority(task),
            "admission_rank": plan.get("admission_rank") if plan else None,
            "selection_reason": plan.get("selection_reason") if plan else None,
        }
        if bundle_id is None:
            return candidate

        try:
            bundle = self._host._get_bundle(bundle_id)
        except KeyError:
            candidate["status"] = "UNROUTED"
            candidate["reason"] = "bundle_not_found"
            return candidate

        candidate["bundle_enabled"] = bool(bundle.enabled)
        if not bundle.enabled:
            candidate["status"] = "BLOCKED"
            candidate["reason"] = "bundle_disabled"
            return candidate

        state = self._host._current_bundle_state(bundle.bundle_id)
        if state["drain_mode"]:
            candidate["status"] = "BLOCKED"
            candidate["reason"] = "runtime_draining"
            return candidate
        cooldown_until = state["cooldown_until"]
        if cooldown_until is not None and cooldown_until > time.time():
            candidate["status"] = "BLOCKED"
            candidate["reason"] = "provider_cooldown"
            return candidate

        runtime = self._host._runtime_for_bundle(bundle.bundle_id)
        candidate["runtime_id"] = runtime.runtime_id if runtime is not None else None
        candidate["runtime_status"] = runtime.status if runtime is not None else None
        candidate["runtime_path"] = "warm" if runtime is not None else "cold"
        plugin = self._host._get_plugin(bundle.plugin_id)
        try:
            estimate = plugin.estimate_resources(task.request, bundle, runtime)
            required = self._resource_requirements(estimate, runtime is not None)
        except Exception as error:
            candidate["error_type"] = type(error).__name__
            return candidate

        candidate["required"] = required
        # Provider estimators may expose conservative evidence without making
        # it part of the generic plugin contract.  Keep it in the read model
        # so an operator can tell a declared profile from a derived one before
        # approving a cold activation.
        for key in (
            "estimate_confidence",
            "estimate_breakdown",
            "estimate_assumptions",
            "context_length",
            "batch_size",
            "kv_offload",
        ):
            if key in estimate:
                candidate[key] = estimate[key]
        concurrency_limit = estimate.get("concurrency_limit")
        effective_limit = bundle.max_parallel_requests
        if concurrency_limit is not None:
            try:
                effective_limit = min(effective_limit, int(concurrency_limit))
            except (TypeError, ValueError):
                candidate["status"] = "ESTIMATE_UNAVAILABLE"
                candidate["reason"] = "invalid_concurrency_limit"
                return candidate
        active_tasks = self._host._active_bundle_task_count(
            bundle.bundle_id,
            exclude_task_id=task.task_id,
        )
        candidate["concurrency"] = {
            "active": active_tasks,
            "limit": effective_limit,
        }
        if active_tasks >= effective_limit:
            candidate["status"] = "CONCURRENCY_WAIT"
            candidate["reason"] = "concurrency_limit"
            return candidate

        resources = self._host.resources
        if resources is None:
            candidate["status"] = "ESTIMATE_UNAVAILABLE"
            candidate["reason"] = "resource_broker_unavailable"
            return candidate
        report = resources.admission_report(**required)
        candidate["resource"] = report
        candidate["free"] = report["free"]
        candidate["shortfall"] = report["shortfall"]
        if report["allowed"]:
            candidate["status"] = "RUNNABLE"
            candidate["reason"] = "warm_runtime_capacity" if runtime is not None else "resources_fit"
        else:
            candidate["status"] = "RESOURCE_WAIT"
            candidate["reason"] = "insufficient_resources"
            candidate["eviction_candidates"] = self._readable_eviction_candidates(
                requested_bundle=bundle,
                waiting_task=task.request,
            )
        return candidate

    @staticmethod
    def _resource_requirements(estimate: dict, warm: bool) -> dict[str, float | int]:
        startup = estimate.get("startup_transient", {}) or {}
        resident = estimate.get("runtime_resident", {}) or {}
        request = estimate.get("request_active", {}) or {}

        def number(mapping: dict, key: str, cast):
            value = mapping.get(key, 0)
            if isinstance(value, bool):
                raise ValueError(f"invalid resource estimate: {key}")
            try:
                result = cast(value)
            except (TypeError, ValueError):
                raise ValueError(f"invalid resource estimate: {key}") from None
            if result < 0:
                raise ValueError(f"invalid resource estimate: {key}")
            return result

        return {
            "cpu": number(request, "cpu", float)
            + (0.0 if warm else number(startup, "cpu", float) + number(resident, "cpu", float)),
            "ram_mb": number(request, "ram_mb", int)
            + (0 if warm else number(startup, "ram_mb", int) + number(resident, "ram_mb", int)),
            "vram_mb": number(request, "vram_mb", int)
            + (0 if warm else number(startup, "vram_mb", int) + number(resident, "vram_mb", int)),
        }

    def _readable_eviction_candidates(
        self,
        *,
        requested_bundle: BundleConfig,
        waiting_task: TaskRequest,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for bundle in self._host._eviction_candidates(waiting_task=waiting_task):
            if bundle.bundle_id == requested_bundle.bundle_id:
                continue
            runtime = self._host._runtime_for_bundle(bundle.bundle_id)
            if runtime is None or self._host._active_bundle_task_count(bundle.bundle_id) > 0:
                continue
            eviction_policy = evaluate_runtime_eviction(
                runtime,
                bundle,
                waiting_task,
                active_task_count=self._host._active_bundle_task_count(bundle.bundle_id),
            )
            reservation_id = self._host._runtime_reservation_id(bundle.bundle_id)
            reservation = next(
                (
                    item
                    for item in self._host.resources.lease_snapshot()
                    if item["reservation_id"] == reservation_id
                ),
                None,
            )
            items.append(
                {
                    "bundle_id": bundle.bundle_id,
                    "runtime_id": runtime.runtime_id,
                    "runtime_status": runtime.status,
                    "lifecycle_state": runtime.lifecycle_state,
                    "preemption_class": eviction_policy["preemption_class"],
                    "eviction_reason": eviction_policy["reason"],
                    "residency_age_seconds": eviction_policy["residency_age_seconds"],
                    "releases": reservation
                    or {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
                }
            )
        return items

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

        # Admission fairness is calculated over the same independent queue
        # keys that drive the executable Candidate Set.  The old name is kept
        # below for event/read-model compatibility, but Endpoint requests no
        # longer share a dispatch bucket merely because they use one Bundle.
        tasks_by_bundle = self._group_queued_tasks(queued_tasks)

        bundle_dispatch_counts = dict.fromkeys(tasks_by_bundle, 0)
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

            self._host._stop_runtime_for_bundle(bundle, reason="eviction")
            if self._host.resources.can_fit(cpu, ram_mb, vram_mb):
                return
