# Protocol Authority Readiness Rollout Acceptance

Status: PASS

Date: 2026-08-12

This report records the live rollout of the sanitized protocol-authority
readiness evidence. It does not claim that an authority policy is configured,
that an epoch transition is finalized, or that an ECO-0007 reward was paid.

## Scope

- Source commit: `ae5d515029b383fa9a2856f98c8b3d101bdde433`
- Image tag: `aidn-hypervisor-lan-testnet-strict:ae5d515`
- Replaced container: `aidn-g5-abci`
- State mount preserved on every host:
  `/home/user/aidn-g5-clean/state:/state`
- Rollout order: `192.168.88.128`, then `192.168.88.129`, then
  `192.168.88.130`
- No application, Ledger, or CometBFT state reset was performed.

## Per-validator result

| Validator | Image ID | Health | Rollback container |
| --- | --- | --- | --- |
| `192.168.88.128` | `sha256:60028b2a4d3d856b68ed7e6b6ed9c41813d93f8ae2defca019a9c5caa716d858` | `{"status":"ok"}` | `aidn-g5-abci-prev-authority-readiness-ae5d515-128` |
| `192.168.88.129` | `sha256:18373007eb425af05a7a5e9cc94100e10b32c544b3f5eda90e5abdb0caeb87a3` | `{"status":"ok"}` | `aidn-g5-abci-prev-authority-readiness-ae5d515-129` |
| `192.168.88.130` | `sha256:88957a50c571d4c6a69a126a798b5b6d54654ff6dd2982fb94d92c8eacced4a3` | `{"status":"ok"}` | `aidn-g5-abci-prev-authority-readiness-ae5d515-130` |

The image IDs differ because each validator built the same source locally. The
rollout verified the expected digest on each host before accepting the new
container.

## Live consensus evidence

The post-rollout RPC checks reported:

- chain ID `chain-Anm7Jk` on all validators;
- the same AppHash:
  `1E541C0A9C3A92DD7F497DE2947A6DD0645C785B90358310B42D44BFC772D491`;
- heights `52509`, `52510`, and `52511` during the check;
- `catching_up: false` on all validators;
- two peers on all validators;
- zero unconfirmed transactions on all validators.

Different heights are expected because blocks continued during the sequential
read. No CometBFT process was replaced by this rollout.

## Sanitized authority evidence

The read-only ABCI query `protocol/authority-policy` returned the same result
on all three validators:

```json
{
  "authority_count": 0,
  "configured": false,
  "epoch_transition_mode": "FAIL_CLOSED",
  "policy_hash": null,
  "threshold": null,
  "version": null
}
```

This is the intended state before an approved public policy is distributed. It
means an unsigned or locally invented `EPOCH_TRANSITION` cannot open a reward
pool. No authority keys or signatures are exposed by this diagnostic.

## ECO-0007 preflight

The quorum preflight after rollout returned a consistent `3/3` observation:

- `chain_agreement_count: 3`;
- `agreement_count: 3`;
- `status: BLOCKED`;
- `reason_code: DEVELOPMENT_REWARD_EPOCH_TRANSITION_UNAVAILABLE`;
- `preflight_hash: sha256:63bad672ba3fc3ce4bda380a3ce7e1c640bc653860148e99fe3c3abcf45dbdfd`.

The validator network is healthy, but no finalized epoch transition exposes a
`GENERAL_DEVELOPMENT` budget. Reward-batch construction and Q payment remain
correctly blocked.

## Next gate

The remaining live work is governance/configuration, not another container
rollout:

1. Supply and approve one public protocol-authority policy.
2. Run the dry-run and coordinated policy rollout helper.
3. Verify the same policy hash through all three ABCI queries.
4. Build and sign a real epoch-engine payload with the approved quorum.
5. Submit it through canonical consensus and verify finality.
