"""Durable local state and State Sync snapshots for the ABCI application."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ABCIStateStoreError(RuntimeError):
    """A local ABCI state file is missing, corrupt, or cannot be persisted."""


@dataclass(frozen=True)
class ABCIStateSnapshot:
    """CometBFT-compatible metadata for one locally retained state snapshot."""

    height: int
    format: int
    chunks: int
    hash: bytes
    app_hash: bytes

    def __post_init__(self) -> None:
        if self.height < 0 or self.format != 1 or self.chunks < 1:
            raise ValueError("ABCI snapshot metadata is invalid")
        if len(self.hash) != 32 or len(self.app_hash) != 32:
            raise ValueError("ABCI snapshot hashes must be SHA-256 values")

    @property
    def identifier(self) -> str:
        return f"{self.height:020d}-{self.hash.hex()}"


@dataclass
class _IncomingSnapshot:
    metadata: ABCIStateSnapshot
    chunks: dict[int, bytes]
    total_bytes: int = 0


class ABCIStateStore:
    """Atomically retain ABCI state and bounded JSON State Sync snapshots.

    The store deliberately uses only canonical JSON and explicitly bounded
    chunks.  It is local durable state, not a replacement for CometBFT's own
    block store or a trust decision about a remote snapshot.
    """

    SCHEMA_VERSION = 1
    SNAPSHOT_FORMAT = 1
    # Two snapshots are not enough when a 200+ chunk snapshot is transferred
    # while the source keeps committing blocks. Keep a bounded recovery window
    # by default; operators can tune it through ConsensusServiceConfig.
    DEFAULT_RETAINED_SNAPSHOTS = 8
    # Once a consumer has requested a chunk, keep that snapshot available for
    # a bounded inactivity window so pruning cannot break an active transfer.
    DEFAULT_SNAPSHOT_LEASE_SECONDS = 30 * 60
    _IDENTIFIER_RE = re.compile(r"^[0-9]{20}-[0-9a-f]{64}$")

    def __init__(
        self,
        root: str | Path,
        *,
        chunk_size: int = 64 * 1024,
        maximum_snapshot_bytes: int = 64 * 1024 * 1024,
        maximum_import_chunk_bytes: int = 1_000_000,
        retained_snapshots: int = DEFAULT_RETAINED_SNAPSHOTS,
        snapshot_lease_seconds: int = DEFAULT_SNAPSHOT_LEASE_SECONDS,
    ) -> None:
        if (
            chunk_size < 1
            or maximum_snapshot_bytes < chunk_size
            or not 1 <= maximum_import_chunk_bytes <= maximum_snapshot_bytes
            or retained_snapshots < 1
            or snapshot_lease_seconds < 1
        ):
            raise ValueError("ABCI state store limits are invalid")
        self.root = Path(root).expanduser().resolve()
        self.chunk_size = chunk_size
        self.maximum_snapshot_bytes = maximum_snapshot_bytes
        self.maximum_import_chunk_bytes = maximum_import_chunk_bytes
        self.retained_snapshots = retained_snapshots
        self.snapshot_lease_seconds = snapshot_lease_seconds
        self._snapshots_dir = self.root / "snapshots"
        self._current_path = self.root / "current.json"
        self._incoming: _IncomingSnapshot | None = None
        self._snapshot_leases: dict[str, float] = {}

    def persist(self, state: dict[str, Any]) -> ABCIStateSnapshot:
        """Atomically persist canonical state before reporting block success."""
        payload = _canonical_json_bytes(state)
        if len(payload) > self.maximum_snapshot_bytes:
            raise ABCIStateStoreError("ABCI state exceeds configured snapshot limit")
        metadata = self._metadata_from_state(state, payload)
        self.root.mkdir(parents=True, exist_ok=True)
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        destination = self._snapshots_dir / metadata.identifier

        if not destination.exists():
            staging = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=self._snapshots_dir))
            try:
                for index, offset in enumerate(range(0, len(payload), self.chunk_size)):
                    _write_file(staging / f"{index:08d}.chunk", payload[offset : offset + self.chunk_size])
                _write_file(
                    staging / "manifest.json",
                    _canonical_json_bytes(
                        {
                            "schema_version": self.SCHEMA_VERSION,
                            "height": metadata.height,
                            "format": metadata.format,
                            "chunks": metadata.chunks,
                            "hash": metadata.hash.hex(),
                            "app_hash": metadata.app_hash.hex(),
                            "created_at": int(time.time()),
                        }
                    ),
                )
                try:
                    os.replace(staging, destination)
                except FileExistsError:
                    # An identical snapshot won a concurrent writer race.
                    shutil.rmtree(staging, ignore_errors=True)
            except Exception as error:
                shutil.rmtree(staging, ignore_errors=True)
                if isinstance(error, ABCIStateStoreError):
                    raise
                raise ABCIStateStoreError("could not persist ABCI snapshot") from error

        try:
            _atomic_write(
                self._current_path,
                _canonical_json_bytes({"schema_version": self.SCHEMA_VERSION, "snapshot_id": metadata.identifier}),
            )
            self._prune_retained_snapshots()
        except OSError as error:
            raise ABCIStateStoreError("could not update ABCI state pointer") from error
        return metadata

    def load_current(self) -> dict[str, Any] | None:
        """Load and verify the state selected by the durable current pointer."""
        if not self._current_path.exists():
            return None
        try:
            pointer = json.loads(self._current_path.read_text(encoding="utf-8"))
            if pointer.get("schema_version") != self.SCHEMA_VERSION:
                raise ValueError("unsupported state pointer version")
            identifier = pointer.get("snapshot_id")
            if not isinstance(identifier, str) or not self._IDENTIFIER_RE.fullmatch(identifier):
                raise ValueError("state pointer snapshot id is invalid")
            return self._load_snapshot_by_identifier(identifier)[1]
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise ABCIStateStoreError("durable ABCI state is corrupt") from error

    def list_snapshots(self) -> list[ABCIStateSnapshot]:
        """Return valid retained snapshots, newest height first."""
        if not self._snapshots_dir.exists():
            return []
        snapshots: list[ABCIStateSnapshot] = []
        for path in self._snapshots_dir.iterdir():
            if not path.is_dir() or not self._IDENTIFIER_RE.fullmatch(path.name):
                continue
            try:
                metadata, _ = self._load_snapshot_by_identifier(path.name)
            except ABCIStateStoreError:
                continue
            snapshots.append(metadata)
        return sorted(snapshots, key=lambda item: (item.height, item.hash), reverse=True)

    def load_snapshot_chunk(self, *, height: int, format: int, chunk: int) -> bytes:
        """Return one verified local State Sync chunk."""
        if chunk < 0:
            raise ABCIStateStoreError("ABCI snapshot chunk index is invalid")
        for metadata in self.list_snapshots():
            if metadata.height == height and metadata.format == format:
                self._renew_snapshot_lease(metadata.identifier)
                if chunk >= metadata.chunks:
                    raise ABCIStateStoreError("ABCI snapshot chunk is unavailable")
                path = self._snapshots_dir / metadata.identifier / f"{chunk:08d}.chunk"
                try:
                    payload = path.read_bytes()
                except OSError as error:
                    raise ABCIStateStoreError("ABCI snapshot chunk is unavailable") from error
                if not payload or len(payload) > self.chunk_size:
                    raise ABCIStateStoreError("ABCI snapshot chunk is invalid")
                return payload
        raise ABCIStateStoreError("ABCI snapshot is unavailable")

    def release_snapshot_lease(self, *, height: int, format: int) -> None:
        """Stop protecting a snapshot after a consumer abandons its transfer."""
        for metadata in self.list_snapshots():
            if metadata.height == height and metadata.format == format:
                self._snapshot_leases.pop(metadata.identifier, None)
                return

    def offer_import(self, metadata: ABCIStateSnapshot) -> bool:
        """Start a bounded incoming State Sync snapshot, replacing no local state."""
        if metadata.chunks > self.maximum_snapshot_bytes:
            return False
        self._incoming = _IncomingSnapshot(metadata=metadata, chunks={})
        return True

    def add_import_chunk(
        self,
        *,
        index: int,
        payload: bytes,
    ) -> tuple[ABCIStateSnapshot, dict[str, Any]] | None:
        """Accept an incoming chunk and return state only after full hash verification."""
        incoming = self._incoming
        if incoming is None or index < 0 or index >= incoming.metadata.chunks:
            raise ABCIStateStoreError("no matching ABCI snapshot import")
        if not payload or len(payload) > self.maximum_import_chunk_bytes:
            raise ABCIStateStoreError("ABCI snapshot import chunk is invalid")
        previous = incoming.chunks.get(index)
        if previous is not None:
            if previous != payload:
                raise ABCIStateStoreError("ABCI snapshot import chunk conflicts")
            return None
        incoming.total_bytes += len(payload)
        if incoming.total_bytes > self.maximum_snapshot_bytes:
            raise ABCIStateStoreError("ABCI snapshot import exceeds configured limit")
        incoming.chunks[index] = payload
        if len(incoming.chunks) != incoming.metadata.chunks:
            return None
        assembled = b"".join(incoming.chunks[position] for position in range(incoming.metadata.chunks))
        self._incoming = None
        if hashlib.sha256(assembled).digest() != incoming.metadata.hash:
            raise ABCIStateStoreError("ABCI snapshot import hash mismatch")
        try:
            state = json.loads(assembled)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ABCIStateStoreError("ABCI snapshot import JSON is invalid") from error
        if not isinstance(state, dict):
            raise ABCIStateStoreError("ABCI snapshot import state is invalid")
        return incoming.metadata, state

    def abort_import(self) -> None:
        """Discard incomplete remote snapshot data without touching local state."""
        self._incoming = None

    def _metadata_from_state(self, state: dict[str, Any], payload: bytes) -> ABCIStateSnapshot:
        try:
            height = int(state["last_block_height"])
            app_hash = bytes.fromhex(str(state["app_hash"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ABCIStateStoreError("ABCI state has no valid height or app hash") from error
        chunks = max(1, (len(payload) + self.chunk_size - 1) // self.chunk_size)
        return ABCIStateSnapshot(
            height=height,
            format=self.SNAPSHOT_FORMAT,
            chunks=chunks,
            hash=hashlib.sha256(payload).digest(),
            app_hash=app_hash,
        )

    def _load_snapshot_by_identifier(self, identifier: str) -> tuple[ABCIStateSnapshot, dict[str, Any]]:
        base = self._snapshots_dir / identifier
        try:
            manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
            if manifest.get("schema_version") != self.SCHEMA_VERSION:
                raise ValueError("unsupported snapshot schema")
            metadata = ABCIStateSnapshot(
                height=int(manifest["height"]),
                format=int(manifest["format"]),
                chunks=int(manifest["chunks"]),
                hash=bytes.fromhex(str(manifest["hash"])),
                app_hash=bytes.fromhex(str(manifest["app_hash"])),
            )
            if metadata.identifier != identifier:
                raise ValueError("snapshot identifier mismatch")
            payload = b"".join(
                (base / f"{index:08d}.chunk").read_bytes() for index in range(metadata.chunks)
            )
            if len(payload) > self.maximum_snapshot_bytes or hashlib.sha256(payload).digest() != metadata.hash:
                raise ValueError("snapshot payload hash mismatch")
            state = json.loads(payload)
            if not isinstance(state, dict):
                raise ValueError("snapshot state is invalid")
            state_metadata = self._metadata_from_state(state, payload)
            if state_metadata.height != metadata.height or state_metadata.app_hash != metadata.app_hash:
                raise ValueError("snapshot state metadata mismatch")
            return metadata, state
        except (OSError, KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ABCIStateStoreError("ABCI snapshot is corrupt") from error

    def _prune_retained_snapshots(self) -> None:
        snapshots = self.list_snapshots()
        now = time.monotonic()
        self._snapshot_leases = {
            identifier: expires_at
            for identifier, expires_at in self._snapshot_leases.items()
            if expires_at > now
        }
        for metadata in snapshots[self.retained_snapshots :]:
            if metadata.identifier in self._snapshot_leases:
                continue
            shutil.rmtree(self._snapshots_dir / metadata.identifier, ignore_errors=True)

    def _renew_snapshot_lease(self, identifier: str) -> None:
        self._snapshot_leases[identifier] = time.monotonic() + self.snapshot_lease_seconds


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ABCIStateStoreError("ABCI state is not JSON serializable") from error


def _write_file(path: Path, content: bytes) -> None:
    with path.open("wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
