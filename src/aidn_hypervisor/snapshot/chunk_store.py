"""Durable local storage for verified snapshot chunks."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

from aidn_hypervisor.snapshot.models import SnapshotChunk


class SnapshotChunkStore(ABC):
    """Store verified chunks under opaque, implementation-owned keys."""

    @abstractmethod
    def put(self, chunk: SnapshotChunk) -> str:
        """Persist a chunk durably and return its opaque storage key."""
        ...

    @abstractmethod
    def get(self, key: str) -> SnapshotChunk | None:
        """Return a persisted chunk, or ``None`` when it is unavailable."""
        ...


class FileSnapshotChunkStore(SnapshotChunkStore):
    """Filesystem-backed, content-addressed chunk store.

    The store owns key generation and never interprets a session key as an
    arbitrary path. Files are atomically replaced so a crash cannot make a
    partly written chunk appear verified after restart.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def put(self, chunk: SnapshotChunk) -> str:
        key = self._key_for(chunk)
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "snapshot_id": chunk.snapshot_id,
            "chunk_index": chunk.chunk_index,
            "total_chunks": chunk.total_chunks,
            "uncompressed_size": chunk.uncompressed_size,
            "compressed_size": chunk.compressed_size,
            "chunk_hash": chunk.chunk_hash,
            "payload_b64": base64.b64encode(chunk.payload).decode("ascii"),
        }
        encoded = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")

        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            try:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            except Exception:
                temp_path.unlink(missing_ok=True)
                raise

        try:
            os.replace(temp_path, path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return key

    def get(self, key: str) -> SnapshotChunk | None:
        try:
            raw = self._path_for(key).read_bytes()
            record = json.loads(raw.decode("utf-8"))
            return SnapshotChunk(
                snapshot_id=record["snapshot_id"],
                chunk_index=record["chunk_index"],
                total_chunks=record["total_chunks"],
                uncompressed_size=record["uncompressed_size"],
                compressed_size=record["compressed_size"],
                chunk_hash=record["chunk_hash"],
                payload=base64.b64decode(record["payload_b64"], validate=True),
            )
        except (KeyError, OSError, ValueError, json.JSONDecodeError):
            return None

    def _key_for(self, chunk: SnapshotChunk) -> str:
        snapshot_namespace = hashlib.sha256(chunk.snapshot_id.encode("utf-8")).hexdigest()
        return f"{snapshot_namespace}/{chunk.chunk_index:08d}-{chunk.chunk_hash}.json"

    def _path_for(self, key: str) -> Path:
        if not key or "\\" in key or key.startswith("/") or ".." in key.split("/"):
            raise ValueError("invalid snapshot chunk storage key")
        candidate = (self._root / key).resolve()
        if candidate.parent != self._root and self._root not in candidate.parents:
            raise ValueError("snapshot chunk storage key escapes root")
        return candidate
