#!/usr/bin/env python3
"""Create a creator recovery wallet for an external Faucet Treasury.

The private key is intentionally generated on the creator-controlled host and
is not a Faucet deployment secret.  Only the public identity JSON may be
copied into the Faucet bootstrap workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "aidn-faucet" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from aidn_faucet.models import wallet_id_for_public_key  # noqa: E402
from aidn_faucet.policy_registry import public_key_for_private_key  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--label", default="AiDN Faucet Creator Recovery")
    parser.add_argument("--force", action="store_true", help="allow a previously empty output directory")
    return parser


def _write_secret(path: Path, value: str) -> None:
    path.write_text(value + "\n", encoding="ascii")
    if os.name != "nt":
        path.chmod(0o600)


def main() -> int:
    args = _parser().parse_args()
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()) and not args.force:
        raise ValueError("output directory is not empty; refuse to replace a creator key")
    output_dir.mkdir(parents=True, exist_ok=True)
    key_path = output_dir / "creator-recovery.key"
    public_path = output_dir / "creator-recovery-wallet.json"
    if (key_path.exists() or public_path.exists()) and not args.force:
        raise ValueError("creator recovery files already exist")
    private_key = Ed25519PrivateKey.generate()
    public_key = public_key_for_private_key(private_key)
    identity = {
        "schema_version": "aidn.creator-recovery-wallet.v1",
        "wallet_id": wallet_id_for_public_key(public_key),
        "public_key": public_key,
        "label": args.label,
        "created_at": datetime.now(UTC).isoformat(),
    }
    _write_secret(
        key_path,
        private_key.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        ).hex(),
    )
    public_path.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"wallet_id": identity["wallet_id"], "public_identity": str(public_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
