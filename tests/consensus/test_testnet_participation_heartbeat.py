from __future__ import annotations

import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.ledger.service import LedgerOperationService
from aidn_hypervisor.testnet_participation import (
    build_testnet_heartbeat_evidence,
    build_testnet_participation_heartbeat_envelope,
)


def _bound_ledger(private_key: Ed25519PrivateKey) -> LedgerOperationService:
    ledger = LedgerOperationService()
    public_key = "ed25519:" + private_key.public_key().public_bytes_raw().hex()
    ledger.record_operation(
        operation_type="OPERATOR_WALLET_BIND",
        origin_type="protocol",
        fee_class="onboarding_exempt",
        initiator_id="node-1",
        created_at="2030-01-01T00:00:00Z",
        payload={
            "node_id": "node-1",
            "operator_id": "node-1",
            "wallet_id": "wallet-owner",
            "public_key": public_key,
            "bootstrap_mode": "create",
            "wallet_binding_version": "1",
            "created_at": "2030-01-01T00:00:00Z",
        },
    )
    return ledger


def test_consensus_commits_a_bound_signed_participation_heartbeat() -> None:
    key = Ed25519PrivateKey.generate()
    ledger = _bound_ledger(key)
    unsigned = build_testnet_heartbeat_evidence(
        evidence_id="heartbeat-1",
        node_id="node-1",
        network_id="aidn-testnet",
        chain_id="aidn-testnet-1",
        observed_at="2030-01-01T00:00:00Z",
        protocol_version="0.1",
        identity_signature_verified=False,
    )
    heartbeat = unsigned.model_copy(
        update={"identity_signature": "ed25519:" + key.sign(unsigned.signing_bytes()).hex()}
    )
    envelope = build_testnet_participation_heartbeat_envelope(heartbeat)
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2030-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=b"P" * 32,
        txs=[json.dumps(envelope.model_dump(mode="json")).encode("utf-8")],
    )

    assert result.operations_executed == 1
    operation = ledger.snapshot_operations()[-1]
    assert operation["operation_type"] == "TESTNET_PARTICIPATION_HEARTBEAT"
    assert operation["result"]["emitted_events"] == ["TestnetParticipationHeartbeatCommitted"]
