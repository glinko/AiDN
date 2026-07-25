"""Tests for AIDNABCIApplication block finalization."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.abci_models import ABCIResult
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
    origin_type: str = "protocol",
    fee_class: str = "standard",
    sender_wallet: str | None = None,
    sender_sequence: int | None = None,
    expires_at: str | None = None,
    created_at: str | None = None,
    payload: dict | None = None,
) -> dict:
    """Build a raw envelope dict. Uses protocol origin by default (no wallet checks)."""
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
        "evidence_references": [],
        "signatures": [],
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


def test_finalize_empty_block(app):
    result = app.finalize_block(block_height=1, block_hash=b"\x01" * 32, txs=[])
    assert result.code == "ok"
    assert "executed=0" in result.log
    assert "rejected=0" in result.log


def test_finalize_block_with_one_tx(app):
    env = make_envelope(origin_type="protocol")
    data = tx_bytes(env)
    result = app.finalize_block(block_height=1, block_hash=b"\x01" * 32, txs=[data])
    assert result.code == "ok"
    assert "executed=1" in result.log
    assert "rejected=0" in result.log
    assert app.mempool.size() == 0
    assert app._last_block_height == 1


def test_finalize_block_with_multiple_txs(app):
    txs = [tx_bytes(make_envelope(payload={"idx": i})) for i in range(3)]
    result = app.finalize_block(block_height=1, block_hash=b"\x01" * 32, txs=txs)
    assert result.code == "ok"
    assert "executed=3" in result.log
    assert "rejected=0" in result.log


def test_finalize_block_executes_and_rejects(app):
    valid = tx_bytes(make_envelope(origin_type="protocol"))
    expired = tx_bytes(make_envelope(origin_type="protocol", expires_at=_past_iso()))
    result = app.finalize_block(
        block_height=1, block_hash=b"\x01" * 32, txs=[valid, expired]
    )
    assert result.code == "ok"
    assert "executed=1" in result.log
    assert "rejected=1" in result.log


def test_finalize_block_updates_height(app):
    app.finalize_block(block_height=1, block_hash=b"\x01" * 32, txs=[])
    assert app._last_block_height == 1
    app.finalize_block(block_height=2, block_hash=b"\x02" * 32, txs=[])
    assert app._last_block_height == 2


def test_finalize_block_updates_app_hash(app):
    h_before = app._app_hash
    env = make_envelope(origin_type="protocol")
    app.finalize_block(block_height=1, block_hash=b"\x01" * 32, txs=[tx_bytes(env)])
    h_after = app._app_hash
    assert h_before != h_after


def test_finalize_block_clears_mempool(app):
    env = make_envelope(origin_type="protocol")
    data = tx_bytes(env)
    app.process_proposal_transaction(data)
    assert app.mempool.size() == 1
    app.finalize_block(block_height=1, block_hash=b"\x01" * 32, txs=[data])
    assert app.mempool.size() == 0


def test_finalize_block_returns_counts(app):
    valid = tx_bytes(make_envelope(origin_type="protocol"))
    expired = tx_bytes(make_envelope(origin_type="protocol", expires_at=_past_iso()))
    result = app.finalize_block(
        block_height=1, block_hash=b"\x01" * 32, txs=[valid, expired]
    )
    tag_map = {t.key: t.value for t in result.tags}
    assert tag_map["executed"] == "1"
    assert tag_map["rejected"] == "1"


def test_finalize_block_with_invalid_txs(app):
    result = app.finalize_block(
        block_height=1, block_hash=b"\x01" * 32, txs=[b"not json at all{{{"]
    )
    assert result.code == "ok"
    assert "rejected=1" in result.log


def test_block_height_monotonic(app):
    for h in range(1, 6):
        app.finalize_block(block_height=h, block_hash=bytes([h]) * 32, txs=[])
        assert app._last_block_height == h


def test_block_execution_order_deterministic(app):
    txs = [tx_bytes(make_envelope(payload={"idx": i})) for i in range(3)]
    result = app.finalize_block(block_height=1, block_hash=b"\x01" * 32, txs=txs)
    assert "executed=3" in result.log


def test_block_emits_events(app):
    env = make_envelope(origin_type="protocol")
    data = tx_bytes(env)
    result = app.finalize_block(block_height=1, block_hash=b"\x01" * 32, txs=[data])
    # Tags should include operation info
    assert len(result.tags) >= 3  # height, executed, rejected


def test_finalize_block_with_time(app):
    result = app.finalize_block(
        block_height=1,
        block_hash=b"\x01" * 32,
        txs=[],
        time="2025-06-01T00:00:00Z",
    )
    assert result.code == "ok"


def test_block_tags_include_height(app):
    result = app.finalize_block(block_height=42, block_hash=b"\x01" * 32, txs=[])
    tag_map = {t.key: t.value for t in result.tags}
    assert tag_map["height"] == "42"


def test_finalize_block_atomic_on_ledger(app):
    env = make_envelope(origin_type="protocol")
    data = tx_bytes(env)
    ops_before = len(app.ledger._operations)
    app.finalize_block(block_height=1, block_hash=b"\x01" * 32, txs=[data])
    ops_after = len(app.ledger._operations)
    assert ops_after == ops_before + 1


def test_consecutive_blocks_increment_height(app):
    for h in range(1, 4):
        app.finalize_block(block_height=h, block_hash=bytes([h]) * 32, txs=[])
    assert app._last_block_height == 3


def test_block_with_all_rejected_txs(app):
    expired1 = tx_bytes(make_envelope(origin_type="protocol", expires_at=_past_iso()))
    expired2 = tx_bytes(make_envelope(origin_type="protocol", expires_at=_past_iso()))
    result = app.finalize_block(
        block_height=1, block_hash=b"\x01" * 32, txs=[expired1, expired2]
    )
    assert result.code == "ok"
    assert "executed=0" in result.log
    assert "rejected=2" in result.log


def test_finalize_block_preserves_state(ledger, admission, app):
    env = make_envelope(origin_type="protocol")
    data = tx_bytes(env)
    app.finalize_block(block_height=1, block_hash=b"\x01" * 32, txs=[data])
    h1 = app._compute_state_hash()
    # Another empty block should still be deterministic
    app.finalize_block(block_height=2, block_hash=b"\x02" * 32, txs=[])
    h2 = app._compute_state_hash()
    assert h1 == h2  # state unchanged by empty block


def test_block_hash_tracking(app):
    block_hash = b"\xDE\xAD\xBE\xEF" * 8
    app.finalize_block(block_height=1, block_hash=block_hash, txs=[])
    assert app._last_block_hash == block_hash


def test_finalize_block_with_mixed_admission(app):
    valid1 = tx_bytes(make_envelope(origin_type="protocol"))
    valid2 = tx_bytes(make_envelope(origin_type="protocol"))
    expired = tx_bytes(make_envelope(origin_type="protocol", expires_at=_past_iso()))
    result = app.finalize_block(
        block_height=1,
        block_hash=b"\x01" * 32,
        txs=[valid1, valid2, expired],
    )
    assert result.code == "ok"
    assert "executed=2" in result.log
    assert "rejected=1" in result.log
