"""Consensus funding tests for the external Faucet Treasury."""

from __future__ import annotations

import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.admission import AdmissionValidator
from aidn_hypervisor.consensus.execution import ExecutionEngine
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.state_store import ABCIStateStore
from aidn_hypervisor.faucet_treasury import (
    FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
    FaucetTreasuryManifest,
    faucet_treasury_funding_authorization_bytes,
    faucet_treasury_manifest_binding_authorization_bytes,
    wallet_id_for_public_key,
)
from aidn_hypervisor.ledger.service import LedgerOperationService


def _public_key(private_key: Ed25519PrivateKey) -> str:
    return "ed25519:" + private_key.public_key().public_bytes_raw().hex()


def _manifest(
    *,
    treasury_key: Ed25519PrivateKey,
    creator_key: Ed25519PrivateKey,
    funding_id: str = "faucet-funding:testnet:v1",
) -> FaucetTreasuryManifest:
    treasury_public_key = _public_key(treasury_key)
    creator_public_key = _public_key(creator_key)
    return FaucetTreasuryManifest(
        treasury_id="faucet-treasury-test-v1",
        network_id="aidn-localnet-1",
        chain_id="aidn-testnet-1",
        wallet_id=wallet_id_for_public_key(treasury_public_key),
        wallet_public_key=treasury_public_key,
        creator_recovery_wallet=wallet_id_for_public_key(creator_public_key),
        genesis_allocation_q_atoms=FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
        funding_mode="CONSENSUS",
        funding_id=funding_id,
        policy_registry_hash="sha256:" + ("cd" * 32),
    )


def _funding_envelope(
    manifest: FaucetTreasuryManifest,
    *,
    creator_key: Ed25519PrivateKey,
    created_at: str = "2030-01-01T00:00:00Z",
    amount: int = FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
    creator_public_key: str | None = None,
) -> LedgerOperationEnvelope:
    creator_public_key = creator_public_key or _public_key(creator_key)
    payload = {
        "funding_id": manifest.funding_id,
        "treasury_id": manifest.treasury_id,
        "network_id": manifest.network_id,
        "chain_id": manifest.chain_id,
        "treasury_wallet_id": manifest.wallet_id,
        "treasury_public_key": manifest.wallet_public_key,
        "creator_recovery_wallet": manifest.creator_recovery_wallet,
        "creator_recovery_public_key": creator_public_key,
        "amount": amount,
        "treasury_manifest_hash": manifest.manifest_hash,
        "funding_mode": "CONSENSUS",
        "authorization_reference": "governance:testnet-faucet-funding",
    }
    payload["authorization_signature"] = "ed25519:" + creator_key.sign(
        faucet_treasury_funding_authorization_bytes(payload)
    ).hex()
    unsigned = LedgerOperationEnvelope(
        operation_type="TREASURY_FUND",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="protocol",
        initiator_id="faucet-treasury-funding",
        fee_class="protocol_sponsored",
        created_at=created_at,
        payload=payload,
    )
    return unsigned.model_copy(
        update={
            "signatures": ["ed25519:" + creator_key.sign(unsigned.signing_bytes()).hex()],
        }
    )


def _manifest_bind_envelope(
    manifest: FaucetTreasuryManifest,
    *,
    creator_key: Ed25519PrivateKey,
    created_at: str = "2030-01-01T00:00:00Z",
) -> LedgerOperationEnvelope:
    creator_public_key = _public_key(creator_key)
    payload = {
        "treasury_manifest": manifest.model_dump(mode="json"),
        "creator_recovery_public_key": creator_public_key,
        "authorization_reference": "governance:testnet-faucet-manifest-bind",
    }
    payload["authorization_signature"] = "ed25519:" + creator_key.sign(
        faucet_treasury_manifest_binding_authorization_bytes(payload)
    ).hex()
    unsigned = LedgerOperationEnvelope(
        operation_type="TREASURY_MANIFEST_BIND",
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="protocol",
        initiator_id="faucet-treasury-manifest-bind",
        fee_class="protocol_sponsored",
        created_at=created_at,
        payload=payload,
    )
    return unsigned.model_copy(
        update={"signatures": ["ed25519:" + creator_key.sign(unsigned.signing_bytes()).hex()]}
    )


def _tx(envelope: LedgerOperationEnvelope) -> bytes:
    return json.dumps(envelope.model_dump(mode="json")).encode("utf-8")


def test_abci_consensus_funds_treasury_once_and_restores_snapshot(tmp_path) -> None:
    treasury_key = Ed25519PrivateKey.generate()
    creator_key = Ed25519PrivateKey.generate()
    manifest = _manifest(treasury_key=treasury_key, creator_key=creator_key)
    store = ABCIStateStore(tmp_path / "abci")
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        genesis_treasury_manifest=manifest,
        state_store=store,
        strict_operation_coverage=True,
        admission_validator=AdmissionValidator(current_time="2029-01-01T00:00:00Z"),
    )
    transaction = _tx(_funding_envelope(manifest, creator_key=creator_key))

    assert app.check_transaction(transaction).code == "ok"
    assert app.finalize_block(block_height=1, block_hash=b"f" * 32, txs=[transaction]).code == "ok"
    assert ledger.wallet_q_atom_balance(manifest.wallet_id) == FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS
    assert len(ledger.snapshot_operations()) == 1

    restored_ledger = LedgerOperationService()
    restored = AIDNABCIApplication(
        ledger_service=restored_ledger,
        genesis_treasury_manifest=manifest,
        state_store=store,
        strict_operation_coverage=True,
    )
    assert restored_ledger.wallet_q_atom_balance(manifest.wallet_id) == (
        FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS
    )
    assert len(restored.ledger.snapshot_operations()) == 1


def test_abci_binds_manifest_before_consensus_funding_and_restores_it(tmp_path) -> None:
    treasury_key = Ed25519PrivateKey.generate()
    creator_key = Ed25519PrivateKey.generate()
    manifest = _manifest(treasury_key=treasury_key, creator_key=creator_key)
    store = ABCIStateStore(tmp_path / "abci")
    ledger = LedgerOperationService()
    app = AIDNABCIApplication(
        ledger_service=ledger,
        state_store=store,
        strict_operation_coverage=True,
        admission_validator=AdmissionValidator(current_time="2029-01-01T00:00:00Z"),
    )
    bind = _tx(_manifest_bind_envelope(manifest, creator_key=creator_key))
    funding = _tx(_funding_envelope(manifest, creator_key=creator_key))

    assert app.check_transaction(funding).code == "rejected"
    assert app.check_transaction(bind).code == "ok"
    assert app.finalize_block(block_height=1, block_hash=b"b" * 32, txs=[bind]).code == "ok"
    assert ledger.faucet_treasury_manifest()["manifest_hash"] == manifest.manifest_hash
    assert app.query(path="faucet/treasury-manifest").value
    assert app.check_transaction(funding).code == "ok"
    assert app.finalize_block(block_height=2, block_hash=b"c" * 32, txs=[funding]).code == "ok"

    restored = AIDNABCIApplication(
        ledger_service=LedgerOperationService(),
        state_store=store,
        strict_operation_coverage=True,
    )
    assert restored.ledger.faucet_treasury_manifest()["manifest_hash"] == manifest.manifest_hash
    assert restored.ledger.wallet_q_atom_balance(manifest.wallet_id) == (
        FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS
    )


def test_manifest_binding_requires_the_declared_creator_and_is_one_time() -> None:
    treasury_key = Ed25519PrivateKey.generate()
    creator_key = Ed25519PrivateKey.generate()
    manifest = _manifest(treasury_key=treasury_key, creator_key=creator_key)
    ledger = LedgerOperationService()
    wrong = _manifest_bind_envelope(manifest, creator_key=Ed25519PrivateKey.generate())
    with pytest.raises(ValueError, match="does not match recovery Wallet"):
        ledger.validate_consensus_treasury_manifest_bind(wrong)

    envelope = _manifest_bind_envelope(manifest, creator_key=creator_key)
    ledger.apply_consensus_treasury_manifest_bind(envelope)
    with pytest.raises(ValueError, match="already bound"):
        ledger.validate_consensus_treasury_manifest_bind(envelope)


def test_treasury_funding_rejects_replay_conflict_and_wrong_signature() -> None:
    treasury_key = Ed25519PrivateKey.generate()
    creator_key = Ed25519PrivateKey.generate()
    manifest = _manifest(treasury_key=treasury_key, creator_key=creator_key)
    ledger = LedgerOperationService()
    ledger.bind_faucet_treasury_manifest(manifest)
    envelope = _funding_envelope(manifest, creator_key=creator_key)
    ledger.apply_consensus_treasury_fund(envelope)

    with pytest.raises(ValueError, match="already committed"):
        ledger.validate_consensus_treasury_fund(envelope)

    conflicting = _funding_envelope(manifest, creator_key=creator_key, created_at="2030-01-02T00:00:00Z")
    with pytest.raises(ValueError, match="already committed|conflicting"):
        ledger.validate_consensus_treasury_fund(conflicting)

    wrong_creator = Ed25519PrivateKey.generate()
    wrong_signature = _funding_envelope(
        manifest,
        creator_key=wrong_creator,
        creator_public_key=_public_key(creator_key),
    )
    with pytest.raises(ValueError, match="authorization signature verification failed"):
        ledger.validate_consensus_treasury_fund(wrong_signature)


def test_treasury_funding_requires_exact_amount_and_consensus_manifest() -> None:
    treasury_key = Ed25519PrivateKey.generate()
    creator_key = Ed25519PrivateKey.generate()
    manifest = _manifest(treasury_key=treasury_key, creator_key=creator_key)
    ledger = LedgerOperationService()
    ledger.bind_faucet_treasury_manifest(manifest)

    with pytest.raises(ValueError, match="exactly 10,000,000 Q"):
        ledger.validate_consensus_treasury_fund(
            _funding_envelope(manifest, creator_key=creator_key, amount=1)
        )

    genesis_values = manifest.model_dump(mode="json")
    genesis_values.update({"funding_mode": "GENESIS", "funding_id": None, "funding_operation_id": None})
    genesis_values.pop("manifest_hash", None)
    genesis_manifest = FaucetTreasuryManifest(**genesis_values)
    genesis_ledger = LedgerOperationService()
    genesis_ledger.bind_faucet_treasury_manifest(genesis_manifest)
    with pytest.raises(ValueError, match="Genesis-funded Treasury"):
        genesis_ledger.validate_consensus_treasury_fund(
            _funding_envelope(manifest, creator_key=creator_key)
        )


def test_execution_engine_applies_consensus_treasury_funding() -> None:
    treasury_key = Ed25519PrivateKey.generate()
    creator_key = Ed25519PrivateKey.generate()
    manifest = _manifest(treasury_key=treasury_key, creator_key=creator_key)
    ledger = LedgerOperationService()
    ledger.bind_faucet_treasury_manifest(manifest)
    engine = ExecutionEngine(
        ledger_service=ledger,
        admission_validator=AdmissionValidator(current_time="2029-01-01T00:00:00Z"),
        strict_operation_coverage=True,
    )

    result = engine.execute_block(
        block_height=1,
        block_hash=hashlib.sha256(b"treasury").digest(),
        txs=[_tx(_funding_envelope(manifest, creator_key=creator_key))],
    )

    assert result.operations_executed == 1
    assert result.operations_rejected == 0
    assert ledger.wallet_q_atom_balance(manifest.wallet_id) == FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS
