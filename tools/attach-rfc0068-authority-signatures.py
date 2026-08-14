#!/usr/bin/env python3
"""Attach independent RFC-0068 authority signatures to an intake package.

The tool only transforms a read-only intake JSON. It never reads private keys,
does not verify repository authority keys locally, and does not write the
evidence store or submit a Ledger operation. The RFC-0068 API performs the
authoritative public-key and threshold verification on submission.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from aidn_hypervisor.contributions.models import canonical_hash  # noqa: E402

_SIGNATURE_RE = re.compile(r"^ed25519:[0-9a-f]{128}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--authority-signature", action="append", required=True, metavar="AUTHORITY_ID|SIGNATURE")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def _signatures(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        authority_id, separator, signature = value.partition("|")
        if not separator or not authority_id.strip() or not _SIGNATURE_RE.fullmatch(signature.strip()):
            raise ValueError("--authority-signature must be AUTHORITY_ID|ed25519:<128 lowercase hex characters>")
        authority_id = authority_id.strip()
        if authority_id in result:
            raise ValueError("duplicate authority signature")
        result[authority_id] = signature.strip()
    return result


def _attach(package: dict[str, Any], signatures: dict[str, str]) -> dict[str, Any]:
    if package.get("schema_version") != "aidn.rfc-0068-attestation-intake.v1":
        raise ValueError("unsupported RFC-0068 intake schema")
    if package.get("mode") not in {"READ_ONLY_PREPARED_REQUEST", "SIGNED_REQUEST_READY_FOR_SUBMISSION"}:
        raise ValueError("intake package is not attachable")
    request = package.get("request")
    evidence = package.get("evidence")
    if not isinstance(request, dict) or not isinstance(evidence, dict):
        raise ValueError("intake package is missing request or evidence")
    request_authorities = request.get("attestation_authorities")
    evidence_authorities = evidence.get("attestation_authorities")
    if not isinstance(request_authorities, list) or not isinstance(evidence_authorities, list):
        raise ValueError("intake package is missing attestation authorities")
    request_ids = {item.get("authority_id") for item in request_authorities if isinstance(item, dict)}
    evidence_ids = {item.get("authority_id") for item in evidence_authorities if isinstance(item, dict)}
    if request_ids != evidence_ids or None in request_ids:
        raise ValueError("request and evidence authority sets differ")
    if set(signatures) != request_ids:
        raise ValueError("signatures must cover every prepared authority exactly once")
    for authorities in (request_authorities, evidence_authorities):
        for authority in authorities:
            authority["signature"] = signatures[authority["authority_id"]]
    package["mode"] = "SIGNED_REQUEST_READY_FOR_SUBMISSION"
    package["evidence_root"] = canonical_hash(evidence)
    package["signed_authority_ids"] = sorted(signatures)
    return package


def main() -> int:
    args = _parser().parse_args()
    try:
        package = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(package, dict):
            raise ValueError("intake package must be a JSON object")
        updated = _attach(package, _signatures(args.authority_signature))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(updated, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "signatures_attached_server_verification_required",
                "evidence_root": updated["evidence_root"],
                "signed_authority_ids": updated["signed_authority_ids"],
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
