#!/usr/bin/env python3
"""Sign an out-of-band G6 independence review for an EVD-0001 bundle."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.evidence import (
    INDEPENDENCE_REVIEW_PATH,
    canonical_json_bytes,
    verify_public_evidence_bundle,
)


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    payload = path.read_bytes()
    if payload.startswith(b"-----BEGIN"):
        key = serialization.load_pem_private_key(payload, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("reviewer key PEM is not an Ed25519 private key")
        return key
    if len(payload) != 32:
        raise ValueError("raw Ed25519 reviewer key must contain exactly 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(payload)


def sign_review(
    *,
    evidence_dir: Path,
    reviewer_id: str,
    operator_id: str,
    control_group_id: str,
    review_basis: str,
    private_key_path: Path,
) -> dict[str, str]:
    if not review_basis.strip():
        raise ValueError("review basis must not be empty")
    verified = verify_public_evidence_bundle(evidence_dir, require_attestation=True)
    output = evidence_dir / Path(*INDEPENDENCE_REVIEW_PATH.split("/"))
    if output.exists():
        raise ValueError(f"refusing to overwrite existing independence review: {output}")
    private_key = _load_private_key(private_key_path.expanduser().resolve())
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    payload = {
        "review_version": 1,
        "reviewer_id": reviewer_id,
        "reviewer_public_key": "ed25519:" + public_key.hex(),
        "review_status": "VERIFIED",
        "review_basis": review_basis,
        "reviewed_operator_id": operator_id,
        "reviewed_control_group_id": control_group_id,
        "reviewed_evidence_root": verified.evidence_root,
        "reviewed_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    review = {
        **payload,
        "signature": "ed25519:" + private_key.sign(canonical_json_bytes(payload)).hex(),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(review, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return {
        "status": "ok",
        "reviewer_id": reviewer_id,
        "operator_id": operator_id,
        "evidence_root": verified.evidence_root,
        "review_path": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--control-group-id", required=True)
    parser.add_argument("--review-basis", required=True)
    parser.add_argument("--private-key", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = sign_review(
            evidence_dir=args.evidence_dir,
            reviewer_id=args.reviewer_id,
            operator_id=args.operator_id,
            control_group_id=args.control_group_id,
            review_basis=args.review_basis,
            private_key_path=args.private_key,
        )
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
