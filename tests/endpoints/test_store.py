import pytest

from pathlib import Path

from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.endpoints.models import (
    EndpointConfigurationSnapshot,
    EndpointManifest,
    EndpointPricing,
)
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.state import HypervisorStateSnapshot, TaskSnapshot


def test_endpoint_store_requires_explicit_in_memory_opt_in() -> None:
    with pytest.raises(ValueError, match="allow_in_memory=True"):
        EndpointStore()


def test_endpoint_store_round_trips_manifest_and_configuration_history(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    file_store = FileStateStore(state_path)
    file_store.save(
        HypervisorStateSnapshot(
            tasks=[
                TaskSnapshot(
                    task_id="task-1",
                    priority=50,
                    enqueue_index=0,
                    created_at="2026-06-29T00:00:00+00:00",
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

    manifest = EndpointManifest(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        created_at="2026-06-29T00:00:00+00:00",
        bundle_id="bundle-a",
        bundle_hash="bundle-hash-a",
        configuration_hash="cfg-a",
        display_name="Operator STT",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        pricing=EndpointPricing(
            billing_unit="second",
            input_price=0.4,
            output_price=0.0,
        ),
    )
    snapshot = EndpointConfigurationSnapshot(
        configuration_hash="cfg-a",
        endpoint_id="ep-1",
        bundle_hash="bundle-hash-a",
        created_at="2026-06-29T00:00:00+00:00",
        runtime=manifest.runtime,
        publication=manifest.publication,
        execution_config={"streaming": False, "timeout": None},
    )

    store = EndpointStore(file_store)
    store.save_manifest(manifest)
    store.save_configuration_snapshot(snapshot)

    reloaded = EndpointStore(file_store)
    reloaded_manifest = reloaded.get_manifest("ep-1")
    reloaded_snapshots = reloaded.list_configuration_snapshots("ep-1")
    reloaded_snapshot = reloaded_snapshots[0]

    assert reloaded_manifest.endpoint_id == "ep-1"
    assert reloaded_manifest.bundle_hash == "bundle-hash-a"
    assert reloaded_manifest.display_name == "Operator STT"
    assert reloaded_manifest.pricing.billing_unit == "second"
    assert reloaded_manifest.pricing.input_price == 0.4
    assert len(reloaded_snapshots) == 1
    assert reloaded_snapshot.configuration_hash == "cfg-a"
    assert reloaded_snapshot.bundle_hash == "bundle-hash-a"
    assert reloaded_snapshot.execution_config["streaming"] is False
    assert FileStateStore(state_path).load().tasks[0].task_id == "task-1"


def test_endpoint_store_read_methods_return_defensive_copies(tmp_path: Path) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    file_store = FileStateStore(state_path)
    manifest = EndpointManifest(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        created_at="2026-06-29T00:00:00+00:00",
        bundle_id="bundle-a",
        bundle_hash="bundle-hash-a",
        configuration_hash="cfg-a",
        display_name="Operator STT",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        pricing=EndpointPricing(
            billing_unit="second",
            input_price=0.4,
            output_price=0.0,
        ),
    )
    snapshot = EndpointConfigurationSnapshot(
        configuration_hash="cfg-a",
        endpoint_id="ep-1",
        bundle_hash="bundle-hash-a",
        created_at="2026-06-29T00:00:00+00:00",
        runtime=manifest.runtime,
        publication=manifest.publication,
        execution_config={"streaming": False, "timeout": None},
    )
    store = EndpointStore(file_store)
    store.save_manifest(manifest)
    store.save_configuration_snapshot(snapshot)

    listed_manifest = store.list_manifests()[0]
    retrieved_manifest = store.get_manifest("ep-1")
    retrieved_snapshot = store.list_configuration_snapshots("ep-1")[0]

    listed_manifest.bundle_hash = "mutated-bundle-hash"
    retrieved_manifest.pricing.input_price = 9.9
    retrieved_snapshot.execution_config["streaming"] = True

    assert store.list_manifests()[0].bundle_hash == "bundle-hash-a"
    assert store.get_manifest("ep-1").pricing.input_price == 0.4
    assert (
        store.list_configuration_snapshots("ep-1")[0].execution_config["streaming"]
        is False
    )
