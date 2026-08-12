from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


def _module():
    path = Path(__file__).parents[1] / "tools" / "run_faucet_live_acceptance.py"
    spec = importlib.util.spec_from_file_location("run_faucet_live_acceptance", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ephemeral_wallet_proof_uses_the_normal_faucet_domain() -> None:
    acceptance = _module()
    key = Ed25519PrivateKey.generate()
    public_key = acceptance.wallet_public_key(key)
    wallet_id = acceptance.wallet_id_for_public_key(public_key)
    challenge = {
        "challenge_id": "faucet-challenge-test",
        "wallet_id": wallet_id,
        "challenge": "challenge-value",
    }

    signature = key.sign(acceptance.challenge_signing_bytes(challenge))
    Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key.removeprefix("ed25519:"))).verify(
        signature,
        acceptance.challenge_signing_bytes(challenge),
    )


def test_report_redaction_never_includes_wallet_proof_or_envelope() -> None:
    acceptance = _module()
    response = {
        "request_id": "request-1",
        "operation_id": "operation-1",
        "status": "APPROVED",
        "wallet_signature": "secret-proof",
        "envelope": {"signatures": ["secret-envelope"]},
    }

    assert acceptance._redacted_claim(response) == {
        "request_id": "request-1",
        "claim_id": None,
        "status": "APPROVED",
        "amount_q_atoms": None,
        "operation_id": "operation-1",
        "transaction_hash": None,
        "policy_id": None,
        "policy_version": None,
        "detail": None,
    }


def test_external_finality_verification_requires_exact_wallet_transfer_proof(tmp_path: Path) -> None:
    acceptance = _module()
    config_path = tmp_path / "cometbft-finality.json"
    config_path.write_text('{"chain_id":"aidn-testnet-1"}\n', encoding="utf-8")
    runtime_config = object()
    deployment = SimpleNamespace(
        chain_id="aidn-testnet-1",
        rpc_endpoints=["https://validator-a.example", "https://validator-b.example"],
        minimum_agreement=2,
        runtime_config=lambda: runtime_config,
    )
    evidence = SimpleNamespace(
        operation_id="operation-1",
        operation_type="WALLET_TRANSFER",
        chain_id="aidn-testnet-1",
        model_dump=lambda: {
            "operation_id": "operation-1",
            "operation_type": "WALLET_TRANSFER",
            "chain_id": "aidn-testnet-1",
        },
    )

    class FinalitySource:
        def finality_evidence(self, operation_id: str):
            assert operation_id == "operation-1"
            return evidence

    captured: dict[str, object] = {}

    def build_source(*, config, transaction_hash_for_operation):
        captured["config"] = config
        assert transaction_hash_for_operation("operation-1") == "A" * 64
        assert transaction_hash_for_operation("other") is None
        return FinalitySource()

    acceptance.load_cometbft_finality_deployment_config = lambda path: deployment
    acceptance.build_cometbft_multi_rpc_finality_source = build_source

    report = acceptance._verify_external_finality(
        finality_config=config_path,
        operation_id="operation-1",
        transaction_hash="A" * 64,
        timeout_seconds=1,
        finality_timeout_seconds=1,
        poll_interval_seconds=0.01,
    )

    assert captured["config"] is runtime_config
    assert report["status"] == "PASS"
    assert report["chain_id"] == "aidn-testnet-1"
    assert report["operation_id"] == "operation-1"
    assert report["transaction_hash"] == "A" * 64
    assert report["minimum_agreement"] == 2
    assert report["evidence"]["operation_type"] == "WALLET_TRANSFER"


def test_external_finality_verification_rejects_wrong_operation_type(tmp_path: Path) -> None:
    acceptance = _module()
    config_path = tmp_path / "cometbft-finality.json"
    config_path.write_text('{"chain_id":"aidn-testnet-1"}\n', encoding="utf-8")
    runtime_config = object()
    deployment = SimpleNamespace(
        chain_id="aidn-testnet-1",
        rpc_endpoints=["https://validator-a.example", "https://validator-b.example"],
        minimum_agreement=2,
        runtime_config=lambda: runtime_config,
    )

    class FinalitySource:
        def finality_evidence(self, operation_id: str):
            del operation_id
            return SimpleNamespace(
                operation_id="operation-1",
                operation_type="TREASURY_FUND",
                chain_id="aidn-testnet-1",
                model_dump=lambda: {},
            )

    acceptance.load_cometbft_finality_deployment_config = lambda path: deployment
    acceptance.build_cometbft_multi_rpc_finality_source = lambda **kwargs: FinalitySource()

    with pytest.raises(acceptance.AcceptanceError, match="unexpected operation type"):
        acceptance._verify_external_finality(
            finality_config=config_path,
            operation_id="operation-1",
            transaction_hash="A" * 64,
            timeout_seconds=1,
            finality_timeout_seconds=1,
            poll_interval_seconds=0.01,
        )
