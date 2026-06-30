import pytest

from aidn_hypervisor.domain.models import (
    AllocationRequest,
    BundleConfig,
    NodeCapacity,
    ResourceProfile,
    TaskRequest,
)
from aidn_hypervisor.model_store import FileModelStore
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.state import (
    HypervisorStateSnapshot,
    JournalEvent,
    RuntimeSnapshot,
    TaskSnapshot,
)


def _bundle(
    bundle_id: str,
    workload_type: str,
    *,
    plugin_id: str = "fake-managed",
    resource_profile: ResourceProfile | None = None,
) -> BundleConfig:
    return BundleConfig(
        bundle_id=bundle_id,
        plugin_id=plugin_id,
        provider_type="fake",
        workload_type=workload_type,
        model_id=f"{bundle_id}-model",
        launch_mode="managed_process",
        device_affinity="cpu",
        resource_profile=resource_profile or ResourceProfile(),
        warm_policy="auto",
    )


def _registry(*plugins: FakeManagedPlugin) -> PluginRegistry:
    registry = PluginRegistry()
    if not plugins:
        plugins = (FakeManagedPlugin(),)
    for plugin in plugins:
        registry.register(plugin)
    return registry


def _service(
    *,
    bundles: list[BundleConfig],
    plugins: PluginRegistry,
    model_store=None,
) -> HypervisorService:
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=bundles,
        plugins=plugins,
        runtimes=ProviderProcessManager(),
        model_store=model_store,
    )


class RestartRetryPlugin(FakeManagedPlugin):
    plugin_id = "fake-restart-retry"

    def supports_restart_retry(self, task, bundle_config) -> bool:
        return True


class UnrecoverableRuntimePlugin(FakeManagedPlugin):
    plugin_id = "fake-unrecoverable-runtime"

    def health_check(self, runtime_handle) -> bool:
        return False


class CooldownStatePlugin(FakeManagedPlugin):
    plugin_id = "fake-cooldown-state"

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


def test_service_snapshot_and_restore_preserves_queued_and_completed_tasks() -> None:
    bundle = _bundle("whisper-a", "speech_to_text")
    service = _service(bundles=[bundle], plugins=_registry())

    queued_task = service.queue.enqueue(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "queued.wav"})
    )
    service._selected_bundles[queued_task.task_id] = "whisper-a"

    completed_task = service.queue.enqueue(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "done.wav"})
    )
    service._selected_bundles[completed_task.task_id] = "whisper-a"
    service.queue.transition_status(completed_task.task_id, "completed")
    service._task_results[completed_task.task_id] = {
        "ok": True,
        "task_type": "audio.transcribe",
    }

    snapshot = service.snapshot_state()

    restored_service = _service(bundles=[bundle], plugins=_registry())
    restored_service.restore_state(snapshot)

    assert restored_service.get_task(queued_task.task_id).status == "queued"
    assert restored_service.get_task(completed_task.task_id).status == "completed"
    assert restored_service.task_result(completed_task.task_id) == {
        "ok": True,
        "task_type": "audio.transcribe",
    }


def test_service_snapshot_and_restore_preserves_allocations() -> None:
    bundle = _bundle("whisper-a", "speech_to_text").model_copy(
        update={"endpoint": "http://127.0.0.1:9000"}
    )
    service = _service(bundles=[bundle], plugins=_registry())

    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text", owner_id="agent-a")
    )

    snapshot = service.snapshot_state()

    restored_service = _service(bundles=[bundle], plugins=_registry())
    restored_service.restore_state(snapshot)

    assert restored_service.get_allocation(allocation["allocation_id"]) == {
        "allocation_id": allocation["allocation_id"],
        "owner_id": "agent-a",
        "workload_type": "speech_to_text",
        "bundle_id": "whisper-a",
        "runtime_id": "rt-1",
        "endpoint": "http://127.0.0.1:9000",
        "status": "active",
    }


def test_service_snapshot_and_restore_preserves_wallet_allocation_activation_events() -> None:
    bundle = _bundle("whisper-a", "speech_to_text").model_copy(
        update={"endpoint": "http://127.0.0.1:9000"}
    )
    service = _service(bundles=[bundle], plugins=_registry())

    service.create_allocation(
        AllocationRequest(workload_type="speech_to_text", owner_id="agent-a")
    )
    activation_event = service.list_wallet_allocation_activation_events()[0]
    snapshot = service.snapshot_state()

    restored_service = _service(bundles=[bundle], plugins=_registry())
    restored_service.restore_state(snapshot)

    assert restored_service.list_wallet_allocation_activation_events() == [
        activation_event
    ]


def test_service_snapshot_and_restore_preserves_disputed_wallet_allocation_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    bundle = _bundle("whisper-a", "speech_to_text").model_copy(
        update={"endpoint": "http://127.0.0.1:9000"}
    )
    service = _service(bundles=[bundle], plugins=_registry())

    allocation = service.create_allocation(
        AllocationRequest(workload_type="speech_to_text", owner_id="agent-a")
    )
    service.release_allocation(allocation["allocation_id"])
    event_id = service.list_wallet_allocation_events()[0]["event_id"]
    disputed = service.dispute_wallet_allocation_event(
        event_id, reason="snapshot dispute"
    )
    snapshot = service.snapshot_state()

    restored_service = _service(bundles=[bundle], plugins=_registry())
    restored_service.restore_state(snapshot)

    assert restored_service.list_wallet_allocation_events() == [disputed]
    assert restored_service.list_wallet_allocation_dispute_events()[0]["event_type"] == "opened"


def test_service_restore_marks_expired_allocation_as_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    bundle = _bundle("whisper-a", "speech_to_text").model_copy(
        update={"endpoint": "http://127.0.0.1:9000"}
    )
    service = _service(bundles=[bundle], plugins=_registry())

    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="speech_to_text",
            owner_id="agent-a",
            lease_seconds=1,
        )
    )
    snapshot = service.snapshot_state()

    current_time[0] += 2.0
    restored_service = _service(bundles=[bundle], plugins=_registry())
    restored_service.restore_state(snapshot)

    assert restored_service.get_allocation(allocation["allocation_id"])["status"] == "expired"


def test_service_snapshot_and_restore_preserves_model_install_jobs(tmp_path) -> None:
    service = _service(
        bundles=[],
        plugins=_registry(),
        model_store=FileModelStore(tmp_path),
    )

    job = service.request_model_install(
        provider_type="llama.cpp",
        model_id="phi-4-mini.gguf",
        source_url="https://example.invalid/models/phi-4-mini.gguf",
        requested_by="operator-a",
    )
    snapshot = service.snapshot_state()

    restored_service = _service(
        bundles=[],
        plugins=_registry(),
        model_store=FileModelStore(tmp_path),
    )
    restored_service.restore_state(snapshot)

    assert restored_service.list_model_installs() == [job]


@pytest.mark.parametrize("status", ["admitted", "starting", "running"])
def test_service_restore_marks_inflight_tasks_failed_by_default(status: str) -> None:
    bundle = _bundle("whisper-a", "speech_to_text")
    snapshot = HypervisorStateSnapshot(
        tasks=[
            TaskSnapshot(
                task_id="task-1",
                priority=50,
                enqueue_index=0,
                created_at="2026-06-19T00:00:00+00:00",
                status=status,
                request=TaskRequest(
                    task_type="audio.transcribe",
                    payload={"audio_ref": "clip.wav"},
                ),
                bundle_id="whisper-a",
            )
        ]
    )

    service = _service(bundles=[bundle], plugins=_registry())
    service.restore_state(snapshot)

    assert service.get_task("task-1").status == "failed"
    assert service.task_result("task-1") is None
    assert service.task_recovery_reason("task-1") == "restart_failed_unknown_inflight"
    assert service.event_journal(limit=1)[0].event_type == "task.recovered"


def test_service_restore_requeues_inflight_task_when_retry_is_configured_and_safe() -> None:
    bundle = _bundle(
        "whisper-a",
        "speech_to_text",
        plugin_id="fake-restart-retry",
    )
    snapshot = HypervisorStateSnapshot(
        tasks=[
            TaskSnapshot(
                task_id="task-1",
                priority=50,
                enqueue_index=0,
                created_at="2026-06-19T00:00:00+00:00",
                status="running",
                request=TaskRequest(
                    task_type="audio.transcribe",
                    payload={"audio_ref": "clip.wav"},
                    constraints={"retry_on_restart": True},
                ),
                bundle_id="whisper-a",
            )
        ]
    )

    service = _service(
        bundles=[bundle],
        plugins=_registry(RestartRetryPlugin()),
    )
    service.restore_state(snapshot)

    assert service.get_task("task-1").status == "queued"
    assert service.task_recovery_reason("task-1") == "restart_retry_queued"


def test_service_restore_reconnects_healthy_runtime_and_reserves_residency() -> None:
    profile = ResourceProfile(steady_cpu=1.5, steady_ram_mb=2048, steady_vram_mb=1024)
    bundle = _bundle("whisper-a", "speech_to_text", resource_profile=profile)
    snapshot = HypervisorStateSnapshot(
        runtimes=[
            RuntimeSnapshot(
                runtime_id="rt-1",
                bundle_id="whisper-a",
                command=["python", "-m", "http.server", "0"],
                status="running",
                health_status="unknown",
                metadata={"endpoint": "http://127.0.0.1:11434", "model_id": "phi4"},
            )
        ]
    )

    service = _service(bundles=[bundle], plugins=_registry())
    service.restore_state(snapshot)

    restored_runtime = service.list_runtimes()[0]
    assert restored_runtime.runtime_id == "rt-1"
    assert restored_runtime.bundle_id == "whisper-a"
    assert restored_runtime.health_status == "healthy"
    assert restored_runtime.metadata == {
        "endpoint": "http://127.0.0.1:11434",
        "model_id": "phi4",
    }
    assert service.resources.summary()["reserved"] == {
        "cpu": pytest.approx(1.5),
        "ram_mb": 2048,
        "vram_mb": 1024,
    }
    assert service.event_journal(limit=1)[0].event_type == "runtime.recovered"


def test_service_restore_skips_unhealthy_runtime_recovery() -> None:
    bundle = _bundle(
        "whisper-a",
        "speech_to_text",
        plugin_id="fake-unrecoverable-runtime",
    )
    snapshot = HypervisorStateSnapshot(
        runtimes=[
            RuntimeSnapshot(
                runtime_id="rt-1",
                bundle_id="whisper-a",
                command=["python", "-m", "http.server", "0"],
                status="running",
                health_status="unknown",
            )
        ]
    )

    service = _service(
        bundles=[bundle],
        plugins=_registry(UnrecoverableRuntimePlugin()),
    )
    service.restore_state(snapshot)

    assert service.list_runtimes() == []
    assert service.resources.summary()["reserved"] == {
        "cpu": 0,
        "ram_mb": 0,
        "vram_mb": 0,
    }
    assert service.event_journal(limit=1)[0].event_type == "runtime.recovery_skipped"


def test_service_snapshot_and_restore_preserves_event_journal() -> None:
    bundle = _bundle("whisper-a", "speech_to_text")
    service = _service(bundles=[bundle], plugins=_registry())
    service.record_event(
        event_type="operator.note",
        message="manual checkpoint",
        task_id="task-1",
        details={"source": "test"},
    )

    snapshot = service.snapshot_state()
    restored_service = _service(bundles=[bundle], plugins=_registry())
    restored_service.restore_state(snapshot)

    restored_event = restored_service.event_journal(limit=1)[0]
    assert restored_event.event_type == "operator.note"
    assert restored_event.message == "manual checkpoint"
    assert restored_event.details == {"source": "test"}


def test_service_snapshot_and_restore_preserves_bundle_cooldown_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(
        "whisper-a",
        "speech_to_text",
        plugin_id="fake-cooldown-state",
    )
    current_time = [1000.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    monkeypatch.setattr("aidn_hypervisor.service.time.sleep", lambda _: None)
    service = _service(
        bundles=[bundle],
        plugins=_registry(CooldownStatePlugin()),
    )

    service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-a.wav"})
    )
    waiting_task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip-b.wav"})
    )

    snapshot = service.snapshot_state()

    restored_service = _service(
        bundles=[bundle],
        plugins=_registry(CooldownStatePlugin()),
    )
    restored_service.restore_state(snapshot)

    assert snapshot.model_dump(mode="json")["bundle_states"] == [
        {
            "bundle_id": "whisper-a",
            "failure_streak": 1,
            "cooldown_until": 1060.0,
            "cooldown_reason": "connection refused",
            "drain_mode": False,
            "drain_reason": None,
        }
    ]
    assert restored_service.get_task(waiting_task.task_id).status == "queued"
    assert restored_service.queue_diagnostics() == [
        {
            "task_id": waiting_task.task_id,
            "bundle_id": "whisper-a",
            "reason": "provider_cooldown",
        }
    ]
