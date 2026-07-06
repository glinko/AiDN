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
    request_schema_id: str
    response_schema_id: str
    accounting_rule: str
    validation_rule: str


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
    resource_type: AdvertisementResourceType
    owner_wallet: str
    hypervisor_id: str
    capability_id: str | None = None
    visibility: str
    signature_scope: str
