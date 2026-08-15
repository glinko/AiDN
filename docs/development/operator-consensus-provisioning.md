# Operator Consensus Provisioning

Status: `Implemented`

## Scope

The Ubuntu operator bootstrap provisions CometBFT automatically. The operator
does not need to discover a binary, create a user-systemd unit, or manually
start the process for a fresh installation.

The supported fresh-host path is:

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/glinko/AiDN/main/tools/aidn-operator-bootstrap-ubuntu.sh \
  | bash -s -- --operator-id node-a --consensus-mode validator
```

The installer prompts for the operator identity and safe local paths. It then:

1. installs the pinned CometBFT toolchain;
2. creates `data-dir/consensus/cometbft` only when it is empty;
3. writes `aidn-cometbft-<operator>.service` as a user-systemd unit;
4. configures RPC `127.0.0.1:26657` and AiDN ABCI `127.0.0.1:26658`;
5. starts the Hypervisor first so its ABCI listener is available;
6. starts CometBFT and verifies `/status` before reporting success.

The default fresh-host profile is a local single-validator chain. It proves
that the local consensus process and the AiDN ABCI bridge work; it is not an
implicit claim that the node has joined a public validator set. An approved
genesis and peer/network profile remain required for a multi-operator network.

## Modes

- `validator`: starts the local AiDN ABCI application and CometBFT validator.
- `non_validator`: starts CometBFT with `proxy_app = "nil"`; it does not claim
  local validator participation.
- `disabled`: leaves consensus disabled for explicitly local-only work.

`--no-consensus` is an alias for `--consensus-mode disabled`.

## Dashboard Installation Wizard

The paired Advanced → CometBFT workspace now exposes a three-step, bounded
installation procedure for an already bootstrapped Ubuntu host. It never
executes an arbitrary shell command received over HTTP.

1. Review the mode, chain ID, moniker and fixed local ports. RPC and ABCI are
   always loopback; P2P may be changed to `0.0.0.0` only with an explicit LAN
   acknowledgement.
2. Press `Install CometBFT`. The request crosses the UID-restricted root
   runtime broker and runs the reviewed installer with paths derived from the
   Hypervisor state directory. Existing genesis state is validated, never
   overwritten. The resulting configuration is staged as
   `consensus-config.pending.json`.
3. Press `Apply configuration & restart`. The pending document is validated,
   atomically promoted to `consensus-config.json`, and the Hypervisor schedules
   its own systemd restart. On reconnect, the normal Start/Restart/Stop controls
   become available for the configured unit.

If the host has not installed the root broker, the wizard remains manual and
points the operator back to the reviewed Ubuntu bootstrap. If RPC is down after
activation, the service card shows the bounded recovery state instead of
claiming that installation succeeded.

After recovery, press `Refresh consensus`. The consensus step is ready only after
both `/status` and `/net_info` respond through the configured RPC endpoint.

## Existing Host Migration

Rerun the bootstrap with the same operator ID, data directory, and chain ID:

```bash
bash tools/aidn-operator-bootstrap-ubuntu.sh \
  --operator-id node-a \
  --data-dir "$HOME/.local/share/aidn/node-a" \
  --consensus-mode validator
```

The installer refuses to rewrite an existing `genesis.json` when its chain ID
does not match the requested value. Stop and reconcile the network profile
explicitly instead of deleting the CometBFT home.

Inspect the managed process with:

```bash
systemctl --user status aidn-cometbft-node-a.service
journalctl --user -u aidn-cometbft-node-a.service -n 100 --no-pager
curl --fail http://127.0.0.1:26657/status
```

The installer never stores the sudo password in a unit or environment file.
