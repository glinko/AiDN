#!/usr/bin/env python3
"""Validate a signed public multi-validator deployment profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aidn_hypervisor.consensus.public_network import (
    PublicMultiValidatorNetworkProfile,
    inspect_public_multivalidator_profile,
)


def _trusted_signer(value: str) -> tuple[str, str]:
    authority_id, separator, public_key = value.partition("=")
    if not separator or not authority_id.strip() or not public_key.strip():
        raise argparse.ArgumentTypeError("trusted signer must use authority-id=ed25519:<64-hex>")
    return authority_id.strip(), public_key.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument(
        "--trusted-profile-signer",
        action="append",
        type=_trusted_signer,
        default=[],
        help="authority-id=ed25519:<64-hex>; may be repeated",
    )
    parser.add_argument(
        "--allow-unproven-independence",
        action="store_true",
        help="verify cryptographic readiness without approving a public ownership claim",
    )
    parser.add_argument(
        "--write-finality-config",
        type=Path,
        help="write the existing CometBFT finality config only after public acceptance succeeds",
    )
    args = parser.parse_args()
    try:
        profile = PublicMultiValidatorNetworkProfile.model_validate_json(
            args.profile.read_text(encoding="utf-8")
        )
        trusted_signers = dict(args.trusted_profile_signer)
        report = inspect_public_multivalidator_profile(
            profile,
            trusted_profile_signers=trusted_signers,
            require_independence_evidence=not args.allow_unproven_independence,
        )
        print(report.model_dump_json(indent=2))
        if report.valid and args.write_finality_config is not None:
            args.write_finality_config.write_text(
                profile.finality_deployment_config().model_dump_json(indent=2) + "\n",
                encoding="utf-8",
            )
        return 0 if report.valid else 2
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "rejected", "error": str(error)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
