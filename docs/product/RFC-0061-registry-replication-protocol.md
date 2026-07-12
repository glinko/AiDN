# RFC-0061 Registry Replication Protocol

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0039 Hypervisor Service Model`
- `RFC-0040 Service Verification Framework`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0042 Hypervisor Network Protocol`
- `RFC-0046 Registry Architecture`
- `RFC-0047 CometBFT Consensus Integration`
- `RFC-0048 Epoch Engine`
- `RFC-0049 Distributed Marketplace & Advertisement Registry`
- `RFC-0057 Validation Report Specification`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0059 Ledger Operation Catalog`
- `ECO-0004 Protocol Service Reward Distribution`
- `ECO-0005 Q Emission, Recycling and Epoch Reward Allocation`

## 1. Purpose

This document defines how AiDN Registry Services:

- discover Registry peers;
- advertise stored object ranges;
- detect missing protocol objects;
- retrieve missing objects;
- verify object integrity;
- synchronize after temporary or prolonged disconnection;
- maintain deterministic Registry completeness;
- reject invalid or conflicting data;
- serve new Hypervisors and Consensus nodes;
- produce evidence for Proof of Registry;
- participate in Registry reward calculation.

The Registry Replication Protocol distributes verifiable protocol information.

It does not establish Ledger consensus.

## 2. Core Principle

Registry Services SHALL replicate immutable protocol objects.

They SHALL NOT replicate unverified mutable database state.

Each Registry independently:

1. receives or retrieves immutable objects;
2. verifies their identity and protocol commitment;
3. stores accepted objects;
4. builds local derived indexes;
5. compares its inventory with other Registry Services;
6. retrieves missing objects.

The canonical Ledger determines which protocol history is valid.

Registry replication makes that history available.

## 3. Registry and Consensus Separation

CometBFT Consensus establishes:

- canonical block order;
- finalized Ledger Operations;
- application state commitments;
- Validator Set transitions.

Registry Services provide:

- durable historical access;
- replicated protocol-object storage;
- object lookup;
- report and Advertisement storage;
- synchronization support;
- Snapshot distribution references.

A Registry Service SHALL NOT resolve competing Ledger histories through peer majority.

Canonical history is determined by finalized consensus evidence.

## 4. Registry Data Model

Registry Services store immutable Registry Objects.

Initial Registry Object types include:

- finalized blocks;
- Ledger Operations;
- operation results;
- State Snapshot commitments;
- Advertisement objects;
- Validation Reports;
- Service Verification Reports;
- Session Settlement commitments;
- Session Failure Reports;
- Usage Report commitments;
- Certification history;
- Reputation Profile history;
- Epoch results;
- reward calculation commitments;
- Validator Set history;
- protocol parameter versions;
- protocol metadata.

Future protocol versions MAY introduce additional object types.

## 5. Immutable Objects and Derived Views

Registry storage is divided into two logical layers.

### 5.1 Immutable Object Store

Contains canonical object bytes addressed by cryptographic identity.

### 5.2 Derived Indexes

Contain searchable views such as:

- active Advertisements;
- Endpoint history;
- Wallet transaction history;
- Validation history;
- latest Certification state;
- latest Reputation Profile;
- object ranges by Epoch;
- Marketplace search indexes.

Derived indexes MAY be rebuilt from immutable objects.

Derived indexes are not independently authoritative.

## 6. Registry Object Envelope

Every replicated Registry Object SHALL use a common envelope.

```yaml
registry_object:
  object_id:
  object_type:
  object_version:
  protocol_version:
  content_hash:
  content_size:
  created_epoch:
  created_block_height:
  ledger_commitment:
  parent_references:
  previous_version_reference:
  payload_encoding:
  compression:
  payload:
  producer_signature:
```

Fields not applicable SHALL be omitted according to the canonical object schema.

## 7. Object Identity

`object_id` SHALL be deterministically derived from the canonical object content or its protocol-defined identity fields.

For content-addressed objects:

`object_id = HASH(canonical_object_bytes)`

For protocol objects with an existing canonical identifier, such as a Ledger Operation:

`object_id = operation_id`

The object schema SHALL specify the applicable method.

## 8. Content Hash

Every Registry Object SHALL include a cryptographic `content_hash`.

The receiving Registry SHALL verify:

- payload size;
- canonical decoding;
- content hash;
- object identifier;
- required signatures;
- protocol references;
- Ledger commitment where applicable.

An object failing any required check SHALL be rejected.

## 9. Ledger Commitment Classes

Registry Objects are classified by commitment type.

### 9.1 Directly Finalized

The complete object appears in finalized Ledger or block data.

Examples:

- Ledger Operations;
- operation results;
- block headers.

### 9.2 Hash-Committed

The Ledger contains a cryptographic commitment to an off-chain object.

Examples:

- Validation Reports;
- Session Failure Reports;
- large Advertisement content;
- reward evidence manifests.

The Registry object is valid only when its hash matches the finalized commitment.

### 9.3 Protocol-Derived

The object can be deterministically derived from finalized Ledger state.

Examples:

- some Epoch manifests;
- derived active-state summaries.

Protocol-derived objects SHALL include the relevant state root and derivation version.

### 9.4 Uncommitted Cache Object

The object is stored for convenience but is not canonical protocol history.

Uncommitted cache objects:

- SHALL be clearly marked;
- SHALL not satisfy Registry completeness;
- SHALL not affect rewards;
- MAY be deleted at any time.

## 10. Required Registry Profile

Reward-eligible Registry Services SHALL implement a versioned Required Registry Profile.

The profile defines:

- required object types;
- required history ranges;
- required retention periods;
- required Snapshot commitments;
- required Advertisement history;
- required Validation history;
- required Epoch history;
- required indexes;
- maximum permitted synchronization lag.

The Required Registry Profile is a protocol parameter.

## 11. Registry Service Classes

The protocol defines the following Registry classes.

### 11.1 Full Registry

Stores all objects required by the current Required Registry Profile.

A Full Registry MAY qualify for the Registry Reward Pool.

### 11.2 Archive Registry

Stores the Full Registry profile plus additional historical or large-object ranges.

Archive Registry support is optional in the MVP.

Additional archival storage MAY receive future protocol incentives.

### 11.3 Cache Registry

Stores a selected subset of protocol objects for local performance.

A Cache Registry:

- MAY serve queries;
- MAY assist local Hypervisors;
- does not satisfy Full Registry completeness;
- does not qualify for Full Registry rewards.

### 11.4 Bootstrap Registry

A temporary Registry profile used during early network startup.

Bootstrap exceptions SHALL be declared through Genesis or protocol configuration.

## 12. Full Registry Does Not Mean All Binary Artifacts

A Full Registry SHALL store all required canonical Registry Objects.

It is not necessarily required to store every large binary artifact forever.

Examples of optionally externalized artifacts include:

- generated images;
- audio;
- video;
- large benchmark datasets;
- complete Session payloads.

Where large artifacts are externalized, the Full Registry SHALL retain:

- content hash;
- metadata;
- ownership and access references;
- availability state;
- applicable retention information.

## 13. Registry Identity

Every Registry Service SHALL have a unique Service Identity under `RFC-0058`.

Registry protocol messages SHALL identify:

- Registry Service ID;
- Hypervisor ID;
- owner Wallet;
- Reward Beneficiary;
- protocol version;
- Registry profile;
- object-range commitments.

A Registry identity does not prove completeness by itself.

## 14. Registry Connection Lifecycle

A Registry peer connection follows:

```text
DISCOVER
    ↓
CONNECT
    ↓
AUTHENTICATE
    ↓
NEGOTIATE
    ↓
EXCHANGE STATUS
    ↓
EXCHANGE INVENTORY
    ↓
SYNCHRONIZE
    ↓
ANTI_ENTROPY
    ↓
DRAIN
    ↓
DISCONNECT
```

## 15. Peer Discovery

Registry Services discover peers through the Hypervisor Network Protocol.

Discovery sources MAY include:

- configured bootstrap peers;
- Registry Advertisements;
- previously known peers;
- Consensus peers exposing Registry capability;
- peer exchange messages;
- future distributed peer-discovery mechanisms.

Discovery does not imply trust.

## 16. Bootstrap Peers

A new Registry MAY use one or more bootstrap peers to enter the network.

Bootstrap peers provide:

- peer addresses;
- current finalized height;
- current Epoch;
- Registry profile version;
- inventory summaries;
- Snapshot references.

A bootstrap peer SHALL NOT be treated as the sole source of canonical truth.

New Registries SHOULD connect to multiple independent peers.

## 17. Peer Authentication

Registry peer connections SHALL be authenticated using Registry Service identities.

Remote connections SHOULD use mutually authenticated encrypted transport.

Authentication confirms:

- possession of the Registry Service key;
- claimed Service ID;
- supported protocol version.

Authentication does not confirm:

- data correctness;
- object completeness;
- reward eligibility;
- honest ownership claims.

## 18. Protocol Negotiation

Peers SHALL negotiate:

- Registry Protocol version;
- supported object versions;
- supported compression;
- maximum object size;
- maximum chunk size;
- supported inventory formats;
- supported range-query methods;
- supported proof formats;
- active Required Registry Profile.

If no compatible version exists, replication SHALL not proceed.

## 19. Registry Status Exchange

After negotiation, each peer sends:

`REGISTRY_STATUS`

Status includes:

```yaml
registry_status:
  registry_service_id:
  registry_profile:
  protocol_version:
  finalized_block_height:
  current_epoch:
  oldest_available_block:
  newest_available_block:
  object_type_ranges:
  snapshot_references:
  inventory_generation:
  synchronization_state:
  health_status:
```

Status is a claim.

It SHALL be verified through subsequent synchronization and challenges.

## 20. Inventory

An Inventory describes which objects a Registry claims to store.

Inventory SHALL be divided into deterministic segments.

A segment MAY be defined by:

`Object Type + Epoch Range + Block Height Range + Deterministic Partition`

Example:

`Validation Reports`
`Epochs 100–109`
`Partition 03`

## 21. Inventory Segment Manifest

Each segment SHALL have a manifest.

```yaml
inventory_segment:
  segment_id:
  object_type:
  profile_version:
  epoch_start:
  epoch_end:
  block_start:
  block_end:
  object_count:
  total_content_size:
  object_id_root:
  content_hash_root:
  first_object_id:
  last_object_id:
  generated_at_height:
  generation:
```

The root SHALL be calculated deterministically from sorted object identifiers and hashes.

## 22. Inventory Root

A Registry MAY publish a higher-level Inventory Root combining all segment manifests.

```text
Registry Inventory Root
    ↓
Object-Type Roots
    ↓
Segment Roots
    ↓
Object IDs and Content Hashes
```

The Inventory Root supports:

- completeness comparison;
- random challenges;
- synchronization planning;
- reward evidence.

An Inventory Root is not sufficient proof that the Registry can actually serve the objects.

## 23. Deterministic Object Ordering

Objects inside a segment SHALL use deterministic ordering.

Recommended ordering:

`object_type -> created_block_height -> created_epoch -> object_id`

Where fields do not apply, the object schema SHALL define the ordering key.

Peers SHALL derive identical roots from identical object sets.

## 24. Inventory Exchange

Peers exchange inventory using:

- `GET_INVENTORY_ROOT`
- `INVENTORY_ROOT`
- `GET_SEGMENT_MANIFESTS`
- `SEGMENT_MANIFESTS`
- `GET_SEGMENT_OBJECT_IDS`
- `SEGMENT_OBJECT_IDS`

A Registry SHOULD first compare higher-level roots.

Detailed object lists are requested only for differing segments.

## 25. Bloom Filters

Bloom filters MAY be used as optional synchronization hints.

Bloom filters SHALL NOT be treated as authoritative completeness evidence because they permit false positives.

A Registry SHALL verify final completeness using deterministic manifests and object roots.

## 26. Pull-Based Replication

Registry replication SHOULD be primarily pull-based.

A Registry:

1. compares inventories;
2. identifies missing objects;
3. selects source peers;
4. requests objects;
5. verifies them;
6. commits them locally.

Unsolicited object announcements MAY improve latency.

Unsolicited data SHALL not bypass verification.

## 27. Object Announcements

A peer MAY announce new objects through:

`OBJECT_ANNOUNCE`

The announcement includes:

- Object ID;
- Object Type;
- Content Hash;
- Content Size;
- finalized block reference;
- relevant segment ID.

The receiver MAY request the object or ignore the announcement.

Announcements SHALL not contain large payloads.

## 28. Single Object Retrieval

Objects are requested using:

`GET_OBJECT`

Response:

`OBJECT`

or:

`OBJECT_NOT_FOUND`

The request SHALL identify:

- Object ID;
- expected Object Type;
- expected Content Hash where known;
- maximum accepted size;
- preferred encoding.

## 29. Range Retrieval

A Registry MAY request deterministic ranges using:

`GET_OBJECT_RANGE`

The request MAY specify:

- Object Type;
- Epoch range;
- block range;
- partition;
- start Object ID;
- maximum object count;
- maximum byte count.

The response SHALL include a continuation cursor where more objects remain.

## 30. Chunked Object Transfer

Large Registry Objects SHALL be transferred in chunks.

Messages include:

- `OBJECT_TRANSFER_BEGIN`
- `OBJECT_CHUNK`
- `OBJECT_TRANSFER_END`
- `OBJECT_TRANSFER_ABORT`

Every chunk SHALL include:

- Object ID;
- transfer ID;
- chunk index;
- chunk hash;
- total chunk count or final marker.

The complete object SHALL be verified after reassembly.

## 31. Transfer Resumption

Interrupted transfers MAY resume.

The receiver provides:

`RESUME_OBJECT_TRANSFER`

including:

- transfer ID;
- verified chunk indexes;
- expected object hash.

A peer SHALL not require retransmission of already verified chunks unless local state was lost.

## 32. Compression

Peers MAY negotiate compression.

The object content hash SHALL apply to canonical uncompressed content unless the object schema explicitly states otherwise.

A receiver SHALL enforce:

- maximum compressed size;
- maximum decompressed size;
- decompression ratio limits;
- supported algorithms.

This protects against compression bombs, because apparently even historical records can be weaponized if given enough enthusiasm.

## 33. Object Verification Pipeline

A received object passes through:

```text
Transport Integrity
        ↓
Chunk Verification
        ↓
Decompression Limits
        ↓
Canonical Decoding
        ↓
Content Hash Verification
        ↓
Object ID Verification
        ↓
Signature Verification
        ↓
Reference Verification
        ↓
Ledger Commitment Verification
        ↓
Local Storage Commit
```

Failure at any stage SHALL reject the object.

## 34. Ledger Commitment Verification

For Ledger-backed objects, the receiving Registry SHALL verify:

- referenced finalized block exists;
- operation or commitment is included;
- Merkle or application proof is valid where applicable;
- content hash matches the commitment;
- protocol version permits the object type;
- object has not been revoked through a later canonical state transition where relevant.

A Registry SHALL not trust a peer-supplied `finalized=true` flag.

## 35. Parent Reference Verification

Objects with dependencies SHALL reference existing parent objects.

Examples include:

- Advertisement version referencing previous Advertisement;
- Validation Report referencing assignment and Endpoint configuration;
- Reputation Profile update referencing previous profile;
- Session Failure Report referencing Session and Usage records.

A child object MAY be temporarily stored in a pending area until parents arrive.

It SHALL not enter the verified object set before dependency validation succeeds.

## 36. Pending Object Store

A Registry MAY maintain a bounded Pending Object Store.

Pending objects include:

- validly hashed objects with missing parents;
- objects awaiting Ledger commitment retrieval;
- objects awaiting required protocol-version metadata.

Pending objects:

- do not satisfy completeness;
- do not enter active indexes;
- do not satisfy Proof of Registry;
- expire after a configured retention period.

## 37. Duplicate Objects

Receiving an already stored object with identical bytes is idempotent.

Receiving the same Object ID with different content is a protocol conflict.

The Registry SHALL:

- reject the conflicting object;
- preserve evidence;
- record the source peer;
- optionally publish a Registry Misbehavior Report.

## 38. Object Versions

Immutable object updates create new Object IDs or protocol-defined versions.

A Registry SHALL not overwrite an older immutable object.

Derived active indexes MAY point to the newest valid version.

Historical versions remain retrievable according to the Required Registry Profile.

## 39. Canonical Conflict Resolution

Registry Services SHALL not resolve conflicts by selecting the version advertised by the largest number of Registry peers.

Conflict resolution follows:

`Finalized Ledger Objects`

Use canonical CometBFT-finalized history.

`Hash-Committed Objects`

Use the object matching the canonical finalized hash commitment.

`Versioned Objects`

Store all valid versions and derive the active version according to canonical Ledger state.

`Invalid Uncommitted Objects`

Reject or retain only as non-canonical cache data.

## 40. Competing Ledger Histories

If peers advertise different block histories:

- the Registry SHALL verify CometBFT commit evidence;
- the Registry SHALL select the finalized canonical chain;
- an unfinalized or minority history SHALL not replace canonical data;
- conflicting signed consensus evidence SHALL be preserved.

Registry peer count SHALL not determine Ledger finality.

## 41. Synchronization Modes

The protocol defines:

- `INITIAL_SYNC`
- `CATCH_UP_SYNC`
- `LIVE_REPLICATION`
- `REPAIR_SYNC`
- `ARCHIVE_SYNC`

## 42. Initial Sync

Initial Sync is used by a new Registry.

It includes:

1. peer discovery;
2. protocol negotiation;
3. finalized height verification;
4. Required Registry Profile retrieval;
5. trusted Snapshot reference discovery;
6. inventory-manifest retrieval;
7. object-range synchronization;
8. object verification;
9. derived index construction;
10. completeness verification;
11. entry into Live Replication.

Detailed State Snapshot restoration is defined by `RFC-0062`.

## 43. Catch-Up Sync

Catch-Up Sync is used after ordinary disconnection.

The Registry:

1. identifies its last complete block and Epoch;
2. compares current peer Inventory Roots;
3. retrieves missing Ledger objects;
4. retrieves referenced reports and metadata;
5. verifies newly completed segments;
6. resumes Live Replication.

Catch-Up Sync SHOULD avoid scanning the complete history.

## 44. Live Replication

During Live Replication, Registry Services:

- receive object announcements;
- follow finalized blocks;
- fetch newly committed objects;
- update open inventory segments;
- periodically compare Inventory Roots;
- serve peer requests;
- monitor synchronization lag.

Live Replication prioritizes recent canonical objects.

## 45. Repair Sync

Repair Sync is used when local corruption or incomplete ranges are detected.

The Registry SHALL:

- isolate affected segments;
- recalculate segment roots;
- identify missing or mismatched objects;
- retrieve objects from multiple peers;
- verify against canonical commitments;
- rebuild affected derived indexes.

Repair SHALL not require deletion of unrelated valid history.

## 46. Archive Sync

Archive Sync retrieves optional historical ranges beyond the Required Registry Profile.

Archive synchronization:

- runs at lower priority than required replication;
- MAY use separate storage;
- SHALL preserve the same object verification rules;
- does not automatically increase Registry rewards in the MVP.

## 47. Anti-Entropy

Every Registry SHALL periodically perform anti-entropy comparison.

Anti-entropy includes:

- Registry Status exchange;
- Inventory Root comparison;
- differing segment identification;
- missing-object retrieval;
- local root recalculation;
- stale peer detection.

Anti-entropy SHALL continue even when no new objects are announced.

## 48. Anti-Entropy Frequency

The MVP SHOULD use:

`Recent open segments:`
`frequent comparison`

`Closed current-Epoch segments:`
`at least once per Epoch`

`Historical segments:`
`randomized periodic sampling`

Exact intervals are protocol or implementation parameters.

Reward evidence SHALL use protocol-defined minimum verification frequency.

## 49. Open and Closed Segments

A segment is `OPEN` while new objects may still enter its deterministic range.

A segment becomes `CLOSED` when:

- its Epoch or block range is finalized;
- no valid new object can enter under the current protocol rules;
- its final segment root is calculated.

Closed segment roots SHALL remain immutable.

## 50. Synchronization Lag

Registry synchronization lag MAY be measured by:

- finalized block-height difference;
- missing required object count;
- missing closed segment count;
- delayed report availability;
- delayed Snapshot availability.

A Full Registry exceeding the maximum permitted lag becomes temporarily reward-ineligible.

## 51. Source Selection

A Registry SHOULD retrieve missing data from multiple peers.

Source selection MAY consider:

- verified historical correctness;
- response latency;
- current load;
- independent Known Control Group;
- object availability;
- prior transfer success;
- network locality.

Local source scoring SHALL not directly modify Ledger Reputation.

## 52. Multi-Source Retrieval

Large synchronization jobs MAY be divided across several peers.

The receiver SHALL ensure:

- deterministic range ownership;
- no duplicate accounting of progress;
- independent object verification;
- bounded concurrent transfers;
- fair peer usage.

An object obtained from one peer does not need confirmation from another when canonical commitment verification succeeds.

## 53. Peer Load Advertisement

A Registry MAY advertise:

```yaml
registry_load:
  active_transfers:
  maximum_transfers:
  outbound_bandwidth_state:
  synchronization_queue:
  request_queue:
  temporary_limits:
```

Load reports are advisory.

A peer MAY refuse or delay non-mandatory requests when overloaded.

## 54. Backpressure

The protocol SHALL support:

- `TRANSFER_WINDOW_UPDATE`
- `TRANSFER_PAUSE`
- `TRANSFER_RESUME`
- `RATE_LIMITED`
- `RETRY_AFTER`

A sender SHALL respect negotiated transfer windows.

Ignoring backpressure MAY cause connection termination or local peer-score reduction.

## 55. Transfer Priorities

Recommended transfer priority:

1. current finalized blocks;
2. Ledger Operations and results;
3. current Epoch protocol objects;
4. active Advertisement objects;
5. Validation and Verification Reports;
6. Snapshot metadata;
7. historical required ranges;
8. optional archive content.

Priority SHALL not affect canonical validity.

## 56. Request Limits

Registry implementations SHALL enforce limits for:

- concurrent requests;
- maximum range size;
- maximum object count;
- maximum bytes;
- maximum outstanding transfers;
- maximum decompression size;
- request frequency;
- failed object retries.

Limits protect against resource-exhaustion attacks.

## 57. Serving Policy

A reward-eligible Full Registry SHALL serve required protocol objects according to the Registry Service Policy.

The policy defines:

- supported object types;
- response deadlines;
- minimum throughput;
- mandatory challenge responses;
- fair-use limits;
- temporary overload behavior.

A Registry SHALL not claim availability while refusing all ordinary protocol requests.

## 58. Registry Queries

Read-only client queries MAY use:

- `GET_OBJECT`
- `GET_OBJECT_RANGE`
- `GET_ACTIVE_OBJECT`
- `GET_OBJECT_HISTORY`
- `GET_BY_LEDGER_REFERENCE`
- `GET_SEGMENT_MANIFEST`

Query responses SHOULD include:

- object bytes or references;
- content hash;
- canonical commitment reference;
- proof metadata;
- Registry Service signature where required.

## 59. Active Object Queries

An active-state query is a derived Registry query.

Examples:

- current Advertisement;
- latest Certification;
- current Reputation Profile.

The response SHALL identify:

- active Object ID;
- derivation block height;
- canonical state reference;
- index version.

Clients MAY independently verify the active pointer from Ledger history.

## 60. Registry Completeness

Completeness is evaluated against the active Required Registry Profile.

A Registry is complete only when:

- every required closed segment is present;
- every segment root matches the canonical manifest;
- required open segments are within permitted lag;
- required Snapshot commitments are present;
- no unresolved corruption exists.

A self-reported object count is not proof of completeness.

## 61. Completeness Manifest

A Full Registry SHALL maintain a Completeness Manifest.

```yaml
registry_completeness:
  registry_service_id:
  profile_version:
  finalized_height:
  current_epoch:
  required_segment_count:
  complete_segment_count:
  incomplete_segments:
  open_segment_lag:
  inventory_root:
  generated_at:
  signature:
```

The manifest is a signed claim subject to verification.

## 62. Proof of Registry

Proof of Registry verifies that a Registry can provide required protocol information.

A challenge MAY request:

- a random Ledger Operation;
- a block range;
- an Advertisement version;
- a Validation Report;
- a Snapshot commitment;
- a segment manifest;
- a randomly selected object from a closed segment;
- an inclusion proof for an object.

## 63. Registry Challenge

A Registry challenge includes:

```yaml
registry_challenge:
  challenge_id:
  target_registry_id:
  object_type:
  object_selector:
  segment_id:
  required_proof:
  issued_at:
  response_deadline:
  challenger_id:
  signature:
```

The selector SHALL be derived from deterministic or protocol-provided randomness.

The target SHALL not choose which object is tested.

## 64. Challenge Response

The response includes:

```yaml
registry_challenge_response:
  challenge_id:
  target_registry_id:
  selected_object_id:
  object_hash:
  object_or_reference:
  segment_inclusion_proof:
  ledger_commitment_proof:
  response_timestamp:
  target_signature:
```

The response SHALL be independently verifiable.

## 65. Proof Success

A challenge succeeds when:

- response arrives before deadline;
- selected object is correct;
- content hash matches;
- segment inclusion proof is valid;
- Ledger commitment proof is valid;
- Registry signature is valid.

Successful challenges contribute to Registry Duty Proof under `ECO-0004`.

## 66. Non-Response Claims

A single challenger cannot conclusively prove remote non-response merely by claiming silence.

When a challenge appears unanswered:

1. the challenger records signed request evidence;
2. an independent verifier or assigned Validator repeats or confirms the challenge;
3. multiple observation points MAY be used;
4. network-wide failure conditions are considered;
5. a finalized Registry Failure Report is produced only after confirmation.

## 67. False Failure Claims

A challenger submitting fabricated failure evidence MAY receive:

- Reputation reduction;
- challenge suspension;
- protocol penalty where objective evidence exists.

Ordinary disagreement over latency SHALL not justify punishment.

## 68. Registry Failure Report

A confirmed failure report includes:

```yaml
registry_failure_report:
  report_id:
  target_registry_id:
  challenge_id:
  failure_type:
  request_evidence:
  confirmation_evidence:
  verifier_ids:
  network_condition_summary:
  result:
  evidence_root:
  signatures:
```

The report MAY affect:

- Health;
- Registry Reputation;
- reward eligibility;
- temporary suspension.

## 69. Registry Misbehavior

Potential Registry misbehavior includes:

- serving an object with an invalid hash;
- serving content conflicting with its Object ID;
- fabricating inventory manifests;
- signing incompatible segment roots for the same closed segment;
- repeated withholding of mandatory objects;
- serving invalid Ledger commitment proofs;
- deliberate protocol amplification attacks.

Objective conflicting signed manifests MAY constitute serious misconduct.

## 70. Inventory Equivocation

If one Registry signs different roots for the same:

- Registry profile;
- closed segment;
- generation;
- canonical finalized height;

the conflicting signatures form objective evidence.

Consequences MAY include:

- immediate reward ineligibility;
- Registry suspension;
- Reputation reduction;
- Registry Bond penalty where defined.

## 71. Ordinary Failure vs Misconduct

The protocol distinguishes:

`Ordinary Failure`

- temporary unavailability;
- storage failure;
- slow response;
- incomplete synchronization;
- accidental corruption.

`Misconduct`

- fabricated proofs;
- conflicting signed manifests;
- knowingly serving invalid content;
- repeated deliberate withholding;
- evidence manipulation.

Ordinary failure primarily reduces reward and eligibility.

Misconduct MAY trigger penalties.

## 72. Local Peer Scoring

Registry implementations MAY maintain local peer scores.

Local score inputs MAY include:

- valid object rate;
- transfer success;
- response latency;
- protocol compliance;
- invalid-data rate;
- connection stability;
- rate-limit behavior.

Local scores influence peer selection.

They SHALL not directly become Ledger Reputation without protocol-verifiable evidence.

## 73. Bad Object Handling

When an invalid object is received, the Registry SHALL:

- reject it;
- preserve minimal evidence;
- record source peer;
- avoid repeatedly requesting the same object from that peer;
- retrieve the object from another peer;
- publish a report only when protocol evidence justifies it.

Invalid data SHALL never enter canonical derived indexes.

## 74. Object Quarantine

Suspicious objects MAY be placed in quarantine.

Quarantined objects:

- are not queryable as canonical;
- do not satisfy completeness;
- are not included in Inventory Roots;
- MAY be retained temporarily for diagnostics.

Quarantine storage SHALL be bounded.

## 75. Storage Corruption Detection

A Registry SHALL periodically verify local stored objects.

Verification MAY include:

- content-hash sampling;
- segment-root recalculation;
- filesystem integrity checks;
- database consistency checks;
- object-reference validation.

Detected corruption triggers Repair Sync.

## 76. Storage Commit Semantics

A received object SHALL be acknowledged as stored only after:

- complete verification;
- durable local write;
- index journal update;
- crash-consistent commit.

A Registry SHALL not advertise an object that exists only in volatile transfer memory.

## 77. Crash Recovery

After Registry restart:

1. incomplete transfers are identified;
2. uncommitted objects are discarded or resumed;
3. durable objects are revalidated as needed;
4. segment manifests are checked;
5. derived indexes are replayed or rebuilt;
6. peer synchronization resumes.

A crash SHALL not require trusting local derived indexes blindly.

## 78. Derived Index Rebuild

A Registry SHALL be able to rebuild derived indexes from:

- immutable objects;
- canonical Ledger references;
- protocol derivation rules.

Index rebuild MAY occur incrementally.

An index failure SHALL not corrupt immutable object history.

## 79. Registry Pruning

A Full Registry MAY prune only data not required by the active Required Registry Profile.

Pruning SHALL NOT remove:

- required canonical objects;
- required historical ranges;
- required report commitments;
- required segment manifests;
- required Snapshot commitments.

Pruning policy SHALL be declared in Registry metadata.

## 80. Profile Upgrades

When the Required Registry Profile expands:

- Registry Services receive a transition period;
- newly required ranges are synchronized;
- reward eligibility MAY continue during the declared grace period;
- failure to complete by the deadline causes ineligibility.

Profile reductions SHALL not require immediate deletion of existing data.

## 81. Registry Joining

A new Registry becomes reward-eligible only after:

- completing Initial Sync;
- satisfying the current profile;
- publishing a valid Completeness Manifest;
- passing Initial Proof of Registry;
- completing activation age;
- satisfying minimum Health and collateral rules.

Partial synchronization does not earn partial Full Registry reward in the MVP.

## 82. Registry Leaving

A Registry MAY enter `DRAINING`.

During draining:

- new large synchronization assignments MAY stop;
- mandatory object serving continues for a configured period;
- active transfers complete or migrate;
- reward eligibility ends according to Epoch rules;
- Registry Bond unbonding MAY begin.

## 83. Registry Reward Evidence

Registry reward evidence MAY include:

- successful mandatory challenges;
- verified completeness;
- current Inventory Root;
- synchronization availability;
- assigned Snapshot delivery;
- assigned historical range delivery;
- response timeliness;
- absence of unresolved signed conflicts.

Raw bandwidth volume SHALL not directly determine reward.

## 84. Additional Registry Contribution

`ECO-0004` permits bounded additional Registry Work Units.

Eligible additional work MAY include:

- protocol-assigned State Sync service;
- serving Snapshot chunks;
- serving required archival ranges;
- assisting new Registry bootstrap;
- responding to additional randomized challenges.

Self-generated traffic SHALL not count.

## 85. Registry Independence

Multiple Registry Services under one Known Control Group MAY operate legitimately.

Each must independently satisfy:

- Service identity;
- storage completeness;
- challenge responses;
- operational availability;
- collateral requirements.

Known Control Group reward limits still apply under `ECO-0004`.

## 86. Shared Storage

Multiple Registry Services MAY use shared physical storage.

Shared storage SHALL be disclosed where required by service metadata.

Each Service remains independently responsible for:

- availability;
- serving;
- authentication;
- response correctness;
- Duty Proof.

Shared storage may create a common failure domain.

It does not automatically prove fraudulent duplication.

## 87. Network Partition

During a network partition:

- Registry Services continue serving locally available canonical objects;
- new canonical history follows CometBFT finality;
- minority-side unfinalized data SHALL not become canonical;
- anti-entropy resumes after connectivity returns;
- fault-neutral correlated failures MAY be recognized.

Registry replication SHALL not invent a separate consensus mechanism during partition.

## 88. Consensus Halt

During Consensus halt:

- existing finalized Registry history remains available;
- no new canonical Ledger objects are finalized;
- pending reports MAY remain uncommitted;
- Registry Services MAY store pending objects separately;
- canonical inventories do not advance beyond the finalized height.

After recovery, pending objects are accepted only if canonical commitments finalize.

## 89. Snapshot Relationship

Registry replication distributes:

- Snapshot commitments;
- Snapshot manifests;
- Snapshot chunk references;
- Snapshot availability metadata.

The rules for:

- selecting a Snapshot;
- verifying Snapshot state;
- applying Snapshot chunks;
- bootstrapping the state machine;

are defined by `RFC-0062`.

## 90. Privacy

Registry replication SHALL not expose private Session payloads unless protocol rules explicitly require them.

Registry Objects SHOULD prefer:

- hashes;
- signed summaries;
- encrypted references;
- access-controlled artifacts;
- minimal evidence.

Private objects MAY use encrypted payloads while retaining public canonical commitments.

## 91. Restricted Objects

Some Registry Objects MAY require access authorization.

Restricted-object replication SHALL define:

- encrypted content;
- authorized recipient policy;
- public commitment;
- key-distribution mechanism;
- retention rules.

A Full Registry MAY satisfy completeness by storing the encrypted canonical object without possessing decryption keys.

## 92. Security Threats

The protocol SHALL account for:

- object poisoning;
- false inventory claims;
- manifest equivocation;
- withholding attacks;
- eclipse attacks;
- Sybil peers;
- decompression bombs;
- oversized range requests;
- transfer amplification;
- duplicate-object flooding;
- invalid parent references;
- stale Ledger commitments;
- conflicting histories;
- bandwidth exhaustion;
- malicious continuation cursors;
- unbounded pending objects.

## 93. Eclipse Resistance

A Registry SHOULD:

- maintain peers from multiple Known Control Groups;
- avoid dependence on one bootstrap peer;
- compare finalized heights across peers;
- use independent network paths where practical;
- retain previously verified peer identities;
- verify all canonical commitments.

Peer diversity reduces the risk that one operator controls the Registry's entire view.

## 94. Amplification Resistance

Registry responses SHALL be bounded by:

- authenticated requests;
- maximum range sizes;
- response budgets;
- rate limits;
- connection-level quotas;
- request-cost accounting where introduced later.

A small unauthenticated request SHALL not trigger an unbounded large response.

## 95. Message Set

The MVP SHALL support:

- `REGISTRY_HELLO`
- `REGISTRY_AUTHENTICATE`
- `REGISTRY_NEGOTIATE`
- `REGISTRY_STATUS`
- `GET_INVENTORY_ROOT`
- `INVENTORY_ROOT`
- `GET_SEGMENT_MANIFESTS`
- `SEGMENT_MANIFESTS`
- `GET_SEGMENT_OBJECT_IDS`
- `SEGMENT_OBJECT_IDS`
- `OBJECT_ANNOUNCE`
- `GET_OBJECT`
- `OBJECT`
- `OBJECT_NOT_FOUND`
- `GET_OBJECT_RANGE`
- `OBJECT_RANGE`
- `OBJECT_RANGE_CONTINUE`
- `OBJECT_TRANSFER_BEGIN`
- `OBJECT_CHUNK`
- `OBJECT_TRANSFER_END`
- `OBJECT_TRANSFER_ABORT`
- `RESUME_OBJECT_TRANSFER`
- `TRANSFER_WINDOW_UPDATE`
- `TRANSFER_PAUSE`
- `TRANSFER_RESUME`
- `RATE_LIMITED`
- `RETRY_AFTER`
- `GET_ACTIVE_OBJECT`
- `GET_OBJECT_HISTORY`
- `GET_BY_LEDGER_REFERENCE`
- `REGISTRY_CHALLENGE`
- `REGISTRY_CHALLENGE_RESPONSE`
- `REGISTRY_DRAINING`
- `REGISTRY_DISCONNECT`
- `REGISTRY_ERROR`

## 96. Error Codes

The MVP SHALL define at least:

- `INVALID_MESSAGE`
- `INVALID_SIGNATURE`
- `UNSUPPORTED_PROTOCOL_VERSION`
- `UNSUPPORTED_OBJECT_VERSION`
- `UNKNOWN_OBJECT_TYPE`
- `OBJECT_NOT_FOUND`
- `OBJECT_HASH_MISMATCH`
- `OBJECT_ID_MISMATCH`
- `INVALID_LEDGER_COMMITMENT`
- `INVALID_PARENT_REFERENCE`
- `INVALID_SEGMENT_MANIFEST`
- `SEGMENT_ROOT_MISMATCH`
- `RANGE_TOO_LARGE`
- `OBJECT_TOO_LARGE`
- `DECOMPRESSION_LIMIT_EXCEEDED`
- `RATE_LIMITED`
- `TRANSFER_SEQUENCE_ERROR`
- `TRANSFER_EXPIRED`
- `INVENTORY_GENERATION_MISMATCH`
- `PROFILE_MISMATCH`
- `PEER_NOT_AUTHORIZED`
- `REGISTRY_DRAINING`
- `INTERNAL_STORAGE_ERROR`

## 97. Idempotency

The following SHALL be idempotent:

- Registry Status exchange;
- Inventory Root requests;
- segment-manifest requests;
- object retrieval;
- range retrieval with the same cursor;
- transfer resumption;
- object announcements;
- challenge-response resubmission.

Storing the same valid immutable object twice SHALL not create duplicate state.

## 98. Registry Protocol Metrics

Registry Services SHOULD expose:

- peer count;
- independent peer-group count;
- finalized height;
- synchronization lag;
- complete segment count;
- incomplete segment count;
- object transfer rate;
- invalid object rate;
- challenge success rate;
- request latency;
- transfer failures;
- storage usage;
- Repair Sync activity;
- pending-object count;
- current Inventory Root.

## 99. Epoch Integration

Registry replication integrates with `RFC-0048` through tasks such as:

- `Freeze Registry Eligibility`
- `Finalize Closed Segment Manifests`
- `Generate Registry Challenges`
- `Collect Challenge Responses`
- `Confirm Registry Failures`
- `Calculate Registry Health`
- `Calculate Registry Rewards`
- `Commit Registry Evidence Root`

Replication itself continues continuously.

Reward and eligibility calculations occur through Epoch Tasks.

## 100. Ledger Integration

Registry replication messages are off-chain.

Ledger Operations MAY be generated for:

- `SERVICE_VERIFICATION_COMMIT`
- `PARTICIPANT_SUSPEND`
- `PARTICIPANT_REINSTATE`
- `PENALTY_APPLY`
- `REWARD_MINT`
- `SNAPSHOT_COMMIT`
- `EPOCH_TRANSITION`

Ordinary object retrieval SHALL not create Ledger Operations.

## 101. Initial Protocol Parameters

The following initial values SHOULD be configurable:

`Maximum object size`
`Maximum chunk size`
`Maximum range object count`
`Maximum range byte count`
`Maximum concurrent transfers`
`Maximum Pending Object retention`
`Maximum synchronization lag`
`Challenge response deadline`
`Anti-entropy interval`
`Closed segment Epoch width`
`Required peer count`
`Required independent peer-group count`
`Registry activation age`
`Registry minimum Health`
`Registry minimum Proof Success`

The exact values SHALL be selected through implementation testing.

## 102. MVP Requirements

The MVP SHALL implement:

- authenticated Registry peers;
- Registry Status exchange;
- versioned Required Registry Profile;
- Full and Cache Registry classes;
- immutable content-addressed object storage;
- deterministic segment manifests;
- Inventory Roots;
- object announcements;
- single-object retrieval;
- range retrieval;
- chunked transfers;
- transfer resumption;
- canonical object verification;
- Ledger commitment verification;
- Initial Sync;
- Catch-Up Sync;
- Live Replication;
- Repair Sync;
- periodic anti-entropy;
- completeness manifests;
- Proof of Registry challenges;
- non-response confirmation;
- Registry reward evidence;
- backpressure;
- rate limits;
- corruption detection;
- derived index rebuild.

## 103. Deferred Features

The MVP MAY postpone:

- paid Registry queries;
- archive-specific reward pool;
- erasure-coded object distribution;
- decentralized object-placement auctions;
- confidential-computing proofs;
- zero-knowledge storage proofs;
- cross-network Registry federation;
- anonymous Registry identities;
- automatic geographic diversity incentives;
- large-artifact permanent storage guarantees;
- proof-of-replication based on specialized hardware.

## 104. Open Questions

The following require further specifications or implementation testing:

- exact Required Registry Profile;
- closed segment size;
- Registry Bond amount;
- maximum synchronization lag;
- minimum independent peer count;
- Snapshot chunk replication factor;
- large-artifact retention policy;
- restricted-object key distribution;
- archive-service economics;
- challenge sampling rate;
- confirmed non-response threshold;
- Registry suspension duration;
- serious misconduct penalties.

## 105. Registry Invariants

- Registry Objects are immutable.
- Derived indexes are rebuildable.
- Canonical Ledger history determines object validity.
- Peer majority does not override consensus finality.
- Every accepted object passes cryptographic verification.
- Duplicate valid objects are idempotent.
- Conflicting content under one Object ID is rejected.
- Pending objects do not satisfy completeness.
- Cache Registry does not qualify as Full Registry.
- Full Registry eligibility depends on the Required Registry Profile.
- Self-reported storage does not prove completeness.
- Inventory Roots do not prove retrievability without challenges.
- Unverified peer data never becomes canonical state.
- Registry replication does not modify Wallet balances.
- Registry rewards remain bounded by the Registry Pool.

## 106. Security Invariants

- Registry discovery does not imply trust.
- Bootstrap peers are not permanent authorities.
- A Registry verifies canonical commitments independently.
- Invalid objects never enter canonical indexes.
- Signed manifest equivocation is preserved as evidence.
- One challenger cannot unilaterally prove non-response.
- Local peer scores do not directly change Ledger Reputation.
- Network partitions do not create alternative Registry consensus.
- Compression and range requests remain bounded.
- Registry Services SHALL tolerate malicious peers without corrupting local canonical state.

## 107. Design Invariants

- Registry replication is continuous and pull-based by default.
- Registry Services compare deterministic inventories.
- Missing objects are retrieved from one or more peers.
- Every object is verified before durable acceptance.
- Full Registry completeness is protocol-defined and versioned.
- Registry Services may prune only outside the required profile.
- Registry history remains auditable.
- Registry failures reduce eligibility before causing penalties.
- Objective evidence is required for misconduct penalties.
- New Registry Services can synchronize without trusting a single operator.
- Snapshot application is delegated to `RFC-0062`.
- Registry replication distributes protocol knowledge but does not replace consensus.
