from __future__ import annotations

from aidn_faucet.policy_registry import public_key_for_private_key
from aidn_faucet.treasury_funding import submit_and_wait_for_treasury_funding
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.faucet_treasury import (
    FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
    FaucetTreasuryManifest,
    faucet_treasury_funding_authorization_bytes,
    wallet_id_for_public_key,
)


class _Transport:
    def __init__(self) -> None:
        self.transaction = b""

    def broadcast_tx_sync(self, tx_data: bytes, *, timeout_seconds: int) -> dict:
        self.transaction = tx_data
        from aidn_hypervisor.consensus.cometbft import cometbft_transaction_hash

        return {"result": {"code": 0, "hash": cometbft_transaction_hash(tx_data)}}


class _Finality:
    def __init__(self, operation_id: str) -> None:
        self.operation_id = operation_id

    def finality_evidence(self, operation_id: str):
        if operation_id != self.operation_id:
            return None
        return ConsensusFinalityEvidence(
            operation_id=operation_id,
            chain_id="chain-test",
            block_height=7,
            block_id="AB" * 32,
            app_hash="",
            commit_hash="CD" * 32,
            finalized_at="2030-01-01T00:00:00Z",
            verifier_id="test-finality",
            operation_type="TREASURY_FUND",
        )


def test_treasury_funding_submits_exact_signed_envelope_and_requires_finality() -> None:
    treasury_key = Ed25519PrivateKey.generate()
    creator_key = Ed25519PrivateKey.generate()
    treasury_public_key = public_key_for_private_key(treasury_key)
    creator_public_key = public_key_for_private_key(creator_key)
    manifest = FaucetTreasuryManifest(
        treasury_id="faucet-treasury-test-v1",
        network_id="aidn-localnet-1",
        chain_id="chain-test",
        wallet_id=wallet_id_for_public_key(treasury_public_key),
        wallet_public_key=treasury_public_key,
        creator_recovery_wallet=wallet_id_for_public_key(creator_public_key),
        genesis_allocation_q_atoms=FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
        funding_mode="CONSENSUS",
        funding_id="faucet-funding:testnet:v1",
        policy_registry_hash="sha256:" + ("ab" * 32),
    )
    payload = {
        "funding_id": manifest.funding_id,
        "treasury_id": manifest.treasury_id,
        "network_id": manifest.network_id,
        "chain_id": manifest.chain_id,
        "treasury_wallet_id": manifest.wallet_id,
        "treasury_public_key": manifest.wallet_public_key,
        "creator_recovery_wallet": manifest.creator_recovery_wallet,
        "creator_recovery_public_key": creator_public_key,
        "amount": FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
        "treasury_manifest_hash": manifest.manifest_hash,
        "funding_mode": "CONSENSUS",
        "authorization_reference": "test-funding",
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
        created_at="2030-01-01T00:00:00Z",
        payload=payload,
    )
    envelope = unsigned.model_copy(
        update={"signatures": ["ed25519:" + creator_key.sign(unsigned.signing_bytes()).hex()]}
    )
    transport = _Transport()

    transaction_hash, evidence = submit_and_wait_for_treasury_funding(
        manifest=manifest,
        envelope=envelope,
        transport=transport,
        finality_source=_Finality(envelope.operation_id),
        sleep=lambda _: None,
    )

    assert transaction_hash
    assert transport.transaction
    assert evidence.operation_id == envelope.operation_id
