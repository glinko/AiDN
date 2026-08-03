"""Canonical replay protection for finalized Ledger operations."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def finalized_operation_digest(record: Mapping[str, Any]) -> str:
    """Return the digest of one immutable finalized operation record."""
    return hashlib.sha256(_canonical_json(record).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FinalizedOperationReference:
    """Replay-proof identity of one operation log entry."""

    operation_id: str
    operation_type: str
    sequence_id: int
    record_digest: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "sequence_id": self.sequence_id,
            "record_digest": self.record_digest,
        }


class FinalizedOperationRegistry:
    """Derived canonical index for replay and finalized-evidence checks.

    The operation log remains the committed source of truth. This index is a
    validated, deterministic projection of that log, so it can be rebuilt on
    restart without introducing a second mutable persistence authority.
    """

    def __init__(self) -> None:
        self._references: dict[str, FinalizedOperationReference] = {}

    @classmethod
    def from_records(cls, records: list[Mapping[str, Any]]) -> FinalizedOperationRegistry:
        registry = cls()
        for record in records:
            registry.register(record)
        return registry

    def register(self, record: Mapping[str, Any]) -> FinalizedOperationReference:
        operation_id = record.get("operation_id")
        operation_type = record.get("operation_type")
        sequence_id = record.get("sequence_id")
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("finalized operation ID is invalid")
        if not isinstance(operation_type, str) or not operation_type.strip():
            raise ValueError("finalized operation type is invalid")
        if isinstance(sequence_id, bool) or not isinstance(sequence_id, int) or sequence_id < 1:
            raise ValueError("finalized operation sequence is invalid")

        reference = FinalizedOperationReference(
            operation_id=operation_id,
            operation_type=operation_type,
            sequence_id=sequence_id,
            record_digest=finalized_operation_digest(record),
        )
        existing = self._references.get(operation_id)
        if existing is not None:
            if existing != reference:
                raise ValueError("conflicting finalized operation identity")
            raise ValueError("duplicate finalized operation ID")
        if any(reference.sequence_id == sequence_id for reference in self._references.values()):
            raise ValueError("finalized operation sequence is duplicated")
        self._references[operation_id] = reference
        return reference

    def contains(self, operation_id: str) -> bool:
        return operation_id in self._references

    def get(self, operation_id: str) -> FinalizedOperationReference | None:
        return self._references.get(operation_id)

    def require(
        self,
        operation_id: str,
        *,
        record_digest: str | None = None,
    ) -> FinalizedOperationReference:
        reference = self._references.get(operation_id)
        if reference is None:
            raise ValueError("finalized operation is not present in replay registry")
        if record_digest is not None and reference.record_digest != record_digest:
            raise ValueError("finalized operation digest conflicts with replay registry")
        return reference

    def operation_ids(self) -> set[str]:
        return set(self._references)

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            reference.as_dict()
            for reference in sorted(self._references.values(), key=lambda item: item.sequence_id)
        ]
