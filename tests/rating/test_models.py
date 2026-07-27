"""M11-S1: Rating models tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aidn_hypervisor.rating.models import (
    RatingDimension,
    RatingEvidence,
    RatingEvidenceType,
    DimensionScore,
    NodeRating,
    RatingConfig,
    RatingUpdateResult,
)


# ── RatingDimension ──────────────────────────────────────────────────


class TestRatingDimension:
    def test_all_dimensions_exist(self) -> None:
        assert len(RatingDimension) == 5
        assert RatingDimension.UPTIME.value == "uptime"
        assert RatingDimension.SUCCESS_RATE.value == "success_rate"
        assert RatingDimension.LATENCY.value == "latency"
        assert RatingDimension.DISPUTE_HISTORY.value == "dispute_history"
        assert RatingDimension.REPUTATION.value == "reputation"

    def test_dimension_is_string_enum(self) -> None:
        assert isinstance(RatingDimension.UPTIME, str)


# ── RatingEvidenceType ──────────────────────────────────────────────


class TestRatingEvidenceType:
    def test_all_evidence_types_exist(self) -> None:
        assert len(RatingEvidenceType) == 7
        assert RatingEvidenceType.SESSION_COMPLETION.value == "session_completion"
        assert RatingEvidenceType.VALIDATION_REPORT.value == "validation_report"
        assert RatingEvidenceType.HEARTBEAT.value == "heartbeat"


# ── RatingEvidence ──────────────────────────────────────────────────


class TestRatingEvidence:
    def test_create_evidence(self) -> None:
        ev = RatingEvidence(
            node_id="node-1",
            dimension=RatingDimension.UPTIME,
            evidence_type=RatingEvidenceType.HEARTBEAT,
            value=0.95,
            weight=0.8,
            epoch=1,
            timestamp="2026-01-01T00:00:00Z",
        )
        assert ev.node_id == "node-1"
        assert ev.dimension == RatingDimension.UPTIME
        assert ev.value == 0.95
        assert ev.weight == 0.8

    def test_evidence_is_frozen(self) -> None:
        ev = RatingEvidence(
            node_id="node-1",
            dimension=RatingDimension.UPTIME,
            evidence_type=RatingEvidenceType.HEARTBEAT,
            value=0.95,
            weight=0.5,
            epoch=1,
            timestamp="2026-01-01T00:00:00Z",
        )
        with pytest.raises(Exception):
            ev.value = 0.5  # type: ignore

    def test_evidence_value_must_be_in_range(self) -> None:
        with pytest.raises(ValidationError):
            RatingEvidence(
                node_id="node-1",
                dimension=RatingDimension.UPTIME,
                evidence_type=RatingEvidenceType.HEARTBEAT,
                value=1.5,
                weight=0.5,
                epoch=1,
                timestamp="2026-01-01T00:00:00Z",
            )

    def test_evidence_value_zero_is_valid(self) -> None:
        ev = RatingEvidence(
            node_id="node-1",
            dimension=RatingDimension.UPTIME,
            evidence_type=RatingEvidenceType.HEARTBEAT,
            value=0.0,
            weight=0.5,
            epoch=1,
            timestamp="2026-01-01T00:00:00Z",
        )
        assert ev.value == 0.0

    def test_evidence_value_one_is_valid(self) -> None:
        ev = RatingEvidence(
            node_id="node-1",
            dimension=RatingDimension.UPTIME,
            evidence_type=RatingEvidenceType.HEARTBEAT,
            value=1.0,
            weight=0.5,
            epoch=1,
            timestamp="2026-01-01T00:00:00Z",
        )
        assert ev.value == 1.0

    def test_evidence_weight_must_be_at_least_0_01(self) -> None:
        with pytest.raises(ValidationError):
            RatingEvidence(
                node_id="node-1",
                dimension=RatingDimension.UPTIME,
                evidence_type=RatingEvidenceType.HEARTBEAT,
                value=0.5,
                weight=0.0,
                epoch=1,
                timestamp="2026-01-01T00:00:00Z",
            )

    def test_evidence_id_is_deterministic(self) -> None:
        ev1 = RatingEvidence(
            node_id="node-1",
            dimension=RatingDimension.UPTIME,
            evidence_type=RatingEvidenceType.HEARTBEAT,
            value=0.95,
            weight=0.8,
            epoch=1,
            timestamp="2026-01-01T00:00:00Z",
        )
        ev2 = RatingEvidence(
            node_id="node-1",
            dimension=RatingDimension.UPTIME,
            evidence_type=RatingEvidenceType.HEARTBEAT,
            value=0.95,
            weight=0.8,
            epoch=1,
            timestamp="2026-01-01T00:00:00Z",
        )
        assert ev1.evidence_id == ev2.evidence_id
        assert len(ev1.evidence_id) == 16

    def test_evidence_id_differs_for_different_epochs(self) -> None:
        ev1 = RatingEvidence(
            node_id="node-1",
            dimension=RatingDimension.UPTIME,
            evidence_type=RatingEvidenceType.HEARTBEAT,
            value=0.95,
            weight=0.8,
            epoch=1,
            timestamp="2026-01-01T00:00:00Z",
        )
        ev2 = RatingEvidence(
            node_id="node-1",
            dimension=RatingDimension.UPTIME,
            evidence_type=RatingEvidenceType.HEARTBEAT,
            value=0.95,
            weight=0.8,
            epoch=2,
            timestamp="2026-01-01T00:00:00Z",
        )
        assert ev1.evidence_id != ev2.evidence_id

    def test_evidence_with_optional_source(self) -> None:
        ev = RatingEvidence(
            node_id="node-1",
            dimension=RatingDimension.UPTIME,
            evidence_type=RatingEvidenceType.HEARTBEAT,
            value=0.95,
            weight=0.8,
            epoch=1,
            timestamp="2026-01-01T00:00:00Z",
            source="heartbeat-monitor",
        )
        assert ev.source == "heartbeat-monitor"


# ── DimensionScore ───────────────────────────────────────────────────


class TestDimensionScore:
    def test_create_dimension_score(self) -> None:
        ds = DimensionScore(
            dimension=RatingDimension.UPTIME,
            score=0.85,
            evidence_count=10,
            confidence=0.75,
            last_updated_epoch=5,
        )
        assert ds.dimension == RatingDimension.UPTIME
        assert ds.score == 0.85
        assert ds.evidence_count == 10

    def test_dimension_score_is_frozen(self) -> None:
        ds = DimensionScore(
            dimension=RatingDimension.UPTIME,
            score=0.85,
            evidence_count=10,
        )
        with pytest.raises(Exception):
            ds.score = 0.5  # type: ignore

    def test_dimension_score_defaults(self) -> None:
        ds = DimensionScore(dimension=RatingDimension.UPTIME, score=0.5)
        assert ds.evidence_count == 0
        assert ds.confidence == 0.0
        assert ds.last_updated_epoch == 0


# ── NodeRating ───────────────────────────────────────────────────────


class TestNodeRating:
    def _make_rating(
        self,
        composite: float = 0.7,
        evidence_count: int = 10,
        dims: dict[str, DimensionScore] | None = None,
    ) -> NodeRating:
        if dims is None:
            dims = {
                "uptime": DimensionScore(
                    dimension=RatingDimension.UPTIME,
                    score=0.85,
                    evidence_count=5,
                    confidence=0.7,
                    last_updated_epoch=5,
                ),
                "success_rate": DimensionScore(
                    dimension=RatingDimension.SUCCESS_RATE,
                    score=0.90,
                    evidence_count=8,
                    confidence=0.8,
                    last_updated_epoch=5,
                ),
            }
        return NodeRating(
            node_id="node-1",
            dimensions=dims,
            composite_score=composite,
            total_evidence_count=evidence_count,
            last_updated_epoch=5,
            last_updated_at="2026-01-01T00:00:00Z",
            maturity_epochs=3,
        )

    def test_create_node_rating(self) -> None:
        rating = self._make_rating()
        assert rating.node_id == "node-1"
        assert rating.composite_score == 0.7
        assert rating.total_evidence_count == 10

    def test_is_established_when_enough_evidence(self) -> None:
        rating = self._make_rating(composite=0.7, evidence_count=10)
        assert rating.is_established is True

    def test_is_not_established_when_low_evidence(self) -> None:
        rating = self._make_rating(composite=0.7, evidence_count=2)
        assert rating.is_established is False

    def test_is_not_established_when_low_score(self) -> None:
        rating = self._make_rating(composite=0.3, evidence_count=10)
        assert rating.is_established is False

    def test_get_dimension(self) -> None:
        rating = self._make_rating()
        ds = rating.get_dimension(RatingDimension.UPTIME)
        assert ds is not None
        assert ds.score == 0.85

    def test_get_missing_dimension(self) -> None:
        rating = self._make_rating()
        ds = rating.get_dimension(RatingDimension.REPUTATION)
        assert ds is None

    def test_node_rating_is_frozen(self) -> None:
        rating = self._make_rating()
        with pytest.raises(Exception):
            rating.composite_score = 0.5  # type: ignore

    def test_maturity_epochs(self) -> None:
        rating = self._make_rating()
        assert rating.maturity_epochs == 3


# ── RatingConfig ────────────────────────────────────────────────────


class TestRatingConfig:
    def test_default_weights_sum_to_one(self) -> None:
        config = RatingConfig()
        total = sum(config.dimension_weights.values())
        assert abs(total - 1.0) < 0.001

    def test_default_prior_confidence(self) -> None:
        config = RatingConfig()
        assert config.prior_confidence == 0.5

    def test_default_decay(self) -> None:
        config = RatingConfig()
        assert config.evidence_decay_per_epoch == 0.05

    def test_custom_weights(self) -> None:
        weights = {
            "uptime": 0.4,
            "success_rate": 0.3,
            "latency": 0.1,
            "dispute_history": 0.1,
            "reputation": 0.1,
        }
        config = RatingConfig(dimension_weights=weights)
        assert config.dimension_weights == weights

    def test_config_is_frozen(self) -> None:
        config = RatingConfig()
        with pytest.raises(Exception):
            config.prior_confidence = 0.3  # type: ignore


# ── RatingUpdateResult ──────────────────────────────────────────────


class TestRatingUpdateResult:
    def test_create_update_result(self) -> None:
        result = RatingUpdateResult(
            node_id="node-1",
            dimension=RatingDimension.UPTIME,
            old_score=0.7,
            new_score=0.75,
            delta=0.05,
            evidence_count=10,
            confidence=0.8,
            epoch=5,
        )
        assert result.delta == 0.05
        assert result.new_score == 0.75

    def test_negative_delta(self) -> None:
        result = RatingUpdateResult(
            node_id="node-1",
            dimension=RatingDimension.UPTIME,
            old_score=0.7,
            new_score=0.65,
            delta=-0.05,
            evidence_count=10,
            confidence=0.8,
            epoch=5,
        )
        assert result.delta == -0.05

    def test_update_result_is_frozen(self) -> None:
        result = RatingUpdateResult(
            node_id="node-1",
            dimension=RatingDimension.UPTIME,
            old_score=0.7,
            new_score=0.75,
            delta=0.05,
            evidence_count=10,
            confidence=0.8,
            epoch=5,
        )
        with pytest.raises(Exception):
            result.new_score = 0.5  # type: ignore
