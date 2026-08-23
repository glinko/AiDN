"""Global, fit-aware scheduler reconciliation for local runtime admission.

The Resource Broker owns the truth about capacity; this service owns the
small orchestration loop that repeatedly re-reads every independent queue
after a material runtime/resource transition.  It deliberately delegates
actual admission and execution to the existing task execution boundary so
there is one authoritative path for leases, provider startup, and accounting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class SchedulerReconciliationService:
    """Drive the local scheduler to a stable, globally evaluated state."""

    _DEFAULT_MAX_CYCLES = 128

    def __init__(self, host) -> None:
        self._host = host

    def reconcile(
        self,
        *,
        trigger: str = "manual",
        max_cycles: int = _DEFAULT_MAX_CYCLES,
    ) -> dict[str, Any]:
        """Run one reconciliation pass, coalescing nested process callbacks."""

        if getattr(self._host, "_scheduler_reconciliation_active", False):
            return {
                "trigger": trigger,
                "status": "already_running",
                "stable": False,
                "cycles": 0,
                "attempted": 0,
                "progressed": 0,
                "evicted": 0,
                "queue": self._host.queue_summary(),
            }
        self._host._scheduler_reconciliation_active = True
        try:
            return self._reconcile(
                trigger=trigger,
                max_cycles=max_cycles,
            )
        finally:
            self._host._scheduler_reconciliation_active = False

    def _reconcile(
        self,
        *,
        trigger: str,
        max_cycles: int,
    ) -> dict[str, Any]:
        """Re-evaluate all queue heads until no useful transition remains.

        A queued candidate that cannot fit is never allowed to block another
        independent candidate that does fit.  If nothing fits, eligible warm
        idle runtimes are considered for eviction and the candidate set is
        rebuilt from scratch after every release.
        """

        if not isinstance(trigger, str) or not trigger.strip():
            raise ValueError("scheduler reconciliation trigger must be non-empty")
        if isinstance(max_cycles, bool) or not isinstance(max_cycles, int):
            raise ValueError("scheduler reconciliation max_cycles must be an integer")
        max_cycles = max(1, min(max_cycles, 1024))

        started_at = self._now()
        state: dict[str, Any] = {
            "trigger": trigger.strip(),
            "status": "running",
            "started_at": started_at,
            "completed_at": None,
            "cycles": 0,
            "attempted": 0,
            "progressed": 0,
            "evicted": 0,
            "candidate_count": 0,
            "waiting": [],
            "stable": False,
        }
        waiting_events_emitted: set[tuple[str, str]] = set()
        # Allocation expiry/release already has a durable lifecycle event and
        # can trigger reconciliation from a read path.  Avoid putting a
        # scheduler bookkeeping event after that domain event in the journal;
        # resource hooks still cover explicit/operator and queue transitions.
        suppressed_event_triggers = (
            "allocation_",
            "operator_runtime_",
            "runtime_exit",
            "lifecycle_",
        )
        emit_events = not state["trigger"].startswith(suppressed_event_triggers)
        if emit_events:
            self._emit_resource_event(
                "aidn.resource.reconciliation_started",
                "global resource reconciliation started",
                details={"trigger": state["trigger"], "max_cycles": max_cycles},
            )
        self._publish_state(state)

        if self._host.resources is None or not self._host._has_plugins():
            state.update(
                status="unavailable",
                stable=True,
                completed_at=self._now(),
                waiting=[],
            )
            self._publish_state(state)
            if emit_events:
                self._emit_resource_event(
                    "aidn.resource.reconciliation_completed",
                    "global resource reconciliation completed without an admission broker",
                    details=self._event_summary(state),
                )
            return self._result(state)

        # Keep the established admission journal contract.  This is a plan
        # snapshot only; execution below still uses the global candidate set.
        initial_plan = self._host._pending_task_plan()
        self._host._runtime_boundary._record_admission_events(initial_plan)
        reconciliation_rank = {
            str(item["task_id"]): int(item["admission_rank"])
            for item in initial_plan
            if isinstance(item.get("admission_rank"), int)
        }

        while state["cycles"] < max_cycles:
            state["cycles"] += 1
            # Pending allocation leases share the same local Resource Broker
            # as task admission.  Reconcile them before rebuilding queue
            # heads so a released lease can activate the next waiting
            # allocation without waiting for an unrelated read request.
            pending_allocations_changed = self._reconcile_pending_allocations()
            if pending_allocations_changed:
                state["progressed"] += 1
            candidates = self._host.scheduler_candidates(limit=500)
            state["candidate_count"] = len(candidates)
            state["waiting"] = [
                {
                    "task_id": item["task_id"],
                    "queue_key": item["queue_key"],
                    "bundle_id": item.get("bundle_id"),
                    "reason": item.get("reason"),
                    "shortfall": item.get("shortfall", {}),
                }
                for item in candidates
                if item.get("status") == "RESOURCE_WAIT"
            ]
            if emit_events:
                self._emit_waiting_events(
                    candidates,
                    emitted=waiting_events_emitted,
                )

            if self._run_runnable_candidates(candidates, state, reconciliation_rank):
                continue

            # No runnable head exists.  Try the oldest/highest-ranked waiting
            # candidate's eligible warm-idle runtimes, then rebuild all heads.
            if self._evict_for_waiting_candidate(candidates, state, reconciliation_rank):
                continue
            state["stable"] = True
            break

        if not state["stable"] and state["cycles"] >= max_cycles:
            state["status"] = "cycle_limit"
        else:
            state["status"] = "stable"
        state["completed_at"] = self._now()
        self._publish_state(state)
        if emit_events:
            self._emit_resource_event(
                "aidn.resource.reconciliation_completed",
                "global resource reconciliation completed",
                details=self._event_summary(state),
                severity="WARNING" if state["status"] == "cycle_limit" else "INFO",
                requires_action=bool(state["waiting"]),
            )
        return self._result(state)

    def _emit_waiting_events(
        self,
        candidates: list[dict[str, Any]],
        *,
        emitted: set[tuple[str, str]],
    ) -> None:
        """Publish one activation-waiting event per task/reason per pass."""

        for candidate in candidates:
            if candidate.get("status") != "RESOURCE_WAIT":
                continue
            task_id = str(candidate.get("task_id") or "")
            reason = str(candidate.get("reason") or "insufficient_resources")
            if not task_id or (task_id, reason) in emitted:
                continue
            emitted.add((task_id, reason))
            self._emit_resource_event(
                "aidn.resource.activation_waiting",
                "runtime activation is waiting for allocatable resources",
                task_id=task_id,
                bundle_id=(
                    str(candidate["bundle_id"])
                    if candidate.get("bundle_id")
                    else None
                ),
                resource_type="task",
                resource_id=task_id,
                details={
                    "queue_key": candidate.get("queue_key"),
                    "reason": reason,
                    "required": candidate.get("required", {}),
                    "free": candidate.get("free", {}),
                    "shortfall": candidate.get("shortfall", {}),
                    "eviction_candidates": candidate.get("eviction_candidates", []),
                },
                severity="WARNING",
                requires_action=True,
            )

    @staticmethod
    def _event_summary(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "trigger": state.get("trigger"),
            "status": state.get("status"),
            "stable": state.get("stable"),
            "cycles": state.get("cycles", 0),
            "attempted": state.get("attempted", 0),
            "progressed": state.get("progressed", 0),
            "evicted": state.get("evicted", 0),
            "candidate_count": state.get("candidate_count", 0),
            "waiting_count": len(state.get("waiting", [])),
        }

    def _emit_resource_event(
        self,
        event_type: str,
        message: str,
        *,
        task_id: str | None = None,
        bundle_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, Any] | None = None,
        severity: str | None = None,
        requires_action: bool | None = None,
    ) -> None:
        recorder = getattr(self._host, "record_event", None)
        if not callable(recorder):
            return
        try:
            recorder(
                event_type=event_type,
                message=message,
                task_id=task_id,
                bundle_id=bundle_id,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details,
                source="scheduler",
                severity=severity,
                requires_action=requires_action,
            )
        except Exception:
            # Scheduling safety must never depend on event persistence or a
            # subscriber.  The reconciliation state remains authoritative.
            return

    def _reconcile_pending_allocations(self) -> bool:
        reconcile = getattr(self._host, "_reconcile_pending_allocations", None)
        if not callable(reconcile):
            return False
        try:
            return bool(reconcile())
        except Exception:
            # A malformed or failing allocation must not prevent independent
            # Endpoint queues from being reevaluated.  The allocation read
            # model retains the retryable reason for the next pass.
            return False

    def _run_runnable_candidates(
        self,
        candidates: list[dict[str, Any]],
        state: dict[str, Any],
        reconciliation_rank: dict[str, int],
    ) -> bool:
        runnable = [item for item in candidates if item.get("status") == "RUNNABLE"]
        runnable.sort(
            key=lambda item: self._candidate_sort_key(
                item,
                reconciliation_rank=reconciliation_rank,
            )
        )
        for candidate in runnable:
            task_id = str(candidate["task_id"])
            task = self._host.queue.get(task_id)
            if task.status != "queued":
                continue
            before = self._runtime_signature()
            state["attempted"] += 1
            previous_status = task.status
            try:
                result = self._host._attempt_task(task_id)
            except Exception:
                # TaskExecutionService records the terminal failure.  A
                # scheduler pass must continue evaluating peer queues rather
                # than turning one provider error into global head-of-line
                # blocking.
                result = False
            after_task = self._host.queue.get(task_id)
            changed = (
                bool(result)
                or after_task.status != previous_status
                or before != self._runtime_signature()
            )
            if changed:
                state["progressed"] += 1
                return True
        return False

    def _evict_for_waiting_candidate(
        self,
        candidates: list[dict[str, Any]],
        state: dict[str, Any],
        reconciliation_rank: dict[str, int],
    ) -> bool:
        waiting = [
            item
            for item in candidates
            if item.get("status") == "RESOURCE_WAIT"
            and item.get("eviction_candidates")
            and isinstance(item.get("required"), dict)
        ]
        waiting.sort(
            key=lambda item: self._candidate_sort_key(
                item,
                reconciliation_rank=reconciliation_rank,
            )
        )
        for candidate in waiting:
            task_id = str(candidate["task_id"])
            task = self._host.queue.get(task_id)
            if task.status != "queued":
                continue
            bundle_id = self._host.selected_bundle_id(task_id)
            if not bundle_id:
                continue
            try:
                bundle = self._host._get_bundle(bundle_id)
                required = candidate["required"]
                before = self._runtime_signature()
                self._host._runtime_boundary._evict_idle_runtimes_for_task(
                    task=task,
                    requested_bundle=bundle,
                    cpu=float(required.get("cpu", 0.0)),
                    ram_mb=int(required.get("ram_mb", 0)),
                    vram_mb=int(required.get("vram_mb", 0)),
                )
            except Exception:
                continue
            if before != self._runtime_signature():
                state["evicted"] += 1
                state["progressed"] += 1
                return True
        return False

    def _runtime_signature(self) -> tuple:
        runtimes = []
        for runtime in self._host.list_runtimes():
            runtimes.append(
                (
                    runtime.runtime_id,
                    runtime.bundle_id,
                    runtime.status,
                    runtime.health_status,
                )
            )
        runtimes.sort()
        resources = self._host.resources
        leases = tuple()
        if resources is not None:
            leases = tuple(
                (
                    item.get("reservation_id"),
                    item.get("cpu"),
                    item.get("ram_mb"),
                    item.get("vram_mb"),
                )
                for item in resources.lease_snapshot()
            )
        return tuple(runtimes), leases

    @staticmethod
    def _candidate_sort_key(
        candidate: dict[str, Any],
        *,
        reconciliation_rank: dict[str, int] | None = None,
    ) -> tuple:
        admission_rank = (
            reconciliation_rank.get(str(candidate.get("task_id")))
            if reconciliation_rank is not None
            else None
        )
        if admission_rank is None:
            admission_rank = candidate.get("admission_rank")
        if not isinstance(admission_rank, int):
            admission_rank = 10**9
        effective_priority = candidate.get("effective_priority", 0)
        if not isinstance(effective_priority, (int, float)):
            effective_priority = 0
        # Admission rank preserves fair-share/aging policy.  Fit filtering
        # happens before this key, so a large RESOURCE_WAIT head cannot block a
        # smaller runnable peer queue.
        return (
            admission_rank,
            -float(effective_priority),
            candidate.get("task_id", ""),
        )

    def _publish_state(self, state: dict[str, Any]) -> None:
        self._host._scheduler_reconciliation_state = dict(state)

    def _result(self, state: dict[str, Any]) -> dict[str, Any]:
        result = dict(state)
        result["queue"] = self._host.queue_summary()
        return result

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
