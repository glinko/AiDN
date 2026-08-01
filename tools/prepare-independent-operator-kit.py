#!/usr/bin/env python3
"""Create a secret-free workspace for an independently operated AiDN peer.

The generated files are templates and evidence manifests only. This command
never generates, reads, or exports private keys, certificates, or Wallet
credentials.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)


def _init_workspace(args: argparse.Namespace) -> None:
    root = args.output.resolve()
    if root.exists() and any(root.iterdir()) and not args.force:
        raise ValueError(f"refusing to overwrite non-empty workspace: {root}")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)

    peer_id = args.peer_id
    _write_json(
        root / "registry-replication.json.template",
        {
            "local_peer_id": peer_id,
            "signing_key_handle": f"secret://registry/{peer_id}/ed25519",
            "listener": {
                "host": "0.0.0.0",
                "port": 9443,
                "tls": {
                    "certificate_handle": f"secret://registry/{peer_id}/certificate",
                    "private_key_handle": f"secret://registry/{peer_id}/private-key",
                    "certificate_authority_handle": "secret://registry/ca",
                },
            },
            "outbound_peers": [
                {
                    "peer_id": "REPLACE_WITH_APPROVED_REMOTE_PEER_ID",
                    "host": "REPLACE_WITH_REMOTE_DNS_NAME",
                    "port": 9443,
                    "tls": {
                        "certificate_handle": f"secret://registry/{peer_id}/certificate",
                        "private_key_handle": f"secret://registry/{peer_id}/private-key",
                        "certificate_authority_handle": "secret://registry/ca",
                    },
                }
            ],
            "network_id": args.network_id,
            "chain_id": args.chain_id,
            "network_revision": args.network_revision,
        },
    )
    _write_json(
        root / "external-cometbft-acceptance.json.template",
        {
            "rpc_endpoints": ["https://REPLACE_RPC_A", "https://REPLACE_RPC_B"],
            "chain_id": "REPLACE_CHAIN_ID",
            "verifier_id": peer_id,
            "operation_id": "REPLACE_AIDN_OPERATION_ID",
            "transaction_hash": "REPLACE_64_HEX_TRANSACTION_HASH",
            "trust_period_seconds": 1209600,
            "trusted_checkpoint": {
                "height": 1,
                "block_id": "REPLACE_64_HEX_BLOCK_ID",
                "app_hash": "REPLACE_64_HEX_APP_HASH",
                "header_time": "2026-01-01T00:00:00Z",
                "validator_set_hash": "REPLACE_64_HEX_VALIDATOR_SET_HASH",
                "next_validator_set_hash": "REPLACE_64_HEX_NEXT_VALIDATOR_SET_HASH",
                "validators": [
                    {
                        "address": "REPLACE_40_HEX_VALIDATOR_ADDRESS",
                        "public_key": "ed25519:REPLACE_BASE64_PUBLIC_KEY",
                        "voting_power": 1,
                    }
                ],
            },
        },
    )
    _write_json(
        root / "operator-attestation.template.json",
        {
            "operator_id": peer_id,
            "organization_or_person": "REPLACE_WITH_OPERATOR_DECLARATION",
            "independence_statement": "REPLACE_WITH_SIGNED_OUT_OF_BAND_ATTESTATION_REFERENCE",
            "registry_endpoint": "https://REPLACE_OPERATOR_ENDPOINT",
            "cometbft_rpc_endpoints": ["https://REPLACE_RPC_A", "https://REPLACE_RPC_B"],
            "control_group_disclosures": [],
            "issued_at": "REPLACE_RFC3339_TIMESTAMP",
            "signature_reference": "REPLACE_OUT_OF_BAND_SIGNATURE_REFERENCE",
        },
    )
    _write_text(
        root / ".gitignore",
        "*\n!.gitignore\n!*.template.json\n!README.md\n",
    )
    _write_text(
        root / "README.md",
        "# AiDN Independent Operator Workspace\n\n"
        "This workspace contains no secret material. Copy templates to non-template names, "
        "replace every REPLACE_ value, and keep completed configurations outside version control. "
        "Follow docs/development/independent-operator-onboarding-and-acceptance.md from the release checkout.\n",
    )
    print(json.dumps({"status": "ok", "workspace": str(root), "peer_id": peer_id}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    init = subcommands.add_parser("init", help="create a secret-free operator workspace")
    init.add_argument("--output", required=True, type=Path)
    init.add_argument("--peer-id", required=True)
    init.add_argument("--network-id", default="aidn")
    init.add_argument("--chain-id", default="main")
    init.add_argument("--network-revision", default="1.0")
    init.add_argument("--force", action="store_true")
    init.set_defaults(handler=_init_workspace)
    args = parser.parse_args()
    try:
        args.handler(args)
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
