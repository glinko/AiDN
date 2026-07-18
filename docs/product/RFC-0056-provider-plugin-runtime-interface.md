# RFC-0056

AiDN Provider Plugin Runtime Interface

Status: Draft

Version: 0.3

Revision note: defines the authenticated Plugin Host interface as application
profiles over RFC-0042 `PLUGIN_CONTROL`, introduces installation generation and
persistent management operations, and keeps Runtime Adapter execution under
RFC-0054.

Supersedes:

* RFC-0056 Version 0.2

Depends on:

* RFC-0039 Hypervisor Service Model
* RFC-0040 AiDN Service Verification Framework
* RFC-0042 AiDN Hypervisor Network Protocol and Dispatcher Architecture
* RFC-0051 Usage Reporting and Verification Protocol
* RFC-0053 Capability Runtime Specification
* RFC-0054 Capability Runtime Protocol
* RFC-0055 Provider Plugin System and Directory
* RFC-0060 Session Failure, Recovery and Forced Settlement

Related specifications include RFC-0044, RFC-0046, RFC-0049, RFC-0059,
RFC-0063 and RFC-0066. They do not define the local Plugin Host wire contract.

---

## 1. Purpose

This document defines how a Hypervisor communicates with one installed Provider
Plugin to:

* authenticate and negotiate a local Plugin connection;
* discover supported management operations;
* validate Provider and model configuration;
* run persistent, idempotent management operations;
* attach or manage Provider Instances;
* discover and manage Model Deployments;
* propose Runtime Bindings;
* register a Runtime Adapter through RFC-0054;
* expose Health, diagnostics, progress and recovery state;
* use scoped secrets, files, resources and network egress.

---

## 2. Core Boundary

RFC-0056 is the Provider management and integration interface.

RFC-0054 is the user-workload execution protocol.

```text
Hypervisor Plugin Manager
    -> PLUGIN_CONTROL
Plugin Host / Plugin Manager
    -> provider-native management API

Hypervisor Runtime Manager
    -> RUNTIME
Runtime Adapter
    -> provider-native execution API
```

RFC-0056 SHALL NOT create a second Session or Request execution protocol.

---

## 3. Interface Planes

The interface contains four logical planes:

* Plugin Control Plane;
* Provider Management Plane;
* Model Management Plane;
* Runtime Adapter Registration Plane.

Execution after Runtime Adapter registration uses RFC-0054 only.

---

## 4. Actors and Authority

The Hypervisor Plugin Manager owns:

* Installed Plugin lifecycle;
* local authorization and permissions;
* identifier allocation;
* operation admission and persistence;
* Plugin Host lifecycle;
* Dispatcher and Runtime Manager coordination.

The Plugin Host owns process isolation, Local IPC, resource limits, crash
detection, log capture and delivery of scoped credentials.

The Provider Plugin owns provider-specific translation and observations. It is
not authoritative for Hypervisor permissions, public Endpoint state, Wallet
state, Dispatcher routes or Runtime identities.

---

## 5. Installed Plugin Identity

Every installed Plugin has a local package-bound identity:

```yaml
installed_plugin_identity:
  installed_plugin_id:
  release_id:
  plugin_id:
  plugin_version:
  package_digest:
  target_hypervisor_id:
  granted_permission_hash:
  installation_generation:
```

`package_digest` SHALL resolve from the referenced immutable Plugin Release.
The downloaded package bytes SHALL match that digest before activation.

The granted permission commitment is:

```text
GrantedPermissionHash =
HASH(CanonicalSortedUniqueGrantedPermissionIDs)
```

Permission IDs are non-empty strings serialized as a deterministic array. The
hash SHALL change whenever the effective granted permission set changes.

---

## 6. Installation Generation

`installation_generation` is a Hypervisor-controlled positive integer.

It SHALL increment after:

* reinstall or package replacement;
* incompatible local-state migration;
* replacement of the Plugin Host identity credential;
* permission change requiring active Plugin reauthorization.

An older process generation SHALL NOT reconnect as the current installation.

Installation Generation is distinct from Dispatcher Route Generation.

---

## 7. Local Authentication Credentials

Publisher keys sign Plugin Releases. Publisher private keys SHALL NOT be
available to installed Plugin code and SHALL NOT authenticate Plugin sessions.

Before process launch, the Plugin Host SHALL provision an installation-specific
credential such as:

* an ephemeral local key pair;
* a short-lived local certificate;
* a one-time launch token bound to authenticated OS peer credentials.

The credential SHALL bind `installed_plugin_id`, Package Digest, Installation
Generation and target Hypervisor. Hypervisor responses SHALL use a separate
local control-plane credential, not Wallet, Consensus or Governance keys.

---

## 8. Local Transport

Authenticated Local IPC is the preferred transport.

Allowed implementations include Unix Domain Sockets, Windows Named Pipes,
loopback mTLS or another bounded local transport. Local IPC SHALL authenticate
the process boundary even when transport encryption is omitted under RFC-0042.

A Plugin SHALL NOT directly access Hypervisor databases or the Dispatcher Route
Table.

---

## 9. Plugin Handshake

The connection state machine is:

```text
CONNECTING
-> HELLO_EXCHANGING
-> IDENTITY_VERIFYING
-> VERSION_NEGOTIATING
-> PERMISSION_VERIFYING
-> STATE_RECONCILING
-> READY
```

Alternative states are `REJECTED`, `DEGRADED`, `QUARANTINED`, `RECOVERING` and
`CLOSED`.

The Plugin Hello payload includes:

```yaml
plugin_hello:
  installed_plugin_id:
  release_id:
  plugin_id:
  plugin_version:
  package_digest:
  installation_generation:
  process_nonce:
  supported_api_versions:
  required_features:
  optional_features:
  local_state_version:
  last_control_sequence:
  launch_credential_proof:
```

The Hypervisor Hello payload includes:

```yaml
hypervisor_plugin_hello:
  installed_plugin_id:
  selected_api_version:
  granted_permission_hash:
  installation_generation:
  plugin_control_route_generation:
  active_network_revision:
  active_runtime_protocol_versions:
  plugin_session_id:
  session_expiration:
  hypervisor_credential_proof:
```

The connection becomes READY only after identity, package, generation, API,
permission and local-state checks succeed.

---

## 10. Plugin API Negotiation

The interface version uses `MAJOR.MINOR`.

A Major change is wire-incompatible. A Minor change may add optional methods,
fields, Health dimensions or operation types.

The highest mutually supported version satisfying all required security
features SHALL be selected. A downgrade that removes required permission,
secret, authentication or Dispatcher behavior is prohibited.

---

## 11. Plugin Session Identity

Every READY connection receives a short-lived Plugin Session Identity:

```yaml
plugin_session_identity:
  plugin_session_id:
  installed_plugin_id:
  installation_generation:
  process_nonce:
  api_version:
  granted_permission_hash:
  plugin_control_route_generation:
  expires_at:
```

It authorizes only owned Provider Instances, Model Deployments, management
operations and explicitly granted permissions. It does not authorize Runtime
execution or unrelated protocol traffic.

---

## 12. RFC-0042 Message Profile

Plugin messages are application payloads inside the RFC-0042 common
`network_message` envelope on `PLUGIN_CONTROL`.

RFC-0056 SHALL NOT define a second independent Message ID, authentication,
expiration, hash, sequencing or replay layer. The following map directly to the
RFC-0042 envelope:

* Message ID;
* correlation and causation IDs;
* source sequence;
* created-at and expiration;
* payload hash, length and encoding;
* source and destination authentication;
* Route Generation.

Plugin payloads add only Plugin API fields such as `plugin_session_id`,
operation type and object scope.

---

## 13. Dispatcher Scope

The Plugin control destination is `installed_plugin_id`. Each operation also
declares its Provider Instance, Model Deployment or Runtime scope.

The Dispatcher and Hypervisor authorization layer SHALL verify:

* current Installation Generation;
* current Plugin Session Identity;
* message type and permission;
* owned object scope;
* current Plugin Control Route Generation;
* expiration and replay state.

A Provider Plugin cannot create or mutate routes. Route Generation is returned
as an observation and authorization boundary controlled by the Dispatcher.

---

## 14. Capability Discovery

After handshake the Hypervisor requests `GetPluginCapabilities`.

The response identifies supported management operations, deployment modes,
Provider families and versions, model operations, AiDN Capabilities, Health and
Usage dimensions, Runtime Protocol versions and Adapter profiles.

Operation support SHALL be explicit. Provider family alone does not imply
support.

---

## 15. Persistent Plugin Operations

Long-running management actions use a persistent Plugin Operation record:

```yaml
plugin_operation:
  operation_id:
  installed_plugin_id:
  operation_type:
  provider_instance_id:
  model_deployment_id:
  runtime_id:
  idempotency_key:
  approved_plan_hash:
  parameters_hash:
  state:
  current_stage:
  progress:
  cancellability:
  recovery_class:
  result_reference:
  error:
  created_at:
  updated_at:
  completed_at:
```

Initial states are `QUEUED`, `RUNNING`, `PAUSED`, `VERIFYING`, `COMPLETED`,
`CANCEL_REQUESTED`, `CANCELLED`, `FAILED`, `ROLLING_BACK` and `ROLLED_BACK`.

Repeating an operation with the same object scope, idempotency key, plan hash
and parameters hash SHALL return the existing operation or terminal result.

---

## 16. Progress and Cancellation

Progress authority is one of `DETERMINISTIC`, `MEASURED`, `ESTIMATED` or
`UNKNOWN`.

Each operation declares `CANCELLABLE`, `CHECKPOINT_CANCELLABLE` or
`NON_CANCELLABLE`.

Cancellation results are `CANCELLATION_ACCEPTED`, `CANCELLATION_PENDING`,
`CANCELLATION_TOO_LATE`, `CANCELLATION_UNSUPPORTED` or
`OPERATION_ALREADY_TERMINAL`.

Progress, logs and diagnostics use bounded Dispatcher queues and SHALL NOT
starve Runtime cancellation or Usage Reports.

---

## 17. Exact Plan Approval

Configuration validation and plan generation are side-effect bounded.

Material normalized configuration changes SHALL be shown before approval. A
Plugin SHALL NOT silently expand public exposure, storage scope, GPU allocation,
system-package changes or network egress.

Apply requires the exact approved:

* Plan Hash;
* Configuration Hash;
* Package identity;
* sandbox policy;
* permission set;
* selected Secret Handles.

The current plan SHALL be rejected when it differs from the approved plan.

---

## 18. Provider Management

Supported operations MAY include:

* `ValidateProviderConfiguration`;
* `TestProviderConnection`;
* `RunProviderPreflight`;
* `BuildProviderInstallationPlan`;
* `AttachProvider`;
* `CreateProvider`;
* `StartProvider`, `StopProvider`, `RestartProvider` and `DrainProvider`;
* `UpdateProvider` and `RemoveProvider`;
* `GetProviderState` and `GetProviderHealth`.

The Hypervisor allocates `provider_instance_id` before attach or creation. The
Plugin returns observations and resulting configuration; it SHALL NOT mint a
new Provider Instance identity.

Removal SHALL enumerate dependent models, Runtime Bindings, Endpoints, active
Sessions, secrets and shared resources before admission.

---

## 19. Model Management

Supported operations MAY include discovery, configuration validation,
installation-plan generation, install, import, registration, load, unload,
start, stop, update, removal, state and Health.

The Hypervisor allocates `model_deployment_id`. Provider-native model identifiers
remain separate and retain provenance.

Model files SHOULD use the shared content-addressed Model Artifact Store defined
by RFC-0055. A Plugin SHALL not delete shared assets still referenced by another
Provider Instance or Model Deployment.

---

## 20. Runtime Binding Proposal

A Plugin may submit `BuildRuntimeBindingProposal` containing Provider Instance,
Model Deployment, Capability, Adapter, Usage, feature, resource and required
route-scope claims.

The Hypervisor independently verifies the Capability Definition, model
readiness, Adapter compatibility, Runtime Protocol version, accounting behavior,
resources, secret scope and Dispatcher authorization.

The Hypervisor Runtime Manager creates or approves Runtime ID. Plugin code SHALL
NOT assign arbitrary Runtime IDs.

---

## 21. Runtime Adapter Registration

After approval, the Runtime Adapter registers as an RFC-0054 Runtime Identity.
The registration is linked to:

* `installed_plugin_id`;
* Provider Instance ID;
* Model Deployment ID;
* Adapter ID and version;
* one Capability Definition;
* Runtime configuration hash.

The Adapter receives an RFC-0054 `RUNTIME` route scoped to its Runtime ID and
assigned Sessions. It does not reuse Plugin Session Identity for execution.

Runtime execution, streaming, cancellation, Usage Reports and Request recovery
then use RFC-0054 only.

---

## 22. Manager and Adapter Separation

A Plugin Manager and Runtime Adapter MAY be separate processes.

A Manager crash SHALL NOT terminate active Sessions when the Provider, Adapter,
Runtime route and required state remain healthy. Manager Health and Adapter
Health SHALL be reported independently.

An Adapter replacement that materially changes behavior requires a new Runtime
authorization and Dispatcher Route Generation transition. Existing Sessions may
move only through explicit RFC-0054 and RFC-0060 recovery rules.

---

## 23. Usage Reporting Capability

Each Usage dimension declares availability, unit, cumulative behavior, billing
suitability and one authority class:

* `AUTHORITATIVE_PROVIDER`;
* `DETERMINISTIC_LOCAL`;
* `OBSERVABLE_LOCAL`;
* `ESTIMATED`;
* `UNAVAILABLE`.

Unavailable values remain unavailable. Estimated values SHALL NOT become exact
billable usage merely because a local tokenizer can produce a number.

---

## 24. Health

Health is separated into:

* Plugin Host Health;
* Plugin Manager Health;
* Provider Instance Health;
* Model Deployment Health;
* Runtime Adapter Health;
* execution-path Health.

Health observations include sequence, observation time and validity boundary.
Expired Health becomes `UNKNOWN`.

---

## 25. Secrets, Files and Resources

Secret access is scoped to one Installed Plugin, Provider Instance, allowed
usage and expiration. Plugins SHOULD receive a Secret Handle or brokered
credential operation instead of persistent global plaintext.

File access SHALL use selected object references or scoped directories. Large
objects SHOULD use content-addressed local references or bounded streams.

The Hypervisor Resource Manager remains authoritative for CPU, memory, GPU,
storage, ports and network allocations. Provider-native visibility does not
grant ownership of a resource.

---

## 26. Recovery and Reconciliation

After restart, the Plugin and Hypervisor reconcile:

* Installation Generation and permission hash;
* Provider Instances;
* Model Deployments;
* Runtime Bindings and Adapter ownership;
* active Plugin Operations;
* last control sequences;
* externally continuing operations.

The Hypervisor is authoritative for identities, permissions, ownership, public
Endpoint bindings and routes. The Plugin may be authoritative only for current
provider-native observations.

Conflicts are classified as `HYPERVISOR_ONLY`, `PLUGIN_ONLY`,
`CONFIGURATION_MISMATCH`, `STATE_MISMATCH`, `GENERATION_MISMATCH` or
`OWNERSHIP_MISMATCH`.

An unknown discovered Provider becomes `ORPHANED_PROVIDER`; it receives no
Runtime or Endpoint binding automatically.

---

## 27. Updates and Security Blocking

Update evaluation SHALL report API, Provider, model-state and Adapter
compatibility; permission changes; migration requirements; Route Generation
impact; rollback availability; warnings and blockers.

Permission expansion requires local approval and a new active authorization
generation. Material Adapter changes require route transition and Session drain
or recovery.

Security policy MAY disable management, stop new Provider creation, block new
Runtime Bindings, drain routes, revoke secrets or stop managed Providers. It
SHALL prefer reversible containment over automatic data deletion.

---

## 28. Stable Errors

The MVP error namespace SHALL cover:

* handshake, identity, generation and API mismatch;
* malformed, replayed and out-of-sequence messages;
* permission and route-scope violations;
* operation unsupported, duplicate, missing, failed or not cancellable;
* Provider configuration, connection, authentication and dependency failures;
* model discovery, license, hash, resource and dependency failures;
* Runtime registration, protocol, route and recovery failures;
* secret, filesystem, network, port and GPU denial;
* state migration, reconciliation, quarantine and crash loops.

Provider-native errors SHALL be sanitized. Raw credentials, internal paths,
private Session payloads and unrelated topology SHALL not appear in errors.

---

## 29. Conformance

Plugin conformance tests SHALL cover handshake, version negotiation,
capabilities, permissions, plan generation, operation idempotency, cancellation,
Provider attachment, Health, model discovery, secret isolation, Dispatcher
scope, restart reconciliation and stable errors.

Runtime Adapters separately pass applicable RFC-0054 tests for registration,
Request validation, streaming, cancellation, Usage Reporting, replay, artifacts,
failure mapping and recovery.

Conformance proves interface compatibility, not absence of malicious code or
upstream vulnerabilities.

---

## 30. Staged MVP

The normative implementation sequence is:

### Stage A - Package and Local Identity

* verified content-addressed Plugin Package Store;
* Plugin Release and Installed Plugin identity;
* Installation Generation and permission hash;
* no third-party package execution yet.

### Stage B - Control Protocol Foundation

* external Plugin Host;
* authenticated Local IPC handshake;
* API negotiation and Plugin Session Identity;
* RFC-0042 `PLUGIN_CONTROL` profiles;
* capability discovery, bounded logs and Health;
* persistent Plugin Operation journal.

### Stage C - Attach Existing

* configuration validation and connection testing;
* scoped secrets and egress;
* Provider attachment, model discovery and Health;
* no host-mutating Provider installation required.

### Stage D - Runtime Adapter

* Runtime Binding proposal;
* Hypervisor-owned Runtime identity;
* RFC-0054 Adapter registration and conformance;
* Request, cancellation, Usage and recovery integration.

### Stage E - Managed Lifecycle

* managed container installation;
* model installation and import;
* operation cancellation and rollback;
* update, reconciliation, removal and security containment.

Native installers, arbitrary Plugin UI, remote Deployment Agents, live Runtime
migration and Plugin-to-Plugin RPC remain deferred.

---

## 31. Compatibility

Built-in in-process adapters MAY remain as an explicit compatibility layer
during migration. They SHALL NOT claim Plugin Host handshake, sandbox or Local
IPC conformance.

Recorded and controlled-filesystem executors remain valid bounded MVP
executors. The existence of an approved plan does not authorize arbitrary shell,
container, package-manager or network execution.

---

## 32. Identity Invariants

* Publisher identity is not Installed Plugin process identity.
* Plugin ID is not Installed Plugin ID.
* Installation Generation is not Route Generation.
* Provider Instance ID is Hypervisor-controlled.
* Model Deployment ID is distinct from provider-native model ID.
* Runtime ID is Hypervisor-approved.
* Plugin Session Identity does not authorize Runtime execution.

---

## 33. Management Invariants

* Unsupported operations are explicit.
* Material actions bind to exact approved hashes.
* Long operations are persistent and idempotent.
* Progress authority and cancellation behavior are declared.
* Shared resources are not silently deleted.
* Hypervisor policy remains authoritative after restart.

---

## 34. Runtime Invariants

* Runtime execution uses RFC-0054.
* Adapter routes are scoped to one Runtime and assigned Sessions.
* Request, Session, deadline and charge-ceiling identity is preserved.
* Usage authority is explicit and unknown usage remains unknown.
* Internal retries remain bounded, safe and visible.
* Active Sessions do not move across incompatible Adapters silently.

---

## 35. Security Invariants

* Downloaded package bytes match the active Plugin Release digest.
* Installed processes use installation-specific credentials.
* Every Plugin call is permission and object-scope checked.
* Plugins cannot mutate Dispatcher routes or assign arbitrary Runtime IDs.
* Secrets, files, egress and resources remain scoped.
* Logs are bounded and redacted.
* Plugin crashes do not crash the Hypervisor control plane.
* Security blocking can contain code without deleting operator data.
* Local operator policy is the final installation and permission authority.
