"""Tests for src/aidn_hypervisor/snapshot/models.py — Snapshot data models."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from aidn_hypervisor.snapshot.models import (
    CompressionAlgorithm,
    SnapshotChunk,
    SnapshotIdentity,
    SnapshotManifest,
    SnapshotType,
    compute_snapshot_id,
)
from aidn_hypervisor.snapshot.models import (
    Encoding as SnapshotEncoding,
)

# ── SnapshotType enum ──────────────────────────────────────────────

class TestSnapshotType:
    def test_full_state_value(self):
        assert SnapshotType.FULL_STATE.value == "full_state"

    def test_recovery_state_value(self):
        assert SnapshotType.RECOVERY_STATE.value == "recovery_state"

    def test_development_state_value(self):
        assert SnapshotType.DEVELOPMENT_STATE.value == "development_state"

    def test_all_values_present(self):
        assert len(SnapshotType) == 3

    def test_can_create_from_string(self):
        st = SnapshotType("full_state")
        assert st == SnapshotType.FULL_STATE


# ── CompressionAlgorithm enum ──────────────────────────────────────

class TestCompressionAlgorithm:
    def test_none_value(self):
        assert CompressionAlgorithm.NONE.value == "none"

    def test_gzip_value(self):
        assert CompressionAlgorithm.GZIP.value == "gzip"

    def test_zstd_value(self):
        assert CompressionAlgorithm.ZSTD.value == "zstd"

    def test_all_values_present(self):
        assert len(CompressionAlgorithm) == 3


# ── SnapshotEncoding enum ──────────────────────────────────────────

class TestSnapshotEncoding:
    def test_json_deterministic_value(self):
        assert SnapshotEncoding.JSON_DETERMINISTIC.value == "json_deterministic"

    def test_protobuf_value(self):
        assert SnapshotEncoding.PROTOBUF.value == "protobuf"

    def test_all_values_present(self):
        assert len(SnapshotEncoding) == 2


# ── Helper to build a minimal valid manifest dict ──────────────────

def _make_manifest_kwargs(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a dict suitable for SnapshotManifest(**kwargs)."""
    base: dict[str, Any] = {
        "snapshot_id": "abc123",
        "snapshot_type": SnapshotType.FULL_STATE,
        "snapshot_format_version": 1,
        "network_id": "aidn-mainnet",
        "chain_id": "chain-001",
        "network_revision": 1,
        "protocol_version": "1.0.0",
        "application_version": "1.0.0",
        "state_schema_version": 1,
        "block_height": 1000,
        "block_hash": "0" * 64,
        "block_time": "2025-01-01T00:00:00Z",
        "epoch": 1,
        "application_state_hash": "0" * 64,
        "validator_set_hash": None,
        "protocol_parameters_hash": None,
        "snapshot_content_hash": "0" * 64,
        "snapshot_content_size": 1024,
        "chunk_count": 1,
        "chunk_size": 1024,
        "chunk_root": "0" * 64,
        "compression": CompressionAlgorithm.NONE,
        "encoding": SnapshotEncoding.JSON_DETERMINISTIC,
        "creation_time": "2025-01-01T00:00:00Z",
        "producer_service_id": "producer-1",
        "producer_signature": "deadbeef",
    }
    if overrides:
        base.update(overrides)
    return base


# ── SnapshotManifest creation ──────────────────────────────────────

class TestSnapshotManifestCreation:
    def test_create_minimal(self):
        m = SnapshotManifest(**_make_manifest_kwargs())
        assert m.snapshot_id == "abc123"
        assert m.snapshot_type == SnapshotType.FULL_STATE
        assert m.block_height == 1000

    def test_create_with_optional_hashes(self):
        m = SnapshotManifest(
            **_make_manifest_kwargs(
                {
                    "validator_set_hash": "a" * 64,
                    "protocol_parameters_hash": "b" * 64,
                }
            )
        )
        assert m.validator_set_hash == "a" * 64
        assert m.protocol_parameters_hash == "b" * 64

    def test_frozen(self):
        m = SnapshotManifest(**_make_manifest_kwargs())
        with pytest.raises(ValidationError):
            m.snapshot_id = "changed"  # type: ignore

    def test_negative_block_height_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotManifest(**_make_manifest_kwargs({"block_height": -1}))

    def test_negative_content_size_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotManifest(
                **_make_manifest_kwargs({"snapshot_content_size": -1})
            )

    def test_negative_chunk_count_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotManifest(**_make_manifest_kwargs({"chunk_count": -1}))

    def test_negative_chunk_size_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotManifest(**_make_manifest_kwargs({"chunk_size": -1}))

    def test_negative_state_schema_version_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotManifest(
                **_make_manifest_kwargs({"state_schema_version": -1})
            )

    def test_negative_format_version_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotManifest(
                **_make_manifest_kwargs({"snapshot_format_version": -1})
            )

    def test_negative_network_revision_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotManifest(
                **_make_manifest_kwargs({"network_revision": -1})
            )

    def test_negative_epoch_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotManifest(**_make_manifest_kwargs({"epoch": -1}))

    def test_zero_block_height_allowed(self):
        m = SnapshotManifest(**_make_manifest_kwargs({"block_height": 0}))
        assert m.block_height == 0


# ── SnapshotChunk creation ─────────────────────────────────────────

class TestSnapshotChunk:
    def _chunk_kwargs(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        base: dict[str, Any] = {
            "snapshot_id": "snap-001",
            "chunk_index": 0,
            "total_chunks": 3,
            "uncompressed_size": 1024,
            "compressed_size": 512,
            "chunk_hash": "0" * 64,
            "payload": b"hello",
        }
        if overrides:
            base.update(overrides)
        return base

    def test_create_valid(self):
        c = SnapshotChunk(**self._chunk_kwargs())
        assert c.chunk_index == 0
        assert c.total_chunks == 3

    def test_frozen(self):
        c = SnapshotChunk(**self._chunk_kwargs())
        with pytest.raises(ValidationError):
            c.chunk_index = 1  # type: ignore

    def test_negative_chunk_index_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotChunk(**self._chunk_kwargs({"chunk_index": -1}))

    def test_chunk_index_out_of_range_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotChunk(**self._chunk_kwargs({"chunk_index": 3}))

    def test_zero_total_chunks_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotChunk(**self._chunk_kwargs({"total_chunks": 0}))

    def test_negative_uncompressed_size_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotChunk(
                **self._chunk_kwargs({"uncompressed_size": -1})
            )

    def test_negative_compressed_size_rejected(self):
        with pytest.raises(ValidationError):
            SnapshotChunk(**self._chunk_kwargs({"compressed_size": -1}))

    def test_chunk_index_last_valid(self):
        c = SnapshotChunk(**self._chunk_kwargs({"chunk_index": 2, "total_chunks": 3}))
        assert c.chunk_index == 2


# ── SnapshotIdentity ───────────────────────────────────────────────

class TestSnapshotIdentity:
    def test_create_valid(self):
        si = SnapshotIdentity(
            chain_id="chain-001",
            block_height=1000,
            application_state_hash="a" * 64,
            snapshot_format_version=1,
            snapshot_content_root="b" * 64,
        )
        assert si.chain_id == "chain-001"
        assert si.snapshot_id is not None
        assert len(si.snapshot_id) == 64  # SHA-256 hex

    def test_frozen(self):
        si = SnapshotIdentity(
            chain_id="chain-001",
            block_height=1000,
            application_state_hash="a" * 64,
            snapshot_format_version=1,
            snapshot_content_root="b" * 64,
        )
        with pytest.raises(ValidationError):
            si.chain_id = "changed"  # type: ignore

    def test_snapshot_id_matches_compute(self):
        si = SnapshotIdentity(
            chain_id="chain-001",
            block_height=1000,
            application_state_hash="a" * 64,
            snapshot_format_version=1,
            snapshot_content_root="b" * 64,
        )
        expected = compute_snapshot_id(
            chain_id="chain-001",
            block_height=1000,
            application_state_hash="a" * 64,
            snapshot_format_version=1,
            snapshot_content_root="b" * 64,
        )
        assert si.snapshot_id == expected


# ── compute_snapshot_id determinism ────────────────────────────────

class TestComputeSnapshotId:
    def test_deterministic_same_inputs(self):
        kwargs = {
            "chain_id": "chain-001",
            "block_height": 500,
            "application_state_hash": "cc" * 32,
            "snapshot_format_version": 2,
            "snapshot_content_root": "dd" * 32,
        }
        id1 = compute_snapshot_id(**kwargs)
        id2 = compute_snapshot_id(**kwargs)
        assert id1 == id2

    def test_deterministic_different_chain_id(self):
        base = {
            "chain_id": "chain-001",
            "block_height": 500,
            "application_state_hash": "cc" * 32,
            "snapshot_format_version": 2,
            "snapshot_content_root": "dd" * 32,
        }
        alt = dict(base, chain_id="chain-002")
        assert compute_snapshot_id(**base) != compute_snapshot_id(**alt)

    def test_deterministic_different_height(self):
        base = {
            "chain_id": "chain-001",
            "block_height": 500,
            "application_state_hash": "cc" * 32,
            "snapshot_format_version": 2,
            "snapshot_content_root": "dd" * 32,
        }
        alt = dict(base, block_height=501)
        assert compute_snapshot_id(**base) != compute_snapshot_id(**alt)

    def test_deterministic_different_state_hash(self):
        base = {
            "chain_id": "chain-001",
            "block_height": 500,
            "application_state_hash": "cc" * 32,
            "snapshot_format_version": 2,
            "snapshot_content_root": "dd" * 32,
        }
        alt = dict(base, application_state_hash="ee" * 32)
        assert compute_snapshot_id(**base) != compute_snapshot_id(**alt)

    def test_deterministic_different_format_version(self):
        base = {
            "chain_id": "chain-001",
            "block_height": 500,
            "application_state_hash": "cc" * 32,
            "snapshot_format_version": 2,
            "snapshot_content_root": "dd" * 32,
        }
        alt = dict(base, snapshot_format_version=3)
        assert compute_snapshot_id(**base) != compute_snapshot_id(**alt)

    def test_deterministic_different_content_root(self):
        base = {
            "chain_id": "chain-001",
            "block_height": 500,
            "application_state_hash": "cc" * 32,
            "snapshot_format_version": 2,
            "snapshot_content_root": "dd" * 32,
        }
        alt = dict(base, snapshot_content_root="ff" * 32)
        assert compute_snapshot_id(**base) != compute_snapshot_id(**alt)

    def test_returns_hex_sha256(self):
        result = compute_snapshot_id(
            chain_id="x",
            block_height=1,
            application_state_hash="a" * 64,
            snapshot_format_version=1,
            snapshot_content_root="b" * 64,
        )
        assert len(result) == 64
        int(result, 16)  # valid hex

    def test_manual_hash_matches(self):
        chain_id = "test-chain"
        height = 42
        state_hash = "ab" * 32
        fmt_ver = 3
        content_root = "cd" * 32
        data = f"{chain_id}:{height}:{state_hash}:{fmt_ver}:{content_root}"
        expected = hashlib.sha256(data.encode()).hexdigest()
        assert (
            compute_snapshot_id(chain_id, height, state_hash, fmt_ver, content_root)
            == expected
        )
