# Controlled Localnet Epoch Schedule Acceptance

Status: PASS

Date: 2026-08-13

This report records the first canonical RFC-0048 schedule commitment on the
controlled AiDN LAN testnet. It is a disposable local-network acceptance
profile, not a public-network governance decision and not evidence of
independent validator ownership.

## Profile Boundary

- Network: `controlled localnet`
- Chain ID: `chain-Anm7Jk`
- Validators: `192.168.88.128`, `192.168.88.129`, `192.168.88.130`
- Authority policy: disposable `2-of-3` Ed25519 threshold
- Policy hash:
  `sha256:40c7c0371dca2160043bcd05e37ceb3d8cc8ab33d67bc21b451c95b3e45625a4`
- Authority private seeds: generated and retained only on the local operator
  workstation outside the repository; no private key was copied to a
  validator or committed to Git.
- The three validator application containers were recreated with the public
  policy only. CometBFT validator keys, blockstore and application state were
  preserved.

The policy is intentionally disposable. When external independent operators
join, the authority policy, signer set, threshold and governance acceptance
must be replaced by a separately approved network profile.

## Schedule Artifact

The committed schedule is:

```json
{
  "schema_version": "aidn.epoch-schedule.v1",
  "genesis_start_time": "2026-07-29T22:55:59.900791419Z",
  "epoch_duration_seconds": 60,
  "parameter_version": "controlled-localnet-parameters-v1",
  "task_set_version": "controlled-localnet-task-set-v1",
  "protocol_version": "0.1-controlled-localnet",
  "schedule_hash": "sha256:8addacbb10ab523a38993b017716ab64ea29b4c2b7e73bf15536dfda2c63f6c0"
}
```

The schedule was prepared offline, bound to the deployed policy hash, and
signed by two distinct local authority keys. The private seeds remain outside
the repository and are not part of this report.

## Consensus Operation

- Operation type: `EPOCH_SCHEDULE_COMMIT`
- Operation ID:
  `7a1729690f1f3dcf3d4b7cf35f784d06beac182d7b7e0fffd6591c5099ce4b82`
- Canonical schedule sequence: `23`
- Canonical schedule record digest:
  `c72fbdcf19f997a6e74180b6208001a3a065706abe940b8d1702aca4a2e3e24b`
- Transaction hash:
  `37D5DE8397F28AB041AA4BB464B30D4C05E857C75D19BDC7679B1E513AC934C7`
- CheckTx result on all configured RPCs: `code=0`
- Finalized block height: `64176`
- Finalized block ID:
  `FEECC07CA43B4072D17FA8F46AD647C33F192686D882C80827633F80A4D4349A`
- Finalized AppHash:
  `1E541C0A9C3A92DD7F497DE2947A6DD0645C785B90358310B42D44BFC772D491`
- Verified finality quorum: `3/3` RPC views, configured minimum `2`
- Finality verifier ID: `controlled-localnet-schedule-20260813:0`

The same transaction bytes and successful result were observed at all three
RPC endpoints. The finality source verified transaction inclusion, the
CometBFT commit and the trusted validator-set transition; a local CheckTx
response alone was not accepted as finality.

## Canonical State Verification

After finalization, all three validators returned the same `epoch/schedule`
projection with `code=0`. The projection contains the committed schedule and
its schedule hash. All three validators also returned the same authority
policy projection with:

```json
{
  "authority_count": 3,
  "configured": true,
  "epoch_transition_mode": "THRESHOLD_AUTHORIZED",
  "policy_hash": "sha256:40c7c0371dca2160043bcd05e37ceb3d8cc8ab33d67bc21b451c95b3e45625a4"
}
```

The application state was not reset during policy rollout or schedule
commitment. The schedule became canonical through the normal consensus
transaction path.

## Implementation Corrections Found During Acceptance

The live rollout exposed two operator-tooling defects:

1. Root-owned policy installation used shell redirection outside the privileged
   shell, which failed on Ubuntu state mounts. The installation is now one
   atomic privileged shell transaction.
2. The schedule submitter attempted to pass a Pydantic-only `mode` argument to
   the dataclass finality evidence serializer. Both epoch submitters now use
   the dataclass-compatible `model_dump()` call.

The rollout installer has regression coverage for privileged atomic writes and
both submitters have a regression guard for finality serialization.

## Acceptance Boundary

This closes the controlled-localnet implementation and canonical schedule
commitment gate. It does not close:

- public or production authority governance;
- independent-operator or organizational-independence evidence;
- production epoch parameter approval;
- live `EPOCH_RESULT_MANIFEST_COMMIT` and `EPOCH_TRANSITION` execution;
- ECO-0007 reward-pool allocation or Q distribution.

Those remain separate roadmap gates and must use a new authority policy and
network-approved schedule when external independent validators are available.
