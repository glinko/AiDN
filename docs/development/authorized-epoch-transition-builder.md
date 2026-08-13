# Authorized Epoch Transition Builder

This tool prepares the next economic-network artifact after the validator
authority boundary rollout. It is an offline builder only.

## Safety boundary

`tools/build-authorized-epoch-transition.py`:

- reads a public protocol-authority policy;
- reads either a caller-supplied legacy transition payload or a hash-bound
  `READY` quorum report;
- reads external Ed25519 private-key files only for signing;
- verifies that every private key controls the declared authority public key;
- requires the configured threshold;
- validates the payload through the same Ledger epoch-transition rules. A
  quorum-bound artifact additionally requires the exact report when it is
  signed or combined;
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

## Quorum-bound production path

### Canonical schedule prerequisite

Before the first transition, the network must finalize exactly one
`EPOCH_SCHEDULE_COMMIT`. The schedule is shared protocol state, not an
operator-local setting. Every validator must use the same schedule hash and
the same protocol-authority policy; a local schedule with no finalized
commitment deliberately keeps the transition preflight `BLOCKED`.

Prepare the schedule from approved Epoch Engine inputs. The helper validates
and hashes the schedule but does not broadcast it:

```text
uv run python tools/prepare-authorized-epoch-schedule.py \
  --policy /secure/aidn/protocol-authority.json \
  --schedule /secure/aidn/epoch-schedule.json \
  --created-at 2030-01-01T00:00:00Z \
  --output /secure/aidn/epoch-schedule.unsigned.json
```

Authorities sign the same unsigned file independently. Private keys remain
outside the repository and are never included in the final artifact:

```text
uv run python tools/sign-authorized-epoch-schedule.py \
  --unsigned-envelope /secure/aidn/epoch-schedule.unsigned.json \
  --policy /secure/aidn/protocol-authority.json \
  --authority-id governance-1 \
  --private-key /secure/keys/governance-1.seed \
  --output /secure/aidn/epoch-schedule.governance-1.sig.json
```

Combine at least the policy threshold of signatures:

```text
uv run python tools/combine-authorized-epoch-schedule.py \
  --unsigned-envelope /secure/aidn/epoch-schedule.unsigned.json \
  --policy /secure/aidn/protocol-authority.json \
  --signature /secure/aidn/epoch-schedule.governance-1.sig.json \
  --signature /secure/aidn/epoch-schedule.governance-2.sig.json \
  --output /secure/aidn/epoch-schedule.signed.json
```

The repository includes a guarded submitter for this exact operation. It
validates the envelope and policy locally, verifies the same policy projection
on every configured validator, broadcasts identical bytes, and waits for
operation-bound multi-RPC finality:

```text
uv run python tools/submit-authorized-epoch-schedule.py \
  --envelope /secure/aidn/epoch-schedule.signed.json \
  --policy /secure/aidn/protocol-authority.json \
  --finality-config /secure/aidn/cometbft-finality.json \
  --dry-run
```

Review the `READY` JSON and remove `--dry-run` only after the schedule and
authority artifacts have been independently approved. No local UI, agent or
validator may mark the schedule active by editing a config file. Confirm finality through
`epoch/schedule` and `operation/finalized/<operation_id>` on the validator
quorum before running the transition-input query.

The production path starts with the multi-validator preflight. Save its JSON
output without editing it:

```text
uv run python tools/query-epoch-transition-inputs.py \
  --rpc-url http://192.168.88.128:26657 \
  --rpc-url http://192.168.88.129:26657 \
  --rpc-url http://192.168.88.130:26657 \
  > /secure/aidn/epoch-20-quorum.json
```

The command exits with `2` until a complete validator quorum is available.
Only a report whose `status` is `READY`, whose `quorum_hash` verifies, and
whose manifest finality reference is identical on the required validators may
be used below. The builder copies the typed report fields; it does not accept
an operator-edited payload alongside the report.

```text
uv run python tools/build-authorized-epoch-transition.py \
  --policy /secure/aidn/protocol-authority.json \
  --quorum-report /secure/aidn/epoch-20-quorum.json \
  --expected-chain-id chain-Anm7Jk \
  --signer governance-1=/secure/keys/governance-1.seed \
  --signer governance-2=/secure/keys/governance-2.seed \
  --created-at 2030-01-01T00:02:00Z \
  --expires-at 2030-01-02T00:00:00Z \
  --output /secure/aidn/epoch-20-transition.signed.json
```

For independent signing, prepare the unsigned artifact with
`tools/prepare-authorized-epoch-transition.py --quorum-report`, then pass the
same immutable report to every invocation of
`tools/sign-authorized-epoch-transition.py --quorum-report`. The combiner also
requires that report. A quorum-bound envelope cannot be signed or combined
without it, and a changed report is rejected. The final validator still
performs its own local check that the referenced manifest operation is
finalized; an external report never replaces that check.

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

## Legacy offline build

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

The payload mode above remains for compatibility and fixtures. It is not the
production path for a manifest-backed transition because it permits a caller
to supply roots directly. Inspect and independently reproduce the operation
ID, policy hash and signature quorum before any broadcast. The next submission
step must use the existing canonical consensus transport and wait for
multi-RPC finality. A single-node `CheckTx` response is not finality.

## Current localnet gate

The query path is deployed on validators `128`, `129` and `130` from commit
`749930f`. All three validators return the same hash-bound report and the
quorum collector reaches `3/3` agreement, but the report remains `BLOCKED`:
the live network has no finalized canonical schedule, has not reached a
configured epoch boundary and has no finalized manifest. The rollout evidence
is recorded in
`docs/development/epoch-transition-input-query-rollout-acceptance-2026-08-13.md`.

The schedule commitment helpers and independent signing path are implemented
and tested, but no live `EPOCH_TRANSITION` should be created or submitted yet.
The next acceptance record must include a finalized canonical schedule, a
finalized manifest, a `READY` quorum preflight, authority signatures and
later-block finality before a reward batch is built.
