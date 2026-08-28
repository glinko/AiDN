# Public Testnet Launch Implementation Roadmap

The ordered implementation and public-launch execution plan is maintained in
[Public Testnet Alpha: Execution Plan](public-testnet-alpha-execution-plan.md).

## Implemented in the first slice

- RFC-0076 local Network Profile model, hashing, verification, atomic
  activation, environment projection, and `aidn network show|verify|use` CLI.
- RFC-0077 deterministic non-emitting participation calculator: 10-minute
  windows, 80% heartbeat-slot presence, 30-minute enrollment, Node Identity
  binding, 1 Q per window, and one 24-hour settlement hash.
- RFC-0077 deterministic treasury transfer batches: one existing
  `WALLET_TRANSFER` per earning Node Identity, settlement/evidence binding,
  replay-stable operation IDs, and treasury-balance preflight.
- Every settlement binds the active program policy hash and the finalized
  source `EPOCH_TRANSITION` operation ID, so a finalized day cannot be silently
  recalculated under different rules.
- Durable payout worker primitive: persists signed batches before submission,
  submits treasury sequences in order, reconciles after timeout/restart, and
  blocks a deterministically rejected batch without skipping a sequence.
- Host-local participation runtime profile: disabled by default, supports
  `inspect`, `dry_run`, and `submit` modes, requires a named protected
  Treasury signer reference rather than key material, and uses the reviewed
  consensus submission/finality adapter.
- Finalized evidence store: accepts only Ed25519-signed heartbeats from the
  Wallet identity canonically bound to the Node by `OPERATOR_WALLET_BIND`.
- `aidn participation verify|calculate` gives operators a non-emitting,
  reproducible review surface for the active policy and one Epoch settlement.
- ECO-0010 default allocation: 60% contribution and 12/12/12/4% permanent
  service pools; ECO-0007 default contribution share updated to 6000 bps.

## Required before public rewards activate

1. Wire the finalized Registry/Consensus bridge to write the evidence store;
   Dashboard observations and mutable Registry advertisements remain ineligible.
2. Add a read-only participation status endpoint and Dashboard Journey card.
   It must show only the protected runtime mode, last finalised source Epoch,
   eligibility/accounting outcome and sanitized errors; it must expose no
   Treasury key, signer material, secret handle value or mutable reward input.
3. Publish the signed `aidn-testnet-1` genesis and public multi-validator
   profile, then package a verified TOML profile in the release.
4. Expose participation status, qualification countdown, eligible windows,
   estimated daily accrual, last finalized payment, and program sunset in the
   Dashboard Journey.
5. Run multi-node acceptance: missing/duplicate/late heartbeat, version skew,
   node restart, day-boundary failover, duplicate settlement, retired/banned
   node, treasury exhaustion, snapshot restore, and Mainnet sunset.
6. Before any economically significant reward programme, harden participation
   evidence beyond self-reported heartbeat: require signed peer/validator
   reachability attestations, bounded endpoint probes, failure-history review,
   and programme-appropriate anti-Sybil signals. These inputs must be bound
   into the final settlement evidence root; Dashboard/Registry observations
   remain advisory.

The Testnet Incentive Treasury must be explicitly funded before step 2 is
enabled. Until the managed worker is enabled, the library can produce verified
transfer batches but cannot collect finalized evidence or submit payments.
