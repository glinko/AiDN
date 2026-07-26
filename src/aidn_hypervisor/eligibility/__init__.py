"""M11-S3: Participant Eligibility + Anti-Sybil."""

from aidn_hypervisor.eligibility.engine import EligibilityEngine
from aidn_hypervisor.eligibility.kcg import KCGManager
from aidn_hypervisor.eligibility.models import (
    ACTIVATION_AGE_EPOCHS,
    MIN_GROUP_SHARE_CAP,
    MIN_SERVICE_HEALTH,
    EligibilityGateResult,
    EligibilitySnapshot,
    EligibilityState,
    GateCheck,
    IneligibilityReason,
    KCGMembership,
    KnownControlGroup,
)

__all__ = [
    "ACTIVATION_AGE_EPOCHS",
    "MIN_GROUP_SHARE_CAP",
    "MIN_SERVICE_HEALTH",
    "EligibilityEngine",
    "EligibilityGateResult",
    "EligibilitySnapshot",
    "EligibilityState",
    "GateCheck",
    "IneligibilityReason",
    "KCGManager",
    "KCGMembership",
    "KnownControlGroup",
]
