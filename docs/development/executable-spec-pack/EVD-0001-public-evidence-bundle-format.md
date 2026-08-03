# EVD-0001 — AiDN Public Evidence Bundle Format

Status: Draft  
Version: 0.1

## 1. Purpose

Defines a portable, hash-addressed evidence package proving that a release and validator deployment passed required public operational gates.

## 2. Directory format

```text
evidence/
├── manifest.json
├── release/
│   ├── binary.sha256
│   ├── version.json
│   ├── profile.json
│   └── operation-catalog.json
├── network/
│   ├── genesis.json
│   ├── genesis.sha256
│   ├── trust-anchor.json
│   └── checkpoint-observations.json
├── validator/
│   ├── node-identity.json
│   ├── validator-public-identity.json
│   ├── rpc-status.json
│   ├── peers-summary.json
│   └── consensus-participation.json
├── drills/
│   ├── graceful-restart.json
│   ├── abrupt-restart.json
│   ├── snapshot-restore.json
│   └── state-sync.json
├── gates/
│   └── release-gate-result.json
└── attestations/
    └── operator-attestation.json
```

## 3. Manifest

```json
{
  "evidence_format_version": 1,
  "network_id": "...",
  "release_version": "...",
  "profile_id": "...",
  "generated_at": "...",
  "artifacts": [
    {
      "path": "release/version.json",
      "sha256": "..."
    }
  ],
  "evidence_root": "..."
}
```

## 4. Evidence root

Artifacts are ordered lexicographically by path.

In the leaf formula, `sha256(file_bytes)` is represented as its lowercase
64-character hexadecimal ASCII form before concatenation.

For each artifact:

```text
ArtifactLeaf =
SHA256(
  "AIDN:EVIDENCE-LEAF:v1"
  || 0x00
  || path
  || 0x00
  || sha256(file_bytes)
)
```

`evidence_root` is the profile-defined Merkle root over ArtifactLeaf values.

The current `EVD-0001.v1` implementation freezes the internal node rule as:

```text
EvidenceNode(left, right) =
  SHA256(
    "AIDN:EVIDENCE-NODE:v1"
    || 0x00
    || left_digest_bytes
    || right_digest_bytes
  )
```

Artifacts are sorted by normalized POSIX path before leaf construction. An odd
Merkle level duplicates its last digest. A one-artifact bundle uses the leaf
digest as its root. The published string form is `sha256:<64 lowercase hex>`.

## 5. Sensitive data prohibition

Evidence MUST NOT contain:

- validator private keys;
- node private keys;
- mnemonic phrases;
- API secrets;
- TLS private keys;
- private authentication cookies;
- unrelated personal data.

## 6. RPC evidence

RPC evidence SHOULD include raw signed/sanitized JSON responses sufficient to prove:

```text
node ID
network ID
height
AppHash
sync state
validator state
peer count
profile/software version
```

## 7. Checkpoint observation

At least one production evidence bundle SHOULD include cross-node observations:

```json
{
  "height": 12345,
  "observations": [
    {
      "observer": "local",
      "block_hash": "...",
      "app_hash": "..."
    },
    {
      "observer": "independent-rpc-1",
      "block_hash": "...",
      "app_hash": "..."
    }
  ]
}
```

## 8. Drill record

Each drill record MUST include:

```text
start timestamp
end timestamp
initial height/AppHash
action performed
recovery height/AppHash
result
tool/software version
artifact hashes
```

## 9. Operator attestation

The final attestation signs the Evidence Root, not each file independently.

The repository verifier accepts the following canonical attestation shape:

```json
{
  "attestation_version": 1,
  "operator_id": "...",
  "control_group_id": "...",
  "independence_status": "OUT_OF_BAND_DECLARED",
  "operator_public_key": "ed25519:<64 lowercase hex>",
  "evidence_root": "sha256:<64 lowercase hex>",
  "signed_at": "...",
  "signature": "ed25519:<128 lowercase hex>"
}
```

The signature covers the canonical JSON object with `signature` omitted. The
attestation file is control metadata and MUST NOT be included in the artifact
Merkle root.

For G6 independent-operator review, the attestation MUST additionally carry
the operator's declared `control_group_id`. The value is an out-of-band claim;
the bundle signature proves who signed the declaration, not that the
organization is independent. That independence claim requires separate review.
`independence_status` MUST remain `OUT_OF_BAND_DECLARED` until that review is
complete; only the reviewed release evidence may use `OUT_OF_BAND_VERIFIED`.

`gates/release-gate-result.json` is also control metadata. It MAY be published
inside the bundle, but it is excluded from the artifact Merkle root so the
final gate result can be written after the immutable artifact manifest and
operator attestation have been created.

## 10. Verification command

Recommended:

```bash
aidn evidence verify ./evidence
```

It MUST:

1. verify manifest canonical encoding;
2. verify every file hash;
3. recompute Evidence Root;
4. verify operator attestation;
5. report missing required gate artifacts.

## 11. Publication

Evidence bundles MAY be distributed through:

- release artifacts;
- project website;
- Git repository;
- content-addressed storage;
- COMET/AiDN object distribution.

The location is not trusted. Hash/signature verification is authoritative.
