from uuid import uuid4

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile
from aidn_hypervisor.providers.models import (
    ModelDeployment,
    ProviderInstance,
    RuntimeBinding,
)
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore


class ProviderInventoryService:
    def __init__(self, *, plugins, store: InMemoryProviderInventoryStore) -> None:
        self.plugins = plugins
        self.store = store
        self._runtime_binding_projections: dict[str, dict] = {}

    def list_plugin_manifests(self) -> list[dict]:
        if hasattr(self.plugins, "list_manifests"):
            return list(self.plugins.list_manifests())
        return [plugin.plugin_manifest() for plugin in self._list_plugins()]

    def attach_provider_instance(
        self,
        *,
        plugin_id: str,
        display_name: str,
        configuration: dict,
    ) -> ProviderInstance:
        plugin = self._get_plugin(plugin_id)
        normalized_configuration = dict(configuration)
        plugin.validate_provider_configuration(normalized_configuration)
        attached = plugin.attach_existing_provider(normalized_configuration)
        manifest = plugin.plugin_manifest()
        instance = ProviderInstance(
            provider_instance_id=f"pi-{uuid4().hex[:12]}",
            plugin_id=plugin_id,
            provider_family=self._provider_family(manifest, plugin_id),
            display_name=str(attached.get("display_name") or display_name),
            connection_mode=attached.get("connection_mode", "attached"),
            configuration=dict(attached.get("configuration") or normalized_configuration),
            operational_state=attached.get("operational_state", "ready"),
        )
        self.store.save_provider_instance(instance)
        return instance

    def discover_models(self, provider_instance_id: str) -> list[ModelDeployment]:
        instance = self.store.get_provider_instance(provider_instance_id)
        plugin = self._get_plugin(instance.plugin_id)
        discovered = plugin.discover_models(instance.model_dump(mode="json"))
        deployments: list[ModelDeployment] = []
        for item in discovered:
            deployment = ModelDeployment(
                model_deployment_id=item.get("model_deployment_id")
                or f"md-{provider_instance_id}-{uuid4().hex[:8]}",
                provider_instance_id=provider_instance_id,
                provider_model_reference=item["provider_model_reference"],
                operator_display_name=item.get("operator_display_name")
                or item["provider_model_reference"],
                declared_model_name=item.get("declared_model_name"),
                metadata_sources=dict(item.get("metadata_sources") or {}),
                capability_bindings=list(item.get("capability_bindings") or []),
                operational_state=item.get("operational_state", "ready"),
            )
            self.store.save_model_deployment(deployment)
            deployments.append(deployment)
        return deployments

    def create_runtime_binding(
        self,
        *,
        model_deployment_id: str,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> RuntimeBinding:
        deployment = self.store.get_model_deployment(model_deployment_id)
        instance = self.store.get_provider_instance(deployment.provider_instance_id)
        plugin = self._get_plugin(instance.plugin_id)
        projection = plugin.create_runtime_binding(
            model_deployment=deployment.model_dump(mode="json"),
            capability_id=capability_id,
            capability_version=capability_version,
            capability_definition_hash=capability_definition_hash,
        )
        runtime_binding_id = str(projection.get("runtime_binding_id") or f"rtb-{uuid4().hex[:12]}")
        binding = RuntimeBinding(
            runtime_binding_id=runtime_binding_id,
            provider_instance_id=instance.provider_instance_id,
            model_deployment_id=deployment.model_deployment_id,
            capability_id=projection.get("capability_id", capability_id),
            capability_version=projection.get("capability_version", capability_version),
            capability_definition_hash=projection.get(
                "capability_definition_hash",
                capability_definition_hash,
            ),
            plugin_id=instance.plugin_id,
            compatibility_bundle_id=str(
                projection.get("compatibility_bundle_id")
                or f"bundle-{runtime_binding_id}"
            ),
            status=projection.get("status", "ready"),
        )
        self.store.save_runtime_binding(binding)
        self._runtime_binding_projections[binding.runtime_binding_id] = dict(
            projection.get("compatibility_bundle") or {}
        )
        return binding

    def bundle_config_for_runtime_binding(self, runtime_binding_id: str) -> BundleConfig:
        binding = self.store.get_runtime_binding(runtime_binding_id)
        deployment = self.store.get_model_deployment(binding.model_deployment_id)
        instance = self.store.get_provider_instance(binding.provider_instance_id)
        projection = dict(
            self._runtime_binding_projections.get(runtime_binding_id)
            or self._rebuild_runtime_binding_projection(binding, deployment)
        )
        endpoint = projection.get("endpoint")
        if endpoint is None:
            endpoint = instance.configuration.get("endpoint") or instance.configuration.get(
                "base_url"
            )
        return BundleConfig(
            bundle_id=binding.compatibility_bundle_id,
            plugin_id=projection.get("plugin_id", instance.plugin_id),
            provider_type=projection.get("provider_type", instance.provider_family),
            workload_type=binding.capability_id,
            model_id=projection.get("model_id", deployment.provider_model_reference),
            launch_mode=projection.get("launch_mode", "managed_process"),
            endpoint=endpoint,
            device_affinity=projection.get("device_affinity", "cpu"),
            resource_profile=ResourceProfile(),
            warm_policy="auto",
            priority_class=50,
            max_parallel_requests=1,
            enabled=True,
        )

    def _rebuild_runtime_binding_projection(
        self,
        binding: RuntimeBinding,
        deployment: ModelDeployment,
    ) -> dict:
        plugin = self._get_plugin(binding.plugin_id)
        projection = plugin.create_runtime_binding(
            model_deployment=deployment.model_dump(mode="json"),
            capability_id=binding.capability_id,
            capability_version=binding.capability_version,
            capability_definition_hash=binding.capability_definition_hash,
        )
        return dict(projection.get("compatibility_bundle") or {})

    def _get_plugin(self, plugin_id: str):
        if hasattr(self.plugins, "get"):
            return self.plugins.get(plugin_id)
        for plugin in self._list_plugins():
            if plugin.plugin_id == plugin_id:
                return plugin
        raise KeyError(plugin_id)

    def _list_plugins(self) -> list:
        if hasattr(self.plugins, "list"):
            return list(self.plugins.list())
        return list(self.plugins or [])

    def _provider_family(self, manifest: dict, plugin_id: str) -> str:
        families = manifest.get("provider_families") or []
        if families:
            return str(families[0])
        return plugin_id
