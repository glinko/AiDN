from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry


def test_registry_returns_registered_plugin() -> None:
    registry = PluginRegistry()
    plugin = FakeManagedPlugin()

    registry.register(plugin)

    assert registry.get("fake-managed") is plugin
