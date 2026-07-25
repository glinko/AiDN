"""Reputation Engine — RFC-0041 compliant reputation profile system.

Provides structured Reputation Profiles with:
- Per-role profile types (Hypervisor, Endpoint, Validation, Registry, Consensus)
- Independent reputation dimensions (Availability, Reliability, Evidence Integrity…)
- Bayesian prior scoring with confidence-weighted evidence accumulators
- Profile state derivation (INSUFFICIENT_DATA → NORMAL → DEGRADED → CRITICAL)
- Advisory overall score with critical dimension cap
"""

from aidn_hypervisor.reputation_engine.models import (
    ReputationSubject,
    ReputationDimensionAccumulator,
    ReputationDimensionScore,
    ReputationProfile,
    ReputationEvent,
    ProfileDimensionWeight,
    ReputationProfileType,
    ReputationDimension,
    ReputationEventDirection,
    ReputationEventSeverity,
    EvidenceConfidenceClass,
    ReputationEventClass,
    ReputationProfileState,
)
from aidn_hypervisor.reputation_engine.store import ReputationStore
from aidn_hypervisor.reputation_engine.engine import ReputationEngine

__all__ = [
    # Types
    "ReputationProfileType",
    "ReputationDimension",
    "ReputationEventDirection",
    "ReputationEventSeverity",
    "EvidenceConfidenceClass",
    "ReputationEventClass",
    "ReputationProfileState",
    # Models
    "ReputationSubject",
    "ReputationDimensionAccumulator",
    "ReputationDimensionScore",
    "ReputationProfile",
    "ReputationEvent",
    "ProfileDimensionWeight",
    # Infrastructure
    "ReputationStore",
    "ReputationEngine",
]
