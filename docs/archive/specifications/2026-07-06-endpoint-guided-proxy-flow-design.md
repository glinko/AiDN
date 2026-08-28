# Endpoint Guided Proxy Flow Design

Date: 2026-07-06
Status: Approved for planning

## Purpose

This slice upgrades the existing endpoint-first proxy handoff into a guided operator flow inside the `Endpoints` workspace.

The goal is not to add a new screen. The goal is to make the existing endpoint control plane feel linear and obvious when an operator is staging a remote route, publishing the updated configuration, and optionally requesting validation.

This design follows `UX-0001 Hypervisor Operator Journey`:

- `Endpoints` remains the canonical control plane.
- publishing and validation remain independent;
- validation remains optional;
- proxy execution remains a first-class strategy;
- the operator should always understand the next required action without needing to understand internal architecture.

## Chosen Approach

We will implement a hybrid guided flow.

- The existing `Endpoints` workspace remains visible and functional.
- When a proxy-guided flow is active, the right-hand operator column gains a prominent `Guided Route Flow` block.
- The guided block temporarily takes visual priority, but it does not hide the normal endpoint policy, publication, or proxy controls.
- Guided state remains client-managed in this slice, using an explicit state machine instead of scattered conditional hints.

This is intentionally incremental.

- It delivers a large UI/UX improvement immediately.
- It does not require a new wizard API.
- It preserves working proxy attach and publish behavior.
- It keeps the codebase ready for a future payload-driven contract if we later want tighter MCP/API synchronization.

## Guided Flow States

The guided flow uses the following states:

### `bootstrap`

Meaning:
- a remote route has been staged;
- no local endpoint is currently available for proxy binding.

Primary CTA:
- `Create Endpoint`

Expected transition:
- `bootstrap -> attach`

### `attach`

Meaning:
- a local endpoint exists;
- an attached remote route is staged;
- the endpoint has not yet bound that route as its proxy target.

Primary CTA:
- `Attach Proxy Route`

Expected transition:
- `attach -> publish`

### `publish`

Meaning:
- the proxy target is already attached;
- the updated endpoint configuration has not yet been published as the new signed snapshot.

Primary CTA:
- `Publish Configuration`

Expected transition:
- `publish -> validate_optional`

### `validate_optional`

Meaning:
- the updated proxy-backed endpoint configuration is already published;
- the operator may optionally request validation.

Primary CTA:
- `Request Validation`

Secondary CTA:
- `Finish`

Expected transitions:
- `validate_optional -> done` after explicit validation request;
- `validate_optional -> done` after explicit finish without validation.

### `done`

Meaning:
- the guided flow is complete;
- the screen returns to ordinary endpoint operations.

## UI Structure

When no guided flow is active:
- `Endpoints` behaves as it does today.

When guided flow is active:

1. A `Guided Route Flow` panel appears in the endpoint action column.
2. The panel shows a three-step rail:
   - `Attach Proxy Route`
   - `Publish Configuration`
   - `Request Validation (Optional)`
3. Each step renders:
   - a status chip;
   - a one-line explanation;
   - a current-step CTA when applicable.
4. The existing editors and trust panels remain below the guided flow.
5. The existing primary actions become synchronized with the guided state so the recommended control is visually dominant.

When the flow is in `bootstrap`:
- the rail still appears;
- the first step explains that a local endpoint must exist before route binding;
- the primary CTA becomes `Create Endpoint`.

## Operator Experience

The operator experience should feel like this:

1. Stage or discover a remote route from `Market` or `Remote Endpoints`.
2. Land in `Endpoints` with the guided flow already active.
3. See exactly one current next step.
4. Complete the next action without scanning the entire page.
5. Continue through publish and optional validation without losing the context of the endpoint editor.

The flow must preserve operator control:

- validation is never automatic;
- hidden auto-transitions are avoided;
- finishing without validation is always allowed;
- the operator may still inspect or edit endpoint policy during the flow.

## State Persistence Rules

This slice must preserve staged proxy intent across endpoint creation.

If a remote route is staged before any endpoint exists:

- the selected remote route is retained in draft state;
- creating the first endpoint automatically rebinds the guided flow to that endpoint;
- the flow resumes at `attach`.

If the operator leaves and returns to `Endpoints` during the same shell session:

- the active guided state remains visible until completed or explicitly dismissed.

## Rendering Rules

The guided panel should determine:

- current step label;
- current CTA;
- secondary CTA visibility;
- status chips for all steps.

Suggested status vocabulary:

- `Current`
- `Done`
- `Waiting`
- `Optional`

The UI should avoid introducing new business semantics beyond those already present in endpoint, publication, and validation actions.

## Implementation Scope

This slice includes:

- a dedicated guided flow panel in `Endpoints`;
- a visible step rail for proxy attach, publication, and optional validation;
- explicit CTA mapping for `bootstrap`, `attach`, `publish`, `validate_optional`, and `done`;
- preservation of staged remote route state through endpoint creation;
- a `Finish` action that clears guided state cleanly.

This slice does not include:

- a new full-screen wizard;
- a server-side wizard payload contract;
- automatic validation requests;
- any ledger, settlement, or validation economics changes.

## Testing Strategy

Tests should confirm:

- the guided panel appears only when flow is active;
- the correct CTA is shown for each guided phase;
- `bootstrap` survives endpoint creation and resumes at `attach`;
- `attach` advances to `publish` after proxy route binding;
- `publish` advances to `validate_optional` after publication;
- `Finish` clears the guided state;
- validation remains optional and explicitly user-triggered.

Shell tests are the minimum requirement for this slice because the behavior is mostly operator-facing orchestration logic in the dashboard.

## Follow-Up

If this UI layer works well, the next deeper slice can promote guided state into a payload-driven contract so operator shell, MCP operators, and future remote clients share the same explicit wizard state.
