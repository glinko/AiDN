# Registry Local Completeness Summary Design

Date: 2026-07-13

Status: Draft

## Goal

Add a versioned local completeness summary contract for the standalone Registry Object store inside `RegistryService`.

This summary is the first narrow lifecycle-and-manifest step after:

- immutable Registry Object envelopes;
- opt-in payload retrieval;
- durable local snapshot persistence for standalone Registry Objects.

The summary gives the service one explicit way to describe what is currently present in its durable local store and whether that store passes basic internal consistency checks.

## Problem

`RegistryService` can now persist standalone Registry Objects across restarts, but it still lacks a lifecycle-oriented summary boundary over that durable store.

Today we can:

- ingest and retain local Registry Objects keyed by `object_id`;
- reload them from a versioned snapshot file;
- query them by `object_id`, `namespace`, `object_type`, and source metadata.

But we still cannot answer a simple service-level question with one stable contract:

> What exactly is in the local durable Registry Object store right now, and does that store look internally consistent?

That missing boundary blocks the next registry steps:

- retention and lifecycle semantics over persisted objects;
- manifest-like completeness summaries over a stable store;
- later profile-aware completeness or manifest scope;
- replication and repair semantics that need a baseline local inventory view.

## Scope

This slice adds:

- one versioned service-level completeness summary model;
- one on-demand `RegistryService` method that builds the summary from the current local store;
- deterministic aggregate counts over the standalone persisted object set;
- basic payload byte totals for stored payload-bearing objects;
- basic internal consistency and integrity flags;
- tests proving summary stability across restarts and mixed local object sets.

This slice does not add:

- a public API or operator route for the summary;
- a persisted manifest or self-stored summary object;
- profile-aware `FULL` or `ARCHIVE` completeness rules;
- namespace segment roots or manifest roots;
- canonical completeness claims;
- replication, challenge, or repair behavior;
- retention policy enforcement.

## Approved Approach

We will implement one on-demand local completeness summary with its own versioned internal model.

The summary is intentionally narrower than an RFC-0046 Registry Manifest:

- it is computed from `RegistryService` local state only;
- it does not claim canonical completeness;
- it does not introduce manifest identity or digest yet;
- it does not leave the service boundary.

This gives us a durable, testable local inventory contract now without pretending that manifest semantics already exist.

## Alternatives Considered

### 1. On-demand summary computed directly from `self._registry_objects`

Recommendation: No.

Pros:

- smallest implementation surface;
- almost no new structure.

Cons:

- lacks an explicit internal contract;
- weaker foundation for later manifest evolution;
- less clear migration path toward versioned lifecycle semantics.

### 2. On-demand summary with a versioned summary model

Recommendation: Yes.

Pros:

- still narrow and low-risk;
- creates a stable internal contract;
- gives future manifest work a natural migration path;
- easy to test without adding publication or storage complexity.

Cons:

- adds some structure now instead of later.

### 3. Two-layer design with separate raw stats and integrity builders

Recommendation: Not yet.

Pros:

- stronger decomposition for later verification and manifest work.

Cons:

- more abstraction than the current slice needs;
- increases local complexity before requirements are proven.

## Proposed Design

### 1. Service Surface

`RegistryService` gains one new service-level method:

- `get_local_registry_completeness_summary()`

This method:

- reads only from the current standalone local store in `self._registry_objects`;
- computes a new summary on demand for each call;
- does not persist the summary;
- does not include node-backed transient compatibility objects;
- does not depend on API, hypervisor routing, or registry replication state.

The method is intended to be a deterministic inspection surface for the durable local store, not a network-facing feature.

### 2. Summary Model

The summary should use a dedicated typed model rather than an ad hoc dictionary.

The model should expose these top-level fields:

- `summary_version`
- `generated_at`
- `snapshot_schema_version`
- `store_totals`
- `by_namespace`
- `by_object_type`
- `integrity`

`store_totals` should contain:

- `total_object_count`
- `payload_object_count`
- `payload_bytes_total`

`by_namespace` should provide counts keyed by namespace.

`by_object_type` should provide counts keyed by object type.

`integrity` should expose:

- `object_count_matches_store`
- `all_object_ids_unique`
- `all_required_fields_present`
- `payload_hash_coverage_count`
- `issues`

This keeps the model small enough for the first slice while making later extensions obvious.

### 3. Computation Rules

The summary must be derived only from the standalone local store already accepted by the service.

Rules:

- `total_object_count` equals the number of unique `object_id` keys in `self._registry_objects`.
- `payload_object_count` counts only objects with a present `payload`.
- `payload_bytes_total` is the sum of canonical serialized payload byte lengths for objects that actually carry `payload`.
- `by_namespace` counts every stored object by its `namespace`.
- `by_object_type` counts every stored object by its `object_type`.
- `snapshot_schema_version` mirrors the currently supported snapshot schema version used by the local durable store.
- `generated_at` is created at summary-build time.

The summary should remain deterministic for the same in-memory store contents except for `generated_at`.

### 4. Integrity Semantics

The first MVP only reports internal store consistency that the service can verify objectively.

It does not attempt to prove:

- canonical completeness;
- global registry coverage;
- profile completeness;
- replication correctness;
- historical manifest continuity.

The integrity fields mean:

- `object_count_matches_store`: the reported total equals the actual local store size.
- `all_object_ids_unique`: true when the dict-backed store contains one effective record per `object_id`.
- `all_required_fields_present`: every stored record contains the minimum registry envelope fields required by the local store contract.
- `payload_hash_coverage_count`: number of objects with `payload_hash` present and non-empty.
- `issues`: machine-readable local consistency anomalies discovered during summary generation.

Expected `issues` scope in this slice:

- missing required field in a stored record;
- impossible local record shape that can still be inspected;
- missing or empty payload metadata where the stored record is otherwise malformed for summary purposes.

The summary builder should not silently repair bad records.

If aggregation can continue deterministically, it should return a summary with `issues`.

If the store is in a state where deterministic aggregation is not possible, the method may raise rather than fabricate a result.

### 5. Relationship To Future Manifest Work

This design deliberately stops short of a true manifest object.

That boundary matters:

- this slice is a local service summary;
- the next slice can add manifest-like scope and deterministic digest;
- later work can add profile-aware completeness boundaries;
- only after that should we decide whether the manifest becomes a Registry Object or another externally referenced artifact.

The intended migration path is:

1. local completeness summary;
2. add explicit scope and digest;
3. add manifest identity or reference semantics;
4. add profile-aware completeness rules;
5. connect the result to replication, verification, and challenge flows.

### 6. Testing

Tests should cover:

- empty store returns a valid zeroed summary;
- mixed object types and namespaces aggregate correctly;
- payload byte totals count only payload-bearing objects;
- summary values survive restart when the local snapshot is reloaded;
- integrity flags remain consistent with the actual local store;
- malformed in-memory record states, where representable in tests, surface as `issues` or raise when deterministic aggregation is impossible.

Tests should stay service-level and avoid API or end-to-end wiring.

## Error Handling

The summary builder should be strict but useful.

Desired behavior:

- do not hide broken local state;
- do not mutate the store while generating a summary;
- prefer explicit `issues` for inspectable anomalies;
- raise only for states where a deterministic summary cannot be produced.

This keeps the summary usable as an operator-facing internal primitive later without making the first slice brittle.

## Success Criteria

This slice is complete when:

- `RegistryService` exposes a versioned local completeness summary method;
- the summary is derived from the durable local object store only;
- the summary reports counts, payload totals, and integrity flags defined here;
- tests prove summary correctness and restart-stable behavior;
- no API, persisted manifest object, or replication semantics are introduced.

## Out Of Scope

The following are explicitly deferred:

- manifest identity;
- manifest digests;
- segment roots;
- retention enforcement;
- profile completeness;
- challenge generation;
- peer replication;
- repair workflows;
- public query endpoints for the summary.

## Why This Slice Now

The durable standalone object store now exists, so the next useful step is not another broad rewrite.

The right next step is a small local lifecycle boundary that makes the store inspectable as a coherent inventory. That gives later manifest and verification work something concrete to build on without prematurely turning a local summary into a protocol object.
