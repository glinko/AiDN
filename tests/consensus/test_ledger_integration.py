"""Tests for consensus integration with LedgerOperationService."""

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.ledger.service import LedgerOperationService


# ── Helpers ──────────────────────────────────────────────────────────

NOW = "2025-06-01T12:00:00Z"

BASE_KW = dict(
    created_at="2025-06-01T11:00:00Z",
)


def _envelope(**kw):
    d = dict(**BASE_KW, **kw)
    return LedgerOperationEnvelope(**d)


def _service():
    return LedgerOperationService()


def _validator(**kw):
    return AdmissionValidator(current_time=NOW, **kw)


# ── 1. Submit valid operation ───────────────────────────────────────

def test_submit_valid_operation():
    svc = _service()
    env = _envelope(
        operation_type="WALLET_TRANSFER",
        origin_type="protocol",
        fee_class="standard",
    )
    v = _validator()
    result = svc.submit_operation(
        operation_type=env.operation_type,
        origin_type=env.origin_type,
        fee_class=env.fee_class,
        admission_validator=v,
        envelope=env,
    )
    assert result["admitted"] is True
    assert result["operation_id"] == env.operation_id
    assert "record" in result


# ── 2. Submit rejected operation ────────────────────────────────────

def test_submit_rejected_operation():
    svc = _service()
    env = _envelope(
        operation_type="WALLET_TRANSFER",
        origin_type="protocol",
        expires_at="2020-01-01T00:00:00Z",
    )
    v = _validator()
    result = svc.submit_operation(
        operation_type=env.operation_type,
        origin_type=env.origin_type,
        fee_class=env.fee_class,
        admission_validator=v,
        envelope=env,
    )
    assert result["admitted"] is False
    assert result["reason"] == "operation_expired"


# ── 3. Submit duplicate rejected ────────────────────────────────────

def test_submit_duplicate_rejected():
    svc = _service()
    env = _envelope(
        operation_type="WALLET_TRANSFER",
        origin_type="protocol",
    )
    v = _validator(finalized_operation_ids={env.operation_id})
    result = svc.submit_operation(
        operation_type=env.operation_type,
        origin_type=env.origin_type,
        fee_class=env.fee_class,
        admission_validator=v,
        envelope=env,
    )
    assert result["admitted"] is False
    assert result["reason"] == "duplicate_operation_id"


# ── 4. Sequence advanced after submit ───────────────────────────────

def test_sequence_advanced_after_submit():
    svc = _service()
    v = _validator()
    env = _envelope(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        sender_wallet="w1",
        sender_sequence=1,
    )
    result = svc.submit_operation(
        operation_type=env.operation_type,
        origin_type=env.origin_type,
        fee_class=env.fee_class,
        admission_validator=v,
        envelope=env,
    )
    assert result["admitted"] is True
    # sequence should be advanced to 2
    assert svc.get_next_sequence("w1") == 2


# ── 5. get_next_sequence for new wallet ─────────────────────────────

def test_get_next_sequence_new_wallet():
    svc = _service()
    assert svc.get_next_sequence("brand-new") == 1


# ── 6. get_next_sequence for existing wallet ────────────────────────

def test_get_next_sequence_existing_wallet():
    svc = _service()
    v = _validator()
    env = _envelope(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        sender_wallet="w1",
        sender_sequence=1,
    )
    svc.submit_operation(
        operation_type=env.operation_type,
        origin_type=env.origin_type,
        fee_class=env.fee_class,
        admission_validator=v,
        envelope=env,
    )
    assert svc.get_next_sequence("w1") == 2


# ── 7. Submit with all fields ───────────────────────────────────────

def test_submit_with_all_fields():
    svc = _service()
    v = _validator()
    env = _envelope(
        operation_type="SESSION_OPEN",
        origin_type="multi_party",
        fee_class="session",
        initiator_id="session-001",
        sender_wallet=None,
        fee_payer="fee-payer-1",
        payload={"session_id": "s-001"},
        evidence_references=["ev-001"],
        signatures=["sig-001"],
        expires_at="2025-12-31T23:59:59Z",
        target_epoch="epoch-10",
    )
    result = svc.submit_operation(
        operation_type=env.operation_type,
        origin_type=env.origin_type,
        fee_class=env.fee_class,
        admission_validator=v,
        envelope=env,
    )
    assert result["admitted"] is True
    assert result["operation_id"] == env.operation_id


# ── 8. Submit preserves operation_id ────────────────────────────────

def test_submit_preserves_operation_id():
    svc = _service()
    v = _validator()
    env = _envelope(
        operation_type="WALLET_TRANSFER",
        origin_type="protocol",
    )
    expected_id = env.operation_id
    result = svc.submit_operation(
        operation_type=env.operation_type,
        origin_type=env.origin_type,
        fee_class=env.fee_class,
        admission_validator=v,
        envelope=env,
    )
    assert result["operation_id"] == expected_id


# ── 9. Full integration flow ────────────────────────────────────────

def test_integration_full_flow():
    svc = _service()
    v = _validator(wallet_sequences={"w1": 1})

    # First op
    env1 = _envelope(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        sender_wallet="w1",
        sender_sequence=1,
    )
    r1 = svc.submit_operation(
        operation_type=env1.operation_type,
        origin_type=env1.origin_type,
        fee_class=env1.fee_class,
        admission_validator=v,
        envelope=env1,
    )
    assert r1["admitted"] is True
    assert svc.get_next_sequence("w1") == 2

    # Second op — must use sequence 2
    env2 = _envelope(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        sender_wallet="w1",
        sender_sequence=2,
    )
    r2 = svc.submit_operation(
        operation_type=env2.operation_type,
        origin_type=env2.origin_type,
        fee_class=env2.fee_class,
        admission_validator=v,
        envelope=env2,
    )
    assert r2["admitted"] is True
    assert svc.get_next_sequence("w1") == 3

    # Third op — wrong sequence, rejected
    env3 = _envelope(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        sender_wallet="w1",
        sender_sequence=5,
    )
    r3 = svc.submit_operation(
        operation_type=env3.operation_type,
        origin_type=env3.origin_type,
        fee_class=env3.fee_class,
        admission_validator=v,
        envelope=env3,
    )
    assert r3["admitted"] is False


# ── 10. Rejection does not advance sequence ─────────────────────────

def test_integration_rejection_does_not_advance_sequence():
    svc = _service()
    v = _validator(wallet_sequences={"w1": 1})

    env = _envelope(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        sender_wallet="w1",
        sender_sequence=1,
        expires_at="2020-01-01T00:00:00Z",  # expired
    )
    result = svc.submit_operation(
        operation_type=env.operation_type,
        origin_type=env.origin_type,
        fee_class=env.fee_class,
        admission_validator=v,
        envelope=env,
    )
    assert result["admitted"] is False
    # sequence should NOT have advanced
    assert svc.get_next_sequence("w1") == 1
