from pydantic import BaseModel, Field, field_validator

from aidn_hypervisor.domain.types import (
    AllocationPolicy,
    LaunchMode,
    TaskMode,
    WarmPolicy,
)


class ResourceProfile(BaseModel):
    cold_start_cpu: float = Field(default=0.0, ge=0)
    cold_start_ram_mb: int = Field(default=0, ge=0)
    cold_start_vram_mb: int = Field(default=0, ge=0)
    steady_cpu: float = Field(default=0.0, ge=0)
    steady_ram_mb: int = Field(default=0, ge=0)
    steady_vram_mb: int = Field(default=0, ge=0)
    per_request_cpu: float = Field(default=0.0, ge=0)
    per_request_ram_mb: int = Field(default=0, ge=0)
    per_request_vram_mb: int = Field(default=0, ge=0)


class BundleConfig(BaseModel):
    bundle_id: str
    plugin_id: str
    provider_type: str
    workload_type: str
    model_id: str
    launch_mode: LaunchMode
    endpoint: str | None = None
    device_affinity: str
    resource_profile: ResourceProfile
    warm_policy: WarmPolicy
    priority_class: int = 50
    max_parallel_requests: int = 1
    enabled: bool = True


class TaskRequest(BaseModel):
    task_type: str
    payload: dict
    mode: TaskMode = "auto"
    bundle_override: str | None = None
    priority: int = 50
    constraints: dict = Field(default_factory=dict)


class AllocationRequest(BaseModel):
    workload_type: str
    owner_id: str
    bundle_id: str | None = None
    policy: AllocationPolicy = "reject"
    lease_seconds: int = Field(default=300, ge=1, le=3600)


class CapabilityProbeRequest(BaseModel):
    owner_id: str
    workload_type: str | None = None
    bundle_id: str | None = None
    include_disabled: bool = False


class CapabilityCatalogEntry(BaseModel):
    bundle_id: str
    plugin_id: str
    provider_type: str
    model_id: str
    workload_type: str
    enabled: bool
    status: str
    endpoint: str | None = None
    can_allocate_now: bool
    can_queue: bool
    allocation_mode: str
    reason: str | None = None


class ModelInstallRequest(BaseModel):
    provider_type: str
    model_id: str
    source_url: str
    requested_by: str


class RegisterBundleFromInstallRequest(BaseModel):
    bundle_id: str
    workload_type: str
    endpoint: str


class NodeCapacity(BaseModel):
    cpu_cores: float = Field(ge=0)
    ram_mb: int = Field(ge=0)
    gpu_devices: list[str] = Field(default_factory=list)
    vram_mb: dict[str, int] = Field(default_factory=dict)

    @field_validator("vram_mb")
    @classmethod
    def _validate_vram_mb(cls, value: dict[str, int]) -> dict[str, int]:
        if any(amount < 0 for amount in value.values()):
            raise ValueError("vram_mb values must be non-negative")
        return value
