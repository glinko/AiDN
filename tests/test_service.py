from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from aidn_hypervisor.domain.models import (
    AllocationRequest,
    BundleConfig,
    NodeCapacity,
    ResourceProfile,
    TaskRequest,
)
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.model_store import FileModelStore
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.plugins.ollama import OllamaPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.plugins.whisper import WhisperPlugin
from aidn_hypervisor.process_manager import ProviderProcessManager, RuntimeHandle
from aidn_hypervisor.providers.executor import (
    ControlledFilesystemProviderInstallationExecutor,
    RecordedProviderInstallationExecutor,
)
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.remote_endpoints.service import RemoteEndpointService
from aidn_hypervisor.remote_endpoints.store import RemoteEndpointStore
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore
from aidn_hypervisor.state import JournalEvent
from aidn_hypervisor.wallet_identity import wallet_identity_registration_payload


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
        self.invoke_outcomes = list(invoke_outcomes or [{"ok": True, "task_type": "audio.transcribe"}])
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


class RecordingStateStore:
    def __init__(self) -> None:
        self.snapshots = []

    def save(self, snapshot) -> None:
        self.snapshots.append(snapshot)


class CustomProviderInstallationExecutor(RecordedProviderInstallationExecutor):
    executor_id = "custom-test-executor"


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


def test_service_create_runtime_binding_projects_and_persists_compatibility_bundle(
    tmp_path,
) -> None:
    from aidn_hypervisor.bundle_registry import FileBundleRegistry

    bundle_registry = FileBundleRegistry(tmp_path / "bundles.json")
    state_store = RecordingStateStore()
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        bundle_registry=bundle_registry,
        state_store=state_store,
    )

    attached = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    models = service.discover_provider_models(attached["provider_instance_id"])
    state_store.snapshots.clear()

    binding = service.create_runtime_binding(
        model_deployment_id=models[0]["model_deployment_id"],
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    compatibility_bundle = next(
        bundle for bundle in service.bundles if bundle.bundle_id == binding["compatibility_bundle_id"]
    )
    persisted_bundle = next(
        bundle
        for bundle in bundle_registry.load(service.plugins)
        if bundle.bundle_id == binding["compatibility_bundle_id"]
    )

    assert isinstance(service.provider_inventory, ProviderInventoryService)
    assert compatibility_bundle.plugin_id == "fake-managed"
    assert compatibility_bundle.provider_type == "fake"
    assert compatibility_bundle.workload_type == "llm.chat"
    assert compatibility_bundle.model_id == "fake-model"
    assert compatibility_bundle.endpoint == "http://127.0.0.1:9999"
    assert persisted_bundle.bundle_id == compatibility_bundle.bundle_id
    assert len(state_store.snapshots) == 1


def test_service_create_runtime_binding_reuses_compatibility_bundle_for_same_logical_binding(
    tmp_path,
) -> None:
    from aidn_hypervisor.bundle_registry import FileBundleRegistry

    bundle_registry = FileBundleRegistry(tmp_path / "bundles.json")
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        bundle_registry=bundle_registry,
    )

    attached = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    model = service.discover_provider_models(attached["provider_instance_id"])[0]

    first = service.create_runtime_binding(
        model_deployment_id=model["model_deployment_id"],
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    second = service.create_runtime_binding(
        model_deployment_id=model["model_deployment_id"],
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    matching_bundles = [bundle for bundle in service.bundles if bundle.bundle_id == first["compatibility_bundle_id"]]
    persisted_matching_bundles = [
        bundle
        for bundle in bundle_registry.load(service.plugins)
        if bundle.bundle_id == first["compatibility_bundle_id"]
    ]

    assert first["runtime_binding_id"] == second["runtime_binding_id"]
    assert first["compatibility_bundle_id"] == second["compatibility_bundle_id"]
    assert len(matching_bundles) == 1
    assert len(persisted_matching_bundles) == 1


def test_service_create_bundle_revision_preserves_source_and_persists_hash(tmp_path) -> None:
    from aidn_hypervisor.bundle_registry import FileBundleRegistry

    bundle_registry = FileBundleRegistry(tmp_path / "bundles.json")
    source = _bundle("whisper-a", "speech_to_text", priority_class=50)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[source],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        bundle_registry=bundle_registry,
    )

    created = service.create_bundle_revision(
        source_bundle_id="whisper-a",
        bundle_id="whisper-b",
        overrides={"priority_class": 90},
        enabled=False,
    )

    assert created["bundle_id"] == "whisper-b"
    assert created["revision"] == 2
    assert created["revision_of"] == "whisper-a"
    assert created["bundle_hash"].startswith("sha256:")
    assert created["enabled"] is False
    assert next(bundle for bundle in service.bundles if bundle.bundle_id == "whisper-a").priority_class == 50
    assert next(bundle for bundle in service.bundles if bundle.bundle_id == "whisper-b").priority_class == 90
    assert bundle_registry.load(service.plugins)[1].bundle_hash == created["bundle_hash"]

    with pytest.raises(ValueError, match="Unknown Bundle revision fields"):
        service.create_bundle_revision(
            source_bundle_id="whisper-a",
            bundle_id="whisper-c",
            overrides={"not_a_bundle_field": True},
        )
    assert all(bundle.bundle_id != "whisper-c" for bundle in service.bundles)

    with pytest.raises(ValueError, match="Immutable Bundle revision fields"):
        service.create_bundle_revision(
            source_bundle_id="whisper-a",
            bundle_id="whisper-d",
            overrides={"revision": 99},
        )
    assert all(bundle.bundle_id != "whisper-d" for bundle in service.bundles)


def test_provider_inventory_survives_state_restore() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    attached = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    models = service.discover_provider_models(attached["provider_instance_id"])
    binding = service.create_runtime_binding(
        model_deployment_id=models[0]["model_deployment_id"],
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    restored = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=service.plugins,
        runtimes=ProviderProcessManager(),
    )
    restored.restore_state(service.snapshot_state())

    assert restored.list_provider_instances()[0]["display_name"] == "Local Fake"
    assert restored.list_model_deployments()[0]["provider_instance_id"] == attached["provider_instance_id"]
    assert restored.list_runtime_bindings()[0]["runtime_binding_id"] == binding["runtime_binding_id"]
    assert any(
        bundle.bundle_id == binding["compatibility_bundle_id"]
        for bundle in restored.bundles
    )


def test_provider_artifact_materialization_survives_state_restore(tmp_path) -> None:
    executor = ControlledFilesystemProviderInstallationExecutor(tmp_path / "executor-root")
    inventory = ProviderInventoryService(
        plugins=_registry(),
        store=InMemoryProviderInventoryStore(),
        installation_executor=executor,
    )
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        provider_inventory=inventory,
    )
    attached = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    executor.stage_local_artifact(
        relative_path="models/model.gguf",
        content_bytes=b"model",
    )
    artifact = executor.promote_local_artifact_to_model_store(relative_path="models/model.gguf")
    artifact_set = executor.create_model_artifact_set(
        display_name="Model",
        files=[
            {
                "relative_path": "weights/model.gguf",
                "artifact_id": artifact.artifact_id,
                "role": "WEIGHTS",
            }
        ],
    )
    materialization = service.materialize_model_artifact_set(
        provider_instance_id=attached["provider_instance_id"],
        artifact_set_id=artifact_set.artifact_set_id,
        destination="models",
    )

    restored = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=service.plugins,
        runtimes=ProviderProcessManager(),
        provider_inventory=ProviderInventoryService(
            plugins=service.plugins,
            store=InMemoryProviderInventoryStore(),
            installation_executor=executor,
        ),
    )
    restored.restore_state(service.snapshot_state())

    assert restored.list_model_artifact_materializations() == [materialization]


def test_restored_provider_inventory_resolves_runtime_binding_bundle_hash() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    attached = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    model = service.discover_provider_models(attached["provider_instance_id"])[0]
    binding = service.create_runtime_binding(
        model_deployment_id=model["model_deployment_id"],
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    original_hash = service.bundle_hash_for_runtime_binding(binding["runtime_binding_id"])

    restored = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=service.plugins,
        runtimes=ProviderProcessManager(),
    )
    restored.restore_state(service.snapshot_state())

    assert restored.bundle_hash_for_runtime_binding(binding["runtime_binding_id"]) == original_hash
    assert restored.bundle_for_runtime_binding(binding["runtime_binding_id"]).endpoint == "http://127.0.0.1:9999"


def test_service_bundle_for_runtime_binding_delegates_to_provider_inventory() -> None:
    expected_bundle = _bundle("bundle-rtb-1", "llm.chat")

    class FakeProviderInventory:
        def bundle_config_for_runtime_binding(self, runtime_binding_id: str) -> BundleConfig:
            assert runtime_binding_id == "rtb-1"
            return expected_bundle

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        provider_inventory=FakeProviderInventory(),
    )

    bundle = service.bundle_for_runtime_binding("rtb-1")

    assert bundle == expected_bundle


def test_service_bundle_hash_for_runtime_binding_delegates_to_provider_inventory() -> None:
    class FakeProviderInventory:
        def bundle_hash_for_runtime_binding(self, runtime_binding_id: str) -> str:
            assert runtime_binding_id == "rtb-1"
            return "bundle-hash-rtb-1"

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        provider_inventory=FakeProviderInventory(),
    )

    bundle_hash = service.bundle_hash_for_runtime_binding("rtb-1")

    assert bundle_hash == "bundle-hash-rtb-1"


def test_service_build_provider_installation_plan_preview() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    plan = service.build_provider_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
    )

    assert plan["plan_id"] == "plan-fake-managed"
    assert plan["plugin_id"] == "fake-managed"


def test_service_prepares_ai_assisted_installation_review_from_configured_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The service façade must use the configured plan path, not a fake path."""

    from aidn_hypervisor.installation_onboarding import (
        InstallationOnboardingPlan,
        read_installation_plan,
        write_installation_plan,
    )

    plan_path = tmp_path / "installation-plan.json"
    monkeypatch.setenv("AIDN_INSTALLATION_PLAN_PATH", str(plan_path))
    registry = PluginRegistry()
    registry.register(LlamaCppPlugin())
    write_installation_plan(
        plan_path,
        InstallationOnboardingPlan(
            setup_mode="ai_assisted",
            provider="llama.cpp",
            model_id="org/model",
            model_source="https://example.test/model.gguf",
            endpoint_action="draft",
        ),
    )
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )
    plan = read_installation_plan(plan_path)

    prepared = service.apply_installation_plan(
        plan_hash=str(plan["plan_hash"]),
        actor="operator-test",
        idempotency_key="install-1",
    )

    assert prepared["status"] == "PROVIDER_REVIEW_REQUIRED"
    assert prepared["next_action"] == "approve_provider_installation"
    assert prepared["application"]["provider"]["plugin_id"] == "llama.cpp"
    workflow = service.installation_plan()["workflow"]
    assert workflow["next_action"]["id"] == "approve_provider_installation"
    assert workflow["stages"][0]["state"] == "REVIEW_REQUIRED"
    assert any(
        event.event_type == "installation.plan.review_prepared"
        for event in service.event_journal()
    )


def test_service_queues_selected_model_as_a_second_explicit_setup_step(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aidn_hypervisor.installation_onboarding import (
        InstallationOnboardingPlan,
        read_installation_plan,
        write_installation_plan,
    )

    plan_path = tmp_path / "installation-plan.json"
    monkeypatch.setenv("AIDN_INSTALLATION_PLAN_PATH", str(plan_path))
    registry = PluginRegistry()
    registry.register(LlamaCppPlugin())
    write_installation_plan(
        plan_path,
        InstallationOnboardingPlan(
            setup_mode="ai_assisted",
            provider="llama.cpp",
            model_id="org/model",
            model_source="https://example.test/model.gguf",
            endpoint_action="draft",
        ),
    )
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )
    monkeypatch.setattr(
        service,
        "list_provider_instances",
        lambda: [{"plugin_id": "llama.cpp", "status": "attached"}],
    )
    current = read_installation_plan(plan_path)
    queued = service.apply_installation_plan(
        plan_hash=str(current["plan_hash"]),
        actor="operator-test",
        idempotency_key="model-1",
        action="request_model_install",
    )

    assert queued["status"] == "MODEL_INSTALL_QUEUED"
    assert queued["application"]["model"]["status"] == "QUEUED"
    assert queued["application"]["model"]["install_id"]
    assert queued["workflow"]["next_action"]["id"] == "wait_model_install"
    service.mark_model_install_completed(queued["application"]["model"]["install_id"])
    bundle = service.apply_installation_plan(
        plan_hash=str(queued["plan_hash"]),
        actor="operator-test",
        idempotency_key="bundle-1",
        action="create_bundle",
    )
    assert bundle["status"] == "BUNDLE_CREATED"
    assert bundle["application"]["bundle"]["bundle_id"].startswith("bundle-steward-")
    assert bundle["workflow"]["next_action"]["id"] == "create_private_endpoint"
    replay = service.apply_installation_plan(
        plan_hash=str(bundle["plan_hash"]),
        actor="operator-test",
        idempotency_key="bundle-1",
        action="create_bundle",
    )
    assert replay["application"]["bundle"]["bundle_id"] == bundle["application"]["bundle"]["bundle_id"]


def test_service_managed_provider_runtime_lifecycle_delegates_through_facade() -> None:
    class FakeProviderInventory:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def install_provider_runtime(self, **payload) -> dict:
            self.calls.append(("install", payload))
            return {"plugin_id": payload["plugin_id"], "status": "SUCCEEDED"}

        def change_provider_runtime(self, **payload) -> dict:
            self.calls.append(("change", payload))
            return {"plugin_id": payload["plugin_id"], "status": "SUCCEEDED"}

        def remove_provider_runtime(self, **payload) -> dict:
            self.calls.append(("remove", payload))
            return {"plugin_id": payload["plugin_id"], "status": "REMOVED"}

        def detach_provider_instance(self, provider_instance_id: str) -> dict:
            self.calls.append(("detach", {"provider_instance_id": provider_instance_id}))
            return {"provider_instance_id": provider_instance_id, "status": "DETACHED"}

    inventory = FakeProviderInventory()
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        provider_inventory=inventory,
    )
    configuration = {"runtime_version": "0.27.1"}

    assert service.install_provider_runtime(
        plugin_id="vllm",
        configuration=configuration,
        operator_note="install",
        upgrade_acknowledged=True,
    )["status"] == "SUCCEEDED"
    assert service.change_provider_runtime(
        plugin_id="vllm",
        configuration=configuration,
        operator_note="change",
    )["status"] == "SUCCEEDED"
    assert service.remove_provider_runtime(plugin_id="vllm")["status"] == "REMOVED"
    assert service.detach_provider_instance("pi-attached")["status"] == "DETACHED"
    assert [name for name, _payload in inventory.calls] == ["install", "change", "remove", "detach"]
    assert inventory.calls[0][1]["operator_note"] == "install"
    assert inventory.calls[0][1]["upgrade_acknowledged"] is True


def test_provider_installation_approval_and_job_survive_snapshot_restore() -> None:
    state_store = RecordingStateStore()
    installation_executor = CustomProviderInstallationExecutor()
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        state_store=state_store,
        provider_inventory=ProviderInventoryService(
            plugins=_registry(),
            store=InMemoryProviderInventoryStore(),
            installation_executor=installation_executor,
        ),
    )

    approval = service.approve_provider_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
        operator_note="approved for local test",
    )
    snapshot = service.snapshot_state()

    restored = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=service.plugins,
        runtimes=ProviderProcessManager(),
        state_store=state_store,
        provider_inventory=ProviderInventoryService(
            plugins=service.plugins,
            store=InMemoryProviderInventoryStore(),
            installation_executor=installation_executor,
        ),
    )
    restored.restore_state(snapshot)
    job = restored.apply_provider_installation_approval(approval["approval_id"])

    restored_approval = restored.list_provider_installation_approvals()[0]
    restored_job = restored.list_provider_installation_jobs()[0]
    restored_instance = restored.list_provider_instances()[0]
    assert restored_approval["approval_id"] == approval["approval_id"]
    assert restored_approval["operator_note"] == "approved for local test"
    assert restored_job["job_id"] == job["job_id"]
    assert restored_job["status"] == "SUCCEEDED"
    assert restored_job["executor_id"] == "custom-test-executor"
    assert job["executor_id"] == "custom-test-executor"
    assert restored_instance["provider_instance_id"] == job["provider_instance_id"]
    assert restored_instance["plugin_id"] == "fake-managed"
    assert restored_instance["operational_state"] == "created"
    # Snapshot cadence includes scheduler/resource transitions. Persisted
    # lifecycle evidence, rather than an implementation-specific count, is
    # the contract being verified here.
    assert len(state_store.snapshots) >= 3
    assert state_store.snapshots[0].provider_installation_approvals[0].approval_id == (approval["approval_id"])
    persisted_job = state_store.snapshots[-1].provider_installation_jobs[0]
    persisted_instance = state_store.snapshots[-1].provider_instances[0]
    assert persisted_job.job_id == job["job_id"]
    assert persisted_job.executor_id == "custom-test-executor"
    assert persisted_instance.provider_instance_id == job["provider_instance_id"]
    assert persisted_instance.plugin_id == "fake-managed"
    approval_snapshot = next(
        candidate
        for candidate in state_store.snapshots
        if candidate.provider_installation_approvals
        and candidate.provider_installation_approvals[0].approval_id == approval["approval_id"]
        and not candidate.provider_installation_jobs
    )
    assert approval_snapshot.provider_installation_approvals[0].approval_id == approval["approval_id"]


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

    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))

    assert service.selected_bundle_id(task.task_id) == "preferred-whisper"


def test_service_submit_uses_active_allocation_bundle_for_routing() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("leased-text", "llm_text").model_copy(update={"endpoint": "http://127.0.0.1:8080"})],
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
        service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))


def test_service_exposes_canonical_overlay_inventory() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[
            _bundle("text-a", "llm_text"),
            _bundle("whisper-a", "speech_to_text"),
        ],
        runtimes=[
            RuntimeHandle(
                runtime_id="rt-1",
                command=["whisper"],
                status="running",
                bundle_id="whisper-a",
                health_status="healthy",
            )
        ],
    )
    private_key = Ed25519PrivateKey.generate()
    public_key = f"ed25519:{private_key.public_key().public_bytes_raw().hex()}"
    registration_nonce = "nonce-1"
    signature = private_key.sign(
        wallet_identity_registration_payload(
            wallet_id="wallet-consumer",
            public_key=public_key,
            registration_nonce=registration_nonce,
        )
    ).hex()
    service.register_wallet_identity(
        wallet_id="wallet-consumer",
        public_key=public_key,
        registration_nonce=registration_nonce,
        signature=f"ed25519:{signature}",
    )

    payload = service.canonical_overlay_inventory()

    assert "services" in payload
    assert "capabilities" in payload
    assert "runtimes" in payload
    assert "compatibility" in payload
    assert "feature_profiles" in payload
    assert "limit_profiles" in payload
    assert "implementation_profiles" in payload
    assert "wallet_identities" in payload
    assert "registry_objects" in payload
    assert payload["services"][0]["kind"] == "compute"
    assert payload["capabilities"][0]["capability_definition_hash"].startswith("sha256:")
    assert payload["wallet_identities"][0]["wallet_id"] == "wallet-consumer"
    assert {item["object_type"] for item in payload["registry_objects"]} == {"wallet_identity", "capability_definition"}


def test_service_executes_task_via_proxy_endpoint_when_endpoint_constraint_is_provided() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
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


def test_service_proxy_paid_session_opens_upstream_session_lazily_and_reuses_it() -> None:
    class StubPaidRemoteHypervisorTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict | None]] = []

        def request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
            self.calls.append((method, url, payload))
            if method == "POST" and url == "http://remote-hv/api/v1/endpoints/ep-remote/sessions":
                return {
                    "session": {
                        "session_id": "remote-session-1",
                        "opened_at": "2026-07-02T00:00:00+00:00",
                    }
                }
            if method == "POST" and url == "http://remote-hv/tasks":
                return {
                    "task_id": f"remote-task-{sum(1 for call in self.calls if call[1] == 'http://remote-hv/tasks')}",
                    "status": "queued",
                    "priority": 50,
                    "task_type": "llm_text.generate",
                    "bundle_id": "remote-text",
                }
            if method == "GET" and url.startswith("http://remote-hv/tasks/remote-task-"):
                return {
                    "task_id": url.rsplit("/", 1)[-1],
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("text-a", "llm_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    endpoint_service = EndpointService(EndpointStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    session_service = SessionService(SessionStore())
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
        session_policy={
            "minimum_deposit": 10.0,
            "recommended_deposit": 25.0,
            "max_concurrent_sessions": 1,
        },
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
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
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    local_session = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id="node-local",
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    service.endpoint_service = endpoint_service
    service.remote_endpoint_service = remote_endpoint_service
    service.session_service = session_service
    service.remote_transport = StubPaidRemoteHypervisorTransport()
    service.proxy_poll_attempts = 1

    first = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={
                "endpoint_id": created.endpoint.endpoint_id,
                "session_id": local_session.session.session_id,
            },
        )
    )
    second = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "again"},
            constraints={
                "endpoint_id": created.endpoint.endpoint_id,
                "session_id": local_session.session.session_id,
            },
        )
    )

    binding = session_service.get_proxy_session_binding(local_session.session.session_id)

    assert service.get_task(first.task_id).status == "completed"
    assert service.get_task(second.task_id).status == "completed"
    assert binding.remote_session_id == "remote-session-1"
    assert binding.status == "active"
    assert (
        sum(
            1
            for method, url, _ in service.remote_transport.calls
            if method == "POST" and url == "http://remote-hv/api/v1/endpoints/ep-remote/sessions"
        )
        == 1
    )
    remote_task_calls = [
        payload
        for method, url, payload in service.remote_transport.calls
        if method == "POST" and url == "http://remote-hv/tasks"
    ]
    assert len(remote_task_calls) == 2
    assert remote_task_calls[0]["constraints"]["session_id"] == "remote-session-1"
    assert remote_task_calls[1]["constraints"]["session_id"] == "remote-session-1"


def test_service_closing_local_proxy_session_attempts_remote_close() -> None:
    class StubPaidRemoteHypervisorTransport:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, dict | None]] = []

        def request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
            self.calls.append((method, url, payload))
            if method == "POST" and url == "http://remote-hv/api/v1/endpoints/ep-remote/sessions":
                return {
                    "session": {
                        "session_id": "remote-session-1",
                        "opened_at": "2026-07-02T00:00:00+00:00",
                    }
                }
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
                    "result": {"ok": True, "task_type": "llm_text.generate"},
                }
            if method == "POST" and url == "http://remote-hv/api/v1/sessions/remote-session-1/close":
                return {"session": {"session_id": "remote-session-1", "status": "closed"}}
            raise AssertionError(f"unexpected proxy request: {method} {url}")

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("text-a", "llm_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    endpoint_service = EndpointService(EndpointStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    session_service = SessionService(SessionStore())
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
        session_policy={"minimum_deposit": 10.0},
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
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
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    local_session = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id="node-local",
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    service.endpoint_service = endpoint_service
    service.remote_endpoint_service = remote_endpoint_service
    service.session_service = session_service
    service.remote_transport = StubPaidRemoteHypervisorTransport()
    service.proxy_poll_attempts = 1

    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={
                "endpoint_id": created.endpoint.endpoint_id,
                "session_id": local_session.session.session_id,
            },
        )
    )
    service.close_endpoint_session(local_session.session.session_id)

    assert (
        "POST",
        "http://remote-hv/api/v1/sessions/remote-session-1/close",
        None,
    ) in service.remote_transport.calls


def test_service_proxy_session_open_failure_keeps_local_session_active() -> None:
    class FailingPaidRemoteHypervisorTransport:
        def request_json(self, method: str, url: str, payload: dict | None = None) -> dict:
            if method == "POST" and url == "http://remote-hv/api/v1/endpoints/ep-remote/sessions":
                raise RuntimeError("remote session open failed")
            raise AssertionError(f"unexpected proxy request: {method} {url}")

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("text-a", "llm_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    endpoint_service = EndpointService(EndpointStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    session_service = SessionService(SessionStore())
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
        session_policy={"minimum_deposit": 10.0},
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="text-a",
            bundle_hash="bundle-hash-a",
            display_name="Proxy Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
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
    endpoint_service.attach_proxy_target(created.endpoint.endpoint_id, attached)
    local_session = session_service.open_session(
        endpoint_id=created.endpoint.endpoint_id,
        client_wallet="wallet-client",
        provider_wallet="wallet-1",
        node_id="node-local",
        deposit_q=25.0,
        session_policy=created.endpoint.session.model_dump(mode="json"),
    )
    service.endpoint_service = endpoint_service
    service.remote_endpoint_service = remote_endpoint_service
    service.session_service = session_service
    service.remote_transport = FailingPaidRemoteHypervisorTransport()

    task = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={
                "endpoint_id": created.endpoint.endpoint_id,
                "session_id": local_session.session.session_id,
            },
        )
    )

    assert service.get_task(task.task_id).status == "failed"
    assert session_service.get_session(local_session.session.session_id).session.status == "active"
    assert session_service.get_proxy_session_binding(local_session.session.session_id).status == "degraded"


def test_service_executes_task_immediately_when_resources_are_available() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
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

    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))

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


def test_service_node_advertisement_includes_canonical_registry_sections() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(update={"endpoint": "http://127.0.0.1:9000"}),
            _bundle("text-a", "llm_text"),
        ],
        runtimes=[
            RuntimeHandle(
                runtime_id="rt-1",
                command=["whisper"],
                status="running",
                bundle_id="whisper-a",
                health_status="healthy",
            )
        ],
    )

    payload = service.node_advertisement(heartbeat_at="2026-07-05T14:00:00+00:00")

    assert payload["canonical_services"][0]["kind"] == "compute"
    assert payload["canonical_capabilities"][0]["capability_id"] == "llm.chat"
    assert payload["canonical_capability_runtimes"][0]["capability_id"] == "speech.stt"
    assert payload["canonical_compute_compatibility"][0]["legacy_bundle_id"] == "whisper-a"
    assert payload["canonical_advertisements"] == []
    assert payload["canonical_feature_profiles"] == []
    assert payload["canonical_limit_profiles"] == []
    assert payload["canonical_implementation_profiles"] == []
    assert {item["object_type"] for item in payload["canonical_registry_objects"]} == {"capability_definition"}


def test_service_node_advertisement_keeps_published_endpoints_alongside_canonical_sections() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[_bundle("text-a", "llm_text")],
        node_id="node-local",
    )
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Text Endpoint",
            model_class="llm_text",
            capabilities=["llm.chat"],
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    service.endpoint_publication_service = publication_service

    payload = service.node_advertisement(heartbeat_at="2026-07-05T14:00:00+00:00")

    assert payload["published_endpoints"][0]["endpoint_id"] == created.endpoint.endpoint_id
    assert payload["canonical_advertisements"] == [
        {
            "advertisement_id": f"adv-{payload['published_endpoints'][0]['current_publication_id']}",
            "offer_id": f"offer-{payload['published_endpoints'][0]['current_publication_id']}",
            "resource_type": "endpoint",
            "owner_wallet": service.owner_wallet_state()["wallet_id"],
            "hypervisor_id": service.node_id,
            "capability_id": "llm.chat",
            "capability_version": "2.0.0",
            "capability_definition_hash": payload["canonical_capabilities"][0]["capability_definition_hash"],
            "feature_profile_hash": payload["canonical_feature_profiles"][0]["feature_profile_hash"],
            "limit_profile_hash": payload["canonical_limit_profiles"][0]["limit_profile_hash"],
            "implementation_profile_hash": payload["canonical_implementation_profiles"][0][
                "implementation_profile_hash"
            ],
            "visibility": "private",
            "signature_scope": "configuration_publication",
            "parameter_policy": {"version": "runtime-parameters.v1", "parameters": []},
        }
    ]
    assert payload["canonical_services"][0]["kind"] == "compute"
    assert payload["canonical_feature_profiles"][0]["endpoint_id"] == created.endpoint.endpoint_id
    assert payload["canonical_limit_profiles"][0]["endpoint_id"] == created.endpoint.endpoint_id
    assert payload["canonical_implementation_profiles"][0]["endpoint_id"] == created.endpoint.endpoint_id
    assert {item["object_type"] for item in payload["canonical_registry_objects"]} == {
        "capability_definition",
        "endpoint_feature_profile",
        "endpoint_limit_profile",
        "endpoint_implementation_profile",
        "accounting_contract",
    }
    accounting_object = next(
        item for item in payload["canonical_registry_objects"] if item["object_type"] == "accounting_contract"
    )
    assert accounting_object["namespace"] == "usage"
    assert accounting_object["source_reference"] == created.endpoint.endpoint_id


def test_service_node_advertisement_excludes_superseded_and_revoked_canonical_advertisements() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[_bundle("text-a", "llm_text")],
        node_id="node-local",
    )
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Text Endpoint",
            model_class="llm_text",
            capabilities=["llm.chat", "llm.embed"],
            publication={"visibility": "public"},
        )
    )
    first = publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    second = publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    service.endpoint_publication_service = publication_service

    payload = service.node_advertisement(heartbeat_at="2026-07-05T14:00:00+00:00")

    assert first.publication_id != second.publication_id
    assert [item["current_publication_id"] for item in payload["published_endpoints"]] == [second.publication_id]
    assert payload["canonical_advertisements"] == [
        {
            "advertisement_id": f"adv-{second.publication_id}",
            "offer_id": f"offer-{second.publication_id}",
            "resource_type": "endpoint",
            "owner_wallet": service.owner_wallet_state()["wallet_id"],
            "hypervisor_id": service.node_id,
            "capability_id": "llm.chat",
            "capability_version": "2.0.0",
            "capability_definition_hash": payload["canonical_capabilities"][0]["capability_definition_hash"],
            "feature_profile_hash": payload["canonical_feature_profiles"][0]["feature_profile_hash"],
            "limit_profile_hash": payload["canonical_limit_profiles"][0]["limit_profile_hash"],
            "implementation_profile_hash": payload["canonical_implementation_profiles"][0][
                "implementation_profile_hash"
            ],
            "visibility": "public",
            "signature_scope": "configuration_publication",
            "parameter_policy": {"version": "runtime-parameters.v1", "parameters": []},
        }
    ]

    publication_service.revoke_publication(created.endpoint.endpoint_id)

    revoked_payload = service.node_advertisement(heartbeat_at="2026-07-05T14:05:00+00:00")

    assert revoked_payload["published_endpoints"] == []
    assert revoked_payload["canonical_advertisements"] == []


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


def test_service_dashboard_home_reduces_to_bootstrap_and_factual_summary(
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
            _bundle("whisper-a", "speech_to_text").model_copy(update={"endpoint": "http://127.0.0.1:9000"}),
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
    assert home["summary"]["bundle_total"] == 3
    assert home["summary"]["enabled_bundle_total"] == 2
    assert home["summary"]["pending_install_total"] == 1
    assert home["summary"]["queue"] == {
        "queued": 0,
        "active": 0,
        "completed": 0,
        "failed": 0,
    }
    assert home["summary"]["free_resources"]["cpu"] == pytest.approx(6.5)
    assert "publish" not in home
    assert "market_visibility" not in home
    assert "fleet_capacity" not in home
    assert "operator_controls" not in home


def test_service_owner_wallet_bootstrap_persists_and_restores_state() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[_bundle("text-a", "llm_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    created = service.configure_owner_wallet(mode="create", label="Primary Wallet")
    snapshot = service.snapshot_state()

    restored = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
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


def test_service_onboarding_state_persists_after_wallet_and_publish() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    endpoint_service = EndpointService(EndpointStore())

    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    service.sync_operator_onboarding_state(
        endpoint_items=[
            {
                "endpoint_id": created.endpoint.endpoint_id,
                "bundle_id": "whisper-a",
                "publication_status": "published",
                "visibility": "private",
            }
        ]
    )

    restored = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    restored.restore_state(service.snapshot_state())

    onboarding = restored.operator_onboarding_state()
    assert onboarding["completed"] is True
    assert onboarding["completed_via"] == "first_local_endpoint_published"
    assert onboarding["current_step"] == "operate"


def test_service_onboarding_stays_incomplete_for_unpublished_endpoint() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    service.sync_operator_onboarding_state(
        endpoint_items=[
            {
                "endpoint_id": "endpoint-draft",
                "bundle_id": "whisper-a",
                "publication_status": "configured",
                "visibility": "private",
            }
        ]
    )

    onboarding = service.operator_onboarding_state()
    assert onboarding["completed"] is False
    assert onboarding["current_step"] == "publish_endpoint"


def test_service_wallet_bootstrap_advances_onboarding_without_manual_sync() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    service.configure_owner_wallet(mode="create", label="Primary Wallet")

    onboarding = service.operator_onboarding_state()
    assert onboarding["completed"] is False
    assert onboarding["current_step"] == "attach_provider"


def test_service_onboarding_completion_remains_after_later_empty_sync() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    service.sync_operator_onboarding_state(
        endpoint_items=[
            {
                "endpoint_id": "endpoint-live",
                "bundle_id": "whisper-a",
                "publication_status": "published",
                "visibility": "private",
            }
        ]
    )

    completed = service.operator_onboarding_state()
    service.sync_operator_onboarding_state(endpoint_items=[])

    onboarding = service.operator_onboarding_state()
    assert onboarding["completed"] is True
    assert onboarding["completed_via"] == "first_local_endpoint_published"
    assert onboarding["completed_at"] == completed["completed_at"]
    assert onboarding["current_step"] == "operate"


def test_service_replacing_wallet_resets_completed_onboarding() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    service.sync_operator_onboarding_state(
        endpoint_items=[
            {
                "endpoint_id": "endpoint-live",
                "bundle_id": "whisper-a",
                "publication_status": "published",
                "visibility": "private",
            }
        ]
    )

    service.configure_owner_wallet(mode="create", label="Replacement Wallet")

    onboarding = service.operator_onboarding_state()
    assert onboarding["completed"] is False
    assert onboarding["completed_via"] is None
    assert onboarding["completed_at"] is None
    assert onboarding["current_step"] == "attach_provider"


def test_service_home_bootstrap_requires_wallet_before_network_actions() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(update={"endpoint": "http://127.0.0.1:9000"}),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(update={"endpoint": "http://127.0.0.1:9000"}),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[
            _bundle("whisper-a", "speech_to_text").model_copy(update={"endpoint": "http://127.0.0.1:9000"}),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
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
    completed = service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "done"}))
    queued = service.queue.enqueue(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "queued.wav"}))
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
        bundles=[_bundle("text-a", "llm_text"), _bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    task_a = service.queue.enqueue(TaskRequest(task_type="llm_text.generate", payload={"prompt": "a"}, priority=80))
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=1.0, ram_mb=1024, vram_mb={"gpu0": 512})),
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

    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))

    assert service.get_task(task.task_id).status == "queued"
    assert service.task_result(task.task_id) is None
    assert service.list_runtimes() == []


def test_service_retries_waiting_tasks_after_bundle_stop_frees_resources() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=4096, vram_mb={"gpu0": 2048})),
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
    queued_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
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

    first_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"}))
    service.queue.transition_status(first_task.task_id, "running")

    second_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"}))

    assert service.get_task(second_task.task_id).status == "queued"
    assert service.task_result(second_task.task_id) is None


def test_service_marks_task_failed_when_runtime_health_check_fails() -> None:
    registry = PluginRegistry()
    registry.register(UnhealthyFakePlugin())
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
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

    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
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

    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"plugin_id": "fake-retry-policy"})],
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

    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"plugin_id": "fake-retry-policy"})],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"plugin_id": "fake-retry-policy"})],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"plugin_id": "fake-cooldown-policy"})],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    failed_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"}))
    queued_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"plugin_id": "fake-cooldown-policy"})],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"}))
    queued_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"plugin_id": "fake-cooldown-policy"})],
        plugins=registry,
        runtimes=ProviderProcessManager(),
    )

    service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"}))
    queued_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    task = service.queue.enqueue(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text")],
        plugins=_registry(),
        runtimes=runtimes,
    )
    task = service.queue.enqueue(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
        bundles=[
            _bundle("bundle-a", "speech_to_text").model_copy(update={"plugin_id": "fake-recording"}),
            _bundle("bundle-b", "speech_to_text").model_copy(update={"plugin_id": "fake-recording"}),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"endpoint": "http://127.0.0.1:9000"})],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    allocation = service.create_allocation(AllocationRequest(workload_type="speech_to_text", owner_id="agent-a"))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"endpoint": "http://127.0.0.1:9000"})],
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
                    "audio_input_second": 0.0,
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
                "audio_input_second": 0.0,
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
                    "allocatable_cpu": 8.0,
                    "allocatable_ram_mb": 16384,
                    "allocatable_vram_mb": 4096,
                    "reconciliation_state": "TRUSTED",
                },
            }
        ],
    }


def test_service_capability_catalog_reports_wait_when_resources_are_busy() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024})),
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
                "allocatable_cpu": 2.0,
                "allocatable_ram_mb": 2048,
                "allocatable_vram_mb": 1024,
                "reconciliation_state": "TRUSTED",
            },
        }
    ]


def test_service_capability_catalog_reports_missing_resource_delta() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024})),
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
        "allocatable_cpu": 2.0,
        "allocatable_ram_mb": 2048,
        "allocatable_vram_mb": 1024,
        "reconciliation_state": "TRUSTED",
    }


def test_service_register_model_install_job_tracks_requested_artifact(tmp_path) -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
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
    assert Path(job["target_path"]).parts[-2:] == ("llama.cpp", "phi-4-mini.gguf")


def test_service_process_model_installs_materializes_artifact_and_marks_job_completed(
    tmp_path,
) -> None:
    source_artifact = tmp_path / "phi-4-mini.gguf"
    source_artifact.write_text("model-bytes", encoding="utf-8")
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
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
    assert (tmp_path / "models" / "fake-managed" / "phi-4-mini.gguf").read_text(encoding="utf-8") == "model-bytes"
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"endpoint": "http://127.0.0.1:9000"})],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )

    catalog = service.capability_catalog(
        owner_id="agent-a",
        workload_type="speech_to_text",
    )
    allocation = service.create_allocation(AllocationRequest(workload_type="speech_to_text", owner_id="agent-a"))

    assert catalog["bundles"][0]["bundle_id"] == "whisper-a"
    assert catalog["bundles"][0]["can_allocate_now"] is True
    assert allocation["bundle_id"] == "whisper-a"
    assert allocation["endpoint"] == "http://127.0.0.1:9000"


def test_operator_can_install_register_and_expose_new_model(tmp_path) -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
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
                "allocatable_cpu": 8.0,
                "allocatable_ram_mb": 16384,
                "allocatable_vram_mb": 4096,
                "reconciliation_state": "TRUSTED",
            },
        }
    ]


def test_service_release_allocation_marks_it_released() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"endpoint": "http://127.0.0.1:9000"})],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )
    allocation = service.create_allocation(AllocationRequest(workload_type="speech_to_text", owner_id="agent-a"))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=1.0, ram_mb=1024, vram_mb={"gpu0": 256})),
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
        service.create_allocation(AllocationRequest(workload_type="speech_to_text", owner_id="agent-a"))


def test_service_create_allocation_with_wait_policy_returns_pending() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024})),
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
    assert (
        allocation["next_attempt_at"]
        == datetime.fromtimestamp(
            current_time[0] + 5,
            UTC,
        ).isoformat()
    )


def test_service_create_allocation_rejects_when_owner_active_quota_is_exceeded() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
        bundles=[_bundle("whisper-a", "speech_to_text").model_copy(update={"endpoint": "http://127.0.0.1:9000"})],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        max_active_allocations_per_owner=1,
    )
    service.create_allocation(AllocationRequest(workload_type="speech_to_text", owner_id="agent-a"))

    with pytest.raises(ValueError, match="owner active allocation quota exceeded"):
        service.create_allocation(AllocationRequest(workload_type="speech_to_text", owner_id="agent-a"))


def test_service_create_wait_allocation_rejects_when_owner_pending_quota_is_exceeded() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=2048, vram_mb={"gpu0": 1024})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
        bundles=[
            _bundle("bundle-a", "speech_to_text").model_copy(update={"plugin_id": "fake-recording"}),
            _bundle("bundle-b", "speech_to_text").model_copy(update={"plugin_id": "fake-recording"}),
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

    admission_events = [event for event in service.event_journal() if event.event_type == "admission.selected"]

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
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

    telemetry = service._runtime_boundary.admission_telemetry()

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 4096})),
        bundles=[
            _bundle("bundle-a", "speech_to_text").model_copy(update={"plugin_id": "fake-recording"}),
            _bundle("bundle-b", "speech_to_text").model_copy(update={"plugin_id": "fake-recording"}),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=4096, vram_mb={"gpu0": 2048})),
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
    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))

    assert service.get_task(task.task_id).status == "completed"
    assert [runtime.bundle_id for runtime in service.list_runtimes()] == []


def test_service_keeps_idle_always_runtime_for_non_higher_priority_task() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=4096, vram_mb={"gpu0": 2048})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=4096, vram_mb={"gpu0": 2048})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
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

    first_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"}))
    service.queue.transition_status(first_task.task_id, "running")

    second_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"}))

    assert service.get_task(second_task.task_id).status == "queued"


def test_service_reports_concurrency_limit_as_queue_diagnostic_reason() -> None:
    registry = PluginRegistry()
    registry.register(ConcurrencyHintPlugin())
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 4096})),
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

    first_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"}))
    service.queue.transition_status(first_task.task_id, "running")
    second_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=1.5, ram_mb=2048, vram_mb={"gpu0": 0})),
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

    task = service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "Hi"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=6.0, ram_mb=8192, vram_mb={"gpu0": 0})),
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

    first_task = service.queue.enqueue(TaskRequest(task_type="llm_text.generate", payload={"prompt": "one"}))
    service._selected_bundles[first_task.task_id] = "phi4-ollama"
    service.queue.transition_status(first_task.task_id, "running")
    second_task = service.queue.enqueue(TaskRequest(task_type="llm_text.generate", payload={"prompt": "two"}))
    service._selected_bundles[second_task.task_id] = "phi4-ollama"
    service.queue.transition_status(second_task.task_id, "running")

    third_task = service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "three"}))

    assert service.get_task(third_task.task_id).status == "queued"


def test_service_reports_insufficient_resources_as_queue_diagnostic_reason() -> None:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=1.0, ram_mb=1024, vram_mb={"gpu0": 512})),
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

    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=4096, vram_mb={"gpu0": 2048})),
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=2.0, ram_mb=4096, vram_mb={"gpu0": 2048})),
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
    waiting_task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"}))

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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 0})),
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

    task = service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "Hi"}))

    runtime = service.list_runtimes()[0]

    assert service.get_task(task.task_id).status == "completed"
    assert service.task_result(task.task_id) == {
        "ok": True,
        "task_type": "llm_text.generate",
        "model_id": "phi4",
        "output_text": "Hello from Ollama",
        "done": True,
        "usage": {
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


def test_plugin_host_ingress_facade_delegates_to_provider_inventory() -> None:
    expected = object()

    class ProviderInventory:
        def plugin_host_local_ingress(self):
            return expected

    service = object.__new__(HypervisorService)
    service.provider_inventory = ProviderInventory()

    assert service.plugin_host_local_ingress() is expected


def test_plugin_host_status_redacts_activation_credential() -> None:
    class ConnectionStore:
        def snapshot(self):
            return [{"installed_plugin_id": "installed-1", "activation_credential_key_id": "secret"}]

    class ProviderInventory:
        plugin_host_connection_store = ConnectionStore()

    service = object.__new__(HypervisorService)
    service.provider_inventory = ProviderInventory()
    service._plugin_host_listeners = []

    assert service.plugin_host_status() == {
        "active_connection_count": 1,
        "connections": [{"installed_plugin_id": "installed-1"}],
        "listener_count": 0,
        "listener_transports": [],
    }


def test_hypervisor_publishes_plugin_release_registry_objects() -> None:
    from aidn_hypervisor.registry_service import RegistryService

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=_registry(),
    )
    release = service.register_provider_plugin_release(
        manifest=service.plugins.get("fake-managed").plugin_manifest(),
        source_reference="registry://plugins/fake-managed",
    )
    registry = RegistryService()

    stored = service.publish_provider_plugin_releases_to_registry(registry)

    assert stored[0]["namespace"] == "plugin"
    assert stored[0]["payload"]["release_id"] == release["release_id"]
    listed = registry.list_registry_objects(query={"namespace": "plugin"})
    assert [item["object_id"] for item in listed] == [stored[0]["object_id"]]
    assert registry.get_registry_object(stored[0]["object_id"], include_payload=True)["payload"] == stored[0]["payload"]


def test_hypervisor_reconciles_plugin_releases_from_local_registry() -> None:
    from aidn_hypervisor.registry_service import RegistryService

    source = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=_registry(),
    )
    target = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=_registry(),
    )
    release = source.register_provider_plugin_release(
        manifest=source.plugins.get("fake-managed").plugin_manifest(),
        source_reference="registry://plugins/fake-managed",
    )
    registry = RegistryService()
    source.publish_provider_plugin_releases_to_registry(registry)

    reconciled = target.reconcile_provider_plugin_releases_from_registry(registry)

    assert reconciled["registry_record_count"] == 1
    assert reconciled["imported_release_count"] == 1
    imported = reconciled["items"][0]
    assert imported["release_id"] == release["release_id"]
    assert imported["package_verification_status"] == "UNVERIFIED"
    assert imported["trusted_publisher"] is False


def test_replicated_plugin_release_imports_metadata_without_package_trust() -> None:
    from aidn_hypervisor.registry.bridge import RegistryServiceAdapter
    from aidn_hypervisor.registry.replicator import RegistryReplicator
    from aidn_hypervisor.registry_service import RegistryService

    source = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=_registry(),
    )
    target = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        plugins=_registry(),
    )
    release = source.register_provider_plugin_release(
        manifest=source.plugins.get("fake-managed").plugin_manifest(),
        source_reference="registry://plugins/fake-managed",
    )
    source_registry = RegistryService()
    source.publish_provider_plugin_releases_to_registry(source_registry)
    source_adapter = RegistryServiceAdapter(legacy_service=source_registry)
    assert source_adapter.sync_from_legacy(object_type="plugin_release") == 1
    source_replicator = RegistryReplicator(
        node_id="node-source",
        store=source_adapter.store,
    )
    target_replicator = RegistryReplicator(node_id="node-target")
    target.bind_provider_plugin_directory_replication(target_replicator)

    request = target_replicator.build_object_request(
        "node-source",
        [source.provider_plugin_registry_objects()[0]["object_id"]],
    )
    response = source_replicator.process_incoming_message(
        peer_id="node-target",
        message=request,
    )
    assert response is not None
    target_replicator.process_incoming_message(peer_id="node-source", message=response)

    imported = target.list_provider_plugin_releases()
    assert [item["release_id"] for item in imported] == [release["release_id"]]
    assert imported[0]["package_verification_status"] == "UNVERIFIED"
    assert imported[0]["trusted_publisher"] is False


def test_service_executes_transcription_task_via_whisper_plugin() -> None:
    registry = PluginRegistry()
    plugin = StubWhisperPlugin()
    registry.register(plugin)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 0})),
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

    task = service.submit(TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "C:/audio/clip.wav"}))

    runtime = service.list_runtimes()[0]

    assert service.get_task(task.task_id).status == "completed"
    assert service.task_result(task.task_id) == {
        "ok": True,
        "task_type": "audio.transcribe",
        "model_id": "large-v3",
        "text": "hello from whisper",
        "usage": {
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
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=4.0, ram_mb=8192, vram_mb={"gpu0": 0})),
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

    task = service.submit(TaskRequest(task_type="llm_text.generate", payload={"prompt": "Hi"}))

    runtime = service.list_runtimes()[0]

    assert service.get_task(task.task_id).status == "completed"
    assert service.task_result(task.task_id) == {
        "ok": True,
        "task_type": "llm_text.generate",
        "model_id": "C:/models/phi4.gguf",
        "output_text": "hello from llama.cpp",
        "usage": {
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
