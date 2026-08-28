# Public Testnet Alpha: Execution Plan

**Status:** active implementation plan  
**Scope:** `aidn-testnet-1`, four independent public validators, and the
testnet-only participation programme.  
**Non-goal:** this document does not promise a conversion of Testnet Q into
Mainnet Q, nor does it enable Mainnet economics.

## Outcome

A new operator can install a Hypervisor from a signed release bundle, verify
the same public `aidn-testnet-1` profile as every other node, join the network,
bind a wallet, and see verifiable participation status.  At the end of a UTC
day, a deliberately enabled and funded Testnet Incentive Treasury can settle
earned Testnet Q from finalized, reproducible evidence.

Public activation is gated: the reward worker is disabled until its Treasury
signer, funded wallet, explicit programme configuration, and release profile
have all been reviewed.

## Guardrails

- **Consensus is the authority.** Mutable Dashboard, Registry, local SQLite,
  and a wall-clock scheduler may cache or display participation, but never make
  it eligible on their own.
- **Node identity is the earning subject.** A wallet is its payout destination;
  it is not itself a unit of uptime.
- **No silent money movement.** A payout worker starts disabled, needs an
  explicit Treasury configuration, persists the signed batch before submission,
  and reconciles a restart before using another sender sequence.
- **No secrets in a release or dashboard.** The private Treasury key stays in a
  protected host-local secret store. Only its public identity and balance are
  observable.
- **No local policy forks.** Network identity, genesis hash, protocol version,
  programme policy hash, and settlement source epoch are bound into evidence
  and each payout batch.
- **Testnet programme is temporary.** A programme ID, start point and sunset
  condition are explicit; Mainnet activation disables it rather than carrying
  it over.

## Workstream 1 — Participation runtime

### 1. Canonical participation evidence

Introduce a narrow, signed participation-heartbeat envelope and a consensus
finality bridge.  The bridge accepts a heartbeat only when its operation is
finalized in the active network and its signer matches the wallet identity
canonically bound to the Node Identity.

Acceptance requirements:

1. Reject an unfinalized operation, another network/chain, an unsupported
   protocol version, an invalid signature, or a heartbeat whose signer does
   not match the active binding.
2. Persist the consensus operation ID, operation hash, finalized height/time,
   and original signed heartbeat atomically with the local evidence record.
3. Make duplicate delivery idempotent and never replace canonical evidence
   with a newer mutable Registry observation.
4. Make the finality bridge independently testable with a fake finality source
   before connecting it to the live CometBFT adapter.

### 2. Eligibility and daily settlement

Keep RFC-0077 policy deterministic:

- one 10-minute window;
- a 30-second expected heartbeat cadence;
- at least 80% of slots in a window;
- 30-minute enrollment qualification;
- 1 Testnet Q per eligible window;
- one UTC 24-hour settlement epoch.

The calculation reads only finalized evidence. Its output binds the programme
policy hash and finalized `EPOCH_TRANSITION` ID. It produces a reviewable
allocation first, not a payment.

### 3. Managed payout worker

Wrap the existing durable payout primitive in a host-managed service:

1. Read an explicit `testnet-participation` runtime configuration.
2. Refuse to start unless `enabled = true`, the profile verifies, the
   programme is active, the Treasury public identity matches configuration,
   and the protected signer is available.
3. On a finalized daily transition, calculate, persist, and expose a proposed
   batch. In `dry_run` it stops there.
4. In `submit` mode, preflight balance, submit in sender-sequence order, and
   reconcile uncertain submission before continuing after a restart.
5. Never retry a deterministically rejected transfer as a new payment; mark the
   batch blocked for explicit operator review.

### 4. Operator visibility

Expose a read-only API projection for: programme state, current qualification
countdown, observed and eligible slots, estimated accrued Q, last finalized
settlement, and any blocked reason.  Dashboard work starts only after this API
is stable, so UI does not become a parallel policy implementation.

## Workstream 2 — Public release package

1. Produce a versioned release manifest with source revision, build artefact
hashes, public Network Profile hash, and genesis hash.
2. Include the verified `aidn-testnet-1` TOML and genesis in a release bundle;
operator bootstrap must verify both before service start.
3. Add a public-node preflight for Ubuntu version, CPU/RAM/disk, time sync,
open P2P port, firewall, DNS/reverse proxy/TLS requirements and unsupported
platforms.
4. Publish a short joining guide and an operator recovery guide. The installer
must make no claim that a node is publicly reachable until external reachability
has been verified.

## Workstream 3 — Immutable network release hardening

1. Collect four validator consensus public keys using the existing safe
genesis tool; never copy validator private keys.
2. Build the four-validator genesis offline, review its validator set and
hash, then distribute the identical immutable file.
3. Create a public profile with the four public persistent peers and a
bootstrap/state-sync plan. Keep user-local ports and API exposure separately
configurable.
4. Run a checkpoint ceremony: every validator reports matching chain ID,
genesis hash, app hash, validator set, and peer connectivity before public
announcement.

## Workstream 4 — Live alpha launch

1. Provision four supported Ubuntu 24.04 VPS instances with public IPv4,
stable DNS, adequate storage, and an explicit firewall policy.
2. Install the same verified release and profile; bootstrap wallets, Node
Identities and browser pairing through the normal operator flow.
3. Bring up consensus, establish P2P, prove independent operator access, and
record the first checkpoint.
4. Run participation in observe-only mode for at least one daily epoch.
5. Compare the reproducible allocation across nodes; run duplicate, late,
missing, restart, treasury-exhaustion and restoration drills.
6. Fund the Testnet Incentive Treasury, make a recorded approval, enable
`dry_run`, review a day, then enable submission for a limited monitored period.

## Ordered implementation backlog

| Order | Deliverable | Exit condition |
| --- | --- | --- |
| 1 | Finalized-heartbeat bridge | Canonical evidence is durable, idempotent and rejects mutable/unfinalized input. |
| 2 | Managed payout runtime | Disabled-by-default service supports inspect, dry-run, submit and restart reconciliation. |
| 3 | Participation status API | One source of truth is ready for Dashboard Journey. |
| 4 | Release manifest/preflight | A fresh public Ubuntu host can verify exactly what it will run. |
| 5 | Launch ceremony scripts | Four public validators can build and verify one immutable network. |
| 6 | Observe-only network drill | Independent nodes reproduce the same daily allocation. |
| 7 | Controlled reward activation | Explicitly funded Treasury makes reviewed Testnet-only payouts. |

## Current implementation point

The deterministic policy calculator, signed heartbeat format, SQLite evidence
store, persistent payout state machine, consensus submitter/finality adapter,
and disabled-by-default runtime profile already exist. The next active slice
is the service-lifecycle bridge: resolve the protected signer, invoke the
runtime only after the canonical daily transition, and expose its read-only
status. Items 3–7 remain deliberately inactive until the preceding exit
conditions are met.
