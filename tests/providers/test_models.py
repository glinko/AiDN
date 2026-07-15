from pydantic import ValidationError

from aidn_hypervisor.providers.models import (
    ModelDeployment,
    ProviderInstance,
    ProviderPluginManifest,
    RuntimeBinding,
)


def test_provider_plugin_manifest_stores_digest_and_capability_flags() -> None:
    manifest = ProviderPluginManifest(
        plugin_id="aidn.provider.fake",
        plugin_version="0.1.0",
        display_name="Fake Provider",
        publisher="AiDN Test",
        package_digest="sha256:abc123",
        provider_families=["fake"],
        plugin_capability_flags=["CAN_ATTACH_EXISTING", "CAN_DISCOVER_MODELS"],
        required_permissions=[],
        supported_aidn_capabilities=["llm.chat"],
    )

    assert manifest.plugin_id == "aidn.provider.fake"
    assert manifest.plugin_capability_flags == [
        "CAN_ATTACH_EXISTING",
        "CAN_DISCOVER_MODELS",
    ]


def test_provider_plugin_manifest_rejects_blank_package_digest() -> None:
    try:
        ProviderPluginManifest(
            plugin_id="aidn.provider.fake",
            plugin_version="0.1.0",
            display_name="Fake Provider",
            publisher="AiDN Test",
            package_digest="   ",
            provider_families=["fake"],
            plugin_capability_flags=["CAN_ATTACH_EXISTING"],
            required_permissions=[],
            supported_aidn_capabilities=["llm.chat"],
        )
    except ValidationError as exc:
        assert "package_digest" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_runtime_binding_requires_primary_capability() -> None:
    for field_name, override in {
        "capability_id": "",
        "capability_version": "   ",
        "capability_definition_hash": "",
    }.items():
        payload = {
            "runtime_binding_id": "rb-1",
            "provider_instance_id": "pi-1",
            "model_deployment_id": "md-1",
            "capability_id": "cap.primary",
            "capability_version": "1.0.0",
            "capability_definition_hash": "cap-hash",
            "plugin_id": "aidn.provider.fake",
            "compatibility_bundle_id": "bundle-rb-1",
            "status": "ready",
        }
        payload[field_name] = override
        try:
            RuntimeBinding(**payload)
        except ValidationError as exc:
            assert field_name in str(exc)
        else:
            raise AssertionError("expected ValidationError")


def test_model_deployment_tracks_metadata_sources() -> None:
    deployment = ModelDeployment(
        model_deployment_id="md-qwen",
        provider_instance_id="pi-ollama",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        declared_model_name="Qwen3 14B",
        metadata_sources={
            "declared_model_name": "OPERATOR_DECLARED",
            "context_limit": "PROVIDER_REPORTED",
        },
        capability_bindings=["llm.chat"],
        operational_state="ready",
    )

    assert deployment.metadata_sources["context_limit"] == "PROVIDER_REPORTED"
