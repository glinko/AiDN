import pytest
from pydantic import ValidationError

from aidn_hypervisor.endpoint_publications.models import (
    PublishedEndpointConfiguration,
    canonical_configuration_payload,
    configuration_hash_for_publication,
    legacy_configuration_hash_for_publication,
    legacy_local_agent_use_configuration_hash,
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
        pricing={"rate_card": {"components": [{
            "component_id": "input", "dimension": "input_tokens",
            "unit_price_q_atoms": 1_000_000, "unit_divisor": 1_000_000,
            "accounting_mode": "provider_metered",
        }]}},
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
        pricing={"rate_card": {"components": [{
            "component_id": "input", "dimension": "input_tokens",
            "unit_price_q_atoms": 1_000_000, "unit_divisor": 1_000_000,
            "accounting_mode": "provider_metered",
        }]}},
    )

    assert configuration_hash_for_publication(payload_a) != configuration_hash_for_publication(
        payload_b
    )


def test_configuration_hash_binds_endpoint_parameter_policy() -> None:
    base_kwargs = {
        "bundle_hash": "bundle-hash-a",
        "model_class": "llm.chat",
        "capabilities": ["llm.chat"],
        "runtime": {"streaming": True},
        "publication": {"visibility": "public"},
        "pricing": {},
    }
    unlocked = {
        "temperature": {
            "value": 0.7,
            "consumer_editable": True,
            "min": 0.0,
            "max": 2.0,
        }
    }
    locked = {"temperature": {**unlocked["temperature"], "consumer_editable": False}}

    assert configuration_hash_for_publication(
        canonical_configuration_payload(
            **base_kwargs,
            runtime_parameter_policy=unlocked,
        )
    ) != configuration_hash_for_publication(
        canonical_configuration_payload(
            **base_kwargs,
            runtime_parameter_policy=locked,
        )
    )


def test_configuration_hash_has_no_local_agent_permission_field() -> None:
    base = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="llm_text",
        capabilities=["llm_text"],
        runtime={"streaming": False},
        publication={"visibility": "private"},
        pricing={},
    )
    assert "local_agent_use" not in base


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
        pricing={"rate_card": {"components": [{
            "component_id": "input", "dimension": "input_tokens",
            "unit_price_q_atoms": 1_000_000, "unit_divisor": 1_000_000,
            "accounting_mode": "provider_metered",
        }]}},
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
        pricing={"rate_card": {"components": [{
            "component_id": "input", "dimension": "input_tokens",
            "unit_price_q_atoms": 1_000_000, "unit_divisor": 1_000_000,
            "accounting_mode": "provider_metered",
        }]}},
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
        pricing={},
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
        pricing={},
        validation_requirement={"enabled": False},
        published_at="2026-06-30T00:00:00+00:00",
        sequence=1,
        status="published",
        wallet_signature="sig-1",
    )

    assert "wallet_signature" not in record.signed_payload()


def test_published_configuration_accepts_pre_migration_local_agent_signature() -> None:
    canonical_payload = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="llm_text",
        capabilities=["llm_text"],
        runtime={"streaming": False},
        publication={"visibility": "private"},
        pricing={},
    )
    record = PublishedEndpointConfiguration(
        publication_id="pub-local-agent-legacy",
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        node_id="node-1",
        configuration_hash=legacy_local_agent_use_configuration_hash(canonical_payload),
        bundle_id="bundle-a",
        bundle_hash="bundle-hash-a",
        model_class="llm_text",
        capabilities=["llm_text"],
        local_agent_use=True,
        runtime={"streaming": False},
        publication={"visibility": "private"},
        pricing={},
        published_at="2026-08-16T00:00:00+00:00",
        sequence=1,
        wallet_signature="sig-legacy",
    )

    assert record.signed_payload()["local_agent_use"] is True


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


def test_published_configuration_accepts_legacy_hash_during_network_upgrade() -> None:
    profile = {
        "marketplace_description": EndpointMarketplaceDescription(
            html="<p>Compatible</p>"
        ).model_dump(mode="json")
    }
    legacy_hash = legacy_configuration_hash_for_publication(
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        runtime={},
        publication={"visibility": "public"},
        pricing={},
    )

    record = PublishedEndpointConfiguration(
        publication_id="pub-legacy-marketplace",
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        node_id="node-1",
        configuration_hash=legacy_hash,
        bundle_id="bundle-a",
        bundle_hash="bundle-hash-a",
        model_class="speech.stt",
        capabilities=["speech.stt"],
        profile=profile,
        runtime={},
        publication={"visibility": "public"},
        pricing={},
        published_at="2026-06-30T00:00:00+00:00",
        sequence=1,
        wallet_signature="sig-1",
    )

    assert record.configuration_hash == legacy_hash
    assert record.profile["marketplace_description"]["html"] == "<p>Compatible</p>"


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
            pricing={},
            validation_requirement={"enabled": False},
            published_at="2026-06-30T00:00:00+00:00",
            sequence=1,
            status="published",
            wallet_signature="sig-1",
        )
