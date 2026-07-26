"""M10-S8: Integration + E2E Tests — Full Snapshot Pipeline.

Covers the complete snapshot lifecycle:
  produce → distribute → discover → download → verify → restore → activate → replay

Mock infrastructure:
  MockRegistrySource, MockChunkTransferSource, MockBlockSource
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import pytest

# ── Snapshot module imports ────────────────────────────────────────

from aidn_hypervisor.snapshot.models import (
    CompressionAlgorithm,
    Encoding,
    SnapshotChunk,
    SnapshotManifest,
    SnapshotType,
    compute_snapshot_id,
)
from aidn_hypervisor.snapshot.producer import (
    ProduceResult,
    SnapshotProducer,
    SnapshotProducerConfig,
)
from aidn_hypervisor.snapshot.encoding import (
    PortableSnapshotEncoder,
    STATE_NAMESPACES,
)
from aidn_hypervisor.snapshot.chunking import Chunker, MerkleTree
from aidn_hypervisor.snapshot.compression import CompressionHandler
from aidn_hypervisor.snapshot.discovery import (
    SnapshotAvailability,
    SnapshotCandidate,
    SnapshotDiscovery,
    SnapshotRegistrySource,
    SnapshotSelector,
)
from aidn_hypervisor.snapshot.download import (
    ChunkTransferSource,
    DownloadConfig,
    DownloadPlanner,
    DownloadResult,
    DownloadSession,
    SnapshotDownloader,
)
from aidn_hypervisor.snapshot.staging import (
    RestorationResult,
    StateRestorer,
    StagingStateStore,
)
from aidn_hypervisor.snapshot.verification import (
    InvariantCheckResult,
    InvariantChecker,
    SnapshotVerifier,
    VerificationResult,
)
from aidn_hypervisor.snapshot.activation import (
    ActivationRecord,
    ActivationResult,
    ActivationState,
    AtomicActivator,
)
from aidn_hypervisor.snapshot.replay import (
    BlockReplayer,
    BlockSource,
    ReplayBlock,
    ReplayConfig,
    ReplayResult,
)

# ── Constants ──────────────────────────────────────────────────────

SIGNING_KEY = b"integration-test-signing-key-42bytes!!"
CHAIN_ID = "aidn-mainnet"
NETWORK_ID = "aidn"
PROTOCOL_VERSION = "1.0.0"
APPLICATION_VERSION = "0.1.0"
STATE_SCHEMA_VERSION = 1
FORMAT_VERSION = 1
EPOCH = 1
BLOCK_HEIGHT = 100
BLOCK_HASH = "0x" + "ab" * 32
BLOCK_TIME = "2025-01-01T00:00:00Z"
PRODUCER_ID = "producer-01"

# ── Sample State Data ─────────────────────────────────────────────

SAMPLE_STATE: dict[str, Any] = {
    "wallets": [
        {"id": "wallet_1", "balance": 1000, "locked": 200, "sequence": 5},
        {"id": "wallet_2", "balance": 2000, "locked": 0, "sequence": 3},
    ],
    "hypervisors": [
        {"id": "hv_1", "status": "active", "endpoint_id": "ep_1"},
    ],
    "endpoints": [
        {"id": "ep_1", "model_id": "llama3", "status": "verified"},
    ],
    "stakes": [
        {"id": "stake_1", "wallet_id": "wallet_1", "amount": 500},
    ],
    "bonds": [],
    "sessions": [],
    "certifications": [],
    "reputation": [],
    "epochs": [{"current": 1, "block_height": 100}],
    "protocol_parameters": {"version": "1.0.0", "max_gas": 1000000},
    "evidence": [],
}


# ── Mock Infrastructure ───────────────────────────────────────────

class MockRegistrySource(SnapshotRegistrySource):
    """In-memory registry source for integration tests."""

    def __init__(self) -> None:
        self._manifests: list[SnapshotManifest] = []
        self._provider_map: dict[str, list[str]] = {}

    def register_snapshot(
        self,
        manifest: SnapshotManifest,
        providers: list[str],
    ) -> None:
        """Register a snapshot with its provider list."""
        self._manifests.append(manifest)
        self._provider_map[manifest.snapshot_id] = providers

    def query_snapshots(self) -> list[SnapshotManifest]:
        return list(self._manifests)

    def get_provider_inventory(self, snapshot_id: str) -> list[str]:
        return list(self._provider_map.get(snapshot_id, []))


class MockChunkTransferSource(ChunkTransferSource):
    """In-memory chunk transfer source for integration tests.

    Stores chunks per provider and simulates availability.
    """

    def __init__(self) -> None:
        # snapshot_id -> provider_id -> {chunk_index -> SnapshotChunk}
        self._store: dict[str, dict[str, dict[int, SnapshotChunk]]] = {}
        # provider_id -> bool (availability flag)
        self._availability: dict[str, bool] = {}

    def store_chunks(
        self,
        snapshot_id: str,
        provider_id: str,
        chunks: list[SnapshotChunk],
    ) -> None:
        """Store chunks for a provider."""
        if snapshot_id not in self._store:
            self._store[snapshot_id] = {}
        if provider_id not in self._store[snapshot_id]:
            self._store[snapshot_id][provider_id] = {}
        for c in chunks:
            self._store[snapshot_id][provider_id][c.chunk_index] = c
        self._availability[provider_id] = True

    def set_provider_available(self, provider_id: str, available: bool) -> None:
        self._availability[provider_id] = available

    def get_chunk(
        self,
        snapshot_id: str,
        chunk_index: int,
        provider_id: str,
    ) -> SnapshotChunk | None:
        snap = self._store.get(snapshot_id)
        if snap is None:
            return None
        prov = snap.get(provider_id)
        if prov is None:
            return None
        return prov.get(chunk_index)

    def get_provider_inventory(
        self,
        snapshot_id: str,
        provider_id: str,
    ) -> list[int]:
        snap = self._store.get(snapshot_id)
        if snap is None:
            return []
        prov = snap.get(provider_id)
        if prov is None:
            return []
        return sorted(prov.keys())

    def is_provider_available(self, provider_id: str) -> bool:
        return self._availability.get(provider_id, False)


class MockBlockSource(BlockSource):
    """In-memory block source for integration tests.

    Stores pre-computed ReplayBlocks with expected state hashes.
    execute_block() applies a deterministic transformation to state.
    """

    def __init__(
        self,
        blocks: list[ReplayBlock],
        finalized_height: int,
    ) -> None:
        self._blocks: dict[int, ReplayBlock] = {
            b.block_height: b for b in blocks
        }
        self._finalized_height = finalized_height

    def get_block(self, height: int) -> ReplayBlock | None:
        return self._blocks.get(height)

    def get_finalized_height(self) -> int:
        return self._finalized_height

    def get_state_at_height(self, height: int) -> dict | None:
        return None  # Not needed for integration tests

    def execute_block(self, state: dict, block: ReplayBlock) -> dict:
        """Apply block: advance height, update state hash, carry extras."""
        new_state = dict(state)
        new_state["height"] = block.block_height
        new_state["last_block_hash"] = block.block_hash
        new_state["state_hash"] = block.application_state_hash
        if block.validator_set_hash:
            new_state["validator_set_hash"] = block.validator_set_hash
        return new_state


# ── Helpers ────────────────────────────────────────────────────────

def _produce_snapshot() -> ProduceResult:
    """Produce a snapshot from SAMPLE_STATE using default producer config."""
    config = SnapshotProducerConfig(
        chunk_size=4096,
        compression=CompressionAlgorithm.NONE,  # simpler for integration tests
    )
    producer = SnapshotProducer(config=config, signing_key=SIGNING_KEY)
    return producer.produce(
        state=SAMPLE_STATE,
        block_height=BLOCK_HEIGHT,
        block_hash=BLOCK_HASH,
        block_time=BLOCK_TIME,
        epoch=EPOCH,
        chain_id=CHAIN_ID,
        network_id=NETWORK_ID,
        network_revision=1,
        protocol_version=PROTOCOL_VERSION,
        application_version=APPLICATION_VERSION,
        state_schema_version=STATE_SCHEMA_VERSION,
        producer_service_id=PRODUCER_ID,
    )


def _produce_multi_chunk_snapshot(num_chunks: int = 4) -> ProduceResult:
    """Produce a snapshot with multiple chunks for resumption tests."""
    chunk_size = max(64, len(json.dumps(SAMPLE_STATE)) // num_chunks)
    config = SnapshotProducerConfig(
        chunk_size=chunk_size,
        compression=CompressionAlgorithm.NONE,
    )
    producer = SnapshotProducer(config=config, signing_key=SIGNING_KEY)
    return producer.produce(
        state=SAMPLE_STATE,
        block_height=BLOCK_HEIGHT,
        block_hash=BLOCK_HASH,
        block_time=BLOCK_TIME,
        epoch=EPOCH,
        chain_id=CHAIN_ID,
        network_id=NETWORK_ID,
        network_revision=1,
        protocol_version=PROTOCOL_VERSION,
        application_version=APPLICATION_VERSION,
        state_schema_version=STATE_SCHEMA_VERSION,
        producer_service_id=PRODUCER_ID,
    )


def _make_replay_blocks(
    start_height: int,
    end_height: int,
) -> list[ReplayBlock]:
    """Create deterministic ReplayBlocks for heights start..end."""
    blocks: list[ReplayBlock] = []
    for h in range(start_height, end_height + 1):
        state_hash = hashlib.sha256(f"state-after-{h}".encode()).hexdigest()
        blocks.append(
            ReplayBlock(
                block_height=h,
                block_hash=hashlib.sha256(f"block-{h}".encode()).hexdigest(),
                application_state_hash=state_hash,
                validator_set_hash=hashlib.sha256(
                    f"validator-set-{h}".encode()
                ).hexdigest(),
                timestamp=f"2025-01-01T00:00:{h:02d}Z",
            )
        )
    return blocks


# ═══════════════════════════════════════════════════════════════════
# Class 1: TestSnapshotProduction (~5 tests)
# ═══════════════════════════════════════════════════════════════════

class TestSnapshotProduction:
    """Producer creates snapshot from sample state data."""

    def test_produce_creates_snapshot(self) -> None:
        """Producer creates snapshot from sample state data."""
        result = _produce_snapshot()
        assert isinstance(result, ProduceResult)
        assert result.manifest is not None
        assert len(result.chunks) > 0

    def test_manifest_fields_populated(self) -> None:
        """Manifest fields populated correctly from produce inputs."""
        result = _produce_snapshot()
        m = result.manifest
        assert m.chain_id == CHAIN_ID
        assert m.network_id == NETWORK_ID
        assert m.block_height == BLOCK_HEIGHT
        assert m.block_hash == BLOCK_HASH
        assert m.epoch == EPOCH
        assert m.protocol_version == PROTOCOL_VERSION
        assert m.application_version == APPLICATION_VERSION
        assert m.state_schema_version == STATE_SCHEMA_VERSION
        assert m.producer_service_id == PRODUCER_ID
        assert m.snapshot_type == SnapshotType.FULL_STATE
        assert m.snapshot_format_version == FORMAT_VERSION

    def test_chunks_created_with_correct_count(self) -> None:
        """Chunks created with correct count matching manifest."""
        result = _produce_snapshot()
        assert len(result.chunks) == result.manifest.chunk_count
        for c in result.chunks:
            assert c.total_chunks == result.manifest.chunk_count

    def test_chunk_root_computed_correctly(self) -> None:
        """Chunk root computed correctly via MerkleTree."""
        result = _produce_snapshot()
        leaf_hashes = [c.chunk_hash for c in result.chunks]
        computed_root = MerkleTree(leaf_hashes).root_hash()
        assert computed_root == result.manifest.chunk_root

    def test_local_restoration_verification_passes(self) -> None:
        """Local restoration verification passes (no exception raised)."""
        # The producer already runs local restoration verification
        # in produce(). If we reach here, it passed.
        result = _produce_snapshot()
        assert result.content_hash != ""
        assert result.content_size > 0


# ═══════════════════════════════════════════════════════════════════
# Class 2: TestSnapshotDistribution (~4 tests)
# ═══════════════════════════════════════════════════════════════════

class TestSnapshotDistribution:
    """Produced chunks stored in mock registry source."""

    def test_chunks_stored_in_mock_registry(self) -> None:
        """Produced chunks can be stored in a mock registry source."""
        result = _produce_snapshot()
        registry = MockRegistrySource()
        registry.register_snapshot(
            manifest=result.manifest,
            providers=["provider-A", "provider-B", "provider-C"],
        )
        manifests = registry.query_snapshots()
        assert len(manifests) == 1
        assert manifests[0].snapshot_id == result.manifest.snapshot_id

    def test_availability_metadata_recorded(self) -> None:
        """Availability metadata recorded in registry."""
        result = _produce_snapshot()
        registry = MockRegistrySource()
        registry.register_snapshot(
            manifest=result.manifest,
            providers=["provider-A", "provider-B", "provider-C"],
        )
        providers = registry.get_provider_inventory(result.manifest.snapshot_id)
        assert len(providers) == 3
        assert "provider-A" in providers
        assert "provider-B" in providers
        assert "provider-C" in providers

    def test_provider_inventory_returns_correct_indices(self) -> None:
        """Provider inventory returns correct chunk indices."""
        result = _produce_snapshot()
        transfer = MockChunkTransferSource()
        transfer.store_chunks(
            result.manifest.snapshot_id,
            "provider-A",
            result.chunks,
        )
        indices = transfer.get_provider_inventory(
            result.manifest.snapshot_id, "provider-A"
        )
        assert indices == list(range(len(result.chunks)))

    def test_multiple_providers_serve_same_snapshot(self) -> None:
        """Multiple providers can serve same snapshot."""
        result = _produce_snapshot()
        transfer = MockChunkTransferSource()
        for prov in ["provider-A", "provider-B", "provider-C"]:
            transfer.store_chunks(
                result.manifest.snapshot_id, prov, result.chunks
            )
        for prov in ["provider-A", "provider-B", "provider-C"]:
            indices = transfer.get_provider_inventory(
                result.manifest.snapshot_id, prov
            )
            assert len(indices) == len(result.chunks)


# ═══════════════════════════════════════════════════════════════════
# Class 3: TestSnapshotDiscovery (~4 tests)
# ═══════════════════════════════════════════════════════════════════

class TestSnapshotDiscovery:
    """Discovery finds snapshots from registry."""

    def test_discovery_finds_snapshots(self) -> None:
        """Discovery finds snapshots from registry."""
        result = _produce_snapshot()
        registry = MockRegistrySource()
        registry.register_snapshot(
            manifest=result.manifest,
            providers=["p1", "p2", "p3"],
        )
        discovery = SnapshotDiscovery(registry)
        results = discovery.discover_snapshots()
        assert len(results) == 1
        assert results[0].snapshot_id == result.manifest.snapshot_id

    def test_selector_picks_highest_scored(self) -> None:
        """Selector picks highest-scored suitable candidate."""
        result = _produce_snapshot()
        registry = MockRegistrySource()
        registry.register_snapshot(
            manifest=result.manifest,
            providers=["p1", "p2", "p3"],
        )
        discovery = SnapshotDiscovery(registry)
        avail = discovery.discover_snapshots()

        candidates: list[SnapshotCandidate] = []
        for a in avail:
            candidates.append(
                SnapshotCandidate(
                    manifest=result.manifest,
                    availability=a,
                    score=0.0,
                    suitable=True,
                    rejection_reasons=[],
                )
            )

        selector = SnapshotSelector(
            chain_id=CHAIN_ID,
            protocol_version=PROTOCOL_VERSION,
            state_schema_versions=[STATE_SCHEMA_VERSION],
            min_provider_groups=3,
        )
        chosen = selector.select(candidates, finalized_height=200)
        assert chosen is not None
        assert chosen.suitable is True
        assert chosen.score > 0.0

    def test_selector_rejects_wrong_chain(self) -> None:
        """Selector rejects wrong chain/protocol/schema."""
        result = _produce_snapshot()
        registry = MockRegistrySource()
        registry.register_snapshot(
            manifest=result.manifest,
            providers=["p1", "p2", "p3"],
        )
        discovery = SnapshotDiscovery(registry)
        avail = discovery.discover_snapshots()

        candidates: list[SnapshotCandidate] = []
        for a in avail:
            candidates.append(
                SnapshotCandidate(
                    manifest=result.manifest,
                    availability=a,
                    score=0.0,
                    suitable=True,
                    rejection_reasons=[],
                )
            )

        # Selector configured for a different chain
        selector = SnapshotSelector(
            chain_id="wrong-chain",
            protocol_version=PROTOCOL_VERSION,
            state_schema_versions=[STATE_SCHEMA_VERSION],
            min_provider_groups=3,
        )
        chosen = selector.select(candidates, finalized_height=200)
        assert chosen is None

    def test_provider_diversity_requirement_enforced(self) -> None:
        """Provider diversity requirement enforced."""
        result = _produce_snapshot()
        registry = MockRegistrySource()
        # Only 1 provider — below min_provider_groups=3
        registry.register_snapshot(
            manifest=result.manifest,
            providers=["only-provider"],
        )
        discovery = SnapshotDiscovery(registry)
        avail = discovery.discover_snapshots()

        candidates: list[SnapshotCandidate] = []
        for a in avail:
            candidates.append(
                SnapshotCandidate(
                    manifest=result.manifest,
                    availability=a,
                    score=0.0,
                    suitable=True,
                    rejection_reasons=[],
                )
            )

        selector = SnapshotSelector(
            chain_id=CHAIN_ID,
            protocol_version=PROTOCOL_VERSION,
            state_schema_versions=[STATE_SCHEMA_VERSION],
            min_provider_groups=3,
        )
        chosen = selector.select(candidates, finalized_height=200)
        assert chosen is None


# ═══════════════════════════════════════════════════════════════════
# Class 4: TestSnapshotDownload (~5 tests)
# ═══════════════════════════════════════════════════════════════════

class TestSnapshotDownload:
    """Download retrieves all chunks from providers."""

    def test_download_retrieves_all_chunks(self) -> None:
        """Download retrieves all chunks from providers."""
        result = _produce_snapshot()
        transfer = MockChunkTransferSource()
        transfer.store_chunks(
            result.manifest.snapshot_id,
            "provider-A",
            result.chunks,
        )
        downloader = SnapshotDownloader(
            config=DownloadConfig(),
            transfer_source=transfer,
        )
        dl_result = downloader.download(
            result.manifest.snapshot_id,
            result.manifest,
            ["provider-A"],
        )
        assert dl_result.success is True
        assert dl_result.chunks_downloaded == result.manifest.chunk_count
        assert dl_result.chunks_failed == []

    def test_multi_source_download_distributes(self) -> None:
        """Multi-source download distributes across providers."""
        result = _produce_snapshot()
        transfer = MockChunkTransferSource()

        # Split chunks: provider-A gets even indices, provider-B gets odd
        even_chunks = [c for c in result.chunks if c.chunk_index % 2 == 0]
        odd_chunks = [c for c in result.chunks if c.chunk_index % 2 == 1]
        transfer.store_chunks(
            result.manifest.snapshot_id, "provider-A", even_chunks
        )
        transfer.store_chunks(
            result.manifest.snapshot_id, "provider-B", odd_chunks
        )

        downloader = SnapshotDownloader(
            config=DownloadConfig(),
            transfer_source=transfer,
        )
        dl_result = downloader.download(
            result.manifest.snapshot_id,
            result.manifest,
            ["provider-A", "provider-B"],
        )
        assert dl_result.success is True
        assert dl_result.chunks_downloaded == result.manifest.chunk_count

    def test_chunk_verification_during_download(self) -> None:
        """Chunk verification during download — bad chunk rejected."""
        result = _produce_snapshot()
        transfer = MockChunkTransferSource()

        # Store a corrupted chunk (wrong hash)
        bad_chunks = list(result.chunks)
        bad_chunk = SnapshotChunk(
            snapshot_id=result.chunks[0].snapshot_id,
            chunk_index=0,
            total_chunks=result.chunks[0].total_chunks,
            uncompressed_size=100,
            compressed_size=100,
            chunk_hash="00" * 32,  # wrong hash
            payload=b"bad data",
        )
        bad_chunks[0] = bad_chunk
        transfer.store_chunks(
            result.manifest.snapshot_id, "provider-A", bad_chunks
        )

        # But provider-B has good chunks
        transfer.store_chunks(
            result.manifest.snapshot_id, "provider-B", result.chunks
        )

        downloader = SnapshotDownloader(
            config=DownloadConfig(),
            transfer_source=transfer,
        )
        dl_result = downloader.download(
            result.manifest.snapshot_id,
            result.manifest,
            ["provider-A", "provider-B"],
        )
        # Should succeed by falling back to provider-B for chunk 0
        assert dl_result.success is True

    def test_download_resumption_after_partial_failure(self) -> None:
        """Download resumption after partial failure."""
        result = _produce_multi_chunk_snapshot(4)
        transfer = MockChunkTransferSource()

        # Initially only provider-A with half the chunks
        half = result.chunks[: len(result.chunks) // 2]
        transfer.store_chunks(
            result.manifest.snapshot_id, "provider-A", half
        )

        downloader = SnapshotDownloader(
            config=DownloadConfig(),
            transfer_source=transfer,
        )
        dl_result = downloader.download(
            result.manifest.snapshot_id,
            result.manifest,
            ["provider-A"],
        )
        # Partial download: some chunks missing
        assert dl_result.chunks_downloaded < result.manifest.chunk_count

        # Now add provider-B with all chunks
        transfer.store_chunks(
            result.manifest.snapshot_id, "provider-B", result.chunks
        )

        # Resume
        resume_result = downloader.resume(
            dl_result.session,
            ["provider-A", "provider-B"],
        )
        assert resume_result.success is True
        assert resume_result.chunks_downloaded == result.manifest.chunk_count

    def test_session_bitmap_persisted(self) -> None:
        """Session bitmap persisted correctly."""
        result = _produce_snapshot()
        transfer = MockChunkTransferSource()
        transfer.store_chunks(
            result.manifest.snapshot_id,
            "provider-A",
            result.chunks,
        )
        downloader = SnapshotDownloader(
            config=DownloadConfig(),
            transfer_source=transfer,
        )
        dl_result = downloader.download(
            result.manifest.snapshot_id,
            result.manifest,
            ["provider-A"],
        )
        session = dl_result.session
        assert len(session.verified_chunk_bitmap) == result.manifest.chunk_count
        assert all(session.verified_chunk_bitmap)
        assert session.snapshot_id == result.manifest.snapshot_id


# ═══════════════════════════════════════════════════════════════════
# Class 5: TestStagingRestoration (~5 tests)
# ═══════════════════════════════════════════════════════════════════

class TestStagingRestoration:
    """Downloaded chunks reassembled and decompressed."""

    def test_chunks_reassembled_and_decompressed(self) -> None:
        """Downloaded chunks reassembled and decompressed."""
        result = _produce_snapshot()
        chunker = Chunker(chunk_size=4096)
        compressor = CompressionHandler()

        reassembled = chunker.reassemble(result.chunks)
        decompressed = compressor.decompress(
            reassembled, result.manifest.compression
        )
        assert isinstance(decompressed, bytes)
        assert len(decompressed) > 0

    def test_staging_state_restored_from_encoded_data(self) -> None:
        """Staging state restored from encoded data."""
        result = _produce_snapshot()
        chunker = Chunker(chunk_size=4096)
        compressor = CompressionHandler()

        reassembled = chunker.reassemble(result.chunks)
        encoded_data = compressor.decompress(
            reassembled, result.manifest.compression
        )

        staging = StagingStateStore()
        restorer = StateRestorer(staging)
        restore_result = restorer.restore(encoded_data)

        assert restore_result.success is True
        assert len(restore_result.namespaces_loaded) > 0
        assert restore_result.total_objects > 0

    def test_application_state_hash_matches_manifest(self) -> None:
        """Application state hash matches manifest."""
        result = _produce_snapshot()
        chunker = Chunker(chunk_size=4096)
        compressor = CompressionHandler()

        reassembled = chunker.reassemble(result.chunks)
        encoded_data = compressor.decompress(
            reassembled, result.manifest.compression
        )

        # Compute expected hash from encoded data
        expected_hash = hashlib.sha256(encoded_data).hexdigest()
        assert expected_hash == result.manifest.application_state_hash

    def test_invariant_checks_pass_on_valid_state(self) -> None:
        """Invariant checks pass on valid state."""
        result = _produce_snapshot()
        chunker = Chunker(chunk_size=4096)
        compressor = CompressionHandler()

        reassembled = chunker.reassemble(result.chunks)
        encoded_data = compressor.decompress(
            reassembled, result.manifest.compression
        )

        staging = StagingStateStore()
        restorer = StateRestorer(staging)
        restorer.restore(encoded_data)

        checker = InvariantChecker()
        inv_result = checker.check_all(staging)
        assert inv_result.valid is True
        assert inv_result.checks_passed == inv_result.checks_performed

    def test_invariant_checks_detect_violations(self) -> None:
        """Invariant checks detect violations."""
        staging = StagingStateStore()
        # Load wallets with negative balance
        staging.load_namespace("wallets", [
            {"id": "w1", "balance": -100, "locked": 0, "sequence": 1},
        ])
        staging.load_namespace("protocol_parameters", {
            "version": "1.0.0",
        })

        checker = InvariantChecker()
        inv_result = checker.check_all(staging)
        assert inv_result.valid is False
        assert len(inv_result.violations) > 0


# ═══════════════════════════════════════════════════════════════════
# Class 6: TestAtomicActivation (~4 tests)
# ═══════════════════════════════════════════════════════════════════

class TestAtomicActivation:
    """Verified staging state activated atomically."""

    def test_verified_staging_activated_atomically(self) -> None:
        """Verified staging state activated atomically."""
        result = _produce_snapshot()
        chunker = Chunker(chunk_size=4096)
        compressor = CompressionHandler()

        reassembled = chunker.reassemble(result.chunks)
        encoded_data = compressor.decompress(
            reassembled, result.manifest.compression
        )

        staging = StagingStateStore()
        restorer = StateRestorer(staging)
        restorer.restore(encoded_data)

        expected_hash = staging.calculate_state_hash()
        activator = AtomicActivator()
        ready = activator.prepare(staging, expected_hash)
        assert ready is True
        assert activator.state == ActivationState.READY

        act_result = activator.activate()
        assert act_result.success is True
        assert activator.state == ActivationState.ACTIVATED
        assert act_result.new_state_hash == expected_hash

    def test_previous_state_preserved_until_activation(self) -> None:
        """Previous state preserved until activation succeeds."""
        activator = AtomicActivator()
        # Set a fake previous active state hash
        activator._active_state_hash = "previous-hash-123"

        staging = StagingStateStore()
        staging.load_namespace("wallets", [
            {"id": "w1", "balance": 100, "locked": 0, "sequence": 1},
        ])
        staging.load_namespace("protocol_parameters", {"version": "1.0.0"})

        expected_hash = staging.calculate_state_hash()
        activator.prepare(staging, expected_hash)
        act_result = activator.activate()

        assert act_result.previous_state_hash == "previous-hash-123"
        assert act_result.success is True

    def test_activation_failure_triggers_rollback(self) -> None:
        """Activation failure triggers rollback."""
        activator = AtomicActivator()
        activator._active_state_hash = "original-hash"

        # Try to activate without prepare (state is IDLE, not READY)
        act_result = activator.activate()
        assert act_result.success is False
        assert activator.state == ActivationState.FAILED

        # Rollback restores original state
        activator.rollback()
        assert activator.state == ActivationState.IDLE
        assert activator.active_state_hash == "original-hash"

    def test_activation_history_recorded(self) -> None:
        """Activation history recorded."""
        result = _produce_snapshot()
        chunker = Chunker(chunk_size=4096)
        compressor = CompressionHandler()

        reassembled = chunker.reassemble(result.chunks)
        encoded_data = compressor.decompress(
            reassembled, result.manifest.compression
        )

        staging = StagingStateStore()
        restorer = StateRestorer(staging)
        restorer.restore(encoded_data)

        activator = AtomicActivator()
        expected_hash = staging.calculate_state_hash()
        activator.prepare(staging, expected_hash)
        activator.activate()

        history = activator.get_activation_history()
        assert len(history) == 1
        record = history[0]
        assert record.success is True
        assert record.new_state_hash == expected_hash
        assert record.snapshot_id != ""


# ═══════════════════════════════════════════════════════════════════
# Class 7: TestFullPipeline (~6 tests)
# ═══════════════════════════════════════════════════════════════════

class TestFullPipeline:
    """Complete lifecycle: produce → chunk → store → discover → select →
    download → verify → restore → activate → replay."""

    def test_complete_lifecycle(self) -> None:
        """Complete snapshot lifecycle end-to-end."""
        # 1. Produce
        result = _produce_snapshot()
        assert result.manifest is not None

        # 2. Store in registry + transfer
        registry = MockRegistrySource()
        registry.register_snapshot(
            manifest=result.manifest,
            providers=["p1", "p2", "p3"],
        )
        transfer = MockChunkTransferSource()
        transfer.store_chunks(
            result.manifest.snapshot_id, "p1", result.chunks
        )

        # 3. Discover
        discovery = SnapshotDiscovery(registry)
        avail_list = discovery.discover_snapshots()
        assert len(avail_list) == 1

        # 4. Select
        candidates: list[SnapshotCandidate] = []
        for a in avail_list:
            candidates.append(
                SnapshotCandidate(
                    manifest=result.manifest,
                    availability=a,
                    score=0.0,
                    suitable=True,
                    rejection_reasons=[],
                )
            )
        selector = SnapshotSelector(
            chain_id=CHAIN_ID,
            protocol_version=PROTOCOL_VERSION,
            state_schema_versions=[STATE_SCHEMA_VERSION],
            min_provider_groups=3,
        )
        chosen = selector.select(candidates, finalized_height=200)
        assert chosen is not None

        # 5. Download
        downloader = SnapshotDownloader(
            config=DownloadConfig(),
            transfer_source=transfer,
        )
        dl_result = downloader.download(
            result.manifest.snapshot_id,
            result.manifest,
            ["p1"],
        )
        assert dl_result.success is True

        # 6. Verify
        verifier = SnapshotVerifier()
        verify_result = verifier.verify_complete(
            result.manifest,
            result.chunks,
            canonical_state_hash=result.manifest.application_state_hash,
            decompress=False,
        )
        assert verify_result.valid is True

        # 7. Restore
        chunker = Chunker(chunk_size=4096)
        compressor = CompressionHandler()
        reassembled = chunker.reassemble(result.chunks)
        encoded_data = compressor.decompress(
            reassembled, result.manifest.compression
        )
        staging = StagingStateStore()
        restorer = StateRestorer(staging)
        restore_result = restorer.restore(encoded_data)
        assert restore_result.success is True

        # 8. Activate
        activator = AtomicActivator()
        expected_hash = staging.calculate_state_hash()
        activator.prepare(staging, expected_hash)
        act_result = activator.activate()
        assert act_result.success is True

        # 9. Replay
        replay_blocks = _make_replay_blocks(
            BLOCK_HEIGHT + 1, BLOCK_HEIGHT + 5
        )
        block_source = MockBlockSource(
            blocks=replay_blocks,
            finalized_height=BLOCK_HEIGHT + 5,
        )
        initial_state = {"height": BLOCK_HEIGHT}
        replay_config = ReplayConfig(
            start_height=BLOCK_HEIGHT + 1,
            target_height=BLOCK_HEIGHT + 5,
        )
        replayer = BlockReplayer(replay_config, block_source)
        replay_result = replayer.replay(initial_state)
        assert replay_result.success is True
        assert replay_result.blocks_replayed == 5

    def test_pipeline_with_multi_source_download(self) -> None:
        """Pipeline with multi-source download."""
        result = _produce_snapshot()
        transfer = MockChunkTransferSource()

        # Split chunks across providers
        even_chunks = [c for c in result.chunks if c.chunk_index % 2 == 0]
        odd_chunks = [c for c in result.chunks if c.chunk_index % 2 == 1]
        transfer.store_chunks(
            result.manifest.snapshot_id, "p-A", even_chunks
        )
        transfer.store_chunks(
            result.manifest.snapshot_id, "p-B", odd_chunks
        )
        transfer.store_chunks(
            result.manifest.snapshot_id, "p-C", result.chunks
        )

        downloader = SnapshotDownloader(
            config=DownloadConfig(),
            transfer_source=transfer,
        )
        dl_result = downloader.download(
            result.manifest.snapshot_id,
            result.manifest,
            ["p-A", "p-B", "p-C"],
        )
        assert dl_result.success is True
        assert dl_result.chunks_downloaded == result.manifest.chunk_count

        # Restore and activate
        chunker = Chunker(chunk_size=4096)
        compressor = CompressionHandler()
        reassembled = chunker.reassemble(result.chunks)
        encoded_data = compressor.decompress(
            reassembled, result.manifest.compression
        )
        staging = StagingStateStore()
        StateRestorer(staging).restore(encoded_data)

        activator = AtomicActivator()
        activator.prepare(staging, staging.calculate_state_hash())
        act_result = activator.activate()
        assert act_result.success is True

    def test_pipeline_with_download_failure_and_resumption(self) -> None:
        """Pipeline with download failure and resumption."""
        result = _produce_multi_chunk_snapshot(4)
        transfer = MockChunkTransferSource()

        # Start with partial provider
        half = result.chunks[: len(result.chunks) // 2]
        transfer.store_chunks(
            result.manifest.snapshot_id, "p-A", half
        )

        downloader = SnapshotDownloader(
            config=DownloadConfig(),
            transfer_source=transfer,
        )
        dl_result = downloader.download(
            result.manifest.snapshot_id,
            result.manifest,
            ["p-A"],
        )
        assert dl_result.success is False  # Partial
        assert dl_result.chunks_downloaded < result.manifest.chunk_count

        # Add complete provider
        transfer.store_chunks(
            result.manifest.snapshot_id, "p-B", result.chunks
        )
        resume_result = downloader.resume(
            dl_result.session,
            ["p-A", "p-B"],
        )
        assert resume_result.success is True
        assert resume_result.chunks_downloaded == result.manifest.chunk_count

    def test_pipeline_rejects_state_hash_mismatch(self) -> None:
        """Pipeline with state hash mismatch detection (should reject)."""
        result = _produce_snapshot()

        # Verify with wrong expected hash
        verifier = SnapshotVerifier()
        verify_result = verifier.verify_complete(
            result.manifest,
            result.chunks,
            canonical_state_hash="00" * 32,  # Wrong hash
            decompress=False,
        )
        assert verify_result.valid is False
        assert any(
            "state hash" in e.lower() or "application" in e.lower()
            for e in verify_result.errors
        )

    def test_pipeline_rejects_invariant_violation(self) -> None:
        """Pipeline with invariant violation detection (should reject)."""
        staging = StagingStateStore()
        # Load invalid state: negative balance
        staging.load_namespace("wallets", [
            {"id": "w1", "balance": -500, "locked": 0, "sequence": 1},
        ])
        staging.load_namespace("protocol_parameters", {
            "version": "1.0.0",
        })

        checker = InvariantChecker()
        inv_result = checker.check_all(staging)
        assert inv_result.valid is False
        assert len(inv_result.violations) > 0

    def test_pipeline_with_block_replay_after_activation(self) -> None:
        """Pipeline with block replay after activation."""
        # Produce and activate
        result = _produce_snapshot()
        chunker = Chunker(chunk_size=4096)
        compressor = CompressionHandler()

        reassembled = chunker.reassemble(result.chunks)
        encoded_data = compressor.decompress(
            reassembled, result.manifest.compression
        )

        staging = StagingStateStore()
        restorer = StateRestorer(staging)
        restorer.restore(encoded_data)

        activator = AtomicActivator()
        activator.prepare(staging, staging.calculate_state_hash())
        act_result = activator.activate()
        assert act_result.success is True

        # Replay blocks starting from snapshot height + 1
        replay_blocks = _make_replay_blocks(
            BLOCK_HEIGHT + 1, BLOCK_HEIGHT + 3
        )
        block_source = MockBlockSource(
            blocks=replay_blocks,
            finalized_height=BLOCK_HEIGHT + 3,
        )
        initial_state = {"height": BLOCK_HEIGHT}
        replay_config = ReplayConfig(
            start_height=BLOCK_HEIGHT + 1,
            target_height=BLOCK_HEIGHT + 3,
        )
        replayer = BlockReplayer(replay_config, block_source)
        replay_result = replayer.replay(initial_state)
        assert replay_result.success is True
        assert replay_result.blocks_replayed == 3
        assert replay_result.end_height == BLOCK_HEIGHT + 3
