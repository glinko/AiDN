"""M6-P3: Onboarding Service — HypervisorService integration.

Derives OnboardingCapability from HypervisorService state and
publishes it to the Registry automatically.
"""

from __future__ import annotations

import logging
from typing import Any

from aidn_hypervisor.model_onboarding.models import (
    InstalledModelInfo,
    OnboardingCapability,
    ProviderCapability,
    ResourceLimits,
)
from aidn_hypervisor.model_onboarding.publisher import OnboardingCapabilityPublisher

logger = logging.getLogger(__name__)

# Default provider types the hypervisor can host
DEFAULT_PROVIDERS = ["llama.cpp", "vllm"]


class OnboardingService:
    """Manages onboarding capability derivation and publication.

    Bridges HypervisorService state with the Registry by deriving
    an OnboardingCapability from the current service configuration
    and publishing it automatically.
    """

    def __init__(
        self,
        hypervisor_service: Any,
        *,
        registry: Any,
        auto_publish: bool = True,
        provider_types: list[str] | None = None,
    ) -> None:
        self._service = hypervisor_service
        self._publisher = OnboardingCapabilityPublisher(registry=registry)
        self._provider_types = provider_types or DEFAULT_PROVIDERS
        self._auto_publish = auto_publish

        if auto_publish:
            self.publish_current()

    # ------------------------------------------------------------------ #
    # Capability derivation
    # ------------------------------------------------------------------ #

    def derive_capability(self) -> OnboardingCapability:
        """Derive current onboarding capability from service state."""
        service = self._service

        # Derive provider capabilities
        providers = [
            ProviderCapability(
                provider_type=pt,
                max_models=5,
                max_model_size_mb=4096,
            )
            for pt in self._provider_types
        ]

        # Derive installed models from completed installs
        installed = []
        for job in getattr(service, "_model_installs", {}).values():
            if job.get("status") in ("completed", "registered"):
                installed.append(
                    InstalledModelInfo(
                        model_id=job.get("model_id", ""),
                        provider_type=job.get("provider_type", ""),
                        bundle_id=job.get("bundle_id"),
                        size_mb=0,
                    )
                )

        # Derive resource limits from service resources
        resources = getattr(service, "resources", None)
        resource_limits: ResourceLimits | None = None
        if resources is not None:
            capacity = getattr(resources, "capacity", None)
            if capacity is not None:
                available_vram = 0
                vram_map = getattr(capacity, "vram_mb", {})
                if isinstance(vram_map, dict):
                    available_vram = sum(vram_map.values())
                elif isinstance(vram_map, (int, float)):
                    available_vram = int(vram_map)

                resource_limits = ResourceLimits(
                    max_total_model_size_mb=int(
                        getattr(capacity, "ram_mb", 16384)
                    ),
                    max_concurrent_models=10,
                    available_vram_mb=available_vram,
                )

        return OnboardingCapability(
            node_id=service.node_id,
            operator_id=getattr(service, "operator_id", service.node_id),
            can_host_custom_model=getattr(
                service, "can_host_custom_model", False
            ),
            supported_providers=providers,
            installed_models=installed,
            resource_limits=resource_limits,
        )

    # ------------------------------------------------------------------ #
    # Publication
    # ------------------------------------------------------------------ #

    def publish_current(self) -> dict | None:
        """Derive and publish the current capability."""
        capability = self.derive_capability()
        return self._publisher.publish(capability)

    # ------------------------------------------------------------------ #
    # Query helpers
    # ------------------------------------------------------------------ #

    def query_node_capability(self, node_id: str) -> dict | None:
        """Query the onboarding capability for a specific node."""
        return self._publisher.query_capability(node_id)

    def list_capable_nodes(self) -> list[dict]:
        """List all nodes that can host custom models."""
        return self._publisher.list_capable_nodes()

    # ------------------------------------------------------------------ #
    # Subscription passthrough
    # ------------------------------------------------------------------ #

    def subscribe(
        self, node_id: str, callback
    ) -> None:
        """Register a callback for capability changes on a node."""
        self._publisher.subscribe(node_id, callback)

    def unsubscribe(
        self, node_id: str, callback
    ) -> None:
        """Remove a previously registered callback."""
        self._publisher.unsubscribe(node_id, callback)
