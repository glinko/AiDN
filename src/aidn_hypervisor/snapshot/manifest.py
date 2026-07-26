"""RFC-0062 — Manifest builder and verifier.

ManifestBuilder constructs a SnapshotManifest from state data.
ManifestVerifier validates signatures, schema compatibility, chain identity,
and finalized height constraints.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from datetime import datetime, timezone
from typing import Any

from aidn_hypervisor.snapshot.models import (
    CompressionAlgorithm,
    Encoding,
    SnapshotManifest,
    SnapshotType,
    compute_snapshot_id,
)


# ── Manifest Builder ──────────────────────────────────────────────

class ManifestBuilder:
    """Construct SnapshotManifest from application state data."""

    DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB

    def __init__(self, *, signing_key: bytes) -> None:
        self._signing_key = signing_key

    def build_manifest(
        self,
        *,
        state_data: dict[str, Any],
        snapshot_type: SnapshotType,
        snapshot_format_version: int,
        network_id: str,
        chain_id: str,
        network_revision: int,
        protocol_version: str,
        application_version: str,
        state_schema_version: int,
        block_height: int,
        block_hash: str,
        block_time: str,
        epoch: int,
        producer_service_id: str,
        validator_set_hash: str | None = None,
        protocol_parameters_hash: str | None = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        compression: CompressionAlgorithm = CompressionAlgorithm.NONE,
        encoding: Encoding = Encoding.JSON_DETERMINISTIC,
    ) -> SnapshotManifest:
        """Build a complete SnapshotManifest from state data."""

        # Canonical JSON (sorted keys, compact separators)
        canonical = json.dumps(state_data, sort_keys=True, separators=(",", ":"))
        content_bytes = canonical.encode()

        # Compute hashes
        application_state_hash = hashlib.sha256(content_bytes).hexdigest()
        snapshot_content_hash = application_state_hash  # same for MVP (no compression)
        snapshot_content_size = len(content_bytes)

        # Chunk calculations
        chunk_count = max(1, math.ceil(snapshot_content_size / chunk_size))

        # chunk_root: Merkle root simplified — single hash for MVP
        # For a single-chunk case, chunk_root == content_hash
        # For multi-chunk, we'd build a proper Merkle tree
        chunk_root = snapshot_content_hash

        # Compute snapshot_id
        snapshot_id = compute_snapshot_id(
            chain_id=chain_id,
            block_height=block_height,
            application_state_hash=application_state_hash,
            snapshot_format_version=snapshot_format_version,
            snapshot_content_root=chunk_root,
        )

        # Creation time
        creation_time = datetime.now(timezone.utc).isoformat()

        # Build manifest (signature computed after)
        manifest = SnapshotManifest(
            snapshot_id=snapshot_id,
            snapshot_type=snapshot_type,
            snapshot_format_version=snapshot_format_version,
            network_id=network_id,
            chain_id=chain_id,
            network_revision=network_revision,
            protocol_version=protocol_version,
            application_version=application_version,
            state_schema_version=state_schema_version,
            block_height=block_height,
            block_hash=block_hash,
            block_time=block_time,
            epoch=epoch,
            application_state_hash=application_state_hash,
            validator_set_hash=validator_set_hash,
            protocol_parameters_hash=protocol_parameters_hash,
            snapshot_content_hash=snapshot_content_hash,
            snapshot_content_size=snapshot_content_size,
            chunk_count=chunk_count,
            chunk_size=chunk_size,
            chunk_root=chunk_root,
            compression=compression,
            encoding=encoding,
            creation_time=creation_time,
            producer_service_id=producer_service_id,
            producer_signature="",  # placeholder — sign below
        )

        # Sign the manifest (HMAC-SHA256 over canonical manifest bytes)
        signature = self._sign_manifest(manifest)

        # Rebuild with actual signature (models are frozen)
        dump = manifest.model_dump(exclude={"producer_signature"})
        manifest = SnapshotManifest(**dump, producer_signature=signature)

        return manifest

    def _sign_manifest(self, manifest: SnapshotManifest) -> str:
        """Compute HMAC-SHA256 signature over canonical manifest bytes."""
        data = manifest.model_dump(exclude={"producer_signature"})
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        sig = hmac.new(self._signing_key, canonical, hashlib.sha256).hexdigest()
        return sig


# ── Manifest Verifier ─────────────────────────────────────────────

class ManifestVerifier:
    """Verify SnapshotManifest integrity, compatibility, and chain identity."""

    @staticmethod
    def verify_manifest(manifest: SnapshotManifest, key: bytes) -> bool:
        """Verify the producer signature using HMAC-SHA256."""
        data = manifest.model_dump(exclude={"producer_signature"})
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        expected_sig = hmac.new(key, canonical, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_sig, manifest.producer_signature)

    @staticmethod
    def verify_schema_compatibility(
        manifest: SnapshotManifest,
        *,
        max_schema_version: int,
        supported_encodings: list[str],
    ) -> bool:
        """Check state schema version and encoding support (RFC-0062 §13)."""
        if manifest.state_schema_version > max_schema_version:
            return False
        if manifest.encoding.value not in supported_encodings:
            return False
        return True

    @staticmethod
    def verify_chain_identity(
        manifest: SnapshotManifest,
        *,
        expected_network_id: str,
        expected_chain_id: str,
    ) -> bool:
        """Check network/chain identity (RFC-0062 §83)."""
        return (
            manifest.network_id == expected_network_id
            and manifest.chain_id == expected_chain_id
        )

    @staticmethod
    def verify_height_finalized(
        manifest: SnapshotManifest,
        *,
        finalized_height: int,
    ) -> bool:
        """Check manifest height <= finalized_height (RFC-0062 §17)."""
        return manifest.block_height <= finalized_height
