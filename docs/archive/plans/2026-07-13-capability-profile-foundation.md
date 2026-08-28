# Capability Profile Foundation

## Goal

Add the minimal canonical/profile layer needed to align the implementation with the new RFC-0045 and RFC-0049 direction without rewriting the full endpoint stack.

## Scope

This slice introduces:

- canonical capability definitions surfaced by the node advertisement;
- canonical endpoint feature profiles;
- canonical endpoint limit profiles;
- canonical endpoint implementation profiles;
- advertisement bindings to the exact capability/profile hashes used by a published offer.

## Approach

We keep the implementation thin and compatibility-first.

1. Derive canonical capability definitions from the existing workload-to-capability mapping and legacy runtime assumptions.
2. Derive endpoint feature, limit and implementation profiles from published endpoint configuration records rather than inventing a second source of truth.
3. Bind published advertisements to those profile hashes so Registry and Marketplace consumers can verify that an offer references one exact capability/profile surface.
4. Extend registry discovery payloads and canonical candidate rows to expose those bindings.

## Non-Goals

- full RFC-0045 schema coverage for request/response/event contracts;
- full Marketplace policy object decomposition;
- new ledger operations or certification logic;
- persistence of these profiles as standalone Registry Objects.

## Expected Outcome

After this slice, node advertisements and canonical discovery results should expose a stable capability/profile foundation that later RFC-alignment work can build on without reworking the existing publication/session flow.
