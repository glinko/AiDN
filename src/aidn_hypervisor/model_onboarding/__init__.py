# M6: Custom Model Onboarding

from aidn_hypervisor.model_onboarding.models import (
    InstalledModelInfo,
    OnboardingCapability,
    ProviderCapability,
    ResourceLimits,
)
from aidn_hypervisor.model_onboarding.publisher import (
    OnboardingCapabilityPublisher,
)
from aidn_hypervisor.model_onboarding.service import OnboardingService

__all__ = [
    "InstalledModelInfo",
    "OnboardingCapability",
    "OnboardingCapabilityPublisher",
    "OnboardingService",
    "ProviderCapability",
    "ResourceLimits",
]
