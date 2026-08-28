# Endpoint-First Shell Contract Consolidation Design

Date: 2026-07-06
Status: Approved for planning

## Purpose

This slice completes the next step of the endpoint-first migration by moving the operator shell from mixed bootstrap and bundle-centric behavior to one canonical endpoint-first contract.

The goal is not a cosmetic refresh.

The goal is to make `Endpoints` the real operator control plane while `Home`, `Providers`, and `Bundles` become focused workflow surfaces that prepare, summarize, and hand off into that control plane.

This design follows:

- [UX-0001 Hypervisor Operator Journey](../../product/UX-0001-hypervisor-operator-journey.md)
- [UX-0002 Endpoint Session and Payment Flow](../../product/UX-0002-endpoint-session-and-payment-flow.md)
- [RFC-0016 Wallet and Identity](../../product/RFC-0016-wallet-and-identity.md)
- [ROADMAP.md](../../../ROADMAP.md)
- [2026-07-05-endpoint-first-migration-design.md](2026-07-05-endpoint-first-migration-design.md)
- [2026-07-06-endpoint-guided-proxy-flow-design.md](2026-07-06-endpoint-guided-proxy-flow-design.md)

## Problem Statement

The app already has enough endpoint-first capability to operate the product correctly:

- endpoint manifests and snapshots;
- endpoint publication, proof, and sync state;
- endpoint-first API routes;
- guided onboarding into the first published local endpoint;
- remote and proxy endpoint flows;
- paid session controls.

However, the operator shell still has a structural split:

- `Endpoints` already behaves like the primary service workspace;
- `Home`, `Providers`, and `Bundles` still carry older bootstrap-centric and bundle-centric decision paths;
- parts of recommendation and CTA logic still live as fragmented UI inference instead of one endpoint-first read model.

The result is not a missing-feature problem.

It is a contract problem.

The product exposes multiple centers of gravity at the same time:

- `Home` can still feel like a mixed bootstrap status board;
- `Providers` can still feel like a destination rather than supply preparation;
- `Bundles` can still feel closer to publication than they should;
- `Endpoints` is functionally central, but not yet enforced as the canonical operator contract across the shell.

This is risky because the next roadmap layer, `M5` trust and validation, should not be built on top of transitional shell logic.

## Product Goal

The next slice must make the shell feel like one coherent operator product:

- `Endpoints` owns service lifecycle;
- `Home` owns agenda and next-step guidance;
- `Providers` owns execution-supply preparation;
- `Bundles` owns endpoint relationship visibility;
- publication, proof, privacy, proxy routing, sessions, and validation intent remain endpoint-attached concerns.

The product should communicate one operator journey:

`wallet -> supply ready -> endpoint exists -> publish -> sync/proof -> optional validation`

without parallel competing control surfaces.

## Non-Goals

This slice does not include:

- a full `M5` rating, reputation, or validation runtime;
- replacement of all legacy APIs in one pass;
- a new persistence model;
- major remote/proxy protocol expansion;
- settlement or ledger redesign;
- a full visual redesign of the dashboard.

This is a contract-consolidation slice.

It is allowed to leave a transitional adapter layer in place as long as operator behavior clearly converges on the endpoint-first model.

## Chosen Approach

We will implement an endpoint-first contract consolidation layer.

That means:

- `Endpoints` becomes the canonical operator-facing lifecycle contract;
- `Home`, `Providers`, and `Bundles` consume centralized endpoint-first summaries instead of recomputing workflow meaning independently;
- legacy bootstrap and bundle-centric branches are reduced to factual inputs or transitional adapters;
- deep lifecycle actions in non-endpoint workspaces are removed or visually demoted in favor of explicit handoff into `Endpoints`.

This is the recommended path because it improves both architecture and UX without the regression risk of a hard rewrite.

## Alternatives Considered

### 1. Endpoint-First Contract Consolidation

Centralize endpoint-first read models, route supporting workspaces into `Endpoints`, and collapse legacy logic behind adapters.

Selected because:

- it solves the real product problem rather than only updating copy;
- it reduces future `M5` risk;
- it preserves working flows while tightening the contract around them.

### 2. Hard Cut To Endpoint-First

Delete older bootstrap and bundle-centric paths in the same slice and switch every workspace to a pure endpoint-first contract immediately.

Rejected because:

- it creates too much regression risk in a shell that already has working onboarding, proxy, and session flows;
- it would combine behavior migration and large cleanup into one risky release.

### 3. UI-First Cleanup

Change labels, hierarchy, and CTA emphasis while keeping current payload logic mostly as-is.

Rejected because:

- it leaves the contract fragmented;
- the shell would still infer meaning in too many places;
- `M5` would still land on a transitional foundation.

## Architecture

### Canonical Center

`Endpoints` becomes the canonical operator contract for:

- draft lifecycle;
- publication;
- proof and sync state;
- privacy and sharing posture;
- proxy target attachment;
- paid session policy;
- optional validation request state.

Any workspace that needs to initiate or continue one of those concerns should hand the operator into `Endpoints`.

### Supporting Workspaces

`Home`, `Providers`, and `Bundles` stay important, but with narrower responsibilities:

- `Home` is the agenda and next-step surface;
- `Providers` is the execution-supply preparation surface;
- `Bundles` is the endpoint-relationship surface.

These screens should summarize facts and recommend the next step, not own duplicate lifecycle controls.

### Transitional Adapter Layer

Legacy bootstrap and bundle-centric domain outputs may still exist during the migration.

They should be treated as inputs to a centralized endpoint-first view-model layer rather than independent product contracts.

This keeps risk low while allowing the UI to converge on one behavior model.

### Read-Model Direction

The shell should prefer server-computed endpoint-first state over scattered client-side inference.

At minimum, one canonical read-model family should own:

- endpoint pipeline state;
- dominant CTA selection;
- provider readiness toward endpoint creation;
- bundle-to-endpoint relationship state;
- handoff metadata into `Endpoints`.

## UX And Behavior Contract

### Home

`Home` should always communicate one endpoint-centric next step.

Expected pipeline states:

- wallet missing;
- no usable supply;
- supply ready, no endpoint yet;
- draft endpoint exists;
- published endpoint exists but drifted;
- published endpoint exists and is in sync;
- optional validation follow-up available.

Primary CTA rules:

- wallet missing -> `Configure Wallet`
- no usable supply -> `Open Providers`
- supply ready, no endpoint -> `Create Endpoint`
- draft endpoint exists -> `Open Endpoints`
- published endpoint drifted -> `Republish In Endpoints`
- published endpoint in sync -> `Manage Endpoint`

Secondary actions may exist, but should remain visually subordinate.

`Home` should stop acting like a mixed bootstrap dashboard and start acting like an endpoint lifecycle agenda.

### Providers

`Providers` is not a destination.

Its primary question is whether local execution supply is ready to support endpoint lifecycle.

Expected provider-facing readiness states:

- `not_attached`
- `attached_no_usable_supply`
- `ready_for_endpoint_creation`
- `already_backing_endpoint_supply`

Primary action rules:

- setup incomplete -> attach provider or inspect install
- supply ready and no endpoint exists -> `Create Endpoint`
- endpoint already exists -> `Open Endpoint`

Provider controls that do not materially advance endpoint lifecycle should be visually secondary.

### Bundles

`Bundles` should explicitly show endpoint relationship instead of behaving like the last step before publication.

Expected bundle relationship states:

- `no_endpoint`
- `draft_endpoint`
- `published_endpoint`
- `published_drifted`

Primary action rules:

- `no_endpoint` -> `Create Endpoint`
- `draft_endpoint` -> `Open Endpoint`
- `published_endpoint` -> `Open Endpoint`
- `published_drifted` -> `Republish In Endpoints`

Publication, proof, privacy, proxy routing, sessions, and validation should not be deep-managed from bundle-centric UI branches.

### Endpoints

`Endpoints` is the only deep lifecycle workspace.

It should remain the place where operators:

- create and refine endpoint drafts;
- manage publication and proof/sync state;
- manage privacy and sharing policy;
- attach remote routes and proxy targets;
- inspect or edit paid session policy;
- request validation explicitly.

Guided flows should stay inside `Endpoints`, not bounce back into the rest of the shell.

### Legacy Cleanup Rule

If `Home`, `Providers`, or `Bundles` would need a deep lifecycle action, they should hand the operator into `Endpoints` instead of re-implementing that control locally.

This is the key product rule that prevents future contract drift.

## Implementation Scope

This slice includes:

- centralized endpoint-first recommendation and handoff builders;
- `Home` migration to an endpoint pipeline summary;
- `Providers` migration to endpoint readiness and handoff states;
- `Bundles` migration to explicit endpoint relationship states;
- reduction or demotion of duplicate lifecycle controls outside `Endpoints`;
- dashboard tests for CTA and handoff behavior.

This slice does not include:

- full deletion of all old fallback inputs;
- new trust economics runtime;
- a payload-driven guided-flow protocol beyond what already exists;
- remote/proxy protocol redesign.

## Migration Plan

1. Centralize endpoint-first recommendation and state builders.
2. Move `Home` onto the endpoint pipeline read model.
3. Move `Providers` onto provider-to-endpoint readiness and handoff rules.
4. Move `Bundles` onto bundle-to-endpoint relationship rules.
5. Remove or demote duplicate lifecycle controls in non-endpoint workspaces.
6. Update roadmap and implementation notes once tests are green.

This sequence keeps the migration incremental and testable.

## Testing Strategy

Tests should confirm:

- `Home` shows one dominant endpoint-centric CTA for each pipeline state;
- `Providers` route operators toward endpoint creation or endpoint management when supply is ready;
- `Bundles` expose explicit endpoint relationship states and route into `Endpoints`;
- deep lifecycle controls remain centered in `Endpoints`;
- guided and proxy-oriented endpoint flows continue to work after shell consolidation.

The minimum acceptable verification is rendered dashboard coverage plus API-level payload checks for the migrated operator views.

## Definition Of Done

This slice is complete when:

- `Home` no longer behaves like a competing bootstrap dashboard;
- `Providers` clearly prepares supply and hands into `Endpoints`;
- `Bundles` clearly shows endpoint relationship and hands into `Endpoints`;
- `Endpoints` is the only deep lifecycle workspace for publication, proxy, proof, sessions, and validation intent;
- duplicate lifecycle controls in non-endpoint workspaces are removed or intentionally demoted;
- regression tests cover CTA and routing behavior across `Home`, `Providers`, and `Bundles`;
- roadmap and docs state that shell migration is materially complete and `M5` can build on the resulting operator surface.

## Risks

The main risk is that some current UI behavior still depends on legacy assumptions embedded in dashboard rendering and bootstrap payload shape.

That is why this slice should prefer:

- centralized builders;
- explicit tests around rendered state;
- incremental cleanup instead of a hard cut.

## Follow-Up

If this slice lands cleanly, the next major product layer should be:

- `M5` trust, rating, and validation publication on top of the consolidated endpoint-first shell;

with remote/proxy lifecycle and marketplace trust surfaces building on the same contract instead of introducing a second center of gravity.
