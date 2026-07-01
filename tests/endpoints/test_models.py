import pytest
from pydantic import ValidationError

from aidn_hypervisor.endpoints.models import (
    CreateEndpointCommand,
    EndpointConfigurationSnapshot,
    EndpointManifest,
    EndpointPricing,
    EndpointPublicationPolicy,
    EndpointRuntimeConfig,
)


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
    with pytest.raises(ValidationError):
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )


def test_configuration_snapshot_requires_bundle_hash() -> None:
    with pytest.raises(ValidationError):
        EndpointConfigurationSnapshot(
            configuration_hash="cfg-a",
            endpoint_id="ep-1",
            created_at="2026-06-29T00:00:00+00:00",
            runtime=EndpointRuntimeConfig(streaming=True, timeout=30),
            publication=EndpointPublicationPolicy(discoverable=True),
            execution_config={"streaming": True, "timeout": 30},
        )


def test_endpoint_pricing_rejects_negative_costs() -> None:
    with pytest.raises(ValidationError):
        EndpointPricing(billing_unit="tokens", input_price=-1)


def test_shared_publication_requires_allowed_wallets() -> None:
    with pytest.raises(ValidationError):
        EndpointPublicationPolicy(visibility="shared")


def test_non_shared_publication_discards_allowlist() -> None:
    policy = EndpointPublicationPolicy(
        visibility="public",
        shared_with_wallet_ids=["wallet-a", "wallet-b"],
    )

    assert policy.shared_with_wallet_ids == []
