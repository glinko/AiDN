"""M6: Custom Model Onboarding — Data models.

Defines the OnboardingCapability model used to advertise a node's
custom model hosting capabilities to the registry.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ProviderCapability(BaseModel):
    """Describes a single provider runtime the node can host."""

    provider_type: str
    max_models: int = Field(default=5, ge=1)
    max_model_size_mb: int = Field(default=4096, ge=1)


class InstalledModelInfo(BaseModel):
    """Describes a model currently installed on the node."""

    model_id: str
    provider_type: str
    bundle_id: str | None = None
    size_mb: int = Field(default=0, ge=0)


class ResourceLimits(BaseModel):
    """Resource constraints for custom model hosting."""

    max_total_model_size_mb: int = Field(default=16384, ge=1)
    max_concurrent_models: int = Field(default=10, ge=1)
    available_vram_mb: int = Field(default=0, ge=0)


class OnboardingCapability(BaseModel):
    """Complete onboarding capability advertisement for a node.

    Published to the registry so agents and operators can discover
    which nodes support custom model onboarding.
    """

    node_id: str
    operator_id: str
    can_host_custom_model: bool
    supported_providers: list[ProviderCapability] = Field(default_factory=list)
    installed_models: list[InstalledModelInfo] = Field(default_factory=list)
    resource_limits: ResourceLimits | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"extra": "forbid"}

    def __init__(self, /, **data: Any) -> None:
        super().__init__(**data)
        now = datetime.now(UTC)
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now

    def model_dump(self, *args: Any, **kwargs: Any) -> dict:
        """Override to ensure consistent serialization."""
        return super().model_dump(*args, **kwargs)
