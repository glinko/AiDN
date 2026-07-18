# RFC-0053 Capability Runtime Specification

Status: `Draft`

Version: `0.5`

Revision note: every Runtime Binding exposes Dispatcher destination scope,
authorized message profiles, Endpoint Configuration binding and current Route
Generation. Runtime replacement invalidates stale routes unless Session-safe
migration is explicitly proven.

Depends on:

- `RFC-0039 Hypervisor Service Model`
- `RFC-0042 Hypervisor Network Protocol`
- `RFC-0044 Session Protocol`
- `RFC-0045 Capability Architecture`
- `RFC-0055 Provider Plugin System and Directory`
- `RFC-0056 Provider Plugin Runtime Interface`

## 1. Purpose

This document defines the Runtime Protocol between the Hypervisor and a Capability Runtime.

A Capability Runtime is an independent service implementing exactly one computational Capability.

The Hypervisor never executes Capability-specific logic.

The Hypervisor orchestrates Runtime Services through the Runtime Protocol.

A Runtime MAY execute as:

- a local operating system process;
- a container;
- a virtual machine;
- a remote service;
- or another supported execution environment.

Runtime deployment is an implementation detail and SHALL NOT affect protocol behavior.

## 2. Design Philosophy

The Hypervisor is a runtime host.

Capability Runtimes implement computational behavior.

Providers are private implementation details of a Runtime.

The Hypervisor never communicates directly with Providers.

The Hypervisor communicates exclusively through the Runtime Protocol.

Every Runtime behaves identically regardless of its internal implementation.

Within a Hypervisor implementation, a Runtime MAY be assembled from:

- one Provider Instance;
- one Model Deployment;
- one Provider Plugin adapter;
- one Runtime Binding exposing exactly one primary Capability contract.

Those assembly details remain internal as long as the resulting Runtime behaves
like one normalized AiDN Runtime Service.

## 3. Runtime Model

Capability Runtimes are independent services.

The Hypervisor does not own Runtime execution.

Instead, Runtime Services register themselves with the Hypervisor.

A Runtime MAY execute:

- locally;
- inside a container;
- inside a virtual machine;
- on another physical host;
- in future supported execution environments.

Runtime location SHALL NOT affect protocol behavior.

From the Hypervisor perspective, every Runtime behaves identically.

## 4. Runtime Registration

Every Runtime registers itself with the Hypervisor.

Registration includes:

- Runtime Identifier;
- Capability Identifier;
- Runtime Version;
- Protocol Version;
- Supported Features;
- Health Status.

Registration SHALL complete before the Runtime accepts Sessions.

Runtime discovery MAY occur through:

- automatic local discovery;
- operator configuration;
- service registration;
- future discovery mechanisms.

Registration semantics SHALL remain identical regardless of Runtime location.

## 5. Capability Identity

Every Runtime implements exactly one Capability.

Examples:

- `llm.chat`
- `llm.embedding`
- `speech.stt`
- `speech.tts`
- `image.generate`
- `image.upscale`
- `video.generate`
- `protein.fold`

Capability identifiers are immutable.

## 6. Runtime Lifecycle

Every Runtime follows the same lifecycle.

```text
Start
    ↓
Initialize
    ↓
Register
    ↓
Discover Providers
    ↓
Publish Endpoints
    ↓
Accept Sessions
    ↓
Execute Requests
    ↓
Report Health
    ↓
Shutdown
```

The Runtime MAY restart independently of the Hypervisor.

The Hypervisor SHALL recover Runtime connectivity automatically.

## 7. Provider Management

Provider discovery and management are entirely the responsibility of the
Runtime-facing plugin or adapter layer behind the Runtime.

Examples:

For Capability `llm.chat`:

- `llama.cpp`
- `Ollama`
- `vLLM`
- `TensorRT-LLM`
- `MLX`

The Hypervisor SHALL remain unaware of Provider-specific implementation details.

The Hypervisor MAY still manage local Hypervisor-owned objects such as:

- Provider Plugin installation;
- Provider Instance attachment;
- Model Deployment lifecycle;
- Runtime Binding lifecycle.

Those control-plane concerns do not give the Hypervisor direct Provider-native
execution semantics.

## 8. Endpoint Management

The Runtime is responsible for:

- discovering available Providers;
- creating Endpoint definitions;
- updating Runtime execution metadata;
- updating local Endpoint execution readiness and availability state.

The Hypervisor publishes Endpoint advertisements to the Marketplace, including the commercial terms selected by the Endpoint operator.

The Runtime remains the authoritative owner of execution metadata exposed through those advertisements, but SHALL NOT directly publish Marketplace price identity.

Public Endpoint publication and withdrawal remain Hypervisor-controlled lifecycle actions.

## 9. Session Handling

The Hypervisor routes Sessions using the Capability Identifier.

The Runtime is responsible for:

- opening execution contexts;
- queue management;
- execution scheduling;
- resource allocation;
- request execution;
- Session completion.

The Hypervisor SHALL NOT interpret Capability-specific requests.

## 10. Usage Accounting

Every Runtime performs deterministic Usage Accounting where the Capability and underlying Provider permit deterministic measurement.

Examples include:

- input tokens;
- output tokens;
- generated images;
- processed audio duration;
- processed video duration;
- execution statistics.

Where exact deterministic accounting is not possible, the Runtime SHALL declare the applicable Accounting Mode according to `RFC-0051`.

The Runtime SHALL NOT represent estimated or unavailable usage as deterministic measured usage.

## 11. Usage Verification

Every Runtime SHALL expose sufficient accounting metadata for independent verification where such verification is supported.

Verification procedures are Capability-specific.

Independent verification is desirable but is not mandatory for every Capability, Provider or Proxy Endpoint.

Where exact verification is unavailable, the Runtime SHALL disclose:

- the Accounting Mode;
- the measurement source;
- unavailable usage fields;
- observable billable units;
- non-authoritative estimates.

Confirmed Verification failures SHALL terminate the Session according to the Session Protocol.

## 12. Validation Support

Every Runtime SHALL expose benchmark and Validation execution support appropriate to its Capability.

Validation MAY include:

- representative execution requests;
- protocol compliance checks;
- output observations;
- usage reporting checks;
- Capability-specific measurements.

Validation SHALL NOT require Runtime modification.

Validation does not prove the hidden identity of a model or Provider.

It records observable Runtime and Endpoint behavior.

## 13. Health Reporting

Every Runtime periodically publishes operational metrics.

Examples include:

- availability;
- latency;
- throughput;
- queue depth;
- execution failures;
- resource utilization;
- Provider availability;
- accounting availability;
- recovery state.

Health Reports contribute to the Reputation Profile only through protocol-defined and verifiable processing.

Local diagnostic metrics SHALL NOT directly alter Ledger Reputation.

## 14. Configuration

Every Runtime owns its complete Capability-specific configuration.

Configuration MAY include:

- execution limits;
- pricing defaults;
- Provider configuration;
- Runtime parameters;
- scheduling policies;
- accounting capabilities;
- Proxy configuration;
- model or backend discovery.

The Hypervisor SHALL treat Runtime-specific configuration as opaque.

The Hypervisor MAY manage references to configuration without interpreting Capability-specific fields.

## 15. Versioning

Every Runtime advertises:

- Runtime Version;
- Capability Version;
- Runtime Protocol Version;
- supported Accounting Contract versions;
- supported optional features.

The Hypervisor SHALL reject incompatible Runtime Protocol versions.

Active Sessions SHALL remain bound to the versions negotiated at Session creation.

A Runtime upgrade SHALL NOT silently reinterpret existing Session accounting or behavior.

## 16. Runtime Isolation

Capability Runtime failures SHALL remain isolated.

The Hypervisor SHALL tolerate:

- Runtime restart;
- Runtime upgrade;
- Runtime relocation;
- Runtime replacement;
- temporary Runtime unavailability;
- Provider failure inside the Runtime.

Isolation is a protocol requirement rather than a specific deployment requirement.

The Hypervisor SHALL communicate exclusively through the Runtime Protocol.

A Runtime failure SHALL NOT directly terminate the Hypervisor.

## 17. Runtime Protocol

The Runtime Protocol SHALL remain transport-independent.

Possible transports include:

- Unix Domain Socket;
- TCP;
- QUIC;
- HTTP/2;
- gRPC;
- WebSocket;
- stdio;
- Named Pipes;
- shared memory with a control channel.

Future transport mechanisms MAY be introduced.

Transport SHALL NOT alter protocol semantics.

The detailed Runtime message protocol is defined by `RFC-0054`.

## 18. Runtime Discovery

The Hypervisor discovers Runtime Services through Runtime Registration.

Every Runtime advertises:

- Runtime Identifier;
- Capability Identifier;
- Runtime Version;
- Protocol Version;
- Health Status;
- Supported Features;
- supported Accounting Modes;
- available Runtime Endpoints.

The Hypervisor SHALL NOT assume Runtime locality.

Discovery SHALL behave identically regardless of deployment topology.

Discovery does not imply authorization.

## 19. Runtime Authorization

A discovered Runtime SHALL be explicitly authorized before use.

Authorization MAY occur through:

- operator approval;
- configured Runtime public key;
- local trust policy;
- registration token;
- certificate enrollment;
- future service authorization mechanisms.

An unauthorized Runtime SHALL NOT:

- publish Endpoints;
- receive Session data;
- report billable usage;
- execute Validation tasks;
- influence Hypervisor state.

## 20. Runtime Identity

Every Runtime SHALL have a unique cryptographic identity.

Runtime Identity is separate from:

- Wallet Identity;
- Hypervisor Node Identity;
- Service Identity;
- Endpoint Identity;
- Provider credentials.

Runtime messages affecting:

- registration;
- Endpoint metadata;
- Usage Reports;
- recovery state;
- benchmark results;

SHALL be authenticated according to `RFC-0054`.

## 21. Runtime Locality

A Runtime MAY be:

- on the same host as the Hypervisor;
- on another host in the same private network;
- inside a container or VM;
- remotely operated;
- shared by multiple authorized Hypervisors.

Runtime locality SHALL not change protocol behavior.

The Hypervisor MAY apply stricter security policy to remote Runtimes.

## 22. Runtime Ownership

Runtime ownership and Endpoint ownership are separate concepts.

A Runtime may be operated by one party while an Endpoint using that Runtime is published by another authorized Hypervisor operator.

The Endpoint operator remains responsible for:

- published pricing;
- Session Policy;
- Accounting Contract;
- result delivery;
- Usage Reporting;
- Consumer-facing protocol behavior.

The Runtime operator does not automatically become the economic counterparty of the Consumer.

## 23. Session Contract Binding

Before accepting a Session, the Runtime SHALL confirm support for:

- Capability Version;
- Endpoint Configuration Hash;
- referenced Accounting Contract;
- Session Policy;
- execution limits;
- required features;
- recovery requirements.

A Runtime SHALL reject Session preparation when it cannot satisfy the negotiated contract.

Commercial terms, including Marketplace price identity, belong to the accepted Advertisement or Offer selected by the Endpoint operator.

The Runtime executes under the accepted Session Contract and its referenced Accounting Contract.

The Hypervisor SHALL NOT accept an external Session before Runtime preparation succeeds.

## 24. Usage Reporting Responsibility

The Runtime SHALL generate Provider-side Usage Reports according to `RFC-0051` and the Accounting Contract bound to the accepted Session Contract.

The Runtime SHALL:

- declare Accounting Modes;
- identify measurement sources;
- preserve report sequencing;
- report unknown values as unknown;
- avoid billing non-authoritative estimates;
- support observable accounting where possible;
- preserve request-level accounting evidence.

Usage Reporting by the Runtime describes measured execution state and SHALL NOT be treated as publication of Marketplace pricing or commercial offer identity.

The Hypervisor SHALL:

- bind reports to Sessions;
- verify Runtime authorization;
- enforce Deposits and maximum charges;
- forward applicable reports;
- initiate Settlement.

## 25. Proxy Runtime Support

A Runtime MAY proxy an external or remote service.

Proxy Runtime behavior MAY include:

- `DIRECT_EXTERNAL_PROXY`;
- `AIDN_ENDPOINT_PROXY`;
- `AGGREGATING_PROXY`;
- `FAILOVER_PROXY`;
- `TRANSFORMING_PROXY`;
- `AGENT_PROXY`;
- `CHAINED_PROXY`.

When upstream usage is unavailable, the Runtime SHALL declare:

`PROXY_OPAQUE`

The Runtime SHALL NOT invent upstream token counts.

Proxy-Opaque billing SHALL use:

- fixed units;
- observable units;
- predefined request classes;
- active execution time where reliably measurable;
- other units accepted under `RFC-0051`.

Estimated tokens MAY be reported only as non-authoritative metadata.

The Endpoint operator remains the Consumer-facing protocol counterparty and remains responsible for:

- published pricing;
- result delivery;
- Usage Reporting;
- upstream failure handling;
- retry and failover behavior;
- data-handling disclosure;
- maximum-charge compliance.

## 26. Runtime Health Ownership

The Runtime is authoritative for its local operational condition.

The Hypervisor is authoritative for public Endpoint state.

A Runtime MAY report:

- available;
- degraded;
- unavailable;
- draining;
- recovering.

The Hypervisor decides whether to:

- continue routing Sessions;
- pause new Sessions;
- update Marketplace metadata;
- withdraw an Endpoint;
- begin Session recovery.

## 27. Failure Recovery

The Runtime SHALL support recovery reporting.

After reconnect or restart, the Runtime SHALL identify:

- recoverable Sessions;
- active request state;
- last Usage Report sequence;
- result hashes;
- Runtime restart identity;
- Session-context availability.

The Hypervisor remains authoritative for canonical Session state.

A Runtime SHALL NOT independently reopen or settle a Session.

## 28. Runtime Replacement

A Hypervisor MAY replace one Runtime with another compatible Runtime.

Replacement requires:

- matching Capability Version;
- support for the accepted Accounting Contract;
- compatible Session state;
- valid context transfer or reconstruction;
- no conflicting Usage history;
- policy permission.

Runtime replacement SHALL NOT:

- reset usage;
- change pricing;
- erase accepted checkpoints;
- alter Endpoint identity;
- silently change observable Session semantics.

## 29. Session Context

A Runtime MAY maintain Capability-specific Session context.

Examples include:

- conversation state;
- cached model context;
- Provider session reference;
- workspace state;
- generated artifacts;
- request history;
- tool state.

Context MAY be:

- Runtime-local;
- exportable;
- encrypted;
- non-portable.

The Runtime SHALL declare whether Session recovery and migration are supported.

## 30. Runtime Pools

Multiple compatible Runtimes MAY implement the same Capability.

The Hypervisor MAY use Runtime Pools for:

- load distribution;
- failover;
- maintenance;
- Provider diversity;
- geographic placement.

Runtime Pools SHALL preserve:

- Endpoint semantics;
- Accounting Contract;
- Capability Version;
- Session affinity where required.

A remote Consumer need not know which internal Runtime handled a request unless the published contract requires disclosure.

## 31. Provider Abstraction

Providers remain private implementation details of the Runtime.

Examples include:

- `llama.cpp`;
- `Ollama`;
- `vLLM`;
- `TensorRT-LLM`;
- `MLX`;
- remote proprietary APIs;
- OAuth-connected agents;
- local media processors.

The Hypervisor SHALL NOT contain Provider-specific execution logic.

The Runtime MAY change Provider only when the resulting Endpoint Configuration remains compatible or is explicitly updated.

## 32. Provider Changes

Execution-relevant Provider changes SHALL cause the Runtime to notify the Hypervisor.

Examples include:

- model change;
- tokenizer change;
- upstream service change;
- accounting change;
- Capability behavior change;
- Provider version change affecting output;
- proxy mode change.

The Hypervisor SHALL determine whether the Endpoint requires:

- configuration update;
- Certification invalidation;
- Marketplace update;
- Session pause;
- new Validation.

## 33. Endpoint Authority

The Runtime proposes and maintains Runtime Endpoint metadata.

The Hypervisor controls the public AiDN Endpoint object.

The Runtime SHALL NOT directly:

- publish to the Ledger;
- publish to the Marketplace;
- change Endpoint ownership;
- change pricing visible to Consumers;
- change access policy;
- withdraw a public Endpoint.

Such actions require Hypervisor processing and applicable Ledger Operations.

## 34. Validation Behavior

The Runtime SHALL support Capability-appropriate Validation execution.

A Runtime MAY provide:

- benchmark execution;
- request execution;
- artifact measurement;
- usage reporting;
- protocol observations;
- health information.

The Runtime SHALL NOT determine final Certification.

Certification is derived from finalized Validation Reports and protocol rules.

## 35. Security Boundary

A compromised Runtime SHALL NOT be able to:

- access Wallet private keys;
- authorize Wallet transfers;
- mint Q;
- unlock Deposits;
- alter Ledger state;
- finalize Settlement;
- create Protocol Rewards;
- impersonate a Hypervisor;
- change unrelated Endpoints;
- access unauthorized Sessions.

The Hypervisor SHALL validate all economically significant Runtime claims.

## 36. Secret Isolation

Provider secrets belong to the Runtime environment.

Examples include:

- API keys;
- OAuth tokens;
- refresh tokens;
- model repository credentials;
- upstream service credentials.

Secrets SHOULD remain inaccessible to:

- remote Consumers;
- unrelated Runtimes;
- Marketplace;
- Registry;
- Ledger;
- Hypervisor components that do not require them.

Runtime logs SHALL not expose secrets.

## 37. Multi-Tenancy

A Runtime MAY serve multiple:

- Sessions;
- Endpoints;
- Hypervisors;
- operators.

Multi-tenant Runtimes SHALL isolate:

- Session content;
- Endpoint configuration;
- Provider credentials;
- Usage Reports;
- artifacts;
- resource limits;
- recovery data.

One tenant SHALL not access another tenant's data.

## 38. Extensibility

Future computational domains require only a new Runtime implementation conforming to this specification and `RFC-0054`.

Examples may include:

- `robotics.control`;
- `cad.simulation`;
- `weather.forecast`;
- `molecular.simulation`;
- `quantum.compute`;
- `distributed agent execution`.

The Hypervisor SHALL require no architectural modification.

This requirement is fundamental to AiDN.

## 39. Conformance

Every Runtime implementation SHALL pass conformance tests covering:

- identity;
- authorization;
- registration;
- Capability metadata;
- Endpoint lifecycle;
- Session preparation;
- request execution;
- Usage Reporting;
- streaming where supported;
- cancellation;
- recovery;
- health;
- shutdown;
- malformed input;
- incompatible versions;
- security boundaries.

Capability-specific tests MAY extend the core suite.

## 40. Reference Runtime

The AiDN project SHOULD provide a minimal Reference Runtime.

The Reference Runtime SHOULD implement:

- one deterministic sample Capability;
- fixed-price accounting;
- observable usage;
- request streaming;
- failure simulation;
- Session recovery;
- Runtime replacement testing;
- benchmark execution.

The Reference Runtime provides a stable integration target for Hypervisor development.

## 41. Runtime Packaging

Runtime distribution format is outside the core scope of this document.

A future specification MAY define:

- Runtime manifest;
- executable or container reference;
- signatures;
- Capability schema;
- configuration schema;
- icons and descriptive metadata;
- benchmark definitions;
- compatibility information;
- update channel.

The Hypervisor SHALL not require one packaging technology.

## 42. Lifecycle Summary

The complete Runtime lifecycle is:

```text
Discover
    ↓
Authorize
    ↓
Connect
    ↓
Authenticate
    ↓
Negotiate Version
    ↓
Register
    ↓
Synchronize
    ↓
Ready
    ↓
Publish Runtime Endpoints
    ↓
Prepare Sessions
    ↓
Execute Requests
    ↓
Report Usage and Health
    ↓
Recover or Replace When Required
    ↓
Drain
    ↓
Shutdown
```

## 43. Open Questions

The following MAY require later dedicated specifications:

- Runtime package format;
- remote Runtime discovery;
- confidential-computing attestation;
- shared Runtime economics;
- Runtime marketplace;
- multi-Runtime collaborative execution;
- secure Session-context migration;
- Runtime ownership transfer;
- cross-operator Runtime authorization;
- distributed Runtime scheduling.

## 44. Design Invariants

- Every Capability is implemented by an independent Runtime Service.
- Every Runtime implements exactly one Capability.
- Runtime deployment is transparent to the Hypervisor.
- Discovery does not imply authorization.
- Runtime Identity is separate from Wallet and Hypervisor Identity.
- Providers remain Runtime implementation details.
- The Hypervisor never contains Capability-specific execution logic.
- The Runtime never directly modifies Ledger state.
- Runtime failures remain isolated.
- Runtime replacement never resets Session accounting.
- Runtime upgrades never silently change active Session contracts.
- Unknown upstream usage remains unknown.
- Proxy-Opaque estimates are not authoritative billing data.
- Public Endpoint state remains controlled by the Hypervisor.
- New Capabilities require no Hypervisor architectural changes.
- Detailed message semantics are defined by `RFC-0054`.
