"""Tests for AIDNABCIApplication transaction processing."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.ledger.service import LedgerOperationService


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _future_iso(hours: int = 24) -> str:
    return (datetime.now(UTC) + timedelta(hours=hours)).isoformat()


def _past_iso(hours: int = 1) -> str:
    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


def make_envelope(
    *,
    operation_type: str = "WALLET_TRANSFER",
    origin_type: str = "wallet",
    fee_class: str = "standard",
    sender_wallet: str | None = None,
    sender_sequence: int | None = None,
    expires_at: str | None = None,
    created_at: str | None = None,
    payload: dict | None = None,
    evidence_references: list[str] | None = None,
    signatures: list[str] | None = None,
) -> dict:
    """Build a raw envelope dict (not yet validated by Pydantic)."""
    return {
        "operation_type": operation_type,
        "operation_version": "1.0.0",
        "protocol_version": "0.1",
        "origin_type": origin_type,
        "initiator_id": None,
        "sender_wallet": sender_wallet,
        "sender_sequence": sender_sequence,
        "fee_payer": None,
        "fee_class": fee_class,
        "created_at": created_at or _past_iso(),
        "expires_at": expires_at or _future_iso(),
        "target_epoch": None,
        "payload": payload or {},
        "evidence_references": evidence_references or [],
        "signatures": signatures or [],
    }


def tx_bytes(envelope_dict: dict) -> bytes:
    return json.dumps(envelope_dict).encode("utf-8")


@pytest.fixture
def ledger():
    return LedgerOperationService()


@pytest.fixture
def admission():
    return AdmissionValidator(current_time=_now_iso())


@pytest.fixture
def app(ledger, admission):
    return AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=admission,
    )


def test_process_valid_tx_accepted(app):
    env = make_envelope()
    result = app.process_proposal_transaction(tx_bytes(env))
    assert result.code == "ok"


def test_process_invalid_json_rejected(app):
    result = app.process_proposal_transaction(b"not json at all{{{")
    assert result.code == "invalid"
    assert "parse error" in result.log


def test_process_expired_tx_rejected(app):
    env = make_envelope(expires_at=_past_iso(hours=2))
    result = app.process_proposal_transaction(tx_bytes(env))
    assert result.code == "rejected"
    assert "operation_expired" in result.log


def test_process_duplicate_in_mempool(app):
    env = make_envelope()
    data = tx_bytes(env)
    r1 = app.process_proposal_transaction(data)
    assert r1.code == "ok"
    r2 = app.process_proposal_transaction(data)
    assert r2.code == "duplicate"


def test_process_tx_wrong_sequence_rejected(app):
    env = make_envelope(
        sender_wallet="w1",
        sender_sequence=999,  # wallet starts at 1
    )
    result = app.process_proposal_transaction(tx_bytes(env))
    assert result.code == "rejected"
    assert "invalid_sender_sequence" in result.log


def test_process_tx_too_large_payload(app):
    # Create a payload that exceeds the default 65536 bytes
    big_payload = {"data": "x" * 70000}
    env = make_envelope(payload=big_payload)
    result = app.process_proposal_transaction(tx_bytes(env))
    assert result.code == "rejected"
    assert "payload_too_large" in result.log


def test_reject_proposal_transaction(app):
    env = make_envelope()
    result = app.reject_proposal_transaction(tx_bytes(env))
    assert result.code == "rejected"
    assert "explicit rejection" in result.log


def test_reject_invalid_transaction(app):
    result = app.reject_proposal_transaction(b"not valid json")
    assert result.code == "invalid"


def test_tx_added_to_mempool(app):
    env = make_envelope()
    data = tx_bytes(env)
    app.process_proposal_transaction(data)
    assert app.mempool.size() == 1


def test_mempool_size_increases(app):
    for i in range(3):
        env = make_envelope(payload={"idx": i})
        app.process_proposal_transaction(tx_bytes(env))
    assert app.mempool.size() == 3


def test_mempool_clears_after_block(app):
    env = make_envelope()
    data = tx_bytes(env)
    app.process_proposal_transaction(data)
    assert app.mempool.size() == 1
    app.finalize_block(block_height=1, block_hash=b"\x01" * 32, txs=[data])
    assert app.mempool.size() == 0


def test_process_multiple_txs(app):
    txs = []
    for i in range(5):
        env = make_envelope(payload={"idx": i})
        txs.append(tx_bytes(env))
    for data in txs:
        result = app.process_proposal_transaction(data)
        assert result.code == "ok"
    assert app.mempool.size() == 5


def test_tx_with_all_fields_accepted(app):
    env = make_envelope(
        operation_type="SESSION_OPEN",
        origin_type="wallet",
        fee_class="session",
        sender_wallet="w1",
        sender_sequence=1,
        payload={"session_id": "s1"},
    )
    result = app.process_proposal_transaction(tx_bytes(env))
    assert result.code == "ok"


def test_process_tx_returns_operation_id(app):
    env = make_envelope()
    data = tx_bytes(env)
    result = app.process_proposal_transaction(data)
    assert result.code == "ok"
    # The operation_id should be in tags
    tag_ids = [t.value for t in result.tags if t.key == "operation_id"]
    assert len(tag_ids) == 1
    assert len(tag_ids[0]) == 64  # SHA-256 hex


def test_admission_reject_reason_in_log(app):
    env = make_envelope(expires_at=_past_iso())
    result = app.process_proposal_transaction(tx_bytes(env))
    assert result.code == "rejected"
    assert len(result.tags) >= 2
    reason_tags = [t for t in result.tags if t.key == "reason"]
    assert len(reason_tags) == 1


def test_genesis_accounts_credited(ledger):
    app = AIDNABCIApplication(
        ledger_service=ledger,
        genesis_accounts={"w_genesis": 10000},
    )
    assert ledger.wallet_q_atom_balance("w_genesis") == 10000


def test_process_tx_without_wallet_accepted(app):
    env = make_envelope(origin_type="protocol", sender_wallet=None)
    result = app.process_proposal_transaction(tx_bytes(env))
    assert result.code == "ok"


def test_process_tx_with_expires_at_accepted(app):
    env = make_envelope(expires_at=_future_iso(hours=48))
    result = app.process_proposal_transaction(tx_bytes(env))
    assert result.code == "ok"


def test_mempool_duplicate_detection(app):
    env = make_envelope()
    data = tx_bytes(env)
    app.process_proposal_transaction(data)
    # Same envelope, same operation_id
    data2 = tx_bytes(env)
    result = app.process_proposal_transaction(data2)
    assert result.code == "duplicate"


def test_process_tx_gas_tracking(app):
    env = make_envelope()
    result = app.process_proposal_transaction(tx_bytes(env))
    # Default gas values
    assert result.gas_used == 0
    assert result.gas_wanted == 0
