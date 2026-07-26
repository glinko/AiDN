"""M11-S1: Rating Engine tests."""

from __future__ import annotations

import pytest

from aidn_hypervisor.rating.models import (
    RatingConfig,
    RatingDimension,
)
from aidn_hypervisor.rating.engine import RatingEngine


# ── Session completion ─────────────────────────────────────────────


class TestSessionCompletion:
    def test_successful_session_increases_score(self) -> None:
        engine = RatingEngine()
        results = engine.ingest_session_completion(
            node_id="node-1", success=True, epoch=1, timestamp="T1"
        )
        assert len(results) >= 2  # success_rate + uptime
        assert engine.get_composite_score("node-1") > 0.0

    def test_failed_session_decreases_success_rate(self) -> None:
        engine = RatingEngine()
        # First establish a baseline
        engine.ingest_session_completion(
            node_id="node-1", success=True, epoch=1, timestamp="T1"
        )
        baseline_sr = engine.get_dimension_score(
            "node-1", RatingDimension.SUCCESS_RATE
        )
        # Then fail
        engine.ingest_session_completion(
            node_id="node-1", success=False, epoch=2, timestamp="T2"
        )
        after_sr = engine.get_dimension_score(
            "node-1", RatingDimension.SUCCESS_RATE
        )
        assert after_sr < baseline_sr

    def test_latency_included_when_provided(self) -> None:
        engine = RatingEngine()
        results = engine.ingest_session_completion(
            node_id="node-1", success=True, latency_seconds=5.0, epoch=1, timestamp="T1"
        )
        assert len(results) >= 3  # success_rate + uptime + latency

    def test_low_latency_better_than_high(self) -> None:
        engine = RatingEngine()
        engine.ingest_session_completion(
            node_id="node-a", success=True, latency_seconds=1.0, epoch=1, timestamp="T1"
        )
        engine.ingest_session_completion(
            node_id="node-b", success=True, latency_seconds=25.0, epoch=1, timestamp="T1"
        )
        # Compare latency dimension directly (lower raw latency → higher score)
        lat_a = engine.get_dimension_score("node-a", RatingDimension.LATENCY)
        lat_b = engine.get_dimension_score("node-b", RatingDimension.LATENCY)
        assert lat_a > lat_b

    def test_multiple_completions_improve_confidence(self) -> None:
        engine = RatingEngine()
        for i in range(10):
            engine.ingest_session_completion(
                node_id="node-1", success=True, epoch=i + 1, timestamp=f"T{i+1}"
            )
        rating = engine.get_rating("node-1", current_epoch=10, timestamp="T10")
        assert rating is not None
        assert rating.total_evidence_count >= 20  # 2 evidences per completion


# ── Session failure ─────────────────────────────────────────────────


class TestSessionFailure:
    def test_provider_fault_increases_dispute_history(self) -> None:
        engine = RatingEngine()
        engine.ingest_session_failure(
            node_id="node-1", attribution="PROVIDER_AT_FAULT", epoch=1, timestamp="T1"
        )
        dispute = engine.get_dimension_score("node-1", RatingDimension.DISPUTE_HISTORY)
        # Dispute history is a negative dimension — score should be > 0 (bad)
        assert dispute > 0.0

    def test_external_fault_no_dispute(self) -> None:
        engine = RatingEngine()
        engine.ingest_session_failure(
            node_id="node-1", attribution="EXTERNAL_FAILURE", epoch=1, timestamp="T1"
        )
        dispute = engine.get_dimension_score("node-1", RatingDimension.DISPUTE_HISTORY)
        assert dispute == 0.0

    def test_failure_decreases_success_rate(self) -> None:
        engine = RatingEngine()
        engine.ingest_session_completion(
            node_id="node-1", success=True, epoch=1, timestamp="T1"
        )
        baseline = engine.get_composite_score("node-1")
        engine.ingest_session_failure(
            node_id="node-1", attribution="PROVIDER_AT_FAULT", epoch=2, timestamp="T2"
        )
        assert engine.get_composite_score("node-1") < baseline


# ── Validation report ──────────────────────────────────────────────


class TestValidationReport:
    def test_certify_increases_reputation(self) -> None:
        engine = RatingEngine()
        engine.ingest_validation_report(
            node_id="node-1", recommendation="certify", confidence=0.9, epoch=1, timestamp="T1"
        )
        rep = engine.get_dimension_score("node-1", RatingDimension.REPUTATION)
        assert rep > 0.5

    def test_de_certify_decreases_reputation(self) -> None:
        engine = RatingEngine()
        engine.ingest_validation_report(
            node_id="node-1", recommendation="de_certify", confidence=0.9, epoch=1, timestamp="T1"
        )
        rep = engine.get_dimension_score("node-1", RatingDimension.REPUTATION)
        assert rep < 0.5

    def test_conditional_is_neutral(self) -> None:
        engine = RatingEngine()
        engine.ingest_validation_report(
            node_id="node-1", recommendation="conditional", confidence=0.9, epoch=1, timestamp="T1"
        )
        rep = engine.get_dimension_score("node-1", RatingDimension.REPUTATION)
        assert abs(rep - 0.5) < 0.15


# ── Heartbeat ──────────────────────────────────────────────────────


class TestHeartbeat:
    def test_healthy_heartbeat_increases_uptime(self) -> None:
        engine = RatingEngine()
        engine.ingest_heartbeat(
            node_id="node-1", healthy=True, epoch=1, timestamp="T1"
        )
        uptime = engine.get_dimension_score("node-1", RatingDimension.UPTIME)
        assert uptime > 0.5

    def test_unhealthy_heartbeat_decreases_uptime(self) -> None:
        engine = RatingEngine()
        engine.ingest_heartbeat(
            node_id="node-1", healthy=False, epoch=1, timestamp="T1"
        )
        uptime = engine.get_dimension_score("node-1", RatingDimension.UPTIME)
        assert uptime < 0.5


# ── Queries ────────────────────────────────────────────────────────


class TestQueries:
    def test_get_rating_builds_fresh(self) -> None:
        engine = RatingEngine()
        engine.ingest_session_completion(
            node_id="node-1", success=True, epoch=1, timestamp="T1"
        )
        rating = engine.get_rating("node-1", current_epoch=1, timestamp="T1")
        assert rating is not None
        assert rating.node_id == "node-1"

    def test_get_rating_returns_stored(self) -> None:
        engine = RatingEngine()
        engine.ingest_session_completion(
            node_id="node-1", success=True, epoch=1, timestamp="T1"
        )
        engine.get_rating("node-1", current_epoch=1, timestamp="T1")
        stored = engine.get_rating("node-1")
        assert stored is not None

    def test_get_all_ratings(self) -> None:
        engine = RatingEngine()
        engine.ingest_session_completion(
            node_id="a", success=True, epoch=1, timestamp="T1"
        )
        engine.ingest_session_completion(
            node_id="b", success=True, epoch=1, timestamp="T1"
        )
        ratings = engine.get_all_ratings(current_epoch=1, timestamp="T1")
        assert len(ratings) == 2

    def test_unknown_node_returns_none(self) -> None:
        engine = RatingEngine()
        assert engine.get_rating("unknown") is None
        assert engine.get_composite_score("unknown") == 0.0


# ── Epoch transitions ──────────────────────────────────────────────


class TestEpochTransitions:
    def test_epoch_transition_builds_ratings(self) -> None:
        engine = RatingEngine()
        engine.ingest_session_completion(
            node_id="node-1", success=True, epoch=1, timestamp="T1"
        )
        ratings = engine.on_epoch_transition(
            epoch=1, timestamp="T1"
        )
        assert "node-1" in ratings

    def test_epoch_transition_advances_maturity(self) -> None:
        engine = RatingEngine()
        engine.ingest_session_completion(
            node_id="node-1", success=True, epoch=1, timestamp="T1"
        )
        engine.on_epoch_transition(
            epoch=1, timestamp="T1", advance_maturity_for=["node-1"]
        )
        assert engine.store.get_maturity("node-1") == 1

    def test_multiple_epochs_advance_maturity(self) -> None:
        engine = RatingEngine()
        engine.ingest_session_completion(
            node_id="node-1", success=True, epoch=1, timestamp="T1"
        )
        for i in range(1, 6):
            engine.on_epoch_transition(
                epoch=i, timestamp=f"T{i}", advance_maturity_for=["node-1"]
            )
        assert engine.store.get_maturity("node-1") == 5


# ── Integration-style ──────────────────────────────────────────────


class TestIntegration:
    def test_full_lifecycle(self) -> None:
        """Node registers, earns good ratings, gets established."""
        engine = RatingEngine()

        # Multiple good sessions
        for i in range(1, 11):
            engine.ingest_session_completion(
                node_id="good-node",
                success=True,
                latency_seconds=2.0,
                epoch=i,
                timestamp=f"T{i}",
            )
            engine.ingest_heartbeat(
                node_id="good-node", healthy=True, epoch=i, timestamp=f"T{i}"
            )

        # Validation report
        engine.ingest_validation_report(
            node_id="good-node",
            recommendation="certify",
            confidence=0.9,
            epoch=10,
            timestamp="T10",
        )

        # Epoch transition
        engine.on_epoch_transition(
            epoch=10, timestamp="T10", advance_maturity_for=["good-node"]
        )

        rating = engine.get_rating("good-node", current_epoch=10, timestamp="T10")
        assert rating is not None
        assert rating.composite_score > 0.5
        assert rating.is_established
        assert rating.maturity_epochs == 1

    def test_bad_node_low_rating(self) -> None:
        """Node with failures gets low rating."""
        engine = RatingEngine()

        for i in range(1, 11):
            engine.ingest_session_completion(
                node_id="bad-node",
                success=False,
                latency_seconds=28.0,
                epoch=i,
                timestamp=f"T{i}",
            )
            engine.ingest_session_failure(
                node_id="bad-node",
                attribution="PROVIDER_AT_FAULT",
                epoch=i,
                timestamp=f"T{i}",
            )

        rating = engine.get_rating("bad-node", current_epoch=10, timestamp="T10")
        assert rating is not None
        assert rating.composite_score < 0.55  # uptime evidence from completion inflates composite

    def test_multi_node_ranking(self) -> None:
        """Multiple nodes ranked by composite score."""
        engine = RatingEngine()

        # Node A: mostly good
        for i in range(1, 11):
            engine.ingest_session_completion(
                node_id="a", success=(i % 3 != 0), epoch=i, timestamp=f"T{i}"
            )

        # Node B: always good
        for i in range(1, 11):
            engine.ingest_session_completion(
                node_id="b", success=True, epoch=i, timestamp=f"T{i}"
            )

        # Node C: mostly bad
        for i in range(1, 11):
            engine.ingest_session_completion(
                node_id="c", success=(i % 2 == 0), epoch=i, timestamp=f"T{i}"
            )

        ratings = engine.get_all_ratings(current_epoch=10, timestamp="T10")
        assert ratings["b"].composite_score >= ratings["a"].composite_score
        assert ratings["a"].composite_score >= ratings["c"].composite_score
