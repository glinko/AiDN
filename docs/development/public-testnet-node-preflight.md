# Public Testnet Node Preflight

Run this check on each public Ubuntu host before installing a Testnet
Hypervisor. It is read-only: it does not change firewall rules, create keys,
obtain TLS certificates, install packages, or start CometBFT.

The first public Testnet host envelope is intentionally modest:

- Ubuntu 24.04 or newer;
- at least 2 CPU cores, 4 GiB RAM, and 40 GiB free storage at the chosen data
  path;
- NTP/system-clock synchronization;
- a free CometBFT P2P port from the selected Network Profile;
- a declared global public IPv4 address; and
- an explicit operator confirmation that the cloud firewall/security group
  allows incoming TCP traffic to that P2P port.

For a loopback-only Dashboard/API, run:

```bash
uv run python tools/preflight-public-testnet-node.py \
  --profile release/network-profile.toml \
  --public-ipv4 "$PUBLIC_IPV4" \
  --external-p2p-firewall-confirmed \
  --data-path /var/lib/aidn \
  --output evidence/node-preflight.json
```

`--external-p2p-firewall-confirmed` is deliberately explicit. A guest VM
cannot reliably inspect an AWS security group, provider firewall, NAT or
upstream routing policy. It records that the responsible operator reviewed
that boundary; it is not a proof of Internet reachability. The later
multi-node deployment acceptance is the proof.

The Dashboard/API remains loopback-only by default. If a node intentionally
publishes it through HTTPS, add a DNS name and state the TLS termination
boundary:

```bash
uv run python tools/preflight-public-testnet-node.py \
  --profile release/network-profile.toml \
  --public-ipv4 "$PUBLIC_IPV4" \
  --external-p2p-firewall-confirmed \
  --api-exposure public_https \
  --public-dns-name node-a.example.net \
  --tls-termination caddy \
  --output evidence/node-preflight.json
```

The report is `PASS` only when every check passes. A failed preflight is a
deployment blocker, not a command that should be retried until it happens to
say `PASS`.

## Binding a public release

The existing signed G0 release-integrity report can now bind the exact public
network facts. A public build must require both the Network Profile and the
separate trusted-authority registry:

```bash
uv run python tools/build-release-integrity-report.py \
  --release-id aidn-testnet-alpha-1 \
  --network-profile release/network-profile.toml \
  --network-profile-signers release-authority/trusted-profile-signers.json \
  --require-public-network \
  --signing-key release-authority/g0-ed25519.seed \
  --report evidence/gates/g0-release-integrity.json
```

The generated signed manifest then contains the immutable source commit and
package artefact hashes together with the Network Profile hash, consensus
binding hash, `genesis.json` hash, and signed public-validator-profile hash.
The signer registry is a local trust anchor and is not accepted from the
candidate release bundle itself.
