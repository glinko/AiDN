"""Tests for registry bridge — legacy RecordService ↔ new registry/ adapter."""

import pytest
from unittest.mock import MagicMock, PropertyMock

from aidn_hypervisor.registry.bridge import (
    legacy_record_to_envelope,
    envelope_to_legacy_record,
    RegistryServiceAdapter,
    _compute_content_hash,
    _compute_content_size,
    _resolve_object_version,
    _resolve_ledger_commitment,
)
from aidn_hypervisor.registry.object_envelope import (
    RegistryObjectEnvelope,
    ObjectVersion,
    LedgerCommitmentClass,
)
from aidn_hypervisor.registry.storage import ImmutableObjectStore


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_legacy_record(
    object_id: str = "test:obj:001",
    object_type: str = "reputation_profile",
    payload: dict | None = None,
    namespace: str = "default",
    payload_hash: str | None = None,
    object_version: str = "1.0",
    source_reference: str | None = None,
    created_epoch: int | None = None,
) -> dict:
    if payload is None:
        payload = {"key": "value", "score": 0.5}
    if payload_hash is None:
        payload_hash = _compute_content_hash(payload)
    record = {
        "object_id": object_id,
        "object_type": object_type,
        "object_version": object_version,
        "namespace": namespace,
        "payload_hash": payload_hash,
        "payload_encoding": "json",
        "source_reference": source_reference,
        "payload": payload,
    }
    if created_epoch is not None:
        record["created_epoch"] = created_epoch
    return record


def _make_envelope(
    object_id: str = "test:obj:001",
    object_type: str = "reputation_profile",
    payload: dict | None = None,
    content_hash: str | None = None,
    created_epoch: int | None = None,
    parent_references: list[str] | None = None,
) -> RegistryObjectEnvelope:
    if payload is None:
        payload = {"key": "value", "score": 0.5}
    if content_hash is None:
        content_hash = _compute_content_hash(payload)
    return RegistryObjectEnvelope(
        object_id=object_id,
        object_type=object_type,
        content_hash=content_hash,
        content_size=_compute_content_size(payload),
        created_epoch=created_epoch,
        parent_references=parent_references or [],
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Conversion functions
# ---------------------------------------------------------------------------

class TestComputeContentHash:
    def test_deterministic_hash(self):
        payload = {"b": 2, "a": 1}
        h1 = _compute_content_hash(payload)
        h2 = _compute_content_hash({"a": 1, "b": 2})
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_empty_payload(self):
        h = _compute_content_hash({})
        assert len(h) == 64

    def test_nested_payload(self):
        payload = {"nested": {"deep": [1, 2, 3]}}
        h = _compute_content_hash(payload)
        assert len(h) == 64


class TestComputeContentSize:
    def test_basic_size(self):
        size = _compute_content_size({"key": "value"})
        assert size > 0

    def test_empty_size(self):
        size = _compute_content_size({})
        assert size > 0  # "{}" is 2 bytes


class TestResolveObjectVersion:
    def test_string_v1(self):
        assert _resolve_object_version("1.0") == ObjectVersion.V1

    def test_enum_passthrough(self):
        assert _resolve_object_version(ObjectVersion.V1) == ObjectVersion.V1

    def test_unknown_string_defaults_v1(self):
        assert _resolve_object_version("99.0") == ObjectVersion.V1


class TestResolveLedgerCommitment:
    def test_reputation_profile(self):
        assert (
            _resolve_ledger_commitment("reputation_profile")
            == LedgerCommitmentClass.REPUTATION_PROFILE
        )

    def test_validation_report(self):
        assert (
            _resolve_ledger_commitment("validation_report")
            == LedgerCommitmentClass.VALIDATION_REPORT
        )

    def test_unknown_type(self):
        assert _resolve_ledger_commitment("unknown_type") is None

    def test_onboarding_capability(self):
        assert (
            _resolve_ledger_commitment("onboarding_capability")
            == LedgerCommitmentClass.ADVERTISEMENT
        )


# ---------------------------------------------------------------------------
# legacy_record_to_envelope
# ---------------------------------------------------------------------------

class TestLegacyRecordToEnvelope:
    def test_basic_conversion(self):
        record = _make_legacy_record()
        envelope = legacy_record_to_envelope(record)
        assert envelope.object_id == "test:obj:001"
        assert envelope.object_type == "reputation_profile"
        assert envelope.object_version == ObjectVersion.V1
        assert envelope.payload == {"key": "value", "score": 0.5}

    def test_content_hash_preserved(self):
        record = _make_legacy_record()
        envelope = legacy_record_to_envelope(record)
        assert envelope.content_hash == record["payload_hash"]

    def test_content_hash_computed_if_missing(self):
        record = _make_legacy_record()
        record["payload_hash"] = None
        envelope = legacy_record_to_envelope(record)
        assert envelope.content_hash == _compute_content_hash(record["payload"])

    def test_source_reference_becomes_parent_ref(self):
        record = _make_legacy_record(source_reference="node:abc")
        envelope = legacy_record_to_envelope(record)
        assert envelope.parent_references == ["node:abc"]

    def test_created_epoch_preserved(self):
        record = _make_legacy_record(created_epoch=42)
        envelope = legacy_record_to_envelope(record)
        assert envelope.created_epoch == 42

    def test_ledger_commitment_inferred(self):
        record = _make_legacy_record(object_type="reputation_profile")
        envelope = legacy_record_to_envelope(record)
        assert envelope.ledger_commitment == LedgerCommitmentClass.REPUTATION_PROFILE

    def test_unknown_type_no_commitment(self):
        record = _make_legacy_record(object_type="custom_type")
        envelope = legacy_record_to_envelope(record)
        assert envelope.ledger_commitment is None

    def test_empty_payload(self):
        record = _make_legacy_record(payload={})
        envelope = legacy_record_to_envelope(record)
        assert envelope.payload == {}

    def test_no_payload(self):
        record = _make_legacy_record()
        record["payload"] = None
        envelope = legacy_record_to_envelope(record)
        assert envelope.payload == {}

    def test_object_id_string_coercion(self):
        record = _make_legacy_record(object_id=123)
        envelope = legacy_record_to_envelope(record)
        assert isinstance(envelope.object_id, str)


# ---------------------------------------------------------------------------
# envelope_to_legacy_record
# ---------------------------------------------------------------------------

class TestEnvelopeToLegacyRecord:
    def test_basic_conversion(self):
        envelope = _make_envelope()
        record = envelope_to_legacy_record(envelope)
        assert record["object_id"] == "test:obj:001"
        assert record["object_type"] == "reputation_profile"
        assert record["payload_hash"] == envelope.content_hash

    def test_namespace_default(self):
        envelope = _make_envelope()
        record = envelope_to_legacy_record(envelope)
        assert record["namespace"] == "default"

    def test_namespace_custom(self):
        envelope = _make_envelope()
        record = envelope_to_legacy_record(envelope, namespace="identity")
        assert record["namespace"] == "identity"

    def test_source_node_id(self):
        envelope = _make_envelope()
        record = envelope_to_legacy_record(envelope, source_node_id="node:abc")
        assert record["_source"]["node_id"] == "node:abc"

    def test_parent_reference_becomes_source_reference(self):
        envelope = _make_envelope(parent_references=["node:xyz"])
        record = envelope_to_legacy_record(envelope)
        assert record["source_reference"] == "node:xyz"

    def test_no_parent_reference(self):
        envelope = _make_envelope(parent_references=[])
        record = envelope_to_legacy_record(envelope)
        assert record["source_reference"] is None

    def test_payload_preserved(self):
        payload = {"custom": "data", "nested": {"key": 42}}
        envelope = _make_envelope(payload=payload)
        record = envelope_to_legacy_record(envelope)
        assert record["payload"] == payload

    def test_payload_encoding_preserved(self):
        envelope = _make_envelope()
        record = envelope_to_legacy_record(envelope)
        assert record["payload_encoding"] == "json"

    def test_object_version_string(self):
        envelope = _make_envelope()
        record = envelope_to_legacy_record(envelope)
        assert record["object_version"] == "1.0"


# ---------------------------------------------------------------------------
# Round-trip conversion
# ---------------------------------------------------------------------------

class TestRoundTripConversion:
    def test_legacy_to_envelope_to_legacy(self):
        original = _make_legacy_record(source_reference="node:test")
        envelope = legacy_record_to_envelope(original)
        restored = envelope_to_legacy_record(envelope, namespace=original["namespace"])
        assert restored["object_id"] == original["object_id"]
        assert restored["object_type"] == original["object_type"]
        assert restored["payload_hash"] == original["payload_hash"]
        assert restored["payload"] == original["payload"]

    def test_envelope_to_legacy_to_envelope(self):
        original = _make_envelope(parent_references=["node:test"])
        record = envelope_to_legacy_record(original)
        restored = legacy_record_to_envelope(record)
        assert restored.object_id == original.object_id
        assert restored.object_type == original.object_type
        assert restored.content_hash == original.content_hash


# ---------------------------------------------------------------------------
# RegistryServiceAdapter
# ---------------------------------------------------------------------------

class TestRegistryServiceAdapter:
    def test_init_without_legacy(self):
        adapter = RegistryServiceAdapter()
        assert adapter.legacy_service is None
        assert adapter.store is not None

    def test_init_with_legacy(self):
        mock_legacy = MagicMock()
        mock_legacy.list_registry_objects.return_value = []
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy)
        assert adapter.legacy_service is mock_legacy

    def test_sync_from_legacy_empty(self):
        mock_legacy = MagicMock()
        mock_legacy.list_registry_objects.return_value = []
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy)
        count = adapter.sync_from_legacy()
        assert count == 0

    def test_sync_from_legacy_populates_store(self):
        mock_legacy = MagicMock()
        record = _make_legacy_record()
        mock_legacy.list_registry_objects.return_value = [record]
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy)
        count = adapter.sync_from_legacy()
        assert count == 1
        assert adapter.store.has("test:obj:001")

    def test_sync_from_legacy_with_type_filter(self):
        mock_legacy = MagicMock()
        mock_legacy.list_registry_objects.return_value = []
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy)
        adapter.sync_from_legacy(object_type="reputation_profile")
        mock_legacy.list_registry_objects.assert_called_once()
        # Called with positional dict arg
        call_args = mock_legacy.list_registry_objects.call_args[0][0]
        assert call_args["object_type"] == "reputation_profile"

    def test_sync_to_legacy_empty(self):
        mock_legacy = MagicMock()
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy)
        count = adapter.sync_to_legacy()
        assert count == 0

    def test_sync_to_legacy_pushes_objects(self):
        mock_legacy = MagicMock()
        mock_legacy.upsert_registry_object.return_value = {}
        store = ImmutableObjectStore()
        envelope = _make_envelope()
        store.put(envelope)
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy, store=store)
        count = adapter.sync_to_legacy()
        assert count == 1
        mock_legacy.upsert_registry_object.assert_called_once()

    def test_query_store_only(self):
        store = ImmutableObjectStore()
        envelope = _make_envelope()
        store.put(envelope)
        adapter = RegistryServiceAdapter(store=store)
        results = adapter.query(source="store")
        assert len(results) == 1
        assert results[0]["source"] == "store"

    def test_query_legacy_only(self):
        mock_legacy = MagicMock()
        record = _make_legacy_record()
        mock_legacy.list_registry_objects.return_value = [record]
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy)
        results = adapter.query(source="legacy")
        assert len(results) == 1
        assert results[0]["source"] == "legacy"

    def test_query_both_store_precedence(self):
        mock_legacy = MagicMock()
        record = _make_legacy_record()
        mock_legacy.list_registry_objects.return_value = [record]
        store = ImmutableObjectStore()
        store.put(_make_envelope())
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy, store=store)
        results = adapter.query(source="both")
        # Store result takes precedence
        found = [r for r in results if r["object_id"] == "test:obj:001"]
        assert len(found) == 1
        assert found[0]["source"] == "store"

    def test_mirror_from_legacy(self):
        mock_legacy = MagicMock()
        record = _make_legacy_record()
        mock_legacy.list_registry_objects.return_value = [record]
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy)
        result = adapter.mirror(direction="from_legacy")
        assert result["synced_from_legacy"] == 1

    def test_mirror_to_legacy(self):
        mock_legacy = MagicMock()
        mock_legacy.upsert_registry_object.return_value = {}
        store = ImmutableObjectStore()
        store.put(_make_envelope())
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy, store=store)
        result = adapter.mirror(direction="to_legacy")
        assert result["pushed_to_legacy"] == 1

    def test_mirror_both(self):
        mock_legacy = MagicMock()
        record = _make_legacy_record()
        mock_legacy.list_registry_objects.return_value = [record]
        mock_legacy.upsert_registry_object.return_value = {}
        adapter = RegistryServiceAdapter(legacy_service=mock_legacy)
        result = adapter.mirror(direction="both")
        assert result["synced_from_legacy"] == 1
        assert result["pushed_to_legacy"] >= 1

    def test_get_stats(self):
        store = ImmutableObjectStore()
        adapter = RegistryServiceAdapter(store=store)
        stats = adapter.get_stats()
        assert stats.total_objects == 0

    def test_has_object(self):
        store = ImmutableObjectStore()
        store.put(_make_envelope())
        adapter = RegistryServiceAdapter(store=store)
        assert adapter.has_object("test:obj:001") is True
        assert adapter.has_object("nonexistent") is False

    def test_add_envelope(self):
        adapter = RegistryServiceAdapter()
        envelope = _make_envelope()
        assert adapter.add_envelope(envelope) is True

    def test_add_legacy_record(self):
        adapter = RegistryServiceAdapter()
        record = _make_legacy_record()
        result = adapter.add_legacy_record(record)
        assert result is not None
        assert result.object_id == "test:obj:001"

    def test_add_legacy_record_failure(self):
        adapter = RegistryServiceAdapter()
        # Empty dict still produces a valid envelope with defaults;
        # test that duplicate adds return None via store rejection
        record = _make_legacy_record()
        adapter.add_legacy_record(record)
        result = adapter.add_legacy_record(record)  # duplicate
        # Second add should fail because store already has the object
        assert result is None
