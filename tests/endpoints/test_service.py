from pathlib import Path

import pytest

from aidn_hypervisor.endpoints.models import CreateEndpointCommand, UpdateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService, EndpointStateError
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.persistence import FileStateStore


def _create_command(**overrides) -> CreateEndpointCommand:
    payload = {
        "owner_wallet": "wallet-1",
        "bundle_id": "bundle-a",
        "bundle_hash": "bundle-hash-a",
        "display_name": "Operator STT",
        "model_class": "speech.stt",
        "capabilities": ["speech.stt"],
    }
    payload.update(overrides)
    return CreateEndpointCommand(**payload)


def test_create_endpoint_generates_initial_configuration_snapshot() -> None:
    service = EndpointService(EndpointStore(allow_in_memory=True))

    created = service.create_endpoint(_create_command())
    snapshots = service.list_configuration_snapshots(created.endpoint.endpoint_id)

    assert created.endpoint.status == "created"
    assert created.snapshot.endpoint_id == created.endpoint.endpoint_id
    assert created.snapshot.configuration_hash == created.endpoint.configuration_hash
    assert created.snapshot.execution_config == {
        "accepts_external_requests": False,
        "streaming": False,
        "timeout": None,
        "max_concurrency": None,
    }
    assert len(snapshots) == 1


def test_update_endpoint_runtime_rotates_configuration_hash_and_adds_snapshot() -> None:
    service = EndpointService(EndpointStore(allow_in_memory=True))
    created = service.create_endpoint(_create_command())

    updated = service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={"streaming": True, "timeout": 45},
        )
    )

    assert updated.snapshot is not None
    assert updated.endpoint.configuration_hash != created.endpoint.configuration_hash
    assert len(service.list_configuration_snapshots(created.endpoint.endpoint_id)) == 2


def test_partial_runtime_update_preserves_existing_runtime_fields() -> None:
    service = EndpointService(EndpointStore(allow_in_memory=True))
    created = service.create_endpoint(
        _create_command(runtime={"max_tokens": 512, "timeout": 30})
    )

    updated = service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={"streaming": True},
        )
    )

    assert updated.snapshot is not None
    assert updated.endpoint.configuration_hash != created.endpoint.configuration_hash
    assert updated.endpoint.runtime.streaming is True
    assert updated.endpoint.runtime.max_tokens == 512
    assert updated.endpoint.runtime.timeout == 30
    assert updated.snapshot.runtime.streaming is True
    assert updated.snapshot.runtime.max_tokens == 512
    assert updated.snapshot.runtime.timeout == 30
    assert updated.snapshot.execution_config["max_concurrency"] == 512
    assert updated.snapshot.execution_config["timeout"] == 30


def test_partial_pricing_update_preserves_existing_pricing_fields() -> None:
    service = EndpointService(EndpointStore(allow_in_memory=True))
    created = service.create_endpoint(
        _create_command(
            pricing={
                "billing_unit": "second",
                "input_price": 0.4,
            }
        )
    )

    updated = service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            pricing={"output_price": 1.2},
        )
    )

    assert updated.snapshot is None
    assert updated.endpoint.pricing.billing_unit == "second"
    assert updated.endpoint.pricing.input_price == 0.4
    assert updated.endpoint.pricing.output_price == 1.2
    assert updated.endpoint.configuration_hash == created.endpoint.configuration_hash


def test_partial_validation_update_preserves_existing_validation_fields() -> None:
    service = EndpointService(EndpointStore(allow_in_memory=True))
    created = service.create_endpoint(
        _create_command(
            validation={
                "enabled": True,
                "model_class_supported": True,
            }
        )
    )

    updated = service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            validation={"validation_profile": "strict"},
        )
    )

    assert updated.snapshot is None
    assert updated.endpoint.validation.enabled is True
    assert updated.endpoint.validation.model_class_supported is True
    assert updated.endpoint.validation.validation_profile == "strict"
    assert (
        updated.endpoint.validation.verification_status
        == created.endpoint.validation.verification_status
    )


def test_update_endpoint_metadata_does_not_rotate_configuration_hash() -> None:
    service = EndpointService(EndpointStore(allow_in_memory=True))
    created = service.create_endpoint(_create_command())

    updated = service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            display_name="Operator STT v2",
        )
    )

    assert updated.snapshot is None
    assert updated.endpoint.display_name == "Operator STT v2"
    assert updated.endpoint.configuration_hash == created.endpoint.configuration_hash
    assert len(service.list_configuration_snapshots(created.endpoint.endpoint_id)) == 1


def test_suspend_requires_active_endpoint() -> None:
    service = EndpointService(EndpointStore(allow_in_memory=True))
    created = service.create_endpoint(_create_command())

    with pytest.raises(EndpointStateError):
        service.suspend_endpoint(created.endpoint.endpoint_id)


def test_endpoint_lifecycle_transitions_follow_expected_order() -> None:
    service = EndpointService(EndpointStore(allow_in_memory=True))
    created = service.create_endpoint(_create_command())

    started = service.start_endpoint(created.endpoint.endpoint_id)
    suspended = service.suspend_endpoint(created.endpoint.endpoint_id)
    resumed = service.resume_endpoint(created.endpoint.endpoint_id)
    stopped = service.stop_endpoint(created.endpoint.endpoint_id)
    deleted = service.delete_endpoint(created.endpoint.endpoint_id)

    assert started.endpoint.status == "active"
    assert suspended.endpoint.status == "suspended"
    assert resumed.endpoint.status == "active"
    assert stopped.endpoint.status == "stopped"
    assert deleted.endpoint.status == "deleted"


def test_persistence_backed_service_keeps_manifest_and_snapshot_history_coherent(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "hypervisor-state.json"
    file_store = FileStateStore(state_path)
    service = EndpointService(EndpointStore(file_store))
    created = service.create_endpoint(
        _create_command(runtime={"max_tokens": 512, "timeout": 30})
    )

    updated = service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={"streaming": True},
        )
    )

    reloaded_store = EndpointStore(file_store)
    reloaded_manifest = reloaded_store.get_manifest(created.endpoint.endpoint_id)
    reloaded_snapshots = reloaded_store.list_configuration_snapshots(
        created.endpoint.endpoint_id
    )

    assert len(reloaded_snapshots) == 2
    assert reloaded_manifest.configuration_hash == updated.endpoint.configuration_hash
    assert reloaded_snapshots[-1].configuration_hash == reloaded_manifest.configuration_hash
    assert reloaded_snapshots[-1].runtime.streaming is True
    assert reloaded_snapshots[-1].runtime.max_tokens == 512
