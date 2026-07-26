"""M11-S1: Rating Engine — high-level event ingestion and rating management."""

from __future__ import annotations

from datetime import UTC, datetime

from aidn_hypervisor.rating.models import (
    NodeRating,
    RatingConfig,
    RatingDimension,
    RatingEvidence,
    RatingEvidenceType,
    RatingUpdateResult,
)
from aidn_hypervisor.rating.store import RatingStore


class RatingEngine:
    """High-level rating engine.

    Provides:
    - Event ingestion from various sources
    - Rating queries
    - Epoch transition hooks
    - Maturity management
    """

    def __init__(self, config: RatingConfig | None = None) -> None:
        self._store = RatingStore(config=config)
        self._config = config or RatingConfig()

    # ── Event ingestion ──────────────────────────────────────────

    def ingest_session_completion(
        self,
        *,
        node_id: str,
        success: bool,
        latency_seconds: float | None = None,
        epoch: int,
        timestamp: str | None = None,
    ) -> list[RatingUpdateResult]:
        """Ingest a session completion event.

        Produces evidence for:
        - SUCCESS_RATE (success/failure)
        - LATENCY (if provided)
        - UPTIME (implicit — the node was available)
        """
        ts = timestamp or datetime.now(UTC).isoformat()
        evidences: list[RatingEvidence] = []

        # Success rate evidence
        evidences.append(RatingEvidence(
            node_id=node_id,
            dimension=RatingDimension.SUCCESS_RATE,
            evidence_type=RatingEvidenceType.SESSION_COMPLETION,
            value=1.0 if success else 0.0,
            weight=0.9,
            epoch=epoch,
            timestamp=ts,
        ))

        # Uptime evidence (node was available)
        evidences.append(RatingEvidence(
            node_id=node_id,
            dimension=RatingDimension.UPTIME,
            evidence_type=RatingEvidenceType.SESSION_COMPLETION,
            value=1.0,
            weight=0.7,
            epoch=epoch,
            timestamp=ts,
        ))

        # Latency evidence (if provided)
        if latency_seconds is not None:
            # Normalize: 0s = 1.0 (perfect), 30s+ = 0.0 (worst)
            latency_score = max(0.0, 1.0 - (latency_seconds / 30.0))
            evidences.append(RatingEvidence(
                node_id=node_id,
                dimension=RatingDimension.LATENCY,
                evidence_type=RatingEvidenceType.SESSION_COMPLETION,
                value=latency_score,
                weight=0.6,
                epoch=epoch,
                timestamp=ts,
            ))

        return self._ingest_batch(evidences)

    def ingest_session_failure(
        self,
        *,
        node_id: str,
        attribution: str,
        epoch: int,
        timestamp: str | None = None,
    ) -> list[RatingUpdateResult]:
        """Ingest a session failure event.

        Produces evidence for:
        - SUCCESS_RATE (0.0)
        - DISPUTE_HISTORY (if node was at fault)
        """
        ts = timestamp or datetime.now(UTC).isoformat()
        evidences: list[RatingEvidence] = []

        # Success rate hit
        evidences.append(RatingEvidence(
            node_id=node_id,
            dimension=RatingDimension.SUCCESS_RATE,
            evidence_type=RatingEvidenceType.SESSION_FAILURE,
            value=0.0,
            weight=0.8,
            epoch=epoch,
            timestamp=ts,
        ))

        # Dispute history (only if node was at fault)
        if attribution in ("PROVIDER_AT_FAULT", "CONSUMER_AT_FAULT"):
            evidences.append(RatingEvidence(
                node_id=node_id,
                dimension=RatingDimension.DISPUTE_HISTORY,
                evidence_type=RatingEvidenceType.SESSION_FAILURE,
                value=1.0,  # high = bad for dispute_history (negative dim)
                weight=0.7,
                epoch=epoch,
                timestamp=ts,
            ))

        return self._ingest_batch(evidences)

    def ingest_validation_report(
        self,
        *,
        node_id: str,
        recommendation: str,
        confidence: float,
        epoch: int,
        timestamp: str | None = None,
    ) -> list[RatingUpdateResult]:
        """Ingest a validation report.

        Produces evidence for REPUTATION dimension.
        """
        ts = timestamp or datetime.now(UTC).isoformat()

        value = 1.0 if recommendation == "certify" else (
            0.0 if recommendation == "de_certify" else 0.5
        )

        ev = RatingEvidence(
            node_id=node_id,
            dimension=RatingDimension.REPUTATION,
            evidence_type=RatingEvidenceType.VALIDATION_REPORT,
            value=value,
            weight=confidence,
            epoch=epoch,
            timestamp=ts,
        )
        return self._ingest_batch([ev])

    def ingest_heartbeat(
        self,
        *,
        node_id: str,
        healthy: bool,
        epoch: int,
        timestamp: str | None = None,
    ) -> list[RatingUpdateResult]:
        """Ingest a heartbeat check.

        Produces evidence for UPTIME dimension.
        """
        ts = timestamp or datetime.now(UTC).isoformat()

        ev = RatingEvidence(
            node_id=node_id,
            dimension=RatingDimension.UPTIME,
            evidence_type=RatingEvidenceType.HEARTBEAT,
            value=1.0 if healthy else 0.0,
            weight=0.5,
            epoch=epoch,
            timestamp=ts,
        )
        return self._ingest_batch([ev])

    def ingest_raw_evidence(
        self, evidence: RatingEvidence
    ) -> RatingUpdateResult:
        """Ingest a raw piece of evidence."""
        self._store.add_evidence(evidence)
        return RatingUpdateResult(
            node_id=evidence.node_id,
            dimension=evidence.dimension,
            old_score=0.0,
            new_score=self._store.get_composite_score(evidence.node_id),
            delta=0.0,
            evidence_count=self._store.get_evidence_count(evidence.node_id),
            confidence=0.0,
            epoch=evidence.epoch,
        )

    # ── Queries ──────────────────────────────────────────────────

    def get_rating(
        self,
        node_id: str,
        *,
        current_epoch: int | None = None,
        timestamp: str | None = None,
    ) -> NodeRating | None:
        """Get the current rating for a node.

        If current_epoch is provided, builds a fresh rating.
        Otherwise returns the last stored rating.
        """
        if current_epoch is not None:
            ts = timestamp or datetime.now(UTC).isoformat()
            return self._store.build_rating(node_id, current_epoch=current_epoch, timestamp=ts)
        return self._store.get_current_rating(node_id)

    def get_composite_score(self, node_id: str) -> float:
        """Get the current composite score."""
        return self._store.get_composite_score(node_id)

    def get_dimension_score(
        self, node_id: str, dimension: RatingDimension
    ) -> float:
        """Get the current score for a specific dimension."""
        ds = self._store.get_dimension_score(node_id, dimension)
        return ds.score if ds else 0.0

    def get_all_ratings(
        self, current_epoch: int, timestamp: str | None = None
    ) -> dict[str, NodeRating]:
        """Get ratings for all known nodes."""
        ts = timestamp or datetime.now(UTC).isoformat()
        return self._store.get_all_ratings(current_epoch=current_epoch, timestamp=ts)

    # ── Epoch transitions ────────────────────────────────────────

    def on_epoch_transition(
        self,
        epoch: int,
        timestamp: str | None = None,
        *,
        advance_maturity_for: list[str] | None = None,
    ) -> dict[str, NodeRating]:
        """Handle epoch transition.

        Builds fresh ratings for all nodes and advances maturity
        for qualifying nodes.

        Returns dict of node_id -> NodeRating.
        """
        ts = timestamp or datetime.now(UTC).isoformat()

        # Advance maturity for qualifying nodes
        if advance_maturity_for:
            for nid in advance_maturity_for:
                self._store.advance_maturity(nid)

        # Build ratings for all nodes
        self._store.on_epoch_transition(epoch=epoch, timestamp=ts)
        return self._store.get_all_ratings(current_epoch=epoch, timestamp=ts)

    # ── Internal ─────────────────────────────────────────────────

    def _ingest_batch(
        self, evidences: list[RatingEvidence]
    ) -> list[RatingUpdateResult]:
        """Ingest a batch of evidence, returning results."""
        results: list[RatingUpdateResult] = []
        for ev in evidences:
            self._store.add_evidence(ev)
            results.append(RatingUpdateResult(
                node_id=ev.node_id,
                dimension=ev.dimension,
                old_score=0.0,
                new_score=self._store.get_composite_score(ev.node_id),
                delta=0.0,
                evidence_count=self._store.get_evidence_count(ev.node_id),
                confidence=0.0,
                epoch=ev.epoch,
            ))
        return results

    # ── Properties ───────────────────────────────────────────────

    @property
    def store(self) -> RatingStore:
        """Access the underlying store."""
        return self._store

    @property
    def config(self) -> RatingConfig:
        """Access the configuration."""
        return self._config
