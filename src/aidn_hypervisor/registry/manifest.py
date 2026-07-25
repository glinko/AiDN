from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, Field

from .object_envelope import RegistryObjectEnvelope


class SegmentManifest(BaseModel, frozen=True):
    """
    RFC-0061 §21 — Deterministic manifest for a segment of objects.

    A segment covers a range of epochs or block heights.
    """

    segment_id: str
    start_epoch: int
    end_epoch: int
    start_block: int | None = None
    end_block: int | None = None
    object_ids: list[str] = Field(default_factory=list)
    object_count: int = 0
    total_bytes: int = 0
    manifest_hash: str = ""  # SHA-256 of sorted object_ids + metadata

    @classmethod
    def create(
        cls,
        *,
        segment_id: str,
        start_epoch: int,
        end_epoch: int,
        objects: list[RegistryObjectEnvelope],
        start_block: int | None = None,
        end_block: int | None = None,
    ) -> SegmentManifest:
        """Create a deterministic manifest from a list of objects."""
        # Sort by epoch, then block, then object_id for determinism
        sorted_objs = sorted(
            objects,
            key=lambda o: (
                o.created_epoch or 0,
                o.created_block_height or 0,
                o.object_id,
            ),
        )

        object_ids = [o.object_id for o in sorted_objs]
        total_bytes = sum(o.content_size for o in sorted_objs)

        # Compute manifest hash
        canonical = json.dumps({
            "segment_id": segment_id,
            "start_epoch": start_epoch,
            "end_epoch": end_epoch,
            "object_ids": object_ids,
            "total_bytes": total_bytes,
        }, sort_keys=True, separators=(",", ":"))
        manifest_hash = hashlib.sha256(canonical.encode()).hexdigest()

        return cls(
            segment_id=segment_id,
            start_epoch=start_epoch,
            end_epoch=end_epoch,
            start_block=start_block,
            end_block=end_block,
            object_ids=object_ids,
            object_count=len(object_ids),
            total_bytes=total_bytes,
            manifest_hash=manifest_hash,
        )

    def verify(self, objects: list[RegistryObjectEnvelope]) -> bool:
        """Verify that the given objects match this manifest."""
        if len(objects) != self.object_count:
            return False

        recreated = SegmentManifest.create(
            segment_id=self.segment_id,
            start_epoch=self.start_epoch,
            end_epoch=self.end_epoch,
            objects=objects,
        )
        return recreated.manifest_hash == self.manifest_hash


class InventoryRoot(BaseModel, frozen=True):
    """
    RFC-0061 §22 — Root hash of the complete inventory.

    Computed from segment manifests in epoch order.
    """

    epoch: int
    segment_hashes: list[str]  # sorted by segment_id
    root_hash: str  # SHA-256 of concatenated segment hashes
    timestamp: int = 0  # unix epoch

    @classmethod
    def create(
        cls,
        *,
        epoch: int,
        manifests: list[SegmentManifest],
        timestamp: int = 0,
    ) -> InventoryRoot:
        """Create inventory root from segment manifests."""
        sorted_manifests = sorted(manifests, key=lambda m: m.segment_id)
        segment_hashes = [m.manifest_hash for m in sorted_manifests]

        root_data = json.dumps({
            "epoch": epoch,
            "segment_hashes": segment_hashes,
        }, sort_keys=True, separators=(",", ":"))
        root_hash = hashlib.sha256(root_data.encode()).hexdigest()

        return cls(
            epoch=epoch,
            segment_hashes=segment_hashes,
            root_hash=root_hash,
            timestamp=timestamp,
        )

    def verify(self, manifests: list[SegmentManifest]) -> bool:
        """Verify that the manifests produce this root hash."""
        recreated = InventoryRoot.create(
            epoch=self.epoch,
            manifests=manifests,
        )
        return recreated.root_hash == self.root_hash
