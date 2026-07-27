"""Tests for the fail-closed durable snapshot activation path."""

from __future__ import annotations

from pathlib import Path

from aidn_hypervisor.snapshot.chunk_store import FileSnapshotChunkStore
from aidn_hypervisor.snapshot.download import ChunkTransferSource, DownloadConfig, SnapshotDownloader
from aidn_hypervisor.snapshot.models import CompressionAlgorithm, SnapshotChunk
from aidn_hypervisor.snapshot.orchestrator import SnapshotOrchestrator
from aidn_hypervisor.snapshot.producer import SnapshotProducer, SnapshotProducerConfig


class MemoryTransferSource(ChunkTransferSource):
    def __init__(self, chunks: list[SnapshotChunk]) -> None:
        self._snapshot_id = chunks[0].snapshot_id
        self._chunks = {chunk.chunk_index: chunk for chunk in chunks}

    def get_chunk(self, snapshot_id: str, chunk_index: int, provider_id: str) -> SnapshotChunk | None:
        if snapshot_id != self._snapshot_id or provider_id != "provider-1":
            return None
        return self._chunks.get(chunk_index)

    def get_provider_inventory(self, snapshot_id: str, provider_id: str) -> list[int]:
        if snapshot_id != self._snapshot_id or provider_id != "provider-1":
            return []
        return list(self._chunks)

    def is_provider_available(self, provider_id: str) -> bool:
        return provider_id == "provider-1"


def _produce_snapshot():
    producer = SnapshotProducer(
        SnapshotProducerConfig(chunk_size=64, compression=CompressionAlgorithm.GZIP),
        b"snapshot-orchestrator-test-key",
    )
    return producer.produce(
        state={
            "wallets": [{"id": "wallet-1", "balance": 10, "locked": 0, "seq": 0}],
            "protocol_parameters": {"version": "1", "total_supply": 10},
        },
        block_height=1,
        block_hash="block-1",
        block_time="2026-07-27T00:00:00Z",
        epoch=1,
        chain_id="aidn-test",
        network_id="aidn",
        network_revision=1,
        protocol_version="1.0.0",
        application_version="0.1.0",
        state_schema_version=1,
        producer_service_id="producer-1",
    )


def _orchestrator(result, tmp_path: Path) -> SnapshotOrchestrator:
    downloader = SnapshotDownloader(
        DownloadConfig(),
        MemoryTransferSource(result.chunks),
        FileSnapshotChunkStore(tmp_path / "chunks"),
    )
    return SnapshotOrchestrator(downloader)


def test_apply_downloads_verifies_restores_and_activates(tmp_path: Path) -> None:
    produced = _produce_snapshot()
    orchestrator = _orchestrator(produced, tmp_path)

    applied = orchestrator.apply(
        produced.manifest,
        ["provider-1"],
        canonical_state_hash=produced.manifest.application_state_hash,
    )

    assert applied.success
    assert applied.phase == "activated"
    assert applied.activation is not None and applied.activation.success
    assert orchestrator.activator.active_state_hash == produced.manifest.application_state_hash


def test_apply_rejects_untrusted_state_commitment_before_activation(tmp_path: Path) -> None:
    produced = _produce_snapshot()
    orchestrator = _orchestrator(produced, tmp_path)

    applied = orchestrator.apply(
        produced.manifest,
        ["provider-1"],
        canonical_state_hash="00" * 32,
    )

    assert not applied.success
    assert applied.phase == "verification"
    assert orchestrator.activator.active_state_hash == ""
