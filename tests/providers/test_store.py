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
    assert len(store.list_provider_instances()) == 1
