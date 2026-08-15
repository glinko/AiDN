# AiDN Ubuntu Operator Release Package

This is the supported one-command installation path for a fresh Ubuntu 24.04+
or later host. It installs the Hypervisor checkout, creates persistent local
state, provisions a host-local operator identity and encrypted Registry secret
store, provisions a pinned CometBFT process, and manages both processes with
user-level systemd services. It also measures scheduler capacity from the host
and records the result before the Hypervisor first starts.

The bootstrap also installs a pinned Node runtime below the operator data
directory, builds the React dashboard, and stages its static assets before the
Hypervisor starts. Node and pnpm are build-only tools; the running Hypervisor
does not require a JavaScript process.

The installer is intentionally safe by default:

- the API binds to `127.0.0.1:8766`;
- the Registry listener is disabled from external access;
- no firewall rule is changed;
- no Wallet, peer approval, or public-directory trust is created;
- sudo is used only through the normal Ubuntu prompt;
- private keys and the Secret Manager master key remain below the operator's
  data directory and are never printed or put in a unit file.

## One command

Use a reviewed immutable tag or commit for an acceptance run. Replace
`<reviewed-ref>` with that exact ref in both places:

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/glinko/AiDN/<reviewed-ref>/tools/aidn-operator-bootstrap-ubuntu.sh \
  | bash -s -- --ref <reviewed-ref>
```

The wizard asks only for the operator/node name and deployment defaults. It
reads from `/dev/tty`, so sudo and wizard prompts work even though the script
itself is downloaded through a pipe. It never asks for or stores the root
password.

For automation with the safe defaults:

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/glinko/AiDN/<reviewed-ref>/tools/aidn-operator-bootstrap-ubuntu.sh \
  | bash -s -- --ref <reviewed-ref> --operator-id operator-example-1 --non-interactive
```

The non-interactive form still requires the caller's ordinary sudo access. It
does not silently enable a public API or a Registry listener.

Consensus is enabled as a local validator by default. Use
`--consensus-mode non_validator` for a participant without local validator
execution, or `--no-consensus` for an explicitly local-only installation. See
[Operator Consensus Provisioning](./operator-consensus-provisioning.md) for
startup ordering, legacy migration, and the boundary between a local genesis
and a joined multi-validator network.

## Enabling peer onboarding

To prepare a LAN/testnet Registry listener during installation, explicitly add
`--enable-registry`:

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/glinko/AiDN/<reviewed-ref>/tools/aidn-operator-bootstrap-ubuntu.sh \
  | bash -s -- --ref <reviewed-ref> --operator-id operator-example-1 \
      --enable-registry --advertise-host 192.0.2.10 --non-interactive
```

This creates `public-peer.json` but does not approve a remote peer or create an
outbound connection. Exchange only the public bundle through an authenticated
operator channel, then import it with the existing
`prepare-registry-replication-identity.py add-peer` command on both hosts. The
host firewall is deliberately not modified by the bootstrap; open TCP 9444
only after reviewing the LAN policy.

Registry enablement does not change the Dashboard listener. During the
interactive wizard, the operator is asked whether to expose the Dashboard/API
on the LAN; the default is `127.0.0.1` and answering yes selects `0.0.0.0`. A non-loopback API
bind requires explicit approval because the MVP API does not provide a public
authentication boundary. In non-interactive mode, use both flags explicitly:

```bash
... --api-host 0.0.0.0 --api-port 8766 --allow-public-api
```

Do not use that option on an untrusted network. Prefer an authenticated
reverse proxy or a private management network for the dashboard.

This changes only the Hypervisor Dashboard/API listener. Provider runtimes
(Ollama, llama.cpp, and vLLM) remain loopback-only.

The supported bootstrap enables the browser-paired Dashboard over the selected
HTTP boundary so the Settings control is usable without first provisioning a
TLS proxy. Treat a LAN bind as trusted-network-only and keep the endpoint off
the public Internet.

After pairing the browser, the same boundary can be changed in **Settings →
Dashboard listener**. Select **Loopback only** or **LAN · 0.0.0.0**, then apply
the listener. The Hypervisor writes the reviewed host value to
`hypervisor-bind-host` and restarts its managed user service; no arbitrary bind
address or shell command is accepted from the browser. If the process was not
started by the supported bootstrap, the setting is read-only until the
bootstrap-generated launcher is restored.

## Resulting layout

For operator `operator-example-1`, defaults are:

```text
~/aidn/operator-example-1/AiDN/                    immutable checkout
~/.local/share/aidn/operator-example-1/            persistent state
  bootstrap-state.json                              secret-free summary
  resource-capacity.json                            CPU, RAM and visible GPU capacity
  hypervisor-bind-host                              `127.0.0.1` or `0.0.0.0`, mode 0600
  operator-identity/                                local identity metadata
    operator-attestation-key.raw                    PRIVATE, mode 0600
    operator-identity.json                          PRIVATE metadata, mode 0600
    operator-public-identity.json                   safe to exchange
  registry-replication/
    public-peer.json                                safe to exchange
    secrets.json                                    encrypted private store
    master-key.b64                                  PRIVATE, mode 0600
  run-hypervisor.sh                                 PRIVATE launcher
  consensus/
    bin/cometbft                                    pinned executable
    cometbft/                                        CometBFT home and genesis
  logs/
~/.config/systemd/user/aidn-hypervisor-operator-example-1.service
~/.config/systemd/user/aidn-cometbft-operator-example-1.service
```

`bootstrap-state.json` contains the exact checkout commit, operator ID, public
key, service name and public bundle path. It contains no private key or master
key. `resource-capacity.json` contains no credentials or process payloads. It
records CPU affinity/cgroup limits, RAM capacity, and GPU VRAM when
`nvidia-smi` is available. Unknown GPU capacity remains explicitly unreported.

The React preview is available at `/operators/dashboard/react`; the legacy
dashboard remains at `/operators/dashboard` during migration. The bootstrap
creates the preview assets automatically, so no operator needs to run a manual
frontend build command.

Verify the service with:

```bash
systemctl --user status aidn-hypervisor-operator-example-1.service
systemctl --user status aidn-cometbft-operator-example-1.service
curl --fail http://127.0.0.1:8766/health
curl --fail http://127.0.0.1:26657/status
```

The installer enables user lingering so the service can return after reboot.
The generated unit uses automatic restart and restricts writable state to the
operator data directory.

The readiness wizard normally marks Host Capacity ready on first load. If host
visibility changes after installation, **Run automatic probe** repeats the same
bounded measurement and atomically refreshes `resource-capacity.json`; it does
not accept capacity numbers from the browser.

## Re-running and removal

Re-running the same command at the same paths is idempotent for identity keys:
existing keys are verified and reused, not rotated. Local checkout changes are
never overwritten; the installer stops if the checkout is dirty or the path is
not an AiDN repository.

To stop and disable one installed operator without deleting evidence or keys:

```bash
systemctl --user disable --now aidn-hypervisor-operator-example-1.service
systemctl --user disable --now aidn-cometbft-operator-example-1.service
```

Do not delete `master-key.b64`, `secrets.json`, or
`operator-attestation-key.raw` until any required evidence and recovery window
has ended. Peer approval, key rotation, Wallet binding, provider installation,
and public network release remain separate workflows.
