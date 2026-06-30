# M3 Operator-Gated Settlement Readiness Design

## Summary

This spec defines the next `M3` slice after settlement lifecycle hardening.

The goal is to finish the pricing and accounting boundary for execution paths
that want stronger wallet and settlement guarantees, without making that
guarantee a hard default for all workloads.

This slice adds:
- a first non-token pricing unit for `speech_to_text` workloads:
  `audio_minute`;
- a derived settlement-readiness profile for bundles and candidates;
- an operator- and agent-controlled routing gate for settlement-ready paths;
- publication of settlement-readiness signals through local catalog and registry
  contracts;
- operator-facing visibility in dashboard policy and market surfaces.

This is still an `M3` slice. It closes accounting and routing semantics before
the roadmap moves on to `M4` rating publication and `M5` onboarding visibility.

## Design Decision

### Selected Direction

Build an operator-gated readiness layer on top of the existing pricing,
provider-usage, catalog, and registry contracts.

That means:
- readiness is derived from bundle workload type, pricing dimensions, and
  provider `usage_contract`;
- bundles remain runnable by default even when they are not settlement-ready;
- agent constraints or operator policy may require settlement-ready execution
  paths;
- local and remote routing consume the same readiness signals.

### Why

This is the smallest slice that:
- gives `whisper`-class workloads a real accounting unit;
- turns `usage_contract` into an actionable execution signal instead of passive
  metadata;
- preserves backward compatibility for existing execution paths;
- prepares later market and rating layers without forcing premature hard gates.

### Rejected Alternatives

#### 1. Observe-Only Readiness

Rejected because it would publish `settlement_ready` metadata but still leave
routers unable to act on it.

That is not enough for agents or operators who explicitly want only
settlement-safe execution options.

#### 2. Hard-Default Production Gate

Rejected because it would break current runnable bundles and force all existing
operators to complete pricing and accounting work before the feature is useful.

That is too disruptive for the current `M3` phase.

#### 3. Dashboard-Only Readiness

Rejected because a visual indicator without routing impact is not a real system
contract.

The routing path, the API surface, and the operator UX must agree on the same
readiness semantics.

## Product Goals

This slice must let the system:
- describe a non-token billable unit for `speech_to_text`;
- declare whether a bundle is settlement-ready for its workload type;
- explain why a bundle is not settlement-ready;
- let an agent require only settlement-ready execution paths;
- let an operator enable the same rule in request and market policy;
- publish these signals through both local and registry-facing contracts.

This slice must let an operator:
- see which bundles are settlement-ready;
- see the reason when a bundle is not settlement-ready;
- choose whether request routing should require settlement readiness;
- preserve current behavior when strict readiness is not desired.

## Non-Goals

This slice does not:
- introduce a hard-default production gate for all execution;
- define rating or reputation semantics;
- define custom model onboarding publication rules;
- add new workload-family pricing beyond `llm_text` and `speech_to_text`;
- redesign settlement correction flows introduced by lifecycle hardening;
- add distributed registry behavior.

## Scope Boundary

The central rule for this slice is:

`settlement_ready` affects routing only when explicitly requested by agent or operator policy.

Everything else in the design follows from that.

## Architecture Overview

The slice has four layers:

1. pricing contract
2. derived accounting profile
3. policy-aware routing gate
4. operator-facing visibility

### 1. Pricing Contract

`RegistryPricing` gains:
- `audio_minute: int | None`

Current pricing dimensions become:
- `input`
- `output`
- `fixed_request`
- `audio_minute`

Token workloads continue using the current `q per 1kk tokens` model.

`speech_to_text` workloads use `audio_minute` as the first non-token billable
dimension in `M3`.

### 2. Derived Accounting Profile

For every bundle, the service derives an accounting profile with at least:
- `usage_contract`
- `billable_dimensions`
- `settlement_ready`
- `settlement_mode`
- `settlement_reason`

This profile is the single source of truth for readiness decisions.

It is computed from:
- workload type;
- provider-declared `usage_contract`;
- available pricing dimensions.

### 3. Policy-Aware Routing Gate

The gate applies in:
- local capability catalog interpretation;
- local bundle selection;
- spillover or market candidate filtering;
- agent-facing capability responses.

The gate is not globally forced.

It activates only when:
- agent request constraints require settlement readiness; or
- operator request policy requires settlement readiness.

### 4. Operator-Facing Visibility

The dashboard must expose:
- readiness status per bundle or candidate;
- readiness reason when false;
- the request-policy toggle that enables settlement gating.

Not-ready bundles should remain visible in operator UX. The system must explain
why they are excluded from settlement-safe routing instead of silently hiding
them.

## Readiness Rules

### `llm_text`

`llm_text` is settlement-ready when:
- the provider contract supports usable usage measurement; and
- token pricing dimensions needed by the workload are present.

Common not-ready reasons:
- `missing_usage_measurement_support`
- `missing_token_pricing_dimension`

### `speech_to_text`

`speech_to_text` is settlement-ready when:
- the provider contract includes the audio billable dimension; and
- `audio_minute` pricing is present.

Common not-ready reasons:
- `missing_audio_minute_dimension`
- `missing_audio_minute_pricing`
- `missing_usage_measurement_support`

### Unsupported Workloads

Any workload type outside the explicitly supported readiness matrix is not
settlement-ready in this slice.

Reason:
- `unsupported_workload_accounting`

## Settlement Mode

This slice keeps `settlement_mode` explicit because routers and operators need
to understand the quality of accounting, not only a boolean result.

Initial modes:
- `strict`
- `best_effort`
- `unsupported`

### `strict`

Used when the provider contract and workload pricing support settlement-safe
accounting and the path can satisfy explicit readiness requirements.

### `best_effort`

Used when the path remains runnable but does not satisfy settlement-safe routing
requirements.

This is the default fallback mode for existing bundles when the gate is not
enabled.

### `unsupported`

Used when the workload family has no supported accounting model in this phase.

## API And Policy Surface

### Agent Request Constraint

`TaskRequest.constraints` gains:
- `require_settlement_ready: bool = False`

When true:
- local execution candidates that are not settlement-ready are excluded;
- spillover or market candidates that are not settlement-ready are excluded.

When false:
- current behavior remains unchanged.

### Operator Requests Policy

Operator requests policy gains:
- `require_settlement_ready: bool = False`

This policy applies to:
- request triage and routing defaults;
- spillover or market routing defaults;
- operator-facing request workspace behavior.

This policy does not override an agent's explicit stricter request.

### Catalog And Registry Publication

Local capability catalog entries and registry bundle advertisements gain:
- `billable_dimensions`
- `settlement_ready`
- `settlement_mode`
- `settlement_reason`

The same meaning must hold in all surfaces.

A registry consumer should not need a second node-local lookup to understand
readiness.

## Dashboard UX

The operator dashboard should show:
- readiness badge;
- settlement mode;
- readiness reason where applicable;
- request-policy toggle for settlement-ready routing.

### UX Rules

- Not-ready bundles remain visible.
- The reason is shown as structured status, not a hidden tooltip-only detail.
- Policy toggles are explicit and reversible.
- Market and local bundle views should use the same labels for the same states.

## Failure Semantics

If settlement gating is enabled and no eligible paths remain:
- routing should fail with a specific reason, not a generic unavailable error;
- the refusal should surface the relevant settlement reason when possible;
- local and remote candidate filtering should be explainable through returned
  metadata.

This slice should prefer reasons that describe the actual accounting gap, such
as:
- `missing_audio_minute_pricing`
- `missing_audio_minute_dimension`
- `missing_token_pricing_dimension`
- `missing_usage_measurement_support`
- `unsupported_workload_accounting`

## Backward Compatibility

This slice must preserve the current system by default.

That means:
- bundles that are runnable today remain runnable when no readiness gate is
  enabled;
- token-based pricing behavior remains intact;
- existing wallet settlement exports remain valid;
- existing request and registry contracts only grow fields rather than silently
  changing semantics.

For `speech_to_text` specifically:
- if `audio_minute` pricing is absent, the bundle may still run by default;
- the bundle is simply marked `settlement_ready = false`.

## Rollout Order

The rollout should happen in three implementation slices inside one shared
feature phase.

### Slice A: Correctness

Add:
- `audio_minute` pricing;
- readiness derivation rules;
- `speech_to_text` accounting classification;
- serialization updates for pricing and readiness metadata.

### Slice B: Routing And API Policy

Add:
- agent request readiness constraint;
- operator request policy flag;
- routing and spillover filtering behavior;
- registry and capability-catalog publication of readiness signals.

This is the first recommended delivery slice that changes runtime behavior.

### Slice C: Operator UX

Add:
- dashboard readiness badges;
- dashboard reasons;
- operator policy toggle in request and market workflow surfaces.

## Testing Requirements

The implementation plan must include tests for:

### 1. Pricing And Readiness Derivation

Verify:
- `audio_minute` pricing serialization;
- readiness derivation for `llm_text`;
- readiness derivation for `speech_to_text`;
- stable reasons for not-ready states.

### 2. Routing Behavior

Verify:
- default execution behavior remains unchanged when gating is disabled;
- local bundle selection respects `require_settlement_ready`;
- spillover or market candidate filtering respects the same flag;
- agent explicit requirements and operator policy compose correctly.

### 3. API And Dashboard Contracts

Verify:
- new policy fields are accepted and persisted;
- capability catalog returns readiness metadata;
- operator-facing surfaces expose readiness state and reason without regressing
  older API fields.

### 4. Registry Publication

Verify:
- bundle advertisements include readiness metadata;
- flattened discovery candidates preserve the same semantics;
- registry consumers see the same readiness interpretation as local consumers.

## Exit Criteria

This slice is complete when:
- `speech_to_text` has a first-class `audio_minute` pricing unit;
- the system can compute settlement readiness per bundle;
- local and remote routing can require settlement-ready paths;
- operators can see and control readiness-aware routing;
- current default execution behavior remains backward compatible.
