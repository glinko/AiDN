# OPS-0001 — AiDN Public Validator Operator Runbook

Status: Draft  
Version: 0.1

## 1. Purpose

This runbook defines the required procedure for an independent operator to deploy, verify, operate, restart, state-sync, and produce public evidence for an AiDN validator.

The goal is:

```text
clean host
    ↓
verified binary
    ↓
verified genesis/trust anchor
    ↓
validator online
    ↓
synced
    ↓
participating
    ↓
restart/state-sync proven
    ↓
evidence bundle signed
```

A public validator release is not considered operationally proven until at least one independent operator completes this runbook without private developer intervention.

## 2. Scope

This runbook covers:

- Linux host preparation;
- binary verification;
- node and validator keys;
- genesis;
- checkpoint/trust anchor;
- P2P bootstrap;
- RPC;
- TLS/reverse proxy guidance;
- system service;
- synchronization;
- validator participation;
- restart;
- state sync;
- snapshot restore;
- evidence collection.

Secrets MUST NOT be included in the public evidence bundle.

## 3. Reference platform

Initial reference platform:

```text
Ubuntu 24.04 LTS x86_64
systemd
chrony/systemd-timesyncd
```

Other platforms MAY be supported later.

## 4. Minimum host requirements

The release documentation MUST publish actual measured requirements.

Placeholder minimum profile:

```text
CPU: 4 cores
RAM: 8 GB
Storage: 100 GB SSD
Network: stable broadband
Public reachability: P2P TCP/UDP as required by active transport profile
Clock synchronization: required
```

Operators MUST consult release-specific values.

## 5. Create service user

Example:

```bash
sudo useradd \
  --system \
  --create-home \
  --home-dir /var/lib/aidn \
  --shell /usr/sbin/nologin \
  aidn
```

Directories:

```bash
sudo install -d -o aidn -g aidn /var/lib/aidn
sudo install -d -o aidn -g aidn /var/lib/aidn/config
sudo install -d -o aidn -g aidn /var/lib/aidn/data
sudo install -d -o aidn -g aidn /var/lib/aidn/evidence
sudo install -d -o root -g root /etc/aidn
```

## 6. Obtain release

Operator MUST obtain:

- release binary/package;
- checksums;
- release signature;
- active Implementation Profile artifact;
- fixture manifest hash;
- genesis/trust-anchor bundle.

Example verification workflow:

```bash
sha256sum -c aidn-linux-amd64.sha256
```

If release signatures are used:

```bash
aidn release verify \
  --binary ./aidn \
  --manifest ./release-manifest.json \
  --signature ./release-manifest.sig
```

A checksum/signature mismatch is a hard stop.

## 7. Install binary

Example:

```bash
sudo install -m 0755 ./aidn /usr/local/bin/aidn
/usr/local/bin/aidn version
/usr/local/bin/aidn profile show
```

Record output for evidence.

## 8. Generate node identity

Run as service user:

```bash
sudo -u aidn aidn keys node generate \
  --home /var/lib/aidn
```

Expected outputs:

```text
node public key
node ID
private key stored with restricted permissions
```

Private keys MUST NOT be printed into shell history or evidence.

## 9. Generate validator key

```bash
sudo -u aidn aidn keys validator generate \
  --home /var/lib/aidn
```

Operator MUST back up the validator key using the project-approved secure procedure.

Recommended:

- offline encrypted backup;
- second offline copy;
- documented recovery test.

## 10. File permissions

Check:

```bash
sudo find /var/lib/aidn -maxdepth 3 -type f -printf '%m %u %g %p\n'
```

Private key files MUST NOT be world-readable.

## 11. Obtain genesis bundle

A public network release MUST publish a genesis/trust-anchor bundle described by EVD-0001.

Operator MUST verify:

```bash
aidn genesis verify \
  --bundle ./aidn-genesis-bundle \
  --network-id <NETWORK_ID>
```

The command MUST verify at minimum:

- genesis hash;
- network ID;
- profile commitment;
- initial state/AppHash commitment where applicable;
- signer threshold or release authorization.

## 12. Trust anchor / checkpoint

If joining after genesis, operator SHOULD obtain a trusted checkpoint bundle from multiple independent channels.

Example:

```bash
aidn checkpoint verify \
  --checkpoint checkpoint.json \
  --genesis genesis.json
```

Record:

```text
height
block hash
AppHash
checkpoint signer set
```

A checkpoint is a trust anchor for bootstrap, not permission to ignore later consensus verification.

## 13. Configure node

Example configuration skeleton:

```toml
network_id = "<NETWORK_ID>"
profile_id = "aidn-mainnet-candidate-1"

[p2p]
listen = "0.0.0.0:26656"
external_address = "<PUBLIC_IP_OR_DNS>:26656"
max_inbound_peers = 40
max_outbound_peers = 20

[rpc]
listen = "127.0.0.1:26657"

[consensus]
timeout_commit = "<release default>"

[state_sync]
enabled = false
```

The actual generated config for the release is authoritative.

## 14. Bootstrap peers

Operator MUST NOT be required to trust one privileged Hypervisor.

The release SHOULD support multiple interchangeable sources:

- cached peers;
- manual peers;
- DNS seeds;
- signed seed manifest;
- local discovery where applicable.

For validator bootstrap, the operator SHOULD configure multiple independently controlled peers.

## 15. Firewall

Example:

```bash
sudo ufw allow 26656/tcp
sudo ufw deny 26657/tcp
```

If QUIC/UDP transport is active, open the release-defined UDP port.

RPC SHOULD remain localhost-only unless intentionally published through authenticated/TLS infrastructure.

## 16. Public RPC

If public RPC is required for evidence or operation:

- terminate TLS;
- apply rate limiting;
- disable unsafe administrative methods;
- do not expose private key operations;
- publish only methods defined safe by the release profile.

Example architecture:

```text
Internet
   ↓ TLS
Reverse Proxy
   ↓ localhost
AiDN RPC
```

## 17. systemd service

Example:

```ini
[Unit]
Description=AiDN Validator
After=network-online.target
Wants=network-online.target

[Service]
User=aidn
Group=aidn
ExecStart=/usr/local/bin/aidn start --home /var/lib/aidn
Restart=on-failure
RestartSec=5
LimitNOFILE=65536
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Install:

```bash
sudo systemctl daemon-reload
sudo systemctl enable aidn
sudo systemctl start aidn
```

## 18. First startup checks

```bash
sudo systemctl status aidn --no-pager
journalctl -u aidn -n 200 --no-pager
```

Hard-stop conditions include:

- genesis mismatch;
- profile mismatch;
- AppHash mismatch;
- validator key load failure;
- unsupported snapshot;
- repeated consensus panic.

## 19. RPC status

Expected command:

```bash
aidn rpc status --rpc http://127.0.0.1:26657 --json
```

Required fields:

```text
network_id
node_id
latest_height
latest_app_hash
catching_up
validator_address/status
peer_count
software_version
profile_id
```

## 20. P2P verification

```bash
aidn rpc peers --rpc http://127.0.0.1:26657 --json
```

Operator SHOULD verify diversity:

- more than one peer;
- multiple IP ranges where available;
- no accidental single-peer dependence.

## 21. Sync completion

Node is synchronized when release-defined conditions hold, minimally:

```text
catching_up = false
latest_height advances normally
latest AppHash matches multiple independent observations
```

## 22. Validator participation

Operator MUST verify that the validator is actually participating, not merely synchronized.

Example:

```bash
aidn validator status --json
```

Evidence SHOULD include:

```text
validator pubkey/address
voting power
active/inactive state
recent signatures or participation statistics
```

## 23. AppHash cross-check

At a chosen height H:

1. Query local node.
2. Query at least two independent public nodes.
3. Compare block ID and AppHash.

Record all three observations.

Mismatch is a hard stop and incident.

## 24. Graceful restart drill

Required production drill:

```bash
sudo systemctl stop aidn
sleep 10
sudo systemctl start aidn
```

Verify:

- no state corruption;
- node catches up;
- AppHash matches network;
- validator resumes participation.

Capture evidence before and after.

## 25. Abrupt process failure drill

On a non-critical test window or staging/public test validator:

```bash
sudo kill -9 "$(pidof aidn)"
sudo systemctl start aidn
```

Verify crash consistency and recovery.

Production policy may require approval before performing this on a high-power validator.

## 26. Snapshot export

```bash
sudo -u aidn aidn snapshot create \
  --home /var/lib/aidn \
  --output /var/lib/aidn/evidence/snapshot
```

Verify:

```bash
aidn snapshot verify /var/lib/aidn/evidence/snapshot
```

## 27. Snapshot restore drill

On a separate host or isolated data directory:

```bash
aidn snapshot restore \
  --snapshot ./snapshot \
  --home /var/lib/aidn-restore-test
```

Then query restored:

```text
height
state root
AppHash
profile
```

They MUST match the snapshot manifest.

## 28. State sync drill

Configure a clean node with:

- verified genesis;
- verified trust height/hash/AppHash;
- at least two independent RPC servers.

Run state sync.

After completion:

```text
AppHash(state-synced node, H)
==
AppHash(full node, H)
```

Then allow at least one additional block and compare again.

## 29. Validator key safety during restore

Snapshot/state sync MUST NOT overwrite validator private keys.

Operator MUST verify key identity before and after recovery.

## 30. Upgrade procedure

Before upgrade:

```bash
aidn version
aidn profile show
aidn snapshot create ...
```

Verify target release compatibility using MIG-0001.

Upgrade MUST NOT proceed if:

- target binary cannot read current state/snapshot;
- activation height is not reached/appropriate;
- validator set is expected to remain mixed in an unsupported combination.

## 31. Rollback procedure

Rollback is permitted only within MIG-0001 rollback rules.

Never roll back application state independently of CometBFT consensus state.

If rollback boundary is crossed, use the documented network recovery procedure instead.

## 32. Evidence collection

Generate evidence:

```bash
aidn evidence collect \
  --home /var/lib/aidn \
  --output /var/lib/aidn/evidence/public-validator
```

The tool SHOULD collect:

- release/version/profile;
- binary hash;
- genesis hash;
- node public identity;
- validator public identity;
- latest status;
- peers summary;
- AppHash observation;
- restart drill record;
- state-sync/snapshot record;
- sanitized config;
- timestamps.

## 33. Evidence redaction

The evidence collector MUST exclude:

- private keys;
- mnemonic phrases;
- API tokens;
- TLS private keys;
- private peer credentials;
- operator personal data not required by the attestation.

## 34. Operator attestation

Operator signs an attestation:

```json
{
  "operator_id": "...",
  "validator_public_id": "...",
  "network_id": "...",
  "release_version": "...",
  "profile_id": "...",
  "evidence_root": "...",
  "statements": [
    "installed from published release artifacts",
    "verified genesis/trust anchor",
    "completed synchronization",
    "verified consensus participation",
    "completed restart drill",
    "completed snapshot or state-sync drill"
  ],
  "signed_at": "...",
  "signature": "..."
}
```

## 35. Independent operator requirement

A release gate SHOULD require attestations from operators who are not members of the same Known Control Group as the core release operator.

The exact threshold belongs in GATE-0001.

## 36. Ongoing health checks

Recommended:

```text
latest height advancing
peer count
missed blocks
disk utilization
clock synchronization
process uptime
RPC health
AppHash spot checks
```

## 37. Incident triggers

Operator SHOULD treat the following as incidents:

- AppHash mismatch;
- repeated consensus divergence;
- validator double-sign risk;
- validator key loss/exposure;
- corrupted state;
- repeated state-sync mismatch;
- profile mismatch;
- inability to verify release/genesis artifacts.

## 38. Double-sign protection

A validator private key MUST NOT be active concurrently on two nodes unless the consensus implementation provides an explicitly safe remote signer design.

Recovery runbooks MUST preserve last-sign state or equivalent CometBFT double-sign protection metadata.

## 39. Evidence completion checklist

```text
[ ] binary verified
[ ] release/profile recorded
[ ] node key generated
[ ] validator key generated and backed up
[ ] genesis verified
[ ] trust anchor/checkpoint verified if used
[ ] P2P reachable
[ ] RPC healthy
[ ] synchronized
[ ] validator participating
[ ] AppHash independently cross-checked
[ ] graceful restart passed
[ ] crash/recovery drill passed where required
[ ] snapshot restore or state sync passed
[ ] evidence bundle generated
[ ] evidence root computed
[ ] operator attestation signed
```

