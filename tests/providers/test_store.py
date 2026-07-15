import pytest

from aidn_hypervisor.providers.models import (
    ModelDeployment,
    ProviderInstance,
    RuntimeBinding,
)
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore


def _provider_instance(
    provider_instance_id: str,
    display_name: str = "Local Fake",
) -> ProviderInstance:
    return ProviderInstance(
        provider_instance_id=provider_instance_id,
        plugin_id="aidn.provider.fake",
        provider_family="fake",
        display_name=display_name,
        connection_mode="attached",
        configuration={"base_url": f"http://127.0.0.1:{1234 if provider_instance_id == 'pi-1' else 4321}"},
        operational_state="ready",
    )


def test_store_round_trips_provider_instances() -> None:
    store = InMemoryProviderInventoryStore()
    instance = _provider_instance("pi-1")

    store.save_provider_instance(instance)

    assert store.get_provider_instance("pi-1").display_name == "Local Fake"
    assert store.list_provider_instances() == [instance]

    updated_instance = instance.model_copy(
        update={
            "display_name": "Updated Fake",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
        }
    )
    store.save_provider_instance(updated_instance)

    assert store.get_provider_instance("pi-1") == updated_instance
    assert store.list_provider_instances() == [updated_instance]

    store.delete_provider_instance("pi-1")

    assert store.list_provider_instances() == []


def test_store_returns_defensive_provider_instance_copies() -> None:
    store = InMemoryProviderInventoryStore()
    instance = _provider_instance("pi-1")

    store.save_provider_instance(instance)
    instance.plugin_id = "aidn.provider.other"
    instance.configuration["base_url"] = "http://127.0.0.1:9999"

    stored = store.get_provider_instance("pi-1")
    assert stored.plugin_id == "aidn.provider.fake"
    assert stored.configuration["base_url"] == "http://127.0.0.1:1234"

    stored.plugin_id = "aidn.provider.third"
    stored.configuration["base_url"] = "http://127.0.0.1:8888"
    listed = store.list_provider_instances()
    listed[0].plugin_id = "aidn.provider.fourth"
    listed[0].configuration["base_url"] = "http://127.0.0.1:7777"

    reread = store.get_provider_instance("pi-1")
    assert reread.plugin_id == "aidn.provider.fake"
    assert reread.configuration["base_url"] == "http://127.0.0.1:1234"


def test_store_round_trips_model_deployments() -> None:
    store = InMemoryProviderInventoryStore()
    store.save_provider_instance(_provider_instance("pi-1"))
    store.save_provider_instance(_provider_instance("pi-2", display_name="Other Fake"))

    first = ModelDeployment(
        model_deployment_id="md-1",
        provider_instance_id="pi-1",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        operational_state="ready",
    )
    second = ModelDeployment(
        model_deployment_id="md-2",
        provider_instance_id="pi-2",
        provider_model_reference="llama3:8b",
        operator_display_name="Llama 8B",
        operational_state="discovered",
    )

    store.save_model_deployment(first)
    store.save_model_deployment(second)

    updated_first = first.model_copy(
        update={
            "operator_display_name": "Qwen 14B Updated",
            "metadata_sources": {"context_limit": "PROVIDER_REPORTED"},
        }
    )
    store.save_model_deployment(updated_first)

    assert store.list_model_deployments() == [
        updated_first,
        second,
    ]
    assert store.list_model_deployments(provider_instance_id="pi-1") == [
        updated_first,
    ]
    assert store.get_model_deployment("md-1") == updated_first


def test_store_returns_defensive_model_and_binding_copies() -> None:
    store = InMemoryProviderInventoryStore()
    store.save_provider_instance(_provider_instance("pi-1"))
    deployment = ModelDeployment(
        model_deployment_id="md-1",
        provider_instance_id="pi-1",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        metadata_sources={"context_limit": "PROVIDER_REPORTED"},
        operational_state="ready",
    )
    binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )

    store.save_model_deployment(deployment)
    store.save_runtime_binding(binding)
    deployment.provider_instance_id = "pi-2"
    deployment.metadata_sources["context_limit"] = "TAMPERED"
    binding.plugin_id = "aidn.provider.other"

    stored_deployment = store.get_model_deployment("md-1")
    stored_binding = store.get_runtime_binding("rb-1")
    assert stored_deployment.provider_instance_id == "pi-1"
    assert stored_deployment.metadata_sources["context_limit"] == "PROVIDER_REPORTED"
    assert stored_binding.plugin_id == "aidn.provider.fake"

    stored_deployment.provider_instance_id = "pi-3"
    stored_deployment.metadata_sources["context_limit"] = "MUTATED"
    stored_binding.plugin_id = "aidn.provider.third"
    listed_deployment = store.list_model_deployments()[0]
    listed_binding = store.list_runtime_bindings()[0]
    listed_deployment.metadata_sources["context_limit"] = "LIST_MUTATED"
    listed_binding.plugin_id = "aidn.provider.fourth"

    reread_deployment = store.get_model_deployment("md-1")
    reread_binding = store.get_runtime_binding("rb-1")
    assert reread_deployment.provider_instance_id == "pi-1"
    assert reread_deployment.metadata_sources["context_limit"] == "PROVIDER_REPORTED"
    assert reread_binding.plugin_id == "aidn.provider.fake"


def test_store_round_trips_runtime_bindings() -> None:
    store = InMemoryProviderInventoryStore()
    provider_instance = _provider_instance("pi-1")
    deployment = ModelDeployment(
        model_deployment_id="md-1",
        provider_instance_id="pi-1",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        operational_state="ready",
    )
    store.save_provider_instance(provider_instance)
    store.save_model_deployment(deployment)

    binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )

    store.save_runtime_binding(binding)

    updated_binding = binding.model_copy(update={"status": "degraded"})
    store.save_runtime_binding(updated_binding)

    assert store.get_runtime_binding("rb-1") == updated_binding
    assert store.list_runtime_bindings() == [updated_binding]


def test_store_rejects_runtime_binding_provider_change_on_replace() -> None:
    store = InMemoryProviderInventoryStore()
    store.save_provider_instance(_provider_instance("pi-1"))
    store.save_provider_instance(_provider_instance("pi-2", display_name="Other Fake"))
    store.save_model_deployment(
        ModelDeployment(
            model_deployment_id="md-1",
            provider_instance_id="pi-1",
            provider_model_reference="qwen3:14b",
            operator_display_name="Qwen 14B",
            operational_state="ready",
        )
    )
    store.save_model_deployment(
        ModelDeployment(
            model_deployment_id="md-2",
            provider_instance_id="pi-2",
            provider_model_reference="llama3:8b",
            operator_display_name="Llama 8B",
            operational_state="ready",
        )
    )
    binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )

    store.save_runtime_binding(binding)

    with pytest.raises(ValueError, match="immutable"):
        store.save_runtime_binding(
            binding.model_copy(
                update={
                    "provider_instance_id": "pi-2",
                    "model_deployment_id": "md-2",
                }
            )
        )

    assert store.get_runtime_binding("rb-1") == binding


def test_store_rejects_runtime_binding_model_change_on_replace() -> None:
    store = InMemoryProviderInventoryStore()
    store.save_provider_instance(_provider_instance("pi-1"))
    store.save_model_deployment(
        ModelDeployment(
            model_deployment_id="md-1",
            provider_instance_id="pi-1",
            provider_model_reference="qwen3:14b",
            operator_display_name="Qwen 14B",
            operational_state="ready",
        )
    )
    store.save_model_deployment(
        ModelDeployment(
            model_deployment_id="md-2",
            provider_instance_id="pi-1",
            provider_model_reference="llama3:8b",
            operator_display_name="Llama 8B",
            operational_state="ready",
        )
    )
    binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )

    store.save_runtime_binding(binding)

    with pytest.raises(ValueError, match="immutable"):
        store.save_runtime_binding(binding.model_copy(update={"model_deployment_id": "md-2"}))

    assert store.get_runtime_binding("rb-1") == binding


def test_store_rejects_runtime_binding_plugin_change_on_replace() -> None:
    store = InMemoryProviderInventoryStore()
    store.save_provider_instance(_provider_instance("pi-1"))
    store.save_model_deployment(
        ModelDeployment(
            model_deployment_id="md-1",
            provider_instance_id="pi-1",
            provider_model_reference="qwen3:14b",
            operator_display_name="Qwen 14B",
            operational_state="ready",
        )
    )
    binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )

    store.save_runtime_binding(binding)

    with pytest.raises(ValueError, match="immutable"):
        store.save_runtime_binding(binding.model_copy(update={"plugin_id": "aidn.provider.other"}))

    assert store.get_runtime_binding("rb-1") == binding


def test_store_rejects_provider_plugin_change_when_dependents_exist() -> None:
    store = InMemoryProviderInventoryStore()
    provider_instance = _provider_instance("pi-1")
    deployment = ModelDeployment(
        model_deployment_id="md-1",
        provider_instance_id="pi-1",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        operational_state="ready",
    )
    binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )

    store.save_provider_instance(provider_instance)
    store.save_model_deployment(deployment)
    store.save_runtime_binding(binding)

    with pytest.raises(ValueError, match="plugin_id"):
        store.save_provider_instance(
            provider_instance.model_copy(update={"plugin_id": "aidn.provider.other"})
        )

    assert store.get_provider_instance("pi-1") == provider_instance


def test_store_rejects_provider_plugin_change_when_no_dependents_exist() -> None:
    store = InMemoryProviderInventoryStore()
    provider_instance = _provider_instance("pi-1")

    store.save_provider_instance(provider_instance)

    with pytest.raises(ValueError, match="plugin_id"):
        store.save_provider_instance(
            provider_instance.model_copy(update={"plugin_id": "aidn.provider.other"})
        )

    assert store.get_provider_instance("pi-1") == provider_instance


def test_store_rejects_model_deployment_provider_change_when_dependents_exist() -> None:
    store = InMemoryProviderInventoryStore()
    provider_instance = _provider_instance("pi-1")
    other_provider_instance = _provider_instance("pi-2", display_name="Other Fake")
    deployment = ModelDeployment(
        model_deployment_id="md-1",
        provider_instance_id="pi-1",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        operational_state="ready",
    )
    binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )

    store.save_provider_instance(provider_instance)
    store.save_provider_instance(other_provider_instance)
    store.save_model_deployment(deployment)
    store.save_runtime_binding(binding)

    with pytest.raises(ValueError, match="provider_instance_id"):
        store.save_model_deployment(
            deployment.model_copy(update={"provider_instance_id": "pi-2"})
        )

    assert store.get_model_deployment("md-1") == deployment


def test_store_rejects_model_deployment_provider_change_when_no_bindings_exist() -> None:
    store = InMemoryProviderInventoryStore()
    store.save_provider_instance(_provider_instance("pi-1"))
    store.save_provider_instance(_provider_instance("pi-2", display_name="Other Fake"))
    deployment = ModelDeployment(
        model_deployment_id="md-1",
        provider_instance_id="pi-1",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        operational_state="ready",
    )

    store.save_model_deployment(deployment)

    with pytest.raises(ValueError, match="provider_instance_id"):
        store.save_model_deployment(
            deployment.model_copy(update={"provider_instance_id": "pi-2"})
        )

    assert store.get_model_deployment("md-1") == deployment


def test_delete_runtime_binding_removes_only_that_binding() -> None:
    store = InMemoryProviderInventoryStore()
    provider_instance = _provider_instance("pi-1")
    deployment = ModelDeployment(
        model_deployment_id="md-1",
        provider_instance_id="pi-1",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        operational_state="ready",
    )
    first_binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )
    second_binding = RuntimeBinding(
        runtime_binding_id="rb-2",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="cap.secondary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash-2",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-2",
        status="ready",
    )

    store.save_provider_instance(provider_instance)
    store.save_model_deployment(deployment)
    store.save_runtime_binding(first_binding)
    store.save_runtime_binding(second_binding)

    store.delete_runtime_binding("rb-1")

    assert store.get_model_deployment("md-1") == deployment
    assert store.list_runtime_bindings() == [second_binding]


def test_delete_model_deployment_cascades_to_runtime_bindings() -> None:
    store = InMemoryProviderInventoryStore()
    provider_instance = _provider_instance("pi-1")
    first_deployment = ModelDeployment(
        model_deployment_id="md-1",
        provider_instance_id="pi-1",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        operational_state="ready",
    )
    second_deployment = ModelDeployment(
        model_deployment_id="md-2",
        provider_instance_id="pi-1",
        provider_model_reference="llama3:8b",
        operator_display_name="Llama 8B",
        operational_state="ready",
    )
    removed_binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )
    kept_binding = RuntimeBinding(
        runtime_binding_id="rb-2",
        provider_instance_id="pi-1",
        model_deployment_id="md-2",
        capability_id="cap.secondary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash-2",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-2",
        status="ready",
    )

    store.save_provider_instance(provider_instance)
    store.save_model_deployment(first_deployment)
    store.save_model_deployment(second_deployment)
    store.save_runtime_binding(removed_binding)
    store.save_runtime_binding(kept_binding)

    store.delete_model_deployment("md-1")

    assert store.list_model_deployments() == [second_deployment]
    assert store.list_runtime_bindings() == [kept_binding]


def test_delete_provider_instance_cascades_to_deployments_and_bindings() -> None:
    store = InMemoryProviderInventoryStore()
    provider_instance = _provider_instance("pi-1")
    other_provider_instance = _provider_instance("pi-2", display_name="Other Fake")
    removed_deployment = ModelDeployment(
        model_deployment_id="md-1",
        provider_instance_id="pi-1",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        operational_state="ready",
    )
    kept_deployment = ModelDeployment(
        model_deployment_id="md-2",
        provider_instance_id="pi-2",
        provider_model_reference="llama3:8b",
        operator_display_name="Llama 8B",
        operational_state="ready",
    )
    removed_binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )
    kept_binding = RuntimeBinding(
        runtime_binding_id="rb-2",
        provider_instance_id="pi-2",
        model_deployment_id="md-2",
        capability_id="cap.secondary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash-2",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-2",
        status="ready",
    )

    store.save_provider_instance(provider_instance)
    store.save_provider_instance(other_provider_instance)
    store.save_model_deployment(removed_deployment)
    store.save_model_deployment(kept_deployment)
    store.save_runtime_binding(removed_binding)
    store.save_runtime_binding(kept_binding)

    store.delete_provider_instance("pi-1")

    assert store.list_provider_instances() == [other_provider_instance]
    assert store.list_model_deployments() == [kept_deployment]
    assert store.list_runtime_bindings() == [kept_binding]


def test_store_rejects_model_deployment_with_unknown_provider_instance() -> None:
    store = InMemoryProviderInventoryStore()
    deployment = ModelDeployment(
        model_deployment_id="md-1",
        provider_instance_id="pi-missing",
        provider_model_reference="qwen3:14b",
        operator_display_name="Qwen 14B",
        operational_state="ready",
    )

    with pytest.raises(ValueError, match="provider_instance_id"):
        store.save_model_deployment(deployment)


def test_store_rejects_runtime_binding_with_unknown_provider_instance() -> None:
    store = InMemoryProviderInventoryStore()
    store.save_provider_instance(_provider_instance("pi-1"))
    store.save_model_deployment(
        ModelDeployment(
            model_deployment_id="md-1",
            provider_instance_id="pi-1",
            provider_model_reference="qwen3:14b",
            operator_display_name="Qwen 14B",
            operational_state="ready",
        )
    )

    binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-missing",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )

    with pytest.raises(ValueError, match="provider_instance_id"):
        store.save_runtime_binding(binding)


def test_store_rejects_runtime_binding_with_unknown_model_deployment() -> None:
    store = InMemoryProviderInventoryStore()
    store.save_provider_instance(_provider_instance("pi-1"))

    binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-missing",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )

    with pytest.raises(ValueError, match="model_deployment_id"):
        store.save_runtime_binding(binding)


def test_store_rejects_runtime_binding_when_deployment_belongs_to_different_provider() -> None:
    store = InMemoryProviderInventoryStore()
    store.save_provider_instance(_provider_instance("pi-1"))
    store.save_provider_instance(_provider_instance("pi-2", display_name="Other Fake"))
    store.save_model_deployment(
        ModelDeployment(
            model_deployment_id="md-1",
            provider_instance_id="pi-1",
            provider_model_reference="qwen3:14b",
            operator_display_name="Qwen 14B",
            operational_state="ready",
        )
    )

    binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-2",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.fake",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )

    with pytest.raises(ValueError, match="must match"):
        store.save_runtime_binding(binding)


def test_store_rejects_runtime_binding_with_mismatched_provider_plugin() -> None:
    store = InMemoryProviderInventoryStore()
    store.save_provider_instance(_provider_instance("pi-1"))
    store.save_model_deployment(
        ModelDeployment(
            model_deployment_id="md-1",
            provider_instance_id="pi-1",
            provider_model_reference="qwen3:14b",
            operator_display_name="Qwen 14B",
            operational_state="ready",
        )
    )

    binding = RuntimeBinding(
        runtime_binding_id="rb-1",
        provider_instance_id="pi-1",
        model_deployment_id="md-1",
        capability_id="cap.primary",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
        plugin_id="aidn.provider.other",
        compatibility_bundle_id="bundle-rb-1",
        status="ready",
    )

    with pytest.raises(ValueError, match="plugin_id"):
        store.save_runtime_binding(binding)
