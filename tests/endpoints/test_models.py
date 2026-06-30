from pathlib import Path

import pytest
from pydantic import ValidationError

from aidn_hypervisor import endpoints
from aidn_hypervisor.endpoints.models import (
    CreateEndpointCommand,
    EndpointConfigurationSnapshot,
    EndpointInvokeRequest,
    EndpointManifest,
    EndpointPricing,
    EndpointPublicationPolicy,
    EndpointReadiness,
    EndpointRuntimeConfig,
    InvokeEndpointCommand,
    InvokeEndpointResult,
)
from aidn_hypervisor.endpoints.state import (
    EndpointConfigurationSnapshotRecord,
    EndpointManifestSnapshot,
)
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.state import HypervisorStateSnapshot


def test_endpoint_manifest_defaults_to_created_status() -> None:
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
    )

    assert manifest.status == "created"
    assert manifest.publication.visibility == "private"
    assert manifest.pricing.billing_unit == "request"


def test_create_endpoint_command_requires_bundle_identity() -> None:
    with pytest.raises(ValidationError) as exc_info:
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )

    locations = {tuple(error["loc"]) for error in exc_info.value.errors()}

    assert ("bundle_id",) in locations
    assert ("bundle_hash",) in locations


def test_configuration_snapshot_requires_bundle_hash() -> None:
    with pytest.raises(ValidationError) as exc_info:
        EndpointConfigurationSnapshot(
            configuration_hash="cfg-a",
            endpoint_id="ep-1",
            created_at="2026-06-29T00:00:00+00:00",
            runtime=EndpointRuntimeConfig(streaming=True, timeout=30),
            publication=EndpointPublicationPolicy(discoverable=True),
            execution_config={"streaming": True, "timeout": 30},
        )

    assert ("bundle_hash",) in [tuple(error["loc"]) for error in exc_info.value.errors()]


def test_endpoint_invoke_request_defaults_constraints() -> None:
    request = EndpointInvokeRequest(
        task_type="llm_text.generate",
        payload={"prompt": "hello"},
    )

    assert request.constraints == {}


def test_endpoint_readiness_captures_runtime_projection() -> None:
    readiness = EndpointReadiness(
        endpoint_id="ep-1",
        bundle_id="text-a",
        ready=False,
        code="endpoint_runtime_unavailable",
        message="Endpoint ep-1 has no ready runtime",
        runtime_id="runtime-1",
        runtime_status="starting",
        runtime_health_status="degraded",
    )

    assert readiness.ready is False
    assert readiness.code == "endpoint_runtime_unavailable"
    assert readiness.bundle_id == "text-a"
    assert readiness.runtime_id == "runtime-1"
    assert readiness.runtime_status == "starting"
    assert readiness.runtime_health_status == "degraded"


def test_endpoint_readiness_requires_reason_when_not_ready() -> None:
    with pytest.raises(ValidationError) as exc_info:
        EndpointReadiness(
            endpoint_id="ep-1",
            bundle_id="text-a",
            ready=False,
        )

    errors = exc_info.value.errors()

    assert len(errors) == 1
    assert "code and message" in errors[0]["msg"]


def test_invoke_endpoint_command_defaults_constraints() -> None:
    command = InvokeEndpointCommand(
        endpoint_id="ep-1",
        task_type="llm_text.generate",
        payload={"prompt": "hello"},
    )

    assert command.endpoint_id == "ep-1"
    assert command.task_type == "llm_text.generate"
    assert command.payload == {"prompt": "hello"}
    assert command.constraints == {}


def test_invoke_endpoint_result_exposes_runtime_and_result_payload() -> None:
    result = InvokeEndpointResult(
        endpoint=EndpointManifest(
            endpoint_id="ep-1",
            owner_wallet="wallet-1",
            created_at="2026-06-29T00:00:00+00:00",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            configuration_hash="cfg-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        ),
        bundle_id="bundle-a",
        runtime_id="runtime-1",
        readiness=EndpointReadiness(
            endpoint_id="ep-1",
            bundle_id="bundle-a",
            ready=True,
            runtime_id="runtime-1",
            runtime_status="ready",
            runtime_health_status="healthy",
        ),
        result={"text": "hello"},
    )

    assert result.bundle_id == "bundle-a"
    assert result.runtime_id == "runtime-1"
    assert result.readiness.ready is True
    assert result.result == {"text": "hello"}


def test_endpoint_package_exports_only_domain_models() -> None:
    assert set(endpoints.__all__) == {
        "CreateEndpointCommand",
        "EndpointConfigurationSnapshot",
        "EndpointInvokeRequest",
        "EndpointManifest",
        "EndpointPricing",
        "EndpointProfile",
        "EndpointPublicationPolicy",
        "EndpointReadiness",
        "EndpointRuntimeConfig",
        "EndpointStatus",
        "EndpointValidationMode",
        "EndpointValidationState",
        "EndpointVerificationStatus",
        "EndpointVisibility",
        "InvokeEndpointCommand",
        "InvokeEndpointResult",
    }
    assert endpoints.EndpointInvokeRequest is EndpointInvokeRequest
    assert endpoints.EndpointReadiness is EndpointReadiness
    assert endpoints.InvokeEndpointCommand is InvokeEndpointCommand
    assert endpoints.InvokeEndpointResult is InvokeEndpointResult


def test_hypervisor_state_snapshot_round_trips_endpoint_records(
    tmp_path: Path,
) -> None:
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
                runtime=EndpointRuntimeConfig(streaming=True, timeout=30),
                publication=EndpointPublicationPolicy(discoverable=True),
                execution_config={"streaming": True, "timeout": 30},
            )
        ],
    )

    store.save(snapshot)
    restored = store.load()

    assert isinstance(restored.endpoints[0], EndpointManifestSnapshot)
    assert restored.endpoints[0].endpoint_id == "ep-1"
    assert isinstance(
        restored.endpoint_configuration_snapshots[0],
        EndpointConfigurationSnapshotRecord,
    )
    assert restored.endpoint_configuration_snapshots[0].bundle_hash == "bundle-hash-a"
