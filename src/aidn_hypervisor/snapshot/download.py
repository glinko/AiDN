"""RFC-0062 §41-§44 — Multi-source snapshot download with resumption.

SnapshotDownloader orchestrates chunk retrieval from multiple providers
with verification, retry, backpressure, and session persistence.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from aidn_hypervisor.snapshot.chunking import ChunkVerifier, Chunker
from aidn_hypervisor.snapshot.models import SnapshotChunk, SnapshotManifest


# ── Data Models ───────────────────────────────────────────────────


class DownloadSession(BaseModel, frozen=True):
    """Persistent download session for resumption."""

    snapshot_id: str
    manifest_hash: str
    verified_chunk_bitmap: list[bool]
    pending_chunks: list[int]
    failed_chunks: list[int]
    providers_used: list[str]
    temporary_files: list[str]
    total_bytes_downloaded: int
    started_at: str
    last_activity: str


class DownloadConfig(BaseModel, frozen=True):
    """Download behaviour configuration."""

    max_concurrent_transfers: int = 4
    max_bandwidth_bytes_per_sec: int = 10_485_760
    max_retry_count: int = 3
    retry_delay_seconds: float = 2.0
    chunk_timeout_seconds: float = 30.0


class DownloadResult(BaseModel, frozen=True):
    """Outcome of a download attempt."""

    snapshot_id: str
    success: bool
    chunks_downloaded: int
    chunks_total: int
    chunks_verified: int
    chunks_failed: list[int]
    total_bytes: int
    session: DownloadSession
    error: str | None = None


# ── Transfer Source Protocol ──────────────────────────────────────


class ChunkTransferSource(ABC):
    """Abstract interface for chunk transfer backends."""

    @abstractmethod
    def get_chunk(
        self,
        snapshot_id: str,
        chunk_index: int,
        provider_id: str,
    ) -> SnapshotChunk | None:
        """Retrieve a single chunk from a provider."""
        ...

    @abstractmethod
    def get_provider_inventory(
        self,
        snapshot_id: str,
        provider_id: str,
    ) -> list[int]:
        """Return available chunk indices for a provider."""
        ...

    @abstractmethod
    def is_provider_available(self, provider_id: str) -> bool:
        """Check if a provider is reachable."""
        ...


# ── Download Planner ──────────────────────────────────────────────

class DownloadPlanner:
    """Map chunks to providers with round-robin diversity (§42)."""

    @staticmethod
    def plan(
        total_chunks: int,
        providers: list[str],
        available_chunks: dict[str, list[int]],
    ) -> dict[int, list[str]]:
        """Return {chunk_index: [provider_ids]} mapping.

        Round-robins chunk assignment across providers that have it
        for provider diversity.
        """
        plan: dict[int, list[str]] = {}
        provider_idx = 0

        for chunk_idx in range(total_chunks):
            candidates = []
            for p_idx, prov in enumerate(providers):
                if chunk_idx in available_chunks.get(prov, []):
                    candidates.append(prov)

            if candidates:
                # Primary provider selected by round-robin for diversity;
                # all remaining candidates appended for fallback on verification failure
                primary = candidates[
                    candidates.index(providers[provider_idx % len(providers)])
                    if providers[provider_idx % len(providers)] in candidates
                    else 0
                ]
                assigned = [primary]
                for c in candidates:
                    if c not in assigned:
                        assigned.append(c)
                plan[chunk_idx] = assigned
                provider_idx = (provider_idx + 1) % len(providers)
            else:
                plan[chunk_idx] = []

        return plan


# ── Snapshot Downloader ───────────────────────────────────────────


class SnapshotDownloader:
    """Multi-source snapshot downloader with resumption (§41-§44)."""

    def __init__(
        self,
        config: DownloadConfig,
        transfer_source: ChunkTransferSource,
    ) -> None:
        self._config = config
        self._source = transfer_source
        self._chunker = Chunker()

    def _verify_chunk(self, chunk: SnapshotChunk) -> bool:
        """Verify a single chunk's integrity."""
        return self._chunker.verify_chunk(chunk)

    def download(
        self,
        snapshot_id: str,
        manifest: SnapshotManifest,
        providers: list[str],
    ) -> DownloadResult:
        """Full download pipeline per §41."""
        now = datetime.now(timezone.utc).isoformat()
        total = manifest.chunk_count

        # Initial session state
        bitmap: list[bool] = [False] * total
        pending: list[int] = list(range(total))
        failed: list[int] = []
        total_bytes = 0

        # Build provider inventory
        available: dict[str, list[int]] = {}
        for prov in providers:
            available[prov] = self._source.get_provider_inventory(snapshot_id, prov)

        # Plan chunk-to-provider mapping
        plan = DownloadPlanner.plan(total, providers, available)

        # Download chunks respecting concurrency limit (§44)
        concurrency = self._config.max_concurrent_transfers

        for start in range(0, len(pending), concurrency):
            batch = pending[start : start + concurrency]
            for chunk_idx in batch:
                prov_list = plan.get(chunk_idx, [])
                downloaded = False

                # Try all providers for this chunk (not just one)
                # Each provider counts as one attempt cycle
                for prov in prov_list:
                    if downloaded:
                        break
                    if not self._source.is_provider_available(prov):
                        continue

                    for attempt in range(self._config.max_retry_count + 1):
                        chunk = self._source.get_chunk(snapshot_id, chunk_idx, prov)
                        if chunk is None:
                            continue

                        # Verify chunk integrity
                        if self._verify_chunk(chunk):
                            bitmap[chunk_idx] = True
                            total_bytes += chunk.compressed_size
                            downloaded = True
                            break

                    if downloaded:
                        break

                if downloaded:
                    failed = [f for f in failed if f != chunk_idx]
                elif chunk_idx not in failed:
                    failed.append(chunk_idx)

        # Remove successfully downloaded from pending
        still_pending = [i for i in pending if not bitmap[i]]

        # Compute manifest hash
        manifest_hash = hashlib.sha256(
            manifest.model_dump_json().encode()
        ).hexdigest()

        success = len(failed) == 0
        verified_count = sum(1 for b in bitmap if b)

        session = DownloadSession(
            snapshot_id=snapshot_id,
            manifest_hash=manifest_hash,
            verified_chunk_bitmap=bitmap,
            pending_chunks=still_pending,
            failed_chunks=failed,
            providers_used=list(set(providers)),
            temporary_files=[],
            total_bytes_downloaded=total_bytes,
            started_at=now,
            last_activity=now,
        )

        return DownloadResult(
            snapshot_id=snapshot_id,
            success=success,
            chunks_downloaded=verified_count,
            chunks_total=total,
            chunks_verified=verified_count,
            chunks_failed=failed,
            total_bytes=total_bytes,
            session=session,
            error=None if success else f"{len(failed)} chunks failed",
        )

    def resume(
        self,
        session: DownloadSession,
        providers: list[str],
    ) -> DownloadResult:
        """Resume a download from a saved session (§43)."""
        now = datetime.now(timezone.utc).isoformat()
        total = len(session.verified_chunk_bitmap)
        bitmap = list(session.verified_chunk_bitmap)
        failed = list(session.failed_chunks)
        total_bytes = session.total_bytes_downloaded

        # Only download missing/failed chunks
        # Include failed chunks for retry with new providers
        needed = [
            i for i in range(total)
            if not bitmap[i]
        ]

        if not needed:
            # Nothing to download — return current state
            return DownloadResult(
                snapshot_id=session.snapshot_id,
                success=len(failed) == 0,
                chunks_downloaded=sum(1 for b in bitmap if b),
                chunks_total=total,
                chunks_verified=sum(1 for b in bitmap if b),
                chunks_failed=failed,
                total_bytes=total_bytes,
                session=session,
                error=None if not failed else f"{len(failed)} chunks failed",
            )

        # Build provider inventory
        available: dict[str, list[int]] = {}
        for prov in providers:
            available[prov] = self._source.get_provider_inventory(
                session.snapshot_id, prov
            )

        plan = DownloadPlanner.plan(total, providers, available)
        concurrency = self._config.max_concurrent_transfers

        for start in range(0, len(needed), concurrency):
            batch = needed[start : start + concurrency]
            for chunk_idx in batch:
                prov_list = plan.get(chunk_idx, [])
                downloaded = False

                # Try all providers for this chunk
                for prov in prov_list:
                    if downloaded:
                        break
                    if not self._source.is_provider_available(prov):
                        continue

                    for attempt in range(self._config.max_retry_count + 1):
                        chunk = self._source.get_chunk(
                            session.snapshot_id, chunk_idx, prov
                        )
                        if chunk is None:
                            continue

                        if self._verify_chunk(chunk):
                            bitmap[chunk_idx] = True
                            total_bytes += chunk.compressed_size
                            downloaded = True
                            break

                    if downloaded:
                        break

                if downloaded:
                    failed = [f for f in failed if f != chunk_idx]
                elif chunk_idx not in failed:
                    failed.append(chunk_idx)

        still_pending = [i for i in range(total) if not bitmap[i]]

        updated_session = DownloadSession(
            snapshot_id=session.snapshot_id,
            manifest_hash=session.manifest_hash,
            verified_chunk_bitmap=bitmap,
            pending_chunks=still_pending,
            failed_chunks=failed,
            providers_used=list(set(session.providers_used + providers)),
            temporary_files=session.temporary_files,
            total_bytes_downloaded=total_bytes,
            started_at=session.started_at,
            last_activity=now,
        )

        verified_count = sum(1 for b in bitmap if b)
        success = len(failed) == 0 and len(still_pending) == 0

        return DownloadResult(
            snapshot_id=session.snapshot_id,
            success=success,
            chunks_downloaded=verified_count,
            chunks_total=total,
            chunks_verified=verified_count,
            chunks_failed=failed,
            total_bytes=total_bytes,
            session=updated_session,
            error=None if success else f"{len(failed)} chunks failed",
        )
