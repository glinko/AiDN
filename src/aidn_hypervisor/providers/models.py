from typing import Literal

from pydantic import BaseModel, Field, field_validator


ProviderConnectionMode = Literal["attached", "managed"]
ProviderOperationalState = Literal["created", "ready", "degraded", "error", "removed"]
ModelOperationalState = Literal["discovered", "installing", "ready", "error", "removed"]
RuntimeBindingStatus = Literal["draft", "ready", "degraded", "disabled"]
PluginTrustStatus = Literal[
    "UNREVIEWED",
    "COMMUNITY_REVIEWED",
    "CONFORMANCE_TESTED",
    "AIDN_CURATED",
    "SECURITY_WARNING",
    "SECURITY_BLOCKED",
]
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


def _require_non_empty(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("value must be non-empty")
    return value


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


class PluginUISchema(BaseModel):
    schema_id: str
    fields: list[dict] = Field(default_factory=list)

    @field_validator("schema_id")
    @classmethod
    def _schema_id_not_blank(cls, value: str) -> str:
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


class ProviderPluginManifest(BaseModel):
    plugin_id: str
    plugin_version: str
    display_name: str
    publisher: str
    package_digest: str
    provider_families: list[str] = Field(default_factory=list)
    plugin_capability_flags: list[str] = Field(default_factory=list)
    required_permissions: list[PluginPermission] = Field(default_factory=list)
    supported_aidn_capabilities: list[str] = Field(default_factory=list)
    trust_status: PluginTrustStatus = "UNREVIEWED"
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
    metadata_sources: dict[str, str] = Field(default_factory=dict)
    capability_bindings: list[str] = Field(default_factory=list)
    operational_state: ModelOperationalState


class RuntimeBinding(BaseModel):
    runtime_binding_id: str
    provider_instance_id: str
    model_deployment_id: str
    capability_id: str
    capability_version: str
    capability_definition_hash: str
    plugin_id: str
    compatibility_bundle_id: str
    status: RuntimeBindingStatus

    @field_validator(
        "runtime_binding_id",
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
