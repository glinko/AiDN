# RFC-0055

Provider Plugin System and Directory

Status: Draft

Version: 0.2

Supersedes:

* RFC-0055 Version 0.1

Depends on:

* RFC-0039 Hypervisor Service Model
* RFC-0045 AiDN Capability Architecture
* RFC-0049 Distributed Marketplace and Endpoint Advertisement Registry
* RFC-0053 Capability Runtime Specification
* RFC-0054 Capability Runtime Protocol

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
* Installation Recipes;
* plugin permissions and trust status;
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
  secret_requirements:
  attach_ui_schema_hash:
  install_ui_schema_hash:
  model_ui_schema_hash:
  package_digest:
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

Applying an Installation Plan SHALL require an explicit operator approval bound
to the exact:

* Plugin ID;
* Installation Plan hash;
* Provider configuration hash;
* permission set;
* secret-reference set where applicable.

The Hypervisor MAY implement a non-host-mutating recorded executor for MVP
operation. Such an executor creates local inventory and audit state but does not
run shell commands, container engines, package managers, downloads or plugin
installer code.

Host-mutating executors SHALL be treated as a higher-risk implementation layer
and require sandboxing, permission checks, secret scoping, diagnostics and
rollback policy.

---

## 15. Installation Recipes

An Installation Recipe is a preset composed from:

* one Provider Plugin;
* one installation mode;
* optional model preset;
* optional runtime-binding defaults;
* optional endpoint-draft defaults.

Recipes are convenience presets rather than new protocol identities.

---

## 16. Plugin Trust Status

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

## 17. Endpoint Publication Boundary

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
