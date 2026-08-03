"""Deterministic Registry repair and catch-up planning (RFC-0061 sections 43-47)."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from .manifest import RegistryInventoryManifest
from .object_envelope import RegistryObjectEnvelope
from .storage import ImmutableObjectStore


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class RegistryRepairPlan(BaseModel, frozen=True):
    """A bounded, immutable plan derived from two inventory manifests."""

    plan_id: str = Field(min_length=1)
    peer_id: str = Field(min_length=1)
    local_inventory_root: str = Field(min_length=1)
    remote_inventory_root: str = Field(min_length=1)
    remote_manifest_id: str = Field(min_length=1)
    missing_object_ids: list[str] = Field(default_factory=list)
    conflicting_object_ids: list[str] = Field(default_factory=list)
    local_only_object_ids: list[str] = Field(default_factory=list)
    created_at: float = 0.0
    mode: str = "catch_up"  # catch_up | repair | anti_entropy


class RegistryRepairResult(BaseModel, frozen=True):
    """Outcome of applying a verified repair batch."""

    plan_id: str
    accepted_object_ids: list[str] = Field(default_factory=list)
    duplicate_object_ids: list[str] = Field(default_factory=list)
    rejected_object_ids: list[str] = Field(default_factory=list)
    rejected_reasons: dict[str, str] = Field(default_factory=dict)
    completed: bool = False


class MultiPeerRepairPlan(BaseModel, frozen=True):
    """Deterministic source-selection plan for a set of Registry peers."""

    plan_id: str = Field(min_length=1)
    local_inventory_root: str = Field(min_length=1)
    peer_ids: list[str] = Field(default_factory=list)
    source_inventory_roots: dict[str, str] = Field(default_factory=dict)
    source_by_object: dict[str, str] = Field(default_factory=dict)
    object_commitments: dict[str, dict[str, Any]] = Field(default_factory=dict)
    target_object_ids: list[str] = Field(default_factory=list)
    conflicting_object_ids: list[str] = Field(default_factory=list)
    quorum_missing_object_ids: list[str] = Field(default_factory=list)
    conflict_evidence: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    minimum_independent_sources: int = Field(ge=1)
    evidence_root: str = Field(min_length=1)
    created_at: float = 0.0
    mode: str = "multi_peer_repair"


class MultiPeerRepairResult(BaseModel, frozen=True):
    """Outcome of applying one source's bounded portion of a multi-peer plan."""

    plan_id: str
    source_peer_id: str
    accepted_object_ids: list[str] = Field(default_factory=list)
    duplicate_object_ids: list[str] = Field(default_factory=list)
    rejected_object_ids: list[str] = Field(default_factory=list)
    rejected_reasons: dict[str, str] = Field(default_factory=dict)
    conflict_object_ids: list[str] = Field(default_factory=list)
    completed: bool = False


class RegistryRepairEngine:
    """Compare manifests and admit only objects matching the remote claim."""

    def __init__(self, store: ImmutableObjectStore) -> None:
        self._store = store

    def build_plan(
        self,
        *,
        peer_id: str,
        local_manifest: RegistryInventoryManifest,
        remote_manifest: RegistryInventoryManifest,
        mode: str = "catch_up",
        created_at: float | None = None,
    ) -> RegistryRepairPlan:
        if not peer_id:
            raise ValueError("peer_id is required")
        if not local_manifest.verify():
            raise ValueError("local inventory manifest is invalid")
        if not remote_manifest.verify():
            raise ValueError("remote inventory manifest is invalid")
        if mode not in {"catch_up", "repair", "anti_entropy"}:
            raise ValueError("unsupported Registry repair mode")

        local = self._manifest_objects(local_manifest)
        remote = self._manifest_objects(remote_manifest)
        missing = sorted(object_id for object_id in remote if object_id not in local)
        conflicts = sorted(
            object_id
            for object_id in remote.keys() & local.keys()
            if remote[object_id] != local[object_id]
        )
        local_only = sorted(object_id for object_id in local if object_id not in remote)
        plan_input = {
            "peer_id": peer_id,
            "local_inventory_root": local_manifest.inventory_root.root_hash,
            "remote_inventory_root": remote_manifest.inventory_root.root_hash,
            "remote_manifest_id": remote_manifest.manifest_id,
            "missing_object_ids": missing,
            "conflicting_object_ids": conflicts,
            "local_only_object_ids": local_only,
            "mode": mode,
        }
        return RegistryRepairPlan(
            plan_id="sha256:" + _canonical_digest(plan_input),
            created_at=time.time() if created_at is None else created_at,
            **plan_input,
        )

    def apply_batch(
        self,
        *,
        plan: RegistryRepairPlan,
        remote_manifest: RegistryInventoryManifest,
        envelopes: list[RegistryObjectEnvelope],
    ) -> RegistryRepairResult:
        if not remote_manifest.verify():
            raise ValueError("remote inventory manifest is invalid")
        if remote_manifest.inventory_root.root_hash != plan.remote_inventory_root:
            raise ValueError("repair plan remote inventory root mismatch")
        expected = self._manifest_objects(remote_manifest)
        missing = set(plan.missing_object_ids)
        accepted: list[str] = []
        duplicates: list[str] = []
        rejected: list[str] = []
        reasons: dict[str, str] = {}

        for envelope in envelopes:
            object_id = envelope.object_id
            expected_entry = expected.get(object_id)
            if object_id not in missing or expected_entry is None:
                rejected.append(object_id)
                reasons[object_id] = "object_not_requested_by_plan"
                continue
            expected_type, expected_hash, expected_size = expected_entry
            if (
                (expected_type != "*" and envelope.object_type != expected_type)
                or envelope.content_hash != expected_hash
                or envelope.content_size != expected_size
                or not envelope.verify_integrity()
            ):
                rejected.append(object_id)
                reasons[object_id] = "object_manifest_mismatch"
                continue
            existing = self._store.get(object_id, include_expired=True)
            if existing is not None:
                if existing != envelope:
                    rejected.append(object_id)
                    reasons[object_id] = "object_identity_conflict"
                else:
                    duplicates.append(object_id)
                continue
            if self._store.put(envelope):
                accepted.append(object_id)
            else:
                rejected.append(object_id)
                reasons[object_id] = "object_storage_rejected"

        remaining = missing.difference(accepted).difference(duplicates)
        return RegistryRepairResult(
            plan_id=plan.plan_id,
            accepted_object_ids=sorted(accepted),
            duplicate_object_ids=sorted(duplicates),
            rejected_object_ids=sorted(rejected),
            rejected_reasons=reasons,
            completed=not remaining,
        )

    def build_multi_peer_plan(
        self,
        *,
        local_manifest: RegistryInventoryManifest,
        peer_manifests: Mapping[str, RegistryInventoryManifest],
        minimum_independent_sources: int = 1,
        known_control_groups: Mapping[str, str] | None = None,
        peer_priorities: Mapping[str, int] | None = None,
        mode: str = "multi_peer_repair",
        created_at: float | None = None,
    ) -> MultiPeerRepairPlan:
        """Select repair sources only after deterministic independent quorum."""
        if not peer_manifests:
            raise ValueError("at least one peer manifest is required")
        if minimum_independent_sources < 1:
            raise ValueError("minimum_independent_sources must be positive")
        if mode not in {"multi_peer_repair", "anti_entropy", "quorum_repair"}:
            raise ValueError("unsupported multi-peer repair mode")
        if not local_manifest.verify():
            raise ValueError("local inventory manifest is invalid")

        groups = known_control_groups or {}
        priorities = peer_priorities or {}
        local = self._manifest_objects(local_manifest)
        remote_objects: dict[str, list[tuple[str, tuple[str, str, int]]]] = {}
        source_roots: dict[str, str] = {}
        for peer_id in sorted(peer_manifests):
            if not peer_id:
                raise ValueError("peer identifiers must not be empty")
            manifest = peer_manifests[peer_id]
            if not manifest.verify():
                raise ValueError(f"peer inventory manifest is invalid: {peer_id}")
            source_roots[peer_id] = manifest.inventory_root.root_hash
            for object_id, commitment in self._manifest_objects(manifest).items():
                remote_objects.setdefault(object_id, []).append((peer_id, commitment))

        source_by_object: dict[str, str] = {}
        object_commitments: dict[str, dict[str, Any]] = {}
        target_object_ids: list[str] = []
        conflicting_object_ids: list[str] = []
        quorum_missing_object_ids: list[str] = []
        conflict_evidence: dict[str, list[dict[str, Any]]] = {}

        for object_id in sorted(remote_objects):
            candidates = remote_objects[object_id]
            by_commitment: dict[tuple[str, str, int], list[str]] = {}
            for peer_id, commitment in candidates:
                by_commitment.setdefault(commitment, []).append(peer_id)
            if len(by_commitment) > 1:
                conflicting_object_ids.append(object_id)
                conflict_evidence[object_id] = [
                    {
                        "object_type": commitment[0],
                        "content_hash": commitment[1],
                        "content_size": commitment[2],
                        "peer_ids": sorted(peer_ids),
                        "independent_group_ids": sorted(
                            {groups.get(peer_id, peer_id) for peer_id in peer_ids}
                        ),
                    }
                    for commitment, peer_ids in sorted(by_commitment.items())
                ]

            ranked: list[tuple[int, int, str, tuple[str, str, int], list[str]]] = []
            for commitment, peer_ids in by_commitment.items():
                independent_groups = {groups.get(peer_id, peer_id) for peer_id in peer_ids}
                ranked.append(
                    (
                        len(independent_groups),
                        len(peer_ids),
                        -max((int(priorities.get(peer_id, 0)) for peer_id in peer_ids), default=0),
                        commitment,
                        sorted(peer_ids),
                    )
                )
            ranked.sort(key=lambda item: (-item[0], -item[1], item[2], item[3], item[4]))
            independent_count, _, _, winning_commitment, winning_peers = ranked[0]
            if independent_count < minimum_independent_sources:
                quorum_missing_object_ids.append(object_id)
                continue

            if object_id in local:
                if local[object_id] != winning_commitment:
                    # Immutable local state is never overwritten by a peer.
                    continue
                continue

            target_object_ids.append(object_id)
            source_peer = sorted(
                winning_peers,
                key=lambda peer_id: (-int(priorities.get(peer_id, 0)), peer_id),
            )[0]
            source_by_object[object_id] = source_peer
            object_commitments[object_id] = {
                "object_type": winning_commitment[0],
                "content_hash": winning_commitment[1],
                "content_size": winning_commitment[2],
                "independent_source_count": independent_count,
                "source_peer_ids": sorted(winning_peers),
            }

        evidence_payload = {
            "local_inventory_root": local_manifest.inventory_root.root_hash,
            "peer_ids": sorted(peer_manifests),
            "source_inventory_roots": source_roots,
            "source_by_object": source_by_object,
            "object_commitments": object_commitments,
            "target_object_ids": target_object_ids,
            "conflicting_object_ids": conflicting_object_ids,
            "quorum_missing_object_ids": quorum_missing_object_ids,
            "conflict_evidence": conflict_evidence,
            "minimum_independent_sources": minimum_independent_sources,
            "mode": mode,
        }
        return MultiPeerRepairPlan(
            plan_id="sha256:" + _canonical_digest(evidence_payload),
            local_inventory_root=local_manifest.inventory_root.root_hash,
            peer_ids=sorted(peer_manifests),
            source_inventory_roots=source_roots,
            source_by_object=source_by_object,
            object_commitments=object_commitments,
            target_object_ids=target_object_ids,
            conflicting_object_ids=sorted(set(conflicting_object_ids)),
            quorum_missing_object_ids=sorted(set(quorum_missing_object_ids)),
            conflict_evidence=conflict_evidence,
            minimum_independent_sources=minimum_independent_sources,
            evidence_root="sha256:" + _canonical_digest(evidence_payload),
            created_at=time.time() if created_at is None else created_at,
            mode=mode,
        )

    def apply_multi_peer_batch(
        self,
        *,
        plan: MultiPeerRepairPlan,
        source_peer_id: str,
        remote_manifest: RegistryInventoryManifest,
        envelopes: list[RegistryObjectEnvelope],
    ) -> MultiPeerRepairResult:
        """Apply only objects assigned to the authenticated selected source."""
        if source_peer_id not in plan.peer_ids:
            raise ValueError("source peer is not part of the repair plan")
        if remote_manifest.inventory_root.root_hash != plan.source_inventory_roots.get(source_peer_id):
            raise ValueError("source inventory root does not match repair plan")
        expected = self._manifest_objects(remote_manifest)
        assigned_ids = [
            object_id
            for object_id in plan.target_object_ids
            if plan.source_by_object.get(object_id) == source_peer_id
        ]
        rejected: list[str] = []
        reasons: dict[str, str] = {}
        filtered: list[RegistryObjectEnvelope] = []
        for envelope in envelopes:
            object_id = envelope.object_id
            commitment = plan.object_commitments.get(object_id)
            source_commitment = expected.get(object_id)
            if object_id not in assigned_ids:
                rejected.append(object_id)
                reasons[object_id] = "object_not_assigned_to_source"
                continue
            if commitment is None or source_commitment != (
                commitment.get("object_type"),
                commitment.get("content_hash"),
                commitment.get("content_size"),
            ):
                rejected.append(object_id)
                reasons[object_id] = "source_manifest_conflicts_with_quorum"
                continue
            filtered.append(envelope)

        single_plan = RegistryRepairPlan(
            plan_id=plan.plan_id,
            peer_id=source_peer_id,
            local_inventory_root=plan.local_inventory_root,
            remote_inventory_root=plan.source_inventory_roots[source_peer_id],
            remote_manifest_id=remote_manifest.manifest_id,
            missing_object_ids=assigned_ids,
            mode=plan.mode,
        )
        result = self.apply_batch(
            plan=single_plan,
            remote_manifest=remote_manifest,
            envelopes=filtered,
        )
        rejected.extend(result.rejected_object_ids)
        reasons.update(result.rejected_reasons)
        remaining = set(plan.target_object_ids).difference(
            result.accepted_object_ids,
            result.duplicate_object_ids,
        )
        return MultiPeerRepairResult(
            plan_id=plan.plan_id,
            source_peer_id=source_peer_id,
            accepted_object_ids=result.accepted_object_ids,
            duplicate_object_ids=result.duplicate_object_ids,
            rejected_object_ids=sorted(set(rejected)),
            rejected_reasons=reasons,
            conflict_object_ids=plan.conflicting_object_ids,
            completed=not remaining,
        )

    @staticmethod
    def _manifest_objects(
        manifest: RegistryInventoryManifest,
    ) -> dict[str, tuple[str, str, int]]:
        objects: dict[str, tuple[str, str, int]] = {}
        for segment in manifest.segments:
            if (
                len(segment.object_ids) != len(segment.content_hashes)
                or len(segment.object_ids) != len(segment.content_sizes)
            ):
                raise ValueError("inventory segment does not contain per-object hashes")
            for object_id, content_hash, content_size in zip(
                segment.object_ids,
                segment.content_hashes,
                segment.content_sizes,
                strict=True,
            ):
                objects[object_id] = (segment.object_type, content_hash, content_size)
        return objects
