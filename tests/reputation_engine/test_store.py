"""Tests for ReputationStore (RFC-0041 Phase 1)."""

import pytest

from aidn_hypervisor.reputation_engine.models import (
    ReputationEvent,
    ReputationSubject,
)
from aidn_hypervisor.reputation_engine.store import ReputationStore


class TestReputationStore:
    def _store(self) -> ReputationStore:
        return ReputationStore()

    def test_create_profile(self):
        store = self._store()
        profile = store.create_profile("HYPERVISOR", "node-1", owner_reference="wallet-1")
        assert profile.subject.subject_id == "node-1"
        assert profile.profile_type == "HYPERVISOR"

    def test_get_profile(self):
        store = self._store()
        store.create_profile("HYPERVISOR", "node-1")
        profile = store.get_profile("HYPERVISOR", "node-1")
        assert profile is not None
        assert profile.subject.subject_id == "node-1"

    def test_get_missing_profile(self):
        store = self._store()
        assert store.get_profile("HYPERVISOR", "nonexistent") is None

    def test_list_profile_ids(self):
        store = self._store()
        store.create_profile("HYPERVISOR", "node-1")
        store.create_profile("ENDPOINT", "ep-1")
        ids = store.list_profile_ids("HYPERVISOR")
        assert "node-1" in ids

    def test_list_all_profiles(self):
        store = self._store()
        store.create_profile("HYPERVISOR", "node-1")
        store.create_profile("ENDPOINT", "ep-1")
        all_ids = store.list_all_profile_ids()
        assert len(all_ids) == 2

    def test_store_event(self):
        store = self._store()
        store.create_profile("HYPERVISOR", "node-1")
        evt = ReputationEvent(
            subject_type="HYPERVISOR",
            subject_id="node-1",
            profile_dimension="AVAILABILITY",
            event_class="AVAILABILITY_EVENT",
            direction="POSITIVE",
            severity="MINOR",
            evidence_confidence="OBSERVATIONAL",
            source_reference="sess-1",
        )
        stored = store.store_event(evt)
        assert stored.event_id == evt.event_id

    def test_get_events_for_profile(self):
        store = self._store()
        store.create_profile("HYPERVISOR", "node-1")
        evt = ReputationEvent(
            subject_type="HYPERVISOR",
            subject_id="node-1",
            profile_dimension="AVAILABILITY",
            event_class="AVAILABILITY_EVENT",
            direction="POSITIVE",
            severity="MINOR",
            evidence_confidence="OBSERVATIONAL",
        )
        store.store_event(evt)
        events = store.get_events("HYPERVISOR", "node-1")
        assert len(events) == 1

    def test_get_events_for_dimension(self):
        store = self._store()
        store.create_profile("HYPERVISOR", "node-1")
        evt1 = ReputationEvent(
            subject_type="HYPERVISOR",
            subject_id="node-1",
            profile_dimension="AVAILABILITY",
            event_class="AVAILABILITY_EVENT",
            direction="POSITIVE",
            severity="MINOR",
            evidence_confidence="OBSERVATIONAL",
        )
        evt2 = ReputationEvent(
            subject_type="HYPERVISOR",
            subject_id="node-1",
            profile_dimension="RELIABILITY",
            event_class="EXECUTION_EVENT",
            direction="NEGATIVE",
            severity="MODERATE",
            evidence_confidence="CRYPTOGRAPHIC",
        )
        store.store_event(evt1)
        store.store_event(evt2)
        avail_events = store.get_events("HYPERVISOR", "node-1", dimension="AVAILABILITY")
        assert len(avail_events) == 1

    def test_delete_profile(self):
        store = self._store()
        store.create_profile("HYPERVISOR", "node-1")
        store.delete_profile("HYPERVISOR", "node-1")
        assert store.get_profile("HYPERVISOR", "node-1") is None

    def test_reset(self):
        store = self._store()
        store.create_profile("HYPERVISOR", "node-1")
        store.create_profile("ENDPOINT", "ep-1")
        store.reset()
        assert len(store.list_all_profile_ids()) == 0

    def test_profile_not_found_for_events(self):
        store = self._store()
        evt = ReputationEvent(
            subject_type="HYPERVISOR",
            subject_id="unknown",
            profile_dimension="AVAILABILITY",
            event_class="AVAILABILITY_EVENT",
            direction="POSITIVE",
            severity="MINOR",
            evidence_confidence="OBSERVATIONAL",
        )
        # Should not crash
        store.store_event(evt)
