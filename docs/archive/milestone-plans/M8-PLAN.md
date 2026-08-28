# M8: Federated/Distributed Registry — План реализации

## Контекст

Текущий `RegistryService` (2337 строк) — централизованный. M8 добавляет:
- репликацию между пиров;
- inventory exchange и синхронизацию;
- верификацию объектов;
- anti-entropy;
- Proof of Registry.

Основной источник: `RFC-0061` (107 секций, 1892 строки).

## Слайсы

### S1: Registry Object Envelope + Storage Engine

**Цель:** Immutable content-addressed storage, object envelope, segment manifests, inventory roots.

- `registry/object_envelope.py` — RegistryObjectEnvelope, ObjectIdentity, ContentHash
- `registry/storage.py` — ImmutableObjectStore (put/get/list/delete, content-addressed)
- `registry/manifest.py` — SegmentManifest, InventoryRoot, deterministic ordering
- Тесты: `test_object_envelope.py`, `test_storage.py`, `test_manifest.py`

**RFC-0061 §§:** 4-10, 23 (Deterministic Object Ordering)

---

### S2: Peer Protocol + Authentication

**Цель:** Registry peer discovery, authentication, protocol negotiation, status exchange.

- `registry/peer.py` — RegistryPeer, PeerState machine, PeerAuthenticator
- `registry/protocol.py` — ProtocolNegotiator, RegistryStatus, version compatibility
- `registry/profile.py` — RequiredRegistryProfile, RegistryClass (Full/Cache/Archive)
- Тесты: `test_peer.py`, `test_protocol.py`, `test_profile.py`

**RFC-0061 §§:** 13-19, 101 (Initial Protocol Parameters)

---

### S3: Inventory Exchange + Bloom Filters

**Цель:** Inventory exchange between peers, bloom filter optimization, object announcements.

- `registry/inventory.py` — InventoryExchange, BloomFilter, inventory diff
- `registry/announcement.py` — ObjectAnnouncer, announcement broadcast
- Тесты: `test_inventory.py`, `test_bloom_filter.py`, `test_announcement.py`

**RFC-0061 §§:** 20-27 (Inventory, Bloom Filters, Announcements)

---

### S4: Replication Engine + Sync Modes

**Цель:** Object retrieval, range retrieval, chunked transfers, sync modes.

- `registry/replication.py` — ReplicationEngine (single/range/chunked retrieval)
- `registry/sync.py` — SyncMode (Initial/CatchUp/Live/Repair), SyncController
- Тесты: `test_replication.py`, `test_sync.py`, `test_chunked_transfer.py`

**RFC-0061 §§:** 28-31, 41-46 (Retrieval, Sync Modes)

---

### S5: Verification + Anti-Entropy + Corruption

**Цель:** Object verification pipeline, ledger commitment verification, anti-entropy, corruption detection.

- `registry/verification.py` — ObjectVerifier, LedgerCommitmentVerifier, ParentRefVerifier
- `registry/anti_entropy.py` — AntiEntropyEngine, corruption detection, index rebuild
- Тесты: `test_verification.py`, `test_anti_entropy.py`, `test_corruption.py`

**RFC-0061 §§:** 33-39, 47-48, 62-64, 77-78

---

### S6: Completeness + Proof of Registry + Rewards

**Цель:** Completeness manifests, Proof of Registry challenges, reward evidence, backpressure.

- `registry/completeness.py` — CompletenessManifest, completeness verification
- `registry/proof.py` — ProofOfRegistry, challenge handler, non-response confirmation
- `registry/rewards.py` — RegistryRewardEvidence, contribution calculation
- `registry/backpressure.py` — RateLimiter, backpressure, serving policy
- Тесты: `test_completeness.py`, `test_proof.py`, `test_rewards.py`, `test_backpressure.py`

**RFC-0061 §§:** 60-61, 83-84, 53-57, 98

---

## MVP Scope

По §102 MVP включает все 6 слайсов. Дефёрренные (§103):
- paid Registry queries
- erasure-coded distribution
- ZK storage proofs
- cross-network federation
- anonymous identities

## Окружение

Python 3.14, pytest, pydantic v2, frozen models, strict TDD.
