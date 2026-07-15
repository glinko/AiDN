from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore


def test_fake_plugin_exposes_attach_schema_and_discovers_models() -> None:
    plugin = FakeManagedPlugin()

    attach_schema = plugin.attach_provider_schema()
    models = plugin.discover_models(
        {
            "provider_instance_id": "pi-fake",
            "display_name": "Local Fake",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
        }
    )

    assert attach_schema["fields"] == [
        {"id": "display_name", "type": "text", "required": True},
        {"id": "base_url", "type": "text", "required": True},
    ]
    assert models[0]["provider_model_reference"] == "fake-model"
    assert models[0]["capability_bindings"] == ["llm.chat"]
    assert models[0]["operational_state"] == "ready"


def test_fake_plugin_discovery_uses_provider_specific_model_deployment_ids() -> None:
    plugin = FakeManagedPlugin()

    first_models = plugin.discover_models(
        {
            "provider_instance_id": "pi-fake-a",
            "display_name": "Local Fake A",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
        }
    )
    second_models = plugin.discover_models(
        {
            "provider_instance_id": "pi-fake-b",
            "display_name": "Local Fake B",
            "configuration": {"base_url": "http://127.0.0.1:9998"},
        }
    )

    assert first_models[0]["model_deployment_id"] != second_models[0]["model_deployment_id"]
    assert first_models[0]["provider_instance_id"] == "pi-fake-a"
    assert second_models[0]["provider_instance_id"] == "pi-fake-b"


def test_base_plugin_attach_existing_provider_passes_configuration_through() -> None:
    plugin = FakeManagedPlugin()

    attached = plugin.attach_existing_provider({"base_url": "http://127.0.0.1:9999"})

    assert attached == {
        "configuration": {"base_url": "http://127.0.0.1:9999"},
        "connection_mode": "attached",
        "operational_state": "ready",
    }


def test_fake_plugin_creates_runtime_binding_projection() -> None:
    plugin = FakeManagedPlugin()

    binding = plugin.create_runtime_binding(
        model_deployment={
            "model_deployment_id": "md-fake",
            "provider_instance_id": "pi-fake",
            "provider_model_reference": "fake-model",
        },
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    assert binding["model_deployment_id"] == "md-fake"
    assert binding["capability_id"] == "llm.chat"
    assert binding["compatibility_bundle"]["plugin_id"] == "fake-managed"
    assert binding["compatibility_bundle"]["provider_type"] == "fake"
    assert binding["compatibility_bundle"]["model_id"] == "fake-model"


def test_provider_inventory_service_attaches_discovers_and_projects_runtime_binding() -> None:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    manifests = service.list_plugin_manifests()
    instance = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    models = service.discover_models(instance.provider_instance_id)
    binding = service.create_runtime_binding(
        model_deployment_id=models[0].model_deployment_id,
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )
    bundle = service.bundle_config_for_runtime_binding(binding.runtime_binding_id)

    assert manifests[0]["plugin_id"] == "fake-managed"
    assert instance.connection_mode == "attached"
    assert instance.configuration["base_url"] == "http://127.0.0.1:9999"
    assert service.store.get_provider_instance(instance.provider_instance_id).display_name == "Local Fake"
    assert models[0].provider_instance_id == instance.provider_instance_id
    assert service.store.get_model_deployment(models[0].model_deployment_id).provider_model_reference == "fake-model"
    assert binding.provider_instance_id == instance.provider_instance_id
    assert service.store.get_runtime_binding(binding.runtime_binding_id).compatibility_bundle_id == binding.compatibility_bundle_id
    assert bundle.bundle_id == binding.compatibility_bundle_id
    assert bundle.plugin_id == "fake-managed"
    assert bundle.provider_type == "fake"
    assert bundle.workload_type == "llm.chat"
    assert bundle.model_id == "fake-model"
    assert bundle.endpoint == "http://127.0.0.1:9999"


def test_provider_inventory_service_validates_configuration_before_attach() -> None:
    class ValidationTrackingPlugin(FakeManagedPlugin):
        plugin_id = "fake-validation-tracking"

        def __init__(self) -> None:
            self.validated_configurations: list[dict] = []

        def validate_provider_configuration(self, configuration: dict) -> None:
            self.validated_configurations.append(dict(configuration))

        def attach_existing_provider(self, configuration: dict) -> dict:
            if not self.validated_configurations:
                raise ValueError("validation not run")
            return {
                "configuration": dict(configuration),
                "connection_mode": "attached",
                "operational_state": "ready",
            }

    plugin = ValidationTrackingPlugin()
    registry = PluginRegistry()
    registry.register(plugin)
    service = ProviderInventoryService(
        plugins=registry,
        store=InMemoryProviderInventoryStore(),
    )

    instance = service.attach_provider_instance(
        plugin_id="fake-validation-tracking",
        display_name="Tracked Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )

    assert instance.plugin_id == "fake-validation-tracking"
    assert plugin.validated_configurations == [{"base_url": "http://127.0.0.1:9999"}]
