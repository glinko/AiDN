from __future__ import annotations

import importlib.util
from pathlib import Path

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
