# Protocol Authority Policy Rollout

This runbook describes the coordinated installation of the public
protocol-authority policy on the LAN validator ABCI containers.

## Preconditions

- The policy has been approved by the protocol authority/governance process.
- The policy file contains only public Ed25519 keys.
- The same canonical `policy_hash` is intended for validators `128`, `129`
  and `130`.
- Private authority keys are not copied to validators.
- The current validator state mount remains
  `/home/user/aidn-g5-clean/state:/state`.
- A maintenance window is available because each ABCI container is recreated
  sequentially.

The rollout tool refuses a relative or path-traversing remote path, validates
the policy before SSH, and does nothing in `--dry-run` mode.

## Dry-run

```text
uv run python tools/rollout-protocol-authority-policy.py \
  --hosts 192.168.88.128 192.168.88.129 192.168.88.130 \
  --policy /secure/aidn/protocol-authority.json \
  --backup-suffix 20260812-authority \
  --dry-run
```

Review:

- `policy_hash`;
- `policy_file_sha256`;
- target host and container paths;
- `broadcast: false`.

## Coordinated rollout

Set the SSH password only through a protected secret injection mechanism or
leave the environment variable unset and use the tool's interactive prompt.
Do not place it in a command line, repository file or shell history. For
PowerShell, leave the variable unset and let the tool prompt:

```text
Remove-Item Env:AIDN_SSH_PASSWORD -ErrorAction SilentlyContinue
uv run python tools/rollout-protocol-authority-policy.py ...
```

For a non-interactive Linux operator shell, use an equivalent protected secret
injection mechanism rather than `--ssh-password`:

```text
AIDN_SSH_PASSWORD='<secret-from-secret-store>' \
uv run python tools/rollout-protocol-authority-policy.py \
  --hosts 192.168.88.128 192.168.88.129 192.168.88.130 \
  --policy /secure/aidn/protocol-authority.json \
  --backup-suffix 20260812-authority
```

The tool:

1. connects to one host at a time;
2. checks the expected state mount;
3. atomically installs the public policy file with a digest check;
4. preserves the current ABCI container as a rollback container;
5. recreates the container with the existing image, mounts and environment;
6. adds only `AIDN_PROTOCOL_AUTHORITY_POLICY_PATH=/state/protocol-authority.json`;
7. waits for health and verifies the running environment;
8. rolls that host back if health or configuration verification fails.

The tool does not restart the external CometBFT process and does not submit an
`EPOCH_TRANSITION`. Consensus state and Ledger state are not reset.

## After rollout

Verify all three validators expose the same policy hash through the operator
diagnostic path, then run the read-only reward preflight:

```text
uv run python tools/query-development-reward-preflight.py \
  --rpc-url http://192.168.88.128:26657 \
  --rpc-url http://192.168.88.129:26657 \
  --rpc-url http://192.168.88.130:26657 \
  --pool-id GENERAL_DEVELOPMENT
```

The result is expected to remain `BLOCKED` until a signed and finalized
`EPOCH_TRANSITION` exists. Installing a policy alone must not create a pool,
mint Q or change any wallet balance.

## Rollback

The tool retains one named previous container per host. If a host fails, it
automatically restores that container and starts it. Do not delete rollback
containers until health, RPC peer state and application hash have been
verified. A later manual cleanup must be performed per host and outside the
economic transition window.

## Current status

The rollout helper is implemented and dry-run tested. It has not been run
against the LAN validators because no approved protocol-authority policy
artifact has been supplied. The current validators therefore remain
fail-closed for `EPOCH_TRANSITION`, which is the correct state until governance
keys and policy hash are available.
