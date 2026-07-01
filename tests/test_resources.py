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
    orchestrator = ResourceOrchestrator(NodeCapacity(cpu_cores=8, ram_mb=4096, gpu_devices=["gpu0"], vram_mb={"gpu0": 2048}))

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
