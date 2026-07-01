# M2 Centralized Registry And Discovery Design

## Summary

This spec defines the first shared network service above the local AiDN hypervisor.

`M1` already gives us a usable standalone execution node:
- local queue and scheduler;
- local resource admission;
- bundle and provider lifecycle;
- allocation leases;
- install and bundle onboarding;
- local capability discovery.

`M2` adds a centralized registry so agents stop binding to one node directly.

The approved direction is:
- a centralized registry first;
- node-level registration plus bundle-level discovery;
- explicit publication of resources, installed bundles, pricing, rating, and onboarding capability;
- no federation or distributed replication in this milestone.

## Decision

### Selected Option

Build `M2` as `Node Registry + Bundle Discovery`.

The registry stores:
- node metadata;
- heartbeat and freshness state;
- bundle inventory per node;
- pricing and rating signals published with the node;
- discovery indexes for agents and routers.

### Rejected Alternatives

#### A. Node Catalog Only

Rejected because it is too weak for real routing.

It would tell an agent that a node exists, but not which concrete bundle, endpoint, provider, or model is actually usable. That would force a second lookup against the node and duplicate discovery logic across clients.

#### C. Full Market-Ready Registry Immediately

Rejected because it mixes too many bounded contexts too early.

Settlement, disputes, and sophisticated reputation economics should not block the first usable discovery release. Those concerns still need stable fields in the contract, but not full implementation in this milestone.

## Goals

`M2` must let:
- any hypervisor register itself in one shared registry;
- the registry decide whether the node is fresh enough to advertise;
- agents query one discovery API and receive node and bundle candidates;
- operators publish whether a node can host custom models;
- pricing in `q per 1kk tokens` and rating metadata travel with discovery results.

## Non-Goals

`M2` does not include:
- federated or distributed registry replication;
- signed advertisements;
- wallet settlement execution;
- rating computation from historical telemetry;
- global cross-node scheduling or remote runtime orchestration.

The registry is a metadata and discovery plane, not an execution plane.

## Architecture

### 1. Hypervisor Node

Each local hypervisor remains the source of truth for its own execution state.

Responsibilities:
- manage local resources and runtimes;
- manage installed bundles and models;
- expose local allocation and operator APIs;
- publish registry advertisements derived from local state.

The hypervisor does not delegate scheduling to the registry.

### 2. Central Registry Service

This is the new `M2` service.

Responsibilities:
- accept node registration and refresh requests;
- store the latest node advertisement;
- store bundle inventory nested under each node;
- track heartbeat freshness and advertisement visibility;
- expose discovery APIs for agents, routers, and operators;
- filter and sort candidates by capability, freshness, price, and rating.

The registry does not:
- launch providers;
- own node-local resources;
- issue allocations directly against a node.

### 3. Discovery Client

The client can be an agent, router, or operator-side tool.

Responsibilities:
- submit workload requirements;
- inspect compatible nodes and bundles;
- select a target node and endpoint;
- optionally prefer lower price, higher rating, or custom-model support.

### 4. Future Market Layers

Wallet/pricing and rating remain separate bounded contexts.

`M2` only reserves stable fields for them:
- pricing publication;
- rating publication;
- timestamps and metadata needed for later freshness and metering logic.

## Registry Data Model

The registry needs two levels of metadata: node-level and bundle-level.

### Node Advertisement

Each advertisement must contain at least:
- `node_id`
- `operator_id`
- `registry_version`
- `base_url`
- `heartbeat_at`
- `heartbeat_ttl_seconds`
- `status`
- `resources.total`
- `resources.free`
- `providers`
- `can_host_custom_model`
- `pricing`
- `rating`
- `bundles`

Recommended shape:

```json
{
  "node_id": "node-us-east-1a",
  "operator_id": "glinko",
  "registry_version": "m2.v1",
  "base_url": "https://node.example",
  "heartbeat_at": "2026-06-19T18:30:00Z",
  "heartbeat_ttl_seconds": 30,
  "status": "ready",
  "resources": {
    "total": { "cpu": 24.0, "ram_mb": 65536, "vram_mb": 49152 },
    "free": { "cpu": 12.0, "ram_mb": 32768, "vram_mb": 24576 }
  },
  "providers": ["llama.cpp", "ollama", "whisper"],
  "can_host_custom_model": true,
  "pricing": {
    "unit": "q_per_1kk_tokens",
    "input": 14,
    "output": 22,
    "fixed_request": null
  },
  "rating": {
    "score": 0.94,
    "tier": "A",
    "updated_at": "2026-06-19T18:25:00Z"
  },
  "bundles": []
}
```

### Bundle Advertisement

Each published bundle must contain enough information for a client to act without another discovery round-trip.

Required fields:
- `bundle_id`
- `workload_type`
- `provider_type`
- `model_id`
- `endpoint`
- `enabled`
- `status`
- `launch_mode`
- `device_affinity`
- `max_parallel_requests`

Recommended optional fields:
- `pricing_override`
- `rating_override`
- `supports_allocation`
- `supports_queue`

Recommended shape:

```json
{
  "bundle_id": "phi4-local",
  "workload_type": "llm_text",
  "provider_type": "llama.cpp",
  "model_id": "phi-4-mini.gguf",
  "endpoint": "https://node.example/runtimes/phi4-local",
  "enabled": true,
  "status": "ready",
  "launch_mode": "managed_process",
  "device_affinity": "cpu",
  "max_parallel_requests": 1,
  "supports_allocation": true,
  "supports_queue": true
}
```

## Freshness Model

Registry data must degrade when the node stops refreshing.

### Heartbeat Rules

Each registration refresh updates:
- advertisement payload;
- `heartbeat_at`;
- computed expiration time from `heartbeat_ttl_seconds`.

### Freshness States

The registry should compute three states:
- `ready`: heartbeat is fresh and node may appear in normal discovery;
- `stale`: heartbeat exceeded TTL but is still inside a grace window;
- `offline`: heartbeat exceeded grace window and node should be hidden from default discovery.

### Default Discovery Behavior

By default:
- `ready` nodes are returned;
- `stale` nodes may be excluded or returned only when explicitly requested;
- `offline` nodes are excluded.

This avoids advertising endpoints that are no longer safe to call.

## Discovery Contract

The registry needs one primary read API for agents and routers.

### Query Inputs

The query should support:
- `workload_type`
- `provider_type`
- `model_id`
- `bundle_id`
- `can_host_custom_model`
- `max_input_price_q_per_1kk`
- `max_output_price_q_per_1kk`
- `min_rating`
- `include_stale`
- `limit`

Not every field is required in the first release, but the contract should be shaped around these filters.

### Response Shape

The response should group bundles under their node to preserve node-level context.

Recommended shape:

```json
{
  "query": {
    "workload_type": "llm_text",
    "model_id": "phi-4-mini",
    "can_host_custom_model": true
  },
  "nodes": [
    {
      "node_id": "node-us-east-1a",
      "status": "ready",
      "base_url": "https://node.example",
      "rating": {
        "score": 0.94,
        "tier": "A"
      },
      "pricing": {
        "unit": "q_per_1kk_tokens",
        "input": 14,
        "output": 22
      },
      "can_host_custom_model": true,
      "resources": {
        "free": { "cpu": 12.0, "ram_mb": 32768, "vram_mb": 24576 }
      },
      "bundles": [
        {
          "bundle_id": "phi4-local",
          "provider_type": "llama.cpp",
          "model_id": "phi-4-mini.gguf",
          "endpoint": "https://node.example/runtimes/phi4-local",
          "status": "ready"
        }
      ]
    }
  ]
}
```

## Sorting Policy

The registry must support at least one deterministic default ordering.

Recommended default order:
1. `status` freshness
2. `rating.score` descending
3. `pricing.input` ascending
4. `pricing.output` ascending
5. `heartbeat_at` descending

This is intentionally simple and stable for the first release.

More advanced policy weighting can come later.

## API Surface

The first `M2` release should expose:

### Operator / Node APIs

- `PUT /registry/nodes/{node_id}`
  Node registration or refresh with full advertisement payload.

- `GET /registry/nodes`
  Operator-oriented listing of registered nodes.

- `GET /registry/nodes/{node_id}`
  Full advertisement for one node.

### Discovery APIs

- `GET /registry/discovery`
  Main discovery endpoint for agents and routers.

### Internal Or Diagnostic APIs

- `POST /registry/nodes/{node_id}/expire`
  Optional helper for tests only or operator diagnostics.

The exact paths may change to fit repo conventions, but the responsibilities should remain the same.

## Boundary Between Registry, Pricing, And Rating

This boundary needs to stay explicit.

### Registry Owns

- advertisement ingestion;
- heartbeat freshness;
- filtering;
- sorting;
- publication of already-computed price and rating fields.

### Pricing Layer Owns Later

- `q` unit semantics;
- usage metering;
- settlement logic;
- validation of price declarations against policy if needed.

### Rating Layer Owns Later

- score computation;
- source metrics;
- penalties, disputes, or reputation evolution.

In `M2`, the registry only stores and returns pricing and rating fields. It does not calculate their business meaning yet.

## Why Bundle-Level Discovery Is Required

This is the key architectural choice behind option `B`.

If the registry only knows nodes, then discovery clients still need a second request to figure out:
- whether the right model exists;
- which endpoint to call;
- whether custom onboarding is supported for that provider family;
- what a concrete bundle costs.

That weakens the whole point of network-level discovery.

Bundle-level publication keeps clients simple and makes the registry answer operational questions directly.

## Risks

### Risk 1: Stale Metadata Produces Bad Routing

If heartbeat expiration is too weak, agents will get dead endpoints.

Mitigation:
- explicit TTL;
- stale/offline states;
- default exclusion of offline nodes.

### Risk 2: Scope Creep Into Wallet And Reputation Logic

If `M2` tries to solve settlement and scoring deeply, delivery will slow down.

Mitigation:
- publish price/rating fields now;
- keep pricing and rating computation out of the first registry implementation.

### Risk 3: Discovery Query Is Too Weak

If filters only work at node level, clients will still need node-specific probing.

Mitigation:
- publish bundles explicitly;
- filter by workload, provider, bundle, and model.

## Deliverables

The first implementation plan for this spec should produce:
- in-memory registry state for node advertisements;
- node registration and refresh endpoint;
- freshness handling for advertisements;
- discovery endpoint with basic filtering and ordering;
- tests for registration, staleness, and discovery filtering.

That is enough to make `M2` real without dragging in federation, wallet settlement, or advanced reputation logic.
