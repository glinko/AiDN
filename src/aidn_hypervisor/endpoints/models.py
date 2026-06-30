from typing import Literal

from pydantic import BaseModel, Field, model_validator

EndpointStatus = Literal["created", "stopped", "active", "suspended", "deleted"]
EndpointVisibility = Literal["public", "private"]
EndpointValidationMode = Literal["enabled", "disabled"]
EndpointVerificationStatus = Literal["unsupported", "pending", "active", "suspended"]


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
    discoverable: bool = False
    validation: EndpointValidationMode = "disabled"
    accepts_external_requests: bool = False


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
    status: EndpointStatus = "created"


class EndpointConfigurationSnapshot(BaseModel):
    configuration_hash: str
    endpoint_id: str
    bundle_hash: str
    created_at: str
    runtime: EndpointRuntimeConfig
    publication: EndpointPublicationPolicy
    execution_config: dict[str, bool | int | str | None] = Field(default_factory=dict)


class EndpointInvokeRequest(BaseModel):
    task_type: str
    payload: dict
    constraints: dict = Field(default_factory=dict)


class EndpointReadiness(BaseModel):
    endpoint_id: str
    bundle_id: str
    ready: bool
    code: str | None = None
    message: str | None = None
    runtime_id: str | None = None
    runtime_status: str | None = None
    runtime_health_status: str | None = None

    @model_validator(mode="after")
    def validate_not_ready_reason(self) -> "EndpointReadiness":
        if not self.ready and (self.code is None or self.message is None):
            raise ValueError("Not-ready endpoint readiness requires both code and message")
        return self


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
    endpoint_id: str
    display_name: str | None = None
    capabilities: list[str] | None = None
    profile: EndpointProfile | None = None
    runtime: EndpointRuntimeConfig | None = None
    publication: EndpointPublicationPolicy | None = None
    pricing: EndpointPricing | None = None
    validation: EndpointValidationState | None = None


class InvokeEndpointCommand(BaseModel):
    endpoint_id: str
    task_type: str
    payload: dict
    constraints: dict = Field(default_factory=dict)


class EndpointResult(BaseModel):
    endpoint: EndpointManifest


class CreateEndpointResult(EndpointResult):
    snapshot: EndpointConfigurationSnapshot


class UpdateEndpointResult(EndpointResult):
    snapshot: EndpointConfigurationSnapshot | None = None


class InvokeEndpointResult(EndpointResult):
    bundle_id: str
    runtime_id: str
    readiness: EndpointReadiness
    result: dict
