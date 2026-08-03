# RFC-0068 Evidence Mode

Status: implemented locally, non-emitting

This document records the first executable slice of RFC-0068. It is an
evidence and attribution service only. It does not implement ECO-0007 and
cannot mint, reserve, transfer, or settle Q.

## Implemented Boundary

The service currently provides:

- an Eligible Repository Set and repository contribution profiles;
- protected-branch verification against a local Git checkout;
- Contributor Identity records;
- signed Ed25519 Wallet binding challenges with one-use replay protection;
- merge events bound to repository, pull request, commit, branch, and source evidence;
- deterministic ECU, sublinear Size Score, and fixed-point CU calculation;
- generated, vendor, lockfile, binary, and formatting exclusion;
- contribution groups and bounded role allocations;
- maintainer attestation thresholds, including two authorities for security work;
- challenge windows and immutable attestation replacement history;
- stage-one and stage-two maturity records with explicit revert classifications;
- atomic JSON persistence independent from the Hypervisor Ledger snapshot;
- a local HTTP API under `/api/v1/contributions`.

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

The response must remain equivalent to:

```json
{
  "mode": "EVIDENCE_ONLY",
  "emits_q": false,
  "ledger_writes": false,
  "protocol": "RFC-0068"
}
```

## Local Attestation Flow

1. Register a repository profile at `POST /api/v1/contributions/profiles`.
2. Register the repository at `POST /api/v1/contributions/repositories`.
3. Register the contributor and source-forge account at `POST /api/v1/contributions/contributors`.
4. Issue a Wallet challenge and sign the canonical binding payload with the Wallet key.
5. Submit the signed binding and source-platform confirmation hash.
6. Submit a merge attestation with the local checkout path and changed-file evidence.
7. Wait until `challenge_until_epoch` has closed, resolve any open challenge, and finalize the attestation.
8. Record maturity decisions at the RFC-defined epoch boundaries.

The Git verifier requires the merge commit to resolve locally and to be an
ancestor of the protected branch (or its local `origin/<branch>` tracking
ref). A boolean supplied by a caller is not accepted as merge proof.

## API Safety Boundary

The API intentionally has no request fields for:

- Q amounts;
- reward pool balances;
- payment operations;
- Ledger operation IDs;
- emission or vesting decisions.

`wallet_address` is evidence of a binding, not a payment destination. A
contribution without a verified Wallet remains attributable with
`wallet_state: UNCLAIMED`.

Validator-mode write protection continues to reject these HTTP mutations;
canonical consensus writes are not introduced by this evidence slice.

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
- ECO-0007 pool allocation and normalization;
- contribution reward records and Ledger operations;
- Q payments, maturity reserves, and unclaimed reward claims;
- automated Reputation changes;
- decentralized challenges and appeals.

Those features require approved economic and governance profiles. They must be
added as separate, auditable layers rather than making the evidence service a
hidden minting authority.
