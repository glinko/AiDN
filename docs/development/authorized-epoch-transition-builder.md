# Authorized Epoch Transition Builder

This tool prepares the next economic-network artifact after the validator
authority boundary rollout. It is an offline builder only.

## Safety boundary

`tools/build-authorized-epoch-transition.py`:

- reads a public protocol-authority policy;
- reads a caller-supplied canonical transition payload;
- reads external Ed25519 private-key files only for signing;
- verifies that every private key controls the declared authority public key;
- requires the configured threshold;
- validates the payload through the same Ledger epoch-transition validator;
- writes a signed envelope for later consensus submission.

It does **not**:

- generate or select authority keys;
- call CometBFT;
- broadcast a transaction;
- mutate local Ledger state;
- create Q or open a reward pool.

Private key files must remain outside the repository and must be protected by
the operator's secret-management procedure. The tool prints only operation ID,
policy hash, signer IDs and output path.

## Policy artifact

The policy is public and must be approved before distribution:

```json
{
  "version": "aidn.protocol-authority.v1",
  "threshold": 2,
  "authorities": {
    "governance-1": "ed25519:<32-byte-public-key>",
    "governance-2": "ed25519:<32-byte-public-key>",
    "governance-3": "ed25519:<32-byte-public-key>"
  }
}
```

The loader computes the canonical `policy_hash`. A supplied `policy_hash` is
checked and must match. The exact same policy artifact must be installed on
validators `128`, `129` and `130` before the transition is submitted.

## Transition payload

The payload file contains the Ledger fields below. Values are examples only;
the epoch roots and budget must come from the approved epoch-engine process and
must not be invented by the operator:

```json
{
  "closing_epoch": 20,
  "opening_epoch": 21,
  "closing_state_root": "sha256:<finalized-root>",
  "epoch_task_result_root": "sha256:<finalized-root>",
  "eligibility_snapshot_root": "sha256:<finalized-root>",
  "reward_calculation_root": "sha256:<approved-calculation-root>",
  "next_protocol_parameters_hash": "sha256:<approved-parameters>",
  "pool_budgets": {
    "GENERAL_DEVELOPMENT": 250000
  },
  "pool_budget_references": {
    "GENERAL_DEVELOPMENT": "epoch:20:GENERAL_DEVELOPMENT"
  }
}
```

The builder adds `protocol_authority_policy_hash` before signing. It requires
`opening_epoch == closing_epoch + 1`, a protocol-origin envelope, and all
canonical Ledger roots and pool references.

## Offline build

```text
uv run python tools/build-authorized-epoch-transition.py \
  --policy /secure/aidn/protocol-authority.json \
  --payload /secure/aidn/epoch-20-transition-payload.json \
  --signer governance-1=/secure/keys/governance-1.seed \
  --signer governance-2=/secure/keys/governance-2.seed \
  --created-at 2030-01-01T00:00:00Z \
  --expires-at 2030-01-02T00:00:00Z \
  --output /secure/aidn/epoch-20-transition.signed.json
```

Inspect and independently reproduce the operation ID, policy hash and
signature quorum before any broadcast. The next submission step must use the
existing canonical consensus transport and wait for multi-RPC finality. A
single-node `CheckTx` response is not finality.

## Current localnet gate

The localnet does not yet have an approved authority policy artifact or a
finalized epoch-engine payload. Therefore this builder is implemented and
tested, but no live `EPOCH_TRANSITION` should be created or submitted yet. The
next acceptance record must include the identical policy hash on all three
validators, finalized transition evidence, and a `READY` ECO-0007 quorum
preflight before a reward batch is built.
