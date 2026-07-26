"""M11-S1: Rating Scorer — Bayesian dimension scoring with evidence accumulation."""

from __future__ import annotations

import math
from typing import Any

from aidn_hypervisor.rating.models import (
    DimensionScore,
    NodeRating,
    RatingConfig,
    RatingDimension,
    RatingEvidence,
    RatingUpdateResult,
)


# ── Direction mapping ────────────────────────────────────────────────

# Dimensions where higher evidence value = worse rating
# Note: LATENCY is NOT here because the engine normalizes latency
# so that higher evidence values = better (low raw latency → high value).
# Only DISPUTE_HISTORY needs flipping since the engine sends raw
# "was there a dispute" values (1.0 = dispute occurred).
_NEGATIVE_DIMENSIONS = {
    RatingDimension.DISPUTE_HISTORY,  # high disputes = bad
}


def _is_negative_dimension(dim: RatingDimension) -> bool:
    """Return True if higher evidence values degrade the score."""
    return dim in _NEGATIVE_DIMENSIONS


# ── Bayesian helpers ─────────────────────────────────────────────────


def _bayesian_update(
    prior: float,
    prior_weight: int,
    evidence_value: float,
    evidence_weight: float,
) -> tuple[float, int]:
    """Perform a Bayesian weighted update.

    Returns (new_mean, new_effective_weight).

    Uses a precision-weighted average:
        new_mean = (prior * prior_weight + evidence * ew) / (prior_weight + ew)
        new_weight = prior_weight + ew

    where ew = evidence_weight * confidence_boost.
    """
    ew = max(evidence_weight, 0.01)
    new_weight = prior_weight + ew
    if new_weight == 0:
        return prior, prior_weight
    new_mean = (prior * prior_weight + evidence_value * ew) / new_weight
    return new_mean, new_weight


def _compute_confidence(evidence_count: int, max_confidence: float = 0.99) -> float:
    """Compute confidence from evidence count using a sigmoid-like curve.

    More evidence → higher confidence, asymptoting at max_confidence.
    """
    if evidence_count == 0:
        return 0.0
    # Logistic growth: confidence approaches max_confidence
    k = 0.5  # growth rate
    midpoint = 10  # evidence count at half-max
    confidence = max_confidence / (1.0 + math.exp(-k * (evidence_count - midpoint)))
    return min(confidence, max_confidence)


def _apply_decay(score: float, epochs_since_update: int, decay_rate: float) -> float:
    """Apply temporal decay to a score, pulling toward neutral (0.5).

    score_new = score + (0.5 - score) * (1 - (1 - decay_rate)^epochs)
    """
    if epochs_since_update <= 0 or decay_rate <= 0.0:
        return score
    decay_factor = 1.0 - (1.0 - decay_rate) ** epochs_since_update
    neutral = 0.5
    new_score = score + (neutral - score) * decay_factor
    return max(0.0, min(1.0, new_score))


def _clamp_delta(score: float, new_score: float, max_delta: float) -> float:
    """Limit score change to max_delta per update."""
    delta = new_score - score
    if abs(delta) > max_delta:
        return score + max_delta if delta > 0 else score - max_delta
    return new_score


# ── Rating Scorer ────────────────────────────────────────────────────


class RatingScorer:
    """Scores node ratings using Bayesian evidence accumulation.

    Each dimension maintains:
    - a score (0.0-1.0)
    - an effective evidence weight (confidence proxy)
    - a raw evidence count

    Updates use precision-weighted averages (Bayesian-style),
    with temporal decay and per-epoch delta clamping.
    """

    def __init__(self, config: RatingConfig | None = None) -> None:
        self.config = config or RatingConfig()
        # Per-node, per-dimension state
        self._scores: dict[str, dict[RatingDimension, float]] = {}
        self._weights: dict[str, dict[RatingDimension, float]] = {}
        self._counts: dict[str, dict[RatingDimension, int]] = {}
        self._epochs: dict[str, dict[RatingDimension, int]] = {}

    # ── Single evidence update ─────────────────────────────────────

    def ingest_evidence(
        self, evidence: RatingEvidence
    ) -> RatingUpdateResult:
        """Ingest a single piece of rating evidence.

        Returns a RatingUpdateResult describing the score change.
        """
        node_id = evidence.node_id
        dim = evidence.dimension

        # Ensure state exists
        self._ensure_state(node_id, dim)

        # Get current state
        old_score = self._scores[node_id][dim]
        prior_weight = self._weights[node_id][dim]
        evidence_count = self._counts[node_id][dim]

        # Flip value for negative dimensions (high latency → low score)
        effective_value = (
            1.0 - evidence.value if _is_negative_dimension(dim) else evidence.value
        )

        # Bayesian update
        new_score, new_weight = _bayesian_update(
            old_score, prior_weight, effective_value, evidence.weight
        )

        # Clamp delta
        new_score = _clamp_delta(old_score, new_score, self.config.max_score_change_per_epoch)

        # Update state
        self._scores[node_id][dim] = new_score
        self._weights[node_id][dim] = new_weight
        self._counts[node_id][dim] = evidence_count + 1
        self._epochs[node_id][dim] = evidence.epoch

        return RatingUpdateResult(
            node_id=node_id,
            dimension=dim,
            old_score=round(old_score, 6),
            new_score=round(new_score, 6),
            delta=round(new_score - old_score, 6),
            evidence_count=evidence_count + 1,
            confidence=round(_compute_confidence(evidence_count + 1), 4),
            epoch=evidence.epoch,
        )

    # ── Bulk ingest ────────────────────────────────────────────────

    def ingest_batch(
        self, evidence_list: list[RatingEvidence]
    ) -> list[RatingUpdateResult]:
        """Ingest multiple pieces of evidence, returning results."""
        results: list[RatingUpdateResult] = []
        for ev in evidence_list:
            results.append(self.ingest_evidence(ev))
        return results

    # ── Score query ────────────────────────────────────────────────

    def get_dimension_score(
        self, node_id: str, dim: RatingDimension
    ) -> DimensionScore | None:
        """Get the current score for a specific dimension."""
        if node_id not in self._scores or dim not in self._scores[node_id]:
            return None

        score = self._scores[node_id][dim]
        count = self._counts[node_id][dim]
        epoch = self._epochs[node_id][dim]

        return DimensionScore(
            dimension=dim,
            score=round(score, 6),
            evidence_count=count,
            confidence=round(_compute_confidence(count), 4),
            last_updated_epoch=epoch,
        )

    def get_all_dimension_scores(self, node_id: str) -> dict[str, DimensionScore]:
        """Get all dimension scores for a node."""
        if node_id not in self._scores:
            return {}

        result: dict[str, DimensionScore] = {}
        for dim in RatingDimension:
            ds = self.get_dimension_score(node_id, dim)
            if ds is not None:
                result[dim.value] = ds
        return result

    # ── Composite score ────────────────────────────────────────────

    def compute_composite_score(self, node_id: str) -> float:
        """Compute the weighted composite score across all dimensions.

        Uses configured dimension weights. Dimensions with no evidence
        contribute zero (not the prior), to avoid rewarding empty dimensions.
        """
        dims = self.get_all_dimension_scores(node_id)
        if not dims:
            return 0.0

        total_weight = 0.0
        weighted_sum = 0.0

        for dim in RatingDimension:
            dim_key = dim.value
            dim_weight = self.config.dimension_weights.get(dim_key, 0.0)
            ds = dims.get(dim_key)

            if ds is not None:
                weighted_sum += ds.score * dim_weight
                total_weight += dim_weight

        if total_weight == 0:
            return 0.0

        # Normalize by total weight of dimensions that have evidence
        return min(1.0, max(0.0, weighted_sum / total_weight))

    # ── Full NodeRating construction ───────────────────────────────

    def build_node_rating(
        self,
        node_id: str,
        *,
        current_epoch: int,
        timestamp: str,
        maturity_epochs: int = 0,
    ) -> NodeRating | None:
        """Build a complete NodeRating for a node.

        Applies temporal decay before computing the composite score.
        """
        dims = self.get_all_dimension_scores(node_id)
        if not dims:
            return None

        # Apply decay to each dimension
        decayed_dims: dict[str, DimensionScore] = {}
        for dim_key, ds in dims.items():
            epochs_since = current_epoch - ds.last_updated_epoch
            decayed_score = _apply_decay(
                ds.score, epochs_since, self.config.evidence_decay_per_epoch
            )
            decayed_dims[dim_key] = ds.model_copy(
                update={"score": round(decayed_score, 6)}
            )

        composite = self._compute_composite_from_dims(decayed_dims)
        total_count = sum(ds.evidence_count for ds in decayed_dims.values())

        return NodeRating(
            node_id=node_id,
            dimensions=decayed_dims,
            composite_score=round(composite, 6),
            total_evidence_count=total_count,
            last_updated_epoch=current_epoch,
            last_updated_at=timestamp,
            maturity_epochs=maturity_epochs,
        )

    # ── Decay + composite helper ───────────────────────────────────

    def _compute_composite_from_dims(
        self, dims: dict[str, DimensionScore]
    ) -> float:
        """Compute composite score from a dict of DimensionScores."""
        total_weight = 0.0
        weighted_sum = 0.0

        for dim_key, ds in dims.items():
            dim_weight = self.config.dimension_weights.get(dim_key, 0.0)
            weighted_sum += ds.score * dim_weight
            total_weight += dim_weight

        if total_weight == 0:
            return 0.0

        return min(1.0, max(0.0, weighted_sum / total_weight))

    # ── Internal state helpers ─────────────────────────────────────

    def _ensure_state(self, node_id: str, dim: RatingDimension) -> None:
        """Ensure internal state dicts have entries for this node+dim."""
        if node_id not in self._scores:
            self._scores[node_id] = {}
            self._weights[node_id] = {}
            self._counts[node_id] = {}
            self._epochs[node_id] = {}

        if dim not in self._scores[node_id]:
            self._scores[node_id][dim] = self.config.prior_confidence
            self._weights[node_id][dim] = 0.0
            self._counts[node_id][dim] = 0
            self._epochs[node_id][dim] = 0

    # ── Reset / bulk ops ───────────────────────────────────────────

    def reset_node(self, node_id: str) -> None:
        """Remove all rating state for a node."""
        self._scores.pop(node_id, None)
        self._weights.pop(node_id, None)
        self._counts.pop(node_id, None)
        self._epochs.pop(node_id, None)

    def has_node(self, node_id: str) -> bool:
        """Check if a node has any rating state."""
        return node_id in self._scores

    def get_known_nodes(self) -> list[str]:
        """Return all node IDs with rating state."""
        return list(self._scores.keys())
