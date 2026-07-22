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
- A local Wallet Identity registry binds `wallet_id -> Ed25519 public key`,
  persists registrations through snapshot/restore, rejects key rotation and
  records canonical `WALLET_IDENTITY_REGISTER` Ledger operations.
- Wallet Identity bindings now also project into the canonical operator
  overlay and local Registry Object view as stable `wallet_identity`
  objects, so public paid-MVP admission and later replication use the same
  object contract instead of a node-private side table.
- Wallet Identity registration now immediately ingests the matching
  `wallet_identity` Registry Object into the connected local Registry store,
  and public paid-session admission plus `GET /wallets/{wallet_id}/identity`
  can resolve identities from that registry-backed canonical object even if
  the local in-memory binding is no longer present.
- The Registry layer now also rejects conflicting `wallet_identity` objects
  for the same `wallet_id`, both for local store ingestion and for peer node
  advertisements, so split-brain wallet bindings fail closed instead of
  remaining latent until paid admission time.
- The Registry now durably records those `wallet_identity` conflicts as local
  conflict evidence and exposes them through registry/operator conflict views,
  so peer reconciliation has a stable audit trail instead of only a transient
  `409` response.
- Registry peers now also have a minimal `wallet_identity` sync slice:
  export/import endpoints can transfer canonical identity objects plus known
  conflict evidence, while the receiving peer imports compatible bindings and
  rejects conflicting ones without losing the conflict trail.
- Registry peers can now also initiate a pull sync from another peer through
  one bounded `sync-from-peer` call, so identity replication no longer
  requires an external client to manually export and then import the same
  payload.
- Registry peers can now maintain a durable list of known wallet-identity
  peers with last-sync state and run a bounded automated repair pass across
  those enabled peers, so replication no longer depends on one-off manual
  sync calls after every restart.
- The Registry can now also bootstrap that peer inventory directly from live
  `RegistryNodeAdvertisement` entries, exclude the local node and optionally
  run discovery plus repair in one bounded pass instead of relying on
  hand-maintained peer lists.
- The operator view can now generate a bounded wallet-identity reconciliation
  report that groups the current canonical bindings by `wallet_id`, surfaces
  payload/source variants, includes durable conflict evidence and summarizes
  known-peer sync health, so manual resolution work no longer starts from raw
  object dumps and scattered `409` traces.
- Public `POST /api/v1/endpoints/{endpoint_id}/public-mvp-sessions` requires a
  registered Consumer wallet identity, a signed Session-open/funding
  authorization bound to the Endpoint configuration, a currently published
  external-facing Endpoint configuration in `in_sync` state, and a registered
  Endpoint Payment Beneficiary identity before escrow can be locked.
- The integration suite now covers one real public paid path against a live
  `llama.cpp` runtime: signed Endpoint publication, public Session open,
  Runtime execution, Final Usage, signed cooperative Settlement acceptance and
  canonical finalization.
- A Session may bind a Consumer Ed25519 authorization key. For such Sessions,
  cooperative Settlement accepts only a signature over the exact Settlement
  identity, input root, amounts and acceptance time.
- `POST /api/v1/endpoints/{endpoint_id}/mvp-sessions` creates an
  `MVP-0001` Session Contract, locks canonical escrow and records the Funding
  Account hash for local compatibility flows; the legacy float-Q deposit is
  display-only on that path.
- `POST /api/v1/endpoints/{endpoint_id}/mvp-sessions/{session_id}/settlement-preview`
  returns the exact signable Consumer acceptance payload for wallet-bound
  cooperative Settlement, and finalization verifies the signature against the
  same registered Consumer key.
- Snapshot persistence and replay-safe Ledger operation records for that
  canonical economic path.

Still required before public paid-MVP launch:

1. Replicate canonical `wallet_identity` objects into authoritative network
   state before multi-node paid launch, so a public `wallet_id` cannot mean
   different keys on different Hypervisors after cross-node sync; local
   uniqueness, conflict rejection, known-peer repair, registry-node inventory
   bootstrap, bounded peer sync and operator reconciliation visibility now
   exist, but final network-wide conflict-resolution policy still remains.
