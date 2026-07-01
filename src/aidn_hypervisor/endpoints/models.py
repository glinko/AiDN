from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EndpointStatus = Literal["created", "stopped", "active", "suspended", "deleted"]
EndpointVisibility = Literal["public", "private", "shared"]
EndpointValidationMode = Literal["enabled", "disabled"]
EndpointVerificationStatus = Literal["unsupported", "pending", "active", "suspended"]
EndpointExecutionStrategy = Literal["local", "proxy"]


class EndpointProfile(BaseModel):
    summary: str | None = None
    strengths: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    recommended_tasks: list[str] = Field(default_factory=list)
    supported_languages: list[str] = Field(default_factory=list)
    preferred_formats: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)


class EndpointRuntimeConfig(BaseModel):
    context_length: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    top_k: int | None = Field(default=None, ge=1)
    max_tokens: int | None = Field(default=None, ge=1)
    streaming: bool = False
    timeout: int | None = Field(default=None, ge=1)


class EndpointPublicationPolicy(BaseModel):
    visibility: EndpointVisibility = "private"
    shared_with_wallet_ids: list[str] = Field(default_factory=list)
    discoverable: bool = False
    validation: EndpointValidationMode = "disabled"
    accepts_external_requests: bool = False

    @field_validator("shared_with_wallet_ids", mode="before")
    @classmethod
    def _normalize_shared_wallets(cls, value):
        if value is None:
            return []
        return [
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        ]

    @model_validator(mode="after")
    def _validate_shared_visibility(self):
        if self.visibility == "shared":
            if not self.shared_with_wallet_ids:
                raise ValueError("Shared endpoints require at least one allowed wallet")
            return self
        self.shared_with_wallet_ids = []
        return self


class EndpointPricing(BaseModel):
    billing_unit: str = "request"
    input_price: float | None = Field(default=None, ge=0.0)
    output_price: float | None = Field(default=None, ge=0.0)
    fixed_price: float | None = Field(default=None, ge=0.0)


class EndpointValidationState(BaseModel):
    enabled: bool = False
    model_class_supported: bool = False
    verification_status: EndpointVerificationStatus = "unsupported"
    validation_profile: str | None = None


class EndpointProxyTarget(BaseModel):
    remote_endpoint_id: str
    source_node_id: str
    source_endpoint_id: str
    source_publication_id: str
    source_configuration_hash: str
    source_base_url: str
    source_model_class: str
    operator_id: str
    alias: str | None = None
    attached_at: str


class EndpointManifest(BaseModel):
    endpoint_id: str
    owner_wallet: str
    created_at: str
    bundle_id: str
    bundle_hash: str
    configuration_hash: str
    display_name: str
    model_class: str
    capabilities: list[str] = Field(default_factory=list)
    profile: EndpointProfile = Field(default_factory=EndpointProfile)
    runtime: EndpointRuntimeConfig = Field(default_factory=EndpointRuntimeConfig)
    publication: EndpointPublicationPolicy = Field(default_factory=EndpointPublicationPolicy)
    pricing: EndpointPricing = Field(default_factory=EndpointPricing)
    validation: EndpointValidationState = Field(default_factory=EndpointValidationState)
    execution_strategy: EndpointExecutionStrategy = "local"
    proxy_target: EndpointProxyTarget | None = None
    status: EndpointStatus = "created"


class EndpointConfigurationSnapshot(BaseModel):
    configuration_hash: str
    endpoint_id: str
    bundle_hash: str
    created_at: str
    runtime: EndpointRuntimeConfig
    publication: EndpointPublicationPolicy
    proxy_target: EndpointProxyTarget | None = None
    execution_config: dict[str, bool | int | str | None] = Field(default_factory=dict)


class CreateEndpointCommand(BaseModel):
    owner_wallet: str
    bundle_id: str
    bundle_hash: str
    display_name: str
    model_class: str
    capabilities: list[str] = Field(default_factory=list)
    profile: EndpointProfile = Field(default_factory=EndpointProfile)
    runtime: EndpointRuntimeConfig = Field(default_factory=EndpointRuntimeConfig)
    publication: EndpointPublicationPolicy = Field(default_factory=EndpointPublicationPolicy)
    pricing: EndpointPricing = Field(default_factory=EndpointPricing)
    validation: EndpointValidationState = Field(default_factory=EndpointValidationState)


class UpdateEndpointCommand(BaseModel):
    endpoint_id: str | None = None
    display_name: str | None = None
    profile: EndpointProfile | None = None
    runtime: EndpointRuntimeConfig | None = None
    publication: EndpointPublicationPolicy | None = None
    pricing: EndpointPricing | None = None
    validation: EndpointValidationState | None = None
    execution_strategy: EndpointExecutionStrategy | None = None
    proxy_target: EndpointProxyTarget | None = None


class EndpointResult(BaseModel):
    endpoint: EndpointManifest


class CreateEndpointResult(EndpointResult):
    snapshot: EndpointConfigurationSnapshot


class UpdateEndpointResult(EndpointResult):
    snapshot: EndpointConfigurationSnapshot | None = None
