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

