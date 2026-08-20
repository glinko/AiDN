from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile, TaskRequest
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


def _service() -> HypervisorService:
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(
                cpu_cores=4,
                ram_mb=4096,
                gpu_devices=["gpu0"],
                vram_mb={"gpu0": 1024},
            )
        ),
        bundles=[
            BundleConfig(
                bundle_id="bundle-large",
                plugin_id="fake-managed",
                provider_type="fake",
                workload_type="llm_text",
                model_id="large",
                launch_mode="managed_process",
                device_affinity="gpu0",
                resource_profile=ResourceProfile(steady_vram_mb=900),
                warm_policy="auto",
            ),
            BundleConfig(
                bundle_id="bundle-small",
                plugin_id="fake-managed",
                provider_type="fake",
                workload_type="llm_text",
                model_id="small",
                launch_mode="managed_process",
                device_affinity="gpu0",
                resource_profile=ResourceProfile(steady_vram_mb=100),
                warm_policy="auto",
            ),
        ],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
    )
    service.resources.reserve("runtime:external", cpu=0, ram_mb=0, vram_mb=700)
    for bundle_id, endpoint_id in (
        ("bundle-large", "endpoint-large"),
        ("bundle-small", "endpoint-small"),
    ):
        task = service.queue.enqueue(
            TaskRequest(
                task_type="llm_text",
                payload={"prompt": "queued"},
                constraints={"endpoint_id": endpoint_id},
            )
        )
        service._selected_bundles[task.task_id] = bundle_id
    return service


def test_scheduler_candidates_represent_all_endpoint_queues_and_explain_fit() -> None:
    service = _service()

    candidates = service.scheduler_candidates()
    by_endpoint = {item["endpoint_id"]: item for item in candidates}

    assert set(by_endpoint) == {"endpoint-large", "endpoint-small"}
    assert by_endpoint["endpoint-large"]["status"] == "RESOURCE_WAIT"
    assert by_endpoint["endpoint-large"]["shortfall"]["vram_mb"] == 576
    assert by_endpoint["endpoint-small"]["status"] == "RUNNABLE"
    assert by_endpoint["endpoint-small"]["reason"] == "resources_fit"


def test_scheduler_status_includes_queue_and_resource_projection() -> None:
    service = _service()

    status = service.scheduler_status()

    assert status["queue"]["queued_tasks"] == 2
    assert status["queue"]["independent_queues"] == 2
    assert status["candidates"]["by_status"] == {
        "RESOURCE_WAIT": 1,
        "RUNNABLE": 1,
    }
    assert status["resources"]["leases"][0]["reservation_id"] == "runtime:external"


def test_global_reconciliation_runs_fitting_peer_and_reports_resource_wait() -> None:
    service = _service()
    by_endpoint = {
        item["endpoint_id"]: item
        for item in service.scheduler_candidates()
    }
    large_task_id = by_endpoint["endpoint-large"]["task_id"]
    small_task_id = by_endpoint["endpoint-small"]["task_id"]

    summary = service.process_pending()

    assert service.get_task(small_task_id).status == "completed"
    assert service.get_task(large_task_id).status == "queued"
    assert summary["completed"] == 1
    reconciliation = service.scheduler_status()["reconciliation"]
    assert reconciliation["status"] == "stable"
    assert reconciliation["cycles"] >= 2
    assert reconciliation["waiting"][0]["task_id"] == large_task_id
