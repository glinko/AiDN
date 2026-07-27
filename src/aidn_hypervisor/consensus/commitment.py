"""RFC-0047 §24 — State commitment and verification."""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel


class StateCommitment(BaseModel, frozen=True):
    """RFC-0047 §24 — State commitment record."""

    epoch: int
    block_height: int
    state_hash: str  # SHA-256 hex
    validator_set_hash: str | None = None
    timestamp: str  # ISO-8601


class CommitmentRecord(BaseModel, frozen=True):
    """Full commitment with metadata."""

    commitment: StateCommitment
    signature: str
    committed_by: str  # node_id
    verified: bool = False


class StateCommitmentService:
    """
    RFC-0047 §24 — State commitment and verification.

    Computes deterministic hashes of ledger state, creates
    commitments, and verifies that state data matches committed hashes.
    """

    def __init__(self) -> None:
        self._commitments: list[StateCommitment] = []
        self._records: list[CommitmentRecord] = []
        self._state_hashes: dict[int, str] = {}  # epoch -> latest hash

    def compute_state_hash(self, state_data: dict) -> str:
        """Compute deterministic hash of ledger state."""
        canonical = json.dumps(
            state_data, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def create_commitment(
        self,
        *,
        epoch: int,
        block_height: int,
        state_data: dict,
        timestamp: str,
    ) -> StateCommitment:
        """Create a state commitment for the current epoch."""
        state_hash = self.compute_state_hash(state_data)

        commitment = StateCommitment(
            epoch=epoch,
            block_height=block_height,
            state_hash=state_hash,
            timestamp=timestamp,
        )
        self._commitments.append(commitment)
        self._state_hashes[epoch] = state_hash
        return commitment

    def verify_commitment(self, epoch: int, state_data: dict) -> bool:
        """Verify that state data matches a committed hash."""
        expected = self._state_hashes.get(epoch)
        if not expected:
            return False
        current = self.compute_state_hash(state_data)
        return current == expected

    def get_latest_commitment(self, epoch: int) -> StateCommitment | None:
        """Get the latest commitment for an epoch."""
        for c in reversed(self._commitments):
            if c.epoch == epoch:
                return c
        return None

    def get_all_commitments(self) -> list[StateCommitment]:
        """Return all recorded commitments."""
        return list(self._commitments)

    def record_commitment(
        self,
        commitment: StateCommitment,
        *,
        signature: str,
        node_id: str,
        verified: bool = False,
    ) -> CommitmentRecord:
        """Record a signed commitment."""
        record = CommitmentRecord(
            commitment=commitment,
            signature=signature,
            committed_by=node_id,
            verified=verified,
        )
        self._records.append(record)
        return record
