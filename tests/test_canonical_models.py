from aidn_hypervisor.canonical_models import (
    CanonicalAdvertisementRecord,
    CanonicalCapabilityRuntimeRecord,
    CanonicalComputeCompatibilityRecord,
    CanonicalProtocolServiceRecord,
)


def test_protocol_service_record_derives_enabled_compute_role() -> None:
    record = CanonicalProtocolServiceRecord(
        service_id="compute",
        kind="compute",
        enabled=True,
        derived_roles=["compute_provider"],
        responsibilities=["endpoint_hosting", "session_execution"],
    )

    assert record.kind == "compute"
    assert record.enabled is True
    assert record.derived_roles == ["compute_provider"]


def test_capability_runtime_record_requires_capability_identity() -> None:
    record = CanonicalCapabilityRuntimeRecord(
        runtime_id="runtime-1",
        capability_id="speech.stt",
        runtime_version="0.1.0",
        protocol_version="runtime.v1",
        location_kind="local_process",
        health_status="healthy",
        supported_features=["streaming"],
    )

    assert record.capability_id == "speech.stt"
    assert record.location_kind == "local_process"


def test_compute_compatibility_record_preserves_legacy_mapping() -> None:
    record = CanonicalComputeCompatibilityRecord(
        compatibility_id="bundle:whisper-a",
        legacy_bundle_id="whisper-a",
        legacy_plugin_id="fake-managed",
        legacy_provider_type="fake",
        canonical_capability_id="speech.stt",
        canonical_runtime_id="runtime-whisper-a",
    )

    assert record.legacy_bundle_id == "whisper-a"
    assert record.canonical_capability_id == "speech.stt"


def test_endpoint_advertisement_record_captures_capability_surface() -> None:
    record = CanonicalAdvertisementRecord(
        advertisement_id="adv-endpoint-1",
        resource_type="endpoint",
        owner_wallet="wallet-1",
        hypervisor_id="node-local",
        capability_id="llm.chat",
        visibility="private",
        signature_scope="configuration_publication",
    )

    assert record.resource_type == "endpoint"
    assert record.capability_id == "llm.chat"
