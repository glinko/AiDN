import pytest

from aidn_hypervisor.domain.models import (
    BundleConfig,
    NodeCapacity,
    ResourceProfile,
    TaskRequest,
)
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.resources import ResourceAdmissionError, ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.service import HypervisorService


def _service(*, ram_mb: int) -> HypervisorService:
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    bundle = BundleConfig(
        bundle_id="bundle-admission",
        plugin_id="fake-managed",
        provider_type="fake",
        workload_type="llm_text",
        model_id="model",
        launch_mode="managed_process",
        device_affinity="cpu",
        resource_profile=ResourceProfile(steady_ram_mb=2048),
        warm_policy="auto",
    )
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4, ram_mb=ram_mb)),
        bundles=[bundle],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
    )


def test_direct_bundle_activation_is_denied_before_runtime_start() -> None:
    service = _service(ram_mb=1024)

    with pytest.raises(ResourceAdmissionError) as error:
        service.start_bundle("bundle-admission")

    assert error.value.code == "RESOURCE_ADMISSION_DENIED"
    assert error.value.details["bundle_id"] == "bundle-admission"
    assert error.value.details["shortfall"]["ram_mb"] == 1024
    assert service.list_runtimes() == []


def test_direct_bundle_activation_holds_and_releases_residency() -> None:
    service = _service(ram_mb=4096)

    runtime = service.start_bundle("bundle-admission")
    assert runtime.status == "starting"
    assert service.resources.summary()["reserved"]["ram_mb"] == 2048

    service.stop_bundle("bundle-admission")
    assert service.resources.summary()["reserved"]["ram_mb"] == 0


def test_resource_race_returns_task_to_resource_wait_instead_of_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(ram_mb=4096)
    original_reserve = service.resources.reserve

    def race_reserve(reservation_id: str, *, cpu: float, ram_mb: int, vram_mb: int):
        if reservation_id == "runtime:bundle-admission":
            raise ResourceAdmissionError(
                details={
                    "reason": "resource_wait",
                    "shortfall": {"ram_mb": 2048},
                }
            )
        return original_reserve(
            reservation_id,
            cpu=cpu,
            ram_mb=ram_mb,
            vram_mb=vram_mb,
        )

    monkeypatch.setattr(service.resources, "reserve", race_reserve)

    task = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "wait for capacity"},
        )
    )

    assert service.get_task(task.task_id).status == "queued"
    assert service.queue_summary() == {
        "queued": 1,
        "active": 0,
        "completed": 0,
        "failed": 0,
    }
    resource_wait_events = [
        event
        for event in service.task_history(task.task_id)
        if event.event_type == "task.resource_wait"
    ]
    assert len(resource_wait_events) == 1
    assert resource_wait_events[0].details["code"] == "RESOURCE_ADMISSION_DENIED"
    assert service.list_runtimes() == []
