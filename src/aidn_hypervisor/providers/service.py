import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile
from aidn_hypervisor.providers.executor import (
    ProviderInstallationExecutor,
    RecordedProviderInstallationExecutor,
)
from aidn_hypervisor.providers.models import (
    InstallationPlan,
    ModelDeployment,
    ProviderInstallationApproval,
    ProviderInstallationJob,
    ProviderPluginManifest,
    ProviderInstance,
    RuntimeBinding,
)
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore


def _canonical_hash(value: dict) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ProviderInventoryService:
    def __init__(
        self,
        *,
        plugins,
        store: InMemoryProviderInventoryStore,
        installation_executor: ProviderInstallationExecutor | None = None,
    ) -> None:
        self.plugins = plugins
        self.store = store
        self.installation_executor = installation_executor or RecordedProviderInstallationExecutor()
        self._runtime_binding_projections: dict[str, dict] = {}

    def list_plugin_manifests(self) -> list[dict]:
        if hasattr(self.plugins, "list_manifests"):
            return list(self.plugins.list_manifests())
        return [plugin.plugin_manifest() for plugin in self._list_plugins()]

    def list_provider_instances(self) -> list[ProviderInstance]:
        return self.store.list_provider_instances()

    def list_model_deployments(self) -> list[ModelDeployment]:
        return self.store.list_model_deployments()

    def list_runtime_bindings(self) -> list[RuntimeBinding]:
        return self.store.list_runtime_bindings()

    def build_installation_plan(self, *, plugin_id: str, configuration: dict) -> dict:
        plugin = self._get_plugin(plugin_id)
        manifest = plugin.plugin_manifest()
        if "CAN_INSTALL_PROVIDER" not in manifest.get("plugin_capability_flags", []):
            raise ValueError(f"Plugin does not support managed installation: {plugin_id}")
        plan = plugin.build_installation_plan(deepcopy(configuration))
        return InstallationPlan.model_validate(plan).model_dump(mode="json")

    def approve_installation_plan(
        self,
        plugin_id: str,
        configuration: dict,
        operator_note: str | None = None,
    ) -> ProviderInstallationApproval:
        plugin = self._get_plugin(plugin_id)
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        approved_configuration = deepcopy(configuration)
        plan = self.build_installation_plan(
            plugin_id=plugin_id,
            configuration=approved_configuration,
        )
        approval = ProviderInstallationApproval(
            approval_id=f"pia-{uuid4().hex[:12]}",
            plugin_id=plugin_id,
            plan_id=plan["plan_id"],
            plan_hash=_canonical_hash(deepcopy(plan)),
            configuration_hash=_canonical_hash(deepcopy(approved_configuration)),
            configuration=deepcopy(approved_configuration),
            approved_permissions=[
                permission["permission_id"]
                for permission in plan.get("required_permissions", [])
            ],
            acknowledged_secret_requirements=[
                requirement.model_dump(mode="json")
                for requirement in manifest.secret_requirements
            ],
            operator_note=operator_note,
            status="APPROVED",
            created_at=_now_iso(),
        )
        self.store.save_installation_approval(approval)
        return approval

    def list_installation_approvals(self) -> list[ProviderInstallationApproval]:
        return self.store.list_installation_approvals()

    def apply_installation_approval(self, approval_id: str) -> ProviderInstallationJob:
        approval = self.store.get_installation_approval(approval_id)
        if approval.status != "APPROVED":
            raise ValueError("installation approval is not active")
        approved_configuration = deepcopy(approval.configuration)
        if _canonical_hash(deepcopy(approved_configuration)) != approval.configuration_hash:
            raise ValueError("installation configuration hash mismatch")

        plugin = self._get_plugin(approval.plugin_id)
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        plan_dict = self.build_installation_plan(
            plugin_id=approval.plugin_id,
            configuration=approved_configuration,
        )
        plan = InstallationPlan.model_validate(plan_dict)
        if _canonical_hash(deepcopy(plan_dict)) != approval.plan_hash:
            raise ValueError("installation plan hash mismatch")

        job = ProviderInstallationJob(
            job_id=f"pij-{uuid4().hex[:12]}",
            approval_id=approval.approval_id,
            plugin_id=approval.plugin_id,
            plan_id=approval.plan_id,
            plan_hash=approval.plan_hash,
            configuration_hash=approval.configuration_hash,
            status="QUEUED",
            executor_id=self.installation_executor.executor_id,
            created_at=_now_iso(),
        )
        self.store.save_installation_job(job)
        job = job.model_copy(update={"status": "RUNNING", "started_at": _now_iso()})
        self.store.save_installation_job(job)

        try:
            provider_instance_id = f"pi-{uuid4().hex[:12]}"
            approval_for_executor = approval.model_copy(deep=True)
            result = self.installation_executor.apply(
                approval=approval_for_executor,
                plan=plan,
                configuration=deepcopy(approved_configuration),
                manifest=manifest.model_dump(mode="json"),
                provider_instance_id=provider_instance_id,
            )
            provider_instance = ProviderInstance.model_validate(result.provider_instance)
            self._validate_applied_provider_instance(
                provider_instance=provider_instance,
                provider_instance_id=provider_instance_id,
                approval=approval,
                approved_configuration=approved_configuration,
            )
            self.store.save_provider_instance(provider_instance)
            job = job.model_copy(
                update={
                    "status": "SUCCEEDED",
                    "step_results": result.step_results,
                    "provider_instance_id": provider_instance.provider_instance_id,
                    "completed_at": _now_iso(),
                }
            )
        except Exception as exc:
            job = job.model_copy(
                update={
                    "status": "FAILED",
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                    "completed_at": _now_iso(),
                }
            )
        self.store.save_installation_job(job)
        return job

    def list_installation_jobs(self) -> list[ProviderInstallationJob]:
        return self.store.list_installation_jobs()

    def attach_provider_instance(
        self,
        *,
        plugin_id: str,
        display_name: str,
        configuration: dict,
    ) -> ProviderInstance:
        plugin = self._get_plugin(plugin_id)
        normalized_configuration = deepcopy(configuration)
        plugin.validate_provider_configuration(deepcopy(normalized_configuration))
        attached = plugin.attach_existing_provider(deepcopy(normalized_configuration))
        manifest = plugin.plugin_manifest()
        instance = ProviderInstance(
            provider_instance_id=f"pi-{uuid4().hex[:12]}",
            plugin_id=plugin_id,
            provider_family=self._provider_family(manifest, plugin_id),
            display_name=str(attached.get("display_name") or display_name),
            connection_mode=attached.get("connection_mode", "attached"),
            configuration=deepcopy(attached.get("configuration") or normalized_configuration),
            operational_state=attached.get("operational_state", "ready"),
        )
        self.store.save_provider_instance(instance)
        return instance

    def _validate_applied_provider_instance(
        self,
        *,
        provider_instance: ProviderInstance,
        provider_instance_id: str,
        approval: ProviderInstallationApproval,
        approved_configuration: dict,
    ) -> None:
        expected = {
            "provider_instance_id": provider_instance_id,
            "plugin_id": approval.plugin_id,
            "connection_mode": "managed",
            "operational_state": "created",
            "configuration": approved_configuration,
        }
        actual = {
            "provider_instance_id": provider_instance.provider_instance_id,
            "plugin_id": provider_instance.plugin_id,
            "connection_mode": provider_instance.connection_mode,
            "operational_state": provider_instance.operational_state,
            "configuration": provider_instance.configuration,
        }
        for field, expected_value in expected.items():
            if actual[field] != expected_value:
                raise ValueError(
                    "provider installation executor returned mismatched "
                    f"{field}: expected {expected_value!r}, got {actual[field]!r}"
                )

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
        logical_suffix = self._runtime_binding_logical_suffix(
            model_deployment_id=model_deployment_id,
            capability_id=capability_id,
            capability_version=capability_version,
            capability_definition_hash=capability_definition_hash,
        )
        runtime_binding_id = f"rtb-{logical_suffix}"
        compatibility_bundle_id = f"bundle-{runtime_binding_id}"
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
            compatibility_bundle_id=compatibility_bundle_id,
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

    def bundle_hash_for_runtime_binding(self, runtime_binding_id: str) -> str:
        return self._bundle_hash(self.bundle_config_for_runtime_binding(runtime_binding_id))

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

    def _runtime_binding_logical_suffix(
        self,
        *,
        model_deployment_id: str,
        capability_id: str,
        capability_version: str,
        capability_definition_hash: str,
    ) -> str:
        digest = hashlib.sha256(
            "|".join(
                [
                    model_deployment_id,
                    capability_id,
                    capability_version,
                    capability_definition_hash,
            ]
        ).encode("utf-8")
        ).hexdigest()
        return digest[:16]

    def _bundle_hash(self, bundle: BundleConfig) -> str:
        payload = json.dumps(
            bundle.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
