from typing import Literal

from pydantic import BaseModel, Field

ProtocolServiceKind = Literal["compute", "registry", "validation", "consensus"]
RuntimeLocationKind = Literal[
    "local_process",
    "container",
    "virtual_machine",
    "remote_service",
]
AdvertisementResourceType = Literal[
    "endpoint",
    "runtime",
    "registry_service",
    "validation_service",
    "consensus_service",
]


class CanonicalProtocolServiceRecord(BaseModel):
    service_id: str
    kind: ProtocolServiceKind
    enabled: bool
    derived_roles: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


class CanonicalCapabilityRecord(BaseModel):
    capability_id: str
    capability_version: str
    capability_definition_hash: str
    request_schema_hash: str
    response_schema_hash: str
    state_model: str
    streaming_model: str
    side_effect_model: str
    input_modalities: list[str] = Field(default_factory=list)
    output_modalities: list[str] = Field(default_factory=list)


class CanonicalEndpointFeatureProfileRecord(BaseModel):
    feature_profile_hash: str
    endpoint_id: str
    advertisement_id: str
    configuration_hash: str
    capability_id: str | None = None
    supported_features: list[str] = Field(default_factory=list)
    unsupported_features: list[str] = Field(default_factory=list)


class CanonicalEndpointLimitProfileRecord(BaseModel):
    limit_profile_hash: str
    endpoint_id: str
    advertisement_id: str
    configuration_hash: str
    capability_id: str | None = None
    max_context_units: int | None = None
    max_output_units: int | None = None
    max_request_duration_seconds: int | None = None
    max_session_duration_seconds: int | None = None


class CanonicalEndpointImplementationProfileRecord(BaseModel):
    implementation_profile_hash: str
    endpoint_id: str
    advertisement_id: str
    configuration_hash: str
    capability_id: str | None = None
    runtime_id: str
    execution_strategy: str
    publication_visibility: str
    validation_enabled: bool = False
    session_queue_policy: str | None = None


class CanonicalWalletIdentityRecord(BaseModel):
    identity_hash: str
    wallet_id: str
    public_key: str
    registration_nonce: str
    registered_at: str


class CanonicalRegistryObjectRecord(BaseModel):
    object_id: str
    object_type: str
    object_version: str
    namespace: str
    payload_hash: str
    payload_encoding: str = "canonical_json"
    source_reference: str
    payload: dict | None = None


class CanonicalCapabilityRuntimeRecord(BaseModel):
    runtime_id: str
    capability_id: str
    runtime_version: str
    protocol_version: str
    location_kind: RuntimeLocationKind
    health_status: str
    supported_features: list[str] = Field(default_factory=list)


class CanonicalComputeCompatibilityRecord(BaseModel):
    compatibility_id: str
    legacy_bundle_id: str
    legacy_plugin_id: str
    legacy_provider_type: str
    canonical_capability_id: str
    canonical_runtime_id: str


class CanonicalAdvertisementRecord(BaseModel):
    advertisement_id: str
    offer_id: str | None = None
    resource_type: AdvertisementResourceType
    owner_wallet: str
    hypervisor_id: str
    capability_id: str | None = None
    capability_version: str | None = None
    capability_definition_hash: str | None = None
    feature_profile_hash: str | None = None
    limit_profile_hash: str | None = None
    implementation_profile_hash: str | None = None
    visibility: str
    signature_scope: str
