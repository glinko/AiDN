# Registry Object Persistence Design

Date: 2026-07-13

Status: Draft

## Goal

Introduce a standalone local Registry Object persistence boundary inside `RegistryService`, so canonical Registry Objects no longer exist only as fields embedded in node advertisements.

This is the next narrow step after envelope query support and opt-in payload retrieval.

## Problem

The current implementation can:

- project immutable canonical Registry Object envelopes;
- attach them to `node_advertisement()`;
- expose registry-backed list/query/get views;
- return canonical payloads on demand.

But those objects are still effectively stored only through:

- `RegistryNodeAdvertisement.canonical_registry_objects`;
- local fallback reconstruction in API routes via `service.node_advertisement()`.

That means the object view is usable, but it does not yet have its own storage boundary. This blocks the next architectural steps in RFC-0046 and RFC-0061:

- retention and lifecycle policy;
- object ingestion rules;
- manifests and completeness views;
- replication and repair;
- cleaner separation between node discovery and object storage.

## Scope

This slice adds:

- a standalone in-memory Registry Object store inside `RegistryService`;
- explicit ingestion methods for immutable canonical Registry Objects;
- list/get behavior that reads from the standalone object store first;
- compatibility fallback to node-advertisement-backed objects when needed;
- local API fallback wiring that ingests local projected objects into the store.

This slice does not add:

- durable disk persistence;
- retention policy enforcement;
- manifests or segment roots;
- replication or repair flows;
- artifact byte storage;
- removal of node-advertisement canonical object fields.

## Approved Approach

We will implement the compatibility-first path:

1. Add a dedicated object store to `RegistryService`.
2. Keep node-backed object views working as fallback.
3. Prefer standalone stored objects during list/get.
4. Continue preserving deduplicated source metadata.
5. Keep default response shapes backward-compatible.

This intentionally creates a temporary dual-source model:

- standalone object store as the primary local persistence boundary;
- node advertisement canonical object arrays as a compatibility source.

That is acceptable because it reduces migration risk while still giving the codebase a real architectural boundary to build on.

## Alternatives Considered

### 1. Standalone object store inside `RegistryService` with compatibility fallback

Recommendation: Yes.

Pros:

- small, safe, incremental change;
- preserves current registry and operator API behavior;
- introduces the right ownership boundary for RFC-0046 object handling;
- avoids immediate churn in discovery and advertisement flows.

Cons:

- temporary dual-source logic;
- some deduplication rules must be explicit.

### 2. Replace node-backed object views immediately and read only from the new store

Recommendation: Not yet.

Pros:

- cleaner architecture sooner;
- fewer long-term code paths.

Cons:

- larger change surface;
- higher risk of breaking current discovery and local fallback behavior;
- unnecessary for this slice.

### 3. Keep object persistence in `HypervisorService` and let `RegistryService` proxy it

Recommendation: No.

Pros:

- short-term local simplicity.

Cons:

- weak storage boundary;
- blurs responsibility between hypervisor execution state and registry object state;
- makes later replication/manifests harder to layer in cleanly.

## Proposed Design

### RegistryService responsibilities

`RegistryService` will own:

- registered node advertisements;
- standalone immutable registry objects;
- deduplicated object list/get views that merge store-backed and compatibility-backed sources.

### New local storage shape

The service will maintain a separate in-memory mapping keyed by `object_id`.

Recommended shape:

```python
_registry_objects: dict[str, dict]
```

Each stored record should preserve the canonical envelope fields already exposed today, plus optional payload data.

### Ingestion API

`RegistryService` should gain explicit object ingestion methods, for example:

- `upsert_registry_object(record)`
- `ingest_registry_objects(records)`

These methods should:

- accept canonical registry object dicts or model payloads;
- normalize to the current JSON-style shape used by API responses;
- preserve `payload` when present;
- key objects by immutable `object_id`.

Because the objects are immutable by contract, “upsert” here means:

- same `object_id` and same content: idempotent no-op;
- same `object_id` and conflicting content: reject.

The exact conflict behavior can be minimal in this slice, but it should not silently replace different content under the same `object_id`.

### Read path

`list_registry_objects()` and `get_registry_object()` should:

1. read from the standalone object store first;
2. include source metadata for stored objects;
3. merge in node-advertisement-backed objects only when the same `object_id` is not already present;
4. preserve existing filters and `include_payload` behavior.

This keeps standalone persistence authoritative without breaking compatibility.

### Local API fallback

When the API uses `_effective_registry_service()` without an externally supplied registry service, it should:

1. build the local node advertisement as it already does;
2. upsert the local node advertisement for discovery compatibility;
3. ingest `canonical_registry_objects` into the standalone store;
4. serve object list/get from the store-backed registry view.

This is the key bridge that makes local object routes stop depending only on nested advertisement state.

## Expected Behavior

After this slice:

- registry object list/get still works for local operator routes;
- payload retrieval still works through `include_payload`;
- standalone store-backed objects are returned even if node-advertisement compatibility paths remain;
- the implementation has a real local object persistence boundary ready for later retention/manifests/replication work.

## Testing Strategy

Use TDD with a narrow red-green cycle.

### Service tests

Add failing tests for:

- storing a registry object directly in `RegistryService` and retrieving it by `object_id`;
- listing store-backed objects without any node advertisement present;
- preferring a standalone stored object over a node-backed compatibility copy with the same `object_id`;
- preserving `include_payload` behavior for stored objects.

### API tests

Add failing tests for:

- local `/operators/registry/objects` working through the standalone store path;
- local `/operators/registry/objects/{object_id}` returning an ingested store-backed object;
- `include_payload=true` continuing to work through that path.

### Regression expectations

Existing tests for:

- node advertisement canonical sections;
- registry discovery;
- registry object query filters;
- payload retrieval;

should remain green without changing default response shapes.

## Risks

### Dual-source divergence

There will temporarily be two sources:

- standalone store;
- node-backed compatibility data.

Mitigation:

- make standalone store primary for reads;
- merge compatibility data only as fallback;
- keep tests explicit about precedence.

### Silent object conflict

If two different payloads are inserted under one `object_id`, the service could accidentally hide corruption.

Mitigation:

- reject conflicting content for the same `object_id`;
- keep idempotent re-insertion allowed.

### Over-expanding scope

It would be easy to slide into manifests, retention, or durable storage.

Mitigation:

- keep this slice strictly in-memory and local;
- leave replication/retention as later steps.

## Non-Goals Reconfirmed

This slice is not:

- full RFC-0046 completion;
- a manifest or completeness implementation;
- retention enforcement;
- durable object persistence;
- RFC-0061 replication.

It is only the storage-boundary step that makes those future slices technically clean.

## Next Step After This Slice

If this lands cleanly, the next logical slice is:

- standalone Registry object lifecycle and retention metadata;

or, if we stay closer to RFC-0061:

- first manifest/inventory scaffolding over the standalone store.
