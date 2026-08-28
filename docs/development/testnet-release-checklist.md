# Testnet Release Checklist

This checklist produces a real `aidn-testnet-1` release from the templates.
The committed examples are deliberately invalid and must never be selected as
an active network profile.

## Release-owned artifacts

1. Finalize the validator set and generate the immutable `genesis.json`.
2. Build and quorum-sign `public-multivalidator-profile.json` with the release
   authority keys.
3. Publish the trusted public-key registry separately from the candidate
   profile. The profile must not trust its own embedded keys.
4. Replace the hashes and peer/state-sync endpoints in
   `config/network-profiles/aidn-testnet.toml.example`, then package it as a
   portable directory whose profile refers to its sibling `genesis.json` and
   `public-multivalidator-profile.json` by relative path. Install it through
   `aidn-operator-bootstrap-ubuntu.sh --network-profile ...` with the separate
   trusted signer registry.
5. Replace `active_from_epoch` in
   `config/testnet-participation.example.toml` with the finalized activation
   Epoch, copy it outside the repository, and protect it from Dashboard edits.

## Preflight on each operator

```text
aidn network --profile-path /etc/aidn/testnet/network-profile.toml \
  --trusted-signers-path /etc/aidn/testnet/trusted-signers.json verify

aidn participation --program-path /etc/aidn/testnet/participation.toml verify
```

The first command must report `valid: true`; the second prints the exact policy
hash that is bound into every daily settlement. A release should record both
hashes and the genesis hash in its announcement.

## Reward activation

1. Fund the dedicated Testnet Incentive Treasury through its reviewed funding
   path. It is not the Faucet Treasury and not a permanent-emission account.
2. Copy `config/testnet-participation-runtime.example.toml` to a protected
   host path. It starts with `enabled = false`; set a reviewed programme path,
   evidence/payout SQLite paths, Treasury Wallet and **secret reference**
   (never a key) before enabling. Begin with `mode = "dry_run"`.
3. Configure the managed worker with a protected signing key resolved from that
   secret reference, the finalized evidence store, its SQLite payout store and
   the reviewed CometBFT transfer submitter.
4. Run a dry calculation at one finalized Epoch:

```text
aidn participation --program-path /etc/aidn/testnet/participation.toml \
  calculate --evidence-store /var/lib/aidn/testnet-participation/evidence.sqlite \
  --protocol-epoch <epoch> \
  --source-epoch-transition-operation-id <operation-id> \
  --period-start <UTC-RFC3339>
```

5. Reconcile the generated `WALLET_TRANSFER` operation IDs to finality before
   the worker can advance the treasury sequence.
6. Keep the worker disabled until every item above succeeds in a multi-node
   rehearsal.
