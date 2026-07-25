"""Tests for registry/object_envelope — Registry Object Envelope (RFC-0061 §6-7)."""

from __future__ import annotations

import hashlib
import json

import pytest

from aidn_hypervisor.registry import (
    LedgerCommitmentClass,
    ObjectIdentity,
    ObjectVersion,
    RegistryObjectEnvelope,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payload() -> dict:
    return {"key": "value", "num": 42}


def _expected_hash(payload: dict | None = None) -> str:
    data = payload or _payload()
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _expected_size(payload: dict | None = None) -> int:
    data = payload or _payload()
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return len(canonical.encode())


# ---------------------------------------------------------------------------
# test_create_envelope
# ---------------------------------------------------------------------------

def test_create_envelope():
    env = RegistryObjectEnvelope.create(object_type="test", payload=_payload())
    assert env.object_type == "test"
    assert env.payload == _payload()
    assert env.content_hash == _expected_hash()
    assert env.content_size == _expected_size()
    assert env.object_version == ObjectVersion.V1
    assert env.protocol_version == "1.0.0"


# ---------------------------------------------------------------------------
# test_create_with_explicit_id
# ---------------------------------------------------------------------------

def test_create_with_explicit_id():
    env = RegistryObjectEnvelope.create(
        object_type="test",
        payload=_payload(),
        object_id="my-custom-id",
    )
    assert env.object_id == "my-custom-id"
    assert env.content_hash == _expected_hash()


# ---------------------------------------------------------------------------
# test_content_hash_computed
# ---------------------------------------------------------------------------

def test_content_hash_computed():
    env = RegistryObjectEnvelope.create(object_type="test", payload=_payload())
    assert env.content_hash == _expected_hash()
    assert len(env.content_hash) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# test_content_size_computed
# ---------------------------------------------------------------------------

def test_content_size_computed():
    env = RegistryObjectEnvelope.create(object_type="test", payload=_payload())
    assert env.content_size == _expected_size()
    assert env.content_size > 0


# ---------------------------------------------------------------------------
# test_verify_integrity_valid
# ---------------------------------------------------------------------------

def test_verify_integrity_valid():
    env = RegistryObjectEnvelope.create(object_type="test", payload=_payload())
    assert env.verify_integrity() is True


# ---------------------------------------------------------------------------
# test_verify_integrity_invalid
# ---------------------------------------------------------------------------

def test_verify_integrity_invalid():
    env = RegistryObjectEnvelope.create(object_type="test", payload=_payload())
    # Build a new envelope with the same hash but different payload
    bad_payload = {"key": "different"}
    bad_env = RegistryObjectEnvelope(
        object_id=env.object_id,
        object_type="test",
        content_hash=env.content_hash,  # wrong hash for bad_payload
        content_size=env.content_size,
        payload=bad_payload,
    )
    assert bad_env.verify_integrity() is False


# ---------------------------------------------------------------------------
# test_envelope_frozen
# ---------------------------------------------------------------------------

def test_envelope_frozen():
    env = RegistryObjectEnvelope.create(object_type="test", payload=_payload())
    with pytest.raises(Exception):  # FrozenInstanceError
        env.object_type = "other"  # type: ignore


# ---------------------------------------------------------------------------
# test_object_identity_computation
# ---------------------------------------------------------------------------

def test_object_identity_computation():
    ident = ObjectIdentity(
        object_type="validation_report",
        identity_fields={"wallet": "w1", "model": "m1"},
    )
    assert len(ident.object_id) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# test_object_identity_deterministic
# ---------------------------------------------------------------------------

def test_object_identity_deterministic():
    a = ObjectIdentity(
        object_type="validation_report",
        identity_fields={"wallet": "w1", "model": "m1"},
    )
    b = ObjectIdentity(
        object_type="validation_report",
        identity_fields={"wallet": "w1", "model": "m1"},
    )
    assert a.object_id == b.object_id


# ---------------------------------------------------------------------------
# test_object_identity_different_fields
# ---------------------------------------------------------------------------

def test_object_identity_different_fields():
    a = ObjectIdentity(
        object_type="validation_report",
        identity_fields={"wallet": "w1", "model": "m1"},
    )
    b = ObjectIdentity(
        object_type="validation_report",
        identity_fields={"wallet": "w2", "model": "m1"},
    )
    assert a.object_id != b.object_id


# ---------------------------------------------------------------------------
# test_ledger_commitment_class_enum
# ---------------------------------------------------------------------------

def test_ledger_commitment_class_enum():
    assert LedgerCommitmentClass.FINALIZED_BLOCK.value == "finalized_block"
    assert LedgerCommitmentClass.DERIVED.value == "derived"
    assert LedgerCommitmentClass.VALIDATION_REPORT.value == "validation_report"


# ---------------------------------------------------------------------------
# test_object_version_enum
# ---------------------------------------------------------------------------

def test_object_version_enum():
    assert ObjectVersion.V1.value == "1.0"


# ---------------------------------------------------------------------------
# test_envelope_with_epoch_block
# ---------------------------------------------------------------------------

def test_envelope_with_epoch_block():
    env = RegistryObjectEnvelope.create(
        object_type="test",
        payload=_payload(),
        created_epoch=42,
        created_block_height=1000,
    )
    assert env.created_epoch == 42
    assert env.created_block_height == 1000


# ---------------------------------------------------------------------------
# test_envelope_with_parent_refs
# ---------------------------------------------------------------------------

def test_envelope_with_parent_refs():
    env = RegistryObjectEnvelope.create(
        object_type="test",
        payload=_payload(),
        parent_references=["parent-1", "parent-2"],
    )
    assert env.parent_references == ["parent-1", "parent-2"]


# ---------------------------------------------------------------------------
# test_envelope_with_previous_version
# ---------------------------------------------------------------------------

def test_envelope_with_previous_version():
    env = RegistryObjectEnvelope.create(
        object_type="test",
        payload=_payload(),
        previous_version_reference="prev-v1",
    )
    assert env.previous_version_reference == "prev-v1"


# ---------------------------------------------------------------------------
# test_envelope_with_producer_signature
# ---------------------------------------------------------------------------

def test_envelope_with_producer_signature():
    env = RegistryObjectEnvelope.create(
        object_type="test",
        payload=_payload(),
        producer_signature="sig-abc",
    )
    assert env.producer_signature == "sig-abc"


# ---------------------------------------------------------------------------
# test_envelope_payload_encoding
# ---------------------------------------------------------------------------

def test_envelope_payload_encoding():
    env = RegistryObjectEnvelope.create(object_type="test", payload=_payload())
    assert env.payload_encoding == "json"


# ---------------------------------------------------------------------------
# test_envelope_compression
# ---------------------------------------------------------------------------

def test_envelope_compression():
    env = RegistryObjectEnvelope.create(object_type="test", payload=_payload())
    assert env.compression is None


# ---------------------------------------------------------------------------
# test_duplicate_object_id_same_hash
# ---------------------------------------------------------------------------

def test_duplicate_object_id_same_hash():
    """Two envelopes with same payload should produce same content-addressed id."""
    a = RegistryObjectEnvelope.create(object_type="test", payload=_payload())
    b = RegistryObjectEnvelope.create(object_type="test", payload=_payload())
    assert a.object_id == b.object_id
    assert a.content_hash == b.content_hash


# ---------------------------------------------------------------------------
# test_content_addressed_default_id
# ---------------------------------------------------------------------------

def test_content_addressed_default_id():
    env = RegistryObjectEnvelope.create(object_type="test", payload=_payload())
    assert env.object_id == env.content_hash
