# Network Registry, Wallet, And Rating Design

## Summary

This spec defines the next architecture layer above the local hypervisor.

AiDN should not stop at a single-node execution service. The intended system is a network of hypervisors that can publish capabilities, pricing, and trust signals so agents can discover the best node for a task.

The first network milestone is a centralized registry and discovery service. A federated or distributed registry remains the target architecture after the centralized stage is working.

## Design Decision

### Decision

Build the network in two major phases:

1. centralized registry first;
2. federated or distributed registry second.

### Why

This keeps the MVP on the shortest path to something useful:
- local hypervisors can already manage work on one node;
- agents need a shared discovery layer before they need a fully decentralized registry;
- wallet, pricing, and rating semantics can be defined before federation complexity is added.

### What This Avoids

This phase intentionally avoids:
- on-chain discovery as a hard dependency for the first working network release;
- peer-to-peer replication before metadata and trust semantics are stable;
- coupling low-level execution logic directly to wallet settlement logic.

## Architecture Layers

### 1. Execution Node

The local hypervisor remains the execution node.

Responsibilities:
- manage local resources;
- manage local provider runtimes;
- track installed bundles and models;
- answer local agent allocation requests;
- expose local operator controls;
- advertise node metadata to the registry.

Each node should publish at least:
- `node_id`
- operator identity
- resources
- supported providers
- installed bundles or models
- `can_host_custom_model`
- pricing in `q per 1kk tokens`
- health and availability state

### 2. Central Registry And Discovery Service

This is the first shared network service.

Responsibilities:
- accept node registration and periodic refresh;
- store node metadata and availability;
- expose discovery APIs for agents, routers, and operators;
- publish pricing and rating metadata alongside capabilities;
- support filtering by workload, provider, model, onboarding capability, and policy.

The registry is not the execution plane.

It should not:
- run inference;
- own provider lifecycle for a node;
- replace the node-local hypervisor scheduler.

### 3. Wallet And Market Layer

This bounded context defines the network economy.

Responsibilities:
- define `q` as a compute unit;
- represent pricing policy;
- record usage and spend events;
- support settlement logic;
- provide wallet-facing accounting interfaces.

The wallet layer should consume usage data from hypervisors or routers, not embed itself into core runtime orchestration.

### 4. Rating And Reputation Layer

This layer publishes trust signals for node selection.

Responsibilities:
- compute node rating inputs;
- store or expose current reputation signals;
- support policy-based routing using trust and price together.

Likely inputs:
- uptime;
- successful task completion rate;
- latency distribution;
- operator reliability;
- dispute or penalty history;
- freshness of status publication.

## Discovery Model

The network should be `network first`.

That means agents should discover execution targets through the registry rather than binding themselves to one hard-coded node.

The discovery response should support:
- listing available nodes;
- listing compatible providers and bundles;
- pricing visibility;
- node rating visibility;
- custom model onboarding visibility;
- policy filtering and sorting.

The local `fit` detail used inside a node is useful for operator diagnostics, but it is not the primary network contract. At network level, discovery should emphasize:
- whether a node can serve a class of work;
- what it costs;
- how trustworthy it is;
- whether it can onboard a new model.

## Pricing Model

Pricing should be expressed in `q`.

The initial unit published by the network should be:
- `q per 1kk tokens`

The design should allow separate rates later for:
- input tokens;
- output tokens;
- audio minutes;
- image generation;
- fixed per-request or per-startup surcharges.

For the first stage, the node should publish enough information for a client to estimate cost before execution.

## Custom Model Onboarding

Nodes may differ in what they are willing or able to host.

The registry must publish whether a node:
- only serves preinstalled models;
- can download and register custom models;
- can run a requested provider family;
- can accept onboarding under operator policy.

The key capability flag for the first phase is:
- `can_host_custom_model`

This should be explicit, not inferred.

## Rating Publication

Rating should be visible in discovery.

The system should support:
- a current node rating;
- an explanation or component breakdown later;
- filtering out unreliable nodes;
- preferring higher-rated nodes when price is similar.

The first release does not need a sophisticated reputation economy, but it must define a stable place in the architecture for one.

## MVP Sequence

### Phase A: Local Hypervisor Completion

Finish the local execution node:
- model install jobs;
- bundle registration from installed artifacts;
- production-ready runtime process execution.

### Phase B: Central Registry

Build the first shared service:
- node registration;
- heartbeat;
- capability publication;
- pricing publication;
- discovery API.

### Phase C: Wallet And Pricing Interface

Add:
- `q` pricing publication;
- usage metering contract;
- wallet-facing settlement interface.

### Phase D: Rating Publication

Add:
- node rating model;
- registry publication of rating;
- routing policy that uses rating plus price.

### Phase E: Federated Or Distributed Registry

After the centralized design is stable:
- define signed node advertisements;
- define replication or federation semantics;
- remove the centralized registry as a single point of coordination.

## Risks

### Risk 1: Mixing Execution And Market Concerns Too Early

If wallet and rating logic are embedded directly into the hypervisor core, the node runtime becomes hard to evolve.

Mitigation:
- keep wallet and reputation as separate bounded contexts;
- integrate through published contracts and events.

### Risk 2: Discoverability Without Freshness Guarantees

A registry is only useful if node state is fresh enough to trust.

Mitigation:
- require heartbeat and status timestamps;
- degrade or hide stale nodes from discovery.

### Risk 3: Overcommitting To Distribution Too Soon

Trying to solve federation before local execution and discovery semantics are stable will slow the project.

Mitigation:
- central registry first;
- federation explicitly planned as a milestone, not forgotten.

## Non-Goals For The Immediate Phase

- fully decentralized registry in the first network release;
- complete on-chain settlement design before discovery works;
- sophisticated slashing or dispute economics before basic rating publication exists.

## Deliverables For Documentation

The repository should expose this plan prominently on GitHub through:
- a root `ROADMAP.md`;
- updated vision links;
- milestone-driven status that is easy to scan without opening deep internal docs.
