#!/usr/bin/env python3
"""Create a public protocol-authority policy and external Ed25519 signer keys.

The private seeds are written only to the operator-selected key directory.
The public policy is the only artifact intended for validator deployment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.epoch_transition import (  # noqa: E402
    restrict_private_key_file,
)
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy  # noqa: E402

_AUTHORITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--authority-id",
        action="append",
        dest="authority_ids",
        help="authority identifier to generate locally; repeat once per signer",
    )
    parser.add_argument(
        "--authority",
        action="append",
        dest="authority_specs",
        metavar="AUTHORITY_ID=PUBLIC_KEY",
        help="public-only authority entry; repeat once per external signer",
    )
    parser.add_argument("--threshold", required=True, type=int)
    parser.add_argument(
        "--key-dir",
        type=Path,
        help="directory outside the repository for private seed files",
    )
    parser.add_argument("--output", required=True, type=Path, help="public policy JSON")
    parser.add_argument(
        "--force",
        action="store_true",
        help="allow replacing the public policy only; existing private keys are never replaced",
    )
    return parser


def _public_key(key: Ed25519PrivateKey) -> str:
    return "ed25519:" + key.public_key().public_bytes_raw().hex()


def _validate_ids(values: list[str]) -> list[str]:
    if not values:
        raise ValueError("at least one authority ID is required")
    if len(set(values)) != len(values):
        raise ValueError("authority IDs must be unique")
    invalid = [value for value in values if _AUTHORITY_ID.fullmatch(value) is None]
    if invalid:
        raise ValueError(f"authority ID is invalid: {invalid[0]}")
    return sorted(values)


def _public_authorities(values: list[str]) -> tuple[tuple[str, str], ...]:
    if not values:
        raise ValueError("at least one --authority or --authority-id is required")
    result: dict[str, str] = {}
    for value in values:
        authority_id, separator, public_key = value.partition("=")
        if not separator or _AUTHORITY_ID.fullmatch(authority_id) is None or not public_key:
            raise ValueError("--authority must use AUTHORITY_ID=PUBLIC_KEY")
        if authority_id in result:
            raise ValueError(f"authority ID is duplicated: {authority_id}")
        result[authority_id] = public_key
    return tuple(sorted(result.items()))


def _write_new_seed(path: Path, key: Ed25519PrivateKey) -> None:
    if path.exists():
        raise ValueError(f"refusing to replace existing private key: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(key.private_bytes_raw().hex() + "\n", encoding="ascii")
    restrict_private_key_file(temporary)
    os.replace(temporary, path)
    restrict_private_key_file(path)


def main() -> int:
    args = _parser().parse_args()
    if args.authority_ids and args.authority_specs:
        raise ValueError("use either --authority-id or --authority, not both")
    if not args.authority_ids and not args.authority_specs:
        raise ValueError("at least one --authority or --authority-id is required")
    if args.output.exists() and not args.force:
        raise ValueError(f"refusing to replace existing policy: {args.output}")

    if args.authority_specs:
        authorities = _public_authorities(args.authority_specs)
        private_key_directory = None
        private_keys_written = 0
    else:
        authority_ids = _validate_ids(args.authority_ids)
        if args.key_dir is None:
            raise ValueError("--key-dir is required when using --authority-id")
        key_dir = args.key_dir.resolve()
        if key_dir == ROOT or ROOT in key_dir.parents:
            raise ValueError("private key directory must be outside the repository")
        keys: dict[str, Ed25519PrivateKey] = {}
        for authority_id in authority_ids:
            key = Ed25519PrivateKey.generate()
            _write_new_seed(key_dir / f"{authority_id}.seed", key)
            keys[authority_id] = key
        authorities = tuple(
            (authority_id, _public_key(keys[authority_id]))
            for authority_id in authority_ids
        )
        private_key_directory = str(key_dir)
        private_keys_written = len(keys)

    if args.threshold < 1 or args.threshold > len(authorities):
        raise ValueError("threshold must be between one and the authority count")
    policy = ProtocolAuthorityPolicy(threshold=args.threshold, authorities=authorities)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(policy.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "CREATED",
                "policy_hash": policy.policy_hash,
                "threshold": policy.threshold,
                "authority_ids": [authority_id for authority_id, _ in authorities],
                "public_policy": str(args.output),
                "private_key_directory": private_key_directory,
                "private_keys_written": private_keys_written,
                "broadcast": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        raise SystemExit(2) from error
