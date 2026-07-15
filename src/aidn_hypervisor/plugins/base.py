from abc import ABC, abstractmethod

from aidn_hypervisor.providers.models import ProviderPluginManifest


class ProviderPlugin(ABC):
    plugin_id: str

    @abstractmethod
    def describe(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def validate_bundle(self, bundle_config) -> None:
        raise NotImplementedError

    @abstractmethod
    def estimate_resources(self, task, bundle_config, runtime_state) -> dict:
        raise NotImplementedError

    @abstractmethod
    def build_launch_spec(self, bundle_config) -> dict:
        raise NotImplementedError

    @abstractmethod
    def health_check(self, runtime_handle) -> bool:
        raise NotImplementedError

    @abstractmethod
    def invoke(self, task, runtime_handle) -> dict:
        raise NotImplementedError

    @abstractmethod
    def stop(self, runtime_handle) -> None:
        raise NotImplementedError

    def bundle_defaults_from_install(self, *, model_id: str, target_path: str) -> dict:
        return {
            "model_id": target_path,
            "launch_mode": "managed_process",
            "device_affinity": "cpu",
        }

    def plugin_manifest(self) -> dict:
        description = self.describe()
        return ProviderPluginManifest(
            plugin_id=description["plugin_id"],
            plugin_version=description.get("plugin_version", "0.1.0"),
            display_name=description.get("display_name", description["plugin_id"]),
            publisher=description.get("publisher", "local"),
            package_digest=description.get(
                "package_digest",
                f"dev:{description['plugin_id']}",
            ),
            provider_families=description.get(
                "provider_families",
                [description.get("provider_type", description["plugin_id"])],
            ),
            plugin_capability_flags=description.get("plugin_capability_flags", []),
            required_permissions=description.get("required_permissions", []),
            supported_aidn_capabilities=description.get(
                "supported_aidn_capabilities",
                [],
            ),
        ).model_dump(mode="json")

    def attach_provider_schema(self) -> dict:
        return {"fields": []}

    def install_provider_schema(self) -> dict:
        return {"fields": []}

    def validate_provider_configuration(self, configuration: dict) -> None:
        return None

    def attach_existing_provider(self, configuration: dict) -> dict:
        self.validate_provider_configuration(configuration)
        return {
            "configuration": dict(configuration),
            "connection_mode": "attached",
            "operational_state": "ready",
        }

    def build_installation_plan(self, configuration: dict) -> dict:
        self.validate_provider_configuration(configuration)
        return {
            "configuration": dict(configuration),
            "steps": [],
        }

    def discover_models(self, provider_instance: dict) -> list[dict]:
        return []

    def create_runtime_binding(
        self,
        *,
        model_deployment: dict,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> dict:
        return {
            "model_deployment_id": model_deployment["model_deployment_id"],
            "provider_instance_id": model_deployment["provider_instance_id"],
            "capability_id": capability_id,
            "capability_version": capability_version,
            "capability_definition_hash": capability_definition_hash,
            "compatibility_bundle": {
                "plugin_id": self.plugin_id,
                "provider_type": self.describe().get("provider_type", self.plugin_id),
                "model_id": model_deployment["provider_model_reference"],
                "launch_mode": "managed_process",
                "device_affinity": "cpu",
            },
        }

    def retry_policy(self) -> dict:
        return {}

    def circuit_breaker_policy(self) -> dict:
        return {}

    def supports_restart_retry(self, task, bundle_config) -> bool:
        return False

    def usage_contract(self) -> dict:
        return {
            "supports_exact": False,
            "supports_estimated": False,
            "default_measurement_source": None,
            "fallback_measurement_source": None,
            "fallback_policy": "none",
            "missing_usage_behavior": "skip",
        }
