# Development Contribution Reward Bridge

This document covers the implementation bridge from RFC-0068 contribution
evidence to ECO-0007 reward planning. It is deliberately separate from the
external Faucet Treasury described by ECO-0008.

## Wallet claim file

A reward-seeking contribution may include the following signed file in the
merged revision:

```text
.aidn/contributor-wallet.json
```

The file contains the contributor identity, source-platform account, Wallet
address, public key, Ed25519 signature, optional binding references and a
claim hash. The verifier reads it from the exact merged commit and matches it
to the registered contributor Wallet binding.

The file is immutable evidence. It is never overwritten after payment. A
Wallet change uses a new signed claim in a later contribution; old rewards
remain bound to the historical claim.

## Lifecycle

```text
PR merged
  -> exact merge evidence and Wallet claim verified
  -> RFC-0068 Contribution Attestation
  -> challenge window closes
  -> attestation finalized
  -> ECO-0007 reward preview
  -> Governance and epoch-pool authorization
  -> ordered consensus plan
  -> immediate or unclaimed payment
  -> maturity stages at their future boundaries
```

The current HTTP APIs are:

```text
POST /api/v1/contributions/rewards/preview
POST /api/v1/contributions/rewards/plan
```

The preview is non-emitting. The plan is hash-bound and requires activation
and finalized epoch evidence. It does not turn GitHub, an agent or an HTTP
caller into a mint authority.

## Safety rules

- GitHub merge webhooks do not directly credit Q.
- A Wallet address in PR text is not sufficient evidence.
- Contribution rewards use ECO-0007 pools, not Faucet Treasury.
- Demand does not expand the authorized reward pool.
- Unverified Wallets remain `UNCLAIMED`.
- Immediate and maturity stages are separate replay-protected payments.
