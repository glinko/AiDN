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
    ProviderInstallationDiagnosticCheck,
    ProviderInstallationDiagnostics,
    ProviderInstallationJob,
    ProviderPluginManifest,
    ProviderInstance,
    ProviderInstallationRollbackResult,
    RuntimeBinding,
    SelectedSecretHandle,
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
        approved_permissions: list[str] | None = None,
        selected_secret_handles: list[dict] | None = None,
        operator_note: str | None = None,
    ) -> ProviderInstallationApproval:
        plugin = self._get_plugin(plugin_id)
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        approved_configuration = deepcopy(configuration)
        plan = self.build_installation_plan(
            plugin_id=plugin_id,
            configuration=approved_configuration,
        )
        normalized_secret_requirements = self._normalized_secret_requirements(manifest)
        normalized_approved_permissions = self._validate_approved_permissions(
            requested_permissions=[
                permission["permission_id"]
                for permission in plan.get("required_permissions", [])
            ],
            approved_permissions=approved_permissions,
        )
        normalized_selected_secret_handles = self._validate_selected_secret_handles(
            normalized_requirements=normalized_secret_requirements,
            selected_secret_handles=selected_secret_handles,
        )
        approval = ProviderInstallationApproval(
            approval_id=f"pia-{uuid4().hex[:12]}",
            plugin_id=plugin_id,
            plan_id=plan["plan_id"],
            plan_hash=_canonical_hash(deepcopy(plan)),
            configuration_hash=_canonical_hash(deepcopy(approved_configuration)),
            configuration=deepcopy(approved_configuration),
            approved_permissions=normalized_approved_permissions,
            acknowledged_secret_requirements=normalized_secret_requirements,
            selected_secret_handles=normalized_selected_secret_handles,
            operator_note=operator_note,
            status="APPROVED",
            created_at=_now_iso(),
        )
        self.store.save_installation_approval(approval)
        return approval

    def list_installation_approvals(self) -> list[ProviderInstallationApproval]:
        return self.store.list_installation_approvals()

    def run_installation_diagnostics(
        self,
        *,
        plugin_id: str,
        configuration: dict,
        approved_permissions: list[str] | None = None,
        selected_secret_handles: list[dict] | None = None,
    ) -> ProviderInstallationDiagnostics:
        plugin = self._get_plugin(plugin_id)
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        diagnostics_configuration = deepcopy(configuration)
        plan = InstallationPlan.model_validate(
            self.build_installation_plan(
                plugin_id=plugin_id,
                configuration=diagnostics_configuration,
            )
        )
        plan_hash = _canonical_hash(plan.model_dump(mode="json"))
        configuration_hash = _canonical_hash(deepcopy(diagnostics_configuration))
        normalized_secret_requirements = self._normalized_secret_requirements(manifest)
        checks: list[ProviderInstallationDiagnosticCheck] = [
            ProviderInstallationDiagnosticCheck(
                check_id="configuration_valid",
                status="PASS",
                summary="Declarative installation plan built successfully.",
                details={
                    "plan_id": plan.plan_id,
                    "declared_sections": [
                        section
                        for section in (
                            "containers",
                            "processes",
                            "model_downloads",
                            "volumes",
                            "networks",
                            "environment",
                            "resource_limits",
                            "health_checks",
                        )
                        if getattr(plan, section)
                    ],
                },
            )
        ]

        try:
            normalized_permissions = self._validate_approved_permissions(
                requested_permissions=[
                    permission.permission_id for permission in plan.required_permissions
                ],
                approved_permissions=approved_permissions,
            )
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="permissions_acknowledged",
                    status="PASS",
                    summary="Requested permissions are fully acknowledged.",
                    details={
                        "requested_permissions": [
                            permission.permission_id for permission in plan.required_permissions
                        ],
                        "approved_permissions": normalized_permissions,
                    },
                )
            )
        except ValueError as exc:
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="permissions_acknowledged",
                    status="FAIL",
                    summary=str(exc),
                    details={
                        "requested_permissions": [
                            permission.permission_id for permission in plan.required_permissions
                        ],
                        "approved_permissions": list(approved_permissions or []),
                    },
                )
            )

        normalized_selected_handles: list[SelectedSecretHandle] = []
        try:
            normalized_selected_handles = self._validate_selected_secret_handles(
                normalized_requirements=normalized_secret_requirements,
                selected_secret_handles=selected_secret_handles,
            )
            missing_optional_requirements = [
                requirement["requirement_key"]
                for requirement in normalized_secret_requirements
                if not requirement["required"]
                and requirement["requirement_key"]
                not in {
                    handle.requirement_key for handle in normalized_selected_handles
                }
            ]
            if missing_optional_requirements:
                checks.append(
                    ProviderInstallationDiagnosticCheck(
                        check_id="secret_handles",
                        status="WARN",
                        summary="Optional secret handles are still unassigned.",
                        details={
                            "selected_secret_handles": [
                                handle.model_dump(mode="json")
                                for handle in normalized_selected_handles
                            ],
                            "missing_optional_requirements": missing_optional_requirements,
                        },
                    )
                )
            else:
                checks.append(
                    ProviderInstallationDiagnosticCheck(
                        check_id="secret_handles",
                        status="PASS",
                        summary="Secret handle requirements are satisfied.",
                        details={
                            "selected_secret_handles": [
                                handle.model_dump(mode="json")
                                for handle in normalized_selected_handles
                            ],
                        },
                    )
                )
        except ValueError as exc:
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="secret_handles",
                    status="FAIL",
                    summary=str(exc),
                    details={
                        "selected_secret_handles": list(selected_secret_handles or []),
                        "requirements": normalized_secret_requirements,
                    },
                )
            )

        diagnostic_approval = ProviderInstallationApproval(
            approval_id="diagnostic-preview",
            plugin_id=plugin_id,
            plan_id=plan.plan_id,
            plan_hash=plan_hash,
            configuration_hash=configuration_hash,
            configuration=deepcopy(diagnostics_configuration),
            approved_permissions=[
                permission.permission_id for permission in plan.required_permissions
            ],
            acknowledged_secret_requirements=normalized_secret_requirements,
            selected_secret_handles=normalized_selected_handles,
            created_at=_now_iso(),
        )
        rollback_result = self._rollback_preview(
            approval=diagnostic_approval,
            plan=plan,
            configuration=deepcopy(diagnostics_configuration),
            manifest=manifest.model_dump(mode="json"),
        )
        checks.append(
            ProviderInstallationDiagnosticCheck(
                check_id="executor_readiness",
                status="PASS",
                summary=f"Executor {self.installation_executor.executor_id} accepted the dry-run preview.",
                details={"executor_id": self.installation_executor.executor_id},
            )
        )
        checks.append(
            ProviderInstallationDiagnosticCheck(
                check_id="rollback_preview",
                status="PASS" if rollback_result.status in {"NOT_REQUIRED", "NOT_NEEDED", "COMPLETED"} else "WARN",
                summary=rollback_result.summary,
                details=deepcopy(rollback_result.details),
            )
        )

        readiness_status = self._diagnostic_readiness_status(checks)
        return ProviderInstallationDiagnostics(
            diagnostics_id=f"pid-{uuid4().hex[:12]}",
            plugin_id=plugin_id,
            plan_id=plan.plan_id,
            plan_hash=plan_hash,
            configuration_hash=configuration_hash,
            executor_id=self.installation_executor.executor_id,
            readiness_status=readiness_status,
            checks=checks,
            rollback_result=rollback_result,
            created_at=_now_iso(),
        )

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
        normalized_secret_requirements = self._normalized_secret_requirements(manifest)
        if normalized_secret_requirements != approval.acknowledged_secret_requirements:
            raise ValueError("installation secret requirements changed since approval")
        rebuilt_permission_ids = [
            permission.permission_id for permission in plan.required_permissions
        ]
        if approval.approved_permissions != rebuilt_permission_ids:
            raise ValueError("installation approved permissions do not match current plan")

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
                    "rollback_status": (
                        result.rollback_result.status
                        if result.rollback_result is not None
                        else "NOT_NEEDED"
                    ),
                    "rollback_summary": (
                        result.rollback_result.summary
                        if result.rollback_result is not None
                        else None
                    ),
                    "completed_at": _now_iso(),
                }
            )
        except Exception as exc:
            rollback_result = self._rollback_preview(
                approval=approval,
                plan=plan,
                configuration=deepcopy(approved_configuration),
                manifest=manifest.model_dump(mode="json"),
            )
            job = job.model_copy(
                update={
                    "status": "FAILED",
                    "rollback_status": rollback_result.status,
                    "rollback_summary": rollback_result.summary,
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                    "completed_at": _now_iso(),
                }
            )
        self.store.save_installation_job(job)
        return job

    def list_installation_jobs(self) -> list[ProviderInstallationJob]:
        return self.store.list_installation_jobs()

    def _diagnostic_readiness_status(
        self,
        checks: list[ProviderInstallationDiagnosticCheck],
    ) -> str:
        statuses = [check.status for check in checks]
        if "FAIL" in statuses:
            return "BLOCKED"
        if "WARN" in statuses:
            return "ACTION_REQUIRED"
        return "READY"

    def _rollback_preview(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> ProviderInstallationRollbackResult:
        executor = self.installation_executor
        rollback_preview = getattr(executor, "rollback_preview", None)
        if rollback_preview is None:
            return ProviderInstallationRollbackResult(
                status="FAILED",
                summary=(
                    f"Executor {executor.executor_id} does not expose rollback preview; "
                    "manual cleanup guidance is required."
                ),
                details={
                    "executor_id": executor.executor_id,
                    "rollback_preview_available": False,
                },
            )
        try:
            return rollback_preview(
                approval=approval,
                plan=plan,
                configuration=configuration,
                manifest=manifest,
            )
        except Exception as exc:
            return ProviderInstallationRollbackResult(
                status="FAILED",
                summary=(
                    f"Rollback preview failed for executor {executor.executor_id}: {exc}"
                ),
                details={
                    "executor_id": executor.executor_id,
                    "rollback_preview_available": True,
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                },
            )

    def _normalized_secret_requirements(
        self,
        manifest: ProviderPluginManifest,
    ) -> list[dict]:
        normalized: list[dict] = []
        for requirement in manifest.secret_requirements:
            normalized.append(
                {
                    "requirement_key": self._secret_requirement_key(
                        secret_type=requirement.secret_type,
                        label=requirement.label,
                    ),
                    "secret_type": requirement.secret_type,
                    "label": requirement.label,
                    "required": requirement.required,
                    "allowed_usage": list(requirement.allowed_usage),
                }
            )
        return normalized

    def _validate_approved_permissions(
        self,
        *,
        requested_permissions: list[str],
        approved_permissions: list[str] | None,
    ) -> list[str]:
        requested_permission_ids = list(requested_permissions)
        if approved_permissions is None:
            return requested_permission_ids
        normalized_approved_permissions = list(approved_permissions)
        missing_permissions = [
            permission_id
            for permission_id in requested_permission_ids
            if permission_id not in normalized_approved_permissions
        ]
        unexpected_permissions = [
            permission_id
            for permission_id in normalized_approved_permissions
            if permission_id not in requested_permission_ids
        ]
        if missing_permissions or unexpected_permissions:
            raise ValueError(
                "approved permissions must match requested permissions exactly"
            )
        return requested_permission_ids

    def _validate_selected_secret_handles(
        self,
        *,
        normalized_requirements: list[dict],
        selected_secret_handles: list[dict] | None,
    ) -> list[SelectedSecretHandle]:
        selected_handles = list(selected_secret_handles or [])
        requirement_by_key = {
            requirement["requirement_key"]: requirement
            for requirement in normalized_requirements
        }
        matched_keys: set[str] = set()
        normalized_selected_handles: list[SelectedSecretHandle] = []
        for item in selected_handles:
            requirement_key = str(item.get("requirement_key") or "").strip()
            if not requirement_key or requirement_key not in requirement_by_key:
                raise ValueError("selected secret handle does not match a known requirement")
            if requirement_key in matched_keys:
                raise ValueError("selected secret handle requirement keys must be unique")
            secret_handle = str(item.get("secret_handle") or "").strip()
            if not secret_handle:
                raise ValueError("selected secret handle must be non-empty")
            requirement = requirement_by_key[requirement_key]
            normalized_selected_handles.append(
                SelectedSecretHandle(
                    requirement_key=requirement_key,
                    secret_type=requirement["secret_type"],
                    label=requirement["label"],
                    secret_handle=secret_handle,
                    allowed_usage=list(requirement["allowed_usage"]),
                )
            )
            matched_keys.add(requirement_key)

        missing_required_keys = [
            requirement["requirement_key"]
            for requirement in normalized_requirements
            if requirement["required"] and requirement["requirement_key"] not in matched_keys
        ]
        if missing_required_keys:
            raise ValueError("required secret handles are missing")
        return normalized_selected_handles

    def _secret_requirement_key(self, *, secret_type: str, label: str) -> str:
        return f"{secret_type}:{label}"

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
