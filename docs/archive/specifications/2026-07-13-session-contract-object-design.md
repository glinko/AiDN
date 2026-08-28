# Session Contract Object Design

Date: 2026-07-13

Status: Draft

## Goal

Add a first-class immutable `session_contract` Registry Object for accepted
session terms, and bind existing session-open and settlement evidence to that
object.

This slice closes the most direct gap between the current local-first session
implementation and the newer RFC model:

- `RFC-0044` expects an explicit Session Contract boundary;
- `RFC-0037` and `RFC-0060` need settlement evidence to point at one accepted
  contract rather than a loose set of snapshots and derived hashes;
- the repo already preserves `advertisement_id`, `offer_id`,
  `accounting_contract_object_id`, and `session_contract_hash`, but it does not
  yet persist an authoritative `session_contract` object.

## Problem

Paid sessions now preserve enough information to reconstruct accepted terms, but
they still do so indirectly.

Today `open_session()` stores:

- `advertisement_id`;
- optional `offer_id`;
- `pricing_policy_hash`;
- `accounting_contract_hash`;
- the accounting contract snapshot and object reference;
- a derived `session_contract_hash`.

That is useful, but still leaves one important gap:

> There is no standalone immutable object representing the exact accepted
> Session Contract that both Session state and Settlement evidence can point to.

This creates three problems:

1. the accepted contract is hash-shaped rather than object-shaped;
2. session and settlement audit surfaces must reconstruct intent from mutable
   session records plus snapshots;
3. later registry, evidence, and dispute flows have no stable object identity
   to reuse.

## Scope

This slice adds:

- one immutable `session_contract` Registry Object shape;
- deterministic object identity and payload hashing for accepted session terms;
- local registry-store persistence of that object at session open time;
- explicit `session_contract_object_*` references on `EndpointSession`;
- `SESSION_OPEN` and `SESSION_SETTLE` payload references to the stored contract
  object;
- operator-visible registry and session audit access to the new object through
  existing object-query surfaces;
- tests proving determinism, persistence, and settlement-reference continuity.

This slice does not add:

- forced-settlement state machine changes;
- invoice objects;
- dispute objects;
- settlement evidence objects;
- retention policy enforcement;
- manifest generation;
- replication;
- session amendment or renegotiation version chains;
- remote cross-node session-contract exchange.

## Approved Approach

Implement a `session-first canonical contract object` and bind settlement
payloads to it immediately.

That means:

- session open remains the moment when accepted terms are frozen;
- the service derives a canonical `session_contract` payload from those terms;
- the local registry store persists that payload as an immutable Registry
  Object;
- the session record stores object references plus the existing
  `session_contract_hash`;
- settlement payloads point back to the same object reference.

This is intentionally wider than a hash-only session patch and narrower than a
full settlement-evidence object family.

## Alternatives Considered

### 1. Narrow hash-and-object session slice

Recommendation: No.

Pros:

- smallest implementation footprint;
- minimal changes outside `open_session()`;
- closes the object-identity gap for session state.

Cons:

- settlement remains anchored mostly to `session_contract_hash`;
- audit still splits between object identity and settlement evidence shape;
- likely requires a near-immediate follow-up to finish the contract reference
  path.

### 2. Session contract object plus settlement reference alignment

Recommendation: Yes.

Pros:

- still a narrow vertical slice;
- makes one object the shared contract reference for Session and Settlement;
- improves auditability without dragging in forced settlement;
- matches the current RFC gap most directly.

Cons:

- touches session, ledger/event payloads, and API read models together;
- slightly more migration work than the narrowest option.

### 3. Full session contract plus settlement evidence object family

Recommendation: Not yet.

Pros:

- most complete long-term architecture;
- would give disputes and forced settlement a ready-made object graph.

Cons:

- too broad for the next slice;
- risks blending `RFC-0044`, `RFC-0037`, and `RFC-0060` implementation into
  one large change;
- raises design questions about lifecycle, retention, and dispute boundaries
  that are not required yet.

## Proposed Design

### 1. Registry Object Boundary

Introduce a new immutable Registry Object type:

- `object_type = "session_contract"`
- `object_version = "session-contract.v1"`
- `namespace = "session"`

This object represents accepted session terms only.

It is not:

- live session state;
- usage state;
- settlement state;
- a mutable session read model.

Its only purpose is to freeze the accepted contract for later evidence and
audit.

### 2. Canonical Payload

The `session_contract` payload should include only accepted, consumer-visible
terms and stable identity fields.

Required fields:

- `session_id`
- `endpoint_id`
- `client_wallet`
- `provider_wallet`
- `node_id`
- `deposit_locked_q`
- `advertisement_id`
- `offer_id`
- `pricing_policy_hash`
- `accounting_contract_hash`
- `accounting_contract_object_id`
- `accounting_contract_object_version`
- `accounting_contract_namespace`
- `session_policy_snapshot`

Optional but useful fields:

- `accepted_at`
- `session_contract_version`

The payload must not include mutable runtime state such as:

- `status`
- `request_count`
- `reserved_slot_index`
- `last_activity_at`
- `close_reason`
- usage checkpoints
- accounting acknowledgements
- settlement totals

Those belong to session lifecycle and settlement state, not to the accepted
contract.

### 3. Identity And Hashing

The service should build the session contract payload first, then derive:

- canonical payload hash;
- deterministic `object_id`;
- persisted object envelope;
- `session_contract_hash`.

`session_contract_hash` should remain present for compatibility, but it should
be derived from the same canonical payload used by the object.

The key rule is:

`session_contract_hash` and `session_contract_object_id` must describe the same
frozen accepted terms, not two independently assembled structures.

### 4. Session Write Path

At `open_session(...)` time:

1. validate the accepted request as today;
2. assemble the canonical session contract payload;
3. persist a `session_contract` Registry Object into the standalone local
   registry store;
4. create the `EndpointSession`;
5. store object references on the session record.

`EndpointSession` should gain:

- `session_contract_object_id`
- `session_contract_object_version`
- `session_contract_namespace`

Optional local convenience field:

- `session_contract_snapshot`

The snapshot is acceptable if it remains clearly secondary to the canonical
Registry Object reference and is used only for fast local inspection or
backward-compatible payloads.

### 5. Settlement Reference Alignment

`SESSION_OPEN` payloads should include:

- `session_contract_object_id`
- `session_contract_hash`

`SESSION_SETTLE` payloads should also include:

- `session_contract_object_id`
- `session_contract_hash`

This does not create a new settlement evidence object in this slice.

It does ensure that settlement evidence now points at the same immutable
accepted contract used by the session domain.

That is the key architectural gain:

- one accepted object;
- two lifecycle phases referencing it;
- no need to infer accepted terms from mutable session state at settlement time.

### 6. Registry And API Surface

No new registry endpoint family is required.

Existing local object surfaces should naturally expose the new object once it is
ingested into the standalone local registry store:

- `GET /operators/registry/objects`
- `GET /operators/registry/objects/{object_id}`

Session/operator read models should expose:

- `session_contract_object_id`
- `session_contract_object_version`
- `session_contract_namespace`
- existing `session_contract_hash`

Where existing session payloads already return snapshots, they may continue to
do so, but the canonical contract reference should be explicit and easy to
follow.

### 7. Relationship To Future Settlement Work

This slice deliberately stops before a full settlement-evidence object family.

The intended path is:

1. freeze accepted terms as a standalone `session_contract` object;
2. bind open and settle payloads to that object;
3. later introduce settlement-evidence objects if and when forced settlement,
   invoice, or dispute flows need them.

That sequencing matters because it gives later evidence work a stable contract
anchor without forcing all evidence semantics into the same change.

## Implementation Shape

The natural implementation split is:

- `src/aidn_hypervisor/sessions/models.py`
  - add `session_contract_object_*` fields and any optional snapshot field;
- `src/aidn_hypervisor/sessions/service.py`
  - build canonical payload;
  - persist the object;
  - derive hash and object references from the same payload;
  - store references on the session record;
  - attach object references to open/settle operation payloads;
- `src/aidn_hypervisor/registry_service.py`
  - reuse existing standalone persistence path with no new storage model;
- `src/aidn_hypervisor/api.py`
  - surface new references in session/operator reads where needed;
- `src/aidn_hypervisor/canonical_models.py`
  - add a typed record if session contract projection needs explicit model
    support instead of plain dict-only storage;
- `tests/sessions/`
  - session-open and session-settlement reference coverage;
- `tests/test_registry_service.py`
  - local stored-object visibility and persistence coverage;
- `tests/ledger/` or existing ledger-hook tests
  - payload reference continuity coverage;
- `tests/test_api.py`
  - operator/session read-model coverage where applicable.

## Testing Strategy

### Session Service Tests

Cover:

- `open_session()` persists a `session_contract` object;
- the session record stores the expected `session_contract_object_*` references;
- `session_contract_hash` is stable and aligned to the same payload used by the
  object;
- repeated mutable session changes do not alter the contract object identity;
- settlement payload references the same object created at open time.

### Registry Tests

Cover:

- the stored `session_contract` object appears in local registry listing;
- fetching by `object_id` returns the expected payload;
- local snapshot persistence survives restart;
- payload retrieval remains opt-in and deterministic.

### API Tests

Cover:

- session/operator responses expose the new contract object references;
- registry object endpoints can return the stored `session_contract`;
- no existing object-query compatibility is broken.

### Ledger/Event Payload Tests

Cover:

- `SESSION_OPEN` includes `session_contract_object_id`;
- `SESSION_SETTLE` includes the same `session_contract_object_id`;
- `session_contract_hash` remains present and aligned with the accepted
  contract payload.

## Error Handling

The session open path should fail rather than create a session without its
contract object.

Desired behavior:

- if session-contract object persistence fails, the session open transaction
  rolls back;
- no session should survive with a missing canonical contract reference;
- conflicts on the same `object_id` are allowed only when payloads are
  identical and therefore idempotent;
- conflicting payloads under one derived identity should raise.

This keeps the new object boundary authoritative instead of advisory.

## Success Criteria

This slice is complete when:

- every newly opened paid session persists an immutable `session_contract`
  Registry Object;
- every session record exposes canonical references to that object;
- `SESSION_OPEN` and `SESSION_SETTLE` both point to the same contract object;
- the local registry store can list and fetch the object across restart;
- tests prove deterministic identity, persistence, and reference continuity;
- no forced-settlement, dispute-object, or retention/manifest work is added.

## Out Of Scope

The following are explicitly deferred:

- session amendment or renegotiation chains;
- settlement-evidence objects;
- invoice objects;
- dispute objects;
- retention policy enforcement;
- registry manifests;
- replication and challenge flows;
- remote propagation of session-contract objects to another node;
- full `RFC-0060` forced-settlement mechanics.

## Why This Slice Now

The repo already has enough Marketplace and accounting identity to say what was
accepted at session-open time, but it still expresses that contract indirectly.

The next useful step is not a broad rewrite of settlement or registry
architecture.

The next useful step is to make the accepted Session Contract explicit,
immutable, and queryable, then point existing open and settle evidence at that
one object. That gives later settlement, evidence, and registry work a stable
anchor without pretending the whole lifecycle is already implemented.
