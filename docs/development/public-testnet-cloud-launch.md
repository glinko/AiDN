# Four-Validator Public Testnet Launch

This runbook prepares a real, public AiDN testnet without pretending that
placeholder addresses or locally generated keys are a network.  It is for four
fresh Ubuntu 24.04 cloud hosts and produces a portable, signed release bundle
that later operators can install with the supported bootstrap.

The default architecture is deliberately small:

```text
four independent Ubuntu validators
  TCP 26656 public: CometBFT P2P
  TCP 443 public: HTTPS read-only CometBFT RPC through a reverse proxy
  TCP 8766 private: Hypervisor Dashboard/API
  TCP 26657 private: raw CometBFT RPC
  TCP 26658 loopback: AiDN ABCI
```

It establishes **three-of-four CometBFT finality**: each founding validator
has voting power 1, and CometBFT commits require more than two thirds of the
total voting power.  That means three online validators are sufficient; two
are not.  This is block finality, not a licence for two validators to change
the Genesis or governance policy.

## What the server purchase must provide

Before granting SSH access, prepare four distinct Ubuntu 24.04+ VMs with:

- a stable public IPv4 address each;
- a DNS name each, such as `v1.testnet.example.org`; TLS certificates require
  names, not bare IP addresses;
- one non-root user with passwordless or normal `sudo` and SSH-key access;
- at least 2 vCPU, 4 GB RAM and 30 GB free disk each for the initial validator
  testnet;
- firewall rules: inbound TCP `22` from the administration network, TCP
  `26656` from the Internet, and TCP `443` from the Internet. Keep raw RPC
  `26657`, ABCI `26658`, and Dashboard `8766` private.

Use distinct cloud accounts or at least documented control groups when
possible. Four IP addresses under one account are technically four validators,
but they are not strong operator-independence evidence.

## Inputs that cannot be decided safely in advance

Do not generate these on a workstation or commit them to the repository:

- the four CometBFT validator keys (`priv_validator_key.json` stays on its
  host forever);
- the four operator attestation keys;
- the release-authority private keys;
- the exact P2P node IDs, public IPs/DNS names, certificate material and the
  first trustworthy checkpoint.

The release needs the following human decisions once the machines exist:

| Item | Recommended initial value |
| --- | --- |
| Network ID | `aidn-testnet` |
| Chain ID | `aidn-testnet-1` |
| Environment | `testnet` |
| Network revision | `1` |
| Founding validator power | `1` each |
| RPC agreement | `3` of `4` |
| Public profile signer quorum | `3` of `4` recommended |
| Participation period | 10 minutes |
| Participation settlement | daily |

The final signer quorum is separate from CometBFT block finality. It is a
release-trust decision and should be made explicitly before generating its
signer registry.

## Phase 1 — prepare the four hosts, do not start consensus

On every host, use the reviewed bootstrap commit and its local identity.  At
this point there is no shared Genesis, so the purpose is only to create the
host-local persistent layout, Comet binary, Comet validator key and encrypted
secret store.  Pass `--no-start`; never let a candidate single-node Genesis
produce blocks.

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/glinko/AiDN/<reviewed-commit>/tools/aidn-operator-bootstrap-ubuntu.sh \
  | bash -s -- \
      --ref <reviewed-commit> \
      --operator-id aidn-testnet-v1 \
      --control-group-id <independent-control-group> \
      --network-id aidn-testnet \
      --chain-id aidn-testnet-1 \
      --enable-registry --advertise-host v1.testnet.example.org \
      --wallet-action create --dashboard-pairing code \
      --no-start --non-interactive
```

Repeat with `v2`–`v4`. Keep each reported data directory and Comet home.  Do
not copy any `config/priv_validator_key.json`, operator-attestation key,
Registry master key, wallet seed or pairing code to another host.

## Phase 2 — Genesis ceremony

On each host, export only the public consensus metadata:

```bash
cd ~/aidn/aidn-testnet-v1/AiDN
uv run python tools/public-testnet-genesis.py extract \
  --validator-id aidn-testnet-v1 \
  --validator-key ~/.local/share/aidn/aidn-testnet-v1/consensus/cometbft/config/priv_validator_key.json \
  --output ~/aidn-testnet-v1-public-validator.json
```

Review the four small JSON manifests out of band. A release coordinator builds
the one shared Genesis from those public files:

```bash
uv run python tools/public-testnet-genesis.py build \
  --chain-id aidn-testnet-1 \
  --genesis-time 2026-09-01T12:00:00Z \
  --validator-manifest v1.json --validator-manifest v2.json \
  --validator-manifest v3.json --validator-manifest v4.json \
  --output genesis.json
sha256sum genesis.json
```

Each founding host must receive the identical `genesis.json` through an
authenticated channel. Before either systemd service is enabled, verify that
every received file has the recorded SHA-256 and install it with the guarded
command below.  It checks that neither block nor state database exists, keeps a
copy of the local placeholder Genesis, and cannot be used after a chain starts:

```bash
uv run python tools/public-testnet-genesis.py install \
  --genesis ~/aidn-testnet-release/genesis.json \
  --comet-home ~/.local/share/aidn/aidn-testnet-v1/consensus/cometbft \
  --confirm-unstarted I_CONFIRM_NO_BLOCK_HAS_BEEN_PRODUCED
```

This pre-start ceremony is the only time founding validators intentionally
replace Comet's generated empty Genesis. The normal installer refuses a
mismatched Genesis afterwards.

## Phase 3 — network profile and first blocks

Copy `config/network-profiles/aidn-testnet.toml.example` into the release
directory. Replace its two hashes, four `persistent_peers` entries and (where
appropriate) seed and state-sync entries. The portable release directory must
look exactly like this:

```text
aidn-testnet-release/
  network-profile.toml
  genesis.json
  public-multivalidator-profile.json       # added after the first checkpoint
  trusted-profile-signers.json             # separate trust anchor
```

The example now uses relative asset names specifically so
`aidn-operator-bootstrap-ubuntu.sh --network-profile` can verify and atomically
install this directory. Do not turn the asset paths back into `/etc/...` paths.

The signed public profile contains a trusted checkpoint, so it is necessarily
created **after** the founders have produced and independently observed the
first finalized blocks. The launch is therefore two stages:

1. founders start the reviewed shared Genesis after its hash ceremony;
2. obtain the same height/block/header/validator-set checkpoint from at least
   three HTTPS RPC endpoints, sign four validator manifests and quorum-sign
   `public-multivalidator-profile.json`;
3. publish the complete verified release bundle; all later joining nodes use
   `--network-profile` plus the separately distributed signer registry.

Until step 3 finishes, call the network a *founding testnet*, not a public
network authority.

## Phase 4 — signed public profile and rewards

Use `tools/validate-public-multivalidator-profile.py` against the signed
profile and separate signer registry. Its report must be valid with operator
and control-group independence evidence before promotion. Then copy
`config/testnet-participation.example.toml` to a protected host location,
replace `active_from_epoch`, and follow
[Testnet Release Checklist](./testnet-release-checklist.md).

Nodes do **not** earn Q merely because they are online today. Rewards begin
only after a funded incentive treasury, canonical finalized heartbeat evidence
and the managed payout worker are enabled. This avoids publishing an incentive
promise that the current service cannot settle.

## SSH handoff required from the operator

When the VMs are ready, provide for each of the four hosts:

```text
public IP, DNS name, SSH user, SSH key access, sudo availability,
cloud/control-group identifier, and whether TCP 22/443/26656 are open.
```

With that, the remaining work is deterministic: host preflight, four local
public manifests, Genesis ceremony, TLS/RPC verification, first checkpoint,
signed release bundle, then a multi-node rewards rehearsal.
