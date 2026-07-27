"""Anti-Entropy Protocol (RFC-0061 §§53-58)."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from pydantic import BaseModel

from .inventory import BloomFilter, InventoryExchange
from .storage import ImmutableObjectStore
from .verification import ConsistencyChecker, ObjectVerifier

# ---------------------------------------------------------------------------
# Anti-Entropy Round
# ---------------------------------------------------------------------------


class AntiEntropyRound(BaseModel, frozen=True):
    """Record of a single anti-entropy round."""

    round_id: str
    peer_id: str
    started_at: float = 0.0
    completed_at: float = 0.0
    objects_compared: int = 0
    discrepancies_found: int = 0
    objects_repaired: int = 0
    status: str = "pending"  # pending | in_progress | completed | failed


# ---------------------------------------------------------------------------
# Anti-Entropy Engine
# ---------------------------------------------------------------------------


class AntiEntropyEngine:
    """
    RFC-0061 §§53-58 — Anti-entropy protocol for registry consistency.

    Uses bloom filters to efficiently detect discrepancies, then
    verifies and repairs inconsistent objects.
    """

    def __init__(self, store: ImmutableObjectStore) -> None:
        self._store = store
        self._verifier = ObjectVerifier(store)
        self._checker = ConsistencyChecker(store)
        self._rounds: list[AntiEntropyRound] = []
        self._discrepancies: list[str] = []

    def start_round(self, *, peer_id: str) -> AntiEntropyRound:
        """Start a new anti-entropy round."""
        round_id = hashlib.sha256(
            f"{peer_id}:{time.time()}".encode()
        ).hexdigest()[:16]

        round_record = AntiEntropyRound(
            round_id=round_id,
            peer_id=peer_id,
            started_at=time.time(),
            status="in_progress",
        )
        self._rounds.append(round_record)
        return round_record

    def compare_inventories(
        self,
        *,
        local_bloom: BloomFilter,
        remote_bloom: BloomFilter,
    ) -> tuple[list[str], list[str]]:
        """
        Compare bloom filters to find discrepancies.

        Returns (local_missing, remote_missing) object ids.
        - local_missing: objects the remote has that we might not
        - remote_missing: objects we have that the remote likely doesn't
        """
        exchange = InventoryExchange(self._store)

        # Objects we have that remote might not
        remote_missing = exchange.find_missing(remote_bloom)

        # Objects remote has that we might not (need remote inventory list)
        # For bloom-only comparison, we can only detect one direction
        local_missing: list[str] = []

        return local_missing, remote_missing

    def verify_discrepancies(self, object_ids: list[str]) -> list[str]:
        """Verify potentially discrepant objects."""
        verified = self._verifier.verify_batch(object_ids)
        invalid = [r.object_id for r in verified.results if not r.valid]
        self._discrepancies.extend(invalid)
        return invalid

    def repair_object(
        self,
        *,
        object_id: str,
        replacement: Any = None,
    ) -> bool:
        """
        Repair a discrepant object.

        In MVP, removal of invalid objects is the primary repair mechanism.
        If a replacement is provided, store it instead.
        """
        obj = self._store.get(object_id)

        if replacement is not None:
            # Replace with verified copy
            return self._store.put(replacement)
        elif obj is not None:
            # Remove invalid object (tombstone)
            return self._store.tombstone(object_id)
        else:
            return False

    def complete_round(
        self,
        *,
        round_id: str,
        objects_compared: int,
        discrepancies_found: int,
        objects_repaired: int,
        status: str = "completed",
    ) -> AntiEntropyRound | None:
        """Complete an anti-entropy round."""
        for i, round_record in enumerate(self._rounds):
            if round_record.round_id == round_id:
                completed = round_record.model_copy(
                    update={
                        "completed_at": time.time(),
                        "objects_compared": objects_compared,
                        "discrepancies_found": discrepancies_found,
                        "objects_repaired": objects_repaired,
                        "status": status,
                    }
                )
                self._rounds[i] = completed
                return completed
        return None

    def get_rounds(self) -> list[AntiEntropyRound]:
        """Return a copy of all round records."""
        return list(self._rounds)

    def get_discrepancies(self) -> list[str]:
        """Return a copy of all detected discrepancies."""
        return list(self._discrepancies)

    def clear_discrepancies(self) -> None:
        """Clear the accumulated discrepancies list."""
        self._discrepancies.clear()
