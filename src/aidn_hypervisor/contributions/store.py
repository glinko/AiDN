"""Durable local storage for RFC-0068 evidence objects.

The store is intentionally independent from the economic Ledger snapshot.  A
missing or corrupt evidence file must never be interpreted as permission to
mint or transfer Q.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from aidn_hypervisor.contributions.models import (
    ContributionAttestation,
    ContributionChallenge,
    ContributionChallengeResolution,
    ContributionGroup,
    ContributionMaturityRecord,
    ContributionMergeEvent,
    ContributorIdentity,
    ContributorWalletBinding,
    ContributorWalletBindingChallenge,
    EligibleRepository,
    RepositoryContributionProfile,
)

T = TypeVar("T", bound=BaseModel)


class ContributionEvidenceStore:
    """Small file-backed repository with atomic snapshots and idempotent reads."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._lock = threading.RLock()
        self.repositories: dict[str, EligibleRepository] = {}
        self.profiles: dict[str, RepositoryContributionProfile] = {}
        self.contributors: dict[str, ContributorIdentity] = {}
        self.wallet_challenges: dict[str, ContributorWalletBindingChallenge] = {}
        self.wallet_bindings: dict[str, ContributorWalletBinding] = {}
        self.groups: dict[str, ContributionGroup] = {}
        self.merge_events: dict[str, ContributionMergeEvent] = {}
        self.attestations: dict[str, ContributionAttestation] = {}
        self.attestation_history: dict[str, list[ContributionAttestation]] = {}
        self.challenges: dict[str, ContributionChallenge] = {}
        self.challenge_resolutions: dict[str, ContributionChallengeResolution] = {}
        self.maturity_records: dict[str, ContributionMaturityRecord] = {}
        if self.path is not None and self.path.exists():
            self._restore()

    def _snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "repositories": self._dump(self.repositories),
            "profiles": self._dump(self.profiles),
            "contributors": self._dump(self.contributors),
            "wallet_challenges": self._dump(self.wallet_challenges),
            "wallet_bindings": self._dump(self.wallet_bindings),
            "groups": self._dump(self.groups),
            "merge_events": self._dump(self.merge_events),
            "attestations": self._dump(self.attestations),
            "attestation_history": {
                key: [item.model_dump(mode="json") for item in values]
                for key, values in self.attestation_history.items()
            },
            "challenges": self._dump(self.challenges),
            "challenge_resolutions": self._dump(self.challenge_resolutions),
            "maturity_records": self._dump(self.maturity_records),
        }

    @staticmethod
    def _dump(values: dict[str, BaseModel]) -> list[dict[str, Any]]:
        return [value.model_dump(mode="json") for value in values.values()]

    def _restore(self) -> None:
        assert self.path is not None
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.get("schema_version") != 1:
                raise ValueError("unsupported contribution evidence schema")
            self.repositories = self._index(raw.get("repositories", []), EligibleRepository, "repository_id")
            self.profiles = self._index(raw.get("profiles", []), RepositoryContributionProfile, "profile_id")
            self.contributors = self._index(raw.get("contributors", []), ContributorIdentity, "contributor_id")
            self.wallet_challenges = self._index(
                raw.get("wallet_challenges", []),
                ContributorWalletBindingChallenge,
                "challenge_id",
            )
            self.wallet_bindings = self._index(
                raw.get("wallet_bindings", []),
                ContributorWalletBinding,
                "binding_id",
            )
            self.groups = self._index(raw.get("groups", []), ContributionGroup, "contribution_group_id")
            self.merge_events = self._index(raw.get("merge_events", []), ContributionMergeEvent, "merge_event_id")
            self.attestations = self._index(raw.get("attestations", []), ContributionAttestation, "contribution_id")
            self.attestation_history = {
                key: [ContributionAttestation.model_validate(item) for item in values]
                for key, values in raw.get("attestation_history", {}).items()
            }
            self.challenges = self._index(raw.get("challenges", []), ContributionChallenge, "challenge_id")
            self.challenge_resolutions = self._index(
                raw.get("challenge_resolutions", []),
                ContributionChallengeResolution,
                "resolution_id",
            )
            self.maturity_records = self._index(
                raw.get("maturity_records", []),
                ContributionMaturityRecord,
                "maturity_id",
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            raise ValueError(f"Unable to restore contribution evidence: {error}") from error

    @staticmethod
    def _index(values: list[dict[str, Any]], model_type: type[T], key: str) -> dict[str, T]:
        result: dict[str, T] = {}
        for value in values:
            model = model_type.model_validate(value)
            result[str(getattr(model, key))] = model
        return result

    def flush(self) -> None:
        if self.path is None:
            return
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
            temporary_path.write_text(
                json.dumps(self._snapshot(), ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
            temporary_path.replace(self.path)

    def put(self, collection: dict[str, T], key: str, value: T) -> None:
        with self._lock:
            collection[key] = value
            self.flush()

    def remove(self, collection: dict[str, T], key: str) -> None:
        with self._lock:
            collection.pop(key, None)
            self.flush()

    def record_attestation(
        self,
        attestation: ContributionAttestation,
        *,
        previous: ContributionAttestation | None = None,
    ) -> None:
        with self._lock:
            if previous is not None:
                self.attestation_history.setdefault(attestation.contribution_id, []).append(previous)
            self.attestations[attestation.contribution_id] = attestation
            self.flush()

    def record_challenge_resolution(
        self,
        challenge: ContributionChallenge,
        resolution: ContributionChallengeResolution,
    ) -> None:
        with self._lock:
            self.challenges[challenge.challenge_id] = challenge
            self.challenge_resolutions[resolution.resolution_id] = resolution
            self.flush()

    def list_attestations(self) -> list[ContributionAttestation]:
        with self._lock:
            return list(self.attestations.values())

    def list_challenges(self, contribution_id: str | None = None) -> list[ContributionChallenge]:
        with self._lock:
            values = list(self.challenges.values())
        if contribution_id is None:
            return values
        return [item for item in values if item.contribution_id == contribution_id]

    def list_maturity(self, contribution_id: str | None = None) -> list[ContributionMaturityRecord]:
        with self._lock:
            values = list(self.maturity_records.values())
        if contribution_id is None:
            return values
        return [item for item in values if item.contribution_id == contribution_id]
