import pytest

from aidn_hypervisor.endpoints.models import (
    CreateEndpointCommand,
    UpdateEndpointCommand,
)
from aidn_hypervisor.endpoints.service import EndpointService, EndpointStateError
from aidn_hypervisor.endpoints.store import EndpointStore


def test_create_endpoint_generates_initial_configuration_snapshot() -> None:
    service = EndpointService(EndpointStore())

    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    assert created.endpoint.status == "created"
    assert created.snapshot.endpoint_id == created.endpoint.endpoint_id
    assert created.snapshot.configuration_hash == created.endpoint.configuration_hash


def test_update_endpoint_runtime_creates_new_configuration_hash() -> None:
    service = EndpointService(EndpointStore())
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    updated = service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={"streaming": True, "timeout": 45},
        )
    )

    assert updated.endpoint.configuration_hash != created.endpoint.configuration_hash
    assert len(service.list_configuration_snapshots(created.endpoint.endpoint_id)) == 2


def test_suspend_requires_active_endpoint() -> None:
    service = EndpointService(EndpointStore())
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    with pytest.raises(EndpointStateError):
        service.suspend_endpoint(created.endpoint.endpoint_id)


def test_update_endpoint_can_enable_validation_without_rotating_configuration() -> None:
    service = EndpointService(EndpointStore())
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a"],
            },
        )
    )

    updated = service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            validation={
                "enabled": True,
                "model_class_supported": True,
                "verification_status": "pending",
            },
        )
    )

    assert updated.endpoint.publication.visibility == "shared"
    assert updated.endpoint.validation.enabled is True
    assert updated.endpoint.validation.verification_status == "pending"
    assert updated.endpoint.configuration_hash == created.endpoint.configuration_hash
    assert updated.snapshot is None


def test_create_endpoint_preserves_shared_wallet_allowlist() -> None:
    service = EndpointService(EndpointStore())

    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Shared STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            publication={
                "visibility": "shared",
                "shared_with_wallet_ids": ["wallet-a", "wallet-b"],
            },
        )
    )

    assert created.endpoint.publication.visibility == "shared"
    assert created.endpoint.publication.shared_with_wallet_ids == ["wallet-a", "wallet-b"]
    assert (
        created.snapshot.publication.shared_with_wallet_ids
        == ["wallet-a", "wallet-b"]
    )
