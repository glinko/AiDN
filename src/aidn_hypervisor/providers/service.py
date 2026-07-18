import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile
from aidn_hypervisor.providers.executor import (
    ProviderInstallationExecutor,
    RecordedProviderInstallationExecutor,
    SandboxEnforcedProviderInstallationExecutor,
)
from aidn_hypervisor.providers.models import (
    InstalledPlugin,
    InstallationPlan,
    ModelArtifact,
    ModelArtifactInventory,
    ModelArtifactGarbageCollectionResult,
    ModelArtifactSet,
    ProviderArtifactMaterialization,
    ModelDeployment,
    PluginPackageVerification,
    PluginRelease,
    ProviderInstallationApproval,
    ProviderInstallationArtifact,
    ProviderInstallationArchiveExtractionResult,
    ProviderInstallationArtifactInventory,
    ProviderInstallationDiagnosticCheck,
    ProviderInstallationDiagnostics,
    ProviderInstallationJob,
    ProviderInstallationStepResult,
    ProviderInstallationUpgradeReview,
    ProviderPluginManifest,
    ProviderInstance,
    ProviderInstallationRollbackResult,
    RuntimeBinding,
    SelectedSecretHandle,
)
from aidn_hypervisor.providers.package_verification import (
    DEFAULT_TRUSTED_PUBLISHER_KEYS,
    verify_plugin_manifest_package,
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
        trusted_publisher_keys: dict[str, list[str]] | None = None,
    ) -> None:
        self.plugins = plugins
        self.store = store
        self.installation_executor = (
            installation_executor or SandboxEnforcedProviderInstallationExecutor()
        )
        self.trusted_publisher_keys = deepcopy(
            trusted_publisher_keys or DEFAULT_TRUSTED_PUBLISHER_KEYS
        )
        self._runtime_binding_projections: dict[str, dict] = {}

    def list_plugin_manifests(self) -> list[dict]:
        return [self._plugin_manifest_payload(plugin) for plugin in self._list_plugins()]

    def list_plugin_releases(self) -> list[PluginRelease]:
        return self.store.list_plugin_releases()

    def list_installed_plugins(self) -> list[InstalledPlugin]:
        return self.store.list_installed_plugins()

    def register_plugin_release(
        self,
        *,
        manifest_payload: dict,
        source_reference: str | None = None,
        release_status: str = "AVAILABLE",
    ) -> PluginRelease:
        """Record a directory release without loading or executing its package."""
        manifest = ProviderPluginManifest.model_validate(manifest_payload)
        package_verification = self._package_verification(manifest)
        self._validate_package_verification(package_verification)
        if manifest.manifest_hash is None:
            raise ValueError("plugin release requires a declared manifest hash")

        release_identity = {
            "plugin_id": manifest.plugin_id,
            "plugin_version": manifest.plugin_version,
            "manifest_hash": manifest.manifest_hash,
            "package_digest": manifest.package_digest,
            "publisher": manifest.publisher,
        }
        release_id = f"prl-{_canonical_hash(release_identity).split(':', 1)[1][:20]}"
        try:
            return self.store.get_plugin_release(release_id)
        except KeyError:
            pass
        release = PluginRelease(
            release_id=release_id,
            plugin_id=manifest.plugin_id,
            plugin_version=manifest.plugin_version,
            manifest_hash=manifest.manifest_hash,
            package_digest=manifest.package_digest,
            publisher=manifest.publisher,
            trust_status=manifest.trust_status,
            declared_permissions=[
                permission.permission_id for permission in manifest.required_permissions
            ],
            release_status=release_status,
            source_reference=source_reference,
            published_at=_now_iso(),
        )
        self.store.save_plugin_release(release)
        return release

    def install_plugin_release(
        self,
        *,
        release_id: str,
        granted_permissions: list[str] | None = None,
        installation_source: str = "PACKAGE",
    ) -> InstalledPlugin:
        """Persist local approval; package acquisition and Plugin Host activation are separate."""
        release = self.store.get_plugin_release(release_id)
        if release.release_status in {"SECURITY_BLOCKED", "REVOKED"}:
            raise ValueError(
                f"plugin release cannot be installed while {release.release_status.lower()}"
            )
        normalized_permissions = sorted(set(granted_permissions or []))
        if not all(permission.strip() for permission in normalized_permissions):
            raise ValueError("granted permissions must not contain blank values")
        undeclared_permissions = sorted(
            set(normalized_permissions) - set(release.declared_permissions)
        )
        if undeclared_permissions:
            raise ValueError(
                "granted permissions must be declared by the plugin release: "
                + ", ".join(undeclared_permissions)
            )
        missing_permissions = sorted(
            set(release.declared_permissions) - set(normalized_permissions)
        )
        if missing_permissions:
            raise ValueError(
                "all declared plugin permissions require local approval: "
                + ", ".join(missing_permissions)
            )
        existing = next(
            (
                installed_plugin
                for installed_plugin in self.store.list_installed_plugins()
                if installed_plugin.release_id == release.release_id
            ),
            None,
        )
        if existing is not None:
            if existing.granted_permissions != normalized_permissions:
                raise ValueError(
                    "installed plugin permissions are immutable; install a new release instead"
                )
            return existing
        installed_plugin = InstalledPlugin(
            installed_plugin_id=f"iplg-{uuid4().hex[:12]}",
            release_id=release.release_id,
            plugin_id=release.plugin_id,
            plugin_version=release.plugin_version,
            granted_permissions=normalized_permissions,
            state="INSTALLED",
            installation_source=installation_source,
            installed_at=_now_iso(),
        )
        self.store.save_installed_plugin(installed_plugin)
        return installed_plugin

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
        upgrade_acknowledged: bool = False,
        selected_secret_handles: list[dict] | None = None,
        operator_note: str | None = None,
    ) -> ProviderInstallationApproval:
        plugin = self._get_plugin(plugin_id)
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        package_verification = self._package_verification(manifest)
        self._validate_package_verification(package_verification)
        approved_configuration = deepcopy(configuration)
        plan = self.build_installation_plan(
            plugin_id=plugin_id,
            configuration=approved_configuration,
        )
        requested_permission_ids = [
            permission["permission_id"] for permission in plan.get("required_permissions", [])
        ]
        normalized_sandbox_policy = self._normalized_sandbox_policy(manifest)
        self._validate_supported_sandbox_policy(
            normalized_sandbox_policy,
            executor_sandbox_capabilities=self._executor_sandbox_capabilities(),
        )
        upgrade_review = self._build_upgrade_review(
            plugin_id=plugin_id,
            requested_permissions=requested_permission_ids,
            package_verification=package_verification,
            normalized_sandbox_policy=normalized_sandbox_policy,
        )
        self._validate_upgrade_acknowledgement(
            upgrade_review=upgrade_review,
            upgrade_acknowledged=upgrade_acknowledged,
        )
        normalized_secret_requirements = self._normalized_secret_requirements(manifest)
        normalized_approved_permissions = self._validate_approved_permissions(
            requested_permissions=requested_permission_ids,
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
            upgrade_review=upgrade_review.model_dump(mode="json"),
            upgrade_acknowledged=upgrade_acknowledged,
            acknowledged_package_verification=package_verification.model_dump(mode="json"),
            acknowledged_sandbox_policy=normalized_sandbox_policy,
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

    def installation_artifact_inventory(self) -> ProviderInstallationArtifactInventory:
        inventory = getattr(
            self.installation_executor,
            "installation_artifact_inventory",
            None,
        )
        if inventory is None:
            return ProviderInstallationArtifactInventory(supported=False)
        return inventory()

    def stage_local_artifact(
        self,
        *,
        relative_path: str,
        content_bytes: bytes,
    ) -> ProviderInstallationArtifact:
        stage_artifact = getattr(
            self.installation_executor,
            "stage_local_artifact",
            None,
        )
        if stage_artifact is None:
            raise ValueError(
                "current installation executor does not support local artifact staging"
            )
        return stage_artifact(relative_path=relative_path, content_bytes=content_bytes)

    def delete_local_artifact(self, *, relative_path: str) -> None:
        delete_artifact = getattr(
            self.installation_executor,
            "delete_local_artifact",
            None,
        )
        if delete_artifact is None:
            raise ValueError(
                "current installation executor does not support local artifact deletion"
            )
        delete_artifact(relative_path=relative_path)

    def extract_local_artifact_archive(
        self,
        *,
        archive_relative_path: str,
        destination_directory: str,
    ) -> ProviderInstallationArchiveExtractionResult:
        extract_archive = getattr(
            self.installation_executor,
            "extract_local_artifact_archive",
            None,
        )
        if extract_archive is None:
            raise ValueError(
                "current installation executor does not support local artifact archive extraction"
            )
        return extract_archive(
            archive_relative_path=archive_relative_path,
            destination_directory=destination_directory,
        )

    def model_artifact_inventory(self) -> ModelArtifactInventory:
        inventory = getattr(self.installation_executor, "model_artifact_inventory", None)
        if inventory is None:
            return ModelArtifactInventory(supported=False)
        return inventory()

    def promote_local_artifact_to_model_store(
        self,
        *,
        relative_path: str,
    ) -> ModelArtifact:
        promote_artifact = getattr(
            self.installation_executor,
            "promote_local_artifact_to_model_store",
            None,
        )
        if promote_artifact is None:
            raise ValueError(
                "current installation executor does not support model artifact storage"
            )
        return promote_artifact(relative_path=relative_path)

    def delete_model_artifact(self, *, artifact_id: str) -> None:
        delete_artifact = getattr(
            self.installation_executor,
            "delete_model_artifact",
            None,
        )
        if delete_artifact is None:
            raise ValueError(
                "current installation executor does not support model artifact storage"
            )
        delete_artifact(artifact_id=artifact_id)

    def list_model_artifact_sets(self) -> list[ModelArtifactSet]:
        list_sets = getattr(self.installation_executor, "list_model_artifact_sets", None)
        if list_sets is None:
            return []
        return list_sets()

    def create_model_artifact_set(
        self,
        *,
        display_name: str,
        files: list[dict],
    ) -> ModelArtifactSet:
        create_set = getattr(self.installation_executor, "create_model_artifact_set", None)
        if create_set is None:
            raise ValueError(
                "current installation executor does not support model artifact storage"
            )
        return create_set(display_name=display_name, files=files)

    def delete_model_artifact_set(self, *, artifact_set_id: str) -> None:
        deployments = self.store.model_deployments_for_artifact_set(artifact_set_id)
        if deployments:
            raise ValueError(
                "cannot delete a model artifact set referenced by model deployment: "
                f"{deployments[0].model_deployment_id}"
            )
        delete_set = getattr(self.installation_executor, "delete_model_artifact_set", None)
        if delete_set is None:
            raise ValueError(
                "current installation executor does not support model artifact storage"
            )
        delete_set(artifact_set_id=artifact_set_id)

    def bind_model_artifact_set(
        self,
        *,
        model_deployment_id: str,
        artifact_set_id: str,
    ) -> ModelDeployment:
        deployment = self.store.get_model_deployment(model_deployment_id)
        if self.store.model_deployment_has_runtime_bindings(model_deployment_id):
            raise ValueError(
                "cannot change a model deployment artifact set after runtime bindings exist"
            )
        get_set = getattr(self.installation_executor, "get_model_artifact_set", None)
        if get_set is None:
            raise ValueError(
                "current installation executor does not support model artifact storage"
            )
        get_set(artifact_set_id)
        updated = deployment.model_copy(update={"artifact_set_id": artifact_set_id})
        self.store.save_model_deployment(updated)
        return updated

    def collect_model_artifact_garbage(self) -> ModelArtifactGarbageCollectionResult:
        collect = getattr(
            self.installation_executor,
            "collect_model_artifact_garbage",
            None,
        )
        if collect is None:
            raise ValueError(
                "current installation executor does not support model artifact storage"
            )
        return collect()

    def materialize_model_artifact_set(
        self, *, provider_instance_id: str, artifact_set_id: str, destination: str
    ) -> ProviderArtifactMaterialization:
        self.store.get_provider_instance(provider_instance_id)
        materialize = getattr(self.installation_executor, "materialize_model_artifact_set", None)
        if materialize is None:
            raise ValueError("current installation executor does not support model artifact materialization")
        result = materialize(
            provider_instance_id=provider_instance_id,
            artifact_set_id=artifact_set_id,
            destination=destination,
        )
        self.store.save_artifact_materialization(result)
        return result

    def list_artifact_materializations(self) -> list[ProviderArtifactMaterialization]:
        return self.store.list_artifact_materializations()

    def run_installation_diagnostics(
        self,
        *,
        plugin_id: str,
        configuration: dict,
        approved_permissions: list[str] | None = None,
        upgrade_acknowledged: bool = False,
        selected_secret_handles: list[dict] | None = None,
    ) -> ProviderInstallationDiagnostics:
        plugin = self._get_plugin(plugin_id)
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        package_verification = self._package_verification(manifest)
        diagnostics_configuration = deepcopy(configuration)
        plan = InstallationPlan.model_validate(
            self.build_installation_plan(
                plugin_id=plugin_id,
                configuration=diagnostics_configuration,
            )
        )
        plan_hash = _canonical_hash(plan.model_dump(mode="json"))
        configuration_hash = _canonical_hash(deepcopy(diagnostics_configuration))
        requested_permission_ids = [
            permission.permission_id for permission in plan.required_permissions
        ]
        normalized_sandbox_policy = self._normalized_sandbox_policy(manifest)
        executor_sandbox_capabilities = self._executor_sandbox_capabilities()
        upgrade_review = self._build_upgrade_review(
            plugin_id=plugin_id,
            requested_permissions=requested_permission_ids,
            package_verification=package_verification,
            normalized_sandbox_policy=normalized_sandbox_policy,
        )
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
        package_status_to_check_status = {
            "VERIFIED": "PASS",
            "UNVERIFIED": "WARN",
            "INVALID": "FAIL",
        }
        checks.append(
            ProviderInstallationDiagnosticCheck(
                check_id="package_verification",
                status=package_status_to_check_status[package_verification.status],
                summary=package_verification.summary,
                details=package_verification.model_dump(mode="json"),
            )
        )
        try:
            self._validate_supported_sandbox_policy(
                normalized_sandbox_policy,
                executor_sandbox_capabilities=executor_sandbox_capabilities,
            )
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="sandbox_policy",
                    status="PASS",
                    summary=(
                        "Plugin sandbox policy is supported by the current executor "
                        "sandbox boundary."
                    ),
                    details={
                        "plugin_sandbox_policy": deepcopy(normalized_sandbox_policy),
                        "executor_sandbox_capabilities": (
                            executor_sandbox_capabilities.model_dump(mode="json")
                        ),
                    },
                )
            )
        except ValueError as exc:
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="sandbox_policy",
                    status="FAIL",
                    summary=str(exc),
                    details={
                        "plugin_sandbox_policy": deepcopy(normalized_sandbox_policy),
                        "executor_sandbox_capabilities": (
                            executor_sandbox_capabilities.model_dump(mode="json")
                        ),
                    },
                )
            )

        try:
            self._validate_upgrade_acknowledgement(
                upgrade_review=upgrade_review,
                upgrade_acknowledged=upgrade_acknowledged,
            )
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="upgrade_review",
                    status="PASS",
                    summary=upgrade_review.summary,
                    details=upgrade_review.model_dump(mode="json"),
                )
            )
        except ValueError as exc:
            checks.append(
                ProviderInstallationDiagnosticCheck(
                    check_id="upgrade_review",
                    status="FAIL",
                    summary=str(exc),
                    details=upgrade_review.model_dump(mode="json"),
                )
            )

        try:
            normalized_permissions = self._validate_approved_permissions(
                requested_permissions=requested_permission_ids,
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
            approved_permissions=requested_permission_ids,
            upgrade_review=upgrade_review.model_dump(mode="json"),
            upgrade_acknowledged=upgrade_acknowledged,
            acknowledged_package_verification=package_verification.model_dump(mode="json"),
            acknowledged_sandbox_policy=deepcopy(normalized_sandbox_policy),
            acknowledged_secret_requirements=normalized_secret_requirements,
            selected_secret_handles=normalized_selected_handles,
            created_at=_now_iso(),
        )
        checks.extend(
            self._executor_diagnostic_checks(
                approval=diagnostic_approval,
                plan=plan,
                configuration=deepcopy(diagnostics_configuration),
                manifest=manifest.model_dump(mode="json"),
            )
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
                status="FAIL" if rollback_result.status == "FAILED" else "PASS",
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
        package_verification = self._package_verification(manifest)
        self._validate_package_verification(package_verification)
        plan_dict = self.build_installation_plan(
            plugin_id=approval.plugin_id,
            configuration=approved_configuration,
        )
        plan = InstallationPlan.model_validate(plan_dict)
        if _canonical_hash(deepcopy(plan_dict)) != approval.plan_hash:
            raise ValueError("installation plan hash mismatch")
        normalized_sandbox_policy = self._normalized_sandbox_policy(manifest)
        self._validate_supported_sandbox_policy(
            normalized_sandbox_policy,
            executor_sandbox_capabilities=self._executor_sandbox_capabilities(),
        )
        if approval.upgrade_review.get("requires_acknowledgement") and not approval.upgrade_acknowledged:
            raise ValueError("installation approval missing required upgrade acknowledgement")
        if normalized_sandbox_policy != approval.acknowledged_sandbox_policy:
            raise ValueError("installation sandbox policy changed since approval")
        normalized_secret_requirements = self._normalized_secret_requirements(manifest)
        if normalized_secret_requirements != approval.acknowledged_secret_requirements:
            raise ValueError("installation secret requirements changed since approval")
        if self._package_verification_binding(
            package_verification.model_dump(mode="json")
        ) != self._package_verification_binding(approval.acknowledged_package_verification):
            raise ValueError("installation package identity changed since approval")
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

        provider_instance_id = f"pi-{uuid4().hex[:12]}"
        try:
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
                    "rollback_step_results": (
                        result.rollback_result.step_results
                        if result.rollback_result is not None
                        else []
                    ),
                    "completed_at": _now_iso(),
                }
            )
        except Exception as exc:
            rollback_started_at = _now_iso()
            rollback_result = self._rollback_execution(
                approval=approval,
                plan=plan,
                configuration=deepcopy(approved_configuration),
                manifest=manifest.model_dump(mode="json"),
                provider_instance_id=provider_instance_id,
            )
            rollback_result = self._finalize_local_inventory_cleanup(
                rollback_result=rollback_result,
                provider_instance_id=provider_instance_id,
            )
            job = job.model_copy(
                update={
                    "status": "FAILED",
                    "rollback_status": rollback_result.status,
                    "rollback_summary": rollback_result.summary,
                    "rollback_step_results": rollback_result.step_results,
                    "rollback_started_at": rollback_started_at,
                    "rollback_completed_at": _now_iso(),
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                    "completed_at": _now_iso(),
                }
            )
        self.store.save_installation_job(job)
        return job

    def rollback_installation_job(self, job_id: str) -> ProviderInstallationJob:
        job = self.store.get_installation_job(job_id)
        if job.status not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("installation job must be terminal before rollback can run")
        if job.rollback_status == "COMPLETED":
            raise ValueError("installation job rollback already completed")

        approval = self.store.get_installation_approval(job.approval_id)
        plugin = self._get_plugin(approval.plugin_id)
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        plan_dict = self.build_installation_plan(
            plugin_id=approval.plugin_id,
            configuration=deepcopy(approval.configuration),
        )
        plan = InstallationPlan.model_validate(plan_dict)

        job = job.model_copy(update={"rollback_started_at": _now_iso()})
        self.store.save_installation_job(job)

        rollback_result = self._rollback_execution(
            approval=approval,
            plan=plan,
            configuration=deepcopy(approval.configuration),
            manifest=manifest.model_dump(mode="json"),
            provider_instance_id=job.provider_instance_id,
        )
        rollback_result = self._finalize_local_inventory_cleanup(
            rollback_result=rollback_result,
            provider_instance_id=job.provider_instance_id,
        )

        job = job.model_copy(
            update={
                "rollback_status": rollback_result.status,
                "rollback_summary": rollback_result.summary,
                "rollback_step_results": rollback_result.step_results,
                "rollback_completed_at": _now_iso(),
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

    def _executor_diagnostic_checks(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
    ) -> list[ProviderInstallationDiagnosticCheck]:
        diagnostic_checks = getattr(self.installation_executor, "diagnostic_checks", None)
        if diagnostic_checks is None:
            return []
        try:
            return list(
                diagnostic_checks(
                    approval=approval,
                    plan=plan,
                    configuration=configuration,
                    manifest=manifest,
                )
            )
        except Exception as exc:
            return [
                ProviderInstallationDiagnosticCheck(
                    check_id="executor_diagnostics",
                    status="FAIL",
                    summary=f"Executor diagnostics failed: {exc}",
                    details={"executor_id": self.installation_executor.executor_id},
                )
            ]

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

    def _rollback_execution(
        self,
        *,
        approval: ProviderInstallationApproval,
        plan: InstallationPlan,
        configuration: dict,
        manifest: dict,
        provider_instance_id: str | None,
    ) -> ProviderInstallationRollbackResult:
        executor = self.installation_executor
        rollback = getattr(executor, "rollback", None)
        if rollback is None:
            preview = self._rollback_preview(
                approval=approval,
                plan=plan,
                configuration=configuration,
                manifest=manifest,
            )
            return preview.model_copy(
                update={
                    "status": "FAILED",
                    "summary": (
                        f"Executor {executor.executor_id} does not expose rollback execution; "
                        "manual cleanup guidance is required."
                    ),
                    "details": {
                        **deepcopy(preview.details),
                        "executor_id": executor.executor_id,
                        "rollback_execution_available": False,
                        "provider_instance_id": provider_instance_id,
                    },
                }
            )
        try:
            return rollback(
                approval=approval,
                plan=plan,
                configuration=configuration,
                manifest=manifest,
                provider_instance_id=provider_instance_id,
            )
        except Exception as exc:
            return ProviderInstallationRollbackResult(
                status="FAILED",
                summary=(
                    f"Rollback execution failed for executor {executor.executor_id}: {exc}"
                ),
                details={
                    "executor_id": executor.executor_id,
                    "rollback_execution_available": True,
                    "provider_instance_id": provider_instance_id,
                    "error_code": exc.__class__.__name__,
                    "error_message": str(exc),
                },
            )

    def _finalize_local_inventory_cleanup(
        self,
        *,
        rollback_result: ProviderInstallationRollbackResult,
        provider_instance_id: str | None,
    ) -> ProviderInstallationRollbackResult:
        if provider_instance_id is None:
            return rollback_result
        if rollback_result.status not in {"COMPLETED", "NOT_REQUIRED", "NOT_NEEDED"}:
            return rollback_result

        cleanup_step: ProviderInstallationStepResult
        if any(
            instance.provider_instance_id == provider_instance_id
            for instance in self.store.list_provider_instances()
        ):
            self.store.delete_provider_instance(provider_instance_id)
            cleanup_step = ProviderInstallationStepResult(
                step_id="rollback-delete-local-provider-instance",
                step_type="rollback_local_inventory_delete",
                status="RECORDED",
                summary="Removed local provider inventory state for the rolled back install job.",
                details={"provider_instance_id": provider_instance_id},
            )
        else:
            cleanup_step = ProviderInstallationStepResult(
                step_id="rollback-local-provider-instance-missing",
                step_type="rollback_local_inventory_delete",
                status="SKIPPED",
                summary="Local provider inventory state was already absent before rollback cleanup.",
                details={"provider_instance_id": provider_instance_id},
            )

        return rollback_result.model_copy(
            update={
                "step_results": [*rollback_result.step_results, cleanup_step],
                "details": {
                    **deepcopy(rollback_result.details),
                    "local_inventory_cleanup": cleanup_step.status,
                },
            }
        )

    def _latest_installation_approval_for_plugin(
        self,
        plugin_id: str,
    ) -> ProviderInstallationApproval | None:
        approvals = [
            approval
            for approval in self.store.list_installation_approvals()
            if approval.plugin_id == plugin_id
        ]
        return approvals[-1] if approvals else None

    def _build_upgrade_review(
        self,
        *,
        plugin_id: str,
        requested_permissions: list[str],
        package_verification: PluginPackageVerification,
        normalized_sandbox_policy: dict,
    ) -> ProviderInstallationUpgradeReview:
        latest_approval = self._latest_installation_approval_for_plugin(plugin_id)
        if latest_approval is None:
            return ProviderInstallationUpgradeReview(
                status="INITIAL_APPROVAL",
                requires_acknowledgement=False,
                current_package_verification=package_verification.model_dump(mode="json"),
                current_sandbox_policy=deepcopy(normalized_sandbox_policy),
                summary="No previous installation approval exists for this plugin.",
            )
        previous_permissions = set(latest_approval.approved_permissions)
        current_permissions = set(requested_permissions)
        added_permissions = sorted(current_permissions - previous_permissions)
        removed_permissions = sorted(previous_permissions - current_permissions)
        previous_package_verification = deepcopy(
            latest_approval.acknowledged_package_verification
        )
        current_package_verification = package_verification.model_dump(mode="json")
        package_verification_changed = self._package_verification_binding(
            previous_package_verification
        ) != self._package_verification_binding(current_package_verification)
        previous_sandbox_policy = deepcopy(latest_approval.acknowledged_sandbox_policy)
        sandbox_policy_changed = previous_sandbox_policy != normalized_sandbox_policy
        if (
            not added_permissions
            and not removed_permissions
            and not sandbox_policy_changed
            and not package_verification_changed
        ):
            return ProviderInstallationUpgradeReview(
                status="UNCHANGED",
                requires_acknowledgement=False,
                previous_package_verification=previous_package_verification,
                current_package_verification=current_package_verification,
                previous_sandbox_policy=previous_sandbox_policy,
                current_sandbox_policy=deepcopy(normalized_sandbox_policy),
                summary="Permission, sandbox contract, and package identity match the latest approval.",
            )
        return ProviderInstallationUpgradeReview(
            status="CHANGED",
            requires_acknowledgement=True,
            added_permissions=added_permissions,
            removed_permissions=removed_permissions,
            package_verification_changed=package_verification_changed,
            previous_package_verification=previous_package_verification,
            current_package_verification=current_package_verification,
            sandbox_policy_changed=sandbox_policy_changed,
            previous_sandbox_policy=previous_sandbox_policy,
            current_sandbox_policy=deepcopy(normalized_sandbox_policy),
            summary="Installation permission, sandbox contract, or package identity changed since the latest approval.",
        )

    def _validate_upgrade_acknowledgement(
        self,
        *,
        upgrade_review: ProviderInstallationUpgradeReview,
        upgrade_acknowledged: bool,
    ) -> None:
        if upgrade_review.requires_acknowledgement and not upgrade_acknowledged:
            raise ValueError(
                "installation permission or sandbox change requires explicit upgrade acknowledgement"
            )

    def _normalized_sandbox_policy(
        self,
        manifest: ProviderPluginManifest,
    ) -> dict:
        return manifest.sandbox_policy.model_dump(mode="json")

    def _package_verification(
        self,
        manifest: ProviderPluginManifest,
    ) -> PluginPackageVerification:
        return verify_plugin_manifest_package(
            manifest,
            trusted_publisher_keys=self.trusted_publisher_keys,
        )

    def _package_verification_binding(self, verification: dict) -> dict:
        return {
            "status": verification.get("status"),
            "verification_mode": verification.get("verification_mode"),
            "package_digest": verification.get("package_digest"),
            "declared_manifest_hash": verification.get("declared_manifest_hash"),
            "computed_manifest_hash": verification.get("computed_manifest_hash"),
            "publisher_key_id": verification.get("publisher_key_id"),
            "signature_present": verification.get("signature_present"),
            "trusted_publisher": verification.get("trusted_publisher"),
        }

    def _validate_package_verification(
        self,
        package_verification: PluginPackageVerification,
    ) -> None:
        if package_verification.status == "INVALID":
            raise ValueError(package_verification.summary)

    def _plugin_manifest_payload(self, plugin) -> dict:
        manifest = ProviderPluginManifest.model_validate(plugin.plugin_manifest())
        payload = manifest.model_dump(mode="json")
        payload["package_verification"] = self._package_verification(manifest).model_dump(
            mode="json"
        )
        return payload

    def executor_sandbox_capabilities(self) -> dict:
        return self._executor_sandbox_capabilities().model_dump(mode="json")

    def _executor_sandbox_capabilities(self):
        sandbox_capabilities = getattr(self.installation_executor, "sandbox_capabilities", None)
        if sandbox_capabilities is None:
            return RecordedProviderInstallationExecutor().sandbox_capabilities()
        return sandbox_capabilities()

    def _validate_supported_sandbox_policy(
        self,
        normalized_sandbox_policy: dict,
        *,
        executor_sandbox_capabilities,
    ) -> None:
        execution_mode = normalized_sandbox_policy.get("execution_mode", "RECORDED_ONLY")
        filesystem_scope = normalized_sandbox_policy.get("filesystem_scope", "NONE")
        network_scope = normalized_sandbox_policy.get("network_scope", "NONE")
        secret_scope = normalized_sandbox_policy.get("secret_scope", "DECLARED_HANDLES_ONLY")
        if execution_mode not in executor_sandbox_capabilities.supported_execution_modes:
            raise ValueError(
                "plugin sandbox policy requires an unsupported execution mode: "
                f"{execution_mode}"
            )
        if filesystem_scope not in executor_sandbox_capabilities.supported_filesystem_scopes:
            raise ValueError(
                "plugin sandbox policy requires an unsupported filesystem scope: "
                f"{filesystem_scope}"
            )
        if network_scope not in executor_sandbox_capabilities.supported_network_scopes:
            raise ValueError(
                "plugin sandbox policy requires an unsupported network scope: "
                f"{network_scope}"
            )
        if secret_scope not in executor_sandbox_capabilities.supported_secret_scopes:
            raise ValueError(
                "plugin sandbox policy requires an unsupported secret scope: "
                f"{secret_scope}"
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
            model_deployment_id = item.get("model_deployment_id") or (
                f"md-{provider_instance_id}-{uuid4().hex[:8]}"
            )
            try:
                existing = self.store.get_model_deployment(model_deployment_id)
            except KeyError:
                existing = None
            deployment = ModelDeployment(
                model_deployment_id=model_deployment_id,
                provider_instance_id=provider_instance_id,
                provider_model_reference=item["provider_model_reference"],
                operator_display_name=item.get("operator_display_name")
                or item["provider_model_reference"],
                declared_model_name=item.get("declared_model_name"),
                artifact_set_id=(
                    existing.artifact_set_id if existing is not None else None
                ),
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
