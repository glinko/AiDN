# Provider Plugin System MVP Design

Date: 2026-07-14

Status: Draft

## Goal

Add a plugin-first provider foundation to the hypervisor so operators can:

- install or attach provider integrations through a common Provider Plugin API;
- create concrete Provider Instances from those plugins;
- discover or install Model Deployments behind those instances;
- create Runtime Bindings from Model Deployments;
- publish Endpoint offers only after a Runtime Binding exists.

This slice keeps the current execution stack working by treating the existing
bundle layer as an internal compatibility projection rather than the long-term
operator-facing contract.

## Problem

The current implementation is operational, but its operator model is still too
close to the first local-runtime MVP:

- provider integrations are code-level plugin adapters, not operator-managed
  products;
- installed models are folded too early into bundle registration;
- operator flows still assume `install -> bundle -> endpoint`;
- the current data model does not distinguish:
  - the plugin package;
  - a concrete provider installation or attachment;
  - a concrete deployed model;
  - the runtime binding that exposes that model to AiDN endpoint lifecycle.

That mismatch now matters because the RFC layer and the desired operator
experience both need stronger boundaries:

- a community plugin should be installable without changing hypervisor core
  code;
- one plugin should be able to manage several Provider Instances;
- one Provider Instance should be able to expose several Model Deployments;
- endpoint publication should remain a separate operator action on top of
  runtime readiness, not a side effect of provider installation.

If we keep deepening the current bundle-centric flow, we will make later RFC
alignment harder in three places:

1. runtime identity and capability binding stay ambiguous;
2. provider-install UX stays entangled with execution registration;
3. future security boundaries for plugin permissions, secrets, and installation
   plans have nowhere explicit to attach.

## Scope

This MVP design adds the minimum first-class architecture needed to support the
future plugin ecosystem while preserving current execution behavior.

It adds:

- `ProviderPlugin` as an installable hypervisor extension with manifest,
  capability flags, permission declarations, and declarative UI schemas;
- `ProviderInstance` as one attached or managed provider installation;
- `ModelDeployment` as one concrete model or backend deployment reachable
  through a Provider Instance;
- `RuntimeBinding` as the AiDN-facing execution binding derived from one Model
  Deployment and one primary Capability;
- a Provider Plugin Directory concept for browsing installable plugins;
- Installation Recipes as optional presets composed from plugin, provider mode,
  model preset, and endpoint defaults;
- a compatibility projection from `RuntimeBinding` back into the current
  bundle/runtime execution path.

It does not add:

- arbitrary third-party frontend code inside the operator UI;
- fully general sandboxing or paid plugin marketplaces;
- hot-swappable root-level installers;
- distributed plugin publication or protocol-native plugin governance;
- full provider package lifecycle automation for every backend;
- removal of the existing bundle execution layer in this slice.

## Approved Approach

Use a compatibility-first Provider Plugin System.

That means:

- introduce the new operator-facing entities now;
- keep the current runtime/process execution machinery underneath them for the
  first slice;
- translate `ModelDeployment -> RuntimeBinding -> BundleConfig` at the service
  boundary so we do not have to rewrite scheduling and execution immediately;
- make the operator UI and roadmap speak in plugin/provider/model/runtime
  language first, while the bundle layer becomes an internal compatibility
  implementation detail.

This is the recommended option because it solves the product and RFC mismatch
without turning the next implementation step into a full runtime rewrite.

## Alternatives Considered

### 1. Keep extending the bundle-first model

Recommendation: No.

Pros:

- smallest short-term code churn;
- reuses current install and execution flow almost unchanged.

Cons:

- cements the wrong operator abstractions;
- leaves no clean boundary for plugin manifests, permissions, or install plans;
- makes later RFC-0055 and RFC-0056 work look like a retrofit instead of the
  system model.

### 2. Compatibility-first plugin foundation

Recommendation: Yes.

Pros:

- introduces the right long-term entities now;
- keeps current execution stable;
- supports both `attach existing provider` and `managed install` flows;
- gives roadmap and RFC updates an explicit architectural anchor.

Cons:

- requires translation layers and dual terminology during migration;
- some current APIs and dashboard payloads will temporarily expose both new and
  compatibility-shaped data.

### 3. Full runtime rewrite before UI and model changes

Recommendation: Not yet.

Pros:

- cleanest final architecture in theory;
- avoids carrying compatibility projections.

Cons:

- far too wide for the next slice;
- delays the operator-facing provider/plugin workflow the user actually wants;
- risks mixing installation, runtime, endpoint, and scheduling changes into one
  brittle migration.

## Core Entities

### 1. Provider Plugin

An installable extension bundle that teaches the hypervisor how to work with a
provider family.

One plugin may support:

- attach-existing mode;
- managed-install mode;
- model discovery;
- model installation;
- runtime execution adaptation;
- health and usage adaptation.

It is not:

- a concrete provider installation;
- a model deployment;
- an endpoint offer.

### 2. Provider Instance

One concrete attached or managed provider installation.

Examples:

- local Ollama on `localhost:11434`;
- remote vLLM at `http://10.0.0.25:8000`;
- a managed local `llama.cpp` process group.

It belongs to one Provider Plugin but may host many Model Deployments.

### 3. Model Deployment

One concrete model or backend deployment reachable through one Provider
Instance.

Examples:

- `qwen3:14b` in Ollama;
- `Qwen/Qwen3-14B` in vLLM;
- one GGUF file in `llama.cpp`;
- one remote model identifier in an OpenAI-compatible upstream.

It is the source of execution metadata and operator-declared model metadata,
but it is not yet an AiDN endpoint offer.

### 4. Runtime Binding

One AiDN-facing execution binding from a Model Deployment to one primary
Capability contract.

Examples:

- `model_deployment=ollama:qwen3:14b -> capability=llm.chat`;
- `model_deployment=bge-m3 -> capability=llm.embed`.

Runtime Binding is the layer that:

- normalizes plugin/provider/model metadata into AiDN execution semantics;
- feeds service verification and runtime protocol surfaces;
- becomes the direct prerequisite for endpoint drafting and publication.

### 5. Endpoint Draft

An operator-owned draft offer derived from a Runtime Binding plus pricing and
policy choices.

Endpoint publication remains a separate explicit decision after runtime
readiness is known.

## Operator Flows

### Flow A: Browse and install provider plugin

1. Operator opens `Providers`.
2. If no providers exist, the screen shows:
   - `Add existing provider`
   - `Browse provider plugins`
3. Operator installs a Provider Plugin from the local directory/catalog.
4. Hypervisor validates:
   - plugin signature or package digest;
   - hypervisor compatibility;
   - requested permissions;
   - trust/security status.
5. Plugin becomes available for Provider Instance creation.

### Flow B: Attach existing provider

1. Operator selects a plugin.
2. Hypervisor renders the plugin's declarative attach schema.
3. Operator enters provider-specific connection fields.
4. Plugin validates configuration and tests connectivity.
5. Hypervisor creates a Provider Instance.
6. Plugin discovers available Model Deployments where possible.

### Flow C: Managed install

1. Operator selects a plugin and an installation mode.
2. Hypervisor renders the plugin's declarative install schema.
3. Plugin returns a declarative Installation Plan.
4. Hypervisor applies the plan through approved control surfaces.
5. Provider health and conformance checks run.
6. Hypervisor creates the Provider Instance.

For the MVP, managed install is declarative-only. A provider plugin may describe
how to install Ollama, vLLM, ComfyUI, llama.cpp, an OpenAI-compatible adapter, or
another provider family, but the hypervisor remains the executor of the plan. The
plugin does not receive unrestricted shell execution or host-root authority.

The plan may include:

- container images or process commands from explicit package sources;
- source repositories or release artifacts with package digests;
- model downloads and storage targets;
- environment variables and resource limits;
- GPU and accelerator requirements;
- private-network bindings;
- health checks and conformance probes;
- secret handles, never raw secret values.

This keeps the operator experience close to "install this provider with this
model", while making the security boundary inspectable before anything changes
on the host.

### Flow D: Add model

1. Operator opens one Provider Instance.
2. Operator chooses:
   - discover installed models;
   - install a recommended model;
   - import an existing model reference;
   - enter a provider-native model reference.
3. Hypervisor creates a Model Deployment after plugin validation.
4. Plugin reports model capabilities and usage-reporting characteristics.

### Flow E: Create runtime binding and endpoint draft

1. Operator selects one Model Deployment.
2. Hypervisor asks for one primary Capability binding.
3. Hypervisor creates a Runtime Binding.
4. Hypervisor projects the Runtime Binding into the existing execution layer.
5. Operator creates an Endpoint Draft from that Runtime Binding.
6. Operator sets pricing and policies.
7. Operator publishes the Advertisement as a separate step.

## Compatibility Boundary

The current codebase already has working:

- provider plugins as Python adapters;
- install jobs;
- bundle registration;
- runtime process lifecycle;
- endpoint publication flows.

This slice should preserve that working behavior by introducing a translation
layer rather than replacing it all at once.

### Compatibility rule

For MVP execution only:

`RuntimeBinding -> BundleConfig compatibility projection`

That projection should preserve:

- plugin identity;
- provider family;
- model reference;
- launch mode;
- endpoint or local transport address;
- resource profile;
- usage contract metadata.

The operator should increasingly see:

`Provider Plugin -> Provider Instance -> Model Deployment -> Runtime Binding`

while the scheduler and process manager may still consume:

`BundleConfig`

until the later runtime rewrite removes that dependency.

## Provider Plugin API Foundation

The MVP should standardize a first explicit plugin contract even if some
methods initially delegate into existing code.

### Manifest and metadata

Every plugin manifest should be able to declare:

- `plugin_id`
- `plugin_version`
- `display_name`
- `publisher`
- `package_digest`
- `hypervisor_api_compatibility`
- `provider_families`
- `plugin_capability_flags`
- `required_permissions`
- `supported_aidn_capabilities`
- `attach/install/model UI schema hashes`
- `installation_recipes`

### Capability flags

Initial flags should include:

- `CAN_ATTACH_EXISTING`
- `CAN_INSTALL_PROVIDER`
- `CAN_UPDATE_PROVIDER`
- `CAN_REMOVE_PROVIDER`
- `CAN_DISCOVER_MODELS`
- `CAN_INSTALL_MODELS`
- `CAN_IMPORT_MODELS`
- `CAN_REMOVE_MODELS`
- `CAN_START_STOP_MODELS`
- `CAN_STREAM`
- `CAN_CANCEL`
- `CAN_REPORT_USAGE`
- `CAN_REPORT_AUTHORITATIVE_TOKENS`
- `CAN_RECOVER_REQUESTS`
- `CAN_MANAGE_GPU`
- `CAN_MANAGE_CONTAINERS`

### Control-plane methods

Initial plugin API surface should be able to express:

- manifest and compatibility inspection;
- provider-instance validation;
- installation-plan generation;
- attach-existing flow;
- model discovery and validation;
- runtime-binding creation;
- health, usage, and diagnostics reporting.

### UI contract

The plugin should provide declarative schemas, not arbitrary embedded frontend
code, for:

- attach provider;
- install provider;
- add model;
- endpoint defaults;
- diagnostics.

That keeps the operator shell consistent and reduces obvious security risk.

## Security Foundation

The MVP should add explicit hooks now even if the first enforcement pass is
lightweight.

### Required foundations

- plugin package digest and publisher identity fields;
- explicit permission manifest;
- per-plugin trust status;
- scoped secret references instead of raw secret persistence in plugin-visible
  state;
- installation plans reviewed and applied by the hypervisor;
- no automatic endpoint publication as a plugin side effect.

### Installer execution tiers

The system intentionally separates three things that are easy to collapse:

- `Provider Plugin`: the signed integration package and runtime adapter.
- `Installation Plan`: a declarative description of host changes the hypervisor
  may apply.
- `Installer Component`: optional plugin-supplied code that may be allowed to
  perform complex installation work in a later risk tier.

The MVP implements the first two and reserves the third.

#### Tier 1: Declarative plan

This is the MVP baseline.

The plugin may generate a plan, but the hypervisor applies it through known
control surfaces such as container management, model download, volume creation,
process configuration, and health checks. This is sufficient for common happy
paths such as:

- install Ollama from a pinned image or release and pull `qwen3:8b`;
- attach or run vLLM with a declared model reference;
- configure a generic OpenAI-compatible provider adapter;
- install a model artifact into a managed model directory.

#### Tier 2: Sandboxed installer component

This is explicitly deferred.

Some provider families may eventually need custom installation logic: building a
wheel, probing local GPU drivers, compiling llama.cpp variants, preparing a
provider-specific bridge, or applying migration scripts. Those cases should use
a sandboxed installer component with:

- separate capability flag such as `CAN_RUN_SANDBOXED_INSTALLER`;
- elevated trust/risk display in the Plugin Directory;
- explicit operator approval for new permissions;
- bounded filesystem and network access;
- no wallet, consensus, governance, or unrelated provider secrets;
- captured logs and support bundle output;
- deterministic install result records where practical.

Tier 2 must not be treated as the default meaning of "install provider".
Community plugins can be powerful, but they should not become a polite UI around
arbitrary remote code execution.

### Deferred but intentionally reserved

- hardened sandboxing;
- per-plugin filesystem jail;
- per-plugin egress policy enforcement;
- sandboxed installer component execution;
- signature-chain governance;
- protocol-native plugin blocking.

Those can land later because the object model and manifest fields will already
exist.

## Data and Trust Semantics

The system should separate what is declared from what is observed.

### Model metadata sources

ModelDeployment data should be able to mark fields as:

- `PLUGIN_DISCOVERED`
- `OPERATOR_DECLARED`
- `MANIFEST_VERIFIED`
- `PROVIDER_REPORTED`
- `LOCALLY_MEASURED`

### Usage reporting sources

Usage reporting should distinguish:

- `AUTHORITATIVE_PROVIDER`
- `DETERMINISTIC_LOCAL`
- `OBSERVABLE_LOCAL`
- `ESTIMATED`
- `UNAVAILABLE`

This matters because the endpoint offer must not pretend a provider exposes
exact accounting data when it does not.

## Operator UI Direction

The dashboard should move from a bundle-first setup flow to a provider-first
inventory flow.

The target MVP user story is:

`Providers -> install or attach provider -> add/discover model -> create runtime binding -> create endpoint`

The bundle workspace may continue to exist temporarily for compatibility, but
it should become subordinate to runtime-binding and endpoint lifecycle.

The first meaningful empty state should be:

`No providers installed`

not:

`No bundles configured`

## Implementation Shape

This design implies a staged implementation shape:

### Stage 1: data model and service boundary

- add first-class plugin, provider-instance, model-deployment, and
  runtime-binding models;
- add compatibility mappers into the existing bundle/runtime layer;
- preserve current execution behavior.

### Stage 2: operator workflow

- replace the current provider/install/bundle bootstrap flow with provider
  plugin and provider-instance flows;
- keep endpoint drafting and publication separate.

### Stage 3: runtime normalization

- make Runtime Binding the primary internal execution contract;
- shrink bundle usage to compatibility-only paths;
- later remove the compatibility path when the runtime layer is fully migrated.

## Testing Strategy

The first implementation plan should cover four verification layers.

### 1. Domain tests

Cover:

- plugin manifest validation;
- Provider Instance creation;
- Model Deployment creation;
- Runtime Binding creation;
- compatibility projection into bundle config.

### 2. Service tests

Cover:

- attach-existing flow;
- managed-install plan generation;
- model discovery;
- model install/import validation;
- endpoint-draft creation gating on Runtime Binding existence.

### 3. API and dashboard tests

Cover:

- providers empty state;
- provider-plugin directory listing;
- attach/install forms from declarative schemas;
- provider-instance detail payloads;
- model-deployment detail payloads;
- create-endpoint CTA from model/runtime state.

### 4. Compatibility tests

Cover:

- Runtime Binding to BundleConfig translation;
- unchanged execution behavior for existing providers;
- stable endpoint publication from the new flow through the current backend.

## RFC Impact

The product RFC set should be updated together with this design so the repo no
longer mixes the old bundle/provider mental model with the new provider-plugin
system.

### Existing RFC updates

- `RFC-0039` should add `ProviderPlugin`, `ProviderInstance`,
  `ModelDeployment`, and `RuntimeBinding` as hypervisor-local entities that sit
  below public Service and Endpoint lifecycle.
- `RFC-0040` should clarify that Service Verification targets Runtime Binding
  and protocol behavior, not provider installation mechanics.
- `RFC-0044` should clarify that Session execution speaks to the Runtime
  Adapter or Runtime Binding surface, never directly to provider-native APIs.
- `RFC-0045` should clarify that capability binding is created from a Model
  Deployment through a Runtime Binding, not from raw provider inventory.
- `RFC-0049` should clarify that an Advertisement is publishable only after a
  Runtime Binding exists and an Endpoint Draft has been created from it.
- `RFC-0053` should redefine the runtime as the normalized AiDN view of
  `ProviderInstance + ModelDeployment + Plugin Adapter` rather than a vague
  self-owning execution box.
- `RFC-0054` should clarify that the Runtime Protocol is the execution-plane
  contract of that normalized runtime surface.

### New RFCs

- `RFC-0055 Provider Plugin System and Directory` should define:
  - plugin manifest;
  - plugin directory;
  - permission model;
  - attach-existing flow;
  - managed-install flow;
  - Provider Instance lifecycle;
  - Model Deployment lifecycle;
  - Installation Recipes;
  - plugin trust and security status.
- `RFC-0056 Provider Plugin Runtime Interface` should define:
  - plugin control-plane RPC;
  - runtime adapter execution-plane surface;
  - model discovery;
  - health;
  - usage reporting;
  - cancellation;
  - streaming;
  - recovery;
  - stable plugin/runtime errors.

## Roadmap Impact

`ROADMAP.md` should move from bundle-first wording toward plugin-first wording.

Key changes:

- the current-stage summary should state that provider-plugin, provider-instance,
  model-deployment, and runtime-binding foundations are the next operator-facing
  architecture slice;
- current execution should be described as a compatibility layer, not the final
  public contract;
- immediate priorities should include provider-plugin-system MVP and operator
  provider workflow migration;
- older bundle-centric language should be rewritten as compatibility execution
  infrastructure.

## Success Criteria

This design is successful when the next implementation slice can deliver:

- a visible Provider Plugin Directory foundation;
- Provider Instance creation through attach-existing and/or managed-install
  flows;
- Model Deployment creation and inspection;
- Runtime Binding creation before endpoint drafting;
- endpoint publication still working through the compatibility execution layer;
- roadmap and RFC language that consistently describe the new architecture.

## Out Of Scope

This design intentionally does not require:

- a full replacement of the existing scheduler or process manager;
- network-distributed plugin packaging;
- canonical protocol governance for plugin publication;
- automatic validation or certification of installed provider plugins;
- production-grade plugin sandboxing in the same slice;
- deprecation of the bundle layer before a later runtime migration completes.

## Why This Slice Now

The current repo has enough local execution maturity that the next blocker is no
longer "can we run work locally?".

The next blocker is that the implementation, roadmap, and product RFC layer do
not yet speak the same operator language for how provider integrations should
actually enter the system.

Adding a compatibility-first Provider Plugin System now gives us the right
foundation without throwing away the runtime and endpoint work that already
exists.
