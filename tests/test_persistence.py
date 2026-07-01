from pathlib import Path

from aidn_hypervisor.domain.models import (
    BundleConfig,
    NodeCapacity,
    ResourceProfile,
    TaskRequest,
)
from aidn_hypervisor.endpoint_publications.models import (
    PublishedEndpointConfiguration,
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.state import (
    EndpointConfigurationSnapshotRecord,
    EndpointManifestSnapshot,
)
from aidn_hypervisor.main import _build_default_service
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.remote_endpoints.models import RemoteEndpointReference
from aidn_hypervisor.remote_endpoints.store import RemoteEndpointStore
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.state import HypervisorStateSnapshot, JournalEvent, TaskSnapshot


def _published_record(
    publication_id: str,
    *,
    endpoint_id: str = "ep-1",
    sequence: int = 1,
) -> PublishedEndpointConfiguration:
    canonical_payload = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        runtime={"timeout": 45, "streaming": True},
        publication={"visibility": "public", "discoverable": True},
        pricing={"billing_unit": "request"},
    )
    configuration_hash = configuration_hash_for_publication(canonical_payload)
    previous_hash = configuration_hash if sequence > 1 else None
    return PublishedEndpointConfiguration(
        schema_version="epcfg.v1",
        publication_id=publication_id,
        endpoint_id=endpoint_id,
        owner_wallet="wallet-1",
        node_id="node-1",
        configuration_hash=configuration_hash,
        previous_configuration_hash=previous_hash,
        bundle_id="bundle-a",
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        profile={},
        runtime={"timeout": 45, "streaming": True},
        publication={"visibility": "public", "discoverable": True},
        pricing={"billing_unit": "request"},
        validation_requirement={},
        published_at=f"2026-06-30T00:00:0{sequence}+00:00",
        sequence=sequence,
        status="published",
        wallet_signature=f"sig-{publication_id}",
    )


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


def _remote_endpoint(
    remote_endpoint_id: str,
    *,
    source_endpoint_id: str = "ep-remote",
) -> RemoteEndpointReference:
    return RemoteEndpointReference(
        remote_endpoint_id=remote_endpoint_id,
        source_node_id="node-remote",
        source_endpoint_id=source_endpoint_id,
        source_owner_wallet="wallet-remote",
        source_publication_id=f"pub-{remote_endpoint_id}",
        source_configuration_hash=f"cfg-{remote_endpoint_id}",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-remote",
        alias="Preferred Remote",
        attached_at="2026-06-30T00:00:00+00:00",
        last_seen_at="2026-06-30T00:00:00+00:00",
        pricing={"unit": "q_per_1kk_tokens", "input": 8, "output": 12},
        rating={"score": 0.96, "tier": "A", "updated_at": "2026-06-30T00:00:00+00:00"},
    )


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
    )

    store.save(snapshot)
    restored = store.load()

    assert restored == snapshot


def test_file_state_store_returns_empty_snapshot_when_file_is_missing(
    tmp_path: Path,
) -> None:
    store = FileStateStore(tmp_path / "missing-state.json")

    assert store.load() == HypervisorStateSnapshot()


def test_file_state_store_round_trips_endpoint_snapshot_fields(tmp_path: Path) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    store = FileStateStore(state_path)
    snapshot = HypervisorStateSnapshot(
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
                runtime={},
                publication={},
                execution_config={"streaming": False},
            )
        ],
    )

    store.save(snapshot)
    restored = store.load()

    assert restored.endpoints[0].endpoint_id == "ep-1"
    assert restored.endpoint_configuration_snapshots[0].configuration_hash == "cfg-a"


def test_file_state_store_round_trips_endpoint_publication_records(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    store = FileStateStore(state_path)
    snapshot = HypervisorStateSnapshot(
        endpoint_publications=[_published_record("pub-1")]
    )

    store.save(snapshot)
    restored = store.load()

    assert restored == snapshot


def test_endpoint_publication_store_restores_records_from_state_store(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    file_store = FileStateStore(state_path)
    snapshot = HypervisorStateSnapshot(
        endpoint_publications=[_published_record("pub-1")]
    )
    file_store.save(snapshot)

    store = EndpointPublicationStore(file_store)

    assert store.list_records() == snapshot.endpoint_publications


def test_endpoint_publication_store_accumulates_appended_records(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    file_store = FileStateStore(state_path)
    store = EndpointPublicationStore(file_store)
    first = _published_record("pub-1")
    second = _published_record("pub-2", sequence=2)

    store.append(first)
    store.append(second)

    assert store.list_records() == [first, second]


def test_endpoint_publication_store_persists_records_after_append(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    file_store = FileStateStore(state_path)
    store = EndpointPublicationStore(file_store)
    first = _published_record("pub-1")
    second = _published_record("pub-2", sequence=2)

    store.append(first)
    store.append(second)

    reloaded = EndpointPublicationStore(file_store)

    assert reloaded.list_records() == [first, second]


def test_endpoint_publication_store_replaces_records_and_persists_them(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    file_store = FileStateStore(state_path)
    store = EndpointPublicationStore(file_store)
    first = _published_record("pub-1")
    second = _published_record("pub-2", sequence=2)
    superseded_first = first.model_copy(update={"status": "superseded"})

    store.append(first)
    store.replace_records([superseded_first, second])

    reloaded = EndpointPublicationStore(file_store)

    assert store.list_records() == [superseded_first, second]
    assert reloaded.list_records() == [superseded_first, second]


def test_endpoint_publication_store_append_is_atomic_when_save_fails() -> None:
    class FailingStateStore:
        def __init__(self) -> None:
            self.snapshot = HypervisorStateSnapshot(
                endpoint_publications=[_published_record("pub-1")]
            )

        def load(self) -> HypervisorStateSnapshot:
            return self.snapshot.model_copy(deep=True)

        def save(self, snapshot: HypervisorStateSnapshot) -> None:
            raise RuntimeError("disk full")

    failing_state_store = FailingStateStore()
    store = EndpointPublicationStore(failing_state_store)
    original_records = store.list_records()

    try:
        store.append(_published_record("pub-2", sequence=2))
    except RuntimeError as exc:
        assert str(exc) == "disk full"
    else:
        raise AssertionError("append should propagate save failure")

    assert store.list_records() == original_records
    assert failing_state_store.load().endpoint_publications == original_records


def test_endpoint_publication_store_defensively_copies_records_at_boundary(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    file_store = FileStateStore(state_path)
    store = EndpointPublicationStore(file_store)
    appended = _published_record("pub-1")

    store.append(appended)
    appended.wallet_signature = "sig-mutated-by-caller"

    listed = store.list_records()
    listed[0].wallet_signature = "sig-mutated-from-list"

    reloaded = EndpointPublicationStore(file_store)

    assert store.list_records()[0].wallet_signature == "sig-pub-1"
    assert reloaded.list_records()[0].wallet_signature == "sig-pub-1"


def test_file_state_store_round_trips_remote_endpoint_records(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    store = FileStateStore(state_path)
    snapshot = HypervisorStateSnapshot(remote_endpoints=[_remote_endpoint("remote-1")])

    store.save(snapshot)
    restored = store.load()

    assert restored == snapshot


def test_remote_endpoint_store_restores_records_from_state_store(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    file_store = FileStateStore(state_path)
    snapshot = HypervisorStateSnapshot(
        remote_endpoints=[_remote_endpoint("remote-1")]
    )
    file_store.save(snapshot)

    store = RemoteEndpointStore(file_store)

    assert store.list_records() == snapshot.remote_endpoints


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
