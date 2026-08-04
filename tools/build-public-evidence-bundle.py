#!/usr/bin/env python3
"""Build and sign an EVD-0001 public evidence bundle.

The builder copies only explicitly selected artifacts.  It never copies the
operator private key into the bundle and leaves the release-gate result as
control metadata outside the Evidence Root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.evidence import (
    ATTESTATION_PATH,
    GATE_RESULT_PATH,
    canonical_json_bytes,
    evidence_root,
    verify_public_evidence_bundle,
)


def _artifact_spec(value: str) -> tuple[Path, str]:
    source, separator, relative = value.partition("=")
    if not separator or not source or not relative:
        raise argparse.ArgumentTypeError("artifact must use SOURCE=relative/path")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or not parsed.parts
        or any(part in {".", ".."} for part in parsed.parts)
        or "\\" in relative
        or ":" in relative
        or relative in {"manifest.json", ATTESTATION_PATH, GATE_RESULT_PATH}
    ):
        raise argparse.ArgumentTypeError("artifact destination must be a safe non-control POSIX path")
    return Path(source).expanduser(), relative


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    payload = path.read_bytes()
    if payload.startswith(b"-----BEGIN"):
        key = serialization.load_pem_private_key(payload, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("operator key PEM is not an Ed25519 private key")
        return key
    if len(payload) != 32:
        raise ValueError("raw Ed25519 operator key must contain exactly 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(payload)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_bundle(
    *,
    output: Path,
    network_id: str,
    release_version: str,
    profile_id: str,
    operator_id: str,
    control_group_id: str,
    independence_status: str,
    private_key_path: Path,
    artifacts: list[tuple[Path, str]],
) -> dict[str, Any]:
    root = output.expanduser().resolve()
    if root.exists():
        if not root.is_dir() or any(root.iterdir()):
            raise ValueError(f"output directory must be empty or absent: {root}")
    root.mkdir(parents=True, exist_ok=True)
    if not artifacts:
        raise ValueError("at least one evidence artifact is required")

    manifest_entries: list[dict[str, str]] = []
    seen_destinations: set[str] = set()
    for source, relative in artifacts:
        source = source.resolve()
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"artifact source is not a regular file: {source}")
        if relative in seen_destinations:
            raise ValueError(f"duplicate artifact destination: {relative}")
        seen_destinations.add(relative)
        destination = root.joinpath(*PurePosixPath(relative).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        manifest_entries.append({"path": relative, "sha256": _sha256(destination)})

    manifest_entries.sort(key=lambda item: item["path"])
    root_hash = evidence_root((item["path"], item["sha256"]) for item in manifest_entries)
    manifest = {
        "evidence_format_version": 1,
        "network_id": network_id,
        "release_version": release_version,
        "profile_id": profile_id,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "artifacts": manifest_entries,
        "evidence_root": root_hash,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    private_key = _load_private_key(private_key_path.expanduser().resolve())
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    attestation_payload = {
        "attestation_version": 1,
        "operator_id": operator_id,
        "control_group_id": control_group_id,
        "independence_status": independence_status,
        "operator_public_key": "ed25519:" + public_key.hex(),
        "evidence_root": root_hash,
        "signed_at": manifest["generated_at"],
    }
    attestation = {
        **attestation_payload,
        "signature": "ed25519:" + private_key.sign(canonical_json_bytes(attestation_payload)).hex(),
    }
    attestation_path = root.joinpath(*PurePosixPath(ATTESTATION_PATH).parts)
    attestation_path.parent.mkdir(parents=True, exist_ok=True)
    attestation_path.write_text(
        json.dumps(attestation, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    result = verify_public_evidence_bundle(root, require_attestation=True)
    return {
        "status": "ok",
        "evidence_dir": str(root),
        "evidence_root": result.evidence_root,
        "artifact_count": result.artifact_count,
        "attestation_verified": result.attestation_verified,
        "operator_id": operator_id,
        "control_group_id": control_group_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--network-id", required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--operator-id", required=True)
    parser.add_argument("--control-group-id", required=True)
    parser.add_argument(
        "--independence-status",
        choices=("OUT_OF_BAND_DECLARED", "OUT_OF_BAND_VERIFIED"),
        default="OUT_OF_BAND_DECLARED",
    )
    parser.add_argument("--private-key", type=Path, required=True)
    parser.add_argument(
        "--artifact",
        action="append",
        type=_artifact_spec,
        default=[],
        help="SOURCE=relative/path; repeat for every publishable evidence file",
    )
    args = parser.parse_args()
    try:
        result = build_bundle(
            output=args.output,
            network_id=args.network_id,
            release_version=args.release_version,
            profile_id=args.profile_id,
            operator_id=args.operator_id,
            control_group_id=args.control_group_id,
            independence_status=args.independence_status,
            private_key_path=args.private_key,
            artifacts=args.artifact,
        )
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "FAIL", "reason": str(error)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
