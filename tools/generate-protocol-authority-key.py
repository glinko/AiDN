#!/usr/bin/env python3
"""Generate one protocol-authority seed for an independent signer."""

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

_AUTHORITY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if _AUTHORITY_ID.fullmatch(args.authority_id) is None:
        raise ValueError("authority ID is invalid")
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("private key file must be outside the repository")
    if output.exists():
        raise ValueError(f"refusing to replace existing private key: {output}")
    key = Ed25519PrivateKey.generate()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temporary.write_text(key.private_bytes_raw().hex() + "\n", encoding="ascii")
    restrict_private_key_file(temporary)
    os.replace(temporary, output)
    restrict_private_key_file(output)
    print(
        json.dumps(
            {
                "status": "CREATED",
                "authority_id": args.authority_id,
                "private_key_file": str(output),
                "public_key": "ed25519:" + key.public_key().public_bytes_raw().hex(),
                "private_key_exported": False,
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
