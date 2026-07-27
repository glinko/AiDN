"""M11-S1: Rating models — node rating with independent dimensions."""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, Field


# ── Enumerations ─────────────────────────────────────────────────────


class RatingDimension(str, Enum):
    """Independent rating dimensions (ECO-0004 §14-§17)."""

    UPTIME = "uptime"
    SUCCESS_RATE = "success_rate"
    LATENCY = "latency"
    DISPUTE_HISTORY = "dispute_history"
    REPUTATION = "reputation"


class RatingEvidenceType(str, Enum):
    """Source of rating evidence."""

    SESSION_COMPLETION = "session_completion"
    SESSION_FAILURE = "session_failure"
    VALIDATION_REPORT = "validation_report"
    HEARTBEAT = "heartbeat"
    CHALLENGE = "challenge"
    DUTY_PROOF = "duty_proof"
    REPUTATION_EVENT = "reputation_event"


class RatingDirection(str, Enum):
    """Whether higher evidence values improve or degrade the rating."""

    POSITIVE = "positive"  # higher = better
    NEGATIVE = "negative"  # higher = worse


# ── Evidence ─────────────────────────────────────────────────────────


class RatingEvidence(BaseModel, frozen=True):
    """A single piece of rating evidence for a node."""

    node_id: str
    dimension: RatingDimension
    evidence_type: RatingEvidenceType
    value: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.01, le=1.0, default=0.5)
    epoch: int
    timestamp: str
    source: str | None = None

    model_config = {"frozen": True}

    @property
    def evidence_id(self) -> str:
        """Deterministic ID for this evidence."""
        raw = f"{self.node_id}:{self.dimension.value}:{self.epoch}:{self.timestamp}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Node Rating ──────────────────────────────────────────────────────


class DimensionScore(BaseModel, frozen=True):
    """Score for a single dimension."""

    dimension: RatingDimension
    score: float = Field(ge=0.0, le=1.0)
    evidence_count: int = 0
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    last_updated_epoch: int = 0

    model_config = {"frozen": True}


class NodeRating(BaseModel, frozen=True):
    """Composite rating for a node across all dimensions."""

    node_id: str
    dimensions: dict[str, DimensionScore]  # dimension key -> score
    composite_score: float = Field(ge=0.0, le=1.0)
    total_evidence_count: int = 0
    last_updated_epoch: int = 0
    last_updated_at: str
    maturity_epochs: int = 0

    model_config = {"frozen": True}

    @property
    def is_established(self) -> bool:
        """Rating is established when composite confidence > 0.5."""
        return self.composite_score > 0.5 and self.total_evidence_count >= 5

    def get_dimension(self, dim: RatingDimension) -> DimensionScore | None:
        """Get score for a specific dimension."""
        return self.dimensions.get(dim.value)


# ── Configuration ────────────────────────────────────────────────────


class RatingConfig(BaseModel, frozen=True):
    """Rating engine configuration."""

    # Dimension weights for composite score
    dimension_weights: dict[str, float] = Field(
        default_factory=lambda: {
            RatingDimension.UPTIME.value: 0.25,
            RatingDimension.SUCCESS_RATE.value: 0.25,
            RatingDimension.LATENCY.value: 0.20,
            RatingDimension.DISPUTE_HISTORY.value: 0.15,
            RatingDimension.REPUTATION.value: 0.15,
        }
    )

    # Bayesian prior (starting confidence for new nodes)
    prior_confidence: float = 0.5

    # Evidence decay factor per epoch (0.0 = no decay, 1.0 = full decay)
    evidence_decay_per_epoch: float = 0.05

    # Minimum evidence count before rating is "established"
    minimum_evidence_count: int = 5

    # Confidence threshold for established rating
    established_threshold: float = 0.5

    # Maximum score change per epoch (prevents sudden swings)
    max_score_change_per_epoch: float = 0.10

    model_config = {"frozen": True}


# ── Scoring Result ───────────────────────────────────────────────────


class RatingUpdateResult(BaseModel, frozen=True):
    """Result of a rating update operation."""

    node_id: str
    dimension: RatingDimension
    old_score: float
    new_score: float
    delta: float
    evidence_count: int
    confidence: float
    epoch: int

    model_config = {"frozen": True}
