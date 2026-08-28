# Public Multi-Validator Rollout

The repository already has the cryptographic CometBFT path: trusted
checkpoint, light-client transitions, transaction Merkle proofs, and a bounded
multi-RPC quorum. This document adds the deployment gate needed before calling
that network public.

## Two Separate Claims

`ConsensusFinalityEvidence` proves that a transaction is included in a block
whose CometBFT commit is valid under the trusted checkpoint. It does not prove
that several RPC URLs are operated by independent organizations.

The public rollout therefore requires both:

1. cryptographic finality readiness;
2. signed out-of-band operator-independence evidence.

The second claim is deliberately not inferred from IP addresses, DNS names,
RPC count, or matching answers.

## Profile

Create one JSON `PublicMultiValidatorNetworkProfile` containing at least four
validator manifests. Every manifest contains:

- network and revision binding;
- CometBFT address and base64 public key;
- HTTPS RPC and P2P endpoints;
- genesis and validator configuration hashes;
- operator ID, control-group ID, and operator Ed25519 signature;
- ownership evidence reference.

The profile additionally contains:

- a trusted checkpoint supplied out of band;
- minimum matching RPC agreement;
- minimum distinct operators and control groups;
- an independence evidence root;
- a threshold of release/Governance signatures.

The profile hash excludes signatures but commits every deployment field. The
profile signatures cover the resulting profile hash. A manifest signature
covers the complete manifest except its own signature.

## Acceptance

Trusted release-authority keys must be supplied separately from the profile:

```bash
PYTHONPATH=src python tools/validate-public-multivalidator-profile.py \
  --profile /etc/aidn/public-multivalidator-profile.json \
  --trusted-profile-signer release-authority-a=ed25519:<64-hex> \
  --trusted-profile-signer release-authority-b=ed25519:<64-hex> \
  --write-finality-config /etc/aidn/cometbft-finality.json
```

The command exits non-zero unless:

- all validator manifests are correctly signed;
- validator, consensus-key, RPC and P2P identities are unique;
- the configured RPC quorum and distinct-operator/control-group thresholds
  are met;
- the trusted checkpoint is structurally valid;
- the profile signature threshold is met;
- independence evidence is explicitly marked `OUT_OF_BAND_VERIFIED` and has a
  non-empty evidence root.

The finality config is written only after the complete public gate passes. It
is the existing `CometBftFinalityDeploymentConfig` format and can be activated
by a validator or non-validator Hypervisor:

```bash
export AIDN_CONSENSUS_MODE=non_validator
export AIDN_COMETBFT_FINALITY_CONFIG=/etc/aidn/cometbft-finality.json
```

Validator mode additionally binds evidence to the local ABCI application and
its committed block/application hash. A non-validator verifies the external
operation-bound evidence without pretending to own the validator state.

## Operator Evidence

The profile is not a magic independence oracle. The release evidence package
must retain, outside the protocol where necessary:

- the operator identity attestations;
- the control-group declarations;
- the validator manifests and signatures;
- the trusted checkpoint provenance;
- the exact profile and acceptance report hashes;
- the external RPC observations used for the release decision.

If those attestations are missing, use `NOT_PROVEN_BY_PROTOCOL` and the profile
may still be inspected for cryptographic readiness with
`--allow-unproven-independence`, but it must not be promoted as a public
network authority.

## Current Implementation Status

The repository implementation currently provides the signed profile and static
acceptance boundary:

- each validator manifest is hash-bound and Ed25519-signed by its declared
  operator key;
- the profile binds network, chain, revision, validator identities, RPC/P2P
  endpoints, CometBFT trusted checkpoint, and profile-signature quorum;
- the acceptance report separates cryptographic finality readiness from
  operator-independence readiness;
- the accepted profile can be projected into the existing finality deployment
  configuration without granting the profile tool authority to start nodes or
  move funds.

This is deployment evidence scaffolding, not a claim that a public testnet is
already running. The following gates are still required before a profile is
promoted to a public-network authority:

1. read-only HTTPS RPC observations for every manifest, including chain and
   trusted-checkpoint consistency;
2. a retained genesis/config/trusted-checkpoint release bundle;
3. production deployment and restart/state-sync/fault-drill reports;
4. signed out-of-band operator and control-group independence attestations.

## Operational Boundary

The profile tool does not start CometBFT, open firewall ports, or install
secrets. Each operator owns its node keys and TLS/HTTP deployment. This keeps
deployment authority local while making the public trust input portable and
reviewable.
