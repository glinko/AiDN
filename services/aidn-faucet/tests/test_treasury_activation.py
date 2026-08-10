from __future__ import annotations

import base64
import json

from aidn_faucet.cometbft_submitter import (
    CometBftFaucetTransferSubmitter,
    HttpCometBftTreasuryManifestProvider,
)

from aidn_hypervisor.consensus.finality import ConsensusFinalityEvidence
from aidn_hypervisor.faucet_treasury import (
    FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
    FaucetTreasuryManifest,
    wallet_id_for_public_key,
)


class _Finality:
    def __init__(self, evidence: ConsensusFinalityEvidence | None) -> None:
        self.evidence = evidence

    def finality_evidence(self, operation_id: str):
        if self.evidence is None or self.evidence.operation_id != operation_id:
            return None
        return self.evidence


class _Transport:
    def __init__(self, response: dict) -> None:
        self.response = response

    def get(self, path: str, *, params: dict[str, str], timeout_seconds: int) -> dict:
        del path, params, timeout_seconds
        return self.response


def _manifest(*, funding_mode: str = "CONSENSUS") -> FaucetTreasuryManifest:
    public_key = "ed25519:" + ("ab" * 32)
    return FaucetTreasuryManifest(
        treasury_id="faucet-treasury-activation-test",
        network_id="aidn-localnet-1",
        chain_id="aidn-testnet-1",
        wallet_id=wallet_id_for_public_key(public_key),
        wallet_public_key=public_key,
        creator_recovery_wallet="wallet-creator-recovery",
        genesis_allocation_q_atoms=FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
        funding_mode=funding_mode,
        funding_operation_id="treasury-fund-operation-1" if funding_mode == "CONSENSUS" else None,
        policy_registry_hash="sha256:" + ("cd" * 32),
    )


def _submitter(manifest: FaucetTreasuryManifest, evidence: ConsensusFinalityEvidence):
    return CometBftFaucetTransferSubmitter(
        treasury_wallet_id=manifest.wallet_id,
        chain_id=manifest.chain_id,
        sequence_provider=lambda wallet_id: 1,
        submission_transport=type("Submission", (), {"broadcast_tx_sync": lambda *args, **kwargs: {}})(),
        finality_source=_Finality(evidence),
        balance_provider=lambda wallet_id: FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
    )


def test_consensus_activation_requires_the_exact_finalized_treasury_fund() -> None:
    manifest = _manifest()
    evidence = ConsensusFinalityEvidence(
        operation_id=manifest.funding_operation_id or "",
        chain_id=manifest.chain_id,
        block_height=12,
        block_id="A" * 64,
        app_hash="B" * 64,
        commit_hash="C" * 64,
        finalized_at="2030-01-01T00:00:00Z",
        verifier_id="test-quorum",
        operation_type="TREASURY_FUND",
    )
    proof = _submitter(manifest, evidence).treasury_activation_proof(manifest)

    assert proof.state == "ACTIVE"
    assert proof.evidence_type == "CONSENSUS_FUNDING"
    assert proof.canonical_evidence["manifest_hash"] == manifest.manifest_hash

    wrong_type = evidence.__class__(**{**evidence.model_dump(), "operation_type": "WALLET_TRANSFER"})
    assert _submitter(manifest, wrong_type).treasury_activation_proof(manifest).state == "UNVERIFIED"


def test_genesis_activation_requires_canonical_manifest_quorum() -> None:
    manifest = _manifest(funding_mode="GENESIS")
    encoded = base64.b64encode(
        json.dumps(manifest.model_dump(mode="json")).encode("utf-8")
    ).decode("ascii")
    response = {"result": {"response": {"code": 0, "value": encoded}}}
    provider = HttpCometBftTreasuryManifestProvider(
        (_Transport(response), _Transport(response)),
        quorum=2,
    )

    assert provider().manifest_hash == manifest.manifest_hash
    assert provider.quorum == 2
    assert provider.source_count == 2
