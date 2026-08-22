from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.resource_broker_read_models import (
    build_resource_broker_dashboard_payload,
)
from aidn_hypervisor.resources import ResourceOrchestrator


def test_resource_broker_dashboard_projects_live_capacity_leases_and_queue_wait() -> None:
    resources = ResourceOrchestrator(
        NodeCapacity(
            cpu_cores=8,
            ram_mb=16_384,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 24_576},
        ),
        probe={
            "source": "test-probe",
            "observed_at": "2026-08-22T12:00:00Z",
            "measured_cpu_cores": 2,
            "measured_ram_mb": 4096,
            "measured_vram_mb": {"gpu0": 8192},
        },
    )
    resources.acquire_lease(
        "runtime:test",
        cpu=2,
        ram_mb=2048,
        vram_mb=4096,
        owner_id="runtime:test",
    )
    queued_at = (datetime.now(UTC) - timedelta(seconds=91)).isoformat()
    service = SimpleNamespace(
        resources=resources,
        queue=SimpleNamespace(
            snapshot=lambda: [SimpleNamespace(status="queued", created_at=queued_at)],
        ),
        scheduler_status=lambda candidate_limit=200: {
            "queue": {"queued_tasks": 1, "independent_queues": 1},
            "candidates": {
                "total": 1,
                "by_status": {"RESOURCE_WAIT": 1},
                "items": [{
                    "task_id": "task-1",
                    "status": "RESOURCE_WAIT",
                    "required": {"vram_mb": 12_000},
                    "free": {"vram_mb": 8_000},
                    "shortfall": {"vram_mb": 4_000},
                }],
            },
            "reconciliation": {"status": "stable", "cycles": 2},
        },
        runtime_operations=lambda: {
            "summary": {"runtime_total": 1, "runtime_ready": 1},
            "runtimes": [{"runtime_id": "runtime:test", "lifecycle_state": "WARM_ACTIVE"}],
            "freshness": {"source": "live_reconciled"},
        },
    )

    payload = build_resource_broker_dashboard_payload(service=service)

    assert payload["available"] is True
    assert payload["hardware"]["source"] == "test-probe"
    assert payload["leases"][0]["lease_id"] == "runtime:test"
    assert payload["metrics"]["resource_wait_count"] == 1
    assert payload["metrics"]["queue_wait"]["sample_count"] == 1
    assert payload["metrics"]["queue_wait"]["p95_seconds"] >= 90
    assert payload["runtimes"][0]["runtime_id"] == "runtime:test"


def test_resource_broker_dashboard_fails_closed_when_resources_are_unavailable() -> None:
    service = SimpleNamespace(
        resources=None,
        queue=SimpleNamespace(snapshot=lambda: []),
    )

    payload = build_resource_broker_dashboard_payload(service=service)

    assert payload["available"] is False
    assert payload["reason"] == "resource_broker_unavailable"
    assert payload["leases"] == []
