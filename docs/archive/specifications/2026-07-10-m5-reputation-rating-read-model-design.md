# M5 Reputation And Rating Read-Model Design

## Goal

Add the first computed `M5` reputation layer on top of the existing endpoint-first shell, validation foundation, and publication trust surfaces.

This slice should make trust selection more explicit without introducing a new persistent state model or ledger-owned reputation history.

## Why This Slice Exists Now

The repo already has:

- endpoint publication trust;
- published and live validation summaries;
- market and registry trust aggregation;
- endpoint-first operator shell surfaces;
- basic node `rating` publication in discovery.

What is still missing is a canonical computed trust contract that explains:

- why one node should rank above another;
- how validation and publication posture affect selection;
- how operators inspect trust beyond a single opaque score.

This slice fills that gap by introducing a computed reputation read model and publishing it consistently through registry, market, and operator payloads.

## Scope

This slice adds:

- a dedicated reputation read-model builder layer;
- a computed `reputation` payload published alongside legacy `rating`;
- trust-aware sorting that prefers `reputation.score` over the legacy static rating field;
- operator-facing reputation breakdown surfaces in the dashboard and market inspector.

This slice does not add:

- a persistent reputation state store;
- ledger-backed reputation updates;
- penalty or slashing economics;
- user-configurable weighting policies;
- dispute-aware reputation decay;
- a new validation or settlement protocol.

## Design Principles

- Reputation is computed from facts that already exist in the system.
- The first slice must be deterministic and explainable.
- Legacy `rating` remains available for compatibility during migration.
- Reputation should be a bounded layer, not free-floating UI math.
- Discovery and market ranking should use the same trust contract the operator sees.

## Architecture Boundary

Introduce a dedicated reputation layer as a read-model boundary.

It should not own source-of-truth events. Instead, it should consume existing facts from:

- hypervisor node status and heartbeat posture;
- endpoint publication sync state;
- published validation and certification summaries;
- market and registry trust aggregates;
- basic operational reliability counters that can already be derived from existing runtime or task outcomes.

The layer should compute a normalized `reputation profile` and publish it outward through existing API and registry surfaces.

The existing `service.rating` field remains temporarily valid as:

- a compatibility field for existing consumers;
- an optional baseline input if needed during the transition.

The new computed `reputation` block becomes the canonical trust contract for new ranking and UI surfaces.

## Inputs For The First Formula

The first formula should use only stable, already-available facts.

### 1. Freshness

Inputs:

- node heartbeat freshness;
- node status such as `ready`, `stale`, or `offline`;
- publication freshness where a public trust artifact is expected.

Purpose:

- penalize stale or degraded nodes before price-based selection happens.

### 2. Publication Integrity

Inputs:

- count of published endpoints currently `in_sync`;
- count of endpoints with `local_changes_not_published`;
- count of endpoints with `published_configuration_not_served`.

Purpose:

- reward nodes whose public claims still match what they appear to serve;
- surface drift as a first-class trust problem instead of hiding it inside endpoint details.

### 3. Validation Posture

Inputs:

- `certified_count`;
- `certified_with_issues_count`;
- `validated_count`;
- `pending_count`;
- `attention_count`;
- status histograms already exposed through trust summaries.

Purpose:

- reflect the publicly visible validation and certification posture of published endpoints;
- prefer nodes with stronger published trust artifacts without making validation mandatory.

### 4. Operational Reliability

Inputs:

- simple success or failure aggregates that can already be derived from current task and runtime outcomes;
- basic readiness signals already used by local or registry candidate ranking.

Purpose:

- represent whether the node actually behaves reliably, not only whether it publishes trust artifacts.

## Explicit Non-Inputs For This Slice

Do not include the following in the first reputation formula:

- dispute economics or penalty history weighting;
- wallet settlement history as a trust multiplier;
- latency percentile models that are not yet normalized across providers;
- manual operator score overrides;
- persisted time-decay windows;
- historical profile snapshots.

These can be added later once the first computed reputation layer is already visible and useful.

## Public Reputation Contract

The first canonical reputation payload should look like this:

```json
{
  "score": 0.91,
  "tier": "A",
  "updated_at": "2026-07-10T09:15:00+00:00",
  "components": {
    "freshness": 0.95,
    "publication_integrity": 0.88,
    "validation_posture": 0.92,
    "operational_reliability": 0.84
  },
  "evidence": {
    "node_status": "ready",
    "published_endpoint_count": 4,
    "in_sync_count": 3,
    "drift_count": 1,
    "certified_count": 2,
    "certified_with_issues_count": 1,
    "attention_count": 0
  }
}
```

### Contract Notes

- `score` is the canonical computed trust number used by selection logic.
- `tier` is a human-readable coarse label derived from `score`.
- `components` exposes the internal breakdown for operator inspection.
- `evidence` contains factual counters and statuses used to justify the score.

The contract must remain compact enough to publish through discovery, while still being explainable in dashboard inspectors.

## Publication Surfaces

The computed `reputation` block should be projected into:

### Registry Advertisement

Publish `reputation` alongside legacy `rating` in the node advertisement record.

This keeps old consumers working while making the new canonical trust contract available to updated clients.

### Discovery Candidates

Include `reputation` in:

- node discovery results;
- flattened `candidates`;
- canonical candidate projections used by market and routing logic.

### Operator Dashboard And Market

Expose `reputation` in:

- market node cards;
- market inspector panels;
- remote endpoint inspector;
- local operator trust summaries where node-level trust is shown.

The dashboard should show both:

- the overall `score` and `tier`;
- the component breakdown that explains what is dragging trust down.

## Compatibility Strategy

Do not remove legacy `rating` in this slice.

Instead:

- keep `rating` published for compatibility;
- publish `reputation` as the new canonical block;
- migrate sorting and UI surfaces to prefer `reputation.score`;
- leave tests and consumers room to transition gradually.

If a surface does not yet have a `reputation` payload available, it may temporarily fall back to legacy `rating`.

## Selection And Sorting Changes

The first slice should not add a general-purpose policy engine.

It should only replace the implicit trust number used in ranking.

### Ranking Inputs

Ranking should prefer:

1. freshness and readiness;
2. `reputation.score`;
3. price;
4. existing deterministic tie-breakers.

### Affected Surfaces

- registry discovery ordering;
- canonical candidate ordering;
- market candidate ranking;
- operator-facing comparison tables that currently use `rating.score`.

### What Stays Out Of Scope

- user-defined weighting presets;
- policy DSL;
- custom routing formulas per operator;
- dynamic risk appetite tuning.

## Implementation Shape

This slice should introduce a small dedicated module, for example:

- `src/aidn_hypervisor/reputation.py`

Responsibilities:

- normalize currently available trust inputs;
- compute component scores;
- derive final `score` and `tier`;
- produce the publishable `reputation` payload.

Existing service and registry layers should call this builder rather than duplicating the formula in:

- `service.py`;
- `registry_service.py`;
- `dashboard.py`;
- `api.py`.

## Testing Requirements

The slice should be considered complete only if tests cover:

- component-score calculation from factual inputs;
- tier derivation from score thresholds;
- registry and discovery publication of `reputation`;
- market and dashboard projection of reputation breakdown;
- sorting behavior that prefers `reputation.score` over legacy `rating.score`;
- compatibility behavior where legacy `rating` still exists.

## Definition Of Done

This slice is complete when:

- every node advertisement includes a computed `reputation` block;
- discovery and market payloads expose that block;
- operator-facing trust surfaces show a reputation breakdown;
- ranking uses `reputation.score` as the canonical trust number;
- legacy `rating` remains available for compatibility;
- the behavior is covered by tests and does not require a new persistent state model.

## Follow-Up After This Slice

If this slice works well, the next likely follow-up layers are:

- persisted reputation profiles;
- richer operational metrics such as normalized latency bands;
- penalty and dispute-aware trust inputs;
- ledger- or protocol-backed reputation state transitions.

Those should be separate slices and should not block the first computed reputation layer.
