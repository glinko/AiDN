"""M5 Phase 4: Registry Publication — TDD tests.

Tests the mechanism for publishing ReputationProfiles to the Registry,
including serialization, signing, versioning, and query integration.
"""

import hashlib
import json
from unittest.mock import MagicMock

import pytest

from aidn_hypervisor.reputation_engine.models import (
    ReputationProfile,
    ReputationSubject,
)
from aidn_hypervisor.reputation_engine.store import ReputationStore

# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def mock_registry():
    """Mock RegistryService for testing."""
    return MagicMock()


@pytest.fixture
def sample_subject():
    return ReputationSubject(
        subject_type="HYPERVISOR",
        subject_id="0xTestSubject",
    )


@pytest.fixture
def sample_profile(sample_subject):
    return ReputationProfile(
        subject=sample_subject,
        profile_type="HYPERVISOR",
    )


# ──────────────────────────────────────────────
# Test: Profile Serialization
# ──────────────────────────────────────────────

class TestProfileSerialization:
    """Test serializing ReputationProfile → registry-compatible dict."""

    def test_serialize_produces_required_fields(self, sample_profile):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=None)
        record = publisher._serialize_profile(sample_profile)

        assert "object_id" in record
        assert "object_type" in record
        assert "object_version" in record
        assert "namespace" in record
        assert "payload_hash" in record
        assert "payload_encoding" in record
        assert "source_reference" in record

    def test_serialize_sets_correct_object_type(self, sample_profile):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=None)
        record = publisher._serialize_profile(sample_profile)

        assert record["object_type"] == "reputation_profile"

    def test_serialize_sets_correct_namespace(self, sample_profile):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=None)
        record = publisher._serialize_profile(sample_profile)

        assert record["namespace"] == "reputation"

    def test_serialize_includes_profile_payload(self, sample_profile):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=None)
        record = publisher._serialize_profile(sample_profile)

        assert "payload" in record
        payload = record["payload"]
        assert payload["subject_wallet"] == "0xTestSubject"
        assert payload["profile_type"] == "HYPERVISOR"

    def test_serialize_includes_dimension_scores(self, sample_profile):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=None)
        record = publisher._serialize_profile(sample_profile)

        payload = record["payload"]
        assert "dimension_scores" in payload
        assert isinstance(payload["dimension_scores"], list)

    def test_serialize_includes_advisory_score(self, sample_profile):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=None)
        record = publisher._serialize_profile(sample_profile)

        payload = record["payload"]
        assert "advisory_overall_score" in payload
        assert isinstance(payload["advisory_overall_score"], float)

    def test_serialize_includes_profile_state(self, sample_profile):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=None)
        record = publisher._serialize_profile(sample_profile)

        payload = record["payload"]
        assert "profile_state" in payload

    def test_serialize_generates_deterministic_object_id(self, sample_profile):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=None)
        record1 = publisher._serialize_profile(sample_profile)
        record2 = publisher._serialize_profile(sample_profile)

        assert record1["object_id"] == record2["object_id"]

    def test_serialize_different_subjects_different_ids(self):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        sub1 = ReputationSubject(subject_type="HYPERVISOR", subject_id="0xSubjectA")
        sub2 = ReputationSubject(subject_type="HYPERVISOR", subject_id="0xSubjectB")
        prof1 = ReputationProfile(subject=sub1, profile_type="HYPERVISOR")
        prof2 = ReputationProfile(subject=sub2, profile_type="HYPERVISOR")

        publisher = ReputationProfilePublisher(registry=None)
        rec1 = publisher._serialize_profile(prof1)
        rec2 = publisher._serialize_profile(prof2)

        assert rec1["object_id"] != rec2["object_id"]

    def test_serialize_sets_version(self, sample_profile):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=None)
        record = publisher._serialize_profile(sample_profile)

        assert record["object_version"] == 1

    def test_serialize_payload_hash_matches_content(self, sample_profile):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=None)
        record = publisher._serialize_profile(sample_profile)

        expected_hash = hashlib.sha256(
            json.dumps(record["payload"], sort_keys=True, default=str).encode()
        ).hexdigest()
        assert record["payload_hash"] == expected_hash

    def test_serialize_payload_encoding_is_json(self, sample_profile):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=None)
        record = publisher._serialize_profile(sample_profile)

        assert record["payload_encoding"] == "json"


# ──────────────────────────────────────────────
# Test: Profile Signing
# ──────────────────────────────────────────────

class TestProfileSigning:
    """Test cryptographic signing of published profiles."""

    def test_sign_adds_signature_field(self, sample_profile, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(
            registry=mock_registry,
            signer_key="test-signing-key-001",
        )
        record = publisher._serialize_profile(sample_profile)
        signed = publisher._sign_record(record)

        assert "signature" in signed
        assert signed["signature"]["algorithm"] == "ed25519"
        assert signed["signature"]["signer"] == "test-signing-key-001"

    def test_sign_includes_timestamp(self, sample_profile, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(
            registry=mock_registry,
            signer_key="test-signing-key-001",
        )
        record = publisher._serialize_profile(sample_profile)
        signed = publisher._sign_record(record)

        assert "signed_at" in signed["signature"]

    def test_sign_without_key_uses_none(self, sample_profile, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=mock_registry)
        record = publisher._serialize_profile(sample_profile)
        signed = publisher._sign_record(record)

        assert "signature" in signed
        assert signed["signature"]["algorithm"] is None
        assert signed["signature"]["signer"] is None


# ──────────────────────────────────────────────
# Test: Publication Lifecycle
# ──────────────────────────────────────────────

class TestPublicationLifecycle:
    """Test the full publish → query → update cycle."""

    def test_publish_upserts_to_registry(self, sample_profile, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        mock_registry.get_registry_object.return_value = None

        publisher = ReputationProfilePublisher(registry=mock_registry)
        publisher.publish(sample_profile)

        mock_registry.upsert_registry_object.assert_called_once()
        published_record = mock_registry.upsert_registry_object.call_args[0][0]
        assert published_record["object_type"] == "reputation_profile"

    def test_publish_returns_record(self, sample_profile, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        mock_registry.get_registry_object.return_value = None
        mock_registry.upsert_registry_object.return_value = {"object_id": "rep-001"}

        publisher = ReputationProfilePublisher(registry=mock_registry)
        result = publisher.publish(sample_profile)

        assert result is not None
        assert "object_id" in result

    def test_publish_increments_version_on_update(self, sample_profile, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        mock_registry.get_registry_object.return_value = {
            "object_id": "rep-001",
            "object_version": 3,
        }

        publisher = ReputationProfilePublisher(registry=mock_registry)
        publisher.publish(sample_profile)

        published = mock_registry.upsert_registry_object.call_args[0][0]
        assert published["object_version"] == 4

    def test_publish_uses_version_1_for_new(self, sample_profile, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        mock_registry.get_registry_object.return_value = None

        publisher = ReputationProfilePublisher(registry=mock_registry)
        publisher.publish(sample_profile)

        published = mock_registry.upsert_registry_object.call_args[0][0]
        assert published["object_version"] == 1

    def test_publish_skips_if_no_changes(self, sample_profile, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        # First, serialize the profile to get the actual payload + hash
        publisher = ReputationProfilePublisher(registry=mock_registry)
        record = publisher._serialize_profile(sample_profile)

        # Mock the registry to return the same payload hash
        mock_registry.get_registry_object.return_value = {
            "object_id": record["object_id"],
            "object_version": 5,
            "payload_hash": record["payload_hash"],
            "payload": record["payload"],
        }

        result = publisher.publish(sample_profile)

        # Should skip because payload is identical
        assert result is None

    def test_publish_batch(self, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        subjects = [
            ReputationSubject(subject_type="HYPERVISOR", subject_id=f"0xSub{i}")
            for i in range(3)
        ]
        profiles = [
            ReputationProfile(subject=s, profile_type="HYPERVISOR")
            for s in subjects
        ]

        mock_registry.get_registry_object.return_value = None

        publisher = ReputationProfilePublisher(registry=mock_registry)
        results = publisher.publish_batch(profiles)

        assert len(results) == 3
        assert mock_registry.upsert_registry_object.call_count == 3


# ──────────────────────────────────────────────
# Test: Query Integration
# ──────────────────────────────────────────────

class TestQueryIntegration:
    """Test querying published profiles from the registry."""

    def test_query_by_wallet(self, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        mock_registry.list_registry_objects.return_value = [
            {
                "object_id": "rep-001",
                "object_type": "reputation_profile",
                "payload": {"subject_wallet": "0xTarget"},
            }
        ]

        publisher = ReputationProfilePublisher(registry=mock_registry)
        results = publisher.query_profile("0xTarget")

        mock_registry.list_registry_objects.assert_called_once()
        assert len(results) == 1
        assert results[0]["payload"]["subject_wallet"] == "0xTarget"

    def test_query_returns_empty_when_not_found(self, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        mock_registry.list_registry_objects.return_value = []

        publisher = ReputationProfilePublisher(registry=mock_registry)
        results = publisher.query_profile("0xNonExistent")

        assert len(results) == 0

    def test_query_filters_by_profile_type(self, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        mock_registry.list_registry_objects.return_value = [
            {"payload": {"profile_type": "HYPERVISOR"}},
            {"payload": {"profile_type": "VALIDATION_SERVICE"}},
        ]

        publisher = ReputationProfilePublisher(registry=mock_registry)
        results = publisher.query_profiles_by_type("HYPERVISOR")

        assert len(results) == 1
        assert results[0]["payload"]["profile_type"] == "HYPERVISOR"


# ──────────────────────────────────────────────
# Test: Subscription / Change Detection
# ──────────────────────────────────────────────

class TestSubscription:
    """Test subscription to profile changes."""

    def test_subscribe_registers_callback(self, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=mock_registry)
        callback = MagicMock()

        publisher.subscribe("0xTestSubject", callback)

        assert "0xTestSubject" in publisher._subscribers

    def test_publish_notifies_subscribers(self, sample_profile, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        mock_registry.get_registry_object.return_value = None

        publisher = ReputationProfilePublisher(registry=mock_registry)
        callback = MagicMock()

        publisher.subscribe("0xTestSubject", callback)
        publisher.publish(sample_profile)

        callback.assert_called_once()
        call_args = callback.call_args[0][0]
        assert call_args["subject_wallet"] == "0xTestSubject"
        assert call_args["event"] == "profile_published"

    def test_unsubscribe_removes_callback(self, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        publisher = ReputationProfilePublisher(registry=mock_registry)
        callback = MagicMock()

        publisher.subscribe("0xTestSubject", callback)
        publisher.unsubscribe("0xTestSubject")

        assert "0xTestSubject" not in publisher._subscribers


# ──────────────────────────────────────────────
# Test: Integration with ReputationStore
# ──────────────────────────────────────────────

class TestStoreIntegration:
    """Test publishing profiles managed by ReputationStore."""

    def test_publish_all_profiles_from_store(self, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        store = ReputationStore()
        store.create_profile(profile_type="HYPERVISOR", subject_id="0xSubA")
        store.create_profile(profile_type="HYPERVISOR", subject_id="0xSubB")

        mock_registry.get_registry_object.return_value = None

        publisher = ReputationProfilePublisher(
            registry=mock_registry,
            store=store,
        )
        results = publisher.publish_all()

        assert len(results) == 2
        assert mock_registry.upsert_registry_object.call_count == 2

    def test_publish_only_dirty_profiles(self, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        store = ReputationStore()
        store.create_profile(profile_type="HYPERVISOR", subject_id="0xSubA")
        store.create_profile(profile_type="HYPERVISOR", subject_id="0xSubB")

        mock_registry.get_registry_object.return_value = None

        publisher = ReputationProfilePublisher(
            registry=mock_registry,
            store=store,
        )

        # Mark only one as dirty via the engine
        from aidn_hypervisor.reputation_engine.engine import ReputationEngine
        engine = ReputationEngine(store=store)

        # Ingest an event for SubA only → marks it dirty
        from aidn_hypervisor.reputation_engine.models import (
            ReputationEvent,
        )

        event = ReputationEvent(
            subject_type="HYPERVISOR",
            subject_id="0xSubA",
            event_class="SESSION_SUCCESS",
            profile_dimension="RELIABILITY",
            direction="POSITIVE",
            severity="MINOR",
            evidence_confidence="DIRECT",
        )
        engine.ingest_event(event)

        results = publisher.publish_dirty()

        assert len(results) == 1
        assert mock_registry.upsert_registry_object.call_count == 1


# ──────────────────────────────────────────────
# Test: Retention & Cleanup
# ──────────────────────────────────────────────

class TestRetention:
    """Test profile retention and retirement in registry."""

    def test_retire_profile_removes_from_registry(self, sample_profile, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        store = ReputationStore()
        store.create_profile(profile_type="HYPERVISOR", subject_id="0xTestSubject")

        publisher = ReputationProfilePublisher(
            registry=mock_registry,
            store=store,
        )

        publisher.retire_profile("0xTestSubject")

        # Should have published a final record with retired=True
        assert mock_registry.upsert_registry_object.call_count >= 1
        last_record = mock_registry.upsert_registry_object.call_args[0][0]
        assert last_record["payload"].get("retired") is True

    def test_retired_profiles_skip_publish(self, mock_registry):
        from aidn_hypervisor.reputation_engine.registry_publication import (
            ReputationProfilePublisher,
        )

        store = ReputationStore()
        ReputationSubject(subject_type="HYPERVISOR", subject_id="0xTestSubject")
        store.create_profile(profile_type="HYPERVISOR", subject_id="0xTestSubject")

        publisher = ReputationProfilePublisher(
            registry=mock_registry,
            store=store,
        )

        # Retire first
        publisher.retire_profile("0xTestSubject")

        # Try to publish all — retired profile should be skipped
        results = publisher.publish_all()
        assert len(results) == 0
