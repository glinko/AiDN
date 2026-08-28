# RFC-0051 Checkpoint Acknowledgement And Ledger Hooks Design

## Summary

This spec defines the next accounting slice for AiDN after the current local
`UsageReport + acknowledgement snapshot + session close baseline` foundation.

The repository already has:
- `UsageReport` and `UsageAcknowledgement` models;
- endpoint-level accounting contract snapshots;
- session-level storage for the latest report, latest acknowledgement, and
  `last_accepted_report_sequence`;
- basic mismatch handling when a usage checkpoint is recorded;
- local wallet and ledger-shaped event streams.

What is still missing is the canonical accounting spine required by
`RFC-0051` and needed before `RFC-0060` forced settlement can be implemented
cleanly:
- sequence-linked report history rather than only latest snapshots;
- sequence-linked acknowledgement history;
- an explicit `Last Accepted Checkpoint` object rather than scattered fields;
- explicit acknowledgement timeout handling;
- a canonical accounting read model exposed through the API;
- replay-safe ledger hooks for report, acknowledgement, mismatch, and timeout
  transitions.

Authoritative references:
- [RFC-0051 Usage Reporting and Verification Protocol](../../product/RFC-0051-usage-reporting-and-verification-protocol.md)
- [RFC-0060 Session Failure, Recovery and Forced Settlement](../../product/RFC-0060-session-failure-recovery-and-forced-settlement.md)
- [RFC-0059 Ledger Operation Catalog](../../product/RFC-0059-ledger-operation-catalog.md)
- [M3 Settlement Lifecycle Hardening Design](2026-06-21-m3-settlement-lifecycle-hardening-design.md)
- [Endpoint Session And Payment Flow Design](2026-07-01-endpoint-session-payment-flow-design.md)

## Design Decision

### Selected Direction

Build a `session-first accounting spine` and extend it through API and
ledger/event hooks in that order.

That means:
- the session domain becomes the authoritative owner of report-chain and
  acknowledgement-chain state;
- API handlers only submit and expose canonical accounting transitions;
- ledger hooks record normalized accounting evidence after domain validation,
  instead of trying to derive truth directly from transport payloads.

### Why

This is the smallest full vertical slice that delivers the user's requested
scope without coupling three immature layers at once.

It gives us:
- a deterministic `Last Accepted Checkpoint` baseline;
- a single place where mismatch and timeout semantics live;
- API payloads that reflect domain truth instead of inventing it;
- future-ready evidence for forced settlement without prematurely building the
  full `SESSION_FORCE_SETTLE` engine.

### Rejected Alternatives

#### 1. API-First Accounting Vertical

Rejected because transport would hard-code payload semantics before the session
domain fully defines mismatch, acknowledgement, and timeout behavior.

#### 2. Ledger-First Accounting Vertical

Rejected because it would force protocol-shaped operations onto accounting state
that is still incomplete in the domain layer, increasing rewrite cost later.

#### 3. Keep Latest Snapshots Only

Rejected because `RFC-0051` and `RFC-0060` both depend on auditable sequence
history and a stable uncontested baseline, not only most-recent snapshots.

## Product Goals

This slice must:
- record canonical usage-report history per Session;
- record canonical acknowledgement history per Session;
- compute and preserve a deterministic `Last Accepted Checkpoint`;
- prevent newer unacknowledged usage from silently advancing settlement
  baseline;
- expose accounting state through a dedicated session API surface;
- emit replay-safe ledger hooks for the accounting transitions that future
  forced settlement will need.

This slice must let the system:
- move from `latest snapshot` accounting to `chain + checkpoint` accounting;
- distinguish `latest reported` from `last accepted`;
- freeze accepted baseline during mismatch or acknowledgement timeout;
- audit why a session became mismatch-blocked or force-settlement-ready.

## Non-Goals

This slice does not:
- implement the full `SESSION_FORCE_SETTLE` operation;
- calculate final forced-settlement payouts or refunds;
- add a marketplace-wide remote accounting transport;
- solve all `RFC-0051` capability-specific accounting modes in one step;
- introduce challenge windows or post-settlement reversal semantics;
- redesign the operator dashboard accounting UI.

## Scope Boundary

The central rule for this slice is:

`Settlement baseline advances only through accepted acknowledgement.`

That means:
- recording a new `UsageReport` never changes uncontested settlement by itself;
- mismatches do not rewrite previously accepted checkpoints;
- timeout does not invent a new accepted checkpoint;
- ledger hooks record evidence of transitions, not final economic settlement.

## Current State And Gaps

Current code already includes:
- `aidn_hypervisor.accounting.models.UsageReport`;
- `aidn_hypervisor.accounting.models.UsageAcknowledgement`;
- session fields for latest report and latest acknowledgement snapshots;
- `sessions.service.record_usage_checkpoint()` with basic mismatch behavior;
- endpoint-derived `AccountingContract` snapshots for paid sessions;
- local ledger-like event streams for wallet and session-adjacent flows.

The main gaps are:
- no durable report chain;
- no durable acknowledgement chain;
- no dedicated checkpoint object;
- no explicit `ack_pending` or `force_settle_required` accounting state;
- no dedicated accounting read endpoint;
- no ledger/event contract for accounting transitions beyond local snapshots.

## Architecture

The slice is intentionally split into three layers:

1. **Domain layer**
   - owns accounting truth inside `sessions` and `accounting`;
   - validates report/ack continuity;
   - advances the `Last Accepted Checkpoint`;
   - sets mismatch and timeout-driven accounting state.

2. **API layer**
   - submits reports and acknowledgements into domain services;
   - exposes canonical accounting status and checkpoint view;
   - does not compute baseline or mismatch semantics independently.

3. **Ledger/event hook layer**
   - records replay-safe evidence after domain transitions succeed;
   - preserves hashes, sequence numbers, status, and checkpoint state;
   - prepares future `RFC-0060` settlement and evidence processing.

The dependency direction is:

`accounting models -> session accounting transitions -> API/read model -> ledger hooks`

Not the other way around.

## Domain Model

### UsageReport Chain

`UsageReport` remains the canonical provider-side accounting claim, but this
slice treats it as an element of an append-only session chain rather than only a
latest snapshot.

Required chain properties:
- `sequence` is monotonic and begins at `1`;
- `previous_report_hash` links each report to the previous accepted chain head;
- identical repeated report payloads are idempotent;
- conflicting payloads at the same sequence are an accounting conflict.

### UsageAcknowledgement Chain

`UsageAcknowledgement` becomes a first-class append-only chain aligned to a
specific provider report by:
- `session_id`;
- `sequence`;
- `provider_report_hash`.

Acknowledgement status remains bounded to the currently modeled verification
states:
- `verified`
- `accepted_unverified`
- `statistically_plausible`
- `mismatch`
- `unable_to_verify`
- `unable_to_verify_upstream_usage`

### SessionAccountingCheckpoint

This slice introduces a dedicated internal checkpoint structure containing:
- `last_report_sequence`
- `last_report_hash`
- `last_ack_sequence`
- `last_ack_hash`
- `last_accepted_report_sequence`
- `last_accepted_report_hash`
- `last_accepted_usage_charged_q`
- `mismatch_open`
- `ack_deadline_at`

The checkpoint becomes the canonical read model for session accounting
progression.

### EndpointSession Accounting State

`EndpointSession.accounting_status` expands from:
- `open`
- `mismatch`

To:
- `open`
- `ack_pending`
- `mismatch`
- `force_settle_required`

The MVP does not add a separate `timeout_pending` state. Timeout is represented
by:
- `accounting_status == "ack_pending"`
- an active `ack_deadline_at`

Until timeout expiry promotes the session to `force_settle_required`.

## Session Accounting State Machine

### 1. Record Usage Report

When a new `UsageReport` is recorded:
- the session validates `sequence` continuity;
- the session validates `previous_report_hash` against the current report head;
- if validation succeeds:
  - the report becomes the current report head;
  - `ack_deadline_at` is set from policy;
  - `accounting_status` becomes `ack_pending`;
- if validation fails:
  - `accounting_status` becomes `mismatch`;
  - `Last Accepted Checkpoint` remains unchanged.

### 2. Record Usage Acknowledgement

When a new `UsageAcknowledgement` is recorded:
- it must reference the current report head or a defined idempotent replay of
  the current report head;
- if `verification_status` is one of:
  - `verified`
  - `accepted_unverified`
  - `statistically_plausible`
  then:
  - the acknowledgement becomes the current ack head;
  - `Last Accepted Checkpoint` advances to the acknowledged report;
  - `accounting_status` returns to `open`;
  - `ack_deadline_at` is cleared.
- if `verification_status == "mismatch"`:
  - the acknowledgement is still recorded;
  - `Last Accepted Checkpoint` does not advance;
  - `accounting_status` becomes `mismatch`.

### 3. Acknowledgement Timeout

When the acknowledgement deadline expires without an accepted acknowledgement:
- `Last Accepted Checkpoint` remains unchanged;
- `accounting_status` becomes `force_settle_required`;
- the current report remains recorded but uncontested.

### 4. Session Close

On ordinary close:
- final settlement baseline uses `Last Accepted Checkpoint`;
- unacknowledged newer reports do not silently become accepted usage.

If the session closes while:
- `accounting_status == "mismatch"`; or
- `accounting_status == "ack_pending"` and the acknowledgement deadline has
  expired;

Then close must preserve the accepted baseline and route the session toward the
future forced-settlement path rather than guessing unverified usage.

## API Surface

This slice adds or formalizes four session accounting surfaces.

### 1. POST `/api/v1/sessions/{session_id}/usage-reports`

Accepts one `UsageReport`.

Returns:
- current accounting status;
- current report head summary;
- current checkpoint summary;
- `ack_deadline_at` where applicable.

Error semantics:
- `404` for unknown session;
- `422` for invalid payload;
- `409` for sequence/hash accounting conflict.

### 2. POST `/api/v1/sessions/{session_id}/usage-acknowledgements`

Accepts one `UsageAcknowledgement`.

Returns:
- current accounting status;
- current acknowledgement head summary;
- current checkpoint summary.

Error semantics:
- `404` for unknown session;
- `422` for invalid payload;
- `409` for acknowledgement/report mismatch at the protocol-transport layer.

Domain mismatch remains represented in the session state rather than hidden as a
generic success response.

### 3. GET `/api/v1/sessions/{session_id}/accounting`

Returns the canonical session accounting read model:
- report head summary;
- acknowledgement head summary;
- `Last Accepted Checkpoint`;
- `accounting_status`;
- mismatch summary;
- acknowledgement deadline summary.

This endpoint exists for operator debugging, local reconciliation, and future
remote sync adaptation.

### 4. Task And Session Read-Model Alignment

Existing task/session result payloads that expose `session_accounting` should be
normalized to the same canonical accounting read-model shape used by the
dedicated session accounting endpoint.

This avoids maintaining one public accounting shape for the session API and a
different ad hoc shape inside task results.

## Ledger And Event Hooks

This slice does not implement full protocol-final operations for every
accounting change.

It does introduce stable replay-safe ledger hooks that future settlement logic
can trust.

### Immediate Internal Events

Emit normalized events for:
- `session.usage_report_recorded`
- `session.usage_acknowledgement_recorded`
- `session.last_accepted_checkpoint_advanced`
- `session.accounting_mismatch_recorded`
- `session.accounting_ack_timeout_started`
- `session.accounting_force_settlement_required`

### Required Evidence Fields

Each accounting event should preserve at minimum:
- `session_id`
- `endpoint_id`
- `sequence`
- `report_hash`
- `ack_hash` where applicable
- `previous_report_hash`
- `verification_status`
- `accounting_contract_version`
- `accepted_checkpoint_sequence`
- `accepted_usage_charged_q`
- `evidence_summary`
- `created_at`

### Ledger Hook Boundary

The ledger/event layer in this slice is responsible for:
- auditability;
- replay safety;
- future evidence handoff to forced settlement;
- canonical transition visibility.

It is not yet responsible for:
- final payout/refund calculation;
- challenge windows;
- post-settlement economic reversal;
- full `SESSION_FORCE_SETTLE` execution.

## Implementation Shape

The natural implementation split is:
- `src/aidn_hypervisor/accounting/models.py`
  - add checkpoint model and any report/ack hash helpers;
- `src/aidn_hypervisor/sessions/models.py`
  - expand session accounting status and checkpoint storage;
- `src/aidn_hypervisor/sessions/service.py`
  - own chain validation, acknowledgement application, timeout transition, and
    close-baseline behavior;
- `src/aidn_hypervisor/api.py`
  - expose the dedicated report/ack/accounting endpoints or session subroutes;
- `src/aidn_hypervisor/ledger/service.py`
  - receive normalized accounting transition events;
- `tests/accounting/`
  - model and helper coverage;
- `tests/sessions/`
  - transition coverage;
- `tests/ledger/` and `tests/test_api.py`
  - event emission and API coverage.

## Testing Strategy

### Model Tests

Add or extend tests for:
- `UsageReport` validation;
- `UsageAcknowledgement` validation;
- `SessionAccountingCheckpoint` validation;
- sequence/hash consistency expectations;
- invalid checkpoint combinations.

### Session Service Tests

This is the primary test layer.

Cover:
- first report moves session to `ack_pending`;
- valid acknowledgement advances checkpoint and returns session to `open`;
- mismatch acknowledgement records mismatch and preserves prior accepted
  checkpoint;
- broken report chain produces mismatch without rewriting accepted baseline;
- second valid report after first acceptance creates a new `ack_pending` head;
- acknowledgement timeout promotes the session to `force_settle_required`;
- close with unacknowledged usage keeps settlement baseline at last accepted
  checkpoint;
- repeated identical report submission is idempotent;
- repeated identical acknowledgement submission is idempotent.

### API Tests

Cover:
- `POST usage-reports` happy path;
- `POST usage-acknowledgements` happy path;
- `GET accounting` read-model shape;
- `409` conflict behavior for broken chain continuity;
- invalid payload and unknown-session behavior.

### Ledger Hook Tests

Cover:
- report submission emits `session.usage_report_recorded`;
- accepted acknowledgement emits
  `session.last_accepted_checkpoint_advanced`;
- mismatch emits `session.accounting_mismatch_recorded`;
- timeout emits `session.accounting_force_settlement_required`.

### Success Criteria

This slice is successful when:
- accepted accounting baseline is deterministic and auditable;
- new usage cannot silently advance settlement without acknowledgement;
- mismatch and timeout preserve accepted baseline rather than rewriting it;
- API and task/session read models expose one canonical accounting view;
- ledger hooks preserve enough evidence for the next forced-settlement slice.

## Risks And Mitigations

### Risk: Over-coupling API to domain internals

Mitigation:
- keep API transport thin;
- return read models, not service-internal mutation details.

### Risk: Ledger hooks pretending to be final protocol operations

Mitigation:
- explicitly treat this slice as replay-safe evidence emission only;
- defer full forced-settlement economics to the next slice.

### Risk: Latest snapshot compatibility regressions

Mitigation:
- preserve existing latest snapshot fields where needed as derived summaries;
- add new chain/checkpoint state alongside them;
- normalize old response shapes gradually to the canonical accounting view.

## Exit Criteria

This slice is complete when:
- every session can store report-chain and acknowledgement-chain progress;
- `Last Accepted Checkpoint` is represented explicitly and updated only through
  accepted acknowledgement;
- acknowledgement timeout moves the session into a deterministic
  `force_settle_required` path;
- the API exposes canonical accounting submission and inspection endpoints;
- ledger hooks capture replay-safe evidence for accounting transitions;
- the repository has green tests covering domain, API, and ledger-hook
  behavior for the new spine.
