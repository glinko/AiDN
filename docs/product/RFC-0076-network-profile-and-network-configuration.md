# RFC-0076 Network Profile and Network Configuration

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0047 CometBFT Consensus Integration`
- `RFC-0062 Snapshot and State Sync Protocol`
- the signed public multi-validator profile defined by the current release gates

## 1. Purpose

Every Hypervisor SHALL select one explicit `NetworkProfile` before joining a
shared network. The profile prevents a node from silently mixing genesis,
chain, protocol, bootstrap, and local CometBFT settings from different
networks.

Profiles are `development`, `testnet`, `mainnet`, or `custom`. The profile is
operator-readable TOML, but it is not itself a replacement for the signed
public multi-validator profile.

## 2. Trust boundary

The profile separates:

```text
consensus-bound                         local operator configuration
network_id                              bind addresses and ports
chain_id                                seeds and persistent peers
protocol_version                        peer limits and PEX
genesis_sha256                          state-sync RPC sources
public_profile_sha256                   discovery bootstrap hints
```

Consensus-bound values SHALL fail closed when process environment, genesis,
or the signed public profile disagrees. Local values may differ per host.

## 3. TOML schema

```toml
schema_version = "aidn.network-profile.v1"

[network]
name = "aidn-testnet"
network_id = "aidn-testnet"
chain_id = "aidn-testnet-1"
environment = "testnet"
protocol_version = "0.1"
genesis_file = "./genesis.json"
genesis_sha256 = "sha256:..."
public_profile_file = "./public-multivalidator-profile.json"
public_profile_sha256 = "sha256:..."

[network.cometbft]
p2p_host = "0.0.0.0"
p2p_port = 26656
rpc_host = "127.0.0.1"
rpc_port = 26657
persistent_peers = []
seeds = []
max_num_inbound_peers = 40
max_num_outbound_peers = 10
pex = true
addr_book_strict = true

[network.consensus]
timeout_propose = "3s"
timeout_prevote = "1s"
timeout_precommit = "1s"
timeout_commit = "3s"

[network.state_sync]
enabled = true
rpc_servers = []
trust_height = 0
trust_hash = ""

[network.discovery]
enabled = true
bootstrap = []
```

Public `testnet` and `mainnet` profiles SHALL bind a public profile file and
hash. Development and custom profiles MAY omit that binding.

## 4. Verification and activation

`aidn network verify` validates the TOML schema, genesis hash, public-profile
hash, public-profile signatures/manifests against the release-owned authority
registry, and network/chain binding. The authority registry is selected by the
read-only `AIDN_NETWORK_PROFILE_SIGNERS_PATH`; trusting keys embedded only in
the candidate profile is forbidden. Release acceptance still applies the
existing independent-operator and trusted-signer quorum gates.

`aidn network use <name>` activates only a profile that verifies at its final
location. Activation is atomic and preserves the previous profile on failure.

`aidn network show` exposes the effective profile and a canonical hash of only
the consensus-bound fields.

The service consumes a selected profile through `AIDN_NETWORK_PROFILE_PATH`.
An environment variable may fill a missing local setting, but cannot override
a consensus-bound value with a different value.

## 5. Upgrade rule

Changing a consensus-bound field creates a new profile identity and requires
the existing protocol upgrade/governance boundary. Editing a port or peer list
does not create a new network. A node SHALL never rewrite genesis to make an
incompatible profile appear valid.
