# RFC-0068 Evidence Mode

Status: implemented locally, evidence and consensus-gated reward planning

This document records the first executable slice of RFC-0068. It is an
evidence and attribution service. It does not autonomously mint or transfer
Q. Finalized evidence can now feed the ECO-0007 fixed-point calculator and
produce a reviewable consensus operation plan; only an explicitly activated
ECO-0007 plan can enter the Ledger.

## Implemented Boundary

The service currently provides:

- an Eligible Repository Set and repository contribution profiles;
- protected-branch verification against a local Git checkout;
- Contributor Identity records;
- signed Ed25519 Wallet binding challenges with one-use replay protection;
- signed `.aidn/contributor-wallet.json` claims read from the exact merged
  commit and bound to the registered Wallet binding;
- merge events bound to repository, pull request, commit, branch, and source evidence;
- deterministic ECU, sublinear Size Score, and fixed-point CU calculation;
- generated, vendor, lockfile, binary, and formatting exclusion;
- contribution groups and bounded role allocations;
- maintainer attestation thresholds, including two authorities for security work;
- a repository-scoped public key registry and Ed25519 verification for
  production-bound attestation authorities; legacy evidence-only records may
  remain unverified until they are re-attested;
- challenge windows and immutable attestation replacement history;
- stage-one and stage-two maturity records with explicit revert classifications;
- atomic JSON persistence independent from the Hypervisor Ledger snapshot;
- a local HTTP API under `/api/v1/contributions`.
- an ECO-0007 preview and consensus-plan bridge under
  `/api/v1/contributions/rewards`.

All scoring uses integer milli-units. The default CU calculation is:

```text
ECU_milli = sum(weighted eligible changed lines)
SizeScore_milli = min(isqrt(ECU_milli * 1000), profile cap)
CU_milli = floor(
  SizeScore_milli * complexity * priority * quality * impact * independence
  / 1000^5
)
```

The canonical hash prefix is `sha256:` over versioned, sorted, compact JSON.
Attestation replacement never deletes the prior hash; the local store retains
the previous object in `attestation_history`.

## Runtime Configuration

When `AIDN_HYPERVISOR_STATE_PATH` is set, the application stores contribution
evidence at:

```text
<state-directory>/contribution-evidence.json
```

Without a state path the service is intentionally in-memory, which is useful
for unit tests and disposable development nodes. The application exposes:

```text
GET /api/v1/contributions/status
```

The response includes:

```json
{
  "mode": "EVIDENCE_ONLY",
  "emits_q": false,
  "ledger_writes": false,
  "protocol": "RFC-0068",
  "reward_preview": true,
  "reward_execution": "ECO-0007_CONSENSUS_GATED"
}
```

## Local Attestation Flow

1. Register a repository profile at `POST /api/v1/contributions/profiles`.
2. Register the repository at `POST /api/v1/contributions/repositories`.
3. Register the contributor and source-forge account at `POST /api/v1/contributions/contributors`.
4. Issue a Wallet challenge and sign the canonical binding payload with the Wallet key.
5. Submit the signed binding and source-platform confirmation hash.
6. Commit `.aidn/contributor-wallet.json` in the contribution and submit a
   merge attestation with the local checkout path and changed-file evidence.
   `tools/prepare-rfc0068-attestation.py` can perform the protected-branch,
   exact-commit, diff and historical Wallet-binding checks and write a
   read-only request package before submission. Use `--attestation-authority-id`
   to emit exact authority signing payloads first; signatures are supplied by
   the independent authorities in a second step. Use
   `tools/attach-rfc0068-authority-signatures.py` to attach them without
   hand-editing the package.
7. Wait until `challenge_until_epoch` has closed, resolve any open challenge, and finalize the attestation.
8. Request an ECO-0007 preview for the finalized attestation batch.
9. Obtain the required Governance activation and finalized epoch pool evidence
   before building or submitting a consensus plan.
10. Record maturity decisions at the RFC-defined epoch boundaries.

## Wallet claim file

The canonical file path is:

```text
.aidn/contributor-wallet.json
```

It contains the contributor identity, source-platform account, Wallet address,
Wallet public key, Ed25519 signature, and optional binding references. The
signature covers the canonical JSON object with the signature and `claim_hash`
fields excluded, under domain `aidn.contributor-wallet-claim.v1`. The
`claim_hash` then commits the complete signed claim. The attestation verifier
reads this file from the exact merge commit and checks the registered binding.

The file is immutable evidence. It is **not** overwritten after payment. A
wallet rotation or correction is represented by a new signed claim and a new
attestation/correction lineage; changing a working-tree file after merge does
not alter the historical reward destination.

The Git verifier requires the merge commit to resolve locally and to be an
ancestor of the protected branch (or its local `origin/<branch>` tracking
ref). A boolean supplied by a caller is not accepted as merge proof.

## API Safety Boundary

The API intentionally has no request fields for direct transfer authority:

- Q amounts;
- direct Wallet credit;
- unbounded emission;
- bypassing the ECO-0007 activation gate.

`POST /api/v1/contributions/rewards/preview` accepts an epoch pool input and
selected finalized contribution IDs, then returns the fixed-point calculation
and wallet provenance. `POST /api/v1/contributions/rewards/plan` additionally
requires a valid activation approval and source epoch transition reference;
it returns ordered envelopes but does not submit them to consensus.

`wallet_address` is evidence of a binding, not a payment destination. A
contribution without a verified Wallet remains attributable with
`wallet_state: UNCLAIMED`.

Before an ECO-0007 consensus plan is built, the service re-runs the production
gate: the attestation must be finalized, the exact merged commit must contain a
valid signed `.aidn/contributor-wallet.json` claim bound to the historical
Wallet binding, and repository authority signatures must verify against the
registered public-key registry. An evidence-only attestation or a current
identity Wallet without the merged claim can still be previewed, but cannot be
paid.

The reward plan is therefore safe to inspect or hand to a consensus-aware
operator, but no HTTP request in this router can directly credit a Wallet.

## Verification

Run the focused suite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\contributions -q --no-cov
```

The suite covers deterministic scoring, exclusion rules, local Git ancestry,
Wallet signatures and replay, challenge/finalization/maturity lifecycle,
persistence, and the non-emitting API.

## Deliberately Deferred

The following remain outside this implementation slice:

- GitHub webhook or forge API ingestion;
- decentralized attestation quorum;
- AST or semantic code analysis;
- automatic GitHub webhook ingestion and unattended Governance activation;
- batch scheduling against a live epoch transition;
- UI controls for reward preview, activation, and payment finality;
- automated Reputation changes;
- decentralized challenges and appeals.

Those features require approved economic and governance profiles. They must be
added as separate, auditable layers rather than making the evidence service a
hidden minting authority.
