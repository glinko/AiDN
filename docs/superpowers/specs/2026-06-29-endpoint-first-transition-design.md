# Endpoint-First Transition Design

## Summary

This spec defines the first transition slice for moving active development from
the older bundle-centric hypervisor prototype toward the newer `AiDN/main`
architecture.

Authoritative operator journey reference:
- [UX-0001 Hypervisor Operator Journey](../../product/UX-0001-hypervisor-operator-journey.md)

The selected slice is:
- `Endpoint-first`;
- `Endpoint + API` for the first milestone;
- with a parallel-domain migration strategy rather than a hard rewrite.

The goal is to introduce `Endpoint` as the primary public object of the
hypervisor while preserving the current Python execution substrate as a working
implementation baseline.

This slice does not attempt to replace the existing scheduler, runtime, wallet,
or registry logic immediately. It creates the new architectural shell that
later execution, market, and dashboard work will target.

Within `UX-0001`, this slice sits after wallet ownership and provider/model setup.
Its job is to make `Endpoint` the primary operator-facing service object before deeper validation, marketplace, and proxy flows are added.

## Design Decision

### Selected Direction

Build a new `Endpoint` bounded context alongside the current bundle-centric
hypervisor services, then expose it through a versioned public API.

That means:
- the current `HypervisorService` remains the execution substrate for now;
- a new `EndpointService` owns endpoint lifecycle and configuration history;
- `/api/v1/endpoints` becomes the first explicitly versioned public API group;
- endpoint lifecycle is modeled independently before it is wired to real
  runtime execution.

### Why

This is the smallest safe slice that aligns current implementation work with
the new `AiDN/main` documents:
- `ARCHITECTURE.md` makes `Hypervisor` the product and `Endpoint` the public
  execution unit;
- `RFC-0024` defines `Endpoint Manifest` as the mutable service contract;
- `RFC-0025` defines advertisement as a projection of endpoint state;
- `IMP-0200` requires a dedicated `EndpointService` interface;
- `IMP-0700` requires a public API that is external-facing and versioned.

This direction also preserves the most useful parts of `AiDN_0.1`:
- queue and scheduler behavior;
- resource accounting;
- runtime control;
- wallet and settlement primitives;
- registry publication substrate.

### Rejected Alternatives

#### 1. Thin Facade Over Legacy Bundles

Rejected because it would expose a new API while still treating bundles as the
real public object internally.

That would delay the actual architectural transition and make later
advertisement, capability, and endpoint reputation work harder to untangle.

#### 2. Hard Rename Of The Existing Codebase

Rejected because it would combine terminology migration, API redesign, and
execution rewiring into one risky rewrite.

That is too disruptive while the Python prototype still provides working
runtime, wallet, and registry behavior worth preserving.

#### 3. Runtime-First Endpoint Wiring

Rejected for the first milestone because it would pull execution mechanics into
the design before the endpoint contract is stable.

The first step should establish the public model and lifecycle first, then bind
it to runtime later through adapters.

## Product Goals

This slice must let the system:
- define `Endpoint` as the primary external hypervisor object;
- model endpoint ownership through the wallet identity without conflating wallet and node identity;
- represent endpoint identity, configuration, publication, pricing, and
  lifecycle independently from runtime internals;
- keep publication and validation as distinct concepts from the beginning of the endpoint model;
- expose endpoint CRUD and lifecycle control through `/api/v1/endpoints`;
- preserve endpoint identity while configuration changes create new
  configuration snapshots;
- keep the current legacy execution APIs running during the transition.

This slice must let the team:
- continue developing in `AiDN/main`;
- use `AiDN_0.1` as an implementation donor rather than as the architecture
  source of truth;
- move toward endpoint-centric discovery, execution, and dashboard flows
  incrementally.

## Non-Goals

This slice does not:
- migrate task execution from `bundle_id` to `endpoint_id`;
- publish endpoint advertisements to the registry yet;
- introduce capability version objects beyond a minimal endpoint field;
- implement validator or attestation behavior;
- implement the full shared-wallet allowlist model for endpoint sharing yet;
- redesign wallet settlement flows;
- replace the existing operator dashboard;
- remove bundle-centric APIs or legacy state structures.

This slice intentionally stops before the next trust/publication layer, which
is now specified separately in
[Endpoint Configuration Publication Design](./2026-06-30-endpoint-configuration-publication-design.md):
- wallet-signed endpoint configuration publication;
- registry indexing of current published endpoint configuration;
- live proof comparison between served and published endpoint configuration.

## Scope Boundary

The central rule for this transition slice is:

`Endpoint becomes the public contract before it becomes the execution substrate.`

Everything else in the design follows from that rule.

## Architecture Overview

The slice has five parts:

1. endpoint manifest model
2. configuration snapshot model
3. endpoint lifecycle service
4. versioned endpoint API
5. parallel coexistence with the legacy hypervisor substrate

### 1. Endpoint Manifest Model

The system introduces a first-class `EndpointManifest` that represents the
mutable local service contract described in `RFC-0024`.

It includes at least:
- stable `endpoint_id`;
- `owner_wallet`;
- creation timestamp;
- `bundle_id`;
- `bundle_hash`;
- current `configuration_hash`;
- public identity and model declaration fields;
- runtime configuration;
- publication policy;
- pricing;
- validation metadata;
- lifecycle status.

`bundle_id` and `bundle_hash` remain in the model from day one so the new
endpoint layer can later attach to the existing bundle-backed execution system
without changing the external contract.

The endpoint model should also be able to grow toward the `UX-0001` privacy modes:
- private;
- shared with selected wallets;
- publicly accessible.

The first implementation slice may keep a narrower persistence shape, but the design language should not imply that validation and publication are the same decision.

### 2. Configuration Snapshot Model

The system introduces a separate immutable
`EndpointConfigurationSnapshot` record.

It captures the observable execution configuration for each endpoint version and
includes at least:
- `configuration_hash`;
- `endpoint_id`;
- `bundle_hash`;
- creation timestamp;
- runtime configuration;
- publication policy;
- provider-independent execution configuration.

Any change to runtime or publication behavior must create a new configuration
snapshot.

Validation attempts or reports do not automatically rotate endpoint publication state.

Endpoint identity remains stable.

Configuration history remains append-only.

### 3. Endpoint Lifecycle Service

A dedicated `EndpointService` owns endpoint lifecycle state and transition
rules.

For the first milestone it supports:
- create;
- update;
- get;
- list;
- start;
- stop;
- suspend;
- resume;
- delete.

This service does not own scheduling, wallet accounting, registry publication,
or provider execution.

Those remain separate concerns.

### 4. Versioned Endpoint API

The first versioned public API group is:
- `GET /api/v1/endpoints`
- `GET /api/v1/endpoints/{endpoint_id}`
- `POST /api/v1/endpoints`
- `PATCH /api/v1/endpoints/{endpoint_id}`
- `POST /api/v1/endpoints/{endpoint_id}/start`
- `POST /api/v1/endpoints/{endpoint_id}/stop`
- `POST /api/v1/endpoints/{endpoint_id}/suspend`
- `POST /api/v1/endpoints/{endpoint_id}/resume`
- `DELETE /api/v1/endpoints/{endpoint_id}`

This group is public-facing and should evolve independently from the existing
unversioned prototype routes.

### 5. Parallel Coexistence

The new endpoint context coexists with current legacy services.

That means:
- `HypervisorService` continues to own queue, runtime, allocation, wallet, and
  registry behavior;
- legacy `/tasks`, `/bundles`, `/allocations`, and related routes remain
  operational;
- the new endpoint layer is additive for the first milestone;
- real execution binding is deferred to a later adapter slice.

## Domain Model

### Endpoint Manifest

The first milestone endpoint manifest should contain:
- `endpoint_id`
- `owner_wallet`
- `created_at`
- `bundle_id`
- `bundle_hash`
- `configuration_hash`
- `display_name`
- `model_class`
- `capabilities: list[str]`
- `profile: dict`
- `runtime: dict`
- `publication: dict`
- `pricing: dict`
- `validation: dict`
- `status`

The first milestone keeps `capabilities` as a simple list because the
capability contract itself belongs to a later slice.

### Configuration Snapshot

The first milestone snapshot should contain:
- `configuration_hash`
- `endpoint_id`
- `bundle_hash`
- `created_at`
- `runtime`
- `publication`
- `execution_config`

`execution_config` is deliberately provider-independent and should stay small in
the first slice, for example:
- `accepts_external_requests`
- `streaming`
- `timeout`
- `max_concurrency`

The publication submodel should be understood as the home for future endpoint visibility semantics such as:
- `private`
- `shared`
- `public`

The validation submodel should remain separate so that:
- publication does not imply validation;
- validation remains operator-initiated;
- failed validation does not silently unpublish or republish the endpoint.

### Lifecycle States

The initial endpoint states are:
- `created`
- `stopped`
- `active`
- `suspended`
- `deleted`

Expected transitions:
- create -> `created`
- start -> `active`
- stop -> `stopped`
- suspend -> `suspended`
- resume -> `active`
- delete -> `deleted`

`deleted` should be a soft-delete state in the first milestone so configuration
history remains queryable.

## API Contract

### Update Rules

For the first milestone, endpoint update should allow:
- `display_name`
- `profile`
- `runtime`
- `publication`
- `pricing`
- `validation` only for explicit operator-controlled metadata that does not masquerade as an automatic validation workflow

It should not allow changing:
- `bundle_id`
- `bundle_hash`
- `endpoint_id`
- `owner_wallet`

Changing the underlying bundle artifact is a separate operation that should be
designed later rather than hidden inside a generic patch route.

### Configuration Hash Rule

If `runtime` or `publication` changes, the service must create a new
configuration snapshot and update `configuration_hash` on the endpoint
manifest.

If only non-execution metadata changes, the endpoint may be updated without a
new configuration snapshot.

Validation requests and reports should remain explicit operator actions layered on top of the endpoint rather than hidden side effects of publication updates.

### Response Shape

The versioned endpoint API should standardize responses as:

```json
{
  "data": {},
  "error": null,
  "correlation_id": "..."
}
```

Errors should use:

```json
{
  "data": null,
  "error": {
    "code": "endpoint_not_found",
    "message": "Unknown endpoint: ep-123"
  },
  "correlation_id": "..."
}
```

This starts moving the public API toward the deterministic contract expected by
`IMP-0700` without forcing the legacy prototype routes to change immediately.

## Code Organization

The endpoint transition should be implemented as a new parallel bounded
context.

New files:
- `src/aidn_hypervisor/endpoints/models.py`
- `src/aidn_hypervisor/endpoints/service.py`
- `src/aidn_hypervisor/endpoints/state.py`
- `src/aidn_hypervisor/endpoints/store.py`
- `src/aidn_hypervisor/endpoints/api.py`
- `tests/endpoints/test_models.py`
- `tests/endpoints/test_service.py`
- `tests/endpoints/test_api.py`

Minimal changes to existing files:
- `src/aidn_hypervisor/main.py`
- `src/aidn_hypervisor/state.py`
- possibly `src/aidn_hypervisor/api.py` only for composition glue

The transition should avoid large edits to:
- `src/aidn_hypervisor/service.py`
- `src/aidn_hypervisor/scheduler.py`
- `src/aidn_hypervisor/process_manager.py`
- `src/aidn_hypervisor/wallet.py`
- `src/aidn_hypervisor/registry_service.py`

## Persistence Strategy

The first milestone should extend the current snapshot-based persistence model
rather than replace it.

That means:
- add endpoint snapshot collections to the existing root state snapshot;
- persist endpoint manifests separately from immutable configuration snapshots;
- treat endpoint configuration history as append-only;
- keep the state format backward-compatible for existing legacy state fields.

The persistence layer should support:
- saving endpoint manifests;
- saving configuration snapshots;
- reading endpoint by id;
- listing all endpoints;
- listing configuration snapshots for one endpoint.

## Service Boundary

`EndpointService` owns:
- endpoint lifecycle rules;
- endpoint manifest validation;
- configuration snapshot creation;
- endpoint persistence orchestration.

`HypervisorService` continues to own:
- queue and scheduler behavior;
- runtime control;
- allocation flow;
- wallet and accounting;
- registry-oriented logic;
- operator request policy.

Future adapter layers may connect the two, but they remain separate in this
first slice.

## Next Milestones

After the first `Endpoint + API` slice, the recommended order is:

1. `Endpoint + runtime adapter`
2. endpoint publication and advertisement generation from manifest state
   The first publication slice is now defined in
   [Endpoint Configuration Publication Design](./2026-06-30-endpoint-configuration-publication-design.md).
3. explicit validation request/report workflow
4. capability attachment through a formal capability SDK layer
5. task submission and routing by `endpoint_id`
6. dashboard migration from bundle-centric views to endpoint-centric views
7. remote and proxy endpoint workflows

This preserves a stable outward contract while internal execution behavior is
migrated progressively.

## Risks

### Risk 1: Dual Domain Models Increase Complexity

Running legacy bundle-centric logic alongside a new endpoint context introduces
temporary duplication.

Mitigation:
- keep responsibilities explicit;
- treat legacy code as execution substrate only;
- keep new public contracts inside the endpoint context only.

### Risk 2: Premature Runtime Coupling

If start and stop lifecycle operations try to control real runtimes in the
first milestone, the migration surface becomes too large.

Mitigation:
- keep the first milestone focused on endpoint state and API;
- defer runtime binding to a dedicated adapter milestone.

### Risk 3: Snapshot Drift

If endpoint updates and configuration snapshots are not generated consistently,
the public contract becomes ambiguous.

Mitigation:
- make snapshot creation a service-owned rule;
- test hash changes and history persistence explicitly.

### Risk 4: Legacy API Pressure

It will be tempting to retrofit new endpoint semantics into the old routes too
early.

Mitigation:
- keep versioned endpoint APIs additive;
- migrate consumers one surface at a time.

## Acceptance Criteria

This slice is complete when:
- `AiDN/main` contains a dedicated `EndpointService`;
- endpoint manifest and configuration snapshot models exist;
- `/api/v1/endpoints` CRUD and lifecycle routes exist;
- lifecycle state transitions are validated in tests;
- runtime or publication updates create a new `configuration_hash`;
- endpoint identity remains stable across configuration changes;
- publication and validation remain distinct concepts in the endpoint contract;
- configuration snapshot history is persisted;
- legacy APIs and tests continue to run without regression.

## Architectural Principle

The endpoint transition should establish the new public truth of the hypervisor
without forcing a full rewrite of the current working prototype.

The sequence is:

`public contract first -> execution binding second -> network projection third`

That keeps `AiDN/main` aligned with its architecture documents while preserving
the delivery value of the existing Python system.
