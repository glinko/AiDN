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
- Legacy operator metering supports `audio_input_seconds` as a distinct
  observable Whisper-class dimension. A Provider may omit it when no duration
  evidence exists; it is never represented as zero tokens.
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
- A Plugin that declares supported billing units is rejected before execution
  when an Endpoint Accounting Contract requires an undeclared unit or mode.

## Explicitly Unsupported

- Multiple Requests per Session and Usage Checkpoints.
- Deposit extensions, partial finalization, corrections and subjective
  arbitration.
- Provider-metered, proxy-opaque, observable and hybrid variable billing.
- Stateful Runtime migration, automatic Provider failover and postpaid
  collection.
- Automatic bridge from the legacy float-Q Session API to canonical `q_atoms`
  Settlement. That bridge must be explicit, audited and hash-bound.
- Variable audio-duration Settlement on the canonical `q_atoms` path. The
  Settlement Engine can now normalize declared decimal dimensions into integer
  source units (audio seconds become milliseconds) and derive hash-bound terms
  from an Accounting Contract, but no public variable-price Session profile
  binds those terms yet. Fixed-price sessions remain the public paid-MVP
  profile.

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
- That same sync slice now also carries quorum-resolution network objects:
  proposal, approval and finalized resolution records are exported as
  hash-bound identity objects and hydrate local quorum state on import, so
  multi-node repair can propagate more than just raw wallet bindings.
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
- Operators can now also apply an explicit wallet-identity conflict
  resolution by choosing the canonical `object_id` or `payload_hash` to keep.
  That choice is durably recorded, marks prior conflict evidence as resolved
  and makes subsequent wallet resolution use the selected binding through a
  stable local override instead of whichever peer last happened to answer.
- The Registry now also supports a bounded network-resolution workflow:
  operators can create a quorum proposal for one `wallet_id`, and the service
  now derives the authoritative voter node set from the live Registry source
  nodes currently advertising the chosen binding. Requested voter lists must
  match that authoritative set, peer approvals are collected under the same
  policy, and the same local canonical resolution is finalized automatically
  once the configured threshold is met. Each authoritative voter node must
  also advertise `owner_wallet_id`, and that owner wallet identity must
  resolve to the same public key as the node's `operator_id` identity before
  quorum authority is accepted. A local wallet identity governance policy now
  snapshots the active voter-status and quorum-floor rules used by each
  proposal for operator auditability.
- Public `POST /api/v1/endpoints/{endpoint_id}/public-mvp-sessions` requires a
  registered Consumer wallet identity, a signed Session-open/funding
  authorization bound to the Endpoint configuration, a currently published
  external-facing Endpoint configuration in `in_sync` state, and a registered
  Endpoint Payment Beneficiary identity before escrow can be locked.
- The public fixed-price Session amount is derived from the published Endpoint
  `fixed_price` in whole `q_atoms`. A Session request with a different amount,
  an absent fixed price or a price that cannot be represented in `q_atoms` is
  rejected before escrow lock; the Consumer signature cannot override the
  published commercial terms.
- The integration suite now covers one real public paid path against a live
  `llama.cpp` runtime: signed Endpoint publication, public Session open,
  Runtime execution, Final Usage, restart recovery from durable state, signed
  cooperative Settlement acceptance and canonical finalization without a
  second provider execution or payment.
- The same public fixed-price execution and restart/Settlement boundary is
  covered against an attached live `vLLM` Runtime Binding. Provider-reported
  token Usage remains evidence only under `MVP-0001`; payment stays fixed-price.
- Legacy provider-plugin telemetry now preserves partial token observation:
  Ollama, llama.cpp and vLLM omit an unavailable token dimension rather than
  reporting it as zero. Fixed-price `MVP-0001` Settlement remains valid when
  upstream token telemetry is partial or unavailable.
- Ollama has an explicit RFC-0054 `ollama-generate` adapter for native
  `/api/generate` execution and JSONL streaming. It maps emitted token counts
  as Provider-authoritative Usage, records delivered stream bytes locally and
  retains best-effort cancellation semantics when no upstream operation handle
  exists.
- The same public fixed-price execution, restart and cooperative Settlement
  boundary is covered against an attached live Ollama Runtime Binding. The
  compatibility projection explicitly maps the `llm.chat` Capability to the
  legacy `llm_text` scheduler workload, so approved native Runtime execution
  cannot be rejected before dispatch because of a Capability/workload mismatch.
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

0. Bind Registry peer transport to durable authenticated peer identity. The local
   Replicator can retrieve bounded inventories, validate immutable object
   envelopes and project replicated `plugin_release` metadata into the local
   Plugin Directory; its opt-in strict mode requires a fresh Ed25519 peer
   handshake and rejects replayed nonces. Those releases remain locally
   `UNVERIFIED` and cannot install or launch code. Operator-managed peer-key
   authorization is persisted locally, and a key rotation or disablement
   revokes an active replication session. The bound transport session requires
   verified TLS, carries the signed handshake, owns outer-message sequencing
   and requires a fresh handshake after reconnect. The multi-peer listener and
   bounded reconnect/backoff lifecycle are implemented. A controlled two-host
   Linux deployment has verified durable immutable-object replication followed
   by forced server restart, fresh mTLS and Ed25519 authentication, and a
   second inventory exchange. Independent-operator deployment evidence and a
   network-finality source remain required before treating object exchange as
   a public directory authority.

1. Replicate canonical `wallet_identity` objects into authoritative network
   state before multi-node paid launch, so a public `wallet_id` cannot mean
   different keys on different Hypervisors after cross-node sync; local
   uniqueness, conflict rejection, known-peer repair, registry-node inventory
   bootstrap, bounded peer sync, operator reconciliation visibility, local
   conflict resolution, quorum-backed resolution proposals and replicated
   quorum state objects now exist. The composed Hypervisor exposes a peer-pull
   control path that can require the expected remote node, operator and owner
   wallet identities; when those expectations are supplied, it accepts only a
   hash-bound Ed25519 sync envelope and rejects mismatches before importing
   any object. A controlled two-host deployment has exercised both the signed
   import and a rejected mismatched-node attempt. This is transport evidence,
   not network-finality or independent-operator evidence. Proposal and
   approval votes now require Ed25519 signatures verified against the
   registered wallet identity for each voting node's `operator_id`, and
   quorum admission now derives the
   authoritative voter set from the source nodes currently advertising the
   chosen binding. Each authoritative voter node must also advertise
   `owner_wallet_id`, and that owner wallet identity must resolve to the same
   public key as the node's `operator_id` identity. A local wallet identity
   governance policy now exists for voter-status and quorum-floor control.
   Finalized decisions now derive a portable Governance Certificate that
   commits the policy hash, authoritative voter keys, quorum, candidate and
   each signed vote; it is published as a Registry object and re-verified
   before an imported final Resolution affects local identity state. The
   composed Hypervisor also records a `GOVERNANCE_AUTHORIZATION_COMMIT` Ledger
   operation and attaches that commitment to the Certificate. Strict local
   policy can require the quorum Certificate and a locally known Ledger commit.
   A certificate can be revoked only through a second quorum from its original
   voter set; that revocation is retained as Registry evidence, commits
   `GOVERNANCE_AUTHORIZATION_REVOKE` and removes the affected Resolution.
   Operators can retrieve local Ledger proofs for both certificates and
   revocations and compare their deterministic commitment subjects with
   configured Registry peers. The resulting peer report verifies record
   integrity and classifies matching, mismatched, unavailable and invalid peer
   observations, but always reports
   `consensus_finality: false`. Network consensus-finality verification and
   broader network governance remain outside this MVP profile.
