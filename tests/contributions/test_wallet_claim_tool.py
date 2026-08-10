from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from aidn_hypervisor.contributions.models import ContributorWalletClaim
from aidn_hypervisor.contributions.service import contributor_wallet_claim_payload


def test_wallet_claim_tool_creates_a_verifiable_claim(tmp_path: Path) -> None:
    output = tmp_path / ".aidn" / "contributor-wallet.json"
    repository_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "tools/create-contributor-wallet-claim.py",
            "--contributor-id",
            "contributor-alice",
            "--source-platform-account",
            "github:alice",
            "--wallet-address",
            "q1alice",
            "--private-key-hex",
            "01" * 32,
            "--output",
            str(output),
        ],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "created" in result.stdout
    claim = ContributorWalletClaim.model_validate(json.loads(output.read_text(encoding="utf-8")))
    assert claim.claim_hash == claim.expected_claim_hash()
    public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(claim.wallet_public_key.removeprefix("ed25519:")))
    public_key.verify(
        bytes.fromhex(claim.wallet_signature.removeprefix("ed25519:")),
        contributor_wallet_claim_payload(claim),
    )
