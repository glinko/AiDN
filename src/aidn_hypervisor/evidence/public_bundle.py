"""Verification primitives for the EVD-0001 public evidence bundle."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

EVIDENCE_FORMAT_VERSION = 1
EVIDENCE_LEAF_DOMAIN = b"AIDN:EVIDENCE-LEAF:v1\x00"
EVIDENCE_NODE_DOMAIN = b"AIDN:EVIDENCE-NODE:v1\x00"
MANIFEST_NAME = "manifest.json"
ATTESTATION_PATH = "attestations/operator-attestation.json"
INDEPENDENCE_REVIEW_PATH = "attestations/independence-review.json"
GATE_RESULT_PATH = "gates/release-gate-result.json"
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_PRIVATE_KEY_RE = re.compile(rb"-----BEGIN [^-]*PRIVATE KEY-----", re.IGNORECASE)


class EvidenceBundleError(ValueError):
    """An EVD-0001 evidence bundle is invalid or failed verification."""


@dataclass(frozen=True)
class EvidenceVerificationResult:
    """A compact, JSON-friendly summary of a verified evidence bundle."""

    evidence_dir: str
    evidence_root: str
    artifact_count: int
    artifact_paths: tuple[str, ...]
    attestation_verified: bool


def canonical_json_bytes(value: Any) -> bytes:
    """Encode a JSON value using the project-wide canonical JSON rules."""

    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceBundleError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, EvidenceBundleError) as error:
        raise EvidenceBundleError(f"invalid JSON object {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvidenceBundleError(f"JSON root must be an object: {path}")
    return value


def _sha256_bytes(value: bytes) -> bytes:
    return hashlib.sha256(value).digest()


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise EvidenceBundleError(f"cannot read evidence artifact {path}: {error}") from error


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise EvidenceBundleError("artifact path must be a non-empty relative string")
    if "\\" in value or ":" in value:
        raise EvidenceBundleError(f"artifact path must use safe POSIX syntax: {value!r}")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or not parsed.parts or any(part in {".", ".."} for part in parsed.parts):
        raise EvidenceBundleError(f"artifact path must not be absolute or traverse: {value!r}")
    normalized = "/".join(parsed.parts)
    if normalized != value:
        raise EvidenceBundleError(f"artifact path is not normalized: {value!r}")
    if value in (MANIFEST_NAME, ATTESTATION_PATH, INDEPENDENCE_REVIEW_PATH, GATE_RESULT_PATH):
        raise EvidenceBundleError(f"control file cannot be an evidence artifact: {value}")
    return value


def _artifact_path(root: Path, relative: str) -> Path:
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    if candidate.is_symlink():
        raise EvidenceBundleError(f"symlink artifacts are not allowed: {relative}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise EvidenceBundleError(f"artifact path escapes evidence directory: {relative}") from error
    if not resolved.is_file():
        raise EvidenceBundleError(f"evidence artifact is missing or not a file: {relative}")
    return resolved


def _artifact_leaf(relative: str, file_hash: str) -> bytes:
    return _sha256_bytes(
        EVIDENCE_LEAF_DOMAIN
        + relative.encode("utf-8")
        + b"\x00"
        + file_hash.encode("ascii")
    )


def evidence_root(artifacts: Iterable[tuple[str, str]]) -> str:
    """Compute the EVD-0001 Merkle root for sorted ``(path, sha256)`` pairs."""

    leaves = [_artifact_leaf(path, digest) for path, digest in sorted(artifacts)]
    if not leaves:
        raise EvidenceBundleError("evidence bundle must contain at least one artifact")
    while len(leaves) > 1:
        if len(leaves) % 2:
            leaves.append(leaves[-1])
        leaves = [
            _sha256_bytes(EVIDENCE_NODE_DOMAIN + left + right)
            for left, right in zip(leaves[::2], leaves[1::2], strict=True)
        ]
    return "sha256:" + leaves[0].hex()


def _check_sensitive_data(relative: str, payload: bytes) -> None:
    path_lower = relative.lower()
    path_markers = ("private", "mnemonic", "secret", "credential", "cookie", "password")
    if any(marker in path_lower for marker in path_markers):
        raise EvidenceBundleError(f"sensitive-looking artifact path is not publishable: {relative}")
    lowered = payload.lower()
    if _PRIVATE_KEY_RE.search(payload):
        raise EvidenceBundleError(f"private key material detected in artifact: {relative}")
    markers = (
        b"private key",
        b"private_key",
        b"mnemonic",
        b"seed phrase",
        b"api_key",
        b"api-key",
        b"api secret",
        b"access_token",
        b"refresh_token",
        b"client_secret",
        b"authorization: bearer",
        b"session_cookie",
        b"auth_cookie",
        b"tls private key",
    )
    if any(marker in lowered for marker in markers):
        raise EvidenceBundleError(f"sensitive-looking content detected in artifact: {relative}")


def _decode_ed25519(value: object, *, kind: str, size: int) -> bytes:
    if not isinstance(value, str) or not value.startswith("ed25519:"):
        raise EvidenceBundleError(f"{kind} must use ed25519:<hex> encoding")
    encoded = value.removeprefix("ed25519:")
    expected_length = size * 2
    if len(encoded) != expected_length or not re.fullmatch(r"[0-9a-f]+", encoded):
        raise EvidenceBundleError(f"{kind} has invalid Ed25519 length or encoding")
    return bytes.fromhex(encoded)


def _verify_operator_attestation(path: Path, expected_root: str) -> None:
    attestation = _load_object(path)
    if attestation.get("evidence_root") != expected_root:
        raise EvidenceBundleError("operator attestation evidence_root mismatch")
    public_key_bytes = _decode_ed25519(
        attestation.get("operator_public_key"),
        kind="operator_public_key",
        size=32,
    )
    signature = _decode_ed25519(
        attestation.get("signature"),
        kind="signature",
        size=64,
    )
    signed_payload = {key: value for key, value in attestation.items() if key != "signature"}
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(
            signature,
            canonical_json_bytes(signed_payload),
        )
    except InvalidSignature as error:
        raise EvidenceBundleError("operator attestation signature is invalid") from error


def _relative_files(root: Path) -> set[str]:
    result: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise EvidenceBundleError(f"symlinks are not allowed in evidence bundle: {path}")
        if path.is_file():
            result.add(path.relative_to(root).as_posix())
    return result


def verify_public_evidence_bundle(
    evidence_dir: str | Path,
    *,
    required_paths: Iterable[str] = (),
    require_attestation: bool = True,
) -> EvidenceVerificationResult:
    """Verify hashes, Merkle commitment, publication safety and attestation."""

    root = Path(evidence_dir).expanduser().resolve()
    if not root.is_dir():
        raise EvidenceBundleError(f"evidence directory does not exist: {root}")
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise EvidenceBundleError(f"evidence manifest is missing: {manifest_path}")
    _check_sensitive_data(MANIFEST_NAME, manifest_path.read_bytes())
    manifest = _load_object(manifest_path)
    if manifest.get("evidence_format_version") != EVIDENCE_FORMAT_VERSION:
        raise EvidenceBundleError("unsupported evidence_format_version")
    for field in ("network_id", "release_version", "profile_id", "generated_at"):
        if not isinstance(manifest.get(field), str) or not manifest[field]:
            raise EvidenceBundleError(f"manifest field is required: {field}")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or not entries:
        raise EvidenceBundleError("manifest artifacts must be a non-empty list")
    expected_root = manifest.get("evidence_root")
    if not isinstance(expected_root, str) or not _SHA256_RE.fullmatch(expected_root):
        raise EvidenceBundleError("manifest evidence_root must be sha256:<64 lowercase hex>")

    hashes: list[tuple[str, str]] = []
    listed_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise EvidenceBundleError("manifest artifact entry must be an object")
        relative = _safe_relative_path(entry.get("path"))
        if relative in listed_paths:
            raise EvidenceBundleError(f"duplicate artifact path: {relative}")
        listed_paths.add(relative)
        expected_hash = entry.get("sha256")
        if not isinstance(expected_hash, str) or not _HEX64_RE.fullmatch(expected_hash):
            raise EvidenceBundleError(f"invalid sha256 for artifact: {relative}")
        artifact = _artifact_path(root, relative)
        actual_hash = _sha256_file(artifact)
        if actual_hash != expected_hash:
            raise EvidenceBundleError(f"artifact hash mismatch: {relative}")
        _check_sensitive_data(relative, artifact.read_bytes())
        hashes.append((relative, actual_hash))

    actual_root = evidence_root(hashes)
    if actual_root != expected_root:
        raise EvidenceBundleError(f"evidence root mismatch: expected {expected_root}, got {actual_root}")

    required = {_safe_relative_path(path) for path in required_paths}
    missing = sorted(required - listed_paths)
    if missing:
        raise EvidenceBundleError("required evidence artifacts are missing: " + ", ".join(missing))

    control_paths = {
        MANIFEST_NAME,
        ATTESTATION_PATH,
        INDEPENDENCE_REVIEW_PATH,
        GATE_RESULT_PATH,
    }
    unlisted = sorted(_relative_files(root) - listed_paths - control_paths)
    if unlisted:
        raise EvidenceBundleError("unlisted files are not publishable evidence: " + ", ".join(unlisted))

    attestation_path = root / Path(*PurePosixPath(ATTESTATION_PATH).parts)
    attestation_verified = False
    if attestation_path.exists():
        if attestation_path.is_symlink() or not attestation_path.is_file():
            raise EvidenceBundleError("operator attestation is not a regular file")
        _check_sensitive_data(ATTESTATION_PATH, attestation_path.read_bytes())
        _verify_operator_attestation(attestation_path, expected_root)
        attestation_verified = True
    elif require_attestation:
        raise EvidenceBundleError("operator attestation is required")

    return EvidenceVerificationResult(
        evidence_dir=str(root),
        evidence_root=expected_root,
        artifact_count=len(hashes),
        artifact_paths=tuple(path for path, _ in sorted(hashes)),
        attestation_verified=attestation_verified,
    )


__all__ = [
    "ATTESTATION_PATH",
    "EVIDENCE_FORMAT_VERSION",
    "EVIDENCE_LEAF_DOMAIN",
    "EVIDENCE_NODE_DOMAIN",
    "EvidenceBundleError",
    "EvidenceVerificationResult",
    "GATE_RESULT_PATH",
    "INDEPENDENCE_REVIEW_PATH",
    "canonical_json_bytes",
    "evidence_root",
    "verify_public_evidence_bundle",
]
