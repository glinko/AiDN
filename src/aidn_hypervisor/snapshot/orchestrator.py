"""Fail-closed snapshot download, verification, restoration, and activation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from aidn_hypervisor.snapshot.activation import ActivationResult, AtomicActivator
from aidn_hypervisor.snapshot.chunking import Chunker
from aidn_hypervisor.snapshot.compression import CompressionHandler
from aidn_hypervisor.snapshot.download import DownloadResult, DownloadSession, SnapshotDownloader
from aidn_hypervisor.snapshot.models import SnapshotChunk, SnapshotManifest
from aidn_hypervisor.snapshot.staging import RestorationResult, StagingStateStore, StateRestorer
from aidn_hypervisor.snapshot.verification import (
    InvariantChecker,
    InvariantCheckResult,
    SnapshotVerifier,
    VerificationResult,
)


@dataclass(frozen=True)
class SnapshotApplyResult:
    """Outcome of one fail-closed snapshot activation attempt."""

    success: bool
    phase: str
    download: DownloadResult | None = None
    verification: VerificationResult | None = None
    restoration: RestorationResult | None = None
    invariants: InvariantCheckResult | None = None
    activation: ActivationResult | None = None
    error: str | None = None


class SnapshotOrchestrator:
    """Execute the only supported path from downloaded chunks to active state.

    ``canonical_state_hash`` must come from the finalized trusted checkpoint,
    not from the untrusted manifest being downloaded. No active state change is
    attempted unless all preceding validation stages succeed.
    """

    def __init__(
        self,
        downloader: SnapshotDownloader,
        *,
        verifier: SnapshotVerifier | None = None,
        invariant_checker: InvariantChecker | None = None,
        activator: AtomicActivator | None = None,
    ) -> None:
        self._downloader = downloader
        self._verifier = verifier or SnapshotVerifier()
        self._invariant_checker = invariant_checker or InvariantChecker()
        self._activator = activator or AtomicActivator()

    @property
    def activator(self) -> AtomicActivator:
        """Expose the activator for active-state inspection and rollback."""
        return self._activator

    def apply(
        self,
        manifest: SnapshotManifest,
        providers: list[str],
        *,
        canonical_state_hash: str,
        session: DownloadSession | None = None,
    ) -> SnapshotApplyResult:
        """Download or resume a snapshot and activate it only after validation."""
        try:
            if session is None:
                download = self._downloader.download(manifest.snapshot_id, manifest, providers)
            else:
                self._validate_session_manifest(session, manifest)
                download = self._downloader.resume(session, providers)
        except (OSError, ValueError) as exc:
            return SnapshotApplyResult(success=False, phase="download", error=str(exc))

        if not download.success:
            return SnapshotApplyResult(
                success=False,
                phase="download",
                download=download,
                error=download.error or "snapshot download is incomplete",
            )

        try:
            chunks = self._downloader.load_verified_chunks(download.session)
        except ValueError as exc:
            return SnapshotApplyResult(success=False, phase="storage", download=download, error=str(exc))

        verification = self._verifier.verify_complete(manifest, chunks, canonical_state_hash=canonical_state_hash)
        if not verification.valid:
            return SnapshotApplyResult(
                success=False,
                phase="verification",
                download=download,
                verification=verification,
                error="; ".join(verification.errors),
            )

        try:
            encoded_data = self._decode_content(manifest, chunks)
            staging = StagingStateStore()
            restoration = StateRestorer(staging).restore(encoded_data)
        except (OSError, ValueError, NotImplementedError) as exc:
            return SnapshotApplyResult(
                success=False,
                phase="restoration",
                download=download,
                verification=verification,
                error=str(exc),
            )

        if restoration.application_state_hash != canonical_state_hash:
            return SnapshotApplyResult(
                success=False,
                phase="restoration",
                download=download,
                verification=verification,
                restoration=restoration,
                error="restored state hash does not match the trusted checkpoint",
            )

        invariants = self._invariant_checker.check_all(staging)
        if not invariants.valid:
            return SnapshotApplyResult(
                success=False,
                phase="invariants",
                download=download,
                verification=verification,
                restoration=restoration,
                invariants=invariants,
                error="; ".join(invariants.violations),
            )

        if not self._activator.prepare(staging, canonical_state_hash):
            return SnapshotApplyResult(
                success=False,
                phase="activation",
                download=download,
                verification=verification,
                restoration=restoration,
                invariants=invariants,
                error="staging state was not accepted for activation",
            )
        activation = self._activator.activate()
        return SnapshotApplyResult(
            success=activation.success,
            phase="activated" if activation.success else "activation",
            download=download,
            verification=verification,
            restoration=restoration,
            invariants=invariants,
            activation=activation,
            error=activation.error,
        )

    @staticmethod
    def _validate_session_manifest(session: DownloadSession, manifest: SnapshotManifest) -> None:
        manifest_hash = hashlib.sha256(manifest.model_dump_json().encode()).hexdigest()
        if (
            session.snapshot_id != manifest.snapshot_id
            or session.manifest_hash != manifest_hash
            or session.expected_chunk_root != manifest.chunk_root
            or len(session.verified_chunk_bitmap) != manifest.chunk_count
        ):
            raise ValueError("download session is not bound to the supplied manifest")

    @staticmethod
    def _decode_content(manifest: SnapshotManifest, chunks: list[SnapshotChunk]) -> bytes:
        compressed = Chunker().reassemble(chunks)
        if manifest.snapshot_content_size > 10_737_418_240:
            raise ValueError("snapshot exceeds the maximum supported uncompressed size")
        compressor = CompressionHandler(
            max_uncompressed_size=manifest.snapshot_content_size,
            max_expansion_ratio=max(
                10.0,
                manifest.snapshot_content_size / max(1, len(compressed)),
            ),
        )
        content = compressor.decompress(compressed, manifest.compression)
        if len(content) != manifest.snapshot_content_size:
            raise ValueError("decompressed snapshot size does not match manifest")
        return content
