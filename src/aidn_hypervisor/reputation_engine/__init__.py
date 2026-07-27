"""Reputation Engine — RFC-0041 compliant reputation profile system.

Provides structured Reputation Profiles with:
- Per-role profile types (Hypervisor, Endpoint, Validation, Registry, Consensus)
- Independent reputation dimensions (Availability, Reliability, Evidence Integrity…)
- Bayesian prior scoring with confidence-weighted evidence accumulators
- Profile state derivation (INSUFFICIENT_DATA → NORMAL → DEGRADED → CRITICAL)
- Advisory overall score with critical dimension cap
"""

from aidn_hypervisor.reputation_engine.engine import ReputationEngine
from aidn_hypervisor.reputation_engine.models import (
    EvidenceConfidenceClass,
    ProfileDimensionWeight,
    ReputationDimension,
    ReputationDimensionAccumulator,
    ReputationDimensionScore,
    ReputationEvent,
    ReputationEventClass,
    ReputationEventDirection,
    ReputationEventSeverity,
    ReputationProfile,
    ReputationProfileState,
    ReputationProfileType,
    ReputationSubject,
)
from aidn_hypervisor.reputation_engine.registry_publication import (
    ReputationProfilePublisher,
)
from aidn_hypervisor.reputation_engine.store import ReputationStore

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
    # Registry publication
    "ReputationProfilePublisher",
]
