# Registry Object Persistence And Query

## Goal

Expose the already-projected immutable Registry Object envelopes as a standalone registry-facing object view with basic listing, filtering, and `object_id` lookup.

## Scope

This slice introduces:

- a Registry Object query model;
- deduplicated Registry Object views derived from stored node advertisements;
- `RegistryService` methods for:
  - list/query objects;
  - get object by `object_id`;
- thin operator API routes for local and registry-backed object lookup.

## Approach

Keep storage compatibility-first.

1. Reuse the existing `RegistryService._nodes` state as the source of persisted object envelopes.
2. Build a deduplicated object view keyed by `object_id`.
3. Preserve source metadata so one object can show which nodes currently advertise it.
4. Let operator routes fall back to the local node advertisement when no external registry service is configured.

## Non-Goals

- new durable storage backend;
- manifest, retention, or replication logic;
- content payload retrieval beyond envelope metadata;
- replacing existing node advertisement or overlay endpoints.

## Expected Outcome

After this slice, the repo will support real registry-style object discovery by `object_id` and basic filters, while still using the current node-advertisement persistence path under the hood.
