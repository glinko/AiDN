from dataclasses import FrozenInstanceError

import pytest

from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.resources import ResourceOrchestrator


def test_reserve_rejects_request_that_exceeds_ram() -> None:
    orchestrator = ResourceOrchestrator(NodeCapacity(cpu_cores=8, ram_mb=4096, gpu_devices=[], vram_mb={}))

    admitted = orchestrator.can_fit(cpu=1.0, ram_mb=8192, vram_mb=0)

    assert admitted is False


def test_reserve_raises_value_error_on_over_capacity_request() -> None:
    orchestrator = ResourceOrchestrator(NodeCapacity(cpu_cores=8, ram_mb=4096, gpu_devices=[], vram_mb={}))

    with pytest.raises(ValueError, match="insufficient resources"):
        orchestrator.reserve("task-1", cpu=1.0, ram_mb=8192, vram_mb=0)


def test_active_reservation_reduces_capacity_until_release() -> None:
    orchestrator = ResourceOrchestrator(
        NodeCapacity(cpu_cores=8, ram_mb=4096, gpu_devices=["gpu0"], vram_mb={"gpu0": 2048})
    )

    reservation = orchestrator.reserve("task-1", cpu=2.0, ram_mb=1024, vram_mb=512)

    assert orchestrator.can_fit(cpu=8.0, ram_mb=4096, vram_mb=2048) is False

    orchestrator.release(reservation.reservation_id)

    assert orchestrator.can_fit(cpu=8.0, ram_mb=4096, vram_mb=2048) is True


def test_reserve_rejects_duplicate_reservation_id() -> None:
    orchestrator = ResourceOrchestrator(NodeCapacity(cpu_cores=8, ram_mb=4096, gpu_devices=[], vram_mb={}))

    orchestrator.reserve("task-1", cpu=1.0, ram_mb=512, vram_mb=0)

    with pytest.raises(ValueError):
        orchestrator.reserve("task-1", cpu=1.0, ram_mb=512, vram_mb=0)


def test_can_fit_rejects_negative_resource_request() -> None:
    orchestrator = ResourceOrchestrator(NodeCapacity(cpu_cores=8, ram_mb=4096, gpu_devices=[], vram_mb={}))

    assert orchestrator.can_fit(cpu=-1.0, ram_mb=0, vram_mb=0) is False


def test_reserve_rejects_negative_resource_request() -> None:
    orchestrator = ResourceOrchestrator(NodeCapacity(cpu_cores=8, ram_mb=4096, gpu_devices=[], vram_mb={}))

    with pytest.raises(ValueError):
        orchestrator.reserve("task-1", cpu=-1.0, ram_mb=0, vram_mb=0)


def test_returned_reservation_cannot_be_mutated() -> None:
    orchestrator = ResourceOrchestrator(NodeCapacity(cpu_cores=8, ram_mb=4096, gpu_devices=[], vram_mb={}))

    reservation = orchestrator.reserve("task-1", cpu=1.0, ram_mb=512, vram_mb=0)

    with pytest.raises(FrozenInstanceError):
        reservation.cpu = 4.0


def test_capacity_refresh_cannot_invalidate_active_reservations() -> None:
    orchestrator = ResourceOrchestrator(NodeCapacity(cpu_cores=8, ram_mb=4096))
    orchestrator.reserve("task-1", cpu=2.0, ram_mb=1024, vram_mb=0)

    with pytest.raises(ValueError, match="below active reservations"):
        orchestrator.replace_capacity(NodeCapacity(cpu_cores=1, ram_mb=4096))


def test_capacity_refresh_exposes_measurement_source() -> None:
    orchestrator = ResourceOrchestrator(NodeCapacity(cpu_cores=1, ram_mb=1024))

    orchestrator.replace_capacity(
        NodeCapacity(cpu_cores=4, ram_mb=8192),
        probe={"source": "operator-refresh"},
    )

    assert orchestrator.summary()["probe"] == {"source": "operator-refresh"}


def test_measured_gpu_usage_reduces_allocatable_vram_without_double_counting_leases() -> None:
    orchestrator = ResourceOrchestrator(
        NodeCapacity(cpu_cores=8, ram_mb=16384, gpu_devices=["gpu0"], vram_mb={"gpu0": 24576}),
        probe={"measured_vram_mb": {"gpu0": 22138}},
    )

    assert orchestrator.admission_report(cpu=0, ram_mb=0, vram_mb=3000)["allowed"] is False
    assert orchestrator.summary()["free"]["vram_mb"] == 2438

    orchestrator.reserve("runtime:r4", cpu=0, ram_mb=0, vram_mb=1000)
    assert orchestrator.summary()["free"]["vram_mb"] == 2438


def test_forecast_is_side_effect_free_and_lists_active_leases() -> None:
    orchestrator = ResourceOrchestrator(
        NodeCapacity(cpu_cores=8, ram_mb=4096, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096})
    )
    orchestrator.reserve("runtime:a", cpu=2.0, ram_mb=1024, vram_mb=1024)

    forecast = orchestrator.forecast(cpu=3.0, ram_mb=1024, vram_mb=4096)

    assert forecast["decision"] == "RESOURCE_WAIT"
    assert forecast["retryable"] is True
    assert forecast["shortfall"]["vram_mb"] == 1024
    assert forecast["leases"] == [
        {"reservation_id": "runtime:a", "cpu": 2.0, "ram_mb": 1024, "vram_mb": 1024}
    ]
    assert orchestrator.summary()["reserved"]["vram_mb"] == 1024
