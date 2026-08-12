# Faucet Treasury Creator Bootstrap

This runbook creates and funds the external Faucet Treasury without granting
the Faucet host authority to mint Q or to change policy unilaterally.

## Roles

| Host | Holds | Must not hold |
| --- | --- | --- |
| Creator workstation | `creator-recovery.key` | Faucet Treasury key |
| Faucet host | `treasury.key`, agent and creator bearer tokens | Creator recovery key |
| Validators | canonical Treasury manifest transition and consensus state | either private key |

The private Creator recovery key must remain on the Creator workstation. Its
public identity and signed artifacts are safe to copy to the Faucet host.

## Bootstrap sequence

The sequence is deliberate. Do not start the Faucet service until step 7.

1. On the Creator workstation, generate a separate recovery wallet:

```bash
uv run python tools/create-faucet-creator-wallet.py \
  --output-dir ~/.local/share/aidn/creator-recovery
```

Keep `creator-recovery.key` offline or in a dedicated secret manager. Copy only
`creator-recovery-wallet.json` when an identity file is required.

2. Choose public, non-secret network values. For the current lab these are:

```text
network_id = aidn-localnet-1
chain_id   = chain-Anm7Jk
```

`network_id` is the AiDN network label; `chain_id` comes from the trusted
CometBFT finality configuration. Do not reuse the lab values for a new network.

3. Create the immutable registry root before the Treasury manifest. It commits
the creator recovery authority, the target network and the target Treasury ID.

```bash
uv run python tools/create-faucet-policy-registry.py \
  --creator-private-key ~/.local/share/aidn/creator-recovery/creator-recovery.key \
  --creator-wallet ~/.local/share/aidn/creator-recovery/creator-recovery-wallet.json \
  --registry-id aidn-localnet-faucet-policy-v1 \
  --network-id aidn-localnet-1 \
  --chain-id chain-Anm7Jk \
  --treasury-id aidn-localnet-faucet-v1 \
  --output ~/.local/share/aidn/faucet-public/policy-registry-root.json
```

4. Create the initial signed release. The fixed daily 50 Q policy is only an
initial release; a later release can use `accumulating-pool` and an explicit
future `--effective-from` boundary.

```bash
uv run python tools/create-faucet-policy-release.py \
  --registry-root ~/.local/share/aidn/faucet-public/policy-registry-root.json \
  --creator-private-key ~/.local/share/aidn/creator-recovery/creator-recovery.key \
  --sequence 1 --policy fixed-daily \
  --policy-version aidn.faucet-policy.v1.fixed-daily.localnet.1 \
  --daily-q 50 \
  --output ~/.local/share/aidn/faucet-public/policy-release-001.json
```

5. Use the `registry_hash` printed in step 3 to create a **pre-finality**
CONSENSUS-funded Treasury credential set on the Faucet host. The `funding_id`
is a stable human-controlled identifier and is not an operation ID.

```bash
uv run python tools/create-faucet-credentials.py \
  --output-dir /var/lib/aidn-faucet/bootstrap \
  --treasury-id aidn-localnet-faucet-v1 \
  --network-id aidn-localnet-1 \
  --chain-id chain-Anm7Jk \
  --creator-recovery-wallet "$(jq -r .wallet_id ~/.local/share/aidn/creator-recovery/creator-recovery-wallet.json)" \
  --policy-registry-hash 'sha256:REPLACE_WITH_ROOT_HASH' \
  --funding-mode CONSENSUS \
  --funding-id aidn-localnet-faucet-genesis-v1
```

Do not configure this manifest through validator environment variables. It is
not active until the following one-time consensus transition finalizes; this
prevents an arbitrary wallet or a single validator from declaring itself the
Treasury.

6. After every validator has deployed the release supporting
`TREASURY_MANIFEST_BIND`, create the Creator-signed manifest-bind envelope.
The private key remains on the Creator workstation.

```bash
uv run python tools/create-faucet-treasury-manifest-bind.py \
  --manifest /secure-copy/faucet-treasury.json \
  --creator-private-key ~/.local/share/aidn/creator-recovery/creator-recovery.key \
  --authorization-reference governance:aidn-localnet-faucet-v1 \
  --output ~/.local/share/aidn/faucet-public/treasury-manifest-bind-envelope.json
```

7. Submit the bind envelope through the trusted CometBFT quorum and wait for
operation-bound finality. Only after this succeeds can `TREASURY_FUND` pass
CheckTx.

```bash
uv run python tools/submit-faucet-treasury-manifest-bind.py \
  --manifest /secure-copy/faucet-treasury.json \
  --envelope ~/.local/share/aidn/faucet-public/treasury-manifest-bind-envelope.json \
  --finality-config /etc/aidn/cometbft-finality.json
```

8. On the Creator workstation, create the signed funding envelope. This signs
only the canonically bound manifest and does not transfer any private key.

```bash
uv run python tools/create-faucet-treasury-funding.py \
  --manifest /secure-copy/faucet-treasury.json \
  --creator-private-key ~/.local/share/aidn/creator-recovery/creator-recovery.key \
  --authorization-reference governance:aidn-localnet-faucet-v1 \
  --output ~/.local/share/aidn/faucet-public/treasury-fund-envelope.json
```

9. Submit that exact signed envelope through the trusted CometBFT quorum. The
command writes the post-finality manifest only after the transaction has
operation-bound verified finality. It also atomically records the verified
transaction hash in `legacy_transaction_hashes` in the supplied finality
configuration. This restart-safe record is required for the Faucet to verify
the funding operation after its in-memory submission registry is lost.

```bash
uv run python tools/submit-faucet-treasury-funding.py \
  --manifest /secure-copy/faucet-treasury.json \
  --envelope ~/.local/share/aidn/faucet-public/treasury-fund-envelope.json \
  --finality-config /etc/aidn/cometbft-finality.json \
  --final-manifest /secure-copy/faucet-treasury-final.json
```

Copy the final manifest, signed root and signed release to the Faucet host.
Only then start the service:

```bash
aidn-faucet serve \
  --manifest /etc/aidn/faucet-treasury.json \
  --private-key /var/lib/aidn-faucet/treasury.key \
  --state /var/lib/aidn-faucet/faucet.sqlite \
  --finality-config /etc/aidn/cometbft-finality.json \
  --policy-registry-root /etc/aidn/faucet-policy-registry-root.json \
  --policy-release /etc/aidn/faucet-policy-release.json \
  --lan
```

## Finality checkpoint rotation

Rotating a trusted CometBFT checkpoint does not require another
`TREASURY_FUND`. The funding transition remains in replicated ABCI state and
the Faucet verifies that state through its configured RPC quorum whenever the
historical transaction proof predates the new checkpoint. A rotation procedure
MUST preserve `legacy_transaction_hashes`; it MUST NOT replace the Treasury
manifest, final manifest, or Faucet SQLite state. A new checkpoint is an
authentication anchor for subsequent consensus verification, not a new
economic genesis.

Use the checked-in tool to rotate the checkpoint. It queries every configured
RPC endpoint, requires the configured quorum to agree on the exact block,
AppHash, current validator set and next-validator-set hash, validates the
deployment schema, and atomically preserves `legacy_transaction_hashes`:

```bash
uv run python tools/rotate-cometbft-finality-checkpoint.py \
  --config /etc/aidn/cometbft-finality.json \
  --height <quorum-verified-height>
```

Use `--output /path/to/new-config.json` for a staged file. The tool rejects a
checkpoint at or below the current height, non-canonical commits, mismatched
validator hashes, and insufficient RPC agreement. Do not edit the JSON by
hand and do not delete historical transaction bindings during a rotation.

## Policy change

The manifest hash never changes when a policy changes. Create a new signed
release with a higher sequence and a future effective timestamp, retain the old
release for audit, then restart the Faucet with the new release. The service
stores policy state under the signed release hash, so an accumulating-pool
release cannot inherit a predecessor's state accidentally.

## Invariants

- The Faucet process cannot mint Q and accepts only canonical `WALLET_TRANSFER`
  claims after Treasury activation.
- A `TREASURY_FUND` is accepted only when its signed payload matches the
  consensus-bound pre-finality manifest.
- `TREASURY_MANIFEST_BIND` is one-time, Creator-signed and committed in the
  same ABCI state and AppHash as all other canonical transitions.
- `funding_operation_id` is a finalized operation identity, never an input
  guessed by an operator.
- A policy release is valid only when its hash, root binding, signature,
  parameters and effective window all verify.
