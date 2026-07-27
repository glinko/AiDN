"""Tests for consensus/admission.py — AdmissionValidator."""


from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope

# ── Helpers ──────────────────────────────────────────────────────────

NOW = "2025-06-01T12:00:00Z"

DEFAULT_KW = dict(
    operation_type="WALLET_TRANSFER",
    origin_type="wallet",
    created_at="2025-06-01T11:00:00Z",
)


def _envelope(**kw):
    d = dict(**DEFAULT_KW, **kw)
    return LedgerOperationEnvelope(**d)


def _validator(**kw):
    return AdmissionValidator(current_time=NOW, **kw)


# ── 1. Valid envelope admitted ──────────────────────────────────────

def test_admit_valid_envelope():
    v = _validator()
    env = _envelope()
    r = v.validate(env)
    assert r.admitted is True
    assert r.reason is None


# ── 2. Duplicate detection ──────────────────────────────────────────

def test_reject_duplicate_operation_id():
    env = _envelope()
    v = _validator(finalized_operation_ids={env.operation_id})
    r = v.validate(env)
    assert r.admitted is False
    assert r.reason == "duplicate_operation_id"


# ── 3. Sender sequence — too low ────────────────────────────────────

def test_reject_invalid_sender_sequence_too_low():
    env = _envelope(sender_wallet="w1", sender_sequence=1)
    v = _validator(wallet_sequences={"w1": 5})
    r = v.validate(env)
    assert r.admitted is False
    assert r.reason == "invalid_sender_sequence"


# ── 4. Sender sequence — too high ───────────────────────────────────

def test_reject_invalid_sender_sequence_too_high():
    env = _envelope(sender_wallet="w1", sender_sequence=10)
    v = _validator(wallet_sequences={"w1": 3})
    r = v.validate(env)
    assert r.admitted is False
    assert r.reason == "invalid_sender_sequence"


# ── 5. Correct sequence accepted ────────────────────────────────────

def test_accept_correct_sequence():
    env = _envelope(sender_wallet="w1", sender_sequence=5)
    v = _validator(wallet_sequences={"w1": 5})
    r = v.validate(env)
    assert r.admitted is True


# ── 6. First sequence for new wallet ────────────────────────────────

def test_accept_first_sequence_for_new_wallet():
    env = _envelope(sender_wallet="new-wallet", sender_sequence=1)
    v = _validator(wallet_sequences={})
    r = v.validate(env)
    assert r.admitted is True


# ── 7. Expiry — rejected ────────────────────────────────────────────

def test_reject_expired_operation():
    env = _envelope(expires_at="2025-05-01T00:00:00Z")
    v = _validator()
    r = v.validate(env)
    assert r.admitted is False
    assert r.reason == "operation_expired"


# ── 8. Expiry — not expired ─────────────────────────────────────────

def test_accept_non_expired_operation():
    env = _envelope(expires_at="2025-12-31T23:59:59Z")
    v = _validator()
    r = v.validate(env)
    assert r.admitted is True


# ── 9. Payload too large ────────────────────────────────────────────

def test_reject_payload_too_large():
    big = {"data": "x" * 70000}
    env = _envelope(payload=big)
    v = _validator()
    r = v.validate(env)
    assert r.admitted is False
    assert r.reason == "payload_too_large"


# ── 10. Payload under limit ─────────────────────────────────────────

def test_accept_payload_under_limit():
    small = {"data": "x" * 100}
    env = _envelope(payload=small)
    v = _validator()
    r = v.validate(env)
    assert r.admitted is True


# ── 11. Too many evidence refs ──────────────────────────────────────

def test_reject_too_many_evidence_refs():
    refs = [f"ev-{i}" for i in range(17)]
    env = _envelope(evidence_references=refs)
    v = _validator()
    r = v.validate(env)
    assert r.admitted is False
    assert r.reason == "too_many_evidence_refs"


# ── 12. Evidence refs under limit ───────────────────────────────────

def test_accept_evidence_refs_under_limit():
    refs = [f"ev-{i}" for i in range(16)]
    env = _envelope(evidence_references=refs)
    v = _validator()
    r = v.validate(env)
    assert r.admitted is True


# ── 13. Too many signatures ────────────────────────────────────────

def test_reject_too_many_signatures():
    sigs = [f"sig-{i}" for i in range(9)]
    env = _envelope(signatures=sigs)
    v = _validator()
    r = v.validate(env)
    assert r.admitted is False
    assert r.reason == "too_many_signatures"


# ── 14. Signatures under limit ──────────────────────────────────────

def test_accept_signatures_under_limit():
    sigs = [f"sig-{i}" for i in range(8)]
    env = _envelope(signatures=sigs)
    v = _validator()
    r = v.validate(env)
    assert r.admitted is True


def test_required_signature_is_enforced_for_configured_origin():
    v = AdmissionValidator(
        current_time=NOW,
        require_signature_for_origins=frozenset({"wallet"}),
    )
    r = v.validate(_envelope())
    assert r.admitted is False
    assert r.reason == "signature_required"


def test_signature_verifier_rejects_invalid_signature():
    v = AdmissionValidator(
        current_time=NOW,
        signature_verifier=lambda envelope: False,
    )
    r = v.validate(_envelope(signatures=["ed25519:invalid"]))
    assert r.admitted is False
    assert r.reason == "signature_invalid"


# ── 15. record_finalized then reject duplicate ──────────────────────

def test_record_finalized_then_reject_duplicate():
    env = _envelope()
    v = _validator()
    v.record_finalized(env.operation_id)
    r = v.validate(env)
    assert r.admitted is False
    assert r.reason == "duplicate_operation_id"


# ── 16. advance_wallet_sequence ─────────────────────────────────────

def test_advance_wallet_sequence():
    v = _validator(wallet_sequences={"w1": 3})
    nxt = v.advance_wallet_sequence("w1")
    assert nxt == 4
    assert v._wallet_sequences["w1"] == 4


# ── 17. advance_wallet_sequence multiple times ──────────────────────

def test_advance_wallet_sequence_multiple():
    v = _validator(wallet_sequences={})
    assert v.advance_wallet_sequence("w1") == 2
    assert v.advance_wallet_sequence("w1") == 3
    assert v.advance_wallet_sequence("w1") == 4


# ── 18. Admit without sender_wallet ─────────────────────────────────

def test_admit_without_sender_wallet():
    env = _envelope(sender_wallet=None)
    v = _validator()
    r = v.validate(env)
    assert r.admitted is True


# ── 19. Admit without expires_at ────────────────────────────────────

def test_admit_without_expires_at():
    env = _envelope(expires_at=None)
    v = _validator()
    r = v.validate(env)
    assert r.admitted is True


# ── 20. Admit with empty payload ────────────────────────────────────

def test_admit_with_empty_payload():
    env = _envelope(payload={})
    v = _validator()
    r = v.validate(env)
    assert r.admitted is True


# ── 21. Multiple validations independent ────────────────────────────

def test_multiple_validations_independent():
    v = _validator(wallet_sequences={"w1": 1})
    env1 = _envelope(sender_wallet="w1", sender_sequence=1)
    env2 = _envelope(sender_wallet="w2", sender_sequence=1)
    assert v.validate(env1).admitted is True
    assert v.validate(env2).admitted is True


# ── 22. Sequence gap rejected ───────────────────────────────────────

def test_sequence_gap_rejected():
    v = _validator(wallet_sequences={"w1": 3})
    env = _envelope(sender_wallet="w1", sender_sequence=5)
    r = v.validate(env)
    assert r.admitted is False
    assert r.reason == "invalid_sender_sequence"


# ── 23. Expired boundary — exact match accepted ─────────────────────

def test_expired_boundary_exact():
    env = _envelope(expires_at=NOW)
    v = _validator()
    r = v.validate(env)
    # expires_at == current_time → not expired (strict <)
    assert r.admitted is True


# ── 24. Payload boundary — exactly at limit ─────────────────────────

def test_payload_boundary_exact():
    # 65536 bytes payload
    data = "x" * 65520  # minus JSON overhead ≈ 65536
    env = _envelope(payload={"data": data})
    v = _validator(max_payload_bytes=65536)
    # should be admitted (under or at limit)
    r = v.validate(env)
    assert r.admitted is True


# ── 25. Admission result reasons ────────────────────────────────────

def test_admission_result_reasons():
    reasons = [
        "duplicate_operation_id",
        "invalid_sender_sequence",
        "operation_expired",
        "payload_too_large",
        "too_many_evidence_refs",
        "too_many_signatures",
    ]
    for reason in reasons:
        env = _envelope()
        # construct a validator that will fail with this reason
        if reason == "duplicate_operation_id":
            v = _validator(finalized_operation_ids={env.operation_id})
        elif reason == "invalid_sender_sequence":
            env = _envelope(sender_wallet="w1", sender_sequence=99)
            v = _validator(wallet_sequences={"w1": 1})
        elif reason == "operation_expired":
            env = _envelope(expires_at="2020-01-01T00:00:00Z")
            v = _validator()
        elif reason == "payload_too_large":
            env = _envelope(payload={"x": "y" * 100000})
            v = _validator()
        elif reason == "too_many_evidence_refs":
            env = _envelope(evidence_references=[f"e{i}" for i in range(20)])
            v = _validator()
        elif reason == "too_many_signatures":
            env = _envelope(signatures=[f"s{i}" for i in range(20)])
            v = _validator()
        r = v.validate(env)
        assert r.admitted is False, f"Expected rejection for {reason}"
        assert r.reason == reason, f"Expected reason {reason}, got {r.reason}"
