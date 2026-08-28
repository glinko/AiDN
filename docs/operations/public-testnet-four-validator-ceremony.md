# Public testnet: four-validator launch ceremony

This ceremony produces a real `aidn-testnet-1` only after four independent
operators and their public endpoints are available. It intentionally has no
placeholder Genesis, fabricated validator key, or self-approved release
profile.

The coordinator never receives an operator's CometBFT validator private key or
its AiDN operator attestation key.

## 1. Collect the public Genesis inputs

On each founding validator, after CometBFT has initialized its home but before
any block is produced:

```bash
uv run python tools/public-testnet-genesis.py extract \
  --validator-id validator-a \
  --validator-key /var/lib/aidn/cometbft/config/priv_validator_key.json \
  --output /tmp/validator-a.genesis-manifest.json
```

Only send the resulting public manifest to the coordinator. Repeat for four
unique validator IDs. The coordinator creates one immutable Genesis:

```bash
uv run python tools/public-testnet-genesis.py build \
  --chain-id aidn-testnet-1 \
  --genesis-time 2026-09-01T18:00:00Z \
  --validator-manifest validator-a.genesis-manifest.json \
  --validator-manifest validator-b.genesis-manifest.json \
  --validator-manifest validator-c.genesis-manifest.json \
  --validator-manifest validator-d.genesis-manifest.json \
  --output genesis.json
```

Every validator independently checks the printed SHA-256 and installs exactly
that file before the first start:

```bash
uv run python tools/public-testnet-genesis.py install \
  --genesis genesis.json \
  --comet-home /var/lib/aidn/cometbft \
  --confirm-unstarted I_CONFIRM_NO_BLOCK_HAS_BEEN_PRODUCED
```

`install` refuses to replace a Genesis after local CometBFT state exists.

## 2. Sign each public deployment manifest locally

The owner first obtains its Comet transport identity locally:

```bash
/var/lib/aidn/cometbft/bin/cometbft show-node-id --home /var/lib/aidn/cometbft
```

Then, on that same validator, create the signed manifest. The attestation key
is the 32-byte local file created by `prepare-operator-identity.py`; it is
read locally and never added to the output.

```bash
uv run python tools/public-testnet-ceremony.py create-validator-manifest \
  --validator-id validator-a \
  --operator-identity /var/lib/aidn/operator-identity/operator-identity.json \
  --operator-attestation-key /var/lib/aidn/operator-identity/operator-attestation-key.raw \
  --genesis-manifest validator-a.genesis-manifest.json \
  --network-id aidn-testnet \
  --chain-id aidn-testnet-1 \
  --network-revision 1 \
  --comet-node-id <40-lowercase-hex-node-id> \
  --rpc-endpoint https://rpc-a.example.net \
  --p2p-endpoint validator-a.example.net:26656 \
  --app-version 1 \
  --genesis genesis.json \
  --configuration /etc/aidn/comet-config-release.json \
  --ownership-evidence OUT_OF_BAND_VERIFIED \
  --ownership-evidence-root sha256:<reviewed-evidence-root> \
  --output validator-a.public-manifest.json
```

The `configuration` digest lets the operator attest to the exact public
connectivity configuration it reviewed. It must be regenerated and re-signed
if that file changes.

## 3. First-block checkpoint and signed public profile

The four founders start only after Genesis hashes, persistent-peer settings,
and firewall/TLS preflight are mutually confirmed. Once a first agreed block
exists, collect the CometBFT checkpoint and build a profile draft from the
four locally signed deployment manifests:

```bash
uv run python tools/public-testnet-ceremony.py build-public-profile-draft \
  --profile-id aidn-testnet-profile-v1 \
  --network-id aidn-testnet \
  --chain-id aidn-testnet-1 \
  --network-revision 1 \
  --effective-epoch 1 \
  --validator-manifest validator-a.public-manifest.json \
  --validator-manifest validator-b.public-manifest.json \
  --validator-manifest validator-c.public-manifest.json \
  --validator-manifest validator-d.public-manifest.json \
  --trusted-checkpoint checkpoint.json \
  --independence-evidence OUT_OF_BAND_VERIFIED \
  --independence-evidence-root sha256:<reviewed-evidence-root> \
  --output public-profile.draft.json
```

Each release authority signs that immutable draft locally, then the coordinator
combines the two or more signature records:

```bash
uv run python tools/public-testnet-ceremony.py sign-public-profile \
  --profile-draft public-profile.draft.json \
  --authority-id release-a \
  --authority-signing-key /secure/release-a.raw \
  --output release-a.signature.json

uv run python tools/public-testnet-ceremony.py assemble-public-profile \
  --profile-draft public-profile.draft.json \
  --profile-signature release-a.signature.json \
  --profile-signature release-b.signature.json \
  --output public-multivalidator-profile.json
```

Validate the final profile with the existing validator:

```bash
uv run python tools/validate-public-multivalidator-profile.py \
  --profile public-multivalidator-profile.json \
  --trusted-profile-signer release-a=ed25519:<public-key> \
  --trusted-profile-signer release-b=ed25519:<public-key>
```

A full public profile cannot be honestly produced before a checkpoint exists.
The initial Genesis installation is therefore a controlled founder ceremony;
the signed profile becomes the trust anchor for subsequent installs and
restarts.

## 4. Build one verified bundle per validator

The coordinator may now generate a host-local bundle for each public Comet
Node ID. It includes the common Genesis, accepted public profile, trusted
signer registry, and an `network-profile.toml` with the other three validators
as `persistent_peers`.

```bash
uv run python tools/public-testnet-ceremony.py build-node-bundle \
  --public-profile public-multivalidator-profile.json \
  --trusted-profile-signers trusted-profile-signers.json \
  --genesis genesis.json \
  --local-comet-node-id <validator-a-node-id> \
  --output-dir release/validator-a
```

The command refuses an unaccepted profile, a Genesis hash mismatch, a node ID
not present in the profile, or an existing output directory. It disables state
sync for founding validators; state sync is configured separately for new
followers after a trustworthy checkpoint has been published.

Finally, run `preflight-public-testnet-node.py` on every host and attach the
resulting profiles to `build-release-integrity-report.py --require-public-network`.
