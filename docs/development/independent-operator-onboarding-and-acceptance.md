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
