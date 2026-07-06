# Canonical Registry Market Dual Payload Design

## Summary

This spec defines the next migration slice after the canonical service capability overlay.

The selected strategy is a dual-payload registry and market contract.

The repository will preserve the current working legacy discovery path:

- node advertisements with `bundles`
- flattened market `candidates`
- bundle-centric dashboard and routing handoffs

At the same time, the registry, discovery, and market payloads will start publishing canonical protocol objects:

- `services`
- `capability runtimes`
- `compute compatibility mappings`
- `canonical advertisements`
- `canonical candidates`

The immediate objective is to make canonical registry and market data available everywhere that discovery already exists, without breaking current operator dashboard, remote endpoint discovery, or bundle-based execution.

## Problem Statement

The repository already contains a canonical overlay for local operator and service read models.

However, the network-facing discovery surfaces are still centered on:

`node -> bundles -> candidates`

That creates a mismatch:

- the local hypervisor can describe itself in canonical terms;
- the registry and market still expose legacy bundle-first terms as the public network contract;
- future work on registry architecture, marketplace, verification, and reputation would otherwise have to keep translating backward into legacy bundle shapes.

If this continues, the codebase will split into two incompatible public models:

- canonical language inside newer local read models;
- legacy language in registry and market contracts.

That would slow down the migration and make later protocol work harder than it needs to be.

## Product Goal

The goal of this slice is to make registry and market payloads dual-stack.

After this slice:

- every node advertisement exposes both legacy and canonical discovery layers;
- registry discovery returns both legacy bundle-centric candidates and canonical candidates;
- market payloads preserve current fields while adding canonical summaries and canonical candidate streams;
- current operator UI and old clients keep working unchanged;
- future clients can begin routing, comparing, and filtering in canonical terms without waiting for a full backend rewrite.

## Non-Goals

This slice does not include:

- deleting `bundles` from registry advertisements;
- deleting legacy flattened `candidates`;
- rewriting allocation or dispatch to become runtime-first;
- fully migrating remote endpoint attach and proxy workflows to canonical routing;
- replacing current dashboard market tables with canonical-only UI;
- changing payment, validation, settlement, or ledger semantics.

This is a publication and read-model expansion slice, not a full execution-path migration.

## Selected Approach

Use a dual-payload advertisement envelope.

The registry advertisement remains the source node document.

That document keeps the current legacy sections and adds canonical sections beside them.

The discovery service keeps the current output contract and adds parallel canonical output.

The market payload keeps current bundle-centric data and adds canonical read-model data for future UI migration.

This is preferred over a canonical-only switch because:

- the current dashboard and tests already depend on bundle-centric discovery;
- remote endpoint and proxy flows still consume bundle-shaped market rows;
- canonical data can be introduced deterministically from already existing local state;
- the repo can migrate consumers one by one instead of doing a multi-surface flag day.

## Architecture

The architecture for this slice becomes:

`HypervisorService.node_advertisement()`
-> builds legacy registry fields
-> builds canonical registry fields from `canonical_overlay_inventory()`
-> emits one dual payload node advertisement

`RegistryService.discover()`
-> reads dual node advertisements
-> preserves existing legacy node filtering and flattened legacy candidates
-> adds canonical filtering and flattened canonical candidates

`dashboard.build_market_payload()`
-> preserves current `nodes` and legacy `candidates`
-> adds `canonical_candidates`
-> adds `canonical_summary`

The execution path remains unchanged:

`bundle / plugin / runtime process`

The publication path becomes richer:

`node advertisement = legacy compatibility + canonical protocol view`

## Data Contract

### Registry Node Advertisement

`RegistryNodeAdvertisement` keeps these legacy fields:

- `providers`
- `bundles`
- `published_endpoints`
- `resources`
- `pricing`
- `rating`
- `can_host_custom_model`

It adds these canonical fields:

- `canonical_services`
- `canonical_capability_runtimes`
- `canonical_compute_compatibility`
- `canonical_advertisements`

Field intent:

- `canonical_services`
  Node-level protocol services such as `compute`, and later `registry`, `validation`, `consensus`.
- `canonical_capability_runtimes`
  Canonical runtime surfaces that execute capabilities such as `speech.stt` or `llm.chat`.
- `canonical_compute_compatibility`
  Transition mappings back to `bundle / plugin / provider` for old consumers and internal dispatch.
- `canonical_advertisements`
  Public protocol-facing advertisements. In this slice, these are primarily endpoint advertisements derived from already published endpoint state.

### Registry Discovery Query

`RegistryDiscoveryQuery` remains backward compatible and keeps current filters:

- `workload_type`
- `provider_type`
- `model_id`
- `bundle_id`
- `require_allocation_support`
- `require_queue_support`
- `ready_endpoint_only`
- `can_host_custom_model`
- pricing and rating filters

It adds canonical filters:

- `capability_id`
- `runtime_id`
- `advertisement_resource_type`
- `visibility`
- `owner_wallet`

Legacy clients may ignore all new query fields.

Canonical clients may ignore legacy fields when they do not need compatibility routing.

### Discovery Result

`RegistryService.discover()` keeps returning:

- `query`
- `nodes`
- `candidates`

It adds:

- `canonical_candidates`

Legacy `candidates` remain bundle-centric.

`canonical_candidates` are flattened protocol-facing rows derived from canonical advertisements and the related runtime and compatibility records.

Minimum canonical candidate shape:

- `node_id`
- `operator_id`
- `base_url`
- `status`
- `service_id`
- `capability_id`
- `runtime_id`
- `advertisement_id`
- `resource_type`
- `visibility`
- `pricing`
- `rating`
- `can_host_custom_model`
- `published_endpoint_count`
- `trust_summary`
- `legacy_bundle_id`
- `legacy_plugin_id`
- `legacy_provider_type`

### Market Payload

`dashboard.build_market_payload()` keeps:

- `nodes`
- `candidates`

It adds:

- `canonical_candidates`
- `canonical_summary`

`canonical_summary` provides pre-aggregated UI-friendly facts:

- `service_kinds`
- `capability_ids`
- `runtime_count`
- `endpoint_advertisement_count`

## Behavior

### Hypervisor Publication

`HypervisorService.node_advertisement()` remains the single node-level publication entrypoint.

It continues to build:

- resource state
- pricing
- rating
- provider list
- bundle advertisements
- published endpoint summaries

It additionally loads the canonical overlay inventory and converts it into registry-facing canonical sections.

The canonical registry sections must be deterministic functions of current local state.

No separate mutable canonical registry store is introduced in this slice.

### Registry Discovery

Legacy behavior must remain stable:

- old bundle-centric filtering still works;
- old flattened candidates still exist;
- current dashboard market and request spillover previews continue to read the same fields.

Canonical behavior is added in parallel:

- canonical query filters operate over canonical node fields;
- canonical candidates are flattened from canonical advertisements plus linked runtime and compatibility data;
- canonical discovery does not require the caller to inspect legacy `bundles`.

### Market Read Model

The market read model stays dual-stack.

Current bundle-centric operator views continue working.

At the same time:

- the market payload exposes canonical candidate rows;
- the market payload exposes aggregated canonical summary fields;
- UI migration can start showing capability and runtime-driven network views without deleting the current bundle market table.

### Remote Discovery Compatibility

Remote endpoint attach and proxy flows continue to rely on `published_endpoints` and current node advertisement semantics in this slice.

The purpose here is to make canonical metadata available beside those flows so the next routing slice can reuse it.

## Compatibility Rules

The following rules are mandatory:

- `bundles` remain required in node advertisements during this migration slice;
- legacy flattened `candidates` remain required in discovery results;
- canonical fields are additive, not replacement fields;
- absence of canonical data must not break old discovery consumers;
- if canonical overlay sections are empty, registry discovery still works through legacy fields;
- canonical publication must not introduce different pricing or rating semantics than the legacy node record.

## Error Handling

If canonical overlay generation fails for a node:

- the node must still be able to publish a valid legacy advertisement;
- canonical sections should fall back to empty lists rather than poisoning the whole advertisement;
- the failure should remain observable through tests and service-level diagnostics, but not silently corrupt legacy discovery.

If canonical filtering inputs are supplied but the corresponding canonical node sections are absent:

- discovery returns zero canonical matches for that node;
- legacy candidate behavior remains unchanged.

If a canonical advertisement cannot be mapped to a compatibility bridge:

- the canonical candidate may still be emitted;
- the `legacy_*` bridge fields should be `null` rather than fabricated.

## Testing Strategy

The test plan for this slice should cover:

- node advertisement dual publication;
- canonical field shape validation in `RegistryNodeAdvertisement`;
- discovery response containing both `candidates` and `canonical_candidates`;
- stable legacy filtering behavior;
- canonical filtering by `capability_id`, `runtime_id`, and `visibility`;
- market payload canonical summary generation;
- market payload preserving current legacy fields and trust summaries;
- canonical advertisement fallback behavior when endpoint or compatibility data is missing.

Regression focus:

- current operator market tests must keep passing;
- current registry discovery tests must keep passing;
- new tests should assert additive canonical behavior instead of replacing legacy expectations.

## Implementation Notes

The most likely files involved are:

- `src/aidn_hypervisor/registry_models.py`
- `src/aidn_hypervisor/service.py`
- `src/aidn_hypervisor/registry_service.py`
- `src/aidn_hypervisor/dashboard.py`
- `src/aidn_hypervisor/api.py`
- market and registry test modules

The preferred implementation order is:

1. extend registry models;
2. publish dual node advertisement payloads;
3. extend registry discovery and canonical candidate flattening;
4. enrich market payloads;
5. expose the new read models through tests and operator-facing surfaces.

## Success Criteria

This slice is successful when:

- the registry can publish both legacy and canonical node discovery data at once;
- discovery clients can read canonical candidates without giving up legacy compatibility;
- the market payload can support both existing bundle-centric UI and future canonical UI;
- no current operator dashboard or remote discovery regression is introduced;
- future registry and marketplace work can target canonical advertisements and runtime records directly.
