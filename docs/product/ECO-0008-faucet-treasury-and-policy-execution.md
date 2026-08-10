# ECO-0008 AiDN Faucet Treasury and Policy Execution

Status: Draft

Version: 0.1

Depends on:

- RFC-0016 AiDN Wallet and Identity
- RFC-0036 AiDN Ledger State Machine
- RFC-0047 AiDN CometBFT Consensus Integration
- RFC-0059 AiDN Ledger Operation Catalog
- RFC-0066 Protocol Upgrade and Emergency Recovery
- RFC-0067 Protocol Governance and Authorization Policy
- ECO-0005 Q Emission, Recycling and Epoch Reward Allocation
- ECO-0009 AiDN Treasury Activation and Canonical Funding Proof

## 1. Purpose

This document defines the boundary between an external AiDN Faucet service and
the canonical AiDN network. The Faucet accelerates wallet adoption by spending
Q from a dedicated Treasury wallet. It is not an emission authority and is not
part of the Hypervisor, MCP node-control plane, or normal Epoch reward logic.

The external service owns policy decisions. Consensus owns only the validity of
the resulting signed transfer and the conservation of Q.

Before issuing a new claim, the external service SHALL also pass the Treasury
activation checks defined by ECO-0009. A locally valid manifest or locally
observed balance is not sufficient.

## 2. Core Principle

```text
Faucet request
    -> external policy evaluation
    -> signed disbursement decision
    -> signed WALLET_TRANSFER from Faucet Treasury
    -> CometBFT finality
    -> external receipt and audit record
```

The Faucet SHALL NOT call a Ledger credit method, create a protocol-origin
mint, or submit an agent-specific economic operation.

`AGENT_FAUCET_CLAIM` is not an active operation under this model. The older
Epoch `FAUCET_CLAIM` is also not a substitute for the external Treasury. Any
legacy implementation must be explicitly disabled in the active network
profile before public deployment.

The external Faucet is not an Epoch reward pool. It receives no automatic
share of protocol emission, no Faucet carryover and no development reward
allocation. Its only funding is the separately identified Treasury balance;
all payouts leave that Wallet through ordinary finalized `WALLET_TRANSFER`
operations. Legacy epoch-budget fields may remain readable during migration,
but they are not claimable or spendable Faucet funds.

## 3. Faucet Treasury

The Faucet Treasury is an ordinary Wallet with a public identity and a special
off-chain administrative label. The label does not grant protocol privileges.

```yaml
faucet_treasury:
  treasury_id:
  network_id:
  chain_id:
  wallet_id:
  wallet_public_key:
  creator_recovery_wallet:
  genesis_allocation_q_atoms:
  funding_operation_id:
  policy_registry_hash:
  state:
  object_version:
```

The private key SHALL NOT appear in:

- CometBFT Genesis;
- application Genesis state;
- Hypervisor state;
- MCP responses;
- agent credentials;
- public evidence bundles.

The creator retains recovery control over the Treasury. The online Faucet
service SHOULD use a separate signer, remote signer or threshold signer rather
than the creator's primary Wallet key.

## 4. Initial Funding

The preferred pre-launch allocation is:

```text
10,000,000 Q = 10,000,000,000,000 q_atoms
```

The allocation is included in the canonical application Genesis and committed
by the Genesis hash. It is an initial balance, not a reward and not a claim.

For an already running network, `genesis.json` SHALL NOT be edited. Funding
requires a one-time governance-authorized consensus operation such as
`TREASURY_FUND` or `SUPPLY_ISSUANCE`. That operation SHALL include:

- a unique funding ID;
- Treasury Wallet and public key;
- exact amount in `q_atoms`;
- supply authorization reference;
- network and chain binding;
- creator/governance authorization;
- replay protection;
- a hard one-time constraint for the Treasury.

Manual database crediting and direct calls to `credit_wallet_q_atoms` are
invalid production funding paths.

The current AiDN implementation uses `TREASURY_FUND`. It is a
protocol-origin, protocol-sponsored operation with no sender Wallet. The
active ABCI application MUST have the matching public Treasury manifest bound
before accepting it. The operation payload is bound to:

```yaml
treasury_funding:
  funding_id:
  treasury_id:
  network_id:
  chain_id:
  treasury_wallet_id:
  treasury_public_key:
  creator_recovery_wallet:
  creator_recovery_public_key:
  amount: 10000000000000
  treasury_manifest_hash:
  funding_mode: CONSENSUS
  authorization_reference:
  authorization_signature:
```

The creator signature covers the canonical funding payload under the
`aidn.faucet-treasury-funding.v1` domain. The same creator key also signs the
operation envelope. The recovery public key MUST derive the declared recovery
Wallet, and all Treasury/network/chain/hash fields MUST match the configured
manifest. A Treasury ID, Wallet ID or funding ID that already appears in a
finalized `TREASURY_FUND` record cannot be funded again. The exact envelope can
be generated for review with
`tools/create-faucet-treasury-funding.py`; submission and finality remain
consensus-service responsibilities.

## 5. Canonical Payment Boundary

Every Faucet payment SHALL be a normal signed `WALLET_TRANSFER`:

- `origin_type: wallet`;
- `sender_wallet: Faucet Treasury Wallet`;
- `fee_payer: Faucet Treasury Wallet`;
- `recipient_wallet: requesting Wallet`;
- positive integer `amount`;
- valid Wallet sequence and signature;
- sufficient Treasury balance for amount and fee.

The consensus layer SHALL not evaluate the external policy. It SHALL verify
the same balance, sequence, signature, replay and network rules as any other
Wallet transfer.

The Faucet decision is committed through `memo_hash` and an external evidence
reference. This allows audit without making policy code consensus-critical.

## 6. Policy Interface

Policy implementations are external, versioned and replaceable.

```yaml
faucet_policy:
  policy_id:
  policy_version:
  treasury_id:
  effective_from:
  effective_until:
  decision_schema:
  recipient_rules:
  amount_rules:
  period_rules:
  treasury_limits:
  policy_hash:
  creator_authorization:
```

A policy change applies only from its declared future boundary. It SHALL not
rewrite or recalculate finalized decisions from an earlier policy version.

The first policy may grant `50 Q` once per UTC calendar day to any Wallet that
proves control of the Wallet key. The recipient is the Wallet, not the agent
identity or Hypervisor node.

## 7. Request Ownership Proof

A request SHALL contain a fresh challenge signed by the recipient Wallet. An
agent bearer token alone is not sufficient to redirect funds to an arbitrary
Wallet.

The Faucet service SHALL enforce an idempotency key derived from:

```text
TreasuryID + PolicyID + PolicyVersion + RecipientWallet + Period
```

The service SHALL use a durable unique constraint or equivalent distributed
lock before submitting a transfer. Multiple Faucet instances must not issue
two payments for one policy period.

## 8. Treasury Limits

The external policy MAY impose daily, per-period, per-request and global
limits. Regardless of policy, a payment SHALL fail closed when:

- Treasury balance is insufficient;
- the Treasury is paused;
- the policy is expired or unauthorized;
- the request challenge is invalid;
- the request is a duplicate;
- the network or chain identity does not match;
- finality cannot be confirmed.

The Faucet SHALL stop before the Treasury can become negative. A low-balance
watermark SHOULD pause new claims and notify the creator.

## 9. Accumulating Policies

A future policy may accumulate a virtual entitlement, for example `5 Q` per
minute, and transfer the accumulated amount on request. This entitlement is
still bounded by the actual Treasury balance and does not mint Q.

If the desired behavior requires new Q to be created over time, it is an
emission policy and requires a separate governance-authorized consensus path.
The Faucet service cannot create that authority by changing its configuration.

## 10. Creator Administration

The creator-facing control surface SHALL support:

- Treasury balance and transfer history;
- policy publication and future activation;
- pause and resume;
- signer rotation;
- Treasury recovery or sweep;
- RPC endpoint rotation;
- audit export;
- low-balance and rejected-transfer alerts.

Private keys SHALL never be displayed after import. Administrative actions
require creator Wallet authorization or an equivalent protected signer. Agents
may request a payout but cannot change policy, signer, Treasury address or
recovery destination.

## 11. Evidence

Each decision SHOULD be retained as an append-only external record:

```yaml
faucet_disbursement_decision:
  decision_id:
  treasury_id:
  policy_id:
  policy_version:
  request_id:
  recipient_wallet:
  amount_q_atoms:
  period_key:
  wallet_challenge_hash:
  decision_hash:
  transfer_operation_id:
  finality_reference:
  state:
```

The public chain remains the payment authority. The external decision record
explains why the payment was made but cannot override a rejected transfer.

## 12. Contribution Rewards Are Separate

Development rewards follow RFC-0068 and ECO-0007. They are paid from the
bounded Development Reward Pool after contribution attestation, challenge
closure and epoch authorization. They SHALL not spend Faucet Treasury funds
unless a separate, explicit development grant is created and authorized.

The merged `.aidn/contributor-wallet.json` is immutable evidence. Payment does
not overwrite it. Wallet rotation uses a new signed claim and a new reward
lineage.

## 13. Security Invariants

- Faucet policy code cannot mint Q.
- Faucet policy code cannot mutate Hypervisor or Ledger state directly.
- Only the Treasury signer can authorize a payment.
- Every payment is a canonical `WALLET_TRANSFER`.
- Creator recovery is separate from the online Faucet process.
- Policy changes are versioned and non-retroactive.
- Duplicate requests cannot create duplicate transfers.
- Treasury balance and total supply remain conserved.
- Agents never receive Treasury private key material.
- A node operator cannot silently replace the Treasury or policy.

## 14. Acceptance Requirements

The first implementation is accepted only after it demonstrates:

- Genesis Treasury allocation of exactly `10,000,000 Q`;
- ordinary transfer finality on at least two validators;
- one valid daily claim;
- duplicate and replay rejection;
- invalid Wallet-signature rejection;
- Treasury exhaustion and low-watermark handling;
- policy version change without retroactive recalculation;
- service restart without duplicate payment;
- RPC failover and finality recovery;
- creator pause, signer rotation and recovery;
- no active `AGENT_FAUCET_CLAIM` transition in the implementation profile.

The repository's first executable service slice is under
`services/aidn-faucet` and is documented in
`docs/development/external-faucet-service.md`. It provides policy, Wallet
proof, durable idempotency and envelope signing. It does not claim production
finality until a deployment supplies the verified submitter required above.
