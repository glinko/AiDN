from aidn_hypervisor.plugins.base import ProviderPlugin
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry


class _DescribeOnlyPlugin(ProviderPlugin):
    plugin_id = "describe-only"

    def describe(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "provider_type": "describe-only-provider",
            "workload_types": ["llm.chat", "speech.stt"],
        }

    def validate_bundle(self, bundle_config) -> None:
        return None

    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        return {}

    def build_launch_spec(self, bundle_config) -> dict:
        return {}

    def health_check(self, runtime_handle) -> bool:
        return True

    def invoke(self, task, runtime_handle) -> dict:
        return {"ok": True}

    def stop(self, runtime_handle) -> None:
        return None


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


def test_registry_manifest_falls_back_to_describe_workload_types() -> None:
    registry = PluginRegistry()
    registry.register(_DescribeOnlyPlugin())

    manifests = registry.list_manifests()

    assert manifests[0]["plugin_id"] == "describe-only"
    assert manifests[0]["provider_families"] == ["describe-only-provider"]
    assert manifests[0]["supported_aidn_capabilities"] == [
        "llm.chat",
        "speech.stt",
    ]
