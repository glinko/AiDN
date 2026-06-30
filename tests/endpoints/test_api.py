from fastapi.testclient import TestClient

from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile
from aidn_hypervisor.endpoints.runtime_adapter import EndpointRuntimeAdapter
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.main import build_app
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


def _endpoint_service() -> EndpointService:
    return EndpointService(EndpointStore(allow_in_memory=True))


class RecordingManagedPlugin(FakeManagedPlugin):
    plugin_id = "fake-recording"

    def invoke(self, task, runtime_handle) -> dict:
        return {
            "ok": True,
            "task_type": task.task_type,
            "payload": dict(task.payload),
            "runtime_id": runtime_handle.runtime_id,
        }


class FailingInvokeManagedPlugin(RecordingManagedPlugin):
    plugin_id = "fake-failing-invoke"

    def invoke(self, task, runtime_handle) -> dict:
        raise RuntimeError("provider connection refused")


def _runtime_backed_endpoint_service(
    *, with_runtime: bool = True, plugin: FakeManagedPlugin | None = None
) -> EndpointService:
    plugin = plugin or RecordingManagedPlugin()
    runtimes = (
        [
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "bundle-a",
            )
        ]
        if with_runtime
        else []
    )
    registry = PluginRegistry()
    registry.register(plugin)
    hypervisor = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 0})
        ),
        bundles=[
            BundleConfig(
                bundle_id="bundle-a",
                plugin_id=plugin.plugin_id,
                provider_type="fake",
                workload_type="llm_text",
                model_id="bundle-a-model",
                launch_mode="managed_process",
                endpoint="http://127.0.0.1:9000",
                device_affinity="cpu",
                resource_profile=ResourceProfile(),
                warm_policy="auto",
                enabled=True,
            )
        ],
        plugins=registry,
        runtimes=runtimes,
    )
    return EndpointService(
        EndpointStore(allow_in_memory=True),
        runtime_adapter=EndpointRuntimeAdapter(hypervisor),
    )


def _create_payload(**overrides) -> dict:
    payload = {
        "owner_wallet": "wallet-1",
        "bundle_id": "bundle-a",
        "bundle_hash": "bundle-hash-a",
        "display_name": "Operator STT",
        "model_class": "speech.stt",
        "capabilities": ["speech.stt"],
        "runtime": {
            "streaming": False,
            "timeout": 30,
        },
        "publication": {
            "visibility": "private",
            "discoverable": False,
            "validation": "disabled",
            "accepts_external_requests": False,
        },
    }
    payload.update(overrides)
    return payload


def test_create_endpoint_returns_201_with_enveloped_response() -> None:
    client = TestClient(build_app(endpoint_service=_endpoint_service()))

    response = client.post("/api/v1/endpoints", json=_create_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["error"] is None
    assert isinstance(body["correlation_id"], str)
    assert body["data"]["endpoint"]["endpoint_id"].startswith("ep-")
    assert body["data"]["endpoint"]["status"] == "created"
    assert (
        body["data"]["snapshot"]["configuration_hash"]
        == body["data"]["endpoint"]["configuration_hash"]
    )


def test_patch_runtime_rotates_configuration_hash() -> None:
    client = TestClient(build_app(endpoint_service=_endpoint_service()))
    created = client.post("/api/v1/endpoints", json=_create_payload()).json()["data"]

    response = client.patch(
        f"/api/v1/endpoints/{created['endpoint']['endpoint_id']}",
        json={
            "runtime": {
                "streaming": True,
                "timeout": 45,
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert (
        body["data"]["endpoint"]["configuration_hash"]
        != created["endpoint"]["configuration_hash"]
    )
    assert body["data"]["snapshot"]["runtime"]["streaming"] is True
    assert body["data"]["snapshot"]["runtime"]["timeout"] == 45


def test_create_invalid_payload_returns_validation_error_envelope() -> None:
    client = TestClient(build_app(endpoint_service=_endpoint_service()))

    response = client.post(
        "/api/v1/endpoints",
        json=_create_payload(runtime={"timeout": 0}),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "endpoint_validation_error"
    assert body["error"]["message"] == "Request validation failed"
    assert isinstance(body["correlation_id"], str)


def test_patch_invalid_payload_returns_validation_error_envelope() -> None:
    client = TestClient(build_app(endpoint_service=_endpoint_service()))
    created = client.post("/api/v1/endpoints", json=_create_payload()).json()["data"]

    response = client.patch(
        f"/api/v1/endpoints/{created['endpoint']['endpoint_id']}",
        json={"runtime": {"timeout": 0}},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "endpoint_validation_error"
    assert body["error"]["message"] == "Request validation failed"
    assert isinstance(body["correlation_id"], str)


def test_suspend_invalid_state_returns_state_error_envelope() -> None:
    client = TestClient(build_app(endpoint_service=_endpoint_service()))
    created = client.post("/api/v1/endpoints", json=_create_payload()).json()["data"]

    response = client.post(
        f"/api/v1/endpoints/{created['endpoint']['endpoint_id']}/suspend"
    )

    assert response.status_code == 409
    assert response.json()["data"] is None
    assert response.json()["error"]["code"] == "endpoint_state_error"


def test_start_and_stop_lifecycle_routes_return_enveloped_results() -> None:
    client = TestClient(build_app(endpoint_service=_endpoint_service()))
    created = client.post("/api/v1/endpoints", json=_create_payload()).json()["data"]
    endpoint_id = created["endpoint"]["endpoint_id"]

    start_response = client.post(f"/api/v1/endpoints/{endpoint_id}/start")
    stop_response = client.post(f"/api/v1/endpoints/{endpoint_id}/stop")

    assert start_response.status_code == 200
    assert start_response.json()["error"] is None
    assert start_response.json()["data"]["endpoint"]["status"] == "active"
    assert stop_response.status_code == 200
    assert stop_response.json()["error"] is None
    assert stop_response.json()["data"]["endpoint"]["status"] == "stopped"


def test_get_and_list_routes_return_happy_path_payloads() -> None:
    client = TestClient(build_app(endpoint_service=_endpoint_service()))
    created = client.post(
        "/api/v1/endpoints",
        json=_create_payload(display_name="Operator Translate"),
    ).json()["data"]["endpoint"]

    list_response = client.get("/api/v1/endpoints")
    get_response = client.get(f"/api/v1/endpoints/{created['endpoint_id']}")

    assert list_response.status_code == 200
    assert list_response.json()["error"] is None
    assert [item["endpoint_id"] for item in list_response.json()["data"]] == [
        created["endpoint_id"]
    ]
    assert get_response.status_code == 200
    assert get_response.json()["error"] is None
    assert get_response.json()["data"]["display_name"] == "Operator Translate"


def test_get_unknown_endpoint_returns_enveloped_404() -> None:
    client = TestClient(build_app(endpoint_service=_endpoint_service()))

    response = client.get("/api/v1/endpoints/ep-missing")

    assert response.status_code == 404
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "endpoint_not_found"
    assert isinstance(body["correlation_id"], str)


def test_invoke_endpoint_returns_enveloped_result_for_active_ready_endpoint() -> None:
    client = TestClient(
        build_app(endpoint_service=_runtime_backed_endpoint_service())
    )
    created = client.post("/api/v1/endpoints", json=_create_payload()).json()["data"]
    endpoint_id = created["endpoint"]["endpoint_id"]
    client.post(f"/api/v1/endpoints/{endpoint_id}/start")

    response = client.post(
        f"/api/v1/endpoints/{endpoint_id}/invoke",
        json={
            "task_type": "llm_text.generate",
            "payload": {"prompt": "hello"},
            "constraints": {"tenant": "demo"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["data"]["endpoint"]["endpoint_id"] == endpoint_id
    assert body["data"]["bundle_id"] == "bundle-a"
    assert body["data"]["runtime_id"] == "rt-1"
    assert body["data"]["readiness"]["ready"] is True
    assert body["data"]["result"] == {
        "ok": True,
        "task_type": "llm_text.generate",
        "payload": {"prompt": "hello"},
        "runtime_id": "rt-1",
    }
    assert isinstance(body["correlation_id"], str)


def test_invoke_unknown_endpoint_returns_enveloped_404() -> None:
    client = TestClient(
        build_app(endpoint_service=_runtime_backed_endpoint_service())
    )

    response = client.post(
        "/api/v1/endpoints/ep-missing/invoke",
        json={"task_type": "llm_text.generate", "payload": {"prompt": "hello"}},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "endpoint_not_found"
    assert body["error"]["message"] == "Unknown endpoint: ep-missing"
    assert isinstance(body["correlation_id"], str)


def test_invoke_inactive_endpoint_returns_not_active_error() -> None:
    client = TestClient(
        build_app(endpoint_service=_runtime_backed_endpoint_service())
    )
    created = client.post("/api/v1/endpoints", json=_create_payload()).json()["data"]
    endpoint_id = created["endpoint"]["endpoint_id"]

    response = client.post(
        f"/api/v1/endpoints/{endpoint_id}/invoke",
        json={"task_type": "llm_text.generate", "payload": {"prompt": "hello"}},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "endpoint_not_active"
    assert body["error"]["message"] == f"Endpoint {endpoint_id} is not active"
    assert isinstance(body["correlation_id"], str)


def test_invoke_runtime_error_uses_native_error_code_and_message() -> None:
    client = TestClient(
        build_app(endpoint_service=_runtime_backed_endpoint_service(with_runtime=False))
    )
    created = client.post("/api/v1/endpoints", json=_create_payload()).json()["data"]
    endpoint_id = created["endpoint"]["endpoint_id"]
    client.post(f"/api/v1/endpoints/{endpoint_id}/start")

    response = client.post(
        f"/api/v1/endpoints/{endpoint_id}/invoke",
        json={"task_type": "llm_text.generate", "payload": {"prompt": "hello"}},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "runtime_unavailable"
    assert body["error"]["message"] == "Runtime is not available: bundle-a"
    assert isinstance(body["correlation_id"], str)


def test_invoke_provider_failure_returns_endpoint_error_envelope() -> None:
    client = TestClient(
        build_app(
            endpoint_service=_runtime_backed_endpoint_service(
                plugin=FailingInvokeManagedPlugin()
            )
        )
    )
    created = client.post("/api/v1/endpoints", json=_create_payload()).json()["data"]
    endpoint_id = created["endpoint"]["endpoint_id"]
    client.post(f"/api/v1/endpoints/{endpoint_id}/start")

    response = client.post(
        f"/api/v1/endpoints/{endpoint_id}/invoke",
        json={"task_type": "llm_text.generate", "payload": {"prompt": "hello"}},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "endpoint_execution_error"
    assert body["error"]["message"] == "provider connection refused"
    assert isinstance(body["correlation_id"], str)
