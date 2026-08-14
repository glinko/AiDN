# Controlled Localnet Contributor Wallet Profile

This profile authorizes the existing operator Wallet on node `127` for
RFC-0068 contribution-accounting tests and controlled-localnet acceptance runs:

- Wallet: `wallet-5320047bb01d`
- Public key: `ed25519:c17c775a8a0402e695733ed4458dab309dbef2829bf19763ad02ae66bb165e03`
- Network: `aidn-localnet-1`
- Chain: `chain-Anm7Jk`
- Authority policy: `sha256:40c7c0371dca2160043bcd05e37ceb3d8cc8ab33d67bc21b451c95b3e45625a4`
- Authority threshold: `2-of-3`

The machine-readable public profile is
[`controlled-localnet-contributor-wallet-profile.json`](./controlled-localnet-contributor-wallet-profile.json).

## Secret boundary

The Wallet seed is stored outside the repository at:

```text
C:\Users\admin\.aidn\secrets\wallet-5320047bb01d.ed25519.seed
```

It is an external operator secret. It must not be pasted into chat, committed
to Git, copied into an evidence bundle, or written into a public profile. The
seed currently derives to the public key above; the acceptance runner verifies
that relation before creating a claim.

## Controlled acceptance run

Run the existing acceptance runner with the public profile and the external
seed file:

```powershell
python tools/run-controlled-localnet-contribution-acceptance.py `
  --repository-source . `
  --workspace "$HOME\.aidn\controlled-localnet-20260813\contribution-wallet127-workspace" `
  --evidence-store "$HOME\.aidn\controlled-localnet-20260813\contribution-wallet127-evidence" `
  --authority-policy "$HOME\.aidn\controlled-localnet-20260813\protocol-authority.json" `
  --authority-key-dir "$HOME\.aidn\controlled-localnet-20260813\authority-keys" `
  --wallet-profile docs/development/controlled-localnet-contributor-wallet-profile.json `
  --wallet-private-key-file "$HOME\.aidn\secrets\wallet-5320047bb01d.ed25519.seed" `
  --output "$HOME\.aidn\controlled-localnet-20260813\contribution-wallet127-evidence.json" `
  --pool-input-output "$HOME\.aidn\controlled-localnet-20260813\contribution-wallet127-pool-input.json"
```

The runner reports `wallet_profile: EXTERNAL_VERIFIED` on success. With no
Wallet arguments it retains the old `EPHEMERAL_FIXTURE` mode for isolated unit
fixtures.

## Future contribution commits

The signed `.aidn/contributor-wallet.json` is a contribution claim for a
merged logical contribution, not a private-key container. For a real branch or
pull request, generate it from the external seed with
`tools/create-contributor-wallet-claim.py` after the contributor identity and
Wallet binding exist in the RFC-0068 evidence service:

```powershell
python tools/create-contributor-wallet-claim.py `
  --contributor-id <registered-contributor-id> `
  --source-platform-account github:glinko `
  --wallet-address wallet-5320047bb01d `
  --private-key-file "$HOME\.aidn\secrets\wallet-5320047bb01d.ed25519.seed" `
  --output .aidn/contributor-wallet.json `
  --force
```

The claim file is committed with the logical contribution and is verified at
the merged protected-branch revision. It should not be rewritten into every
small follow-up commit, because RFC-0068 groups logical work and prevents
duplicate reward claims.

## Authority signatures

Validators `128`, `129` and `130` currently expose the same authority policy
hash and `2-of-3` threshold through `protocol/authority-policy`. Validators do
not hold the authority private seeds and therefore do not sign contribution
claims directly. The signing keys are kept in the external authority key store
at:

```text
C:\Users\admin\.aidn\controlled-localnet-20260813\authority-keys
```

Before signing, the runner loads the external seed, derives its public key and
the RFC-0068 verifier checks the authority signature against the policy-bound
public key. A policy hash mismatch must stop the run; it must never be solved by
inventing a new local authority key.

This is controlled-localnet evidence only. The Wallet is not an independent
external contributor identity and the authority set is not a public-network
governance policy.
