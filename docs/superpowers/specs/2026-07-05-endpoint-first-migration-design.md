# Endpoint-First Migration Design

## Summary

This spec defines the next operator-product slice after guided dashboard onboarding.

The goal is to make `Endpoint` the canonical operator-facing object across the dashboard, while keeping `Provider`, `Bundle`, and `Install` as supporting layers that feed or maintain endpoint lifecycle.

This slice does not introduce a new backend subsystem.

It changes how the existing operator shell interprets and presents state so that:

`Provider -> Bundle -> Endpoint -> Publication/Proof/Validation`

becomes the dominant operator mental model.

Authoritative product references:
- [UX-0001 Hypervisor Operator Journey](../../product/UX-0001-hypervisor-operator-journey.md)
- [UX-0002 Endpoint Session and Payment Flow](../../product/UX-0002-endpoint-session-and-payment-flow.md)
- [RFC-0016 Wallet and Identity](../../product/RFC-0016-wallet-and-identity.md)
- [ROADMAP.md](../../../ROADMAP.md)
- [2026-07-04-guided-dashboard-onboarding-design.md](./2026-07-04-guided-dashboard-onboarding-design.md)

## Problem Statement

The current dashboard already has the core ingredients for endpoint-first operation:
- endpoint manifests and snapshots;
- versioned `/api/v1/endpoints` routes;
- endpoint publication, proof, and sync state;
- guided onboarding that reaches a first published local Endpoint.

However, the operator shell still carries older bundle-centric and bootstrap-centric emphasis.

The current product issue is not missing capability.

It is competing hierarchy:
- `Home` still mixes multiple bootstrap and inventory signals;
- `Providers` and `Bundles` can still feel like terminal destinations instead of preparatory workflow screens;
- `Endpoints` already holds the core service lifecycle, but the rest of the shell does not consistently treat it as the primary operator workspace.

This leaves the product in an awkward middle state where endpoint-first infrastructure exists, but the UI and payloads still partially communicate an older execution-inventory-first model.

## Product Goal

The next slice must make the operator shell feel aligned with the endpoint-first journey already implied by the codebase and roadmap:
- `Endpoint` is the primary service object;
- `Provider` and `Bundle` help produce or maintain an Endpoint;
- publication, proof/sync state, visibility, and validation intent are operator decisions attached to the Endpoint lifecycle;
- `Home` should always point the operator toward the next endpoint-centric action.

The result should feel like one coherent operating model rather than a dashboard with multiple competing centers of gravity.

## Non-Goals

This slice does not include:
- full removal of all legacy fallback paths;
- storage migration of endpoint or onboarding state;
- new validation economics, rating, or reputation runtime;
- major endpoint service refactors unrelated to operator-shell presentation;
- complete redesign of every workspace;
- remote/proxy execution expansion beyond what is needed to preserve endpoint-first framing.

This is a migration-of-emphasis slice, not a protocol rewrite.

## Selected Approach

Use a view-model-first endpoint migration layer.

This means:
- operator payloads become more explicit about endpoint relationship and next endpoint-centric action;
- `Home` is reframed around endpoint pipeline state rather than general bootstrap state;
- `Providers` and `Bundles` become preparatory screens whose primary job is to feed `Endpoints`;
- `Endpoints` becomes the canonical operator lifecycle workspace;
- shell behavior and CTA hierarchy are updated before any risky data-model changes.

This approach keeps risk low because it relies on interpretation and presentation of existing state rather than forcing a broad persistence or service rewrite.

## Alternatives Considered

### 1. Full Backend-Led Migration

Rewrite operator service contracts first, then redesign the shell afterward.

Rejected because:
- it is higher risk than the product problem requires;
- it would likely force larger persistence and API churn;
- the repo already has enough endpoint-first primitives to make progress at the view-model layer first.

### 2. View-Model-First Migration

Make `operator_views.py` and shell hierarchy communicate a single endpoint-first model while keeping existing state contracts mostly stable.

Selected because:
- it solves the current product problem directly;
- it is incremental and testable;
- it preserves momentum from the onboarding slice;
- it creates a cleaner base for later trust, reputation, and remote-routing work.

### 3. UI-Only Copy Refresh

Only change labels and text in the shell without tightening payload semantics.

Rejected because:
- it would leave real recommendation logic fragmented;
- the UI would still rely on mixed bootstrap and bundle-centric assumptions;
- the migration would remain cosmetic instead of structural.

## Scope

This slice is intentionally limited to three changes.

### 1. `Home` becomes an endpoint pipeline surface

`Home` should show one canonical endpoint status instead of multiple competing bootstrap cues.

Expected states include:
- no endpoint exists yet;
- endpoint draft exists;
- endpoint is published;
- endpoint is published but local configuration has drifted;
- validation remains optional or is already requested.

The primary CTA on `Home` should always point to the next endpoint-centric action.

### 2. `Providers` and `Bundles` become endpoint-producing workspaces

These screens should no longer feel like the end of the workflow.

Instead:
- if a provider has not yet produced a usable local bundle, the screen remains preparatory;
- if a provider or bundle can produce a service, the dominant action becomes `create endpoint` or `open endpoint`;
- if an Endpoint already exists for that bundle, the recommendation should prefer `open endpoint` or `improve endpoint` over repeating bundle-first actions.

### 3. `Endpoints` becomes the canonical operator workspace

This workspace should clearly group:
- draft lifecycle;
- visibility and sharing policy;
- signed publication;
- proof and sync state;
- validation intent;
- later proxy and remote routing lifecycle.

Other workspaces should increasingly hand off into `Endpoints` instead of competing with it.

## Behavioral Contract

### `Home`

`Home` should always communicate one next endpoint-centric step.

Rules:
- if no Endpoint exists, push toward first endpoint creation;
- if a draft exists, push toward review or publish;
- if a published endpoint has drift, push toward sync or republish;
- if a published endpoint is in sync, present it as the primary live service surface;
- validation remains a separate optional operator decision.

### `Providers`

`Providers` is not a final destination.

Rules:
- if no provider has yielded usable local supply, the screen remains setup-oriented;
- once supply is usable, the screen should prefer endpoint creation or opening an existing endpoint;
- provider actions that do not help endpoint lifecycle should visually recede.

### `Bundles`

Every bundle should expose its endpoint relationship explicitly.

Expected relationship states:
- `no_endpoint`
- `draft_endpoint_exists`
- `published_endpoint_exists`

Recommendation logic should use that relationship, not only “first endpoint candidate” heuristics.

### `Endpoints`

`Endpoints` is the default operator decision surface.

It should be the workspace operators enter when they need to:
- turn local execution inventory into a service;
- publish or revoke a network-visible claim;
- compare local and published configuration state;
- request validation when they decide the service is ready.

## Architecture Notes

This slice should stay view-model first.

Expected implementation direction:
- enrich operator payloads with endpoint-relationship metadata and recommendation state;
- keep endpoint and onboarding persistence stable;
- move the shell toward endpoint-first CTA hierarchy without broad service rewrites;
- preserve legacy fallback logic only where still needed for compatibility.

This keeps the data plane stable while tightening the operator experience.

## Testing Strategy

Verification should cover four layers.

### 1. Unit tests

Add focused tests for:
- endpoint-first recommendation logic;
- bundle-to-endpoint relationship mapping;
- home pipeline state selection.

### 2. Operator view tests

Verify `Home / Providers / Bundles / Endpoints` payloads expose:
- canonical endpoint-centric recommendations;
- explicit endpoint relationship state;
- consistent handoff metadata into `Endpoints`.

### 3. API and shell tests

Verify:
- dashboard routes return the new payload shape;
- shell markup exposes the new CTA and copy hierarchy;
- source-level handoff markers remain stable where the shell depends on them.

### 4. Smoke verification

Do one live dashboard pass confirming:
- `Home` points to the next endpoint step;
- `Providers` and `Bundles` drive into `Endpoints`;
- `Endpoints` feels like the primary operator workspace.

## Exit Criteria

This slice is complete when:
- `Home` consistently leads into the next endpoint-centric step;
- `Providers` and `Bundles` clearly behave as endpoint-producing or endpoint-maintenance surfaces;
- `Endpoints` is visibly the canonical operator lifecycle workspace;
- payloads and shell behavior communicate the same endpoint-first hierarchy;
- `ROADMAP.md` can be updated to reflect the next stage of endpoint-first shell migration.
