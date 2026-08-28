# Registry Object Envelope

## Goal

Turn the existing local hash-bound capability, profile, and accounting artifacts into one shared immutable Registry Object envelope without introducing full Registry persistence yet.

## Scope

This slice introduces:

- a common registry object envelope model;
- projected registry objects for:
  - capability definitions;
  - endpoint feature profiles;
  - endpoint limit profiles;
  - endpoint implementation profiles;
  - accounting contracts;
- exposure of those envelopes through `canonical_overlay_inventory`;
- exposure of those envelopes through `node_advertisement`.

## Approach

Keep the change compatibility-first and projection-based.

1. Reuse existing payload hashes where they already exist.
2. Derive object IDs deterministically from object type, object version, and payload hash.
3. Project envelopes from already-computed capability/profile records and from the existing accounting contract derivation path.
4. Do not add full Registry storage, manifests, replication, or query semantics in this slice.

## Non-Goals

- standalone persisted Registry Object storage;
- profile/accounting query APIs;
- Registry manifests, segment roots, or replication;
- replacing current canonical overlay/profile fields with object references only.

## Expected Outcome

After this slice, the implementation will expose a stable local Registry Object layer that later work can persist, replicate, and verify without redesigning the object identities again.
