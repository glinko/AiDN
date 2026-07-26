"""RFC-0062 §6-§25 — Snapshot data models.

All models are frozen (immutable) pydantic v2 BaseModel.
"""

from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


# ── Enums ──────────────────────────────────────────────────────────

class SnapshotType(str, Enum):
    """RFC-0062 §6 — Snapshot type classification."""

    FULL_STATE = "full_state"
    """Complete canonical application state for new node bootstrap."""

    RECOVERY_STATE = "recovery_state"
    """Repair/replace corrupted local state at known height."""

    DEVELOPMENT_STATE = "development_state"
    """Testnet/dev metadata; SHALL NOT be accepted by production."""


class CompressionAlgorithm(str, Enum):
    """RFC-0062 §24 — Compression algorithm."""

    NONE = "none"
    GZIP = "gzip"
    ZSTD = "zstd"


class Encoding(str, Enum):
    """RFC-0062 §25 — Snapshot encoding format."""

    JSON_DETERMINISTIC = "json_deterministic"
    """Canonical JSON with sorted keys."""

    PROTOBUF = "protobuf"
    """Future protobuf encoding."""


# ── Snapshot Identity ──────────────────────────────────────────────

def compute_snapshot_id(
    chain_id: str,
    block_height: int,
    application_state_hash: str,
    snapshot_format_version: int,
    snapshot_content_root: str,
) -> str:
    """RFC-0062 §10 — Deterministic snapshot ID computation."""
    data = (
        f"{chain_id}:{block_height}:{application_state_hash}"
        f":{snapshot_format_version}:{snapshot_content_root}"
    )
    return hashlib.sha256(data.encode()).hexdigest()


class SnapshotIdentity(BaseModel, frozen=True):
    """RFC-0062 §10 — Deterministic snapshot identity."""

    chain_id: str
    block_height: int
    application_state_hash: str
    snapshot_format_version: int
    snapshot_content_root: str
    snapshot_id: str = ""

    @model_validator(mode="before")
    @classmethod
    def _compute_snapshot_id(cls, data):
        """Auto-compute snapshot_id from identity fields if not provided."""
        if isinstance(data, dict):
            if not data.get("snapshot_id"):
                data["snapshot_id"] = compute_snapshot_id(
                    data.get("chain_id", ""),
                    data.get("block_height", 0),
                    data.get("application_state_hash", ""),
                    data.get("snapshot_format_version", 0),
                    data.get("snapshot_content_root", ""),
                )
        return data


# ── Snapshot Manifest ──────────────────────────────────────────────

class SnapshotManifest(BaseModel, frozen=True):
    """RFC-0062 §11 — Snapshot manifest."""

    snapshot_id: str
    snapshot_type: SnapshotType
    snapshot_format_version: int = Field(ge=0)
    network_id: str
    chain_id: str
    network_revision: int = Field(ge=0)
    protocol_version: str
    application_version: str
    state_schema_version: int = Field(ge=0)
    block_height: int = Field(ge=0)
    block_hash: str
    block_time: str
    epoch: int = Field(ge=0)
    application_state_hash: str
    validator_set_hash: str | None = None
    protocol_parameters_hash: str | None = None
    snapshot_content_hash: str
    snapshot_content_size: int = Field(ge=0)
    chunk_count: int = Field(ge=0)
    chunk_size: int = Field(ge=0)
    chunk_root: str
    compression: CompressionAlgorithm
    encoding: Encoding
    creation_time: str
    producer_service_id: str
    producer_signature: str


# ── Snapshot Chunk ─────────────────────────────────────────────────

class SnapshotChunk(BaseModel, frozen=True):
    """RFC-0062 §22 — Individual snapshot chunk."""

    snapshot_id: str
    chunk_index: int = Field(ge=0)
    total_chunks: int = Field(ge=1)
    uncompressed_size: int = Field(ge=0)
    compressed_size: int = Field(ge=0)
    chunk_hash: str
    payload: bytes

    @model_validator(mode="after")
    def _check_chunk_index_range(self) -> "SnapshotChunk":
        """chunk_index must be < total_chunks."""
        if self.chunk_index >= self.total_chunks:
            raise ValueError(
                f"chunk_index {self.chunk_index} >= total_chunks {self.total_chunks}"
            )
        return self
