"""Tests for consensus/models.py — LedgerOperationEnvelope."""

import json

import pytest

from aidn_hypervisor.consensus.models import (
    LedgerFeeClass,
    LedgerOperationEnvelope,
    LedgerOriginType,
    OperationType,
)

# ── Helpers ──────────────────────────────────────────────────────────

def _make_envelope(**overrides):
    defaults = dict(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        created_at="2025-01-01T00:00:00Z",
    )
    defaults.update(overrides)
    return LedgerOperationEnvelope(**defaults)


# ── 1. Basic creation ────────────────────────────────────────────────

def test_create_envelope_basic():
    env = _make_envelope()
    assert env.operation_type == "WALLET_TRANSFER"
    assert env.operation_version == "1.0.0"
    assert env.protocol_version == "0.1"
    assert env.origin_type == "wallet"
    assert env.fee_class == "standard"
    assert env.payload == {}
    assert env.evidence_references == []
    assert env.signatures == []
    assert env.operation_id != ""


# ── 2. Deterministic operation_id ────────────────────────────────────

def test_operation_id_is_deterministic():
    payload = {"key": "value", "amount": 100}
    env1 = _make_envelope(payload=payload)
    env2 = _make_envelope(payload=payload)
    assert env1.operation_id == env2.operation_id


def test_operation_id_differs_on_payload_change():
    env1 = _make_envelope(payload={"amount": 100})
    env2 = _make_envelope(payload={"amount": 200})
    assert env1.operation_id != env2.operation_id


def test_operation_id_differs_on_type_change():
    env1 = _make_envelope(operation_type="WALLET_TRANSFER")
    env2 = _make_envelope(operation_type="SESSION_OPEN")
    assert env1.operation_id != env2.operation_id


def test_operation_id_cannot_be_overridden():
    with pytest.raises(ValueError, match="operation_id does not match"):
        _make_envelope(operation_id="forged")


def test_signature_does_not_change_operation_identity():
    unsigned = _make_envelope(payload={"amount": 100})
    signed = _make_envelope(payload={"amount": 100}, signatures=["ed25519:deadbeef"])
    assert signed.operation_id == unsigned.operation_id
    assert signed.signing_bytes() == unsigned.signing_bytes()


# ── 3. Canonical bytes ───────────────────────────────────────────────

def test_canonical_bytes_deterministic():
    env = _make_envelope(payload={"x": 1})
    b1 = env.canonical_bytes()
    b2 = env.canonical_bytes()
    assert b1 == b2
    # no whitespace
    assert b" " not in b1
    assert b"\t" not in b1
    assert b"\n" not in b1


# ── 4. Immutability ──────────────────────────────────────────────────

def test_envelope_immutability():
    env = _make_envelope()
    with pytest.raises(Exception):  # pydantic FrozenInstanceError
        env.operation_type = "SESSION_OPEN"  # type: ignore


# ── 5. sender_sequence validation ────────────────────────────────────

def test_sender_sequence_ge_1():
    with pytest.raises(Exception):
        _make_envelope(sender_sequence=0)
    with pytest.raises(Exception):
        _make_envelope(sender_sequence=-1)
    # valid
    _make_envelope(sender_sequence=1)
    _make_envelope(sender_sequence=42)


# ── 6. All operation types ───────────────────────────────────────────

def test_all_operation_types():
    types: list[OperationType] = [
        "WALLET_TRANSFER",
        "SESSION_OPEN",
        "DEPOSIT_LOCK",
        "SESSION_SETTLE",
        "ENDPOINT_PUBLISH",
        "VALIDATION_REQUEST",
        "VALIDATION_REPORT",
        "VALIDATOR_STAKE",
        "VALIDATOR_UNSTAKE",
        "REGISTRY_UPSERT",
        "SNAPSHOT_COMMIT",
        "EPOCH_TASK",
        "SETTLEMENT_PROPOSE",
        "SETTLEMENT_ACCEPT",
    ]
    for op_type in types:
        env = _make_envelope(operation_type=op_type)
        assert env.operation_type == op_type


# ── 7. All origin types ──────────────────────────────────────────────

def test_all_origin_types():
    origins: list[LedgerOriginType] = [
        "wallet",
        "multi_party",
        "protocol",
        "evidence_triggered",
    ]
    for origin in origins:
        env = _make_envelope(origin_type=origin)
        assert env.origin_type == origin


# ── 8. All fee classes ───────────────────────────────────────────────

def test_all_fee_classes():
    classes: list[LedgerFeeClass] = [
        "standard",
        "session",
        "protocol_sponsored",
        "onboarding_exempt",
        "faucet_exempt",
    ]
    for fc in classes:
        env = _make_envelope(fee_class=fc)
        assert env.fee_class == fc


# ── 9. Optional fields ───────────────────────────────────────────────

def test_envelope_with_expires_at():
    env = _make_envelope(expires_at="2025-12-31T23:59:59Z")
    assert env.expires_at == "2025-12-31T23:59:59Z"


def test_envelope_with_target_epoch():
    env = _make_envelope(target_epoch="epoch-42")
    assert env.target_epoch == "epoch-42"


def test_envelope_with_evidence_references():
    refs = ["ev-001", "ev-002"]
    env = _make_envelope(evidence_references=refs)
    assert env.evidence_references == refs


def test_envelope_with_signatures():
    sigs = ["sig-abc", "sig-def"]
    env = _make_envelope(signatures=sigs)
    assert env.signatures == sigs


# ── 10. operation_id excludes itself from hash ───────────────────────

def test_canonical_excludes_operation_id_from_hash():
    env = _make_envelope()
    canon = env.canonical_bytes().decode("utf-8")
    parsed = json.loads(canon)
    assert parsed["operation_id"] == ""


# ── 11. Payload edge cases ───────────────────────────────────────────

def test_empty_payload_allowed():
    env = _make_envelope(payload={})
    assert env.payload == {}


def test_nested_payload_serialization():
    nested = {"outer": {"inner": [1, 2, 3]}, "flag": True}
    env = _make_envelope(payload=nested)
    assert env.payload == nested
    # canonical bytes should be deterministic
    assert env.canonical_bytes() == env.canonical_bytes()


# ── 12. Custom versions ──────────────────────────────────────────────

def test_protocol_version_custom():
    env = _make_envelope(protocol_version="2.0")
    assert env.protocol_version == "2.0"


def test_operation_version_custom():
    env = _make_envelope(operation_version="3.1.4")
    assert env.operation_version == "3.1.4"


# ── 13. Equality ─────────────────────────────────────────────────────

def test_envelope_equality():
    env1 = _make_envelope(payload={"a": 1})
    env2 = _make_envelope(payload={"a": 1})
    env3 = _make_envelope(payload={"a": 2})
    assert env1 == env2
    assert env1 != env3
