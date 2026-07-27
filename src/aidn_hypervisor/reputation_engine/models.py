"""Reputation Engine models (RFC-0041 Phase 1).

Implements the structured Reputation Profile with:
- per-role profile types
- independent dimensions with evidence accumulators
- Bayesian prior scoring with confidence weighting
- profile state derivation
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

# ──────────────────────────────────────────────
# Profile Types (RFC-0041 §3)
# ──────────────────────────────────────────────
ReputationProfileType = Literal[
    "HYPERVISOR",
    "CONSENSUS_SERVICE",
    "REGISTRY_SERVICE",
    "VALIDATION_SERVICE",
    "ENDPOINT",
]

# ──────────────────────────────────────────────
# Dimensions (RFC-0041 §7 + role-specific)
# ──────────────────────────────────────────────
ReputationDimension = Literal[
    # Common dimensions
    "AVAILABILITY",
    "RELIABILITY",
    "PROTOCOL_COMPLIANCE",
    "ACCOUNTING_CONSISTENCY",
    "EVIDENCE_INTEGRITY",
    "RECOVERY_RELIABILITY",
    # Endpoint-specific
    "CERTIFICATION_HISTORY",
    "VALIDATION_REPORT_AVAILABILITY",
    "VALIDATION_REPORT_RETENTION",
]

# ──────────────────────────────────────────────
# Event Direction (RFC-0041 §25)
# ──────────────────────────────────────────────
ReputationEventDirection = Literal["POSITIVE", "NEGATIVE", "NEUTRAL"]

# ──────────────────────────────────────────────
# Event Severity (RFC-0041 §27)
# ──────────────────────────────────────────────
ReputationEventSeverity = Literal[
    "INFORMATIONAL",
    "MINOR",
    "MODERATE",
    "MAJOR",
    "CRITICAL",
]

# ──────────────────────────────────────────────
# Evidence Confidence (RFC-0041 §28)
# ──────────────────────────────────────────────
EvidenceConfidenceClass = Literal[
    "FINALIZED_PROTOCOL",
    "CRYPTOGRAPHIC",
    "REPRODUCIBLE",
    "MULTI_SOURCE",
    "STATISTICAL",
    "OBSERVATIONAL",
    "SUBJECTIVE",
]

# ──────────────────────────────────────────────
# Event Classes (RFC-0041 §26)
# ──────────────────────────────────────────────
ReputationEventClass = Literal[
    "AVAILABILITY_EVENT",
    "EXECUTION_EVENT",
    "PROTOCOL_EVENT",
    "ACCOUNTING_EVENT",
    "EVIDENCE_EVENT",
    "RECOVERY_EVENT",
    "CERTIFICATION_EVENT",
    "SECURITY_EVENT",
    "FEEDBACK_EVENT",
    "ADMINISTRATIVE_EVENT",
]

# ──────────────────────────────────────────────
# Profile State (RFC-0041 §41)
# ──────────────────────────────────────────────
ReputationProfileState = Literal[
    "INSUFFICIENT_DATA",
    "ESTABLISHING",
    "NORMAL",
    "WATCH",
    "DEGRADED",
    "CRITICAL",
    "DISQUALIFIED",
    "RETIRED",
]

# ──────────────────────────────────────────────
# Constants (RFC-0041 §19, §21, §22)
# ──────────────────────────────────────────────
PRIOR_SCORE = 0.5
PRIOR_POSITIVE_MASS = 1.0
PRIOR_NEGATIVE_MASS = 1.0
TARGET_EVIDENCE_MASS = 10.0  # role-specific default; lower → faster confidence build

# Severity → base weight mapping (RFC-0041 §36)
SEVERITY_WEIGHTS: dict[str, float] = {
    "INFORMATIONAL": 0.1,
    "MINOR": 0.3,
    "MODERATE": 0.6,
    "MAJOR": 1.0,
    "CRITICAL": 2.0,
}

# Evidence confidence → factor mapping (RFC-0041 §36)
CONFIDENCE_FACTORS: dict[str, float] = {
    "FINALIZED_PROTOCOL": 1.0,
    "CRYPTOGRAPHIC": 0.9,
    "REPRODUCIBLE": 0.75,
    "MULTI_SOURCE": 0.6,
    "STATISTICAL": 0.4,
    "OBSERVATIONAL": 0.25,
    "SUBJECTIVE": 0.1,
}


# ──────────────────────────────────────────────
# Profile Dimension Weights (RFC-0041 §15)
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class ProfileDimensionWeight:
    """Dimension weights per profile type.

    Higher weight → more influence on advisory overall score.
    Critical dimensions (EVIDENCE_INTEGRITY) get higher weight.
    """

    weights: dict[str, float]

    @classmethod
    def get_weights(cls, profile_type: str) -> dict[str, float]:
        """Return dimension weights for a profile type."""
        configs: dict[str, dict[str, float]] = {
            "HYPERVISOR": {
                "AVAILABILITY": 1.0,
                "RELIABILITY": 1.2,
                "PROTOCOL_COMPLIANCE": 1.0,
                "ACCOUNTING_CONSISTENCY": 0.8,
                "EVIDENCE_INTEGRITY": 1.5,  # critical
                "RECOVERY_RELIABILITY": 0.8,
            },
            "ENDPOINT": {
                "AVAILABILITY": 1.2,
                "RELIABILITY": 1.5,
                "PROTOCOL_COMPLIANCE": 1.0,
                "ACCOUNTING_CONSISTENCY": 1.2,
                "EVIDENCE_INTEGRITY": 1.5,  # critical
                "RECOVERY_RELIABILITY": 0.8,
                "CERTIFICATION_HISTORY": 0.5,
                "VALIDATION_REPORT_AVAILABILITY": 0.4,
                "VALIDATION_REPORT_RETENTION": 0.3,
            },
            "VALIDATION_SERVICE": {
                "AVAILABILITY": 1.0,
                "RELIABILITY": 1.5,
                "PROTOCOL_COMPLIANCE": 1.0,
                "ACCOUNTING_CONSISTENCY": 0.5,
                "EVIDENCE_INTEGRITY": 2.0,  # extra critical for validators
                "RECOVERY_RELIABILITY": 0.8,
            },
            "REGISTRY_SERVICE": {
                "AVAILABILITY": 1.2,
                "RELIABILITY": 1.0,
                "PROTOCOL_COMPLIANCE": 1.0,
                "ACCOUNTING_CONSISTENCY": 0.3,
                "EVIDENCE_INTEGRITY": 1.5,
                "RECOVERY_RELIABILITY": 0.8,
            },
            "CONSENSUS_SERVICE": {
                "AVAILABILITY": 1.0,
                "RELIABILITY": 1.2,
                "PROTOCOL_COMPLIANCE": 1.0,
                "ACCOUNTING_CONSISTENCY": 0.3,
                "EVIDENCE_INTEGRITY": 2.0,  # extra critical
                "RECOVERY_RELIABILITY": 1.0,
            },
        }
        return configs.get(profile_type, configs["HYPERVISOR"])

    @classmethod
    def create(cls, profile_type: str) -> ProfileDimensionWeight:
        return cls(weights=cls.get_weights(profile_type))


# ──────────────────────────────────────────────
# Reputation Subject (RFC-0041 §5)
# ──────────────────────────────────────────────
@dataclass
class ReputationSubject:
    subject_type: ReputationProfileType
    subject_id: str
    owner_reference: str | None = None
    hypervisor_reference: str | None = None
    service_role: str | None = None
    profile_version: str = "reputation.v1"


# ──────────────────────────────────────────────
# Dimension Accumulator (RFC-0041 §20-23)
# ──────────────────────────────────────────────
@dataclass
class ReputationDimensionAccumulator:
    """Evidence accumulator for one dimension.

    Maintains positive/negative evidence mass and derives
    RawScore, Confidence, and EffectiveScore per RFC-0041.
    """

    dimension: ReputationDimension
    positive_mass: float = 0.0
    negative_mass: float = 0.0
    event_count: int = 0

    @property
    def total_mass(self) -> float:
        return self.positive_mass + self.negative_mass

    @property
    def raw_score(self) -> float:
        """RawScore(d) per RFC-0041 §21.

        RawScore = (PriorPos + PosMass) / (PriorPos + PriorNeg + PosMass + NegMass)
        """
        total = PRIOR_POSITIVE_MASS + PRIOR_NEGATIVE_MASS + self.positive_mass + self.negative_mass
        if total <= 0:
            return PRIOR_SCORE
        return (PRIOR_POSITIVE_MASS + self.positive_mass) / total

    @property
    def confidence(self) -> float:
        """EvidenceConfidence(d) per RFC-0041 §22.

        Confidence = min(1, TotalMass / TargetMass)
        """
        return min(1.0, self.total_mass / TARGET_EVIDENCE_MASS)

    @property
    def effective_score(self) -> float:
        """EffectiveScore(d) per RFC-0041 §23.

        Effective = Prior + Confidence × (Raw − Prior)
        """
        return PRIOR_SCORE + self.confidence * (self.raw_score - PRIOR_SCORE)

    def add_mass(self, *, positive: float = 0.0, negative: float = 0.0) -> None:
        """Add evidence mass from a finalized event."""
        self.positive_mass += max(0.0, positive)
        self.negative_mass += max(0.0, negative)
        self.event_count += 1

    def to_score(self) -> ReputationDimensionScore:
        """Snapshot current accumulator state as a score."""
        return ReputationDimensionScore(
            dimension=self.dimension,
            raw_score=round(self.raw_score, 6),
            confidence=round(self.confidence, 6),
            effective_score=round(self.effective_score, 6),
            positive_mass=round(self.positive_mass, 6),
            negative_mass=round(self.negative_mass, 6),
            event_count=self.event_count,
            state=self._derive_state(),
        )

    def _derive_state(self) -> str:
        """Derive dimension state from confidence + score."""
        if self.confidence == 0.0:
            return "INSUFFICIENT_DATA"
        if self.confidence < 0.3:
            return "ESTABLISHING"
        if self.effective_score < 0.3:
            return "CRITICAL"
        if self.effective_score < 0.5:
            return "DEGRADED"
        if self.effective_score < 0.65:
            return "WATCH"
        return "NORMAL"


# ──────────────────────────────────────────────
# Dimension Score Snapshot (RFC-0041 §18)
# ──────────────────────────────────────────────
@dataclass
class ReputationDimensionScore:
    dimension: ReputationDimension
    raw_score: float = PRIOR_SCORE
    confidence: float = 0.0
    effective_score: float = PRIOR_SCORE
    positive_mass: float = 0.0
    negative_mass: float = 0.0
    event_count: int = 0
    state: ReputationProfileState = "INSUFFICIENT_DATA"


# ──────────────────────────────────────────────
# Reputation Profile (RFC-0041 §6-7)
# ──────────────────────────────────────────────
@dataclass
class ReputationProfile:
    """Structured Reputation Profile for one subject.

    Contains per-dimension accumulators, derived scores,
    advisory overall score, and profile state.
    """

    subject: ReputationSubject
    profile_type: ReputationProfileType
    accumulators: dict[str, ReputationDimensionAccumulator] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    profile_version: str = "reputation.v1"

    def __post_init__(self):
        # Initialize accumulators for all dimensions in the profile's weight config
        if not self.accumulators:
            weights = ProfileDimensionWeight.get_weights(self.profile_type)
            for dim in weights:
                self.accumulators[dim] = ReputationDimensionAccumulator(dimension=dim)

    @property
    def dimension_scores(self) -> list[ReputationDimensionScore]:
        """Current snapshot of all dimension scores."""
        return [acc.to_score() for acc in self.accumulators.values()]

    @property
    def advisory_overall_score(self) -> float:
        """Weighted advisory score per RFC-0041 §15.

        Overall = Σ(score × weight) / Σ(weight)
        Subject to critical dimension cap (§16).
        """
        weights = ProfileDimensionWeight.get_weights(self.profile_type)
        if not weights:
            return 0.0

        weighted_sum = 0.0
        weight_total = 0.0
        min_critical_score = 1.0

        for dim, acc in self.accumulators.items():
            w = weights.get(dim, 1.0)
            score = acc.effective_score
            weighted_sum += score * w
            weight_total += w

            # Track minimum critical dimension score
            if dim == "EVIDENCE_INTEGRITY":
                min_critical_score = min(min_critical_score, score)

        if weight_total <= 0:
            return 0.0

        overall = weighted_sum / weight_total

        # Critical dimension cap (RFC-0041 §16)
        # If Evidence Integrity is below 0.3, cap overall at that level
        if min_critical_score < 0.3:
            overall = min(overall, min_critical_score + 0.2)

        return round(min(1.0, max(0.0, overall)), 6)

    @property
    def state(self) -> ReputationProfileState:
        """Derive profile state from dimension states + overall score.

        Only considers dimensions that have evidence (event_count > 0).
        Dimensions with no evidence are ignored for state derivation.
        """
        scores = self.dimension_scores
        if not scores:
            return "INSUFFICIENT_DATA"

        # Only consider dimensions with evidence
        active = [s for s in scores if s.event_count > 0]
        if not active:
            return "INSUFFICIENT_DATA"

        avg_confidence = sum(s.confidence for s in active) / len(active)

        if avg_confidence < 0.1:
            return "INSUFFICIENT_DATA"
        if avg_confidence < 0.3:
            return "ESTABLISHING"

        # Check for critical dimensions
        critical_dims = [s for s in active if s.state == "CRITICAL"]
        if len(critical_dims) >= 2:
            return "CRITICAL"
        if len(critical_dims) == 1:
            return "DEGRADED"

        degraded_dims = [s for s in active if s.state == "DEGRADED"]
        if len(degraded_dims) >= 2:
            return "DEGRADED"
        if len(degraded_dims) == 1:
            return "WATCH"

        if self.advisory_overall_score >= 0.65:
            return "NORMAL"

        return "WATCH"

    @property
    def tier(self) -> str:
        """Advisory tier label (A/B/C/D/unrated)."""
        score = self.advisory_overall_score
        if score <= 0.0:
            return "unrated"
        if score >= 0.9:
            return "A"
        if score >= 0.75:
            return "B"
        if score >= 0.5:
            return "C"
        return "D"

    def add_event(self, event: ReputationEvent) -> None:
        """Ingest a finalized ReputationEvent into the profile."""
        dim = event.profile_dimension
        acc = self.accumulators.get(dim)
        if acc is None:
            acc = ReputationDimensionAccumulator(dimension=dim)
            self.accumulators[dim] = acc

        # Calculate event mass (RFC-0041 §36)
        base_weight = SEVERITY_WEIGHTS.get(event.severity, 0.1)
        conf_factor = CONFIDENCE_FACTORS.get(event.evidence_confidence, 0.1)
        event_mass = base_weight * conf_factor

        if event.direction == "POSITIVE":
            acc.add_mass(positive=event_mass)
        elif event.direction == "NEGATIVE":
            acc.add_mass(negative=event_mass)
        # NEUTRAL events only increment event_count (handled by add_mass call)
        elif event.direction == "NEUTRAL":
            acc.event_count += 1

        self.last_updated_at = datetime.now(UTC).isoformat()


# ──────────────────────────────────────────────
# Reputation Event (RFC-0041 §24)
# ──────────────────────────────────────────────
@dataclass
class ReputationEvent:
    """A finalized Reputation Event that changes score.

    All score changes originate from finalized ReputationEvents.
    """

    subject_type: ReputationProfileType
    subject_id: str
    profile_dimension: ReputationDimension
    event_class: ReputationEventClass
    direction: ReputationEventDirection
    severity: ReputationEventSeverity
    evidence_confidence: EvidenceConfidenceClass
    source_type: str | None = None
    source_reference: str | None = None
    evidence_root: str | None = None
    observed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    event_id: str = field(default_factory=lambda: f"rep-{uuid.uuid4().hex[:12]}")
    event_version: str = "reputation.v1"
