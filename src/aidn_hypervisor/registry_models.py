from pydantic import BaseModel, Field


class RegistryPricing(BaseModel):
    unit: str = "q_per_1kk_tokens"
    input: int = Field(ge=0)
    output: int = Field(ge=0)
    fixed_request: int | None = Field(default=None, ge=0)


class RegistryRating(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    tier: str
    updated_at: str


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


class RegistryNodeAdvertisement(BaseModel):
    node_id: str
    operator_id: str
    registry_version: str = "m2.v1"
    base_url: str
    heartbeat_at: str
    heartbeat_ttl_seconds: int = 30
    status: str = "ready"
    resources: dict[str, dict[str, float | int]]
    providers: list[str]
    can_host_custom_model: bool
    pricing: RegistryPricing
    rating: RegistryRating
    bundles: list[RegistryBundleAdvertisement]


class RegistryDiscoveryQuery(BaseModel):
    workload_type: str | None = None
    provider_type: str | None = None
    model_id: str | None = None
    bundle_id: str | None = None
    require_allocation_support: bool = False
    require_queue_support: bool = False
    ready_endpoint_only: bool = False
    can_host_custom_model: bool | None = None
    max_input_price_q_per_1kk: int | None = Field(default=None, ge=0)
    max_output_price_q_per_1kk: int | None = Field(default=None, ge=0)
    min_rating: float | None = Field(default=None, ge=0.0, le=1.0)
    include_stale: bool = False
    limit: int = Field(default=20, ge=1, le=100)
