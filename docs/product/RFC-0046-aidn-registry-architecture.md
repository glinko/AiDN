# RFC-0046 — AiDN Registry Architecture

Status: Draft

Version: 0.3

Supersedes:

* RFC-0046 Version 0.2

Depends on:

* RFC-0036 AiDN Ledger State Machine
* RFC-0039 Hypervisor Service Model
* RFC-0040 AiDN Service Verification Framework
* RFC-0041 Reputation Profile Engine
* RFC-0042 AiDN Hypervisor Network Protocol
* RFC-0044 AiDN Session Protocol
* RFC-0045 AiDN Capability Architecture
* RFC-0047 CometBFT Consensus Integration
* RFC-0048 Epoch Engine
* RFC-0049 Distributed Marketplace and Advertisement Registry
* RFC-0057 Validation Report Specification
* RFC-0058 Participant Eligibility and Sybil Resistance
* RFC-0059 Ledger Operation Catalog
* RFC-0061 Registry Replication Protocol
* RFC-0062 Snapshot and State Sync Protocol
* RFC-0065 Endpoint Certification Derivation and Lifecycle Protocol
* RFC-0066 Protocol Upgrade and Emergency Recovery
* RFC-0067 Protocol Governance and Authorization Policy

---

## 1. Purpose

This document defines the AiDN Registry Architecture.

It specifies:

* the role of Registry Services;
* the boundary between Registry and Ledger;
* Registry object classes;
* canonical and non-canonical objects;
* content addressing;
* object envelopes;
* namespaces;
* storage profiles;
* retention classes;
* object indexing;
* querying;
* object availability;
* Registry manifests;
* consistency commitments;
* privacy and restricted objects;
* object corruption handling;
* Registry lifecycle;
* Service verification;
* reward eligibility boundaries;
* integration with Marketplace, Reputation, Validation and Snapshots.

Registry replication mechanics are defined by RFC-0061.

Snapshot and State Sync mechanics are defined by RFC-0062.

---

## 2. Core Principle

A Registry stores, indexes and serves protocol objects.

A Registry SHALL NOT independently decide canonical protocol state.

Conceptually:

```text
Ledger
    ↓ commits canonical hashes and state
Registry
    ↓ stores and serves referenced objects
Clients
    ↓ verify objects against canonical commitments
```

A Registry response is trustworthy only to the extent that its object can be verified against:

* canonical Ledger state;
* a valid content hash;
* a signed protocol commitment;
* an accepted trust anchor.

---

## 3. Registry Is Not Consensus

Registry Services SHALL NOT independently determine:

* Wallet balances;
* Session Settlement;
* Validator Set;
* Q emission;
* Certification state;
* Governance authorization;
* active Protocol Version;
* canonical Reputation Profile;
* canonical Epoch Result.

These values are determined by canonical State Machine execution.

---

## 4. Registry Is Not the Ledger

The Ledger stores or commits the minimum canonical state required for deterministic protocol operation.

The Registry stores larger or historical objects that would be inefficient or unnecessary to place directly in canonical application state.

Examples include:

* Validation Commitments and optional report mirrors;
* Capability schemas;
* Advertisement documents;
* historical Reputation Events;
* Session evidence;
* artifact metadata;
* Governance review documents;
* Snapshot manifests;
* archived Ledger blocks.

---

## 5. Registry Is Not a Trusted Database

A Registry operator SHALL NOT be trusted merely because it exposes an API or stores a database.

Clients SHALL verify:

* object hash;
* object type;
* canonical reference;
* signature;
* version;
* expiration;
* namespace;
* access policy.

A Registry may be honest, incomplete, outdated, corrupted or malicious.

The architecture assumes verification rather than administrative optimism.

---

## 6. Registry Service

A Registry Service is a Service role operated under RFC-0039.

Every Registry Service SHALL have:

* Service ID;
* owner;
* operating Hypervisor;
* Registry Profile;
* Service Configuration Hash;
* network addresses;
* Health;
* Verification Record;
* Reputation Profile;
* storage commitments.

---

## 7. Registry Identity

```yaml
registry_identity:
  registry_service_id:
  service_public_key:
  owner_wallet:
  operator_hypervisor_id:
  reward_beneficiary:
  registry_profile_id:
  configuration_hash:
  identity_version:
```

Registry identity is separate from:

* Hypervisor Identity;
* Wallet Identity;
* Snapshot identity;
* object author identity;
* content hash.

---

## 8. Registry Responsibilities

A Registry Service MAY perform:

* object ingestion;
* object validation;
* content-addressed storage;
* canonical-reference verification;
* object retrieval;
* historical retention;
* indexing;
* query processing;
* replication;
* inventory publication;
* Snapshot serving;
* availability proofs;
* corruption detection;
* repair synchronization.

The exact responsibilities depend on the Registry Profile.

---

## 9. Registry Non-Responsibilities

A Registry SHALL NOT:

* modify canonical objects;
* reinterpret finalized Ledger Operations;
* fabricate missing signatures;
* replace canonical commitments;
* settle Sessions;
* assign Validators;
* issue Certification;
* change object authorship;
* infer canonical state solely from local indexes.

---

## 10. Registry Object

A Registry Object is an immutable or explicitly versioned data object stored by one or more Registry Services.

Every object SHALL have:

* Object ID;
* Object Type;
* namespace;
* version;
* payload hash;
* canonical encoding;
* author or protocol source;
* retention class;
* access class;
* optional canonical reference.

---

## 11. Object Identity

For immutable content-addressed objects:

```text
object_id
=
HASH(
    object_type
    +
    object_version
    +
    canonical_payload
)
```

The same canonical content SHALL produce the same Object ID.

---

## 12. Object Envelope

```yaml
registry_object:
  object_id:
  object_type:
  object_version:
  namespace:
  network_id:
  chain_id:
  network_revision:
  payload_hash:
  payload_length:
  payload_encoding:
  payload_reference:
  author_subject:
  author_signature:
  canonical_reference:
  parent_object_ids:
  retention_class:
  access_class:
  expiration_epoch:
  created_at:
  object_flags:
```

---

## 13. Canonical Serialization

Object hashing and signing SHALL use deterministic serialization.

Canonical representation SHALL not depend on:

* map ordering;
* whitespace;
* local encoding defaults;
* locale;
* floating-point formatting;
* database serialization.

---

## 14. Object Immutability

A content-addressed object SHALL be immutable.

Updating an object means publishing a new object with:

* a new Object ID;
* a version or replacement reference;
* an optional link to the previous object.

A Registry SHALL NOT modify stored content while preserving the same Object ID.

---

## 15. Mutable Logical Records

Some logical records evolve over time.

Examples include:

* Endpoint Advertisement;
* Reputation Profile;
* Governance Proposal state;
* Registry inventory.

Such records SHALL be represented as immutable versions linked through:

previous_object_id

or another explicit version chain.

---

## 16. Canonical Object

A Canonical Object is an object whose hash, root or state is committed by canonical protocol execution.

Examples include:

* finalized block;
* Ledger Operation;
* Epoch Result Manifest;
* Certification Record;
* Governance Authorization Certificate;
* State Repair Manifest;
* canonical Capability Definition.

---

## 17. Canonical Reference

A Canonical Object SHALL identify its canonical reference.

```yaml
canonical_reference:
  reference_type:
  block_height:
  block_hash:
  operation_id:
  state_key:
  committed_hash:
```

Not all fields apply to every object.

---

## 18. Non-Canonical Object

A Non-Canonical Object is not independently part of canonical state.

Examples include:

* public analysis;
* optional Marketplace metadata;
* operator documentation;
* subjective commentary;
* unfinalized evidence;
* diagnostic logs;
* test results.

A Non-Canonical Object SHALL NOT be presented as canonical merely because a Registry stores it.

---

## 19. Pending Object

A Registry MAY temporarily store an object awaiting canonical commitment.

The object SHALL be marked:

PENDING_CANONICAL_REFERENCE

If the expected commitment does not finalize, the object remains non-canonical or expires.

---

## 20. Orphaned Object

An object whose expected canonical reference never finalized MAY become:

ORPHANED

Orphaned objects MAY be retained for diagnostics.

They SHALL not appear in canonical query results by default.

---

## 21. Object Classes

Initial Registry Object classes include:

LEDGER_HISTORY
PROTOCOL_DEFINITION
SERVICE_METADATA
MARKETPLACE
SESSION_EVIDENCE
USAGE_AND_SETTLEMENT
VALIDATION
CERTIFICATION
REPUTATION
GOVERNANCE
EPOCH
SNAPSHOT
SECURITY_AND_RECOVERY
ARTIFACT_METADATA

---

## 22. Ledger History Objects

May include:

* blocks;
* block headers;
* Ledger Operations;
* operation receipts;
* State Roots;
* Validator Set updates;
* consensus evidence.

Archive retention requirements depend on Registry Profile.

---

## 23. Protocol Definition Objects

May include:

* RFC manifests;
* Capability Definitions;
* schemas;
* validation profiles;
* conformance profiles;
* economic parameter sets;
* Task Set definitions;
* upgrade manifests.

---

## 24. Service Metadata Objects

May include:

* Service registrations;
* Service Configuration manifests;
* Service Verification Records;
* Service Network Advertisements;
* Health history;
* dependency manifests.

---

## 25. Marketplace Objects

May include:

* active Endpoint Advertisements;
* current withdrawal notices;
* Pricing Policies;
* Accounting Contracts;
* Session Policies;
* Data Handling Policies;
* Proxy Declarations;
* Failover Policies;
* Endpoint availability records;
* historical Advertisement versions.

Detailed Marketplace behavior is defined by RFC-0049.

---

## 26. Session Evidence Objects

May include:

* Session Contracts;
* Request manifests;
* result manifests;
* stream roots;
* artifact descriptors;
* recovery records;
* failure reports.

Raw private payloads SHOULD NOT be public by default.

---

## 27. Usage and Settlement Objects

May include:

* Usage Reports;
* Checkpoints;
* checkpoint acknowledgments;
* Settlement proposals;
* Forced Settlement evidence;
* settlement explanations.

Canonical economic results remain in Ledger state.

---

## 28. Validation Objects

May include:

* Validation Assignment commitments;
* concealed offer records;
* Validation Commitments;
* optional Validation Report mirrors;
* evidence manifests;
* report reveal records;
* assignment failure records.

---

## 29. Certification Objects

May include:

* Certification Records;
* Certification observations;
* expiration records;
* revocation records;
* recovery validation history;
* Configuration Hash references.

---

## 30. Reputation Objects

May include:

* Reputation Events;
* Profile snapshots;
* score derivation references;
* correction records;
* historical flags;
* Marketplace explanations.

---

## 31. Governance Objects

May include:

* Governance Proposals;
* review documents;
* Chamber Snapshots;
* votes;
* Economic Signals;
* Authorization Certificates;
* Council records;
* emergency-action records.

---

## 32. Epoch Objects

May include:

* Epoch Transition objects;
* Participant Snapshots;
* Service Snapshots;
* Task Results;
* reward calculations;
* Epoch Result Manifests;
* challenge and correction records.

---

## 33. Snapshot Objects

May include:

* Snapshot Manifests;
* Snapshot chunks;
* State Sync metadata;
* provider commitments;
* availability proofs;
* restoration test results.

Detailed behavior is defined by RFC-0062.

---

## 34. Security and Recovery Objects

May include:

* security incident commitments;
* State Repair Manifests;
* Network Recovery Manifests;
* emergency-action evidence;
* conflicting-signature evidence;
* key-rotation history.

---

## 35. Artifact Metadata Objects

May include:

* artifact descriptors;
* content hashes;
* content types;
* retention deadlines;
* access policies;
* storage references.

Registry Services MAY store artifact bytes where their profile permits it.

---

## 36. Registry Namespace

Every object SHALL belong to a namespace.

Initial namespaces include:

ledger
protocol
service
marketplace
session
usage
validation
certification
reputation
governance
epoch
snapshot
security
artifact

---

## 37. Namespace Purpose

Namespaces support:

* access control;
* retention policy;
* indexing;
* replication policy;
* profile requirements;
* query routing;
* proof scope.

Namespace does not replace Object Type.

---

## 38. Namespace Isolation

An object SHALL NOT be served under an unrelated namespace merely to bypass:

* retention policy;
* access restrictions;
* completeness requirements;
* validation rules;
* query limits.

---

## 39. Registry Profiles

The initial Registry Profiles are:

FULL
ARCHIVE
CACHE
SNAPSHOT_PROVIDER
HYBRID

---

## 40. Full Registry

A Full Registry stores the required current protocol object set and a bounded recent history.

It is intended for:

* ordinary network operation;
* current Marketplace discovery;
* recent Validation evidence;
* current Governance;
* recent Epoch data;
* current protocol definitions.

---

## 41. Full Registry Requirements

A Full Registry SHALL retain at least:

* all currently active protocol definitions;
* current Service metadata;
* current active Endpoint Advertisements;
* current Advertisement withdrawal notices;
* current Pricing Policy, Accounting Contract, Proxy Declaration and Failover Policy objects referenced by active Endpoint Advertisements;
* active Certification records;
* current Reputation Profiles;
* recent Ledger history;
* recent Epoch Results;
* required recent Validation Commitments, custody records and Settlement evidence;
* current Snapshot metadata.

Exact retention windows are versioned.

---

## 42. Archive Registry

An Archive Registry stores long-term or complete historical data.

It MAY retain:

* all finalized blocks;
* all Ledger Operations;
* historical protocol versions;
* complete governance history;
* historical Registry objects;
* retired Endpoints;
* expired Certification;
* old Reputation Events;
* previous Network Revision history.

---

## 43. Archive Completeness

An Archive Registry SHALL define its claimed historical range.

Examples:

GENESIS_TO_CURRENT
HEIGHT_RANGE
EPOCH_RANGE
NETWORK_REVISION_RANGE
NAMESPACE_RANGE

An Archive Registry SHALL NOT claim complete history outside its declared range.

---

## 44. Cache Registry

A Cache Registry stores objects opportunistically.

It may optimize:

* geographic latency;
* popular-object delivery;
* artifact distribution;
* temporary Session evidence;
* Snapshot chunks.

Cache Registries are not expected to satisfy Full or Archive completeness.

---

## 45. Cache Expiration

A Cache Registry MAY evict objects according to local policy.

It SHALL preserve:

* correct object hashes;
* accurate availability claims;
* profile disclosures.

It SHALL not claim durable retention it does not provide.

---

## 46. Snapshot Provider

A Snapshot Provider stores and serves State Sync Snapshots.

It SHALL support:

* Snapshot Manifest retrieval;
* chunk retrieval;
* resumable transfer;
* hash verification;
* retention declaration;
* availability reporting.

Snapshot correctness rules belong to RFC-0062.

---

## 47. Hybrid Registry

A Hybrid Registry implements more than one profile.

Example:

FULL
+
SNAPSHOT_PROVIDER

or:

ARCHIVE
+
CACHE

Each profile SHALL be verified and reported separately.

---

## 48. Profile Independence

Passing verification for one Registry Profile SHALL NOT automatically prove another.

A Registry may be:

VERIFIED as FULL
UNVERIFIED as ARCHIVE

---

## 49. Registry Profile Declaration

```yaml
registry_profile_declaration:
  registry_service_id:
  supported_profiles:
  namespace_coverage:
  history_coverage:
  retention_policy_hash:
  storage_policy_hash:
  replication_policy_hash:
  snapshot_policy_hash:
  configuration_hash:
```

---

## 50. Profile Change

A material Registry Profile change SHALL require:

* new Configuration Hash;
* updated profile declaration;
* possible reverification;
* updated Marketplace or network metadata;
* preservation of previous history.

---

## 51. Retention Classes

Initial retention classes are:

EPHEMERAL
SESSION_BOUND
RECENT
ACTIVE_LIFECYCLE
LONG_TERM
PERMANENT_ARCHIVE

---

## 52. Ephemeral Retention

Used for objects with short operational value.

Examples include:

* temporary transfer metadata;
* uncommitted diagnostics;
* short-lived discovery data.

---

## 53. Session-Bound Retention

Used for objects retained through:

* Session activity;
* Settlement;
* challenge window;
* evidence expiration.

The retention deadline SHALL be deterministic from Session policy.

---

## 54. Recent Retention

Used for objects retained for a fixed recent Epoch or block window.

Examples include:

* recent Ledger history;
* recent Health events;
* recent Registry challenges.

---

## 55. Active-Lifecycle Retention

Used while the referenced protocol object remains active.

Examples include:

* current Endpoint Advertisement;
* current Advertisement withdrawal notice;
* current Pricing Policy, Accounting Contract, Proxy Declaration or Failover Policy referenced by an active Advertisement;
* active Capability Definition;
* active Governance Proposal;
* valid Certification.

A historical replacement record SHOULD remain after deactivation.

---

## 56. Long-Term Retention

Used for important historical audit objects.

Examples include:

* optional mirrored Validation Reports;
* Settlement evidence;
* Reputation corrections;
* Governance votes.

---

## 57. Permanent Archive

Used for objects that Archive Registries commit to retaining indefinitely or for the network's supported lifetime.

Examples may include:

* finalized block history;
* protocol upgrade history;
* State Repair history;
* Network Recovery Manifests.

---

## 58. Retention Policy

Every Registry SHALL publish a versioned Retention Policy.

```yaml
registry_retention_policy:
  registry_service_id:
  profile_id:
  namespace_rules:
  object_type_rules:
  minimum_retention:
  eviction_rules:
  legal_or_operator_exceptions:
  policy_version:
```

---

## 59. No Hidden Eviction

A Registry SHALL NOT claim an object as durably retained while applying an undisclosed earlier eviction policy.

Actual availability may still fail because of outage or corruption.

---

## 60. Expired Object

An expired object MAY remain retrievable.

Expiration means:

* the Registry is no longer required to retain it under that policy;
* clients should not depend on continued availability;
* it may be omitted from current indexes.

Expiration does not change the Object ID.

---

## 61. Tombstone

Logical removal or replacement SHALL use an immutable Tombstone Object where required.

```yaml
registry_tombstone:
  target_object_id:
  reason:
  replacement_object_id:
  effective_epoch:
  author_subject:
  signature:
```

A Tombstone does not erase the underlying historical object from Archive Registries.

---

## 62. Content-Addressed Storage

Registry storage SHOULD use content addressing internally or preserve equivalent integrity guarantees.

An object retrieved by Object ID SHALL match that Object ID.

---

## 63. Deduplication

Identical immutable objects MAY be stored once and referenced from several logical indexes.

Deduplication SHALL NOT merge objects with different:

* Object Type;
* canonical encoding;
* access policy;
* network domain.

---

## 64. Object Ingestion

A Registry ingesting an object SHALL verify as applicable:

* schema;
* Object ID;
* payload hash;
* network domain;
* author signature;
* object version;
* canonical reference;
* access policy;
* size limit;
* namespace policy.

---

## 65. Ingestion States

RECEIVED
VALIDATING
STORED
INDEXED
REJECTED
QUARANTINED

---

## 66. Quarantined Object

An object MAY be quarantined when:

* its signature is valid but canonical status is unknown;
* its parent is missing;
* its schema is unknown but potentially compatible;
* malware or unsafe content is suspected;
* its canonical reference cannot currently be verified.

Quarantined objects SHALL not appear in ordinary trusted queries.

---

## 67. Invalid Object

An object SHALL be rejected when:

* payload hash mismatches;
* signature is invalid;
* network domain is invalid;
* Object ID conflicts with content;
* mandatory schema is invalid;
* prohibited size is exceeded;
* canonical reference is objectively false.

---

## 68. Conflicting Object

Two objects may conflict at the logical-record level.

Examples include:

* two Advertisement versions claiming the same sequence;
* conflicting signed Registry manifests;
* conflicting Governance votes;
* conflicting Usage Reports.

The Registry SHALL retain conflict evidence where policy requires it.

It SHALL not silently choose the friendlier version.

---

## 69. Canonical Resolution

When conflicting objects have canonical outcomes, the Registry SHALL index the canonical result while preserving relevant conflict history.

Canonical resolution derives from Ledger state or another explicit protocol rule.

---

## 70. Registry Index

A Registry Index is a derived query structure.

Indexes MAY support:

* Object ID;
* Object Type;
* namespace;
* author;
* Endpoint;
* Capability;
* Session;
* Epoch;
* block height;
* Configuration Hash;
* Certification state;
* Reputation state.

---

## 71. Index Is Not Canonical State

A Registry index may be:

* incomplete;
* stale;
* corrupted;
* implementation-specific.

Clients SHALL verify returned objects.

Index output SHALL not itself replace canonical evidence.

---

## 72. Rebuildable Index

Indexes SHOULD be rebuildable from retained objects and canonical commitments.

Loss of an index SHALL not imply loss of the underlying objects.

---

## 73. Derived View

A Registry MAY publish derived views such as:

* active Endpoints by Capability;
* current Certified Endpoints;
* recent Validation failures;
* Governance participation;
* historical price changes.

Derived views SHALL identify:

* source objects;
* calculation version;
* freshness;
* non-canonical status.

---

## 74. Query Interface

A Registry SHOULD support:

GET_OBJECT
GET_OBJECT_METADATA
QUERY_OBJECTS
GET_VERSION_CHAIN
GET_CANONICAL_REFERENCE
GET_INVENTORY
GET_MANIFEST
GET_PROOF
SUBSCRIBE_OBJECTS

Exact transport messages use RFC-0042.

---

## 75. Get Object

GET_OBJECT retrieves one exact Object ID.

The response SHALL include:

* Object Envelope;
* payload or payload reference;
* Registry source;
* retrieval metadata;
* optional proof.

---

## 76. Query Objects

QUERY_OBJECTS MAY filter by:

* namespace;
* Object Type;
* subject;
* version;
* block range;
* Epoch range;
* creation time;
* canonical status;
* active status.

Query results SHALL be bounded and paginated.

---

## 77. Query Pagination

Pagination SHALL use stable cursors or deterministic ordering.

A cursor SHALL bind to:

* query hash;
* Registry view version;
* expiration;
* position.

---

## 78. Query Consistency

A Registry SHOULD declare query consistency:

CURRENT_BEST_EFFORT
SNAPSHOT_CONSISTENT
CANONICAL_HEIGHT_BOUND
HISTORICAL_FIXED

---

## 79. Canonical Height-Bound Query

A query MAY request objects canonical at or before a specific finalized height.

The Registry SHALL not mix later mutable-view updates into that result without disclosure.

---

## 80. Query Freshness

Every query response SHOULD include:

* observed canonical height;
* Network Revision;
* index-update time;
* object-set freshness;
* known synchronization lag.

---

## 81. Query Limits

Registries MAY enforce:

* maximum result count;
* maximum query complexity;
* maximum time range;
* maximum response bytes;
* rate limits;
* access controls.

Limits SHALL be published.

---

## 82. Subscription

A client MAY subscribe to object updates for a bounded scope.

Examples include:

* new Endpoint Advertisements;
* Certification changes;
* Governance Proposal updates;
* new Epoch Results.

Subscriptions are delivery conveniences.

Canonical changes still require independent verification.

---

## 83. Object Availability

An object is available when a Registry can serve valid content matching its declared Object ID within protocol limits.

Availability SHALL NOT be inferred only from an inventory claim.

---

## 84. Inventory

A Registry MAY publish compact inventory data describing stored object ranges or sets.

Inventory MAY use:

* namespace roots;
* segment roots;
* range manifests;
* Bloom filters;
* Merkle trees;
* content-set summaries.

Detailed replication inventory is defined by RFC-0061.

---

## 85. Registry Manifest

A Registry Manifest commits to a bounded view of stored content.

```yaml
registry_manifest:
  registry_service_id:
  profile_id:
  manifest_scope:
  network_revision:
  start_reference:
  end_reference:
  namespace_roots:
  object_count:
  total_declared_bytes:
  generated_at:
  expiration:
  previous_manifest_hash:
  signature:
```

---

## 86. Manifest Scope

A Manifest SHALL clearly identify whether it covers:

* one namespace;
* several namespaces;
* one block range;
* one Epoch range;
* one Registry Profile;
* one Snapshot set;
* all current required objects.

---

## 87. Manifest Is a Signed Claim

A valid Manifest proves that the Registry signed the claim.

It does not prove that:

* all objects are actually retrievable;
* storage is durable;
* the Registry remains online;
* the claim is complete.

Challenge and Duty Proof provide additional evidence.

---

## 88. Manifest Equivocation

Conflicting signed Manifests for the same:

* Registry Service;
* scope;
* sequence;
* generation boundary;

constitute objective evidence of equivocation.

---

## 89. Segment

Large Registry scopes MAY be divided into deterministic segments.

A segment MAY be based on:

* Object ID prefix;
* namespace;
* block range;
* Epoch range;
* Object Type;
* Snapshot chunk range.

---

## 90. Segment Root

Each segment SHALL have a deterministic root.

```text
segment_root
=
MERKLE_ROOT(sorted_object_commitments)
```

The exact ordering and commitment structure SHALL be versioned.

---

## 91. Completeness

Registry completeness is evaluated relative to:

* declared Registry Profile;
* namespace coverage;
* historical range;
* required object set;
* canonical commitments.

A Cache Registry is not incomplete merely because it lacks Archive history.

---

## 92. Completeness Root

A profile MAY define a required-set root for one Epoch or range.

The Registry proves correspondence between:

* required-set root;
* stored segment roots;
* challenge responses.

---

## 93. Availability Proof

An Availability Proof demonstrates that a Registry served a requested object or segment within defined conditions.

It MAY include:

* Challenge ID;
* requested Object ID;
* response hash;
* response deadline;
* Registry signature;
* challenger acknowledgment;
* transfer evidence.

---

## 94. Availability Does Not Prove Durability

Serving one object once does not prove long-term retention.

Repeated challenges and historical behavior contribute to Registry Reputation and eligibility.

---

## 95. Registry Verification

Registry Services SHALL be verified under RFC-0040.

Verification MAY include:

* identity control;
* protocol conformance;
* profile declaration;
* object retrieval;
* segment-root checks;
* manifest consistency;
* synchronization lag;
* Snapshot serving where declared;
* repair synchronization.

---

## 96. Continuous Verification

Successful real Registry duties MAY maintain Verification status.

Examples include:

* repeated object challenges;
* valid manifests;
* successful Snapshot transfer;
* synchronized canonical height;
* correct replication behavior.

---

## 97. Registry Health

Registry Health MAY include:

* network availability;
* query latency;
* synchronization lag;
* object retrieval success;
* storage pressure;
* manifest freshness;
* replication backlog;
* corruption rate;
* Snapshot availability.

---

## 98. Self-Reported Metrics

Self-reported metrics MAY support diagnostics.

They SHALL NOT alone establish:

* completeness;
* reward eligibility;
* durable retention;
* valid Snapshot availability.

---

## 99. Registry Reputation

The Registry Reputation Profile may include:

REGISTRY_AVAILABILITY
PROOF_SUCCESS
COMPLETENESS_RELIABILITY
OBJECT_INTEGRITY
SYNCHRONIZATION_RELIABILITY
QUERY_SERVICE_RELIABILITY
SNAPSHOT_DELIVERY_RELIABILITY
RECOVERY_RELIABILITY

---

## 100. Registry Eligibility

Registry reward or duty eligibility MAY require:

* valid Registry registration;
* verified Registry Profile;
* minimum Service age;
* acceptable Health;
* acceptable Reputation;
* successful Duty Proof;
* acceptable synchronization lag;
* required Stake or Bond;
* no active suspension.

---

## 101. Registration Does Not Earn Rewards

A Registry SHALL NOT receive Q merely because it:

* registers;
* reports disk size;
* publishes a Manifest;
* claims Archive status;
* exposes an API;
* stores popular public files.

Rewards require protocol-defined qualifying work.

---

## 102. Registry Work Evidence

Rewardable work MAY include:

* successful object availability;
* profile completeness;
* replication contribution;
* Snapshot serving;
* challenge response;
* repair assistance;
* sustained synchronized service.

The exact economic formula is defined elsewhere.

---

## 103. No Storage-Size-Only Reward

Declared or measured storage size SHALL NOT alone determine Registry reward.

Otherwise operators are encouraged to store useless duplication while ignoring required objects, a strategy already perfected by many shared drives.

---

## 104. Known Control Groups

Registry independence SHALL account for Known Control Groups.

Several Registry Services under common control SHALL NOT automatically count as independent replicas.

---

## 105. Shared Infrastructure

Registries MAY share:

* storage providers;
* datacenters;
* network providers;
* software;
* object backends.

Shared infrastructure is permitted.

It SHALL be reflected in failure-domain analysis where known.

---

## 106. Geographic and Operator Diversity

The network MAY use diversity factors for:

* reward allocation;
* recommended query sources;
* Snapshot recommendations;
* bootstrap peer selection;
* replication targets.

Diversity is not proven solely by IP geography.

---

## 107. Registry Replication

Replication SHALL follow RFC-0061.

At the architectural level, replication SHALL preserve:

* Object IDs;
* payload hashes;
* namespaces;
* access classes;
* canonical references;
* version chains;
* retention metadata.

---

## 108. No Rewriting During Replication

A receiving Registry SHALL NOT:

* rewrite object payloads;
* replace author signatures;
* change Object IDs;
* alter canonical references;
* silently weaken access policy.

Local storage encoding may differ if retrieved canonical content remains identical.

---

## 109. Replication Source Trust

A Registry SHALL verify received objects independently.

A trusted peer connection does not make every replicated object valid.

---

## 110. Partial Replication

A Registry MAY replicate only:

* selected namespaces;
* selected ranges;
* selected Object Types;
* selected profiles.

Its profile declaration SHALL accurately describe the result.

---

## 111. Replication Lag

Registry synchronization lag SHALL be measurable relative to:

* canonical height;
* latest required object commitment;
* latest Manifest;
* latest Epoch Result;
* latest Snapshot set.

---

## 112. Corruption Detection

A Registry SHOULD periodically verify:

* stored Object IDs;
* payload hashes;
* segment roots;
* database indexes;
* Manifest correspondence;
* storage readability.

---

## 113. Corrupted Object

A corrupted local object SHALL:

* be removed from ordinary serving;
* be marked for repair;
* trigger local alert;
* avoid continued Manifest inclusion;
* be recovered from another valid source where possible.

---

## 114. Corruption Is Not Canonical Deletion

Local corruption does not change:

* Object ID;
* canonical reference;
* historical validity;
* other Registry copies.

---

## 115. Repair Synchronization

A Registry MAY repair missing or corrupted objects through RFC-0061.

Repair SHALL verify the complete object before reinsertion.

---

## 116. Index Corruption

A corrupt index SHOULD be rebuilt.

The Registry SHALL not delete valid objects merely because an index temporarily lost their references.

---

## 117. Storage Failure

When storage failure threatens profile requirements, the Registry SHOULD enter:

DEGRADED

or:

DRAINING

and update its public Health.

---

## 118. Graceful Draining

A draining Registry SHOULD:

* stop accepting new retention commitments;
* publish reduced availability;
* complete active transfers where possible;
* assist replication of at-risk objects;
* preserve manifests and history;
* retire cleanly.

---

## 119. Registry Retirement

Retirement SHALL:

* stop new duties;
* preserve Registry identity history;
* preserve Verification and Reputation history;
* not erase prior Manifest obligations;
* allow applicable Stake or Bond release only after pending obligations resolve.

---

## 120. Registry Replacement

Changing storage software or hardware MAY preserve Registry identity when:

* Service Identity remains valid;
* profile behavior remains compatible;
* object commitments remain available;
* Configuration compatibility is established;
* required verification passes.

---

## 121. Registry Relocation

A Registry may relocate between Hypervisors.

Relocation SHALL preserve:

* Service Identity;
* object commitments;
* manifests;
* profile declaration;
* history;
* Reputation.

Network advertisements SHALL be updated.

---

## 122. Network Protocol Integration

Registry communication SHALL use the REGISTRY channel class from RFC-0042.

Bulk transfers SHALL use:

* bounded streams;
* chunk hashes;
* Transfer IDs;
* resume support;
* low or background priority.

---

## 123. Critical Query Priority

Small canonical object requests SHOULD be prioritized over large historical replication.

Examples include:

* current Capability Definition;
* active Endpoint Advertisement;
* Governance Authorization Certificate;
* current Snapshot Manifest.

---

## 124. Snapshot Integration

Registry Architecture supports Snapshot metadata and optional Snapshot bytes.

Snapshot trust, generation and State Sync are defined by RFC-0062.

A Registry serving a Snapshot does not make that Snapshot canonical by itself.

---

## 125. Snapshot Trust Anchor

Clients SHALL verify Snapshot data against an accepted:

* finalized State Root;
* block hash;
* Network Revision;
* Snapshot Manifest;
* protocol version.

---

## 126. Marketplace Integration

Marketplace objects are stored through Registry Services.

The Registry SHALL support querying by:

* Capability ID;
* Endpoint ID;
* active Advertisement;
* current withdrawal state;
* price profile;
* Accounting Mode;
* Certification state;
* Reputation reference;
* Proxy disclosure.

Registry results remain verifiable object sets, not Marketplace recommendations.

---

## 127. Recommendation Separation

A Registry MAY expose a local ranking or recommendation.

Such ranking SHALL be marked non-canonical.

The Registry SHALL not represent its ranking as protocol Reputation or governance preference.

---

## 128. Validation Integration

Compact Validation Commitments and custody-availability records SHALL be indexable through Registry Services.

The complete Validation Report is stored by the validated Endpoint Hypervisor as mandatory origin custody. Registry Services MAY act as immutable mirrors or caches, but Full Registry conformance SHALL NOT require replication of every complete Validation Report or Evidence Bundle.

The Registry SHALL:

* preserve commitment and report hashes;
* preserve Storage Receipt and Storage Failure references;
* preserve report Configuration Hash references;
* preserve evidence roots;
* enforce access policy;
* distinguish pending and revealed reports.

The stable logical locator SHALL resolve through the current Endpoint-to-Hypervisor route. Registry indexes SHALL NOT replace it with one operator-specific transport URL.

---

## 129. Certification Integration

Certification derivation uses canonical Validation evidence and protocol rules.

A Registry stores:

* Validation Commitments and custody state;
* optional report mirrors;
* Certification Records;
* observations;
* history.

It does not independently certify Endpoints.

An optional mirror may preserve evidence after origin loss, but SHALL NOT clear the Endpoint's custody failure or Reputation history.

---

## 130. Reputation Integration

The Registry stores Reputation Events and Profile history.

The canonical current Profile is determined by RFC-0041 and Epoch processing.

A local Registry index may provide explanations and historical searches.

---

## 131. Governance Integration

The Registry SHALL retain enough governance history to audit:

* Proposal versions;
* sponsorship;
* Chamber Snapshots;
* votes;
* Economic Signals;
* Authorization Certificates;
* emergency actions;
* mode transitions.

---

## 132. Upgrade Integration

Before a major protocol upgrade, the Registry network SHOULD ensure availability of:

* Release Manifests;
* Migration Manifests;
* test vectors;
* pre-upgrade Snapshot;
* post-upgrade protocol definitions.

---

## 133. Protocol Versioned Objects

Every object whose semantics depend on protocol rules SHALL identify:

* Protocol Version;
* schema version;
* Object Version;
* Network Revision.

---

## 134. Unknown Object Version

A Registry MAY store an unknown future object version as opaque content when:

* basic envelope is valid;
* size limits are satisfied;
* network domain is valid;
* access policy permits it.

It SHALL NOT claim semantic validation.

---

## 135. Deprecated Object Version

Deprecated objects MAY remain stored and queryable.

New logical records SHOULD use the active version.

---

## 136. Restricted Objects

Some Registry Objects may be restricted.

Examples include:

* private Session evidence;
* sealed Validation evidence;
* encrypted dispute material;
* sensitive security reports;
* access-controlled artifacts.

---

## 137. Access Classes

Initial access classes are:

PUBLIC
AUTHENTICATED
SUBJECT_ONLY
PARTICIPANT_SET
PROTOCOL_AUTHORITY
ENCRYPTED_OPAQUE

---

## 138. Public Object

A Public Object may be retrieved by any client subject to rate limits.

---

## 139. Authenticated Object

Requires an authenticated AiDN identity.

Authentication does not necessarily imply permission to decrypt the payload.

---

## 140. Subject-Only Object

May be retrieved only by one or more identified protocol subjects.

Example:

* Consumer and Endpoint;
* assigned Validator;
* Service owner.

---

## 141. Participant-Set Object

May be retrieved by a committed participant group.

Examples include:

* Governance Chamber members;
* selected Validation actors;
* recovery authorities.

---

## 142. Protocol-Authority Object

Access requires a protocol-defined authority or threshold-controlled process.

This class SHOULD be used sparingly.

---

## 143. Encrypted Opaque Object

The Registry stores ciphertext and metadata.

The Registry may be unable to read the payload.

It SHALL still verify:

* ciphertext hash;
* size;
* envelope;
* retention metadata;
* access references.

---

## 144. Registry Cannot Guarantee Confidentiality Alone

A Registry can enforce access controls and store encrypted objects.

End-to-end confidentiality ultimately depends on:

* encryption;
* key distribution;
* client behavior;
* authorized recipient security.

---

## 145. Data Minimization

Public Registry objects SHOULD avoid unnecessary inclusion of:

* raw prompts;
* private outputs;
* personal data;
* OAuth tokens;
* API keys;
* internal topology;
* secrets;
* unrelated Session content.

---

## 146. Malicious Content

Registry Services SHOULD treat stored payloads as untrusted.

They SHOULD apply:

* content-size limits;
* safe metadata parsing;
* decompression limits;
* sandboxed preview generation;
* malware scanning where applicable;
* no automatic execution.

---

## 147. Artifact Execution Prohibition

A Registry SHALL NOT automatically execute:

* uploaded scripts;
* model files;
* binaries;
* document macros;
* container images;

merely to index or preview them.

---

## 148. Query Privacy

Queries may reveal user interests and network activity.

Privacy-sensitive clients MAY:

* query several Registries;
* use relays;
* retrieve by Object ID;
* use local indexes;
* avoid centralized recommendation APIs.

---

## 149. Registry Logs

Registry operators SHOULD minimize retention of:

* client IP addresses;
* private query text;
* access tokens;
* restricted-object access history.

Required audit logs SHALL be policy-defined.

---

## 150. Registry Security Threats

The architecture SHALL account for:

* object substitution;
* Object ID collision attempts;
* manifest equivocation;
* false availability;
* incomplete profile claims;
* stale query results;
* index poisoning;
* access-control bypass;
* malicious payloads;
* replication poisoning;
* retention dishonesty;
* Sybil Registry identities;
* shared failure domains;
* Snapshot substitution.

---

## 151. Object Substitution Protection

A Registry SHALL not return content that fails the requested Object ID.

Clients SHALL verify every retrieved object hash.

---

## 152. Index Poisoning Protection

Indexes SHALL be derived only from:

* validated object envelopes;
* valid signatures where required;
* correct namespaces;
* explicit canonical references.

Invalid objects SHALL not become visible merely because indexing code parsed them enthusiastically.

---

## 153. Stale Data Protection

Query responses SHOULD expose:

* current Registry synchronization height;
* object freshness;
* index freshness;
* Manifest timestamp;
* known lag.

Clients MAY reject stale results.

---

## 154. False Availability Claim

Repeated inability to serve objects included in a signed current Manifest may create:

* failed Duty Proof;
* Health degradation;
* Reputation events;
* eligibility loss;
* penalty where an explicit rule applies.

---

## 155. Manifest Fraud

Objectively conflicting or fabricated Manifests may create:

* critical Verification failure;
* critical Reputation flag;
* Service suspension;
* penalty under an applicable economic rule.

---

## 156. Profile Overclaiming

A Registry claiming Archive or Full coverage without satisfying the declared scope SHALL fail relevant verification.

Profile claims SHALL be public and hash-bound.

---

## 157. Registry Sybil Resistance

Creating many Registry identities SHALL not automatically create:

* more rewards;
* more governance votes;
* more independent availability;
* more Snapshot trust.

Known Control Group and contribution rules apply.

---

## 158. Registry Service Operations

RFC-0059 SHOULD support operations equivalent to:

REGISTRY_SERVICE_REGISTER
REGISTRY_PROFILE_UPDATE
REGISTRY_MANIFEST_COMMIT
REGISTRY_AVAILABILITY_PROOF_COMMIT
REGISTRY_VERIFICATION_COMMIT
REGISTRY_SUSPEND
REGISTRY_REINSTATE
REGISTRY_RETIRE

Exact schemas remain in RFC-0059.

---

## 159. Registry Registration

Registry registration SHALL include:

* Service ID;
* profile declaration;
* Configuration Hash;
* owner;
* operator;
* Reward Beneficiary;
* public network metadata;
* policy hashes.

Registration does not prove object availability.

---

## 160. Manifest Commitment

A signed Registry Manifest MAY be committed to Ledger or another canonical object when required for:

* Duty Proof;
* reward eligibility;
* Snapshot availability;
* challenge generation;
* profile verification.

Not every operational Manifest must be individually placed on-chain.

---

## 161. Epoch Integration

RFC-0048 SHALL support Registry-related tasks including:

Freeze Registry Eligibility
Freeze Registry Profile State
Finalize Registry Manifests
Generate Registry Challenges
Evaluate Challenge Responses
Calculate Registry Health
Calculate Registry Completeness
Calculate Registry Work Units
Process Registry Failures
Update Registry Reputation
Schedule Repair Verification
Select Snapshot Providers
Publish Registry Metrics

---

## 162. Registry Challenge Scheduling

Challenge scheduling SHALL follow RFC-0061.

At the architectural level, challenges SHALL be:

* bounded;
* unpredictable;
* profile-relevant;
* replay-protected;
* independently verifiable.

---

## 163. Registry Reward Boundary

Registry reward calculation SHALL use verified protocol contribution.

It SHALL not reward:

* registration alone;
* self-reported disk capacity alone;
* duplicate Services under common control as independent replicas;
* serving only self-selected easy objects;
* unavailable objects claimed in stale Manifests.

---

## 164. Error Codes

The MVP SHALL define at least:

REGISTRY_OBJECT_NOT_FOUND
REGISTRY_OBJECT_INVALID
REGISTRY_OBJECT_HASH_MISMATCH
REGISTRY_OBJECT_SCHEMA_INVALID
REGISTRY_OBJECT_VERSION_UNSUPPORTED
REGISTRY_OBJECT_NETWORK_MISMATCH
REGISTRY_OBJECT_ACCESS_DENIED
REGISTRY_OBJECT_EXPIRED
REGISTRY_CANONICAL_REFERENCE_INVALID
REGISTRY_CANONICAL_REFERENCE_UNAVAILABLE
REGISTRY_OBJECT_ORPHANED
REGISTRY_OBJECT_QUARANTINED
REGISTRY_OBJECT_CONFLICT
REGISTRY_PROFILE_UNSUPPORTED
REGISTRY_PROFILE_SCOPE_MISMATCH
REGISTRY_RETENTION_POLICY_VIOLATION
REGISTRY_MANIFEST_INVALID
REGISTRY_MANIFEST_EXPIRED
REGISTRY_MANIFEST_CONFLICT
REGISTRY_SEGMENT_ROOT_MISMATCH
REGISTRY_QUERY_INVALID
REGISTRY_QUERY_LIMIT_EXCEEDED
REGISTRY_CURSOR_INVALID
REGISTRY_CURSOR_EXPIRED
REGISTRY_INDEX_STALE
REGISTRY_TRANSFER_INVALID
REGISTRY_TRANSFER_INCOMPLETE
REGISTRY_STORAGE_UNAVAILABLE
REGISTRY_CORRUPTION_DETECTED
REGISTRY_REPAIR_REQUIRED

---

## 165. Idempotency

The following SHALL be idempotent:

* immutable object ingestion;
* object retrieval;
* Manifest commitment;
* Availability Proof commitment;
* Tombstone ingestion;
* replication of an existing object;
* Profile update with the same version;
* retirement submission.

The same valid Object ID SHALL not create duplicate logical content.

---

## 166. Conformance Testing

Registry implementations SHALL be tested for:

* valid object ingestion;
* invalid hash rejection;
* invalid signature rejection;
* namespace enforcement;
* canonical-reference verification;
* version chains;
* query pagination;
* stale cursor handling;
* Manifest generation;
* Manifest conflict detection;
* segment-root calculation;
* profile coverage;
* access control;
* encrypted opaque objects;
* corruption detection;
* repair synchronization;
* draining and retirement.

---

## 167. Reference Registry Harness

The AiDN project SHOULD provide a Registry Conformance Harness capable of:

* submitting valid and invalid objects;
* verifying Object IDs;
* querying by namespace and type;
* testing profile completeness;
* generating segment roots;
* testing Manifest behavior;
* simulating corruption;
* testing repair;
* testing restricted access;
* measuring synchronization lag.

---

## 168. Observability

A Registry SHOULD expose:

* active profiles;
* canonical synchronization height;
* Namespace coverage;
* stored object count;
* logical and physical storage;
* Manifest age;
* replication backlog;
* query latency;
* object retrieval success;
* corruption count;
* repair state;
* Snapshot availability;
* current Health.

---

## 169. Registry Metrics

The network SHOULD publish aggregate metrics including:

* eligible Registry count;
* independent Known Control Groups;
* profile distribution;
* namespace coverage;
* average synchronization lag;
* challenge success;
* object retrieval success;
* Manifest conflicts;
* Snapshot provider diversity;
* repair success;
* Archive coverage;
* current storage backlog.

---

## 170. MVP Requirements

The MVP SHALL implement:

* Registry Service identity;
* Full, Archive, Cache and Snapshot Provider profiles;
* Hybrid profile support;
* immutable content-addressed objects;
* deterministic Object IDs;
* Object Envelopes;
* namespaces;
* canonical and non-canonical distinction;
* canonical references;
* version chains;
* Tombstones;
* retention classes;
* profile declarations;
* object validation;
* quarantine;
* indexing;
* bounded queries;
* stable cursors;
* query freshness;
* Registry Manifests;
* segment roots;
* completeness scope;
* restricted and encrypted objects;
* corruption detection;
* repair hooks;
* Service Verification integration;
* Reputation integration;
* Marketplace integration;
* Full Registry retention of active Advertisements, current withdrawals and referenced current Marketplace policy objects;
* Snapshot integration;
* Registry network channels;
* complete Registry history.

---

## 171. Deferred Features

The MVP MAY postpone:

* erasure-coded object storage;
* decentralized content-routing tables;
* anonymous Registry queries;
* zero-knowledge completeness proofs;
* private information retrieval;
* paid public object delivery;
* storage auctions;
* cross-network Registry replication;
* formal proofs of physical storage;
* hardware-attested storage;
* automatic legal-retention enforcement;
* decentralized full-text search;
* generalized artifact CDN.

---

## 172. Open Protocol Parameters

The following remain configurable:

* Full Registry retention window;
* recent Ledger history window;
* Validation evidence retention;
* Session evidence retention;
* Governance history retention;
* maximum object size;
* maximum query size;
* query rate limits;
* cursor lifetime;
* Manifest frequency;
* segment size;
* synchronization lag threshold;
* corruption scan frequency;
* repair timeout;
* access-token lifetime;
* Snapshot retention count;
* Registry Profile verification frequency.

---

## 173. Identity Invariants

Registry Service
≠
Ledger
Registry Service
≠
Consensus Authority
Registry Object ID
≠
Logical Record Name
Registry Index
≠
Canonical State
Registry Advertisement
≠
Proof of Availability

---

## 174. Object Invariants

* Immutable objects never change under the same Object ID.
* Every payload matches its hash.
* Every object belongs to one network domain.
* Version changes create new objects.
* Logical removal does not erase Archive history.
* Conflicting signed objects remain auditable.
* Canonical status requires an explicit canonical reference.
* Orphaned objects do not appear as canonical by default.

---

## 175. Profile Invariants

* Registry requirements depend on the declared profile.
* Cache Registries are not judged as Archives.
* Full verification does not imply Archive verification.
* Hybrid profile components are evaluated separately.
* Profile changes are hash-bound.
* Retention claims are public.
* One operator's many Registry identities do not automatically represent independent storage.

---

## 176. Query Invariants

* Query responses identify freshness.
* Query results remain independently verifiable.
* Pagination is stable and bounded.
* Derived views are non-canonical.
* Local rankings are not protocol rankings.
* Restricted data is not exposed through public indexes.
* Stale indexes do not modify canonical state.

---

## 177. Economic Invariants

RegistryRegistration
DoesNotAutomaticallyEarnQ
DeclaredStorageSize
DoesNotAutomaticallyEarnQ
SignedManifest
DoesNotAutomaticallyProveAvailability
DuplicateControlledRegistries
DoNotAutomaticallyCreateIndependentRewards
RewardableRegistryWork
RequiresProtocolEvidence

---

## 178. Security Invariants

* Registry content is treated as untrusted.
* Objects are never executed merely for storage or indexing.
* Public clients verify Object IDs.
* Replicated objects are independently validated.
* Manifest equivocation is detectable.
* Access classes are enforced.
* Encryption keys are not required to be known by the Registry.
* Snapshot data is checked against a canonical trust anchor.
* Local corruption cannot alter network history.
* Registry failure cannot independently change Wallet balances or Settlement.

---

## 179. Design Invariants

* Registry provides availability, history and discovery.
* Ledger provides canonical state.
* Content addressing provides object integrity.
* Canonical commitments provide protocol authority.
* Registry Profiles allow different useful storage roles.
* Replication and Snapshot protocols extend the architecture without redefining it.
* Registry indexes improve usability but remain rebuildable.
* Private evidence can be stored without becoming public.
* Registry operators compete through availability, completeness, latency and reliability.
* The architecture avoids promoting whichever database answered first into an oracle of truth, a temptation apparently irresistible to distributed systems once they acquire an HTTP endpoint.

Комментарии к решениям

1. Registry хранит данные, но не решает, что истинно

Основная цепочка:

Ledger:
CertificationRecordHash = abc123
Registry:
отдаёт объект с hash abc123
Client:
проверяет hash и canonical reference

Registry не может вернуть другой Certification Record и заявить:

"У меня в базе так".

То есть может, конечно. База данных не испытывает стыда. Но клиент обязан его отвергнуть.

---

2. Объекты immutable, логические записи versioned

Endpoint Advertisement меняется со временем:

Advertisement v1
→ Advertisement v2
→ withdrawn

Мы не редактируем объект v1.

Создаётся новый объект, который ссылается на предыдущий. Это позволяет восстановить:

* какие цены действовали;
* какой Configuration Hash публиковался;
* когда Endpoint был отозван;
* с какой политикой открылась конкретная Session.

---

3. Canonical и Non-Canonical Objects разделены

Canonical:

* Epoch Result;
* Certification Record;
* Governance Authorization;
* Capability Definition.

Non-canonical:

* аналитика;
* локальный рейтинг;
* операторское описание;
* субъективный обзор;
* непроверенный отчёт.

Registry может хранить оба типа, но обязан честно указывать статус. Иначе красивый обзор одного оператора постепенно превращается в "официальное решение сети", просто потому что его чаще возвращал поиск.

---

4. Почему нужны разные Registry Profiles

Один сервер не обязан хранить всё.

Full Registry нужен для текущей работы сети.

Archive Registry сохраняет историю.

Cache Registry ускоряет популярные объекты.

Snapshot Provider помогает новым нодам синхронизироваться.

Принуждать каждый маленький Registry хранить полный архив навсегда означало бы быстро сократить сеть до нескольких операторов с большими дисками и ещё большим терпением.

---

5. Cache Registry не является плохим Archive Registry

Это отдельная полезная роль.

Cache может:

* хранить популярные модели или артефакты;
* ускорять Marketplace;
* отдавать Snapshot chunks;
* уменьшать межрегиональный трафик.

Но он обязан честно говорить:

retention: opportunistic

Он не получает Archive-репутацию за то, что вчера случайно кэшировал старый блок.

---

6. Registry Manifest является заявлением, а не доказательством

Manifest говорит:

Я храню объекты X, Y и Z

Он полезен для:

* построения Challenges;
* replication planning;
* completeness;
* reward calculation.

Но реальное наличие проверяется только retrieval и availability proofs.

Иначе Registry мог бы хранить исключительно Manifest о том, насколько много он хранит. Фантастически эффективная компрессия, экономически чуть менее убедительная.

---

7. Storage size не должна быть основой награды

Если платить за терабайты, оператор сможет:

* хранить дубликаты;
* хранить нерелевантные объекты;
* раздувать encoding;
* заявлять большой диск;
* игнорировать required object set.

Поэтому работа оценивается через:

* нужные объекты;
* completeness;
* availability;
* challenge success;
* synchronization;
* Snapshot serving;
* repair contribution.

---

8. Index не является источником истины

Индекс нужен для запросов:

покажи все Certified image.generate Endpoints

Но он может быть устаревшим.

Поэтому ответ Registry должен содержать:

* найденные объекты;
* их hashes;
* canonical references;
* freshness;
* текущую высоту синхронизации.

Клиент не обязан доверять красивой таблице результатов только потому, что SQL выполнился без ошибки.

---

9. Restricted Objects нужны для Session и Validation

Не все доказательства должны быть публичными.

Например:

* raw prompt;
* private agent workspace;
* concealed Validation evidence;
* security incident;
* Session dispute.

Registry может хранить encrypted opaque object:

Registry знает:
hash, размер, retention, access metadata
Registry не знает:
содержание

Это позволяет сохранять evidence availability без публикации пользовательских данных.

---

10. Registry не должен исполнять содержимое

Registry получает:

* архивы;
* документы;
* код;
* модели;
* изображения;
* бинарники.

Он не должен автоматически запускать их ради индексации.

Даже preview generation следует делать в sandbox. Иначе распределённое хранилище быстро эволюционирует в распределённый ботнет, что, безусловно, тоже форма децентрализации, но не та, которую мы проектируем.

---

11. Registry Profiles проверяются независимо

Registry может быть:

FULL: VERIFIED
SNAPSHOT_PROVIDER: DEGRADED
ARCHIVE: UNVERIFIED

Это правильнее, чем один общий статус Registry verified.

Разные роли имеют разные:

* completeness;
* retention;
* Duty Proof;
* workload;
* reward evidence.

---

12. Где проходит граница с RFC-0061

RFC-0046 отвечает:

* какие Registry существуют;
* какие объекты хранятся;
* как устроены Object ID;
* какие есть profiles;
* что такое Manifest и Segment;
* как работают queries и retention.

RFC-0061 отвечает:

* как Registries обмениваются inventory;
* как выбирают источники;
* как реплицируют segments;
* как проводят challenges;
* как считают Duty Proof;
* как восстанавливают недостающие объекты.

---

13. Где проходит граница с RFC-0062

RFC-0046 говорит, что Snapshot Manifest и chunks являются Registry Objects.

RFC-0062 определяет:

* как выбирается Snapshot Height;
* кто создаёт Snapshot;
* как проверяется State Root;
* как выбирается trusted Snapshot;
* как нода выполняет State Sync.

Registry может раздать Snapshot, но не может самостоятельно объявить его каноническим.

---

14. Что теперь нужно синхронизировать

После принятия RFC-0046 v0.2:

* RFC-0039: Registry Service должен ссылаться на Registry Profile Declaration;
* RFC-0040: Registry Verification должна использовать profile-specific scope;
* RFC-0041: добавить Snapshot Delivery Reliability и Manifest Equivocation;
* RFC-0042: REGISTRY channel должен использовать Object ID, Transfer ID и profile scope;
* RFC-0048: добавить Registry Epoch Tasks из раздела 161;
* RFC-0049: Marketplace хранит versioned Advertisement Objects через Registry;
* RFC-0059: сверить Registry Ledger Operations из раздела 158;
* RFC-0061: привести Inventory и Segment Manifest к объектной модели этого RFC;
* RFC-0062: Snapshot Manifest должен быть объектом namespace snapshot;
* RFC-0065: Certification history хранится как immutable version chain;
* RFC-0066: pre-upgrade и post-upgrade Snapshot availability используют Registry Profiles;
* RFC-0067: Governance history retention становится обязательной частью Full/Archive policy.

Следующий оставшийся фундаментальный документ из твоего списка: RFC-0049 - Distributed Marketplace and Advertisement Registry. Он как раз должен использовать эту объектную модель, а не притворяться отдельной централизованной таблицей Endpoints.
