# GATE-0001 — AiDN Release Gate Checklist

Status: Draft  
Version: 0.1

## 1. Purpose

Defines binary pass/fail gates for promoting an AiDN build to a public production candidate.

A release SHALL NOT be promoted based on subjective confidence alone.

## 2. Gate classes

```text
G0 Build Integrity
G1 Deterministic Protocol
G2 State/Snapshot Integrity
G3 Multi-Node Consensus
G4 Public Networking
G5 Fault Recovery
G6 Independent Operator
G7 Evidence Publication
```

## 3. G0 — Build Integrity

```text
[ ] reproducible or provenance-attested build produced
[ ] binary/package hashes published
[ ] release manifest signed
[ ] active Implementation Profile generated
[ ] operation catalog hash published
[ ] fixture manifest hash published
[ ] dependency/license scan passes
```

Recommended commands:

```bash
make build
make verify-build
make release-manifest
```

## 4. G1 — Deterministic Protocol

```text
[ ] unit tests pass
[ ] all FIX-0001 fixtures pass
[ ] strict supported-operation coverage = 100%
[ ] unknown operation rejection tested
[ ] unsupported operation version tested
[ ] duplicate operation idempotency tested
[ ] predecessor mismatch tested
[ ] monetary underflow/overflow tested
[ ] canonical JSON/hash golden vectors pass
```

Recommended:

```bash
make test-unit
aidn test fixtures --strict
aidn test operation-coverage --strict
```

## 5. G2 — State/Snapshot Integrity

```text
[ ] snapshot export succeeds
[ ] snapshot verification succeeds
[ ] restore yields identical StateRoot
[ ] restore yields identical AppHash
[ ] state sync yields identical AppHash
[ ] restored/state-synced node advances one block identically
```

## 6. G3 — Multi-Node Consensus

Minimum acceptance topology:

```text
4 validators
at least 2 independently operated hosts/control groups where possible
```

Required:

```text
[ ] all nodes reach same height
[ ] all nodes expose same AppHash at sampled heights
[ ] transaction ordering deterministic
[ ] validator restart does not diverge state
[ ] one validator offline does not halt within tolerated fault model
```

## 7. G4 — Public Networking

```text
[ ] LAN acceptance passes
[ ] public Internet P2P acceptance passes
[ ] bootstrap works from documented public sources
[ ] no single bootstrap peer is mandatory
[ ] public RPC evidence obtainable
[ ] TLS configuration validated where RPC is public
[ ] NAT/relay path tested if part of release profile
```

## 8. G5 — Fault Recovery

Required drills:

```text
[ ] graceful validator restart
[ ] abrupt process termination
[ ] host reboot
[ ] snapshot restore
[ ] state sync
[ ] corrupted/invalid snapshot rejected
[ ] stale predecessor operation rejected after recovery
```

Production candidate SHOULD additionally test:

```text
[ ] temporary network partition
[ ] validator peer loss
[ ] disk-full safety behavior
```

## 9. G6 — Independent Operator

Before public production:

```text
[ ] at least 2 independent operator attestations
[ ] at least 1 operator followed OPS-0001 from a clean host
[ ] no private developer intervention was required
[ ] each attestation contains an EVD-0001 evidence root
```

Threshold may be raised for mainnet.

## 10. G7 — Evidence Publication

Publish:

```text
release manifest
binary hashes
profile artifact/hash
fixture manifest/hash
genesis/trust-anchor bundle
live RPC evidence
fault drill evidence
operator attestations
migration notes
```

## 10.1 Repository gate runner

The local machine-checkable subset is run with:

```bash
uv run python tools/verify-release-gates.py \
  --profile profiles/aidn-mainnet-candidate-1.json \
  --fixture-manifest fixtures/manifest.json \
  --evidence-dir ./evidence
```

The command verifies G0, the deterministic portion of G1, and G7 when an
EVD-0001 bundle is supplied. G2-G6 require operational evidence and remain
`NOT_RUN` until that evidence is provided. `--allow-incomplete` is permitted
for local development only; it does not convert an incomplete report into a
release approval.

## 11. Hard blockers

Any of the following blocks release:

```text
AppHash divergence
fixture failure
strict operation coverage < 100%
snapshot restore mismatch
state sync mismatch
genesis verification ambiguity
unresolved validator double-sign risk
unsupported mixed-version state
missing migration rule for changed state/AppHash
missing independent operator evidence
```

## 12. Release gate result

Machine-readable result:

```json
{
  "release": "...",
  "profile_id": "...",
  "gates": {
    "G0": "PASS",
    "G1": "PASS",
    "G2": "PASS",
    "G3": "PASS",
    "G4": "PASS",
    "G5": "PASS",
    "G6": "PASS",
    "G7": "PASS"
  },
  "evidence_root": "...",
  "approved_at": "...",
  "status": "PASS"
}
```
