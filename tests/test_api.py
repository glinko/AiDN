from dataclasses import replace
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from aidn_hypervisor.bundle_registry import FileBundleRegistry
from aidn_hypervisor.domain.models import (
    AllocationRequest,
    BundleConfig,
    NodeCapacity,
    ResourceProfile,
    TaskRequest,
)
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.models import CreateEndpointCommand, UpdateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.main import build_app
from aidn_hypervisor.model_store import FileModelStore
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager, RuntimeHandle
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.registry_models import RegistryDiscoveryQuery, RegistryNodeAdvertisement
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.remote_endpoints.service import RemoteEndpointService
from aidn_hypervisor.remote_endpoints.store import RemoteEndpointStore
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore


def _bundle(
    bundle_id: str,
    workload_type: str,
    *,
    resource_profile: ResourceProfile | None = None,
    priority_class: int = 50,
    enabled: bool = True,
    endpoint: str | None = None,
) -> BundleConfig:
    return BundleConfig(
        bundle_id=bundle_id,
        plugin_id="fake-managed",
        provider_type="fake",
        workload_type=workload_type,
        model_id=f"{bundle_id}-model",
        launch_mode="managed_process",
        endpoint=endpoint,
        device_affinity="cpu",
        resource_profile=resource_profile or ResourceProfile(),
        warm_policy="auto",
        priority_class=priority_class,
        enabled=enabled,
    )


def _service(
    *,
    with_runtime: bool = True,
    use_process_manager: bool = False,
    capacity: NodeCapacity | None = None,
    reserve_runtime: bool = True,
    whisper_profile: ResourceProfile | None = None,
    bundle_registry=None,
    whisper_endpoint: str | None = None,
    model_store=None,
) -> HypervisorService:
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())

    resources = ResourceOrchestrator(
        capacity
        or NodeCapacity(
            cpu_cores=8.0,
            ram_mb=16384,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 8192},
        )
    )
    if reserve_runtime:
        resources.reserve("runtime-whisper-a", cpu=1.5, ram_mb=2048, vram_mb=1024)

    runtimes = (
        ProviderProcessManager()
        if use_process_manager
        else [
            RuntimeHandle(
                runtime_id="rt-1",
                bundle_id="whisper-a",
                command=["python", "-m", "http.server", "0"],
                status="running",
                health_status="healthy",
            )
        ]
        if with_runtime
        else []
    )

    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=resources,
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=whisper_profile,
                priority_class=80,
                endpoint=whisper_endpoint,
            ),
            _bundle("text-a", "llm_text", priority_class=60),
            _bundle("disabled-text", "llm_text", enabled=False),
        ],
        plugins=plugins,
        runtimes=runtimes,
        bundle_registry=bundle_registry,
        model_store=model_store,
    )


class CooldownApiPlugin(FakeManagedPlugin):
    plugin_id = "fake-cooldown-api"

    def __init__(self) -> None:
        self.invoke_attempts = 0

    def retry_policy(self) -> dict:
        return {
            "invoke": {
                "max_attempts": 3,
                "backoff_seconds": 0.0,
                "retry_exceptions": (RuntimeError,),
            }
        }

    def circuit_breaker_policy(self) -> dict:
        return {"failure_threshold": 1, "cooldown_seconds": 60.0}

    def invoke(self, task, runtime_handle) -> dict:
        self.invoke_attempts += 1
        raise RuntimeError("connection refused")


def test_submit_task_endpoint_returns_queued_task_and_selected_bundle() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/tasks",
        json={"task_type": "audio.transcribe", "payload": {"audio_ref": "clip.wav"}},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["task_type"] == "audio.transcribe"
    assert response.json()["priority"] == 50
    assert response.json()["bundle_id"] == "whisper-a"
    assert response.json()["task_id"]


def test_submit_task_endpoint_uses_allocation_bundle_when_allocation_id_is_provided() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("preferred-text", "llm_text", priority_class=100),
            _bundle("leased-text", "llm_text", priority_class=10, endpoint="http://127.0.0.1:8080"),
        ],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )
    service.plugins.register(FakeManagedPlugin())
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="leased-text",
        )
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {"allocation_id": allocation["allocation_id"]},
        },
    )

    assert response.status_code == 202
    assert response.json()["bundle_id"] == "leased-text"


def test_submit_task_endpoint_executes_via_proxy_endpoint_when_endpoint_id_is_provided() -> None:
    class StubRemoteHypervisorTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict | None]] = []

        def request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
            self.calls.append((method, url, payload))
            if method == "POST" and url == "http://remote-hv/tasks":
                return {
                    "task_id": "remote-task-1",
                    "status": "queued",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                }
            if method == "GET" and url == "http://remote-hv/tasks/remote-task-1":
                return {
                    "task_id": "remote-task-1",
                    "status": "completed",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                    "result": {
                        "ok": True,
                        "task_type": "llm_text.generate",
                        "output_text": "hello from remote",
                    },
                }
            raise AssertionError(f"unexpected proxy request: {method} {url}")

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("text-a", "llm_text", priority_class=100)],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )
    service.plugins.register(FakeManagedPlugin())
    endpoint_service = EndpointService(EndpointStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="http://remote-hv",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    service.remote_transport = StubRemoteHypervisorTransport()
    service.proxy_poll_attempts = 1
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {"endpoint_id": created.endpoint.endpoint_id},
        },
    )

    assert response.status_code == 202
    assert response.json()["bundle_id"] == "text-a"
    detail = client.get(response.json()["task_id"] and f"/tasks/{response.json()['task_id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["result"]["output_text"] == "hello from remote"
    assert detail.json()["result"]["proxy"]["remote_endpoint_id"] == "ep-remote"


def test_submit_task_endpoint_rejects_paid_endpoint_request_without_session() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="whisper-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post(
        "/tasks",
        json={
            "task_type": "audio.transcribe",
            "payload": {"audio_ref": "clip.wav"},
            "constraints": {"endpoint_id": created.endpoint.endpoint_id},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        f"Active session required for paid endpoint: {created.endpoint.endpoint_id}"
    )


def test_submit_task_endpoint_updates_session_activity_for_paid_endpoint_session() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    session_service = SessionService(SessionStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="whisper-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 1,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    session = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    ).session
    session_service.store.save_session(
        session.model_copy(
            update={
                "last_activity_at": "2026-06-30T00:00:00+00:00",
                "idle_deadline_at": "2026-06-30T00:10:00+00:00",
            }
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )
    )

    response = client.post(
        "/tasks",
        json={
            "task_type": "audio.transcribe",
            "payload": {"audio_ref": "clip.wav"},
            "constraints": {
                "endpoint_id": created.endpoint.endpoint_id,
                "session_id": session.session_id,
            },
        },
    )

    refreshed = session_service.get_session(session.session_id).session

    assert response.status_code == 202
    assert refreshed.last_activity_at != "2026-06-30T00:00:00+00:00"
    assert refreshed.idle_deadline_at != "2026-06-30T00:10:00+00:00"


def test_get_task_endpoint_exposes_proxy_trace_for_proxy_execution() -> None:
    class StubRemoteHypervisorTransport:
        def request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
            if method == "POST" and url == "http://remote-hv/tasks":
                return {
                    "task_id": "remote-task-1",
                    "status": "queued",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                }
            if method == "GET" and url == "http://remote-hv/tasks/remote-task-1":
                return {
                    "task_id": "remote-task-1",
                    "status": "completed",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                    "result": {
                        "ok": True,
                        "output_text": "hello from remote",
                    },
                }
            raise AssertionError(f"unexpected proxy request: {method} {url}")

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("text-a", "llm_text", priority_class=100)],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )
    service.plugins.register(FakeManagedPlugin())
    endpoint_service = EndpointService(EndpointStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="http://remote-hv",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    service.remote_transport = StubRemoteHypervisorTransport()
    service.proxy_poll_attempts = 1
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {"endpoint_id": created.endpoint.endpoint_id},
        },
    )

    assert response.status_code == 202
    detail = client.get(f"/tasks/{response.json()['task_id']}")

    assert detail.status_code == 200
    assert detail.json()["proxy_trace"]["strategy"] == "proxy"
    assert detail.json()["proxy_trace"]["status"] == "completed"
    assert detail.json()["proxy_trace"]["remote_task_id"] == "remote-task-1"
    assert detail.json()["proxy_trace"]["remote_endpoint_id"] == "ep-remote"
    assert detail.json()["proxy_trace"]["remote_node_id"] == "node-remote"
    assert detail.json()["proxy_trace"]["source_base_url"] == "http://remote-hv"
    assert detail.json()["proxy_trace"]["dispatched_at"]


def test_submit_task_endpoint_rejects_released_allocation_id() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("leased-text", "llm_text", endpoint="http://127.0.0.1:8080")],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )
    service.plugins.register(FakeManagedPlugin())
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="leased-text",
        )
    )
    service.release_allocation(allocation["allocation_id"])
    client = TestClient(build_app(service=service))

    response = client.post(
        "/tasks",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {"allocation_id": allocation["allocation_id"]},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == f"Allocation is not active: {allocation['allocation_id']}"


def test_queue_endpoint_returns_enqueued_tasks_with_selected_bundles() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=1.0,
            ram_mb=1024,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 512},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=1.0,
            steady_cpu=0.5,
            per_request_cpu=0.5,
        ),
    )
    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    client = TestClient(build_app(service=service))

    response = client.get("/queue")

    assert response.status_code == 200
    assert response.json() == [
        {
            "task_id": task.task_id,
            "status": "queued",
            "priority": 50,
            "task_type": "audio.transcribe",
            "bundle_id": "whisper-a",
        }
    ]


def test_task_detail_endpoint_returns_submitted_task_status() -> None:
    service = _service()
    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    client = TestClient(build_app(service=service))
    history = [event.model_dump(mode="json") for event in service.task_history(task.task_id)]

    response = client.get(f"/tasks/{task.task_id}")

    assert response.status_code == 200
    assert response.json() == {
        "task_id": task.task_id,
        "status": "completed",
        "priority": 50,
        "task_type": "audio.transcribe",
        "bundle_id": "whisper-a",
        "result": {"ok": True, "task_type": "audio.transcribe"},
        "recovery_reason": None,
        "history": [
            {
                "timestamp": history[0]["timestamp"],
                "event_type": "task.submitted",
                "message": "task accepted into queue",
                "task_id": task.task_id,
                "bundle_id": "whisper-a",
                "runtime_id": None,
                "details": {
                    "task_type": "audio.transcribe",
                    "mode": "auto",
                },
            },
            {
                "timestamp": history[1]["timestamp"],
                "event_type": "admission.selected",
                "message": "task selected for admission attempt",
                "task_id": task.task_id,
                "bundle_id": "whisper-a",
                "runtime_id": None,
                "details": {
                    "base_priority": 50,
                    "aging_bonus": 0,
                    "effective_priority": 50,
                    "fair_share_round": 0,
                    "admission_rank": 1,
                    "selection_reason": "only_remaining_bundle",
                },
            },
            {
                "timestamp": history[2]["timestamp"],
                "event_type": "task.completed",
                "message": "task completed successfully",
                "task_id": task.task_id,
                "bundle_id": "whisper-a",
                "runtime_id": "rt-1",
                "details": {},
            },
        ],
    }


def test_cancel_task_endpoint_marks_queued_task_cancelled() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=1.0,
            ram_mb=1024,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 512},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=1.0,
            steady_cpu=0.5,
            per_request_cpu=0.5,
        ),
    )
    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    client = TestClient(build_app(service=service))

    response = client.post(f"/tasks/{task.task_id}/cancel")

    assert response.status_code == 200
    assert response.json() == {
        "task_id": task.task_id,
        "status": "cancelled",
        "priority": 50,
        "task_type": "audio.transcribe",
        "bundle_id": "whisper-a",
        "result": None,
    }

    detail_response = client.get(f"/tasks/{task.task_id}")

    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "cancelled"


def test_queue_endpoint_omits_cancelled_tasks() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=1.0,
            ram_mb=1024,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 512},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=1.0,
            steady_cpu=0.5,
            per_request_cpu=0.5,
        ),
    )
    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    client = TestClient(build_app(service=service))

    client.post(f"/tasks/{task.task_id}/cancel")
    response = client.get("/queue")

    assert response.status_code == 200
    assert response.json() == []


def test_cancel_task_endpoint_rejects_non_cancellable_tasks() -> None:
    service = _service()
    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    service.queue.transition_status(task.task_id, "running")
    client = TestClient(build_app(service=service))

    response = client.post(f"/tasks/{task.task_id}/cancel")

    assert response.status_code == 409
    assert "not cancellable" in response.json()["detail"]


def test_bundles_endpoint_returns_bundle_definitions_and_status() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/bundles")

    assert response.status_code == 200
    assert response.json() == [
        {
            "bundle_id": "whisper-a",
            "plugin_id": "fake-managed",
            "provider_type": "fake",
            "workload_type": "speech_to_text",
            "model_id": "whisper-a-model",
            "launch_mode": "managed_process",
            "enabled": True,
            "priority_class": 80,
            "status": "running",
        },
        {
            "bundle_id": "text-a",
            "plugin_id": "fake-managed",
            "provider_type": "fake",
            "workload_type": "llm_text",
            "model_id": "text-a-model",
            "launch_mode": "managed_process",
            "enabled": True,
            "priority_class": 60,
            "status": "stopped",
        },
        {
            "bundle_id": "disabled-text",
            "plugin_id": "fake-managed",
            "provider_type": "fake",
            "workload_type": "llm_text",
            "model_id": "disabled-text-model",
            "launch_mode": "managed_process",
            "enabled": False,
            "priority_class": 50,
            "status": "disabled",
        },
    ]


def test_start_bundle_endpoint_launches_runtime_and_updates_bundle_status() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    client = TestClient(build_app(service=service))

    response = client.post("/bundles/whisper-a/start")

    assert response.status_code == 200
    assert response.json() == {
        "runtime_id": "rt-1",
        "bundle_id": "whisper-a",
        "command": ["python", "-m", "http.server", "0"],
        "status": "starting",
    }

    bundles_response = client.get("/bundles")

    assert bundles_response.status_code == 200
    assert bundles_response.json()[0]["status"] == "starting"


def test_start_bundle_endpoint_rejects_disabled_bundles() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    client = TestClient(build_app(service=service))

    response = client.post("/bundles/disabled-text/start")

    assert response.status_code == 409
    assert "disabled" in response.json()["detail"]


def test_stop_bundle_endpoint_removes_active_runtime() -> None:
    service = _service(with_runtime=True)
    client = TestClient(build_app(service=service))

    response = client.post("/bundles/whisper-a/stop")

    assert response.status_code == 200
    assert response.json() == {
        "bundle_id": "whisper-a",
        "status": "stopped",
    }

    runtimes_response = client.get("/runtimes")
    bundles_response = client.get("/bundles")

    assert runtimes_response.status_code == 200
    assert runtimes_response.json() == []
    assert bundles_response.status_code == 200
    assert bundles_response.json()[0]["status"] == "stopped"


def test_runtimes_endpoint_returns_runtime_handles() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/runtimes")

    assert response.status_code == 200
    assert response.json() == [
        {
            "runtime_id": "rt-1",
            "bundle_id": "whisper-a",
            "command": ["python", "-m", "http.server", "0"],
            "status": "running",
            "health_status": "healthy",
            "active_task_count": 0,
            "failure_streak": 0,
            "cooldown_until": None,
            "cooldown_reason": None,
            "drain_mode": False,
            "drain_reason": None,
        }
    ]


def test_runtime_detail_endpoint_returns_runtime_with_history() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    runtime = service.start_bundle("whisper-a")
    client = TestClient(build_app(service=service))

    response = client.get(f"/runtimes/{runtime.runtime_id}")

    assert response.status_code == 200
    assert response.json() == {
        "runtime_id": "rt-1",
        "bundle_id": "whisper-a",
        "command": ["python", "-m", "http.server", "0"],
        "status": "starting",
        "health_status": "unknown",
        "active_task_count": 0,
        "failure_streak": 0,
        "cooldown_until": None,
        "cooldown_reason": None,
        "drain_mode": False,
        "drain_reason": None,
        "history": [
            {
                "timestamp": service.event_journal(limit=1)[0].timestamp,
                "event_type": "runtime.started",
                "message": "runtime started",
                "task_id": None,
                "bundle_id": "whisper-a",
                "runtime_id": "rt-1",
                "details": {},
            }
        ],
    }


def test_runtime_detail_endpoint_returns_404_for_unknown_runtime() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/runtimes/rt-missing")

    assert response.status_code == 404
    assert "Unknown runtime" in response.json()["detail"]


def test_resources_endpoint_returns_total_reserved_and_free_capacity() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/resources")

    assert response.status_code == 200
    assert response.json() == {
        "total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192},
        "reserved": {"cpu": 1.5, "ram_mb": 2048, "vram_mb": 1024},
        "free": {"cpu": 6.5, "ram_mb": 14336, "vram_mb": 7168},
    }


def test_plugins_endpoint_returns_installed_plugin_descriptions() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/plugins")

    assert response.status_code == 200
    assert response.json() == [
        {
            "plugin_id": "fake-managed",
            "workload_types": ["llm_text", "speech_to_text"],
            "usage_contract": {
                "supports_exact": False,
                "supports_estimated": False,
                "default_measurement_source": None,
                "fallback_measurement_source": None,
                "fallback_policy": "none",
                "missing_usage_behavior": "skip",
            },
        }
    ]


def test_queue_diagnostics_endpoint_reports_blocked_reason() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=1.0,
            ram_mb=1024,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 512},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=1.0,
            steady_cpu=0.5,
            per_request_cpu=0.5,
        ),
    )
    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    client = TestClient(build_app(service=service))

    response = client.get("/diagnostics/queue")

    assert response.status_code == 200
    assert response.json() == {
        "summary": {"queued": 1, "active": 0, "completed": 0, "failed": 0},
        "items": [
            {
                "task_id": task.task_id,
                "bundle_id": "whisper-a",
                "reason": "insufficient_resources",
            }
        ],
    }


def test_create_allocation_endpoint_returns_agent_lease() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        whisper_endpoint="http://127.0.0.1:9000",
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/allocations",
        json={"workload_type": "speech_to_text", "owner_id": "agent-a"},
    )

    assert response.status_code == 201
    assert response.json() == {
        "allocation_id": response.json()["allocation_id"],
        "owner_id": "agent-a",
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": "rt-1",
        "endpoint": "http://127.0.0.1:9000",
        "status": "active",
    }


def test_release_allocation_endpoint_marks_lease_released() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        whisper_endpoint="http://127.0.0.1:9000",
    )
    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text", owner_id="agent-a")
    )
    client = TestClient(build_app(service=service))

    response = client.delete(f"/allocations/{allocation['allocation_id']}")

    assert response.status_code == 200
    assert response.json() == {
        "allocation_id": allocation["allocation_id"],
        "owner_id": "agent-a",
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": "rt-1",
        "endpoint": "http://127.0.0.1:9000",
        "status": "released",
    }


def test_capabilities_endpoint_lists_enabled_bundle_inventory() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    client = TestClient(build_app(service=service))

    response = client.get("/capabilities")

    assert response.status_code == 200
    assert response.json() == [
        {
            "bundle_id": "whisper-a",
            "workload_type": "speech_to_text",
            "enabled": True,
            "status": "running",
            "endpoint": "http://127.0.0.1:9000",
        },
        {
            "bundle_id": "text-a",
            "workload_type": "llm_text",
            "enabled": True,
            "status": "stopped",
            "endpoint": None,
        },
        {
            "bundle_id": "disabled-text",
            "workload_type": "llm_text",
            "enabled": False,
            "status": "disabled",
            "endpoint": None,
        },
    ]


def test_operator_registry_advertisement_endpoint_returns_current_node_payload() -> None:
    service = _service(with_runtime=False, use_process_manager=True)
    service.node_id = "node-local"
    service.operator_id = "operator-a"
    service.base_url = "https://node.example"
    service.can_host_custom_model = False
    service.pricing = {
        "unit": "q_per_1kk_tokens",
        "input": 10,
        "output": 14,
        "fixed_request": None,
    }
    service.rating = {
        "score": 0.88,
        "tier": "B",
        "updated_at": "2026-06-19T18:20:00Z",
    }
    client = TestClient(build_app(service=service))

    response = client.get("/operators/registry/advertisement")

    assert response.status_code == 200
    assert response.json()["node_id"] == "node-local"
    assert response.json()["bundles"][0]["bundle_id"] == "whisper-a"


def test_operator_dashboard_fleet_endpoint_returns_aggregated_payload(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    client = TestClient(build_app(service=service))

    response = client.get("/operators/dashboard/fleet")

    assert response.status_code == 200
    assert response.json()["node"]["node_id"] == service.node_id
    assert response.json()["bundles"][0]["bundle_id"] == "whisper-a"
    assert response.json()["owner_wallet"]["configured"] is False
    assert response.json()["node_identity"]["node_id"] == service.node_id


def test_operator_dashboard_market_endpoint_marks_own_and_external_candidates() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(timezone.utc).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[
                {
                    "bundle_id": "remote-text",
                    "plugin_id": "fake-managed",
                    "workload_type": "llm_text",
                    "provider_type": "fake",
                    "model_id": "remote-text-model",
                    "endpoint": "https://remote.example/runtimes/remote-text",
                    "enabled": True,
                    "status": "ready",
                    "launch_mode": "attached_service",
                    "device_affinity": "cpu",
                    "max_parallel_requests": 2,
                    "supports_allocation": True,
                    "supports_queue": True,
                }
            ],
        )
    )
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/market")

    assert response.status_code == 200
    assert {item["origin"] for item in response.json()["candidates"]} == {
        "own",
        "external",
    }
    assert any(
        item["node_id"] == hypervisor.node_id and item["origin"] == "own"
        for item in response.json()["candidates"]
    )


def test_operator_dashboard_market_endpoint_includes_published_endpoint_counts() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    hypervisor.endpoint_publication_service = publication_service
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(timezone.utc).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[
                {
                    "bundle_id": "remote-text",
                    "plugin_id": "fake-managed",
                    "workload_type": "llm_text",
                    "provider_type": "fake",
                    "model_id": "remote-text-model",
                    "endpoint": "https://remote.example/runtimes/remote-text",
                    "enabled": True,
                    "status": "ready",
                    "launch_mode": "attached_service",
                    "device_affinity": "cpu",
                    "max_parallel_requests": 2,
                    "supports_allocation": True,
                    "supports_queue": True,
                }
            ],
            published_endpoints=[
                {
                    "endpoint_id": "ep-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                }
            ],
        )
    )
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    response = client.get("/operators/dashboard/market")

    assert response.status_code == 200
    own = next(
        item for item in response.json()["candidates"] if item["node_id"] == hypervisor.node_id
    )
    external = next(
        item for item in response.json()["candidates"] if item["node_id"] == "node-external"
    )
    assert own["published_endpoint_count"] == 1
    assert external["published_endpoint_count"] == 1


def test_operator_dashboard_remote_endpoints_route_returns_discovered_and_attached_items() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(timezone.utc).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[],
            published_endpoints=[
                {
                    "endpoint_id": "ep-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                }
            ],
        )
    )
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-external",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-b",
        pricing={"unit": "q_per_1kk_tokens", "input": 9, "output": 15, "fixed_request": 1},
        rating={"score": 0.97, "tier": "A", "updated_at": "2026-06-20T11:55:00Z"},
        alias="Preferred Remote",
    )
    client = TestClient(
        build_app(
            service=hypervisor,
            registry_service=registry,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.get("/operators/dashboard/remote-endpoints")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["attached"] == 1
    assert body["summary"]["discovered"] == 1
    assert body["attached"][0]["source_endpoint_id"] == "ep-remote"
    assert body["discovered"][0]["endpoint_id"] == "ep-remote"
    assert body["discovered"][0]["already_attached"] is True


def test_attach_remote_endpoint_route_persists_preferred_catalogue_entry() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(timezone.utc).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[],
            published_endpoints=[
                {
                    "endpoint_id": "ep-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                }
            ],
        )
    )
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    client = TestClient(
        build_app(
            service=hypervisor,
            registry_service=registry,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.post(
        "/operators/remote-endpoints/attach",
        json={"node_id": "node-external", "endpoint_id": "ep-remote", "alias": "Primary Remote"},
    )

    assert response.status_code == 201
    body = response.json()["data"]["remote_endpoint"]
    assert body["source_node_id"] == "node-external"
    assert body["source_endpoint_id"] == "ep-remote"
    assert body["alias"] == "Primary Remote"
    assert remote_endpoint_service.list_remote_endpoints()[0].source_endpoint_id == "ep-remote"


def test_attach_proxy_target_route_updates_endpoint_to_proxy_strategy() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    registry = RegistryService()
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-external",
            operator_id="operator-b",
            base_url="https://remote.example",
            heartbeat_at=datetime.now(timezone.utc).isoformat(),
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "free": {"cpu": 8.0, "ram_mb": 24576, "vram_mb": 8192},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": 9,
                "output": 15,
                "fixed_request": 1,
            },
            rating={
                "score": 0.97,
                "tier": "A",
                "updated_at": "2026-06-20T11:55:00Z",
            },
            bundles=[],
            published_endpoints=[
                {
                    "endpoint_id": "ep-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-external",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-06-30T00:00:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                }
            ],
        )
    )
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-external",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-b",
        pricing={"unit": "q_per_1kk_tokens", "input": 9, "output": 15, "fixed_request": 1},
        rating={"score": 0.97, "tier": "A", "updated_at": "2026-06-20T11:55:00Z"},
        alias="Primary Remote",
    )
    client = TestClient(
        build_app(
            service=service,
            registry_service=registry,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.post(
        f"/api/v1/endpoints/{created.endpoint.endpoint_id}/proxy-target",
        json={"remote_endpoint_id": attached.remote_endpoint_id},
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["endpoint"]["execution_strategy"] == "proxy"
    assert body["endpoint"]["proxy_target"]["remote_endpoint_id"] == attached.remote_endpoint_id
    assert body["snapshot"]["proxy_target"]["remote_endpoint_id"] == attached.remote_endpoint_id


def test_operator_dashboard_shell_route_returns_terminal_layout_markup() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "AiDN Operator Dashboard" in response.text
    assert 'data-screen="home"' in response.text
    assert 'data-screen="fleet"' in response.text
    assert 'data-screen="market"' in response.text
    assert 'data-role="command-rail"' in response.text
    assert 'data-role="metrics-strip"' in response.text
    assert 'data-role="workspace"' in response.text
    assert 'data-role="inspector"' in response.text
    assert 'data-role="operations-band"' in response.text


def test_operator_dashboard_shell_route_exposes_market_terminal_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Execution Market" in response.text
    assert "Selected Offer" in response.text
    assert "Request Queue" in response.text
    assert "Policy Controls" in response.text
    assert "Published Endpoints" in response.text
    assert "Trust Posture" in response.text


def test_operator_dashboard_shell_route_exposes_remote_endpoint_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="remote"' in response.text
    assert "/operators/dashboard/remote-endpoints" in response.text
    assert "Remote Endpoints" in response.text
    assert "Preferred Catalogue" in response.text
    assert "Attach Remote Endpoint" in response.text


def test_operator_dashboard_shell_route_exposes_wallet_drawer_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-wallet-open="rail"' in response.text
    assert 'data-wallet-open="ops"' in response.text
    assert 'data-wallet-close="true"' in response.text
    assert 'id="wallet-drawer"' in response.text
    assert "/operators/wallet/usage" in response.text
    assert "/operators/wallet/allocations" in response.text
    assert "/operators/wallet/allocations/disputes" in response.text
    assert "/operators/wallet/quote" in response.text


def test_operator_dashboard_shell_route_exposes_requests_workspace_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="requests"' in response.text
    assert "/operators/dashboard/requests" in response.text
    assert 'data-requests-policy="strategy"' in response.text
    assert "Spillover Preview" in response.text


def test_operator_dashboard_shell_route_exposes_endpoints_workspace_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert 'data-screen="endpoints"' in response.text
    assert "/operators/dashboard/endpoints" in response.text
    assert "/api/v1/endpoints" in response.text
    assert "Endpoint Control Plane" in response.text
    assert "Visibility & Access" in response.text
    assert "Validation Requested" in response.text
    assert "Configured Endpoints" in response.text
    assert "Selected Endpoint Actions" in response.text
    assert "Endpoint Policy Editor" in response.text
    assert "Endpoint Runtime Editor" in response.text
    assert "Configuration History" in response.text
    assert 'data-endpoint-action="publish"' in response.text
    assert 'data-endpoint-action="request-validation"' in response.text
    assert 'data-endpoint-action="save-policy"' in response.text
    assert 'data-endpoint-action="save-config"' in response.text
    assert 'data-endpoint-field="visibility"' in response.text
    assert 'data-endpoint-field="sharedWallets"' in response.text
    assert 'data-endpoint-field="validationEnabled"' in response.text
    assert 'data-endpoint-config-field="displayName"' in response.text
    assert 'data-endpoint-config-field="profileSummary"' in response.text
    assert 'data-endpoint-config-field="contextLength"' in response.text
    assert 'data-endpoint-config-field="temperature"' in response.text
    assert 'data-endpoint-config-field="maxTokens"' in response.text
    assert 'data-endpoint-config-field="timeout"' in response.text
    assert 'data-endpoint-config-field="streaming"' in response.text


def test_operator_dashboard_shell_route_exposes_proxy_attach_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Proxy Route Attachment" in response.text
    assert "Proxy Runtime Trace" in response.text
    assert "Proxy Route Summary" in response.text
    assert 'data-endpoint-proxy-field="remoteEndpointId"' in response.text
    assert 'data-endpoint-action="attach-proxy-target"' in response.text


def test_operator_dashboard_shell_route_exposes_wallet_and_endpoint_controls() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Wallet Ownership" in response.text
    assert "Node Identity" in response.text
    assert "First Endpoint" in response.text
    assert "/operators/wallet/bootstrap/create" in response.text
    assert "/operators/wallet/bootstrap/import" in response.text
    assert "/api/v1/endpoints" in response.text
    assert 'data-bootstrap-action="create-wallet"' in response.text
    assert 'data-bootstrap-action="import-wallet"' in response.text
    assert 'data-endpoint-action="create"' in response.text
    assert 'data-endpoint-action="publish"' in response.text
    assert 'data-endpoint-action="request-validation"' in response.text
    assert 'data-bootstrap-field="walletLabel"' in response.text
    assert 'data-bootstrap-field="endpointVisibility"' in response.text
    assert 'data-bootstrap-field="sharedWallets"' in response.text
    assert "/operators/endpoints/bootstrap" not in response.text


def test_operator_dashboard_home_market_preview_matches_market_candidates() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    registry = RegistryService()
    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    client = TestClient(build_app(service=hypervisor, registry_service=registry))

    home = client.get("/operators/dashboard/home")
    market = client.get("/operators/dashboard/market")

    assert home.status_code == 200
    assert market.status_code == 200
    assert home.json()["bootstrap"]["wallet_ready"] is False
    assert home.json()["bootstrap"]["node_identity"]["node_id"] == hypervisor.node_id
    assert home.json()["market_preview"]["candidate_count"] == len(
        market.json()["candidates"]
    )


def test_operator_dashboard_home_bootstrap_prefers_endpoint_service_state() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    client = TestClient(build_app(service=hypervisor, endpoint_service=endpoint_service))

    home = client.get("/operators/dashboard/home")

    assert home.status_code == 200
    assert home.json()["bootstrap"]["wallet_ready"] is True
    assert home.json()["bootstrap"]["endpoint_count"] == 1
    assert home.json()["bootstrap"]["items"][0]["endpoint_id"] == created.endpoint.endpoint_id
    assert home.json()["bootstrap"]["next_step"] == "Review your configured endpoint and publish it"


def test_owner_wallet_bootstrap_create_endpoint_returns_owner_state() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/wallet/bootstrap/create",
        json={"label": "Primary Wallet"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["wallet"]["configured"] is True
    assert body["wallet"]["label"] == "Primary Wallet"
    assert body["wallet"]["wallet_id"].startswith("wallet-")
    assert body["private_key"].startswith("sk-")


def test_operator_dashboard_requests_endpoint_returns_grouped_payload() -> None:
    service = _service(with_runtime=False, use_process_manager=True, reserve_runtime=False)
    service.queue.enqueue(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "queued.wav"})
    )
    client = TestClient(build_app(service=service))

    response = client.get("/operators/dashboard/requests")

    assert response.status_code == 200
    assert "summary" in response.json()
    assert "queue" in response.json()
    assert "policy" in response.json()
    assert "market_spillover_preview" in response.json()


def test_operator_dashboard_requests_endpoint_includes_proxy_trace_on_task_rows() -> None:
    class StubRemoteHypervisorTransport:
        def request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
            if method == "POST" and url == "http://remote-hv/tasks":
                return {
                    "task_id": "remote-task-1",
                    "status": "queued",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                }
            if method == "GET" and url == "http://remote-hv/tasks/remote-task-1":
                return {
                    "task_id": "remote-task-1",
                    "status": "completed",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                    "result": {
                        "ok": True,
                        "output_text": "hello from remote",
                    },
                }
            raise AssertionError(f"unexpected proxy request: {method} {url}")

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, gpu_devices=["gpu0"], vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("text-a", "llm_text", priority_class=100)],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )
    service.plugins.register(FakeManagedPlugin())
    endpoint_service = EndpointService(EndpointStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="http://remote-hv",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    service.endpoint_service = endpoint_service
    service.remote_endpoint_service = remote_endpoint_service
    service.remote_transport = StubRemoteHypervisorTransport()
    service.proxy_poll_attempts = 1
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"endpoint_id": created.endpoint.endpoint_id},
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.get("/operators/dashboard/requests")

    assert response.status_code == 200
    assert response.json()["recent"][0]["proxy_trace"]["remote_endpoint_id"] == "ep-remote"
    assert response.json()["recent"][0]["proxy_trace"]["remote_node_id"] == "node-remote"


def test_operator_dashboard_endpoints_endpoint_returns_endpoint_control_payload() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "shared",
                "discoverable": True,
                "accepts_external_requests": True,
                "shared_with_wallet_ids": ["wallet-a"],
            },
        )
    )
    endpoint_service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            validation={
                "enabled": True,
                "model_class_supported": True,
                "verification_status": "pending",
            },
        )
    )
    client = TestClient(build_app(service=service, endpoint_service=endpoint_service))

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 1
    assert response.json()["summary"]["validation_requested"] == 1
    assert response.json()["items"][0]["visibility"] == "shared"
    assert response.json()["items"][0]["shared_with_wallet_ids"] == ["wallet-a"]
    assert response.json()["policy"]["publish_requires_validation"] is False


def test_operator_dashboard_endpoints_payload_exposes_session_policy() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 2,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )
    client = TestClient(build_app(service=service, endpoint_service=endpoint_service))

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    assert response.json()["items"][0]["session"]["minimum_deposit"] == 10.0
    assert response.json()["items"][0]["session"]["max_concurrent_sessions"] == 2


def test_operator_dashboard_endpoints_endpoint_prefers_endpoint_service_payload_for_configured_endpoint() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            profile={"summary": "Speech endpoint tuned for transcription"},
            runtime={
                "context_length": 8192,
                "temperature": 0.2,
                "max_tokens": 1024,
                "timeout": 45,
                "streaming": True,
            },
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
                "discoverable": True,
            },
        )
    )
    endpoint_service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={
                "context_length": 16384,
                "temperature": 0.1,
                "max_tokens": 2048,
                "timeout": 60,
                "streaming": True,
            },
            validation={
                "enabled": True,
                "model_class_supported": True,
                "verification_status": "pending",
            },
        )
    )
    client = TestClient(build_app(service=service, endpoint_service=endpoint_service))

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    assert response.json()["summary"]["total"] == 1
    assert response.json()["summary"]["configured"] == 1
    assert response.json()["summary"]["published"] == 0
    assert response.json()["summary"]["shared"] == 1
    assert response.json()["summary"]["validation_requested"] == 1
    assert response.json()["items"][0]["endpoint_id"] == created.endpoint.endpoint_id
    assert response.json()["items"][0]["visibility"] == "shared"
    assert response.json()["items"][0]["shared_with_wallet_ids"] == ["wallet-a"]
    assert response.json()["items"][0]["profile"]["summary"] == "Speech endpoint tuned for transcription"
    assert response.json()["items"][0]["runtime"]["context_length"] == 16384
    assert response.json()["items"][0]["runtime"]["temperature"] == 0.1
    assert response.json()["items"][0]["runtime"]["max_tokens"] == 2048
    assert response.json()["items"][0]["runtime"]["timeout"] == 60
    assert response.json()["items"][0]["runtime"]["streaming"] is True
    assert len(response.json()["items"][0]["configuration_snapshots"]) == 2
    assert (
        response.json()["items"][0]["configuration_snapshots"][0]["configuration_hash"]
        == created.endpoint.configuration_hash
    )
    assert (
        response.json()["items"][0]["configuration_snapshots"][1]["runtime"]["context_length"]
        == 16384
    )
    assert (
        response.json()["items"][0]["configuration_snapshots"][1]["runtime"]["timeout"]
        == 60
    )
    assert response.json()["items"][0]["publication_status"] == "configured"
    assert response.json()["items"][0]["current_publication"] is None


def test_operator_dashboard_endpoints_payload_exposes_proxy_strategy() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    attached = remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-external",
        source_endpoint_id="ep-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-b",
        pricing={"unit": "q_per_1kk_tokens", "input": 9, "output": 15},
        rating={"score": 0.97, "tier": "A", "updated_at": "2026-06-20T11:55:00Z"},
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            remote_endpoint_service=remote_endpoint_service,
        )
    )

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["execution_strategy"] == "proxy"
    assert item["proxy_target"]["remote_endpoint_id"] == attached.remote_endpoint_id


def test_publish_configuration_endpoint_returns_signed_record() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.post(
        f"/api/v1/endpoints/{created.endpoint.endpoint_id}/publish-configuration"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["publication"]["endpoint_id"] == created.endpoint.endpoint_id
    assert (
        body["data"]["publication"]["owner_wallet"]
        == service.owner_wallet_state()["wallet_id"]
    )
    assert body["data"]["publication"]["wallet_signature"]


def test_endpoint_proof_returns_live_configuration_hash() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
                "discoverable": True,
            },
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.get(f"/api/v1/endpoints/{created.endpoint.endpoint_id}/proof")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["proof"]["endpoint_id"] == created.endpoint.endpoint_id
    assert body["data"]["proof"]["node_id"] == service.node_id
    assert (
        body["data"]["proof"]["configuration_hash"]
        == created.endpoint.configuration_hash
    )
    assert body["data"]["proof"]["publication"]["visibility"] == "shared"


def test_revoke_publication_endpoint_returns_revoked_record() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.post(
        f"/api/v1/endpoints/{created.endpoint.endpoint_id}/revoke-publication"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["publication"]["endpoint_id"] == created.endpoint.endpoint_id
    assert body["data"]["publication"]["status"] == "revoked"


def test_wallet_endpoint_publications_export_returns_publication_journal() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.get("/operators/wallet/endpoints/publications/export")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["endpoint_id"] == created.endpoint.endpoint_id
    assert body["items"][0]["wallet_signature"]


def test_registry_advertisement_includes_current_published_configuration_hash() -> None:
    hypervisor = _service(whisper_endpoint="http://127.0.0.1:9000")
    hypervisor.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
                "discoverable": True,
                "accepts_external_requests": True,
            },
        )
    )
    publication = publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=hypervisor.owner_wallet_state()["wallet_id"],
        node_id=hypervisor.node_id,
        wallet_private_key=hypervisor.owner_wallet_private_key(),
    )
    hypervisor.endpoint_publication_service = publication_service
    client = TestClient(
        build_app(
            service=hypervisor,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.get("/operators/registry/advertisement")

    assert response.status_code == 200
    body = response.json()
    assert body["published_endpoints"][0]["endpoint_id"] == created.endpoint.endpoint_id
    assert (
        body["published_endpoints"][0]["current_configuration_hash"]
        == publication.configuration_hash
    )
    assert (
        body["published_endpoints"][0]["current_publication_id"]
        == publication.publication_id
    )


def test_operator_dashboard_endpoints_payload_reports_publication_sync_state() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
                "discoverable": True,
            },
        )
    )
    publication = publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["local_configuration_hash"] == publication.configuration_hash
    assert item["published_configuration_hash"] == publication.configuration_hash
    assert item["publication_sync_status"] == "in_sync"


def test_operator_dashboard_endpoints_payload_requires_signed_publication_for_published_status() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
                "discoverable": True,
                "accepts_external_requests": True,
            },
        )
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=EndpointPublicationService(
                store=EndpointPublicationStore(),
                endpoint_service=endpoint_service,
            ),
        )
    )

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["endpoint_id"] == created.endpoint.endpoint_id
    assert item["publication_status"] == "configured"
    assert item["published_configuration_hash"] is None
    assert item["publication_sync_status"] == "never_published"


def test_operator_dashboard_shell_exposes_publication_sync_copy() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.get("/operators/dashboard")

    assert response.status_code == 200
    assert "Published Configuration" in response.text
    assert "Sync Status" in response.text
    assert 'data-endpoint-action="publish-configuration"' in response.text
    assert "/publish-configuration" in response.text
    assert 'data-endpoint-action="revoke-publication"' in response.text
    assert 'data-endpoint-action="view-signed-publication"' in response.text
    assert "Revoke Publication" in response.text
    assert "View Signed Publication" in response.text
    assert "Signed Publication" in response.text
    assert "Wallet Signature" in response.text
    assert "Publication Payload" in response.text


def test_operator_dashboard_endpoints_payload_includes_publication_history() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    publication_service.revoke_publication(created.endpoint.endpoint_id)
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert len(item["publication_history"]) == 1
    assert item["publication_history"][0]["status"] == "revoked"


def test_operator_dashboard_endpoints_payload_includes_current_publication_payload() -> None:
    service = _service(whisper_endpoint="http://127.0.0.1:9000")
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    publication = publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    client = TestClient(
        build_app(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=publication_service,
        )
    )

    response = client.get("/operators/dashboard/endpoints")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["current_publication"]["publication_id"] == publication.publication_id
    assert item["current_publication"]["wallet_signature"] == publication.wallet_signature


def test_operator_dashboard_requests_policy_endpoint_updates_service_state() -> None:
    client = TestClient(build_app(service=_service()))

    response = client.post(
        "/operators/dashboard/requests/policy",
        json={
            "allow_spillover": True,
            "dispatch_strategy": "balanced",
            "ready_endpoint_only": False,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "allow_spillover": True,
        "dispatch_strategy": "balanced",
        "ready_endpoint_only": False,
    }


def test_hypervisor_advertisement_can_be_registered_and_discovered() -> None:
    hypervisor = _service(
        with_runtime=False,
        use_process_manager=True,
        whisper_endpoint="http://127.0.0.1:9000",
    )
    hypervisor.node_id = "node-a"
    hypervisor.operator_id = "operator-a"
    hypervisor.base_url = "https://node-a.example"
    hypervisor.can_host_custom_model = True
    hypervisor.pricing = {
        "unit": "q_per_1kk_tokens",
        "input": 12,
        "output": 18,
        "fixed_request": None,
    }
    hypervisor.rating = {
        "score": 0.91,
        "tier": "A",
        "updated_at": "2026-06-19T18:25:00Z",
    }
    registry = RegistryService()

    registry.upsert_node(RegistryNodeAdvertisement(**hypervisor.node_advertisement()))
    result = registry.discover(
        RegistryDiscoveryQuery(
            workload_type="speech_to_text",
            can_host_custom_model=True,
        )
    )

    assert result["nodes"][0]["node_id"] == "node-a"
    assert result["nodes"][0]["bundles"][0]["bundle_id"] == "whisper-a"


def test_agent_capabilities_endpoint_reports_ready_bundle_catalog() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        whisper_endpoint="http://127.0.0.1:9000",
    )
    service.node_id = "node-a"
    service.operator_id = "operator-a"
    service.can_host_custom_model = True
    service.pricing = {
        "unit": "q_per_1kk_tokens",
        "input": 12,
        "output": 18,
        "fixed_request": 4,
    }
    client = TestClient(build_app(service=service))

    response = client.get(
        "/agent/capabilities",
        params={"owner_id": "agent-a", "workload_type": "speech_to_text"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "node": {
            "node_id": "node-a",
            "operator_id": "operator-a",
            "can_host_custom_model": True,
            "pricing": {
                "unit": "q_per_1kk_tokens",
                "input": 12,
                "output": 18,
                "fixed_request": 4,
            },
        },
        "resources": {
            "total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192},
            "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
            "free": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 8192},
        },
        "bundles": [
            {
                "bundle_id": "whisper-a",
                "plugin_id": "fake-managed",
                "provider_type": "fake",
                "model_id": "whisper-a-model",
                "workload_type": "speech_to_text",
                "enabled": True,
                "status": "stopped",
                "endpoint": "http://127.0.0.1:9000",
                "can_allocate_now": True,
                "can_queue": False,
                "allocation_mode": "active",
                "reason": None,
                "required": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
                "requires_runtime_start": True,
                "fit": {
                    "fits": True,
                    "cpu_shortfall": 0.0,
                    "ram_mb_shortfall": 0,
                    "vram_mb_shortfall": 0,
                },
            }
        ],
    }


def test_agent_capabilities_endpoint_reports_waiting_bundle_catalog() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=2.0,
            ram_mb=2048,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 1024},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=0.5,
            cold_start_ram_mb=512,
            steady_cpu=1.5,
            steady_ram_mb=1536,
        ),
        whisper_endpoint="http://127.0.0.1:9000",
    )
    service.resources.reserve("busy", cpu=2.0, ram_mb=2048, vram_mb=0)
    service.node_id = "node-a"
    service.operator_id = "operator-a"
    service.can_host_custom_model = True
    service.pricing = {
        "unit": "q_per_1kk_tokens",
        "input": 12,
        "output": 18,
        "fixed_request": 4,
    }
    client = TestClient(build_app(service=service))

    response = client.get(
        "/agent/capabilities",
        params={"owner_id": "agent-a", "workload_type": "speech_to_text"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "node": {
            "node_id": "node-a",
            "operator_id": "operator-a",
            "can_host_custom_model": True,
            "pricing": {
                "unit": "q_per_1kk_tokens",
                "input": 12,
                "output": 18,
                "fixed_request": 4,
            },
        },
        "resources": {
            "total": {"cpu": 2.0, "ram_mb": 2048, "vram_mb": 1024},
            "reserved": {"cpu": 2.0, "ram_mb": 2048, "vram_mb": 0},
            "free": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 1024},
        },
        "bundles": [
            {
                "bundle_id": "whisper-a",
                "plugin_id": "fake-managed",
                "provider_type": "fake",
                "model_id": "whisper-a-model",
                "workload_type": "speech_to_text",
                "enabled": True,
                "status": "stopped",
                "endpoint": "http://127.0.0.1:9000",
                "can_allocate_now": False,
                "can_queue": True,
                "allocation_mode": "wait",
                "reason": "insufficient_resources",
                "required": {"cpu": 2.0, "ram_mb": 2048, "vram_mb": 0},
                "requires_runtime_start": True,
                "fit": {
                    "fits": False,
                    "cpu_shortfall": 2.0,
                    "ram_mb_shortfall": 2048,
                    "vram_mb_shortfall": 0,
                },
            }
        ],
    }


def test_operator_model_install_endpoint_queues_install_job(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    client = TestClient(build_app(service=service))

    response = client.post(
        "/operators/models/install",
        json={
            "provider_type": "llama.cpp",
            "model_id": "phi-4-mini.gguf",
            "source_url": "https://example.invalid/models/phi-4-mini.gguf",
            "requested_by": "operator-a",
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["provider_type"] == "llama.cpp"
    assert response.json()["target_path"].endswith("llama.cpp\\phi-4-mini.gguf")


def test_operator_model_install_list_endpoint_returns_queued_jobs(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    service.request_model_install(
        provider_type="llama.cpp",
        model_id="phi-4-mini.gguf",
        source_url="https://example.invalid/models/phi-4-mini.gguf",
        requested_by="operator-a",
    )
    client = TestClient(build_app(service=service))

    response = client.get("/operators/models/install")

    assert response.status_code == 200
    assert response.json()[0]["status"] == "queued"
    assert response.json()[0]["model_id"] == "phi-4-mini.gguf"


def test_operator_model_install_process_endpoint_executes_queued_jobs(tmp_path) -> None:
    source_artifact = tmp_path / "phi-4-mini.gguf"
    source_artifact.write_text("model-bytes", encoding="utf-8")
    service = _service(model_store=FileModelStore(tmp_path / "models"))
    install = service.request_model_install(
        provider_type="fake-managed",
        model_id="phi-4-mini.gguf",
        source_url=source_artifact.as_uri(),
        requested_by="operator-a",
    )
    client = TestClient(build_app(service=service))

    response = client.post("/operators/models/install/process")

    assert response.status_code == 200
    assert response.json() == [
        {
            "install_id": install["install_id"],
            "provider_type": "fake-managed",
            "model_id": "phi-4-mini.gguf",
            "source_url": source_artifact.as_uri(),
            "target_path": install["target_path"],
            "requested_by": "operator-a",
            "status": "completed",
            "bundle_id": None,
            "last_error": None,
        }
    ]


def test_operator_register_bundle_from_install_endpoint_creates_bundle(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    install = service.request_model_install(
        provider_type="fake-managed",
        model_id="phi-4-mini.gguf",
        source_url="https://example.invalid/models/phi-4-mini.gguf",
        requested_by="operator-a",
    )
    service.mark_model_install_completed(install["install_id"])
    client = TestClient(build_app(service=service))

    response = client.post(
        f"/operators/models/{install['install_id']}/register-bundle",
        json={
            "bundle_id": "phi4-local",
            "workload_type": "llm_text",
            "endpoint": "http://127.0.0.1:8080",
        },
    )

    assert response.status_code == 200
    assert response.json()["bundle_id"] == "phi4-local"
    assert response.json()["plugin_id"] == "fake-managed"
    assert service.bundles[-1].model_id == install["target_path"]


def test_operator_can_install_register_and_expose_new_model_via_api(tmp_path) -> None:
    service = _service(model_store=FileModelStore(tmp_path))
    service.node_id = "node-a"
    service.operator_id = "operator-a"
    service.can_host_custom_model = True
    service.pricing = {
        "unit": "q_per_1kk_tokens",
        "input": 12,
        "output": 18,
        "fixed_request": 4,
    }
    source_artifact = tmp_path / "phi-4-mini.gguf"
    source_artifact.write_text("model-bytes", encoding="utf-8")
    client = TestClient(build_app(service=service))

    install_response = client.post(
        "/operators/models/install",
        json={
            "provider_type": "fake-managed",
            "model_id": "phi-4-mini.gguf",
            "source_url": source_artifact.as_uri(),
            "requested_by": "operator-a",
        },
    )
    install_id = install_response.json()["install_id"]

    complete_response = client.post("/operators/models/install/process")
    register_response = client.post(
        f"/operators/models/{install_id}/register-bundle",
        json={
            "bundle_id": "phi4-local",
            "workload_type": "llm_text",
            "endpoint": "http://127.0.0.1:8080",
        },
    )
    catalog_response = client.get(
        "/agent/capabilities",
        params={
            "owner_id": "agent-a",
            "workload_type": "llm_text",
            "bundle_id": "phi4-local",
        },
    )

    assert install_response.status_code == 202
    assert complete_response.status_code == 200
    assert register_response.status_code == 200
    assert catalog_response.status_code == 200
    assert complete_response.json()[0]["status"] == "completed"
    assert register_response.json()["bundle_id"] == "phi4-local"
    assert catalog_response.json()["node"]["can_host_custom_model"] is True
    assert catalog_response.json()["bundles"][0]["bundle_id"] == "phi4-local"
    assert catalog_response.json()["bundles"][0]["model_id"].endswith("phi-4-mini.gguf")


def test_create_allocation_endpoint_returns_409_when_resources_do_not_fit() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=1.0,
            ram_mb=1024,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 256},
        ),
        whisper_profile=ResourceProfile(
            steady_cpu=2.0,
            steady_ram_mb=2048,
            steady_vram_mb=512,
        ),
        whisper_endpoint="http://127.0.0.1:9000",
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/allocations",
        json={"workload_type": "speech_to_text", "owner_id": "agent-a"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "reason": "insufficient_resources",
        "retryable": True,
        "bundle_id": "whisper-a",
        "message": "insufficient resources for allocation runtime residency: whisper-a",
        "retry_after_seconds": 5,
        "next_attempt_at": response.json()["detail"]["next_attempt_at"],
    }


def test_create_allocation_endpoint_returns_pending_lease_for_wait_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=2.0,
            ram_mb=2048,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 1024},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=0.5,
            cold_start_ram_mb=512,
            steady_cpu=1.5,
            steady_ram_mb=1536,
        ),
        whisper_endpoint="http://127.0.0.1:9000",
    )
    service.resources.reserve("busy", cpu=2.0, ram_mb=2048, vram_mb=0)
    client = TestClient(build_app(service=service))

    response = client.post(
        "/allocations",
        json={
            "workload_type": "speech_to_text",
            "owner_id": "agent-a",
            "policy": "wait",
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "allocation_id": response.json()["allocation_id"],
        "owner_id": "agent-a",
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": None,
        "endpoint": None,
        "status": "pending",
        "reason": "insufficient_resources",
        "retry_after_seconds": 5,
        "next_attempt_at": datetime.fromtimestamp(
            current_time[0] + 5,
            timezone.utc,
        ).isoformat(),
    }


def test_reconcile_allocation_endpoint_activates_pending_wait_lease() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=2.0,
            ram_mb=2048,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 1024},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=0.5,
            cold_start_ram_mb=512,
            steady_cpu=1.0,
            steady_ram_mb=1024,
        ),
        whisper_endpoint="http://127.0.0.1:9000",
    )
    service.resources.reserve("busy", cpu=2.0, ram_mb=2048, vram_mb=0)
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="speech_to_text",
            owner_id="agent-a",
            policy="wait",
        )
    )
    client = TestClient(build_app(service=service))

    service.resources.release("busy")
    response = client.post(f"/allocations/{allocation['allocation_id']}/reconcile")

    assert response.status_code == 200
    assert response.json() == {
        "allocation_id": allocation["allocation_id"],
        "owner_id": "agent-a",
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": "rt-1",
        "endpoint": "http://127.0.0.1:9000",
        "status": "active",
    }


def test_create_allocation_endpoint_returns_409_when_owner_active_quota_is_exceeded() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        whisper_endpoint="http://127.0.0.1:9000",
    )
    service.max_active_allocations_per_owner = 1
    service.create_allocation(
        AllocationRequest(workload_type="speech_to_text", owner_id="agent-a")
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/allocations",
        json={"workload_type": "speech_to_text", "owner_id": "agent-a"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "owner_quota_exceeded"


def test_admission_diagnostics_endpoint_reports_selection_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: 1_781_827_800.0)
    service = _service(with_runtime=False, use_process_manager=True)
    older_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "older.wav"},
            priority=10,
            mode="manual",
            bundle_override="whisper-a",
        )
    )
    service._selected_bundles[older_task.task_id] = "whisper-a"
    newer_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "newer.wav"},
            priority=40,
            mode="manual",
            bundle_override="whisper-a",
        )
    )
    service._selected_bundles[newer_task.task_id] = "whisper-a"
    peer_task = service.queue.enqueue(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "peer"},
            priority=30,
            mode="manual",
            bundle_override="text-a",
        )
    )
    service._selected_bundles[peer_task.task_id] = "text-a"
    service.queue.restore(
        [
            replace(service.get_task(older_task.task_id), created_at="2026-06-19T00:00:00+00:00"),
            replace(service.get_task(newer_task.task_id), created_at="2026-06-19T00:09:00+00:00"),
            replace(service.get_task(peer_task.task_id), created_at="2026-06-19T00:09:00+00:00"),
        ]
    )
    client = TestClient(build_app(service=service))

    response = client.get("/diagnostics/admission")

    assert response.status_code == 200
    assert response.json() == {
        "summary": {"queued": 3, "active": 0, "completed": 0, "failed": 0},
        "items": [
            {
                "task_id": older_task.task_id,
                "bundle_id": "whisper-a",
                "base_priority": 10,
                "aging_bonus": 100,
                "effective_priority": 110,
                "fair_share_round": 0,
                "admission_rank": 1,
                "selection_reason": "highest_effective_priority",
            },
            {
                "task_id": peer_task.task_id,
                "bundle_id": "text-a",
                "base_priority": 30,
                "aging_bonus": 10,
                "effective_priority": 40,
                "fair_share_round": 0,
                "admission_rank": 2,
                "selection_reason": "lowest_dispatch_count",
            },
            {
                "task_id": newer_task.task_id,
                "bundle_id": "whisper-a",
                "base_priority": 40,
                "aging_bonus": 10,
                "effective_priority": 50,
                "fair_share_round": 1,
                "admission_rank": 3,
                "selection_reason": "only_remaining_bundle",
            },
        ],
    }


def test_process_pending_endpoint_returns_processing_summary() -> None:
    service = _service(
        with_runtime=False,
        use_process_manager=True,
        reserve_runtime=False,
        capacity=NodeCapacity(
            cpu_cores=1.0,
            ram_mb=1024,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 512},
        ),
        whisper_profile=ResourceProfile(
            cold_start_cpu=1.0,
            steady_cpu=0.5,
            per_request_cpu=0.5,
        ),
    )
    service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    client = TestClient(build_app(service=service))

    response = client.post("/operators/process-pending")

    assert response.status_code == 200
    assert response.json() == {
        "queued": 1,
        "active": 0,
        "completed": 0,
        "failed": 0,
    }


def test_operator_state_endpoint_returns_snapshot() -> None:
    service = _service()
    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    client = TestClient(build_app(service=service))

    response = client.get("/operators/state")

    assert response.status_code == 200
    assert response.json()["tasks"] == [
        {
            "task_id": task.task_id,
            "priority": 50,
            "enqueue_index": 0,
            "created_at": service.get_task(task.task_id).created_at,
            "status": "completed",
            "request": {
                "task_type": "audio.transcribe",
                "payload": {"audio_ref": "clip.wav"},
                "mode": "auto",
                "bundle_override": None,
                "priority": 50,
                "constraints": {},
            },
            "bundle_id": "whisper-a",
            "result": {"ok": True, "task_type": "audio.transcribe"},
            "recovery_reason": None,
        }
    ]


def test_operator_restore_state_endpoint_replaces_runtime_and_queue_state() -> None:
    service = _service(with_runtime=False, use_process_manager=True, reserve_runtime=False)
    client = TestClient(build_app(service=service))

    response = client.post(
        "/operators/state/restore",
        json={
            "tasks": [
                {
                    "task_id": "task-1",
                    "priority": 50,
                    "enqueue_index": 0,
                    "created_at": "2026-06-19T00:00:00+00:00",
                    "status": "queued",
                    "request": {
                        "task_type": "audio.transcribe",
                        "payload": {"audio_ref": "clip.wav"},
                        "mode": "auto",
                        "bundle_override": None,
                        "priority": 50,
                        "constraints": {},
                    },
                    "bundle_id": "whisper-a",
                    "result": None,
                }
            ],
            "runtimes": [
                {
                    "runtime_id": "rt-1",
                    "bundle_id": "whisper-a",
                    "command": ["python", "-m", "http.server", "0"],
                    "status": "running",
                    "health_status": "unknown",
                    "last_error": None,
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"queued": 1, "active": 0, "completed": 0, "failed": 0}
    assert service.get_task("task-1").status == "queued"
    assert service.list_runtimes()[0].runtime_id == "rt-1"


def test_operator_events_endpoint_returns_recent_journal_entries() -> None:
    service = _service()
    service.record_event(
        event_type="operator.note",
        message="first",
        details={"index": 1},
    )
    service.record_event(
        event_type="operator.note",
        message="second",
        details={"index": 2},
    )
    client = TestClient(build_app(service=service))

    response = client.get("/operators/events?limit=1")

    assert response.status_code == 200
    assert response.json() == [
        {
            "timestamp": service.event_journal(limit=1)[0].timestamp,
            "event_type": "operator.note",
            "message": "second",
            "task_id": None,
            "bundle_id": None,
            "runtime_id": None,
            "details": {"index": 2},
        }
    ]


def test_operator_events_endpoint_includes_admission_decision_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: 1_781_827_800.0)
    service = _service(with_runtime=False, use_process_manager=True)
    older_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "older.wav"},
            priority=10,
            mode="manual",
            bundle_override="whisper-a",
        )
    )
    service._selected_bundles[older_task.task_id] = "whisper-a"
    newer_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "newer.wav"},
            priority=40,
            mode="manual",
            bundle_override="whisper-a",
        )
    )
    service._selected_bundles[newer_task.task_id] = "whisper-a"
    peer_task = service.queue.enqueue(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "peer"},
            priority=30,
            mode="manual",
            bundle_override="text-a",
        )
    )
    service._selected_bundles[peer_task.task_id] = "text-a"
    service.queue.restore(
        [
            replace(service.get_task(older_task.task_id), created_at="2026-06-19T00:00:00+00:00"),
            replace(service.get_task(newer_task.task_id), created_at="2026-06-19T00:09:00+00:00"),
            replace(service.get_task(peer_task.task_id), created_at="2026-06-19T00:09:00+00:00"),
        ]
    )
    service.process_pending()
    client = TestClient(build_app(service=service))

    response = client.get("/operators/events")

    assert response.status_code == 200
    admission_events = [
        event for event in response.json() if event["event_type"] == "admission.selected"
    ]
    assert admission_events == [
        {
            "timestamp": admission_events[0]["timestamp"],
            "event_type": "admission.selected",
            "message": "task selected for admission attempt",
            "task_id": older_task.task_id,
            "bundle_id": "whisper-a",
            "runtime_id": None,
            "details": {
                "base_priority": 10,
                "aging_bonus": 100,
                "effective_priority": 110,
                "fair_share_round": 0,
                "admission_rank": 1,
                "selection_reason": "highest_effective_priority",
            },
        },
        {
            "timestamp": admission_events[1]["timestamp"],
            "event_type": "admission.selected",
            "message": "task selected for admission attempt",
            "task_id": peer_task.task_id,
            "bundle_id": "text-a",
            "runtime_id": None,
            "details": {
                "base_priority": 30,
                "aging_bonus": 10,
                "effective_priority": 40,
                "fair_share_round": 0,
                "admission_rank": 2,
                "selection_reason": "lowest_dispatch_count",
            },
        },
        {
            "timestamp": admission_events[2]["timestamp"],
            "event_type": "admission.selected",
            "message": "task selected for admission attempt",
            "task_id": newer_task.task_id,
            "bundle_id": "whisper-a",
            "runtime_id": None,
            "details": {
                "base_priority": 40,
                "aging_bonus": 10,
                "effective_priority": 50,
                "fair_share_round": 1,
                "admission_rank": 3,
                "selection_reason": "only_remaining_bundle",
            },
        },
    ]


def test_operator_bundle_config_endpoint_returns_persisted_bundle_definitions(
    tmp_path,
) -> None:
    path = tmp_path / "bundles.json"
    registry = FileBundleRegistry(path)
    service = _service(bundle_registry=registry)
    registry.save(service.bundles)
    client = TestClient(build_app(service=service))

    response = client.get("/operators/bundles/config")

    assert response.status_code == 200
    assert response.json()[0]["bundle_id"] == "whisper-a"
    assert response.json()[0]["plugin_id"] == "fake-managed"


def test_operator_replace_bundle_config_endpoint_persists_and_reloads_bundles(
    tmp_path,
) -> None:
    path = tmp_path / "bundles.json"
    registry = FileBundleRegistry(path)
    service = _service(bundle_registry=registry)
    client = TestClient(build_app(service=service))

    response = client.put(
        "/operators/bundles/config",
        json=[
            {
                "bundle_id": "whisper-local",
                "plugin_id": "fake-managed",
                "provider_type": "fake",
                "workload_type": "speech_to_text",
                "model_id": "whisper-large",
                "launch_mode": "attached_service",
                "endpoint": "http://127.0.0.1:9000",
                "device_affinity": "cpu",
                "resource_profile": {
                    "cold_start_cpu": 0.0,
                    "cold_start_ram_mb": 0,
                    "cold_start_vram_mb": 0,
                    "steady_cpu": 1.0,
                    "steady_ram_mb": 1024,
                    "steady_vram_mb": 0,
                    "per_request_cpu": 0.5,
                    "per_request_ram_mb": 256,
                    "per_request_vram_mb": 0,
                },
                "warm_policy": "auto",
                "priority_class": 70,
                "max_parallel_requests": 1,
                "enabled": True,
            }
        ],
    )

    assert response.status_code == 200
    assert response.json() == {"bundle_count": 1, "status": "reloaded"}
    assert [bundle.bundle_id for bundle in service.bundles] == ["whisper-local"]
    assert registry.load(service.plugins)[0].bundle_id == "whisper-local"


def test_operator_reload_bundle_config_endpoint_refreshes_bundles_from_disk(
    tmp_path,
) -> None:
    path = tmp_path / "bundles.json"
    registry = FileBundleRegistry(path)
    service = _service(bundle_registry=registry)
    registry.save(
        [
            BundleConfig(
                bundle_id="phi4-ollama",
                plugin_id="fake-managed",
                provider_type="fake",
                workload_type="llm_text",
                model_id="phi4",
                launch_mode="attached_service",
                endpoint="http://127.0.0.1:11434",
                device_affinity="cpu",
                resource_profile=ResourceProfile(),
                warm_policy="auto",
            )
        ]
    )
    client = TestClient(build_app(service=service))

    response = client.post("/operators/bundles/reload")

    assert response.status_code == 200
    assert response.json() == {"bundle_count": 1, "status": "reloaded"}
    assert [bundle.bundle_id for bundle in service.bundles] == ["phi4-ollama"]


def test_api_surfaces_bundle_cooldown_status_and_runtime_metadata(
    monkeypatch,
) -> None:
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    monkeypatch.setattr("aidn_hypervisor.service.time.sleep", lambda _: None)
    plugins = PluginRegistry()
    plugin = CooldownApiPlugin()
    plugins.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"plugin_id": "fake-cooldown-api"}
            )
        ],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
    )
    service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"})
    )
    queued_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"})
    )
    client = TestClient(build_app(service=service))

    bundles_response = client.get("/bundles")
    runtimes_response = client.get("/runtimes")
    diagnostics_response = client.get("/diagnostics/queue")
    state_response = client.get("/operators/state")

    assert bundles_response.status_code == 200
    assert bundles_response.json() == [
        {
            "bundle_id": "whisper-a",
            "plugin_id": "fake-cooldown-api",
            "provider_type": "fake",
            "workload_type": "speech_to_text",
            "model_id": "whisper-a-model",
            "launch_mode": "managed_process",
            "enabled": True,
            "priority_class": 50,
            "status": "cooldown",
        }
    ]
    assert runtimes_response.status_code == 200
    assert runtimes_response.json() == [
        {
            "runtime_id": "rt-1",
            "bundle_id": "whisper-a",
            "command": ["python", "-m", "http.server", "0"],
            "status": "running",
            "health_status": "cooldown",
            "active_task_count": 0,
            "failure_streak": 1,
            "cooldown_until": 1060.0,
            "cooldown_reason": "connection refused",
            "drain_mode": False,
            "drain_reason": None,
        }
    ]
    assert diagnostics_response.status_code == 200
    assert diagnostics_response.json() == {
        "summary": {"queued": 1, "active": 0, "completed": 0, "failed": 1},
        "items": [
            {
                "task_id": queued_task.task_id,
                "bundle_id": "whisper-a",
                "reason": "provider_cooldown",
            }
        ],
    }
    assert state_response.status_code == 200
    assert state_response.json()["bundle_states"] == [
        {
            "bundle_id": "whisper-a",
            "failure_streak": 1,
            "cooldown_until": 1060.0,
            "cooldown_reason": "connection refused",
            "drain_mode": False,
            "drain_reason": None,
        }
    ]


def test_operator_reset_cooldown_endpoint_clears_bundle_cooldown(monkeypatch) -> None:
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    monkeypatch.setattr("aidn_hypervisor.service.time.sleep", lambda _: None)
    plugins = PluginRegistry()
    plugin = CooldownApiPlugin()
    plugins.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"plugin_id": "fake-cooldown-api"}
            )
        ],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
    )
    service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"})
    )
    client = TestClient(build_app(service=service))

    response = client.post("/operators/bundles/whisper-a/cooldown/reset")

    assert response.status_code == 200
    assert response.json() == {
        "bundle_id": "whisper-a",
        "status": "ready",
        "cooldown_until": None,
        "cooldown_reason": None,
        "failure_streak": 0,
    }
    assert service.bundle_state("whisper-a") == {
        "bundle_id": "whisper-a",
        "failure_streak": 0,
        "cooldown_until": None,
        "cooldown_reason": None,
        "drain_mode": False,
        "drain_reason": None,
    }


def test_operator_retry_bundle_endpoint_reprocesses_waiting_task(monkeypatch) -> None:
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    monkeypatch.setattr("aidn_hypervisor.service.time.sleep", lambda _: None)
    plugins = PluginRegistry()
    plugin = CooldownApiPlugin()
    plugin.invoke = lambda task, runtime_handle: (_ for _ in ()).throw(RuntimeError("connection refused"))
    plugins.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"plugin_id": "fake-cooldown-api"}
            )
        ],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
    )
    service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"})
    )
    queued_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"})
    )
    plugin.invoke = lambda task, runtime_handle: {
        "ok": True,
        "task_type": task.task_type,
    }
    client = TestClient(build_app(service=service))

    response = client.post("/operators/bundles/whisper-a/retry")

    assert response.status_code == 200
    assert response.json() == {
        "bundle_id": "whisper-a",
        "status": "retried",
        "summary": {"queued": 0, "active": 0, "completed": 1, "failed": 1},
    }
    assert service.get_task(queued_task.task_id).status == "completed"


def test_operator_disable_and_enable_bundle_endpoints_toggle_status() -> None:
    service = _service(with_runtime=True)
    client = TestClient(build_app(service=service))

    disable_response = client.post("/operators/bundles/whisper-a/disable")
    bundles_response = client.get("/bundles")
    enable_response = client.post("/operators/bundles/whisper-a/enable")
    bundles_enabled_response = client.get("/bundles")

    assert disable_response.status_code == 200
    assert disable_response.json() == {
        "bundle_id": "whisper-a",
        "enabled": False,
        "status": "disabled",
    }
    assert bundles_response.status_code == 200
    assert bundles_response.json()[0]["status"] == "disabled"
    assert enable_response.status_code == 200
    assert enable_response.json() == {
        "bundle_id": "whisper-a",
        "enabled": True,
        "status": "enabled",
    }
    assert bundles_enabled_response.status_code == 200
    assert bundles_enabled_response.json()[0]["status"] == "running"


def test_operator_drain_runtime_endpoint_marks_runtime_and_bundle_draining() -> None:
    service = _service(with_runtime=True)
    client = TestClient(build_app(service=service))

    response = client.post("/operators/runtimes/rt-1/drain")
    bundles_response = client.get("/bundles")
    runtimes_response = client.get("/runtimes")

    assert response.status_code == 200
    assert response.json() == {
        "runtime_id": "rt-1",
        "bundle_id": "whisper-a",
        "drain_mode": True,
        "status": "draining",
    }
    assert bundles_response.status_code == 200
    assert bundles_response.json()[0]["status"] == "draining"
    assert runtimes_response.status_code == 200
    assert runtimes_response.json()[0]["drain_mode"] is True
    assert runtimes_response.json()[0]["drain_reason"] == "operator_requested"


def test_operator_force_stop_runtime_endpoint_removes_runtime() -> None:
    service = _service(with_runtime=True)
    client = TestClient(build_app(service=service))

    response = client.post("/operators/runtimes/rt-1/force-stop")
    runtimes_response = client.get("/runtimes")

    assert response.status_code == 200
    assert response.json() == {
        "runtime_id": "rt-1",
        "bundle_id": "whisper-a",
        "status": "force_stopped",
    }
    assert runtimes_response.status_code == 200
    assert runtimes_response.json() == []


def test_operator_restart_runtime_endpoint_clears_drain_and_processes_queue() -> None:
    service = _service(with_runtime=True, use_process_manager=False)
    task = service.queue.enqueue(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    service._selected_bundles[task.task_id] = "whisper-a"
    service.drain_runtime("rt-1")
    service.process_pending()
    client = TestClient(build_app(service=service))

    response = client.post("/operators/runtimes/rt-1/restart")
    bundles_response = client.get("/bundles")

    assert response.status_code == 200
    assert response.json()["bundle_id"] == "whisper-a"
    assert response.json()["status"] == "restarted"
    assert service.get_task(task.task_id).status == "completed"
    assert bundles_response.status_code == 200
    assert bundles_response.json()[0]["status"] == "running"
