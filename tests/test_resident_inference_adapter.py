from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.resident_inference_adapter import (
    ResidentInferenceAdapter,
    ResidentInferenceError,
    ResidentInferenceResourceWait,
)
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.model_store import FileModelStore
from aidn_hypervisor.main import build_app


def _adapter(tmp_path: Path, *, vram_mb: int = 0, ram_mb: int = 4096):
    model = tmp_path / "steward.gguf"
    model.write_bytes(b"test-model")
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    resources = ResourceOrchestrator(
        NodeCapacity(cpu_cores=4, ram_mb=ram_mb, vram_mb=( {"gpu0": vram_mb} if vram_mb else {}))
    )
    runtimes = ProviderProcessManager()
    adapter = ResidentInferenceAdapter(
        node_id="node-test",
        resources=resources,
        runtimes=runtimes,
        plugin_resolver=plugins.get,
    )
    return adapter, resources, runtimes, model


def test_cpu_resident_start_and_stop_are_lease_gated(tmp_path: Path) -> None:
    adapter, resources, runtimes, model = _adapter(tmp_path)

    prepared = adapter.prepare(
        model_path=str(model),
        provider_type="fake",
        plugin_id="fake-managed",
    )
    assert prepared["state"] == "READY_TO_START"
    assert resources.lease_details() == []

    started = adapter.start()
    assert started["state"] == "STARTING"
    assert started["execution"]["resource_lease"] == "steward:node-test:inference"
    assert resources.summary()["reserved"]["ram_mb"] == 1024
    assert len(runtimes.list_runtimes()) == 1

    result = adapter.infer("hello")
    assert result == {"ok": True, "task_type": "llm_text.generate"}
    assert all(
        item["status"] == "RELEASED"
        for item in resources.lease_details(include_inactive=True)
        if item["lease_id"].startswith("steward:node-test:inference-request:")
    )

    adapter.stop()
    assert resources.summary()["reserved"]["ram_mb"] == 0
    assert runtimes.list_runtimes() == []


def test_gpu_burst_falls_back_to_cpu_when_gpu_lease_is_denied(tmp_path: Path) -> None:
    adapter, resources, _runtimes, model = _adapter(tmp_path, vram_mb=512)
    adapter.prepare(
        model_path=str(model),
        provider_type="fake",
        plugin_id="fake-managed",
        profile="GPU_BURST",
        vram_mb=1024,
    )

    started = adapter.start()
    assert started["execution"]["profile"] == "GPU_BURST"
    assert started["execution"]["effective_profile"] == "CPU_RESIDENT"
    assert started["execution"]["fallback_reason"]
    assert resources.summary()["reserved"]["vram_mb"] == 0


def test_gpu_burst_restarts_on_cpu_when_broker_reclaims_vram(tmp_path: Path) -> None:
    adapter, resources, runtimes, model = _adapter(tmp_path, vram_mb=4096)
    adapter.prepare(
        model_path=str(model),
        provider_type="fake",
        plugin_id="fake-managed",
        profile="GPU_BURST",
        vram_mb=1024,
    )
    adapter.start()
    lease_id = "steward:node-test:inference"
    assert resources.summary()["reserved"]["vram_mb"] == 1024

    resources.revoke_lease(lease_id)
    resources.acquire_lease("operator-gpu", cpu=0, ram_mb=0, vram_mb=4096)

    status = adapter.refresh()
    assert status["state"] == "STARTING"
    assert status["execution"]["effective_profile"] == "CPU_RESIDENT"
    assert status["execution"]["fallback_reason"]
    assert resources.summary()["reserved"]["vram_mb"] == 4096
    assert len(runtimes.list_runtimes()) == 1

    resources.release_lease("operator-gpu")
    adapter.stop()


def test_gpu_resident_denial_does_not_start_or_leave_a_lease(tmp_path: Path) -> None:
    adapter, resources, runtimes, model = _adapter(tmp_path, vram_mb=512)
    adapter.prepare(
        model_path=str(model),
        provider_type="fake",
        plugin_id="fake-managed",
        profile="GPU_RESIDENT",
        vram_mb=1024,
    )

    with pytest.raises(ResidentInferenceResourceWait) as error:
        adapter.start()

    assert error.value.code == "INFERENCE_RESOURCE_WAIT"
    assert adapter.status()["state"] == "RESOURCE_WAIT"
    assert resources.summary()["reserved"]["vram_mb"] == 0
    assert runtimes.list_runtimes() == []


def test_runtime_start_failure_releases_residency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, resources, runtimes, model = _adapter(tmp_path)
    adapter.prepare(model_path=str(model), provider_type="fake", plugin_id="fake-managed")

    def fail(_launch_spec):
        raise RuntimeError("launch failed")

    monkeypatch.setattr(runtimes, "start_runtime", fail)
    with pytest.raises(ValueError, match="failed to start"):
        adapter.start()
    assert resources.summary()["reserved"]["ram_mb"] == 0
    assert adapter.status()["state"] == "FAILED"


def test_readiness_timeout_stops_runtime_and_releases_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, resources, runtimes, model = _adapter(tmp_path)
    plugin = adapter._plugin_resolver("fake-managed")
    monkeypatch.setattr(plugin, "health_check", lambda _runtime: False)
    adapter.prepare(model_path=str(model), provider_type="fake", plugin_id="fake-managed", readiness_timeout_seconds=0)

    with pytest.raises(ResidentInferenceError) as error:
        adapter.start()

    assert error.value.details["code"] == "INFERENCE_RUNTIME_NOT_READY"
    assert resources.summary()["reserved"]["ram_mb"] == 0
    assert runtimes.list_runtimes() == []


def test_inference_timeout_releases_request_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, resources, _runtimes, model = _adapter(tmp_path)
    plugin = adapter._plugin_resolver("fake-managed")
    import time

    def slow_invoke(_task, _runtime):
        time.sleep(0.2)
        return {"ok": True}

    monkeypatch.setattr(plugin, "invoke", slow_invoke)
    adapter.prepare(model_path=str(model), provider_type="fake", plugin_id="fake-managed")
    adapter.start()

    with pytest.raises(ResidentInferenceError) as error:
        adapter.infer("hello", timeout_seconds=0.05)

    assert error.value.details["code"] == "INFERENCE_REQUEST_TIMEOUT"
    assert all(item["status"] == "RELEASED" for item in resources.lease_details(include_inactive=True) if item["lease_id"].startswith("steward:node-test:inference-request:"))
    adapter.stop()


def test_completed_reviewed_model_job_prepares_but_does_not_autostart(tmp_path: Path) -> None:
    source = tmp_path / "model.gguf"
    source.write_bytes(b"model")
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4, ram_mb=4096)),
        plugins=plugins,
        runtimes=ProviderProcessManager(),
        model_store=FileModelStore(tmp_path / "models"),
    )

    job = service.request_model_install(
        provider_type="fake-managed",
        model_id="model.gguf",
        source_url=source.as_uri(),
        requested_by="operator",
        resident_adapter_requested=True,
        resident_execution_profile="CPU_RESIDENT",
    )
    processed = service.process_model_installs()

    assert processed[0]["status"] == "completed"
    assert processed[0]["resident_adapter_status"] == "READY_TO_START"
    assert service.resident_inference_status()["state"] == "READY_TO_START"
    assert service.list_runtimes() == []
    assert service.resources.lease_details() == []

    service.resident_agent.set_enabled(True, persist=False)
    started = service.start_resident_inference_from_install(job["install_id"])
    assert started["execution"]["resource_lease"] == "steward:node-local:inference"
    assert service.resources.summary()["reserved"]["ram_mb"] == 1024


def test_operator_api_controls_resident_inference_without_autostart(tmp_path: Path) -> None:
    model = tmp_path / "steward.gguf"
    model.write_bytes(b"model")
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4, ram_mb=4096)),
        plugins=plugins,
        runtimes=ProviderProcessManager(),
    )
    client = TestClient(build_app(service=service))

    enabled = client.post("/operators/dashboard/steward/enabled", json={"enabled": True})
    assert enabled.status_code == 200
    prepared = client.post(
        "/operators/dashboard/steward/inference/prepare",
        json={
            "model_path": str(model),
            "provider_type": "fake",
            "plugin_id": "fake-managed",
        },
    )
    assert prepared.status_code == 200
    assert prepared.json()["state"] == "READY_TO_START"
    assert service.runtimes.list_runtimes() == []

    started = client.post("/operators/dashboard/steward/inference/start")
    assert started.status_code == 200
    assert started.json()["execution"]["resource_lease"] == "steward:node-local:inference"

    stopped = client.post("/operators/dashboard/steward/inference/stop")
    assert stopped.status_code == 200
    assert service.resources.summary()["reserved"]["ram_mb"] == 0
