# M10: Snapshot & State Sync Protocol (RFC-0062)

## Goal

Implement the Snapshot and State Sync Protocol per RFC-0062, enabling fast node bootstrapping via verified snapshot downloads, staging restoration, canonical state hash verification, and later-block replay — without trusting snapshot providers.

## RFC-0062 Scope (102 sections)

- Snapshot identity, manifest, types (FULL_STATE, RECOVERY_STATE, DEVELOPMENT_STATE)
- Chunking with Merkle chunk root
- Trust anchor & sync modes (GENESIS_REPLAY, CHECKPOINT_STATE_SYNC, LOCAL_RECOVERY)
- Snapshot discovery, selection, multi-source download, resumption
- Chunk verification, complete content verification
- Staging state, restoration, invariant validation, atomic activation
- Later-block replay, validator set verification
- Snapshot availability, replication target, challenges
- Protocol upgrade boundaries, retention, pruning
- Crash recovery (download, restoration, activation)
- Message set, error codes
- Epoch integration, ledger integration
- Defect reports, misbehavior detection
- MVP: portable format, chunking, chunk root, multi-source download, staging, verification, activation, replay

## Existing Infrastructure

| Module | Relevance |
|---|---|
| `consensus/snapshot.py` | Basic producer/consumer (to be replaced/extended) |
| `consensus/commitment.py` | State commitment (SHA-256) — reuse |
| `registry/storage.py` | ImmutableObjectStore — reuse for snapshot chunks |
| `registry/inventory.py` | BloomFilter — reuse for snapshot availability |
| `registry/replicator.py` | RegistryReplicator — reuse for snapshot distribution |
| `registry/discovery.py` | Peer discovery — reuse for snapshot provider discovery |
| `registry/messages.py` | Network message types — extend with snapshot messages |
| `consensus/epoch.py` | EpochService — integrate snapshot production |
| `consensus/execution.py` | ExecutionEngine — reuse for later-block replay |

## Execution Plan: 8 Slices

### S1: Snapshot Models + Manifest (RFC-0062 §6-§17, §22-§25)

**What:** Core snapshot data models, manifest generation, snapshot identity.

**New files:**
- `src/aidn_hypervisor/snapshot/models.py` — SnapshotManifest, SnapshotChunk, SnapshotType, SnapshotIdentity
- `src/aidn_hypervisor/snapshot/manifest.py` — ManifestBuilder, ManifestVerifier

**Models:**
- `SnapshotType` (FULL_STATE, RECOVERY_STATE, DEVELOPMENT_STATE)
- `SnapshotManifest` — full manifest per §11 (snapshot_id, type, format_version, chain_id, block_height, application_state_hash, validator_set_hash, chunk_count, chunk_root, compression, producer_signature, etc.)
- `SnapshotChunk` — per §22 (snapshot_id, chunk_index, total_chunks, uncompressed_size, compressed_size, chunk_hash, payload)
- `SnapshotIdentity` — deterministic ID per §10 (HASH(chain_id + height + state_hash + format_version + content_root))

**Key features:**
- Deterministic snapshot_id computation
- Manifest serialization/deserialization
- Manifest signature verification
- Frozen pydantic models

**Tests:** ~40 tests

---

### S2: Snapshot Chunking + Merkle Root (RFC-0062 §22-§25, §45)

**What:** Chunk splitting, Merkle tree for chunk root, chunk verification.

**New files:**
- `src/aidn_hypervisor/snapshot/chunking.py` — Chunker, MerkleTree, ChunkVerifier
- `src/aidn_hypervisor/snapshot/compression.py` — CompressionHandler

**Key features:**
- Split arbitrary state data into configurable-size chunks (4-16 MiB)
- Build Merkle tree from chunk hashes → chunk_root
- Verify individual chunk hash + Merkle inclusion proof
- Compression support (gzip, declared in manifest)
- Bounded memory usage

**Tests:** ~40 tests

---

### S3: Snapshot Producer + Portable Encoding (RFC-0062 §8, §14-§16, §20-§21)

**What:** Snapshot generation from canonical state, deterministic serialization.

**New files:**
- `src/aidn_hypervisor/snapshot/producer.py` — SnapshotProducer (extends/extends consensus/snapshot.py)
- `src/aidn_hypervisor/snapshot/encoding.py` — PortableSnapshotEncoder

**Key features:**
- Serialize canonical application state into deterministic logical representation
- Namespace ordering (wallets/, hypervisors/, endpoints/, stakes/, etc.) per §14
- Non-blocking generation (database snapshot / copy-on-write semantics)
- Local restoration test before publishing
- Manifest creation + commitment metadata

**Tests:** ~40 tests

---

### S4: Trust Anchor + Sync Modes (RFC-0062 §30-§36)

**What:** Trust anchor management, sync mode selection, checkpoint validation.

**New files:**
- `src/aidn_hypervisor/snapshot/trust_anchor.py` — TrustAnchor, TrustAnchorStore, CheckpointValidator
- `src/aidn_hypervisor/snapshot/sync_mode.py` — SyncModeSelector, SyncModeConfig

**Key features:**
- Trust anchor sources (local state, software release, operator config) per §31
- Checkpoint age limits / trust period enforcement per §35
- Long-range attack resistance per §36
- Sync mode selection: GENESIS_REPLAY, CHECKPOINT_STATE_SYNC, LOCAL_RECOVERY
- Chain identity verification (network_id, chain_id, genesis) per §83

**Tests:** ~35 tests

---

### S5: Snapshot Discovery + Selection + Download (RFC-0062 §37-§44)

**What:** Snapshot discovery, provider selection, multi-source download, resumption.

**New files:**
- `src/aidn_hypervisor/snapshot/discovery.py` — SnapshotDiscovery, SnapshotSelector
- `src/aidn_hypervisor/snapshot/download.py` — SnapshotDownloader, DownloadPlanner, ChunkAssignment

**Key features:**
- Discover snapshots via registry queries (reuse registry/discovery)
- Selection criteria: canonical commitment, height compatibility, protocol version, provider diversity, stability delay per §38
- Multi-source download: assign chunk ranges across providers per §42
- Download resumption: persist verified chunk bitmap, resume after crash per §43
- Backpressure: concurrency limits, bandwidth limits, retry-after per §44
- Provider diversity target: 3 independent groups per §40

**Tests:** ~45 tests

---

### S6: Staging Restoration + Verification + Activation (RFC-0062 §46-§51)

**What:** Staging state, restoration, invariant validation, atomic activation.

**New files:**
- `src/aidn_hypervisor/snapshot/staging.py` — StagingStateStore, StateRestorer
- `src/aidn_hypervisor/snapshot/verification.py` — SnapshotVerifier, InvariantChecker
- `src/aidn_hypervisor/snapshot/activation.py` — AtomicActivator

**Key features:**
- Staging state store (never overwrite active state directly) per §47
- Restoration in defined namespace order per §48
- Application state hash calculation + comparison with manifest + canonical commitment per §49
- Invariant validation: balances >= 0, supply conservation, unique identities, etc. per §50
- Atomic activation: switch active state reference, preserve old state until success per §51
- Crash recovery during restoration per §86

**Tests:** ~50 tests

---

### S7: Later-Block Replay + Sync Completion (RFC-0062 §52-§54, §88-§89)

**What:** Replay finalized blocks after snapshot height, complete sync.

**New files:**
- `src/aidn_hypervisor/snapshot/replay.py` — BlockReplayer, SyncCompleter
- `src/aidn_hypervisor/snapshot/progress.py` — SyncProgressTracker, SyncMetrics

**Key features:**
- Retrieve and execute all finalized blocks after snapshot height per §52
- Verify each resulting application state hash per §52
- Validator set verification per §53
- Sync completion criteria: restoration + hash match + replay + validator verification + lag threshold per §54
- Progress tracking: chunks downloaded, bytes, providers active, replay height per §88
- Metrics: completion rate, download time, invalid chunk rate per §89

**Tests:** ~35 tests

---

### S8: Integration + E2E Tests (Full Pipeline)

**What:** End-to-end integration tests covering the complete snapshot lifecycle.

**New files:**
- `tests/snapshot/test_integration.py`

**Test classes:**
- `TestSnapshotProduction` — producer creates snapshot, manifest, chunks
- `TestSnapshotDistribution` — registry distribution, availability metadata
- `TestSnapshotDownload` — multi-source download, resumption, backpressure
- `TestStagingRestoration` — staging restore, hash verification, invariant checks
- `TestAtomicActivation` — activation, crash recovery, old state preservation
- `TestBlockReplay` — replay after activation, state hash verification
- `TestFullPipeline` — complete lifecycle: produce → distribute → discover → download → verify → restore → activate → replay

**Tests:** ~30 tests

---

## Total Expected

| Slice | Tests | Lines |
|---|---|---|
| S1: Models + Manifest | ~40 | ~300 |
| S2: Chunking + Merkle | ~40 | ~300 |
| S3: Producer + Encoding | ~40 | ~350 |
| S4: Trust Anchor + Sync Modes | ~35 | ~250 |
| S5: Discovery + Download | ~45 | ~400 |
| S6: Staging + Verification | ~50 | ~450 |
| S7: Replay + Completion | ~35 | ~300 |
| S8: Integration + E2E | ~30 | ~250 |
| **Total** | **~315** | **~2600** |

## Dependencies Between Slices

```
S1 (Models + Manifest)
  ↓
S2 (Chunking + Merkle)
  ↓
S3 (Producer + Encoding)
  ↓
S4 (Trust Anchor + Sync Modes)
  ↓
S5 (Discovery + Download)
  ↓
S6 (Staging + Verification + Activation)
  ↓
S7 (Replay + Completion)
  ↓
S8 (Integration + E2E)
```

Each slice depends on the previous one. Execute sequentially via subagents.

## Execution Rules

1. **TDD** — tests first, then implementation
2. **Frozen pydantic models** — all models use `frozen=True`
3. **Deterministic serialization** — canonical JSON with sorted keys
4. **No external deps** — pure Python, hashlib for crypto
5. **Reuse existing** — registry storage, bloom filters, replicator, epoch service
6. **Commit after each slice** — `feat(M10-Sn): <description>`
7. **Push after all slices** — single push after S8 completes

## Deferred (RFC-0062 §98)

- Erasure-coded distribution
- P2P swarming
- Differential snapshots
- Incremental state patches
- Zero-knowledge state proofs
- Confidential state sync
- Hardware-attested production
- Automatic trust anchor governance
- Cross-chain state sync
- Paid snapshot transfer markets
- Live consensus state migration
