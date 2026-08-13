# Protocol Authority and Epoch Transition Operations

This is the operational procedure for opening the first ECO-0007 development
pool on a real AiDN network. It separates governance decisions, signer custody,
validator configuration and consensus submission.

## What must be approved

The network owner/governance process must approve these values before any live
operation:

1. Authority IDs and the threshold. For the current three-validator localnet,
   use a disposable `2-of-3` policy only if three independent signers are
   actually available.
2. The effective policy boundary and the policy hash.
3. The closing epoch and the exact finalized evidence roots.
4. The `GENERAL_DEVELOPMENT` pool budget in integer `q_atoms`, derived from the
   active ECO-0007 emission parameters. It must not be guessed from a UI
   balance or copied from an example.

The creator wallet, operator wallet, Treasury wallet and protocol-authority
keys are different identities. Do not reuse a wallet private key as an
authority signer.

## 1. Create the policy and keys

Run this on the authority provisioning machine, not on validators. The key
directory must be outside the checkout:

```text
python tools/create-protocol-authority-policy.py \
  --authority-id authority-1 \
  --authority-id authority-2 \
  --authority-id authority-3 \
  --threshold 2 \
  --key-dir /secure/aidn/protocol-authority-keys \
  --output /secure/aidn/protocol-authority.json
```

The command writes one private seed per authority and a public JSON policy.
It refuses to overwrite an existing seed and refuses to put private keys in
the repository. Back up each seed independently and keep the public policy in
the governance evidence bundle.

For a real independent quorum, each signer receives only its own seed and the
same unsigned envelope. No one signer needs the other private keys.

For stricter separation, each signer generates only its own key and sends the
public key to the policy coordinator:

```text
python tools/generate-protocol-authority-key.py \
  --authority-id authority-1 \
  --output /secure/aidn/authority-1.seed
```

The coordinator then creates a public-only policy and never receives the
private seeds:

```text
python tools/create-protocol-authority-policy.py \
  --authority authority-1=ed25519:<public-key-1> \
  --authority authority-2=ed25519:<public-key-2> \
  --authority authority-3=ed25519:<public-key-3> \
  --threshold 2 \
  --output /secure/aidn/protocol-authority.json
```

## 2. Distribute the public policy

Validate it locally, then install the exact same file on validators `128`,
`129` and `130` with the existing rollout helper:

```text
python tools/rollout-protocol-authority-policy.py --dry-run \
  --hosts 192.168.88.128 192.168.88.129 192.168.88.130 \
  --policy /secure/aidn/protocol-authority.json \
  --backup-suffix authority-v1
```

Only after reviewing the hash, run the same command without `--dry-run` with
the SSH password supplied through `AIDN_SSH_PASSWORD`. Then query
`protocol/authority-policy` on all three RPCs and require one identical policy
hash. A policy mismatch blocks the network; it must not be repaired by
silently choosing the majority file.

## 3. Produce the real epoch payload

The Epoch Engine must freeze the closing epoch and output a JSON object with:

```json
{
  "closing_epoch": 20,
  "opening_epoch": 21,
  "closing_state_root": "sha256:<finalized-state-root>",
  "epoch_task_result_root": "sha256:<frozen-task-results>",
  "eligibility_snapshot_root": "sha256:<eligibility-snapshot>",
  "reward_calculation_root": "sha256:<deterministic-reward-calculation>",
  "next_protocol_parameters_hash": "sha256:<approved-next-parameters>",
  "pool_budgets": {"GENERAL_DEVELOPMENT": 0},
  "pool_budget_references": {
    "GENERAL_DEVELOPMENT": "epoch:20:GENERAL_DEVELOPMENT"
  }
}
```

The numbers and roots above are placeholders and must not be submitted. The
current repository validates the shape and hash bindings, but the live source
of these values must be the finalized Epoch Engine state. If the engine cannot
produce these roots from the current chain, that is an implementation blocker,
not an operator input problem.

## 4. Independent signing

Prepare an unsigned envelope:

```text
python tools/prepare-authorized-epoch-transition.py \
  --policy /secure/aidn/protocol-authority.json \
  --payload /secure/aidn/epoch-20-payload.json \
  --created-at 2030-01-01T00:00:00Z \
  --expires-at 2030-01-02T00:00:00Z \
  --output /secure/aidn/epoch-20.unsigned.json
```

Distribute this exact file and the public policy to the three signers. Each
signer runs only its own command:

```text
python tools/sign-authorized-epoch-transition.py \
  --unsigned-envelope /secure/aidn/epoch-20.unsigned.json \
  --policy /secure/aidn/protocol-authority.json \
  --authority-id authority-1 \
  --private-key /secure/aidn/protocol-authority-keys/authority-1.seed \
  --output /secure/aidn/signatures/authority-1.json
```

The signature file contains no private material. A second signer repeats the
same operation with its own authority ID and seed. Combine at least the
configured threshold:

```text
python tools/combine-authorized-epoch-transition.py \
  --unsigned-envelope /secure/aidn/epoch-20.unsigned.json \
  --policy /secure/aidn/protocol-authority.json \
  --signature /secure/aidn/signatures/authority-1.json \
  --signature /secure/aidn/signatures/authority-2.json \
  --output /secure/aidn/epoch-20.signed.json
```

The combiner verifies the policy hash, operation ID, signature ownership and
threshold. It cannot alter the payload without invalidating the signatures.

## 5. Dry-run and submit

Before broadcast:

```text
python tools/submit-authorized-epoch-transition.py --dry-run \
  --envelope /secure/aidn/epoch-20.signed.json \
  --policy /secure/aidn/protocol-authority.json \
  --finality-config /etc/aidn/cometbft-finality.json
```

After a second person reviews the operation ID, policy hash, roots and pool
budget, submit without `--dry-run`. The command sends identical bytes to the
configured RPCs and returns `FINALIZED` only after operation-bound inclusion,
commit verification and the configured multi-RPC quorum. `CheckTx` admission
alone is never treated as payment or epoch finality.

## What the agent can and cannot do

The agent can validate artifacts, run dry-runs, query all validators, prepare
reports and submit an already approved signed envelope. It must not invent
the pool budget, generate replacement roots, use an operator wallet as a
protocol authority, or treat a local projection as finality.

The current localnet is therefore blocked until governance supplies the public
policy and the Epoch Engine supplies a real finalized payload. After those
inputs exist, the remaining process is deterministic and scriptable.
