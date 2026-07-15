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


class _ExplicitEmptyCapabilitiesPlugin(_DescribeOnlyPlugin):
    plugin_id = "explicit-empty"

    def describe(self) -> dict:
        return {
            "plugin_id": self.plugin_id,
            "provider_type": "explicit-empty-provider",
            "supported_aidn_capabilities": [],
            "workload_types": ["llm.chat"],
        }


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


def test_registry_manifest_preserves_explicit_empty_supported_capabilities() -> None:
    registry = PluginRegistry()
    registry.register(_ExplicitEmptyCapabilitiesPlugin())

    manifests = registry.list_manifests()

    assert manifests[0]["plugin_id"] == "explicit-empty"
    assert manifests[0]["supported_aidn_capabilities"] == []


def test_registry_manifest_includes_install_schema_permissions_and_recipes() -> None:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())

    manifest = registry.list_manifests()[0]

    assert manifest["trust_status"] == "CONFORMANCE_TESTED"
    assert manifest["required_permissions"][0]["permission_id"] == "network.private"
    assert manifest["attach_ui_schema"]["schema_id"] == "fake.attach.v1"
    assert manifest["install_ui_schema"]["schema_id"] == "fake.install.v1"
    assert manifest["secret_requirements"] == []
    assert manifest["installation_recipes"][0]["recipe_id"] == "fake-managed-local"
    assert "CAN_INSTALL_PROVIDER" in manifest["plugin_capability_flags"]


def test_fake_plugin_builds_declarative_installation_plan() -> None:
    plugin = FakeManagedPlugin()

    plan = plugin.build_installation_plan(
        {
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        }
    )

    assert plan["plugin_id"] == "fake-managed"
    assert plan["summary"] == "Attach or prepare Fake Managed Provider"
    assert plan["unsupported_actions"] == []
    assert plan["health_checks"][0]["type"] == "http"
