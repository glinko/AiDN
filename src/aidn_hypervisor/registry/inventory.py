"""Inventory Exchange + Bloom Filters (RFC-0061 §§20, 24-25)."""

from __future__ import annotations

import hashlib
import math
import time

from pydantic import BaseModel, Field

from .storage import ImmutableObjectStore


class BloomFilter:
    """
    RFC-0061 §25 — Probabilistic membership filter for inventory exchange.

    Uses multiple hash functions (MurmurHash3 with different seeds)
    to reduce false positive rate.
    """

    def __init__(
        self,
        *,
        estimated_elements: int = 1000,
        false_positive_rate: float = 0.01,
    ) -> None:
        self._estimated_elements = max(1, estimated_elements)
        self._false_positive_rate = max(0.0001, min(false_positive_rate, 0.5))

        # Optimal sizing per standard Bloom filter formulas
        self._bits = max(
            64,
            int(-self._estimated_elements * math.log(self._false_positive_rate) / (math.log(2) ** 2)),
        )
        self._hash_count = max(2, int(math.log(2) * self._bits / self._estimated_elements))
        self._bit_array = bytearray(self._bits)
        self._count = 0

    @property
    def bit_count(self) -> int:
        """Number of bits in the filter."""
        return self._bits

    @property
    def hash_count(self) -> int:
        """Number of hash functions used."""
        return self._hash_count

    @property
    def element_count(self) -> int:
        """Number of elements added."""
        return self._count

    @staticmethod
    def _hash(item: str, index: int) -> int:
        """Multi-purpose hash using hashlib with dual-hash technique."""
        key = f"{index}:{item}".encode()
        h1 = int(hashlib.sha256(key).hexdigest()[:16], 16)
        h2 = int(hashlib.sha512(key).hexdigest()[:16], 16)
        return (h1 + index * h2)

    def add(self, item: str) -> None:
        """Add an item to the filter."""
        for i in range(self._hash_count):
            h = self._hash(item, i) % self._bits
            self._bit_array[h] = 1
        self._count += 1

    def might_contain(self, item: str) -> bool:
        """Check if item might be in the set (false positives possible)."""
        for i in range(self._hash_count):
            h = self._hash(item, i) % self._bits
            if self._bit_array[h] == 0:
                return False
        return True

    def definitely_not_contains(self, item: str) -> bool:
        """Check if item is definitely not in the set."""
        return not self.might_contain(item)

    def serialize(self) -> bytes:
        """Serialize the filter for network transfer."""
        return bytes(self._bit_array)

    @classmethod
    def deserialize(
        cls,
        data: bytes,
        *,
        estimated_elements: int = 1000,
        false_positive_rate: float = 0.01,
    ) -> BloomFilter:
        """Deserialize a filter from network data."""
        bf = cls(estimated_elements=estimated_elements, false_positive_rate=false_positive_rate)
        bf._bit_array = bytearray(data)
        return bf

    def merge(self, other: BloomFilter) -> None:
        """Merge another filter into this one (OR operation)."""
        if len(self._bit_array) != len(other._bit_array):
            raise ValueError("Bloom filter size mismatch")
        for i in range(len(self._bit_array)):
            if other._bit_array[i]:
                self._bit_array[i] = 1


class InventoryEntry(BaseModel, frozen=True):
    """Single entry in a registry inventory."""

    object_id: str
    object_type: str
    content_hash: str
    content_size: int
    epoch: int | None = None
    block_height: int | None = None


class InventorySummary(BaseModel, frozen=True):
    """RFC-0061 §20 — Registry inventory summary for exchange."""

    peer_id: str
    total_objects: int
    total_bytes: int
    earliest_epoch: int | None = None
    latest_epoch: int | None = None
    objects_by_type: dict[str, int] = Field(default_factory=dict)
    bloom_filter_size: int = 0
    timestamp: float = 0.0


class RetrievalPlan(BaseModel):
    """Plan for retrieving missing objects."""

    total_missing: int
    object_ids: list[str]
    priority: list[str] = Field(default_factory=list)
    normal: list[str] = Field(default_factory=list)


class InventoryExchange:
    """
    RFC-0061 §24 — Inventory exchange between registry peers.

    Compares inventories, identifies missing objects, and produces
    a retrieval plan.
    """

    def __init__(self, store: ImmutableObjectStore) -> None:
        self._store = store

    def build_summary(self, *, peer_id: str) -> InventorySummary:
        """Build an inventory summary from the local store."""
        stats = self._store.stats()
        return InventorySummary(
            peer_id=peer_id,
            total_objects=stats.total_objects,
            total_bytes=stats.total_bytes,
            earliest_epoch=stats.earliest_epoch,
            latest_epoch=stats.latest_epoch,
            objects_by_type=stats.objects_by_type,
            timestamp=time.time(),
        )

    def build_bloom_filter(self) -> BloomFilter:
        """Build a bloom filter from the local inventory."""
        stats = self._store.stats()
        bf = BloomFilter(estimated_elements=stats.total_objects or 1000)
        for oid in self._store.all_ids():
            bf.add(oid)
        return bf

    def find_missing(self, remote_bloom_filter: BloomFilter) -> list[str]:
        """
        Find objects that the remote peer is missing.

        Returns object_ids that we have but the remote likely doesn't.
        """
        missing: list[str] = []
        for oid in self._store.all_ids():
            if remote_bloom_filter.definitely_not_contains(oid):
                missing.append(oid)
        return missing

    def find_local_gaps(self, remote_inventory: list[str]) -> list[str]:
        """
        Find objects that the remote has but we don't.

        Returns object_ids from remote that we should request.
        """
        local_ids = set(self._store.all_ids())
        return [oid for oid in remote_inventory if oid not in local_ids]

    def build_retrieval_plan(self, remote_object_ids: list[str]) -> RetrievalPlan:
        """
        Build a prioritized plan to retrieve missing objects.
        """
        local_ids = set(self._store.all_ids())
        missing = [oid for oid in remote_object_ids if oid not in local_ids]

        # Prioritize: required types first, then by epoch
        priority_objects: list[str] = []
        normal_objects: list[str] = []

        for oid in missing:
            obj = self._store.get(oid)
            if obj is None:
                normal_objects.append(oid)

        return RetrievalPlan(
            total_missing=len(missing),
            object_ids=missing,
            priority=priority_objects,
            normal=normal_objects,
        )
