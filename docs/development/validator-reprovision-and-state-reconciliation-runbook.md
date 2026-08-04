# Validator Reprovision and State Reconciliation Runbook

Status: Draft

Scope: controlled CometBFT testnet and release-gate G5 preparation.

## Purpose

This runbook defines the fail-closed response when a validator cannot start
after an ABCI or CometBFT interruption. It separates an ordinary process
restart from a state-boundary incompatibility. The latter requires an
approved reprovision; it must not be hidden by `unsafe-reset-all`, manual
database edits or a fabricated recovery report.

## Classify Before Changing State

Collect read-only evidence first:

- CometBFT `/status` and `/net_info`, when RPC is available;
- ABCI snapshot pointer, snapshot height and AppHash;
- node ID, chain ID and validator public identity;
- `data/priv_validator_state.json` metadata;
- the CometBFT startup log;
- the running application image and source/profile version.

For the current controlled deployment, run the credential-free diagnostic
action before any state-changing action:

```bash
AIDN_G5_TARGET_SSH=user@validator-host \\
  AIDN_G5_SSH_KEY=~/.ssh/aidn-g5-operator_ed25519 \\
  tools/g5-current-runtime-control.sh diagnose
```

The action only inspects the container, process, RPC and startup log. It
prints hashes and a small failure classification; it does not restart, kill,
reboot, mutate state or print container environment variables.

The following startup pattern is a hard reprovision signal:

```text
ABCI Handshake App Info: appHeight=H
ABCI Replay Blocks: appHeight=H storeHeight=H stateHeight=H-1
expected height H but last stored abci responses was at height H-1
```

It means the application persisted durable state during `FinalizeBlock`
without the corresponding CometBFT `Commit`. A restart cannot make those two
durability boundaries agree. Do not collect G5 restart or reboot PASS evidence
from that node.

## Reprovision Preconditions

An authorized operator must confirm all of the following before any
state-changing action:

1. The replacement application image is built from the intended commit and
   uses the current `FinalizeBlock` preview plus `Commit` persistence boundary.
2. At least two verified synchronized peers expose the same chain ID,
   validator-independent trust checkpoint and AppHash.
3. The validator key, node key, genesis and last-sign state are backed up
   without exposing private material in evidence.
4. The old node is isolated and cannot sign concurrently with the replacement.
5. The current application and CometBFT data directories are archived before
   replacement.

## Safe Reprovision Sequence

1. Stop CometBFT and the ABCI application through the operator's approved
   service/container controls. Verify that both processes and RPC are down.
2. Preserve the validator key, node key, genesis, last-sign state, current
   ABCI snapshot and the startup log. Never overwrite validator keys from a
   snapshot or state-sync payload.
3. Provision a separate replacement data directory. Configure state sync or
   snapshot restore from the verified checkpoint and at least two peers.
4. Initialize the replacement application from the canonical snapshot at the
   trust height. Verify the resulting AppHash independently before starting
   consensus.
5. Copy only the preserved identity material into the replacement CometBFT
   home. Do not copy an inconsistent blockstore or response store into the
   replacement.
6. Start the ABCI application first, then CometBFT. Confirm chain ID, node ID,
   validator identity, height, AppHash and `catching_up=false` on every peer.
7. Preserve before/after snapshots and hashes. Only then run the G5 graceful,
   abrupt, host-reboot and stale-predecessor drills.

The exact service, image and state-sync commands are deployment-specific and
must be supplied by the operator. The repository control script deliberately
does not guess them or embed credentials.

## Application Projection Repair

If CometBFT is healthy and only the local Hypervisor projection differs from
the durable ABCI snapshot, use
`tools/repair-validator-state-from-abci.py` in plan-only mode first. Apply a
verified plan only while the validator is offline, with an explicit backup and
`--confirm-offline`. This tool cannot repair a CometBFT blockstore/ABCI
response-store mismatch; use the reprovision sequence instead.

## Evidence Rules

- A failed recovery attempt remains evidence of `RECOVERY_REQUIRED`, not G5
  PASS.
- Rebooting a host without starting ABCI before CometBFT is not recovery.
- Matching height alone is insufficient; AppHash, chain ID, node identity and
  `catching_up=false` must also converge.
- Old reports generated before the current application boundary are stale and
  must be recollected after reprovision.
