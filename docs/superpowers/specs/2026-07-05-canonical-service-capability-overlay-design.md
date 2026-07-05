# Canonical Service Capability Overlay Design

## Summary

This spec defines how the repository adopts the new RFC set from `C:\Users\admin\Documents\AiDN` as the authoritative architecture without destabilizing the currently working hypervisor, endpoint, session, and dashboard stack.

The selected strategy is a compatibility-first overlay.

The repository will move its canonical language and new implementation surfaces toward:

- `Hypervisor`
- `Protocol Service`
- `Capability`
- `Capability Runtime`
- `Endpoint`
- `Advertisement`
- `Service Verification`
- `Reputation Profile`
- `Epoch Task`

At the same time, the existing `bundle` and `provider plugin` layers will remain temporarily available as a compatibility layer inside the compute path.

The immediate implementation slice is not a full rewrite.

It is the introduction of a canonical domain layer plus a compute compatibility layer that lets the rest of the codebase evolve toward the new RFC model.

Authoritative source documents for this migration:

- `RFC-0039 Hypervisor Service Model`
- `RFC-0040 Service Verification Framework`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0042 Hypervisor Network Protocol`
- `RFC-0043 Hypervisor Lifecycle`
- `RFC-0044 Session Protocol`
- `RFC-0045 Capability Architecture`
- `RFC-0046 Registry Architecture`
- `RFC-0048 Epoch Engine`
- `RFC-0049 Distributed Marketplace & Advertisement Registry`
- `RFC-0053 Capability Runtime Specification`

Relevant existing repository references:

- [ROADMAP.md](../../../ROADMAP.md)
- [00_VISION.md](../../../00_VISION.md)
- [02_ARCHITECTURE.md](../../../02_ARCHITECTURE.md)
- [docs/product/UX-0001-hypervisor-operator-journey.md](../../product/UX-0001-hypervisor-operator-journey.md)
- [docs/product/UX-0002-endpoint-session-and-payment-flow.md](../../product/UX-0002-endpoint-session-and-payment-flow.md)
- [docs/product/RFC-0035-validation-escrow-system.md](../../product/RFC-0035-validation-escrow-system.md)
- [docs/product/RFC-0036-aidn-ledger-state-machine.md](../../product/RFC-0036-aidn-ledger-state-machine.md)
- [docs/product/RFC-0037-settlement-engine.md](../../product/RFC-0037-settlement-engine.md)

## Problem Statement

The current codebase was built around a public operational model that centers on:

`provider plugin -> bundle -> endpoint`

That model was useful for getting the local hypervisor, registry, session, and dashboard surfaces working.

However, the new RFC set establishes a different canonical architecture:

- the Hypervisor is one software platform;
- protocol responsibilities emerge from enabled services;
- capabilities become first-class protocol objects;
- runtimes become the canonical execution boundary;
- providers become private runtime implementation details;
- advertisements become the public discovery surface;
- service verification and reputation become structured protocol layers rather than free-floating metadata.

If the repository continues to extend the current public `bundle/provider` model as if it were canonical, the gap between code and architecture will widen.

The result would be predictable:

- new work would harden the wrong abstractions;
- future verification, reputation, registry, and marketplace work would accumulate translation debt;
- UI and API contracts would keep exposing legacy structures as if they were protocol primitives.

The repo therefore needs a controlled migration path that preserves the current working product while explicitly changing the canonical model under it.

## Product Goal

The goal of this slice is to establish a canonical architectural overlay in both code and docs.

After this slice:

- new docs and roadmap language use `services / capabilities / runtimes / advertisements`;
- the codebase contains explicit first-class types and payloads for those concepts;
- current `bundle/provider` execution continues to work, but only as a compatibility layer under `Compute Service`;
- future RFC implementation work can land on the canonical model instead of extending the legacy one.

This slice is successful when the repo is no longer forced to choose between:

- preserving current behavior; and
- moving toward the new RFC architecture.

## Non-Goals

This slice does not include:

- a full transport implementation of `RFC-0042 Hypervisor Network Protocol`;
- a complete distributed registry replication engine;
- a full consensus-service implementation;
- a full reputation or epoch scheduler implementation;
- deletion of all existing bundle/provider APIs;
- immediate complete dashboard rewrite into the new terminology;
- replacement of all session, endpoint, or validation logic.

This slice is an architectural realignment layer, not a full protocol completion pass.

## Selected Approach

Use a compatibility-first overlay.

This means:

1. Introduce canonical domain objects now.
2. Keep legacy operational surfaces working.
3. Map legacy objects into canonical objects instead of pretending they are already the same thing.
4. Make new implementation work target the canonical objects first.
5. Remove or narrow legacy facades only after the canonical paths are proven.

This is the lowest-risk approach that still treats the new RFC set as authoritative rather than aspirational.

## Alternatives Considered

### 1. Hard Rewrite Now

Replace the existing public `bundle/provider` stack immediately with a pure `service/capability/runtime` model.

Rejected because:

- the current repo already contains working sessions, endpoint publication, dashboard, and registry flows;
- a hard rewrite would create a very large blast radius across API, UI, persistence, and tests;
- it would slow feature progress while offering limited short-term product value.

### 2. Docs-Only Alignment

Update docs and roadmap to match the new RFCs but delay code changes.

Rejected because:

- it would create immediate code-doc drift;
- developers would keep extending the old model because the code still encourages it;
- the next several milestones would become harder, not easier.

### 3. Compatibility-First Overlay

Introduce the canonical layer in code and docs while keeping current execution flows alive behind compatibility mappings.

Selected because:

- it lets the repo adopt the new RFC architecture immediately;
- it avoids a destabilizing big-bang refactor;
- it gives future work a correct target abstraction;
- it preserves momentum on the working operator product.

## Architectural Frame

The canonical architectural frame becomes:

`Hypervisor -> Protocol Services -> Capability Runtimes -> Endpoints -> Advertisements`

Supporting protocol layers become:

- `Service Verification`
- `Reputation Profiles`
- `Epoch Tasks`
- `Ledger / Settlement / Escrow`

The current legacy frame:

`provider plugin -> bundle -> endpoint`

is reclassified as:

`Compute Service internal compatibility layer`

That classification matters.

It means:

- `bundle` is no longer a protocol primitive;
- `provider plugin` is no longer a public discovery primitive;
- runtime-oriented and capability-oriented objects become the public architectural surface for new work.

## Domain Mapping

The migration needs one explicit mapping table.

### Canonical Objects

- `Hypervisor`
  - the node-local software platform
- `Protocol Service`
  - `compute`, `registry`, `validation`, `consensus`
- `Capability`
  - immutable identifier such as `llm.chat`, `speech.stt`, `image.generate`
- `Capability Runtime`
  - one runtime service implementing exactly one capability
- `Endpoint`
  - a published or draft execution surface exposed by a runtime
- `Advertisement`
  - signed discoverable resource metadata
- `Service Verification Report`
  - evidence that a service fulfilled protocol duties
- `Reputation Profile`
  - structured metric set for hypervisors, services, and endpoints

### Legacy To Canonical Mapping

- current `provider plugin`
  - becomes a private provider implementation adapter inside a capability runtime
- current `bundle`
  - becomes a local compute-supply configuration record used by the compute compatibility layer
- current `runtime handle`
  - becomes an implementation of canonical `Capability Runtime` process state
- current registry node advertisement
  - becomes a temporary projection that must later derive from canonical service and advertisement state
- current endpoint publication
  - becomes the first signed building block toward canonical advertisement publication

## Implementation Tracks

This migration is too broad for one undifferentiated refactor.

It should be executed across five coordinated tracks.

### Track A: Canonical Domain Layer

Introduce first-class code constructs for:

- protocol services;
- capabilities;
- capability runtimes;
- advertisements;
- reputation profiles;
- service verification descriptors.

This track changes the repo’s vocabulary and data model without yet removing legacy behavior.

### Track B: Compute Compatibility Layer

Reframe existing `provider/bundle/runtime` code under `Compute Service`.

This track does not delete the current machinery.

It wraps and reclassifies it so future code consumes canonical runtime/capability views instead of the raw legacy structures.

### Track C: Registry And Marketplace Realignment

Move discovery away from `node + bundles` as the canonical public shape.

The registry and marketplace should gradually expose:

- advertisements;
- service records;
- endpoint records;
- runtime capability records.

Legacy flattened discovery may continue temporarily as a projection from those canonical records.

### Track D: Verification, Reputation, And Epoch Foundations

Prepare the repo for:

- service verification contracts;
- structured reputation profiles;
- epoch-scheduled verification and reward work.

This track provides the trust architecture needed by the new RFC set.

### Track E: Operator Product Migration

Update operator-facing product surfaces from:

- `Providers / Bundles` as dominant concepts

toward:

- `Services / Capabilities / Runtimes / Endpoints`

This should happen only after the canonical domain layer exists, so the UI is not forced to speak in abstractions the backend does not own.

## Recommended Delivery Order

The order of work should be:

1. `Canonical Domain Layer`
2. `Compute Compatibility Layer`
3. `Registry And Marketplace Realignment`
4. `Verification, Reputation, And Epoch Foundations`
5. `Operator Product Migration`

This order keeps the codebase stable while moving new work toward the new RFC architecture.

## First Implementation Slice

The immediate implementation slice is:

`Canonical Service Capability Overlay`

It includes four deliverables.

### 1. Canonical Service Model In Code

The codebase gains explicit models for:

- active protocol services;
- service status and enablement;
- service responsibilities and role derivation.

At minimum, the repo should explicitly model:

- `Compute Service`
- `Registry Service`
- `Validation Service`
- `Consensus Service` as a dormant but explicit future-facing service record

### 2. Canonical Capability And Runtime Model

The codebase gains explicit models for:

- capability identifiers;
- capability runtime identity;
- runtime capability metadata;
- runtime status and features.

Current process-managed runtimes should be representable through this new model even if their underlying orchestration remains unchanged.

### 3. Compute Compatibility Projections

The current bundle/provider world should project into the canonical layer.

That means the repo should provide a clean mapping path from:

- bundle configuration
- provider plugin description
- process runtime state

into:

- compute service view
- capability view
- capability runtime view
- endpoint supply view

The new canonical layer should be readable without requiring consumers to know about bundles.

### 4. Documentation And Roadmap Realignment

The repo docs should be updated so the current product and engineering direction is stated in canonical terms.

This includes:

- `ROADMAP.md`
- `00_VISION.md`
- `02_ARCHITECTURE.md`
- product docs cross-links where needed

The docs must clearly state which current concepts are transitional and which are canonical.

## API And UI Impact For This Slice

This slice should make a minimal but explicit public impact.

### API

Add new read-oriented canonical payloads or enrich existing operator payloads with canonical sections, for example:

- active protocol services;
- capability runtime inventory;
- canonical capability identifiers;
- compatibility metadata showing how legacy bundle/provider items map into canonical runtime/service objects.

Legacy API routes may remain intact.

However, newly introduced payload fields should prefer canonical naming.

### UI

The operator dashboard does not need a full rename pass yet.

But it should begin to surface canonical meaning where safe, for example:

- `Providers` as compute implementation inputs;
- `Bundles` as transitional local supply records;
- `Endpoints` as service publication surfaces backed by capabilities and runtimes.

This slice prepares later UI migration without forcing immediate language replacement everywhere.

## Invariants

The following rules should hold after this slice:

1. New RFCs are the authoritative architecture.
2. New code should target canonical `service/capability/runtime` abstractions first.
3. Legacy `bundle/provider` structures remain transitional compute internals.
4. Public discovery and reputation work should grow toward advertisements and service/capability records, not deeper bundle-centric contracts.
5. Existing sessions, endpoints, and publication flows must remain functional during the migration.

## Testing Strategy

Verification for this slice should cover four levels.

### 1. Domain Model Tests

Add focused tests for:

- protocol service model behavior;
- capability identity and runtime mapping;
- compatibility projection from legacy bundle/provider records into canonical structures.

### 2. Operator View Tests

Verify canonical service/runtime/capability sections appear in operator payloads and remain consistent with existing endpoint-first flows.

### 3. API Tests

Verify new canonical read surfaces or payload enrichments serialize correctly and preserve backward compatibility for the current working routes.

### 4. Documentation Consistency

The main roadmap, architecture, and vision docs should be updated in the same branch and reviewed for terminology consistency.

## Exit Criteria

This slice is complete when:

- the repo has explicit first-class service/capability/runtime models;
- current bundle/provider execution is formally treated as a compatibility layer;
- operator/API payloads can expose canonical runtime/service meaning without breaking current flows;
- roadmap and architecture docs describe the canonical model rather than the legacy one;
- the next implementation slice can build registry, reputation, verification, and marketplace work on the canonical layer instead of extending bundle-centric contracts.
