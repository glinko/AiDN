from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .object_envelope import RegistryObjectEnvelope
from .retention import RegistryRetentionPolicy


@dataclass
class StorageStats:
    """Storage engine statistics."""

    total_objects: int = 0
    total_bytes: int = 0
    objects_by_type: dict[str, int] = field(default_factory=dict)
    earliest_epoch: int | None = None
    latest_epoch: int | None = None


class ImmutableObjectStore:
    """
    RFC-0061 §4 — Immutable content-addressed object storage.

    All objects are append-only. Once stored, an object cannot be
    modified or deleted (soft delete via tombstone only).
    """

    def __init__(self):
        self._objects: dict[str, RegistryObjectEnvelope] = {}
        self._type_index: dict[str, list[str]] = defaultdict(list)
        self._epoch_index: dict[int, list[str]] = defaultdict(list)
        self._insertion_order: list[str] = []  # for deterministic iteration
        self._tombstones: set[str] = set()
        self._expired: set[str] = set()

    def put(self, envelope: RegistryObjectEnvelope) -> bool:
        """
        Store an object. Returns True if stored, False if already exists.
        Rejects if object_id already maps to a different object.
        """
        if not envelope.verify_integrity():
            raise ValueError("Registry object envelope integrity check failed")
        if envelope.object_id in self._objects:
            existing = self._objects[envelope.object_id]
            if existing != envelope:
                return False  # conflict
            return False  # duplicate
        if envelope.object_id in self._tombstones:
            return False  # tombstoned

        self._objects[envelope.object_id] = envelope
        self._type_index[envelope.object_type].append(envelope.object_id)
        if envelope.created_epoch is not None:
            self._epoch_index[envelope.created_epoch].append(envelope.object_id)
        self._insertion_order.append(envelope.object_id)
        return True

    def get(
        self,
        object_id: str,
        *,
        include_expired: bool = False,
    ) -> RegistryObjectEnvelope | None:
        """Retrieve an object, optionally including retention-expired entries."""
        if object_id in self._tombstones or (
            object_id in self._expired and not include_expired
        ):
            return None
        return self._objects.get(object_id)

    def get_many(
        self,
        object_ids: list[str],
        *,
        include_expired: bool = False,
    ) -> list[RegistryObjectEnvelope]:
        """Batch retrieval."""
        result = []
        for oid in object_ids:
            obj = self.get(oid, include_expired=include_expired)
            if obj is not None:
                result.append(obj)
        return result

    def list_by_type(
        self,
        object_type: str,
        *,
        include_tombstoned: bool = False,
        include_expired: bool = False,
        limit: int | None = None,
    ) -> list[RegistryObjectEnvelope]:
        """List objects of a given type."""
        ids = self._type_index.get(object_type, [])
        result = []
        for oid in ids:
            if not include_tombstoned and oid in self._tombstones:
                continue
            if not include_expired and oid in self._expired:
                continue
            obj = self._objects.get(oid)
            if obj is not None:
                result.append(obj)
            if limit and len(result) >= limit:
                break
        return result

    def list_by_epoch(
        self,
        epoch: int,
        *,
        include_tombstoned: bool = False,
        include_expired: bool = False,
    ) -> list[RegistryObjectEnvelope]:
        """List objects from a given epoch."""
        ids = self._epoch_index.get(epoch, [])
        result = []
        for oid in ids:
            if not include_tombstoned and oid in self._tombstones:
                continue
            if not include_expired and oid in self._expired:
                continue
            obj = self._objects.get(oid)
            if obj is not None:
                result.append(obj)
        return result

    def has(self, object_id: str, *, include_expired: bool = False) -> bool:
        """Check if object exists and is visible under the requested lifecycle view."""
        return (
            object_id in self._objects
            and object_id not in self._tombstones
            and (include_expired or object_id not in self._expired)
        )

    def tombstone(self, object_id: str) -> bool:
        """Soft-delete an object. Returns True if tombstoned."""
        if object_id not in self._objects:
            return False
        self._tombstones.add(object_id)
        return True

    def delete(self, object_id: str) -> bool:
        """Hard delete (only for testing / emergency)."""
        if object_id not in self._objects:
            return False
        del self._objects[object_id]
        self._tombstones.discard(object_id)
        self._expired.discard(object_id)
        self._insertion_order.remove(object_id)
        return True

    def all_ids(self, *, include_expired: bool = False) -> list[str]:
        """All object ids in deterministic insertion order."""
        return [
            oid
            for oid in self._insertion_order
            if oid not in self._tombstones
            and (include_expired or oid not in self._expired)
        ]

    def stats(self) -> StorageStats:
        """Storage statistics."""
        ids = self.all_ids()
        epochs = []
        by_type: dict[str, int] = {}
        total_bytes = 0

        for oid in ids:
            obj = self._objects.get(oid)
            if obj:
                total_bytes += obj.content_size
                by_type[obj.object_type] = by_type.get(obj.object_type, 0) + 1
                if obj.created_epoch is not None:
                    epochs.append(obj.created_epoch)

        return StorageStats(
            total_objects=len(ids),
            total_bytes=total_bytes,
            objects_by_type=by_type,
            earliest_epoch=min(epochs) if epochs else None,
            latest_epoch=max(epochs) if epochs else None,
        )

    def snapshot(
        self,
        *,
        include_expired: bool = False,
    ) -> dict[str, RegistryObjectEnvelope]:
        """Create a snapshot of visible objects (for testing/replication)."""
        return {
            oid: self._objects[oid]
            for oid in self.all_ids(include_expired=include_expired)
        }

    def expired_ids(self) -> list[str]:
        """Return retention-expired object ids in deterministic insertion order."""
        return [
            oid
            for oid in self._insertion_order
            if oid in self._expired and oid not in self._tombstones
        ]

    def is_expired(self, object_id: str) -> bool:
        return object_id in self._expired

    def apply_retention(
        self,
        *,
        current_epoch: int,
        policy: RegistryRetentionPolicy,
        apply: bool = True,
        limit: int | None = None,
    ) -> dict:
        """Evaluate and optionally enforce explicit/versioned retention expiry.

        Expiry is a visibility transition, not a destructive delete. An expired
        object remains retrievable with ``include_expired=True`` and keeps its
        object identity for audit and replication repair.
        """
        candidates: list[tuple[str, int | None]] = []
        for object_id in self._insertion_order:
            if object_id in self._tombstones:
                continue
            envelope = self._objects[object_id]
            expiration_epoch = policy.expiration_epoch_for(
                created_epoch=envelope.created_epoch,
                retention_class=envelope.retention_class,
                explicit_expiration_epoch=envelope.expiration_epoch,
            )
            if policy.is_expired(
                current_epoch=current_epoch,
                expiration_epoch=expiration_epoch,
            ):
                candidates.append((object_id, expiration_epoch))

        if limit is not None:
            candidates = candidates[: max(0, int(limit))]
        expired_ids = [object_id for object_id, _ in candidates]
        newly_expired = [object_id for object_id in expired_ids if object_id not in self._expired]
        if apply:
            self._expired.update(expired_ids)
        return {
            "current_epoch": int(current_epoch),
            "policy_hash": policy.policy_hash,
            "applied": bool(apply),
            "expired_count": len(expired_ids),
            "newly_expired_count": len(newly_expired),
            "expired_ids": expired_ids,
            "expiration_epochs": {
                object_id: expiration_epoch
                for object_id, expiration_epoch in candidates
            },
        }
