import pytest

from aidn_hypervisor.endpoints.endpoint_application_service import EndpointApplicationService
from aidn_hypervisor.endpoints.models import (
    CreateEndpointCommand,
    EndpointProfile,
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


def test_validator_endpoint_draft_does_not_record_publish_operation() -> None:
    recorded: list[dict] = []
    service = EndpointService(
        EndpointStore(),
        operation_recorder=lambda **kwargs: recorded.append(kwargs),
        record_creation_operation=False,
    )

    service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Draft Endpoint",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    assert recorded == []


def test_validator_endpoint_draft_update_does_not_record_wallet_operation() -> None:
    recorded: list[dict] = []
    service = EndpointService(
        EndpointStore(),
        operation_recorder=lambda **kwargs: recorded.append(kwargs),
        record_creation_operation=False,
        record_update_operation=False,
    )
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Draft Endpoint",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            pricing={"fixed_price": 1.0},
        )
    )

    assert recorded == []


def test_endpoint_application_delete_schedules_validation_custody_retirement() -> None:
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    calls: list[str] = []

    class ValidationStub:
        def request_endpoint_retirement(self, *, endpoint_id: str):
            calls.append(endpoint_id)
            return []

    application = EndpointApplicationService(
        endpoint_service=endpoint_service,
        validation_service=ValidationStub(),
    )

    result = application.delete_endpoint(created.endpoint.endpoint_id)

    assert result["deleted"].endpoint.status == "deleted"
    assert calls == [created.endpoint.endpoint_id]


def test_create_endpoint_accepts_runtime_binding_identity_with_bundle_fallback() -> None:
    cmd = CreateEndpointCommand(
        owner_wallet="wallet-a",
        runtime_binding_id="rtb-1",
        bundle_id="bundle-rtb-1",
        bundle_hash="bundle-hash-a",
        display_name="Local Qwen",
        model_class="llm.chat",
        capabilities=["llm.chat"],
    )

    assert cmd.runtime_binding_id == "rtb-1"
    assert cmd.bundle_id == "bundle-rtb-1"


def test_create_endpoint_persists_runtime_binding_in_configuration_commitment() -> None:
    created = EndpointService(EndpointStore()).create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-a",
            runtime_binding_id="rtb-1",
            bundle_id="bundle-rtb-1",
            bundle_hash="bundle-hash-a",
            display_name="Local Qwen",
            model_class="llm.chat",
            capabilities=["llm.chat"],
        )
    )

    assert created.endpoint.runtime_binding_id == "rtb-1"
    assert created.snapshot.runtime_binding_id == "rtb-1"
    assert created.snapshot.execution_config["runtime_binding_id"] == "rtb-1"


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


def test_update_endpoint_pricing_rotates_configuration_hash_and_snapshot() -> None:
    service = EndpointService(EndpointStore())
    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            pricing={"fixed_price": 2.0},
        )
    )

    updated = service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            pricing={"audio_input_second_price": 0.4, "fixed_price": 2.0},
        )
    )

    assert updated.endpoint.configuration_hash != created.endpoint.configuration_hash
    assert updated.snapshot is not None
    assert updated.snapshot.pricing.audio_input_second_price == 0.4
    assert len(service.list_configuration_snapshots(created.endpoint.endpoint_id)) == 2


def test_update_endpoint_marketplace_description_rotates_configuration_hash() -> None:
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
            profile=EndpointProfile(
                summary="Fast speech recognition",
                marketplace_description={"html": "<p>Try this endpoint.</p>"},
            ),
        )
    )

    assert updated.endpoint.configuration_hash != created.endpoint.configuration_hash
    assert updated.snapshot is not None
    assert updated.snapshot.profile.marketplace_description is not None
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


def test_create_endpoint_persists_session_policy() -> None:
    service = EndpointService(EndpointStore())

    created = service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Paid STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            session={
                "minimum_deposit": 10.0,
                "recommended_deposit": 25.0,
                "idle_fee_per_minute": 1.0,
                "idle_timeout_seconds": 600,
                "max_concurrent_sessions": 2,
                "maximum_session_duration_seconds": 3600,
                "queue_policy": "busy",
                "minimum_session_fee": 2.0,
            },
        )
    )

    assert created.endpoint.session.minimum_deposit == 10.0
    assert created.endpoint.session.max_concurrent_sessions == 2
    assert created.snapshot.session.queue_policy == "busy"
