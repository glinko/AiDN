from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.validator_schedule import compute_validator_set_hash
from aidn_hypervisor.ledger.service import LedgerOperationService

PUBLIC_KEY = "ed25519:" + base64.b64encode(bytes(range(32))).decode("ascii")


def _envelope(operation_type: str, payload: dict, *, sender_wallet: str | None = None) -> bytes:
    value = {
        "operation_type": operation_type,
        "operation_version": "1.0.0",
        "protocol_version": "0.1",
        "origin_type": "protocol" if sender_wallet is None else "wallet",
        "initiator_id": "epoch-engine",
        "sender_wallet": sender_wallet,
        "sender_sequence": 1 if sender_wallet is not None else None,
        "fee_payer": None,
        "fee_class": "protocol_sponsored",
        "created_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
        "target_epoch": "8",
        "payload": payload,
        "evidence_references": ["sha256:eligibility"],
        "signatures": ["ed25519:epoch-engine"],
    }
    return json.dumps(value).encode()


def _payload() -> dict:
    additions = [
        {
            "node_id": "node-2",
            "operator_id": "operator-2",
            "consensus_address": "sha256:node-2",
            "consensus_public_key": PUBLIC_KEY,
            "stake": 500_000_000_000,
            "voting_power": 1,
        }
    ]
    return {
        "activation_epoch": 8,
        "validator_additions": additions,
        "validator_removals": [],
        "voting_power_updates": [],
        "validator_set_hash": compute_validator_set_hash(additions),
        "eligibility_evidence_root": "sha256:eligibility-root-8",
    }


def test_abci_commits_validator_set_schedule_without_wallet_effect() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_envelope("CONSENSUS_VALIDATOR_SET_UPDATE", _payload())],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "ok"
    assert ledger.wallet_q_atom_balance("wallet:epoch-engine") == 0
    assert ledger.snapshot_operations()[0]["operation_type"] == (
        "CONSENSUS_VALIDATOR_SET_UPDATE"
    )


def test_execution_rejects_validator_set_update_with_overlapping_membership() -> None:
    ledger = LedgerOperationService()
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )
    payload = _payload()
    payload["validator_removals"] = [{"node_id": "node-2"}]

    result = engine.execute_block(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_envelope("CONSENSUS_VALIDATOR_SET_UPDATE", payload)],
    )

    assert result.operations_executed == 0
    assert result.operations_rejected == 1
    assert "overlap" in (result.execution_events[0].error or "")
    assert ledger.snapshot_operations() == []


def test_validator_set_update_rejects_wallet_origin_and_conflicting_epoch() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )
    wallet_tx = _envelope(
        "CONSENSUS_VALIDATOR_SET_UPDATE",
        _payload(),
        sender_wallet="wallet:operator",
    )
    first = _envelope("CONSENSUS_VALIDATOR_SET_UPDATE", _payload())
    conflict_payload = {**_payload(), "validator_set_hash": "sha256:other-set"}
    conflict = _envelope("CONSENSUS_VALIDATOR_SET_UPDATE", conflict_payload)

    wallet_result = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[wallet_tx],
    )
    first_result = app.finalize_block(
        block_height=2,
        block_hash=b"B" * 32,
        txs=[first],
    )
    conflict_result, conflict_txs = app.finalize_block_with_results(
        block_height=3,
        block_hash=b"C" * 32,
        txs=[conflict],
    )

    assert wallet_result[1][0].code == "rejected"
    assert "protocol origin" in wallet_result[1][0].log
    assert first_result.code == "ok"
    assert conflict_result.code == "ok"
    assert conflict_txs[0].code == "rejected"
    assert "already committed" in conflict_txs[0].log
    assert len(ledger.snapshot_operations()) == 1


def test_validator_set_update_rejects_final_set_hash_mismatch() -> None:
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(
            current_time=datetime.now(UTC).isoformat()
        ),
    )
    payload = _payload()
    payload["validator_removals"] = []
    payload["voting_power_updates"] = []
    payload["validator_set_hash"] = "sha256:not-the-final-set"

    result, tx_results = app.finalize_block_with_results(
        block_height=1,
        block_hash=b"A" * 32,
        txs=[_envelope("CONSENSUS_VALIDATOR_SET_UPDATE", payload)],
    )

    assert result.code == "ok"
    assert tx_results[0].code == "rejected"
    assert "hash" in tx_results[0].log
    assert ledger.snapshot_operations() == []
