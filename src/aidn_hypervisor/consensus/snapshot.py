"""RFC-0047 §26 — Snapshot production and consumption."""

from __future__ import annotations

import hashlib
import json
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SnapshotFormat(str, Enum):
    """Supported snapshot serialization formats."""

    PROTOBUF = "protobuf"
    JSON = "json"


class SnapshotMetadata(BaseModel, frozen=True):
    """Snapshot metadata for verification."""

    height: int
    format: SnapshotFormat
    chunks: int
    hash: str  # SHA-256 of snapshot payload
    timestamp: int  # unix epoch
    app_version: str = "1.0.0"


class SnapshotProducer:
    """RFC-0047 §26 — Create and export snapshots."""

    def __init__(self) -> None:
        self._snapshots: list[tuple[SnapshotMetadata, bytes]] = []

    def create_snapshot(
        self,
        *,
        height: int,
        state_data: dict,
        format: SnapshotFormat = SnapshotFormat.JSON,
    ) -> tuple[SnapshotMetadata, bytes]:
        """Create a snapshot of current state."""
        if format == SnapshotFormat.JSON:
            payload = json.dumps(state_data, sort_keys=True).encode()
        else:
            payload = json.dumps(state_data).encode()

        metadata = SnapshotMetadata(
            height=height,
            format=format,
            chunks=1,
            hash=hashlib.sha256(payload).hexdigest(),
            timestamp=int(time.time()),
        )

        self._snapshots.append((metadata, payload))
        return metadata, payload

    def get_snapshots(self) -> list[SnapshotMetadata]:
        """Return metadata for all produced snapshots."""
        return [m for m, _ in self._snapshots]


class SnapshotConsumer:
    """RFC-0047 §26 — Validate and restore snapshots."""

    def __init__(self) -> None:
        self._restored: list[SnapshotMetadata] = []

    def validate_snapshot(
        self,
        metadata: SnapshotMetadata,
        payload: bytes,
    ) -> bool:
        """Validate snapshot integrity."""
        expected_hash = hashlib.sha256(payload).hexdigest()
        return expected_hash == metadata.hash

    def restore_snapshot(
        self,
        metadata: SnapshotMetadata,
        payload: bytes,
    ) -> dict | None:
        """Restore state from a snapshot."""
        if not self.validate_snapshot(metadata, payload):
            return None

        if metadata.format == SnapshotFormat.JSON:
            state = json.loads(payload)
        else:
            state = json.loads(payload)

        self._restored.append(metadata)
        return state

    def get_restored(self) -> list[SnapshotMetadata]:
        """Return metadata for all successfully restored snapshots."""
        return list(self._restored)
