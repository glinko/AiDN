# Guided Dashboard Onboarding Design

## Summary

This spec defines the next product slice for the AiDN Hypervisor operator application.

The goal is to close the first-run operator bootstrap loop without introducing a separate wizard application or duplicating the existing dashboard.

The selected direction is a guided dashboard onboarding layer that keeps the existing operator shell intact while steering a new operator through:

`wallet -> provider -> bundle -> first endpoint -> publish`

The first-run onboarding flow is considered complete when the operator publishes the first local Endpoint. Validation remains optional and does not block completion.

Authoritative product references:
- [UX-0001 Hypervisor Operator Journey](../../product/UX-0001-hypervisor-operator-journey.md)
- [UX-0002 Endpoint Session and Payment Flow](../../product/UX-0002-endpoint-session-and-payment-flow.md)
- [ECO-0000 Economic Principles](../../product/ECO-0000-economic-principles.md)
- [RFC-0016 Wallet and Identity](../../product/RFC-0016-wallet-and-identity.md)
- [ROADMAP.md](../../../ROADMAP.md)

## Problem Statement

The current application already contains most of the capabilities needed to reach a first published Endpoint:
- wallet bootstrap;
- provider attachment;
- install and bundle management;
- endpoint creation and publication;
- operator dashboard navigation across those resources.

However, the first-run operator experience is still fragmented.

The current app has three product issues:
- `Home` is informative, but not yet the canonical first-run orchestrator;
- the bootstrap path still depends on older fallback affordances instead of one coherent operator journey;
- advanced features like validation, remote routing, and paid Sessions are already present, but they visually compete with the simpler first-run goal.

This makes the product feel more like a toolkit than a guided operating surface for first-time operators.

## Product Goal

The next slice must make the Hypervisor feel aligned with `UX-0001`:
- first-run should be fast and obvious;
- the operator should not need to understand internal subsystem boundaries;
- the product should guide the operator to the first published Endpoint;
- after onboarding, the same dashboard should continue to function as the normal operating environment.

The onboarding layer must help, not replace, the dashboard.

## Non-Goals

This slice does not include:
- full validation-economics implementation;
- full reputation or rating runtime;
- removal of all older bootstrap-compatible logic on day one;
- marketplace-specific purchasing flows;
- a separate standalone onboarding application;
- mandatory validation before first publish.

This slice is about first-run operator guidance, not about completing all trust or payment systems.

## Selected Approach

Use a guided dashboard layer with persisted onboarding state.

This means:
- the operator keeps the normal dashboard structure;
- `Home` becomes the agenda and progress surface for first-run;
- `Providers`, `Bundles`, and `Endpoints` participate in guided mode;
- onboarding state is persisted so the experience survives reloads and partial progress;
- the onboarding layer completes once the first local Endpoint is published.

This is intentionally not a separate wizard mode and not a purely computed UI-only heuristic.

It is a hybrid:
- current onboarding step is derived from actual system facts;
- onboarding completion and transition history are persisted.

## Alternatives Considered

### 1. Pure Home Overlay

All onboarding controls live directly inside `Home`.

Rejected because:
- it would duplicate real workspace behavior;
- `Home` would grow into a second application shell;
- it would make later maintenance harder.

### 2. Guided Dashboard Layer

`Home` drives progress while the existing workspaces participate in guided mode.

Selected because:
- it preserves the dashboard as the product;
- it avoids duplication;
- it matches the operator journey well;
- it scales naturally into post-onboarding usage.

### 3. Separate First-Run Mode

Rejected because:
- it introduces a second navigation model;
- it creates more migration work later;
- it conflicts with the goal that the dashboard itself is the Hypervisor product.

## User Journey

The onboarding sequence is:

1. No owner Wallet configured
2. Wallet configured
3. At least one Provider attached
4. At least one usable local Bundle or first-endpoint candidate exists
5. First local Endpoint published
6. Onboarding completed

The operator should never be trapped in a hard wizard.

The user can still navigate normally, but the product should consistently surface:
- current step;
- next action;
- why the action matters;
- what comes next.

## Completion Rule

Onboarding completes when:
- the operator has published at least one local Endpoint.

Onboarding does not require:
- validation requested;
- validation completed;
- remote endpoint attachment;
- proxy configuration;
- paid Session setup.

This is critical because `UX-0001` treats validation and publication as separate actions.

## Persisted State Model

Add a persisted onboarding object to Hypervisor state:

```yaml
onboarding:
  version: 1
  mode: guided_dashboard
  status: active | completed
  current_step: wallet_ready | provider_ready | bundle_ready | endpoint_published
  completed_steps:
    - wallet_ready
    - provider_ready
  completed_at:
  last_transition_at:
  first_published_endpoint_id:
```

Rules:
- `current_step` should not be mutated manually by the UI;
- the backend derives the current step from factual state;
- the derived result updates the persisted onboarding snapshot;
- `completed` is sticky and does not roll back automatically if the operator later deletes or changes the first Endpoint.

This allows:
- reliable reload behavior;
- deterministic post-onboarding `Home` rendering;
- historical insight into progress transitions;
- simpler testing and product logic.

## Derived Transition Rules

The backend should derive onboarding progress from real state:

### `wallet_ready`

Becomes complete when:
- owner wallet is configured.

### `provider_ready`

Becomes complete when:
- at least one Provider is attached and available.

### `bundle_ready`

Becomes complete when:
- at least one usable local Bundle or first-endpoint candidate exists.

### `endpoint_published`

Becomes complete when:
- at least one local Endpoint exists in published state.

### `completed`

Becomes complete immediately after `endpoint_published`.

## Screen Behavior

### Home

`Home` becomes the first-run agenda and post-onboarding landing surface.

While onboarding is active, `Home` must show:
- progress indicator;
- current step card;
- primary CTA;
- why this step matters;
- what happens next.

Primary CTA examples:
- `Create Wallet`
- `Import Wallet`
- `Open Providers`
- `Open Bundles`
- `Open Endpoints`

After onboarding completion, `Home` becomes a normal operator landing screen and should shift to CTA such as:
- `Open Endpoints`
- `Open Remote Endpoints`
- `Open Marketplace`
- `Open Sessions`

### Providers

When onboarding step is `provider_ready`, the `Providers` workspace enters guided mode.

It should:
- show a compact onboarding banner;
- prioritize attach/import actions;
- reduce visual emphasis on secondary controls;
- provide a success handoff when a Provider appears.

Expected handoff copy:
- `Provider attached. Continue to Bundles.`

### Bundles

When onboarding step is `bundle_ready`, the `Bundles` workspace enters guided mode.

It should:
- highlight the first usable local Bundle or endpoint candidate;
- prioritize bundle registration or attach steps;
- clearly point to the next CTA toward `Endpoints`.

Expected handoff copy:
- `Bundle ready. Continue to Endpoints.`

### Endpoints

When onboarding step is `endpoint_published`, the `Endpoints` workspace enters guided mode.

It should:
- focus on the first draft or publishable Endpoint;
- emphasize create, visibility, and publish actions;
- demote advanced controls like validation, proxy, or remote trust to secondary priority.

Expected completion handoff:
- onboarding marked `completed`;
- success state shown;
- CTA `Return Home`.

## Guided Mode Behavior

Guided mode should not hide the underlying dashboard architecture completely.

Instead, it changes:
- visual priority;
- CTA placement;
- copy emphasis;
- recommendation banners;
- success handoff messaging.

The operator should always feel that:
- the product is helping with the next action;
- the operator still owns the node;
- deeper controls are available when needed.

## Backend Architecture

Add service-level onboarding projection and persistence support.

Suggested responsibilities:
- `get_onboarding_state()`
- `refresh_onboarding_state()`
- transition updates triggered by real domain events

Transition sources:
- wallet create/import;
- provider attach;
- bundle registration or bundle attach;
- endpoint publish.

The backend should remain the source of truth for onboarding transitions.

## API Contract

Dashboard payloads should expose onboarding data consistently.

Suggested fields:
- `onboarding.status`
- `onboarding.current_step`
- `onboarding.completed_steps`
- `onboarding.completed_at`
- `onboarding.first_published_endpoint_id`
- `onboarding.next_action`
- `onboarding.guided_screen`

This projection should be available wherever the UI needs first-run guidance, especially:
- `Home`
- `Providers`
- `Bundles`
- `Endpoints`

## Migration Strategy

The onboarding layer should sit on top of the current dashboard implementation first.

Migration phases:

### Phase 1

Introduce persisted onboarding state and a canonical onboarding projection.

### Phase 2

Render onboarding state in `Home`.

### Phase 3

Add guided-mode banners and focused CTA behavior to `Providers`, `Bundles`, and `Endpoints`.

### Phase 4

Reduce older bootstrap-specific compatibility paths once the guided layer covers the same operator path cleanly.

## Error Handling

Rules:
- failed actions do not advance onboarding;
- if backend state has progressed further than the current UI view, the UI should jump to the correct step on refresh;
- if payloads are temporarily incomplete, `Home` should render a safe fallback like `Refreshing onboarding status...`;
- once `completed`, onboarding does not auto-reopen.

This avoids UI drift and prevents onboarding from becoming unstable under reloads or partial mutations.

## Testing Strategy

### 1. State Transition Tests

Add tests for:
- wallet transition;
- provider transition;
- bundle transition;
- endpoint publish transition;
- sticky completion behavior.

### 2. Operator View Tests

Add tests for:
- onboarding projection shape;
- `Home` current step rendering;
- `guided_screen` selection;
- post-completion summary behavior.

### 3. Dashboard Shell Tests

Add tests for:
- onboarding CTA copy on `Home`;
- guided banners on `Providers`, `Bundles`, and `Endpoints`;
- success completion state after first publish.

### 4. Browser Smoke

Verify:
- fresh state begins at Wallet step;
- progress moves after real actions;
- first local publish completes onboarding;
- `Home` returns as the post-onboarding landing screen.

## Why This Slice Now

This is the strongest next slice because it directly addresses the highest-priority roadmap gap:

- the operator bootstrap loop is still the main product-critical gap;
- the app already has enough underlying capability to make the flow coherent now;
- it prepares the shell for later validation, marketplace, and session workflows without making first-run more complicated;
- it keeps the Hypervisor aligned with `UX-0001` instead of drifting into a subsystem-first product.
