# Canonical Advertisement Publication Design

## Summary

This spec defines the next migration slice after the canonical registry and market dual-payload work.

The selected objective is to replace the current empty `canonical_advertisements` publication with deterministic endpoint-backed canonical advertisement records.

After this slice:

- published endpoint configurations will appear in `canonical_advertisements`;
- unpublished, superseded, and revoked endpoint publications will not appear there;
- canonical market discovery will have a real publication object to consume instead of a placeholder list;
- legacy `published_endpoints`, `bundles`, and legacy market flows will remain intact.

This is the first step that turns the canonical market model from a read-model scaffold into a real network publication surface.

## Problem Statement

The repository already publishes:

- canonical protocol services;
- canonical capability runtimes;
- canonical compute compatibility mappings;
- canonical discovery and market read models.

However, `HypervisorService.node_advertisement()` still emits:

`canonical_advertisements = []`

That means the canonical market layer currently lacks a real public object representing what a node is actually publishing for remote consumption.

The endpoint publication subsystem already contains the right source data:

- signed publication identity;
- configuration hash;
- owner wallet;
- visibility;
- endpoint and model metadata.

But that publication state is only exposed through legacy `published_endpoints` summaries and proof-style API routes. It is not yet projected into the canonical registry contract.

If this gap remains:

- the canonical market stays structurally correct but operationally incomplete;
- future proof, routing, and session flows would still have to begin from legacy endpoint summaries;
- canonical identity would remain disconnected from the real endpoint publication lifecycle.

## Product Goal

The goal of this slice is to publish real canonical advertisement records from endpoint publication state.

After this slice:

- a published endpoint configuration produces one canonical advertisement record;
- the canonical advertisement is derived from the active signed publication record;
- the canonical advertisement can be joined to proof and market identity surfaces by publication and configuration hash;
- legacy and canonical publication views remain dual-stack.

This is a publication projection slice, not a routing or settlement slice.

## Non-Goals

This slice does not include:

- rewriting session open or dispatch to use canonical identities;
- changing settlement, validation, wallet, or ledger semantics;
- introducing a separate canonical publication database or store;
- publishing multiple canonical advertisements per endpoint for each capability;
- changing the current `published_endpoints` summary contract;
- redesigning the operator dashboard UI around canonical publication status.

Those belong to later proof, routing, and market UX slices.

## Selected Approach

Use the existing endpoint publication subsystem as the single source of truth.

Specifically:

- read active publication records from `EndpointPublicationService`;
- project those records into `CanonicalAdvertisementRecord` values;
- keep that projection deterministic and stateless;
- surface the projected records through `HypervisorService.node_advertisement()`.

This is preferred over introducing a new store because:

- the active publication record already contains the required identity and hash data;
- signed publication state already has lifecycle semantics for publish, supersede, and revoke;
- the current dual-payload node advertisement can be extended without changing registry persistence;
- the implementation stays small, testable, and reversible.

## Architecture

The architecture for this slice becomes:

`EndpointPublicationService`
-> returns publication records
-> active `published` records are selected
-> canonical advertisement projector maps them into canonical advertisement rows
-> `HypervisorService.node_advertisement()` emits those rows in `canonical_advertisements`

The projection should live beside the existing canonical overlay helpers so the service layer remains thin.

Recommended shape:

- `project_protocol_services(service)`
- `project_capability_runtimes(service)`
- `project_compute_compatibility(service)`
- `project_canonical_advertisements(publication_records)`

`HypervisorService.node_advertisement()` should continue to assemble the overall node envelope, but the transformation logic for advertisement records should not be inlined into that method.

## Data Contract

### Source Record

The source object is `PublishedEndpointConfiguration`.

Relevant fields already available:

- `publication_id`
- `endpoint_id`
- `owner_wallet`
- `node_id`
- `configuration_hash`
- `model_class`
- `capabilities`
- `publication`
- `status`
- `published_at`

Only records with:

- `status == "published"`

are eligible for canonical advertisement projection.

### Canonical Advertisement Record

Each active publication record yields one `CanonicalAdvertisementRecord`.

Field mapping:

- `advertisement_id`
  Deterministic value derived from publication identity. Initial rule: `adv-{publication_id}`.
- `resource_type`
  Always `"endpoint"` in this slice.
- `owner_wallet`
  Copied from publication record.
- `hypervisor_id`
  Copied from `node_id`.
- `capability_id`
  Derived from publication capabilities.
- `visibility`
  Copied from `publication.visibility`, defaulting only if the publication model already does so.
- `signature_scope`
  Constant value `"configuration_publication"` in this slice.

### Capability Selection Rule

This slice intentionally emits one canonical advertisement per active endpoint publication record.

If the publication record contains:

- exactly one capability: use that capability directly;
- multiple capabilities: use the first capability in the stored ordered list as the primary `capability_id`.

This is an explicit temporary rule for this slice.

It avoids inventing multi-advertisement expansion before there is a stronger capability taxonomy and routing model.

## Behavior

### Publication Inclusion

If an endpoint has an active published configuration:

- it appears in `published_endpoints`;
- it also appears in `canonical_advertisements`.

If an endpoint publication has been:

- superseded;
- revoked;
- never published;

then it must not appear in `canonical_advertisements`.

### Determinism

The canonical advertisement list must be a deterministic function of:

- current endpoint publication records;
- the endpoint publication lifecycle state.

No extra mutable canonical registry state may be introduced.

### Backward Compatibility

This slice must preserve:

- legacy `bundles`;
- legacy `published_endpoints`;
- current registry advertisement shape outside the additive canonical publication rows;
- current proof and endpoint publication API behavior.

Canonical publication is additive, not a replacement.

## Testing Strategy

The test plan for this slice should cover:

- `node_advertisement()` includes canonical advertisement records for active publications;
- `node_advertisement()` leaves `canonical_advertisements` empty when no publications exist;
- revoked and superseded publication records are excluded from canonical advertisement output;
- canonical advertisement field mapping is correct for:
  - `advertisement_id`
  - `owner_wallet`
  - `hypervisor_id`
  - `visibility`
  - `capability_id`
  - `signature_scope`
- legacy `published_endpoints` assertions remain green.

Regression focus:

- current endpoint publication service tests must keep passing;
- current registry advertisement tests must keep passing;
- current market payload tests must keep passing after real canonical advertisements begin to appear.

## Implementation Notes

The most likely files involved are:

- `src/aidn_hypervisor/canonical_projection.py`
- `src/aidn_hypervisor/service.py`
- `src/aidn_hypervisor/endpoint_publications/models.py`
- `src/aidn_hypervisor/endpoint_publications/service.py`
- `tests/test_service.py`
- `tests/endpoint_publications/test_service.py`
- selected market/API tests where canonical publication begins surfacing

Preferred implementation order:

1. add failing service-level tests for canonical advertisement publication;
2. add projector helper for canonical advertisement rows;
3. wire projector output into `node_advertisement()`;
4. add lifecycle regression tests for superseded and revoked publication exclusion;
5. run the focused endpoint publication and registry advertisement suites.

## Success Criteria

This slice is successful when:

- a published endpoint produces a real canonical advertisement row;
- canonical advertisement identity is derived from active publication identity;
- canonical publication rows disappear when publication is revoked or superseded;
- no legacy publication or market contract is broken;
- the next slice can join canonical market objects to proof and configuration hash surfaces without inventing a new source of truth.
