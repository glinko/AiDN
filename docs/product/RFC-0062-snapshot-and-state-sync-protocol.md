# RFC-0062 Snapshot and State Sync Protocol

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0046 Registry Architecture`
- `RFC-0047 CometBFT Consensus Integration`
- `RFC-0048 Epoch Engine`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0059 Ledger Operation Catalog`
- `RFC-0061 Registry Replication Protocol`
- `ECO-0004 Protocol Service Reward Distribution`

## 1. Purpose

This document defines how an AiDN node may:

- create an application-state Snapshot;
- commit Snapshot metadata to canonical Ledger history;
- distribute Snapshot data through Registry Services;
- discover suitable Snapshots;
- download Snapshot chunks from one or more providers;
- verify Snapshot integrity;
- restore the AiDN Ledger State Machine;
- replay later finalized blocks;
- recover from local state corruption;
- reject invalid, stale or incompatible Snapshots.

The protocol provides fast synchronization without treating the Snapshot provider as a trusted authority.

## 2. Core Principle

A Snapshot is an optimization.

It is not a source of consensus truth.

A node SHALL trust canonical finalized consensus commitments rather than the Registry Service or Snapshot producer that supplied the bytes.

The State Sync process is:

```text
Obtain trusted consensus anchor
        ↓
Select compatible Snapshot
        ↓
Download Snapshot data
        ↓
Verify Snapshot commitments
        ↓
Restore application state
        ↓
Calculate application state hash
        ↓
Compare with canonical state commitment
        ↓
Replay later finalized blocks
        ↓
Enter synchronized state
```

A Snapshot that does not reproduce the canonical application state hash SHALL be rejected.

## 3. Scope

This specification covers application-state synchronization.

A Snapshot is not a Registry archive or a backup of complete chain history.

It captures current canonical application state at one finalized height.

Historical blocks, reports, Advertisements and other protocol-history objects remain synchronized through Registry replication and block history.

It does not replace:

- CometBFT block consensus;
- Registry object replication;
- ordinary Catch-Up Sync;
- peer discovery;
- complete historical archive synchronization;
- Runtime Session recovery.

Registry synchronization is defined by `RFC-0061`.

Session recovery is defined by `RFC-0060`.

## 4. Application State

The Snapshot SHALL represent all canonical AiDN application state required to continue deterministic Ledger execution from the Snapshot height.

This includes at minimum:

- Wallet balances;
- Wallet sequences;
- locked balances;
- Stakes;
- Bonds;
- Session economic state;
- Hypervisor records;
- Service records;
- Endpoint records;
- active Advertisement references;
- Certification state;
- Reputation Profiles;
- Epoch state;
- reward-pool state;
- recyclable-Q accounting;
- protocol parameters;
- Consensus Validator Set metadata;
- consumed evidence identifiers;
- replay-protection state.

## 5. Data Excluded from Application State

The Snapshot SHALL not be required to contain every historical or large Registry object.

Examples of excluded data include:

- full Validation Report payloads;
- images;
- audio;
- video;
- complete Session request and response content;
- old Advertisement bodies;
- historical Registry indexes;
- diagnostic logs;
- Runtime state.

The Snapshot SHALL contain canonical references and hashes where those objects affect current application state.

Historical objects are synchronized separately through Registry replication.

A Snapshot is therefore not equivalent to a Full Registry dataset.

## 6. Snapshot Types

The protocol defines three Snapshot types.

- `FULL_STATE`
- `RECOVERY_STATE`
- `DEVELOPMENT_STATE`

### 6.1 Full State Snapshot

Contains complete canonical application state required to initialize a new node.

### 6.2 Recovery State Snapshot

Used to repair or replace corrupted local state at a known height.

Its canonical semantics are identical to a Full State Snapshot.

### 6.3 Development State Snapshot

May contain testnet-specific or implementation-development metadata.

Development Snapshots SHALL NOT be accepted by production-like networks.

## 7. Snapshot Consumer

A Snapshot Consumer is a node attempting State Sync.

A Consumer MAY be:

- a new Consensus Service;
- a recovering Consensus Service;
- a Full Registry;
- a read-only Ledger node;
- a development or auditing node.

The Consumer independently verifies all Snapshot data.

## 8. Snapshot Producer

A Snapshot Producer is a node that serializes canonical application state into a Snapshot.

A Producer MAY be:

- an active Consensus Service;
- a synchronized non-voting Ledger node;
- a Full Registry with verified application state;
- another protocol-authorized service.

Producing a Snapshot does not make it canonical.

Canonical validity comes from consensus commitments.

## 9. Snapshot Provider

A Snapshot Provider stores and serves:

- Snapshot manifests;
- Snapshot chunks;
- availability metadata.

The Producer and Provider MAY be different nodes.

Registry Services are expected to be the primary Snapshot Providers.

## 10. Snapshot Identity

Every Snapshot SHALL have a deterministic identifier.

```text
snapshot_id =
HASH(
    chain_id
    +
    block_height
    +
    application_state_hash
    +
    snapshot_format_version
    +
    snapshot_content_root
)
```

Different chunk layouts MAY produce different Snapshot IDs for the same application state.

They remain equivalent only when they reproduce the same canonical application state hash.

## 11. Snapshot Manifest

Every Snapshot SHALL have an immutable manifest.

```yaml
snapshot_manifest:
  snapshot_id:
  snapshot_type:
  snapshot_format_version:
  network_id:
  chain_id:
  network_revision:
  protocol_version:
  application_version:
  state_schema_version:
  block_height:
  block_hash:
  block_time:
  epoch:
  application_state_hash:
  validator_set_hash:
  protocol_parameters_hash:
  snapshot_content_hash:
  snapshot_content_size:
  chunk_count:
  chunk_size:
  chunk_root:
  compression:
  encoding:
  creation_time:
  producer_service_id:
  producer_signature:
```

All interpretation-critical fields SHALL be covered by the Producer signature.

## 12. Snapshot Format Version

The Snapshot format SHALL be versioned independently from:

- AiDN protocol version;
- application version;
- state schema version;
- Registry protocol version.

This permits storage-format improvements without silently changing Ledger semantics.

## 13. State Schema Version

`state_schema_version` identifies the logical application-state layout.

A Consumer SHALL accept a Snapshot only when it:

- supports the schema directly; or
- supports a deterministic migration from that schema.

Unsupported state schemas SHALL be rejected before application begins.

## 14. Snapshot Content

Snapshot content SHALL use a deterministic logical representation.

The representation SHOULD divide state into ordered namespaces.

Example:

```text
wallets/
hypervisors/
services/
endpoints/
sessions/
stakes/
bonds/
certifications/
reputation/
epochs/
protocol_parameters/
evidence/
```

Objects within each namespace SHALL use deterministic ordering.

## 15. Physical Encoding

Physical Snapshot encoding MAY differ between implementations if all of the following remain true:

- the logical state is identical;
- the format is declared;
- the Consumer supports it;
- the restored application state hash matches the canonical commitment.

The MVP SHOULD define one standard portable encoding.

That portable encoding remains the authoritative Snapshot representation even when faster native encodings are also available.

Implementation-specific raw database copies SHOULD NOT be the only supported format.

## 16. Database Independence

A canonical Snapshot SHALL not require the Consumer to use the Producer's:

- database engine;
- filesystem;
- operating system;
- CPU architecture;
- programming language.

A PostgreSQL database dump, RocksDB directory or memory image MAY be offered as an optional acceleration format.

It SHALL not replace the portable canonical Snapshot format.

## 17. Snapshot Height

A Snapshot SHALL correspond to one finalized block height.

The height SHALL identify:

- finalized block hash;
- application state hash after block execution;
- active Validator Set;
- protocol version;
- Epoch.

The Snapshot SHALL not represent partially applied block execution.

## 18. Snapshot Stability Delay

A Snapshot MAY be generated immediately after finalization.

The protocol SHOULD nevertheless use a configurable stability delay before recommending it for public State Sync.

Example:

`SnapshotStabilityDelay = 100 blocks`

The delay allows:

- distribution to multiple Registry Services;
- manifest verification;
- availability confirmation;
- detection of Producer defects.

The delay does not imply probabilistic finality.

## 19. Snapshot Production Schedule

Snapshots SHOULD be produced at deterministic intervals.

Recommended initial policy:

`One Snapshot per Epoch`

Additional Snapshots MAY be produced:

- before a protocol upgrade;
- after a state migration;
- after major recovery;
- at configured block intervals;
- for testnet diagnostics.

## 20. Snapshot Generation

Snapshot generation follows:

```text
Select finalized height
        ↓
Freeze logical application view
        ↓
Serialize state deterministically
        ↓
Calculate content hash
        ↓
Split into chunks
        ↓
Calculate chunk root
        ↓
Create manifest
        ↓
Verify local restoration
        ↓
Publish Snapshot
        ↓
Commit Snapshot metadata
```

A Producer SHOULD perform a local restoration test before advertising the Snapshot.

## 21. Non-Blocking Generation

Snapshot generation SHOULD avoid stopping Ledger execution for an extended period.

Implementations MAY use:

- database snapshots;
- copy-on-write state;
- immutable state versions;
- transactionally consistent exports.

The resulting Snapshot SHALL correspond exactly to the declared finalized height.

## 22. Chunking

Snapshot content SHALL be split into numbered chunks.

Each chunk includes:

```yaml
snapshot_chunk:
  snapshot_id:
  chunk_index:
  total_chunks:
  uncompressed_size:
  compressed_size:
  chunk_hash:
  payload:
```

Chunk indexes SHALL begin from a protocol-defined value and be contiguous.

## 23. Chunk Root

The manifest SHALL commit to every chunk.

```text
chunk_root =
MERKLE_ROOT(
    ordered chunk_index
    +
    chunk_hash
)
```

The Consumer SHALL verify each chunk and the final Chunk Root.

## 24. Chunk Size

Chunk size SHALL be configurable within protocol bounds.

The initial implementation SHOULD use a size suitable for:

- resumable transfer;
- bounded memory usage;
- multi-source downloading;
- Registry request limits.

Very small chunks create excessive metadata.

Very large chunks make failures expensive to retry, because apparently even file segmentation requires diplomacy.

## 25. Compression

Snapshot compression SHALL be declared in the manifest.

The Consumer SHALL enforce:

- compressed-size limit;
- uncompressed-size limit;
- expansion-ratio limit;
- supported algorithm list.

The Snapshot Content Hash SHALL apply to the canonical uncompressed Snapshot content unless the format explicitly defines otherwise.

## 26. Snapshot Commitment

Canonical Snapshot metadata SHALL be committed through:

`SNAPSHOT_COMMIT`

as defined by `RFC-0059`.

The commitment SHALL include at minimum:

- Snapshot ID;
- block height;
- application state hash;
- Snapshot content hash;
- Chunk Root;
- protocol version;
- Registry references.

## 27. Commitment Does Not Endorse Producer

A finalized Snapshot commitment proves that:

- the metadata was accepted by the protocol;
- it refers to a finalized state;
- the declared commitments are canonical references.

It does not prove that every Registry Provider remains available or that the Producer is permanently trustworthy.

Availability remains independently tested.

### Repository MVP Boundary

The repository's consensus entrypoints treat `SNAPSHOT_COMMIT` as a typed,
metadata-only operation. They require the Snapshot identity and content hashes,
the Chunk Root, protocol version, non-negative block height and Epoch, an
optional matching target Epoch, and at least one typed Registry reference.
The same Snapshot ID cannot be committed twice, and a Wallet-originated
operation cannot create the commitment.

This boundary prevents malformed or replayed Snapshot metadata from entering
the local Ledger. It is not a substitute for the trusted-checkpoint/finality
boundary in this RFC: external finality, producer authorization, chunk
availability, restoration, and post-restore application-state verification
remain separate checks before a node activates restored state.

## 28. Snapshot Commit Eligibility

A Snapshot may be committed only when:

- its height is finalized;
- its application state hash matches canonical state;
- its protocol version is valid;
- its manifest passes schema validation;
- its Producer is authorized or the protocol allows open production;
- local restoration verification succeeds where required.

## 29. Multiple Snapshots per Height

The protocol MAY accept multiple Snapshot formats for the same block height.

They may differ in:

- physical encoding;
- chunk size;
- compression;
- Provider set.

They SHALL reproduce the same canonical application state hash.

Consumers MAY choose any compatible committed Snapshot.

## 30. Trust Anchor

Fast State Sync requires a trusted consensus anchor.

Hashes prove integrity only relative to a known canonical commitment.

If the Consumer does not already know which height, block hash and application-state commitment are canonical, matching Snapshot hashes can still describe internally consistent but non-canonical data.

A Trust Anchor identifies a finalized canonical point known independently by the Consumer.

```yaml
trusted_checkpoint:
  network_id:
  chain_id:
  network_revision:
  block_height:
  block_hash:
  application_state_hash:
  validator_set_hash:
  protocol_version:
```

The Consumer SHALL obtain the Trust Anchor through a configured trusted mechanism.

## 31. Trust Anchor Sources

A Trust Anchor MAY come from:

- previously trusted local state;
- software-release metadata;
- an operator-configured checkpoint;
- a hardware or deployment image;
- multiple organizationally independent sources;
- a future protocol checkpoint mechanism.

Agreement between untrusted peers alone SHALL not automatically make a checkpoint trusted.

## 32. Synchronization Modes

AiDN defines three synchronization modes.

- `GENESIS_REPLAY`
- `CHECKPOINT_STATE_SYNC`
- `LOCAL_RECOVERY`

### 32.1 Genesis Replay

The node verifies and executes canonical history from Genesis.

This mode minimizes checkpoint trust but is slow.

### 32.2 Checkpoint State Sync

The node begins from a trusted recent checkpoint and a verified Snapshot.

This is the recommended fast bootstrap mode.

### 32.3 Local Recovery

The node begins from previously trusted local state and repairs forward or restores a newer Snapshot.

## 33. Genesis Replay

Genesis Replay SHALL remain available as the strongest historical verification path where retained history permits it.

A node using Genesis Replay:

1. verifies Genesis;
2. verifies block and Validator Set transitions;
3. executes every Ledger Operation;
4. derives current application state;
5. optionally verifies published Snapshots.

## 34. Checkpoint State Sync

Checkpoint State Sync requires:

- trusted checkpoint;
- compatible committed Snapshot;
- verified consensus path from the trusted checkpoint to the Snapshot height where required;
- verified application state restoration;
- replay of blocks after Snapshot height.

The Consumer SHALL not skip consensus verification merely because several Registry peers supplied identical bytes.

Without a Trust Anchor, Snapshot and chunk hashes prove only internal integrity rather than canonical truth.

## 35. Trust Period

A trusted checkpoint SHALL have a maximum permitted age for fast State Sync.

The trust period SHOULD be shorter than the relevant Consensus unbonding and historical accountability period.

An excessively old checkpoint increases long-range attack risk.

A Consumer with an expired checkpoint SHOULD:

- obtain a newer trusted checkpoint; or
- use Genesis Replay.

## 36. Long-Range Attack Resistance

A long-offline node may encounter a fabricated historical chain signed by old compromised Validator keys.

Protection includes:

- recent trusted checkpoints;
- Validator Set transition verification;
- unbonding periods;
- historical misconduct accountability;
- chain ID binding;
- checkpoint-age limits.

Registry peer majority alone does not solve long-range trust.

## 37. Snapshot Discovery

Consumers discover Snapshots through:

- Registry queries;
- Registry Advertisements;
- configured providers;
- Consensus peer metadata;
- previously cached manifests.

Discovery response SHALL include:

- Snapshot ID;
- height;
- format versions;
- application state hash;
- Chunk Root;
- Provider list;
- availability status.

## 38. Snapshot Selection

The Consumer SHOULD select the highest suitable Snapshot that satisfies:

- canonical commitment exists;
- height is compatible with the Trust Anchor;
- protocol version is supported;
- state schema is supported or migratable;
- sufficient Providers are available;
- stability delay elapsed;
- Snapshot is not revoked or marked defective;
- enough later block history is available.

## 39. Highest Is Not Always Best

The newest Snapshot MAY be rejected in favor of an older one when:

- too few Providers have it;
- its format is unsupported;
- its availability is unverified;
- a protocol upgrade boundary complicates restoration;
- required later blocks are unavailable;
- it has an active defect report.

Selection SHALL prioritize reliable completion over ceremonial closeness to the chain tip.

## 40. Provider Diversity

A Consumer SHOULD obtain Snapshot metadata and chunks from multiple independent Registry Providers.

A cryptographically verified Snapshot MAY still be valid when its bytes are obtained from only one Provider.

Multiple independent Providers are nevertheless preferred for:

- availability;
- withholding resistance;
- eclipse resistance;
- faster download;
- earlier detection of defective Snapshot data.

Recommended initial target:

`TargetSnapshotProviderGroups = 3`

Insufficient diversity does not make a cryptographically verified Snapshot invalid.

It increases availability and eclipse risk.

## 41. Download Planning

The Consumer SHALL:

1. retrieve the canonical manifest;
2. verify commitment references;
3. obtain Provider inventories;
4. map available chunks;
5. assign chunk ranges;
6. begin bounded parallel downloads;
7. reassign failed chunks as needed.

## 42. Multi-Source Download

Chunks MAY be downloaded from different Providers.

Every chunk is independently verified.

A Provider supplying one valid chunk need not be trusted for other chunks.

The Consumer SHALL prevent duplicate completion accounting.

## 43. Download Resumption

Snapshot downloads SHALL be resumable.

The Consumer SHALL persist:

- Snapshot ID;
- manifest hash;
- verified chunk bitmap;
- Provider history;
- temporary file references;
- failure counters.

After restart, only missing or invalid chunks need to be retrieved again.

## 44. Download Backpressure

The Consumer and Providers SHALL support:

- transfer windows;
- concurrency limits;
- bandwidth limits;
- pause and resume;
- retry-after responses.

State Sync SHALL not make an overloaded Registry unusable for ordinary protocol queries.

## 45. Chunk Verification

For every chunk, the Consumer SHALL verify:

- Snapshot ID;
- index;
- declared size;
- compression bounds;
- chunk hash;
- Merkle inclusion under Chunk Root.

Invalid chunks SHALL be discarded.

## 46. Complete Content Verification

After all chunks are assembled, the Consumer SHALL verify:

- total chunk count;
- Snapshot content size;
- Snapshot content hash;
- manifest signature;
- canonical encoding;
- no extra trailing data;
- no missing namespaces.

## 47. Staging State

A Snapshot SHALL be applied to a staging state store.

It SHALL NOT overwrite the current working state directly.

The required high-level flow is:

`download -> staging restore -> application state hash -> invariant checks -> atomic activation`

The staging environment allows:

- schema validation;
- duplicate-key detection;
- invariant checks;
- application state hash calculation;
- safe failure cleanup.

## 48. State Restoration

Restoration follows:

```text
Create empty staging state
        ↓
Load protocol metadata
        ↓
Load namespaces in defined order
        ↓
Validate object references
        ↓
Validate balances and locks
        ↓
Validate replay-protection data
        ↓
Calculate application state hash
```

Restoration order SHALL be deterministic.

## 49. Application State Hash

After restoration, the Consumer SHALL calculate the AiDN application state hash using the same canonical algorithm used during ordinary block execution.

The calculated hash SHALL equal:

- the Snapshot manifest's application state hash; and
- the canonical application state commitment at the Snapshot height.

Failure of either comparison rejects the Snapshot.

## 50. State Invariant Validation

Before activation, the Consumer SHALL verify at minimum:

`Available balances >= 0`
`Locked balances >= 0`
`Wallet balances + locked balances = total supply`
`Session distributions do not exceed Deposits`
`Stake and Bond conservation holds`
`Wallet sequences are valid`
`Object identities are unique`
`Consumed evidence is not duplicated`
`Protocol parameter version matches the declared height`

## 51. Atomic Activation

A verified staging state SHALL be activated atomically.

Activation SHALL:

- stop application writes briefly if required;
- switch the active state reference;
- preserve the previous state until activation succeeds;
- record the activated Snapshot ID;
- begin later-block replay.

A crash during activation SHALL leave either the old state or the complete new state active.

## 52. Later Block Replay

After Snapshot activation, the Consumer SHALL retrieve and execute all finalized blocks after the Snapshot height.

```text
Snapshot height H
        ↓
Apply block H+1
        ↓
Apply block H+2
        ↓
...
        ↓
Reach current finalized height
```

Each resulting application state hash SHALL be verified normally.

## 53. Validator Set Verification

The Consumer SHALL verify Validator Set transitions needed to establish canonical block finality after the Trust Anchor.

It SHALL not accept block headers merely because a Registry supplied them.

The verification path SHALL preserve CometBFT's consensus safety assumptions.

## 54. State Sync Completion

State Sync completes only when:

- Snapshot restoration succeeded;
- application state hash matched;
- later finalized blocks were replayed;
- current Validator Set was verified;
- synchronization lag is within the permitted threshold;
- required Registry objects are available or scheduled for retrieval.

The node may then enter:

`SYNCHRONIZED`

## 55. Consensus Activation

A Consensus Candidate SHALL not become active solely because State Sync completed.

It must additionally satisfy:

- `ECO-0006` eligibility;
- required activation age;
- Consensus Stake;
- Service Verification;
- Validator Set selection.

State Sync proves state compatibility, not entitlement to vote.

## 56. Registry Activation

A Full Registry using State Sync SHALL still synchronize all objects required by the Required Registry Profile.

Application-state restoration alone does not prove Registry completeness.

## 57. Local State Recovery

A node detecting local state corruption MAY use a Recovery Snapshot.

Recovery SHALL:

- identify the last trusted local height;
- stop state mutation;
- preserve diagnostic evidence;
- select a compatible Snapshot;
- restore to staging state;
- verify state hash;
- replay later blocks;
- atomically replace corrupted state.

## 58. Partial State Repair

The MVP SHOULD prefer complete Snapshot restoration over arbitrary partial database repair.

Partial repair is permitted only when:

- the affected state namespace is independently committed;
- the repair is deterministic;
- the resulting complete application state hash is verified.

Otherwise, complete restoration is safer than surgically guessing which records survived.

## 59. Snapshot Availability

A committed Snapshot is considered available when enough Providers can serve its manifest and chunks.

Availability metadata SHALL identify:

- Provider Service IDs;
- Provider Known Control Groups;
- chunk coverage;
- last verified availability;
- transfer health.

## 60. Replication Target

The protocol SHOULD target at least:

`3 independent Registry Provider groups`

for every recommended Snapshot.

A Snapshot with fewer Providers MAY remain valid but SHOULD not be the preferred public bootstrap Snapshot.

## 61. Snapshot Availability Challenges

Validators or protocol-assigned nodes MAY challenge Providers to serve:

- a selected manifest;
- a random chunk;
- a chunk inclusion proof;
- the final chunk;
- a specified byte range.

Successful responses contribute to Registry Duty Proof.

## 62. Snapshot Producer Verification

Snapshot Producers MAY be tested by:

- local restoration checks;
- independent restoration by other nodes;
- application state hash confirmation;
- manifest consistency;
- repeated successful Snapshot history.

A Producer's Reputation SHALL not substitute for hash verification.

## 63. Invalid Snapshot

A Snapshot is invalid when:

- content hash differs;
- Chunk Root differs;
- application state hash differs;
- canonical block commitment differs;
- manifest fields are inconsistent;
- state invariants fail;
- unsupported hidden extensions alter semantics;
- Producer signature is invalid.

An invalid Snapshot SHALL never become active state.

## 64. Defective Snapshot Report

A Consumer detecting an invalid committed Snapshot MAY publish a Defective Snapshot Report.

```yaml
defective_snapshot_report:
  report_id:
  snapshot_id:
  consumer_service_id:
  failure_stage:
  expected_values:
  observed_values:
  evidence_root:
  software_version:
  signature:
```

One report does not automatically prove Producer misconduct.

## 65. Independent Confirmation

Before serious Reputation or economic consequences:

- another independent Consumer SHOULD reproduce the failure; or
- objective conflicting hashes or signatures SHALL exist.

Implementation-specific restoration failure is not automatically a Snapshot defect.

## 66. Snapshot Provider Misbehavior

Provider misconduct MAY include:

- serving chunks inconsistent with advertised hashes;
- signing conflicting manifests for one Snapshot ID;
- repeated deliberate withholding after claiming availability;
- serving maliciously oversized or malformed content;
- fabricating availability proofs.

Ordinary storage failure is not necessarily misconduct.

## 67. Snapshot Producer Misbehavior

Producer misconduct MAY include:

- knowingly committing content that cannot reproduce canonical state;
- signing conflicting manifest content under one Snapshot ID;
- fabricating restoration-test evidence;
- deliberate state omission.

Objective evidence is required for penalties.

## 68. Snapshot Revocation

Canonical application state itself is not revoked.

A particular Snapshot distribution object MAY be marked:

- `DEFECTIVE`
- `DEPRECATED`
- `UNAVAILABLE`
- `INCOMPATIBLE`

Revocation or deprecation SHALL not change the underlying block or state commitment.

## 69. Protocol Upgrade Boundary

Snapshots near protocol upgrades SHALL declare:

- pre-upgrade or post-upgrade application version;
- state schema;
- migration identifier;
- activation height or Epoch.

Consumers SHALL not apply an upgrade-boundary Snapshot without the required migration code.

## 70. Pre-Upgrade Snapshot

The network SHOULD preserve a stable Snapshot shortly before a major protocol upgrade.

This supports:

- rollback diagnostics;
- migration testing;
- independent upgrade verification;
- recovery from implementation defects.

It does not authorize rollback of finalized canonical history.

## 71. Post-Upgrade Snapshot

A new Snapshot SHOULD be produced after:

- upgrade activation;
- deterministic migration completion;
- successful state-hash verification;
- a configurable stability interval.

This becomes the preferred bootstrap point for the new application version.

## 72. Snapshot Migration

A Consumer MAY migrate Snapshot state during restoration only through a versioned deterministic migration.

The migration SHALL define:

- source schema;
- target schema;
- migration algorithm;
- activation version;
- expected post-migration state commitment.

Arbitrary local migration scripts SHALL not produce consensus-compatible state.

## 73. Snapshot Retention

Registry Services SHALL retain Snapshots according to a versioned retention policy.

The policy SHOULD preserve:

- several recent Snapshots;
- the latest stable Snapshot;
- upgrade-boundary Snapshots;
- selected historical Snapshots;
- Genesis bootstrap data.

Recommended initial retention is the latest two or three stable Snapshots plus required upgrade-boundary Snapshots. A
production source SHOULD retain a larger bounded window when snapshot transfer
can span several block commits; the AiDN validator profile defaults to eight.

Once a State Sync Consumer has requested the first chunk of a Snapshot, the
source SHALL protect that exact Snapshot from ordinary retention pruning for a
bounded transfer lease. The lease is renewed by subsequent chunk requests and
expires after a configured inactivity interval. The initial validator profile
uses 30 minutes. An explicit lease expiry or source failure MAY terminate the
transfer, but a source SHALL NOT silently substitute a different Snapshot or
mix chunks from different Snapshot identities. The Consumer SHALL restart from
one complete advertised Snapshot when the lease expires or a chunk becomes
unavailable.

## 74. Snapshot Pruning

A Provider MAY prune a Snapshot when:

- it is outside the Required Registry Profile;
- enough newer stable Snapshots exist;
- upgrade retention requirements are satisfied;
- Provider availability metadata is updated.

An active Snapshot transfer lease is an exception to ordinary pruning. The
source MAY reclaim the Snapshot after the lease expires or the transfer is
explicitly released.

Pruning the bytes does not delete the canonical Snapshot commitment.

## 75. Minimum Snapshot Set

The initial Required Registry Profile SHOULD require:

- latest stable Snapshot;
- previous stable Snapshot;
- latest pre-upgrade Snapshot;
- latest post-upgrade Snapshot where applicable.

Additional historical Snapshots may be optional.

## 76. Snapshot Storage Accounting

Snapshot serving MAY contribute bounded additional Registry Work Units under `ECO-0004`.

Qualifying work MAY include:

- successful assigned chunk delivery;
- new-node State Sync support;
- availability challenges;
- independent Provider diversity.

Self-generated downloads SHALL not earn reward.

## 77. No Separate Snapshot Mint

The MVP defines no separate Snapshot reward pool.

Snapshot production and serving are part of Registry and Consensus infrastructure duties.

A future protocol may introduce a distinct reward only if measurable cost justifies it.

## 78. Snapshot Privacy

Application-state Snapshots contain public Ledger state and protocol metadata.

They SHALL not include:

- private Wallet keys;
- Runtime credentials;
- OAuth tokens;
- raw private Session payloads;
- uncommitted private reports;
- local diagnostic secrets.

Sensitive references SHALL remain hashed or encrypted according to their protocol object rules.

## 79. Access-Controlled State

If future canonical state contains encrypted access-controlled objects, the Snapshot MAY include their ciphertext and public commitments.

Snapshot Providers need not possess decryption keys.

## 80. Denial-of-Service Protection

Consumers and Providers SHALL enforce limits for:

- manifest size;
- chunk size;
- number of simultaneous transfers;
- decompression ratio;
- retry count;
- invalid-chunk count;
- Provider connection count;
- temporary storage use;
- staging-state size.

## 81. Malicious Provider Handling

A Consumer receiving repeated invalid chunks from a Provider SHALL:

- stop using that Provider;
- preserve minimal evidence;
- retrieve chunks elsewhere;
- reduce local peer score;
- publish protocol evidence only where objectively justified.

State Sync SHOULD continue when alternative Providers exist.

## 82. Eclipse Resistance

A State Sync Consumer SHOULD:

- use multiple independent Registry groups;
- verify trusted checkpoint independently;
- compare manifests across providers;
- verify every canonical commitment;
- avoid relying solely on one bootstrap host;
- retain previously trusted network identifiers.

## 83. Chain Identity

Every Snapshot SHALL bind to:

- network ID;
- chain ID;
- Genesis identity;
- protocol domain.

A Snapshot from another network SHALL be rejected even if its schema and hashes are internally valid.

## 84. Wrong-Network Protection

The Consumer SHALL verify network identity before allocating large download or restoration resources.

This prevents accidental or malicious State Sync from:

- testnet;
- a fork;
- another AiDN deployment;
- a similarly named chain.

## 85. Crash During Download

After a crash during download:

- verified chunks remain reusable;
- incomplete chunks are discarded or resumed;
- manifest identity is rechecked;
- Provider connections are re-established;
- download resumes.

## 86. Crash During Restoration

After a crash during restoration:

- the staging state SHALL be considered incomplete;
- active state remains unchanged;
- restoration MAY restart or resume using an implementation-defined journal;
- complete invariant and state-hash verification remains mandatory.

## 87. Crash During Activation

Activation SHALL use atomic storage semantics.

After restart, the node SHALL identify:

- old active state;
- new verified state;
- activation journal status.

It SHALL never merge both state stores heuristically.

## 88. State Sync Progress

Consumers SHOULD expose progress including:

- selected Snapshot;
- manifest verification;
- chunks downloaded;
- bytes downloaded;
- Providers active;
- chunks rejected;
- restoration progress;
- current replay height;
- estimated synchronization lag.

Progress is diagnostic and does not determine eligibility.

## 89. State Sync Metrics

The network SHOULD monitor:

- Snapshot production success;
- Snapshot availability;
- independent Provider count;
- State Sync completion rate;
- average download time;
- average restoration time;
- invalid chunk rate;
- defective Snapshot reports;
- replay duration;
- Snapshot age;
- synchronization failures by version.

## 90. Message Set

The MVP SHALL support:

- `GET_SNAPSHOT_LIST`
- `SNAPSHOT_LIST`
- `GET_SNAPSHOT_MANIFEST`
- `SNAPSHOT_MANIFEST`
- `GET_SNAPSHOT_PROVIDER_STATUS`
- `SNAPSHOT_PROVIDER_STATUS`
- `GET_SNAPSHOT_CHUNK`
- `SNAPSHOT_CHUNK`
- `SNAPSHOT_CHUNK_NOT_FOUND`
- `GET_SNAPSHOT_CHUNK_RANGE`
- `SNAPSHOT_CHUNK_RANGE`
- `RESUME_SNAPSHOT_TRANSFER`
- `SNAPSHOT_TRANSFER_PAUSE`
- `SNAPSHOT_TRANSFER_RESUME`
- `SNAPSHOT_TRANSFER_ABORT`
- `SNAPSHOT_AVAILABILITY_CHALLENGE`
- `SNAPSHOT_AVAILABILITY_RESPONSE`
- `SNAPSHOT_DEFECT_REPORT`
- `SNAPSHOT_ERROR`

These messages MAY reuse Registry transport and authentication from `RFC-0061`.

## 91. Error Codes

The MVP SHALL define at least:

- `SNAPSHOT_NOT_FOUND`
- `SNAPSHOT_NOT_COMMITTED`
- `SNAPSHOT_DEPRECATED`
- `SNAPSHOT_DEFECTIVE`
- `SNAPSHOT_INCOMPATIBLE`
- `WRONG_NETWORK`
- `UNSUPPORTED_SNAPSHOT_FORMAT`
- `UNSUPPORTED_STATE_SCHEMA`
- `UNSUPPORTED_APPLICATION_VERSION`
- `TRUST_ANCHOR_REQUIRED`
- `TRUST_ANCHOR_EXPIRED`
- `INVALID_MANIFEST`
- `INVALID_PRODUCER_SIGNATURE`
- `INVALID_CHUNK_INDEX`
- `CHUNK_HASH_MISMATCH`
- `CHUNK_ROOT_MISMATCH`
- `CONTENT_HASH_MISMATCH`
- `APPLICATION_STATE_HASH_MISMATCH`
- `STATE_INVARIANT_FAILURE`
- `MIGRATION_REQUIRED`
- `MIGRATION_FAILED`
- `INSUFFICIENT_STORAGE`
- `TRANSFER_RATE_LIMITED`
- `PROVIDER_UNAVAILABLE`
- `BLOCK_REPLAY_UNAVAILABLE`
- `VALIDATOR_SET_VERIFICATION_FAILED`

## 92. Epoch Integration

Snapshot processing integrates with Epoch Tasks including:

- `Select Snapshot Height`
- `Generate Snapshot`
- `Verify Snapshot Restoration`
- `Commit Snapshot Metadata`
- `Replicate Snapshot`
- `Challenge Snapshot Availability`
- `Update Recommended Snapshot`
- `Calculate Registry Contribution`
- `Prune Expired Snapshot Data`

Snapshot transfer itself continues outside Epoch execution.

## 93. Ledger Integration

This protocol uses:

- `SNAPSHOT_COMMIT`;
- `SERVICE_VERIFICATION_COMMIT`;
- `PARTICIPANT_SUSPEND`;
- `PENALTY_APPLY`;
- `EPOCH_TRANSITION`.

Ordinary Snapshot downloads do not create Ledger Operations.

## 94. Recommended Snapshot

The protocol MAY identify one Snapshot as the Recommended Snapshot for a given application version.

Selection SHOULD consider:

- stable finalized height;
- provider diversity;
- format compatibility;
- successful restoration history;
- availability;
- absence of active defect reports.

Recommended status does not bypass verification.

## 95. Reference Snapshot Tooling

The AiDN project SHOULD provide reference tooling for:

- Snapshot generation;
- manifest inspection;
- chunk verification;
- state restoration;
- application state hash calculation;
- Snapshot comparison;
- defect reporting;
- migration testing.

Independent implementations SHALL be able to reproduce the same canonical application state hash.

## 96. Conformance Testing

Snapshot implementations SHALL be tested for:

- deterministic logical export;
- portable restoration;
- chunk corruption detection;
- missing chunk handling;
- wrong-network rejection;
- incompatible schema rejection;
- application state hash verification;
- invariant detection;
- crash recovery;
- multi-source download;
- block replay;
- upgrade-boundary migration.

## 97. MVP Requirements

The MVP SHALL implement:

- one portable Full State Snapshot format;
- versioned manifests;
- canonical state commitments;
- Snapshot chunking;
- Chunk Root verification;
- Registry-based discovery and distribution;
- multi-source download;
- resumable transfer;
- staging restoration;
- state invariant verification;
- application state hash verification;
- atomic activation;
- later-block replay;
- trusted checkpoint support;
- Genesis Replay fallback;
- Snapshot availability challenges;
- minimum Snapshot retention;
- defect reports;
- upgrade-boundary metadata.

## 98. Deferred Features

The MVP MAY postpone:

- erasure-coded Snapshot distribution;
- peer-to-peer swarming;
- differential Snapshots;
- incremental state patches;
- zero-knowledge state proofs;
- confidential state synchronization;
- hardware-attested Snapshot production;
- automatic Trust Anchor governance;
- cross-chain State Sync;
- paid Snapshot transfer markets;
- live Consensus state migration.

## 99. Open Protocol Parameters

The following remain configurable:

- Snapshot production frequency;
- stability delay;
- chunk size;
- maximum Snapshot size;
- compression algorithms;
- portable Snapshot encoding profile;
- provider-diversity target;
- trust-period duration;
- checkpoint maximum age;
- Snapshot retention count;
- active Snapshot transfer lease duration;
- upgrade-boundary retention;
- availability-challenge rate;
- transfer concurrency;
- decompression limits;
- recommended-Snapshot selection weights;
- defect-confirmation threshold.

Recommended initial directions are:

- Snapshot production frequency: once per Epoch;
- stability delay: 50-100 blocks;
- chunk size: approximately 4-16 MiB;
- provider-diversity target: three independent Provider groups;
- Snapshot retention count: latest two or three stable Snapshots plus upgrade-boundary retention;
- active Snapshot transfer lease: 30 minutes of inactivity in the initial validator profile;
- trust period: aligned with unbonding and checkpoint policy;
- portable Snapshot encoding profile: deterministic protobuf-like or CBOR-like export.

Exact values SHOULD be chosen after measuring real application-state size, download characteristics and restoration time.

## 100. Snapshot Invariants

- Every Snapshot binds to one finalized block height.
- Snapshot bytes do not establish consensus truth.
- Snapshot is not a complete Registry archive.
- The application state hash is authoritative.
- Snapshot providers are not trusted by identity.
- Every chunk is independently verified.
- Restoration occurs in staging state.
- Active state changes only after complete verification.
- State Sync never changes canonical Ledger history.
- Multiple physical Snapshots may represent the same canonical state.
- Application state and Registry history remain distinct.
- Snapshot restoration does not grant Consensus eligibility.
- Registry completeness is not satisfied by application state alone.
- Unsupported migrations are rejected.
- Wrong-network Snapshots are rejected.
- Invalid Snapshots never become active state.

## 101. Security Invariants

- A single Registry cannot dictate node state.
- Peer majority cannot override canonical consensus commitments.
- A recent Trust Anchor is required for fast synchronization.
- Long-range histories are not accepted solely through old signatures.
- Snapshot activation is atomic.
- Chunk and content sizes are bounded.
- Invalid Provider data cannot corrupt active canonical state.
- Old consensus keys cannot silently redefine a recent trusted checkpoint.
- Local corruption triggers verified recovery rather than arbitrary record repair.
- Snapshot penalties require objective evidence.

## 102. Design Invariants

- State Sync is an optimization over verified canonical state.
- Genesis Replay remains the trust-minimized fallback.
- Checkpoint State Sync provides practical fast bootstrap.
- Registry Services distribute Snapshot data.
- Consensus commitments determine Snapshot validity.
- Portable Snapshot format prevents database-vendor lock-in.
- Snapshot generation and serving are infrastructure duties, not independent monetary products in the MVP.
- New nodes can synchronize without trusting one operator.
- Recovery preserves supply, balance and evidence invariants.
- Every synchronized node reaches the same application state from the same canonical history.
