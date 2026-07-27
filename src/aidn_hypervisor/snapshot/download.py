"""RFC-0062 §41-§44 — Multi-source snapshot download with resumption.

SnapshotDownloader orchestrates chunk retrieval from multiple providers
with verification, retry, backpressure, and session persistence.
"""

from __future__ import annotations

import hashlib
import tempfile
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from aidn_hypervisor.snapshot.chunk_store import FileSnapshotChunkStore, SnapshotChunkStore
from aidn_hypervisor.snapshot.chunking import Chunker, MerkleTree
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
    chunk_hashes: list[str | None] = Field(default_factory=list)
    chunk_storage_keys: list[str | None] = Field(default_factory=list)
    expected_chunk_root: str = ""


class DownloadConfig(BaseModel, frozen=True):
    """Download behaviour configuration."""

    max_concurrent_transfers: int = Field(default=4, ge=1)
    max_bandwidth_bytes_per_sec: int = Field(default=10_485_760, ge=1)
    max_retry_count: int = Field(default=3, ge=0)
    retry_delay_seconds: float = Field(default=2.0, ge=0)
    chunk_timeout_seconds: float = Field(default=30.0, gt=0)


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
            for prov in providers:
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
        chunk_store: SnapshotChunkStore | None = None,
    ) -> None:
        self._config = config
        self._source = transfer_source
        self._chunker = Chunker()
        self._chunk_store = chunk_store or FileSnapshotChunkStore(Path(tempfile.gettempdir()) / "aidn-snapshot-chunks")

    def _verify_chunk(self, chunk: SnapshotChunk) -> bool:
        """Verify a single chunk's integrity."""
        return self._chunker.verify_chunk(chunk)

    def _chunk_matches_manifest(
        self,
        chunk: SnapshotChunk,
        manifest: SnapshotManifest,
        expected_index: int,
    ) -> bool:
        """Verify that a valid chunk also belongs to this exact manifest."""
        return (
            chunk.snapshot_id == manifest.snapshot_id
            and chunk.chunk_index == expected_index
            and chunk.total_chunks == manifest.chunk_count
            and chunk.compressed_size == len(chunk.payload)
            and self._verify_chunk(chunk)
        )

    @staticmethod
    def _verified_root(
        bitmap: list[bool],
        chunk_hashes: list[str | None],
        expected_chunk_root: str,
    ) -> bool:
        """Return whether all verified chunks produce the manifest Merkle root."""
        if not expected_chunk_root or not all(bitmap):
            return False
        if len(chunk_hashes) != len(bitmap) or any(chunk_hash is None for chunk_hash in chunk_hashes):
            return False
        hashes = [chunk_hash for chunk_hash in chunk_hashes if chunk_hash]
        return MerkleTree(hashes).root_hash() == expected_chunk_root

    @staticmethod
    def _invalidate_unproven_chunks(
        bitmap: list[bool],
        chunk_hashes: list[str | None],
        chunk_storage_keys: list[str | None],
    ) -> list[int]:
        """Invalidate a set whose individual chunks do not form the manifest."""
        bitmap[:] = [False] * len(bitmap)
        chunk_hashes[:] = [None] * len(chunk_hashes)
        chunk_storage_keys[:] = [None] * len(chunk_storage_keys)
        return list(range(len(bitmap)))

    def _stored_chunk_is_valid(
        self,
        key: str | None,
        *,
        snapshot_id: str,
        chunk_index: int,
        total_chunks: int,
        expected_hash: str | None,
    ) -> bool:
        """Check that a session key resolves to exactly its verified chunk."""
        if key is None or expected_hash is None:
            return False
        chunk = self._chunk_store.get(key)
        return (
            chunk is not None
            and chunk.snapshot_id == snapshot_id
            and chunk.chunk_index == chunk_index
            and chunk.total_chunks == total_chunks
            and chunk.chunk_hash == expected_hash
            and chunk.compressed_size == len(chunk.payload)
            and self._verify_chunk(chunk)
        )

    def load_verified_chunks(self, session: DownloadSession) -> list[SnapshotChunk]:
        """Load and revalidate the complete persisted chunk set for activation."""
        total = len(session.verified_chunk_bitmap)
        if (
            total < 1
            or len(session.chunk_hashes) != total
            or len(session.chunk_storage_keys) != total
            or not self._verified_root(
                session.verified_chunk_bitmap,
                session.chunk_hashes,
                session.expected_chunk_root,
            )
        ):
            raise ValueError("download session does not prove a complete chunk set")

        chunks: list[SnapshotChunk] = []
        for index, (chunk_hash, key) in enumerate(zip(session.chunk_hashes, session.chunk_storage_keys, strict=True)):
            if not self._stored_chunk_is_valid(
                key,
                snapshot_id=session.snapshot_id,
                chunk_index=index,
                total_chunks=total,
                expected_hash=chunk_hash,
            ):
                raise ValueError(f"verified chunk {index} is unavailable or invalid")
            chunk = self._chunk_store.get(key)
            if chunk is None:  # Defensive: validation above already loaded it.
                raise ValueError(f"verified chunk {index} disappeared during load")
            chunks.append(chunk)
        return chunks

    def download(
        self,
        snapshot_id: str,
        manifest: SnapshotManifest,
        providers: list[str],
    ) -> DownloadResult:
        """Full download pipeline per §41."""
        if snapshot_id != manifest.snapshot_id:
            raise ValueError("snapshot_id must match the manifest")
        if manifest.chunk_count < 1:
            raise ValueError("manifest chunk_count must be positive")

        now = datetime.now(UTC).isoformat()
        total = manifest.chunk_count

        # Initial session state
        bitmap: list[bool] = [False] * total
        chunk_hashes: list[str | None] = [None] * total
        chunk_storage_keys: list[str | None] = [None] * total
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

                    for _attempt in range(self._config.max_retry_count + 1):
                        chunk = self._source.get_chunk(snapshot_id, chunk_idx, prov)
                        if chunk is None:
                            continue

                        # Verify chunk integrity
                        if self._chunk_matches_manifest(chunk, manifest, chunk_idx):
                            try:
                                storage_key = self._chunk_store.put(chunk)
                            except OSError:
                                continue
                            bitmap[chunk_idx] = True
                            chunk_hashes[chunk_idx] = chunk.chunk_hash
                            chunk_storage_keys[chunk_idx] = storage_key
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
        manifest_hash = hashlib.sha256(manifest.model_dump_json().encode()).hexdigest()

        if not failed and not self._verified_root(bitmap, chunk_hashes, manifest.chunk_root):
            failed = self._invalidate_unproven_chunks(bitmap, chunk_hashes, chunk_storage_keys)
            still_pending = list(range(total))

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
            chunk_hashes=chunk_hashes,
            chunk_storage_keys=chunk_storage_keys,
            expected_chunk_root=manifest.chunk_root,
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
        now = datetime.now(UTC).isoformat()
        total = len(session.verified_chunk_bitmap)
        if total < 1:
            raise ValueError("download session must contain at least one chunk")
        bitmap = list(session.verified_chunk_bitmap)
        chunk_hashes = list(session.chunk_hashes)
        chunk_storage_keys = list(session.chunk_storage_keys)
        if len(chunk_hashes) != total or len(chunk_storage_keys) != total:
            # Legacy sessions cannot prove the chunks recorded before restart.
            chunk_hashes = [None] * total
            chunk_storage_keys = [None] * total
            bitmap = [False] * total
        else:
            # A persisted bitmap is trustworthy only when the locally stored
            # payload still matches the exact session commitment.
            for index in range(total):
                if bitmap[index] and self._stored_chunk_is_valid(
                    chunk_storage_keys[index],
                    snapshot_id=session.snapshot_id,
                    chunk_index=index,
                    total_chunks=total,
                    expected_hash=chunk_hashes[index],
                ):
                    continue
                bitmap[index] = False
                chunk_hashes[index] = None
                chunk_storage_keys[index] = None
        failed = list(session.failed_chunks)
        total_bytes = session.total_bytes_downloaded

        # Only download missing/failed chunks
        # Include failed chunks for retry with new providers
        needed = [
            index
            for index in range(total)
            if not bitmap[index]
            or not self._stored_chunk_is_valid(
                chunk_storage_keys[index],
                snapshot_id=session.snapshot_id,
                chunk_index=index,
                total_chunks=total,
                expected_hash=chunk_hashes[index],
            )
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
            available[prov] = self._source.get_provider_inventory(session.snapshot_id, prov)

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

                    for _attempt in range(self._config.max_retry_count + 1):
                        chunk = self._source.get_chunk(session.snapshot_id, chunk_idx, prov)
                        if chunk is None:
                            continue

                        if (
                            chunk.snapshot_id == session.snapshot_id
                            and chunk.chunk_index == chunk_idx
                            and chunk.total_chunks == total
                            and chunk.compressed_size == len(chunk.payload)
                            and self._verify_chunk(chunk)
                        ):
                            try:
                                storage_key = self._chunk_store.put(chunk)
                            except OSError:
                                continue
                            bitmap[chunk_idx] = True
                            chunk_hashes[chunk_idx] = chunk.chunk_hash
                            chunk_storage_keys[chunk_idx] = storage_key
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

        if not failed and not self._verified_root(bitmap, chunk_hashes, session.expected_chunk_root):
            failed = self._invalidate_unproven_chunks(bitmap, chunk_hashes, chunk_storage_keys)
            still_pending = list(range(total))

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
            chunk_hashes=chunk_hashes,
            chunk_storage_keys=chunk_storage_keys,
            expected_chunk_root=session.expected_chunk_root,
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
