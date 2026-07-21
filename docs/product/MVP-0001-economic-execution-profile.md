# MVP-0001 Economic Execution Profile

Status: Accepted implementation profile

## Purpose

This profile selects the smallest interoperable subset of RFC-0037, RFC-0044,
RFC-0051, RFC-0053, RFC-0054, RFC-0056 and RFC-0060 for a paid MVP. It is
normative where it narrows a broader RFC. Features not listed as supported are
unsupported, not silently approximated.

## Supported Scope

- One `ESCROW_PREPAID` Session contains one accepted Request.
- Accounting mode is `FIXED_PRICE`. `DETERMINISTIC` is admitted only after its
  exact `q_atoms` bridge is implemented; legacy float-Q Session accounting is
  not that bridge.
- A Session Contract v2 binds `endpoint_payment_beneficiary` and
  `consumer_refund_beneficiary`.
- The Request binds its Session Contract, Endpoint Configuration, Runtime
  Generation, Runtime Configuration Hash and Dispatcher Route Generation.
- A terminal Request emits a Final Usage Report. It may contain unavailable
  dimensions because a fixed price does not require token metering.
- Canonical Ledger state locks `q_atoms` in `SESSION_ESCROW_LOCK`, then uses
  `SESSION_SETTLEMENT_PROPOSE`, `SESSION_SETTLEMENT_ACCEPT` and
  `SESSION_SETTLEMENT_FINALIZE` for cooperative completion.
- Consumer absence may force-settle a completed fixed-price Request only after
  the timeout and only with a final Usage Report, terminal Result evidence and
  no Usage conflict.
- Endpoint unavailability is conservatively settled as zero Endpoint Payment
  and a Consumer refund after the timeout.

## Required Invariants

- `EndpointPayment <= MaximumSessionCharge <= EndpointPaymentReserve`.
- Locked `q_atoms` are conserved as Endpoint Payment, Consumer refund, Network
  Fees and any explicitly retained dispute reserve.
- A proposal, acceptance and finalization bind the same Settlement Input Root.
- An old Route Generation is never delivered to a new Runtime implicitly.
- A Runtime Adapter cannot alter the charge ceiling or deadline.

## Explicitly Unsupported

- Multiple Requests per Session and Usage Checkpoints.
- Deposit extensions, partial finalization, corrections and subjective
  arbitration.
- Provider-metered, proxy-opaque, observable and hybrid variable billing.
- Stateful Runtime migration, automatic Provider failover and postpaid
  collection.
- Automatic bridge from the legacy float-Q Session API to canonical `q_atoms`
  Settlement. That bridge must be explicit, audited and hash-bound.

## Implementation Status

Implemented now:

- Plugin-managed Provider, Model Deployment, Runtime Binding and RFC-0054
  Runtime/Dispatcher generation checks.
- Final Usage enforcement at Runtime terminal transition.
- Runtime-bound Sessions persist one replay-safe terminal evidence record that
  commits the Result hash, Final Usage chain head, Runtime Binding and Runtime/
  Route generation lineage. Settlement cross-checks that record before paying a
  runtime-bound Endpoint.
- Canonical `q_atoms` funding accounts, escrow lock, proposal, acceptance,
  cooperative finalization and the two conservative forced-settlement rules.
- A Session may bind a Consumer Ed25519 authorization key. For such Sessions,
  cooperative Settlement accepts only a signature over the exact Settlement
  identity, input root, amounts and acceptance time.
- Public `POST /api/v1/endpoints/{endpoint_id}/mvp-sessions` creates an
  `MVP-0001` Session Contract, locks canonical escrow and records the Funding
  Account hash; the legacy float-Q deposit is display-only on that path.
- Snapshot persistence and replay-safe Ledger operation records for that
  canonical economic path.

Still required before public paid-MVP launch:

1. Make Consumer Ed25519 authorization mandatory for public Session admission;
   legacy unsigned Sessions remain local-only compatibility behavior.
2. Add an end-to-end smoke test: endpoint publish, session, escrow, request,
   result, final Usage, proposal, acceptance and Ledger finalization.
