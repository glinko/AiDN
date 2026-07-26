"""M11-S1: Rating Scorer tests."""

from __future__ import annotations

import pytest

from aidn_hypervisor.rating.models import (
    DimensionScore,
    NodeRating,
    RatingConfig,
    RatingDimension,
    RatingEvidence,
    RatingEvidenceType,
)
from aidn_hypervisor.rating.scoring import (
    RatingScorer,
    _bayesian_update,
    _compute_confidence,
    _apply_decay,
    _is_negative_dimension,
)


# ── Bayesian helpers ─────────────────────────────────────────────────


class TestBayesianUpdate:
    def test_single_evidence_moves_toward_value(self) -> None:
        mean, weight = _bayesian_update(prior=0.5, prior_weight=0, evidence_value=0.9, evidence_weight=1.0)
        assert mean > 0.5
        assert mean < 0.95  # not exactly 0.9 because of prior_weight=0

    def test_high_weight_evidence_dominates(self) -> None:
        mean, weight = _bayesian_update(prior=0.5, prior_weight=1.0, evidence_value=0.9, evidence_weight=10.0)
        assert mean > 0.8

    def test_low_weight_evidence_has_little_effect(self) -> None:
        mean, weight = _bayesian_update(prior=0.5, prior_weight=10.0, evidence_value=0.9, evidence_weight=0.01)
        assert abs(mean - 0.5) < 0.01

    def test_weight_accumulates(self) -> None:
        _, w1 = _bayesian_update(prior=0.5, prior_weight=0, evidence_value=0.8, evidence_weight=1.0)
        _, w2 = _bayesian_update(prior=0.5, prior_weight=w1, evidence_value=0.8, evidence_weight=1.0)
        assert w2 > w1

    def test_converges_with_repeated_evidence(self) -> None:
        mean = 0.5
        weight = 0.0
        for _ in range(20):
            mean, weight = _bayesian_update(prior=mean, prior_weight=weight, evidence_value=0.9, evidence_weight=1.0)
        assert mean > 0.85


class TestComputeConfidence:
    def test_zero_evidence_gives_zero_confidence(self) -> None:
        assert _compute_confidence(0) == 0.0

    def test_confidence_increases_with_evidence(self) -> None:
        c1 = _compute_confidence(1)
        c10 = _compute_confidence(10)
        c50 = _compute_confidence(50)
        assert c1 < c10 < c50

    def test_confidence_caps_at_max(self) -> None:
        c = _compute_confidence(1000)
        assert c <= 0.99

    def test_confidence_is_positive_for_any_evidence(self) -> None:
        assert _compute_confidence(1) > 0.0


class TestApplyDecay:
    def test_no_decay_when_zero_epochs(self) -> None:
        assert _apply_decay(0.8, 0, 0.05) == 0.8

    def test_no_decay_when_zero_rate(self) -> None:
        assert _apply_decay(0.8, 5, 0.0) == 0.8

    def test_decay_pulls_toward_neutral(self) -> None:
        result = _apply_decay(0.9, 10, 0.05)
        assert result < 0.9
        assert result > 0.5

    def test_low_score_decays_upward(self) -> None:
        result = _apply_decay(0.2, 10, 0.05)
        assert result > 0.2
        assert result < 0.5

    def test_neutral_score_unchanged(self) -> None:
        result = _apply_decay(0.5, 10, 0.05)
        assert abs(result - 0.5) < 0.001

    def test_decay_is_bounded(self) -> None:
        result = _apply_decay(0.0, 100, 0.05)
        assert result >= 0.0
        assert result <= 1.0


class TestNegativeDimension:
    def test_dispute_history_is_negative(self) -> None:
        assert _is_negative_dimension(RatingDimension.DISPUTE_HISTORY) is True

    def test_uptime_is_positive(self) -> None:
        assert _is_negative_dimension(RatingDimension.UPTIME) is False

    def test_success_rate_is_positive(self) -> None:
        assert _is_negative_dimension(RatingDimension.SUCCESS_RATE) is False

    def test_reputation_is_positive(self) -> None:
        assert _is_negative_dimension(RatingDimension.REPUTATION) is False

    def test_latency_is_positive(self) -> None:
        # Latency evidence is pre-normalized by the engine
        # (high value = low raw latency = good), so scoring treats it as positive.
        assert _is_negative_dimension(RatingDimension.LATENCY) is False


# ── RatingScorer ─────────────────────────────────────────────────────


class TestRatingScorer:
    def _make_evidence(
        self,
        node_id: str = "node-1",
        dim: RatingDimension = RatingDimension.UPTIME,
        value: float = 0.9,
        weight: float = 0.8,
        epoch: int = 1,
    ) -> RatingEvidence:
        return RatingEvidence(
            node_id=node_id,
            dimension=dim,
            evidence_type=RatingEvidenceType.HEARTBEAT,
            value=value,
            weight=weight,
            epoch=epoch,
            timestamp="2026-01-01T00:00:00Z",
        )

    # ── Evidence ingestion ───────────────────────────────────────

    def test_ingest_positive_evidence_increases_score(self) -> None:
        scorer = RatingScorer()
        result = scorer.ingest_evidence(self._make_evidence(value=0.95))
        assert result.new_score > result.old_score
        assert result.delta > 0

    def test_ingest_negative_evidence_decreases_positive_dim(self) -> None:
        scorer = RatingScorer()
        result = scorer.ingest_evidence(self._make_evidence(value=0.1))
        assert result.new_score < result.old_score
        assert result.delta < 0

    def test_high_latency_value_increases_score(self) -> None:
        # Latency evidence is pre-normalized by the engine:
        # high value = low raw latency = good.
        # Scoring treats it as a positive dimension.
        scorer = RatingScorer()
        ev = self._make_evidence(dim=RatingDimension.LATENCY, value=0.9)
        result = scorer.ingest_evidence(ev)
        assert result.new_score > result.old_score

    def test_low_latency_value_decreases_score(self) -> None:
        # Low normalized value = high raw latency = bad.
        scorer = RatingScorer()
        ev = self._make_evidence(dim=RatingDimension.LATENCY, value=0.1)
        result = scorer.ingest_evidence(ev)
        assert result.new_score < result.old_score

    def test_evidence_count_increments(self) -> None:
        scorer = RatingScorer()
        r1 = scorer.ingest_evidence(self._make_evidence(epoch=1))
        r2 = scorer.ingest_evidence(self._make_evidence(epoch=2))
        assert r2.evidence_count == r1.evidence_count + 1

    def test_score_clamped_to_range(self) -> None:
        scorer = RatingScorer()
        for i in range(100):
            scorer.ingest_evidence(self._make_evidence(value=1.0, epoch=i + 1))
        ds = scorer.get_dimension_score("node-1", RatingDimension.UPTIME)
        assert ds is not None
        assert 0.0 <= ds.score <= 1.0

    # ── Delta clamping ───────────────────────────────────────────

    def test_delta_clamped_per_update(self) -> None:
        config = RatingConfig(max_score_change_per_epoch=0.10)
        scorer = RatingScorer(config=config)
        result = scorer.ingest_evidence(self._make_evidence(value=1.0))
        assert abs(result.delta) <= 0.10 + 1e-9

    # ── Dimension queries ────────────────────────────────────────

    def test_get_dimension_score_after_ingest(self) -> None:
        scorer = RatingScorer()
        scorer.ingest_evidence(self._make_evidence(value=0.8))
        ds = scorer.get_dimension_score("node-1", RatingDimension.UPTIME)
        assert ds is not None
        assert ds.evidence_count == 1

    def test_get_missing_dimension_returns_none(self) -> None:
        scorer = RatingScorer()
        ds = scorer.get_dimension_score("node-1", RatingDimension.UPTIME)
        assert ds is None

    def test_get_all_dimensions(self) -> None:
        scorer = RatingScorer()
        scorer.ingest_evidence(self._make_evidence(dim=RatingDimension.UPTIME, value=0.8))
        scorer.ingest_evidence(self._make_evidence(dim=RatingDimension.SUCCESS_RATE, value=0.9))
        dims = scorer.get_all_dimension_scores("node-1")
        assert len(dims) == 2
        assert "uptime" in dims
        assert "success_rate" in dims

    # ── Composite score ─────────────────────────────────────────

    def test_composite_score_with_single_dimension(self) -> None:
        scorer = RatingScorer()
        scorer.ingest_evidence(self._make_evidence(value=0.8))
        composite = scorer.compute_composite_score("node-1")
        assert composite > 0.0
        assert composite <= 1.0

    def test_composite_score_weighted(self) -> None:
        scorer = RatingScorer()
        scorer.ingest_evidence(self._make_evidence(dim=RatingDimension.UPTIME, value=1.0))
        scorer.ingest_evidence(self._make_evidence(dim=RatingDimension.SUCCESS_RATE, value=0.0))
        composite = scorer.compute_composite_score("node-1")
        # uptime=1.0 (weight 0.25), success_rate=0.0 (weight 0.25)
        # composite = (1.0*0.25 + 0.0*0.25) / (0.25+0.25) = 0.5
        assert abs(composite - 0.5) < 0.01

    def test_composite_zero_for_unknown_node(self) -> None:
        scorer = RatingScorer()
        assert scorer.compute_composite_score("unknown") == 0.0

    # ── NodeRating construction ─────────────────────────────────

    def test_build_node_rating(self) -> None:
        scorer = RatingScorer()
        scorer.ingest_evidence(self._make_evidence(value=0.8))
        rating = scorer.build_node_rating("node-1", current_epoch=1, timestamp="2026-01-01T00:00:00Z")
        assert rating is not None
        assert rating.node_id == "node-1"
        assert rating.composite_score > 0.0

    def test_build_node_rating_returns_none_for_unknown(self) -> None:
        scorer = RatingScorer()
        rating = scorer.build_node_rating("unknown", current_epoch=1, timestamp="2026-01-01T00:00:00Z")
        assert rating is None

    def test_build_node_rating_applies_decay(self) -> None:
        scorer = RatingScorer()
        scorer.ingest_evidence(self._make_evidence(value=0.9, epoch=1))
        rating_now = scorer.build_node_rating("node-1", current_epoch=1, timestamp="2026-01-01T00:00:00Z")
        rating_later = scorer.build_node_rating("node-1", current_epoch=10, timestamp="2026-01-10T00:00:00Z")
        assert rating_now is not None and rating_later is not None
        assert rating_later.composite_score < rating_now.composite_score

    # ── Multi-node isolation ────────────────────────────────────

    def test_different_nodes_independent(self) -> None:
        scorer = RatingScorer()
        scorer.ingest_evidence(self._make_evidence(node_id="a", value=0.9))
        scorer.ingest_evidence(self._make_evidence(node_id="b", value=0.1))
        da = scorer.get_dimension_score("a", RatingDimension.UPTIME)
        db = scorer.get_dimension_score("b", RatingDimension.UPTIME)
        assert da is not None and db is not None
        assert da.score > db.score

    # ── Reset ───────────────────────────────────────────────────

    def test_reset_node(self) -> None:
        scorer = RatingScorer()
        scorer.ingest_evidence(self._make_evidence(value=0.8))
        scorer.reset_node("node-1")
        assert not scorer.has_node("node-1")
        assert scorer.get_dimension_score("node-1", RatingDimension.UPTIME) is None

    # ── Known nodes ─────────────────────────────────────────────

    def test_get_known_nodes(self) -> None:
        scorer = RatingScorer()
        scorer.ingest_evidence(self._make_evidence(node_id="a", value=0.8))
        scorer.ingest_evidence(self._make_evidence(node_id="b", value=0.6))
        nodes = scorer.get_known_nodes()
        assert set(nodes) == {"a", "b"}

    # ── Batch ingest ───────────────────────────────────────────

    def test_ingest_batch(self) -> None:
        scorer = RatingScorer()
        evidences = [
            self._make_evidence(epoch=1, value=0.8),
            self._make_evidence(epoch=2, value=0.9),
            self._make_evidence(epoch=3, value=0.7),
        ]
        results = scorer.ingest_batch(evidences)
        assert len(results) == 3
        ds = scorer.get_dimension_score("node-1", RatingDimension.UPTIME)
        assert ds is not None
        assert ds.evidence_count == 3

    # ── Confidence growth ───────────────────────────────────────

    def test_confidence_grows_with_evidence(self) -> None:
        scorer = RatingScorer()
        for i in range(20):
            scorer.ingest_evidence(self._make_evidence(epoch=i + 1, value=0.8))
        ds = scorer.get_dimension_score("node-1", RatingDimension.UPTIME)
        assert ds is not None
        assert ds.confidence > 0.5

    # ── Multiple dimensions ─────────────────────────────────────

    def test_multiple_dimensions_independent(self) -> None:
        scorer = RatingScorer()
        scorer.ingest_evidence(self._make_evidence(dim=RatingDimension.UPTIME, value=0.9))
        scorer.ingest_evidence(self._make_evidence(dim=RatingDimension.SUCCESS_RATE, value=0.5))
        uptime = scorer.get_dimension_score("node-1", RatingDimension.UPTIME)
        sr = scorer.get_dimension_score("node-1", RatingDimension.SUCCESS_RATE)
        assert uptime is not None and sr is not None
        assert uptime.score > sr.score

    # ── Custom config ───────────────────────────────────────────

    def test_custom_dimension_weights(self) -> None:
        weights = {
            "uptime": 0.5,
            "success_rate": 0.5,
            "latency": 0.0,
            "dispute_history": 0.0,
            "reputation": 0.0,
        }
        config = RatingConfig(dimension_weights=weights)
        scorer = RatingScorer(config=config)
        scorer.ingest_evidence(self._make_evidence(dim=RatingDimension.UPTIME, value=1.0))
        scorer.ingest_evidence(self._make_evidence(dim=RatingDimension.SUCCESS_RATE, value=0.0))
        composite = scorer.compute_composite_score("node-1")
        assert abs(composite - 0.5) < 0.01

    def test_no_decay_config(self) -> None:
        config = RatingConfig(evidence_decay_per_epoch=0.0)
        scorer = RatingScorer(config=config)
        scorer.ingest_evidence(self._make_evidence(value=0.9, epoch=1))
        rating_now = scorer.build_node_rating("node-1", current_epoch=1, timestamp="T1")
        rating_later = scorer.build_node_rating("node-1", current_epoch=100, timestamp="T2")
        assert rating_now is not None and rating_later is not None
        assert abs(rating_now.composite_score - rating_later.composite_score) < 0.001
