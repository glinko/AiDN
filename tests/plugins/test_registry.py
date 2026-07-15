from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry


def test_registry_returns_registered_plugin() -> None:
    registry = PluginRegistry()
    plugin = FakeManagedPlugin()

    registry.register(plugin)

    assert registry.get("fake-managed") is plugin


def test_registry_lists_plugin_directory_manifest() -> None:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())

    manifests = registry.list_manifests()

    assert manifests == [FakeManagedPlugin().plugin_manifest()]
    assert manifests[0]["plugin_id"] == "fake-managed"
    assert manifests[0]["display_name"] == "Fake Managed Provider"
    assert manifests[0]["provider_families"] == ["fake"]
    assert "CAN_ATTACH_EXISTING" in manifests[0]["plugin_capability_flags"]
    assert "llm.chat" in manifests[0]["supported_aidn_capabilities"]
