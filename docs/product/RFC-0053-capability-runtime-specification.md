# RFC-0053 AiDN Capability Runtime Specification

Status: `Draft`

Version: `0.8`

Revision note: Runtime Usage Profile uses the normative RFC-0051 schema and a
cycle-free Profile Hash derivation committed by Runtime Configuration.

Supersedes:

- `RFC-0053 Version 0.7`

Depends on:

- `RFC-0039 Hypervisor Service Model`
- `RFC-0042 AiDN Hypervisor Network Protocol and Dispatcher Architecture`
- `RFC-0045 AiDN Capability Architecture`

Extended by:

- `RFC-0040 AiDN Service Verification Framework`
- `RFC-0044 AiDN Session Protocol`
- `RFC-0049 Distributed Marketplace and Endpoint Advertisement Registry`
- `RFC-0051 Usage Reporting and Verification Protocol`
- `RFC-0054 Capability Runtime Protocol`
- `RFC-0055 Provider Plugin System and Directory`
- `RFC-0056 Provider Plugin Runtime Interface`
- `RFC-0060 Session Failure, Recovery and Forced Settlement`
- `RFC-0063 Proxy Endpoint Protocol`
- `RFC-0066 Protocol Upgrade and Emergency Recovery`

## 1. Purpose

This document defines the AiDN Capability Runtime architecture: Runtime
identity, binding, instances, execution backends, Capability conformance,
lifecycle, readiness, resources, isolation, Usage Reporting, recovery,
verification, Endpoint integration and Dispatcher authorization.

Wire-level Runtime messages are defined by RFC-0054. Provider Plugin management
is defined by RFC-0055 and RFC-0056.

RFC-0053 SHALL NOT define an alternative Runtime wire envelope or generic
Plugin execution call. Runtime Binding approval precedes RFC-0054 handshake;
the handshake activates but does not create Runtime authority.

## 2. Core Boundary

A Capability Runtime is an AiDN execution boundary implementing one versioned
Capability contract.

```text
Session Request
  -> Hypervisor
  -> Network Dispatcher
  -> Capability Runtime
  -> Execution Backend
  -> Result and Usage
```

The complete plugin-managed path is:

```text
Provider Plugin
  -> manages Provider Instance
  -> discovers Model Deployment
  -> configures Runtime Adapter
  -> proposes Runtime Binding
  -> Hypervisor approves Runtime identity and route
  -> Endpoint sells access to the Runtime
```

Provider Plugin, Provider Instance, Model Deployment, Runtime Adapter,
Capability Runtime, Endpoint and Session are distinct entities.

## 3. Runtime Independence

A Runtime MAY be implemented as:

- `PLUGIN_MANAGED`;
- `NATIVE`;
- `EXTERNAL_DIRECT`;
- `PROXY`;
- `COMPOSITE`;
- `REMOTE_RUNTIME`.

A Plugin-managed Runtime references one Installed Plugin, Provider Instance,
Model Deployment and Adapter. A native Runtime implements RFC-0054 directly. A
Proxy Runtime also follows RFC-0063. A composite Runtime coordinates internal
components while exposing one primary Capability.

User workload execution SHALL use RFC-0054. RFC-0056 management RPC SHALL NOT
become a second execution protocol.

## 4. Runtime Identity

Every Runtime SHALL have a Hypervisor-approved stable Runtime ID.

```yaml
runtime_identity:
  runtime_id:
  runtime_owner:
  operator_hypervisor_id:
  implementation_class:
  runtime_generation:
  capability_id:
  capability_major_version:
  runtime_configuration_hash:
  identity_version:
```

Recommended derivation:

```text
RuntimeID = HASH(OperatorHypervisorID + RuntimeNonce)
```

Runtime ID SHALL NOT be derived only from a Provider address, port, model name
or Plugin ID. Provider Plugins may propose but SHALL NOT assign arbitrary
Runtime IDs.

## 5. Runtime Generation

`runtime_generation` identifies an execution lineage under one Runtime ID. It
SHALL increase after an incompatible recreation, including incompatible Adapter
replacement, model or Provider migration, state-format reset or loss of
recoverable Runtime state.

`runtime_generation` and Dispatcher `route_generation` are independent:

- Runtime Generation identifies the executor lineage.
- Route Generation identifies the currently authorized delivery route.

A reconnect may change Route Generation without changing Runtime Generation. A
Runtime replacement commonly changes both.

## 6. Runtime Binding

A Runtime Binding is the immutable configuration that connects an execution
backend to one Runtime identity and one primary Capability.

```yaml
runtime_binding:
  runtime_binding_id:
  runtime_id:
  runtime_generation:
  implementation_class:
  installed_plugin_id:
  plugin_id:
  plugin_version:
  provider_instance_id:
  model_deployment_id:
  adapter_id:
  adapter_version:
  capability_id:
  capability_version:
  capability_definition_hash:
  supported_features:
  supported_modalities:
  supported_accounting_modes:
  usage_reporting_profile_hash:
  resource_profile_hash:
  security_profile_hash:
  recovery_profile_hash:
  dispatcher_route_scope:
  runtime_configuration_hash:
  operational_state:
```

Fields not applicable to an implementation class SHALL be omitted. A
Plugin-managed Runtime SHALL include the Installed Plugin, Provider Instance,
Model Deployment and Adapter identity.

`route_generation` SHALL NOT be part of Runtime Binding or
`RuntimeConfigurationHash`; it is mutable Dispatcher state. An active Runtime
route separately binds Runtime ID, Runtime Generation, Runtime Binding Hash and
Route Generation.

## 7. Runtime Configuration Hash

```text
RuntimeConfigurationHash = HASH(CanonicalRuntimeConfiguration)
```

The canonical configuration includes Capability binding, execution backend,
Adapter, Provider and model references, execution parameters, supported
features, Usage profile, resource policy, state model, cancellation, recovery,
security and side-effect policy.

It excludes lifecycle state, Runtime Instance ID, current Route Generation,
Health samples and plaintext secrets. Material behavior changes require a new
hash and a higher Runtime Generation. Process restart, equivalent hardware
replacement, logging changes and non-semantic patches MAY preserve the hash.

## 8. Runtime Instance

A Runtime Instance is one active process, container, VM or remote execution
unit realizing a Runtime Binding.

```yaml
runtime_instance:
  runtime_id:
  runtime_generation:
  instance_id:
  runtime_binding_hash:
  execution_host_id:
  process_reference:
  started_at:
  operational_state:
  health_reference:
```

A restart MAY change Instance ID without changing Runtime ID, Runtime
Generation or Runtime Configuration Hash.

## 9. Capability Binding

Every Runtime SHALL implement one primary Capability ID and one Major Version.
It MAY support a compatible Minor Version range. Every accepted Request SHALL
bind to an exact Capability Definition Hash.

A Runtime SHALL reject unknown Definition Hashes, unsupported modalities and
required features in state `UNSUPPORTED`, `TEMPORARILY_UNAVAILABLE` or
`DEGRADED` when the Request cannot tolerate the limitation.

Hidden payload flags SHALL NOT switch one Runtime identity among unrelated
primary Capabilities.

## 10. Lifecycle

The normative lifecycle is:

```text
DRAFT -> STAGING -> REGISTERING -> VERIFYING -> READY
```

Additional states are `STARTING`, `DEGRADED`, `OVERLOADED`, `DRAINING`,
`STOPPED`, `RECOVERING`, `FAILED`, `QUARANTINED`, `REVOKED`, `REMOVING` and
`REMOVED`.

- Draft and Staging Runtimes SHALL NOT receive ordinary public work.
- Ready requires all mandatory readiness dimensions.
- Overloaded is healthy but lacks current capacity.
- Draining accepts completion, cancellation, recovery and close traffic only.
- Revoked routes SHALL NOT reactivate after process restart.

## 11. Registration and Dispatcher Scope

Registration occurs through RFC-0054 and, for Plugin-managed Runtimes, Adapter
approval through RFC-0056. The Hypervisor verifies Runtime ID, Runtime
Generation, Configuration Hash, Capability Definition, Adapter ownership,
Provider/model ownership and requested Dispatcher scope.

Every active route SHALL bind:

```yaml
runtime_route_binding:
  runtime_id:
  runtime_generation:
  runtime_binding_hash:
  route_generation:
  route_state:
  allowed_message_types:
```

The route permits only assigned Requests, authorized Session events, Runtime
Health, Usage Reports, cancellation, recovery, artifact events and Runtime
control. A stale Runtime Instance SHALL not regain traffic by reconnecting with
only the same Runtime ID.

## 12. Readiness and Health

Readiness is multidimensional:

```yaml
runtime_readiness:
  process_ready:
  adapter_ready:
  provider_ready:
  model_ready:
  capability_ready:
  usage_reporting_ready:
  dispatcher_route_ready:
  recovery_ready:
```

Health SHALL separately describe Runtime process, Adapter, Provider, model,
Capability, resources, Usage Reporting, recovery and route. Expired Health is
`UNKNOWN`, not Healthy. Provider process Health alone does not prove Runtime
readiness.

## 13. Capacity and Admission

A Runtime SHALL expose bounded capacity for requests, sessions, queue depth,
input, output and artifacts. Runtime capacity is current execution ability;
Endpoint Advertisement limits are contractual maxima.

Admission evaluates Health, Runtime and Route Generation, capacity, Session
authorization, feature and modality requirements, deadline, resources,
side-effect policy and Request limits. Results are `ACCEPTED`, `REJECTED`,
`QUEUED`, `BACKPRESSURED`, `TEMPORARILY_UNAVAILABLE` or `REQUIRES_RECOVERY`.

Queue ownership SHALL be disclosed and every queue SHALL be bounded by count,
bytes, exposure, wait time and subject quota. Queue time SHALL not be counted
twice across Dispatcher, Runtime Manager, Runtime and Provider queues.

## 14. Endpoint Binding

An Endpoint Configuration references one or more authorized Runtime Bindings:

```yaml
endpoint_runtime_binding:
  endpoint_id:
  endpoint_configuration_hash:
  runtime_binding_hash:
  routing_policy:
  failover_policy:
  binding_hash:
```

Several Endpoints MAY share one compatible Runtime while retaining independent
prices, access policies, Session limits, Advertisements and Certification.
One Endpoint MAY use several compatible Runtimes for capacity, redundancy,
regions or rollout.

Stateful Sessions SHOULD be pinned to one compatible Runtime lineage. Failover
and migration SHALL be explicit and SHALL NOT silently substitute an
incompatible model, Provider, Data Handling behavior or accounting contract.

## 15. Request Identity and Idempotency

Every Runtime Request preserves Session ID, Request ID, Endpoint ID, accepted
Endpoint Configuration Hash, Runtime ID, Runtime Generation, Capability
Definition Hash, charge ceiling, deadline and idempotency information.

A duplicate Request ID returns existing state/result, resumes delivery or is
rejected if content conflicts. It SHALL NOT silently execute twice. Provider
Adapters maintain durable AiDN-to-provider Request mappings where cancellation,
Usage, recovery or side-effect attribution requires them.

## 16. Streaming and Cancellation

Streams preserve Stream ID, Request ID, Runtime ID, modality, ordering and
result-root policy. Every stream terminates explicitly as completed, partial,
cancelled, failed or expired; transport close is not successful completion.

Cancellation support is `IMMEDIATE`, `CHECKPOINT_BOUNDED`, `BEST_EFFORT` or
`UNSUPPORTED`. A Runtime SHALL NOT claim confirmed cancellation while upstream
billable or side-effecting work continues. Provider uncertainty is reported and
handled by Session Failure and Accounting policy.

## 17. Retries and Side Effects

Internal retries obey Request idempotency, Capability side-effect model,
Failure Policy, deadline, charge ceiling, Pending Exposure and retry limit.
Retries and material Provider changes are visible in diagnostics and Usage.
Undeclared retries SHALL NOT create Consumer charges.

Side-effect classes include `NONE`, `READ_ONLY_EXTERNAL`, `REVERSIBLE_WRITE`,
`EXTERNAL_WRITE`, `IRREVERSIBLE`, `FINANCIAL` and `SECURITY_SENSITIVE`.
Approval binds Session, Request, action, scope, expiration and exposure. Plugins
and Adapters SHALL NOT fabricate Consumer approval.

## 18. State Models

A Runtime declares `STATELESS`, `SESSION_STATEFUL`, `EXTERNAL_STATEFUL` or
`WORKSPACE_STATEFUL`. Session state, Provider threads, workspaces, artifacts,
credentials and tool results SHALL be isolated.

State references include Runtime ID, Session ID, state model, state reference,
State Generation, recoverability and checkpoint. Reset or replacement increments
State Generation; stale Requests SHALL not attach to unrelated new state.

## 19. Artifacts

Runtime artifacts are content-addressed descriptors containing Request ID,
content hash, media type, size, storage reference, retention and access class.
Storage location does not change artifact identity. Consumers and Hypervisors
SHALL be able to verify artifact bytes against the content hash.

Retention follows Session, Data Handling, Validation evidence, Registry and
Endpoint obligations. The validated Hypervisor, not the Runtime process, owns
long-term Validation Report custody.

## 20. Usage Reporting

Every Runtime defines a dimension-specific Usage profile. Authority classes are:

- `AUTHORITATIVE_PROVIDER`;
- `DETERMINISTIC_LOCAL`;
- `OBSERVABLE_LOCAL`;
- `ESTIMATED`;
- `UNAVAILABLE`.

Each dimension declares unit, availability, authority, cumulative behavior,
scope, billing eligibility and limitations. Unknown values remain unknown and
SHALL NOT be replaced by zero. Estimates remain estimates unless the Accounting
Contract explicitly accepts a deterministic measurement method.

Usage chains remain ordered through recovery where possible. Retry work is
reported according to the Accounting Contract even when non-billable.

## 21. Resources and Security

Resource profiles describe CPU, memory, GPU, storage, network, allocation mode
and enforcement. Remote opaque resources use `EXTERNAL` or `UNOBSERVABLE`; the
Runtime SHALL NOT fabricate hardware claims.

Security profiles describe isolation, egress, filesystem scope, secret scope,
code execution, side effects and external Provider use. Runtime and Adapter
secrets are scoped to the Runtime, Provider Instance and permitted upstream
usage. Public Endpoint Data Handling SHALL NOT claim guarantees stronger than
the Runtime can enforce.

## 22. Recovery

Recovery classes are `FULLY_RECOVERABLE`, `CHECKPOINT_RECOVERABLE`,
`RECONSTRUCTIBLE`, `BEST_EFFORT` and `NON_RECOVERABLE`.

```yaml
runtime_recovery_state:
  runtime_id:
  runtime_generation:
  route_generation:
  active_requests:
  recoverable_requests:
  unrecoverable_requests:
  active_sessions:
  state_references:
  last_event_sequence:
  usage_chain_heads:
  artifact_references:
  state_hash:
```

After restart the Runtime reconciles provider-native operations, Requests,
Sessions, streams, Usage and artifacts. It SHALL NOT blindly restart work unless
prior execution state, idempotency, side effects, deadline and Session recovery
all permit it. Unrecoverable work enters RFC-0060 handling and SHALL NOT be
reported completed.

## 23. Update, Migration and Rollback

The preferred update sequence is:

```text
Prepare new Runtime
  -> Stage
  -> Conformance and readiness
  -> Authorize new Runtime and Route Generation
  -> Drain old Runtime
  -> Explicitly migrate compatible Sessions
  -> Activate
  -> Retain rollback
```

Model, Adapter, Provider, state, security or accounting changes are material
when Consumer-visible behavior changes. Stateful migration requires compatible
state format, checkpoint, Session pinning update and State Generation
continuity. Rollback SHALL NOT move active Sessions to an incompatible Runtime
Generation.

## 24. Verification and Certification

Runtime Verification asks whether the Runtime correctly implements the
Capability contract. It binds Runtime ID, Runtime Generation, Runtime
Configuration Hash, Capability Definition Hash, Adapter version and applicable
Provider/model references.

Endpoint Certification asks whether one Endpoint Configuration produced
meaningful behavior through its public Session path. Validation SHALL traverse
Hypervisor, Dispatcher, Session routing and accounting rather than call the
Provider directly.

Plugin conformance, Runtime Verification and Endpoint Certification are
independent evidence classes.

## 25. Public and Private State

Endpoints MAY commit publicly to a Runtime Binding Hash without revealing local
Provider addresses, credentials, model paths, resource topology or process IDs.
Registry Services MAY hold public Runtime commitments, verification records,
Adapter manifests and conformance evidence. Most Runtime lifecycle actions and
execution topology remain local.

## 26. Observability

The Hypervisor SHOULD expose Runtime state, Runtime and Route Generations,
Capability, Provider/model references, Health, capacity, queue depth, active
Requests and Sessions, resource use, Usage state, recovery and conformance.
Metrics SHOULD cover requests, latency, failures, queueing, streams,
cancellation, retries, Usage, recovery, Provider/model failures and generation
changes.

## 27. Required Errors

The MVP SHALL define stable errors for identity, generation, configuration,
Capability, route scope, admission, execution, streaming, cancellation, Usage,
artifacts, state, recovery, resources, Provider/model availability and security.
At minimum it includes:

```text
RUNTIME_NOT_FOUND
RUNTIME_GENERATION_MISMATCH
RUNTIME_CONFIGURATION_MISMATCH
RUNTIME_CAPABILITY_DEFINITION_MISMATCH
RUNTIME_NOT_READY
RUNTIME_OVERLOADED
RUNTIME_ROUTE_GENERATION_MISMATCH
RUNTIME_ROUTE_SCOPE_DENIED
RUNTIME_REQUEST_DUPLICATE
RUNTIME_REQUEST_CONFLICT
RUNTIME_QUEUE_FULL
RUNTIME_CANCELLATION_UNSUPPORTED
RUNTIME_USAGE_UNAVAILABLE
RUNTIME_STATE_GENERATION_MISMATCH
RUNTIME_RECOVERY_REQUIRED
RUNTIME_REQUEST_UNRECOVERABLE
RUNTIME_SIDE_EFFECT_NOT_AUTHORIZED
RUNTIME_SECURITY_POLICY_VIOLATION
```

Provider-native errors are sanitized and mapped to stable Runtime errors.

## 28. Conformance

Runtime conformance SHALL test identity, Runtime Generation, exact Capability
binding, Configuration Hash, Dispatcher authorization, schema validation,
features, replay, bounded queues, streaming, cancellation, Usage authority,
artifacts, side effects, state isolation, recovery, restart, Route Generation,
Provider/model failure, Plugin failure, update, migration and rollback.

The project SHOULD provide a Reference Runtime Harness with deterministic sample
execution and fault injection.

## 29. MVP Requirements

The MVP SHALL implement:

- Runtime ID, Runtime Generation, Runtime Binding and Runtime Instance;
- Plugin-managed and native implementation classes;
- one primary Capability and exact Definition Hash binding;
- deterministic Runtime Configuration Hash;
- lifecycle, readiness, multidimensional Health and capacity;
- bounded admission and queues;
- Endpoint-to-Runtime binding and Session pinning;
- Dispatcher Runtime and Route Generation checks;
- Request idempotency, streaming and honest cancellation;
- dimension-specific Usage authority;
- artifacts, state models and side-effect authorization;
- recovery, verification, update and rollback;
- stable errors and operational metrics.

Live stateful migration, cross-Hypervisor federation, distributed GPU
scheduling, automatic sharding, confidential execution and hardware-attested
model identity MAY be deferred.

## 30. Invariants

- Runtime ID, Runtime Binding ID and Runtime Instance ID are distinct.
- Runtime Generation and Route Generation are distinct.
- Every Runtime binds to one primary Capability and exact Definition Hash.
- Runtime Configuration is hash-bound and excludes mutable route state.
- Provider Plugins manage integration but do not own Runtime identity.
- Plugin Manager failure does not necessarily stop an independent Adapter.
- Runtime execution uses RFC-0054, not generic Plugin RPC.
- Draft and Staging Runtimes do not receive public work.
- Duplicate Requests do not create duplicate effects.
- Runtime Adapters do not change deadlines or charge ceilings.
- Session state, secrets and artifacts remain isolated.
- Unknown Usage remains unknown and estimates remain estimates.
- Internal retries do not create hidden charges.
- Active Sessions do not silently move across incompatible Runtime Generations.
- Endpoint Certification and Runtime Verification remain separate.
- Provider-specific implementation details do not enter Hypervisor core.

## RFC-0051 Runtime Usage Profile Binding

The Runtime Usage Profile schema and dimension semantics are normative in
RFC-0051. Runtime Configuration commits to `usage_profile_hash`. To avoid a
hash cycle, Usage Profile Hash excludes its `runtime_configuration_hash`
back-reference while the Profile object carries that field and registration
validates it against the active Runtime Binding. A material change to
Availability, Authority, billing eligibility, retry or Provider-attempt behavior
requires a new Profile Hash and Runtime Configuration Hash.
