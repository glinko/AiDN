"""M11-S1: Rating Store tests."""

from __future__ import annotations

import pytest

from aidn_hypervisor.rating.models import (
    RatingConfig,
    RatingDimension,
    RatingEvidence,
    RatingEvidenceType,
)
from aidn_hypervisor.rating.store import RatingStore


# ── Helpers ──────────────────────────────────────────────────────────


def _ev(
    node_id: str = "node-1",
    dim: RatingDimension = RatingDimension.UPTIME,
    value: float = 0.9,
    epoch: int = 1,
    weight: float = 0.8,
) -> RatingEvidence:
    return RatingEvidence(
        node_id=node_id,
        dimension=dim,
        evidence_type=RatingEvidenceType.HEARTBEAT,
        value=value,
        weight=weight,
        epoch=epoch,
        timestamp=f"2026-01-{epoch:02d}T00:00:00Z",
    )


# ── Evidence storage ─────────────────────────────────────────────────


class TestEvidenceStorage:
    def test_add_evidence(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1))
        assert store.get_evidence_count("node-1") == 1

    def test_add_batch(self) -> None:
        store = RatingStore()
        store.add_evidence_batch([_ev(epoch=1), _ev(epoch=2), _ev(epoch=3)])
        assert store.get_evidence_count("node-1") == 3

    def test_evidence_query_all(self) -> None:
        store = RatingStore()
        store.add_evidence_batch([_ev(epoch=1), _ev(epoch=2)])
        items = store.get_evidence("node-1")
        assert len(items) == 2

    def test_evidence_query_filtered_by_dimension(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(dim=RatingDimension.UPTIME, epoch=1))
        store.add_evidence(_ev(dim=RatingDimension.SUCCESS_RATE, epoch=1))
        items = store.get_evidence("node-1", dimension=RatingDimension.UPTIME)
        assert len(items) == 1
        assert items[0].dimension == RatingDimension.UPTIME

    def test_evidence_query_filtered_by_epoch(self) -> None:
        store = RatingStore()
        store.add_evidence_batch([_ev(epoch=1), _ev(epoch=2), _ev(epoch=3)])
        items = store.get_evidence("node-1", epoch=2)
        assert len(items) == 1
        assert items[0].epoch == 2

    def test_evidence_query_with_limit(self) -> None:
        store = RatingStore()
        store.add_evidence_batch([_ev(epoch=i) for i in range(1, 11)])
        items = store.get_evidence("node-1", limit=3)
        assert len(items) == 3
        assert items[-1].epoch == 10

    def test_evidence_empty_for_unknown_node(self) -> None:
        store = RatingStore()
        items = store.get_evidence("unknown")
        assert items == []


# ── Rating building ─────────────────────────────────────────────────


class TestRatingBuilding:
    def test_build_rating(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1))
        rating = store.build_rating("node-1", current_epoch=1, timestamp="T1")
        assert rating is not None
        assert rating.node_id == "node-1"

    def test_build_rating_none_for_unknown(self) -> None:
        store = RatingStore()
        rating = store.build_rating("unknown", current_epoch=1, timestamp="T1")
        assert rating is None

    def test_get_current_rating(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1))
        store.build_rating("node-1", current_epoch=1, timestamp="T1")
        current = store.get_current_rating("node-1")
        assert current is not None

    def test_get_current_rating_none_if_not_built(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1))
        current = store.get_current_rating("node-1")
        assert current is None

    def test_rating_history_grows(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1))
        store.build_rating("node-1", current_epoch=1, timestamp="T1")
        store.build_rating("node-1", current_epoch=2, timestamp="T2")
        history = store.get_rating_history("node-1")
        assert len(history) == 2

    def test_rating_history_with_limit(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1))
        for i in range(1, 6):
            store.build_rating("node-1", current_epoch=i, timestamp=f"T{i}")
        history = store.get_rating_history("node-1", limit=2)
        assert len(history) == 2


# ── Score queries ────────────────────────────────────────────────────


class TestScoreQueries:
    def test_get_dimension_score(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1, value=0.9))
        ds = store.get_dimension_score("node-1", RatingDimension.UPTIME)
        assert ds is not None
        assert ds.score > 0.5

    def test_get_composite_score(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1, value=0.8))
        score = store.get_composite_score("node-1")
        assert score > 0.0

    def test_composite_zero_for_unknown(self) -> None:
        store = RatingStore()
        assert store.get_composite_score("unknown") == 0.0


# ── Maturity ─────────────────────────────────────────────────────────


class TestMaturity:
    def test_advance_maturity(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1))
        store.advance_maturity("node-1")
        assert store.get_maturity("node-1") == 1

    def test_advance_maturity_multiple(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1))
        for _ in range(5):
            store.advance_maturity("node-1")
        assert store.get_maturity("node-1") == 5

    def test_maturity_in_rating(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1))
        store.advance_maturity("node-1")
        store.advance_maturity("node-1")
        rating = store.build_rating("node-1", current_epoch=2, timestamp="T2")
        assert rating is not None
        assert rating.maturity_epochs == 2

    def test_reset_maturity(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1))
        store.advance_maturity("node-1")
        store.advance_maturity("node-1")
        store.reset_maturity("node-1")
        assert store.get_maturity("node-1") == 0

    def test_default_maturity_zero(self) -> None:
        store = RatingStore()
        assert store.get_maturity("any-node") == 0


# ── Node management ─────────────────────────────────────────────────


class TestNodeManagement:
    def test_has_node(self) -> None:
        store = RatingStore()
        assert not store.has_node("node-1")
        store.add_evidence(_ev(epoch=1))
        assert store.has_node("node-1")

    def test_get_all_nodes(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(node_id="a", epoch=1))
        store.add_evidence(_ev(node_id="b", epoch=1))
        nodes = store.get_all_nodes()
        assert set(nodes) == {"a", "b"}

    def test_reset_node(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(epoch=1))
        store.advance_maturity("node-1")
        store.reset_node("node-1")
        assert not store.has_node("node-1")
        assert store.get_evidence_count("node-1") == 0
        assert store.get_maturity("node-1") == 0


# ── Bulk queries ────────────────────────────────────────────────────


class TestBulkQueries:
    def test_get_all_ratings(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(node_id="a", epoch=1))
        store.add_evidence(_ev(node_id="b", epoch=1))
        ratings = store.get_all_ratings(current_epoch=1, timestamp="T1")
        assert len(ratings) == 2
        assert "a" in ratings
        assert "b" in ratings

    def test_get_established_nodes(self) -> None:
        store = RatingStore()
        # Add enough evidence for established rating
        for i in range(10):
            store.add_evidence(_ev(epoch=i + 1, value=0.9))
        store.build_rating("node-1", current_epoch=10, timestamp="T10")
        established = store.get_established_nodes()
        assert "node-1" in established


# ── Epoch transition ────────────────────────────────────────────────


class TestEpochTransition:
    def test_on_epoch_transition_builds_ratings(self) -> None:
        store = RatingStore()
        store.add_evidence(_ev(node_id="a", epoch=1))
        store.add_evidence(_ev(node_id="b", epoch=1))
        store.on_epoch_transition(epoch=1, timestamp="T1")
        assert store.get_current_rating("a") is not None
        assert store.get_current_rating("b") is not None


# ── Scorer access ───────────────────────────────────────────────────


class TestScorerAccess:
    def test_scorer_property(self) -> None:
        store = RatingStore()
        scorer = store.scorer
        assert scorer is not None
