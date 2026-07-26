"""Snapshot package — RFC-0062 snapshot models, manifest builder, and verifier."""

from aidn_hypervisor.snapshot.models import (
    CompressionAlgorithm,
    Encoding as SnapshotEncoding,
    SnapshotChunk,
    SnapshotIdentity,
    SnapshotManifest,
    SnapshotType,
    compute_snapshot_id,
)
from aidn_hypervisor.snapshot.manifest import ManifestBuilder, ManifestVerifier
from aidn_hypervisor.snapshot.chunking import Chunker, ChunkVerifier, MerkleTree
from aidn_hypervisor.snapshot.compression import CompressionHandler
from aidn_hypervisor.snapshot.encoding import (
    PortableSnapshotEncoder,
    STATE_NAMESPACES,
)
from aidn_hypervisor.snapshot.producer import (
    ProduceResult,
    SnapshotProducer,
    SnapshotProducerConfig,
    SnapshotProducerError,
)
from aidn_hypervisor.snapshot.trust_anchor import (
    CheckpointValidationResult,
    CheckpointValidator,
    TrustAnchor,
    TrustAnchorStore,
)
from aidn_hypervisor.snapshot.sync_mode import (
    SyncMode,
    SyncModeConfig,
    SyncModeSelector,
    SyncModeSelection,
)

__all__ = [
    "CheckpointValidationResult",
    "CheckpointValidator",
    "Chunker",
    "ChunkVerifier",
    "CompressionAlgorithm",
    "CompressionHandler",
    "ManifestBuilder",
    "ManifestVerifier",
    "MerkleTree",
    "PortableSnapshotEncoder",
    "ProduceResult",
    "SnapshotChunk",
    "SnapshotEncoding",
    "SnapshotIdentity",
    "SnapshotManifest",
    "SnapshotProducer",
    "SnapshotProducerConfig",
    "SnapshotProducerError",
    "SnapshotType",
    "STATE_NAMESPACES",
    "SyncMode",
    "SyncModeConfig",
    "SyncModeSelector",
    "SyncModeSelection",
    "TrustAnchor",
    "TrustAnchorStore",
    "compute_snapshot_id",
]
