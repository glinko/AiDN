"""Live operator read models for runtime readiness and provider jobs.

The durable dashboard snapshot is useful for recovery, but it is not the
authority for facts owned by a child process or the provider-runtime broker.
This module is the deliberately small read-side boundary that reconciles
those two sources before projecting a response for operators and agents.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


_TERMINAL_JOB_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED"}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _bounded_text(value: Any, *, limit: int = 1024) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:limit]


def _runtime_record(service, runtime, readiness: dict[str, Any]) -> dict[str, Any]:
    bundles = getattr(service, "bundles", [])
    bundle = next(
        (item for item in bundles if item.bundle_id == runtime.bundle_id),
        None,
    )
    active_task_count = 0
    try:
        active_task_count = int(
            service._runtime_boundary.runtime_active_task_count(runtime.bundle_id or "")
        )
    except (AttributeError, TypeError, ValueError):
        active_task_count = 0
    readiness_payload = readiness.get("readiness") or {}
    return {
        "runtime_id": runtime.runtime_id,
        "bundle_id": runtime.bundle_id,
        "provider_type": getattr(bundle, "provider_type", None),
        "plugin_id": getattr(bundle, "plugin_id", None),
        "model_id": readiness.get("model_id") or getattr(bundle, "model_id", None),
        "endpoint": readiness.get("endpoint") or runtime.metadata.get("endpoint"),
        "runtime_status": readiness.get("runtime_status") or runtime.status,
        "health_status": readiness.get("health_status") or runtime.health_status,
        "readiness_status": readiness_payload.get("status") or runtime.readiness_status,
        "readiness_code": readiness_payload.get("code") or runtime.readiness_code,
        "readiness_message": readiness_payload.get("message") or runtime.readiness_message,
        "readiness_checked_at": readiness_payload.get("checked_at")
        or runtime.readiness_checked_at,
        "readiness_diagnostic": dict(
            readiness_payload.get("diagnostic") or runtime.readiness_diagnostic or {}
        ),
        "last_error": readiness.get("last_error") or runtime.last_error,
        "active_task_count": active_task_count,
    }


def _installation_job_record(job: dict[str, Any]) -> dict[str, Any]:
    progress_events = job.get("progress_events")
    events = progress_events if isinstance(progress_events, list) else []
    last_event = events[-1] if events and isinstance(events[-1], dict) else None
    return {
        "job_id": job.get("job_id"),
        "approval_id": job.get("approval_id"),
        "plugin_id": job.get("plugin_id"),
        "provider_instance_id": job.get("provider_instance_id"),
        "status": job.get("status"),
        "progress_percent": job.get("progress_percent", 0),
        "current_step": job.get("current_step"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "updated_at": job.get("updated_at"),
        "cancel_requested": bool(job.get("cancel_requested", False)),
        "broker_status": job.get("broker_status"),
        "error_code": job.get("error_code"),
        "error_message": _bounded_text(job.get("error_message")),
        "step_count": len(job.get("step_results") or []),
        "progress_event_count": len(events),
        "last_progress_event": last_event,
    }


def build_runtime_operations_payload(*, service) -> dict[str, Any]:
    """Return a freshly reconciled runtime/provider operations projection.

    A read can legitimately advance a durable installation job after a
    restart: the provider broker is authoritative and the Hypervisor must
    reattach its poller before reporting progress.  Errors are retained as a
    bounded diagnostic in the read model instead of turning a status page into
    a 500 response.
    """

    reconciliation_error: str | None = None
    try:
        service.refresh_runtime_health(force=True)
    except Exception as error:  # pragma: no cover - plugin boundary
        reconciliation_error = f"runtime_health_reconciliation_failed: {type(error).__name__}"

    jobs_reconciled = False
    try:
        reconcile_jobs = getattr(service.provider_inventory, "reconcile_installation_jobs", None)
        if callable(reconcile_jobs):
            reconcile_jobs()
            jobs_reconciled = True
    except Exception as error:  # pragma: no cover - broker boundary
        detail = f"provider_job_reconciliation_failed: {type(error).__name__}"
        reconciliation_error = f"{reconciliation_error}; {detail}" if reconciliation_error else detail

    runtimes: list[dict[str, Any]] = []
    for runtime in list(service.list_runtimes()):
        try:
            readiness = service.runtime_readiness(runtime.runtime_id, force=False)
            runtimes.append(_runtime_record(service, runtime, readiness))
        except (KeyError, ValueError):
            # A runtime may exit between list and probe.  The process manager
            # callback will persist the terminal state; omit the torn record
            # rather than presenting a false ready instance.
            continue
        except Exception as error:  # pragma: no cover - plugin boundary
            runtimes.append(
                _runtime_record(
                    service,
                    runtime,
                    {
                        "runtime_status": runtime.status,
                        "health_status": "unknown",
                        "readiness": {
                            "status": "UNKNOWN",
                            "code": "runtime_readiness_failed",
                            "message": f"Runtime readiness probe failed: {type(error).__name__}",
                            "checked_at": runtime.readiness_checked_at,
                            "diagnostic": {},
                        },
                        "last_error": runtime.last_error,
                    },
                )
            )

    jobs = [
        _installation_job_record(job)
        for job in service.list_provider_installation_jobs()
    ]
    active_jobs = [job for job in jobs if job.get("status") not in _TERMINAL_JOB_STATUSES]
    ready_runtimes = [item for item in runtimes if item.get("readiness_status") == "READY"]
    failed_runtimes = [
        item
        for item in runtimes
        if item.get("readiness_status") in {"FAILED", "NOT_READY"}
        or item.get("health_status") in {"unhealthy", "cooldown"}
    ]
    return {
        # Stamp after the live probes and broker reconciliation.  Consumers
        # can compare this value with the freshness boundary without treating
        # time spent probing as part of the next read's age.
        "generated_at": _now_iso(),
        "freshness": {
            "source": "live_reconciled",
            "max_age_seconds": 15,
            "runtime_health_reconciled": reconciliation_error is None
            or not reconciliation_error.startswith("runtime_health_reconciliation_failed"),
            "installation_jobs_reconciled": jobs_reconciled,
            "reconciliation_error": reconciliation_error,
        },
        "summary": {
            "runtime_total": len(runtimes),
            "runtime_ready": len(ready_runtimes),
            "runtime_failed_or_not_ready": len(failed_runtimes),
            "runtime_active_tasks": sum(item["active_task_count"] for item in runtimes),
            "installation_job_total": len(jobs),
            "installation_job_active": len(active_jobs),
            "installation_job_failed": sum(
                1 for job in jobs if job.get("status") == "FAILED"
            ),
        },
        "runtimes": runtimes,
        "installation_jobs": jobs,
    }
