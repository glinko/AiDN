"""Durable, bounded escalation tasks for the resident Node Steward.

RFC-0075 deliberately separates higher-order reasoning from Hypervisor
execution.  This module is the durable hand-off boundary: it stores a small
sanitized context, a routing decision, and (optionally) a typed plan.  It does
not invoke a model, execute a tool, reserve resources, or grant approval.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any
from uuid import uuid4

MAX_TASKS = 256
MAX_GOAL_LENGTH = 512
MAX_IDEMPOTENCY_LENGTH = 256
MAX_CONTEXT_KEYS = 48
MAX_CONTEXT_DEPTH = 3
MAX_CONTEXT_ITEMS = 24
MAX_CONTEXT_STRING = 512
MAX_PLAN_ACTIONS = 32
MAX_PLAN_ARGUMENT_KEYS = 24
MAX_POSTCONDITIONS = 32
MAX_OPAQUE_ID_LENGTH = 256

TERMINAL_STATES = {"COMPLETED", "FAILED", "EXPIRED", "CANCELLED"}
ACTIVE_STATES = {
    "CREATED",
    "CONTEXT_PREPARED",
    "WAITING_PROVIDER",
    "PLAN_READY",
    "WAITING_APPROVAL",
    "APPROVED",
    "EXECUTING",
    "VERIFYING",
}

_SECRET_TERMS = {
    "access_token",
    "api_key",
    "authorization",
    "credential",
    "credentials",
    "mnemonic",
    "password",
    "private_key",
    "secret",
    "seed",
    "signing_key",
    "token",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _hash_payload(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()}"


def _secret_key(key: object) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized in _SECRET_TERMS or any(term in normalized for term in ("token", "secret", "password", "private_key", "credential"))


def _bounded(value: Any, *, depth: int = 0) -> Any:
    """Return a JSON-safe bounded projection without prompt/transcript growth."""

    if depth > MAX_CONTEXT_DEPTH:
        return "[TRUNCATED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_CONTEXT_STRING]
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:MAX_CONTEXT_KEYS]:
            key = str(raw_key)[:128]
            if _secret_key(key):
                result[key] = "[REDACTED]"
            else:
                result[key] = _bounded(item, depth=depth + 1)
        if len(value) > MAX_CONTEXT_KEYS:
            result["_truncated_keys"] = len(value) - MAX_CONTEXT_KEYS
        return result
    if isinstance(value, (list, tuple)):
        items = [_bounded(item, depth=depth + 1) for item in list(value)[:MAX_CONTEXT_ITEMS]]
        if len(value) > MAX_CONTEXT_ITEMS:
            items.append(f"[TRUNCATED {len(value) - MAX_CONTEXT_ITEMS} ITEMS]")
        return items
    return str(value)[:MAX_CONTEXT_STRING]


class EscalationTaskError(ValueError):
    """Stable domain error for the API/MCP escalation boundary."""

    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = str(code)
        self.details = dict(details or {})


class EscalationTaskService:
    """Thread-safe bounded store for RFC-0075 Escalation Tasks."""

    def __init__(
        self,
        *,
        on_change: Callable[[], None] | None = None,
        on_event: Callable[[str, dict[str, Any], dict[str, Any]], None] | None = None,
        max_tasks: int = MAX_TASKS,
    ) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._lock = RLock()
        self._on_change = on_change
        self._on_event = on_event
        self._max_tasks = max(1, min(int(max_tasks), MAX_TASKS))

    @staticmethod
    def _require_text(value: Any, field: str, *, maximum: int = MAX_OPAQUE_ID_LENGTH) -> str:
        if not isinstance(value, str) or not value.strip():
            raise EscalationTaskError("ESCALATION_INVALID_ARGUMENT", f"{field} is required")
        value = value.strip()
        if len(value) > maximum:
            raise EscalationTaskError("ESCALATION_INVALID_ARGUMENT", f"{field} exceeds {maximum} characters")
        return value

    @staticmethod
    def _normalize_postconditions(value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > MAX_POSTCONDITIONS:
            raise EscalationTaskError("ESCALATION_POSTCONDITIONS_INVALID", "postconditions must be a bounded list")
        result: list[dict[str, Any]] = []
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                raise EscalationTaskError("ESCALATION_POSTCONDITIONS_INVALID", f"postcondition {index} must be an object")
            path = item.get("path") or item.get("key")
            if not isinstance(path, str) or not path.strip() or len(path.strip()) > 128:
                raise EscalationTaskError("ESCALATION_POSTCONDITIONS_INVALID", f"postcondition {index} requires a path")
            if "expected" in item:
                expected = item["expected"]
            elif "equals" in item:
                expected = item["equals"]
            else:
                raise EscalationTaskError("ESCALATION_POSTCONDITIONS_INVALID", f"postcondition {index} requires expected")
            result.append({
                "path": path.strip(),
                "expected": _bounded(expected),
                **({"description": str(item["description"])[:256]} if item.get("description") is not None else {}),
            })
        return result

    @staticmethod
    def _normalize_plan(value: Any, *, requires_operator_approval: bool | None = None) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise EscalationTaskError("ESCALATION_PLAN_INVALID", "plan must be an object")
        actions = value.get("actions")
        if not isinstance(actions, list) or not actions or len(actions) > MAX_PLAN_ACTIONS:
            raise EscalationTaskError("ESCALATION_PLAN_INVALID", "plan.actions must contain 1..32 typed actions")
        normalized_actions: list[dict[str, Any]] = []
        for index, action in enumerate(actions):
            if not isinstance(action, dict):
                raise EscalationTaskError("ESCALATION_PLAN_INVALID", f"plan action {index} must be an object")
            tool = action.get("tool")
            if not isinstance(tool, str) or not tool.strip() or len(tool.strip()) > 128:
                raise EscalationTaskError("ESCALATION_PLAN_INVALID", f"plan action {index} requires a tool")
            arguments = action.get("arguments", {})
            if not isinstance(arguments, dict) or len(arguments) > MAX_PLAN_ARGUMENT_KEYS:
                raise EscalationTaskError("ESCALATION_PLAN_INVALID", f"plan action {index} arguments are too large")
            normalized_actions.append({
                "tool": tool.strip(),
                "arguments": _bounded(arguments),
                **({"target": str(action["target"])[:MAX_OPAQUE_ID_LENGTH]} if action.get("target") is not None else {}),
                **({"expected_revision": str(action["expected_revision"])[:MAX_OPAQUE_ID_LENGTH]} if action.get("expected_revision") is not None else {}),
                **({"purpose": str(action["purpose"])[:256]} if action.get("purpose") is not None else {}),
            })
        return {
            "summary": str(value.get("summary") or "")[0:512],
            "actions": normalized_actions,
            "requires_operator_approval": bool(
                value.get("requires_operator_approval", True)
                if requires_operator_approval is None
                else requires_operator_approval
            ),
        }

    @staticmethod
    def _is_expired(task: dict[str, Any], now: datetime | None = None) -> bool:
        expires_at = task.get("expires_at")
        if not expires_at:
            return False
        try:
            expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        except ValueError:
            return True
        return expiry <= (now or _now())

    def _expire_due_locked(self) -> list[dict[str, Any]]:
        changed: list[dict[str, Any]] = []
        now = _now()
        for task in self._tasks.values():
            if task["state"] not in TERMINAL_STATES and self._is_expired(task, now):
                task["state"] = "EXPIRED"
                task["updated_at"] = _iso(now)
                task["last_error"] = {"code": "ESCALATION_EXPIRED", "message": "Escalation task expired"}
                changed.append(deepcopy(task))
        return changed

    def _notify(self, *, changed: bool, events: list[tuple[str, dict[str, Any], dict[str, Any]]] | None = None) -> None:
        if changed and self._on_change is not None:
            self._on_change()
        for event_type, task, details in events or []:
            if self._on_event is not None:
                self._on_event(event_type, task, details)

    def _emit_expired(self, tasks: list[dict[str, Any]]) -> None:
        for task in tasks:
            if self._on_event is not None:
                self._on_event("aidn.escalation.expired", task, {"state": "EXPIRED"})

    def create(
        self,
        *,
        goal: str,
        task_class: str = "REASONING_ESCALATION",
        data_class: str = "OPERATOR",
        route_decision: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        postconditions: list[dict[str, Any]] | None = None,
        idempotency_key: str,
        owner_id: str | None = None,
        control_session_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        expires_in_seconds: int | None = 86_400,
    ) -> dict[str, Any]:
        goal = self._require_text(goal, "goal", maximum=MAX_GOAL_LENGTH)
        idempotency_key = self._require_text(idempotency_key, "idempotency_key", maximum=MAX_IDEMPOTENCY_LENGTH)
        task_class = self._require_text(task_class, "task_class", maximum=64)
        data_class = self._require_text(data_class, "data_class", maximum=32).upper()
        if data_class == "SECRET":
            raise EscalationTaskError("ESCALATION_SECRET_CONTEXT_DENIED", "SECRET escalation context is not supported")
        if expires_in_seconds is not None and not 60 <= int(expires_in_seconds) <= 7 * 86_400:
            raise EscalationTaskError("ESCALATION_INVALID_ARGUMENT", "expires_in_seconds must be between 60 and 604800")
        normalized_context = _bounded(context or {})
        normalized_route = _bounded(route_decision or {})
        normalized_postconditions = self._normalize_postconditions(postconditions)
        fingerprint_payload = {
            "goal": goal,
            "task_class": task_class,
            "data_class": data_class,
            "route": normalized_route,
            "context": normalized_context,
            "postconditions": normalized_postconditions,
            "owner_id": str(owner_id or ""),
            "control_session_id": str(control_session_id or ""),
        }
        fingerprint = _hash_payload(fingerprint_payload)
        events: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        expired: list[dict[str, Any]] = []
        with self._lock:
            expired = self._expire_due_locked()
            existing = self._idempotency.get(idempotency_key)
            if existing is not None:
                existing_fingerprint, task_id = existing
                if existing_fingerprint != fingerprint:
                    raise EscalationTaskError(
                        "ESCALATION_IDEMPOTENCY_CONFLICT",
                        "The idempotency key was already used with different escalation arguments",
                        details={"task_id": task_id},
                    )
                result = deepcopy(self._tasks[task_id])
                self._notify(changed=bool(expired))
                self._emit_expired(expired)
                return result
            if len(self._tasks) >= self._max_tasks:
                # Retain durable terminal history only up to the configured cap.
                removable = [task for task in self._tasks.values() if task["state"] in TERMINAL_STATES]
                if not removable:
                    raise EscalationTaskError("ESCALATION_CAPACITY_EXCEEDED", "Escalation task store is full")
                oldest = min(removable, key=lambda task: task.get("updated_at", ""))
                self._tasks.pop(oldest["task_id"], None)
                old_key = oldest.get("idempotency_key")
                if isinstance(old_key, str):
                    self._idempotency.pop(old_key, None)
            now = _now()
            decision_status = str(normalized_route.get("status") or normalized_route.get("decision") or "")
            selected_provider = normalized_route.get("selected_provider_id")
            if not selected_provider and isinstance(normalized_route.get("selected_provider"), dict):
                selected_provider = normalized_route["selected_provider"].get("provider_id")
            state = "WAITING_PROVIDER" if not selected_provider or decision_status in {"NO_ELIGIBLE_PROVIDER", "ROUTE_UNAVAILABLE"} else "CONTEXT_PREPARED"
            task_id = f"esc_{uuid4().hex}"
            task = {
                "task_id": task_id,
                "idempotency_key": idempotency_key,
                "idempotency_fingerprint": fingerprint,
                "goal": goal,
                "task_class": task_class,
                "data_class": data_class,
                "state": state,
                "created_at": _iso(now),
                "updated_at": _iso(now),
                "expires_at": _iso(now + timedelta(seconds=int(expires_in_seconds))) if expires_in_seconds is not None else None,
                "attempt_count": 0,
                "owner_id": str(owner_id)[:MAX_OPAQUE_ID_LENGTH] if owner_id else None,
                "control_session_id": str(control_session_id)[:MAX_OPAQUE_ID_LENGTH] if control_session_id else None,
                "correlation_id": str(correlation_id)[:MAX_OPAQUE_ID_LENGTH] if correlation_id else None,
                "causation_id": str(causation_id)[:MAX_OPAQUE_ID_LENGTH] if causation_id else None,
                "route_decision": normalized_route,
                "selected_provider_id": str(selected_provider)[:MAX_OPAQUE_ID_LENGTH] if selected_provider else None,
                "context": normalized_context,
                "postconditions": normalized_postconditions,
                "plan": None,
                "plan_hash": None,
                "plan_idempotency_key": None,
                "approval": {"required": False, "status": "NOT_REQUESTED", "reference": None, "approver_id": None},
                "verification": None,
                "last_error": None,
            }
            self._tasks[task_id] = task
            self._idempotency[idempotency_key] = (fingerprint, task_id)
            events.append(("aidn.escalation.created", deepcopy(task), {"state": state, "selected_provider_id": task["selected_provider_id"]}))
            if state == "WAITING_PROVIDER":
                events.append(("aidn.escalation.waiting_provider", deepcopy(task), {"route_status": decision_status or "NO_ELIGIBLE_PROVIDER"}))
            result = deepcopy(task)
        self._notify(changed=True, events=events)
        self._emit_expired(expired)
        return result

    def list(self, *, state: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        expired: list[dict[str, Any]] = []
        with self._lock:
            expired = self._expire_due_locked()
            items = [
                deepcopy(task)
                for task in self._tasks.values()
                if state is None or task["state"] == str(state).upper()
            ]
            items.sort(key=lambda task: task.get("created_at", ""), reverse=True)
            items = items[: max(1, min(int(limit), MAX_TASKS))]
        self._notify(changed=bool(expired))
        self._emit_expired(expired)
        return items

    def get(self, task_id: str) -> dict[str, Any]:
        task_id = self._require_text(task_id, "task_id")
        expired: list[dict[str, Any]] = []
        with self._lock:
            expired = self._expire_due_locked()
            task = self._tasks.get(task_id)
            if task is None:
                raise EscalationTaskError("ESCALATION_NOT_FOUND", f"Unknown escalation task: {task_id}")
            result = deepcopy(task)
        self._notify(changed=bool(expired))
        self._emit_expired(expired)
        return result

    def set_plan(
        self,
        task_id: str,
        plan: dict[str, Any],
        *,
        idempotency_key: str,
        requires_operator_approval: bool | None = None,
    ) -> dict[str, Any]:
        task_id = self._require_text(task_id, "task_id")
        idempotency_key = self._require_text(idempotency_key, "idempotency_key", maximum=MAX_IDEMPOTENCY_LENGTH)
        normalized_plan = self._normalize_plan(plan, requires_operator_approval=requires_operator_approval)
        plan_hash = _hash_payload({"task_id": task_id, "plan": normalized_plan})
        events: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise EscalationTaskError("ESCALATION_NOT_FOUND", f"Unknown escalation task: {task_id}")
            if task["state"] in TERMINAL_STATES:
                raise EscalationTaskError("ESCALATION_TERMINAL", "A terminal escalation task cannot receive a new plan")
            if task.get("plan_idempotency_key") is not None:
                if task["plan_idempotency_key"] != idempotency_key:
                    raise EscalationTaskError("ESCALATION_PLAN_CONFLICT", "A different plan idempotency key is already attached")
                if task.get("plan_hash") != plan_hash:
                    raise EscalationTaskError("ESCALATION_PLAN_CONFLICT", "The plan idempotency key was reused with different content")
                return deepcopy(task)
            now = _now()
            task["plan"] = normalized_plan
            task["plan_hash"] = plan_hash
            task["plan_id"] = "plan_" + plan_hash.removeprefix("sha256:")[:24]
            task["plan_idempotency_key"] = idempotency_key
            requires_approval = bool(normalized_plan["requires_operator_approval"])
            task["approval"] = {
                "required": requires_approval,
                "status": "PENDING" if requires_approval else "NOT_REQUIRED",
                "reference": None,
                "approver_id": None,
            }
            task["state"] = "WAITING_APPROVAL" if requires_approval else "PLAN_READY"
            task["updated_at"] = _iso(now)
            task["last_error"] = None
            snapshot = deepcopy(task)
            events.append(("aidn.escalation.plan_ready", snapshot, {"plan_hash": plan_hash, "requires_approval": requires_approval}))
            if requires_approval:
                events.append(("aidn.approval.required", snapshot, {"plan_hash": plan_hash, "approval_type": "ESCALATION_PLAN"}))
        self._notify(changed=True, events=events)
        return snapshot

    def approve(self, task_id: str, *, plan_hash: str, approval_reference: str, approver_id: str) -> dict[str, Any]:
        task_id = self._require_text(task_id, "task_id")
        plan_hash = self._require_text(plan_hash, "plan_hash")
        approval_reference = self._require_text(approval_reference, "approval_reference")
        approver_id = self._require_text(approver_id, "approver_id")
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise EscalationTaskError("ESCALATION_NOT_FOUND", f"Unknown escalation task: {task_id}")
            if task.get("plan_hash") != plan_hash:
                raise EscalationTaskError("ESCALATION_PLAN_STALE", "Approval references a stale escalation plan", details={"current_plan_hash": task.get("plan_hash")})
            if task["state"] in TERMINAL_STATES:
                raise EscalationTaskError("ESCALATION_TERMINAL", "A terminal escalation task cannot be approved")
            if not task.get("approval", {}).get("required"):
                raise EscalationTaskError("ESCALATION_APPROVAL_NOT_REQUIRED", "This escalation plan does not require approval")
            task["approval"] = {"required": True, "status": "GRANTED", "reference": approval_reference, "approver_id": approver_id}
            task["state"] = "APPROVED"
            task["updated_at"] = _iso(_now())
            snapshot = deepcopy(task)
        self._notify(changed=True, events=[("aidn.approval.granted", snapshot, {"plan_hash": plan_hash, "approver_id": approver_id})])
        return snapshot

    @staticmethod
    def _read_path(observed: Any, path: str) -> tuple[bool, Any]:
        current = observed
        for component in path.split("."):
            if isinstance(current, dict) and component in current:
                current = current[component]
            else:
                return False, None
        return True, current

    def verify(self, task_id: str, *, observed: dict[str, Any]) -> dict[str, Any]:
        task_id = self._require_text(task_id, "task_id")
        observed = _bounded(observed or {})
        if not isinstance(observed, dict):
            raise EscalationTaskError("ESCALATION_VERIFICATION_INVALID", "observed must be an object")
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise EscalationTaskError("ESCALATION_NOT_FOUND", f"Unknown escalation task: {task_id}")
            if not task.get("postconditions"):
                raise EscalationTaskError("ESCALATION_POSTCONDITIONS_REQUIRED", "No postconditions were declared")
            if task["state"] in {"CANCELLED", "EXPIRED"}:
                raise EscalationTaskError("ESCALATION_TERMINAL", "This escalation task is no longer verifiable")
            checks: list[dict[str, Any]] = []
            all_passed = True
            for condition in task["postconditions"]:
                found, actual = self._read_path(observed, str(condition["path"]))
                passed = found and actual == condition["expected"]
                all_passed = all_passed and passed
                checks.append({"path": condition["path"], "expected": condition["expected"], "actual": actual if found else None, "passed": passed})
            task["verification"] = {"observed": observed, "checks": checks, "passed": all_passed, "verified_at": _iso(_now())}
            task["state"] = "COMPLETED" if all_passed else "FAILED"
            task["updated_at"] = _iso(_now())
            if not all_passed:
                task["last_error"] = {"code": "ESCALATION_POSTCONDITION_FAILED", "message": "One or more postconditions did not match"}
            else:
                task["last_error"] = None
            snapshot = deepcopy(task)
        event = "aidn.escalation.completed" if all_passed else "aidn.escalation.failed"
        self._notify(changed=True, events=[(event, snapshot, {"postconditions_passed": all_passed})])
        return snapshot

    def cancel(self, task_id: str, *, reason: str = "cancelled") -> dict[str, Any]:
        task_id = self._require_text(task_id, "task_id")
        reason = str(reason or "cancelled")[:512]
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise EscalationTaskError("ESCALATION_NOT_FOUND", f"Unknown escalation task: {task_id}")
            if task["state"] in TERMINAL_STATES:
                return deepcopy(task)
            task["state"] = "CANCELLED"
            task["updated_at"] = _iso(_now())
            task["last_error"] = {"code": "ESCALATION_CANCELLED", "message": reason}
            snapshot = deepcopy(task)
        self._notify(changed=True, events=[("aidn.escalation.cancelled", snapshot, {"reason": reason})])
        return snapshot

    def snapshot_state(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(task) for task in self._tasks.values()]

    def restore_state(self, snapshot: Any) -> None:
        if snapshot is None:
            return
        if not isinstance(snapshot, list):
            raise EscalationTaskError("ESCALATION_STATE_INVALID", "Persisted escalation state must be a list")
        tasks: dict[str, dict[str, Any]] = {}
        idempotency: dict[str, tuple[str, str]] = {}
        for item in snapshot[-self._max_tasks :]:
            if not isinstance(item, dict) or not isinstance(item.get("task_id"), str):
                continue
            # Snapshots are written by this bounded service. Preserve the
            # already-normalized plan/actions verbatim; applying the context
            # depth budget again here would truncate a plan after restart.
            task = deepcopy(item)
            task_id = str(task["task_id"])
            task["state"] = str(task.get("state") or "FAILED").upper()
            if task["state"] not in ACTIVE_STATES | TERMINAL_STATES:
                task["state"] = "FAILED"
            task.setdefault("postconditions", [])
            task.setdefault("approval", {"required": False, "status": "NOT_REQUESTED", "reference": None, "approver_id": None})
            tasks[task_id] = task
            key = task.get("idempotency_key")
            if isinstance(key, str) and key:
                fingerprint = task.get("idempotency_fingerprint")
                if not isinstance(fingerprint, str) or not fingerprint:
                    fingerprint = _hash_payload({"task_id": task_id, "goal": task.get("goal")})
                idempotency[key] = (fingerprint, task_id)
        with self._lock:
            self._tasks = tasks
            self._idempotency = idempotency
