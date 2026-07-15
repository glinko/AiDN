from aidn_hypervisor.providers.models import (
    ModelDeployment,
    ProviderInstance,
    RuntimeBinding,
)
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore


def test_store_round_trips_provider_instances() -> None:
    store = InMemoryProviderInventoryStore()
    instance = ProviderInstance(
        provider_instance_id="pi-1",
        plugin_id="aidn.provider.fake",
        provider_family="fake",
        display_name="Local Fake",
        connection_mode="attached",
        configuration={"base_url": "http://127.0.0.1:1234"},
        operational_state="ready",
    )

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


def test_store_round_trips_model_deployments() -> None:
    store = InMemoryProviderInventoryStore()
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


def test_store_round_trips_runtime_bindings() -> None:
    store = InMemoryProviderInventoryStore()
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


def test_delete_provider_instance_cascades_to_deployments_and_bindings() -> None:
    store = InMemoryProviderInventoryStore()
    provider_instance = ProviderInstance(
        provider_instance_id="pi-1",
        plugin_id="aidn.provider.fake",
        provider_family="fake",
        display_name="Local Fake",
        connection_mode="attached",
        configuration={"base_url": "http://127.0.0.1:1234"},
        operational_state="ready",
    )
    other_provider_instance = ProviderInstance(
        provider_instance_id="pi-2",
        plugin_id="aidn.provider.fake",
        provider_family="fake",
        display_name="Other Fake",
        connection_mode="attached",
        configuration={"base_url": "http://127.0.0.1:4321"},
        operational_state="ready",
    )
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
