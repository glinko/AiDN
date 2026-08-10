#!/usr/bin/env python3
"""Create a creator-authorized TREASURY_FUND consensus envelope."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope  # noqa: E402
from aidn_hypervisor.faucet_treasury import (  # noqa: E402
    FAUCET_TREASURY_INITIAL_ALLOCATION_Q_ATOMS,
    FaucetTreasuryManifest,
    faucet_treasury_funding_authorization_bytes,
    wallet_id_for_public_key,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--creator-private-key", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--authorization-reference", required=True)
    parser.add_argument("--created-at", default=datetime.now(UTC).isoformat())
    return parser


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    raw = path.read_bytes()
    if raw.startswith(b"-----BEGIN"):
        key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("creator private key must be Ed25519")
        return key
    try:
        seed = bytes.fromhex(raw.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError) as error:
        raise ValueError("creator private key must be a PEM key or 32-byte hex seed") from error
    if len(seed) != 32:
        raise ValueError("creator private key hex seed must contain 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(seed)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    args = _parser().parse_args()
    manifest = FaucetTreasuryManifest.model_validate(
        json.loads(args.manifest.read_text(encoding="utf-8"))
    )
    if manifest.funding_mode != "CONSENSUS":
        raise ValueError("TREASURY_FUND requires a CONSENSUS-funded Treasury manifest")
    if not manifest.funding_operation_id:
        raise ValueError("consensus Treasury manifest is missing funding_operation_id")

    creator_key = _load_private_key(args.creator_private_key)
    creator_public_key = "ed25519:" + creator_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()
    if wallet_id_for_public_key(creator_public_key) != manifest.creator_recovery_wallet:
        raise ValueError("creator private key does not control manifest creator_recovery_wallet")

    payload = {
        "funding_id": manifest.funding_operation_id,
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
        "authorization_reference": args.authorization_reference,
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
        created_at=args.created_at,
        payload=payload,
    )
    signed = unsigned.model_copy(
        update={
            "signatures": ["ed25519:" + creator_key.sign(unsigned.signing_bytes()).hex()],
        }
    )
    _write_json(args.output, signed.model_dump(mode="json"))
    print(json.dumps({"operation_id": signed.operation_id, "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
