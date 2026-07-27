"""M11-S1: Rating Store — in-memory persistence for rating evidence and history."""

from __future__ import annotations

from collections import defaultdict

from aidn_hypervisor.rating.models import (
    DimensionScore,
    NodeRating,
    RatingConfig,
    RatingDimension,
    RatingEvidence,
)
from aidn_hypervisor.rating.scoring import RatingScorer


class RatingStore:
    """In-memory store for rating evidence and computed ratings.

    Wraps a RatingScorer with persistence, epoch tracking,
    and evidence history queries.
    """

    def __init__(self, config: RatingConfig | None = None) -> None:
        self.config = config or RatingConfig()
        self._scorer = RatingScorer(config=self.config)
        self._evidence: dict[str, list[RatingEvidence]] = defaultdict(list)
        self._ratings: dict[str, list[NodeRating]] = defaultdict(list)
        self._maturity: dict[str, int] = defaultdict(int)

    # ── Evidence ──────────────────────────────────────────────────

    def add_evidence(self, evidence: RatingEvidence) -> None:
        """Store a piece of rating evidence and update scores."""
        self._evidence[evidence.node_id].append(evidence)
        self._scorer.ingest_evidence(evidence)

    def add_evidence_batch(self, evidence_list: list[RatingEvidence]) -> None:
        """Store multiple pieces of evidence."""
        for ev in evidence_list:
            self._evidence[ev.node_id].append(ev)
        self._scorer.ingest_batch(evidence_list)

    def get_evidence(
        self,
        node_id: str,
        *,
        dimension: RatingDimension | None = None,
        epoch: int | None = None,
        limit: int | None = None,
    ) -> list[RatingEvidence]:
        """Query evidence for a node with optional filters."""
        items = self._evidence.get(node_id, [])

        if dimension is not None:
            items = [e for e in items if e.dimension == dimension]

        if epoch is not None:
            items = [e for e in items if e.epoch == epoch]

        if limit is not None:
            items = items[-limit:]

        return list(items)

    def get_evidence_count(self, node_id: str) -> int:
        """Return total evidence count for a node."""
        return len(self._evidence.get(node_id, []))

    # ── Ratings ───────────────────────────────────────────────────

    def build_rating(
        self,
        node_id: str,
        *,
        current_epoch: int,
        timestamp: str,
    ) -> NodeRating | None:
        """Build a current NodeRating for a node.

        Applies temporal decay and stores the result in history.
        """
        maturity = self._maturity.get(node_id, 0)
        rating = self._scorer.build_node_rating(
            node_id,
            current_epoch=current_epoch,
            timestamp=timestamp,
            maturity_epochs=maturity,
        )
        if rating is not None:
            self._ratings[node_id].append(rating)
        return rating

    def get_current_rating(self, node_id: str) -> NodeRating | None:
        """Get the most recent stored rating for a node."""
        ratings = self._ratings.get(node_id, [])
        return ratings[-1] if ratings else None

    def get_rating_history(
        self, node_id: str, limit: int | None = None
    ) -> list[NodeRating]:
        """Get rating history for a node."""
        items = list(self._ratings.get(node_id, []))
        if limit is not None:
            items = items[-limit:]
        return items

    def get_dimension_score(
        self, node_id: str, dim: RatingDimension
    ) -> DimensionScore | None:
        """Get the current dimension score from the scorer."""
        return self._scorer.get_dimension_score(node_id, dim)

    def get_composite_score(self, node_id: str) -> float:
        """Get the current composite score for a node."""
        return self._scorer.compute_composite_score(node_id)

    # ── Maturity ──────────────────────────────────────────────────

    def advance_maturity(self, node_id: str) -> None:
        """Advance maturity epoch count for a node.

        Call at epoch transition for nodes that qualified.
        """
        self._maturity[node_id] = self._maturity.get(node_id, 0) + 1

    def get_maturity(self, node_id: str) -> int:
        """Get the current maturity epoch count."""
        return self._maturity.get(node_id, 0)

    def reset_maturity(self, node_id: str) -> None:
        """Reset maturity to zero (e.g., after serious failure)."""
        self._maturity[node_id] = 0

    # ── Node management ──────────────────────────────────────────

    def has_node(self, node_id: str) -> bool:
        """Check if a node has any rating data."""
        return self._scorer.has_node(node_id)

    def get_all_nodes(self) -> list[str]:
        """Return all known node IDs."""
        return self._scorer.get_known_nodes()

    def reset_node(self, node_id: str) -> None:
        """Remove all data for a node."""
        self._scorer.reset_node(node_id)
        self._evidence.pop(node_id, None)
        self._ratings.pop(node_id, None)
        self._maturity.pop(node_id, None)

    # ── Bulk queries ─────────────────────────────────────────────

    def get_all_ratings(
        self, current_epoch: int, timestamp: str
    ) -> dict[str, NodeRating]:
        """Build and return current ratings for all known nodes."""
        result: dict[str, NodeRating] = {}
        for node_id in self._scorer.get_known_nodes():
            rating = self.build_rating(
                node_id, current_epoch=current_epoch, timestamp=timestamp
            )
            if rating is not None:
                result[node_id] = rating
        return result

    def get_established_nodes(self) -> list[str]:
        """Return nodes with established ratings."""
        established: list[str] = []
        for node_id in self._scorer.get_known_nodes():
            current = self.get_current_rating(node_id)
            if current is not None and current.is_established:
                established.append(node_id)
        return established

    # ── Epoch transition ─────────────────────────────────────────

    def on_epoch_transition(self, epoch: int, timestamp: str) -> None:
        """Handle epoch transition: build ratings, apply decay."""
        for node_id in list(self._scorer.get_known_nodes()):
            self.build_rating(node_id, current_epoch=epoch, timestamp=timestamp)

    # ── Internal access ──────────────────────────────────────────

    @property
    def scorer(self) -> RatingScorer:
        """Access the underlying scorer for advanced operations."""
        return self._scorer
