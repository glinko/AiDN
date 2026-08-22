"""Canonical Runtime Instance lifecycle projection.

The process manager owns the low-level ``status`` field (whether a child
process is starting, running, or stopped).  RFC-0073 needs a richer,
operator-facing state machine that also accounts for active work and warm
retention.  This module keeps that projection in one place so API, MCP, and
the scheduler do not each invent their own interpretation of a runtime.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aidn_hypervisor.process_manager import RuntimeHandle


RUNTIME_INSTANCE_STATES = (
    "COLD",
    "STARTING",
    "WARM_IDLE",
    "WARM_ACTIVE",
    "BUSY",
    "EVICTION_CANDIDATE",
    "DRAINING",
    "STOPPING",
    "STOPPED",
    "FAILED",
)

_RUNTIME_INSTANCE_STATE_SET = frozenset(RUNTIME_INSTANCE_STATES)
DEFAULT_WARM_RETENTION_SECONDS = 300
DEFAULT_MINIMUM_RESIDENCY_SECONDS = 0
PREEMPTION_CLASSES = (
    "NON_PREEMPTIBLE",
    "DRAINABLE",
    "CHECKPOINTABLE",
    "IMMEDIATELY_PREEMPTIBLE",
)
_PREEMPTION_CLASS_SET = frozenset(PREEMPTION_CLASSES)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _iso_timestamp(value: datetime | None = None) -> str:
    return (value or _now_utc()).astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def warm_retention_seconds(environ: dict[str, str] | None = None) -> int:
    """Return the configured warm-runtime retention window.

    A malformed environment value must never make runtime reads fail.  The
    value is intentionally an integer number of seconds so the same policy is
    easy to expose in CLI/dashboard configuration later.
    """

    source = os.environ if environ is None else environ
    raw = source.get("AIDN_RUNTIME_WARM_RETENTION_SECONDS")
    if raw is None:
        return DEFAULT_WARM_RETENTION_SECONDS
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_WARM_RETENTION_SECONDS


def minimum_residency_seconds(environ: dict[str, str] | None = None) -> int:
    """Return the global lower bound for a newly loaded runtime.

    The value is deliberately zero by default.  Operators can turn on churn
    protection globally through the same TOML-backed environment contract
    used by the rest of the Hypervisor configuration.
    """

    source = os.environ if environ is None else environ
    raw = source.get("AIDN_RUNTIME_MINIMUM_RESIDENCY_SECONDS")
    if raw is None:
        return DEFAULT_MINIMUM_RESIDENCY_SECONDS
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_MINIMUM_RESIDENCY_SECONDS


def _bundle_value(bundle: Any | None, name: str, default: Any = None) -> Any:
    if bundle is None:
        return default
    value = getattr(bundle, name, default)
    return default if value is None else value


def runtime_preemption_class(runtime: RuntimeHandle | None, bundle: Any | None = None) -> str:
    """Resolve the normalized preemption class for one runtime."""

    value = _bundle_value(bundle, "preemption_class", None)
    if value is None and runtime is not None:
        metadata = getattr(runtime, "metadata", {})
        value = metadata.get("preemption_class") if isinstance(metadata, dict) else None
    normalized = str(value or "DRAINABLE").upper()
    return normalized if normalized in _PREEMPTION_CLASS_SET else "DRAINABLE"


def runtime_retention_seconds(
    runtime: RuntimeHandle | None,
    bundle: Any | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> int:
    """Resolve per-bundle warm retention with a global fallback."""

    value = _bundle_value(bundle, "warm_retention_seconds", None)
    if value is None and runtime is not None:
        metadata = getattr(runtime, "metadata", {})
        raw = metadata.get("warm_retention_seconds") if isinstance(metadata, dict) else None
        if raw not in (None, ""):
            value = raw
    if value is None:
        return warm_retention_seconds(environ)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return warm_retention_seconds(environ)


def runtime_minimum_residency_seconds(
    runtime: RuntimeHandle | None,
    bundle: Any | None = None,
    *,
    environ: dict[str, str] | None = None,
) -> int:
    """Resolve the churn-protection residency floor for one runtime."""

    value = _bundle_value(bundle, "minimum_residency_seconds", None)
    if value is None and runtime is not None:
        metadata = getattr(runtime, "metadata", {})
        raw = metadata.get("minimum_residency_seconds") if isinstance(metadata, dict) else None
        if raw not in (None, ""):
            value = raw
    if value is None:
        return minimum_residency_seconds(environ)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return minimum_residency_seconds(environ)


def mark_runtime_residency_started(
    runtime: RuntimeHandle,
    *,
    at: datetime | None = None,
) -> None:
    """Persist the timestamp used by minimum-residency eviction policy."""

    metadata = getattr(runtime, "metadata", None)
    if not isinstance(metadata, dict):
        return
    metadata["residency_started_at"] = _iso_timestamp(at)


def runtime_residency_age_seconds(
    runtime: RuntimeHandle,
    *,
    now: datetime | None = None,
) -> float | None:
    """Return residency age, or ``None`` for legacy handles without metadata."""

    metadata = getattr(runtime, "metadata", {})
    started = _parse_timestamp(
        metadata.get("residency_started_at") if isinstance(metadata, dict) else None
    )
    if started is None:
        return None
    reference = (now or _now_utc()).astimezone(UTC)
    return max(0.0, (reference - started).total_seconds())


def is_local_owner_task(task: Any | None) -> bool:
    """Recognize explicit local-owner work without trusting free-form text."""

    constraints = getattr(task, "constraints", None)
    if not isinstance(constraints, dict):
        return False
    if constraints.get("local_owner") is True:
        return True
    for key in ("owner_scope", "request_origin", "execution_scope"):
        value = str(constraints.get(key, "")).strip().lower()
        if value in {"local", "operator", "local_owner"}:
            return True
    return False


def evaluate_runtime_eviction(
    runtime: RuntimeHandle | None,
    bundle: Any | None,
    waiting_task: Any | None,
    *,
    active_task_count: int = 0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Explain whether an idle runtime is eligible for policy eviction.

    This helper only evaluates *idle* runtimes.  Draining active work and
    checkpoint/preemption execution remain explicit lifecycle operations; the
    scheduler must never terminate an in-flight request as a side effect of a
    read-only admission calculation.
    """

    local_owner = is_local_owner_task(waiting_task)
    result: dict[str, Any] = {
        "eligible": False,
        "reason": "runtime_missing",
        "preemption_class": runtime_preemption_class(runtime, bundle),
        "local_owner": local_owner,
        "runtime_state": getattr(runtime, "lifecycle_state", "COLD") if runtime else "COLD",
        "residency_age_seconds": None,
        "minimum_residency_seconds": runtime_minimum_residency_seconds(runtime, bundle),
    }
    if runtime is None:
        return result
    if active_task_count > 0:
        result["reason"] = "active_work"
        return result

    result["residency_age_seconds"] = runtime_residency_age_seconds(runtime, now=now)
    preemption = result["preemption_class"]
    minimum = result["minimum_residency_seconds"]
    age = result["residency_age_seconds"]
    # Local owner reclamation is an explicit higher-level safety policy.  It
    # can reclaim idle warm capacity even when a remote-facing runtime is
    # pinned or marked non-preemptible.
    if not local_owner and bool(getattr(runtime, "pinned_warm", False)):
        result["reason"] = "pinned_warm"
        return result
    if not local_owner and preemption == "NON_PREEMPTIBLE":
        result["reason"] = "non_preemptible"
        return result
    if not local_owner and minimum and age is not None and age < minimum:
        result["reason"] = "minimum_residency"
        return result

    warm_policy = str(_bundle_value(bundle, "warm_policy", "auto")).lower()
    priority = int(getattr(waiting_task, "priority", 0) or 0)
    bundle_priority = int(_bundle_value(bundle, "priority_class", 50) or 50)
    if warm_policy == "always" and not local_owner and priority <= bundle_priority:
        result["reason"] = "priority_policy"
        return result

    result["eligible"] = True
    result["reason"] = "local_owner_reclamation" if local_owner else "policy_allows_eviction"
    return result


def set_runtime_lifecycle_state(runtime: RuntimeHandle, state: str) -> str:
    """Set and validate the canonical RFC-0073 lifecycle state."""

    normalized = str(state).upper()
    if normalized not in _RUNTIME_INSTANCE_STATE_SET:
        raise ValueError(f"Unknown Runtime Instance state: {state}")
    runtime.lifecycle_state = normalized
    return normalized


def touch_runtime_activity(
    runtime: RuntimeHandle,
    *,
    at: datetime | None = None,
) -> None:
    """Record activity while retaining the runtime for warm reuse."""

    runtime.last_activity_at = _iso_timestamp(at)
    if getattr(runtime, "status", None) not in {"stopped", "failed"}:
        set_runtime_lifecycle_state(runtime, "WARM_ACTIVE")


def derive_runtime_state(
    runtime: RuntimeHandle | None,
    *,
    active_task_count: int = 0,
    drain_mode: bool = False,
    now: datetime | None = None,
    warm_retention_seconds_value: int | None = None,
) -> str:
    """Project one RuntimeHandle into the RFC-0073 state machine.

    ``COLD`` is represented by the absence of a RuntimeHandle.  Once a handle
    exists, the process status, provider readiness, task count, and warm
    retention determine its state.  Explicit control states (draining,
    stopping, eviction candidate) are preserved while the handle is still
    active so an in-flight operation remains visible to operators.
    """

    if runtime is None:
        return "COLD"

    status = str(getattr(runtime, "status", "")).lower()
    current = str(getattr(runtime, "lifecycle_state", "")).upper()
    health = str(getattr(runtime, "health_status", "")).lower()
    readiness = str(getattr(runtime, "readiness_status", "")).upper()

    if status == "cold":
        return "COLD"
    if status == "failed":
        return "FAILED"
    if status == "stopping":
        return "STOPPING"
    if status == "stopped":
        failed = health in {"unhealthy", "cooldown"} or readiness == "FAILED"
        if getattr(runtime, "last_error", None) and readiness not in {"STOPPED", "UNKNOWN"}:
            failed = True
        return "FAILED" if failed else "STOPPED"

    if current in {"STOPPING", "EVICTION_CANDIDATE"} and status in {
        "starting",
        "running",
        "draining",
    }:
        return current
    if drain_mode or status == "draining":
        return "DRAINING"
    if status == "starting":
        return "STARTING"
    if health in {"unhealthy", "cooldown"} or readiness in {"FAILED", "NOT_READY"}:
        return "FAILED"
    if active_task_count > 0:
        return "BUSY"
    if bool(getattr(runtime, "pinned_warm", False)):
        return "WARM_ACTIVE"

    activity = _parse_timestamp(getattr(runtime, "last_activity_at", None))
    if activity is not None:
        retention = (
            warm_retention_seconds()
            if warm_retention_seconds_value is None
            else max(0, int(warm_retention_seconds_value))
        )
        reference = (now or _now_utc()).astimezone(UTC)
        if reference - activity <= timedelta(seconds=retention):
            return "WARM_ACTIVE"
    return "WARM_IDLE"


class RuntimeInstanceManager:
    """Small state-machine facade used by read-side and lifecycle code.

    The process manager remains the owner of subprocesses.  This facade keeps
    transitions and projections centralized without taking ownership of
    process spawning, leases, or provider health probes.
    """

    states = RUNTIME_INSTANCE_STATES

    @staticmethod
    def project(
        runtime: RuntimeHandle | None,
        *,
        active_task_count: int = 0,
        drain_mode: bool = False,
        now: datetime | None = None,
        warm_retention_seconds_value: int | None = None,
    ) -> str:
        return derive_runtime_state(
            runtime,
            active_task_count=active_task_count,
            drain_mode=drain_mode,
            now=now,
            warm_retention_seconds_value=warm_retention_seconds_value,
        )

    @staticmethod
    def transition(runtime: RuntimeHandle, state: str) -> str:
        return set_runtime_lifecycle_state(runtime, state)
