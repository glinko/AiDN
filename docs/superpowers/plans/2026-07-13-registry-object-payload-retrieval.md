# Registry Object Payload Retrieval

## Goal

Expose canonical Registry Object payloads through the standalone registry object view, without changing the default lightweight envelope responses.

## Scope

This slice introduces:

- payload-bearing canonical registry object projection for locally published objects;
- optional `include_payload` support in `RegistryObjectQuery`;
- `RegistryService` support for returning payloads on demand;
- operator API support for payload-inclusive object list and point lookup.

## Approach

Keep the default responses lean and backward-compatible.

1. Extend projected canonical registry objects with optional canonical payload data.
2. Ensure each returned payload matches the existing `payload_hash` semantics.
3. Add `include_payload` as an explicit opt-in for list and point lookups.
4. Preserve the existing deduplication and source metadata behavior.

## Non-Goals

- standalone registry payload persistence outside node advertisements;
- artifact byte retrieval;
- manifest, retention, or replication changes;
- changing existing default response shapes to always include payloads.

## Expected Outcome

After this slice, registry object lookup can return canonical payload content when requested, which closes the gap between object envelopes and usable protocol object inspection.
