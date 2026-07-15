from aidn_hypervisor.providers.models import ProviderInstance
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

    store.delete_provider_instance("pi-1")

    assert store.list_provider_instances() == []


def test_store_round_trips_model_deployments() -> None:
    store = InMemoryProviderInventoryStore()
    first = {
        "model_deployment_id": "md-1",
        "provider_instance_id": "pi-1",
        "provider_model_reference": "qwen3:14b",
        "operator_display_name": "Qwen 14B",
        "operational_state": "ready",
    }
    second = {
        "model_deployment_id": "md-2",
        "provider_instance_id": "pi-2",
        "provider_model_reference": "llama3:8b",
        "operator_display_name": "Llama 8B",
        "operational_state": "discovered",
    }

    from aidn_hypervisor.providers.models import ModelDeployment

    store.save_model_deployment(ModelDeployment(**first))
    store.save_model_deployment(ModelDeployment(**second))

    assert store.list_model_deployments() == [
        ModelDeployment(**first),
        ModelDeployment(**second),
    ]
    assert store.list_model_deployments(provider_instance_id="pi-1") == [
        ModelDeployment(**first),
    ]


def test_store_round_trips_runtime_bindings() -> None:
    store = InMemoryProviderInventoryStore()
    from aidn_hypervisor.providers.models import RuntimeBinding

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

    assert store.get_runtime_binding("rb-1") == binding
    assert store.list_runtime_bindings() == [binding]
