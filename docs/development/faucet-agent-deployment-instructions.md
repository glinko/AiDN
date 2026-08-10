# Faucet Deployment Instructions for an AiDN Agent

This document is written to be handed to a local deployment agent. It
describes the external Faucet Treasury service from ECO-0008. The Faucet is
not a Hypervisor wallet feature and must not be implemented as an unrestricted
core Ledger mint path.

## Agent brief

> Deploy the external `services/aidn-faucet` service on the designated Ubuntu
> host. Keep the Treasury private key, agent token and creator token on that
> host only. Bind the GUI and MCP endpoint to the approved private LAN address,
> never to a public interface without HTTPS and an authenticated reverse
> proxy. Do not generate or invent `chain_id`, a trusted checkpoint, a creator
> recovery wallet, or a consensus funding authorization. Stop and report any
> missing value instead of substituting a guessed one.

## What each credential is

### Treasury key

`treasury.key` is a new Ed25519 private key for the dedicated Faucet Treasury
Wallet. It is generated locally by the deployment command. It is not the
operator's ordinary Wallet key and must not be sent to an agent, GitHub, an
MCP client, or another node. Keep a separate encrypted backup under the
creator's control.

The public part becomes `wallet_public_key` in the secret-free Treasury
manifest. The corresponding `wallet_id` is derived automatically.

### Agent token

`agent-token` is a random bearer credential for normal agent operations:
status, challenge, claim and reconciliation. It is separate from the
Treasury key and creator token. Give it only to the agent that is allowed to
request Faucet claims.

### Creator token

`creator-token` is a second random bearer credential for the creator/operator
control surface: pause, resume, low-balance watermark, claim inspection and
claim reconciliation. It is equivalent to an administrative control secret,
not an ordinary agent capability. Keep it with the creator and do not put it
into an agent's long-term MCP configuration unless that is deliberately
approved.

The generator writes both tokens to mode `0600` files and never prints their
values.

## Values the agent must receive from the creator

The agent can generate secrets, but these values require an explicit trusted
input:

- `treasury_id`, unique for this Treasury lineage;
- active `network_id` and `chain_id`;
- `creator_recovery_wallet`, controlled by the creator;
- the approved `policy_registry_hash`;
- for an already-running network, a creator-approved stable `funding_id`, the
  finalized envelope `funding_operation_id` after submission, and the canonical
  submission procedure;
- `/etc/aidn/cometbft-finality.json`, containing at least two approved RPC
  endpoints and an out-of-band trusted checkpoint;
- the node's approved LAN bind address, for example `192.168.88.127`.

The trusted checkpoint must not be bootstrapped from whichever RPC answers
first. The finality file is an authorization/trust input and remains the
creator or network-operator responsibility.

## Fresh host procedure

Run from a reviewed AiDN checkout, not from an arbitrary branch:

```bash
sudo install -d -o root -g root -m 0755 /opt/aidn
sudo git clone https://github.com/glinko/AiDN.git /opt/aidn/AiDN
cd /opt/aidn/AiDN
uv sync --project services/aidn-faucet --frozen
```

Create the secret directory. The command below generates the Treasury key,
both bearer tokens, the public manifest, an environment file and a public
summary. It does not fund the Treasury.

```bash
sudo install -d -o root -g root -m 0700 /var/lib/aidn-faucet
sudo -u root uv run python tools/create-faucet-credentials.py \
  --output-dir /var/lib/aidn-faucet/credentials \
  --treasury-id aidn-faucet-main-v1 \
  --network-id aidn-localnet-1 \
  --chain-id aidn-testnet-1 \
  --creator-recovery-wallet wallet-REPLACE_CREATOR \
  --policy-registry-hash sha256:REPLACE_POLICY_REGISTRY_HASH \
  --funding-mode CONSENSUS \
  --funding-id faucet-funding:aidn-faucet-main-v1:1
```

Replace every `REPLACE_` value before running. For a brand-new network where
the manifest is included before Genesis, use `--funding-mode GENESIS` and omit
`--funding-id`. The command creates a pre-funding manifest; the actual
`funding_operation_id` is produced only after the signed consensus envelope
is built.

The command reports only the Treasury ID, Wallet ID and manifest hash. Inspect
the generated `summary.json`; do not print `treasury.key`, `agent-token`,
`creator-token` or `faucet.env` into an agent transcript.

## Funding the Treasury

The 10,000,000 Q allocation is fixed by the manifest schema. Credential
generation alone does not create balance.

- **GENESIS:** include the validated manifest in the network Genesis before
  the chain starts.
- **CONSENSUS:** use the creator-controlled Wallet to authorize and submit the
  `TREASURY_FUND` envelope through the canonical consensus transaction path.
  Use `tools/create-faucet-treasury-funding.py` to create the signed envelope
  only after the creator supplies the matching creator private key and
  authorization reference. Do not submit it through a Faucet shortcut or
  directly mutate a node's SQLite/state JSON.

The funding tool prints the computed envelope `operation_id`. Run it with
`--final-manifest /var/lib/aidn-faucet/credentials/faucet-treasury.json` to
write that ID into the manifest after the envelope is created. The manifest
hash remains unchanged. Submit the exact generated envelope through the
canonical consensus path, wait for finality, then start or restart the Faucet.

Example envelope preparation:

```bash
sudo -u root uv run python tools/create-faucet-treasury-funding.py \
  --manifest /var/lib/aidn-faucet/credentials/faucet-treasury.json \
  --creator-private-key /secure/creator-recovery.key \
  --output /var/lib/aidn-faucet/treasury-fund-envelope.json \
  --final-manifest /var/lib/aidn-faucet/credentials/faucet-treasury.json \
  --authorization-reference governance:aidn-faucet-main-v1
```

For an already-running testnet, the normal path is `CONSENSUS`. The agent must
stop if the creator Wallet or canonical submission path is unavailable.

The Faucet does not treat this local manifest as proof that funding happened.
After startup it verifies ECO-0009 activation evidence. In `CONSENSUS` mode
the configured finality source must prove the exact `TREASURY_FUND` operation
and manifest hash. In `GENESIS` mode the configured RPC quorum must return the
same manifest from the canonical ABCI path `faucet/treasury-manifest`.
Until that check is `ACTIVE`, the service may expose diagnostics but refuses
new claims.

## Install the service environment

Copy the credentials into the service-owned locations and keep ownership
restricted:

```bash
sudo useradd --system --home-dir /var/lib/aidn-faucet --create-home \
  --shell /usr/sbin/nologin aidn-faucet 2>/dev/null || true
sudo chown -R aidn-faucet:aidn-faucet /var/lib/aidn-faucet
sudo chmod 0700 /var/lib/aidn-faucet /var/lib/aidn-faucet/credentials
sudo chmod 0600 /var/lib/aidn-faucet/credentials/treasury.key \
  /var/lib/aidn-faucet/credentials/agent-token \
  /var/lib/aidn-faucet/credentials/creator-token \
  /var/lib/aidn-faucet/credentials/faucet.env
```

Create `/etc/aidn/faucet.env` as `root:aidn-faucet`, mode `0640`. Do not copy
the tokens into a unit file or command-line history. The environment must
contain:

```dotenv
AIDN_FAUCET_AGENT_TOKEN=...
AIDN_FAUCET_CREATOR_TOKEN=...
AIDN_FAUCET_HOST=192.168.88.127
```

Copy the values from the generated `faucet.env` using a protected local file
operation. Keep `faucet-treasury.json` readable by the service account, but
keep `treasury.key` and the tokens private.

The finality file must be installed separately:

```bash
sudo install -o root -g aidn-faucet -m 0640 \
  /secure-transfer/cometbft-finality.json \
  /etc/aidn/cometbft-finality.json
```

Validate it before starting:

```bash
cd /opt/aidn/AiDN
uv run python -c \
  'from pathlib import Path; from aidn_hypervisor.consensus.deployment import load_cometbft_finality_deployment_config; print(load_cometbft_finality_deployment_config(Path("/etc/aidn/cometbft-finality.json")).model_dump_json())'
```

## Start command

Use the service's virtual environment and the same persistent paths:

```bash
sudo -u aidn-faucet /opt/aidn/AiDN/services/aidn-faucet/.venv/bin/aidn-faucet serve \
  --manifest /var/lib/aidn-faucet/credentials/faucet-treasury.json \
  --private-key /var/lib/aidn-faucet/credentials/treasury.key \
  --state /var/lib/aidn-faucet/faucet.sqlite \
  --finality-config /etc/aidn/cometbft-finality.json
```

The CLI reads the agent token, creator token and host from the protected
environment. It prints the GUI and MCP URLs without printing secret values.

For a temporary test run, use `--lan` instead of `AIDN_FAUCET_HOST` to bind
`0.0.0.0`; a specific LAN IP is preferred because it does not expose other
interfaces.

## systemd installation

Use the reviewed template at
`deploy/systemd/aidn-faucet.service.template`. It uses the exact same
manifest, key, state and finality paths and reads the LAN bind address and
tokens from `/etc/aidn/faucet.env`. Do not put private key bytes or token
values in the unit.

```bash
sudo install -o root -g root -m 0644 \
  deploy/systemd/aidn-faucet.service.template \
  /etc/systemd/system/aidn-faucet.service
```

After installation:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now aidn-faucet
sudo systemctl status aidn-faucet --no-pager
curl --fail http://127.0.0.1:8790/health
```

## LAN verification

Restrict the port to the approved subnet, for example:

```bash
sudo ufw allow from 192.168.88.0/24 to any port 8790 proto tcp
```

Then verify from another LAN host:

```bash
curl --fail http://192.168.88.127:8790/health
curl --fail http://192.168.88.127:8790/
```

The GUI shell is intentionally available without a token, but status and
control actions require the creator token. MCP clients use:

```text
http://192.168.88.127:8790/mcp
```

with `Authorization: Bearer <agent-token>` and must preserve the returned
`Mcp-Session-Id`.

Plain HTTP is acceptable only on the controlled private LAN. Use HTTPS and an
authenticated reverse proxy before allowing access from an untrusted network.

## Agent completion report

The agent must report:

- checked-out commit;
- Treasury ID, Wallet ID and manifest hash only;
- funding mode and consensus funding operation ID, if applicable;
- finality configuration validation result;
- systemd status and `/health` result;
- GUI and MCP URLs;
- firewall rule;
- whether funding reached canonical finality.
- Treasury activation state and proof hash;
- activation diagnostic reason when claims are blocked.

It must never report or paste the Treasury private key, bearer token values,
creator private key, signed funding envelope or Wallet seed material.
