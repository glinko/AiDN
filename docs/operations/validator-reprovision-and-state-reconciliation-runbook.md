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

## Isolated replacement helper

The repository includes `tools/provision-validator-replacement.sh` for a
non-root operator deployment. It refuses an existing replacement root, copies
only `genesis.json`, `node_key.json` and `priv_validator_key.json`, creates a
zeroed `priv_validator_state.json`, and enables CometBFT State Sync. It never
copies `blockstore.db`, `state.db`, `evidence.db` or old ABCI response state.

Run it only after obtaining a trusted block height/hash and a peer list from
healthy validators:

```bash
export AIDN_REPROVISION_ROOT="$HOME/aidn-g5-reprovision-<timestamp>"
export AIDN_REPROVISION_REPO="$HOME/aidn/AiDN"
export AIDN_SOURCE_COMET_HOME="$HOME/aidn-g5-clean/node"
export AIDN_COMET_BIN="$HOME/aidn-g5-clean/cometbft"
export AIDN_TRUST_HEIGHT=12745
export AIDN_TRUST_HASH=<trusted-block-hash>
export AIDN_RPC_SERVERS=tcp://validator-1:26657,tcp://validator-2:26657
export AIDN_PERSISTENT_PEERS=<healthy-peer-list-without-the-replacement>

tools/provision-validator-replacement.sh prepare
tools/provision-validator-replacement.sh start
tools/provision-validator-replacement.sh status
```

For a controlled abrupt-process drill, use the isolated action below. It
terminates only the CometBFT and ABCI PIDs recorded by this replacement root;
the operator must invoke `start` separately to make recovery explicit:

```bash
tools/provision-validator-replacement.sh abrupt
tools/provision-validator-replacement.sh start
```

The replacement RPC must converge with the validator set and retain the
preserved node ID and chain ID before it can be used in G5 evidence. If State
Sync cannot obtain chunks from healthy P2P peers, stop the replacement and
repair peer reachability; do not copy old databases or mark the drill as
successful. Use a new root for every retry.

## Evidence Rules

- A failed recovery attempt remains evidence of `RECOVERY_REQUIRED`, not G5
  PASS.
- Rebooting a host without starting ABCI before CometBFT is not recovery.
- Matching height alone is insufficient; AppHash, chain ID, node identity and
  `catching_up=false` must also converge.
- Old reports generated before the current application boundary are stale and
  must be recollected after reprovision.
