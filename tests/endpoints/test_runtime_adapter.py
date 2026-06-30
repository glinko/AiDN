import pytest

from aidn_hypervisor.domain.models import (
    BundleConfig,
    NodeCapacity,
    ResourceProfile,
    TaskRequest,
)
from aidn_hypervisor.endpoints.models import CreateEndpointCommand, InvokeEndpointCommand
from aidn_hypervisor.endpoints.runtime_adapter import (
    EndpointExecutionError,
    EndpointRuntimeAdapter,
)
from aidn_hypervisor.endpoints.service import EndpointService, EndpointStateError
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager, RuntimeHandle
from aidn_hypervisor.queue import InMemoryTaskQueue, QueuedTask
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


class UnhealthyManagedPlugin(FakeManagedPlugin):
    plugin_id = "fake-unhealthy"

    def health_check(self, runtime_handle) -> bool:
        return False


class RecordingManagedPlugin(FakeManagedPlugin):
    plugin_id = "fake-recording"

    def __init__(self) -> None:
        self.invocations: list[dict] = []

    def invoke(self, task, runtime_handle) -> dict:
        self.invocations.append(
            {
                "task_type": task.task_type,
                "payload": dict(task.payload),
                "constraints": dict(task.constraints),
                "runtime_id": runtime_handle.runtime_id,
            }
        )
        return {
            "ok": True,
            "echo": dict(task.payload),
            "runtime_id": runtime_handle.runtime_id,
        }


class ConcurrencyLimitedRecordingPlugin(RecordingManagedPlugin):
    plugin_id = "fake-concurrency-recording"

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        result = super().estimate_resources(task, bundle_config, runtime_state)
        result["concurrency_limit"] = 1
        return result


class RuntimeSpecificConcurrencyRecordingPlugin(RecordingManagedPlugin):
    plugin_id = "fake-runtime-specific-concurrency-recording"

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        result = super().estimate_resources(task, bundle_config, runtime_state)
        result["concurrency_limit"] = 2 if runtime_state.runtime_id == "rt-1" else 1
        return result


class RecordingRuntimeManager:
    def __init__(self) -> None:
        self.launch_specs: list[dict] = []

    def start_runtime(self, launch_spec: dict) -> RuntimeHandle:
        self.launch_specs.append(dict(launch_spec))
        return RuntimeHandle(
            "rt-started",
            list(launch_spec["command"]),
            "starting",
            launch_spec.get("bundle_id"),
        )

    def list_runtimes(self) -> list[RuntimeHandle]:
        return []


def _bundle(
    *,
    plugin_id: str = "fake-recording",
    enabled: bool = True,
    resource_profile: ResourceProfile | None = None,
    warm_policy: str = "auto",
) -> BundleConfig:
    return BundleConfig(
        bundle_id="bundle-a",
        plugin_id=plugin_id,
        provider_type="fake",
        workload_type="llm_text",
        model_id="bundle-a-model",
        launch_mode="managed_process",
        endpoint="http://127.0.0.1:9000",
        device_affinity="cpu",
        resource_profile=resource_profile or ResourceProfile(),
        warm_policy=warm_policy,
        enabled=enabled,
    )


def _registry(*plugins: FakeManagedPlugin) -> PluginRegistry:
    registry = PluginRegistry()
    for plugin in plugins:
        registry.register(plugin)
    return registry


def _hypervisor(
    *,
    bundle: BundleConfig | None = None,
    plugin: FakeManagedPlugin | None = None,
    runtimes: list[RuntimeHandle] | None = None,
    resources: ResourceOrchestrator | None = None,
    state_store: FileStateStore | None = None,
) -> HypervisorService:
    active_plugin = plugin or RecordingManagedPlugin()
    active_bundle = bundle or _bundle(plugin_id=active_plugin.plugin_id)
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=resources
        or ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[active_bundle],
        plugins=_registry(active_plugin),
        runtimes=runtimes or [],
        state_store=state_store,
    )


def _endpoint_service(hypervisor: HypervisorService) -> EndpointService:
    return EndpointService(
        EndpointStore(allow_in_memory=True),
        runtime_adapter=EndpointRuntimeAdapter(hypervisor),
    )


def _create_active_endpoint(service: EndpointService) -> str:
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Bundle A",
            model_class="llm.text",
            capabilities=["llm.text"],
        )
    )
    service.start_endpoint(created.endpoint.endpoint_id)
    return created.endpoint.endpoint_id


def _invoke_command(endpoint_id: str) -> InvokeEndpointCommand:
    return InvokeEndpointCommand(
        endpoint_id=endpoint_id,
        task_type="llm_text.generate",
        payload={"prompt": "hello"},
        constraints={"tenant": "demo"},
    )


def _task_request() -> TaskRequest:
    return TaskRequest(
        task_type="llm_text.generate",
        payload={"prompt": "hello"},
        mode="manual",
        bundle_override="bundle-a",
        constraints={"tenant": "demo"},
    )


def test_endpoint_service_invokes_active_ready_endpoint_via_runtime_adapter() -> None:
    plugin = RecordingManagedPlugin()
    resources = ResourceOrchestrator(
        NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 0})
    )
    reserve_calls: list[tuple[str, float, int, int]] = []
    release_calls: list[str] = []
    original_reserve = resources.reserve
    original_release = resources.release

    def tracking_reserve(
        reservation_id: str, cpu: float, ram_mb: int, vram_mb: int
    ):
        reserve_calls.append((reservation_id, cpu, ram_mb, vram_mb))
        return original_reserve(reservation_id, cpu, ram_mb, vram_mb)

    def tracking_release(reservation_id: str) -> None:
        release_calls.append(reservation_id)
        original_release(reservation_id)

    resources.reserve = tracking_reserve  # type: ignore[method-assign]
    resources.release = tracking_release  # type: ignore[method-assign]
    hypervisor = _hypervisor(
        bundle=_bundle(
            plugin_id=plugin.plugin_id,
            resource_profile=ResourceProfile(
                per_request_cpu=0.25,
                per_request_ram_mb=128,
                per_request_vram_mb=0,
            ),
        ),
        plugin=plugin,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ],
        resources=resources,
    )
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)

    result = service.invoke_endpoint(_invoke_command(endpoint_id))

    assert result.endpoint.status == "active"
    assert result.bundle_id == "bundle-a"
    assert result.runtime_id == "rt-1"
    assert result.readiness.ready is True
    assert result.result == {
        "ok": True,
        "echo": {"prompt": "hello"},
        "runtime_id": "rt-1",
    }
    assert plugin.invocations == [
        {
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {"tenant": "demo"},
            "runtime_id": "rt-1",
        }
    ]
    request_reservations = [
        call for call in reserve_calls if call[0].startswith("request:sync:")
    ]
    assert request_reservations
    assert request_reservations[0][1:] == (0.25, 128, 0)
    assert request_reservations[0][0] in release_calls
    assert hypervisor.resources.summary()["reserved"] == {
        "cpu": 0.0,
        "ram_mb": 0,
        "vram_mb": 0,
    }


def test_endpoint_service_returns_readiness_for_active_endpoint() -> None:
    hypervisor = _hypervisor(
        plugin=RecordingManagedPlugin(),
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ],
    )
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)

    readiness = service.endpoint_readiness(endpoint_id, _invoke_command(endpoint_id))

    assert readiness.ready is True
    assert readiness.endpoint_id == endpoint_id
    assert readiness.bundle_id == "bundle-a"
    assert readiness.runtime_id == "rt-1"


def test_endpoint_service_rejects_non_active_endpoint_readiness() -> None:
    service = _endpoint_service(_hypervisor())
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Bundle A",
            model_class="llm.text",
            capabilities=["llm.text"],
        )
    )

    with pytest.raises(EndpointStateError):
        service.endpoint_readiness(
            created.endpoint.endpoint_id,
            _invoke_command(created.endpoint.endpoint_id),
        )


def test_endpoint_service_rejects_non_active_endpoint_invocation() -> None:
    service = _endpoint_service(_hypervisor())
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Bundle A",
            model_class="llm.text",
            capabilities=["llm.text"],
        )
    )

    with pytest.raises(EndpointStateError):
        service.invoke_endpoint(
            InvokeEndpointCommand(
                endpoint_id=created.endpoint.endpoint_id,
                task_type="llm_text.generate",
                payload={"prompt": "hello"},
            )
        )


def test_endpoint_service_surfaces_deterministic_runtime_unavailable_error() -> None:
    service = _endpoint_service(_hypervisor())
    endpoint_id = _create_active_endpoint(service)

    with pytest.raises(EndpointExecutionError) as excinfo:
        service.invoke_endpoint(
            _invoke_command(endpoint_id).model_copy(update={"constraints": {}})
        )

    assert excinfo.value.code == "runtime_unavailable"
    assert excinfo.value.readiness.ready is False
    assert excinfo.value.readiness.code == "runtime_unavailable"
    assert excinfo.value.readiness.runtime_id is None


def test_endpoint_sync_invoke_does_not_queue_or_start_when_runtime_unavailable() -> None:
    runtimes = RecordingRuntimeManager()
    hypervisor = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle()],
        plugins=_registry(RecordingManagedPlugin()),
        runtimes=runtimes,
    )
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)

    readiness = service.endpoint_readiness(endpoint_id, _invoke_command(endpoint_id))
    with pytest.raises(EndpointExecutionError) as excinfo:
        service.invoke_endpoint(_invoke_command(endpoint_id))

    assert readiness.code == "runtime_unavailable"
    assert excinfo.value.code == "runtime_unavailable"
    assert hypervisor.queue.snapshot() == []
    assert runtimes.launch_specs == []


def test_sync_bundle_invoke_rejects_effective_concurrency_saturation() -> None:
    plugin = ConcurrencyLimitedRecordingPlugin()
    hypervisor = _hypervisor(
        bundle=_bundle(
            plugin_id=plugin.plugin_id,
            resource_profile=ResourceProfile(per_request_cpu=0.25),
        ).model_copy(update={"max_parallel_requests": 3}),
        plugin=plugin,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ],
    )
    active_task = hypervisor.queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "busy"})
    )
    hypervisor._selected_bundles[active_task.task_id] = "bundle-a"
    hypervisor.queue.transition_status(active_task.task_id, "running")

    readiness = hypervisor.bundle_runtime_readiness("bundle-a", _task_request())

    assert readiness["ready"] is False
    assert readiness["reason"] == "concurrency_limit"
    assert readiness["runtime_id"] == "rt-1"
    assert "concurrency" in str(readiness["message"]).lower()
    with pytest.raises(RuntimeError, match="concurrency"):
        hypervisor.invoke_bundle_sync("bundle-a", _task_request())
    assert plugin.invocations == []


def test_endpoint_invoke_maps_concurrency_limit_to_execution_error() -> None:
    plugin = ConcurrencyLimitedRecordingPlugin()
    hypervisor = _hypervisor(
        bundle=_bundle(
            plugin_id=plugin.plugin_id,
            resource_profile=ResourceProfile(per_request_cpu=0.25),
        ).model_copy(update={"max_parallel_requests": 3}),
        plugin=plugin,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ],
    )
    active_task = hypervisor.queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "busy"})
    )
    hypervisor._selected_bundles[active_task.task_id] = "bundle-a"
    hypervisor.queue.transition_status(active_task.task_id, "running")
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)

    with pytest.raises(EndpointExecutionError) as excinfo:
        service.invoke_endpoint(_invoke_command(endpoint_id))

    assert excinfo.value.code == "concurrency_limit"
    assert excinfo.value.readiness.ready is False
    assert excinfo.value.readiness.code == "concurrency_limit"
    assert plugin.invocations == []


def test_endpoint_invoke_reuses_ready_admission_when_concurrency_changes() -> None:
    plugin = ConcurrencyLimitedRecordingPlugin()
    hypervisor = _hypervisor(
        bundle=_bundle(
            plugin_id=plugin.plugin_id,
            resource_profile=ResourceProfile(per_request_cpu=0.25),
        ).model_copy(update={"max_parallel_requests": 3}),
        plugin=plugin,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ],
    )
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)
    original_readiness = hypervisor.bundle_runtime_readiness
    readiness_calls = 0

    def readiness_then_saturate(bundle_id: str, request: TaskRequest) -> dict:
        nonlocal readiness_calls
        readiness_calls += 1
        readiness = original_readiness(bundle_id, request)
        if readiness_calls == 1:
            active_task = hypervisor.queue.enqueue(
                TaskRequest(task_type="llm_text.generate", payload={"prompt": "busy"})
            )
            hypervisor._selected_bundles[active_task.task_id] = "bundle-a"
            hypervisor.queue.transition_status(active_task.task_id, "running")
        return readiness

    hypervisor.bundle_runtime_readiness = readiness_then_saturate  # type: ignore[method-assign]

    result = service.invoke_endpoint(_invoke_command(endpoint_id))

    assert readiness_calls == 1
    assert result.readiness.ready is True
    assert result.result["runtime_id"] == "rt-1"
    assert len(plugin.invocations) == 1


def test_endpoint_invoke_maps_late_request_reservation_failure_to_execution_error() -> None:
    plugin = RecordingManagedPlugin()
    resources = ResourceOrchestrator(
        NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 0})
    )
    original_reserve = resources.reserve

    def reserve_then_fail_sync_request(
        reservation_id: str, cpu: float, ram_mb: int, vram_mb: int
    ):
        if reservation_id.startswith("request:sync:"):
            raise ValueError("insufficient resources")
        return original_reserve(reservation_id, cpu, ram_mb, vram_mb)

    resources.reserve = reserve_then_fail_sync_request  # type: ignore[method-assign]
    hypervisor = _hypervisor(
        bundle=_bundle(
            plugin_id=plugin.plugin_id,
            resource_profile=ResourceProfile(per_request_cpu=0.25),
        ),
        plugin=plugin,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ],
        resources=resources,
    )
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)

    with pytest.raises(EndpointExecutionError) as excinfo:
        service.invoke_endpoint(_invoke_command(endpoint_id))

    assert excinfo.value.code == "insufficient_resources"
    assert excinfo.value.readiness.ready is False
    assert excinfo.value.readiness.message == "insufficient resources"
    assert plugin.invocations == []


def test_endpoint_invoke_revalidates_drain_mode_after_cached_readiness() -> None:
    plugin = RecordingManagedPlugin()
    hypervisor = _hypervisor(
        plugin=plugin,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ],
    )
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)
    original_readiness = hypervisor.bundle_runtime_readiness

    def readiness_then_drain(bundle_id: str, request: TaskRequest) -> dict:
        readiness = original_readiness(bundle_id, request)
        hypervisor._set_bundle_state(
            "bundle-a",
            failure_streak=0,
            cooldown_until=None,
            cooldown_reason=None,
            drain_mode=True,
            drain_reason="operator maintenance",
        )
        return readiness

    hypervisor.bundle_runtime_readiness = readiness_then_drain  # type: ignore[method-assign]

    with pytest.raises(EndpointExecutionError) as excinfo:
        service.invoke_endpoint(_invoke_command(endpoint_id))

    assert excinfo.value.code == "bundle_draining"
    assert excinfo.value.readiness.ready is False
    assert excinfo.value.readiness.code == "bundle_draining"
    assert plugin.invocations == []


def test_endpoint_invoke_reports_revalidated_runtime_after_runtime_swap() -> None:
    plugin = RecordingManagedPlugin()
    hypervisor = _hypervisor(
        plugin=plugin,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ],
    )
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)
    original_readiness = hypervisor.bundle_runtime_readiness

    def readiness_then_swap_runtime(bundle_id: str, request: TaskRequest) -> dict:
        readiness = original_readiness(bundle_id, request)
        hypervisor.runtimes = [
            RuntimeHandle(
                "rt-2",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ]
        return readiness

    hypervisor.bundle_runtime_readiness = readiness_then_swap_runtime  # type: ignore[method-assign]

    result = service.invoke_endpoint(_invoke_command(endpoint_id))

    assert plugin.invocations == [
        {
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {"tenant": "demo"},
            "runtime_id": "rt-2",
        }
    ]
    assert result.result["runtime_id"] == "rt-2"
    assert result.runtime_id == "rt-2"
    assert result.readiness.runtime_id == "rt-2"


def test_endpoint_invoke_fails_when_swapped_runtime_lowers_concurrency_limit() -> None:
    plugin = RuntimeSpecificConcurrencyRecordingPlugin()
    hypervisor = _hypervisor(
        bundle=_bundle(
            plugin_id=plugin.plugin_id,
            resource_profile=ResourceProfile(per_request_cpu=0.25),
        ).model_copy(update={"max_parallel_requests": 3}),
        plugin=plugin,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ],
    )
    active_task = hypervisor.queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "busy"})
    )
    hypervisor._selected_bundles[active_task.task_id] = "bundle-a"
    hypervisor.queue.transition_status(active_task.task_id, "running")
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)
    original_readiness = hypervisor.bundle_runtime_readiness

    def readiness_then_swap_runtime(bundle_id: str, request: TaskRequest) -> dict:
        readiness = original_readiness(bundle_id, request)
        hypervisor.runtimes = [
            RuntimeHandle(
                "rt-2",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ]
        return readiness

    hypervisor.bundle_runtime_readiness = readiness_then_swap_runtime  # type: ignore[method-assign]

    with pytest.raises(EndpointExecutionError) as excinfo:
        service.invoke_endpoint(_invoke_command(endpoint_id))

    assert excinfo.value.code == "concurrency_limit"
    assert excinfo.value.readiness.ready is False
    assert excinfo.value.readiness.code == "concurrency_limit"
    assert excinfo.value.readiness.runtime_id == "rt-2"
    assert plugin.invocations == []


def test_endpoint_readiness_rejects_mismatched_command_endpoint_id() -> None:
    hypervisor = _hypervisor(
        plugin=RecordingManagedPlugin(),
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ],
    )
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)

    with pytest.raises(EndpointStateError, match="does not match"):
        service.endpoint_readiness(endpoint_id, _invoke_command("other-endpoint"))


def test_endpoint_service_readiness_and_invoke_agree_on_request_resource_fit() -> None:
    plugin = RecordingManagedPlugin()
    resources = ResourceOrchestrator(
        NodeCapacity(cpu_cores=0.5, ram_mb=2048, vram_mb={"gpu0": 0})
    )
    reserve_calls: list[tuple[str, float, int, int]] = []
    original_reserve = resources.reserve

    def tracking_reserve(
        reservation_id: str, cpu: float, ram_mb: int, vram_mb: int
    ):
        reserve_calls.append((reservation_id, cpu, ram_mb, vram_mb))
        return original_reserve(reservation_id, cpu, ram_mb, vram_mb)

    resources.reserve = tracking_reserve  # type: ignore[method-assign]
    hypervisor = _hypervisor(
        bundle=_bundle(
            plugin_id=plugin.plugin_id,
            resource_profile=ResourceProfile(
                per_request_cpu=1.0,
                per_request_ram_mb=128,
            ),
        ),
        plugin=plugin,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ],
        resources=resources,
    )
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)
    command = _invoke_command(endpoint_id)

    readiness = service.endpoint_readiness(endpoint_id, command)

    assert readiness.ready is False
    assert readiness.code == "insufficient_resources"
    assert readiness.runtime_id == "rt-1"
    with pytest.raises(EndpointExecutionError) as excinfo:
        service.invoke_endpoint(command)
    assert excinfo.value.code == "insufficient_resources"
    assert excinfo.value.readiness.code == readiness.code
    assert excinfo.value.readiness.message == readiness.message
    assert reserve_calls == []
    assert plugin.invocations == []


@pytest.mark.parametrize(
    ("bundle", "plugin", "runtimes", "expected_code"),
    [
        (_bundle(enabled=False), RecordingManagedPlugin(), [], "bundle_disabled"),
        (_bundle(), RecordingManagedPlugin(), [], "runtime_unavailable"),
        (
            _bundle(),
            RecordingManagedPlugin(),
            [
                RuntimeHandle(
                    "rt-1",
                    ["python", "-m", "http.server", "0"],
                    "running",
                    "bundle-a",
                )
            ],
            "bundle_draining",
        ),
        (
            _bundle(),
            RecordingManagedPlugin(),
            [
                RuntimeHandle(
                    "rt-1",
                    ["python", "-m", "http.server", "0"],
                    "running",
                    "bundle-a",
                )
            ],
            "provider_cooldown",
        ),
        (
            _bundle(plugin_id="fake-unhealthy"),
            UnhealthyManagedPlugin(),
            [
                RuntimeHandle(
                    "rt-1",
                    ["python", "-m", "http.server", "0"],
                    "running",
                    "bundle-a",
                )
            ],
            "runtime_unhealthy",
        ),
    ],
)
def test_runtime_adapter_reports_deterministic_readiness_codes(
    bundle: BundleConfig,
    plugin: FakeManagedPlugin,
    runtimes: list[RuntimeHandle],
    expected_code: str,
) -> None:
    hypervisor = _hypervisor(bundle=bundle, plugin=plugin, runtimes=runtimes)
    if expected_code == "bundle_draining":
        hypervisor._set_bundle_state(
            "bundle-a",
            failure_streak=0,
            cooldown_until=None,
            cooldown_reason=None,
            drain_mode=True,
            drain_reason="operator maintenance",
        )
    elif expected_code == "provider_cooldown":
        hypervisor._set_bundle_state(
            "bundle-a",
            failure_streak=1,
            cooldown_until=9999999999.0,
            cooldown_reason="provider offline",
            drain_mode=False,
            drain_reason=None,
        )

    readiness = EndpointRuntimeAdapter(hypervisor).endpoint_readiness(
        _endpoint_service(hypervisor).create_endpoint(
            CreateEndpointCommand(
                owner_wallet="wallet-1",
                bundle_id="bundle-a",
                bundle_hash="bundle-hash-a",
                display_name="Bundle A",
                model_class="llm.text",
                capabilities=["llm.text"],
            )
        ).endpoint,
        _invoke_command("endpoint-placeholder"),
    )

    assert readiness.ready is False
    assert readiness.code == expected_code


def test_sync_endpoint_invoke_persists_after_never_warm_runtime_cleanup(tmp_path) -> None:
    state_store = FileStateStore(tmp_path / "state.json")
    plugin = RecordingManagedPlugin()
    hypervisor = _hypervisor(
        bundle=_bundle(plugin_id=plugin.plugin_id, warm_policy="never"),
        plugin=plugin,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ],
        state_store=state_store,
    )
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)

    result = service.invoke_endpoint(_invoke_command(endpoint_id))

    assert result.result["runtime_id"] == "rt-1"
    assert hypervisor.list_runtimes() == []
    assert state_store.load().runtimes == []


def test_sync_endpoint_invoke_reconsiders_queued_legacy_work_after_cleanup() -> None:
    plugin = RecordingManagedPlugin()
    process_manager = ProviderProcessManager()
    process_manager.restore_runtime(
        RuntimeHandle(
            "rt-1",
            ["python", "-m", "http.server", "0"],
            "running",
            "bundle-a",
        )
    )
    hypervisor = _hypervisor(
        bundle=_bundle(plugin_id=plugin.plugin_id, warm_policy="never"),
        plugin=plugin,
        runtimes=[],
    )
    hypervisor.runtimes = process_manager
    legacy_task = QueuedTask(
        priority=0,
        enqueue_index=0,
        created_at="2026-06-30T00:00:00+00:00",
        task_id="legacy-queued",
        request=TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "queued"},
        ),
        status="queued",
    )
    hypervisor.queue.restore([legacy_task])
    hypervisor._selected_bundles[legacy_task.task_id] = "bundle-a"
    service = _endpoint_service(hypervisor)
    endpoint_id = _create_active_endpoint(service)

    service.invoke_endpoint(_invoke_command(endpoint_id))

    assert hypervisor.get_task(legacy_task.task_id).status == "completed"
    assert hypervisor.task_result(legacy_task.task_id) == {
        "ok": True,
        "echo": {"prompt": "queued"},
        "runtime_id": "rt-2",
    }
    assert hypervisor.list_runtimes() == []
