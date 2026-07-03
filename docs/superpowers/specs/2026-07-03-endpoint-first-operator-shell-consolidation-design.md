# Endpoint-First Operator Shell Consolidation Design

## Summary

This spec defines the next app-development slice after the current docs alignment pass.

The goal is to consolidate the existing operator application around a single endpoint-first dashboard contract while deepening the operator bootstrap loop from:

`wallet -> provider/model -> bundle -> first endpoint -> publish`

This is an app-consolidation milestone, not a new standalone protocol subsystem.

Authoritative product references:
- [UX-0001 Hypervisor Operator Journey](../../product/UX-0001-hypervisor-operator-journey.md)
- [UX-0002 Endpoint Session and Payment Flow](../../product/UX-0002-endpoint-session-and-payment-flow.md)
- [ECO-0000 Economic Principles](../../product/ECO-0000-economic-principles.md)
- [RFC-0016 Wallet and Identity](../../product/RFC-0016-wallet-and-identity.md)
- [ECO-0003 Validation Economics](../../product/ECO-0003-validation-economics.md)
- [RFC-0035 Validation Escrow System](../../product/RFC-0035-validation-escrow-system.md)
- [RFC-0036 AiDN Ledger State Machine](../../product/RFC-0036-aidn-ledger-state-machine.md)
- [ROADMAP.md](../../../ROADMAP.md)

## Problem Statement

The current app already contains most of the underlying operator capabilities:
- owner wallet bootstrap;
- node identity;
- provider and bundle inventory;
- model install jobs;
- endpoint lifecycle and publication;
- paid sessions;
- remote and proxy endpoint flows;
- early trust and validation surfaces.

However, the operator experience is still split across two layers:

1. older dashboard-shaped service methods in `HypervisorService`;
2. richer endpoint-first payload composition in `api.py`.

This causes three problems:
- the first-run operator path is not one clean guided flow;
- dashboard data contracts are partially duplicated;
- future `M5` trust and validation work would land on top of a split operator shell.

## Product Goal

The next slice must make the operator shell feel like one coherent product surface where:
- `Endpoint` is the primary operator object;
- `Providers` and `Bundles` are supporting resources that exist to make endpoints possible;
- `Home` acts as the operator agenda and bootstrap orchestrator;
- the app clearly guides the operator from wallet ownership to a publishable endpoint;
- trust, publication, pricing, privacy, and validation remain explicit operator choices.

## Non-Goals

This slice does not include:
- full `M5` reputation and rating runtime;
- distributed or federated registry work;
- on-chain settlement implementation;
- deep validation forensics or validator governance UX;
- a full redesign of the dashboard visual language.

The slice may expose trust and validation state where already implemented, but it does not aim to complete the full `M5` economic runtime.

## Selected Approach

Build an API-centric operator view-model layer.

The canonical dashboard contract should move out of ad hoc payload assembly in `api.py` and out of UI-shaped methods in `HypervisorService`.

Instead, the app should introduce a dedicated module that:
- composes operator-facing payloads from domain services;
- centralizes next-step and readiness logic;
- provides one consistent contract to the operator dashboard.

`HypervisorService` should not continue to accumulate product-shaped dashboard logic.

Instead, its existing dashboard methods should be preserved only as transitional legacy surfaces and then gradually reduced to factual summaries.

This is important because the domain layer should remain a source of facts and commands, not the long-term owner of UI composition.

## Architecture

### 1. Domain Fact Sources

The existing domain services remain the authoritative source of operational state:
- `HypervisorService`
- `EndpointService`
- `EndpointPublicationService`
- `SessionService`
- `ValidationService`
- remote endpoint and registry services

These services are responsible for:
- domain state;
- mutations and commands;
- persistence;
- process and queue control;
- publication, session, and validation facts.

They should not be expanded into the main owner of dashboard presentation structure.

### 2. Operator View-Model Layer

Add a dedicated module:

- `src/aidn_hypervisor/operator_views.py`

This module becomes the canonical owner of operator-facing dashboard payloads.

Its responsibilities:
- build `Home`, `Endpoints`, `Providers`, `Bundles`, `Installs`, `Market`, and `Remote Endpoints` payloads;
- compute bootstrap funnel status;
- compute `next_step`;
- compute endpoint publication sync and validation/trust summaries;
- normalize how provider, bundle, install, and endpoint readiness are described to the UI.

This module must be read-only and side-effect free.

It composes facts but does not mutate domain state.

### 3. Operator API Layer

`api.py` should become a thin orchestration layer that:
- validates request input;
- invokes domain services for actions;
- invokes `operator_views.py` for payload composition;
- returns canonical operator payloads.

It should no longer own scattered operator-dashboard business logic.

### 4. Dashboard UI Layer

`operator_dashboard.html` should consume the operator view-model contract as its primary data shape.

This slice should expand the current shell rather than redesigning it from scratch.

The main UX shift is structural:
- `Home` becomes a guided bootstrap agenda;
- `Providers`, `Bundles`, and `Installs` become actionable workspaces;
- `Endpoints` remains the center of publish/privacy/validation/proxy control.

## Data Flow

The bootstrap funnel should be normalized around this sequence:

1. `No wallet configured`
2. `Wallet configured, no suitable provider/bundle candidate`
3. `Provider attached or model install available`
4. `Bundle candidate ready for endpoint creation`
5. `Draft endpoint exists`
6. `Published endpoint exists`
7. `Validation is available as explicit follow-up`

The operator UI should not infer these steps independently in multiple places.

Instead, one centralized builder should compute:
- current stage;
- next step;
- blocking conditions;
- best available candidate bundle for first endpoint creation;
- recommended action text.

## Required Payloads

The operator view-model layer should provide the following builders.

### Home

Purpose:
- summarize operator progress;
- guide the next action;
- bridge endpoint management with providers, bundles, installs, and market visibility.

Must include:
- owner wallet state;
- node identity;
- provider count;
- bundle count;
- install counts and actionable install state;
- first endpoint candidate;
- endpoint publication and sync summary;
- operator `next_step`.

### Endpoints

Purpose:
- keep `Endpoint` as the main operator object.

Must include:
- endpoint summary counts;
- endpoint items;
- publication sync state;
- validation state;
- execution strategy and proxy target context;
- visibility mode;
- recommended follow-up action where relevant.

### Providers

Purpose:
- surface attachable and active execution backends as operator resources.

Must include:
- provider inventory;
- provider readiness;
- mapping from providers to available bundles or install targets;
- whether a provider can immediately support endpoint creation.

### Bundles

Purpose:
- show which model/bundle units are ready, disabled, cooling down, or awaiting endpoint use.

Must include:
- bundle readiness;
- runtime readiness;
- whether a bundle is already bound to an endpoint;
- whether the bundle is the best current first-endpoint candidate.

### Installs

Purpose:
- make model install jobs part of the operator funnel instead of background telemetry.

Must include:
- pending/running/failed/completed install jobs;
- whether a completed install is ready for bundle registration;
- recommended next action per job.

### Market And Remote Endpoints

These payloads already exist in richer form and should be normalized into the same operator view-model layer rather than living as separate builder islands.

## Home Funnel Rules

`Home.next_step` should be centralized and deterministic.

The first version should follow these rules:

1. If wallet is not configured:
   - `Create or import a wallet`
2. Else if there is no provider or bundle candidate:
   - `Attach a provider or install a model`
3. Else if a bundle candidate exists but no endpoint draft exists:
   - `Create your first endpoint from <bundle_id>`
4. Else if a draft endpoint exists but is not yet published:
   - `Review pricing, visibility, and publish your endpoint`
5. Else if a published endpoint exists without validation:
   - `Request validation when ready`
6. Else:
   - `Manage remote routes, proxy execution, or additional endpoints`

This rule set may evolve, but it must live in one place.

## Service-Layer Transition Rule

The existing `HypervisorService.operator_dashboard_*()` methods should not be deleted abruptly if they are still useful for tests or fallback paths.

Instead:
- keep them operational during the transition;
- reduce them to factual summaries where possible;
- stop expanding them as the canonical UI contract;
- move all richer product-shaped payload composition into `operator_views.py`.

The desired end state is:
- service layer = facts and commands;
- operator view-model layer = UI contract.

## Operator Routes

This slice should normalize or add operator dashboard routes for:
- `/operators/dashboard/home`
- `/operators/dashboard/endpoints`
- `/operators/dashboard/providers`
- `/operators/dashboard/bundles`
- `/operators/dashboard/installs`
- `/operators/dashboard/market`
- `/operators/dashboard/remote-endpoints`

The route family should feel complete against the required module vocabulary from `UX-0001`, even if deeper modules like `Validation`, `Metrics`, `MCP`, or `Settings` remain outside this implementation slice.

## UI Changes

The dashboard frontend should evolve in place.

### Home

Changes:
- stronger bootstrap funnel presentation;
- clearer recommended next action;
- more visible linkage from install/provider/bundle state to endpoint creation;
- less dependence on generic summary text.

### Providers

Changes:
- dedicated workspace with provider readiness and attachable execution backends;
- visible relationship between provider state and endpoint readiness.

### Bundles

Changes:
- dedicated workspace showing which bundles are ready to become endpoints;
- visible relationship to installs and endpoint creation.

### Installs

Changes:
- dedicated workspace or integrated bundle subview;
- actionable install state rather than passive telemetry rows.

### Endpoints

Changes:
- remain the primary publication object;
- preserve visibility/publication/validation/proxy separation;
- integrate naturally with the bootstrap funnel and provider/bundle readiness.

## Testing Strategy

The slice should add or update tests in four layers.

### 1. View-Model Unit Tests

Add focused tests for:
- home bootstrap next-step logic;
- first endpoint candidate selection;
- provider/bundle/install readiness summaries;
- endpoint publication sync and trust summary composition.

### 2. API Contract Tests

Add tests for:
- `/operators/dashboard/providers`
- `/operators/dashboard/bundles`
- `/operators/dashboard/installs`

These tests should assert shape, key fields, and bootstrap/actionability semantics.

### 3. Regression Tests

Preserve behavior for:
- existing `Home`;
- `Endpoints`;
- `Market`;
- `Remote Endpoints`;
- `Sessions`.

This is important because this slice is a consolidation refactor, not a greenfield replacement.

### 4. Dashboard Shell Smoke Checks

At minimum, verify that:
- the shell still loads;
- the new workspace payloads render without breaking the existing app shell;
- the bootstrap controls still exist and remain wired to the correct actions.

## Rollout Strategy

The implementation should be incremental.

### Phase 1

Introduce `operator_views.py` and move existing richer endpoint and home payload builders there.

### Phase 2

Switch current dashboard routes to use the new module as the canonical source.

### Phase 3

Add `Providers`, `Bundles`, and `Installs` payloads and routes.

### Phase 4

Expand frontend workspaces to consume those routes and express the bootstrap funnel clearly.

### Phase 5

Reduce `HypervisorService.operator_dashboard_*()` methods toward factual summaries and keep only what is needed as transitional support.

## Why This Slice Now

This slice is the best next step because it:
- directly matches the current roadmap priority;
- improves the operator experience before more trust and market complexity is added;
- reduces architectural split in the existing app;
- makes future `M5` and `M6` integration easier;
- strengthens the product identity of the Hypervisor as an operator-facing system rather than a loose collection of backend features.
