# ECO-0009 AiDN Treasury Activation and Canonical Funding Proof

Status: Draft

Version: 0.1

Depends on:

* RFC-0036 AiDN Ledger State Machine
* RFC-0047 AiDN CometBFT Consensus Integration
* RFC-0059 AiDN Ledger Operation Catalog
* RFC-0066 Protocol Upgrade and Emergency Recovery
* RFC-0067 Protocol Governance and Authorization Policy
* ECO-0008 AiDN Faucet Treasury and Policy Execution

## 1. Purpose

This document defines how an external Faucet, Wallet service or operator tool
proves that a declared Faucet Treasury is the Treasury recognized by the
canonical AiDN network.

It closes the distinction between:

```text
Treasury manifest
    !=
canonical Treasury activation
```

A manifest is public configuration. It is not a mint authority, a balance
proof, a creator authorization or permission to spend Q.

## 2. Threat Model

An attacker may create a different Ed25519 key, derive a valid-looking Wallet
ID, publish a manifest containing 10,000,000 Q and run a private Faucet around
it. That object must not become the network Treasury merely because its JSON
is well formed or its local database contains a balance.

The protocol SHALL also defend against:

* a changed manifest paired with an old funding operation;
* a funding operation for a different Treasury being presented as evidence;
* a stale or locally fabricated balance;
* an RPC response from a node on another chain;
* a single inconsistent RPC response;
* replay of a previous Treasury activation;
* a Faucet that starts before canonical funding is final;
* replacement of an already active Treasury without an authorized migration.

## 3. Core Principle

The Faucet MAY issue a claim only after the following relation is verified:

```text
ActiveTreasury
    =
ManifestBinding
    +
CanonicalFundingEvidence
    +
ChainBinding
    +
CanonicalBalanceObservation
```

The activation proof does not mint Q and does not grant a new Ledger
privilege. It is an evidence object consumed by the external Faucet safety
boundary.

## 4. Treasury Activation States

Implementations SHALL expose one of:

* `ACTIVE` - all required evidence is present and internally consistent;
* `UNVERIFIED` - the Treasury may be configured locally, but canonical
  activation or balance evidence is missing;
* `DEGRADED` - evidence was previously available but a current consistency
  check failed;
* `DISABLED` - the service was deliberately configured without activation
  enforcement. This state is not acceptable for a public Faucet deployment.

Only `ACTIVE` permits new Faucet claims.

## 5. Manifest Binding

The proof SHALL bind all of the following to the supplied manifest:

* `treasury_id`;
* `network_id`;
* `chain_id`;
* Treasury `wallet_id`;
* Treasury public key through the manifest Wallet derivation;
* `manifest_hash`;
* `funding_mode`;
* `funding_id` for consensus funding;
* `funding_operation_id` when funding mode is `CONSENSUS` and finalization has
  occurred;
* exact initial allocation of `10,000,000 Q`.

The proof hash SHALL cover the complete canonical proof payload. A caller
cannot replace one field after the proof was created without changing the
proof hash.

## 6. Consensus Funding Proof

For `funding_mode: CONSENSUS`, the proof SHALL contain:

* the exact finalized `funding_operation_id` from the funding receipt or
  post-finalization manifest;
* the stable `funding_id` bound by the canonical manifest and operation
  payload;
* operation type `TREASURY_FUND`;
* verified finality evidence for that operation;
* matching `chain_id`;
* matching `manifest_hash` binding;
* block height, block ID, AppHash and commit hash from the finality evidence;
* the configured finality quorum and source count;
* a current canonical Treasury balance observation.

The finality source SHALL verify transaction inclusion, transaction hash,
operation identity, commit validity and the active chain trust anchor. A
`WALLET_TRANSFER`, local admission result or RPC label is not a funding proof.

The pre-funding manifest cannot contain the hash-derived envelope operation ID:
the operation payload contains the manifest hash, while the manifest binds the
stable funding request ID. Implementations SHALL not use the stable
`funding_id` as a substitute for the finalized operation ID.

The operation itself remains subject to the Ledger rules in ECO-0008 and the
consensus transition in RFC-0036. This ECO adds the consumer-side verification
that the external Faucet must perform before spending.

## 7. Genesis Funding Proof

For `funding_mode: GENESIS`, the proof SHALL obtain the Treasury manifest from
the canonical ABCI query path:

```text
faucet/treasury-manifest
```

The returned manifest hash, chain ID and Wallet ID SHALL match the local
manifest. Configured RPC sources SHALL agree on one manifest hash and the
current Treasury balance.

The query path is served by the AiDN ABCI application from the bound durable
Genesis manifest. It is not a local file read and cannot be satisfied by a
Faucet-created JSON object.

Future protocol profiles MAY add a Merkle proof for the query value and an
explicit height-zero Genesis commitment. Until such a profile is active, a
deployment SHOULD use multi-RPC agreement and an operator-approved finality
configuration for the canonical state query.

## 8. Quorum Semantics

Quorum evidence means that the configured verification sources returned one
identical canonical result. It does not by itself prove that the RPC URLs are
operated by independent organizations.

Organizational independence remains governed by public validator profiles,
operator attestations and network governance. A Faucet SHALL not describe
same-operator RPC replicas as independent operators merely because their URLs
are different.

## 9. Balance Observation

The balance observation SHALL:

* use the Treasury Wallet from the manifest;
* use the same chain and approved RPC set as activation verification;
* reject negative, malformed or disagreeing values;
* remain an observation of current spendable balance, not proof of initial
  issuance;
* never be replaced by a locally configured starting balance.

The exact initial allocation is proven by Genesis binding or `TREASURY_FUND`;
the current balance determines whether the Faucet can safely submit a payout.

## 10. Faucet Startup and Claims

The external Faucet MAY start in `UNVERIFIED` state so that operators can see
the diagnostic reason and repair the network configuration. It SHALL refuse
new claims until activation becomes `ACTIVE`.

Startup or status refresh SHALL report stable reasons such as:

* `FAUCET_TREASURY_ACTIVATION_VERIFIER_UNAVAILABLE`;
* `FAUCET_TREASURY_FUNDING_NOT_FINALIZED`;
* `FAUCET_TREASURY_FUNDING_EVIDENCE_MISMATCH`;
* `FAUCET_TREASURY_GENESIS_MANIFEST_MISMATCH`;
* `FAUCET_TREASURY_BALANCE_UNAVAILABLE`.

Existing pending claims MAY be reconciled by operation ID. Reconciliation
must not create a replacement operation merely because activation status is
temporarily unavailable.

## 11. Treasury Replacement

An operator cannot activate a second Treasury by changing the local manifest.
Replacement requires a separate authorized protocol migration that defines:

* old Treasury final state;
* new Treasury manifest;
* transfer or issuance operation;
* creator or Governance authorization;
* effective network revision or epoch;
* Faucet policy boundary;
* recovery and audit evidence.

The activation proof for the old Treasury remains historical evidence and must
not be rewritten.

## 12. Private Material

The activation proof SHALL never include:

* the Treasury private key;
* creator private key;
* Faucet agent token;
* Faucet creator token;
* Wallet seed material;
* the signed payout envelope.

Public proof data may be exposed through status APIs, MCP resources and audit
records because it contains commitments and consensus evidence, not secrets.

## 13. Recovery and Caching

Activation status MAY be cached for a short bounded interval to avoid polling
the consensus network on every dashboard request. A cache must be invalidated
after:

* manifest replacement attempt;
* chain or finality configuration change;
* RPC quorum disagreement;
* balance observation failure;
* service restart.

A stale `ACTIVE` cache must not be used beyond its configured expiration.

## 14. Required Operations and Interfaces

The MVP implementation SHALL provide:

* `FaucetTreasuryActivationProof`;
* canonical activation status in the Faucet status response;
* proof hash verification;
* consensus `TREASURY_FUND` operation-type verification;
* Genesis canonical manifest query;
* quorum metadata in the proof;
* fail-closed claim enforcement;
* stable diagnostic error codes;
* activation evidence in MCP status and public audit output.

The proof is an observation/verification object. It is not a new Ledger
operation and cannot be submitted to mint or move Q.

## 15. Error Codes

Implementations SHALL support at least:

* `FAUCET_TREASURY_NOT_ACTIVE`;
* `FAUCET_TREASURY_ACTIVATION_VERIFIER_UNAVAILABLE`;
* `FAUCET_TREASURY_ACTIVATION_VERIFIER_FAILED`;
* `FAUCET_TREASURY_ACTIVATION_PROOF_INVALID`;
* `FAUCET_TREASURY_ACTIVATION_PROOF_MISMATCH`;
* `FAUCET_TREASURY_CHAIN_MISMATCH`;
* `FAUCET_TREASURY_WALLET_MISMATCH`;
* `FAUCET_TREASURY_FUNDING_NOT_FINALIZED`;
* `FAUCET_TREASURY_FUNDING_EVIDENCE_MISMATCH`;
* `FAUCET_TREASURY_GENESIS_QUERY_UNAVAILABLE`;
* `FAUCET_TREASURY_GENESIS_QUERY_FAILED`;
* `FAUCET_TREASURY_GENESIS_MANIFEST_MISMATCH`;
* `FAUCET_TREASURY_BALANCE_UNAVAILABLE`.

## 16. Invariants

* A valid-looking manifest does not activate a Treasury.
* A local balance does not prove canonical funding.
* A finalized operation for another manifest cannot activate this Treasury.
* `TREASURY_FUND` is the only accepted consensus funding operation in the MVP.
* The initial Treasury allocation is exactly `10,000,000 Q`.
* The Faucet cannot issue a new claim in `UNVERIFIED`, `DEGRADED` or
  `DISABLED` state when enforcement is enabled.
* Activation evidence is bound to network, chain, Wallet and manifest hash.
* Quorum labels do not prove independent organizational control.
* Activation proof creation does not mint Q or transfer Q.
* Treasury replacement is a separate authorized protocol transition.
* Pending payout reconciliation cannot silently create a duplicate transfer.

## 17. Security Rationale

The network recognizes a Treasury through canonical state and consensus
transitions, not through the confidence of the process that happens to run the
Faucet. This separation means that an attacker can create as many local
manifests and private Wallets as desired without acquiring the canonical
10,000,000 Q allocation or the ability to spend it through the public Faucet.
