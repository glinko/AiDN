"""Finality-bound projection for consensus Reputation profile roots."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from aidn_hypervisor.consensus.finality import (
    ConsensusFinalityEvidence,
    ConsensusFinalitySource,
)


@dataclass(frozen=True)
class FinalizedReputationProfileUpdate:
    """An evidence-only profile update proven final by the active network."""

    operation_id: str
    object_id: str
    effective_epoch: int
    previous_profile_hash: str
    new_profile_hash: str
    evidence_root: str
    formula_version: str
    metric_deltas: dict[str, dict[str, int]]
    finality_evidence: ConsensusFinalityEvidence

    def model_dump(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "object_id": self.object_id,
            "effective_epoch": self.effective_epoch,
            "previous_profile_hash": self.previous_profile_hash,
            "new_profile_hash": self.new_profile_hash,
            "evidence_root": self.evidence_root,
            "formula_version": self.formula_version,
            "metric_deltas": self.metric_deltas,
            "finality_evidence": self.finality_evidence.model_dump(),
        }


class ReputationProfileFinalityAdapter:
    """Expose Reputation roots only after operation-bound finality evidence.

    The adapter is intentionally read-only. It does not calculate scores,
    ingest Reputation events, publish Marketplace data or move Q. A caller
    may use the returned immutable projection as the sole input to a later
    explicit profile-engine reconciliation step.
    """

    def __init__(self, *, ledger_service, finality_source: ConsensusFinalitySource | None) -> None:
        self._ledger_service = ledger_service
        self._finality_source = finality_source

    def resolve(
        self,
        *,
        object_id: str,
        effective_epoch: int | None = None,
    ) -> FinalizedReputationProfileUpdate | None:
        if not object_id.strip():
            raise ValueError("Reputation profile object_id is required")
        commitment = self._ledger_service.reputation_profile_update_commitment(
            object_id,
            effective_epoch=effective_epoch,
        )
        if commitment is None or self._finality_source is None:
            return None
        if commitment.get("operation_type") != "REPUTATION_PROFILE_UPDATE":
            return None
        operation_id = commitment.get("operation_id")
        payload = commitment.get("payload")
        if not isinstance(operation_id, str) or not operation_id.strip():
            return None
        if not isinstance(payload, dict):
            return None
        try:
            finality = self._finality_source.finality_evidence(operation_id)
        except Exception:
            return None
        if not isinstance(finality, ConsensusFinalityEvidence):
            return None
        if finality.operation_id != operation_id:
            return None
        required = (
            "object_id",
            "effective_epoch",
            "previous_profile_hash",
            "new_profile_hash",
            "evidence_root",
            "formula_version",
            "metric_deltas",
        )
        if any(field not in payload for field in required):
            return None
        if payload.get("object_id") != object_id:
            return None
        if effective_epoch is not None and payload.get("effective_epoch") != effective_epoch:
            return None
        if not isinstance(payload.get("effective_epoch"), int) or isinstance(
            payload.get("effective_epoch"), bool
        ):
            return None
        metric_deltas = self._normalize_metric_deltas(payload.get("metric_deltas"))
        if metric_deltas is None:
            return None
        hashes = (
            payload.get("previous_profile_hash"),
            payload.get("new_profile_hash"),
            payload.get("evidence_root"),
        )
        if any(
            not isinstance(value, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
            for value in hashes
        ):
            return None
        if hashes[0] == hashes[1] or payload.get("formula_version") != "reputation.v1":
            return None
        return FinalizedReputationProfileUpdate(
            operation_id=operation_id,
            object_id=object_id,
            effective_epoch=payload["effective_epoch"],
            previous_profile_hash=str(payload["previous_profile_hash"]),
            new_profile_hash=str(payload["new_profile_hash"]),
            evidence_root=str(payload["evidence_root"]),
            formula_version=str(payload["formula_version"]),
            metric_deltas=metric_deltas,
            finality_evidence=finality,
        )

    @staticmethod
    def _normalize_metric_deltas(value: object) -> dict[str, dict[str, int]] | None:
        if not isinstance(value, dict) or not value:
            return None
        required_fields = {
            "positive_mass_milli",
            "negative_mass_milli",
            "event_count",
        }
        normalized: dict[str, dict[str, int]] = {}
        for dimension, delta in value.items():
            if (
                not isinstance(dimension, str)
                or not dimension.strip()
                or not isinstance(delta, dict)
                or set(delta) != required_fields
            ):
                return None
            values: dict[str, int] = {}
            for field in required_fields:
                field_value = delta[field]
                if (
                    isinstance(field_value, bool)
                    or not isinstance(field_value, int)
                    or field_value < 0
                ):
                    return None
                values[field] = field_value
            if not any(values.values()):
                return None
            normalized[dimension] = values
        return normalized

    def require(
        self,
        *,
        object_id: str,
        effective_epoch: int | None = None,
    ) -> FinalizedReputationProfileUpdate:
        result = self.resolve(object_id=object_id, effective_epoch=effective_epoch)
        if result is None:
            raise ValueError("Reputation profile consensus finality is unavailable")
        return result


__all__ = [
    "FinalizedReputationProfileUpdate",
    "ReputationProfileFinalityAdapter",
]
