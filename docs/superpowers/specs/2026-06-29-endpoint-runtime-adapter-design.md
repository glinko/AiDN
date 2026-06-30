# Endpoint Runtime Adapter Design

## Summary

This spec defines the next milestone after the completed `Endpoint + API`
transition slice.

The selected direction is:
- add a runtime adapter behind the endpoint model;
- add endpoint-native synchronous execution;
- keep queue, recovery, and auto-start behavior out of scope for this slice.

The primary public addition is:
- `POST /api/v1/endpoints/{endpoint_id}/invoke`

This route makes `endpoint_id` the first real execution-facing public handle,
while still delegating actual runtime and plugin work to the existing legacy
hypervisor substrate.

## Design Decision

### Selected Direction

Build an endpoint execution adapter over the current `HypervisorService`
runtime and plugin substrate.

That means:
- `EndpointService` remains the owner of endpoint manifests, lifecycle, and
  endpoint-facing rules;
- a new adapter layer resolves `endpoint_id` to the current execution target;
- the adapter validates readiness against the live legacy runtime state;
- synchronous invoke reuses the existing execution substrate instead of
  introducing a second scheduler or queue path.

### Why

This is the smallest useful milestone that turns endpoint into a real execution
entry point without forcing a full execution rewrite.

It preserves what already works:
- plugin invocation;
- runtime process management;
- bundle-backed execution behavior;
- legacy `/tasks` and bundle-centric routes.

It also creates the right architectural bridge for later work:
- endpoint advertisement can depend on real readiness rather than only stored
  lifecycle state;
- task routing by `endpoint_id` can later reuse the same endpoint-to-runtime
  mapping rules;
- dashboard migration can read endpoint-native execution status instead of
  inferring everything from bundles alone.

### Rejected Alternatives

#### 1. Thin Router Delegation Into `HypervisorService`

Rejected because it would make endpoint execution look like an API alias rather
than a true endpoint-owned surface.

That would postpone the architectural move from bundle-centric public contracts
to endpoint-centric public contracts.

#### 2. Separate `EndpointRuntimeService`

Rejected for this milestone because it adds a second service boundary before
the execution contract itself is proven.

That split may make sense later, but it would increase code volume and review
surface too early.

#### 3. Full Queue And Recovery Integration

Rejected because it mixes three problems:
- endpoint-native sync invoke;
- runtime lifecycle recovery;
- queued task routing by `endpoint_id`.

This milestone should solve only the first one.

## Product Goals

This slice must let the system:
- execute work through `endpoint_id` instead of only `bundle_id`;
- expose endpoint-native synchronous invocation through the versioned endpoint
  API;
- reuse all currently supported workload types through the existing runtime and
  plugin substrate;
- project real execution readiness from bundle and runtime state;
- return deterministic endpoint-native readiness failures when execution is not
  currently possible.

This slice must let the team:
- keep legacy `/tasks` behavior unchanged;
- add endpoint execution without rewriting schedulers, queues, or plugins;
- prepare the codebase for later queue routing and endpoint-centric operator
  views.

## Non-Goals

This slice does not:
- auto-start stopped runtimes during invoke;
- enqueue endpoint invoke requests for later execution;
- retry, recover, or restart runtimes implicitly;
- migrate the internal task queue model from `bundle_id` to `endpoint_id`;
- remove bundle-centric task submission paths;
- redesign wallet settlement behavior around endpoint invoke.

## Scope Boundary

The central rule for this milestone is:

`Endpoint becomes a synchronous execution handle before it becomes a queue and recovery orchestrator.`

Everything else follows from that rule.

## Architecture Overview

The milestone has five parts:

1. endpoint execution adapter
2. runtime readiness projection
3. endpoint-native invoke route
4. strict readiness failure contract
5. legacy coexistence

### 1. Endpoint Execution Adapter

The new logic sits behind `EndpointService` and maps:

`endpoint_id -> manifest -> bundle_id -> runtime -> plugin execution path`

The adapter does not replace `HypervisorService`.

It uses the current substrate for:
- runtime enumeration;
- bundle status and availability;
- plugin-backed synchronous execution.

### 2. Runtime Readiness Projection

Stored endpoint lifecycle state is not enough to decide whether invoke is
allowed.

The system needs a derived readiness projection that combines:
- endpoint lifecycle status;
- bundle enabled state;
- runtime existence;
- runtime health and status;
- bundle cooldown and drain state.

This readiness projection is runtime-derived view state, not new persisted
truth.

### 3. Endpoint-Native Invoke Route

The public route for this milestone is:

- `POST /api/v1/endpoints/{endpoint_id}/invoke`

This route is the first endpoint-native execution entry point.

It should:
- accept an invoke payload appropriate for the existing workload types;
- validate endpoint lifecycle and readiness;
- delegate sync execution through the adapter;
- return the result in the endpoint response envelope.

### 4. Strict Readiness Failure Contract

If invoke is impossible right now, the route must fail explicitly.

It must not:
- auto-start a runtime;
- degrade into the task queue;
- retry internally;
- silently reattach or heal runtime state.

### 5. Legacy Coexistence

Legacy paths remain valid:
- `/tasks`
- `/bundles`
- `/runtimes`
- existing operator routes

This milestone adds endpoint-native execution without removing or mutating the
legacy task submission model.

## Execution Flow

For `POST /api/v1/endpoints/{endpoint_id}/invoke`, the request flow is:

1. the endpoint API route receives the request;
2. `EndpointService` loads the endpoint manifest;
3. endpoint lifecycle is validated:
   - only `active` may invoke;
   - `created`, `stopped`, `suspended`, and `deleted` fail immediately;
4. the adapter resolves the execution target from the manifest:
   - current `bundle_id`;
   - current runtime;
   - current plugin-backed execution path;
5. readiness is evaluated from live runtime and bundle state;
6. if readiness passes, synchronous execution runs through the existing
   execution substrate;
7. the route returns the result in endpoint envelope form;
8. if readiness fails, the route returns a deterministic endpoint error without
   fallback behavior.

## Service Boundary

`EndpointService` owns:
- endpoint-facing lifecycle validation;
- readiness gating;
- endpoint execution orchestration;
- mapping endpoint-native errors to endpoint-native meanings.

The legacy hypervisor substrate continues to own:
- runtime process control internals;
- bundle/plugin execution internals;
- queueing and scheduler behavior;
- cooldown and drain mechanics;
- wallet, registry, and allocation logic.

The adapter is a bridge, not a second scheduler.

## API Contract

### New Route

The milestone adds:

- `POST /api/v1/endpoints/{endpoint_id}/invoke`

### Invoke Preconditions

Invoke is allowed only when all of these are true:
- endpoint status is `active`;
- the referenced bundle exists and is enabled;
- a runtime for that bundle exists;
- runtime state is healthy enough for direct synchronous execution;
- bundle state is not blocked by cooldown or drain conditions.

### Error Behavior

If preconditions fail, the API must return endpoint-native errors through the
existing endpoint envelope:

```json
{
  "data": null,
  "error": {
    "code": "endpoint_runtime_unavailable",
    "message": "Endpoint ep-123 has no ready runtime"
  },
  "correlation_id": "..."
}
```

Suggested error codes for this milestone:
- `endpoint_not_found`
- `endpoint_not_active`
- `endpoint_bundle_unavailable`
- `endpoint_runtime_unavailable`
- `endpoint_runtime_unhealthy`
- `endpoint_invoke_failed`
- `endpoint_validation_error`

### Success Behavior

Success responses continue to use:

```json
{
  "data": {},
  "error": null,
  "correlation_id": "..."
}
```

The exact `data` payload may mirror the current synchronous execution result
shape from the legacy substrate for the first milestone, as long as it is
wrapped in the endpoint envelope.

## Data Model And State

The persisted endpoint manifest remains the same execution anchor:
- `endpoint_id`
- `bundle_id`
- `status`
- current configuration fields

This milestone should not add a second persisted runtime truth source for the
endpoint.

Runtime readiness should be computed from live system state rather than written
back into endpoint persistence as durable state.

If an endpoint detail or readiness API projection is needed, it should be a
derived view.

## Code Organization

This milestone should stay incremental.

Likely touched areas:
- `src/aidn_hypervisor/endpoints/service.py`
- `src/aidn_hypervisor/endpoints/api.py`
- `src/aidn_hypervisor/main.py`
- a new adapter-oriented endpoint helper file if needed
- endpoint API and service tests
- legacy regression tests where coexistence must be proven

The implementation should avoid rewriting:
- `src/aidn_hypervisor/scheduler.py`
- `src/aidn_hypervisor/queue.py`
- `src/aidn_hypervisor/wallet*.py`
- registry internals

## Testing Strategy

The milestone needs four test layers.

### 1. Endpoint Service Tests

These should prove:
- only `active` endpoints may invoke;
- non-active lifecycle states fail deterministically;
- bundle and runtime resolution errors map to endpoint-native errors.

### 2. Adapter Tests

These should prove:
- ready runtime and enabled bundle allow invoke;
- missing runtime fails cleanly;
- disabled bundle fails cleanly;
- cooldown, drain, or unhealthy runtime states block invoke;
- no auto-start, queue fallback, or hidden retry occurs.

### 3. Endpoint API Tests

These should prove:
- `POST /api/v1/endpoints/{endpoint_id}/invoke` exists;
- success responses use endpoint envelope;
- validation, not-found, not-active, and readiness failures use endpoint error
  envelope consistently.

### 4. Legacy Coexistence Regression

These should prove:
- `/tasks` still works;
- `/bundles` and runtime inspection routes still work;
- shared persistence remains intact after invoke-related changes.

## Acceptance Criteria

This slice is complete when:
- `POST /api/v1/endpoints/{endpoint_id}/invoke` exists;
- invoke works only for `active` endpoints;
- synchronous execution is delegated through the existing runtime and plugin
  substrate;
- all currently supported workload types can pass through the endpoint bridge
  if the legacy substrate already supports them;
- readiness failures return endpoint-native deterministic errors;
- no auto-start, queue fallback, or implicit recovery behavior exists in the
  invoke path;
- legacy routes and persistence remain compatible.

## Next Milestones

After this runtime adapter slice, the recommended order remains:

1. endpoint advertisement generation from runtime-backed endpoint state
2. formal capability attachment and capability SDK work
3. queued task submission and routing by `endpoint_id`
4. dashboard migration from bundle-centric to endpoint-centric execution views

## Risks

### Risk 1: Hidden Legacy Coupling

If endpoint invoke reaches too far into `HypervisorService` internals, the
adapter may become a second copy of legacy execution logic.

Mitigation:
- keep the adapter narrow;
- reuse existing substrate interfaces rather than copying execution behavior.

### Risk 2: Readiness Semantics Drift

If endpoint readiness rules differ from real runtime behavior, clients will see
unpredictable invoke failures.

Mitigation:
- compute readiness directly from live runtime and bundle state;
- cover cooldown, drain, disabled bundle, and missing runtime cases in tests.

### Risk 3: Scope Drift Into Queueing

It will be tempting to add auto-start or queue fallback for convenience.

Mitigation:
- keep invoke synchronous and strict;
- defer fallback behaviors to the later `endpoint_id` routing milestone.

## Architectural Principle

The sequence for endpoint execution should be:

`public endpoint invoke -> runtime adapter -> queue/routing later`

That preserves the new endpoint-centric public contract while keeping the
existing hypervisor execution substrate as the implementation engine until a
later deeper migration.
