# ECO-0007 Production Reward Batch

This document describes the production-bound execution layer for RFC-0068 and
ECO-0007. It is separate from the Faucet Treasury: development rewards use the
authorized Development Pool and the canonical consensus path.

## Boundary

The production profile does not change the deterministic reward formula. It
binds that formula to:

- `network_id` and `chain_id`;
- a future-effective ECO-0007 activation approval;
- the exact policy hash;
- the `GENERAL_DEVELOPMENT` pool (or another explicitly registered pool);
- an allowlisted operation scope;
- batch-level Q, contribution and operation limits.

The resulting `DevelopmentRewardProductionBatch` is an inspectable,
hash-bound consensus plan. It is not a mint instruction and it does not submit
transactions. Q movement occurs only after the ordered envelopes are accepted
and finalized by the canonical consensus service.

## Artifacts

The implementation provides:

- `DevelopmentRewardProductionProfile` in
  `src/aidn_hypervisor/reward/development_production.py`;
- `DevelopmentRewardProductionBatch` containing the ordered
  `DEVELOPMENT_REWARD_*` envelopes;
- `tools/build-development-reward-profile.py`;
- `tools/build-development-reward-batch.py`;
- `POST /api/v1/contributions/rewards/production-batch` for a planner that
  already holds finalized evidence.

Both builders are fail-closed. They verify signed activation, policy and
commitment hashes, epoch/pool references, operation scope, replay-safe
operation identities and configured limits. They never read private signing
keys and never create a Governance approval.

## Build workflow

1. Governance creates and signs an activation approval whose economic scope is
   `DEVELOPMENT_PAYMENTS`.
2. The operator obtains a finalized epoch transition and its exact pool budget
   reference.
3. Build the profile from the signed approval:

   ```text
   uv run python tools/build-development-reward-profile.py \
     --network-id <network> \
     --chain-id <chain> \
     --effective-epoch <epoch> \
     --activation-approval activation-approval.json \
     --max-batch-q-atoms <limit> \
     --max-contributions <limit> \
     --max-operations <limit> \
     --output production-profile.json
   ```

4. Build the contribution batch from the immutable evidence store, pool input,
   profile and activation approval:

   ```text
   uv run python tools/build-development-reward-batch.py \
     --store contribution-store.json \
     --pool-input pool-input.json \
     --production-profile production-profile.json \
     --activation-approval activation-approval.json \
     --current-epoch <epoch> \
     --source-epoch-transition-operation-id <finalized-operation-id> \
     --pool-budget-reference <budget-reference> \
     --created-at <canonical-timestamp> \
     --output production-batch.json
   ```

5. Inspect `production-batch.json` and verify the batch hash and envelope
   order. A future submission runner must submit one envelope at a time and
   wait for finality of each predecessor before sending the next one.
6. Reconcile every finalized operation against the quorum and verify the
   resulting Wallet payment records. A transport acknowledgement or a single
   node's mempool response is not payment finality.

## Required live evidence before activation

The production roadmap item remains open until all of the following exist:

- a finalized epoch transition on the target chain;
- a signed activation approval accepted by the configured authority quorum;
- finalized RFC-0068 attestations and historical Wallet bindings;
- a profile and batch whose hashes are reproduced independently;
- canonical finality evidence for every ordered operation;
- Wallet balance and reward-record evidence from the validator quorum;
- restart/reconciliation evidence proving that no payment stage can replay.

Until then, the HTTP route and CLI are planning/verification surfaces only.
This prevents a Forge webhook, dashboard caller or local operator process from
becoming an unauthorized Q issuer.

