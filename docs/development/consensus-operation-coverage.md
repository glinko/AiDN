# Consensus Operation Coverage

Last updated: `2026-08-03`

This document is the implementation matrix for the consensus operation
boundary. The normative operation schemas and state transitions remain in
[RFC-0059](../product/RFC-0059-ledger-operation-catalog.md). This matrix
answers a narrower question: which operation types are allowed to enter the
specialized ABCI and deterministic block-execution paths in the current
release profile.

## Production Rule

Validator mode uses the fail-closed profile by default through
`AIDN_CONSENSUS_STRICT_OPERATION_COVERAGE=true` (the application default is
kept permissive for embedded libraries and compatibility tests).

In strict mode, an operation is admitted only when one of these conditions is
true:

- the operation has a specialized deterministic Ledger transition in both
  consensus entrypoints;
- the operation type is an explicitly registered custom handler in the
  deterministic execution engine.

Known operation types without a specialized transition are rejected with:

`consensus operation transition is not implemented: <OPERATION_TYPE>`

Unknown operation types without a custom handler are rejected with:

`consensus operation type is not registered: <OPERATION_TYPE>`

The check runs at transaction admission, proposal validation and finalized
block execution. A rejected operation is not inserted into the mempool, not
recorded in the canonical operation log, and cannot advance a sender sequence.

## Implemented Operations

The following operation types have specialized consensus transitions in both
ABCI and `ExecutionEngine`:

- `CONSENSUS_VALIDATOR_SET_UPDATE`
- `DEVELOPMENT_POOL_ALLOCATE`
- `DEVELOPMENT_REWARD_CALCULATE`
- `DEVELOPMENT_REWARD_PAY_IMMEDIATE`
- `DEVELOPMENT_REWARD_PAY_MATURITY`
- `DEVELOPMENT_REWARD_MARK_UNCLAIMED`
- `DEVELOPMENT_REWARD_CLAIM`
- `DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED`
- `DEVELOPMENT_REWARD_FINALIZE_COMMITMENT`
- `DEVELOPMENT_REWARD_RESERVE`
- `EPOCH_TRANSITION`
- `PENALTY_APPLY`
- `PARTICIPANT_REINSTATE`
- `PARTICIPANT_SUSPEND`
- `REWARD_MINT`
- `REPUTATION_PROFILE_UPDATE`
- `SERVICE_VERIFICATION_COMMIT`
- `SESSION_CHECKPOINT_COMMIT`
- `SESSION_ESCROW_EXTEND`
- `SESSION_ESCROW_LOCK`
- `SESSION_ESCROW_RELEASE`
- `SESSION_FAILURE_EVIDENCE`
- `SESSION_FORCE_SETTLE`
- `SESSION_ACCEPT`
- `SESSION_OPEN`
- `SESSION_SETTLEMENT_ACCEPT`
- `SESSION_SETTLEMENT_CORRECT`
- `SESSION_SETTLEMENT_DISPUTE`
- `SESSION_SETTLEMENT_FINALIZE`
- `SESSION_SETTLEMENT_PARTIAL_FINALIZE`
- `SESSION_SETTLEMENT_PROPOSE`
- `SESSION_SETTLEMENT_READY_COMMIT`
- `SNAPSHOT_COMMIT`
- `STAKE_LOCK`
- `STAKE_RELEASE`
- `UNSTAKE_REQUEST`
- `WALLET_TRANSFER`

`WALLET_TRANSFER` uses the MVP `STANDARD` fee of `10,000 q_atoms` and is
covered by dedicated balance, fee-recycling, insufficient-balance and replay
tests in both execution entrypoints.

`SESSION_OPEN` is a non-economic lifecycle projection. It is accepted only
after a finalized `SESSION_ESCROW_LOCK`, binds the Session Contract, Endpoint
configuration and payment beneficiaries to that Funding Account, and never
debits a wallet or moves a reserve. The lock remains the sole canonical MVP
funding mutation; same-block lock/open dependencies are rejected.

`SESSION_ACCEPT` is also lifecycle-only. It is authorized by the locked
Endpoint Payment beneficiary, requires the exact finalized `SESSION_OPEN`
operation and matching Session/Endpoint hashes, and only records the
acceptance projection. It does not debit the Endpoint or Consumer and cannot
be used to bypass escrow finality.

`REPUTATION_PROFILE_UPDATE` is an evidence-only profile-root transition. It
requires protocol sponsorship, finalized evidence operation references,
fixed-point metric accumulators, the active formula version and a strictly
increasing effective-epoch hash chain. Consensus stores the commitment but
does not calculate scores, apply Reputation events or move Q. Consumers now
have a read-only finality adapter that exposes the root only when an
operation-bound verified consensus finality source confirms the exact update;
missing or mismatched evidence fails closed.

The Registry read-model exposes this boundary through:

`GET /registry/reputation-profiles/{object_id}/finality`

It returns `not_found` when no canonical update exists, `pending_finality`
while the committed operation lacks matching verified evidence, and
`consensus_finalized` only after the adapter succeeds. The pending response
may include the operation identity for polling, but never exposes the
unfinalized profile-root payload as a canonical profile.

The set is exported as `CONSENSUS_APPLIED_OPERATION_TYPES` and is tested
against the protocol catalog. Adding an operation to the catalog without
adding a transition therefore keeps the strict production profile closed.

`SESSION_SETTLEMENT_READY_COMMIT` is an evidence-only predecessor for a
typed Settlement proposal. It commits the immutable Settlement Input roots,
Funding predecessor and beneficiaries, but never moves funds or finalizes a
Session by itself.

## Declared but Not Implemented

These catalog entries remain intentionally outside the current specialized
consensus profile:

- `DEPOSIT_LOCK`
- `ENDPOINT_PUBLISH`
- `EPOCH_TASK`
- `REGISTRY_UPSERT`
- `SESSION_SETTLE`
- `SETTLEMENT_ACCEPT`
- `SETTLEMENT_PROPOSE`
- `VALIDATION_REPORT`
- `VALIDATION_REQUEST`
- `VALIDATOR_STAKE`
- `VALIDATOR_UNSTAKE`
- `DEVELOPMENT_POOL_CARRYOVER`
- `DEVELOPMENT_BOUNTY_CREATE`
- `DEVELOPMENT_BOUNTY_RESERVE`
- `DEVELOPMENT_BOUNTY_RELEASE`
- `DEVELOPMENT_REWARD_CANCEL_UNVESTED`
- `DEVELOPMENT_REWARD_CORRECT`

They may still be used by local compatibility services or prepared as
off-chain/domain records, but a validator configured with the strict profile
must reject them until their canonical transition is implemented and covered
in both entrypoints. A similarly named operation is not treated as an alias:
for example, `SESSION_SETTLE` does not bypass the specialized
`SESSION_SETTLEMENT_FINALIZE` transition.

`DEVELOPMENT_REWARD_CALCULATE` commits a self-contained, activation-bound
calculation as immutable evidence and has no Wallet, reserve, mint or other Q
effect. `DEVELOPMENT_POOL_ALLOCATE` is the second narrow exception: it commits
an immutable reserve record only when a finalized `EPOCH_TRANSITION` authorizes
the exact budget and a finalized calculation is present. `DEVELOPMENT_REWARD_RESERVE`
is the third narrow exception: it binds one exact calculated schedule to a
finalized pool allocation and records the full reward reserve without paying a
Wallet or minting Q. `DEVELOPMENT_REWARD_PAY_IMMEDIATE` is the fourth narrow
exception: it requires finalized calculation, pool and reserve sources, binds
the exact payable payment hash and verified Wallet, and materializes one
source-bound payment record. `DEVELOPMENT_REWARD_PAY_MATURITY` is the fifth:
it additionally requires a finalized epoch transition whose opening epoch has
reached the exact stage boundary, accepts only a reserved maturity stage, and
credits only that stage amount. `DEVELOPMENT_REWARD_MARK_UNCLAIMED` is the
sixth narrow exception: it accepts only an exact calculated `UNCLAIMED` stage
with no Wallet, persists an immutable claim-expiration record, and neither
credits a Wallet nor consumes the reserve. Paid and unclaimed transitions
protect the reserve and allocation through replay/conservation checks and are
not aliases for `REWARD_MINT`. `DEVELOPMENT_REWARD_CLAIM` is the seventh narrow
exception: it requires the finalized unclaimed record, a finalized epoch
boundary inside the immutable claim window, and a valid RFC-0068 signed Wallet
binding. It creates a separate immutable `CLAIMED` record, consumes exactly one
unclaimed stage, credits only the bound Wallet, and rejects duplicate claims;
the original `UNCLAIMED` evidence remains unchanged. After these additions,
the remaining ECO-0007 entries stay in the declared-unimplemented set.
`DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED` and `DEVELOPMENT_REWARD_FINALIZE_COMMITMENT`
are the two implemented additions:
expiry returns one unclaimed stage to carryover availability after a finalized
claim-window boundary, while finalized commitment stores the exact evidence
roots and operation IDs without creating a Q effect. The remaining typed
envelopes require the same activation and commitment binding, but strict
ABCI/Execution rejects them until their monetary transitions are explicitly
approved and implemented.

## Extension Rule

The operation envelope remains extensible. A deployment may register a custom
operation handler in `ExecutionEngine`; strict mode then permits that exact
type through the handler. The handler is deployment-local and does not make
the type a protocol operation. A network-wide operation requires a catalog
entry, deterministic semantics, replay behavior, snapshot behavior and
conformance tests before it can be added to the implemented set.

## Rollout Gate

Before enabling a newly implemented operation on a validator set, the release
must provide:

- matching ABCI and deterministic-execution transitions;
- admission and proposal rejection tests for malformed or unsupported input;
- replay and same-block dependency tests;
- snapshot/restart coverage;
- an update to the operation matrix and RFC-0059 implementation notes;
- a controlled multi-validator drill using the new operation. The current
  drill covers the RFC-0060 failure chain and the finalized
  `SESSION_ESCROW_LOCK` -> `SESSION_OPEN` -> `SESSION_ACCEPT` lifecycle chain
  through public CometBFT RPC.
