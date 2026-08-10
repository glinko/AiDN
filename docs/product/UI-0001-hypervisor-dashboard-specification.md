# UI-0001 AiDN Hypervisor Dashboard Specification

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0053 AiDN Capability Runtime Specification`
- `RFC-0054 AiDN Capability Runtime Protocol`
- `RFC-0055 Provider Plugin System and Directory`
- `RFC-0056 Provider Plugin Runtime Interface`
- `RFC-0060 Session Failure, Recovery and Forced Settlement`
- `RFC-0062 Snapshot and State Sync Protocol`
- `MVP-0001 Economic Execution Profile`

## 1. Purpose

This document defines the information architecture and operator interaction model of the AiDN Hypervisor Dashboard. It is a UI specification, not an RFC or economic policy: RFCs define protocol behavior, while UI documents define how an operator discovers, configures, understands, and controls the corresponding domain objects.

The Dashboard SHALL expose each architectural object through one canonical interaction surface. It SHALL use stable domain concepts rather than provider-native implementation details.

## 2. Core Model

The primary operational object is a **Bundle**. A Bundle is the operator's coherent deployment unit: it connects the execution chain, resource profile, lifecycle controls, and one or more compatible Endpoint offers.

```text
Provider Plugin -> Provider Instance -> Model Deployment -> Runtime Binding
                -> Bundle -> Endpoint -> Validation
```

This is an operator-view composition, not a replacement for protocol identities:

```text
Bundle != Provider Plugin
Bundle != Runtime Binding
Bundle != Endpoint
Bundle != Session
```

The Endpoint remains the Consumer-facing commercial offer with its own identity, configuration, price, policy, certification, and Session binding. A Bundle may back multiple Endpoint offers, and an Endpoint may select a compatible Runtime set where policy permits. The UI SHALL make these relationships visible without making either object a hidden copy of the other.

## 3. Design Philosophy

The Dashboard SHALL resemble a professional virtualization control plane rather than a generic AI chat application. Its goals are predictable navigation, low cognitive load, reproducible workflows, progressive disclosure, visible operational consequences, and a clean boundary between ordinary operators and advanced administrators.

The supplied `UI-0001` visual reference establishes the intended direction: dark operational workspace, persistent Hypervisor tabs, navigation rail, central working surface, resource visibility, dense but legible status, and health signals that do not hide their underlying state.

## 4. Global Layout

The Dashboard SHALL have four persistent regions:

```text
+----------------------------------------------------------------+
| Hypervisor tabs                              User/Notifications |
+---------------------+------------------------------------------+
| Navigation          | Workspace                                |
|                     |                                          |
+---------------------+------------------------------------------+
| Resource footer: CPU GPU RAM Storage Network Sessions Jobs     |
+----------------------------------------------------------------+
```

The header contains connected Hypervisors, active workspace, notifications, synchronization state, and user menu. Each connected Hypervisor appears as a tab; changing a tab changes the managed Hypervisor and SHALL preserve clear context. The footer remains visible across workspaces and exposes CPU, GPU, GPU memory, RAM, disk, network, power where available, sessions, and jobs.

## 5. Navigation and Modes

The navigation tree SHALL be stable. An object SHALL NOT appear in several unrelated locations merely for convenience. Cross-links are allowed, but they SHALL point to the object's canonical page.

Basic Mode targets ordinary operators:

```text
Overview
Agents
Bundles
Market
Catalog
Wallet
Settings
```

Advanced Mode keeps the same workflow and reveals infrastructure:

```text
Overview
Agents
Infrastructure
  Provider Plugins
  Provider Instances
  Models
  Runtime Adapters
Bundles
Validation
Network
Market
Catalog
Wallet
Logs
Settings
```

Basic Mode hides Provider Plugins, Runtime Adapters, Resource Profiles, validation evidence, logs, and diagnostics by default. Advanced Mode SHALL reveal them without changing object identity, lifecycle rules, or navigation ownership.

## 6. Overview

Overview presents the current Hypervisor health and work that needs attention. It SHALL include CPU, GPU, RAM, storage, network, sessions, running Bundles, published Endpoints, Wallet balance, reputation, and validation status.

It SHOULD provide:

- active Bundle list with Provider, Model, Endpoint, runtime status, session count, and validation state;
- recent activity with direct links to the canonical object page;
- System Health summary for Provider Plugins, Provider Instances, GPUs, network, and storage;
- resource charts and current capacity without overstating stale telemetry;
- endpoint and validation summaries that distinguish `VERIFIED`, `PENDING`, `RUNNING`, `FAILED`, `EXPIRED`, and `PRIVATE`.

## 7. Bundles

Bundles are the primary operational workspace. A Bundle card or table row SHALL show Bundle name/version, Provider, Model, associated Endpoint offers, validation state, resource consumption, active session count, and lifecycle status.

Bundle details SHALL visualize:

```text
Provider Plugin
  -> Provider Instance
  -> Model Deployment
  -> Runtime Binding
  -> Bundle
  -> Endpoint offer(s)
  -> Validation
```

The details inspector SHALL expose Bundle hash and version, linked Endpoint configuration revisions, Runtime Binding/configuration identity, resource profile, dependencies, validation evidence, current health, and non-destructive activity history.

Editing SHALL NOT mutate a published or active Bundle in place:

```text
Bundle v7 -> clone and edit -> Bundle v8 -> validate -> activate/publish
```

Before confirmation, the UI SHALL show detected changes, resource impact, validation impact, affected Endpoint offers, rollback/activation consequences, and any Session-routing restriction. Existing Sessions SHALL remain bound to their accepted configuration; the UI SHALL never imply that a clone rewrites them.

## 8. Bundle Creation and Activation

The Catalog provides Provider Plugins, Bundle templates, Runtime components, and official packages. Selecting a template launches the Bundle creation wizard:

```text
Select template -> Configure Provider -> Select Model -> Allocate resources
-> Configure Endpoint -> Select validation profile -> Review -> Create Bundle
```

The wizard SHALL use the real Provider Plugin, Model Deployment, Runtime Binding, Endpoint, and validation APIs. It SHALL NOT invent a parallel configuration model.

Before activation or model materialization, resource preflight SHALL present known and estimated requirements, including GPU memory, RAM, disk, ports, and relevant policy constraints. Failure is explicit:

```text
GPU memory: 22.4 / 24 GB - OK
Estimated GPU memory: 27 GB - insufficient resources
```

Activation SHALL be disabled while a hard admission condition fails. Warnings remain distinct from blockers. Any Bundle change that invalidates validation SHALL prominently show `Validation Required` and name the affected Endpoint offers.

## 9. Market, Catalog, and Infrastructure

Market is a Consumer-oriented discovery surface. It shows Endpoint offers, capabilities, published price/accounting mode, service ratings, reputation, availability, and validation/certification state. It SHALL NOT expose private deployment internals such as Provider credentials, paths, private addresses, or unnecessary model/runtime topology.

Catalog is operator-oriented. Installation or template selection begins the Bundle wizard and ends only after the operator understands provider permissions, model selection, resource impact, Endpoint configuration, and validation requirements.

Advanced Infrastructure pages are canonical for Provider Plugins, Provider Instances, Models, Runtime Adapters/Bindings, Validation, Network, Logs, and diagnostics. They SHALL expose authoritative IDs, generations, hashes, health/readiness, resource/accounting limitations, and links back to related Bundle and Endpoint pages.

## 10. Interaction Invariants

The following SHALL hold:

- **One object, one canonical page.** A Bundle, Endpoint, Runtime Binding, Provider Instance, and Validation Report each have distinct canonical surfaces.
- **Immutable operational revisions.** Editing creates a new Bundle revision; it does not rewrite active configuration or historical evidence.
- **Visible consequences.** Configuration, publication, validation, resource, trust, and economic effects are shown before confirmation.
- **Stable navigation.** New infrastructure modules extend the tree without relocating core workspaces.
- **No false health.** Stale, degraded, overloaded, or unavailable states are shown honestly; a green process indicator is not a claim that model, route, or Endpoint is ready.
- **No secret leakage.** UI views never expose reusable credentials, secret handles, private Provider topology, or cross-Session data.
- **Architecture fidelity.** The UI reflects actual protocol ownership and does not create convenience abstractions that obscure Runtime, Endpoint, or Session boundaries.

## 11. Reference Implementation

The protocol and HTTP API SHALL remain framework-independent. The recommended
reference implementation is React/Vite with Tailwind CSS and shadcn/ui
primitives, TanStack Query, TanStack Table, Zustand, Zod, Lucide, and Recharts.
Those choices are not a network requirement; they are the maintained reference
for an operator UI that follows this specification.

The initial React route may coexist with the legacy static shell during staged
migration. A replacement workspace SHALL not become the default until it has
functional parity with the operator actions it replaces.

### 11.1 Functional Migration Boundary

The maintained React Dashboard SHALL not present an action button unless it
invokes a real, authenticated control-plane operation and renders the resulting
success, pending, blocked, or failed state. During the current migration, the
following operator controls are implemented through the browser-paired
Dashboard boundary:

- owner Wallet creation and import, including one-time display of a newly
  generated private key;
- host Resource Probe refresh;
- existing Provider attachment, health probing, and model discovery;
- Bundle enable, disable, retry, and cooldown reset;
- MCP agent enrollment, credential lifecycle, permission and default-approval
  controls.

The remaining legacy workflows SHALL be migrated in this order:

1. consumer Market, Session, settlement, and wallet accounting workflows.

Until a workflow reaches the React Dashboard, its legacy surface remains the
canonical operator surface. A React view MAY show its current state but SHALL
describe it as read-only rather than implying an unavailable mutation exists.

### 11.2 Model-to-Endpoint Operator Flow

The maintained React Dashboard SHALL provide one continuous, paired-operator
flow from an installed provider model to a validated Endpoint. The flow is
explicitly ordered so that every later object references an already persisted
identity rather than an uncommitted form value:

```text
Provider install request
  -> installation processing/materialization
  -> Model Deployment
  -> Model Artifact Set and node materialization
  -> Runtime Binding
  -> immutable Bundle revision
  -> Endpoint draft
  -> readiness/preflight
  -> consensus publication
  -> validation request
```

The Models workspace SHALL let an operator queue and process a provider/model
installation, register the resulting deployment as a Bundle candidate, create
or bind an Artifact Set, materialize it on the node, and create a Runtime
Binding. Each action SHALL display the returned ID, current state, error, and
the next allowed action. Destination defaults MAY be selected by the node, but
the UI SHALL show the resolved destination after materialization.

Bundle editing SHALL create a new revision with a new Bundle ID, monotonic
revision number, source revision reference, and deterministic content hash.
The source Bundle remains unchanged. Revision creation SHALL reject attempts to
override identity, revision, ancestry, or content-hash fields.

Endpoint configuration SHALL begin as a draft. Draft fields include the
Runtime Binding, capability, visibility, owner/payment beneficiary, accounting
mode, fixed price, minimum deposit, and validation profile. Publish is a
separate action: it runs readiness checks, requires the paired operator
boundary, and uses the canonical consensus publication path. A failed or
pending publication SHALL remain visible with its operation ID and retry path;
the UI SHALL never show a draft as published merely because the HTTP request
was accepted.

Validation is requested only against an existing Endpoint identity. The
Dashboard SHALL expose `DRAFT`, `PUBLISHED`, `VALIDATION_PENDING`, `VALIDATED`,
`REJECTED`, and `REVOKED` states, plus the exact reason and evidence reference
when a transition is blocked. Endpoint changes after publication SHALL create
a new draft/configuration revision rather than mutate the published offer.

## 12. Future Extensions

Potential additions include Storage, COMET Objects, Peer Explorer, AI Scheduler, GPU Allocator, Automation, and Developer Tools. They SHALL extend the primary navigation model without duplicating Bundle, Endpoint, or Runtime ownership.

## 13. Implementation Order

This specification is post-MVP product work. Implementation SHALL proceed as:

1. Add a Dashboard domain map and route inventory that maps existing surfaces to the canonical UI objects.
2. Implement Bundle-centric overview/list/detail views using current endpoint-first service contracts.
3. Add immutable Bundle clone/revision and impact-preflight UX once backend lifecycle evidence is complete.
4. Add Basic/Advanced mode persistence and infrastructure pages without duplicating APIs.
5. Validate navigation and lifecycle flows with operator usability tests before treating the visual system as stable.
