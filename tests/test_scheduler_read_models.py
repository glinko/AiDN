from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile, TaskRequest
from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
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


def test_scheduler_explain_decision_returns_resource_factors() -> None:
    service = _service()
    candidate = next(
        item
        for item in service.scheduler_candidates()
        if item["endpoint_id"] == "endpoint-large"
    )

    explanation = service.scheduler_explain_decision(candidate["task_id"])

    assert explanation["decision"] == "WAITING_FOR_RESOURCES"
    assert explanation["reason"] == "insufficient_resources"
    assert explanation["queue"]["head_of_line"] is True
    assert explanation["candidate"]["shortfall"]["vram_mb"] == 576
    assert {item["name"] for item in explanation["factors"]} >= {
        "queue_order",
        "priority",
        "required",
        "free",
        "shortfall",
        "eviction_candidates",
    }


def test_scheduler_explain_decision_identifies_endpoint_head_of_line() -> None:
    service = _service()
    first = next(
        item
        for item in service.scheduler_candidates()
        if item["endpoint_id"] == "endpoint-large"
    )
    later = service.queue.enqueue(
        TaskRequest(
            task_type="llm_text",
            payload={"prompt": "later"},
            constraints={"endpoint_id": "endpoint-large"},
        )
    )
    service._selected_bundles[later.task_id] = "bundle-large"

    explanation = service.scheduler_explain_decision(later.task_id)

    assert explanation["decision"] == "WAITING_FOR_QUEUE"
    assert explanation["reason"] == "head_of_line"
    assert explanation["queue"]["head_task_id"] == first["task_id"]
    assert explanation["queue"]["position"] == 2


def test_endpoint_queue_is_fifo_without_blocking_a_fitting_peer() -> None:
    service = _service()
    existing_large = next(
        item for item in service.scheduler_candidates() if item["endpoint_id"] == "endpoint-large"
    )
    later_large = service.queue.enqueue(
        TaskRequest(
            task_type="llm_text",
            payload={"prompt": "later"},
            priority=100,
            constraints={"endpoint_id": "endpoint-large"},
        )
    )
    service._selected_bundles[later_large.task_id] = "bundle-large"

    candidates = service.scheduler_candidates()
    large = next(item for item in candidates if item["endpoint_id"] == "endpoint-large")

    # Endpoint queues are FIFO even when a newer request has a higher
    # priority.  The peer Endpoint remains independently schedulable.
    assert large["task_id"] == existing_large["task_id"]
    assert large["queue_key"] == "endpoint:endpoint-large"
    assert large["queue_policy"] == "fifo"
    assert large["queue_position"] == 1
    assert large["head_of_line"] is True
    assert large["queue_depth"] == 2
    small = next(item for item in candidates if item["endpoint_id"] == "endpoint-small")

    service.process_pending()

    assert service.get_task(later_large.task_id).status == "queued"
    assert service.get_task(existing_large["task_id"]).status == "queued"
    assert service.get_task(small["task_id"]).status == "completed"


def test_endpoint_mutations_trigger_global_reconciliation_callback() -> None:
    service = _service()
    endpoint_service = EndpointService(
        EndpointStore(),
        record_creation_operation=False,
        record_update_operation=False,
    )
    triggers: list[str] = []
    service.reconcile_scheduler = lambda *, trigger: triggers.append(trigger)
    service.bind_external_services(endpoint_service=endpoint_service)

    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-test",
            bundle_id="bundle-small",
            bundle_hash="bundle-small-hash",
            display_name="Small endpoint",
            model_class="llm_text",
        )
    )
    endpoint_service.disable_endpoint(created.endpoint.endpoint_id)

    assert triggers == ["endpoint_created", "endpoint_disabled"]


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


def test_global_reconciliation_emits_resource_lifecycle_events() -> None:
    service = _service()

    service.process_pending()

    events = [
        event
        for event in service.event_journal()
        if event.event_type.startswith("aidn.resource.reconciliation")
        or event.event_type == "aidn.resource.activation_waiting"
    ]
    assert [event.event_type for event in events].count(
        "aidn.resource.reconciliation_started"
    ) == 1
    assert [event.event_type for event in events].count(
        "aidn.resource.reconciliation_completed"
    ) == 1
    waiting = [
        event for event in events if event.event_type == "aidn.resource.activation_waiting"
    ]
    assert waiting
    assert waiting[0].task_id
    assert waiting[0].details["shortfall"]["vram_mb"] == 576
