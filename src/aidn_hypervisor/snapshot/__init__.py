"""Snapshot package — RFC-0062 snapshot models, manifest builder, and verifier."""

from aidn_hypervisor.snapshot.activation import (
    ActivationRecord,
    ActivationResult,
    ActivationState,
    AtomicActivator,
)
from aidn_hypervisor.snapshot.chunk_store import (
    FileSnapshotChunkStore,
    SnapshotChunkStore,
)
from aidn_hypervisor.snapshot.chunking import Chunker, ChunkVerifier, MerkleTree
from aidn_hypervisor.snapshot.compression import CompressionHandler
from aidn_hypervisor.snapshot.discovery import (
    SnapshotAvailability,
    SnapshotCandidate,
    SnapshotDiscovery,
    SnapshotRegistrySource,
    SnapshotSelector,
)
from aidn_hypervisor.snapshot.download import (
    ChunkTransferSource,
    DownloadConfig,
    DownloadPlanner,
    DownloadResult,
    DownloadSession,
    SnapshotDownloader,
)
from aidn_hypervisor.snapshot.encoding import (
    STATE_NAMESPACES,
    PortableSnapshotEncoder,
)
from aidn_hypervisor.snapshot.manifest import ManifestBuilder, ManifestVerifier
from aidn_hypervisor.snapshot.models import (
    CompressionAlgorithm,
    SnapshotChunk,
    SnapshotIdentity,
    SnapshotManifest,
    SnapshotType,
    compute_snapshot_id,
)
from aidn_hypervisor.snapshot.models import (
    Encoding as SnapshotEncoding,
)
from aidn_hypervisor.snapshot.orchestrator import (
    SnapshotApplyResult,
    SnapshotOrchestrator,
)
from aidn_hypervisor.snapshot.producer import (
    ProduceResult,
    SnapshotProducer,
    SnapshotProducerConfig,
    SnapshotProducerError,
)
from aidn_hypervisor.snapshot.progress import (
    SyncMetrics,
    SyncMetricsCollector,
    SyncPhase,
    SyncProgress,
    SyncProgressTracker,
)
from aidn_hypervisor.snapshot.replay import (
    BlockReplayer,
    BlockSource,
    ReplayBlock,
    ReplayConfig,
    ReplayResult,
)
from aidn_hypervisor.snapshot.staging import (
    RestorationResult,
    StagingStateStore,
    StateRestorer,
)
from aidn_hypervisor.snapshot.sync_mode import (
    SyncMode,
    SyncModeConfig,
    SyncModeSelection,
    SyncModeSelector,
)
from aidn_hypervisor.snapshot.trust_anchor import (
    CheckpointValidationResult,
    CheckpointValidator,
    TrustAnchor,
    TrustAnchorStore,
)
from aidn_hypervisor.snapshot.verification import (
    InvariantChecker,
    InvariantCheckResult,
    InvariantError,
    SnapshotVerifier,
    VerificationResult,
)

__all__ = [
    "CheckpointValidationResult",
    "CheckpointValidator",
    "ChunkTransferSource",
    "Chunker",
    "ChunkVerifier",
    "CompressionAlgorithm",
    "CompressionHandler",
    "DownloadConfig",
    "DownloadPlanner",
    "DownloadResult",
    "DownloadSession",
    "FileSnapshotChunkStore",
    "ManifestBuilder",
    "ManifestVerifier",
    "MerkleTree",
    "PortableSnapshotEncoder",
    "ProduceResult",
    "SnapshotAvailability",
    "SnapshotCandidate",
    "SnapshotChunk",
    "SnapshotChunkStore",
    "SnapshotDiscovery",
    "SnapshotDownloader",
    "SnapshotEncoding",
    "SnapshotIdentity",
    "SnapshotManifest",
    "SnapshotProducer",
    "SnapshotProducerConfig",
    "SnapshotProducerError",
    "SnapshotRegistrySource",
    "SnapshotApplyResult",
    "SnapshotOrchestrator",
    "SnapshotSelector",
    "SnapshotType",
    "STATE_NAMESPACES",
    "SyncMode",
    "SyncModeConfig",
    "SyncModeSelector",
    "SyncModeSelection",
    "ActivationRecord",
    "ActivationResult",
    "ActivationState",
    "AtomicActivator",
    "InvariantCheckResult",
    "InvariantChecker",
    "InvariantError",
    "RestorationResult",
    "SnapshotVerifier",
    "StateRestorer",
    "StagingStateStore",
    "VerificationResult",
    "TrustAnchor",
    "TrustAnchorStore",
    "compute_snapshot_id",
    # replay
    "BlockReplayer",
    "BlockSource",
    "ReplayBlock",
    "ReplayConfig",
    "ReplayResult",
    # progress
    "SyncMetrics",
    "SyncMetricsCollector",
    "SyncPhase",
    "SyncProgress",
    "SyncProgressTracker",
]
