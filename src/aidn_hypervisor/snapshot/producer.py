"""RFC-0062 §8, §20-§21 — Snapshot Producer.

Canonical snapshot generation with local restoration verification.
Full pipeline: encode → hash → compress → chunk → Merkle root → manifest.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from aidn_hypervisor.snapshot.chunking import Chunker, MerkleTree
from aidn_hypervisor.snapshot.compression import CompressionHandler
from aidn_hypervisor.snapshot.encoding import PortableSnapshotEncoder
from aidn_hypervisor.snapshot.models import (
    CompressionAlgorithm,
    Encoding,
    SnapshotChunk,
    SnapshotManifest,
    SnapshotType,
    compute_snapshot_id,
)

# ── Custom Exception ──────────────────────────────────────────────

class SnapshotProducerError(Exception):
    """Error during snapshot production."""

    pass


# ── Config ────────────────────────────────────────────────────────

class SnapshotProducerConfig(BaseModel, frozen=True):
    """Snapshot producer configuration."""

    chunk_size: int = 8_388_608  # 8 MiB
    compression: CompressionAlgorithm = CompressionAlgorithm.GZIP
    format_version: int = 1
    stability_delay_blocks: int = 100
    max_snapshot_size: int = 10_737_418_240  # 10 GiB


# ── Result ────────────────────────────────────────────────────────

class ProduceResult(BaseModel, frozen=True):
    """Result of a successful snapshot production."""

    manifest: SnapshotManifest
    chunks: list[SnapshotChunk]
    content_hash: str
    content_size: int
    chunk_root: str


# ── Producer ──────────────────────────────────────────────────────

class SnapshotProducer:
    """Produce canonical snapshots per RFC-0062 §20-§21.

    Pipeline:
    1. Select finalized height (provided)
    2. Freeze logical application view (copy state)
    3. Serialize deterministically (PortableSnapshotEncoder)
    4. Calculate content hash
    5. Compress (CompressionHandler)
    6. Split into chunks (Chunker)
    7. Calculate chunk root (MerkleTree)
    8. Create manifest with pipeline-computed values
    9. Verify local restoration (decode → re-encode → compare hash)
    10. Return result
    """

    def __init__(self, config: SnapshotProducerConfig, signing_key: bytes) -> None:
        self.config = config
        self._signing_key = signing_key
        self._encoder = PortableSnapshotEncoder(chunk_size=config.chunk_size)
        self._compression = CompressionHandler()
        self._chunker = Chunker(chunk_size=config.chunk_size)

    # ── Produce ──────────────────────────────────────────────────

    def produce(
        self,
        *,
        state: dict[str, Any],
        block_height: int,
        block_hash: str,
        block_time: str,
        epoch: int,
        chain_id: str,
        network_id: str,
        network_revision: int,
        protocol_version: str,
        application_version: str,
        state_schema_version: int,
        producer_service_id: str,
    ) -> ProduceResult:
        """Produce a full snapshot from canonical application state.

        Args:
            state: Canonical application state dict.
            block_height: Block height for the snapshot.
            block_hash: Block hash at the given height.
            block_time: ISO-8601 timestamp of the block.
            epoch: Current epoch number.
            chain_id: Chain identifier.
            network_id: Network identifier.
            network_revision: Network revision number.
            protocol_version: Protocol version string.
            application_version: Application version string.
            state_schema_version: State schema version.
            producer_service_id: ID of the producing service.

        Returns:
            ProduceResult with manifest, chunks, and metadata.

        Raises:
            SnapshotProducerError: On any step failure.
        """
        try:
            # ── Step 0: Validate inputs ────────────────────────
            self._validate_inputs(
                block_height=block_height,
                block_hash=block_hash,
                epoch=epoch,
                chain_id=chain_id,
                network_id=network_id,
                protocol_version=protocol_version,
                application_version=application_version,
                state_schema_version=state_schema_version,
                producer_service_id=producer_service_id,
            )

            # ── Step 1: Freeze logical application view ───────
            frozen_state = copy.deepcopy(state)

            # ── Step 2: Serialize deterministically ───────────
            encoded_bytes = self._encoder.encode(frozen_state)

            # ── Step 3: Calculate content hash ────────────────
            content_hash = self._encoder.compute_content_hash(frozen_state)
            content_size = self._encoder.compute_content_size(frozen_state)

            # ── Step 4: Enforce max snapshot size ─────────────
            if content_size > self.config.max_snapshot_size:
                raise SnapshotProducerError(
                    f"Snapshot content size {content_size} exceeds max "
                    f"{self.config.max_snapshot_size}"
                )

            # ── Step 5: Compress ──────────────────────────────
            compressed_bytes = self._compression.compress(
                encoded_bytes,
                self.config.compression,
            )

            # ── Step 6: Split into chunks ─────────────────────
            temp_snapshot_id = compute_snapshot_id(
                chain_id=chain_id,
                block_height=block_height,
                application_state_hash=content_hash,
                snapshot_format_version=self.config.format_version,
                snapshot_content_root=content_hash,
            )

            chunks = self._chunker.split(
                compressed_bytes,
                snapshot_id=temp_snapshot_id,
            )

            # ── Step 7: Calculate chunk root (MerkleTree) ─────
            if not chunks:
                chunk_root = content_hash
            else:
                leaf_hashes = [c.chunk_hash for c in chunks]
                chunk_root = MerkleTree(leaf_hashes).root_hash()

            # ── Step 8: Compute final snapshot_id ─────────────
            snapshot_id = compute_snapshot_id(
                chain_id=chain_id,
                block_height=block_height,
                application_state_hash=content_hash,
                snapshot_format_version=self.config.format_version,
                snapshot_content_root=chunk_root,
            )

            # Update chunk snapshot_ids to final value
            chunks = [
                SnapshotChunk(
                    snapshot_id=snapshot_id,
                    chunk_index=c.chunk_index,
                    total_chunks=c.total_chunks,
                    uncompressed_size=c.uncompressed_size,
                    compressed_size=c.compressed_size,
                    chunk_hash=c.chunk_hash,
                    payload=c.payload,
                )
                for c in chunks
            ]

            # ── Step 9: Build manifest with pipeline values ───
            creation_time = datetime.now(UTC).isoformat()
            chunk_count = len(chunks) if chunks else 1

            manifest = SnapshotManifest(
                snapshot_id=snapshot_id,
                snapshot_type=SnapshotType.FULL_STATE,
                snapshot_format_version=self.config.format_version,
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
                application_state_hash=content_hash,
                validator_set_hash=None,
                protocol_parameters_hash=None,
                snapshot_content_hash=content_hash,
                snapshot_content_size=content_size,
                chunk_count=chunk_count,
                chunk_size=self.config.chunk_size,
                chunk_root=chunk_root,
                compression=self.config.compression,
                encoding=Encoding.JSON_DETERMINISTIC,
                creation_time=creation_time,
                producer_service_id=producer_service_id,
                producer_signature="",
            )

            # Sign the manifest (HMAC-SHA256)
            signature = self._sign_manifest_with_key(manifest)
            # Rebuild with signature (models are frozen)
            dump = manifest.model_dump(exclude={"producer_signature"})
            manifest = SnapshotManifest(**dump, producer_signature=signature)

            # ── Step 10: Local restoration verification ───────
            self._verify_local_restoration(
                frozen_state=frozen_state,
                content_hash=content_hash,
            )

            # ── Return result ─────────────────────────────────
            return ProduceResult(
                manifest=manifest,
                chunks=chunks,
                content_hash=content_hash,
                content_size=content_size,
                chunk_root=chunk_root,
            )

        except SnapshotProducerError:
            raise
        except Exception as exc:
            raise SnapshotProducerError(
                f"Snapshot production failed: {exc}"
            ) from exc

    # ── Signing ─────────────────────────────────────────────────

    def _sign_manifest_with_key(self, manifest: SnapshotManifest) -> str:
        """Compute HMAC-SHA256 signature using the producer's signing key."""
        data = manifest.model_dump(exclude={"producer_signature"})
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(
            self._signing_key,
            canonical,
            hashlib.sha256,
        ).hexdigest()

    # ── Input validation ────────────────────────────────────────

    @staticmethod
    def _validate_inputs(
        *,
        block_height: int,
        block_hash: str,
        epoch: int,
        chain_id: str,
        network_id: str,
        protocol_version: str,
        application_version: str,
        state_schema_version: int,
        producer_service_id: str,
    ) -> None:
        """Validate all produce() inputs. Raises SnapshotProducerError."""
        if block_height < 1:
            raise SnapshotProducerError(
                f"block_height must be >= 1, got {block_height}"
            )
        if epoch < 0:
            raise SnapshotProducerError(
                f"epoch must be >= 0, got {epoch}"
            )
        if not chain_id:
            raise SnapshotProducerError("chain_id must not be empty")
        if not network_id:
            raise SnapshotProducerError("network_id must not be empty")
        if not block_hash:
            raise SnapshotProducerError("block_hash must not be empty")
        if not protocol_version:
            raise SnapshotProducerError("protocol_version must not be empty")
        if not application_version:
            raise SnapshotProducerError("application_version must not be empty")
        if not producer_service_id:
            raise SnapshotProducerError("producer_service_id must not be empty")
        if state_schema_version < 0:
            raise SnapshotProducerError(
                f"state_schema_version must be >= 0, got {state_schema_version}"
            )

    # ── Local restoration verification ──────────────────────────

    @staticmethod
    def _verify_local_restoration(
        *,
        frozen_state: dict[str, Any],
        content_hash: str,
    ) -> None:
        """Verify that decoding and re-encoding produces the same hash.

        This catches encoding mismatches and ensures the snapshot
        can be restored from its encoded form.

        Raises:
            SnapshotProducerError: If restoration fails for any reason.
        """
        try:
            encoder = PortableSnapshotEncoder()
            encoded = encoder.encode(frozen_state)
            decoded = encoder.decode(encoded)
            re_encoded = encoder.encode(decoded)
            re_hash = hashlib.sha256(re_encoded).hexdigest()

            if re_hash != content_hash:
                raise SnapshotProducerError(
                    f"Local restoration verification failed: "
                    f"original hash {content_hash} != restored hash {re_hash}"
                )
        except SnapshotProducerError:
            raise
        except Exception as exc:
            raise SnapshotProducerError(
                f"Local restoration verification failed: {exc}"
            )
