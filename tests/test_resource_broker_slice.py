from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.main import build_app
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resource_probe import ResourceProbeReport, read_resource_probe_report, write_resource_probe_report
from aidn_hypervisor.resources import (
    ResourceAdmissionError,
    ResourceOrchestrator,
    ResourceReconciliationRequiredError,
    ResourceSafetyPolicy,
)
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


def _capacity(*, ram_mb: int = 4096, vram_mb: int = 4096) -> NodeCapacity:
    return NodeCapacity(
        cpu_cores=4,
        ram_mb=ram_mb,
        gpu_devices=["gpu0"] if vram_mb else [],
        vram_mb={"gpu0": vram_mb} if vram_mb else {},
    )


def test_atomic_lease_has_lifecycle_details_and_legacy_projection() -> None:
    broker = ResourceOrchestrator(_capacity())

    lease = broker.acquire_lease(
        "runtime:test",
        cpu=1.0,
        ram_mb=512,
        vram_mb=1024,
        owner_id="bundle-test",
        lease_seconds=30,
        metadata={"kind": "runtime"},
    )

    assert lease.status == "ACTIVE"
    assert lease.owner_id == "bundle-test"
    assert lease.expires_at is not None
    assert broker.lease_snapshot() == [
        {"reservation_id": "runtime:test", "cpu": 1.0, "ram_mb": 512, "vram_mb": 1024}
    ]
    details = broker.lease_details()[0]
    assert details["lease_id"] == "runtime:test"
    assert details["metadata"] == {"kind": "runtime"}


def test_lease_ttl_expiry_releases_capacity() -> None:
    now = datetime(2026, 8, 21, tzinfo=UTC)
    broker = ResourceOrchestrator(_capacity(), clock=lambda: now)
    broker.acquire_lease("temporary", cpu=1.0, ram_mb=512, vram_mb=0, lease_seconds=5)

    assert broker.expire_leases(now=now + timedelta(seconds=4)) == []
    assert broker.expire_leases(now=now + timedelta(seconds=5)) == ["temporary"]
    assert broker.lease_snapshot() == []
    assert broker.lease_details(include_inactive=True)[0]["status"] == "EXPIRED"


def test_uncertain_reconciliation_fails_closed_then_recovers() -> None:
    broker = ResourceOrchestrator(_capacity(ram_mb=4096, vram_mb=4096))
    broker.acquire_lease("runtime:existing", cpu=1.0, ram_mb=1024, vram_mb=1024)

    status = broker.reconcile_hardware(
        _capacity(ram_mb=512, vram_mb=512),
        probe={"source": "operator-refresh", "observed_at": "2026-08-21T00:00:00+00:00"},
    )
    assert status["reconciliation"]["state"] == "UNCERTAIN"
    with pytest.raises(ResourceReconciliationRequiredError) as error:
        broker.acquire_lease("runtime:new", cpu=0, ram_mb=0, vram_mb=0)
    assert error.value.code == "RESOURCE_RECONCILIATION_REQUIRED"

    recovered = broker.reconcile_hardware(_capacity(), probe={"source": "operator-refresh"})
    assert recovered["reconciliation"]["state"] == "TRUSTED"
    broker.acquire_lease("runtime:new", cpu=0, ram_mb=0, vram_mb=0)


def test_resource_safety_headroom_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIDN_RESOURCE_VRAM_SAFETY_MB", "512")
    monkeypatch.setenv("AIDN_RESOURCE_VRAM_SAFETY_RATIO", "0")
    policy = ResourceSafetyPolicy.from_environment()
    broker = ResourceOrchestrator(_capacity(vram_mb=4096), safety=policy)

    assert broker.summary()["free"]["vram_mb"] == 3584
    assert broker.admission_report(cpu=0, ram_mb=0, vram_mb=3585)["allowed"] is False


def test_resource_probe_extended_hardware_fields_round_trip(tmp_path) -> None:
    report = ResourceProbeReport(
        capacity=_capacity(),
        source="test-monitor",
        observed_at="2026-08-21T00:00:00+00:00",
        measured_cpu_cores=1.5,
        measured_ram_mb=1234,
        storage={"path": "/", "total_bytes": 100, "used_bytes": 40, "free_bytes": 60},
        external_processes=(
            {"gpu_uuid": "GPU-1", "pid": 42, "process_name": "python", "used_memory_mb": 100},
        ),
    )
    path = tmp_path / "probe.json"
    write_resource_probe_report(report, path)
    restored = read_resource_probe_report(path)

    assert restored == report


def test_hardware_status_api_is_separate_from_legacy_summary() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(_capacity()),
        bundles=[],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )
    client = TestClient(build_app(service=service))
    response = client.get("/resources/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert "reconciliation" in payload
    assert "cpu" in payload
    assert "ram" in payload
    assert "gpus" in payload
