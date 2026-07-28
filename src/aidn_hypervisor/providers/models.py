import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ProviderConnectionMode = Literal["attached", "managed"]
ProviderOperationalState = Literal["created", "ready", "degraded", "error", "removed"]
ModelOperationalState = Literal["discovered", "installing", "ready", "error", "removed"]
RuntimeBindingStatus = Literal["draft", "ready", "degraded", "disabled"]
RuntimeImplementationClass = Literal[
    "PLUGIN_MANAGED",
    "NATIVE",
    "EXTERNAL_DIRECT",
    "PROXY",
    "COMPOSITE",
    "REMOTE_RUNTIME",
]
RuntimeOperationalState = Literal[
    "DRAFT",
    "STAGING",
    "REGISTERING",
    "VERIFYING",
    "READY",
    "STARTING",
    "DEGRADED",
    "OVERLOADED",
    "DRAINING",
    "STOPPED",
    "RECOVERING",
    "FAILED",
    "QUARANTINED",
    "REVOKED",
    "REMOVING",
    "REMOVED",
]
PluginTrustStatus = Literal[
    "UNREVIEWED",
    "COMMUNITY_REVIEWED",
    "CONFORMANCE_TESTED",
    "AIDN_CURATED",
    "SECURITY_WARNING",
    "SECURITY_BLOCKED",
]
PluginReleaseStatus = Literal[
    "AVAILABLE",
    "DEPRECATED",
    "SECURITY_WARNING",
    "SECURITY_BLOCKED",
    "REVOKED",
]
InstalledPluginState = Literal[
    "INSTALLED",
    "ACTIVE",
    "DISABLED",
    "DEGRADED",
    "SECURITY_BLOCKED",
    "REVOKED",
    "REMOVED",
]
InstalledPluginSource = Literal["PACKAGE", "LEGACY_BUILTIN"]
PluginPermissionRisk = Literal["low", "medium", "high"]
PluginSecretType = Literal[
    "NONE",
    "API_KEY",
    "BEARER_TOKEN",
    "OAUTH",
    "BASIC_AUTH",
    "CLIENT_CERTIFICATE",
    "CUSTOM_SECRET_SET",
]
PluginPackageVerificationStatus = Literal[
    "VERIFIED",
    "UNVERIFIED",
    "INVALID",
]
PluginPackageVerificationMode = Literal[
    "NONE",
    "HASH_ONLY",
    "ED25519",
]
PluginSandboxExecutionMode = Literal[
    "RECORDED_ONLY",
    "SANDBOX_REQUIRED",
    "UNSANDBOXED_HOST",
]
PluginSandboxFilesystemScope = Literal[
    "NONE",
    "PLUGIN_DATA_ONLY",
    "MODEL_STORAGE_ONLY",
    "CONTROLLED_PATHS",
]
PluginSandboxNetworkScope = Literal[
    "NONE",
    "PRIVATE_ONLY",
    "DECLARED_EGRESS",
]
PluginSandboxSecretScope = Literal[
    "NONE",
    "DECLARED_HANDLES_ONLY",
]
ProviderInstallationUpgradeReviewStatus = Literal[
    "INITIAL_APPROVAL",
    "UNCHANGED",
    "CHANGED",
]
ProviderInstallationApprovalStatus = Literal["APPROVED", "REVOKED"]
ProviderInstallationJobStatus = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELLED"]
ProviderInstallationStepStatus = Literal["RECORDED", "SKIPPED", "FAILED"]
ProviderInstallationDiagnosticStatus = Literal["PASS", "WARN", "FAIL"]
ProviderInstallationReadinessStatus = Literal["READY", "ACTION_REQUIRED", "BLOCKED"]
ProviderInstallationRollbackStatus = Literal[
    "NOT_REQUIRED",
    "NOT_NEEDED",
    "PENDING",
    "COMPLETED",
    "FAILED",
]


def _require_non_empty(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("value must be non-empty")
    return value


def plugin_permission_hash(permissions: list[str]) -> str:
    normalized = sorted({_require_non_empty(permission) for permission in permissions})
    payload = json.dumps(normalized, separators=(",", ":"), ensure_ascii=True)
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


class PluginPermission(BaseModel):
    permission_id: str
    label: str
    risk_level: PluginPermissionRisk = "low"
    reason: str

    @field_validator("permission_id", "label", "reason")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class PluginSecretRequirement(BaseModel):
    secret_type: PluginSecretType
    label: str
    required: bool = False
    allowed_usage: list[str] = Field(default_factory=list)

    @field_validator("label")
    @classmethod
    def _label_not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class SelectedSecretHandle(BaseModel):
    requirement_key: str
    secret_type: PluginSecretType
    label: str
    secret_handle: str
    allowed_usage: list[str] = Field(default_factory=list)

    @field_validator("requirement_key", "label", "secret_handle")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class PluginUISchema(BaseModel):
    schema_id: str
    fields: list[dict] = Field(default_factory=list)

    @field_validator("schema_id")
    @classmethod
    def _schema_id_not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class PluginPackageVerification(BaseModel):
    status: PluginPackageVerificationStatus
    verification_mode: PluginPackageVerificationMode = "NONE"
    summary: str
    package_digest: str
    declared_manifest_hash: str | None = None
    computed_manifest_hash: str | None = None
    publisher_key_id: str | None = None
    signature_present: bool = False
    trusted_publisher: bool = False
    details: dict = Field(default_factory=dict)

    @field_validator("summary", "package_digest")
    @classmethod
    def _required_text(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("declared_manifest_hash", "computed_manifest_hash", "publisher_key_id")
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class PluginSandboxPolicy(BaseModel):
    execution_mode: PluginSandboxExecutionMode = "RECORDED_ONLY"
    filesystem_scope: PluginSandboxFilesystemScope = "NONE"
    network_scope: PluginSandboxNetworkScope = "NONE"
    secret_scope: PluginSandboxSecretScope = "DECLARED_HANDLES_ONLY"
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def _notes_not_blank_when_present(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class ExecutorSandboxCapabilities(BaseModel):
    supported_execution_modes: list[PluginSandboxExecutionMode] = Field(default_factory=list)
    supported_filesystem_scopes: list[PluginSandboxFilesystemScope] = Field(
        default_factory=list
    )
    supported_network_scopes: list[PluginSandboxNetworkScope] = Field(default_factory=list)
    supported_secret_scopes: list[PluginSandboxSecretScope] = Field(default_factory=list)
    host_mutation: bool = False
    notes: str | None = None

    @field_validator("notes")
    @classmethod
    def _notes_not_blank_when_present(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class InstallationRecipe(BaseModel):
    recipe_id: str
    display_name: str
    description: str
    provider_configuration: dict = Field(default_factory=dict)
    model_configuration: dict = Field(default_factory=dict)
    endpoint_defaults: dict = Field(default_factory=dict)

    @field_validator("recipe_id", "display_name", "description")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class InstallationPlan(BaseModel):
    plan_id: str
    plugin_id: str
    plan_version: str
    summary: str
    containers: list[dict] = Field(default_factory=list)
    processes: list[dict] = Field(default_factory=list)
    model_downloads: list[dict] = Field(default_factory=list)
    volumes: list[dict] = Field(default_factory=list)
    networks: list[dict] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    resource_limits: dict = Field(default_factory=dict)
    health_checks: list[dict] = Field(default_factory=list)
    required_permissions: list[PluginPermission] = Field(default_factory=list)
    secret_references: list[dict] = Field(default_factory=list)
    unsupported_actions: list[str] = Field(default_factory=list)

    @field_validator("plan_id", "plugin_id", "plan_version", "summary")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("unsupported_actions")
    @classmethod
    def _reject_unsupported_actions(cls, value: list[str]) -> list[str]:
        if value:
            raise ValueError("installation plan must be declarative-only")
        return value


class ProviderInstallationApproval(BaseModel):
    approval_id: str
    plugin_id: str
    plan_id: str
    plan_hash: str
    configuration_hash: str
    configuration: dict = Field(default_factory=dict)
    approved_permissions: list[str] = Field(default_factory=list)
    upgrade_review: dict = Field(default_factory=dict)
    upgrade_acknowledged: bool = False
    acknowledged_package_verification: dict = Field(default_factory=dict)
    acknowledged_sandbox_policy: dict = Field(default_factory=dict)
    acknowledged_secret_requirements: list[dict] = Field(default_factory=list)
    selected_secret_handles: list[SelectedSecretHandle] = Field(default_factory=list)
    operator_note: str | None = None
    status: ProviderInstallationApprovalStatus = "APPROVED"
    created_at: str

    @field_validator(
        "approval_id",
        "plugin_id",
        "plan_id",
        "plan_hash",
        "configuration_hash",
        "created_at",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderInstallationStepResult(BaseModel):
    step_id: str
    step_type: str
    status: ProviderInstallationStepStatus
    summary: str
    details: dict = Field(default_factory=dict)

    @field_validator("step_id", "step_type", "summary")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderInstallationDiagnosticCheck(BaseModel):
    check_id: str
    status: ProviderInstallationDiagnosticStatus
    summary: str
    details: dict = Field(default_factory=dict)

    @field_validator("check_id", "summary")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderInstallationRollbackResult(BaseModel):
    status: ProviderInstallationRollbackStatus
    summary: str
    details: dict = Field(default_factory=dict)
    step_results: list["ProviderInstallationStepResult"] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderInstallationDiagnostics(BaseModel):
    diagnostics_id: str
    plugin_id: str
    plan_id: str
    plan_hash: str
    configuration_hash: str
    executor_id: str
    readiness_status: ProviderInstallationReadinessStatus
    checks: list[ProviderInstallationDiagnosticCheck] = Field(default_factory=list)
    rollback_result: ProviderInstallationRollbackResult
    created_at: str

    @field_validator(
        "diagnostics_id",
        "plugin_id",
        "plan_id",
        "plan_hash",
        "configuration_hash",
        "executor_id",
        "created_at",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderInstallationArtifact(BaseModel):
    relative_path: str
    size_bytes: int
    sha256: str
    updated_at: str

    @field_validator("relative_path", "sha256", "updated_at")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderInstallationArtifactInventory(BaseModel):
    supported: bool
    imports_root: str | None = None
    max_artifact_bytes: int | None = None
    archive_extract_supported: bool = False
    supported_archive_formats: list[str] = Field(default_factory=list)
    max_extracted_bytes: int | None = None
    max_extracted_files: int | None = None
    items: list[ProviderInstallationArtifact] = Field(default_factory=list)

    @field_validator("imports_root")
    @classmethod
    def _optional_imports_root(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class ProviderInstallationArchiveExtractionResult(BaseModel):
    archive_relative_path: str
    destination_directory: str
    extracted_file_count: int
    extracted_total_bytes: int
    extracted_relative_paths: list[str] = Field(default_factory=list)

    @field_validator("archive_relative_path", "destination_directory")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ModelArtifact(BaseModel):
    """Immutable locally stored model bytes, addressed by their SHA-256 digest."""

    artifact_id: str
    content_sha256: str
    size_bytes: int
    original_filename: str
    storage_relative_path: str
    source_type: str
    source_reference: str
    created_at: str
    integrity_status: Literal["VERIFIED"] = "VERIFIED"
    reference_count: int = Field(default=0, ge=0)
    unreferenced_since: str | None = None
    garbage_collection_eligible_at: str | None = None

    @field_validator(
        "artifact_id",
        "content_sha256",
        "original_filename",
        "storage_relative_path",
        "source_type",
        "source_reference",
        "created_at",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("unreferenced_since", "garbage_collection_eligible_at")
    @classmethod
    def _optional_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class ModelArtifactInventory(BaseModel):
    supported: bool
    store_root: str | None = None
    max_artifact_bytes: int | None = None
    garbage_collection_grace_seconds: int | None = None
    items: list[ModelArtifact] = Field(default_factory=list)

    @field_validator("store_root")
    @classmethod
    def _optional_store_root(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class ModelArtifactGarbageCollectionResult(BaseModel):
    evaluated_at: str
    grace_seconds: int = Field(ge=0)
    retained_artifact_ids: list[str] = Field(default_factory=list)
    pending_artifact_ids: list[str] = Field(default_factory=list)
    collected_artifact_ids: list[str] = Field(default_factory=list)

    @field_validator("evaluated_at")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ModelArtifactSetFile(BaseModel):
    relative_path: str
    artifact_id: str
    role: Literal["WEIGHTS", "TOKENIZER", "CONFIG", "ADAPTER", "AUXILIARY"] = "AUXILIARY"

    @field_validator("relative_path", "artifact_id")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ModelArtifactSet(BaseModel):
    artifact_set_id: str
    display_name: str
    files: list[ModelArtifactSetFile] = Field(min_length=1)
    manifest_hash: str
    created_at: str

    @field_validator("artifact_set_id", "display_name", "manifest_hash", "created_at")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderArtifactMaterialization(BaseModel):
    materialization_id: str
    provider_instance_id: str
    artifact_set_id: str
    destination: str
    status: Literal["READY", "FAILED"]
    files: list[dict] = Field(default_factory=list)
    created_at: str

    @field_validator(
        "materialization_id",
        "provider_instance_id",
        "artifact_set_id",
        "destination",
        "created_at",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderInstallationUpgradeReview(BaseModel):
    status: ProviderInstallationUpgradeReviewStatus
    requires_acknowledgement: bool = False
    added_permissions: list[str] = Field(default_factory=list)
    removed_permissions: list[str] = Field(default_factory=list)
    package_verification_changed: bool = False
    previous_package_verification: dict = Field(default_factory=dict)
    current_package_verification: dict = Field(default_factory=dict)
    sandbox_policy_changed: bool = False
    previous_sandbox_policy: dict = Field(default_factory=dict)
    current_sandbox_policy: dict = Field(default_factory=dict)
    summary: str

    @field_validator("summary")
    @classmethod
    def _summary_not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderInstallationJob(BaseModel):
    job_id: str
    approval_id: str
    plugin_id: str
    plan_id: str
    plan_hash: str
    configuration_hash: str
    status: ProviderInstallationJobStatus
    executor_id: str
    step_results: list[ProviderInstallationStepResult] = Field(default_factory=list)
    provider_instance_id: str | None = None
    rollback_status: ProviderInstallationRollbackStatus = "NOT_NEEDED"
    rollback_summary: str | None = None
    rollback_step_results: list[ProviderInstallationStepResult] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    rollback_started_at: str | None = None
    rollback_completed_at: str | None = None

    @field_validator(
        "job_id",
        "approval_id",
        "plugin_id",
        "plan_id",
        "plan_hash",
        "configuration_hash",
        "executor_id",
        "created_at",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class ProviderInstallationExecutionResult(BaseModel):
    step_results: list[ProviderInstallationStepResult] = Field(default_factory=list)
    provider_instance: dict
    rollback_result: ProviderInstallationRollbackResult | None = None

    @field_validator("provider_instance")
    @classmethod
    def _validate_provider_instance(cls, value: dict) -> dict:
        return ProviderInstance.model_validate(value).model_dump()


class ProviderPluginManifest(BaseModel):
    plugin_id: str
    plugin_version: str
    display_name: str
    publisher: str
    package_digest: str
    publisher_public_key: str | None = None
    publisher_signature: str | None = None
    manifest_hash: str | None = None
    provider_families: list[str] = Field(default_factory=list)
    plugin_capability_flags: list[str] = Field(default_factory=list)
    required_permissions: list[PluginPermission] = Field(default_factory=list)
    supported_aidn_capabilities: list[str] = Field(default_factory=list)
    trust_status: PluginTrustStatus = "UNREVIEWED"
    sandbox_policy: PluginSandboxPolicy = Field(default_factory=PluginSandboxPolicy)
    source_repository: str | None = None
    license: str | None = None
    supported_platforms: list[str] = Field(default_factory=list)
    supported_architectures: list[str] = Field(default_factory=list)
    supported_accelerators: list[str] = Field(default_factory=list)
    attach_ui_schema: PluginUISchema | None = None
    install_ui_schema: PluginUISchema | None = None
    model_ui_schema: PluginUISchema | None = None
    endpoint_defaults_schema: PluginUISchema | None = None
    diagnostics_schema: PluginUISchema | None = None
    secret_requirements: list[PluginSecretRequirement] = Field(default_factory=list)
    installation_recipes: list[InstallationRecipe] = Field(default_factory=list)

    @field_validator("plugin_id", "plugin_version", "display_name", "publisher", "package_digest")
    @classmethod
    def _required_strings_not_blank(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("publisher_public_key", "publisher_signature", "manifest_hash")
    @classmethod
    def _optional_strings_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)

    @field_validator("required_permissions", mode="before")
    @classmethod
    def _normalize_legacy_permissions(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [
            {
                "permission_id": permission,
                "label": permission,
                "risk_level": "low",
                "reason": "Legacy permission declaration",
            }
            if isinstance(permission, str)
            else permission
            for permission in value
        ]


class PluginRelease(BaseModel):
    """Immutable package identity published by a plugin source or local catalog."""

    release_id: str
    plugin_id: str
    plugin_version: str
    manifest_hash: str
    package_digest: str
    publisher: str
    trust_status: PluginTrustStatus
    declared_permissions: list[str] = Field(default_factory=list)
    release_status: PluginReleaseStatus = "AVAILABLE"
    revocation_reason: str | None = None
    revoked_at: str | None = None
    source_reference: str | None = None
    package_verification_status: PluginPackageVerificationStatus = "UNVERIFIED"
    package_verification_mode: PluginPackageVerificationMode = "NONE"
    trusted_publisher: bool = False
    published_at: str

    @field_validator(
        "release_id",
        "plugin_id",
        "plugin_version",
        "manifest_hash",
        "package_digest",
        "publisher",
        "published_at",
    )
    @classmethod
    def _required_strings_not_blank(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator("source_reference")
    @classmethod
    def _optional_source_reference_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)

    @field_validator("declared_permissions")
    @classmethod
    def _normalize_declared_permissions(cls, value: list[str]) -> list[str]:
        return sorted({_require_non_empty(permission) for permission in value})


class InstalledPlugin(BaseModel):
    """Locally approved activation record for one immutable Plugin Release."""

    installed_plugin_id: str
    release_id: str
    plugin_id: str
    plugin_version: str
    package_digest: str | None = None
    granted_permissions: list[str] = Field(default_factory=list)
    granted_permission_hash: str | None = None
    installation_generation: int = Field(default=1, ge=1)
    activation_credential_key_id: str | None = None
    state: InstalledPluginState = "INSTALLED"
    installation_source: InstalledPluginSource
    installed_at: str
    activated_at: str | None = None

    @field_validator(
        "installed_plugin_id",
        "release_id",
        "plugin_id",
        "plugin_version",
        "installed_at",
    )
    @classmethod
    def _required_strings_not_blank(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator(
        "package_digest",
        "granted_permission_hash",
        "activation_credential_key_id",
        "activated_at",
    )
    @classmethod
    def _optional_identity_value_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)

    @field_validator("granted_permissions")
    @classmethod
    def _normalize_granted_permissions(cls, value: list[str]) -> list[str]:
        return sorted({_require_non_empty(permission) for permission in value})

    @model_validator(mode="after")
    def _validate_installation_identity(self) -> "InstalledPlugin":
        if self.installation_source == "PACKAGE" and self.package_digest is None:
            raise ValueError("package-installed plugin requires package_digest")
        expected_permission_hash = plugin_permission_hash(self.granted_permissions)
        if self.granted_permission_hash is None:
            self.granted_permission_hash = expected_permission_hash
        elif self.granted_permission_hash != expected_permission_hash:
            raise ValueError("granted_permission_hash does not match granted_permissions")
        return self


class ProviderInstance(BaseModel):
    provider_instance_id: str
    plugin_id: str
    provider_family: str
    display_name: str
    connection_mode: ProviderConnectionMode
    configuration: dict = Field(default_factory=dict)
    operational_state: ProviderOperationalState


class ModelDeployment(BaseModel):
    model_deployment_id: str
    provider_instance_id: str
    provider_model_reference: str
    operator_display_name: str
    declared_model_name: str | None = None
    artifact_set_id: str | None = None
    metadata_sources: dict[str, str] = Field(default_factory=dict)
    capability_bindings: list[str] = Field(default_factory=list)
    operational_state: ModelOperationalState

    @field_validator("artifact_set_id")
    @classmethod
    def _optional_artifact_set_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class RuntimeBinding(BaseModel):
    runtime_binding_id: str
    runtime_id: str
    runtime_generation: int = Field(default=1, ge=1)
    implementation_class: RuntimeImplementationClass = "PLUGIN_MANAGED"
    provider_instance_id: str
    model_deployment_id: str
    capability_id: str
    capability_version: str
    capability_definition_hash: str
    plugin_id: str
    installed_plugin_id: str | None = None
    plugin_version: str | None = None
    adapter_id: str | None = None
    adapter_version: str | None = None
    supported_features: list[str] = Field(default_factory=list)
    supported_modalities: list[str] = Field(default_factory=list)
    supported_accounting_modes: list[str] = Field(default_factory=list)
    usage_reporting_profile_hash: str | None = None
    resource_profile_hash: str | None = None
    security_profile_hash: str | None = None
    recovery_profile_hash: str | None = None
    dispatcher_route_scope: dict = Field(default_factory=lambda: {"channel_class": "RUNTIME"})
    runtime_configuration_hash: str | None = None
    compatibility_bundle_id: str
    status: RuntimeBindingStatus
    operational_state: RuntimeOperationalState | None = None

    @model_validator(mode="before")
    @classmethod
    def _populate_compatibility_identity(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        normalized.setdefault("runtime_id", normalized.get("runtime_binding_id"))
        if normalized.get("operational_state") is None:
            normalized["operational_state"] = {
                "draft": "DRAFT",
                "ready": "READY",
                "degraded": "DEGRADED",
                "disabled": "REVOKED",
            }.get(normalized.get("status"), "DRAFT")
        return normalized

    @model_validator(mode="after")
    def _bind_runtime_configuration(self):
        allowed_states = {
            "draft": {
                "DRAFT",
                "STAGING",
                "REGISTERING",
                "VERIFYING",
                "STARTING",
                "RECOVERING",
            },
            "ready": {"READY"},
            "degraded": {"DEGRADED", "OVERLOADED", "DRAINING"},
            "disabled": {
                "STOPPED",
                "FAILED",
                "QUARANTINED",
                "REVOKED",
                "REMOVING",
                "REMOVED",
            },
        }
        if self.operational_state not in allowed_states[self.status]:
            raise ValueError("status does not match Runtime operational_state")
        payload = {
            "implementation_class": self.implementation_class,
            "provider_instance_id": self.provider_instance_id,
            "model_deployment_id": self.model_deployment_id,
            "capability_id": self.capability_id,
            "capability_version": self.capability_version,
            "capability_definition_hash": self.capability_definition_hash,
            "plugin_id": self.plugin_id,
            "installed_plugin_id": self.installed_plugin_id,
            "plugin_version": self.plugin_version,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "supported_features": sorted(set(self.supported_features)),
            "supported_modalities": sorted(set(self.supported_modalities)),
            "supported_accounting_modes": sorted(set(self.supported_accounting_modes)),
            "usage_reporting_profile_hash": self.usage_reporting_profile_hash,
            "resource_profile_hash": self.resource_profile_hash,
            "security_profile_hash": self.security_profile_hash,
            "recovery_profile_hash": self.recovery_profile_hash,
            "dispatcher_route_scope": self.dispatcher_route_scope,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        expected = f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
        if self.runtime_configuration_hash is None:
            self.runtime_configuration_hash = expected
        elif self.runtime_configuration_hash != expected:
            raise ValueError("runtime_configuration_hash does not match Runtime configuration")
        return self

    def binding_hash(self) -> str:
        payload = {
            "runtime_id": self.runtime_id,
            "runtime_generation": self.runtime_generation,
            "runtime_configuration_hash": self.runtime_configuration_hash,
            "capability_definition_hash": self.capability_definition_hash,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return f"sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"

    @field_validator(
        "runtime_binding_id",
        "runtime_id",
        "provider_instance_id",
        "model_deployment_id",
        "capability_id",
        "capability_version",
        "capability_definition_hash",
        "plugin_id",
        "compatibility_bundle_id",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)

    @field_validator(
        "installed_plugin_id",
        "plugin_version",
        "adapter_id",
        "adapter_version",
        "usage_reporting_profile_hash",
        "resource_profile_hash",
        "security_profile_hash",
        "recovery_profile_hash",
        "runtime_configuration_hash",
    )
    @classmethod
    def _optional_not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_non_empty(value)


class RuntimeIdentity(BaseModel):
    runtime_id: str
    runtime_owner: str
    operator_hypervisor_id: str
    implementation_class: RuntimeImplementationClass
    runtime_generation: int = Field(ge=1)
    capability_id: str
    capability_major_version: int = Field(ge=0)
    runtime_configuration_hash: str
    identity_version: str = "1"

    @field_validator(
        "runtime_id",
        "runtime_owner",
        "operator_hypervisor_id",
        "capability_id",
        "runtime_configuration_hash",
        "identity_version",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)


class RuntimeInstance(BaseModel):
    runtime_id: str
    runtime_generation: int = Field(ge=1)
    instance_id: str
    runtime_binding_hash: str
    execution_host_id: str
    process_reference: str | None = None
    started_at: str
    operational_state: RuntimeOperationalState
    health_reference: str | None = None

    @field_validator(
        "runtime_id",
        "instance_id",
        "runtime_binding_hash",
        "execution_host_id",
        "started_at",
    )
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _require_non_empty(value)
