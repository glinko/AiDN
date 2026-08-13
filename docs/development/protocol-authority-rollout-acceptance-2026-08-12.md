# Protocol Authority Boundary Rollout Acceptance

Status: PASS

Date: 2026-08-12

This report records the controlled rollout of the hash-bound protocol-authority
boundary introduced for protocol-owned `EPOCH_TRANSITION` operations. It does
not claim that a development reward pool has been activated or that a reward
has been paid.

## Scope

- Source commit: `8145166e4701e6162ebb755cd635e0d4e03d6bdd`
- Image tag: `aidn-hypervisor-lan-testnet-strict:8145166`
- Replaced container: `aidn-g5-abci`
- State mount preserved: `/home/user/aidn-g5-clean/state:/state`
- Rollout order: `192.168.88.128`, then `192.168.88.129`, then `192.168.88.130`
- No ledger, application, or CometBFT state reset was performed.

## Per-validator result

| Validator | Image ID | Health | Rollback container |
| --- | --- | --- | --- |
| `192.168.88.128` | `sha256:0d39b191b711234eacbd0be12a26b08e7bcf32edc0932b61741d5482005be734` | `{"status":"ok"}` | `aidn-g5-abci-prev-8145166-r2-128` |
| `192.168.88.129` | `sha256:7fbd641de098a4c4b855cc0098d59c3a0c20d2ec3aa81b19fd62760100ca2193` | `{"status":"ok"}` | `aidn-g5-abci-prev-8145166-r2-rest` |
| `192.168.88.130` | `sha256:6cd4062e7881f7c8efb2900b56176e52cb98720b65d00599440a51a1e9e5ccdb` | `{"status":"ok"}` | `aidn-g5-abci-prev-8145166-r2-130` |

The image IDs differ because each validator built the image locally. The
source commit, Dockerfile, and rollout validation were identical. The rollout
wrapper verified the expected image ID on each host before accepting the new
container.

## Consensus verification

At the live verification point, all three CometBFT RPC endpoints reported:

- height `52127`;
- `catching_up: false`;
- two peers;
- zero unconfirmed transactions.

The RPC endpoints were reachable through SSH on each validator and the chain
continued producing blocks. The rollout did not replace or reinitialize the
CometBFT containers.

## Authority policy state

The validator image now contains the authority boundary, but no authority
policy has been installed into the validator configuration yet. The strict
bootstrap therefore uses the empty fail-closed policy for protocol-owned
`EPOCH_TRANSITION` operations. This is intentional: it prevents an unsigned
or locally invented epoch transition from creating a development budget.

The next configuration change must install one identical, hash-bound policy on
all three validators. It must be reviewed and distributed as a coordinated
change; a policy present on only one validator is not an acceptable network
state.

## ECO-0007 preflight result

The quorum preflight was run against all three validator RPCs after rollout.
It returned a consistent `3/3` observation with:

- `status: BLOCKED`;
- `reason_code: DEVELOPMENT_REWARD_EPOCH_TRANSITION_UNAVAILABLE`;
- `preflight_hash: sha256:63bad672ba3fc3ce4bda380a3ce7e1c640bc653860148e99fe3c3abcf45dbdfd`.

This is the expected fail-closed result for the current chain: no finalized
`EPOCH_TRANSITION` exposes a `GENERAL_DEVELOPMENT` pool budget. No Q was
minted or credited by this rollout.

## Next acceptance gate

The next slice is complete only when all of the following are true:

1. One approved protocol-authority policy hash is installed on validators
   `128`, `129`, and `130`.
2. A signed `EPOCH_TRANSITION` passes `CheckTx` and block execution under that
   exact policy.
3. The transition is finalized by the required validator quorum.
4. Quorum preflight returns the same usable `GENERAL_DEVELOPMENT` budget from
   independent RPC observations.
5. The first ECO-0007 batch is built, executed, and independently reproduced
   without bypassing consensus.

Until then, reward-batch construction must remain blocked.
