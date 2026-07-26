"""
RFC-0061 Bridge — Adapter between legacy RegistryService and new registry/ infrastructure.

Provides bidirectional conversion between:
- Legacy dict-based registry records (RegistryService._registry_objects)
- New RegistryObjectEnvelope models (ImmutableObjectStore)
- RegistryServiceAdapter wraps the legacy service with the new API surface
"""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from typing import Any

from .object_envelope import RegistryObjectEnvelope, ObjectVersion, LedgerCommitmentClass
from .storage import ImmutableObjectStore, StorageStats


# ---------------------------------------------------------------------------
# Field mapping: legacy dict ↔ RegistryObjectEnvelope
# ---------------------------------------------------------------------------

# Legacy record fields that map directly to envelope fields
LEGACY_TO_ENVELOPE_MAP: dict[str, str] = {
    "object_id": "object_id",
    "object_type": "object_type",
    "object_version": "object_version",
    "payload_encoding": "payload_encoding",
    "payload": "payload",
}

# Legacy payload_hash maps to content_hash
LEGACY_HASH_FIELD = "payload_hash"
ENVELOPE_HASH_FIELD = "content_hash"

# Legacy source_reference → parent_references[0] when present
LEGACY_SOURCE_REF_FIELD = "source_reference"

# Legacy namespace → stored in payload meta
LEGACY_NAMESPACE_FIELD = "namespace"


def _compute_content_hash(payload: dict) -> str:
    """Compute SHA-256 of canonical JSON payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _compute_content_size(payload: dict) -> int:
    """Compute byte size of canonical JSON payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return len(canonical.encode())


def _resolve_object_version(value: Any) -> ObjectVersion:
    """Map legacy object_version to ObjectVersion enum."""
    if isinstance(value, ObjectVersion):
        return value
    if isinstance(value, str):
        try:
            return ObjectVersion(value)
        except ValueError:
            return ObjectVersion.V1
    return ObjectVersion.V1


def _resolve_ledger_commitment(object_type: str) -> LedgerCommitmentClass | None:
    """Infer ledger commitment class from object_type."""
    TYPE_TO_COMMITMENT: dict[str, LedgerCommitmentClass] = {
        "reputation_profile": LedgerCommitmentClass.REPUTATION_PROFILE,
        "validation_report": LedgerCommitmentClass.VALIDATION_REPORT,
        "session_settlement": LedgerCommitmentClass.SESSION_SETTLEMENT,
        "session_failure": LedgerCommitmentClass.SESSION_FAILURE,
        "usage_report": LedgerCommitmentClass.USAGE_REPORT,
        "epoch_record": LedgerCommitmentClass.EPOCH_RECORD,
        "consensus_commitment": LedgerCommitmentClass.CONSENSUS_COMMITMENT,
        "registry_profile": LedgerCommitmentClass.REGISTRY_PROFILE,
        "advertisement": LedgerCommitmentClass.ADVERTISEMENT,
        "onboarding_capability": LedgerCommitmentClass.ADVERTISEMENT,
    }
    return TYPE_TO_COMMITMENT.get(object_type)


# ---------------------------------------------------------------------------
# Conversion functions
# ---------------------------------------------------------------------------

def legacy_record_to_envelope(record: dict) -> RegistryObjectEnvelope:
    """
    Convert a legacy RegistryService dict record to RegistryObjectEnvelope.

    Handles field mapping, hash computation, and version resolution.
    """
    payload = record.get("payload") or {}
    object_type = record.get("object_type", "unknown")

    envelope = RegistryObjectEnvelope(
        object_id=str(record.get("object_id", "")),
        object_type=object_type,
        object_version=_resolve_object_version(record.get("object_version", "1.0")),
        content_hash=record.get(LEGACY_HASH_FIELD) or _compute_content_hash(payload),
        content_size=record.get("content_size") or _compute_content_size(payload),
        created_epoch=record.get("created_epoch"),
        created_block_height=record.get("created_block_height"),
        ledger_commitment=_resolve_ledger_commitment(object_type),
        parent_references=(
            [record[LEGACY_SOURCE_REF_FIELD]]
            if record.get(LEGACY_SOURCE_REF_FIELD)
            else []
        ),
        payload_encoding=record.get("payload_encoding", "json"),
        payload=payload,
    )
    return envelope


def envelope_to_legacy_record(
    envelope: RegistryObjectEnvelope,
    *,
    namespace: str = "default",
    source_node_id: str | None = None,
) -> dict:
    """
    Convert a RegistryObjectEnvelope to a legacy RegistryService dict record.

    Suitable for passing to RegistryService.upsert_registry_object().
    """
    record: dict[str, Any] = {
        "object_id": envelope.object_id,
        "object_type": envelope.object_type,
        "object_version": envelope.object_version.value
        if hasattr(envelope.object_version, "value")
        else str(envelope.object_version),
        "namespace": namespace,
        "payload_hash": envelope.content_hash,
        "payload_encoding": envelope.payload_encoding,
        "source_reference": (
            envelope.parent_references[0]
            if envelope.parent_references
            else None
        ),
        "payload": deepcopy(envelope.payload) if envelope.payload else None,
    }
    if source_node_id is not None:
        record["_source"] = {
            "node_id": source_node_id,
            "operator_id": None,
            "status": "stored",
        }
    return record


# ---------------------------------------------------------------------------
# RegistryServiceAdapter — wraps legacy service with new API
# ---------------------------------------------------------------------------

class RegistryServiceAdapter:
    """
    Bridges the legacy RegistryService with the new registry/ infrastructure.

    Provides:
    - sync_from_legacy(): Populate ImmutableObjectStore from legacy records
    - sync_to_legacy(): Push new envelopes back to RegistryService
    - query(): Unified query interface
    - mirror(): Keep both stores in sync
    """

    def __init__(
        self,
        legacy_service: Any | None = None,
        store: ImmutableObjectStore | None = None,
    ):
        self._legacy = legacy_service
        self._store = store or ImmutableObjectStore()

    @property
    def store(self) -> ImmutableObjectStore:
        return self._store

    @property
    def legacy_service(self) -> Any | None:
        return self._legacy

    def sync_from_legacy(self, *, object_type: str | None = None) -> int:
        """
        Populate the ImmutableObjectStore from legacy RegistryService records.

        Returns the number of objects synced.
        """
        if self._legacy is None:
            return 0

        query: dict[str, Any] = {"include_payload": True}
        if object_type is not None:
            query["object_type"] = object_type

        try:
            records = self._legacy.list_registry_objects(query)
        except Exception:
            # Fallback: try direct access to _registry_objects
            if not hasattr(self._legacy, "_registry_objects"):
                return 0
            records = [
                deepcopy(v)
                for k, v in self._legacy._registry_objects.items()
                if object_type is None or v.get("object_type") == object_type
            ]

        synced = 0
        for record in records:
            try:
                envelope = legacy_record_to_envelope(record)
                if self._store.put(envelope):
                    synced += 1
            except Exception:
                continue

        return synced

    def sync_to_legacy(
        self,
        *,
        namespace: str = "default",
        source_node_id: str | None = None,
    ) -> int:
        """
        Push objects from ImmutableObjectStore to legacy RegistryService.

        Returns the number of objects pushed.
        """
        if self._legacy is None:
            return 0

        pushed = 0
        for object_id in self._store.all_ids():
            envelope = self._store.get(object_id)
            if envelope is None:
                continue

            try:
                record = envelope_to_legacy_record(
                    envelope,
                    namespace=namespace,
                    source_node_id=source_node_id,
                )
                self._legacy.upsert_registry_object(record, persist=False)
                pushed += 1
            except Exception:
                continue

        # Persist once after all upserts
        try:
            if hasattr(self._legacy, "_persist_registry_object_snapshot"):
                self._legacy._persist_registry_object_snapshot()
        except Exception:
            pass

        return pushed

    def query(
        self,
        *,
        object_type: str | None = None,
        include_payload: bool = True,
        source: str = "both",  # "store" | "legacy" | "both"
    ) -> list[dict]:
        """
        Unified query across both stores.

        When source="both", merges results preferring store-backed records.
        """
        results: dict[str, dict] = {}

        if source in ("store", "both"):
            if object_type:
                ids = self._store.list_by_type(object_type)
            else:
                ids = self._store.all_ids()

            for oid in ids:
                envelope = self._store.get(oid)
                if envelope is None:
                    continue
                row = {
                    "object_id": envelope.object_id,
                    "object_type": envelope.object_type,
                    "object_version": (
                        envelope.object_version.value
                        if hasattr(envelope.object_version, "value")
                        else str(envelope.object_version)
                    ),
                    "content_hash": envelope.content_hash,
                    "content_size": envelope.content_size,
                    "source": "store",
                }
                if include_payload and envelope.payload:
                    row["payload"] = deepcopy(envelope.payload)
                results[oid] = row

        if source in ("legacy", "both") and self._legacy is not None:
            try:
                query: dict[str, Any] = {"include_payload": include_payload}
                if object_type:
                    query["object_type"] = object_type
                legacy_records = self._legacy.list_registry_objects(query)
                for record in legacy_records:
                    oid = str(record.get("object_id", ""))
                    if oid not in results:  # store takes precedence
                        results[oid] = {
                            **record,
                            "source": "legacy",
                        }
            except Exception:
                pass

        return list(results.values())

    def mirror(self, *, direction: str = "both") -> dict[str, int]:
        """
        Synchronize both stores in the specified direction.

        Returns {"synced_from_legacy": N, "pushed_to_legacy": M}.
        """
        result: dict[str, int] = {
            "synced_from_legacy": 0,
            "pushed_to_legacy": 0,
        }

        if direction in ("from_legacy", "both") and self._legacy is not None:
            result["synced_from_legacy"] = self.sync_from_legacy()

        if direction in ("to_legacy", "both") and self._legacy is not None:
            result["pushed_to_legacy"] = self.sync_to_legacy()

        return result

    def get_stats(self) -> StorageStats:
        """Get storage stats from the ImmutableObjectStore."""
        return self._store.stats()

    def has_object(self, object_id: str) -> bool:
        """Check if object exists in the new store."""
        return self._store.has(object_id)

    def add_envelope(self, envelope: RegistryObjectEnvelope) -> bool:
        """Add a single envelope to the store."""
        return self._store.put(envelope)

    def add_legacy_record(self, record: dict) -> RegistryObjectEnvelope | None:
        """
        Add a legacy record by converting it to an envelope first.

        Returns the stored envelope or None on failure.
        """
        try:
            envelope = legacy_record_to_envelope(record)
            if self._store.put(envelope):
                return envelope
        except Exception:
            pass
        return None
