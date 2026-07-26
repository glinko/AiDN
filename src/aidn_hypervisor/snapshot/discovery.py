"""RFC-0062 §37-§40 — Snapshot discovery and provider selection.

SnapshotDiscovery queries a registry for available snapshots.
SnapshotSelector scores and filters candidates per selection criteria.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


# ── Data Models ───────────────────────────────────────────────────


class SnapshotAvailability(BaseModel, frozen=True):
    """Snapshot availability status from the registry."""

    snapshot_id: str
    provider_service_ids: list[str]
    provider_group_count: int
    chunk_coverage: float = Field(ge=0.0, le=1.0)
    last_verified: str
    transfer_health: str  # "good", "degraded", "poor"


class SnapshotCandidate(BaseModel, frozen=True):
    """A snapshot candidate for selection, scored and evaluated."""

    manifest: Any  # SnapshotManifest (forward-ref avoided)
    availability: SnapshotAvailability
    score: float
    suitable: bool
    rejection_reasons: list[str]


# ── Registry Source Protocol ──────────────────────────────────────


class SnapshotRegistrySource(ABC):
    """Abstract registry source interface."""

    @abstractmethod
    def query_snapshots(self) -> list:
        """Query registry for snapshot manifests."""
        ...

    @abstractmethod
    def get_provider_inventory(self, snapshot_id: str) -> list[str]:
        """Get provider list for a snapshot."""
        ...


# ── Snapshot Discovery ────────────────────────────────────────────


class SnapshotDiscovery:
    """Discover available snapshots via registry."""

    def __init__(self, registry_source: SnapshotRegistrySource) -> None:
        self._source = registry_source

    def discover_snapshots(self) -> list[SnapshotAvailability]:
        """Query registry for available snapshots."""
        manifests = self._source.query_snapshots()
        results: list[SnapshotAvailability] = []

        for manifest in manifests:
            providers = self._source.get_provider_inventory(manifest.snapshot_id)
            avail = SnapshotAvailability(
                snapshot_id=manifest.snapshot_id,
                provider_service_ids=providers,
                provider_group_count=len(set(providers)) if providers else 0,
                chunk_coverage=1.0 if providers else 0.0,
                last_verified=manifest.creation_time,
                transfer_health="good" if len(providers) >= 3 else "degraded",
            )
            results.append(avail)

        return results

    def get_provider_status(self, snapshot_id: str) -> SnapshotAvailability | None:
        """Get availability for a specific snapshot."""
        manifests = self._source.query_snapshots()
        for manifest in manifests:
            if manifest.snapshot_id == snapshot_id:
                providers = self._source.get_provider_inventory(snapshot_id)
                return SnapshotAvailability(
                    snapshot_id=snapshot_id,
                    provider_service_ids=providers,
                    provider_group_count=len(set(providers)) if providers else 0,
                    chunk_coverage=1.0 if providers else 0.0,
                    last_verified=manifest.creation_time,
                    transfer_health="good" if len(providers) >= 3 else "degraded",
                )
        return None


# ── Snapshot Selector ─────────────────────────────────────────────


class SnapshotSelector:
    """Select the best snapshot candidate per RFC-0062 §38."""

    def __init__(
        self,
        *,
        chain_id: str,
        protocol_version: str,
        state_schema_versions: list[int],
        min_provider_groups: int = 3,
        stability_delay_blocks: int = 100,
    ) -> None:
        self._chain_id = chain_id
        self._protocol_version = protocol_version
        self._state_schema_versions = state_schema_versions
        self._min_provider_groups = min_provider_groups
        self._stability_delay_blocks = stability_delay_blocks

    def select(
        self,
        candidates: list[SnapshotCandidate],
        *,
        finalized_height: int,
    ) -> SnapshotCandidate | None:
        """Select the highest-scored suitable candidate.

        Returns None if no candidate passes all criteria.
        """
        if not candidates:
            return None

        evaluated: list[SnapshotCandidate] = []

        for candidate in candidates:
            rejection_reasons = self._evaluate(candidate, finalized_height)
            suitable = len(rejection_reasons) == 0

            if suitable:
                score = self._compute_score(candidate, finalized_height)
            else:
                score = 0.0

            evaluated.append(
                SnapshotCandidate(
                    manifest=candidate.manifest,
                    availability=candidate.availability,
                    score=score,
                    suitable=suitable,
                    rejection_reasons=rejection_reasons,
                )
            )

        suitable_candidates = [c for c in evaluated if c.suitable]
        if not suitable_candidates:
            return None

        return max(suitable_candidates, key=lambda c: c.score)

    def _evaluate(
        self,
        candidate: SnapshotCandidate,
        finalized_height: int,
    ) -> list[str]:
        """Return rejection reasons (empty = suitable)."""
        reasons: list[str] = []
        manifest = candidate.manifest
        avail = candidate.availability

        # 1. Canonical commitment exists
        if not manifest.application_state_hash:
            reasons.append("missing application_state_hash")

        # 2. Chain identity match
        if manifest.chain_id != self._chain_id:
            reasons.append("chain_id mismatch")

        # 3. Height compatible with trust anchor
        if manifest.block_height > finalized_height:
            reasons.append("height exceeds finalized")

        # 3. Protocol version supported
        if manifest.protocol_version != self._protocol_version:
            reasons.append("unsupported protocol version")

        # 4. State schema supported
        if manifest.state_schema_version not in self._state_schema_versions:
            reasons.append("unsupported state schema version")

        # 5. Sufficient providers
        if avail.provider_group_count < self._min_provider_groups:
            reasons.append("insufficient provider groups")

        # 6. Stability delay elapsed
        gap = finalized_height - manifest.block_height
        if gap < self._stability_delay_blocks:
            reasons.append("stability delay not elapsed")

        return reasons

    def _compute_score(
        self,
        candidate: SnapshotCandidate,
        finalized_height: int,
    ) -> float:
        """Compute selection score per §38 (higher = better)."""
        manifest = candidate.manifest
        avail = candidate.availability

        # Base score: prefer newer snapshots
        base = manifest.block_height / finalized_height if finalized_height > 0 else 0.0

        # Provider diversity bonus
        provider_bonus = min(avail.provider_group_count / 3, 1.0) * 0.2

        # Availability bonus
        availability_bonus = avail.chunk_coverage * 0.1

        # Transfer health bonus
        health_map = {"good": 0.05, "degraded": 0.02, "poor": 0.0}
        health_bonus = health_map.get(avail.transfer_health, 0.0)

        return base + provider_bonus + availability_bonus + health_bonus
