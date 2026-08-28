# Proxy Session Propagation Design

## Summary

This spec defines the next `M4` slice after the unified wallet ledger: proxy-aware paid session propagation.

The goal is to let a local published Endpoint run as a paid `proxy` Endpoint while preserving the existing operator and client contract:

- the client opens exactly one local Session;
- the local Hypervisor hides the upstream execution topology;
- the Hypervisor lazily opens and manages the upstream remote Session when proxy execution actually begins.

This keeps the product aligned with:

- [UX-0001 Hypervisor Operator Journey](../../product/UX-0001-hypervisor-operator-journey.md)
- [UX-0002 Endpoint Session and Payment Flow](../../product/UX-0002-endpoint-session-and-payment-flow.md)
- [ECO-0003 Validation Economics](../../product/ECO-0003-validation-economics.md)
- [ROADMAP.md](../../../ROADMAP.md)

## Problem

The current Session flow works for local paid Endpoints, and proxy execution already works for remote task dispatch.

However, these two capabilities are still separate:

- a local paid Session can reserve local execution;
- a proxy Endpoint can route requests to a remote Endpoint;
- there is no broker layer that opens, reuses, and closes an upstream paid Session for proxied paid execution.

Without that broker layer, proxy publication breaks the intended operator experience:

- the client would need to understand remote topology;
- the operator could not present one paid local Endpoint backed by a remote paid provider;
- paid remote execution would leak infrastructure detail into the client flow.

## Goals

- Preserve one local client-facing Session as the only public Session contract.
- Support paid `proxy` Endpoints that require an upstream remote Session.
- Open the upstream Session lazily on the first real proxy request.
- Reuse the same upstream Session for subsequent requests within the same local Session.
- Best-effort close the upstream Session when the local Session is closed.
- Expose operator-facing proxy session status in local API and dashboard payloads.
- Persist broker state through snapshot and restore.

## Non-Goals

- Revenue sharing across proxy hops.
- Cross-node disputes or coordinated dual-ledger settlement.
- Multi-hop proxy chains.
- A public client API for directly operating upstream Sessions.
- On-chain synchronization between local and remote deposits.

## Design Choice

Two approaches were considered:

### 1. Eager Broker

Open the upstream Session immediately when the local Session is created.

Pros:

- simpler request path later;
- remote reservation is already ready when the first task arrives.

Cons:

- creates unnecessary remote reservations for Sessions that never execute;
- locks remote deposits too early;
- increases idle exposure and operator cost.

### 2. Lazy Broker

Open the upstream Session only when the first proxy-bound request is actually dispatched.

Pros:

- avoids unnecessary remote reservations;
- matches the current Session philosophy more closely;
- reduces idle cost and queue pressure on remote nodes.

Cons:

- adds one more branch to the first request path.

### Decision

Use `Lazy Broker`.

The local Session remains the public contract. The upstream Session is an internal implementation detail opened only when proxy execution is required.

## User-Facing Behavior

### Client

- Opens one local Session on the local published Endpoint.
- Sends requests against that local Session as usual.
- Never sees or manages the upstream Session directly.

### Operator

- Can publish a local Endpoint as `proxy`.
- Can inspect whether a local Session has:
  - no upstream Session yet;
  - an active upstream binding;
  - a degraded upstream binding;
  - a pending upstream close or reconciliation state.

### Hypervisor

- Detects when a paid proxy Endpoint requires an upstream Session.
- Opens that upstream Session on demand.
- Reuses the upstream Session while the local Session remains active.
- Attempts to close the upstream Session when the local Session closes.

## Architecture

### Core Principle

Local Session ownership and client economics remain local.

The upstream Session is represented as a broker binding rather than as a second public Session visible to the client.

### New Runtime Object

Introduce `ProxySessionBinding`.

Suggested fields:

```yaml
local_session_id:
remote_endpoint_id:
remote_session_id:
remote_node_id:
source_base_url:
status:
opened_at:
last_error:
close_status:
```

Recommended status vocabulary:

- `pending_open`
- `active`
- `degraded`
- `close_pending`
- `closed`

Recommended `close_status` vocabulary:

- `not_requested`
- `closed`
- `pending_reconcile`

### Ownership Rules

- A local Session may have zero or one upstream `ProxySessionBinding`.
- The binding belongs to the local Session.
- The binding is private operator runtime state.
- The binding is not part of the client-facing endpoint contract.

## Request Flow

### Local Open

When a local Session is created on a paid proxy Endpoint:

- the local Session is created immediately;
- no upstream Session is created yet;
- no broker binding exists yet.

### First Proxy Request

When the first request is submitted through that Session:

1. validate the local Session as normal;
2. detect that the Endpoint execution strategy is `proxy`;
3. inspect whether a `ProxySessionBinding` already exists;
4. if no binding exists, open an upstream Session on the remote node;
5. persist the new binding;
6. dispatch the proxied request with the remote `session_id`;
7. return the proxy result as normal.

### Subsequent Proxy Requests

For additional requests in the same local Session:

- reuse the existing upstream binding;
- pass the bound `remote_session_id` to the remote node;
- continue until the local Session is closed or the upstream binding becomes invalid.

## Close Flow

When the local Session is closed:

1. complete the existing local settlement path;
2. if an upstream binding exists, attempt to close the remote Session;
3. if the remote close succeeds:
   - mark the binding closed;
   - store a remote settlement summary if available;
4. if the remote close fails:
   - still close the local Session;
   - mark the binding as `close_pending` or equivalent reconcile state.

The local operator contract must not remain blocked by remote close failure.

## Failure Handling

### Upstream Open Failure

If the upstream Session cannot be opened on the first proxy request:

- the local Session remains active;
- the request fails with a proxy-session-specific error;
- the binding is not promoted to active;
- the failure reason is recorded for operator inspection.

This avoids silently destroying valid local client state due to transient remote issues.

### Upstream Request Failure

If an upstream Session already exists but a proxied request fails:

- the local Session remains active;
- the binding is marked `degraded` or similar;
- the next request may attempt reuse or reopen depending on the remote error.

If the remote node explicitly indicates that the remote Session no longer exists, the Hypervisor may reopen upstream state on the next request attempt.

### Upstream Close Failure

If remote close fails:

- the local Session still closes;
- the local ledger and operator trace record the unresolved upstream close state;
- reconciliation can be added later without rewriting the local Session contract.

## API And UI Surfaces

### Public Client Contract

No new client-facing Session API is required for this slice.

The client still uses:

- local session open;
- local request execution;
- local session close.

### Operator-Facing Detail Payloads

Extend existing session/task detail payloads with an internal `proxy_session` block.

Suggested shape:

```yaml
proxy_session:
  local_session_id:
  remote_session_id:
  remote_endpoint_id:
  remote_node_id:
  source_base_url:
  status:
  close_status:
  opened_at:
  last_error:
```

This block should appear only when:

- the local Endpoint is a proxy Endpoint; and
- a binding exists or a proxy-session error has occurred.

### Dashboard Expectations

The operator dashboard should eventually display:

- whether the Session is local-only or proxy-backed;
- whether upstream binding is active;
- remote node and endpoint identity;
- last remote error;
- whether upstream close is still pending.

This spec does not require a full new dashboard workspace, only the payload support needed for one.

## Storage And Persistence

Persist `ProxySessionBinding` records through the same snapshot lifecycle used by Sessions and wallet events.

Requirements:

- survive app restart;
- survive state export and restore;
- retain enough information to continue close reconciliation later;
- avoid being recomputed from task history alone.

## Remote Endpoint Contract Assumptions

The first implementation may assume:

- the attached remote Endpoint is already known locally through the remote endpoint catalogue;
- the remote node exposes the existing Session API;
- the remote Endpoint policy is discoverable enough to know whether a paid Session is required.

If remote policy data is incomplete, the Hypervisor should fail explicitly rather than guessing.

## Implementation Slice

### Model Layer

Add a `ProxySessionBinding` model in the session domain or adjacent runtime state package.

### Store Layer

Extend `sessions/store.py` with:

- binding lookup by local session id;
- save/update binding;
- list bindings for snapshot export.

### Runtime Layer

Extend proxy execution in `service.py` so that:

- the proxy path lazily opens an upstream Session when needed;
- the binding is reused on subsequent requests;
- remote `session_id` is forwarded in the proxied task request;
- close triggers best-effort upstream close.

### API Layer

Extend operator-facing session/task payloads with `proxy_session`.

No client-facing protocol expansion is required beyond current local Session APIs.

## Test Plan

Required automated tests:

1. proxy execution opens upstream Session lazily on first request;
2. repeated requests within one local Session reuse the same upstream Session;
3. local close triggers upstream close;
4. upstream open failure does not destroy the local Session;
5. binding persists through snapshot and restore;
6. operator-facing payloads expose proxy session state.

## Risks

- Remote nodes may expose partial or inconsistent Session behavior.
- Local and remote settlement are still separate economic layers in this milestone.
- Remote close reconciliation may need a later background repair loop.

These risks are acceptable for the current `M4` slice because they do not change the local client contract and do not block the operator from understanding the failure mode.

## Success Criteria

This slice is complete when:

- a paid local proxy Endpoint can broker an upstream Session automatically;
- the client still interacts with only one local Session;
- the operator can inspect upstream proxy session state locally;
- broker state survives restore;
- remote close failure is visible but does not corrupt local settlement.
