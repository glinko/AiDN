"""M6-P1: Onboarding Capability models — TDD tests.

Tests the OnboardingCapability model used to advertise a node's
custom model hosting capabilities to the registry.
"""

from datetime import UTC, datetime


class TestOnboardingCapabilityModel:
    """Test OnboardingCapability data model."""

    def test_create_minimal_capability(self):
        from aidn_hypervisor.model_onboarding.models import (
            OnboardingCapability,
        )

        cap = OnboardingCapability(
            node_id="node-001",
            operator_id="op-001",
            can_host_custom_model=True,
            supported_providers=[],
            installed_models=[],
        )

        assert cap.node_id == "node-001"
        assert cap.can_host_custom_model is True
        assert cap.supported_providers == []
        assert cap.installed_models == []
        assert cap.created_at is not None
        assert cap.updated_at is not None

    def test_create_with_provider_capabilities(self):
        from aidn_hypervisor.model_onboarding.models import (
            OnboardingCapability,
            ProviderCapability,
        )

        cap = OnboardingCapability(
            node_id="node-001",
            operator_id="op-001",
            can_host_custom_model=True,
            supported_providers=[
                ProviderCapability(
                    provider_type="llama.cpp",
                    max_models=5,
                    max_model_size_mb=4096,
                ),
                ProviderCapability(
                    provider_type="vllm",
                    max_models=3,
                    max_model_size_mb=8192,
                ),
            ],
            installed_models=[],
        )

        assert len(cap.supported_providers) == 2
        assert cap.supported_providers[0].provider_type == "llama.cpp"
        assert cap.supported_providers[0].max_models == 5
        assert cap.supported_providers[1].provider_type == "vllm"

    def test_create_with_installed_models(self):
        from aidn_hypervisor.model_onboarding.models import (
            InstalledModelInfo,
            OnboardingCapability,
        )

        cap = OnboardingCapability(
            node_id="node-001",
            operator_id="op-001",
            can_host_custom_model=True,
            supported_providers=[],
            installed_models=[
                InstalledModelInfo(
                    model_id="phi-4-mini.gguf",
                    provider_type="llama.cpp",
                    bundle_id="bundle-phi",
                    size_mb=2048,
                ),
            ],
        )

        assert len(cap.installed_models) == 1
        assert cap.installed_models[0].model_id == "phi-4-mini.gguf"
        assert cap.installed_models[0].bundle_id == "bundle-phi"

    def test_create_with_resource_limits(self):
        from aidn_hypervisor.model_onboarding.models import (
            OnboardingCapability,
            ResourceLimits,
        )

        cap = OnboardingCapability(
            node_id="node-001",
            operator_id="op-001",
            can_host_custom_model=True,
            supported_providers=[],
            installed_models=[],
            resource_limits=ResourceLimits(
                max_total_model_size_mb=16384,
                max_concurrent_models=10,
                available_vram_mb=4096,
            ),
        )

        assert cap.resource_limits.max_total_model_size_mb == 16384
        assert cap.resource_limits.max_concurrent_models == 10
        assert cap.resource_limits.available_vram_mb == 4096

    def test_disabled_capability(self):
        from aidn_hypervisor.model_onboarding.models import OnboardingCapability

        cap = OnboardingCapability(
            node_id="node-001",
            operator_id="op-001",
            can_host_custom_model=False,
            supported_providers=[],
            installed_models=[],
        )

        assert cap.can_host_custom_model is False

    def test_timestamps_are_set(self):
        from aidn_hypervisor.model_onboarding.models import OnboardingCapability

        before = datetime.now(UTC)
        cap = OnboardingCapability(
            node_id="node-001",
            operator_id="op-001",
            can_host_custom_model=True,
            supported_providers=[],
            installed_models=[],
        )
        after = datetime.now(UTC)

        assert before <= cap.created_at <= after
        assert before <= cap.updated_at <= after
        assert cap.created_at == cap.updated_at

    def test_full_capability(self):
        from aidn_hypervisor.model_onboarding.models import (
            InstalledModelInfo,
            OnboardingCapability,
            ProviderCapability,
            ResourceLimits,
        )

        cap = OnboardingCapability(
            node_id="node-001",
            operator_id="op-001",
            can_host_custom_model=True,
            supported_providers=[
                ProviderCapability(
                    provider_type="llama.cpp",
                    max_models=5,
                    max_model_size_mb=4096,
                ),
            ],
            installed_models=[
                InstalledModelInfo(
                    model_id="phi-4-mini.gguf",
                    provider_type="llama.cpp",
                    bundle_id="bundle-phi",
                    size_mb=2048,
                ),
            ],
            resource_limits=ResourceLimits(
                max_total_model_size_mb=16384,
                max_concurrent_models=10,
                available_vram_mb=4096,
            ),
        )

        assert cap.can_host_custom_model is True
        assert len(cap.supported_providers) == 1
        assert len(cap.installed_models) == 1
        assert cap.resource_limits is not None
        assert cap.resource_limits.max_total_model_size_mb == 16384
