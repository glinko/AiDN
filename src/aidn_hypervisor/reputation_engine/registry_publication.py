"""M5 Phase 4: Registry Publication.

Publishes computed ReputationProfiles to the Registry service,
making them discoverable and queryable by other nodes.

Responsibilities:
- Serialize ReputationProfile → registry-compatible record
- Sign records with optional signer key
- Handle versioning (increment on update)
- Skip publication if payload unchanged
- Support batch publication from ReputationStore
- Query published profiles by subject or type
- Subscribe to profile change notifications
- Retire profiles (mark as no longer publishable)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from aidn_hypervisor.reputation_engine.models import (
    ReputationProfile,
    ReputationProfileType,
)
from aidn_hypervisor.reputation_engine.store import ReputationStore


# ──────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────

REGISTRY_OBJECT_TYPE = "reputation_profile"
REGISTRY_NAMESPACE = "reputation"
REGISTRY_PAYLOAD_ENCODING = "json"
REGISTRY_PROFILE_VERSION = "reputation-registry.v1"


# ──────────────────────────────────────────────
# Publisher
# ──────────────────────────────────────────────


class ReputationProfilePublisher:
    """Publishes ReputationProfiles to the Registry.

    Args:
        registry: RegistryService instance (or mock for testing).
        store: ReputationStore to read profiles from.
        signer_key: Optional key identifier for signing records.
    """

    def __init__(
        self,
        *,
        registry: Any | None = None,
        store: ReputationStore | None = None,
        signer_key: str | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        self.signer_key = signer_key
        self._subscribers: dict[str, list[Callable]] = {}
        self._retired_subjects: set[str] = set()

    # ── Serialization ───────────────────────

    def _serialize_profile(
        self, profile: ReputationProfile
    ) -> dict[str, Any]:
        """Convert a ReputationProfile into a registry-compatible record."""
        subject_id = profile.subject.subject_id
        profile_type = profile.profile_type

        # Build payload
        payload = self._build_payload(profile)

        # Compute payload hash
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()

        # Deterministic object ID from subject + type
        object_id = self._compute_object_id(profile_type, subject_id)

        # Resolve version
        version = self._resolve_version(object_id)

        record: dict[str, Any] = {
            "object_id": object_id,
            "object_type": REGISTRY_OBJECT_TYPE,
            "object_version": version,
            "namespace": REGISTRY_NAMESPACE,
            "payload_hash": payload_hash,
            "payload_encoding": REGISTRY_PAYLOAD_ENCODING,
            "source_reference": f"reputation-engine:{profile_type}:{subject_id}",
            "payload": payload,
        }

        return record

    def _build_payload(self, profile: ReputationProfile) -> dict[str, Any]:
        """Build the payload dict from a ReputationProfile."""
        dimension_scores = []
        for score in profile.dimension_scores:
            dimension_scores.append({
                "dimension": score.dimension,
                "score": round(score.effective_score, 6),
                "confidence": round(score.confidence, 6),
                "positive_mass": round(score.positive_mass, 4),
                "negative_mass": round(score.negative_mass, 4),
                "event_count": score.event_count,
                "state": score.state,
            })

        return {
            "subject_wallet": profile.subject.subject_id,
            "profile_type": profile.profile_type,
            "dimension_scores": dimension_scores,
            "advisory_overall_score": round(profile.advisory_overall_score, 6),
            "profile_state": profile.state,
            "profile_version": REGISTRY_PROFILE_VERSION,
            "created_at": profile.created_at,
            "last_updated_at": profile.last_updated_at,
            "retired": profile.subject.subject_id in self._retired_subjects,
        }

    def _compute_object_id(self, profile_type: str, subject_id: str) -> str:
        """Generate a deterministic object ID."""
        raw = f"{REGISTRY_OBJECT_TYPE}:{profile_type}:{subject_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _resolve_version(self, object_id: str) -> int:
        """Resolve the next version number for an object."""
        if self.registry is None:
            return 1

        try:
            existing = self.registry.get_registry_object(object_id)
        except Exception:
            return 1

        if existing is None:
            return 1

        return existing.get("object_version", 0) + 1

    # ── Signing ─────────────────────────────

    def _sign_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Add signature metadata to a record."""
        now = datetime.now(timezone.utc).isoformat()

        if self.signer_key:
            record["signature"] = {
                "algorithm": "ed25519",
                "signer": self.signer_key,
                "signed_at": now,
                "payload_hash": record.get("payload_hash"),
            }
        else:
            record["signature"] = {
                "algorithm": None,
                "signer": None,
                "signed_at": now,
                "payload_hash": record.get("payload_hash"),
            }

        return record

    # ── Publication ─────────────────────────

    def publish(self, profile: ReputationProfile) -> dict | None:
        """Publish a single profile to the registry.

        Returns the published record, or None if skipped (no changes).
        """
        if self.registry is None:
            return None

        subject_id = profile.subject.subject_id

        # Skip retired profiles
        if subject_id in self._retired_subjects:
            return None

        record = self._serialize_profile(profile)
        record = self._sign_record(record)

        # Check if payload has changed
        try:
            existing = self.registry.get_registry_object(record["object_id"])
        except Exception:
            existing = None

        if existing is not None:
            existing_hash = existing.get("payload_hash")
            if existing_hash == record["payload_hash"]:
                # No changes — skip publication
                return None

        # Upsert to registry
        result = self.registry.upsert_registry_object(record)

        # Clear dirty flag if store is available
        if self.store is not None:
            self.store.clear_dirty(profile.profile_type, subject_id)

        # Notify subscribers
        self._notify_subscribers(subject_id, "profile_published", record)

        return result

    def publish_batch(
        self, profiles: list[ReputationProfile]
    ) -> list[dict | None]:
        """Publish multiple profiles. Returns list of results."""
        results: list[dict | None] = []
        for profile in profiles:
            result = self.publish(profile)
            results.append(result)
        return results

    # ── Store-backed publication ────────────

    def publish_all(self) -> list[dict | None]:
        """Publish all profiles from the store (excluding retired)."""
        if self.store is None:
            return []

        results: list[dict | None] = []
        all_ids = self.store.list_all_profile_ids()

        for profile_type, subject_id in all_ids:
            # Skip retired
            if self.store.is_retired(profile_type, subject_id):
                continue

            profile = self.store.get_profile(profile_type, subject_id)
            if profile is not None:
                result = self.publish(profile)
                results.append(result)

        return results

    def publish_dirty(self) -> list[dict | None]:
        """Publish only profiles marked as dirty (excluding retired)."""
        if self.store is None:
            return []

        results: list[dict | None] = []
        dirty_ids = self.store.get_dirty_profiles()

        for profile_type, subject_id in dirty_ids:
            # Skip retired
            if self.store.is_retired(profile_type, subject_id):
                self.store.clear_dirty(profile_type, subject_id)
                continue

            profile = self.store.get_profile(profile_type, subject_id)
            if profile is not None:
                result = self.publish(profile)
                results.append(result)

        return results

    # ── Query ───────────────────────────────

    def query_profile(self, subject_id: str) -> list[dict]:
        """Query the registry for a profile by subject ID."""
        if self.registry is None:
            return []

        all_objects = self.registry.list_registry_objects(
            object_type=REGISTRY_OBJECT_TYPE,
            namespace=REGISTRY_NAMESPACE,
        )

        results = []
        for obj in all_objects:
            payload = obj.get("payload", {})
            if payload.get("subject_wallet") == subject_id:
                results.append(obj)

        return results

    def query_profiles_by_type(
        self, profile_type: ReputationProfileType
    ) -> list[dict]:
        """Query the registry for profiles of a given type."""
        if self.registry is None:
            return []

        all_objects = self.registry.list_registry_objects(
            object_type=REGISTRY_OBJECT_TYPE,
            namespace=REGISTRY_NAMESPACE,
        )

        results = []
        for obj in all_objects:
            payload = obj.get("payload", {})
            if payload.get("profile_type") == profile_type:
                results.append(obj)

        return results

    # ── Subscriptions ──────────────────────

    def subscribe(
        self, subject_id: str, callback: Callable[[dict], None]
    ) -> None:
        """Register a callback for profile changes."""
        if subject_id not in self._subscribers:
            self._subscribers[subject_id] = []
        self._subscribers[subject_id].append(callback)

    def unsubscribe(self, subject_id: str) -> None:
        """Remove all callbacks for a subject."""
        self._subscribers.pop(subject_id, None)

    def _notify_subscribers(
        self,
        subject_id: str,
        event: str,
        record: dict | None = None,
    ) -> None:
        """Notify all subscribers for a subject."""
        callbacks = self._subscribers.get(subject_id, [])
        for cb in callbacks:
            try:
                cb({
                    "subject_wallet": subject_id,
                    "event": event,
                    "record": record,
                })
            except Exception:
                pass  # Don't let subscriber errors break publication

    # ── Retirement ─────────────────────────

    def retire_profile(self, subject_id: str) -> None:
        """Mark a profile as retired (no longer publishable).

        Publishes a final record with retired=True.
        """
        self._retired_subjects.add(subject_id)

        # Also mark in store if available
        if self.store is not None:
            all_ids = self.store.list_all_profile_ids()
            for profile_type, sid in all_ids:
                if sid == subject_id:
                    self.store.mark_retired(profile_type, subject_id)

        # Publish final retired record if registry available
        if self.registry is not None and self.store is not None:
            all_ids = self.store.list_all_profile_ids()
            for profile_type, sid in all_ids:
                if sid == subject_id:
                    profile = self.store.get_profile(profile_type, sid)
                    if profile is not None:
                        record = self._serialize_profile(profile)
                        record["payload"]["retired"] = True
                        # Update hash to reflect retired status
                        record["payload_hash"] = hashlib.sha256(
                            json.dumps(
                                record["payload"],
                                sort_keys=True,
                                default=str,
                            ).encode()
                        ).hexdigest()
                        record = self._sign_record(record)
                        self.registry.upsert_registry_object(record)
