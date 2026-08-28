# IMP-0001 — AiDN Implementation Profile

Status: Draft  
Version: 0.1  
Profile Name: `aidn-mainnet-candidate-1`

## 1. Purpose

This document defines the exact AiDN protocol subset that an implementation may claim to support for the current release profile.

It is intentionally narrower than the architectural RFC set.

An implementation conforming to this profile MUST implement exactly the behavior described here for:

- state representation;
- canonical serialization;
- hashing;
- object identifiers;
- predecessor linkage;
- operation validation;
- idempotency;
- unsupported operations;
- snapshots;
- AppHash derivation;
- deterministic error behavior.

Architecture documents may define additional future behavior. Such behavior is NOT production-supported until included in an active Implementation Profile.

This document is a Draft candidate profile, not an activation claim. The
identifier `aidn-mainnet-candidate-1` becomes release-authoritative only after
the machine-readable profile artifact, operation catalog commitment, fixture
manifest, migration matrix, and GATE-0001 evidence are published together.

## 2. Conformance vocabulary

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT, MAY, and OPTIONAL are normative.

## 3. Profile identity

Every node MUST expose:

```json
{
  "profile_id": "aidn-mainnet-candidate-1",
  "state_schema_version": 1,
  "canonical_encoding_version": 1,
  "app_hash_version": 1,
  "operation_catalog_version": 1
}
```

A node MUST NOT participate as a validator if its active profile is incompatible with the network activation profile.

## 4. Consensus boundary

CometBFT orders transactions.

The AiDN application state machine is authoritative for:

- transaction validity;
- state transition validity;
- operation idempotency;
- object/predecessor validity;
- state root calculation;
- AppHash returned to CometBFT.

CometBFT consensus MUST NOT be used as a substitute for application-level semantic validation.

## 5. Determinism requirements

For identical:

```text
PreState
+
OrderedOperations
+
ProfileVersion
```

every conforming validator MUST produce byte-identical:

```text
PostState
AppHash
OperationResults
DeterministicErrorCodes
```

No consensus transition may depend on:

- wall-clock time unless time is explicitly supplied by consensus input;
- local filesystem ordering;
- locale;
- floating point arithmetic;
- map/dictionary iteration order;
- thread scheduling;
- host architecture;
- random values not committed in the operation;
- external RPC responses;
- GitHub/API state;
- DNS results.

## 6. Numeric representation

Consensus-visible monetary and accounting values MUST use integer smallest units.

Floating point values MUST NOT appear in consensus state.

Example:

```text
1 Q = Q_ATOMS_PER_Q
```

`Q_ATOMS_PER_Q` MUST be fixed by the active economic profile.

Ratios MUST use either:

- integer basis points;
- rational numerator/denominator pairs;
- fixed-point integers with a profile-defined scale.

## 7. Timestamp representation

Consensus-visible timestamps MUST be encoded as UTC RFC3339 strings with:

- `Z` timezone;
- second precision unless another field explicitly requires finer precision;
- no local timezone offsets.

Example:

```json
"2026-08-03T15:22:04Z"
```

If a timestamp originates from block context, the application MUST use the CometBFT block time supplied for that transition.

## 8. Canonical JSON

Consensus-visible JSON MUST use canonical encoding version 1.

Rules:

1. UTF-8.
2. Object keys sorted lexicographically by Unicode code point.
3. No insignificant whitespace.
4. Integers serialized in base-10 without leading zeroes.
5. Negative zero forbidden.
6. Floating point forbidden.
7. Strings encoded using standard JSON escaping.
8. Arrays preserve semantic order.
9. `null` and missing field are distinct.
10. Optional fields MUST be omitted when absent unless the schema explicitly requires `null`.
11. Duplicate object keys are invalid.
12. Unknown fields are handled according to section 19.

Canonical JSON bytes are the UTF-8 bytes of the normalized object.

## 9. Canonical hash

Unless a type defines otherwise:

```text
CanonicalHash(object)
=
SHA-256(
  DomainSeparator
  || 0x00
  || CanonicalJSON(object)
)
```

Domain separators MUST be ASCII strings defined per object family.

Examples:

```text
AIDN:OPERATION:v1
AIDN:STATE:v1
AIDN:SNAPSHOT:v1
AIDN:CONTRIBUTION:v1
AIDN:REWARD:v1
```

Hashes MUST be encoded externally as lowercase hexadecimal unless a schema explicitly requires raw bytes.

## 10. Operation ID

Every state-changing operation MUST have a deterministic `operation_id`.

Default derivation:

```text
operation_id =
SHA256(
  "AIDN:OPERATION:v1"
  || 0x00
  || canonical_operation_without_operation_id
)
```

A submitted `operation_id` MUST equal the computed value.

Mismatch:

```text
ERR_OPERATION_ID_MISMATCH
```

## 11. Predecessor linkage

Operations that mutate a versioned object MUST include:

```json
"predecessor_id": "..."
```

The predecessor MUST equal the current canonical version identifier for the targeted object.

If no predecessor exists and the operation is a create operation:

```json
"predecessor_id": null
```

Invalid predecessor:

```text
ERR_PREDECESSOR_MISMATCH
```

The state MUST remain unchanged.

## 12. State object versioning

Versioned state objects MUST contain:

```json
{
  "object_id": "...",
  "revision": 7,
  "predecessor_id": "...",
  "state": "ACTIVE"
}
```

Revisions MUST increase monotonically by exactly one unless a type-specific rule says otherwise.

## 13. Supported operation classes

The release profile MUST maintain an explicit generated operation catalog.

At minimum, current candidate implementation work may include the following classes where implemented:

### Session/Escrow

```text
SESSION_ESCROW_LOCK
SESSION_ESCROW_EXTEND
SESSION_ESCROW_RELEASE
SESSION_SETTLEMENT_PROPOSE
SESSION_SETTLEMENT_ACCEPT
SESSION_SETTLEMENT_FINALIZE
```

### Development accounting

```text
DEVELOPMENT_POOL_ALLOCATE
DEVELOPMENT_POOL_CARRYOVER

DEVELOPMENT_BOUNTY_CREATE
DEVELOPMENT_BOUNTY_RESERVE
DEVELOPMENT_BOUNTY_RELEASE
DEVELOPMENT_BOUNTY_EXPIRE

DEVELOPMENT_REWARD_CALCULATE
DEVELOPMENT_REWARD_RESERVE
DEVELOPMENT_REWARD_PAY_IMMEDIATE
DEVELOPMENT_REWARD_PAY_MATURITY
DEVELOPMENT_REWARD_MARK_UNCLAIMED
DEVELOPMENT_REWARD_CLAIM
DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED
DEVELOPMENT_REWARD_FINALIZE_COMMITMENT
DEVELOPMENT_REWARD_CANCEL_UNVESTED
DEVELOPMENT_REWARD_CORRECT
```

### Contribution accounting

```text
CONTRIBUTOR_IDENTITY_REGISTER
CONTRIBUTOR_WALLET_BIND
CONTRIBUTOR_WALLET_ROTATE

CONTRIBUTION_ATTEST
CONTRIBUTION_CHALLENGE
CONTRIBUTION_CHALLENGE_RESOLVE
CONTRIBUTION_FINALIZE
CONTRIBUTION_MATURITY_CONFIRM
CONTRIBUTION_MATURITY_REDUCE
```

The checked-in machine-readable operation catalog is authoritative for a release.

If an operation appears in an RFC but not in the active catalog, the node MUST reject it as unsupported.

## 14. Operation envelope

Every consensus operation MUST include:

```json
{
  "operation_type": "DEVELOPMENT_POOL_CARRYOVER",
  "operation_version": 1,
  "network_id": "...",
  "profile_id": "aidn-mainnet-candidate-1",
  "actor_id": "...",
  "nonce": "...",
  "predecessor_id": "...",
  "payload": {},
  "signature": "...",
  "operation_id": "..."
}
```

Requiredness of `predecessor_id` depends on the operation schema.

## 15. Signature boundary

Signatures MUST cover the canonical unsigned operation object.

The unsigned object MUST exclude only:

```text
signature
operation_id
```

unless a type-specific schema states otherwise.

Signature verification failure:

```text
ERR_INVALID_SIGNATURE
```

## 16. Transaction processing order

For each block:

1. Decode operation.
2. Validate canonical form.
3. Validate network/profile/version.
4. Recompute Operation ID.
5. Check replay/idempotency index.
6. Validate signature/authority.
7. Validate predecessor.
8. Validate operation-specific invariants.
9. Apply transition to in-memory deterministic state.
10. Persist operation result.
11. At commit, derive state root and AppHash.

No external calls are allowed in steps 1–11.

## 17. Idempotency

Operations are idempotent by `operation_id`.

If an already finalized operation is resubmitted byte-identically:

- it MUST NOT mutate state again;
- it MUST return the original deterministic result;
- it MUST return the original resulting state identifier.

Result status:

```text
IDEMPOTENT_REPLAY
```

If the same logical client idempotency key is submitted with different canonical payload:

```text
ERR_IDEMPOTENCY_CONFLICT
```

## 18. Replay protection

The implementation MUST retain a consensus-visible or deterministically reconstructable index sufficient to prevent reapplication of finalized state-changing operations.

Pruning MUST NOT make an old valid operation executable again.

## 19. Unknown fields

For canonical consensus objects:

- unknown top-level fields MUST be rejected unless the schema explicitly marks an extension container;
- extension fields MUST live under a designated object such as `extensions`;
- unknown extension entries MAY be preserved as opaque canonical JSON if the profile explicitly permits them.

Default:

```text
ERR_UNKNOWN_FIELD
```

This rule exists to prevent validators from hashing semantically different objects.

## 20. Unknown operations

Unknown `operation_type`:

```text
ERR_UNSUPPORTED_OPERATION
```

The transaction MUST NOT mutate state.

A node MUST NOT silently ignore unknown consensus operations.

## 21. Unsupported operation version

Known operation with unsupported `operation_version`:

```text
ERR_UNSUPPORTED_OPERATION_VERSION
```

No state mutation.

## 22. Unsupported profile

If:

```text
operation.profile_id != active_profile_id
```

result:

```text
ERR_PROFILE_MISMATCH
```

unless an explicitly activated compatibility rule applies.

## 23. Invalid state transition

Operations MUST define allowed predecessor states.

Example:

```text
BOUNTY_ACTIVE
→ DEVELOPMENT_BOUNTY_RELEASE
→ BOUNTY_RELEASED
```

Attempting:

```text
BOUNTY_RELEASED
→ DEVELOPMENT_BOUNTY_RELEASE
```

with a different operation id is invalid:

```text
ERR_INVALID_STATE_TRANSITION
```

## 24. Insufficient balance/reserve

Any transition that would produce a negative balance, reserve, or pool is invalid.

```text
ERR_INSUFFICIENT_FUNDS
ERR_INSUFFICIENT_RESERVE
```

State MUST remain unchanged.

## 25. Development pool invariant

For every epoch:

```text
PoolIn
=
ImmediatePaid
+
MaturityReserved
+
BountyReserved
+
SecurityReserved
+
CarryoverOut
+
ReturnedToReserve
+
UncommittedAvailable
```

No undefined remainder is permitted.

## 26. Reward invariant

For every development reward:

```text
GrossReward
=
ImmediatePaid
+
MaturityPaid
+
Unclaimed
+
CancelledUnvested
+
StillReserved
```

## 27. Settlement invariant

Where Session settlement is enabled:

```text
LockedFunds
=
EndpointPayment
+
ConsumerRefund
+
NetworkFees
+
AnyExplicitReserve
```

for the finalized settlement accounting model active in the profile.

## 28. State root

State MUST be represented as deterministic logical collections.

The implementation MUST define a canonical ordered export:

```text
collection_name
object_key
canonical_object_bytes
```

Default State Root derivation:

```text
Leaf =
SHA256(
  "AIDN:STATE-LEAF:v1"
  || 0x00
  || collection_name
  || 0x00
  || object_key
  || 0x00
  || canonical_object_bytes
)
```

Leaves are ordered lexicographically by `(collection_name, object_key)`.

The Merkle construction used by the implementation MUST be specified and fixture-tested. If a simple linear hash accumulator is used before Merkleization exists, that algorithm MUST be profile-versioned and frozen for the release.

## 29. AppHash

For AppHash version 1:

```text
AppHash =
SHA256(
  "AIDN:APPHASH:v1"
  || 0x00
  || StateRoot
  || 0x00
  || uint64_be(BlockHeight)
  || 0x00
  || ProfileCommitment
)
```

`ProfileCommitment` MUST commit to:

- profile ID;
- state schema version;
- canonical encoding version;
- AppHash version;
- operation catalog hash.

The exact byte vector MUST be covered by FIX-0001.

## 30. Empty state

Genesis AppHash MUST be explicitly fixture-defined.

No implementation may derive its own interpretation of an empty map.

## 31. Snapshot format

Snapshots MUST contain at minimum:

```json
{
  "snapshot_format_version": 1,
  "network_id": "...",
  "profile_id": "...",
  "height": 12345,
  "app_hash": "...",
  "state_schema_version": 1,
  "canonical_encoding_version": 1,
  "operation_catalog_hash": "...",
  "state_root": "...",
  "created_at": "...",
  "chunks": [],
  "manifest_hash": "..."
}
```

A snapshot MUST be rejected if the reconstructed state does not produce the declared AppHash under the declared profile.

## 32. Snapshot restore

Restore procedure:

1. Verify snapshot manifest hash.
2. Verify network/profile compatibility.
3. Verify all chunk hashes.
4. Reconstruct canonical state.
5. Derive StateRoot.
6. Derive expected AppHash at snapshot height.
7. Compare with manifest.
8. Only then make state active.

Failure MUST leave the previous active state intact.

## 33. State sync

A state-synced node MUST produce the same AppHash as a fully replayed node at the same height.

This is a release gate.

## 34. Crash consistency

A crash may not produce a partially committed consensus transition.

Implementation MUST provide atomicity between:

- application state;
- operation replay index;
- committed height;
- AppHash metadata.

## 35. ABCI error determinism

Consensus transaction validation errors MUST map to stable numeric or symbolic codes.

Human-readable text MAY improve between patch releases but MUST NOT be hashed into consensus state.

## 36. Minimum stable error catalog

```text
ERR_DECODE_FAILED
ERR_NON_CANONICAL_ENCODING
ERR_UNKNOWN_FIELD
ERR_UNSUPPORTED_OPERATION
ERR_UNSUPPORTED_OPERATION_VERSION
ERR_PROFILE_MISMATCH
ERR_NETWORK_MISMATCH
ERR_OPERATION_ID_MISMATCH
ERR_INVALID_SIGNATURE
ERR_UNAUTHORIZED_ACTOR
ERR_IDEMPOTENCY_CONFLICT
ERR_PREDECESSOR_MISMATCH
ERR_INVALID_STATE_TRANSITION
ERR_INSUFFICIENT_FUNDS
ERR_INSUFFICIENT_RESERVE
ERR_INVARIANT_VIOLATION
ERR_SNAPSHOT_INCOMPATIBLE
ERR_SNAPSHOT_HASH_MISMATCH
ERR_APPHASH_MISMATCH
```

## 37. Query/RPC behavior

RPC queries MUST distinguish:

```text
NOT_FOUND
UNSUPPORTED
UNAVAILABLE
INVALID_QUERY
```

Query endpoints MUST NOT mutate state.

## 38. Live RPC evidence

A production candidate MUST expose enough RPC evidence to demonstrate:

- node identity;
- network identity;
- latest committed height;
- latest AppHash;
- validator status where applicable;
- peer count;
- sync state;
- software/profile versions.

Exact commands belong in OPS-0001 and GATE-0001.

## 39. Strict operation coverage

Every supported state-changing operation MUST have:

- one happy-path fixture;
- one duplicate/idempotency fixture;
- one invalid predecessor or invalid state fixture;
- one serialization/hash fixture.

Financial operations additionally MUST have insufficient-funds/reserve coverage.

## 40. Release profile generation

The repository SHOULD generate a machine-readable profile artifact:

```text
profiles/aidn-mainnet-candidate-1.json
```

containing:

- supported operation versions;
- active schemas;
- hash algorithms;
- error catalog;
- profile commitment inputs.

The generated artifact hash MUST appear in the release evidence bundle.

The repository generator is:

```bash
uv run python tools/generate-implementation-profile.py \
  --output profiles/aidn-mainnet-candidate-1.json
uv run python tools/generate-implementation-profile.py \
  --check
```

The generated profile is derived from the current code and operation-coverage
matrix. Until Governance activates it, its status remains
`DRAFT_CANDIDATE`/`NOT_ACTIVE`; generation alone does not claim protocol
support for known operations listed as unsupported. The profile distinguishes
active operation types from historical `legacy_operation_types`; legacy names
remain reject-only and do not become aliases for a newer transition.

## 41. Unsupported behavior principle

Anything not explicitly supported by this profile is unsupported.

Implementations MUST prefer deterministic rejection over permissive interpretation.

## 42. Promotion criteria

A feature may be added to a later active Implementation Profile only when:

1. architecture exists;
2. state schema is frozen;
3. canonical bytes are specified;
4. operation transitions are specified;
5. fixtures exist;
6. snapshot/migration impact is known;
7. release gate coverage exists.

## 43. Conformance statement

A node claiming compliance MUST publish:

```json
{
  "profile_id": "aidn-mainnet-candidate-1",
  "profile_commitment": "...",
  "binary_hash": "...",
  "operation_catalog_hash": "...",
  "state_schema_version": 1,
  "app_hash_version": 1
}
```
