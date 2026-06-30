# Operator Fleet And Market Dashboard Design

## Summary

This spec defines the first operator-facing control surface for the AiDN hypervisor network.

The dashboard is not a generic admin UI. It is the operator shell for a multi-node hypervisor that:
- manages owned and connected nodes;
- installs and publishes local model offers;
- compares external market offers and endpoints;
- lets the operator decide whether to serve work locally or attach outside capacity.

The approved shell is the `Split Command Center` direction.

That means:
- two top-level modes: `Fleet` and `Market`;
- a hybrid `Home` screen that bridges both modes;
- first priority on `publish/onboard`;
- second priority on `market visibility and external endpoint consumption`.

## Design Decision

### Selected Direction

Build the dashboard as a `Hybrid Split Command Center`.

The interface should feel like a hypervisor control plane first and a compute marketplace second.

The home screen must answer three operator questions at a glance:
1. what can I publish now;
2. what is already live in the market;
3. what should I borrow externally if my own fleet is constrained.

### Rejected Alternatives

#### A. Publish-First Workshop

Rejected as the primary shell because it over-optimizes for onboarding and underexposes the market side of AiDN.

It is still useful as a subflow inside `Fleet`.

#### B. Market-First Terminal

Rejected as the primary shell because it weakens the hypervisor identity.

It makes install, register, publish, and resource orchestration feel secondary, even though those are the operator's core responsibilities.

## Product Goals

The first dashboard release must let an operator:
- see their fleet state across multiple owned or connected nodes;
- install custom models and register bundles without leaving the operator surface;
- price and publish offers into the registry;
- inspect how their offers appear in discovery and market ranking;
- compare external offers by price, rating, readiness, and policy;
- attach external endpoints when local capacity is constrained.

## Non-Goals

The first dashboard release does not include:
- wallet settlement or dispute operations as a primary screen;
- deep historical analytics;
- rating breakdown or reputation forensics;
- federated registry topology views;
- full "why this workload does not fit" diagnostics;
- complex approval workflows across multiple operator roles.

Those concerns are important, but they should not delay the first usable operator surface.

## Information Architecture

The dashboard has three primary screens:

### 1. Home

The hybrid command center.

Purpose:
- bridge fleet operations and market operations;
- show the current operator agenda;
- keep high-value actions one click away.

Permanent blocks:
- `Publish & Onboard`
- `Market Visibility`
- `Fleet Capacity`
- `Operator Controls`

### 2. Fleet

The owned-and-connected infrastructure plane.

Purpose:
- manage nodes, queues, runtimes, and bundle inventory;
- run install and publish workflows;
- monitor resource pressure and runtime readiness.

### 3. Market

The external consumption and comparison plane.

Purpose:
- browse registry offers;
- compare external candidates with local offers;
- attach or lease external endpoints.

## Interaction Model

### Top-Level Modes

The shell should expose:
- `Home`
- `Fleet`
- `Market`

`Home` is the landing screen.

`Fleet` and `Market` are not tabs on one dataset. They are separate operational modes with different mental models:
- `Fleet` is about assets the operator controls directly;
- `Market` is about capacity the operator can consume, compare, or compete against.

### Origin Semantics

Every offer or endpoint shown in operator views should carry one explicit origin:
- `own`
- `connected`
- `external`

This keeps the UI honest about what the operator controls, what a connected remote hypervisor contributes, and what belongs to the wider registry.

## Home Screen Design

The home screen should be dense enough to feel operational, but not so dense that it becomes a telemetry wallpaper.

### Block 1: Publish And Onboard

Must show:
- install jobs in progress or awaiting action;
- draft bundles awaiting pricing or publish;
- live publish count;
- validation or publish warnings.

Primary actions:
- `Install Model`
- `Create Bundle`
- `Set Pricing`
- `Publish Offer`
- `Connect Remote Node`

### Block 2: Market Visibility

Must show:
- which local offers are already live;
- how they rank on price or rating relative to comparable offers;
- attractive external offers the operator may want to attach;
- endpoint readiness and queue/allocation support.

Primary actions:
- `Preview Listing`
- `Compare Offers`
- `Attach Endpoint`

### Block 3: Fleet Capacity

Must show:
- node count;
- free CPU, RAM, and VRAM by node or node group;
- queue pressure;
- pending jobs;
- spillover risk where jobs may need market capacity.

Primary actions:
- `Raise Limits`
- `Pause Queue`
- `Rebalance`

### Block 4: Operator Controls

This is the fast-action layer.

It should expose operator moves without requiring deep navigation:
- publish;
- attach external endpoint;
- reprice bundle;
- connect remote node;
- pause or resume queue;
- adjust runtime or resource policy.

## Fleet Screen Design

The `Fleet` screen should expand local and connected-node management.

Required sections:
- node list with health and connectivity;
- resources summary for CPU, RAM, and VRAM;
- queue pressure and pending jobs;
- install jobs;
- bundle inventory;
- draft and live offers;
- runtime readiness and launch mode.

The operator must be able to:
- inspect a node;
- connect a remote node;
- install a model;
- register a bundle;
- update bundle pricing;
- publish or unpublish an offer;
- adjust basic queue and capacity controls.

## Market Screen Design

The `Market` screen should behave like an offer explorer, not like a raw JSON viewer.

Required capabilities:
- filters by model, workload, provider, price, rating, readiness, and custom-hosting policy;
- candidate list with compare-friendly columns;
- ability to distinguish `own`, `connected`, and `external` offers;
- endpoint attach or lease action;
- visibility into whether a candidate supports queue or direct allocation.

The operator must be able to:
- find cheaper or better-rated alternatives;
- decide whether to keep work local or consume external capacity;
- attach an external endpoint into the operator environment.

## Visual Direction

The selected look is a `hybrid control room`.

It should:
- feel operational and trustworthy;
- keep market data prominent;
- preserve the sense that this is still a hypervisor and not just a marketplace frontend.

Visual characteristics:
- warm neutral background, not dark-mode by default;
- strong card boundaries and grouped control surfaces;
- expressive but restrained accent color for action and publish states;
- dense information hierarchy with clear sections;
- no fake geographical worldview as the main metaphor.

The market emphasis should come from:
- offer cards or compare rows;
- price and rating visibility;
- attach and publish actions;
- origin labels;
- side-by-side local vs external opportunity framing.

## Backend Contract Requirements

The UI must sit on real hypervisor and registry state.

It should not introduce a dashboard-only business model that diverges from the execution plane.

### Fleet Data Sources

The dashboard must read:
- local bundle inventory;
- capability catalog;
- install jobs;
- node pricing and custom-model policy;
- resource availability;
- queue or pending work pressure;
- runtime readiness;
- connected remote node state.

Recommended operator read model:
- `GET /operators/dashboard/fleet`

This endpoint should aggregate existing operator and hypervisor state into one UI-friendly payload.

### Market Data Sources

The dashboard must read:
- registry discovery results;
- flattened `candidates`;
- pricing;
- rating;
- endpoint readiness;
- allocation support;
- queue support;
- provider, model, and plugin identity;
- custom-hosting policy.

Recommended operator read model:
- `GET /operators/dashboard/market`

This endpoint should wrap or adapt existing discovery outputs rather than replace them.

### Publish And Onboard Data Sources

The dashboard must rely on real workflows for:
- artifact install;
- bundle registration;
- pricing declaration;
- advertisement publication or refresh.

Recommended operator flow endpoints should remain grounded in current contracts and add only the missing orchestration state needed for drafts, warnings, and publish status.

## Data Model Extensions

The first dashboard implementation should add a lightweight operator-facing read model with:
- `origin` for offers and endpoints;
- `publish_status` for local bundles or offers;
- `install_status` for model onboarding;
- grouped node summaries for multi-node fleet views.

These fields should describe existing system state, not invent new lifecycle semantics.

## MVP Scope

The first shipping slice includes:
- `Home`
- `Fleet`
- `Market`
- working quick actions and forms for the first operator paths;
- real filters and candidate comparisons;
- real publish and attach flows backed by hypervisor or registry endpoints.

The first shipping slice does not include:
- dedicated `Wallet` screen;
- settlement and dispute UX;
- historical reporting views;
- detailed rating analytics;
- federated registry management UI.

## Recommended Delivery Sequence

Build in this order:

1. add operator dashboard read models for fleet and market;
2. implement the shared shell and home screen;
3. implement `Fleet` operational flows for install, register, price, and publish;
4. implement `Market` comparison and attach flows;
5. iterate on wallet, rating, and history after the operator shell is already useful.

## Roadmap Alignment

This dashboard does not replace the current roadmap.

It turns existing roadmap milestones into an operator-usable surface:
- `M2` discovery becomes operator-visible market inventory;
- `M3` pricing becomes live publish and compare behavior;
- `M4` rating becomes a selection signal inside market views;
- `M5` custom model onboarding becomes the primary fleet-side workflow.

The dashboard should therefore be treated as the operator UX layer across `M2` through `M5`, not as a separate disconnected product.

## Reference Mockup

The approved shell direction is visualized here:

- [operator-market-dashboard-options.html](../mockups/operator-market-dashboard-options.html)
