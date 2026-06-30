# M3 Settlement Lifecycle Hardening Design

## Summary

This spec defines the next wallet and settlement slice for AiDN after the current
`grace / dispute / closed` allocation finalization workflow.

The goal is to make settlement events operator-correctable without mutating the
underlying usage ledger.

This slice adds:
- an explicit `hold` settlement state;
- operator `hold` and `release` actions;
- a reconcile correction journal;
- separate `base` vs `effective` settlement totals;
- replay-safe export of settlement corrections.

This is a backend-first slice. It does not add a new dashboard workflow yet.

## Design Decision

### Selected Direction

Build a `hold + correction journal` layer on top of the existing allocation
settlement event model.

That means:
- usage events remain immutable;
- settlement events remain the operator-facing aggregate for financial state;
- corrections are append-only journal entries that adjust settlement-facing
  totals without rewriting historical usage records.

### Why

This is the smallest slice that closes a real operator reconcile workflow.

It supports:
- pausing settlement when accounting is uncertain;
- applying an explicit settlement correction;
- releasing the event back into `grace` or directly into `closed`;
- preserving a durable audit trail for every correction.

### Rejected Alternatives

#### 1. Hold Without Corrections

Rejected because it only pauses settlement and still leaves operators with no
system contract for resolving accounting mismatches.

#### 2. Full Settlement State Machine Rewrite

Rejected because it would mix settlement hardening with broader routing,
reputation, and market concerns. That is too wide for the current M3 slice.

#### 3. Mutable Usage Ledger

Rejected because usage history should remain the immutable factual record.
Settlement-facing corrections belong in a separate audit stream.

## Product Goals

This slice must let an operator:
- stop an allocation settlement event from auto-closing;
- see the difference between raw metered spend and corrected settlement spend;
- apply a settlement correction without modifying recorded usage events;
- release a held settlement back into the normal lifecycle;
- export correction history through a replay-safe stream.

## Non-Goals

This slice does not:
- add a new settlement UI flow in the operator dashboard;
- expose correction signals to registry discovery or routing;
- define the non-token pricing unit for `whisper`-class workloads;
- change node rating or reputation semantics;
- add signed settlement batches or checkpoint digests.

## Scope Boundary

The central rule for this slice is:

`Usage history stays immutable. Settlement state becomes operator-correctable.`

That means:
- raw usage events remain append-only;
- settlement events may change state and effective totals;
- every correction must be separately journaled and exportable.

## Information Model

AiDN already has three related wallet artifacts:
- usage events;
- allocation activation events;
- allocation finalization events.

This slice adds a fourth artifact:
- allocation settlement correction events.

### Source Of Truth Split

- usage events answer: `what was metered`
- settlement events answer: `what is currently eligible for settlement`
- correction events answer: `why the settlement-facing total differs from raw metering`

This split is required for auditability.

## Settlement State Machine

### Settlement Status

Expand settlement status from:
- `grace`
- `closed`

To:
- `grace`
- `hold`
- `closed`

### Dispute Overlay

Keep dispute as a separate overlay:
- `none`
- `open`
- `resolved`

`hold` is not a replacement for dispute. It is a settlement control state.

### State Transitions

- allocation `release` or `expire`
  - creates a settlement event in `grace` or directly `closed`, depending on
    grace policy
- `grace -> closed`
  - automatic transition after the grace window expires
  - only when there is no hold and no open dispute
- `grace -> hold`
  - manual operator action
  - or automatic hold caused by dispute open / strict-accounting settlement block
- `hold -> grace`
  - operator release when the event should continue through reconcile window
- `hold -> closed`
  - operator release when reconcile is complete
- `closed -> hold`
  - allowed for late accounting review or settlement correction

### Automatic Hold Rules

The first implementation slice should auto-hold on:
- dispute opened on a settlement event;
- strict-accounting blocked settlement conditions.

Everything else remains a manual operator decision.

### Automatic Close Rules

Automatic grace-to-closed advancement must not run when:
- `settlement_status == "hold"`
- `dispute_status == "open"`

## Correction Model

Corrections are append-only journal records.

Each correction record should contain:
- `correction_id`
- `sequence_id`
- `event_id`
- `allocation_id`
- `created_at`
- `created_by`
- `reason`
- `base_usage_total_q`
- `effective_usage_total_q_before`
- `effective_usage_total_q_after`
- `delta_q`
- `annotations`
- `resolution_note`

### Base Versus Effective Totals

Settlement events should expose:
- `base_usage_total_q`
- `effective_usage_total_q`

Definitions:
- `base_usage_total_q` is the raw settlement total derived from metered usage
- `effective_usage_total_q` is the operator-approved settlement total after any
  corrections

This allows operators and downstream consumers to compare raw metering with
settlement-facing output without replaying every correction entry.

## Data Model Changes

### Settlement Event Fields

Extend allocation settlement events with:
- `settlement_status: grace | hold | closed`
- `hold_reason: str | None`
- `hold_source: manual | dispute | strict_accounting | system | None`
- `hold_started_at: str | None`
- `hold_released_at: str | None`
- `base_usage_total_q: float`
- `effective_usage_total_q: float`
- `correction_count: int`

### Service Journal Events

Each operator write action should also emit a normal service journal event:
- `wallet.allocation_hold_started`
- `wallet.allocation_hold_released`
- `wallet.allocation_correction_applied`

These events are not a replacement for the correction export stream. They are
for service-local audit continuity.

## API Design

This slice is backend-first and should add four operator-facing endpoints.

### 1. Hold Settlement Event

`POST /operators/wallet/allocations/{event_id}/hold`

Purpose:
- move an allocation settlement event into `hold`

Request body:
- `reason`

Behavior:
- if the event is already in `hold`, reject with conflict in this slice

### 2. Release Settlement Event

`POST /operators/wallet/allocations/{event_id}/release`

Purpose:
- release a held settlement event back into lifecycle flow

Request body:
- `reason`
- `target_status: grace | closed`

Behavior:
- reject when the event is not in `hold`
- reject `closed` target when open dispute or unresolved settlement block
  forbids closure

### 3. Apply Settlement Correction

`POST /operators/wallet/allocations/{event_id}/corrections`

Purpose:
- create a correction journal entry and update
  `effective_usage_total_q`

Request body:
- `reason`
- `effective_usage_total_q`
- `annotations`
- `release_after_apply: bool`
- `release_target_status: grace | closed | null`

Behavior:
- allowed only when the event is in `hold`
- must not mutate usage events
- must append a correction record and increment settlement correction count

### 4. Export Settlement Corrections

`GET /operators/wallet/allocations/corrections/export`

Purpose:
- export correction records through a replay-safe stream

Contract:
- use the same cursor envelope style as usage, activation, dispute, and
  settlement export streams

## Error Handling

The system must reject invalid transitions.

Required conflicts:
- hold an event already in `hold`
- release an event not in `hold`
- apply correction to an event not in `hold`
- close an event with `dispute_status=open`
- close an event still blocked by strict-accounting settlement policy
- apply a correction with negative `effective_usage_total_q`

Required not-found behavior:
- missing settlement event returns `404`

Required invariants:
- usage events remain immutable
- correction journal is append-only
- auto-close must skip held settlement events

## Testing Requirements

The first implementation pass must cover:

### Service State Machine

- `grace -> hold`
- `hold -> grace`
- `hold -> closed`
- `closed -> hold`
- held events do not auto-close during reconcile pass

### Service Correction Behavior

- correction only allowed in `hold`
- correction updates `effective_usage_total_q`
- correction does not rewrite raw usage history
- correction increments settlement event metadata and emits journal entry

### API Contracts

- hold endpoint returns updated settlement event
- release endpoint returns updated settlement event
- correction endpoint returns updated settlement event plus correction record
- invalid transitions return `409`

### Export Contracts

- correction export is replay-safe and ordered by `sequence_id`
- settlement export reflects updated `effective_usage_total_q`
- held or disputed events do not auto-close on export/reconcile access

## Rollout Standard

This slice is acceptable only if:
- operators can freeze settlement events intentionally;
- operators can apply settlement corrections without mutating usage history;
- correction history is exportable with replay-safe cursors;
- auto-close no longer overrides active hold state.

## Next Step After This Slice

After settlement lifecycle hardening is complete, the next M3 work should be:
- define the first non-token pricing unit for `whisper`-class workloads;
- decide runtime enforcement boundaries for provider `usage_contract`;
- expose accounting readiness signals for later router and registry use.

## Related Documents

- M3 plan: [2026-06-19-m3-wallet-pricing-and-usage-metering.md](../plans/2026-06-19-m3-wallet-pricing-and-usage-metering.md)
- network architecture: [2026-06-19-network-registry-wallet-rating-design.md](./2026-06-19-network-registry-wallet-rating-design.md)
- roadmap: [../../../ROADMAP.md](../../../ROADMAP.md)
