"""Reputation Engine — scoring, state derivation, event ingestion (RFC-0041 Phase 1).

The engine:
1. Ensures a ReputationProfile exists for each (profile_type, subject_id)
2. Ingests finalized ReputationEvents into profile accumulators
3. Derives per-dimension scores with Bayesian prior + confidence weighting
4. Derives advisory overall score with critical dimension cap
5. Derives profile state from dimension states + confidence
"""

from __future__ import annotations

from aidn_hypervisor.reputation_engine.models import (
    ReputationEvent,
    ReputationProfile,
    ReputationProfileType,
)
from aidn_hypervisor.reputation_engine.store import ReputationStore


class ReputationEngine:
    """Central engine for reputation scoring.

    Wraps a ReputationStore and provides:
    - Profile lifecycle (create, get, ensure)
    - Event ingestion with automatic profile creation
    - Score derivation (per-dimension + advisory overall)
    - State derivation (INSUFFICIENT_DATA → NORMAL → DEGRADED → CRITICAL)
    """

    def __init__(self, store: ReputationStore) -> None:
        self.store = store

    # ── Profile Lifecycle ────────────────────

    def get_or_create_profile(
        self,
        profile_type: ReputationProfileType,
        subject_id: str,
        *,
        owner_reference: str | None = None,
    ) -> ReputationProfile:
        """Get existing profile or create one."""
        return self.store.ensure_profile(
            profile_type,
            subject_id,
            owner_reference=owner_reference,
        )

    def get_profile(
        self, profile_type: str, subject_id: str
    ) -> ReputationProfile | None:
        """Get profile by type and ID."""
        return self.store.get_profile(profile_type, subject_id)

    def list_profiles(self, profile_type: str | None = None) -> list[tuple[str, str]]:
        """List all profile keys, optionally filtered by type."""
        if profile_type:
            return self.store.list_profile_ids(profile_type)
        return self.store.list_all_profile_ids()

    # ── Event Ingestion ─────────────────────

    def ingest_event(self, event: ReputationEvent) -> ReputationProfile:
        """Ingest a finalized ReputationEvent.

        1. Ensure profile exists
        2. Add event mass to appropriate dimension accumulator
        3. Store event in log
        4. Return updated profile
        """
        # Ensure profile exists
        profile = self.store.ensure_profile(
            event.subject_type,
            event.subject_id,
        )

        # Add event to profile accumulators
        profile.add_event(event)

        # Store event in log
        self.store.store_event(event)

        # Mark profile as dirty for registry publication
        self.store.mark_dirty(event.subject_type, event.subject_id)

        return profile

    def ingest_events(self, events: list[ReputationEvent]) -> dict[str, ReputationProfile]:
        """Ingest multiple events. Returns updated profiles."""
        profiles: dict[str, ReputationProfile] = {}
        for event in events:
            profile = self.ingest_event(event)
            key = f"{event.subject_type}:{event.subject_id}"
            profiles[key] = profile
        return profiles

    # ── Score Queries ───────────────────────

    def get_dimension_score(
        self,
        profile_type: str,
        subject_id: str,
        dimension: str,
    ) -> dict | None:
        """Get current score for one dimension."""
        profile = self.store.get_profile(profile_type, subject_id)
        if profile is None:
            return None

        acc = profile.accumulators.get(dimension)
        if acc is None:
            return None

        score = acc.to_score()
        return {
            "dimension": score.dimension,
            "effective_score": score.effective_score,
            "raw_score": score.raw_score,
            "confidence": score.confidence,
            "positive_mass": score.positive_mass,
            "negative_mass": score.negative_mass,
            "event_count": score.event_count,
            "state": score.state,
        }

    def get_profile_summary(
        self, profile_type: str, subject_id: str
    ) -> dict | None:
        """Get a summary of the profile including overall score, tier, and state."""
        profile = self.store.get_profile(profile_type, subject_id)
        if profile is None:
            return None

        dimension_scores = []
        for acc in profile.accumulators.values():
            score = acc.to_score()
            dimension_scores.append({
                "dimension": score.dimension,
                "effective_score": score.effective_score,
                "confidence": score.confidence,
                "state": score.state,
                "event_count": score.event_count,
            })

        return {
            "subject_type": profile.subject.subject_type,
            "subject_id": profile.subject.subject_id,
            "profile_type": profile.profile_type,
            "state": profile.state,
            "tier": profile.tier,
            "advisory_overall_score": profile.advisory_overall_score,
            "dimensions": dimension_scores,
            "created_at": profile.created_at,
            "last_updated_at": profile.last_updated_at,
            "profile_version": profile.profile_version,
        }

    def get_event_history(
        self,
        profile_type: str,
        subject_id: str,
        *,
        dimension: str | None = None,
        limit: int = 50,
    ) -> list[ReputationEvent]:
        """Get event history for a profile."""
        return self.store.get_events(profile_type, subject_id, dimension=dimension, limit=limit)
