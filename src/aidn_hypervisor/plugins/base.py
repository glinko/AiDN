from abc import ABC, abstractmethod

from aidn_hypervisor.providers.models import InstallationPlan, ProviderPluginManifest
from aidn_hypervisor.providers.package_verification import (
    compute_manifest_hash,
    package_signature_payload,
)

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    _ED25519_AVAILABLE = True
except Exception:  # pragma: no cover - optional crypto support
    Ed25519PrivateKey = None
    _ED25519_AVAILABLE = False


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
        if "supported_aidn_capabilities" in description:
            supported_aidn_capabilities = description["supported_aidn_capabilities"]
        else:
            supported_aidn_capabilities = description.get("workload_types", [])
        signing_private_key = description.get("developer_signing_private_key") or getattr(
            self,
            "developer_signing_private_key",
            None,
        )
        publisher_public_key = description.get("publisher_public_key")
        if signing_private_key and not publisher_public_key:
            if not _ED25519_AVAILABLE:
                raise RuntimeError(
                    "developer_signing_private_key requires Ed25519 support"
                )
            private_key = Ed25519PrivateKey.from_private_bytes(
                bytes.fromhex(signing_private_key)
            )
            publisher_public_key = (
                f"ed25519:{private_key.public_key().public_bytes_raw().hex()}"
            )
        manifest = ProviderPluginManifest(
            plugin_id=description["plugin_id"],
            plugin_version=description.get("plugin_version", "0.1.0"),
            display_name=description.get("display_name", description["plugin_id"]),
            publisher=description.get("publisher", "local"),
            package_digest=description.get(
                "package_digest",
                f"dev:{description['plugin_id']}",
            ),
            publisher_public_key=publisher_public_key,
            publisher_signature=description.get("publisher_signature"),
            manifest_hash=description.get("manifest_hash"),
            provider_families=description.get(
                "provider_families",
                [description.get("provider_type", description["plugin_id"])],
            ),
            plugin_capability_flags=description.get("plugin_capability_flags", []),
            required_permissions=description.get("required_permissions", []),
            supported_aidn_capabilities=supported_aidn_capabilities,
            trust_status=description.get("trust_status", "UNREVIEWED"),
            sandbox_policy=description.get("sandbox_policy", {}),
            source_repository=description.get("source_repository"),
            license=description.get("license"),
            supported_platforms=description.get("supported_platforms", []),
            supported_architectures=description.get("supported_architectures", []),
            supported_accelerators=description.get("supported_accelerators", []),
            attach_ui_schema=description.get("attach_ui_schema")
            or self.attach_provider_schema(),
            install_ui_schema=description.get("install_ui_schema")
            or self.install_provider_schema(),
            model_ui_schema=description.get("model_ui_schema"),
            endpoint_defaults_schema=description.get("endpoint_defaults_schema"),
            diagnostics_schema=description.get("diagnostics_schema"),
            secret_requirements=description.get("secret_requirements", []),
            installation_recipes=description.get("installation_recipes", []),
        )
        if signing_private_key:
            private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(signing_private_key))
            manifest_hash = compute_manifest_hash(manifest)
            manifest = manifest.model_copy(
                update={
                    "manifest_hash": manifest_hash,
                    "publisher_signature": (
                        "ed25519:"
                        + private_key.sign(
                            package_signature_payload(
                                manifest,
                                manifest_hash=manifest_hash,
                            )
                        ).hex()
                    ),
                }
            )
        return manifest.model_dump(mode="json")

    def attach_provider_schema(self) -> dict:
        return {"schema_id": f"{self.plugin_id}.attach.v1", "fields": []}

    def install_provider_schema(self) -> dict:
        return {"schema_id": f"{self.plugin_id}.install.v1", "fields": []}

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
        return InstallationPlan(
            plan_id=f"plan-{self.plugin_id}",
            plugin_id=self.plugin_id,
            plan_version="1.0.0",
            summary=f"Prepare {self.plugin_id}",
            required_permissions=self.plugin_manifest().get("required_permissions", []),
        ).model_dump(mode="json")

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
