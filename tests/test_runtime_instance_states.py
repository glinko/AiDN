from datetime import UTC, datetime, timedelta

from aidn_hypervisor.process_manager import ProviderProcessManager, RuntimeHandle
from aidn_hypervisor.runtime_instance_manager import (
    RuntimeInstanceManager,
    derive_runtime_state,
    set_runtime_lifecycle_state,
    touch_runtime_activity,
    warm_retention_seconds,
)
from aidn_hypervisor.state import RuntimeSnapshot


def _runtime(**updates) -> RuntimeHandle:
    values = {
        "runtime_id": "rt-1",
        "command": ["python", "-m", "http.server", "0"],
        "status": "running",
        "bundle_id": "bundle-a",
        "health_status": "healthy",
        "readiness_status": "READY",
    }
    values.update(updates)
    return RuntimeHandle(**values)


def test_runtime_instance_state_projection_covers_scheduler_states() -> None:
    now = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
    runtime = _runtime(status="starting", health_status="unknown", readiness_status="UNKNOWN")

    assert derive_runtime_state(None) == "COLD"
    assert derive_runtime_state(runtime) == "STARTING"

    runtime.status = "running"
    runtime.health_status = "healthy"
    runtime.readiness_status = "READY"
    assert derive_runtime_state(runtime) == "WARM_IDLE"
    assert derive_runtime_state(runtime, active_task_count=1) == "BUSY"
    assert derive_runtime_state(runtime, drain_mode=True) == "DRAINING"

    set_runtime_lifecycle_state(runtime, "EVICTION_CANDIDATE")
    assert derive_runtime_state(runtime) == "EVICTION_CANDIDATE"

    runtime.lifecycle_state = "WARM_IDLE"
    touch_runtime_activity(runtime, at=now)
    assert runtime.lifecycle_state == "WARM_ACTIVE"
    assert derive_runtime_state(
        runtime,
        now=now + timedelta(seconds=299),
        warm_retention_seconds_value=300,
    ) == "WARM_ACTIVE"
    assert derive_runtime_state(
        runtime,
        now=now + timedelta(seconds=301),
        warm_retention_seconds_value=300,
    ) == "WARM_IDLE"

    runtime.status = "stopped"
    runtime.readiness_status = "STOPPED"
    runtime.health_status = "unknown"
    assert derive_runtime_state(runtime) == "STOPPED"
    runtime.readiness_status = "FAILED"
    runtime.last_error = "provider exited"
    assert derive_runtime_state(runtime) == "FAILED"
    runtime.status = "failed"
    assert derive_runtime_state(runtime) == "FAILED"


def test_runtime_instance_manager_validates_transitions_and_retention(monkeypatch) -> None:
    runtime = _runtime()
    manager = RuntimeInstanceManager()

    assert manager.states[-1] == "FAILED"
    assert manager.project(runtime) == "WARM_IDLE"
    assert manager.transition(runtime, "BUSY") == "BUSY"
    assert runtime.lifecycle_state == "BUSY"

    try:
        manager.transition(runtime, "not-a-runtime-state")
    except ValueError as error:
        assert "Unknown Runtime Instance state" in str(error)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("invalid runtime state was accepted")

    monkeypatch.setenv("AIDN_RUNTIME_WARM_RETENTION_SECONDS", "42")
    assert warm_retention_seconds() == 42
    monkeypatch.setenv("AIDN_RUNTIME_WARM_RETENTION_SECONDS", "invalid")
    assert warm_retention_seconds() == 300


def test_runtime_lifecycle_metadata_round_trips_through_snapshot() -> None:
    runtime = _runtime(
        lifecycle_state="WARM_ACTIVE",
        last_activity_at="2026-08-21T12:00:00Z",
        pinned_warm=True,
    )
    snapshot = RuntimeSnapshot(
        runtime_id=runtime.runtime_id,
        command=runtime.command,
        status=runtime.status,
        bundle_id=runtime.bundle_id,
        health_status=runtime.health_status,
        readiness_status=runtime.readiness_status,
        lifecycle_state=runtime.lifecycle_state,
        last_activity_at=runtime.last_activity_at,
        pinned_warm=runtime.pinned_warm,
    )

    assert snapshot.lifecycle_state == "WARM_ACTIVE"
    assert snapshot.last_activity_at == "2026-08-21T12:00:00Z"
    assert snapshot.pinned_warm is True


def test_process_manager_stop_marks_runtime_terminal_state() -> None:
    manager = ProviderProcessManager()
    runtime = manager.start_runtime({"command": ["python", "-c", "pass"]})

    stopped = manager.stop_runtime(runtime.runtime_id)

    assert stopped.lifecycle_state == "STOPPED"
