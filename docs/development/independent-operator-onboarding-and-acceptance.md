# Independent Operator Onboarding and Acceptance

This guide lets an independent operator deploy an AiDN Hypervisor, mutually approve one Registry peer, and produce technical acceptance evidence. It does **not** grant public directory trust or prove independent organizational ownership. Those are separate human/Governance decisions.

## 1. Safety Boundary

Do not send any of the following to another operator or repository:

- Ed25519 private signing keys;
- TLS private keys, Secret Manager files, or master keys;
- Wallet seed phrases or reusable API credentials.

Exchange only public peer identity, public certificate/CA material under your approved PKI process, DNS endpoint, network/chain/revision, and independently signed operator attestation. Both operators approve the other's Ed25519 public key locally before any transport is opened.

## 2. Host Prerequisites

Use a dedicated Linux account and a current Python 3.11+ installation. Install `uv`, Git, Docker only if a Provider Plugin requires its sandbox, and an ingress/reverse proxy if the Dashboard/API must be remotely reachable. The Registry replication listener uses TCP 9443 with mTLS; do not expose the Hypervisor API directly to the Internet without a separate authenticated deployment policy.

```bash
sudo useradd --system --create-home --home-dir /var/lib/aidn --shell /usr/sbin/nologin aidn
sudo install -d -o aidn -g aidn -m 0700 /var/lib/aidn /etc/aidn
git clone https://github.com/glinko/AiDN.git /opt/aidn/AiDN
cd /opt/aidn/AiDN
uv sync --all-extras --frozen
uv run pytest -q
```

Use an immutable release tag or reviewed commit rather than an unreviewed branch for acceptance evidence. Record `git rev-parse HEAD` in the evidence package.

### One-command Ubuntu bootstrap

For a fresh Ubuntu 24.04+ host, the following downloads the current bootstrap, installs its OS and Python dependencies, clones AiDN, creates a secret-free operator workspace, and starts the Hypervisor on `127.0.0.1:8766`:

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://raw.githubusercontent.com/glinko/AiDN/main/tools/bootstrap-independent-operator-ubuntu.sh | bash -s -- --peer-id operator-example-1
```

It prompts for `sudo` only to install Ubuntu packages. It emits the checked-out commit and writes `/home/<user>/.local/share/aidn/bootstrap-state.json`. For acceptance evidence, pin a reviewed tag or commit:

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://raw.githubusercontent.com/glinko/AiDN/<reviewed-ref>/tools/bootstrap-independent-operator-ubuntu.sh | bash -s -- --peer-id operator-example-1 --ref <reviewed-ref>
```

The bootstrap intentionally starts a loopback-only API with Registry replication disabled. It does not publish an Endpoint, open public ports, create Wallet/Registry/TLS keys, or make a directory-trust claim. Continue with the mutual approval steps below before configuring replication.

### One-command two-host transport smoke

When both hosts are under the same test operator's SSH control, run this from the local AiDN checkout to prove the existing mTLS plus Ed25519 Registry transport across hosts:

```bash
~/aidn/AiDN/tools/run-cross-host-registry-smoke.sh \
  --remote-ssh user@<remote-host>
```

The runner automatically discovers exactly one remote AiDN checkout through the bundled acceptance harness. Pass `--remote-repo /known/path` only when automatic discovery reports more than one candidate. The runner starts a disposable loopback-only test peer remotely, copies only its disposable client bundle through SCP, opens a temporary SSH tunnel, and verifies signed handshake, inventory exchange, and immutable object transfer. It terminates the remote peer and tunnel afterward. It uses no production Hypervisor state or identity and is not evidence of independent ownership; its purpose is a one-command interoperability check before the mutually approved production configuration.

The remote host needs either `uv` or an already synchronized `AiDN/.venv`. If neither exists, bootstrap that host first with `--no-start`; the test peer does not require a running Hypervisor there.

## 3. Create the Operator Workspace

Run this on the independent operator's host:

```bash
cd /opt/aidn/AiDN
python tools/prepare-independent-operator-kit.py init \
  --output /var/lib/aidn/operator-kit --peer-id operator-example-1 \
  --network-id aidn --chain-id aidn-testnet-1 --network-revision 1.0
```

The workspace is mode `0700` and contains templates only. Copy each template to a non-template filename, replace every `REPLACE_` value, and keep completed files outside Git. The generator deliberately creates no cryptographic secrets.

## 4. Local Secret and Hypervisor Configuration

Create the local Ed25519 signing key, mTLS certificate/private key, CA trust bundle, and Secret Manager master key through your operating-system credential store, KMS, or equivalent approved local procedure. Store the resulting bytes only through local `secret://` handles listed in `registry-replication.json`.

Set the required runtime environment in `/etc/aidn/hypervisor.env`, mode `0640`, owned by `root:aidn`:

```bash
AIDN_HYPERVISOR_STATE_PATH=/var/lib/aidn/hypervisor-state.json
AIDN_HYPERVISOR_BUNDLES_PATH=/var/lib/aidn/bundles.json
AIDN_REGISTRY_REPLICATION_CONFIG=/etc/aidn/registry-replication.json
AIDN_SECRET_MANAGER_PATH=/var/lib/aidn/secrets.json
# Inject this value through systemd credentials, a KMS agent, or another local secret mechanism.
# Do not commit it or copy it into the replication JSON.
AIDN_SECRET_MANAGER_MASTER_KEY=<base64-encoded-32-byte-local-secret>
```

Install `deploy/systemd/aidn-hypervisor.service.template` as `/etc/systemd/system/aidn-hypervisor.service`, review the `ExecStart` path, then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aidn-hypervisor
sudo systemctl status aidn-hypervisor
curl --fail http://127.0.0.1:8766/health
```

The provided unit binds the API to loopback. Publish it only through a separately authenticated reverse proxy or private network.

## 5. Mutual Registry Peer Approval

Each operator independently verifies the other operator's identity and public Ed25519 key through an out-of-band authenticated channel. Each adds the other peer to its own Registry snapshot/operator control path and configures the matching outbound peer in `/etc/aidn/registry-replication.json`.

The configuration uses opaque secret handles and network addresses only. It SHALL NOT contain private key bytes. Both sides must agree on `network_id`, `chain_id`, and `network_revision`. A changed peer key requires local rotation approval; it is not accepted automatically.

### Persistent controlled-testnet identity

For a controlled testnet, use `tools/prepare-registry-replication-identity.py`. Run `init` independently on each host; it creates a local encrypted Secret Manager, an Ed25519 signing key, a host-local CA, an mTLS certificate, and a public bundle. It does not export private material. Exchange `public-peer.json` through an authenticated operator channel, then run `add-peer` on both hosts. The command also writes the approved remote Ed25519 key into the supplied local Registry snapshot.

Example on `hv-node10` (`192.168.88.126`):

```bash
cd /home/user/aidn/AiDN
uv run python tools/prepare-registry-replication-identity.py init \
  --root /home/user/.local/share/aidn/registry-testnet \
  --peer-id hv-node10 --host 192.168.88.126 --port 9444 \
  --chain-id aidn-testnet-1
```

Run the same command on `node4` (`192.168.88.127`) with `--peer-id node4` and its host address. Exchange the two `public-peer.json` files, then import the remote bundle on each host:

```bash
uv run python tools/prepare-registry-replication-identity.py add-peer \
  --root /home/user/.local/share/aidn/registry-testnet \
  --bundle /secure-transfer/node4-public-peer.json \
  --registry-snapshot /home/user/.local/share/aidn/registry-objects.json
```

Before starting a replication-enabled Hypervisor, set `AIDN_REGISTRY_REPLICATION_CONFIG`, `AIDN_SECRET_MANAGER_PATH`, and a locally injected `AIDN_SECRET_MANAGER_MASTER_KEY` from `master-key.b64`. Keep the key file mode `0600`; the generated testnet directory is separate from the running Hypervisor's existing state. Use port `9444` only after opening that TCP port between the two approved hosts and reviewing the firewall rule.

For a long-running Ubuntu host, stop any disposable `nohup` process first and install the systemd wrapper:

```bash
tools/install-registry-testnet-systemd.sh \
  --root /home/user/.local/share/aidn/registry-testnet \
  --repo /home/user/aidn/AiDN \
  --run-as user \
  --service-name aidn-registry-testnet \
  --api-port 8767
```

The installer refuses to replace a live PID recorded by the disposable runner, keeps the master key out of the unit file, enables restart-on-failure, and restricts writes to the dedicated testnet root. Verify with `systemctl status aidn-registry-testnet` and `journalctl -u aidn-registry-testnet`.

For the controlled LAN acceptance profile used on `2026-08-01`, `hv-node10` (`192.168.88.126`) and `node4` (`192.168.88.127`) used separate encrypted Secret Manager stores, dedicated Hypervisor API port `8767`, and Registry replication port `9444`. Mutual peer approval, authenticated `last_authenticated_at` records, `/health` responses, and transfer of the immutable object `sha256:operator-acceptance-20260801` were observed. This proves transport and object-replication behavior only; it does not prove independent operator ownership. The listener permits one active transport session per peer identity, so a second verifier must run against a dedicated listener or after the existing session is stopped.

Before production configuration, test TCP reachability and mTLS policy through the disposable harness in [registry-replication-operator-deployment.md](./registry-replication-operator-deployment.md). The harness bootstrap bundle is test-only and must not be reused as a production identity.

## 6. Technical Acceptance Evidence

After both live Hypervisors are configured, use an actual immutable object expected to replicate and an already-finalized AiDN operation from the external testnet. Populate the external finality configuration with two independently hosted HTTPS RPC endpoints and a trusted checkpoint obtained out of band.

```bash
cd /opt/aidn/AiDN
export AIDN_SECRET_MANAGER_PATH=/var/lib/aidn/secrets.json
export AIDN_SECRET_MANAGER_MASTER_KEY="$(< /run/credentials/aidn-secret-manager-key-base64)"
tools/run-independent-operator-acceptance.sh \
  --registry-config /etc/aidn/registry-replication.json \
  --registry-snapshot /var/lib/aidn/registry-objects.json \
  --peer-id approved-independent-peer-id \
  --required-object-id immutable-public-object-id \
  --external-finality-config /etc/aidn/external-cometbft-acceptance.json \
  --evidence-dir /var/lib/aidn/acceptance-evidence
```

The runner writes separate Registry replication and external-finality JSON reports plus SHA-256 sums. Preserve the reports, exact checkout commit, peer attestation, checkpoint source, validator/control-group evidence, and operator contact/ownership statement.

Successful output still reports `ownership_evidence: NOT_PROVEN_BY_PROTOCOL`. mTLS, Ed25519, and two RPC endpoints prove protocol-level identity and matching evidence, not that operators are independent. Do not enable a public directory-trust or public network-finality claim until the corresponding out-of-band evidence is reviewed.

## 7. Failure Handling

- Stop and investigate peer-key, certificate, chain, network revision, or object-hash mismatches. Do not replace expected values merely to make a check pass.
- Treat an unavailable, divergent, or tied external RPC view as a failed finality check.
- Disable a compromised peer locally, rotate affected credentials, preserve evidence, and reconnect only after explicit re-approval.
- Never retry a paid Session or Ledger operation solely because acceptance evidence is unavailable; follow Session recovery and settlement rules.
