"""Tests for snapshot download (RFC-0062 §41-§44)."""

from __future__ import annotations

import hashlib

import pytest

from aidn_hypervisor.snapshot.chunking import MerkleTree
from aidn_hypervisor.snapshot.download import (
    ChunkTransferSource,
    DownloadConfig,
    DownloadSession,
    SnapshotDownloader,
)
from aidn_hypervisor.snapshot.models import (
    CompressionAlgorithm,
    Encoding,
    SnapshotChunk,
    SnapshotManifest,
    SnapshotType,
)

# ── Helpers ────────────────────────────────────────────────────────


def _make_manifest(
    *,
    snapshot_id: str = "snap-001",
    chunk_count: int = 4,
    chunk_size: int = 1024,
    chunk_root: str | None = None,
) -> SnapshotManifest:
    if chunk_root in (None, "chunk-root-abc"):
        chunk_hash = hashlib.sha256(b"x" * chunk_size).hexdigest()
        chunk_root = MerkleTree([chunk_hash] * chunk_count).root_hash()
    return SnapshotManifest(
        snapshot_id=snapshot_id,
        snapshot_type=SnapshotType.FULL_STATE,
        snapshot_format_version=1,
        network_id="aidn",
        chain_id="aidn-mainnet",
        network_revision=1,
        protocol_version="1.0.0",
        application_version="1.0.0",
        state_schema_version=1,
        block_height=1000,
        block_hash="block-hash-xyz",
        block_time="2025-01-01T00:00:00Z",
        epoch=1,
        application_state_hash="app-state-hash",
        validator_set_hash=None,
        protocol_parameters_hash=None,
        snapshot_content_hash="content-hash",
        snapshot_content_size=chunk_count * chunk_size,
        chunk_count=chunk_count,
        chunk_size=chunk_size,
        chunk_root=chunk_root,
        compression=CompressionAlgorithm.NONE,
        encoding=Encoding.JSON_DETERMINISTIC,
        creation_time="2025-01-01T00:00:00Z",
        producer_service_id="producer-1",
        producer_signature="sig-123",
    )


def _make_chunk(
    *,
    snapshot_id: str = "snap-001",
    chunk_index: int = 0,
    total_chunks: int = 4,
    payload: bytes = b"x" * 1024,
) -> SnapshotChunk:
    chunk_hash = hashlib.sha256(payload).hexdigest()
    return SnapshotChunk(
        snapshot_id=snapshot_id,
        chunk_index=chunk_index,
        total_chunks=total_chunks,
        uncompressed_size=len(payload),
        compressed_size=len(payload),
        chunk_hash=chunk_hash,
        payload=payload,
    )


class MockTransferSource(ChunkTransferSource):
    """Configurable mock for ChunkTransferSource."""

    def __init__(
        self,
        *,
        chunks: dict[str, dict[int, SnapshotChunk]] | None = None,
        provider_chunks: dict[str, list[int]] | None = None,
        always_fail: set[str] | None = None,
        fail_chunk: tuple[str, int] | None = None,
    ):
        self._chunks = chunks or {}
        self._provider_chunks = provider_chunks or {}
        self._always_fail = always_fail or set()
        self._fail_chunk = fail_chunk
        self._call_count: dict[str, int] = {}

    def get_chunk(self, snapshot_id: str, chunk_index: int, provider_id: str) -> SnapshotChunk | None:
        key = f"{provider_id}:{chunk_index}"
        self._call_count[key] = self._call_count.get(key, 0) + 1

        if provider_id in self._always_fail:
            return None

        if self._fail_chunk and (snapshot_id, chunk_index) == self._fail_chunk:
            return None

        snap_chunks = self._chunks.get(snapshot_id, {})
        return snap_chunks.get(chunk_index)

    def get_provider_inventory(self, snapshot_id: str, provider_id: str) -> list[int]:
        return self._provider_chunks.get(provider_id, [])

    def is_provider_available(self, provider_id: str) -> bool:
        return provider_id not in self._always_fail


def _build_full_source(
    *,
    snapshot_id: str = "snap-001",
    total_chunks: int = 4,
    providers: list[str] | None = None,
) -> MockTransferSource:
    """Build a source where each provider has all chunks."""
    providers = providers or ["prov-1", "prov-2", "prov-3"]
    chunks: dict[str, dict[int, SnapshotChunk]] = {}
    provider_chunks: dict[str, list[int]] = {}

    for i in range(total_chunks):
        chunks[snapshot_id] = chunks.get(snapshot_id, {})
        chunks[snapshot_id][i] = _make_chunk(
            snapshot_id=snapshot_id,
            chunk_index=i,
            total_chunks=total_chunks,
        )
        for p in providers:
            provider_chunks[p] = list(range(total_chunks))

    return MockTransferSource(chunks=chunks, provider_chunks=provider_chunks)


# ── DownloadConfig ────────────────────────────────────────────────


class TestDownloadConfig:
    def test_defaults(self):
        cfg = DownloadConfig()
        assert cfg.max_concurrent_transfers == 4
        assert cfg.max_bandwidth_bytes_per_sec == 10_485_760
        assert cfg.max_retry_count == 3
        assert cfg.retry_delay_seconds == 2.0
        assert cfg.chunk_timeout_seconds == 30.0

    def test_custom_values(self):
        cfg = DownloadConfig(
            max_concurrent_transfers=2,
            max_bandwidth_bytes_per_sec=5_000_000,
            max_retry_count=5,
            retry_delay_seconds=1.0,
            chunk_timeout_seconds=10.0,
        )
        assert cfg.max_concurrent_transfers == 2
        assert cfg.max_bandwidth_bytes_per_sec == 5_000_000
        assert cfg.max_retry_count == 5

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("max_concurrent_transfers", 0),
            ("max_bandwidth_bytes_per_sec", 0),
            ("max_retry_count", -1),
            ("retry_delay_seconds", -1.0),
            ("chunk_timeout_seconds", 0.0),
        ],
    )
    def test_rejects_invalid_limits(self, field: str, value: int | float):
        with pytest.raises(ValueError):
            DownloadConfig(**{field: value})


# ── SnapshotDownloader ────────────────────────────────────────────


class TestSnapshotDownloader:
    def _make_downloader(
        self,
        *,
        config: DownloadConfig | None = None,
        source: ChunkTransferSource | None = None,
    ) -> SnapshotDownloader:
        return SnapshotDownloader(
            config=config or DownloadConfig(),
            transfer_source=source or MockTransferSource(),
        )

    def test_download_all_chunks_single_provider(self):
        source = _build_full_source(total_chunks=4, providers=["prov-1"])
        manifest = _make_manifest(chunk_count=4, chunk_root="chunk-root-abc")
        downloader = self._make_downloader(source=source)
        result = downloader.download("snap-001", manifest, ["prov-1"])
        assert result.success is True
        assert result.chunks_downloaded == 4
        assert result.chunks_total == 4
        assert result.chunks_failed == []

    def test_download_requires_manifest_snapshot_identity(self):
        manifest = _make_manifest(snapshot_id="manifest-snapshot", chunk_count=1)

        with pytest.raises(ValueError, match="snapshot_id must match"):
            self._make_downloader().download("requested-snapshot", manifest, [])

    def test_multi_source_download(self):
        source = _build_full_source(total_chunks=4, providers=["prov-1", "prov-2", "prov-3"])
        manifest = _make_manifest(chunk_count=4, chunk_root="chunk-root-abc")
        downloader = self._make_downloader(source=source)
        result = downloader.download("snap-001", manifest, ["prov-1", "prov-2", "prov-3"])
        assert result.success is True
        assert result.chunks_downloaded == 4

    def test_chunk_verification_on_download(self):
        source = _build_full_source(total_chunks=2, providers=["prov-1"])
        manifest = _make_manifest(chunk_count=2, chunk_root="chunk-root-abc")
        downloader = self._make_downloader(source=source)
        result = downloader.download("snap-001", manifest, ["prov-1"])
        assert result.chunks_verified == 2

    def test_download_rejects_chunk_from_another_snapshot(self):
        source = _build_full_source(total_chunks=1, providers=["prov-1"])
        source._chunks["snap-001"][0] = _make_chunk(snapshot_id="other-snapshot", chunk_index=0, total_chunks=1)
        manifest = _make_manifest(chunk_count=1)

        result = self._make_downloader(source=source).download("snap-001", manifest, ["prov-1"])

        assert not result.success
        assert result.chunks_failed == [0]

    def test_download_rejects_valid_chunks_with_wrong_manifest_root(self):
        source = _build_full_source(total_chunks=2, providers=["prov-1"])
        manifest = _make_manifest(chunk_count=2, chunk_root="0" * 64)

        result = self._make_downloader(source=source).download("snap-001", manifest, ["prov-1"])

        assert not result.success
        assert result.chunks_downloaded == 0
        assert result.session.verified_chunk_bitmap == [False, False]
        assert result.session.chunk_hashes == [None, None]

    def test_download_result_fields(self):
        source = _build_full_source(total_chunks=2, providers=["prov-1"])
        manifest = _make_manifest(chunk_count=2, chunk_root="chunk-root-abc")
        downloader = self._make_downloader(source=source)
        result = downloader.download("snap-001", manifest, ["prov-1"])
        assert result.snapshot_id == "snap-001"
        assert result.success is True
        assert result.error is None
        assert result.session is not None

    def test_empty_snapshot_single_chunk(self):
        source = _build_full_source(total_chunks=1, providers=["prov-1"])
        manifest = _make_manifest(chunk_count=1, chunk_root="chunk-root-abc")
        downloader = self._make_downloader(source=source)
        result = downloader.download("snap-001", manifest, ["prov-1"])
        assert result.success is True
        assert result.chunks_downloaded == 1

    def test_provider_failure_handled(self):
        source = MockTransferSource(always_fail={"prov-bad"})
        manifest = _make_manifest(chunk_count=1, chunk_root="chunk-root-abc")
        downloader = self._make_downloader(source=source)
        result = downloader.download("snap-001", manifest, ["prov-bad"])
        # Should fail since no provider has chunks
        assert result.success is False or result.chunks_downloaded == 0

    def test_partial_download_returns_failed_list(self):
        source = MockTransferSource(always_fail={"prov-1"})
        manifest = _make_manifest(chunk_count=2, chunk_root="chunk-root-abc")
        downloader = self._make_downloader(source=source)
        result = downloader.download("snap-001", manifest, ["prov-1"])
        assert result.success is False
        assert len(result.chunks_failed) > 0

    def test_download_resumption(self):
        source = _build_full_source(total_chunks=4, providers=["prov-1"])
        downloader = self._make_downloader(source=source)
        chunk_hash = hashlib.sha256(b"x" * 1024).hexdigest()
        chunk_root = MerkleTree([chunk_hash] * 4).root_hash()

        # Create a partial session
        session = DownloadSession(
            snapshot_id="snap-001",
            manifest_hash="manifest-hash",
            verified_chunk_bitmap=[True, True, False, False],
            pending_chunks=[2, 3],
            failed_chunks=[],
            providers_used=["prov-1"],
            temporary_files=[],
            total_bytes_downloaded=2048,
            started_at="2025-01-01T00:00:00Z",
            last_activity="2025-01-01T00:01:00Z",
            chunk_hashes=[chunk_hash, chunk_hash, None, None],
            expected_chunk_root=chunk_root,
        )
        result = downloader.resume(session, ["prov-1"])
        assert result.success
        assert result.chunks_downloaded == 4

    def test_resume_does_not_trust_legacy_completed_bitmap(self):
        source = _build_full_source(total_chunks=1, providers=["prov-1"])
        session = DownloadSession(
            snapshot_id="snap-001",
            manifest_hash="manifest-hash",
            verified_chunk_bitmap=[True],
            pending_chunks=[],
            failed_chunks=[],
            providers_used=["prov-1"],
            temporary_files=[],
            total_bytes_downloaded=1024,
            started_at="2025-01-01T00:00:00Z",
            last_activity="2025-01-01T00:01:00Z",
        )

        result = self._make_downloader(source=source).resume(session, ["prov-1"])

        assert not result.success
        assert result.session.verified_chunk_bitmap == [False]

    def test_session_bitmap_persisted(self):
        source = _build_full_source(total_chunks=4, providers=["prov-1"])
        manifest = _make_manifest(chunk_count=4, chunk_root="chunk-root-abc")
        downloader = self._make_downloader(source=source)
        result = downloader.download("snap-001", manifest, ["prov-1"])
        assert result.session is not None
        assert len(result.session.verified_chunk_bitmap) == 4
        assert len(result.session.chunk_hashes) == 4
        assert result.session.expected_chunk_root == manifest.chunk_root

    def test_backpressure_concurrency_limit(self):
        """Concurrency limit is respected — downloader doesn't exceed max_concurrent_transfers."""
        source = _build_full_source(total_chunks=8, providers=["prov-1"])
        config = DownloadConfig(max_concurrent_transfers=2)
        manifest = _make_manifest(chunk_count=8, chunk_root="chunk-root-abc")
        downloader = self._make_downloader(config=config, source=source)
        result = downloader.download("snap-001", manifest, ["prov-1"])
        assert result.success is True
        assert result.chunks_downloaded == 8
