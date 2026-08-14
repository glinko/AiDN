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
POST /api/v1/contributions/rewards/production-batch
```

The preview is non-emitting. The plan is hash-bound and requires activation
and finalized epoch evidence. It does not turn GitHub, an agent or an HTTP
caller into a mint authority. The production-batch route additionally binds a
bounded deployment profile and returns an ordered consensus plan; it still
does not submit that plan. See
[eco-0007-production-reward-batch.md](./eco-0007-production-reward-batch.md)
for the operator workflow.

## Read-only merge intake

The repository includes `tools/prepare-rfc0068-attestation.py` to remove the
most error-prone manual step. It accepts only evidence that can be checked
locally:

- the merge commit is reachable from the protected branch;
- changed files and line counts come from `git diff --numstat`, not caller
  supplied totals;
- the evidence root includes the resolved merge commit, protected-branch tip
  and ancestry verification method;
- `.aidn/contributor-wallet.json` is read from the exact merge commit;
- its Ed25519 signature and claim hash are valid;
- its Wallet and public key match a historical binding in the supplied
  RFC-0068 evidence store;
- the source-platform evidence reference is a real `sha256:` commitment.
- production reward planning also requires the repository's public authority
  key registry, a valid signature for every listed authority, the policy
  threshold, and a verified Wallet state.

Example:

```powershell
.\.venv\Scripts\python.exe tools\prepare-rfc0068-attestation.py `
  --repository-path C:\work\AiDN `
  --evidence-store C:\var\aidn\contribution-evidence.json `
  --repository-id aidn `
  --pull-request-id 123 `
  --merge-commit-hash <protected-branch-merge> `
  --base-branch main `
  --source-commit-hash <source-commit> `
  --merge-actor github:maintainer `
  --pull-request-author github:contributor `
  --primary-contributor-id contributor-... `
  --contribution-epoch 1 `
  --contribution-class CODE `
  --source-platform-evidence-hash sha256:<forge-event-root> `
  --attestation-authority-id maintainer-1\|maintainer `
  --output rfc0068-attestation-intake.json
```

The output is a `READ_ONLY_PREPARED_REQUEST`. It is an input for
`POST /api/v1/contributions/attestations`, not a finalized attestation. The
maintainer still submits the request, waits for the challenge window, resolves
any challenge, and calls the finalize endpoint. The command never writes the
evidence store, creates maintainer signatures, transfers Q, or broadcasts a
consensus transaction. The output includes `attestation_context` with the
derived contribution ID, evidence roots, role allocations, and exact UTF-8
signing bytes (hex encoded) for each authority. Each authority signs its own
payload independently; replace the `PENDING` entries with the returned
`ed25519:<128-hex>` signatures before submitting the request. For an economic
or security-sensitive repository policy, supply the required independent
authority entries; do not reuse an operator Wallet or protocol-authority seed
as contributor evidence.

Attach the signatures without editing the JSON by hand:

```powershell
.\.venv\Scripts\python.exe tools\attach-rfc0068-authority-signatures.py `
  --input rfc0068-attestation-intake.json `
  --authority-signature maintainer-1\|ed25519:<128-lowercase-hex> `
  --output rfc0068-attestation-signed.json
```

For threshold policies, repeat `--authority-signature` for every prepared
authority. The tool only attaches externally produced signatures and
recomputes the evidence root; it deliberately reports that server-side public
key verification is still required.

## Safety rules

- GitHub merge webhooks do not directly credit Q.
- A Wallet address in PR text is not sufficient evidence.
- Contribution rewards use ECO-0007 pools, not Faucet Treasury.
- Demand does not expand the authorized reward pool.
- Unverified Wallets remain `UNCLAIMED`.
- Immediate and maturity stages are separate replay-protected payments.
- A prepared intake JSON is not a contribution attestation and cannot enter a
  reward batch until the service records it as `FINALIZED`.
