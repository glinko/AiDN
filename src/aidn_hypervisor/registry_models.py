from pydantic import BaseModel, Field

from aidn_hypervisor.canonical_models import (
    CanonicalAdvertisementRecord,
    CanonicalCapabilityRecord,
    CanonicalCapabilityRuntimeRecord,
    CanonicalComputeCompatibilityRecord,
    CanonicalEndpointFeatureProfileRecord,
    CanonicalEndpointImplementationProfileRecord,
    CanonicalEndpointLimitProfileRecord,
    CanonicalProtocolServiceRecord,
    CanonicalRegistryObjectRecord,
)


class RegistryPricing(BaseModel):
    unit: str = "q_per_1kk_tokens"
    input: int = Field(ge=0)
    output: int = Field(ge=0)
    fixed_request: int | None = Field(default=None, ge=0)


class RegistryRating(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    tier: str
    updated_at: str


class RegistryReputation(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    tier: str
    updated_at: str
    components: dict[str, float] = Field(default_factory=dict)
    evidence: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class RegistryBundleAdvertisement(BaseModel):
    bundle_id: str
    plugin_id: str
    workload_type: str
    provider_type: str
    model_id: str
    endpoint: str | None = None
    enabled: bool
    status: str
    launch_mode: str
    device_affinity: str
    max_parallel_requests: int
    supports_allocation: bool = True
    supports_queue: bool = True


class RegistryPublishedEndpointSummary(BaseModel):
    endpoint_id: str
    owner_wallet: str
    node_id: str
    current_publication_id: str
    current_configuration_hash: str
    published_at: str
    status: str
    visibility: str
    model_class: str
    publication_sync_status: str | None = None
    published_validation_summary: dict | None = None
    live_validation_summary: dict | None = None


class RegistryNodeAdvertisement(BaseModel):
    node_id: str
    operator_id: str
    owner_wallet_id: str | None = None
    registry_version: str = "m2.v2"
    base_url: str
    heartbeat_at: str
    heartbeat_ttl_seconds: int = 30
    status: str = "ready"
    resources: dict[str, dict[str, float | int]]
    providers: list[str]
    can_host_custom_model: bool
    pricing: RegistryPricing
    rating: RegistryRating
    reputation: RegistryReputation | None = None
    bundles: list[RegistryBundleAdvertisement]
    published_endpoints: list[RegistryPublishedEndpointSummary] = Field(
        default_factory=list
    )
    canonical_services: list[CanonicalProtocolServiceRecord] = Field(default_factory=list)
    canonical_capabilities: list[CanonicalCapabilityRecord] = Field(default_factory=list)
    canonical_capability_runtimes: list[CanonicalCapabilityRuntimeRecord] = Field(
        default_factory=list
    )
    canonical_compute_compatibility: list[CanonicalComputeCompatibilityRecord] = Field(
        default_factory=list
    )
    canonical_feature_profiles: list[CanonicalEndpointFeatureProfileRecord] = Field(
        default_factory=list
    )
    canonical_limit_profiles: list[CanonicalEndpointLimitProfileRecord] = Field(
        default_factory=list
    )
    canonical_implementation_profiles: list[
        CanonicalEndpointImplementationProfileRecord
    ] = Field(default_factory=list)
    canonical_registry_objects: list[CanonicalRegistryObjectRecord] = Field(
        default_factory=list
    )
    canonical_advertisements: list[CanonicalAdvertisementRecord] = Field(
        default_factory=list
    )


class RegistryDiscoveryQuery(BaseModel):
    workload_type: str | None = None
    provider_type: str | None = None
    model_id: str | None = None
    bundle_id: str | None = None
    capability_id: str | None = None
    runtime_id: str | None = None
    advertisement_resource_type: str | None = None
    visibility: str | None = None
    owner_wallet: str | None = None
    require_allocation_support: bool = False
    require_queue_support: bool = False
    ready_endpoint_only: bool = False
    can_host_custom_model: bool | None = None
    max_input_price_q_per_1kk: int | None = Field(default=None, ge=0)
    max_output_price_q_per_1kk: int | None = Field(default=None, ge=0)
    min_rating: float | None = Field(default=None, ge=0.0, le=1.0)
    include_stale: bool = False
    limit: int = Field(default=20, ge=1, le=100)


class RegistryObjectQuery(BaseModel):
    object_type: str | None = None
    namespace: str | None = None
    source_reference: str | None = None
    node_id: str | None = None
    include_stale: bool = False
    include_payload: bool = False
    limit: int = Field(default=50, ge=1, le=500)


class RegistryConflictEvidence(BaseModel):
    conflict_id: str
    conflict_class: str
    object_type: str
    namespace: str
    logical_key: str
    existing_record: dict
    conflicting_record: dict
    observed_at: str
    status: str = "open"
    resolved_at: str | None = None
    resolution_note: str | None = None
    resolution_payload: dict | None = None


class RegistryWalletIdentitySyncImportRequest(BaseModel):
    objects: list[dict] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)


class RegistryWalletIdentityPeerSyncRequest(BaseModel):
    peer_base_url: str
    limit: int = Field(default=500, ge=1, le=5000)


class RegistryWalletIdentityPeerConfig(BaseModel):
    peer_base_url: str
    enabled: bool = True
    added_at: str | None = None
    last_sync_at: str | None = None
    last_sync_status: str | None = None
    last_sync_error: str | None = None
    last_import_result: dict | None = None


class RegistryWalletIdentityPeerRepairRequest(BaseModel):
    limit: int = Field(default=500, ge=1, le=5000)


class RegistryWalletIdentityPeerDiscoveryRequest(BaseModel):
    self_node_id: str | None = None
    include_stale: bool = False
    auto_register: bool = True
    repair_after_discovery: bool = False
    limit: int = Field(default=500, ge=1, le=5000)


class RegistryWalletIdentityResolutionRequest(BaseModel):
    wallet_id: str = Field(min_length=1)
    chosen_object_id: str | None = None
    chosen_payload_hash: str | None = None
    operator_note: str | None = None


class RegistryWalletIdentityQuorumProposalRequest(BaseModel):
    wallet_id: str = Field(min_length=1)
    chosen_object_id: str | None = None
    chosen_payload_hash: str | None = None
    proposer_node_id: str = Field(min_length=1)
    proposer_signature: str | None = None
    eligible_voter_node_ids: list[str] = Field(default_factory=list)
    quorum_threshold: int | None = Field(default=None, ge=1)
    operator_note: str | None = None


class RegistryWalletIdentityQuorumApprovalRequest(BaseModel):
    resolution_id: str = Field(min_length=1)
    approver_node_id: str = Field(min_length=1)
    approval_signature: str | None = None
    approval_note: str | None = None


class RegistryWalletIdentityGovernancePolicy(BaseModel):
    policy_version: str = "wallet-identity-governance-policy.v1"
    authorized_voter_statuses: list[str] = Field(
        default_factory=lambda: ["ready", "stale"]
    )
    threshold_mode: str = "majority"
    minimum_eligible_voter_count: int = Field(default=1, ge=1)
    minimum_quorum_threshold: int = Field(default=1, ge=1)
    owner_wallet_link_required: bool = True
    signature_scheme: str = "ed25519"
    quorum_resolution_required: bool = False
    ledger_authorization_required: bool = False
    updated_at: str | None = None


class RegistryWalletIdentityGovernancePolicyUpdateRequest(BaseModel):
    authorized_voter_statuses: list[str] | None = None
    threshold_mode: str | None = None
    minimum_eligible_voter_count: int | None = Field(default=None, ge=1)
    minimum_quorum_threshold: int | None = Field(default=None, ge=1)
    quorum_resolution_required: bool | None = None
    ledger_authorization_required: bool | None = None


class RegistryCompletenessIssue(BaseModel):
    code: str
    object_id: str | None = None
    field: str | None = None
    detail: str | None = None


class RegistryCompletenessTotals(BaseModel):
    total_object_count: int = Field(ge=0)
    payload_object_count: int = Field(ge=0)
    payload_bytes_total: int = Field(ge=0)


class RegistryCompletenessIntegrity(BaseModel):
    object_count_matches_store: bool
    all_object_ids_unique: bool
    all_required_fields_present: bool
    payload_hash_coverage_count: int = Field(ge=0)
    issues: list[RegistryCompletenessIssue] = Field(default_factory=list)


class RegistryLocalCompletenessSummary(BaseModel):
    summary_version: str
    generated_at: str
    snapshot_schema_version: str
    store_totals: RegistryCompletenessTotals
    by_namespace: dict[str, int] = Field(default_factory=dict)
    by_object_type: dict[str, int] = Field(default_factory=dict)
    integrity: RegistryCompletenessIntegrity
