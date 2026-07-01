from dataclasses import replace
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from aidn_hypervisor.domain.models import (
    AllocationRequest,
    BundleConfig,
    NodeCapacity,
    ResourceProfile,
    TaskRequest,
)
from aidn_hypervisor.model_store import FileModelStore
from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.plugins.ollama import OllamaPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.plugins.whisper import WhisperPlugin
from aidn_hypervisor.process_manager import ProviderProcessManager, RuntimeHandle
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.remote_endpoints.service import RemoteEndpointService
from aidn_hypervisor.remote_endpoints.store import RemoteEndpointStore
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.state import JournalEvent


def _bundle(
    bundle_id: str,
    workload_type: str,
    *,
    resource_profile: ResourceProfile | None = None,
    warm_policy: str = "auto",
    priority_class: int = 50,
    enabled: bool = True,
) -> BundleConfig:
    return BundleConfig(
        bundle_id=bundle_id,
        plugin_id="fake-managed",
        provider_type="fake",
        workload_type=workload_type,
        model_id=f"{bundle_id}-model",
        launch_mode="managed_process",
        device_affinity="cpu",
        resource_profile=resource_profile or ResourceProfile(),
        warm_policy=warm_policy,
        priority_class=priority_class,
        enabled=enabled,
    )


def _registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())
    return registry


class UnhealthyFakePlugin(FakeManagedPlugin):
    plugin_id = "fake-unhealthy"

    def health_check(self, runtime_handle) -> bool:
        return False


class FailingInvokePlugin(FakeManagedPlugin):
    plugin_id = "fake-failing"

    def invoke(self, task, runtime_handle) -> dict:
        raise RuntimeError("invoke failed")


class ConcurrencyHintPlugin(FakeManagedPlugin):
    plugin_id = "fake-concurrency-hint"

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        result = super().estimate_resources(task, bundle_config, runtime_state)
        result["concurrency_limit"] = 1
        return result


class RetryPolicyPlugin(FakeManagedPlugin):
    plugin_id = "fake-retry-policy"

    def __init__(
        self,
        *,
        health_outcomes: list[bool] | None = None,
        invoke_outcomes: list[dict | Exception] | None = None,
        health_backoff_seconds: float = 0.0,
        invoke_backoff_seconds: float = 0.0,
    ) -> None:
        self.health_outcomes = list(health_outcomes or [True])
        self.invoke_outcomes = list(
            invoke_outcomes or [{"ok": True, "task_type": "audio.transcribe"}]
        )
        self.health_attempts = 0
        self.invoke_attempts = 0
        self.health_backoff_seconds = health_backoff_seconds
        self.invoke_backoff_seconds = invoke_backoff_seconds

    def retry_policy(self) -> dict:
        return {
            "health_check": {
                "max_attempts": 3,
                "backoff_seconds": self.health_backoff_seconds,
            },
            "invoke": {
                "max_attempts": 3,
                "backoff_seconds": self.invoke_backoff_seconds,
                "retry_exceptions": (RuntimeError,),
            },
        }

    def health_check(self, runtime_handle) -> bool:
        self.health_attempts += 1
        if self.health_outcomes:
            return self.health_outcomes.pop(0)
        return True

    def invoke(self, task, runtime_handle) -> dict:
        self.invoke_attempts += 1
        if self.invoke_outcomes:
            outcome = self.invoke_outcomes.pop(0)
        else:
            outcome = {"ok": True, "task_type": task.task_type}
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class CooldownPolicyPlugin(RetryPolicyPlugin):
    plugin_id = "fake-cooldown-policy"

    def __init__(
        self,
        *,
        cooldown_seconds: float = 60.0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.cooldown_seconds = cooldown_seconds

    def circuit_breaker_policy(self) -> dict:
        return {
            "failure_threshold": 1,
            "cooldown_seconds": self.cooldown_seconds,
        }


class StubOllamaPlugin(OllamaPlugin):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def _request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
        self.calls.append((method, url, payload))
        if url.endswith("/api/tags"):
            return {"models": [{"name": "phi4"}]}
        if url.endswith("/api/generate"):
            return {"response": "Hello from Ollama", "done": True}
        raise AssertionError(f"unexpected request: {method} {url}")


class StubWhisperPlugin(WhisperPlugin):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def _request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
        self.calls.append((method, url, payload))
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/v1/audio/transcriptions"):
            return {"text": "hello from whisper"}
        raise AssertionError(f"unexpected request: {method} {url}")


class StubLlamaCppPlugin(LlamaCppPlugin):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def _request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
        self.calls.append((method, url, payload))
        if url.endswith("/health"):
            return {"status": "ok"}
        if url.endswith("/completion"):
            return {"content": "hello from llama.cpp"}
        raise AssertionError(f"unexpected request: {method} {url}")


class RecordingPlugin(FakeManagedPlugin):
    plugin_id = "fake-recording"

    def __init__(self) -> None:
        self.invocations: list[str] = []

    def invoke(self, task, runtime_handle) -> dict:
        marker = task.payload.get("marker", task.task_type)
        self.invocations.append(marker)
        return {"ok": True, "task_type": task.task_type, "marker": marker}


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
                    "usage": {
                        "input_tokens": 12,
                        "output_tokens": 5,
                        "fixed_request_count": 1,
                        "measurement_kind": "exact",
                        "measurement_source": "provider_api",
                    },
                },
            }
        raise AssertionError(f"unexpected proxy request: {method} {url}")


def test_service_submit_routes_and_records_selected_bundle_for_manual_mode() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[_bundle("whisper-a", "speech_to_text")],
    )

    task = service.submit(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "clip.wav"},
            mode="manual",
            bundle_override="whisper-a",
        )
    )

    assert service.selected_bundle_id(task.task_id) == "whisper-a"
    assert task.request.bundle_override == "whisper-a"


def test_service_submit_routes_and_records_selected_bundle_for_automatic_mode() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[
            _bundle("text-a", "llm_text", priority_class=100),
            _bundle("preferred-whisper", "speech_to_text", priority_class=80),
            _bundle("fallback-whisper", "speech_to_text", priority_class=40),
        ],
    )

    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    assert service.selected_bundle_id(task.task_id) == "preferred-whisper"


def test_service_submit_uses_active_allocation_bundle_for_routing() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("preferred-text", "llm_text", priority_class=100),
            _bundle("leased-text", "llm_text", priority_class=10).model_copy(
                update={"endpoint": "http://127.0.0.1:8080"}
            ),
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="leased-text",
        )
    )

    task = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )

    assert service.selected_bundle_id(task.task_id) == "leased-text"
    assert task.request.mode == "manual"
    assert task.request.bundle_override == "leased-text"
    assert task.request.constraints["wallet_owner_id"] == "agent-a"


def test_service_submit_rejects_task_when_allocation_is_not_active() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("leased-text", "llm_text").model_copy(
                update={"endpoint": "http://127.0.0.1:8080"}
            )
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="leased-text",
        )
    )
    service.release_allocation(allocation["allocation_id"])

    with pytest.raises(ValueError, match="Allocation is not active"):
        service.submit(
            TaskRequest(
                task_type="llm_text.generate",
                payload={"prompt": "hello"},
                constraints={"allocation_id": allocation["allocation_id"]},
            )
        )


def test_service_submit_raises_when_request_cannot_be_routed() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[_bundle("text-a", "llm_text")],
    )

    with pytest.raises(ValueError, match="compatible"):
        service.submit(
            TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
        )


def test_service_executes_task_via_proxy_endpoint_when_endpoint_constraint_is_provided() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("text-a", "llm_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
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

    task = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"endpoint_id": created.endpoint.endpoint_id},
        )
    )

    assert service.selected_bundle_id(task.task_id) == "text-a"
    assert service.get_task(task.task_id).status == "completed"
    assert service.task_result(task.task_id) == {
        "ok": True,
        "task_type": "llm_text.generate",
        "output_text": "hello from remote",
        "usage": {
            "input_tokens": 12,
            "output_tokens": 5,
            "fixed_request_count": 1,
            "measurement_kind": "exact",
            "measurement_source": "provider_api",
        },
        "proxy": {
            "remote_task_id": "remote-task-1",
            "remote_endpoint_id": "ep-remote",
            "remote_node_id": "node-remote",
            "source_base_url": "http://remote-hv",
        },
    }
    assert service.remote_transport.calls == [
        (
            "POST",
            "http://remote-hv/tasks",
            {
                "task_type": "llm_text.generate",
                "payload": {"prompt": "hello"},
                "mode": "auto",
                "bundle_override": None,
                "priority": 50,
                "constraints": {"endpoint_id": "ep-remote"},
            },
        ),
        ("GET", "http://remote-hv/tasks/remote-task-1", None),
    ]


def test_service_executes_task_immediately_when_resources_are_available() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=1.0,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
                warm_policy="auto",
            )
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    stored_task = service.get_task(task.task_id)

    assert stored_task.status == "completed"
    assert service.task_result(task.task_id) == {
        "ok": True,
        "task_type": "audio.transcribe",
    }
    assert service.list_runtimes()[0].bundle_id == "whisper-a"
    assert service.resources.summary()["reserved"]["cpu"] == pytest.approx(0.5)


def test_service_node_advertisement_reports_resources_pricing_and_bundles() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(
                cpu_cores=8.0,
                ram_mb=16384,
                gpu_devices=["gpu0"],
                vram_mb={"gpu0": 8192},
            )
        ),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        node_id="node-local",
        operator_id="operator-a",
        base_url="https://node.example",
        can_host_custom_model=True,
        pricing={
            "unit": "q_per_1kk_tokens",
            "input": 12,
            "output": 18,
            "fixed_request": None,
        },
        rating={
            "score": 0.91,
            "tier": "A",
            "updated_at": "2026-06-19T18:25:00Z",
        },
    )

    payload = service.node_advertisement(heartbeat_at="2026-06-19T18:30:00Z")

    assert payload["node_id"] == "node-local"
    assert payload["operator_id"] == "operator-a"
    assert payload["can_host_custom_model"] is True
    assert payload["pricing"]["input"] == 12
    assert payload["rating"]["score"] == 0.91
    assert payload["bundles"][0]["bundle_id"] == "whisper-a"
    assert payload["bundles"][0]["plugin_id"] == "fake-managed"
    assert payload["bundles"][0]["status"] == "ready"


def test_service_dashboard_fleet_reports_node_resources_bundles_and_installs(
    tmp_path,
) -> None:
    store = FileModelStore(tmp_path)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(
                cpu_cores=8.0,
                ram_mb=16384,
                gpu_devices=["gpu0"],
                vram_mb={"gpu0": 8192},
            )
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text"),
            _bundle("text-a", "llm_text"),
            _bundle("disabled-text", "llm_text", enabled=False),
        ],
        plugins=_registry(),
        runtimes=[
            RuntimeHandle(
                runtime_id="rt-1",
                bundle_id="whisper-a",
                command=["python", "-m", "http.server", "0"],
                status="running",
                health_status="healthy",
            )
        ],
        model_store=store,
    )
    service.resources.reserve("runtime-whisper-a", cpu=1.5, ram_mb=2048, vram_mb=1024)
    install = service.request_model_install(
        requested_by="operator-a",
        source_url="https://example.invalid/models/phi4.gguf",
        model_id="phi4-gguf",
        provider_type="fake",
    )

    fleet = service.operator_dashboard_fleet()

    assert fleet["node"]["node_id"] == service.node_id
    assert fleet["node"]["operator_id"] == service.operator_id
    assert fleet["resources"]["free"]["cpu"] == pytest.approx(6.5)
    assert fleet["queue"] == {"queued": 0, "active": 0, "completed": 0, "failed": 0}
    assert fleet["bundles"][0]["bundle_id"] == "whisper-a"
    assert fleet["bundles"][0]["publish_status"] == "ready_to_publish"
    assert fleet["installs"][0]["install_id"] == install["install_id"]
    assert fleet["installs"][0]["install_status"] == "pending"


def test_service_dashboard_home_reports_publish_market_and_capacity_blocks(
    tmp_path,
) -> None:
    store = FileModelStore(tmp_path)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(
                cpu_cores=8.0,
                ram_mb=16384,
                gpu_devices=["gpu0"],
                vram_mb={"gpu0": 8192},
            )
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"endpoint": "http://127.0.0.1:9000"}
            ),
            _bundle("text-a", "llm_text"),
            _bundle("disabled-text", "llm_text", enabled=False),
        ],
        plugins=_registry(),
        runtimes=[
            RuntimeHandle(
                runtime_id="rt-1",
                bundle_id="whisper-a",
                command=["python", "-m", "http.server", "0"],
                status="running",
                health_status="healthy",
            )
        ],
        model_store=store,
    )
    service.resources.reserve("runtime-whisper-a", cpu=1.5, ram_mb=2048, vram_mb=1024)
    service.request_model_install(
        requested_by="operator-a",
        source_url="https://example.invalid/models/phi4.gguf",
        model_id="phi4-gguf",
        provider_type="fake",
    )

    home = service.operator_dashboard_home()

    assert home["bootstrap"]["wallet_ready"] is False
    assert home["bootstrap"]["node_identity"]["node_id"] == service.node_id
    assert home["bootstrap"]["first_endpoint_candidate"]["bundle_id"] == "whisper-a"
    assert home["bootstrap"]["next_step"] == "Create or import a wallet"
    assert home["publish"]["draft_offer_count"] == 3
    assert home["publish"]["install_pending_count"] == 1
    assert home["publish"]["live_offer_count"] == 2
    assert home["market_visibility"]["local_offer_count"] == 3
    assert home["fleet_capacity"]["node_count"] == 1
    assert "Publish Offer" in home["operator_controls"]["actions"]


def test_service_owner_wallet_bootstrap_persists_and_restores_state() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[_bundle("text-a", "llm_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    created = service.configure_owner_wallet(mode="create", label="Primary Wallet")
    snapshot = service.snapshot_state()

    restored = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[_bundle("text-a", "llm_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    restored.restore_state(snapshot)

    owner = restored.owner_wallet_state()
    assert owner["configured"] is True
    assert owner["wallet_id"] == created["wallet"]["wallet_id"]
    assert owner["label"] == "Primary Wallet"
    assert restored.node_identity()["owner_wallet_id"] == created["wallet"]["wallet_id"]


def test_service_home_bootstrap_requires_wallet_before_network_actions() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"endpoint": "http://127.0.0.1:9000"}
            ),
            _bundle("text-a", "llm_text"),
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    payload = service.operator_dashboard_home()["bootstrap"]

    assert payload["wallet_ready"] is False
    assert payload["endpoint_count"] == 0
    assert payload["first_endpoint_candidate"]["bundle_id"] == "whisper-a"
    assert payload["next_step"] == "Create or import a wallet"


def test_service_home_bootstrap_surfaces_first_endpoint_candidate_after_wallet_setup() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"endpoint": "http://127.0.0.1:9000"}
            ),
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    wallet = service.configure_owner_wallet(mode="create", label="Primary Wallet")
    payload = service.operator_dashboard_home()["bootstrap"]

    assert payload["wallet_ready"] is True
    assert payload["owner_wallet"]["wallet_id"] == wallet["wallet"]["wallet_id"]
    assert payload["endpoint_count"] == 0
    assert payload["first_endpoint_candidate"]["bundle_id"] == "whisper-a"
    assert payload["next_step"] == "Create your first endpoint from whisper-a"


def test_service_endpoints_dashboard_defaults_to_empty_without_endpoint_state() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"endpoint": "http://127.0.0.1:9000"}
            ),
            _bundle("text-a", "llm_text"),
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    wallet = service.configure_owner_wallet(mode="create", label="Primary Wallet")

    payload = service.operator_dashboard_endpoints()

    assert payload["owner_wallet"]["wallet_id"] == wallet["wallet"]["wallet_id"]
    assert payload["node_identity"]["node_id"] == service.node_id
    assert payload["summary"] == {
        "total": 0,
        "configured": 0,
        "published": 0,
        "validation_requested": 0,
        "private": 0,
        "shared": 0,
        "public": 0,
    }
    assert payload["policy"]["publish_requires_validation"] is False
    assert payload["items"] == []


def test_service_requests_dashboard_reports_queue_recent_and_policy() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text"),
            _bundle("text-a", "llm_text"),
        ],
        plugins=_registry(),
        runtimes=[
            RuntimeHandle(
                runtime_id="rt-1",
                bundle_id="text-a",
                command=["python", "-m", "http.server", "0"],
                status="running",
                health_status="healthy",
            )
        ],
    )
    completed = service.submit(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "done"})
    )
    queued = service.queue.enqueue(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "queued.wav"})
    )
    service._selected_bundles[queued.task_id] = "whisper-a"

    payload = service.operator_dashboard_requests()

    assert payload["summary"]["queued"] >= 1
    assert payload["summary"]["completed_recent"] >= 1
    assert payload["policy"] == {
        "allow_spillover": False,
        "dispatch_strategy": "local_first",
        "ready_endpoint_only": True,
    }
    assert any(item["task_id"] == queued.task_id for item in payload["queue"])
    assert any(item["task_id"] == completed.task_id for item in payload["recent"])


def test_service_snapshot_and_restore_preserves_requests_policy() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[_bundle("text-a", "llm_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    service.update_operator_requests_policy(
        allow_spillover=True,
        dispatch_strategy="balanced",
        ready_endpoint_only=False,
    )

    snapshot = service.snapshot_state()
    restored = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[_bundle("text-a", "llm_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    restored.restore_state(snapshot)

    assert restored.operator_requests_policy() == {
        "allow_spillover": True,
        "dispatch_strategy": "balanced",
        "ready_endpoint_only": False,
    }


def test_service_requests_dashboard_recent_is_sorted_by_terminal_event_time() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[_bundle("text-a", "llm_text"), _bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    task_a = service.queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "a"}, priority=80)
    )
    task_b = service.queue.enqueue(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "b.wav"}, priority=40)
    )
    service._selected_bundles[task_a.task_id] = "text-a"
    service._selected_bundles[task_b.task_id] = "whisper-a"
    service.queue.transition_status(task_b.task_id, "completed")
    service.queue.transition_status(task_a.task_id, "completed")
    service._task_results[task_a.task_id] = {"ok": True, "task_type": "llm_text.generate"}
    service._task_results[task_b.task_id] = {"ok": True, "task_type": "audio.transcribe"}
    service._events.extend(
        [
            JournalEvent(
                timestamp="2026-06-20T12:00:01+00:00",
                event_type="task.completed",
                message="task completed successfully",
                task_id=task_b.task_id,
            ),
            JournalEvent(
                timestamp="2026-06-20T12:00:02+00:00",
                event_type="task.completed",
                message="task completed successfully",
                task_id=task_a.task_id,
            ),
        ]
    )

    payload = service.operator_dashboard_requests()

    assert [item["task_id"] for item in payload["recent"][:2]] == [
        task_a.task_id,
        task_b.task_id,
    ]


def test_service_requests_dashboard_spillover_preview_honors_strategy_and_queue_support() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[_bundle("text-a", "llm_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    candidates = [
        {
            "bundle_id": "trusted-premium",
            "node_id": "node-trusted",
            "origin": "external",
            "supports_queue": True,
            "endpoint_ready": True,
            "pricing": {"input": 520},
            "rating": {"score": 0.99},
        },
        {
            "bundle_id": "budget-queue",
            "node_id": "node-budget",
            "origin": "external",
            "supports_queue": True,
            "endpoint_ready": True,
            "pricing": {"input": 310},
            "rating": {"score": 0.81},
        },
        {
            "bundle_id": "direct-only",
            "node_id": "node-direct",
            "origin": "external",
            "supports_queue": False,
            "endpoint_ready": True,
            "pricing": {"input": 120},
            "rating": {"score": 0.95},
        },
        {
            "bundle_id": "not-ready",
            "node_id": "node-cold",
            "origin": "external",
            "supports_queue": True,
            "endpoint_ready": False,
            "pricing": {"input": 280},
            "rating": {"score": 0.90},
        },
    ]

    service.update_operator_requests_policy(
        allow_spillover=True,
        dispatch_strategy="local_first",
        ready_endpoint_only=True,
    )
    local_first = service.operator_dashboard_requests(market_candidates=candidates)
    service.update_operator_requests_policy(
        allow_spillover=True,
        dispatch_strategy="market_first",
        ready_endpoint_only=True,
    )
    market_first = service.operator_dashboard_requests(market_candidates=candidates)
    service.update_operator_requests_policy(
        allow_spillover=True,
        dispatch_strategy="balanced",
        ready_endpoint_only=False,
    )
    balanced = service.operator_dashboard_requests(market_candidates=candidates)

    assert [item["bundle_id"] for item in local_first["market_spillover_preview"]] == [
        "trusted-premium",
        "budget-queue",
    ]
    assert [item["bundle_id"] for item in market_first["market_spillover_preview"]] == [
        "budget-queue",
        "trusted-premium",
    ]
    assert [item["bundle_id"] for item in balanced["market_spillover_preview"]] == [
        "not-ready",
        "trusted-premium",
        "budget-queue",
    ]


def test_service_rejects_invalid_registry_pricing_during_construction() -> None:
    with pytest.raises(ValidationError):
        HypervisorService(
            queue=InMemoryTaskQueue(),
            scheduler=Scheduler(),
            pricing={
                "unit": "q_per_1kk_tokens",
                "input": -1,
                "output": 0,
                "fixed_request": None,
            },
        )


def test_service_leaves_task_queued_when_resources_are_unavailable() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=1.0, ram_mb=1024, vram_mb={"gpu0": 512})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=1.0,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
            )
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    assert service.get_task(task.task_id).status == "queued"
    assert service.task_result(task.task_id) is None
    assert service.list_runtimes() == []


def test_service_retries_waiting_tasks_after_bundle_stop_frees_resources() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2.0, ram_mb=4096, vram_mb={"gpu0": 2048})
        ),
        bundles=[
            _bundle(
                "text-a",
                "llm_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.0,
                    steady_cpu=2.0,
                    per_request_cpu=0.0,
                ),
                warm_policy="always",
                priority_class=100,
            ),
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
                warm_policy="never",
                priority_class=80,
            ),
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "hello"}))
    queued_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    assert service.get_task(queued_task.task_id).status == "queued"

    service.stop_bundle("text-a")

    assert service.get_task(queued_task.task_id).status == "completed"
    assert service.task_result(queued_task.task_id) == {
        "ok": True,
        "task_type": "audio.transcribe",
    }


def test_service_start_bundle_passes_launch_mode_to_runtime_manager() -> None:
    class RecordingRuntimes:
        def __init__(self) -> None:
            self.launch_specs: list[dict] = []

        def start_runtime(self, launch_spec: dict) -> RuntimeHandle:
            self.launch_specs.append(dict(launch_spec))
            return RuntimeHandle(
                runtime_id="rt-1",
                command=list(launch_spec["command"]),
                status="starting",
                bundle_id=launch_spec.get("bundle_id"),
                metadata=dict(launch_spec.get("metadata", {})),
            )

        def list_runtimes(self) -> list[RuntimeHandle]:
            return []

    runtimes = RecordingRuntimes()
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[_bundle("text-a", "llm_text")],
        plugins=_registry(),
        runtimes=runtimes,
    )

    service.start_bundle("text-a")

    assert runtimes.launch_specs == [
        {
            "command": ["python", "-m", "http.server", "0"],
            "bundle_id": "text-a",
            "launch_mode": "managed_process",
        }
    ]


def test_service_respects_bundle_max_parallel_requests_for_running_tasks() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
            )
        ],
        plugins=_registry(),
        runtimes=[RuntimeHandle("rt-1", ["python", "-m", "http.server", "0"], "running", "whisper-a")],
    )

    first_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"})
    )
    service.queue.transition_status(first_task.task_id, "running")

    second_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"})
    )

    assert service.get_task(second_task.task_id).status == "queued"
    assert service.task_result(second_task.task_id) is None


def test_service_marks_task_failed_when_runtime_health_check_fails() -> None:
    registry = PluginRegistry()
    registry.register(UnhealthyFakePlugin())
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=1.0,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
            ).model_copy(update={"plugin_id": "fake-unhealthy"})
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    assert service.get_task(task.task_id).status == "failed"
    assert service.task_result(task.task_id) is None
    assert service.list_runtimes() == []
    assert service.resources.summary()["reserved"] == {
        "cpu": 0,
        "ram_mb": 0,
        "vram_mb": 0,
    }


def test_service_marks_task_failed_when_invoke_raises() -> None:
    registry = PluginRegistry()
    registry.register(FailingInvokePlugin())
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=1.0,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
            ).model_copy(update={"plugin_id": "fake-failing"})
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    assert service.get_task(task.task_id).status == "failed"
    assert service.task_result(task.task_id) is None
    assert service.resources.summary()["reserved"]["cpu"] == pytest.approx(0.5)


def test_service_retries_runtime_health_check_with_backoff_before_running_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PluginRegistry()
    plugin = RetryPolicyPlugin(
        health_outcomes=[False, True],
        health_backoff_seconds=0.25,
    )
    registry.register(plugin)
    sleep_calls: list[float] = []
    monkeypatch.setattr("aidn_hypervisor.service.time.sleep", sleep_calls.append)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"plugin_id": "fake-retry-policy"}
            )
        ],
        plugins=registry,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "whisper-a",
            )
        ],
    )

    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    runtime = service.list_runtimes()[0]

    assert service.get_task(task.task_id).status == "completed"
    assert plugin.health_attempts == 2
    assert sleep_calls == [0.25]
    assert runtime.health_status == "healthy"
    assert runtime.last_error is None


def test_service_retries_invoke_with_backoff_until_real_provider_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PluginRegistry()
    plugin = RetryPolicyPlugin(
        invoke_outcomes=[
            RuntimeError("connection refused"),
            {"ok": True, "task_type": "audio.transcribe"},
        ],
        invoke_backoff_seconds=0.5,
    )
    registry.register(plugin)
    sleep_calls: list[float] = []
    monkeypatch.setattr("aidn_hypervisor.service.time.sleep", sleep_calls.append)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"plugin_id": "fake-retry-policy"}
            )
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    runtime = service.list_runtimes()[0]

    assert service.get_task(task.task_id).status == "completed"
    assert service.task_result(task.task_id) == {
        "ok": True,
        "task_type": "audio.transcribe",
    }
    assert plugin.invoke_attempts == 2
    assert sleep_calls == [0.5]
    assert runtime.health_status == "healthy"
    assert runtime.last_error is None


def test_service_marks_runtime_unhealthy_when_retryable_invoke_errors_exhausted() -> None:
    registry = PluginRegistry()
    plugin = RetryPolicyPlugin(
        invoke_outcomes=[
            RuntimeError("connection refused"),
            RuntimeError("connection refused"),
            RuntimeError("connection refused"),
        ]
    )
    registry.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"plugin_id": "fake-retry-policy"}
            )
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    runtime = service.list_runtimes()[0]

    assert service.get_task(task.task_id).status == "failed"
    assert service.task_result(task.task_id) is None
    assert plugin.invoke_attempts == 3
    assert runtime.health_status == "unhealthy"
    assert runtime.last_error == "connection refused"


def test_service_places_bundle_into_cooldown_after_retryable_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PluginRegistry()
    plugin = CooldownPolicyPlugin(
        invoke_outcomes=[
            RuntimeError("connection refused"),
            RuntimeError("connection refused"),
            RuntimeError("connection refused"),
        ]
    )
    registry.register(plugin)
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    monkeypatch.setattr("aidn_hypervisor.service.time.sleep", lambda _: None)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"plugin_id": "fake-cooldown-policy"}
            )
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    failed_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"})
    )
    queued_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"})
    )

    runtime = service.list_runtimes()[0]

    assert service.get_task(failed_task.task_id).status == "failed"
    assert service.get_task(queued_task.task_id).status == "queued"
    assert plugin.invoke_attempts == 3
    assert runtime.health_status == "cooldown"
    assert service.bundle_state("whisper-a") == {
        "bundle_id": "whisper-a",
        "failure_streak": 1,
        "cooldown_until": 1060.0,
        "cooldown_reason": "connection refused",
        "drain_mode": False,
        "drain_reason": None,
    }
    assert service.queue_diagnostics() == [
        {
            "task_id": queued_task.task_id,
            "bundle_id": "whisper-a",
            "reason": "provider_cooldown",
        }
    ]


def test_service_resumes_queued_tasks_after_bundle_cooldown_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PluginRegistry()
    plugin = CooldownPolicyPlugin(
        invoke_outcomes=[
            RuntimeError("connection refused"),
            RuntimeError("connection refused"),
            RuntimeError("connection refused"),
            {"ok": True, "task_type": "audio.transcribe"},
        ]
    )
    registry.register(plugin)
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    monkeypatch.setattr("aidn_hypervisor.service.time.sleep", lambda _: None)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"plugin_id": "fake-cooldown-policy"}
            )
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"})
    )
    queued_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"})
    )

    current_time[0] = 1061.0
    service.process_pending()

    runtime = service.list_runtimes()[0]

    assert service.get_task(queued_task.task_id).status == "completed"
    assert service.task_result(queued_task.task_id) == {
        "ok": True,
        "task_type": "audio.transcribe",
    }
    assert plugin.invoke_attempts == 4
    assert runtime.health_status == "healthy"
    assert service.bundle_state("whisper-a") == {
        "bundle_id": "whisper-a",
        "failure_streak": 0,
        "cooldown_until": None,
        "cooldown_reason": None,
        "drain_mode": False,
        "drain_reason": None,
    }


def test_service_retry_bundle_clears_cooldown_and_reprocesses_waiting_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PluginRegistry()
    plugin = CooldownPolicyPlugin(
        invoke_outcomes=[
            RuntimeError("connection refused"),
            RuntimeError("connection refused"),
            RuntimeError("connection refused"),
            {"ok": True, "task_type": "audio.transcribe"},
        ]
    )
    registry.register(plugin)
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    monkeypatch.setattr("aidn_hypervisor.service.time.sleep", lambda _: None)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"plugin_id": "fake-cooldown-policy"}
            )
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"})
    )
    queued_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"})
    )

    summary = service.retry_bundle("whisper-a")

    assert service.get_task(queued_task.task_id).status == "completed"
    assert service.task_result(queued_task.task_id) == {
        "ok": True,
        "task_type": "audio.transcribe",
    }
    assert summary == {"queued": 0, "active": 0, "completed": 1, "failed": 1}
    assert service.bundle_state("whisper-a") == {
        "bundle_id": "whisper-a",
        "failure_streak": 0,
        "cooldown_until": None,
        "cooldown_reason": None,
        "drain_mode": False,
        "drain_reason": None,
    }


def test_service_disable_bundle_blocks_processing_until_reenabled() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    task = service.queue.enqueue(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    service._selected_bundles[task.task_id] = "whisper-a"

    result = service.set_bundle_enabled("whisper-a", False)
    service.process_pending()

    assert result == {"bundle_id": "whisper-a", "enabled": False, "status": "disabled"}
    assert service.get_task(task.task_id).status == "queued"

    result = service.set_bundle_enabled("whisper-a", True)
    service.process_pending()

    assert result == {"bundle_id": "whisper-a", "enabled": True, "status": "enabled"}
    assert service.get_task(task.task_id).status == "completed"


def test_service_drain_runtime_blocks_new_tasks_until_restart() -> None:
    runtimes = ProviderProcessManager()
    runtimes.restore_runtime(
        RuntimeHandle(
            "rt-1",
            ["python", "-m", "http.server", "0"],
            "running",
            "whisper-a",
            health_status="healthy",
        )
    )
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=runtimes,
    )
    task = service.queue.enqueue(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    service._selected_bundles[task.task_id] = "whisper-a"

    drain = service.drain_runtime("rt-1")
    service.process_pending()

    assert drain == {
        "runtime_id": "rt-1",
        "bundle_id": "whisper-a",
        "drain_mode": True,
        "status": "draining",
    }
    assert service.get_task(task.task_id).status == "queued"
    assert service.bundle_state("whisper-a") == {
        "bundle_id": "whisper-a",
        "failure_streak": 0,
        "cooldown_until": None,
        "cooldown_reason": None,
        "drain_mode": True,
        "drain_reason": "operator_requested",
    }
    assert service.queue_diagnostics() == [
        {
            "task_id": task.task_id,
            "bundle_id": "whisper-a",
            "reason": "runtime_draining",
        }
    ]

    restart = service.restart_runtime("rt-1")

    assert restart["bundle_id"] == "whisper-a"
    assert restart["status"] == "restarted"
    assert service.get_task(task.task_id).status == "completed"
    assert service.bundle_state("whisper-a") == {
        "bundle_id": "whisper-a",
        "failure_streak": 0,
        "cooldown_until": None,
        "cooldown_reason": None,
        "drain_mode": False,
        "drain_reason": None,
    }


def test_service_force_stop_runtime_removes_runtime_without_restarting() -> None:
    runtimes = ProviderProcessManager()
    runtimes.restore_runtime(
        RuntimeHandle(
            "rt-1",
            ["python", "-m", "http.server", "0"],
            "running",
            "whisper-a",
            health_status="healthy",
        )
    )
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=runtimes,
    )

    result = service.force_stop_runtime("rt-1")

    assert result == {
        "runtime_id": "rt-1",
        "bundle_id": "whisper-a",
        "status": "force_stopped",
    }
    assert service.list_runtimes() == []


def test_service_process_pending_fair_shares_between_bundles() -> None:
    registry = PluginRegistry()
    plugin = RecordingPlugin()
    registry.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("bundle-a", "speech_to_text").model_copy(
                update={"plugin_id": "fake-recording"}
            ),
            _bundle("bundle-b", "speech_to_text").model_copy(
                update={"plugin_id": "fake-recording"}
            ),
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )
    for bundle_id, marker in [
        ("bundle-a", "a1"),
        ("bundle-a", "a2"),
        ("bundle-b", "b1"),
    ]:
        task = service.queue.enqueue(
            TaskRequest(
                task_type="audio.transcribe",
                payload={"audio_ref": f"{marker}.wav", "marker": marker},
                mode="manual",
                bundle_override=bundle_id,
            )
        )
        service._selected_bundles[task.task_id] = bundle_id

    service.process_pending()

    assert plugin.invocations == ["a1", "b1", "a2"]


def test_service_create_allocation_starts_runtime_and_returns_endpoint() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"endpoint": "http://127.0.0.1:9000"}
            )
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text", owner_id="agent-a")
    )

    assert allocation == {
        "allocation_id": allocation["allocation_id"],
        "owner_id": "agent-a",
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": "rt-1",
        "endpoint": "http://127.0.0.1:9000",
        "status": "active",
    }
    assert service.list_runtimes()[0].runtime_id == "rt-1"


def test_service_capability_catalog_reports_fit_and_endpoint_readiness() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"endpoint": "http://127.0.0.1:9000"}
            )
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        node_id="node-a",
        operator_id="operator-a",
        can_host_custom_model=True,
        pricing={
            "unit": "q_per_1kk_tokens",
            "input": 12,
            "output": 18,
            "fixed_request": 4,
        },
    )

    catalog = service.capability_catalog(
        owner_id="agent-a",
        workload_type="speech_to_text",
    )

    assert catalog["resources"]["free"]["cpu"] == 8.0
    assert catalog == {
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
            "total": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 4096},
            "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
            "free": {"cpu": 8.0, "ram_mb": 16384, "vram_mb": 4096},
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


def test_service_capability_catalog_reports_wait_when_resources_are_busy() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    cold_start_ram_mb=512,
                    steady_cpu=1.5,
                    steady_ram_mb=1536,
                ),
            ).model_copy(update={"endpoint": "http://127.0.0.1:9000"})
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    service.resources.reserve("busy", cpu=2.0, ram_mb=2048, vram_mb=0)

    catalog = service.capability_catalog(
        owner_id="agent-a",
        workload_type="speech_to_text",
    )

    assert catalog["bundles"] == [
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
    ]


def test_service_capability_catalog_reports_missing_resource_delta() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=1.0,
                    cold_start_ram_mb=1024,
                    steady_cpu=2.0,
                    steady_ram_mb=2048,
                    steady_vram_mb=512,
                ),
            ).model_copy(update={"endpoint": "http://127.0.0.1:9000"})
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    service.resources.reserve("busy", cpu=1.5, ram_mb=1024, vram_mb=256)

    catalog = service.capability_catalog(owner_id="agent-a")

    assert catalog["bundles"][0]["required"] == {
        "cpu": 3.0,
        "ram_mb": 3072,
        "vram_mb": 512,
    }
    assert catalog["bundles"][0]["fit"] == {
        "fits": False,
        "cpu_shortfall": 2.5,
        "ram_mb_shortfall": 2048,
        "vram_mb_shortfall": 0,
    }


def test_service_register_model_install_job_tracks_requested_artifact(tmp_path) -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        model_store=FileModelStore(tmp_path),
    )

    job = service.request_model_install(
        provider_type="llama.cpp",
        model_id="phi-4-mini.gguf",
        source_url="https://example.invalid/models/phi-4-mini.gguf",
        requested_by="operator-a",
    )

    assert job["status"] == "queued"
    assert job["provider_type"] == "llama.cpp"
    assert job["model_id"] == "phi-4-mini.gguf"
    assert job["source_url"].endswith(".gguf")
    assert job["requested_by"] == "operator-a"
    assert job["last_error"] is None
    assert job["target_path"].endswith("llama.cpp\\phi-4-mini.gguf")


def test_service_process_model_installs_materializes_artifact_and_marks_job_completed(
    tmp_path,
) -> None:
    source_artifact = tmp_path / "phi-4-mini.gguf"
    source_artifact.write_text("model-bytes", encoding="utf-8")
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        model_store=FileModelStore(tmp_path / "models"),
    )

    install = service.request_model_install(
        provider_type="fake-managed",
        model_id="phi-4-mini.gguf",
        source_url=source_artifact.as_uri(),
        requested_by="operator-a",
    )

    processed = service.process_model_installs()

    assert [job["install_id"] for job in processed] == [install["install_id"]]
    assert processed[0]["status"] == "completed"
    assert processed[0]["last_error"] is None
    assert service.list_model_installs()[0]["status"] == "completed"
    assert (tmp_path / "models" / "fake-managed" / "phi-4-mini.gguf").read_text(
        encoding="utf-8"
    ) == "model-bytes"
    assert [event.event_type for event in service.event_journal(limit=3)] == [
        "model.install.requested",
        "model.install.started",
        "model.install.completed",
    ]


def test_service_process_model_installs_marks_job_failed_on_missing_artifact(
    tmp_path,
) -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        model_store=FileModelStore(tmp_path / "models"),
    )

    install = service.request_model_install(
        provider_type="fake-managed",
        model_id="missing.gguf",
        source_url=(tmp_path / "missing.gguf").as_uri(),
        requested_by="operator-a",
    )

    processed = service.process_model_installs()

    assert [job["install_id"] for job in processed] == [install["install_id"]]
    assert processed[0]["status"] == "failed"
    assert processed[0]["last_error"] is not None
    assert service.list_model_installs()[0]["status"] == "failed"
    assert not (tmp_path / "models" / "fake-managed" / "missing.gguf").exists()
    assert [event.event_type for event in service.event_journal(limit=3)] == [
        "model.install.requested",
        "model.install.started",
        "model.install.failed",
    ]


def test_service_registers_bundle_from_completed_install(tmp_path) -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        model_store=FileModelStore(tmp_path),
    )
    install = service.request_model_install(
        provider_type="fake-managed",
        model_id="phi-4-mini.gguf",
        source_url="https://example.invalid/models/phi-4-mini.gguf",
        requested_by="operator-a",
    )
    service.mark_model_install_completed(install["install_id"])

    bundle = service.register_bundle_from_install(
        install_id=install["install_id"],
        bundle_id="phi4-local",
        workload_type="llm_text",
        endpoint="http://127.0.0.1:8080",
    )

    assert bundle["bundle_id"] == "phi4-local"
    assert bundle["plugin_id"] == "fake-managed"
    assert service.bundles[-1].model_id == install["target_path"]
    assert service.list_model_installs()[0]["status"] == "registered"


def test_agent_can_discover_then_allocate_same_bundle() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"endpoint": "http://127.0.0.1:9000"}
            )
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    catalog = service.capability_catalog(
        owner_id="agent-a",
        workload_type="speech_to_text",
    )
    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text", owner_id="agent-a")
    )

    assert catalog["bundles"][0]["bundle_id"] == "whisper-a"
    assert catalog["bundles"][0]["can_allocate_now"] is True
    assert allocation["bundle_id"] == "whisper-a"
    assert allocation["endpoint"] == "http://127.0.0.1:9000"


def test_operator_can_install_register_and_expose_new_model(tmp_path) -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        model_store=FileModelStore(tmp_path),
        can_host_custom_model=True,
        pricing={
            "unit": "q_per_1kk_tokens",
            "input": 12,
            "output": 18,
            "fixed_request": 4,
        },
    )

    install = service.request_model_install(
        provider_type="fake-managed",
        model_id="phi-4-mini.gguf",
        source_url="https://example.invalid/models/phi-4-mini.gguf",
        requested_by="operator-a",
    )
    service.mark_model_install_completed(install["install_id"])
    service.register_bundle_from_install(
        install_id=install["install_id"],
        bundle_id="phi4-local",
        workload_type="llm_text",
        endpoint="http://127.0.0.1:8080",
    )

    catalog = service.capability_catalog(
        owner_id="agent-a",
        workload_type="llm_text",
        bundle_id="phi4-local",
    )

    assert catalog["node"]["can_host_custom_model"] is True
    assert catalog["node"]["pricing"]["input"] == 12
    assert catalog["bundles"] == [
        {
            "bundle_id": "phi4-local",
            "plugin_id": "fake-managed",
            "provider_type": "fake-managed",
            "model_id": install["target_path"],
            "workload_type": "llm_text",
            "enabled": True,
            "status": "stopped",
            "endpoint": "http://127.0.0.1:8080",
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
    ]


def test_service_release_allocation_marks_it_released() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"endpoint": "http://127.0.0.1:9000"}
            )
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text", owner_id="agent-a")
    )

    released = service.release_allocation(allocation["allocation_id"])

    assert released["allocation_id"] == allocation["allocation_id"]
    assert released["status"] == "released"
    assert service.get_allocation(allocation["allocation_id"])["status"] == "released"


def test_service_get_allocation_expires_lease_and_releases_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    steady_cpu=1.5,
                    steady_ram_mb=2048,
                    steady_vram_mb=1024,
                ),
            ).model_copy(update={"endpoint": "http://127.0.0.1:9000"})
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="speech_to_text",
            owner_id="agent-a",
            lease_seconds=1,
        )
    )

    current_time[0] += 2.0
    expired = service.get_allocation(allocation["allocation_id"])

    assert expired["status"] == "expired"
    assert service.resources.summary()["reserved"] == {
        "cpu": 0,
        "ram_mb": 0,
        "vram_mb": 0,
    }
    assert service.event_journal(limit=1)[0].event_type == "allocation.expired"


def test_service_create_allocation_rejects_when_runtime_residency_cannot_fit() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=1.0, ram_mb=1024, vram_mb={"gpu0": 256})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    steady_cpu=2.0,
                    steady_ram_mb=2048,
                    steady_vram_mb=512,
                ),
            ).model_copy(update={"endpoint": "http://127.0.0.1:9000"})
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    with pytest.raises(ValueError, match="insufficient resources"):
        service.create_allocation(
            AllocationRequest(workload_type="speech_to_text", owner_id="agent-a")
        )


def test_service_create_allocation_with_wait_policy_returns_pending() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    cold_start_ram_mb=512,
                    steady_cpu=1.5,
                    steady_ram_mb=1536,
                ),
            ).model_copy(update={"endpoint": "http://127.0.0.1:9000"})
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    service.resources.reserve("busy", cpu=2.0, ram_mb=2048, vram_mb=0)

    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="speech_to_text",
            owner_id="agent-a",
            policy="wait",
        )
    )

    assert allocation == {
        "allocation_id": allocation["allocation_id"],
        "owner_id": "agent-a",
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": None,
        "endpoint": None,
        "status": "pending",
        "reason": "insufficient_resources",
        "retry_after_seconds": 5,
        "next_attempt_at": allocation["next_attempt_at"],
    }


def test_service_get_allocation_activates_pending_wait_lease_when_resources_free() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    cold_start_ram_mb=512,
                    steady_cpu=1.0,
                    steady_ram_mb=1024,
                ),
            ).model_copy(update={"endpoint": "http://127.0.0.1:9000"})
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    service.resources.reserve("busy", cpu=2.0, ram_mb=2048, vram_mb=0)
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="speech_to_text",
            owner_id="agent-a",
            policy="wait",
        )
    )

    service.resources.release("busy")
    activated = service.get_allocation(allocation["allocation_id"])

    assert activated == {
        "allocation_id": allocation["allocation_id"],
        "owner_id": "agent-a",
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": "rt-1",
        "endpoint": "http://127.0.0.1:9000",
        "status": "active",
    }
    assert service.event_journal(limit=1)[0].event_type == "allocation.activated"


def test_service_pending_allocation_exposes_retry_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    cold_start_ram_mb=512,
                    steady_cpu=1.5,
                    steady_ram_mb=1536,
                ),
            ).model_copy(update={"endpoint": "http://127.0.0.1:9000"})
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    service.resources.reserve("busy", cpu=2.0, ram_mb=2048, vram_mb=0)

    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="speech_to_text",
            owner_id="agent-a",
            policy="wait",
        )
    )

    assert allocation["retry_after_seconds"] == 5
    assert allocation["next_attempt_at"] == datetime.fromtimestamp(
        current_time[0] + 5,
        timezone.utc,
    ).isoformat()


def test_service_create_allocation_rejects_when_owner_active_quota_is_exceeded() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(
                update={"endpoint": "http://127.0.0.1:9000"}
            )
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        max_active_allocations_per_owner=1,
    )
    service.create_allocation(
        AllocationRequest(workload_type="speech_to_text", owner_id="agent-a")
    )

    with pytest.raises(ValueError, match="owner active allocation quota exceeded"):
        service.create_allocation(
            AllocationRequest(workload_type="speech_to_text", owner_id="agent-a")
        )


def test_service_create_wait_allocation_rejects_when_owner_pending_quota_is_exceeded() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    cold_start_ram_mb=512,
                    steady_cpu=1.5,
                    steady_ram_mb=1536,
                ),
            ).model_copy(update={"endpoint": "http://127.0.0.1:9000"})
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        max_pending_allocations_per_owner=1,
    )
    service.resources.reserve("busy", cpu=2.0, ram_mb=2048, vram_mb=0)
    service.create_allocation(
        AllocationRequest(
            workload_type="speech_to_text",
            owner_id="agent-a",
            policy="wait",
        )
    )

    with pytest.raises(ValueError, match="owner pending allocation quota exceeded"):
        service.create_allocation(
            AllocationRequest(
                workload_type="speech_to_text",
                owner_id="agent-a",
                policy="wait",
            )
        )


def test_service_process_pending_exports_admission_decisions_to_event_journal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PluginRegistry()
    plugin = RecordingPlugin()
    registry.register(plugin)
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: 1_781_827_800.0)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("bundle-a", "speech_to_text").model_copy(
                update={"plugin_id": "fake-recording"}
            ),
            _bundle("bundle-b", "speech_to_text").model_copy(
                update={"plugin_id": "fake-recording"}
            ),
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )
    older_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "older.wav", "marker": "older"},
            priority=10,
            mode="manual",
            bundle_override="bundle-a",
        )
    )
    service._selected_bundles[older_task.task_id] = "bundle-a"
    newer_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "newer.wav", "marker": "newer"},
            priority=40,
            mode="manual",
            bundle_override="bundle-a",
        )
    )
    service._selected_bundles[newer_task.task_id] = "bundle-a"
    peer_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "peer.wav", "marker": "peer"},
            priority=30,
            mode="manual",
            bundle_override="bundle-b",
        )
    )
    service._selected_bundles[peer_task.task_id] = "bundle-b"
    service.queue.restore(
        [
            replace(service.get_task(older_task.task_id), created_at="2026-06-19T00:00:00+00:00"),
            replace(service.get_task(newer_task.task_id), created_at="2026-06-19T00:09:00+00:00"),
            replace(service.get_task(peer_task.task_id), created_at="2026-06-19T00:09:00+00:00"),
        ]
    )

    service.process_pending()

    admission_events = [
        event for event in service.event_journal() if event.event_type == "admission.selected"
    ]

    assert [event.task_id for event in admission_events] == [
        older_task.task_id,
        peer_task.task_id,
        newer_task.task_id,
    ]
    assert [event.bundle_id for event in admission_events] == [
        "bundle-a",
        "bundle-b",
        "bundle-a",
    ]
    assert [event.message for event in admission_events] == [
        "task selected for admission attempt",
        "task selected for admission attempt",
        "task selected for admission attempt",
    ]
    assert [event.details for event in admission_events] == [
        {
            "base_priority": 10,
            "aging_bonus": 100,
            "effective_priority": 110,
            "fair_share_round": 0,
            "admission_rank": 1,
            "selection_reason": "highest_effective_priority",
        },
        {
            "base_priority": 30,
            "aging_bonus": 10,
            "effective_priority": 40,
            "fair_share_round": 0,
            "admission_rank": 2,
            "selection_reason": "lowest_dispatch_count",
        },
        {
            "base_priority": 40,
            "aging_bonus": 10,
            "effective_priority": 50,
            "fair_share_round": 1,
            "admission_rank": 3,
            "selection_reason": "only_remaining_bundle",
        },
    ]


def test_service_admission_telemetry_reports_fair_share_priority_and_aging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: 1_781_827_800.0)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("bundle-a", "speech_to_text"),
            _bundle("bundle-b", "llm_text"),
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )
    older_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "older.wav"},
            priority=10,
            mode="manual",
            bundle_override="bundle-a",
        )
    )
    service._selected_bundles[older_task.task_id] = "bundle-a"
    newer_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "newer.wav"},
            priority=40,
            mode="manual",
            bundle_override="bundle-a",
        )
    )
    service._selected_bundles[newer_task.task_id] = "bundle-a"
    peer_task = service.queue.enqueue(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "peer"},
            priority=30,
            mode="manual",
            bundle_override="bundle-b",
        )
    )
    service._selected_bundles[peer_task.task_id] = "bundle-b"
    service.queue.restore(
        [
            replace(service.get_task(older_task.task_id), created_at="2026-06-19T00:00:00+00:00"),
            replace(service.get_task(newer_task.task_id), created_at="2026-06-19T00:09:00+00:00"),
            replace(service.get_task(peer_task.task_id), created_at="2026-06-19T00:09:00+00:00"),
        ]
    )

    telemetry = service.admission_telemetry()

    assert telemetry == [
        {
            "task_id": older_task.task_id,
            "bundle_id": "bundle-a",
            "base_priority": 10,
            "aging_bonus": 100,
            "effective_priority": 110,
            "fair_share_round": 0,
            "admission_rank": 1,
            "selection_reason": "highest_effective_priority",
        },
        {
            "task_id": peer_task.task_id,
            "bundle_id": "bundle-b",
            "base_priority": 30,
            "aging_bonus": 10,
            "effective_priority": 40,
            "fair_share_round": 0,
            "admission_rank": 2,
            "selection_reason": "lowest_dispatch_count",
        },
        {
            "task_id": newer_task.task_id,
            "bundle_id": "bundle-a",
            "base_priority": 40,
            "aging_bonus": 10,
            "effective_priority": 50,
            "fair_share_round": 1,
            "admission_rank": 3,
            "selection_reason": "only_remaining_bundle",
        },
    ]


def test_service_ages_waiting_task_priority_to_prevent_starvation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = PluginRegistry()
    plugin = RecordingPlugin()
    registry.register(plugin)
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle("bundle-a", "speech_to_text").model_copy(
                update={"plugin_id": "fake-recording"}
            ),
            _bundle("bundle-b", "speech_to_text").model_copy(
                update={"plugin_id": "fake-recording"}
            ),
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )
    older_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "older.wav", "marker": "older"},
            priority=10,
            mode="manual",
            bundle_override="bundle-a",
        )
    )
    service._selected_bundles[older_task.task_id] = "bundle-a"
    newer_task = service.queue.enqueue(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "newer.wav", "marker": "newer"},
            priority=70,
            mode="manual",
            bundle_override="bundle-b",
        )
    )
    service._selected_bundles[newer_task.task_id] = "bundle-b"
    service.queue.restore(
        [
            service.get_task(older_task.task_id).__class__(
                priority=older_task.priority,
                enqueue_index=older_task.enqueue_index,
                created_at="2026-06-19T00:00:00+00:00",
                task_id=older_task.task_id,
                request=older_task.request,
                status="queued",
            ),
            service.get_task(newer_task.task_id).__class__(
                priority=newer_task.priority,
                enqueue_index=newer_task.enqueue_index,
                created_at="2026-06-19T00:09:00+00:00",
                task_id=newer_task.task_id,
                request=newer_task.request,
                status="queued",
            ),
        ]
    )

    service.process_pending()

    assert plugin.invocations[0] == "older"


def test_service_evicts_idle_auto_runtime_under_resource_pressure() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2.0, ram_mb=4096, vram_mb={"gpu0": 2048})
        ),
        bundles=[
            _bundle(
                "text-a",
                "llm_text",
                resource_profile=ResourceProfile(
                    steady_cpu=2.0,
                ),
                warm_policy="auto",
                priority_class=100,
            ),
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
                warm_policy="never",
                priority_class=80,
            ),
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "hello"}))
    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    assert service.get_task(task.task_id).status == "completed"
    assert [runtime.bundle_id for runtime in service.list_runtimes()] == []


def test_service_keeps_idle_always_runtime_for_non_higher_priority_task() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2.0, ram_mb=4096, vram_mb={"gpu0": 2048})
        ),
        bundles=[
            _bundle(
                "text-a",
                "llm_text",
                resource_profile=ResourceProfile(
                    steady_cpu=2.0,
                ),
                warm_policy="always",
                priority_class=100,
            ),
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
                warm_policy="never",
                priority_class=80,
            ),
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "hello"}))
    task = service.submit(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "clip.wav"},
            priority=50,
        )
    )

    assert service.get_task(task.task_id).status == "queued"
    assert [runtime.bundle_id for runtime in service.list_runtimes()] == ["text-a"]


def test_service_evicts_idle_always_runtime_for_higher_priority_task() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2.0, ram_mb=4096, vram_mb={"gpu0": 2048})
        ),
        bundles=[
            _bundle(
                "text-a",
                "llm_text",
                resource_profile=ResourceProfile(
                    steady_cpu=2.0,
                ),
                warm_policy="always",
                priority_class=100,
            ),
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
                warm_policy="never",
                priority_class=80,
            ),
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "hello"}))
    task = service.submit(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "clip.wav"},
            priority=200,
        )
    )

    assert service.get_task(task.task_id).status == "completed"
    assert [runtime.bundle_id for runtime in service.list_runtimes()] == []


def test_service_respects_plugin_specific_concurrency_limit() -> None:
    registry = PluginRegistry()
    registry.register(ConcurrencyHintPlugin())
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
            ).model_copy(update={"plugin_id": "fake-concurrency-hint", "max_parallel_requests": 3})
        ],
        plugins=registry,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "whisper-a",
            )
        ],
    )

    first_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"})
    )
    service.queue.transition_status(first_task.task_id, "running")

    second_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"})
    )

    assert service.get_task(second_task.task_id).status == "queued"


def test_service_reports_concurrency_limit_as_queue_diagnostic_reason() -> None:
    registry = PluginRegistry()
    registry.register(ConcurrencyHintPlugin())
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
            ).model_copy(update={"plugin_id": "fake-concurrency-hint", "max_parallel_requests": 3})
        ],
        plugins=registry,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["python", "-m", "http.server", "0"],
                "running",
                "whisper-a",
            )
        ],
    )

    first_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"})
    )
    service.queue.transition_status(first_task.task_id, "running")
    second_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"})
    )

    diagnostics = service.queue_diagnostics()

    assert diagnostics == [
        {
            "task_id": second_task.task_id,
            "bundle_id": "whisper-a",
            "reason": "concurrency_limit",
        }
    ]


def test_service_attached_service_provider_hint_ignores_cold_start_headroom() -> None:
    registry = PluginRegistry()
    plugin = StubOllamaPlugin()
    registry.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=1.5, ram_mb=2048, vram_mb={"gpu0": 0})
        ),
        bundles=[
            BundleConfig(
                bundle_id="phi4-ollama",
                plugin_id="ollama",
                provider_type="ollama",
                workload_type="llm_text",
                model_id="phi4",
                launch_mode="attached_service",
                endpoint="http://127.0.0.1:11434",
                device_affinity="cpu",
                resource_profile=ResourceProfile(
                    cold_start_cpu=4.0,
                    cold_start_ram_mb=8192,
                    steady_cpu=1.0,
                    steady_ram_mb=1024,
                    per_request_cpu=0.5,
                    per_request_ram_mb=256,
                ),
                warm_policy="auto",
            )
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "Hi"})
    )

    assert service.get_task(task.task_id).status == "completed"
    assert service.resources.summary()["reserved"] == {
        "cpu": pytest.approx(1.0),
        "ram_mb": 1024,
        "vram_mb": 0,
    }


def test_service_real_ollama_provider_hint_limits_third_parallel_request() -> None:
    registry = PluginRegistry()
    plugin = StubOllamaPlugin()
    registry.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=6.0, ram_mb=8192, vram_mb={"gpu0": 0})
        ),
        bundles=[
            BundleConfig(
                bundle_id="phi4-ollama",
                plugin_id="ollama",
                provider_type="ollama",
                workload_type="llm_text",
                model_id="phi4",
                launch_mode="attached_service",
                endpoint="http://127.0.0.1:11434",
                device_affinity="cpu",
                resource_profile=ResourceProfile(
                    steady_cpu=1.0,
                    per_request_cpu=0.5,
                ),
                warm_policy="auto",
                max_parallel_requests=4,
            )
        ],
        plugins=registry,
        runtimes=[
            RuntimeHandle(
                "rt-1",
                ["ollama", "serve"],
                "running",
                "phi4-ollama",
                metadata={"endpoint": "http://127.0.0.1:11434", "model_id": "phi4"},
            )
        ],
    )

    first_task = service.queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "one"})
    )
    service._selected_bundles[first_task.task_id] = "phi4-ollama"
    service.queue.transition_status(first_task.task_id, "running")
    second_task = service.queue.enqueue(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "two"})
    )
    service._selected_bundles[second_task.task_id] = "phi4-ollama"
    service.queue.transition_status(second_task.task_id, "running")

    third_task = service.submit(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "three"})
    )

    assert service.get_task(third_task.task_id).status == "queued"


def test_service_reports_insufficient_resources_as_queue_diagnostic_reason() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=1.0, ram_mb=1024, vram_mb={"gpu0": 512})
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=1.0,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
            )
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    diagnostics = service.queue_diagnostics()

    assert diagnostics == [
        {
            "task_id": task.task_id,
            "bundle_id": "whisper-a",
            "reason": "insufficient_resources",
        }
    ]


def test_service_reports_eviction_policy_blocked_for_idle_always_runtime() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2.0, ram_mb=4096, vram_mb={"gpu0": 2048})
        ),
        bundles=[
            _bundle(
                "text-a",
                "llm_text",
                resource_profile=ResourceProfile(steady_cpu=2.0),
                warm_policy="always",
                priority_class=100,
            ),
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
                warm_policy="never",
                priority_class=80,
            ),
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "hello"}))
    blocked_task = service.submit(
        TaskRequest(
            task_type="audio.transcribe",
            payload={"audio_ref": "clip.wav"},
            priority=50,
        )
    )

    diagnostics = service.queue_diagnostics()

    assert diagnostics == [
        {
            "task_id": blocked_task.task_id,
            "bundle_id": "whisper-a",
            "reason": "eviction_policy_blocked",
        }
    ]


def test_service_process_pending_returns_summary_counts() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=2.0, ram_mb=4096, vram_mb={"gpu0": 2048})
        ),
        bundles=[
            _bundle(
                "text-a",
                "llm_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.0,
                    steady_cpu=2.0,
                    per_request_cpu=0.0,
                ),
                warm_policy="always",
                priority_class=100,
            ),
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
                warm_policy="never",
                priority_class=80,
            ),
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "hello"}))
    waiting_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    initial = service.process_pending()
    service.stop_bundle("text-a")
    summary = service.process_pending()

    assert service.get_task(waiting_task.task_id).status == "completed"
    assert initial["queued"] == 1
    assert summary["queued"] == 0
    assert summary["completed"] >= 2


def test_service_executes_llm_task_via_ollama_plugin() -> None:
    registry = PluginRegistry()
    plugin = StubOllamaPlugin()
    registry.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 0})
        ),
        bundles=[
            BundleConfig(
                bundle_id="phi4-ollama",
                plugin_id="ollama",
                provider_type="ollama",
                workload_type="llm_text",
                model_id="phi4",
                launch_mode="attached_service",
                endpoint="http://127.0.0.1:11434",
                device_affinity="cpu",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
                warm_policy="auto",
            )
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "Hi"})
    )

    runtime = service.list_runtimes()[0]

    assert service.get_task(task.task_id).status == "completed"
    assert service.task_result(task.task_id) == {
        "ok": True,
        "task_type": "llm_text.generate",
        "model_id": "phi4",
        "output_text": "Hello from Ollama",
        "done": True,
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "fixed_request_count": 1,
            "measurement_kind": "estimated",
            "measurement_source": "provider_api_partial",
        },
        "raw": {"response": "Hello from Ollama", "done": True},
    }
    assert runtime.metadata == {
        "endpoint": "http://127.0.0.1:11434",
        "model_id": "phi4",
    }
    assert plugin.calls == [
        ("GET", "http://127.0.0.1:11434/api/tags", None),
        (
            "POST",
            "http://127.0.0.1:11434/api/generate",
            {"model": "phi4", "prompt": "Hi", "stream": False},
        ),
    ]


def test_service_executes_transcription_task_via_whisper_plugin() -> None:
    registry = PluginRegistry()
    plugin = StubWhisperPlugin()
    registry.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 0})
        ),
        bundles=[
            BundleConfig(
                bundle_id="whisper-local",
                plugin_id="whisper",
                provider_type="whisper",
                workload_type="speech_to_text",
                model_id="large-v3",
                launch_mode="attached_service",
                endpoint="http://127.0.0.1:9000",
                device_affinity="cpu",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
                warm_policy="auto",
            )
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "C:/audio/clip.wav"})
    )

    runtime = service.list_runtimes()[0]

    assert service.get_task(task.task_id).status == "completed"
    assert service.task_result(task.task_id) == {
        "ok": True,
        "task_type": "audio.transcribe",
        "model_id": "large-v3",
        "text": "hello from whisper",
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "fixed_request_count": 1,
            "measurement_kind": "estimated",
            "measurement_source": "provider_request",
        },
        "raw": {"text": "hello from whisper"},
    }
    assert runtime.metadata == {
        "endpoint": "http://127.0.0.1:9000",
        "model_id": "large-v3",
    }
    assert plugin.calls == [
        ("GET", "http://127.0.0.1:9000/health", None),
        (
            "POST",
            "http://127.0.0.1:9000/v1/audio/transcriptions",
            {"model": "large-v3", "audio_ref": "C:/audio/clip.wav"},
        ),
    ]


def test_service_executes_llm_task_via_llamacpp_plugin() -> None:
    registry = PluginRegistry()
    plugin = StubLlamaCppPlugin()
    registry.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 0})
        ),
        bundles=[
            BundleConfig(
                bundle_id="phi4-llamacpp",
                plugin_id="llama.cpp",
                provider_type="llama.cpp",
                workload_type="llm_text",
                model_id="C:/models/phi4.gguf",
                launch_mode="managed_process",
                endpoint="http://127.0.0.1:8080",
                device_affinity="cpu",
                resource_profile=ResourceProfile(
                    cold_start_cpu=0.5,
                    steady_cpu=0.5,
                    per_request_cpu=0.5,
                ),
                warm_policy="auto",
            )
        ],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "Hi"})
    )

    runtime = service.list_runtimes()[0]

    assert service.get_task(task.task_id).status == "completed"
    assert service.task_result(task.task_id) == {
        "ok": True,
        "task_type": "llm_text.generate",
        "model_id": "C:/models/phi4.gguf",
        "output_text": "hello from llama.cpp",
        "usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "fixed_request_count": 1,
            "measurement_kind": "estimated",
            "measurement_source": "provider_api_partial",
        },
        "raw": {"content": "hello from llama.cpp"},
    }
    assert runtime.command == [
        "llama-server",
        "--model",
        "C:/models/phi4.gguf",
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
    ]
    assert runtime.metadata == {
        "endpoint": "http://127.0.0.1:8080",
        "model_id": "C:/models/phi4.gguf",
    }
    assert plugin.calls == [
        ("GET", "http://127.0.0.1:8080/health", None),
        (
            "POST",
            "http://127.0.0.1:8080/completion",
            {"prompt": "Hi", "stream": False},
        ),
    ]
