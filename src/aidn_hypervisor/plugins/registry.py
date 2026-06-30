from aidn_hypervisor.plugins.base import ProviderPlugin


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, ProviderPlugin] = {}

    def register(self, plugin: ProviderPlugin) -> None:
        self._plugins[plugin.plugin_id] = plugin

    def get(self, plugin_id: str) -> ProviderPlugin:
        return self._plugins[plugin_id]

    def list(self) -> list[ProviderPlugin]:
        return list(self._plugins.values())
