# ECO-0007 Simulation Profile

Status: simulator plus source-bound payment/unclaimed consensus slice

The executable simulator calculates a bounded development reward proposal from
finalized RFC-0068 evidence without writing the Ledger or creating a
`REWARD_MINT` operation. The separate strict consensus slice accepts explicit
`DEVELOPMENT_REWARD_PAY_IMMEDIATE` and `DEVELOPMENT_REWARD_PAY_MATURITY`
transitions only after their finalized source predecessors. Immediate payment
credits the exact verified Wallet amount from the reserved stage. Maturity
payment additionally proves a finalized epoch boundary for stage one or two.
`DEVELOPMENT_REWARD_MARK_UNCLAIMED` records an exact no-Wallet stage with a
claim-expiration epoch; it does not credit a Wallet or consume the reserve.
`DEVELOPMENT_REWARD_CLAIM` consumes that immutable stage only after a valid
RFC-0068 signed Wallet binding and credits the bound Wallet exactly once. All
four transitions remain distinct from `REWARD_MINT`.

## Fixed-Point Profile

- `1 Q = 1,000,000 q_atoms`.
- `1 CU = 1,000 milli-CU`.
- Development Share defaults to `500 / 10,000` (5%).
- Security reserve defaults to 15% of the base Development allocation.
- Documentation reserve defaults to 5% of the base Development allocation.
- Ordinary contribution cap defaults to 20% of one epoch base allocation.
- Automatic contributor cap defaults to 35% of one epoch base allocation.
- Reward stages default to 40% immediate, 30% maturity stage one, and 30% maturity stage two.
- Maturity boundaries default to merge epoch +4 and +12.

All proportional allocations use floor values followed by largest-remainder
allocation with lexical ID tie-breaking. No binary floating-point arithmetic
is used.

## Pool Flow

```text
Distributable epoch emission
  -> DevelopmentBaseAllocation
  -> + carryover + grants + returned rewards
  -> - security reserve
  -> - documentation reserve
  -> - existing maturity reserve
  -> - approved bounty reservations
  -> contribution budget
  -> capped and normalized contribution rewards
  -> immediate schedule + maturity reserve + carryover
```

The simulator records contributor-cap overflow and role-allocation remainder
as uncommitted value. It does not silently redistribute those atoms to other
contributors. Carryover is capped at `base allocation * maximum carryover
epochs`; excess is explicitly reported as returned to the emission reserve.

`UNCLAIMED` Wallet state changes the payment state in the proposal only. It
does not redirect the reward or fabricate a substitute Wallet.

## Run the Harness

With no arguments the tool runs a deterministic example:

```powershell
.\.venv\Scripts\python.exe tools\simulate-development-rewards.py
```

For a custom scenario, provide JSON with `pool`, optional `policy`, and a
`contributions` array. The result can be written to a file:

```powershell
.\.venv\Scripts\python.exe tools\simulate-development-rewards.py `
  --input .\simulation-input.json `
  --output .\artifacts\development-reward-simulation.json
```

The output must contain:

```json
{
  "simulation_only": true,
  "emits_q": false,
  "ledger_writes": false
}
```

The `calculation_root` commits policy, pool state, allocation, schedules, and
payment-state evidence. `verify_integrity()` recomputes the same root.

## Launch Simulation Matrix

The executable launch matrix is available with:

```powershell
.\.venv\Scripts\python.exe tools\simulate-development-reward-scenarios.py `
  --output .\artifacts\eco-0007-launch-matrix.json
```

It runs the pre-activation economic profiles required by ECO-0007:

- low contribution volume;
- one dominant contributor;
- many small contributors;
- one very large PR;
- PR fragmentation and Contribution Group anti-splitting;
- reviewer allocation and Known Control Group cap;
- high security reserve;
- inactive epoch;
- oversubscribed pool;
- high carryover;
- returned unclaimed rewards.

Every scenario records an input hash, calculation root, conservation/cap
invariants, and a result hash. The report is deterministic and fails closed
if any invariant is false.

The focused unit tests additionally cover:

- low demand and carryover;
- oversubscribed normalization;
- contribution and contributor caps;
- reserved maturity and bounty exposure;
- unclaimed Wallets;
- invalid policy and insufficient pool;
- milli-CU conversion;
- deterministic calculation roots.

The matrix is evidence for policy review, not approval. It does not create Q,
call a Wallet, write the Ledger, or authorize a `REWARD_MINT` operation. Live
payment remains unavailable to the simulator and is limited in consensus to
the separately approved, source-bound immediate, maturity and unclaimed-stage
profile.

The next activation step is not a hidden transfer path. It requires an
approved ECO-0007 parameter set and an explicit Governance activation gate
bound to that policy hash. Maturity payment, unclaimed-stage recording,
Wallet claim, expiry-return and finalized evidence closure are now covered;
correction and the remaining bounty/carryover transitions still require
separate consensus transitions with replay/conservation tests.

## Governance Activation Gate

`aidn_hypervisor.reward.development_activation` implements the first half of
that boundary. `DevelopmentRewardActivationApproval` binds:

- the exact `DevelopmentRewardPolicy` hash;
- an effective epoch;
- the eligible Governance authority public keys;
- a unique quorum threshold;
- distinct Ed25519 approval signatures.
- an optional signed rollout profile with a future effective epoch and caps for
  epoch reward atoms, contribution count and optionally one contributor's
  reward.

`DevelopmentRewardActivationGate.assert_active()` checks the approval against
the exact `DevelopmentRewardCalculation`. It rejects missing approval,
revocation, policy mismatch, premature epochs, invalid quorum, tampered hashes,
and invalid signatures. It returns an auditable activation decision only; it
does not call a Wallet, Ledger, epoch transition, or `REWARD_MINT` operation.

The gate is therefore a fail-closed prerequisite for a future Ledger adapter,
not an activation of development rewards. No live Q distribution is permitted
until Governance publishes and accepts the corresponding approval object.
When a rollout profile is present, the exact calculation is rejected before
commitment creation if it exceeds any active cap. The profile is included in
the signed activation identity, so a local operator cannot widen the rollout
after quorum approval.

## Dry-Run Commitment

`build_development_reward_commitment()` produces a compact, deterministic
evidence object over the policy, pool, allocation, schedule, and payment-state
roots. It can be marked `ACTIVATION_VERIFIED` only when supplied with a valid
activation decision bound to the same calculation root and policy hash. The
commitment remains explicitly:

```json
{
  "simulation_only": true,
  "emits_q": false,
  "ledger_writes": false
}
```

This is suitable for review artifacts and future consensus-test fixtures. It
is not a Ledger commitment, does not reserve maturity funds, and cannot be
used as a substitute for the future authorized distribution operation.

## Reserved Ledger Operations

The ECO-0007 operation names are registered in the Ledger catalog. The typed
builder in `reward/development_operations.py` requires the activation approval
and commitment to bind to the same policy and calculation. The
`DEVELOPMENT_REWARD_CALCULATE` envelope is now accepted by strict consensus as
an immutable, self-contained evidence commit; it performs no Q effect.
`DEVELOPMENT_POOL_ALLOCATE` is also accepted, but only as a source-bound
reserve record. It must reference a finalized prior-block `EPOCH_TRANSITION`
budget and a finalized prior-block calculation, and its activation approval
must explicitly authorize the `POOL_ALLOCATION` or `DEVELOPMENT_RESERVES`
economic effect profile. The allocation remains fully available and does not
credit a Wallet or mint Q. `DEVELOPMENT_REWARD_RESERVE` is also accepted when
it references finalized calculation and pool-allocation operations and binds
one exact reward schedule; it records a bounded reserve without a Wallet or Q
 effect. `DEVELOPMENT_REWARD_PAY_IMMEDIATE` is accepted only with finalized
calculation, pool and reserve predecessors, an exact payable payment hash and
an explicit verified Wallet binding. `DEVELOPMENT_REWARD_PAY_MATURITY` uses the
same source binding but requires a finalized `EPOCH_TRANSITION` whose opening
epoch has reached the payment's stage-one or stage-two maturity boundary and
accepts only the `RESERVED` stage state. Each immutable payment record carries
the post-payment reserve/allocation view, protects `(reserve_id, payment_hash,
stage)` against replay, and credits no other amount. Pool carryover, bounty,
and correction envelopes remain `DECLARED_UNIMPLEMENTED` and are rejected.
`DEVELOPMENT_REWARD_MARK_UNCLAIMED` uses the same finalized sources,
accepts only an `UNCLAIMED` payment with no Wallet, records a stable
claim-expiration epoch, leaves the reserve and Wallet unchanged, and rejects
duplicate stage identities. `DEVELOPMENT_REWARD_CLAIM` then requires that
unclaimed record, a finalized epoch boundary inside the claim window and an
RFC-0068 signed Wallet binding; it creates a separate immutable claim record,
consumes exactly one stage and credits only the bound Wallet. No operation is
treated as a `REWARD_MINT` alias. `DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED`
requires a finalized epoch boundary after the immutable claim window and
returns one unclaimed stage to carryover availability without crediting a
Wallet. `DEVELOPMENT_REWARD_FINALIZE_COMMITMENT` closes the exact finalized
evidence set through source IDs and roots; it is audit-only and has no Q effect.
