"""RFC-0061 §§28-31 — Object Replication Engine.

Handles single-object retrieval, range retrieval, and chunked transfers
with resumption support.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from .object_envelope import RegistryObjectEnvelope
from .storage import ImmutableObjectStore


# ---------------------------------------------------------------------------
# Transfer state machine
# ---------------------------------------------------------------------------


class TransferState(str):
    """State of an object transfer."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    RESUMED = "resumed"


class TransferProgress(BaseModel):
    """Progress of a chunked transfer."""
    object_id: str
    state: str = TransferState.PENDING
    chunks_total: int = 0
    chunks_received: int = 0
    bytes_received: int = 0
    error: str | None = None
    started_at: float = Field(default_factory=time.time)
    completed_at: float | None = None


# ---------------------------------------------------------------------------
# Replication Engine
# ---------------------------------------------------------------------------


class ReplicationEngine:
    """
    RFC-0061 §§28-31 — Object replication engine.

    Handles single-object retrieval, range retrieval, and chunked transfers
    with resumption support.
    """

    def __init__(self, store: ImmutableObjectStore):
        self._store = store
        self._transfers: dict[str, TransferProgress] = {}
        self._transfer_log: list[TransferProgress] = []

    # -- single-object retrieval (§28) ------------------------------------

    def retrieve_single(
        self,
        *,
        object_id: str,
        source_peer_id: str | None = None,
    ) -> RegistryObjectEnvelope | None:
        """
        RFC-0061 §28 — Retrieve a single object.

        In MVP, simulates retrieval by checking local store.
        Real impl would fetch from remote peer.
        """
        return self._store.get(object_id)

    # -- range retrieval (§29) -------------------------------------------

    def retrieve_range(
        self,
        *,
        start_epoch: int,
        end_epoch: int,
    ) -> list[RegistryObjectEnvelope]:
        """
        RFC-0061 §29 — Retrieve objects in an epoch range.
        """
        result: list[RegistryObjectEnvelope] = []
        for epoch in range(start_epoch, end_epoch + 1):
            result.extend(self._store.list_by_epoch(epoch))
        return result

    # -- chunked transfer (§30) ------------------------------------------

    def start_chunked_transfer(
        self,
        *,
        object_id: str,
        total_chunks: int,
        content_size: int = 0,
    ) -> TransferProgress:
        """
        RFC-0061 §30 — Start a chunked object transfer.
        """
        progress = TransferProgress(
            object_id=object_id,
            state=TransferState.IN_PROGRESS,
            chunks_total=total_chunks,
        )
        self._transfers[object_id] = progress
        return progress

    def receive_chunk(
        self,
        *,
        object_id: str,
        chunk_index: int,
        chunk_data: bytes,
    ) -> TransferProgress | None:
        """Receive a chunk for an in-progress transfer."""
        progress = self._transfers.get(object_id)
        if not progress or progress.state != TransferState.IN_PROGRESS:
            return None

        progress.chunks_received += 1
        progress.bytes_received += len(chunk_data)

        if progress.chunks_received >= progress.chunks_total:
            progress.state = TransferState.COMPLETED
            progress.completed_at = time.time()

        return progress

    def complete_transfer(
        self,
        *,
        object_id: str,
        envelope: RegistryObjectEnvelope,
    ) -> bool:
        """Complete a transfer by storing the object."""
        progress = self._transfers.get(object_id)
        if not progress:
            return False

        stored = self._store.put(envelope)
        if stored:
            progress.state = TransferState.COMPLETED
            progress.completed_at = time.time()
        else:
            progress.state = TransferState.FAILED
            progress.error = "storage_failed"

        self._transfer_log.append(progress.model_copy())
        return stored

    # -- transfer resumption (§31) ---------------------------------------

    def resume_transfer(
        self,
        *,
        object_id: str,
        from_chunk: int = 0,
    ) -> TransferProgress | None:
        """
        RFC-0061 §31 — Resume an interrupted transfer.
        """
        progress = self._transfers.get(object_id)
        if not progress:
            return None

        if progress.state == TransferState.FAILED:
            progress.state = TransferState.IN_PROGRESS
            progress.chunks_received = from_chunk
            progress.error = None
            return progress

        return progress

    # -- queries ---------------------------------------------------------

    def get_transfer(self, object_id: str) -> TransferProgress | None:
        """Get current transfer progress for an object."""
        return self._transfers.get(object_id)

    def get_completed_transfers(self) -> list[TransferProgress]:
        """All completed transfers from the log."""
        return [
            t for t in self._transfer_log
            if t.state == TransferState.COMPLETED
        ]

    def get_failed_transfers(self) -> list[TransferProgress]:
        """All failed transfers from the log."""
        return [
            t for t in self._transfer_log
            if t.state == TransferState.FAILED
        ]

    @property
    def active_transfers(self) -> int:
        """Count of currently in-progress transfers."""
        return sum(
            1 for t in self._transfers.values()
            if t.state == TransferState.IN_PROGRESS
        )
