# UX-0003 — Node Journey / Setup Graph

Status: Implemented MVP
Version: 0.1

## Purpose

The Overview presents one canonical, live graph of the Hypervisor's path from
initialized node to a discoverable AI service. The graph is a read projection,
not a second configuration store and not a static onboarding wizard.

## Contract

`GET /operators/dashboard/journey` returns:

- `hypervisor` identity and network evidence;
- required and optional progress counters;
- `nodes` with state, dependencies, reason, details, and an optional dashboard
  action;
- `edges` that describe required or optional dependencies;
- `recommended_action`, computed on the Hypervisor.

The server-side `JourneyStateService` derives the projection from existing
wallet, provider, model, Bundle, Endpoint, validation, resource, queue, hook,
and consensus read models. React does not infer readiness from nullable fields.

## Renderers

The React dashboard uses the same graph for two renderers:

- desktop: a dependency graph with SVG connectors, node cards, a sticky status
  rail, progress, next action, quick actions, and a legend;
- mobile: collapsible Identity, Compute, Network, Operations, and Extensions
  branches with the same node cards;
- List mode: a compact accessible projection for operators who need to scan
  state rather than follow the topology.

Selecting a node opens a detail sheet. The sheet is a right rail on desktop
and a bottom sheet on mobile. Actions route into the canonical dashboard
workspace instead of duplicating domain workflows.

## State semantics

`ready`, `in_progress`, `not_started`, `blocked`, `warning`, and `error` are
explicitly labelled and never communicated by color alone. Optional stages do
not reduce required progress. Missing resource or network evidence is shown as
uncertain rather than fabricated as healthy.

## Refresh

The Journey query is polled with the existing dashboard read cadence and is
included in the global Refresh action. Future RFC-0072 event subscriptions may
invalidate the same query without changing the graph contract.
