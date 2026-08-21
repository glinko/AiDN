from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile
from aidn_hypervisor.endpoints.models import CreateEndpointCommand, EndpointPublicationPolicy
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.lifecycle_manager import LifecycleError, LifecycleManager, ResetManager
from aidn_hypervisor.main import build_app
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


class _FakeHost:
    node_id = "node-test"

    def __init__(self) -> None:
        self.runtimes = [
            RuntimeHandle(
                runtime_id="rt-1",
                command=["provider"],
                status="running",
                bundle_id="bundle-a",
            )
        ]
        self._lifecycle_operations: dict[str, dict] = {}
        self._lifecycle_tombstones: dict[str, dict] = {}
        self._lifecycle_maintenance_state = "ENABLED"
        self.events: list[dict] = []
        self.persist_count = 0

    def list_runtimes(self):
        return list(self.runtimes)

    def force_stop_runtime(self, runtime_id: str):
        for runtime in self.runtimes:
            if runtime.runtime_id == runtime_id:
                self.runtimes.remove(runtime)
                runtime.status = "stopped"
                return {"runtime_id": runtime_id, "status": "force_stopped"}
        raise KeyError(runtime_id)

    def runtime_active_task_count(self, _bundle_id: str) -> int:
        return 0

    def reconcile_scheduler(self, **_kwargs):
        return {"status": "stable"}

    def record_event(self, **payload):
        self.events.append(payload)

    def _persist_state(self):
        self.persist_count += 1


class _TransitionHost(_FakeHost):
    def __init__(self) -> None:
        super().__init__()
        self.bundles = [
            BundleConfig(
                bundle_id="bundle-a",
                plugin_id="plugin",
                provider_type="llama.cpp",
                workload_type="llm_text",
                model_id="model-a",
                launch_mode="managed_process",
                endpoint="http://127.0.0.1:8080",
                device_affinity="cuda:0",
                resource_profile=ResourceProfile(steady_vram_mb=1024),
                warm_policy="auto",
            )
        ]
        self.endpoint_service = EndpointService(EndpointStore())
        self.endpoint_service.create_endpoint(
            CreateEndpointCommand(
                owner_wallet="wallet-a",
                bundle_id="bundle-a",
                bundle_hash="sha256:bundle",
                display_name="Endpoint A",
                model_class="llm",
                publication=EndpointPublicationPolicy(
                    visibility="public",
                    discoverable=True,
                    accepts_external_requests=True,
                ),
            )
        )

    def bundle_config(self):
        return list(self.bundles)

    def set_bundle_enabled(self, bundle_id: str, enabled: bool):
        for index, bundle in enumerate(self.bundles):
            if bundle.bundle_id == bundle_id:
                self.bundles[index] = bundle.model_copy(update={"enabled": enabled})
                self._persist_state()
                return {"bundle_id": bundle_id, "enabled": enabled, "status": "enabled" if enabled else "disabled"}
        raise KeyError(bundle_id)

    def replace_bundle_config(self, bundles):
        self.bundles = list(bundles)


def test_runtime_removal_is_plan_bound_and_creates_tombstone() -> None:
    host = _FakeHost()
    manager = LifecycleManager(host)

    plan = manager.removal_plan("runtime", "rt-1")
    assert plan["plan_hash"].startswith("sha256:")
    assert plan["actions"][-1]["action"] == "DELETE_LOCAL"

    operation = manager.apply_removal(plan["plan_id"], plan["plan_hash"])
    assert operation["state"] == "COMPLETED"
    assert host.runtimes == []
    assert manager.get_tombstone("runtime", "rt-1")["network_state"] == "LOCAL_ONLY"

    with pytest.raises(LifecycleError) as error:
        manager.removal_plan("runtime", "rt-1")
    assert error.value.code == "OBJECT_TOMBSTONED"


def test_stale_plan_is_rejected_before_mutation() -> None:
    host = _FakeHost()
    manager = LifecycleManager(host)
    plan = manager.removal_plan("runtime", "rt-1")
    host.runtimes[0].status = "degraded"

    with pytest.raises(LifecycleError) as error:
        manager.apply_removal(plan["plan_id"], plan["plan_hash"])
    assert error.value.code == "REMOVAL_PLAN_STALE"
    assert host.runtimes[0].status == "degraded"


def test_runtime_reset_preserves_configuration_and_reenables_maintenance() -> None:
    host = _FakeHost()
    lifecycle = LifecycleManager(host)
    reset = ResetManager(lifecycle)
    plan = reset.plan("runtime")

    result = reset.apply(plan["reset_id"], plan["plan_hash"], actor="operator", force=False, idempotency_key="reset-1")

    assert result["state"] == "COMPLETED"
    assert host.runtimes == []
    assert host._lifecycle_maintenance_state == "ENABLED"
    assert any(item["event_type"] == "aidn.node.reset_completed" for item in host.events)


def test_runtime_reset_rejects_future_profile_without_erasing_state() -> None:
    host = _FakeHost()
    lifecycle = LifecycleManager(host)
    reset = ResetManager(lifecycle)
    plan = reset.plan("factory")

    with pytest.raises(LifecycleError) as error:
        reset.apply(plan["reset_id"], plan["plan_hash"], actor="operator", force=False, idempotency_key=None)
    assert error.value.code == "RESET_PROFILE_NOT_IMPLEMENTED"
    assert host.runtimes


def test_bundle_disable_and_retire_are_plan_bound_transitions() -> None:
    host = _TransitionHost()
    manager = LifecycleManager(host)

    disable = manager.transition_plan("bundle", "bundle-a", "DISABLE")
    result = manager.apply_transition(disable["transition_id"], disable["plan_hash"])
    assert result["state"] == "COMPLETED"
    assert manager._target("bundle", "bundle-a")["state"] == "DISABLED"

    host.runtimes.clear()
    retire = manager.transition_plan("bundle", "bundle-a", "RETIRE")
    manager.apply_transition(retire["transition_id"], retire["plan_hash"])
    assert manager._target("bundle", "bundle-a")["state"] == "RETIRED"


def test_endpoint_unpublish_then_retire_preserves_manifest_and_closes_access() -> None:
    host = _TransitionHost()
    manager = LifecycleManager(host)
    endpoint_id = host.endpoint_service.list_endpoints()[0].endpoint_id

    unpublish = manager.transition_plan("endpoint", endpoint_id, "UNPUBLISH")
    manager.apply_transition(unpublish["transition_id"], unpublish["plan_hash"])
    endpoint = host.endpoint_service.get_endpoint(endpoint_id).endpoint
    assert endpoint.publication.discoverable is False
    assert endpoint.publication.accepts_external_requests is False
    assert manager._target("endpoint", endpoint_id)["state"] == "UNPUBLISHED"

    host.runtimes.clear()
    retire = manager.transition_plan("endpoint", endpoint_id, "RETIRE")
    manager.apply_transition(retire["transition_id"], retire["plan_hash"])
    endpoint = host.endpoint_service.get_endpoint(endpoint_id).endpoint
    assert endpoint.status == "stopped"
    assert manager._target("endpoint", endpoint_id)["state"] == "RETIRED"


def test_operator_api_exposes_plan_and_tombstone_routes() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2, ram_mb=2048, gpu_devices=[], vram_mb={})
        ),
        bundles=[],
        plugins=PluginRegistry(),
        runtimes=[],
    )
    client = TestClient(build_app(service=service))

    reset_response = client.post("/operators/node/reset/runtime/plan")
    assert reset_response.status_code == 200
    assert reset_response.json()["profile"] == "runtime"
    assert client.get("/operators/lifecycle/tombstones").status_code == 200
