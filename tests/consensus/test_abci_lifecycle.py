"""Tests for AIDNABCIApplication lifecycle — init, info, commit, snapshot, query."""


import pytest

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.abci_models import ABCIInfoResponse
from aidn_hypervisor.ledger.service import LedgerOperationService


@pytest.fixture
def ledger():
    return LedgerOperationService()


@pytest.fixture
def app(ledger):
    return AIDNABCIApplication(ledger_service=ledger)


def test_info_returns_app_metadata(app):
    resp = app.info()
    assert isinstance(resp, ABCIInfoResponse)
    assert resp.data == "AiDN Consensus Application"
    assert resp.app_version == 1
    assert resp.last_block_height == 0
    assert "0.1" in resp.version


def test_init_chain_sets_genesis(app):
    result = app.init_chain(genesis_time="2025-01-01T00:00:00Z", initial_height=1)
    assert result.code == "ok"
    assert app._last_block_height == 1
    assert app._genesis_time == "2025-01-01T00:00:00Z"


def test_init_chain_with_custom_time(app):
    result = app.init_chain(genesis_time="2026-06-01T12:00:00Z", initial_height=5)
    assert result.code == "ok"
    assert app._last_block_height == 5
    assert app._genesis_time == "2026-06-01T12:00:00Z"


def test_commit_returns_app_hash(app):
    resp = app.commit()
    assert len(resp.data) == 32  # SHA-256
    assert resp.version == "0"


def test_commit_updates_after_block(ledger, app):
    # Before block
    h1 = app.commit().data
    # Finalize a block with no txs
    app.finalize_block(block_height=1, block_hash=b"\x01" * 32, txs=[])
    h2 = app.commit().data
    # An empty block leaves the deterministic application state unchanged.
    assert len(h2) == 32
    assert h2 == h1


def test_app_hash_changes_after_operations(ledger, app):
    h_before = app._compute_state_hash()
    # Credit a wallet changes state
    ledger.credit_wallet_q_atoms(wallet_id="w1", amount_q_atoms=100)
    h_after = app._compute_state_hash()
    assert h_before != h_after


def test_prepare_snapshot_contains_state(app):
    snapshot = app.prepare_snapshot()
    assert "app_version" in snapshot
    assert "protocol_version" in snapshot
    assert "genesis_time" in snapshot
    assert "last_block_height" in snapshot
    assert "last_block_hash" in snapshot
    assert "app_hash" in snapshot
    assert "commitments" in snapshot
    assert "ledger_operations" in snapshot
    assert "wallet_sequences" in snapshot
    assert "settlement_state" in snapshot


def test_apply_snapshot_restores_state(ledger, app):
    # Take a snapshot
    snapshot = app.prepare_snapshot()
    # Modify state
    app._last_block_height = 999
    # Restore
    result = app.apply_snapshot(snapshot)
    assert result.code == "ok"
    assert app._last_block_height == snapshot["last_block_height"]


def test_apply_snapshot_invalid_fails(ledger, app):
    previous_height = app.info().last_block_height
    previous_hash = app.info().last_block_app_hash
    bad_snapshot = {
        "last_block_height": "not_an_int",
        "last_block_hash": "invalid_hex",
        "app_hash": "invalid_hex",
    }
    result = app.apply_snapshot(bad_snapshot)
    assert result.code == "internal"
    assert "snapshot restore failed" in result.log
    assert app.info().last_block_height == previous_height
    assert app.info().last_block_app_hash == previous_hash


def test_query_app_hash(app):
    resp = app.query(path="state/app_hash")
    assert resp.key == b"app_hash"
    assert len(resp.value) == 32


def test_query_height(app):
    resp = app.query(path="state/height")
    assert resp.key == b"height"
    assert resp.value == b"0"


def test_query_wallet_balance(ledger, app):
    ledger.credit_wallet_q_atoms(wallet_id="w1", amount_q_atoms=500)
    resp = app.query(path="wallet/balance/w1")
    assert resp.key == b"wallet:w1:balance"
    assert resp.value == b"500"


def test_query_wallet_sequence(app):
    resp = app.query(path="wallet/sequence/w1")
    assert resp.key == b"wallet:w1:sequence"
    assert resp.value == b"1"  # default next sequence


def test_query_mempool_size(app):
    resp = app.query(path="mempool/size")
    assert resp.key == b"mempool_size"
    assert resp.value == b"0"


def test_query_unknown_path(app):
    resp = app.query(path="nonexistent/path")
    assert resp.key == b"unknown_path"
    assert resp.value == b""
