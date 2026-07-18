# RFC-0054 AiDN Capability Runtime Protocol

Status: `Draft`

Version: `0.7`

Revision note: RUNTIME_USAGE_REPORT transports the normative RFC-0051 evidence
object; terminal Result admission requires an accepted matching Final Report.

Supersedes:

- `RFC-0054 Version 0.6`

Depends on:

- `RFC-0039 Hypervisor Service Model`
- `RFC-0042 AiDN Hypervisor Network Protocol and Dispatcher Architecture`
- `RFC-0045 AiDN Capability Architecture`
- `RFC-0051 Usage Reporting and Verification Protocol`
- `RFC-0053 AiDN Capability Runtime Specification`

Extended by:

- `RFC-0040 AiDN Service Verification Framework`
- `RFC-0044 AiDN Session Protocol`
- `RFC-0049 Distributed Marketplace and Endpoint Advertisement Registry`
- `RFC-0055 Provider Plugin System and Directory`
- `RFC-0056 Provider Plugin Runtime Interface`
- `RFC-0060 Session Failure, Recovery and Forced Settlement`
- `RFC-0063 Proxy Endpoint Protocol`
- `RFC-0064 Validation Assignment, Concealed Session and Escrow Protocol`
- `RFC-0066 Protocol Upgrade and Emergency Recovery`

## 1. Purpose

This document defines wire-level communication between an AiDN Hypervisor and a
Capability Runtime. It covers authentication, version negotiation, Runtime and
Route Generations, readiness, Health, capacity, execution admission, streaming,
artifacts, Usage, cancellation, state, draining, reconnect, recovery, replay
protection and stable errors.

Runtime architecture is defined by RFC-0053. Provider Plugin management is
defined by RFC-0055 and RFC-0056.

## 2. Protocol Boundary

```text
Hypervisor
  -> RFC-0054
Capability Runtime
  -> implementation-specific
Provider, Native Engine or Composite Backend
```

RFC-0054 defines execution. It does not define Plugin installation, Provider or
model management, Plugin permissions, Marketplace pricing, Endpoint
publication or final Settlement.

A Runtime SHALL NOT require management-plane access to process an ordinary
Request. A Plugin-managed Adapter must already have an approved RFC-0053 Runtime
Binding before RFC-0054 handshake begins. The handshake SHALL NOT create
Plugin permissions, Provider ownership, Runtime identity or Dispatcher routes.

## 3. Transport and Envelope

RFC-0054 payloads travel through the RFC-0042 `RUNTIME` channel. Local Runtime
transport SHOULD use authenticated `LOCAL_IPC`; remote Runtimes MAY use
`QUIC_TLS`, `TCP_TLS` or `RELAY_TUNNEL`.

Every payload is contained in an RFC-0042 `network_message`. The outer envelope
provides Network ID, Chain ID, Network Revision, transport Message ID,
destination route, expiration, priority, payload integrity and transport
authentication.

RFC-0054 provides a separate semantic Runtime Message ID. Network Message ID
and Runtime Message ID SHALL both be replay-protected and SHALL NOT be treated
as the same identity.

## 4. Version Negotiation

Runtime Protocol versions use `MAJOR.MINOR`. A Runtime advertises minimum,
maximum and preferred versions or an equivalent supported set, plus required
and optional features. Peers select the highest mutually active version.

A downgrade SHALL be rejected when it removes required security, Runtime or
Route Generation checks, persistent Request idempotency, dimension-specific
Usage authority or required recovery behavior.

## 5. Runtime Protocol Identity

Every Runtime connection binds:

```yaml
runtime_protocol_identity:
  runtime_id:
  runtime_generation:
  runtime_configuration_hash:
  runtime_binding_hash:
  capability_id:
  capability_version:
  capability_definition_hash:
  operator_hypervisor_id:
```

Runtime Generation identifies execution lineage. Runtime Configuration Hash
identifies material behavior. Runtime Binding Hash identifies the approved
binding. Route Generation identifies the active Dispatcher target. Instance ID
identifies one process start and MAY change without changing the other values.

## 6. Connection Lifecycle

```text
CONNECTING
  -> HELLO_EXCHANGING
  -> IDENTITY_VERIFYING
  -> VERSION_NEGOTIATING
  -> CONFIGURATION_VERIFYING
  -> STATE_RECONCILING
  -> READY
```

Alternative states are `REJECTED`, `RECOVERING`, `QUARANTINED`, `DRAINING` and
`CLOSED`.

## 7. Runtime Hello

The Runtime initiates:

```yaml
runtime_hello:
  runtime_id:
  runtime_generation:
  instance_id:
  runtime_configuration_hash:
  capability_id:
  supported_capability_versions:
  supported_definition_hashes:
  supported_runtime_protocol_versions:
  supported_runtime_features:
  adapter_id:
  adapter_version:
  last_runtime_event_sequence:
  last_hypervisor_command_sequence:
  recovery_state_available:
  runtime_nonce:
  runtime_challenge:
  runtime_signature:
```

The Hypervisor verifies Runtime identity against an existing Binding and active
route. A Plugin Session Identity does not authenticate Runtime execution.

## 8. Hypervisor Hello

```yaml
hypervisor_runtime_hello:
  handshake_id:
  runtime_id:
  accepted_runtime_generation:
  accepted_runtime_configuration_hash:
  runtime_binding_hash:
  selected_runtime_protocol_version:
  selected_capability_version:
  selected_capability_definition_hash:
  route_generation:
  granted_route_scope:
  network_revision:
  hypervisor_command_sequence:
  runtime_challenge_response:
  hypervisor_challenge:
  recovery_directive:
  hypervisor_signature:
```

The Dispatcher remains authoritative for Route Generation. The Runtime SHALL
NOT choose or increment it.

## 9. Handshake Completion

```yaml
runtime_hello_complete:
  handshake_id:
  runtime_id:
  runtime_generation:
  route_generation:
  hypervisor_challenge_response:
  current_operational_state:
  current_health_reference:
  current_capacity_reference:
  runtime_signature:
```

Authorization completes only when Runtime ID, Generation, Configuration and
Binding Hashes, Capability Definition, protocol version, Network Revision,
route scope and both challenge responses are valid. A missing approved Binding
or route is rejection, not implicit registration.

## 10. Runtime Connection Identity

```yaml
runtime_connection_identity:
  runtime_connection_id:
  runtime_id:
  runtime_generation:
  runtime_configuration_hash:
  runtime_binding_hash:
  instance_id:
  route_generation:
  selected_runtime_protocol_version:
  connection_state:
  established_at:
  expires_at:
```

Connection ID changes after reconnect. A new connection SHALL close, replace or
explicitly coexist with any previous active connection under deterministic
policy.

## 11. Common Runtime Message

```yaml
runtime_message:
  runtime_message_id:
  runtime_message_type:
  runtime_message_version:
  runtime_id:
  runtime_generation:
  runtime_configuration_hash:
  route_generation:
  runtime_connection_id:
  session_id:
  request_id:
  correlation_id:
  causation_id:
  runtime_sequence:
  created_at:
  expiration:
  payload_hash:
  payload:
  authentication:
```

Runtime Message ID remains stable across safe transport retransmission.
Runtime and Hypervisor command directions maintain independent monotonic
sequences. Duplicate identical semantic messages are idempotent; conflicting
content under one ID or sequence is rejected.

Usage Reports and final Results SHOULD carry persistent authentication that
survives one connection lifetime.

## 12. Initial Message Types

The initial protocol includes:

```text
RUNTIME_READY
RUNTIME_HEALTH
RUNTIME_CAPACITY
RUNTIME_EXECUTE
RUNTIME_REQUEST_ACCEPT
RUNTIME_REQUEST_REJECT
RUNTIME_REQUEST_PROGRESS
RUNTIME_STREAM_OPEN
RUNTIME_STREAM_CHUNK
RUNTIME_STREAM_CLOSE
RUNTIME_ARTIFACT_DECLARE
RUNTIME_RESULT
RUNTIME_USAGE_REPORT
RUNTIME_USAGE_ACK
RUNTIME_CANCEL
RUNTIME_CANCEL_RESULT
RUNTIME_STATE_CHECKPOINT
RUNTIME_STATE_RESET
RUNTIME_STATE_RESET_RESULT
RUNTIME_RECOVERY_STATE
RUNTIME_RECOVERY_PLAN
RUNTIME_RECOVERY_RESULT
RUNTIME_DRAIN
RUNTIME_DRAIN_STATUS
RUNTIME_DRAIN_COMPLETE
RUNTIME_SHUTDOWN
RUNTIME_ERROR
```

## 13. Readiness

After handshake and required reconciliation, the Runtime sends `RUNTIME_READY`
with Runtime ID, Generations, Configuration Hash, exact Capability Definition,
supported features, Usage Profile Hash, Health and capacity references.

Readiness dimensions are process, Adapter, Provider, model, Capability, Usage
Reporting, route and recovery. The Runtime SHALL NOT report Ready while a
mandatory dimension is false.

## 14. Health and Capacity

`RUNTIME_HEALTH` separately reports process, Adapter, Provider, model,
Capability, resources, Usage, recovery and route, with `observed_at` and
`valid_until`. Expired Health is `UNKNOWN`.

`RUNTIME_CAPACITY` reports maximum and active Requests/Sessions, queue limits,
input/output/artifact limits and temporary capacity factor. Capacity is advisory
for routing; the authoritative decision for one Request is its admission
response.

## 15. Execute Request

```yaml
runtime_execute_request:
  runtime_id:
  runtime_generation:
  runtime_configuration_hash:
  route_generation:
  endpoint_id:
  endpoint_configuration_hash:
  session_id:
  session_contract_hash:
  request_id:
  capability_id:
  capability_version:
  capability_definition_hash:
  required_features:
  optional_features:
  request_payload_hash:
  request_payload_encoding:
  request_payload:
  request_payload_reference:
  state_reference:
  input_limits:
  output_limits:
  artifact_limits:
  request_charge_ceiling:
  accounting_contract_hash:
  side_effect_authorizations:
  idempotency_key:
  request_deadline:
  trace_context:
```

Exactly one payload location is used. Large payloads SHOULD use bounded streams
or content-addressed references rather than one control frame.

The Runtime SHALL NOT increase charge ceiling, extend deadline, reinterpret the
Accounting Contract or widen side-effect approval.

## 16. Validation Before Admission

Before substantial execution, the Runtime validates identity, Runtime and Route
Generations, Configuration Hash, Endpoint and Session binding, Capability
Definition, features, payload integrity, limits, deadline, Request replay, State
Generation, side effects and Accounting Contract compatibility.

Minimal preprocessing needed for validation is permitted. Provider execution
before valid admission is prohibited.

## 17. Request Idempotency

Request ID identifies one semantic Request and SHALL be persistent or
recoverable when economic or side-effect consequences exist.

An identical duplicate returns current state, previous acceptance, resumed
output or existing final Result. Reuse of Request ID with different payload,
Session, Endpoint Configuration, charge ceiling, Capability Definition or side
effects is `RUNTIME_REQUEST_CONFLICT`.

Provider-native Request IDs remain internal mappings and do not replace AiDN
Request ID.

## 18. Admission

Admission states are `ACCEPTED`, `QUEUED`, `REJECTED`, `BACKPRESSURED`,
`TEMPORARILY_UNAVAILABLE` and `RECOVERY_REQUIRED`.

`RUNTIME_REQUEST_ACCEPT` confirms responsibility, accepted Capability
Definition/features and optional bounded queue information. It does not mean
execution completed, output exists, Usage is final or Settlement is owed.

Queue depth, bytes and wait are bounded. Progress authority is
`DETERMINISTIC`, `MEASURED`, `ESTIMATED` or `UNKNOWN`.

## 19. Request States

Execution states include `VALIDATING`, `ADMITTED`, `QUEUED`, `EXECUTING`,
`WAITING_UPSTREAM`, `WAITING_APPROVAL`, `FINALIZING`, `COMPLETED`, `PARTIAL`,
`CANCEL_REQUESTED`, `CANCELLED`, `FAILED`, `EXPIRED` and `RECOVERING`.

Progress MAY be reported but SHALL disclose authority. It is not a terminal
Result.

## 20. Streaming

Streaming uses explicit `RUNTIME_STREAM_OPEN`, `RUNTIME_STREAM_CHUNK` and
`RUNTIME_STREAM_CLOSE` messages. Stream identity binds Runtime, Request, Stream
ID, modality and Route Generation.

Ordering models are `STRICT_ORDERED`, `INDEPENDENT_SEGMENTS`,
`ARTIFACT_CHUNKS` and `EVENT_STREAM`. Chunks carry sequence, hash, length and
content/reference. Identical duplicates are idempotent; conflicting content
under one sequence is rejected.

Stream terminal states are `COMPLETED`, `PARTIAL`, `CANCELLED`, `FAILED` and
`EXPIRED`. Transport closure alone is not successful completion. Interrupted
streams remain `RECOVERING` until resume, redelivery, partial close or failure
is chosen.

## 21. Artifacts

`RUNTIME_ARTIFACT_DECLARE` binds artifact identity to Request ID, content hash,
media type, size, storage reference, access class and retention. Consumers and
Hypervisors SHALL be able to verify bytes against Content Hash.

Declaration does not prove continued availability. Retention follows Session,
Endpoint, Registry and Validation evidence policy.

## 22. Final Result

`RUNTIME_RESULT` binds Runtime and Route Generations, Configuration Hash,
Endpoint Configuration, Session and Request, terminal state, payload/result
hashes, stream roots, artifacts, state reference, final Usage Report and Runtime
signature.

Terminal states are `COMPLETED`, `PARTIAL`, `CANCELLED`, `FAILED`, `EXPIRED`
and `UNRECOVERABLE`. Once accepted, a conflicting final Result is prohibited.
Partial Results identify completed and missing output, billing boundary and
resume possibility.

## 23. Usage Report

```yaml
runtime_usage_report:
  usage_report_id:
  runtime_id:
  runtime_generation:
  runtime_configuration_hash:
  endpoint_id:
  endpoint_configuration_hash:
  session_id:
  request_id:
  accounting_contract_hash:
  report_type:
  usage_sequence:
  previous_usage_report_hash:
  dimensions:
  provider_attempts:
  provider_attempt_count:
  request_state:
  cumulative:
  terminal:
  observed_from:
  observed_to:
  limitations:
  created_at:
  report_hash:
  runtime_signature:
```

Each dimension declares unit, value, availability, authority, cumulative
behavior, billing eligibility, source and limitations. Authority is one of:

- `AUTHORITATIVE_PROVIDER`;
- `DETERMINISTIC_LOCAL`;
- `OBSERVABLE_LOCAL`;
- `ESTIMATED`.

Availability is `AVAILABLE`, `PARTIAL`, `UNAVAILABLE` or `NOT_APPLICABLE`.
Unavailable and not-applicable Usage have no Authority or numeric value and
SHALL NOT be encoded as zero.
Estimated values remain estimated. Deterministic token measurement requires an
explicit tokenizer and accepted construction rules.

## 24. Usage Chain and Acknowledgment

Multiple Usage Reports form an ordered hash chain. `RUNTIME_USAGE_ACK` returns
`ACCEPTED`, `DUPLICATE`, `REJECTED`, `CONFLICT`, `OUT_OF_SEQUENCE` or
`PENDING_REVIEW`, accepted sequence and Report Hash.

Conflicting reports remain auditable. Internal retry Usage is reported; billing
eligibility follows Accounting Contract, Failure Policy, retry disclosure and
charge ceiling. Non-billable work MAY remain diagnostic.

## 25. Validation Requests

Concealed Validation uses ordinary `RUNTIME_EXECUTE`. RFC-0054 SHALL NOT require
an `is_validation` field visible to the Runtime. Operational Usage may be
recorded, while Validation compensation is determined by RFC-0064.

## 26. Cancellation

`RUNTIME_CANCEL` binds cancellation identity, Runtime, Session, Request, reason,
requested terminal state, deadline and authorization. Support classes are
`IMMEDIATE`, `CHECKPOINT_BOUNDED`, `BEST_EFFORT`, `PROVIDER_DEPENDENT` and
`UNSUPPORTED`.

`RUNTIME_CANCEL_RESULT` separately reports output forwarding, Provider execution
state, confirmed stop, side-effect state and terminal Usage/Result references.
Output suppression is not confirmed Provider cancellation. Already incurred
Usage remains reportable.

## 27. State

State checkpoints bind Runtime, Session, State Generation, checkpoint sequence,
hash, recoverability and retention. State References are scoped to Runtime,
Session, Capability and permitted recovery path.

State reset uses expected State Generation and returns the new generation plus
retained and removed references. Cross-Session, cross-Runtime and stale State
References are rejected.

## 28. Recovery State

After reconnect neither side assumes its local state is complete. The Runtime
sends:

```yaml
runtime_recovery_state:
  runtime_id:
  runtime_generation:
  runtime_configuration_hash:
  route_generation:
  instance_id:
  active_requests:
  terminal_requests:
  recoverable_requests:
  unrecoverable_requests:
  active_streams:
  usage_chain_heads:
  state_references:
  artifact_references:
  last_runtime_event_sequence:
  last_hypervisor_command_sequence:
  recovery_state_hash:
```

## 29. Recovery Plan

The Hypervisor responds with a hash-bound `RUNTIME_RECOVERY_PLAN`. Request
directives are:

```text
CONTINUE_EXISTING_EXECUTION
RESUME_OUTPUT
REDELIVER_FINAL_RESULT
REDELIVER_USAGE
RESTART_IF_IDEMPOTENT
CANCEL
FAIL_UNRECOVERABLE
IGNORE_UNKNOWN_REQUEST
WAIT_FOR_PROVIDER
```

Unknown Runtime work is reported and not automatically adopted. Missing
Runtime work becomes unrecoverable unless reconstruction is proven. Restart
requires known prior state, idempotency, valid deadline, side-effect safety and
an explicit directive.

Result and Usage redelivery preserve original IDs and hashes and do not create
new execution.

## 30. Generation During Recovery

Recovery compares Runtime Generation, Runtime Configuration Hash, State
Generation and Route Generation independently. A Route Generation mismatch
requires explicit rebinding. A newer Runtime Generation SHALL NOT claim older
work without an authorized migration protocol.

## 31. Draining and Shutdown

`RUNTIME_DRAIN` stops new Requests/Sessions according to policy while preserving
cancellation, Usage acknowledgments, recovery, close control and diagnostics.
Drain status reports active, queued, recoverable and blocked work.

Shutdown modes are `GRACEFUL`, `IMMEDIATE`, `SECURITY` and
`RESOURCE_EMERGENCY`. Emergency actions may block routes, revoke credentials and
preserve recovery evidence, but SHALL NOT rewrite completed Results or Usage.

## 32. Errors

`RUNTIME_ERROR` contains stable error code/class, Runtime/Session/Request,
correlation, failure stage, retryability, Provider state, diagnostic reference
and sanitized message.

Required classes cover handshake, identity, version, configuration, route,
Capability, admission, Request, queue, execution, stream, cancellation, Usage,
artifact, state, recovery, resource, security, Provider, model and internal
failure.

Required codes include:

```text
RUNTIME_HANDSHAKE_INVALID
RUNTIME_IDENTITY_INVALID
RUNTIME_NOT_REGISTERED
RUNTIME_GENERATION_MISMATCH
RUNTIME_CONFIGURATION_MISMATCH
RUNTIME_CAPABILITY_DEFINITION_MISMATCH
RUNTIME_ROUTE_GENERATION_MISMATCH
RUNTIME_ROUTE_SCOPE_DENIED
RUNTIME_REQUEST_DUPLICATE
RUNTIME_REQUEST_CONFLICT
RUNTIME_REQUEST_EXPIRED
RUNTIME_SESSION_NOT_AUTHORIZED
RUNTIME_ENDPOINT_BINDING_MISMATCH
RUNTIME_REQUIRED_FEATURE_UNAVAILABLE
RUNTIME_ACCOUNTING_CONTRACT_MISMATCH
RUNTIME_SIDE_EFFECT_NOT_AUTHORIZED
RUNTIME_QUEUE_FULL
RUNTIME_EXECUTION_FAILED
RUNTIME_STREAM_SEQUENCE_CONFLICT
RUNTIME_USAGE_CHAIN_CONFLICT
RUNTIME_CANCELLATION_UNSUPPORTED
RUNTIME_RECOVERY_CONFLICT
RUNTIME_REQUEST_UNRECOVERABLE
RUNTIME_STATE_GENERATION_MISMATCH
```

Errors SHALL NOT expose credentials, private Provider addresses, model paths,
unrelated Session content or Hypervisor private topology.

## 33. Delivery and Retry

RFC-0054 does not claim physical exactly-once delivery. Safe effects use stable
Request ID, Runtime Generation, Configuration Hash, Route Generation,
idempotency, Usage chain and recovery.

Hypervisor retries preserve Request ID and require a valid deadline, route and
idempotent reconciliation. Route changes, stateful failover and Provider
substitution require explicit policy and side-effect safety.

The Runtime may retry Provider work only under Endpoint Failure Policy,
idempotency, side-effect, deadline, retry and charge limits. It SHALL NOT
silently change model, Provider, region, Data Handling class or accounting
source unless active Runtime and Endpoint Configuration permit it.

## 34. Security and Isolation

Runtime messages are authenticated and routes are scoped. Reusable Provider
credentials SHOULD NOT travel in ordinary RFC-0054 messages. Plugin-managed
Adapters receive scoped secret handles through RFC-0056.

Runtime isolates Request payloads, streams, state, artifacts, Provider threads,
tools and credentials between Sessions. An Adapter SHALL NOT process messages
for another Runtime ID. Payloads and artifacts are hash-verified; queues are
bounded; Provider errors are sanitized; old Network Revision effects are
rejected.

## 35. Observability

The Hypervisor SHOULD expose connection/protocol version, Runtime and Route
Generations, Configuration Hash, readiness, Health, capacity, Request and queue
state, streams, Usage chains, recovery and drain state.

Logs SHOULD cover handshake, admission, terminal states, stream failure, Usage
conflict, cancellation, recovery, Generation mismatch, route change and
security violation without raw private payloads.

## 36. Conformance

Protocol conformance tests handshake, version negotiation, identity and
Generation checks, Configuration Hash, admission, Request idempotency,
streaming, cancellation, Usage authority/chains, Result finalization, recovery,
drain and stable errors.

A Plugin-managed Adapter separately passes RFC-0056 interface conformance,
RFC-0054 execution conformance and RFC-0045 Capability conformance. Passing one
does not imply passing the others.

The project SHOULD provide a harness that changes Route Generation, replays
Requests, interrupts streams, drops acknowledgments, creates Usage conflicts,
restarts Runtime, applies Recovery Plans and tests drain/shutdown.

## 37. Upgrade

RFC-0066 upgrades define active RFC-0054 versions, compatibility windows,
required reconnect, durable Request migration and treatment of active Sessions.
Compatible active Sessions SHOULD continue on their accepted protocol version.
Required migration defines state, Request, Usage, stream and rollback behavior.

## 38. MVP Requirements

The MVP SHALL implement:

- RUNTIME channel and approved Runtime Hello handshake;
- version negotiation and mutual challenge response;
- Runtime ID, Generation, Configuration and Binding Hash checks;
- Dispatcher Route Generation and scope checks;
- semantic Runtime Message ID, sequencing and replay protection;
- Runtime Ready, Health and capacity;
- Execute, acceptance/rejection and persistent Request idempotency;
- bounded queues, progress and explicit streaming;
- artifacts and final Results;
- dimension-specific Usage authority, hash chain and acknowledgments;
- honest cancellation and State Generation;
- reconnect, Recovery State/Plan, redelivery and no blind restart;
- draining, shutdown, stable errors and conformance tests.

Live Provider-native migration, distributed sharding, multipath streaming,
speculative multi-Runtime execution, confidential proofs, hardware attestation,
zero-knowledge Usage and direct Consumer-to-Runtime transport MAY be deferred.

## 39. Open Parameters

Configurable parameters include handshake timeout, connection lifetime, Health
and capacity freshness, message/inline/chunk sizes, queue depth/bytes/wait,
concurrent Requests/streams, acknowledgment timeouts, Result retention, retry
limits/backoff, recovery state limit/timeout and drain/shutdown timeout.

## 40. Invariants

- RFC-0054 is execution, not Provider or Plugin management.
- Endpoint publication, pricing and Settlement remain external.
- Every connection binds one approved Runtime ID and exact Configuration.
- Runtime Generation and Route Generation are independently checked.
- Instance ID may change after ordinary restart.
- Network and Runtime Message IDs remain distinct.
- Duplicate identical Requests do not execute twice.
- Conflicting duplicate Requests and stream chunks are rejected.
- Acceptance is not completion and transport close is not stream completion.
- Runtime does not alter deadline, charge ceiling or side-effect approval.
- Usage authority is dimension-specific; unknown values remain unknown.
- Usage and Results remain separate and hash-bound.
- Output suppression is not confirmed Provider cancellation.
- Recovery reconciles both sides and never blindly restarts work.
- Existing Results and Usage may be redelivered without re-execution.
- Concealed Validation uses ordinary execution messages.
- Provider-native peculiarities remain behind the Runtime Adapter.

## RFC-0051 Evidence Transport Binding

`RUNTIME_USAGE_REPORT` is the transport representation of the RFC-0051 Usage
Report, not a separate accounting object. Availability includes `AVAILABLE`,
`PARTIAL`, `UNAVAILABLE` and `NOT_APPLICABLE`; only available or partial values
carry Authority. The Hypervisor acknowledges authenticated reports with
`ACCEPTED`, `DUPLICATE`, `REJECTED`, `CONFLICT`, `OUT_OF_SEQUENCE` or
`PENDING_REVIEW` and preserves conflict evidence. A terminal Runtime Result
SHALL NOT be accepted without the matching accepted Final Usage Report.
