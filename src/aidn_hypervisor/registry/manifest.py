from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from .object_envelope import RegistryObjectEnvelope


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _hash_without_prefix(value: str | None) -> str:
    text = str(value or "")
    if text.startswith("sha256:"):
        return text.removeprefix("sha256:")
    return text


class ManifestObjectEntry(BaseModel, frozen=True):
    """The public, payload-free inventory evidence for one Registry Object."""

    object_id: str = Field(min_length=1)
    object_type: str = Field(min_length=1)
    created_epoch: int | None = None
    created_block_height: int | None = None
    content_hash: str = ""
    content_size: int = 0

    @classmethod
    def from_object(
        cls,
        value: RegistryObjectEnvelope | Mapping[str, Any] | ManifestObjectEntry,
    ) -> ManifestObjectEntry:
        if isinstance(value, ManifestObjectEntry):
            return value
        if isinstance(value, RegistryObjectEnvelope):
            return cls(
                object_id=value.object_id,
                object_type=value.object_type,
                created_epoch=value.created_epoch,
                created_block_height=value.created_block_height,
                content_hash=_hash_without_prefix(value.content_hash),
                content_size=max(0, int(value.content_size)),
            )
        if not isinstance(value, Mapping):
            raise TypeError("manifest objects must be Registry envelopes or mappings")
        payload = value.get("payload")
        content_size = value.get("content_size")
        if content_size is None and payload is not None:
            encoded = json.dumps(
                payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            content_size = len(encoded)
        return cls(
            object_id=str(value.get("object_id") or ""),
            object_type=str(value.get("object_type") or ""),
            created_epoch=value.get("created_epoch"),
            created_block_height=value.get("created_block_height"),
            content_hash=_hash_without_prefix(
                value.get("content_hash") or value.get("payload_hash")
            ),
            content_size=max(0, int(content_size or 0)),
        )


def _entry_sort_key(entry: ManifestObjectEntry) -> tuple[str, int, int, str]:
    return (
        entry.object_type,
        -1 if entry.created_block_height is None else int(entry.created_block_height),
        -1 if entry.created_epoch is None else int(entry.created_epoch),
        entry.object_id,
    )


_MERKLE_DOMAIN = "aidn.registry.segment-leaf.v1"
_MERKLE_EMPTY_DOMAIN = "aidn.registry.segment-empty.v1"


class MerkleProofStep(BaseModel, frozen=True):
    """One sibling in a deterministic segment Merkle inclusion path."""

    side: str
    hash: str = Field(min_length=1)


class SegmentMerkleProof(BaseModel, frozen=True):
    """Proof that one object/hash/size tuple belongs to a segment root."""

    profile_version: str = "segment-merkle.v1"
    object_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    content_size: int = Field(ge=0)
    leaf_hash: str = Field(min_length=1)
    leaf_index: int = Field(ge=0)
    leaf_count: int = Field(ge=1)
    siblings: list[MerkleProofStep] = Field(default_factory=list)
    root_hash: str = Field(min_length=1)


def _merkle_leaf_hash(*, object_id: str, content_hash: str, content_size: int) -> str:
    return _canonical_digest(
        {
            "domain": _MERKLE_DOMAIN,
            "object_id": object_id,
            "content_hash": content_hash,
            "content_size": int(content_size),
        }
    )


def _merkle_empty_hash() -> str:
    return _canonical_digest({"domain": _MERKLE_EMPTY_DOMAIN})


def _merkle_parent(left: str, right: str) -> str:
    return _canonical_digest(
        {
            "domain": "aidn.registry.segment-node.v1",
            "left": left,
            "right": right,
        }
    )


def _merkle_root(leaves: list[str]) -> str:
    if not leaves:
        return _merkle_empty_hash()
    level = list(leaves)
    while len(level) > 1:
        next_level: list[str] = []
        for index in range(0, len(level), 2):
            right = level[index + 1] if index + 1 < len(level) else level[index]
            next_level.append(_merkle_parent(level[index], right))
        level = next_level
    return level[0]


def _build_merkle_proof(
    *,
    object_ids: list[str],
    content_hashes: list[str],
    content_sizes: list[int],
    object_id: str,
) -> SegmentMerkleProof:
    if not object_ids or len(object_ids) != len(content_hashes) or len(object_ids) != len(content_sizes):
        raise ValueError("segment Merkle proof input is invalid")
    try:
        leaf_index = object_ids.index(object_id)
    except ValueError as error:
        raise ValueError("object is not present in segment") from error
    leaves = [
        _merkle_leaf_hash(
            object_id=candidate_id,
            content_hash=content_hash,
            content_size=content_size,
        )
        for candidate_id, content_hash, content_size in zip(
            object_ids,
            content_hashes,
            content_sizes,
            strict=True,
        )
    ]
    index = leaf_index
    level = leaves
    siblings: list[MerkleProofStep] = []
    while len(level) > 1:
        if index % 2:
            sibling_index = index - 1
            side = "left"
        else:
            sibling_index = index + 1 if index + 1 < len(level) else index
            side = "right"
        siblings.append(MerkleProofStep(side=side, hash=level[sibling_index]))
        next_level: list[str] = []
        for pair_index in range(0, len(level), 2):
            right = level[pair_index + 1] if pair_index + 1 < len(level) else level[pair_index]
            next_level.append(_merkle_parent(level[pair_index], right))
        level = next_level
        index //= 2
    leaf_hash = leaves[leaf_index]
    return SegmentMerkleProof(
        object_id=object_id,
        content_hash=content_hashes[leaf_index],
        content_size=content_sizes[leaf_index],
        leaf_hash=leaf_hash,
        leaf_index=leaf_index,
        leaf_count=len(leaves),
        siblings=siblings,
        root_hash=level[0],
    )


def verify_segment_merkle_proof(proof: SegmentMerkleProof) -> bool:
    if proof.profile_version != "segment-merkle.v1":
        return False
    if proof.leaf_index >= proof.leaf_count:
        return False
    expected_levels = 0
    level_width = proof.leaf_count
    while level_width > 1:
        expected_levels += 1
        level_width = (level_width + 1) // 2
    if len(proof.siblings) != expected_levels:
        return False
    expected_leaf = _merkle_leaf_hash(
        object_id=proof.object_id,
        content_hash=proof.content_hash,
        content_size=proof.content_size,
    )
    if expected_leaf != proof.leaf_hash:
        return False
    current = proof.leaf_hash
    for step in proof.siblings:
        if step.side == "left":
            current = _merkle_parent(step.hash, current)
        elif step.side == "right":
            current = _merkle_parent(current, step.hash)
        else:
            return False
    return current == proof.root_hash


class SegmentManifest(BaseModel, frozen=True):
    """RFC-0061 deterministic inventory segment manifest."""

    segment_id: str
    object_type: str = "*"
    profile_version: str = "registry-inventory.v1"
    start_epoch: int
    end_epoch: int
    start_block: int | None = None
    end_block: int | None = None
    object_ids: list[str] = Field(default_factory=list)
    # Hashes are payload-free and let a challenger verify one object against
    # the segment content root without downloading the complete segment.
    content_hashes: list[str] = Field(default_factory=list)
    content_sizes: list[int] = Field(default_factory=list)
    object_count: int = 0
    total_bytes: int = 0
    total_content_size: int = 0
    object_id_root: str = ""
    content_hash_root: str = ""
    content_merkle_root: str = ""
    merkle_profile_version: str = "segment-merkle.v1"
    first_object_id: str | None = None
    last_object_id: str | None = None
    generated_at_height: int | None = None
    generation: int = 1
    manifest_hash: str = ""
    manifest_id: str = ""

    @classmethod
    def create(
        cls,
        *,
        segment_id: str,
        start_epoch: int,
        end_epoch: int,
        objects: Sequence[RegistryObjectEnvelope | Mapping[str, Any] | ManifestObjectEntry],
        object_type: str | None = None,
        profile_version: str = "registry-inventory.v1",
        start_block: int | None = None,
        end_block: int | None = None,
        generated_at_height: int | None = None,
        generation: int = 1,
    ) -> SegmentManifest:
        entries = sorted(
            (ManifestObjectEntry.from_object(value) for value in objects),
            key=_entry_sort_key,
        )
        object_ids = [entry.object_id for entry in entries]
        content_hashes = [entry.content_hash for entry in entries]
        content_sizes = [entry.content_size for entry in entries]
        object_types = {entry.object_type for entry in entries}
        selected_object_type = object_type or (
            next(iter(object_types)) if len(object_types) == 1 else "*"
        )
        object_id_root = _canonical_digest(object_ids)
        content_hash_root = _canonical_digest(
            [
                {
                    "object_id": entry.object_id,
                    "content_hash": entry.content_hash,
                }
                for entry in entries
            ]
        )
        total_content_size = sum(entry.content_size for entry in entries)
        content_merkle_root = _merkle_root(
            [
                _merkle_leaf_hash(
                    object_id=entry.object_id,
                    content_hash=entry.content_hash,
                    content_size=entry.content_size,
                )
                for entry in entries
            ]
        )
        identity_payload = {
            "segment_id": segment_id,
            "object_type": selected_object_type,
            "profile_version": profile_version,
            "start_epoch": int(start_epoch),
            "end_epoch": int(end_epoch),
            "start_block": start_block,
            "end_block": end_block,
            "generation": int(generation),
        }
        manifest_id = f"sha256:{_canonical_digest(identity_payload)}"
        hash_payload = {
            **identity_payload,
            "object_count": len(entries),
            "total_content_size": total_content_size,
            "object_id_root": object_id_root,
            "content_hash_root": content_hash_root,
            "content_merkle_root": content_merkle_root,
            "merkle_profile_version": "segment-merkle.v1",
            "first_object_id": object_ids[0] if object_ids else None,
            "last_object_id": object_ids[-1] if object_ids else None,
            "generated_at_height": generated_at_height,
            "manifest_id": manifest_id,
        }
        manifest_hash = _canonical_digest(hash_payload)
        return cls(
            segment_id=segment_id,
            object_type=selected_object_type,
            profile_version=profile_version,
            start_epoch=start_epoch,
            end_epoch=end_epoch,
            start_block=start_block,
            end_block=end_block,
            object_ids=object_ids,
            content_hashes=content_hashes,
            content_sizes=content_sizes,
            object_count=len(entries),
            total_bytes=total_content_size,
            total_content_size=total_content_size,
            object_id_root=object_id_root,
            content_hash_root=content_hash_root,
            content_merkle_root=content_merkle_root,
            merkle_profile_version="segment-merkle.v1",
            first_object_id=object_ids[0] if object_ids else None,
            last_object_id=object_ids[-1] if object_ids else None,
            generated_at_height=generated_at_height,
            generation=generation,
            manifest_hash=manifest_hash,
            manifest_id=manifest_id,
        )

    def verify(
        self,
        objects: Sequence[RegistryObjectEnvelope | Mapping[str, Any] | ManifestObjectEntry],
    ) -> bool:
        """Verify object count, ordering, content roots and manifest identity."""
        recreated = SegmentManifest.create(
            segment_id=self.segment_id,
            start_epoch=self.start_epoch,
            end_epoch=self.end_epoch,
            objects=objects,
            object_type=self.object_type,
            profile_version=self.profile_version,
            start_block=self.start_block,
            end_block=self.end_block,
            generated_at_height=self.generated_at_height,
            generation=self.generation,
        )
        return recreated.model_dump(mode="json") == self.model_dump(mode="json")

    def verify_self(self) -> bool:
        """Verify the self-contained roots and manifest commitment."""
        if self.merkle_profile_version != "segment-merkle.v1":
            return False
        if self.object_count != len(self.object_ids):
            return False
        if len(set(self.object_ids)) != self.object_count:
            return False
        if len(self.content_hashes) != self.object_count:
            return False
        if len(self.content_sizes) != self.object_count:
            return False
        if any(size < 0 for size in self.content_sizes):
            return False
        if self.total_bytes != self.total_content_size:
            return False
        if self.object_ids:
            if self.first_object_id != self.object_ids[0] or self.last_object_id != self.object_ids[-1]:
                return False
        identity_payload = {
            "segment_id": self.segment_id,
            "object_type": self.object_type,
            "profile_version": self.profile_version,
            "start_epoch": int(self.start_epoch),
            "end_epoch": int(self.end_epoch),
            "start_block": self.start_block,
            "end_block": self.end_block,
            "generation": int(self.generation),
        }
        manifest_id = f"sha256:{_canonical_digest(identity_payload)}"
        if manifest_id != self.manifest_id:
            return False
        if _canonical_digest(self.object_ids) != self.object_id_root:
            return False
        if _canonical_digest(
            [
                {"object_id": object_id, "content_hash": content_hash}
                for object_id, content_hash in zip(
                    self.object_ids,
                    self.content_hashes,
                    strict=True,
                )
            ]
        ) != self.content_hash_root:
            return False
        expected_merkle_root = _merkle_root(
            [
                _merkle_leaf_hash(
                    object_id=object_id,
                    content_hash=content_hash,
                    content_size=content_size,
                )
                for object_id, content_hash, content_size in zip(
                    self.object_ids,
                    self.content_hashes,
                    self.content_sizes,
                    strict=True,
                )
            ]
        )
        if expected_merkle_root != self.content_merkle_root:
            return False
        expected_hash = _canonical_digest(
            {
                **identity_payload,
                "object_count": self.object_count,
                "total_content_size": self.total_content_size,
                "object_id_root": self.object_id_root,
                "content_hash_root": self.content_hash_root,
                "content_merkle_root": self.content_merkle_root,
                "merkle_profile_version": self.merkle_profile_version,
                "first_object_id": self.first_object_id,
                "last_object_id": self.last_object_id,
                "generated_at_height": self.generated_at_height,
                "manifest_id": manifest_id,
            }
        )
        return expected_hash == self.manifest_hash

    def build_merkle_proof(self, object_id: str) -> SegmentMerkleProof:
        """Build an inclusion proof for one object in this segment."""
        if self.merkle_profile_version != "segment-merkle.v1":
            raise ValueError("segment does not support the Merkle proof profile")
        return _build_merkle_proof(
            object_ids=self.object_ids,
            content_hashes=self.content_hashes,
            content_sizes=self.content_sizes,
            object_id=object_id,
        )


class InventoryRoot(BaseModel, frozen=True):
    """RFC-0061 root over deterministic segment manifest identities."""

    epoch: int
    profile_version: str = "registry-inventory.v1"
    generation: int = 1
    segment_ids: list[str] = Field(default_factory=list)
    segment_hashes: list[str] = Field(default_factory=list)
    root_hash: str
    timestamp: int = 0
    inventory_id: str = ""

    @classmethod
    def create(
        cls,
        *,
        epoch: int,
        manifests: Sequence[SegmentManifest],
        timestamp: int = 0,
        profile_version: str = "registry-inventory.v1",
        generation: int = 1,
    ) -> InventoryRoot:
        sorted_manifests = sorted(manifests, key=lambda manifest: manifest.segment_id)
        segment_ids = [manifest.segment_id for manifest in sorted_manifests]
        segment_hashes = [manifest.manifest_hash for manifest in sorted_manifests]
        root_hash = _canonical_digest(
            {
                "epoch": int(epoch),
                "profile_version": profile_version,
                "generation": int(generation),
                "segments": [
                    {
                        "segment_id": manifest.segment_id,
                        "manifest_id": manifest.manifest_id,
                        "manifest_hash": manifest.manifest_hash,
                    }
                    for manifest in sorted_manifests
                ],
            }
        )
        inventory_id = "sha256:" + _canonical_digest(
            {
                "epoch": int(epoch),
                "profile_version": profile_version,
                "generation": int(generation),
                "root_hash": root_hash,
            }
        )
        return cls(
            epoch=epoch,
            profile_version=profile_version,
            generation=generation,
            segment_ids=segment_ids,
            segment_hashes=segment_hashes,
            root_hash=root_hash,
            timestamp=timestamp,
            inventory_id=inventory_id,
        )

    def verify(self, manifests: Sequence[SegmentManifest]) -> bool:
        recreated = InventoryRoot.create(
            epoch=self.epoch,
            manifests=manifests,
            timestamp=self.timestamp,
            profile_version=self.profile_version,
            generation=self.generation,
        )
        return recreated.model_dump(mode="json") == self.model_dump(mode="json") and all(
            manifest.verify_self() for manifest in manifests
        )


class RegistryInventoryManifest(BaseModel, frozen=True):
    """Top-level local inventory commitment used before peer replication."""

    registry_service_id: str
    profile_version: str = "registry-inventory.v1"
    generation: int = 1
    generated_at_epoch: int
    generated_at_height: int | None = None
    retention_policy_hash: str
    segments: list[SegmentManifest] = Field(default_factory=list)
    inventory_root: InventoryRoot
    manifest_hash: str
    manifest_id: str

    @classmethod
    def create(
        cls,
        *,
        registry_service_id: str,
        generated_at_epoch: int,
        objects: Sequence[RegistryObjectEnvelope | Mapping[str, Any] | ManifestObjectEntry],
        retention_policy_hash: str,
        generated_at_height: int | None = None,
        generation: int = 1,
        profile_version: str = "registry-inventory.v1",
    ) -> RegistryInventoryManifest:
        entries = [ManifestObjectEntry.from_object(value) for value in objects]
        groups: dict[str, list[ManifestObjectEntry]] = {}
        for entry in entries:
            groups.setdefault(entry.object_type or "*", []).append(entry)
        segments: list[SegmentManifest] = []
        for object_type in sorted(groups):
            group = groups[object_type]
            epochs = [entry.created_epoch for entry in group if entry.created_epoch is not None]
            blocks = [
                entry.created_block_height
                for entry in group
                if entry.created_block_height is not None
            ]
            segments.append(
                SegmentManifest.create(
                    segment_id=f"{object_type}:all",
                    object_type=object_type,
                    profile_version=profile_version,
                    start_epoch=min(epochs) if epochs else generated_at_epoch,
                    end_epoch=max(epochs) if epochs else generated_at_epoch,
                    start_block=min(blocks) if blocks else None,
                    end_block=max(blocks) if blocks else None,
                    generated_at_height=generated_at_height,
                    generation=generation,
                    objects=group,
                )
            )
        inventory_root = InventoryRoot.create(
            epoch=generated_at_epoch,
            manifests=segments,
            profile_version=profile_version,
            generation=generation,
        )
        hash_payload = {
            "registry_service_id": registry_service_id,
            "profile_version": profile_version,
            "generation": generation,
            "generated_at_epoch": generated_at_epoch,
            "generated_at_height": generated_at_height,
            "retention_policy_hash": retention_policy_hash,
            "inventory_id": inventory_root.inventory_id,
            "root_hash": inventory_root.root_hash,
        }
        manifest_hash = _canonical_digest(hash_payload)
        manifest_id = "sha256:" + _canonical_digest(
            {
                "registry_service_id": registry_service_id,
                "profile_version": profile_version,
                "generation": generation,
                "generated_at_epoch": generated_at_epoch,
                "root_hash": inventory_root.root_hash,
            }
        )
        return cls(
            registry_service_id=registry_service_id,
            profile_version=profile_version,
            generation=generation,
            generated_at_epoch=generated_at_epoch,
            generated_at_height=generated_at_height,
            retention_policy_hash=retention_policy_hash,
            segments=segments,
            inventory_root=inventory_root,
            manifest_hash=manifest_hash,
            manifest_id=manifest_id,
        )

    def verify(self) -> bool:
        return self.inventory_root.verify(self.segments) and self.manifest_hash == _canonical_digest(
            {
                "registry_service_id": self.registry_service_id,
                "profile_version": self.profile_version,
                "generation": self.generation,
                "generated_at_epoch": self.generated_at_epoch,
                "generated_at_height": self.generated_at_height,
                "retention_policy_hash": self.retention_policy_hash,
                "inventory_id": self.inventory_root.inventory_id,
                "root_hash": self.inventory_root.root_hash,
            }
        )
