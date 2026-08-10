from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from aidn_hypervisor.faucet_treasury import (
    FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
    FaucetTreasuryActivationProof,
    FaucetTreasuryManifest,
    validate_faucet_treasury_manifest,
)


def _manifest_kwargs() -> dict[str, str | int]:
    public_key = "ed25519:" + ("ab" * 32)
    return {
        "treasury_id": "faucet-treasury-main-v1",
        "network_id": "aidn-localnet-1",
        "chain_id": "aidn-testnet-1",
        "wallet_id": "wallet-" + hashlib.sha256(public_key.encode()).hexdigest()[:12],
        "wallet_public_key": public_key,
        "creator_recovery_wallet": "wallet-creator-recovery",
        "genesis_allocation_q_atoms": FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
        "policy_registry_hash": "sha256:" + ("cd" * 32),
    }


def test_manifest_is_hash_bound_and_projects_one_genesis_account() -> None:
    manifest = FaucetTreasuryManifest(**_manifest_kwargs())

    assert manifest.manifest_hash == manifest.expected_manifest_hash()
    assert manifest.genesis_accounts() == {manifest.wallet_id: 10_000_000_000_000}
    assert "private_key" not in manifest.model_dump(mode="json")


def test_manifest_rejects_wrong_network_and_allocation() -> None:
    manifest = FaucetTreasuryManifest(**_manifest_kwargs())

    with pytest.raises(ValueError, match="network_id"):
        validate_faucet_treasury_manifest(manifest, expected_network_id="other-network")
    with pytest.raises(ValidationError, match="exactly 10,000,000 Q"):
        FaucetTreasuryManifest(**{**_manifest_kwargs(), "genesis_allocation_q_atoms": 1})


def test_manifest_rejects_private_material_and_hash_tampering() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        FaucetTreasuryManifest(**{**_manifest_kwargs(), "private_key": "secret"})

    manifest = FaucetTreasuryManifest(**_manifest_kwargs())
    with pytest.raises(ValidationError, match="manifest_hash"):
        FaucetTreasuryManifest(**{**manifest.model_dump(mode="json"), "manifest_hash": "sha256:" + ("00" * 32)})


def test_activation_proof_binds_consensus_funding_and_rejects_tampering() -> None:
    values = _manifest_kwargs()
    values.update(
        {
            "funding_mode": "CONSENSUS",
            "funding_id": "treasury-fund-request-1",
            "funding_operation_id": "a" * 64,
        }
    )
    manifest = FaucetTreasuryManifest(**values)
    proof = FaucetTreasuryActivationProof(
        state="ACTIVE",
        treasury_id=manifest.treasury_id,
        network_id=manifest.network_id,
        chain_id=manifest.chain_id,
        wallet_id=manifest.wallet_id,
        manifest_hash=manifest.manifest_hash,
        funding_mode="CONSENSUS",
        funding_id=manifest.funding_id,
        funding_operation_id=manifest.funding_operation_id,
        funded_amount_q_atoms=FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
        observed_balance_q_atoms=FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
        evidence_type="CONSENSUS_FUNDING",
        canonical_evidence={
            "operation_id": manifest.funding_operation_id,
            "operation_type": "TREASURY_FUND",
            "funding_id": manifest.funding_id,
            "chain_id": manifest.chain_id,
            "manifest_hash": manifest.manifest_hash,
        },
        quorum=2,
        source_count=3,
    )

    assert proof.proof_hash == proof.expected_proof_hash()
    with pytest.raises(ValidationError, match="proof_hash"):
        FaucetTreasuryActivationProof(
            **{**proof.model_dump(mode="json"), "observed_balance_q_atoms": 1}
        )


def test_manifest_cli_create_and_verify(tmp_path: Path) -> None:
    manifest_path = tmp_path / "faucet-treasury.json"
    create = subprocess.run(
        [
            sys.executable,
            "tools/create-faucet-treasury-genesis.py",
            "create",
            "--output",
            str(manifest_path),
            "--treasury-id",
            "faucet-treasury-main-v1",
            "--network-id",
            "aidn-localnet-1",
            "--chain-id",
            "aidn-testnet-1",
            "--wallet-id",
            _manifest_kwargs()["wallet_id"],
            "--wallet-public-key",
            _manifest_kwargs()["wallet_public_key"],
            "--creator-recovery-wallet",
            "wallet-creator-recovery",
            "--policy-registry-hash",
            "sha256:" + ("cd" * 32),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert raw["manifest_hash"] in create.stdout

    verify = subprocess.run(
        [
            sys.executable,
            "tools/create-faucet-treasury-genesis.py",
            "verify",
            "--manifest",
            str(manifest_path),
            "--network-id",
            "aidn-localnet-1",
            "--chain-id",
            "aidn-testnet-1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert '"status": "ok"' in verify.stdout


def test_finalized_operation_id_does_not_change_manifest_hash() -> None:
    pre_funding = FaucetTreasuryManifest(
        **{
            **_manifest_kwargs(),
            "funding_mode": "CONSENSUS",
            "funding_id": "treasury-fund-request-1",
        }
    )
    finalized = FaucetTreasuryManifest(
        **{
            **pre_funding.model_dump(mode="json"),
            "funding_operation_id": "b" * 64,
        }
    )

    assert finalized.manifest_hash == pre_funding.manifest_hash
