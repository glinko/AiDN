# RFC-0054 Capability Runtime Protocol

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0039 Hypervisor Service Model`
- `RFC-0042 Hypervisor Network Protocol`
- `RFC-0044 Session Protocol`
- `RFC-0045 Capability Architecture`
- `RFC-0051 Usage Reporting and Verification Protocol`
- `RFC-0053 Capability Runtime Specification`
- `RFC-0059 Ledger Operation Catalog`
- `RFC-0060 Session Failure, Recovery and Forced Settlement`

## 1. Purpose

This document defines the logical protocol used between an AiDN Hypervisor and a Capability Runtime.

`RFC-0053` defines the Capability Runtime as a service model and architectural boundary.

This document defines the detailed Runtime message protocol used across that boundary.

The Runtime Protocol enables an independent Runtime Service to:

- register with a Hypervisor;
- advertise its Capability;
- publish Endpoint definitions;
- accept and execute Sessions;
- stream results;
- report usage;
- report health;
- recover interrupted Sessions;
- execute Validation benchmarks;
- shut down or disconnect safely.

The protocol is independent of:

- implementation language;
- operating system;
- deployment topology;
- process ownership;
- transport technology;
- Provider implementation.

## 2. Scope

This protocol applies only to communication between:

```text
Hypervisor
    ↕
Capability Runtime
```

It does not define communication between two remote Hypervisors.

Remote Hypervisor communication is defined by `RFC-0042`.

The Hypervisor translates external AiDN Session messages into Runtime Protocol messages.

## 3. Design Principles

The Runtime Protocol SHALL be:

- transport-independent;
- language-independent;
- versioned;
- authenticated;
- bidirectional;
- asynchronous where required;
- streaming-capable;
- reconnectable;
- idempotent;
- observable;
- safe under partial failure.

The Hypervisor SHALL remain unaware of Runtime-specific Provider implementations.

The Runtime SHALL remain unable to modify Ledger state directly.

## 4. Architectural Boundary

The Hypervisor is responsible for:

- network identity;
- Wallet authorization;
- Ledger integration;
- Deposit enforcement;
- Session routing;
- Endpoint publication;
- Settlement;
- protocol-level timeouts;
- Runtime authorization;
- Session failure handling.

The Capability Runtime is responsible for:

- Provider discovery;
- model or backend management;
- Capability-specific execution;
- request parsing;
- response generation;
- usage reporting;
- Capability-specific validation;
- Runtime-local resource scheduling;
- Runtime health reporting.

## 5. Runtime Deployment

A Capability Runtime MAY execute as:

- a local process;
- a system service;
- a container;
- a virtual machine;
- a service on another physical host;
- a service within an orchestration platform;
- another compatible execution environment.

Runtime location SHALL NOT alter protocol semantics.

The Hypervisor SHALL NOT assume that a Runtime is local.

## 6. Runtime Identity

Every Runtime SHALL have a unique Runtime Identity.

```yaml
runtime_identity:
  runtime_id:
  runtime_public_key:
  capability_id:
  runtime_version:
  runtime_protocol_version:
```

The Runtime private key authorizes Runtime Protocol messages.

A Runtime key is separate from:

- Wallet keys;
- Hypervisor Node Identity keys;
- Endpoint identities;
- Provider credentials.

## 7. Runtime Authorization

Before registration, the Hypervisor SHALL determine whether the Runtime is authorized to connect.

Authorization MAY be established through:

- explicit operator approval;
- preconfigured Runtime public key;
- one-time registration token;
- local trust policy;
- certificate enrollment;
- future service-discovery authorization.

Discovery alone SHALL NOT imply authorization.

## 8. Runtime Ownership

A Runtime MAY be:

- managed by the local Hypervisor operator;
- shared by multiple authorized Hypervisors;
- operated remotely by another infrastructure owner.

Runtime ownership and Endpoint ownership are separate concepts.

The Hypervisor publishing an Endpoint remains responsible for that Endpoint's protocol behavior.

## 9. Transport Independence

The Runtime Protocol MAY use:

- Unix Domain Sockets;
- TCP;
- QUIC;
- HTTP/2;
- gRPC;
- WebSocket;
- Named Pipes;
- standard input and output;
- shared memory with a control channel;
- future transports.

The selected transport SHALL NOT change:

- message meaning;
- Session semantics;
- usage accounting;
- error semantics;
- recovery behavior.

## 10. Recommended MVP Transport

The reference MVP SHOULD support:

Local Runtime:
Unix Domain Socket or loopback gRPC
Remote Runtime:
gRPC over mutually authenticated TLS

Other transports MAY be added later.

The logical message schema remains authoritative.

## 11. Protocol Layers

The Runtime Protocol has two logical planes.

### 11.1 Control Plane

Used for:

- registration;
- capability metadata;
- Endpoint management;
- health;
- version negotiation;
- Session lifecycle;
- recovery;
- configuration status;
- shutdown.

### 11.2 Data Plane

Used for:

- execution requests;
- streamed request data;
- streamed responses;
- artifacts;
- progress events;
- usage checkpoints.

Control and Data Planes MAY share one transport connection.

## 12. Connection Lifecycle

A Runtime connection follows:

```text
CONNECT
    ↓
AUTHENTICATE
    ↓
NEGOTIATE
    ↓
REGISTER
    ↓
SYNCHRONIZE
    ↓
READY
    ↓
SERVE
    ↓
DRAIN
    ↓
DISCONNECT
```

A Runtime SHALL NOT accept new Sessions before reaching `READY`.

## 13. Runtime Connection States

Initial connection states are:

- `DISCONNECTED`
- `CONNECTING`
- `AUTHENTICATING`
- `NEGOTIATING`
- `REGISTERING`
- `SYNCHRONIZING`
- `READY`
- `DEGRADED`
- `DRAINING`
- `UNAVAILABLE`
- `REJECTED`

The Hypervisor SHALL maintain the authoritative local connection state.

## 14. Common Message Envelope

Every Runtime Protocol message SHALL use a common envelope.

```yaml
runtime_message:
  message_id:
  message_type:
  message_version:
  runtime_protocol_version:
  runtime_id:
  hypervisor_id:
  connection_id:
  request_id:
  correlation_id:
  session_id:
  endpoint_id:
  sequence:
  created_at:
  deadline:
  payload:
  signature:
```

Fields not applicable SHALL be omitted according to canonical schema.

## 15. Message Identity

Every message SHALL have a unique `message_id`.

Message identity supports:

- replay protection;
- idempotency;
- diagnostics;
- correlation;
- duplicate detection.

A retried message SHALL retain the same Message ID when it represents the same logical operation.

## 16. Request and Correlation IDs

`request_id` identifies one logical request.

`correlation_id` links:

- responses;
- progress events;
- streamed chunks;
- Usage Reports;
- errors;
- cancellation messages.

A Runtime SHALL NOT reuse a Request ID within the same connection or Session.

## 17. Message Sequence

Ordered message streams SHALL use monotonically increasing sequence numbers.

Sequence numbers MAY be scoped to:

- connection;
- Session;
- execution request;
- streaming channel.

The scope SHALL be defined by the message type.

Duplicate messages with identical IDs and content SHALL be handled idempotently.

Conflicting messages with the same sequence SHALL generate a protocol error.

## 18. Deadlines

Messages MAY include a protocol deadline.

The deadline defines when the receiver may stop attempting execution.

Runtime deadlines SHALL use synchronized protocol timestamps or relative durations negotiated at connection time.

Ledger consequences still rely on finalized protocol time rather than Runtime-local clocks.

## 19. Authentication

Every Runtime connection SHALL be authenticated.

For remote connections, the protocol SHOULD use mutual TLS.

Message-level signatures MAY additionally protect:

- Runtime registration;
- Endpoint definitions;
- Usage Reports;
- recovery state;
- benchmark results;
- shutdown notices.

Unsigned ordinary Data Plane chunks MAY be permitted only inside an authenticated integrity-protected channel.

## 20. Confidentiality

Remote Runtime transports SHALL provide encryption.

Local transports SHOULD enforce operating-system access controls.

Sensitive Runtime data MAY include:

- Provider credentials;
- OAuth tokens;
- model configuration;
- private Endpoint metadata;
- Session content;
- execution artifacts.

Provider credentials SHALL NOT be transmitted to the Hypervisor unless explicitly required.

## 21. Version Negotiation

The Hypervisor and Runtime SHALL negotiate compatible versions before registration.

The negotiation request includes:

```yaml
NEGOTIATE_VERSION:
  supported_runtime_protocol_versions:
  supported_capability_versions:
  supported_message_features:
  required_security_features:
```

The response includes:

```yaml
VERSION_SELECTED:
  runtime_protocol_version:
  capability_version:
  enabled_features:
  disabled_features:
```

If no compatible version exists, registration SHALL fail.

## 22. Feature Negotiation

Optional features MAY include:

- bidirectional streaming;
- resumable streaming;
- Runtime-side Session persistence;
- artifact references;
- shared-memory transfer;
- batching;
- speculative execution;
- Proxy-Opaque accounting;
- external side-effect reporting;
- benchmark support;
- hot Runtime replacement.

Unknown optional features SHALL be ignored unless marked required.

## 23. Runtime Registration

The Runtime registers using:

`REGISTER_RUNTIME`

Required payload:

```yaml
register_runtime:
  runtime_id:
  runtime_public_key:
  capability_id:
  capability_version:
  runtime_version:
  runtime_protocol_version:
  supported_features:
  deployment_metadata:
  health_status:
  endpoint_generation_mode:
```

Registration SHALL be signed by the Runtime Identity.

## 24. Registration Response

The Hypervisor responds with:

`RUNTIME_REGISTERED`

or:

`RUNTIME_REJECTED`

A successful response includes:

```yaml
runtime_registered:
  connection_id:
  hypervisor_id:
  accepted_capability_version:
  accepted_features:
  heartbeat_policy:
  session_limits:
  endpoint_policy:
  configuration_reference:
```

## 25. Registration Rejection

Possible rejection reasons include:

- `UNAUTHORIZED_RUNTIME`
- `UNSUPPORTED_PROTOCOL_VERSION`
- `UNSUPPORTED_CAPABILITY`
- `INVALID_RUNTIME_SIGNATURE`
- `DUPLICATE_RUNTIME_ID`
- `RUNTIME_SUSPENDED`
- `SECURITY_POLICY_MISMATCH`
- `CONFIGURATION_REQUIRED`

A rejected Runtime SHALL NOT publish Endpoints or accept Sessions.

## 26. Runtime Synchronization

After registration, the Hypervisor and Runtime synchronize state.

Synchronization includes:

- known Endpoint definitions;
- active Sessions;
- recoverable Sessions;
- current configuration versions;
- pending shutdown state;
- Runtime capabilities;
- accounting contract versions.

A Runtime SHALL not assume its local state is authoritative until synchronization completes.

## 27. Synchronization Messages

Initial messages include:

- `SYNC_BEGIN`
- `SYNC_ENDPOINTS`
- `SYNC_SESSIONS`
- `SYNC_CONFIGURATION`
- `SYNC_COMPLETE`

Synchronization SHALL be resumable.

Each synchronized object SHALL include:

- object identifier;
- version;
- state hash;
- last modification sequence.

## 28. Runtime Ready

The Runtime sends:

`RUNTIME_READY`

only after:

- registration succeeds;
- synchronization completes;
- required Providers are available;
- required configuration is valid;
- the Runtime can accept protocol requests.

The Hypervisor then marks the Runtime as `READY`.

## 29. Runtime Capability Metadata

The Runtime SHALL expose Capability metadata.

`GET_CAPABILITY_METADATA`
`CAPABILITY_METADATA`

Metadata MAY include:

- request schema;
- response schema;
- supported accounting modes;
- supported validation features;
- supported content types;
- streaming support;
- cancellation support;
- Provider types;
- Runtime limits.

## 30. Provider Discovery

The Runtime MAY discover Providers automatically.

Provider discovery remains internal to the Runtime.

The Runtime MAY report high-level Provider status:

- `PROVIDER_AVAILABLE`
- `PROVIDER_DEGRADED`
- `PROVIDER_UNAVAILABLE`

The Hypervisor SHALL not require Provider-specific APIs.

## 31. Provider Credentials

Provider credentials remain Runtime-private.

Examples include:

- API keys;
- OAuth credentials;
- refresh tokens;
- model repository credentials;
- local Provider authentication.

The Runtime MAY report credential status without exposing secrets.

```yaml
provider_auth_status:
  provider_reference:
  status: VALID | EXPIRED | REAUTH_REQUIRED | INVALID
```

## 32. Endpoint Discovery

The Hypervisor requests Runtime Endpoint definitions with:

`LIST_RUNTIME_ENDPOINTS`

The Runtime responds:

`RUNTIME_ENDPOINT_LIST`

Each Endpoint definition includes:

```yaml
runtime_endpoint:
  runtime_endpoint_id:
  capability_id:
  provider_reference:
  endpoint_configuration_hash:
  supported_features:
  accounting_modes:
  health:
  concurrency:
  metadata_hash:
```

## 33. Endpoint Proposal

The Runtime MAY propose a new Endpoint using:

`PROPOSE_ENDPOINT`

The proposal is not a Marketplace publication.

The Hypervisor operator or policy engine decides whether to create and publish the AiDN Endpoint.

## 34. Endpoint Binding

When accepted, the Hypervisor binds:

```text
AiDN Endpoint ID
    ↕
Runtime Endpoint ID
```

The binding is represented by:

`BIND_ENDPOINT`

The Runtime responds:

`ENDPOINT_BOUND`

The binding SHALL include the current Endpoint configuration hash.

## 35. Endpoint Update Notification

The Runtime SHALL notify the Hypervisor when execution-relevant Endpoint configuration changes.

`ENDPOINT_CONFIGURATION_CHANGED`

Examples include:

- model change;
- Provider change;
- tokenizer change;
- Capability version change;
- execution backend change;
- accounting behavior change.

The Hypervisor decides whether:

- Endpoint metadata is updated;
- Certification is invalidated;
- new Sessions are paused;
- Marketplace Advertisement is changed.

## 36. Endpoint Availability

The Runtime reports:

- `ENDPOINT_AVAILABLE`
- `ENDPOINT_DEGRADED`
- `ENDPOINT_UNAVAILABLE`

Availability messages SHALL include:

- Runtime Endpoint ID;
- reason code;
- expected recovery where known;
- affected active Sessions;
- current concurrency.

The Hypervisor controls public Endpoint state.

## 37. Endpoint Removal

The Runtime MAY announce:

`RUNTIME_ENDPOINT_REMOVED`

The Hypervisor SHALL:

- stop routing new Sessions;
- preserve active Sessions if recoverable;
- update public Endpoint state;
- initiate failure handling when necessary.

Removing a Runtime Endpoint does not directly modify Ledger state.

## 38. Session Routing

The Hypervisor routes a Session only to a Runtime that:

- is `READY` or permitted `DEGRADED`;
- supports the required Capability version;
- owns the bound Runtime Endpoint;
- supports the accepted Accounting Contract;
- has available concurrency;
- is not draining.

## 39. Runtime Session States

The Runtime SHALL track:

- `SESSION_UNKNOWN`
- `SESSION_PREPARING`
- `SESSION_READY`
- `SESSION_ACTIVE`
- `SESSION_PAUSED`
- `SESSION_RECOVERING`
- `SESSION_CLOSING`
- `SESSION_CLOSED`
- `SESSION_FAILED`

Runtime Session state does not replace canonical Hypervisor or Ledger Session state.

## 40. Session Preparation

Before external Session acceptance, the Hypervisor sends:

`PREPARE_SESSION`

Payload includes:

```yaml
prepare_session:
  session_id:
  endpoint_id:
  runtime_endpoint_id:
  capability_version:
  endpoint_configuration_hash:
  accounting_contract:
  pricing_reference:
  session_policy:
  resource_requirements:
  preparation_deadline:
```

The Runtime SHALL not begin billable execution during preparation.

## 41. Session Preparation Response

The Runtime responds with:

`SESSION_PREPARED`

or:

`SESSION_PREPARE_REJECTED`

Successful preparation confirms:

- required Provider is available;
- required model or backend can be used;
- Session context was allocated;
- Accounting Contract is supported;
- concurrency slot is reserved.

## 42. External Session Acceptance

The Hypervisor SHALL send the remote `SESSION_ACCEPT` only after Runtime preparation succeeds.

If Ledger or network acceptance later fails, the Hypervisor SHALL release the prepared Runtime Session.

`RELEASE_PREPARED_SESSION`

## 43. Runtime Session Activation

After external Session acceptance is finalized or otherwise authorized, the Hypervisor sends:

`ACTIVATE_SESSION`

The Runtime responds:

`SESSION_ACTIVATED`

Billable Session behavior begins only after activation.

## 44. Execute Request

The Hypervisor sends:

`EXECUTE_REQUEST`

Required payload:

```yaml
execute_request:
  session_id:
  request_id:
  endpoint_id:
  capability_request:
  request_hash:
  execution_parameters:
  output_limits:
  budget_limits:
  accounting_checkpoint_policy:
  deadline:
```

The Runtime SHALL validate the request before execution.

## 45. Request Acceptance

The Runtime responds:

`REQUEST_ACCEPTED`

or:

`REQUEST_REJECTED`

Acceptance includes:

- request ID;
- execution queue state;
- estimated start;
- estimated limits;
- Runtime request sequence.

A rejected request SHALL not create billable execution unless the accepted policy includes a disclosed attempt fee.

## 46. Request Execution States

The Runtime MAY emit:

- `REQUEST_QUEUED`
- `REQUEST_STARTED`
- `REQUEST_PROGRESS`
- `REQUEST_RESULT_AVAILABLE`
- `REQUEST_COMPLETED`
- `REQUEST_FAILED`
- `REQUEST_CANCELLED`

Each transition SHALL be correlated to the Request ID.

## 47. Input Streaming

Capabilities MAY support streamed input.

Input stream messages include:

- `INPUT_STREAM_OPEN`
- `INPUT_STREAM_CHUNK`
- `INPUT_STREAM_END`
- `INPUT_STREAM_ABORT`

Chunks SHALL include:

- stream ID;
- chunk sequence;
- content hash or integrity metadata;
- final-chunk indicator where applicable.

## 48. Output Streaming

Streaming output messages include:

- `OUTPUT_STREAM_OPEN`
- `OUTPUT_STREAM_CHUNK`
- `OUTPUT_STREAM_END`
- `OUTPUT_STREAM_ABORT`

The Hypervisor SHALL preserve ordering.

Duplicate chunks SHALL be detected by:

- stream ID;
- chunk sequence;
- chunk hash.

Duplicate transport delivery SHALL not create duplicate accounting.

## 49. Backpressure

The Runtime Protocol SHALL support backpressure.

The receiver MAY indicate:

- `STREAM_WINDOW_UPDATE`
- `STREAM_PAUSE`
- `STREAM_RESUME`

The sender SHALL not exceed the negotiated receive window.

Failure to respect backpressure MAY cause:

- stream cancellation;
- request failure;
- Runtime disconnection;
- Health degradation.

## 50. Artifact Delivery

Large outputs MAY be delivered as:

- streamed bytes;
- local file references;
- shared-memory objects;
- content-addressed Registry references;
- temporary authenticated download references.

Artifact metadata includes:

```yaml
artifact:
  artifact_id:
  content_type:
  size:
  content_hash:
  delivery_mode:
  expiration:
```

The Hypervisor SHALL verify artifact hashes before accepting completion.

## 51. Progress Reporting

A Runtime MAY emit progress events.

`REQUEST_PROGRESS`

Progress MAY include:

- percentage where meaningful;
- current stage;
- processed units;
- estimated remaining time;
- tool activity;
- warnings.

Progress is informational unless a Capability contract defines billable milestones.

## 52. Tool Calls

Agentic Runtimes MAY emit visible tool-call events.

- `TOOL_CALL_STARTED`
- `TOOL_CALL_COMPLETED`
- `TOOL_CALL_FAILED`

Events SHALL include:

- tool-call ID;
- tool category;
- input hash;
- output hash;
- visibility;
- side-effect classification.

Private Provider-internal tool calls need not be exposed unless they are billable.

## 53. External Side Effects

Before an irreversible external action, the Runtime SHOULD emit:

`SIDE_EFFECT_PROPOSED`

The Hypervisor or Consumer policy may require explicit authorization.

After completion, the Runtime emits:

`SIDE_EFFECT_COMPLETED`

with verifiable evidence where possible.

Examples include:

- sending an email;
- modifying a repository;
- triggering deployment;
- submitting an external transaction.

## 54. Request Completion

A Runtime SHALL emit:

`REQUEST_COMPLETED`

only when the Capability-specific completion condition is met.

Completion includes:

- result references;
- final result hash;
- completion status;
- Runtime-side request usage;
- warnings;
- side-effect summary.

Internal computation without deliverable output SHALL not automatically qualify as completion.

## 55. Request Failure

The Runtime emits:

`REQUEST_FAILED`

with:

```yaml
request_failure:
  request_id:
  failure_class:
  retryable:
  partial_result_available:
  billable_status:
  evidence_hash:
  message:
```

The Runtime SHALL distinguish:

- Provider error;
- invalid Consumer request;
- resource exhaustion;
- timeout;
- upstream failure;
- cancellation;
- protocol error;
- internal Runtime failure.

## 56. Request Cancellation

The Hypervisor sends:

`CANCEL_REQUEST`

The Runtime responds:

- `CANCEL_ACCEPTED`
- `CANCEL_REJECTED`
- `REQUEST_CANCELLED`

Cancellation SHALL occur at the nearest Capability-safe boundary.

The Runtime SHALL report:

- delivered result portion;
- observable usage;
- cancellation fee applicability;
- remaining side effects.

## 57. Session Pause

The Hypervisor MAY send:

`PAUSE_SESSION`

Reasons include:

- Deposit threshold;
- acknowledgement timeout;
- Consumer disconnect;
- accounting mismatch;
- manual operator action;
- Consensus interruption.

The Runtime SHALL stop beginning new billable work.

## 58. Session Resume

The Hypervisor sends:

`RESUME_SESSION`

The Runtime SHALL verify:

- Session state;
- current accounting checkpoint;
- policy hashes;
- active request state;
- resource availability.

The Runtime responds:

`SESSION_RESUMED`

or:

`SESSION_RESUME_REJECTED`

## 59. Usage Reporting

The Runtime SHALL send signed Provider Usage Reports through:

`USAGE_REPORT`

The report SHALL comply with `RFC-0051`.

The Hypervisor SHALL not invent Capability-specific usage values.

It SHALL:

- verify Runtime signature;
- bind the report to the Session;
- forward applicable reporting to the remote Hypervisor;
- preserve the report chain.

## 60. Usage Report Timing

Usage Reports SHALL be emitted:

- at configured checkpoints;
- after completed requests;
- before maximum unreported exposure;
- before Session close;
- after partial failure where applicable;
- after billable idle intervals when Runtime-managed.

## 61. Accounting Modes

The Runtime SHALL declare supported Accounting Modes:

- `DETERMINISTIC`
- `OBSERVABLE`
- `PROVIDER_METERED`
- `FIXED_PRICE`
- `PROXY_OPAQUE`

A Runtime SHALL not silently change Accounting Mode during an active Session.

## 62. Proxy-Opaque Runtime

A Runtime using an opaque upstream service SHALL explicitly report:

```yaml
proxy_opaque_status:
  upstream_usage_available: false
  token_estimation_available:
  billable_estimates: false
  observable_units:
  upstream_status:
  upstream_disclosure_mode:
  upstream_switching_possible:
  retry_policy_hash:
  failover_policy_hash:
```

Unknown upstream usage SHALL not be represented as zero.

Estimated tokens SHALL remain non-authoritative.

## 63. Usage Verification Support

Where supported, the Runtime exposes:

- `VERIFY_USAGE`
- `USAGE_VERIFICATION_RESULT`

The verification result MAY include:

- reproduced values;
- tolerance;
- mismatch fields;
- measurement version;
- evidence hash.

Proxy-specific Runtime events MAY additionally include:

- `UPSTREAM_AVAILABLE`
- `UPSTREAM_DEGRADED`
- `UPSTREAM_UNAVAILABLE`
- `UPSTREAM_AUTH_EXPIRED`
- `UPSTREAM_RATE_LIMITED`
- `UPSTREAM_QUOTA_EXHAUSTED`
- `UPSTREAM_SWITCHED`
- `PROXY_RETRY_STARTED`
- `PROXY_RETRY_COMPLETED`
- `PROXY_RETRY_FAILED`

The Consumer-side Hypervisor may use another Runtime or verifier to perform independent verification.

## 64. Health Reporting

The Runtime SHALL report Health periodically.

`RUNTIME_HEALTH`

Health MAY include:

```yaml
runtime_health:
  status:
  uptime:
  active_sessions:
  queued_requests:
  request_success_rate:
  provider_status:
  resource_utilization:
  recent_errors:
  accounting_status:
  timestamp:
```

Local Health reports do not directly modify Ledger Reputation.

Only protocol-verifiable evidence may do so.

## 65. Heartbeat

The Hypervisor and Runtime SHALL exchange heartbeat messages.

- `HEARTBEAT`
- `HEARTBEAT_ACK`

The heartbeat policy defines:

- interval;
- timeout;
- missed-heartbeat threshold;
- degraded threshold;
- unavailable threshold.

Heartbeat failure triggers Runtime recovery behavior.

## 66. Runtime Degraded State

A Runtime enters `DEGRADED` when:

- some Providers are unavailable;
- queue delays exceed policy;
- partial functionality remains;
- resource pressure is high;
- accounting support is impaired;
- repeated recoverable errors occur.

The Hypervisor MAY continue routing compatible Sessions according to policy.

## 67. Runtime Unavailable State

A Runtime becomes `UNAVAILABLE` when:

- heartbeat timeout expires;
- authentication fails;
- incompatible state is detected;
- required Provider is absent;
- Runtime explicitly reports fatal failure.

The Hypervisor SHALL stop routing new Sessions.

Active Sessions enter recovery or failure handling under `RFC-0060`.

## 68. Runtime Reconnection

A disconnected Runtime MAY reconnect using the same Runtime Identity.

The Runtime SHALL present:

- previous Runtime ID;
- new connection ID request;
- last synchronized state hash;
- active Session summary;
- Session checkpoint hashes;
- Runtime restart identifier.

## 69. Reconnection Authorization

The Hypervisor SHALL reject reconnection when:

- Runtime Identity changed unexpectedly;
- Runtime is suspended;
- state history conflicts;
- protocol version is no longer supported;
- another active connection claims the same Runtime Identity without takeover authorization.

## 70. Session Recovery

After reconnect, the Runtime sends:

`RECOVER_RUNTIME_SESSIONS`

For each Session:

```yaml
runtime_session_recovery:
  session_id:
  runtime_session_state:
  active_request_id:
  active_request_state:
  last_usage_report_hash:
  last_usage_sequence:
  result_hashes:
  recoverable:
```

The Hypervisor compares this with its canonical local Session state.

## 71. Recovery Decision

The Hypervisor responds per Session:

- `SESSION_RECOVERY_ACCEPTED`
- `SESSION_RECOVERY_RESET_TO_CHECKPOINT`
- `SESSION_RECOVERY_REJECTED`
- `SESSION_FORCE_CLOSE_REQUIRED`

The Hypervisor remains authoritative for protocol-level Session state.

The Runtime remains authoritative only for its recoverable execution context.

## 72. Runtime Replacement

A Hypervisor MAY bind an active Session to a replacement Runtime when:

- the Capability version matches;
- Endpoint behavior remains compatible;
- Accounting Contract is supported;
- Session context can be restored;
- policy permits replacement;
- no conflicting usage history exists.

The replacement Runtime receives:

`IMPORT_SESSION_CONTEXT`

## 73. Session Context Export

A Runtime supporting replacement MAY produce:

`EXPORT_SESSION_CONTEXT`

The context MAY include:

- conversation state;
- Provider session reference;
- request history;
- cached context;
- execution settings;
- Usage Report sequence;
- Capability-specific state.

Sensitive context SHALL be encrypted for the authorized destination Runtime.

## 74. Runtime Replacement Failure

If Session context cannot be restored:

- no new execution begins;
- the Session enters Provider recovery failure;
- the Hypervisor follows `RFC-0060`;
- accepted usage remains payable;
- unverified work remains Provider risk.

## 75. Validation Benchmark Execution

A Validator-capable Hypervisor MAY request:

`RUN_BENCHMARK`

Payload includes:

```yaml
run_benchmark:
  benchmark_id:
  capability_id:
  endpoint_id:
  benchmark_version:
  request_set_reference:
  evidence_requirements:
  deadline:
```

The Runtime responds with benchmark events and results.

## 76. Benchmark Isolation

Benchmark execution SHOULD be isolated from ordinary Session state.

It SHALL not:

- alter user Session histories;
- consume another Session's Deposit;
- modify Endpoint configuration;
- reveal active Validator identity externally where prohibited.

Validation traffic presented to an Endpoint SHALL remain ordinary Session traffic where required by `RFC-0057`.

## 77. Benchmark Result

The Runtime emits:

`BENCHMARK_RESULT`

including:

- result hashes;
- measurements;
- Capability observations;
- Runtime version;
- Provider status;
- usage metadata;
- evidence references.

The Runtime does not determine final Certification.

## 78. Configuration Management

Runtime-specific configuration remains opaque to the Hypervisor.

The Hypervisor MAY send:

`APPLY_RUNTIME_CONFIGURATION_REFERENCE`

The reference MAY identify:

- operator-managed configuration;
- secret storage entry;
- container environment;
- mounted configuration file;
- remote configuration object.

The Hypervisor SHALL not interpret Capability-specific fields unless separately standardized.

## 79. Configuration Validation

The Runtime reports:

- `CONFIGURATION_VALID`
- `CONFIGURATION_INVALID`
- `CONFIGURATION_RESTART_REQUIRED`

An invalid configuration SHALL prevent the affected Endpoint from accepting Sessions.

## 80. Secret Handling

Secrets SHALL be managed outside ordinary Runtime Protocol payloads where practical.

Preferred methods include:

- operating-system secret stores;
- mounted secret files;
- encrypted Runtime-local storage;
- short-lived credential references;
- external secret-management systems.

Runtime logs SHALL not include secrets.

## 81. Runtime Drain

Before planned shutdown or upgrade, the Runtime sends:

`RUNTIME_DRAINING`

The Hypervisor SHALL:

- stop routing new Sessions;
- allow existing Sessions to finish;
- identify Sessions requiring migration;
- enforce maximum drain time.

## 82. Graceful Runtime Shutdown

The Hypervisor or Runtime MAY initiate:

`SHUTDOWN_RUNTIME`

or:

`RUNTIME_SHUTDOWN_NOTICE`

Graceful shutdown includes:

- stopping new Sessions;
- completing or pausing active requests;
- publishing final Usage Reports;
- exporting recoverable Session contexts;
- releasing resources;
- sending `RUNTIME_STOPPED`.

## 83. Forced Runtime Shutdown

A forced shutdown may occur after:

- fatal security failure;
- protocol incompatibility;
- operator action;
- resource exhaustion;
- repeated malformed messages.

Active Sessions SHALL follow `RFC-0060` recovery rules.

## 84. Runtime Upgrade

A Runtime MAY be upgraded independently of the Hypervisor.

The upgrade procedure SHOULD support:

```text
DRAIN
    ↓
EXPORT SESSION CONTEXT
    ↓
STOP OLD RUNTIME
    ↓
START NEW RUNTIME
    ↓
REGISTER
    ↓
SYNCHRONIZE
    ↓
IMPORT SESSION CONTEXT
    ↓
RESUME
```

An upgrade SHALL not silently change active Session contracts.

## 85. Multiple Runtimes per Capability

A Hypervisor MAY register multiple Runtimes implementing the same Capability.

Example:

```text
llm.chat Runtime A
llm.chat Runtime B
llm.chat Runtime C
```

The Hypervisor MAY route Sessions based on:

- Endpoint binding;
- availability;
- load;
- policy;
- Runtime version;
- Provider type;
- locality.

## 86. Runtime Pools

Multiple compatible Runtimes MAY form a Runtime Pool.

A Runtime Pool SHALL declare:

- compatible Capability version;
- compatible Accounting Contracts;
- Session migration support;
- load-balancing policy;
- failure-domain metadata.

Runtime Pool behavior SHALL remain transparent to the remote Consumer unless it changes published Endpoint semantics.

## 87. Session Affinity

A Session SHALL remain bound to one Runtime unless:

- the Runtime fails;
- migration is requested;
- policy permits replacement;
- context compatibility is confirmed.

Request-by-request random Runtime switching SHALL not occur when it would alter:

- conversation state;
- accounting;
- model behavior;
- hidden Provider session state.

## 88. Load Reporting

The Runtime MAY report:

`RUNTIME_LOAD`

including:

- active Session count;
- maximum Session count;
- queue depth;
- estimated queue time;
- resource utilization;
- Provider capacity.

The Hypervisor uses load information for routing.

Published Marketplace load remains Hypervisor-controlled.

## 89. Concurrency

Each Runtime Endpoint SHALL declare concurrency limits.

```yaml
concurrency:
  maximum_sessions:
  maximum_active_requests:
  exclusive_session_supported:
  queue_supported:
```

The Runtime SHALL reject preparation when capacity is unavailable.

The Hypervisor SHALL not promise more capacity than registered Runtimes expose.

## 90. Exclusive Sessions

A Runtime Endpoint MAY support exclusive Session reservation.

The Runtime SHALL reserve the required resource during `PREPARE_SESSION`.

Exclusive reservation policies SHALL remain consistent with the public Endpoint Session Policy.

## 91. Error Envelope

Runtime Protocol errors SHALL use:

```yaml
runtime_error:
  error_code:
  error_category:
  retryable:
  request_id:
  session_id:
  details_hash:
  human_message:
```

Human-readable messages are diagnostic.

Error codes determine protocol behavior.

## 92. Error Categories

Initial categories are:

- `AUTHENTICATION`
- `AUTHORIZATION`
- `VERSION`
- `SCHEMA`
- `STATE`
- `CAPACITY`
- `PROVIDER`
- `EXECUTION`
- `ACCOUNTING`
- `STREAM`
- `TIMEOUT`
- `RECOVERY`
- `CONFIGURATION`
- `SECURITY`
- `INTERNAL`

## 93. Standard Error Codes

The MVP SHALL define at least:

- `INVALID_MESSAGE`
- `INVALID_SIGNATURE`
- `UNAUTHORIZED_RUNTIME`
- `UNSUPPORTED_PROTOCOL_VERSION`
- `UNSUPPORTED_CAPABILITY_VERSION`
- `UNKNOWN_RUNTIME`
- `UNKNOWN_ENDPOINT`
- `UNKNOWN_SESSION`
- `UNKNOWN_REQUEST`
- `INVALID_SESSION_STATE`
- `STALE_CONFIGURATION`
- `ACCOUNTING_CONTRACT_UNSUPPORTED`
- `CAPACITY_EXHAUSTED`
- `PROVIDER_UNAVAILABLE`
- `PROVIDER_AUTH_EXPIRED`
- `REQUEST_INVALID`
- `REQUEST_TIMEOUT`
- `REQUEST_CANCELLED`
- `STREAM_SEQUENCE_ERROR`
- `STREAM_WINDOW_EXCEEDED`
- `ARTIFACT_HASH_MISMATCH`
- `USAGE_REPORT_CONFLICT`
- `RECOVERY_STATE_CONFLICT`
- `SESSION_CONTEXT_UNAVAILABLE`
- `RUNTIME_DRAINING`
- `RUNTIME_INTERNAL_ERROR`

## 94. Retry Behavior

Every error SHALL declare whether retry is safe.

Retry classes include:

- `DO_NOT_RETRY`
- `RETRY_SAME_MESSAGE`
- `RETRY_AFTER_DELAY`
- `RECONNECT_AND_RETRY`
- `REPREPARE_SESSION`
- `REQUIRE_OPERATOR_ACTION`

Retries SHALL preserve Message IDs when repeating the same logical action.

## 95. Idempotent Messages

The following SHALL be idempotent:

- `REGISTER_RUNTIME`;
- synchronization messages;
- `PREPARE_SESSION`;
- `ACTIVATE_SESSION`;
- `PAUSE_SESSION`;
- `RESUME_SESSION`;
- `CANCEL_REQUEST`;
- `USAGE_REPORT`;
- recovery messages;
- Endpoint binding;
- graceful shutdown requests.

Repeated identical messages SHALL not duplicate state changes.

## 96. Non-Idempotent Execution

`EXECUTE_REQUEST` is economically sensitive.

The Runtime SHALL detect duplicate Request IDs.

A repeated identical Execute Request SHALL:

- return the existing request state;
- not start duplicate computation;
- not create duplicate billing.

A repeated Request ID with different content SHALL be rejected.

## 97. Logging

The Runtime and Hypervisor SHOULD log:

- connection changes;
- registration;
- Session transitions;
- request transitions;
- errors;
- recovery events;
- Usage Report sequences;
- Runtime upgrades;
- security events.

Logs SHALL avoid storing private Session payloads by default.

## 98. Metrics

The Runtime Protocol SHOULD expose:

- connection uptime;
- reconnect count;
- message latency;
- request latency;
- stream throughput;
- stream backpressure;
- active Sessions;
- queue depth;
- error rate;
- recovery success;
- Usage Report delay;
- Provider failure rate;
- Runtime replacement success.

Local metrics do not directly become Ledger Reputation.

## 99. Rate Limiting

The Hypervisor and Runtime MAY apply rate limits to:

- registration attempts;
- malformed messages;
- Session preparation;
- request execution;
- benchmark execution;
- artifact downloads;
- health requests.

Rate limits SHALL not silently alter active Session billing.

## 100. Security Boundaries

A compromised Runtime SHALL not be able to:

- access Wallet private keys;
- mint Q;
- unlock Deposits;
- finalize Settlement;
- publish Ledger Operations without Hypervisor authorization;
- impersonate the Hypervisor;
- modify unrelated Runtime configuration;
- access other Sessions without authorization.

The Hypervisor SHALL treat Runtime-provided data as signed claims requiring validation.

## 101. Remote Runtime Security

Remote Runtime deployment SHOULD require:

- mutual TLS;
- Runtime allowlisting;
- connection replay protection;
- Session-level authorization;
- restricted network exposure;
- certificate rotation;
- message size limits;
- stream limits;
- audit logs.

A remote Runtime SHALL not become publicly accessible merely because it registers with one Hypervisor.

## 102. Runtime Multi-Tenancy

A Runtime MAY serve multiple Hypervisors.

It SHALL isolate:

- Session content;
- Endpoint configuration;
- Provider credentials;
- usage accounting;
- Runtime quotas;
- artifacts;
- authorization.

One Hypervisor SHALL not access another Hypervisor's Runtime Sessions.

## 103. Runtime Trust Model

The Hypervisor trusts the Runtime only for Capability-specific execution claims.

It does not trust the Runtime to determine:

- Wallet authorization;
- Ledger state;
- available Deposit;
- final Settlement;
- protocol rewards;
- Certification;
- participant eligibility.

Runtime claims MAY influence these systems only through signed evidence and protocol-defined processing.

## 104. Ledger Boundary

Runtime Protocol messages do not directly modify Ledger state.

A Runtime message MAY cause the Hypervisor to construct a Ledger Operation.

Examples:

```text
Runtime Usage Report
→
Hypervisor Session Settlement preparation
Runtime Endpoint Configuration Changed
→
Hypervisor ENDPOINT_UPDATE operation
Runtime Benchmark Result
→
Validation Report evidence
```

The Hypervisor remains the Ledger integration boundary.

## 105. Failure Handling

Runtime Protocol failure SHALL map to `RFC-0060`.

Examples:

| Runtime Failure | Session Consequence |
| --- | --- |
| Temporary disconnect | `RECOVERING` |
| Provider unavailable | `PROVIDER_UNAVAILABLE` |
| Runtime state conflict | `STATE_RECOVERY_FAILURE` |
| Usage Report conflict | `ACCOUNTING_MISMATCH` |
| Fatal Runtime crash | Provider recovery or Forced Settlement |
| Runtime draining | Graceful Session close or migration |

## 106. Protocol Incompatibility

If a Runtime becomes incompatible during active operation:

- new Sessions SHALL stop;
- active Sessions SHOULD continue only if their negotiated versions remain supported;
- incompatible Sessions SHALL enter graceful close or recovery;
- configuration and version evidence SHALL be preserved.

A Runtime upgrade SHALL not retroactively reinterpret Usage Reports.

## 107. Message Schema Evolution

New message versions SHALL:

- preserve existing semantics where practical;
- declare required and optional fields;
- define downgrade behavior;
- define unknown-field handling;
- activate through version negotiation.

A receiver SHALL reject unknown required fields.

It MAY preserve unknown optional fields.

## 108. Capability Extensions

A Capability MAY define namespaced Runtime messages.

Example:

```text
llm.chat/context_cache_status
video.generate/frame_progress
agent.execute/workspace_change
```

Capability extensions SHALL not override:

- authentication;
- Session identity;
- Deposit enforcement;
- Usage Report requirements;
- core error semantics;
- recovery invariants.

## 109. Runtime Protocol Conformance

Every Runtime implementation SHALL pass conformance tests covering:

- registration;
- authentication;
- version negotiation;
- Endpoint binding;
- Session lifecycle;
- duplicate request handling;
- cancellation;
- streaming;
- backpressure;
- Usage Reporting;
- recovery;
- shutdown;
- malformed messages;
- incompatible versions;
- security boundaries.

## 110. Reference Test Runtime

The project SHOULD maintain a minimal Reference Runtime.

The Reference Runtime SHOULD:

- implement a simple deterministic Capability;
- support fixed-price requests;
- support streaming;
- support Usage Reports;
- support recovery;
- intentionally expose failure test modes.

It provides a protocol-development target independent of complex AI Providers.

## 111. MVP Message Set

The MVP SHALL implement:

- `NEGOTIATE_VERSION`
- `VERSION_SELECTED`
- `REGISTER_RUNTIME`
- `RUNTIME_REGISTERED`
- `RUNTIME_REJECTED`
- `RUNTIME_READY`
- `SYNC_BEGIN`
- `SYNC_ENDPOINTS`
- `SYNC_SESSIONS`
- `SYNC_CONFIGURATION`
- `SYNC_COMPLETE`
- `GET_CAPABILITY_METADATA`
- `CAPABILITY_METADATA`
- `LIST_RUNTIME_ENDPOINTS`
- `RUNTIME_ENDPOINT_LIST`
- `PROPOSE_ENDPOINT`
- `BIND_ENDPOINT`
- `ENDPOINT_BOUND`
- `ENDPOINT_CONFIGURATION_CHANGED`
- `ENDPOINT_AVAILABLE`
- `ENDPOINT_DEGRADED`
- `ENDPOINT_UNAVAILABLE`
- `RUNTIME_ENDPOINT_REMOVED`
- `PREPARE_SESSION`
- `SESSION_PREPARED`
- `SESSION_PREPARE_REJECTED`
- `RELEASE_PREPARED_SESSION`
- `ACTIVATE_SESSION`
- `SESSION_ACTIVATED`
- `PAUSE_SESSION`
- `RESUME_SESSION`
- `SESSION_RESUMED`
- `SESSION_RESUME_REJECTED`
- `EXECUTE_REQUEST`
- `REQUEST_ACCEPTED`
- `REQUEST_REJECTED`
- `REQUEST_STARTED`
- `REQUEST_PROGRESS`
- `REQUEST_COMPLETED`
- `REQUEST_FAILED`
- `CANCEL_REQUEST`
- `REQUEST_CANCELLED`
- `OUTPUT_STREAM_OPEN`
- `OUTPUT_STREAM_CHUNK`
- `OUTPUT_STREAM_END`
- `OUTPUT_STREAM_ABORT`
- `STREAM_WINDOW_UPDATE`
- `STREAM_PAUSE`
- `STREAM_RESUME`
- `USAGE_REPORT`
- `VERIFY_USAGE`
- `USAGE_VERIFICATION_RESULT`
- `RUNTIME_HEALTH`
- `HEARTBEAT`
- `HEARTBEAT_ACK`
- `RUNTIME_LOAD`
- `RECOVER_RUNTIME_SESSIONS`
- `SESSION_RECOVERY_ACCEPTED`
- `SESSION_RECOVERY_REJECTED`
- `SESSION_FORCE_CLOSE_REQUIRED`
- `RUN_BENCHMARK`
- `BENCHMARK_RESULT`
- `RUNTIME_DRAINING`
- `SHUTDOWN_RUNTIME`
- `RUNTIME_SHUTDOWN_NOTICE`
- `RUNTIME_STOPPED`
- `ERROR`

## 112. Deferred Features

The MVP MAY postpone:

- shared-memory bulk transfer;
- multi-Hypervisor Runtime pools;
- live Session migration;
- cross-host Session-context transfer;
- zero-copy streaming;
- confidential-computing attestation;
- Runtime marketplace;
- dynamic remote Runtime discovery;
- distributed Runtime scheduling;
- collaborative multi-Runtime execution;
- nested Runtime calls.

## 113. Open Protocol Parameters

The following remain configurable:

- maximum message size;
- maximum stream chunk size;
- heartbeat interval;
- heartbeat timeout;
- reconnect delay;
- registration timeout;
- Session preparation timeout;
- synchronization timeout;
- maximum concurrent Sessions;
- maximum concurrent requests;
- stream window size;
- benchmark rate limit;
- artifact retention;
- context export size;
- Runtime drain timeout;
- supported security modes.

These values SHALL be versioned or negotiated.

## 114. Protocol Invariants

- Every Runtime has a unique authenticated identity.
- Discovery does not imply authorization.
- Runtime deployment topology does not alter semantics.
- The Hypervisor never directly communicates with internal Providers.
- The Runtime never directly modifies Ledger state.
- Every Session is prepared before external acceptance.
- Duplicate Execute Requests never start duplicate work.
- Usage Reports remain signed and sequence-linked.
- Runtime replacement never resets accounting.
- Runtime reconnect never overrides canonical Hypervisor Session state.
- Streaming duplicates never create duplicate billing.
- Backpressure SHALL be respected.
- Runtime failure SHALL not terminate the Hypervisor.
- Hypervisor failure SHALL not authorize arbitrary Runtime billing.
- Active Session contracts remain immutable across Runtime upgrades.
- Capability extensions cannot override core economic rules.

## 115. Design Invariants

- The Runtime Protocol is transport-independent.
- The Runtime Protocol is language-independent.
- Capability Runtimes are independent replaceable services.
- Hypervisor and Runtime responsibilities remain strictly separated.
- Providers remain private Runtime implementation details.
- Runtime communication is authenticated.
- Runtime Sessions are recoverable where supported.
- Runtime failures are isolated.
- The Hypervisor controls Ledger and economic state.
- The Runtime controls Capability-specific execution.
- All economically relevant Runtime claims are verifiable or explicitly classified by Accounting Mode.
- New Capabilities can implement the Runtime Protocol without modifying Hypervisor core.
