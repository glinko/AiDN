# Registry Object Durable Persistence Design

Date: 2026-07-13

Status: Draft

## Goal

Add durable local persistence for standalone Registry Objects so the `RegistryService` object store survives process restarts and stops depending on process memory alone.

This is the next narrow step after introducing:

- immutable Registry Object envelopes;
- opt-in payload retrieval;
- standalone in-memory Registry Object storage inside `RegistryService`.

## Problem

The current implementation now has a real local object boundary:

- `RegistryService` owns a standalone object store keyed by `object_id`;
- operator routes ingest projected canonical objects into that store;
- object reads prefer store-backed rows and preserve meaningful local provenance.

But the store is still process-memory only.

That means a restart loses:

- locally ingested accounting contracts;
- projected capability/profile objects;
- any future standalone Registry Object state not immediately re-derived.

This blocks the next meaningful Registry steps:

- object durability beyond one process;
- lifecycle and retention metadata with persistent effect;
- manifest or inventory generation over a stable persisted object set;
- future replication or repair work over a non-ephemeral local store.

## Scope

This slice adds:

- a durable local snapshot file for standalone Registry Objects;
- load/save hooks around `RegistryService` standalone object storage;
- persisted preservation of payloads and source metadata;
- safe reuse of existing `object_id` conflict rules after reload;
- tests proving restart-safe object retention.

This slice does not add:

- append-only journaling;
- embedded database storage;
- retention policy enforcement;
- manifests or segment roots;
- replication or repair flows;
- multi-process coordination;
- advanced crash recovery beyond basic snapshot replace.

## Approved Approach

We will use a single snapshot-file design.

The snapshot file becomes the first durable boundary for standalone Registry Objects:

- simple enough to implement and validate quickly;
- compatible with the current in-memory `RegistryService` shape;
- a clean base for later retention and manifest work.

This is intentionally not a final storage architecture. It is the minimum durable layer that preserves today’s object semantics and reduces future migration risk.

## Alternatives Considered

### 1. Single snapshot file

Recommendation: Yes.

Pros:

- smallest useful durability slice;
- easy to verify with restart-style tests;
- preserves current service API with minimal churn;
- keeps future migration to manifest or inventory logic straightforward.

Cons:

- rewrites the whole snapshot on update;
- no append-only audit trail yet;
- basic durability only.

### 2. Append-only journal plus rebuild

Recommendation: Not yet.

Pros:

- stronger replay and audit path;
- more natural future event history.

Cons:

- broader scope;
- requires compaction or replay strategy immediately;
- distracts from the current durability goal.

### 3. Embedded database

Recommendation: Not yet.

Pros:

- more scalable storage foundation.

Cons:

- too much infrastructure too early;
- increases scope before lifecycle and manifest requirements are proven in code.

## Proposed Design

### Storage boundary

`RegistryService` remains the public owner of:

- object ingestion;
- object lookup;
- compatibility merge with node-backed Registry Objects.

A separate persisted snapshot file stores only the standalone object-store content.

Node advertisements remain outside this snapshot.

### Persisted data model

The persisted snapshot should contain:

- schema version;
- stored object records;
- optional metadata needed for later migrations.

Recommended top-level shape:

```json
{
  "schema_version": "registry-object-store.v1",
  "objects": [
    {
      "object_id": "...",
      "object_type": "...",
      "object_version": "...",
      "namespace": "...",
      "payload_hash": "...",
      "payload_encoding": "canonical_json",
      "source_reference": "...",
      "payload": { "...": "..." },
      "_source": {
        "node_id": "...",
        "operator_id": "...",
        "status": "ready"
      }
    }
  ]
}
```

Using a list instead of a raw dict keeps the file format easier to evolve and inspect, while `RegistryService` can still rebuild its in-memory map keyed by `object_id`.

### Service lifecycle

`RegistryService` should support explicit loading and saving.

Reasonable API shape:

- constructor accepts an optional snapshot path;
- service loads snapshot content on initialization when the file exists;
- `upsert_registry_object()` persists after successful mutation;
- `ingest_registry_objects()` persists once after batch ingestion, not once per record;
- persistence failures should not silently corrupt in-memory state.

### Save strategy

Use a basic snapshot write flow:

1. serialize canonical snapshot content;
2. write to a temp file in the same directory;
3. replace the target snapshot file atomically where supported.

This is enough for the current slice.

We do not need:

- journal replay;
- checksums beyond JSON validity;
- multi-writer locking;
- snapshot compaction.

### Load strategy

On initialization:

1. if snapshot file does not exist, start empty;
2. if it exists, parse the JSON;
3. validate `schema_version`;
4. rebuild `_registry_objects` from the stored list;
5. enforce the same `object_id` conflict and normalization rules already used for live ingestion.

If the snapshot is invalid, the failure should be explicit rather than silently discarded.

### Compatibility behavior

The current read contract remains:

- standalone store is primary;
- node-backed objects are compatibility fallback;
- source provenance is preserved;
- conflicts across store-backed and node-backed objects remain explicit failures.

Durability should not change the API semantics seen by callers, except that objects now survive restart.

## File Responsibilities

Likely touched files:

- `src/aidn_hypervisor/registry_service.py`
  - snapshot path, load/save logic, durable batch persistence behavior.
- `tests/test_registry_service.py`
  - save/load/restart/conflict persistence coverage.
- possibly `src/aidn_hypervisor/api.py`
  - only if local fallback should accept or expose a persisted store path.
- `ROADMAP.md`
  - update from in-memory-only standalone persistence to durable local persistence.
- `docs/archive/specifications/2026-07-13-rfc-implementation-alignment-audit.md`
  - update remaining gap wording.

## Expected Behavior

After this slice:

- standalone Registry Objects survive `RegistryService` recreation when pointed at the same snapshot path;
- stored payloads and `_source` metadata survive reload;
- `get_registry_object()` and `list_registry_objects()` after reload match pre-restart behavior;
- local operator object routes can build on a persisted standalone store instead of process memory only.

## Testing Strategy

Use TDD with narrow restart-style tests.

### Core service tests

Add failing tests for:

- storing one Registry Object and reconstructing a new `RegistryService` from the same snapshot path;
- persisting payload and `_source` metadata across reload;
- batch ingestion persisting several objects in one snapshot;
- persisted conflict handling after reload;
- missing snapshot path producing an empty store without error.

### Persistence behavior tests

Add failing tests for:

- snapshot file created after `upsert_registry_object()`;
- snapshot file updated after `ingest_registry_objects()`;
- invalid snapshot schema causing explicit failure.

### Regression expectations

Existing tests for:

- local operator object routes;
- payload retrieval;
- store-vs-node precedence;
- duplicate conflict handling;

should remain green.

## Risks

### Scope creep into full storage architecture

It would be easy to slide into journaling, retention, or replication.

Mitigation:

- keep this slice snapshot-only;
- defer lifecycle and manifest logic;
- defer multi-process concerns.

### Persistence on every write

Snapshot rewrite per mutation is not ideal long term.

Mitigation:

- acceptable for this slice;
- future journal or buffered persistence can optimize later without changing object semantics.

### Corrupt snapshot handling

Silent fallback to an empty store would hide data loss.

Mitigation:

- fail explicitly on malformed or incompatible snapshot files.

## Non-Goals Reconfirmed

This slice is not:

- a manifest implementation;
- retention enforcement;
- replication;
- repair synchronization;
- a final storage engine.

It is only the first durable local storage boundary for Registry Objects.

## Next Step After This Slice

If this lands cleanly, the next logical slice is:

- lifecycle and retention metadata on persisted objects;

or:

- first manifest/inventory scaffolding over the durable standalone store.
