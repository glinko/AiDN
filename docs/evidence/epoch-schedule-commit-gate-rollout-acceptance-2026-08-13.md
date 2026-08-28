# Epoch Schedule Commitment Gate Rollout Acceptance

Status: PASS

Date: 2026-08-13

This report records the coordinated deployment of the canonical
`EPOCH_SCHEDULE_COMMIT` gate to the controlled LAN validator set. It proves
that the validators run the implementation which requires a finalized
schedule commitment before an epoch transition can become ready. It does not
claim that a schedule, authority policy or epoch transition has been finalized.

## Scope

- Source commit: `6d4165483a3e68fe8c4fb4aac15a9b9351ddb0bb`
- Image tag: `aidn-hypervisor-lan-testnet-strict:6d41654`
- Replaced container: `aidn-g5-abci`
- State mount preserved on every host:
  `/home/user/aidn-g5-clean/state:/state`
- Rollout order: `192.168.88.128`, then `192.168.88.129`, then
  `192.168.88.130`
- CometBFT process, validator keys, blockstore and application state were not
  reset or replaced.

## Per-validator result

| Validator | Image ID | Health and RPC | Rollback container |
| --- | --- | --- | --- |
| `192.168.88.128` | `sha256:1c1d3c538e3f172d65bd5f29b256d717c7551975f89a5fe453a396a1e43ce61d` | PASS | `aidn-g5-abci-prev-6d41654-128` |
| `192.168.88.129` | `sha256:355bf7e06b6198e4ce5c8f724f03cf13887cc945b3195d0c547a8c59c1676cd6` | PASS | `aidn-g5-abci-prev-6d41654-129` |
| `192.168.88.130` | `sha256:4493a4cc9f8e55777aad5ae5ddd46152499e936e3c785cb3970a9e2ba466f3c2` | PASS | `aidn-g5-abci-prev-6d41654-130` |

Each image was built from the exact source commit on the target host. The
previous application container remains stopped as a rollback target.

## Consensus convergence

After the sequential rollout, all three RPCs converged with:

- chain ID `chain-Anm7Jk`;
- height `58726` at the convergence check;
- identical AppHash
  `1E541C0A9C3A92DD7F497DE2947A6DD0645C785B90358310B42D44BFC772D491`;
- `catching_up=false`;
- the existing CometBFT validator identities and P2P process intact.

Validator `130` briefly reported `catching_up=true` immediately after its
replacement, then converged before the quorum query was accepted.

## Read-only gate evidence

The coordinated query was run against all three RPC endpoints at report
height `58727`. The collector returned `3/3` agreement and the same report on
every validator:

- `status: BLOCKED`;
- `reason_code: EPOCH_TRANSITION_INPUTS_NOT_READY`;
- `schedule_finality_count: 0`;
- `manifest_finality_count: 0`;
- `report_hash: sha256:d5688d8ee0031e81d258751d7953c903ddd1e2d6db571d905cd653735513d8a3`;
- `observations_hash: sha256:a15acd6436a056b6a915cd59aca991db991901e2a0fec75854b75a39566c58c7`;
- `quorum_hash: sha256:93e4132a9596ee6cda148f8bb8842b56d465c153d655f0da893518627efbe1b0`.

The report exposes empty schedule references:

- `epoch_schedule_commit_operation_id: null`;
- `epoch_schedule_commit_sequence_id: null`;
- `epoch_schedule_commit_record_digest: null`;
- `epoch_schedule_hash: null`;
- `epoch_schedule_version: null`.

This is the expected fail-closed result. The query command exits non-zero for
the blocked readiness result; that is not a rollout failure.

The independent authority projection also remained intentionally empty on all
three validators:

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

## Acceptance boundary

This rollout closes the implementation/deployment gate for the schedule
commitment requirement. It does not close the live economics gate. No
authority policy, schedule envelope, `EPOCH_SCHEDULE_COMMIT`,
`EPOCH_RESULT_MANIFEST_COMMIT`, `EPOCH_TRANSITION` or reward operation was
submitted by this rollout, and no Q was created or transferred.

The next live actions require externally approved inputs:

1. Approve and distribute one public protocol-authority policy to all three
   validators.
2. Prepare, independently sign and combine one canonical RFC-0048 schedule.
3. Submit the signed `EPOCH_SCHEDULE_COMMIT` through canonical consensus.
4. Verify its operation ID, sequence, record digest and schedule hash on all
   three RPCs before preparing a dependent transition.

