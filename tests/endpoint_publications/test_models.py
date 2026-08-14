import pytest
from pydantic import ValidationError

from aidn_hypervisor.endpoint_publications.models import (
    PublishedEndpointConfiguration,
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
from aidn_hypervisor.endpoints.models import EndpointMarketplaceDescription


def test_configuration_hash_changes_when_execution_relevant_fields_change() -> None:
    payload_a = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        runtime={"context_length": 8192, "timeout": 45, "streaming": True},
        publication={
            "visibility": "shared",
            "shared_with_wallet_ids": ["wallet-a"],
            "discoverable": True,
            "validation": "disabled",
            "accepts_external_requests": True,
        },
        pricing={"billing_unit": "request", "input_price": 1.0},
    )
    payload_b = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        runtime={"context_length": 8192, "timeout": 60, "streaming": True},
        publication={
            "visibility": "shared",
            "shared_with_wallet_ids": ["wallet-a"],
            "discoverable": True,
            "validation": "disabled",
            "accepts_external_requests": True,
        },
        pricing={"billing_unit": "request", "input_price": 1.0},
    )

    assert configuration_hash_for_publication(payload_a) != configuration_hash_for_publication(
        payload_b
    )


def test_configuration_hash_treats_capabilities_as_order_stable() -> None:
    payload_a = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.translate", "speech.stt"],
        runtime={"context_length": 8192, "timeout": 45, "streaming": True},
        publication={
            "visibility": "public",
            "shared_with_wallet_ids": [],
            "discoverable": True,
            "validation": "disabled",
            "accepts_external_requests": True,
        },
        pricing={"billing_unit": "request", "input_price": 1.0},
    )
    payload_b = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt", "speech.translate"],
        runtime={"context_length": 8192, "timeout": 45, "streaming": True},
        publication={
            "visibility": "public",
            "shared_with_wallet_ids": [],
            "discoverable": True,
            "validation": "disabled",
            "accepts_external_requests": True,
        },
        pricing={"billing_unit": "request", "input_price": 1.0},
    )

    assert payload_a["capabilities"] == payload_b["capabilities"]
    assert configuration_hash_for_publication(payload_a) == configuration_hash_for_publication(
        payload_b
    )


def test_configuration_hash_binds_marketplace_description_only_when_present() -> None:
    base = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        runtime={},
        publication={"visibility": "public"},
        pricing={},
    )
    described = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        runtime={},
        publication={"visibility": "public"},
        pricing={},
        profile={
            "marketplace_description": {
                "html": "<p>Safe</p>",
                "sanitizer_version": "aidn-marketplace-html.v1",
                "content_hash": "sha256:description",
            }
        },
    )

    assert "marketplace_description" not in base
    assert "marketplace_description" in described
    assert configuration_hash_for_publication(base) != configuration_hash_for_publication(described)


def test_published_endpoint_configuration_excludes_signature_from_signed_payload() -> None:
    canonical_payload = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        runtime={"timeout": 45, "streaming": True},
        publication={"visibility": "public", "discoverable": True},
        pricing={"billing_unit": "request"},
    )
    record = PublishedEndpointConfiguration(
        schema_version="epcfg.v1",
        publication_id="pub-1",
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        node_id="node-1",
        configuration_hash=configuration_hash_for_publication(canonical_payload),
        previous_configuration_hash=None,
        bundle_id="bundle-a",
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        profile={"summary": "Operator STT"},
        runtime={"timeout": 45, "streaming": True},
        publication={"visibility": "public", "discoverable": True},
        pricing={"billing_unit": "request"},
        validation_requirement={"enabled": False},
        published_at="2026-06-30T00:00:00+00:00",
        sequence=1,
        status="published",
        wallet_signature="sig-1",
    )

    assert "wallet_signature" not in record.signed_payload()


def test_published_configuration_normalizes_marketplace_html_before_hash_check() -> None:
    description = EndpointMarketplaceDescription(
        html="<p>Safe<script>alert(1)</script></p>"
    )
    profile = {
        "summary": "Operator STT",
        "marketplace_description": description.model_dump(mode="json"),
    }
    payload = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        runtime={},
        publication={"visibility": "public"},
        pricing={},
        profile=profile,
    )

    record = PublishedEndpointConfiguration(
        schema_version="epcfg.v1",
        publication_id="pub-safe-description",
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        node_id="node-1",
        configuration_hash=configuration_hash_for_publication(payload),
        bundle_id="bundle-a",
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        profile={
            "summary": "Operator STT",
            "marketplace_description": {
                "html": "<p>Safe<script>alert(1)</script></p>",
            },
        },
        runtime={},
        publication={"visibility": "public"},
        pricing={},
        published_at="2026-06-30T00:00:00+00:00",
        sequence=1,
        wallet_signature="sig-1",
    )

    assert record.profile["marketplace_description"] == description.model_dump(
        mode="json"
    )


def test_published_endpoint_configuration_rejects_inconsistent_configuration_hash() -> None:
    with pytest.raises(ValidationError):
        PublishedEndpointConfiguration(
            schema_version="epcfg.v1",
            publication_id="pub-1",
            endpoint_id="ep-1",
            owner_wallet="wallet-1",
            node_id="node-1",
            configuration_hash="cfg-1",
            previous_configuration_hash=None,
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            model_class="speech.stt",
            capabilities=["speech.stt"],
            profile={"summary": "Operator STT"},
            runtime={"timeout": 45, "streaming": True},
            publication={"visibility": "public", "discoverable": True},
            pricing={"billing_unit": "request"},
            validation_requirement={"enabled": False},
            published_at="2026-06-30T00:00:00+00:00",
            sequence=1,
            status="published",
            wallet_signature="sig-1",
        )
