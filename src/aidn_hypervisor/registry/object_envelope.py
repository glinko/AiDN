from __future__ import annotations

import hashlib
import hmac
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Encode a Registry object payload using the committed JSON form."""
    return json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class ObjectVersion(StrEnum):
    """Registry object versioning."""

    V1 = "1.0"


class LedgerCommitmentClass(StrEnum):
    """How tightly an object is tied to the Ledger."""

    FINALIZED_BLOCK = "finalized_block"
    LEDGER_OPERATION = "ledger_operation"
    OPERATION_RESULT = "operation_result"
    STATE_SNAPSHOT = "state_snapshot"
    ADVERTISEMENT = "advertisement"
    VALIDATION_REPORT = "validation_report"
    SESSION_SETTLEMENT = "session_settlement"
    SESSION_FAILURE = "session_failure"
    USAGE_REPORT = "usage_report"
    REPUTATION_PROFILE = "reputation_profile"
    EPOCH_RECORD = "epoch_record"
    CONSENSUS_COMMITMENT = "consensus_commitment"
    REGISTRY_PROFILE = "registry_profile"
    DERIVED = "derived"  # not directly committed


class RegistryObjectEnvelope(BaseModel, frozen=True):
    """RFC-0061 §6 — Canonical envelope for all replicated objects."""

    object_id: str
    object_type: str
    namespace: str = "default"
    object_version: ObjectVersion = ObjectVersion.V1
    protocol_version: str = "1.0.0"
    content_hash: str = ""  # SHA-256 of payload
    content_size: int = 0  # bytes
    created_epoch: int | None = None
    created_block_height: int | None = None
    ledger_commitment: LedgerCommitmentClass | None = None
    parent_references: list[str] = Field(default_factory=list)
    previous_version_reference: str | None = None
    payload_encoding: str = "json"  # json | protobuf | raw
    compression: str | None = None  # gzip | none
    payload: dict[str, Any] = Field(default_factory=dict)
    producer_signature: str | None = None

    @classmethod
    def create(
        cls,
        *,
        object_type: str,
        payload: dict[str, Any],
        object_id: str | None = None,
        namespace: str = "default",
        created_epoch: int | None = None,
        created_block_height: int | None = None,
        ledger_commitment: LedgerCommitmentClass | None = None,
        parent_references: list[str] | None = None,
        previous_version_reference: str | None = None,
        producer_signature: str | None = None,
    ) -> RegistryObjectEnvelope:
        """Factory: compute id, hash, size from payload."""
        canonical = canonical_payload_bytes(payload)
        content_hash = hashlib.sha256(canonical).hexdigest()
        content_size = len(canonical)

        if object_id is None:
            object_id = content_hash  # content-addressed by default

        return cls(
            object_id=object_id,
            object_type=object_type,
            namespace=namespace,
            content_hash=content_hash,
            content_size=content_size,
            created_epoch=created_epoch,
            created_block_height=created_block_height,
            ledger_commitment=ledger_commitment,
            parent_references=parent_references or [],
            previous_version_reference=previous_version_reference,
            payload=payload,
            producer_signature=producer_signature,
        )

    def verify_integrity(self) -> bool:
        """Verify identity, content hash and content size against the payload."""
        if not self.object_id or not self.object_type or self.content_size < 0:
            return False
        try:
            canonical = canonical_payload_bytes(self.payload)
        except (TypeError, ValueError):
            return False
        expected_hash = hashlib.sha256(canonical).hexdigest()
        return hmac.compare_digest(expected_hash, self.content_hash) and len(canonical) == self.content_size


class ObjectIdentity(BaseModel, frozen=True):
    """RFC-0061 §7 — Deterministic object identity."""

    object_type: str
    identity_fields: dict[str, str]  # canonical fields → values

    @property
    def object_id(self) -> str:
        """Compute deterministic id from type + fields."""
        canonical = json.dumps(
            {"type": self.object_type, **self.identity_fields},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()
