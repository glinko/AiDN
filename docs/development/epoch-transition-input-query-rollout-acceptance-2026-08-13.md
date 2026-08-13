# Epoch Transition Input Query Rollout Acceptance

Status: PASS

Date: 2026-08-13

This report records the coordinated deployment of the read-only Epoch
Transition Input and public Epoch Result Manifest query paths. It does not
claim that an epoch transition is ready, that a development pool is active,
or that any Q was minted or paid. The deployed image predates the
`EPOCH_SCHEDULE_COMMIT` rollout described below; no live schedule commitment
was submitted by this acceptance.

## Scope

- Source commit: `749930f`
- Image tag: `aidn-hypervisor-lan-testnet-strict:749930f`
- Replaced container: `aidn-g5-abci`
- State mount preserved: `/home/user/aidn-g5-clean/state:/state`
- Rollout order: `192.168.88.128`, then `192.168.88.129`, then
  `192.168.88.130`
- CometBFT process and state were not replaced.
- Ledger, application and blockstore state were not reset.

## Per-validator result

| Validator | Image ID | Health | Rollback container |
| --- | --- | --- | --- |
| `192.168.88.128` | `sha256:8d21243ce4dd322408b1ad823cb8b9cfb0de7d60a9182f5c39156e16c1e30f0b` | `{"status":"ok"}` | `aidn-g5-abci-prev-749930f-128` |
| `192.168.88.129` | `sha256:b2a7646ff89aa94566b57bf6953ed3e5d4b0dc94436dc47c523ca77b8a7734bb` | `{"status":"ok"}` | `aidn-g5-abci-prev-749930f-129b` |
| `192.168.88.130` | `sha256:4cf100fef076e6eb71efafbb785a747544cb46d1247bafaa5ea16c0918109b0e` | `{"status":"ok"}` | `aidn-g5-abci-prev-749930f-130` |

Image IDs differ because each validator built the same source locally. The
rollout verified the expected image digest on each host before accepting the
replacement. Each old container remains available as a stopped rollback
target.

## Quorum verification

At the verification point all three RPCs reported:

- chain ID `chain-Anm7Jk`;
- height `56575` during the direct status check;
- the same AppHash:
  `1E541C0A9C3A92DD7F497DE2947A6DD0645C785B90358310B42D44BFC772D491`;
- `catching_up: false`;
- the same validator set identity for each endpoint.

The read-only `epoch/transition-inputs` query returned code `0` and the
expected key on all three validators. The response value length was `1676`
bytes on every endpoint. Before this rollout the same query returned the
`unknown_path` key and an empty value on all three validators.

The quorum collector then returned:

- `status: BLOCKED`;
- `required_quorum: 2`;
- `agreement_count: 3`;
- `chain_agreement_count: 3`;
- `report_hash: sha256:d2c50e5d4262a204e3e32ece1bb74af7f7e0b7b1d03ffc1e5a28c24f1f19a3d4`;
- `quorum_hash: sha256:a0a4140e9167b0dfe4af0ba6aebd5b9f9936d6c80ce274a83aa5bc873444eaf2`;
- `reason_code: EPOCH_TRANSITION_INPUTS_NOT_READY`.

The three reports agree on the same closing height `56577`, closing block
hash, closing state root and source AppHash. No manifest finality reference
was present.

## Expected blocked state

The report is correctly blocked because the active network has not reached a
configured epoch boundary and has no finalized Epoch Result Manifest. The
following values remain absent on every validator:

- closing/opening epoch pair;
- epoch schedule and schedule hash;
- task-result and eligibility roots;
- reward-calculation root;
- next protocol-parameter hash;
- ECO-0007 pool budgets and source references;
- finalized `EPOCH_RESULT_MANIFEST_COMMIT`.

The new implementation also requires the following additional live boundary:

- one finalized `EPOCH_SCHEDULE_COMMIT` with identical schedule hash,
  sequence and record digest on the validator quorum;
- the public `epoch/schedule` projection matching its finalized operation;
- a transition-input report carrying that exact schedule reference.

Until this operation is finalized, a validator may retain a configured
schedule for local compatibility tests, but the live readiness report must
remain blocked with `epoch_schedule_commit_operation` in its missing inputs.

This is a successful query-path rollout, not a successful economic transition.
The network must not create an authority-signed transition or reward batch
from this blocked report.

## Next gate

The next implementation and live-network slice is to prepare, threshold-sign
and submit one canonical, hash-bound `EPOCH_SCHEDULE_COMMIT`, verify its
multi-RPC finality, and then produce the missing finalized evidence at an
actual epoch boundary. Only after a later-block manifest is finalized and the
schedule reference agrees can the quorum-bound builder create the first
authority-signed transition.
