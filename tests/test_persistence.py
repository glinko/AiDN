from pathlib import Path

from fastapi.testclient import TestClient

from aidn_hypervisor.domain.models import (
    BundleConfig,
    NodeCapacity,
    ResourceProfile,
    TaskRequest,
)
from aidn_hypervisor.endpoints.models import (
    EndpointPublicationPolicy,
    EndpointRuntimeConfig,
)
from aidn_hypervisor.endpoints.state import (
    EndpointConfigurationSnapshotRecord,
    EndpointManifestSnapshot,
)
from aidn_hypervisor.main import (
    _build_default_endpoint_service,
    _build_default_service,
    build_app,
)
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.state import HypervisorStateSnapshot, JournalEvent, TaskSnapshot


def _bundle(
    bundle_id: str,
    workload_type: str,
    *,
    resource_profile: ResourceProfile | None = None,
    warm_policy: str = "auto",
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
    )


def _registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())
    return registry


def _service(state_path: Path) -> HypervisorService:
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
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
                warm_policy="never",
            )
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        state_store=FileStateStore(state_path),
    )


def test_file_state_store_round_trips_snapshot(tmp_path: Path) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    store = FileStateStore(state_path)
    snapshot = HypervisorStateSnapshot(
        tasks=[
            TaskSnapshot(
                task_id="task-1",
                priority=50,
                enqueue_index=0,
                created_at="2026-06-19T00:00:00+00:00",
                status="queued",
                request=TaskRequest(
                    task_type="audio.transcribe",
                    payload={"audio_ref": "clip.wav"},
                ),
                bundle_id="whisper-a",
            )
        ],
        events=[
            JournalEvent(
                timestamp="2026-06-19T00:00:01+00:00",
                event_type="task.submitted",
                message="task accepted",
                task_id="task-1",
            )
        ],
        endpoints=[
            EndpointManifestSnapshot(
                endpoint_id="ep-1",
                owner_wallet="wallet-1",
                created_at="2026-06-29T00:00:00+00:00",
                bundle_id="bundle-a",
                bundle_hash="bundle-hash-a",
                configuration_hash="cfg-a",
                display_name="Operator STT",
                model_class="speech.stt",
                capabilities=["speech.stt"],
            )
        ],
        endpoint_configuration_snapshots=[
            EndpointConfigurationSnapshotRecord(
                configuration_hash="cfg-a",
                endpoint_id="ep-1",
                bundle_hash="bundle-hash-a",
                created_at="2026-06-29T00:00:00+00:00",
                runtime=EndpointRuntimeConfig(streaming=True, timeout=30),
                publication=EndpointPublicationPolicy(discoverable=True),
                execution_config={"streaming": True, "timeout": 30},
            )
        ],
    )

    store.save(snapshot)
    restored = store.load()

    assert restored == snapshot


def test_file_state_store_returns_empty_snapshot_when_file_is_missing(
    tmp_path: Path,
) -> None:
    store = FileStateStore(tmp_path / "missing-state.json")

    assert store.load() == HypervisorStateSnapshot()


def test_service_submit_persists_latest_state_to_disk(tmp_path: Path) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    service = _service(state_path)

    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )

    snapshot = FileStateStore(state_path).load()

    assert state_path.exists()
    assert snapshot.tasks[0].task_id == task.task_id
    assert snapshot.tasks[0].status == "completed"
    assert snapshot.tasks[0].result == {"ok": True, "task_type": "audio.transcribe"}


def test_service_submit_preserves_endpoint_state_during_legacy_persist(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    FileStateStore(state_path).save(
        HypervisorStateSnapshot(
            endpoints=[
                EndpointManifestSnapshot(
                    endpoint_id="ep-1",
                    owner_wallet="wallet-1",
                    created_at="2026-06-29T00:00:00+00:00",
                    bundle_id="bundle-a",
                    bundle_hash="bundle-hash-a",
                    configuration_hash="cfg-a",
                    display_name="Operator STT",
                    model_class="speech.stt",
                    capabilities=["speech.stt"],
                )
            ],
            endpoint_configuration_snapshots=[
                EndpointConfigurationSnapshotRecord(
                    configuration_hash="cfg-a",
                    endpoint_id="ep-1",
                    bundle_hash="bundle-hash-a",
                    created_at="2026-06-29T00:00:00+00:00",
                    runtime=EndpointRuntimeConfig(streaming=True, timeout=30),
                    publication=EndpointPublicationPolicy(discoverable=True),
                    execution_config={"streaming": True, "timeout": 30},
                )
            ],
        )
    )
    service = _service(state_path)

    task = service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    snapshot = FileStateStore(state_path).load()

    assert snapshot.tasks[0].task_id == task.task_id
    assert [manifest.endpoint_id for manifest in snapshot.endpoints] == ["ep-1"]
    assert [
        config.configuration_hash
        for config in snapshot.endpoint_configuration_snapshots
    ] == ["cfg-a"]


def test_service_cancel_persists_updated_status_to_disk(tmp_path: Path) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    service = _service(state_path)
    blocked_service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=1.0, ram_mb=1024, vram_mb={"gpu0": 512})
        ),
        bundles=service.bundles,
        plugins=service.plugins,
        runtimes=ProviderProcessManager(),
        state_store=FileStateStore(state_path),
    )

    task = blocked_service.submit(
        TaskRequest(task_type="audio.transcribe", payload={"audio_ref": "clip.wav"})
    )
    blocked_service.cancel_task(task.task_id)

    snapshot = FileStateStore(state_path).load()

    assert snapshot.tasks[0].status == "cancelled"


def test_default_service_restores_state_from_configured_file(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    FileStateStore(state_path).save(
        HypervisorStateSnapshot(
            tasks=[
                TaskSnapshot(
                    task_id="task-1",
                    priority=50,
                    enqueue_index=0,
                    created_at="2026-06-19T00:00:00+00:00",
                    status="queued",
                    request=TaskRequest(
                        task_type="audio.transcribe",
                        payload={"audio_ref": "clip.wav"},
                    ),
                    bundle_id="whisper-a",
                )
            ]
        )
    )
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(state_path))

    service = _build_default_service()

    assert service.get_task("task-1").status == "queued"


def test_default_service_restores_event_journal_from_configured_file(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    FileStateStore(state_path).save(
        HypervisorStateSnapshot(
            events=[
                JournalEvent(
                    timestamp="2026-06-19T00:00:01+00:00",
                    event_type="task.recovered",
                    message="unknown in-flight task failed during restart recovery",
                    task_id="task-1",
                )
            ]
        )
    )
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(state_path))

    service = _build_default_service()

    assert service.event_journal(limit=1)[0].event_type == "task.recovered"


def test_default_endpoint_service_restores_state_from_provided_store(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    store = FileStateStore(state_path)
    store.save(
        HypervisorStateSnapshot(
            endpoints=[
                EndpointManifestSnapshot(
                    endpoint_id="ep-1",
                    owner_wallet="wallet-1",
                    created_at="2026-06-29T00:00:00+00:00",
                    bundle_id="bundle-a",
                    bundle_hash="bundle-hash-a",
                    configuration_hash="cfg-a",
                    display_name="Operator STT",
                    model_class="speech.stt",
                    capabilities=["speech.stt"],
                )
            ],
            endpoint_configuration_snapshots=[
                EndpointConfigurationSnapshotRecord(
                    configuration_hash="cfg-a",
                    endpoint_id="ep-1",
                    bundle_hash="bundle-hash-a",
                    created_at="2026-06-29T00:00:00+00:00",
                    runtime=EndpointRuntimeConfig(streaming=True, timeout=30),
                    publication=EndpointPublicationPolicy(discoverable=True),
                    execution_config={"streaming": True, "timeout": 30},
                )
            ],
        )
    )

    service = _build_default_endpoint_service(store)

    assert [manifest.endpoint_id for manifest in service.list_endpoints()] == ["ep-1"]


def test_default_app_endpoint_api_persists_without_erasing_legacy_tasks(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    FileStateStore(state_path).save(
        HypervisorStateSnapshot(
            tasks=[
                TaskSnapshot(
                    task_id="task-1",
                    priority=50,
                    enqueue_index=0,
                    created_at="2026-06-19T00:00:00+00:00",
                    status="queued",
                    request=TaskRequest(
                        task_type="audio.transcribe",
                        payload={"audio_ref": "clip.wav"},
                    ),
                    bundle_id="whisper-a",
                )
            ]
        )
    )
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(state_path))
    client = TestClient(build_app())

    response = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Operator STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
            "runtime": {"streaming": False, "timeout": 30},
            "publication": {
                "visibility": "private",
                "discoverable": False,
                "validation": "disabled",
                "accepts_external_requests": False,
            },
        },
    )

    snapshot = FileStateStore(state_path).load()

    assert response.status_code == 201
    assert [task.task_id for task in snapshot.tasks] == ["task-1"]
    assert [manifest.display_name for manifest in snapshot.endpoints] == ["Operator STT"]


def test_default_app_restores_endpoint_state_from_configured_file(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    FileStateStore(state_path).save(
        HypervisorStateSnapshot(
            endpoints=[
                EndpointManifestSnapshot(
                    endpoint_id="ep-1",
                    owner_wallet="wallet-1",
                    created_at="2026-06-29T00:00:00+00:00",
                    bundle_id="bundle-a",
                    bundle_hash="bundle-hash-a",
                    configuration_hash="cfg-a",
                    display_name="Recovered STT",
                    model_class="speech.stt",
                    capabilities=["speech.stt"],
                )
            ],
            endpoint_configuration_snapshots=[
                EndpointConfigurationSnapshotRecord(
                    configuration_hash="cfg-a",
                    endpoint_id="ep-1",
                    bundle_hash="bundle-hash-a",
                    created_at="2026-06-29T00:00:00+00:00",
                    runtime=EndpointRuntimeConfig(streaming=True, timeout=30),
                    publication=EndpointPublicationPolicy(discoverable=True),
                    execution_config={"streaming": True, "timeout": 30},
                )
            ],
        )
    )
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(state_path))
    client = TestClient(build_app())

    response = client.get("/api/v1/endpoints")

    assert response.status_code == 200
    assert [item["endpoint_id"] for item in response.json()["data"]] == ["ep-1"]
    assert [item["display_name"] for item in response.json()["data"]] == [
        "Recovered STT"
    ]


def test_default_app_endpoint_api_uses_injected_service_state_store(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    monkeypatch.delenv("AIDN_HYPERVISOR_STATE_PATH", raising=False)
    client = TestClient(build_app(service=_service(state_path)))

    response = client.post(
        "/api/v1/endpoints",
        json={
            "owner_wallet": "wallet-1",
            "bundle_id": "bundle-a",
            "bundle_hash": "bundle-hash-a",
            "display_name": "Injected Service STT",
            "model_class": "speech.stt",
            "capabilities": ["speech.stt"],
            "runtime": {"streaming": False, "timeout": 30},
            "publication": {
                "visibility": "private",
                "discoverable": False,
                "validation": "disabled",
                "accepts_external_requests": False,
            },
        },
    )

    snapshot = FileStateStore(state_path).load()

    assert response.status_code == 201
    assert [manifest.display_name for manifest in snapshot.endpoints] == [
        "Injected Service STT"
    ]
