# AiDN Roadmap

Last updated: `2026-06-30`

This is the main public roadmap for the repository.

It should stay current and answer four questions:

1. What are we building?
2. What stage are we in now?
3. What milestones come next?
4. What has to be true before we move to the next stage?

The roadmap must also stay aligned with the product-level operator journey defined in [docs/product/UX-0001-hypervisor-operator-journey.md](./docs/product/UX-0001-hypervisor-operator-journey.md).

Milestones still describe technical delivery order, but feature sequencing and UI priorities should preserve that operator journey whenever reasonably possible.

## North Star

AiDN is moving toward a decentralized network of trusted AI compute nodes.

In the target system:
- any hypervisor node can join the network;
- each node can publish its resources, installed models, providers, pricing, and operational status;
- agents discover the best execution target through the network, not by hard-coding a single node;
- routing depends on availability, trust, latency, price, and policy;
- node operators earn `q` compute units for useful work;
- trust, rating, and wallet settlement support sustainable network growth.

The distributed registry is a target architecture, not the first milestone.

## Current Stage

Status: `M2 complete, M3 started`

Product alignment summary:
- the repo now has a strong local hypervisor and operator-dashboard foundation;
- the next product-critical gap is the operator bootstrap loop from install -> wallet -> provider -> model -> first endpoint;
- validation, marketplace, and remote execution should stay explicit operator actions layered on top of that core flow, not replace it.

We already have a working local hypervisor foundation:
- local task queue and admission control;
- local resource accounting for `CPU`, `RAM`, and `VRAM`;
- bundle and provider abstraction;
- subprocess-backed runtime lifecycle and operator controls;
- agent allocation leases;
- agent capability catalog for local discovery, including endpoint readiness, resource fit, node pricing/custom-model policy, and bundle provider/model identity;
- install job execution for local model artifacts.
- centralized registry advertisement, heartbeat freshness, and discovery API;
- registry discovery now preserves bundle plugin identity alongside provider/model metadata, so agents can distinguish adapter families without a second node-local lookup;
- registry discovery now also exposes a flattened `candidates` view so agents can consume node-plus-bundle execution options without walking nested `nodes[].bundles[]` payloads;
- flattened registry candidates now support execution-readiness filtering for allocation support, queue support, and ready endpoint availability;
- the operator dashboard now ships as a terminal-style multi-node control room with `Home / Fleet / Market`, a persistent command rail, right-side selection inspector, and lower-band operational cards on top of the current hypervisor and registry contracts;
- the operator dashboard wallet surface is now a live inline console with `Usage / Settlements / Disputes / Quote` tabs, opening from the rail or lower operations band without leaving the main shell;
- the operator dashboard now also includes a live `Requests` workspace for queue triage, recent-task inspection, admission visibility, persisted spillover policy, and market spillover preview inside the main operator shell;
- the operator dashboard now also includes a first `Endpoints` workspace, so visibility, publication, and validation can be reviewed as separate operator decisions instead of being folded into bundle or market views;
- a parallel endpoint-first package now exists with snapshot-backed manifest storage, lifecycle service methods, and a versioned `/api/v1/endpoints` API on the main app surface;
- the `Endpoints` dashboard workspace can now prefer the endpoint-first service and versioned API for visibility, publication, and validation actions, while legacy bootstrap routes remain as transition fallback;
- wallet-signed endpoint configuration publication now exists as a first trust layer with publish/revoke/export APIs, registry-visible current configuration hashes, and live proof comparison surfaces;
- the operator dashboard `Endpoints` workspace now exposes local-vs-published configuration sync state, so operators can see whether local edits have drifted from the last published network-visible claim;
- basic node pricing publication in registry discovery;
- operator wallet quote, usage event, and export contract;
- automatic wallet metering from task execution when usage metadata is available;
- usage events linked to `task_id` and `allocation_id` for stronger lease attribution.
- wallet attribution can now derive owner identity from an active allocation lease when `wallet_owner_id` is not passed explicitly;
- task submission with `allocation_id` now routes through the active lease bundle and rejects inactive allocations;
- allocation activation now emits a wallet-facing journal hook with lease metadata for both direct activations and pending-lease promotion;
- allocation activation is now exported through a dedicated replay-safe wallet stream with the same cursor contract used by usage and settlement exports;
- allocation `release` and `expire` now emit settlement-facing wallet finalization events with aggregated spend snapshots;
- allocation finalization now uses a grace period before settlement closure, so late spend can still be absorbed before the event becomes `closed`;
- closed allocation settlement events can now be reopened manually into a fresh grace window with dispute metadata, so operators can absorb late usage corrections without rewriting history;
- allocation settlement now supports a longer-lived dispute overlay plus a dedicated replay-safe dispute stream, so operators can freeze auto-closure, record dispute lifecycle changes, and resolve them without changing the core `grace/closed` contract;
- real `ollama`, `llama.cpp`, and `whisper` adapters now emit provider-facing `usage` contracts with explicit `exact` vs `estimated` measurement metadata;
- provider adapters now publish a declarative `usage_contract` in plugin descriptions so operators and future routers can see exact/estimated metering capability before execution;
- validated metering metadata with `measurement_kind` and `measurement_source`;
- invalid provider usage payloads skipped safely without failing completed tasks.
- provider contracts can now opt into `missing_usage_behavior=strict_accounting`, which keeps the task completed but marks the result `unbillable` and settlement-blocked when usage is missing or invalid;
- settlement export now exposes monotonic `sequence_id` cursors, retention window metadata, and stale-cursor detection.

What is still missing in the current stage:
- decision on whether adapter-declared `usage_contract` becomes an enforced runtime gate, plus a first non-token pricing unit for `whisper`-class workloads;
- rating publication and reputation policy;
- network-visible custom model onboarding workflow.
- first-class wallet ownership onboarding and node identity flow in the operator experience;
- full endpoint-first persistence and API beyond the current bootstrap/dashboard slice, so privacy, sharing, publication, and validation remain distinct all the way through the service contract;
- complete dashboard migration of `Home` bootstrap and remaining bundle-centric endpoint affordances onto the new endpoint service and `/api/v1/endpoints` contract;
- remote endpoint and proxy endpoint workflows framed as operator routing tools, not only discovery data.

## Milestones

### M1: Local Hypervisor MVP

Goal: make one node useful as a standalone execution hypervisor.

Status: `Complete`

Checkpoints:
- [x] Local queue and scheduler
- [x] Resource admission and reservations
- [x] Bundle and plugin registry
- [x] Manual and automatic routing
- [x] Agent allocation leases
- [x] Agent capability catalog
- [x] Model install jobs
- [x] Install artifact download and completion automation
- [x] Register installed model as schedulable bundle
- [x] Production-ready provider process execution

Exit criteria:
- a node can advertise its local capabilities through a stable API;
- an operator can install or register local models without direct code edits;
- an agent can request a usable local endpoint from the hypervisor;
- runtime startup and shutdown are backed by real execution control, not only in-memory handles.

### M2: Centralized Registry And Discovery

Goal: make multiple nodes discoverable through one shared registry service.

Status: `Complete`

Checkpoints:
- [x] Registry service for node registration
- [x] Node heartbeat and health status
- [x] Published node metadata:
  - resources
  - installed models
  - providers
  - `can_host_custom_model`
  - pricing in `q per 1kk tokens`
- [x] Discovery API for agents and routers
- [x] Basic registry-side filtering by workload, provider, model, and policy

Exit criteria:
- any node can register and refresh its state in the registry;
- agents can query one discovery endpoint instead of a specific node;
- registry records pricing and onboarding capability per node.

### M3: Wallet And Pricing Interface

Goal: introduce `q` as the network compute unit and define how work is priced.

Status: `In progress`

Checkpoints:
- [x] Initial `q per 1kk tokens` pricing contract
- [x] Operator wallet quote calculator
- [x] Manual usage event recording contract
- [x] Automatic usage metering from real executions
- [x] Provider metering contract for `exact` vs `estimated` usage
- [x] Wallet-facing accounting export interface
- [x] Cost declaration per node:
  - input token price
  - output token price
  - optional fixed task price
- [x] Metering contract for usage reporting
- [x] Settlement-ready event model
- [x] Settlement export replay and retention contract
- [x] Operator-facing wallet console for quote, settlement reopen, and dispute resolution workflows

Exit criteria:
- the system can describe the price of work in `q`;
- a wallet layer can consume usage events and calculate spend;
- pricing is part of discovery, not hidden in node-local config only.

### M4: Rating And Reputation

Goal: publish trust and quality signals for node selection.

Status: `Planned`

Checkpoints:
- [ ] Rating model for nodes
- [ ] Core metrics:
  - uptime
  - success rate
  - latency
  - operator reliability
  - dispute or penalty history
- [ ] Registry publication of rating data
- [ ] Selection policy that can combine price and rating

Exit criteria:
- nodes are ranked by structured signals instead of static preference only;
- discovery clients can filter or sort by trust and price together.

### M5: Custom Model Onboarding

Goal: let nodes advertise and execute whether they can download and host custom models.

Status: `Planned`

Checkpoints:
- [ ] Operator model install workflow
- [ ] Node flag `can_host_custom_model`
- [ ] Install job lifecycle
- [ ] Bundle creation from installed artifacts
- [ ] Registry publication of onboarding capability

Exit criteria:
- a node can explicitly declare whether it accepts custom model onboarding;
- the registry can expose that capability to agents or operators.

### M6: Federated Or Distributed Registry

Goal: move from a single registry service to a federated or distributed discovery layer.

Status: `Target architecture`

Checkpoints:
- [ ] Federation model and trust boundaries
- [ ] Signed node advertisements
- [ ] Cross-registry replication or exchange
- [ ] Conflict resolution and freshness model
- [ ] Discovery behavior under partial partition

Exit criteria:
- network discovery no longer depends on one central registry instance;
- node metadata and ratings can propagate across trusted registry peers.

## Immediate Priorities

Order of work right now:

1. Close the operator bootstrap loop from `install -> wallet ownership -> provider attach -> model/bundle setup -> first endpoint publish`
2. Make endpoint management the primary operator object, including privacy mode, publication mode, and validation as separate actions
3. Finish migrating the operator shell onto the endpoint-first trust layer, so publish/proof/sync state are first-class controls across `Home`, `Endpoints`, and later marketplace flows
4. Expand the dashboard into full `Providers / Bundles / Endpoints / Remote Endpoints / Marketplace / MCP` workflows instead of only telemetry and market visibility
5. Finish `M3` accounting decisions in a way that supports the operator journey instead of leaking settlement complexity into first-run UX
6. Define `M4` rating and `M5` custom model onboarding contracts around the endpoint-centric operator experience

## Source Documents

- Vision: [00_VISION.md](./00_VISION.md)
- Terms: [01_TERMS.md](./01_TERMS.md)
- Operator journey: [docs/product/UX-0001-hypervisor-operator-journey.md](./docs/product/UX-0001-hypervisor-operator-journey.md)
- Current hypervisor execution plan: [docs/superpowers/plans/2026-06-19-agent-resource-discovery-and-model-onboarding.md](./docs/superpowers/plans/2026-06-19-agent-resource-discovery-and-model-onboarding.md)
- Network architecture spec: [docs/superpowers/specs/2026-06-19-network-registry-wallet-rating-design.md](./docs/superpowers/specs/2026-06-19-network-registry-wallet-rating-design.md)
- M2 registry contract: [docs/superpowers/specs/2026-06-19-m2-centralized-registry-and-discovery-design.md](./docs/superpowers/specs/2026-06-19-m2-centralized-registry-and-discovery-design.md)
- Operator dashboard spec: [docs/superpowers/specs/2026-06-20-operator-fleet-market-dashboard-design.md](./docs/superpowers/specs/2026-06-20-operator-fleet-market-dashboard-design.md)
- Operator dashboard terminal redesign spec: [docs/superpowers/specs/2026-06-20-operator-dashboard-terminal-redesign-design.md](./docs/superpowers/specs/2026-06-20-operator-dashboard-terminal-redesign-design.md)
- Operator dashboard terminal redesign plan: [docs/superpowers/plans/2026-06-20-operator-dashboard-terminal-redesign.md](./docs/superpowers/plans/2026-06-20-operator-dashboard-terminal-redesign.md)
- M3 pricing and metering plan: [docs/superpowers/plans/2026-06-19-m3-wallet-pricing-and-usage-metering.md](./docs/superpowers/plans/2026-06-19-m3-wallet-pricing-and-usage-metering.md)

## Maintenance Rule

Every meaningful architecture or milestone change should update this file in the same branch.
