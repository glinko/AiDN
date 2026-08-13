# Protocol Authority Policy

This document defines the deployment boundary for protocol-owned
`EPOCH_TRANSITION` operations. It is required before a validator network can
open an ECO-0007 reward pool.

## Why this exists

CometBFT finality proves that validators agreed on a block. It does not prove
that an arbitrary protocol-origin transaction was produced by the authorized
epoch/governance controller. A transition that carries an unrestricted pool
budget could otherwise authorize Q distribution without a valid authority
decision.

Strict validator mode therefore requires:

- a configured public authority set;
- an explicit signature threshold;
- the exact `protocol_authority_policy_hash` in the transition payload;
- distinct Ed25519 signatures over the canonical envelope signing bytes.

The private keys are held by the protocol authority/governance process and are
never configured on validators. Validators store only public keys and the
threshold.

## Public configuration

The validator accepts one of these environment variables:

```text
AIDN_PROTOCOL_AUTHORITY_POLICY_PATH=/etc/aidn/protocol-authority.json
```

or:

```text
AIDN_PROTOCOL_AUTHORITY_POLICY_JSON=<single-line-json>
```

Only one may be set. The file is public-key material and may be distributed to
all validators through the release/configuration channel. An example shape is:

```json
{
  "version": "aidn.protocol-authority.v1",
  "threshold": 2,
  "authorities": {
    "governance-1": "ed25519:<32-byte-hex-public-key>",
    "governance-2": "ed25519:<32-byte-hex-public-key>",
    "governance-3": "ed25519:<32-byte-hex-public-key>"
  },
  "policy_hash": "sha256:<hash-of-the-canonical-policy>"
}
```

`policy_hash` is optional when creating the file and is validated when present.
Use the canonical hash emitted by `ProtocolAuthorityPolicy.as_dict()` in the
final checked-in deployment artifact. Every validator in one network MUST
load the same policy hash before the first transition that references it.
The threshold is limited to the eight signature slots available in the
canonical operation envelope.

When the policy is absent, strict validator mode uses an explicit empty
fail-closed policy. `EPOCH_TRANSITION` is rejected with
`EPOCH_TRANSITION_AUTHORITY_POLICY_REQUIRED`; it is never accepted unsigned.

## Transition binding

The transition payload contains:

```yaml
protocol_authority_policy_hash: sha256:...
```

Each authority signs `LedgerOperationEnvelope.signing_bytes()`. The signature
does not change `operation_id`; signatures are authorization evidence, not part
of operation identity. The validator deduplicates matching signatures by
trusted public key, so copying one authority signature cannot satisfy a
multi-key threshold.

The same policy is checked at:

1. CometBFT `CheckTx`;
2. ABCI block execution;
3. the deterministic `ExecutionEngine` used by fixtures and replay tooling.

## Operational sequence

1. Governance/epoch engine creates the deterministic transition payload and
   adds the configured policy hash.
2. The authority signers sign the exact unsigned canonical envelope.
3. The signed envelope is independently checked for operation ID, policy hash,
   signature validity and threshold.
4. The transaction enters the normal consensus submission path.
5. Validators accept it only if their public policy files produce the same
   hash and threshold result.
6. After verified finality, the ECO-0007 preflight can expose the exact pool
   budget and the reward batch may be built.

## Rotation

Authority rotation is a protocol/governance change, not an environment-only
edit during an active epoch. The rollout MUST define a future-effective
policy boundary and install the new public policy on every validator before
the first transition using the new hash. A node with a divergent policy must
fail closed rather than participate with a different economic rule.

## Current localnet status

The LAN validator rollout is complete, but the current chain has no finalized
`EPOCH_TRANSITION` with a `GENERAL_DEVELOPMENT` pool budget. Therefore the
ECO-0007 production preflight remains `BLOCKED`, and no payout batch may be
submitted. Configuring this policy is a prerequisite for the next transition;
it does not retroactively create a pool or mint Q.
