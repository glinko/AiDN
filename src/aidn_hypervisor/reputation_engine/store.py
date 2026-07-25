"""Reputation Store — in-memory persistence for profiles and events."""

from __future__ import annotations

from aidn_hypervisor.reputation_engine.models import (
    ReputationEvent,
    ReputationProfile,
    ReputationProfileType,
    ReputationSubject,
)


class ReputationStore:
    """In-memory store for Reputation Profiles and Events.

    Maps (profile_type, subject_id) → ReputationProfile
    and maintains an event log per profile.
    """

    def __init__(self) -> None:
        # (profile_type, subject_id) → ReputationProfile
        self._profiles: dict[tuple[str, str], ReputationProfile] = {}
        # (profile_type, subject_id) → list[ReputationEvent]
        self._events: dict[tuple[str, str], list[ReputationEvent]] = {}

    def _key(self, profile_type: str, subject_id: str) -> tuple[str, str]:
        return (profile_type, subject_id)

    # ── Profile CRUD ─────────────────────────

    def create_profile(
        self,
        profile_type: ReputationProfileType,
        subject_id: str,
        *,
        owner_reference: str | None = None,
        hypervisor_reference: str | None = None,
    ) -> ReputationProfile:
        key = self._key(profile_type, subject_id)
        if key in self._profiles:
            return self._profiles[key]

        subject = ReputationSubject(
            subject_type=profile_type,
            subject_id=subject_id,
            owner_reference=owner_reference,
            hypervisor_reference=hypervisor_reference,
        )
        profile = ReputationProfile(
            subject=subject,
            profile_type=profile_type,
        )
        self._profiles[key] = profile
        self._events[key] = []
        return profile

    def get_profile(
        self, profile_type: str, subject_id: str
    ) -> ReputationProfile | None:
        key = self._key(profile_type, subject_id)
        return self._profiles.get(key)

    def ensure_profile(
        self,
        profile_type: ReputationProfileType,
        subject_id: str,
        *,
        owner_reference: str | None = None,
    ) -> ReputationProfile:
        """Get or create a profile."""
        profile = self.get_profile(profile_type, subject_id)
        if profile is not None:
            return profile
        return self.create_profile(
            profile_type,
            subject_id,
            owner_reference=owner_reference,
        )

    def delete_profile(self, profile_type: str, subject_id: str) -> bool:
        key = self._key(profile_type, subject_id)
        if key in self._profiles:
            del self._profiles[key]
            self._events.pop(key, None)
            return True
        return False

    def list_profile_ids(self, profile_type: str) -> list[str]:
        return [
            sid for (pt, sid) in self._profiles if pt == profile_type
        ]

    def list_all_profile_ids(self) -> list[tuple[str, str]]:
        return list(self._profiles.keys())

    # ── Event CRUD ──────────────────────────

    def store_event(self, event: ReputationEvent) -> ReputationEvent:
        key = self._key(event.subject_type, event.subject_id)

        # Auto-create profile if missing
        if key not in self._profiles:
            self.create_profile(event.subject_type, event.subject_id)

        if key not in self._events:
            self._events[key] = []

        self._events[key].append(event)
        return event

    def get_events(
        self,
        profile_type: str,
        subject_id: str,
        *,
        dimension: str | None = None,
        limit: int = 100,
    ) -> list[ReputationEvent]:
        key = self._key(profile_type, subject_id)
        events = self._events.get(key, [])

        if dimension:
            events = [e for e in events if e.profile_dimension == dimension]

        # Most recent first
        return list(reversed(events))[:limit]

    def event_count(self, profile_type: str, subject_id: str) -> int:
        key = self._key(profile_type, subject_id)
        return len(self._events.get(key, []))

    # ── Maintenance ────────────────────────

    def reset(self) -> None:
        self._profiles.clear()
        self._events.clear()
