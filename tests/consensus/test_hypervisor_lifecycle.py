from __future__ import annotations

import hashlib

import pytest
from fastapi.testclient import TestClient

from aidn_hypervisor.consensus.state_store import ABCIStateStoreError
from aidn_hypervisor.main import build_app


def _configure_validator(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(tmp_path / "hypervisor.json"))
    monkeypatch.setenv("AIDN_CONSENSUS_MODE", "validator")
    monkeypatch.setenv("AIDN_COMETBFT_ABCI_STATE_PATH", str(tmp_path / "abci"))
    monkeypatch.setenv("AIDN_COMETBFT_ABCI_PORT", "0")


def test_validator_lifecycle_restores_matching_hypervisor_and_abci_state(
    monkeypatch, tmp_path
):
    _configure_validator(monkeypatch, tmp_path)

    first_app = build_app()
    first_consensus = first_app.state.consensus_service
    assert first_consensus is not None
    assert first_consensus.abci is not None
    assert first_consensus.abci.ledger is first_app.state.hypervisor_service.ledger_operation_service

    with TestClient(first_app):
        assert first_consensus._abci_socket_server.is_running
        result, _ = first_consensus.abci.finalize_block_with_results(
            block_height=1,
            block_hash=hashlib.sha256(b"first block").digest(),
            txs=[],
        )
        assert result.code == "ok"
        first_consensus.abci.commit()
    assert not first_consensus._abci_socket_server

    restored_app = build_app()
    restored_consensus = restored_app.state.consensus_service
    assert restored_consensus is not None
    assert restored_consensus.abci is not None
    assert restored_consensus.abci.info().last_block_height == 1
    assert (
        restored_consensus.abci.ledger
        is restored_app.state.hypervisor_service.ledger_operation_service
    )


def test_validator_lifecycle_fails_closed_when_abci_ledger_differs(monkeypatch, tmp_path):
    _configure_validator(monkeypatch, tmp_path)

    app = build_app()
    consensus = app.state.consensus_service
    assert consensus is not None
    assert consensus.abci is not None
    result, _ = consensus.abci.finalize_block_with_results(
        block_height=1,
        block_hash=hashlib.sha256(b"empty block").digest(),
        txs=[],
    )
    assert result.code == "ok"
    consensus.abci.commit()

    hypervisor = app.state.hypervisor_service
    hypervisor.ledger_operation_service.credit_wallet_q_atoms(
        wallet_id="wallet-mismatch",
        amount_q_atoms=5,
    )
    hypervisor._persist_state()

    with pytest.raises(ABCIStateStoreError, match="does not match the restored Hypervisor Ledger"):
        build_app()


def test_validator_lifecycle_retains_local_runtime_evidence_after_restart(
    monkeypatch, tmp_path
):
    _configure_validator(monkeypatch, tmp_path)

    app = build_app()
    consensus = app.state.consensus_service
    assert consensus is not None
    assert consensus.abci is not None
    assert consensus.abci.finalize_block(
        block_height=1,
        block_hash=hashlib.sha256(b"runtime-evidence-block").digest(),
        txs=[],
    ).code == "ok"

    evidence = app.state.hypervisor_service.ledger_operation_service.record_operation(
        operation_type="SESSION_RUNTIME_EVIDENCE_COMMIT",
        origin_type="multi_party",
        fee_class="session",
        initiator_id="session-local",
        payload={"request_id": "request-local"},
    )
    app.state.hypervisor_service._persist_state()

    restored = build_app()
    restored_consensus = restored.state.consensus_service
    assert restored_consensus is not None
    assert restored_consensus.abci is not None
    assert restored_consensus.abci.info().last_block_height == 1
    assert evidence in restored.state.hypervisor_service.ledger_operation_service.snapshot_operations()


def test_validator_mode_requires_both_durable_state_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("AIDN_CONSENSUS_MODE", "validator")
    monkeypatch.setenv("AIDN_COMETBFT_ABCI_STATE_PATH", str(tmp_path / "abci"))
    with pytest.raises(ValueError, match="AIDN_HYPERVISOR_STATE_PATH"):
        build_app()

    monkeypatch.setenv("AIDN_HYPERVISOR_STATE_PATH", str(tmp_path / "hypervisor.json"))
    monkeypatch.delenv("AIDN_COMETBFT_ABCI_STATE_PATH")
    with pytest.raises(ValueError, match="AIDN_COMETBFT_ABCI_STATE_PATH"):
        build_app()
