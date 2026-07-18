# RFC-0055

Provider Plugin System and Directory

Status: Draft

Version: 0.20

Revision note: binds Installed Plugin activation to Installation Generation and
an installation-specific local identity. Detailed control-plane RPC, operations
and Runtime Adapter registration are delegated to RFC-0056.

Supersedes:

* RFC-0055 Version 0.19

Depends on:

* RFC-0039 Hypervisor Service Model
* RFC-0040 AiDN Service Verification Framework
* RFC-0042 AiDN Hypervisor Network Protocol and Dispatcher Architecture
* RFC-0044 AiDN Session Protocol
* RFC-0045 AiDN Capability Architecture
* RFC-0046 AiDN Registry Architecture
* RFC-0049 Distributed Marketplace and Endpoint Advertisement Registry
* RFC-0053 Capability Runtime Specification
* RFC-0054 Capability Runtime Protocol
* RFC-0058 Participant Eligibility and Sybil Resistance
* RFC-0059 Ledger Operation Catalog
* RFC-0063 Proxy Endpoint Protocol
* RFC-0066 Protocol Upgrade and Emergency Recovery

---

## 1. Purpose

This document defines the AiDN Provider Plugin System and Directory.

It specifies:

* Provider Plugin identity and manifest structure;
* Provider Plugin Directory behavior;
* Provider Instance lifecycle;
* Model Deployment lifecycle;
* Runtime Binding prerequisites;
* attach-existing flow;
* managed-install flow;
* installation approval and apply boundaries;
* installation diagnostics and local artifact readiness reporting;
* controlled local artifact staging for managed install;
* controlled staged-archive extraction for managed install;
* shared Model Artifact Store promotion and provider materialization;
* rollback execution and rollback-result lifecycle for managed install jobs;
* Installation Recipes;
* plugin permissions, sandbox policy and trust status;
* declarative plugin UI schemas;
* plugin security and secret boundaries.

---

## 2. Core Principle

The Hypervisor SHALL understand one common Provider Plugin contract.

Provider-specific behavior belongs to installable plugins rather than to
hypervisor core code.

Conceptually:

```text
Plugin Directory
    ->
Provider Plugin
    ->
Provider Instance
    ->
Model Deployment
    ->
Runtime Binding
    ->
Endpoint Draft
    ->
Advertisement
```

---

## 3. Provider Plugin

A Provider Plugin is an installable Hypervisor extension for one Provider
family or API family.

It is not:

* a concrete Provider installation;
* a model deployment;
* a Runtime identity;
* an Endpoint offer.

One Provider Plugin MAY support several Provider Instances.

Detailed Plugin Host handshake, management operation, recovery and Runtime
Adapter registration semantics are defined by RFC-0056. This RFC defines
package, directory, permission and lifecycle policy rather than duplicating the
wire interface.

---

## 4. Provider Instance

A Provider Instance is one attached or managed installation reachable through
one Provider Plugin.

Examples include:

* local Ollama;
* remote vLLM;
* local `llama.cpp`;
* remote OpenAI-compatible API.

One Provider Instance MAY expose several Model Deployments.

---

## 5. Model Deployment

A Model Deployment is one concrete model or backend deployment reachable
through one Provider Instance.

It SHALL retain:

* provider-native model reference;
* operator display metadata;
* model metadata source annotations;
* capability candidates;
* context and modality information where known;
* usage-reporting capability summary.

A Model Deployment is not yet a published AiDN Endpoint.

---

## 6. Runtime Binding

A Runtime Binding is the AiDN-facing execution binding created from one Model
Deployment and one primary Capability contract.

Endpoint drafting and publication SHALL begin only after a Runtime Binding or
equivalent normalized execution surface exists.

---

## 7. Plugin Directory

A Provider Plugin Directory is a signed catalog of installable Provider
Plugins.

The Directory MAY expose:

* plugin description;
* publisher;
* source repository;
* license;
* package digest;
* supported platforms;
* supported accelerators;
* compatibility range;
* trust status;
* available Installation Recipes.

The Directory is not:

* protocol Reputation;
* Endpoint Certification;
* proof that the plugin is safe for every environment.

---

## 8. Installation Modes

The protocol recognizes two primary installation modes:

ATTACH_EXISTING
MANAGED_INSTALL

ATTACH_EXISTING binds a preexisting Provider into Hypervisor management.

MANAGED_INSTALL uses plugin-supplied plans or bounded installers to create a
Provider Instance under Hypervisor supervision.

One plugin MAY support both modes.

---

## 9. Plugin Manifest

Every Provider Plugin SHALL publish a manifest.

```yaml
provider_plugin_manifest:
  plugin_id:
  plugin_version:
  display_name:
  description:
  publisher:
  source_repository:
  license:
  hypervisor_api_compatibility:
  provider_families:
  supported_platforms:
  supported_architectures:
  supported_accelerators:
  plugin_capability_flags:
  required_permissions:
  sandbox_policy:
  secret_requirements:
  attach_ui_schema_hash:
  install_ui_schema_hash:
  model_ui_schema_hash:
  package_digest:
  publisher_public_key:
  publisher_signature:
  manifest_hash:
```

---

## 10. Capability Flags

Initial plugin capability flags include:

* CAN_ATTACH_EXISTING
* CAN_INSTALL_PROVIDER
* CAN_UPDATE_PROVIDER
* CAN_REMOVE_PROVIDER
* CAN_DISCOVER_MODELS
* CAN_INSTALL_MODELS
* CAN_IMPORT_MODELS
* CAN_REMOVE_MODELS
* CAN_START_STOP_MODELS
* CAN_STREAM
* CAN_CANCEL
* CAN_REPORT_USAGE
* CAN_REPORT_AUTHORITATIVE_TOKENS
* CAN_RECOVER_REQUESTS
* CAN_MANAGE_GPU
* CAN_MANAGE_CONTAINERS

The Hypervisor SHOULD use capability flags to shape the operator UI.

---

## 11. Declarative UI

Provider Plugins SHOULD provide declarative UI schemas rather than arbitrary
frontend code for:

* attach provider;
* install provider;
* add model;
* endpoint defaults;
* diagnostics.

The Hypervisor remains responsible for rendering the operator UI.

---

## 12. Permissions

A Provider Plugin SHALL declare requested permissions.

Examples include:

* container management;
* model-directory access;
* limited private-network access;
* GPU access;
* secret-handle access;
* remote deployment agent access.

Permission changes on plugin update SHALL require explicit operator approval.
When a plugin's requested permission set or sandbox policy differs from the
latest managed-install approval for that plugin, the Hypervisor SHALL require a
fresh explicit upgrade acknowledgement before diagnostics or approval can
proceed.

Provider Plugins SHALL also declare a sandbox policy for managed install.

The sandbox policy SHOULD identify at least:

* execution mode;
* filesystem scope;
* network scope;
* secret scope.

The Hypervisor SHALL treat sandbox policy as part of the managed-install trust
boundary rather than optional display metadata.

Managed-install compatibility SHALL also be evaluated against the sandbox
boundary declared by the active installation executor.

That executor boundary SHOULD identify at least:

* supported execution modes;
* supported filesystem scopes;
* supported network scopes;
* supported secret scopes;
* whether host mutation is enabled.

---

## 13. Secrets

Provider credentials SHALL be mediated by the Hypervisor secret manager.

Plugins SHOULD receive scoped secret references rather than unrestricted raw
secret storage access.

A plugin SHALL NOT:

* publish provider credentials;
* store them in Registry objects;
* emit them in logs;
* reuse them for another Provider Instance without authorization.

---

## 14. Installation Plans

Where practical, plugins SHOULD return declarative installation plans instead
of arbitrary host commands.

Example plan contents include:

* containers;
* volumes;
* networks;
* ports;
* model downloads;
* environment variables;
* resource limits;
* health checks.

The Hypervisor remains the authority that applies the plan.

An MVP sandbox-enforced executor MAY accept only a bounded declarative subset
within otherwise allowed plan sections.

Examples include:

* private-only network declarations with limited keys;
* read-only HTTP health checks without embedded credentials or query parameters;
* flat scalar resource-limit metadata.

Applying an Installation Plan SHALL require an explicit operator approval bound
to the exact:

* Plugin ID;
* Installation Plan hash;
* Provider configuration hash;
* permission set;
* verified package identity;
* sandbox policy;
* secret-reference set where applicable.

The Hypervisor SHOULD expose upgrade-review details to the operator, including:

* added permissions;
* removed permissions;
* package-identity change relative to the latest approval;
* sandbox-policy change relative to the latest approval;
* whether a fresh upgrade acknowledgement is required.

The Hypervisor MAY implement one or more non-host-mutating executors for MVP
operation. Such executors create local inventory and audit state but do not run
shell commands, container engines, package managers, downloads or plugin
installer code.

Host-mutating executors SHALL be treated as a higher-risk implementation layer
and require enforced sandbox policy, permission checks, secret scoping,
diagnostics and rollback policy.

An MVP Hypervisor MAY expose a sandbox-enforced non-host-mutating executor as
its default managed-install path while still persisting and validating sandbox
policy against executor capabilities as part of approval, diagnostics and
apply-state binding.

Managed-install jobs SHOULD expose rollback state separately from apply state.

Managed-install diagnostics SHOULD expose any required `local-import://`
artifacts before apply proceeds.

That readiness surface SHOULD identify at least:

* the controlled imports root;
* each required relative import path;
* the declared destination volume path;
* whether the artifact is already staged locally.

An implementation MAY also expose a bounded operator-facing staging surface
for those artifacts.

That staging surface SHOULD:

* accept only relative paths inside the controlled imports root;
* enforce explicit maximum artifact size;
* expose staged artifact metadata;
* avoid arbitrary host-path access;
* remain separate from shell, container, or package-manager execution.

An implementation MAY also expose bounded archive extraction inside the same
controlled imports root when operators need to prepare model files or
manifests before apply.

That archive-extraction surface SHOULD:

* accept only previously staged local archives;
* extract only into relative directories inside the controlled imports root;
* reject path traversal and absolute archive members;
* enforce explicit extracted file-count and total-size limits;
* expose which archive formats are accepted;
* remain separate from shell, container, or package-manager execution.

### 14.1 Shared Model Artifact Store

An implementation MAY promote a staged local file into a separate shared Model
Artifact Store. The staging area and Model Artifact Store SHALL remain distinct:
staging is temporary operator preparation state, while the store contains
immutable content-addressed bytes suitable for reuse by several Provider
Instances.

Each stored artifact SHALL bind at least:

* a content hash and stable artifact identifier;
* byte size;
* original filename and source reference;
* storage location relative to the controlled store root;
* verified integrity status.

Promotion SHALL recompute and verify the content hash before making bytes
available. Identical byte content MAY deduplicate to one artifact. Matching
model names alone SHALL NOT imply identity or deduplication.

A managed-install plan MAY reference immutable bytes with
`model-artifact://sha256:<digest>`. The executor SHALL materialize that source
only into the declared Provider volume path. Removing a staged source SHALL NOT
remove an already promoted artifact. Artifact lifecycle, reference accounting,
garbage collection, large resumable ingestion, and provider-specific caching
MAY be added by later versions.

An implementation MAY define an immutable Model Artifact Set to represent a
multi-file model package. A set SHALL contain an ordered, path-bound list of
artifact identifiers and file roles such as `WEIGHTS`, `TOKENIZER`, `CONFIG`,
`ADAPTER`, or `AUXILIARY`. Every member SHALL be verified before set creation.
An Artifact Set MAY be bound to one Model Deployment before Runtime Binding is
created. An implementation SHALL prevent removal of an artifact referenced by
a set, and prevent removal of a set referenced by a Model Deployment.

The Hypervisor SHOULD render Artifact Set composition through declarative local
controls that expose selected artifacts, relative target paths, and file roles.
It MAY materialize immutable artifact bytes by copy. A hardlink optimization
MAY be offered only as an explicit local policy and only for read-only store
payloads; the resulting execution evidence SHALL identify the actual method.

When an Artifact Set is materialized for a Provider Instance, the Hypervisor
SHALL retain a local Provider Artifact Materialization record binding the exact
Provider Instance, Artifact Set, controlled destination, member files, and
actual materialization method. This record is local operational evidence; it
does not replace Runtime Binding, Service Verification, or Endpoint
Certification. State restoration SHALL preserve the record, while the
underlying immutable Artifact Set remains the authoritative byte identity.

Implementations MAY perform explicit local garbage collection for unreferenced
artifacts. Collection SHALL use a configured grace period, SHALL re-evaluate
current set references before deletion, and SHALL be fail-closed when Artifact
Set metadata is unreadable. A collection pass SHOULD first record an
unreferenced timestamp; it SHALL NOT remove newly unreferenced bytes in that
same pass merely because a grace period is configured as zero for testing.

Rollback lifecycle SHOULD support at least:

* rollback preview during diagnostics;
* rollback execution after apply failure where the executor can provide it;
* explicit operator-triggered rollback for terminal install jobs;
* rollback step results and timestamps distinct from apply execution;
* local Provider Instance inventory cleanup where rollback succeeds or is not
  otherwise required.

An implementation MAY also provide a narrowly scoped host-mutating executor
that writes only controlled local installation state inside an explicitly
approved filesystem root. Such an executor does not by itself imply support
for shell execution, container lifecycle, package-manager actions, downloads,
or arbitrary plugin installer code.

Examples of allowed narrow host mutation MAY include:

* creating controlled provider-local volume directories;
* writing staged model-artifact manifests for later operator-reviewed fetch;
* importing local artifacts from a dedicated Hypervisor-controlled import area
  into declared provider volume paths;
* extracting staged local archives into that same controlled import area
  before apply;
* writing managed installation state needed for deterministic rollback.

---

## 15. Package Verification

Provider Plugin package identity SHALL be bound to at least:

* package digest;
* manifest hash;
* publisher identity claim;
* publisher signature where available.

The Hypervisor SHOULD verify package identity before accepting or applying a
managed-install approval.

Signed package verification MAY use a local trusted-publisher key set in MVP
implementations.

The Hypervisor SHALL:

* reject objectively invalid package identity evidence;
* surface unverified-but-not-invalid package state distinctly from verified
  package state;
* bind approval and apply to the exact acknowledged package identity;
* expose package-verification results in diagnostics and operator views.

Package verification remains distinct from plugin trust status.

---

## 15.1 Plugin Release

A Plugin Release is one immutable package identity. It SHALL bind:

* Plugin ID;
* Plugin Version;
* Manifest Hash;
* Package Digest;
* Publisher identity;
* declared permission set;
* release security state.

Changing any package-identity field creates a new Plugin Release. A security
state change MAY update the release record, but SHALL NOT replace its historical
package identity.

Initial release states are:

* AVAILABLE;
* DEPRECATED;
* SECURITY_WARNING;
* SECURITY_BLOCKED;
* REVOKED.

`SECURITY_BLOCKED` and `REVOKED` Releases SHALL NOT be newly installed or
activated. They remain historically auditable.

## 15.2 Installed Plugin

An Installed Plugin is a local Hypervisor record that binds one Plugin Release
to the permissions explicitly approved by the operator. It is distinct from a
Plugin Release and from a Provider Instance.

```yaml
installed_plugin:
  installed_plugin_id:
  release_id:
  plugin_id:
  plugin_version:
  package_digest:
  granted_permissions:
  granted_permission_hash:
  installation_generation:
  state:
  installation_source:
  installed_at:
  activated_at:
```

Installation records are local state. Directory publication alone SHALL NOT
create an Installed Plugin, download a package, execute plugin code or grant a
permission.

The initial MVP recognizes two sources:

* `PACKAGE` for a release acquired through a future verified package store;
* `LEGACY_BUILTIN` for an adapter compiled into a Hypervisor compatibility
  build.

`LEGACY_BUILTIN` SHALL NOT be presented as a downloaded or sandboxed community
package. It exists only to make the migration from built-in adapters explicit.

Every package-installed Plugin activation SHALL use an installation-specific
local credential. Publisher keys authenticate Releases and SHALL NOT be used as
Plugin process credentials. Reinstall, package replacement, incompatible state
migration or active permission reauthorization increments Installation
Generation and invalidates older Plugin processes.

## 15.3 Directory and Package-Store Boundary

The Registry Directory stores signed Release metadata; it does not prove that
the corresponding package bytes were downloaded. The Hypervisor SHALL verify:

```text
HASH(downloaded_package_bytes) == PluginRelease.package_digest
```

before Package activation. MVP Release registration may record and inspect
verified metadata without acquiring or executing package bytes. Package Store,
unpacking and Plugin Host activation are separate lifecycle stages so metadata
registration can never become accidental code execution.

---

## 16. Installation Recipes

An Installation Recipe is a preset composed from:

* one Provider Plugin;
* one installation mode;
* optional model preset;
* optional runtime-binding defaults;
* optional endpoint-draft defaults.

Recipes are convenience presets rather than new protocol identities.

---

## 17. Plugin Trust Status

The Directory or Hypervisor MAY display a plugin trust status such as:

* UNREVIEWED
* COMMUNITY_REVIEWED
* CONFORMANCE_TESTED
* AIDN_CURATED
* SECURITY_WARNING
* SECURITY_BLOCKED

Plugin trust status is distinct from:

* Service Verification;
* Endpoint Certification;
* Reputation.

---

## 18. Endpoint Publication Boundary

A Provider Plugin SHALL NOT automatically publish an Endpoint offer merely
because:

* a Provider Instance was attached;
* a provider was installed;
* a model was discovered;
* a model was installed.

Endpoint drafting and Advertisement publication remain separate operator
decisions layered on top of Runtime Binding and Marketplace policy.

---

## 18. Compatibility

During MVP implementation, a Hypervisor MAY project Runtime Bindings into an
older compatibility execution model such as bundle registration.

That compatibility layer SHALL NOT redefine the normative Provider Plugin,
Provider Instance, Model Deployment or Runtime Binding identities introduced by
this RFC.

---

## 19. Security Invariants

* Provider Plugins are installable code and SHALL be treated as untrusted until
  authorized.
* Plugin permissions are explicit.
* Provider credentials are not public protocol data.
* Plugin installation does not create Endpoint publication.
* Installation approval does not grant Wallet, Consensus or Governance
  authority.
* Host-mutating plugin execution is not implied by the existence of an
  Installation Plan.
* Plugin trust status is not Endpoint Certification.
* A plugin package digest identifies one exact installable artifact.
* A Plugin Release is immutable; an Installed Plugin is locally authorized.
* Existing built-in adapters are visibly distinct from package-installed
  community plugins until Plugin Host isolation is available.

---

## 20. Design Invariants

* Hypervisor core knows one plugin contract, not one installer per Provider.
* Provider Plugin, Provider Instance, Model Deployment and Endpoint are
  distinct objects.
* One plugin may manage many Provider Instances.
* One Provider Instance may expose many Model Deployments.
* Runtime Binding is the prerequisite execution surface for endpoint lifecycle.
* Installation Recipes are presets, not protocol authorities.
* Approval, apply-job history and executor identity remain auditable even when
  the executor is a safe recorded MVP executor.
* Plugin Release registration does not acquire or execute package bytes.
