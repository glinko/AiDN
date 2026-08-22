"""Operator read models for the Resource Broker and local Scheduler.

The Resource Broker already owns admission decisions.  This module only
projects that live state for the Advanced Mode dashboard; it never reserves,
evicts, or starts a runtime as a side effect of a read.
"""

from __future__ import annotations

from datetime import UTC, datetime
from math import ceil
from typing import Any


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _percentile(values: list[float], percentile: float) -> float | None:
    """Return a deterministic nearest-rank percentile for a small sample."""

    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil((percentile / 100) * len(ordered)) - 1))
    return round(ordered[index], 3)


def _queue_wait_metrics(service) -> dict[str, Any]:
    """Measure wait for requests currently present in the queue.

    The queue currently has no durable completion timestamps, so these are
    explicitly labelled as a live sample rather than historical service-level
    percentiles.  A future telemetry store can replace this projection without
    changing the dashboard contract.
    """

    queue = getattr(service, "queue", None)
    snapshot = queue.snapshot() if queue is not None else []
    now = _now()
    waits: list[float] = []
    for task in snapshot:
        if getattr(task, "status", None) != "queued":
            continue
        created_at = _parse_timestamp(getattr(task, "created_at", None))
        if created_at is None:
            continue
        waits.append(max(0.0, (now - created_at).total_seconds()))
    return {
        "source": "current_queued_tasks",
        "sample_count": len(waits),
        "p50_seconds": _percentile(waits, 50),
        "p95_seconds": _percentile(waits, 95),
        "oldest_seconds": round(max(waits), 3) if waits else None,
        "historical": False,
    }


def _safe_runtime_operations(service) -> dict[str, Any]:
    try:
        payload = service.runtime_operations()
    except Exception as error:  # pragma: no cover - provider boundary
        return {
            "generated_at": _now_iso(),
            "freshness": {
                "source": "runtime_read_failed",
                "reconciliation_error": f"{type(error).__name__}",
            },
            "summary": {},
            "runtimes": [],
            "installation_jobs": [],
        }
    return payload if isinstance(payload, dict) else {}


def build_resource_broker_dashboard_payload(*, service) -> dict[str, Any]:
    """Build a bounded, read-only Resources/Scheduler dashboard payload."""

    resources = getattr(service, "resources", None)
    if resources is None:
        return {
            "available": False,
            "generated_at": _now_iso(),
            "reason": "resource_broker_unavailable",
            "hardware": {},
            "summary": {},
            "scheduler": {},
            "leases": [],
            "runtimes": [],
            "runtime_summary": {},
            "metrics": {
                "queue_wait": _queue_wait_metrics(service),
            },
        }

    hardware = resources.hardware_status()
    summary = resources.summary()
    try:
        leases = resources.lease_details()
    except AttributeError:  # pragma: no cover - compatibility with old stores
        leases = resources.lease_snapshot()

    try:
        scheduler = service.scheduler_status(candidate_limit=200)
    except Exception as error:  # pragma: no cover - scheduler boundary
        scheduler = {
            "queue": {},
            "candidates": {"total": 0, "by_status": {}, "items": []},
            "resources": {},
            "reconciliation": {
                "status": "error",
                "error": type(error).__name__,
            },
        }

    runtime_operations = _safe_runtime_operations(service)
    candidate_projection = scheduler.get("candidates") or {}
    by_status = dict(candidate_projection.get("by_status") or {})
    candidate_total = int(candidate_projection.get("total") or 0)
    runnable = int(by_status.get("RUNNABLE", 0))
    waiting = int(by_status.get("RESOURCE_WAIT", 0))
    queue_wait = _queue_wait_metrics(service)

    return {
        "available": True,
        "generated_at": _now_iso(),
        "hardware": hardware,
        "summary": summary,
        "scheduler": scheduler,
        "leases": leases,
        "runtimes": list(runtime_operations.get("runtimes") or []),
        "runtime_summary": dict(runtime_operations.get("summary") or {}),
        "metrics": {
            "candidate_count": candidate_total,
            "runnable_count": runnable,
            "resource_wait_count": waiting,
            "admission_denial_count": max(0, candidate_total - runnable),
            "queue_wait": queue_wait,
            "runtime_freshness": dict(runtime_operations.get("freshness") or {}),
        },
    }
