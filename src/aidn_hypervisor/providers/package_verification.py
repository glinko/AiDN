import hashlib
import json
import re

from aidn_hypervisor.providers.models import (
    PluginPackageVerification,
    ProviderPluginManifest,
)

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    _ED25519_AVAILABLE = True
except Exception:  # pragma: no cover - dependency/import fallback
    InvalidSignature = Exception
    Ed25519PublicKey = None
    _ED25519_AVAILABLE = False


DEFAULT_TRUSTED_PUBLISHER_KEYS = {
    "AiDN Test": [
        "ed25519:8f31030dea1c93ad07101ee994e1f4d1a8a43dda2a5606de3ae30406d4e68435",
    ]
}

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ED25519_KEY_RE = re.compile(r"^ed25519:[0-9a-f]{64}$")
_ED25519_SIGNATURE_RE = re.compile(r"^ed25519:[0-9a-f]{128}$")


def _canonical_json(value: dict) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def compute_manifest_hash(manifest: ProviderPluginManifest | dict) -> str:
    if isinstance(manifest, ProviderPluginManifest):
        payload = manifest.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"manifest_hash", "publisher_signature"},
        )
    else:
        payload = {
            key: value
            for key, value in manifest.items()
            if key not in {"manifest_hash", "publisher_signature"}
            and value is not None
        }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def package_signature_payload(
    manifest: ProviderPluginManifest,
    *,
    manifest_hash: str,
) -> bytes:
    payload = {
        "plugin_id": manifest.plugin_id,
        "plugin_version": manifest.plugin_version,
        "publisher": manifest.publisher,
        "package_digest": manifest.package_digest,
        "manifest_hash": manifest_hash,
    }
    return _canonical_json(payload).encode("utf-8")


def _publisher_key_id(public_key_hex: str) -> str:
    raw = bytes.fromhex(public_key_hex)
    digest = hashlib.sha256(raw).hexdigest()
    return f"sha256:{digest}"


def verify_plugin_manifest_package(
    manifest: ProviderPluginManifest,
    *,
    trusted_publisher_keys: dict[str, list[str]] | None = None,
) -> PluginPackageVerification:
    trusted_publisher_keys = trusted_publisher_keys or {}
    computed_manifest_hash = compute_manifest_hash(manifest)
    declared_manifest_hash = manifest.manifest_hash
    signature_present = bool(manifest.publisher_signature)
    trusted_keys = list(trusted_publisher_keys.get(manifest.publisher, []))
    details = {
        "trusted_key_count": len(trusted_keys),
        "publisher": manifest.publisher,
    }

    if not _SHA256_RE.fullmatch(manifest.package_digest):
        return PluginPackageVerification(
            status="INVALID",
            verification_mode="NONE",
            summary="Plugin package digest must be sha256:<64 hex>.",
            package_digest=manifest.package_digest,
            declared_manifest_hash=declared_manifest_hash,
            computed_manifest_hash=computed_manifest_hash,
            signature_present=signature_present,
            trusted_publisher=False,
            details=details,
        )

    if declared_manifest_hash is None:
        return PluginPackageVerification(
            status="UNVERIFIED",
            verification_mode="HASH_ONLY",
            summary="Plugin package declares a digest but does not declare a manifest hash.",
            package_digest=manifest.package_digest,
            computed_manifest_hash=computed_manifest_hash,
            signature_present=signature_present,
            trusted_publisher=False,
            details=details,
        )

    if not _SHA256_RE.fullmatch(declared_manifest_hash):
        return PluginPackageVerification(
            status="INVALID",
            verification_mode="HASH_ONLY",
            summary="Plugin manifest hash must be sha256:<64 hex>.",
            package_digest=manifest.package_digest,
            declared_manifest_hash=declared_manifest_hash,
            computed_manifest_hash=computed_manifest_hash,
            signature_present=signature_present,
            trusted_publisher=False,
            details=details,
        )

    if declared_manifest_hash != computed_manifest_hash:
        return PluginPackageVerification(
            status="INVALID",
            verification_mode="HASH_ONLY",
            summary="Plugin manifest hash does not match the current manifest content.",
            package_digest=manifest.package_digest,
            declared_manifest_hash=declared_manifest_hash,
            computed_manifest_hash=computed_manifest_hash,
            signature_present=signature_present,
            trusted_publisher=False,
            details=details,
        )

    if not manifest.publisher_public_key or not manifest.publisher_signature:
        return PluginPackageVerification(
            status="UNVERIFIED",
            verification_mode="HASH_ONLY",
            summary="Plugin package is hash-bound but not signed by a trusted publisher.",
            package_digest=manifest.package_digest,
            declared_manifest_hash=declared_manifest_hash,
            computed_manifest_hash=computed_manifest_hash,
            signature_present=signature_present,
            trusted_publisher=False,
            details=details,
        )

    if not _ED25519_KEY_RE.fullmatch(manifest.publisher_public_key):
        return PluginPackageVerification(
            status="INVALID",
            verification_mode="ED25519",
            summary="Plugin publisher public key must use ed25519:<32-byte hex> format.",
            package_digest=manifest.package_digest,
            declared_manifest_hash=declared_manifest_hash,
            computed_manifest_hash=computed_manifest_hash,
            signature_present=signature_present,
            trusted_publisher=False,
            details=details,
        )

    if not _ED25519_SIGNATURE_RE.fullmatch(manifest.publisher_signature):
        return PluginPackageVerification(
            status="INVALID",
            verification_mode="ED25519",
            summary="Plugin publisher signature must use ed25519:<64-byte hex> format.",
            package_digest=manifest.package_digest,
            declared_manifest_hash=declared_manifest_hash,
            computed_manifest_hash=computed_manifest_hash,
            signature_present=signature_present,
            trusted_publisher=False,
            details=details,
        )

    publisher_key_id = _publisher_key_id(manifest.publisher_public_key.split(":", 1)[1])
    trusted_publisher = manifest.publisher_public_key in trusted_keys
    details["publisher_key_id"] = publisher_key_id

    if not trusted_publisher:
        return PluginPackageVerification(
            status="UNVERIFIED",
            verification_mode="ED25519",
            summary="Plugin signature is present, but the publisher key is not trusted by this hypervisor.",
            package_digest=manifest.package_digest,
            declared_manifest_hash=declared_manifest_hash,
            computed_manifest_hash=computed_manifest_hash,
            publisher_key_id=publisher_key_id,
            signature_present=True,
            trusted_publisher=False,
            details=details,
        )

    if not _ED25519_AVAILABLE:
        return PluginPackageVerification(
            status="UNVERIFIED",
            verification_mode="ED25519",
            summary="Plugin signature is present, but Ed25519 verification support is unavailable.",
            package_digest=manifest.package_digest,
            declared_manifest_hash=declared_manifest_hash,
            computed_manifest_hash=computed_manifest_hash,
            publisher_key_id=publisher_key_id,
            signature_present=True,
            trusted_publisher=True,
            details=details,
        )

    public_key = Ed25519PublicKey.from_public_bytes(
        bytes.fromhex(manifest.publisher_public_key.split(":", 1)[1])
    )
    signature = bytes.fromhex(manifest.publisher_signature.split(":", 1)[1])
    try:
        public_key.verify(
            signature,
            package_signature_payload(manifest, manifest_hash=declared_manifest_hash),
        )
    except InvalidSignature:
        return PluginPackageVerification(
            status="INVALID",
            verification_mode="ED25519",
            summary="Plugin publisher signature is invalid for the declared package identity.",
            package_digest=manifest.package_digest,
            declared_manifest_hash=declared_manifest_hash,
            computed_manifest_hash=computed_manifest_hash,
            publisher_key_id=publisher_key_id,
            signature_present=True,
            trusted_publisher=True,
            details=details,
        )

    return PluginPackageVerification(
        status="VERIFIED",
        verification_mode="ED25519",
        summary="Plugin package digest and manifest are signed by a trusted publisher.",
        package_digest=manifest.package_digest,
        declared_manifest_hash=declared_manifest_hash,
        computed_manifest_hash=computed_manifest_hash,
        publisher_key_id=publisher_key_id,
        signature_present=True,
        trusted_publisher=True,
        details=details,
    )
