# RFC-0059 Ledger Operation Catalog

Status: `Draft`

Version: `0.4`

Revision note: the catalog includes RFC-0037 Funding Account, proposal,
bounded-dispute, partial-finalization, forced and correction operations.

Supersedes:

- `RFC-0059 Version 0.3`

Depends on:

- `ECO-0000 Economic Principles`
- `ECO-0003 Validation Economics`
- `ECO-0005 Q Emission, Recycling and Epoch Reward Allocation`
- `RFC-0016 Wallet and Identity`
- `RFC-0035 Validation Escrow System`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0037 Settlement Engine`
- `RFC-0039 Hypervisor Service Model`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0042 Hypervisor Network Protocol`
- `RFC-0044 Session Protocol`
- `RFC-0046 Registry Architecture`
- `RFC-0047 CometBFT Consensus Integration`
- `RFC-0048 Epoch Engine`
- `RFC-0049 Distributed Marketplace & Advertisement Registry`
- `RFC-0051 Usage Reporting and Verification Protocol`
- `RFC-0057 Validation Report Specification`
- `RFC-0058 Participant Eligibility and Sybil Resistance`

## 1. Purpose

This document defines the canonical Ledger Operations supported by the AiDN protocol.

For every operation, the catalog specifies:

- operation identity;
- origin and authorization;
- required fields;
- validation rules;
- applicable Network Fee;
- state preconditions;
- deterministic state transition;
- emitted events;
- failure behavior;
- idempotency rules.

All compliant AiDN Ledger implementations SHALL interpret these operations identically.

## 2. Scope

This document specifies operations that modify canonical protocol state.

It does not specify ordinary off-chain protocol messages such as:

- Session payload streaming;
- prompts and model responses;
- Endpoint discovery requests;
- Runtime health messages;
- Validator test traffic;
- Registry read queries;
- peer discovery;
- local Hypervisor configuration.

An off-chain message becomes relevant to the Ledger only when it produces a signed, economically significant or trust-significant state transition.

## 3. Core Principle

A Ledger Operation is the only mechanism permitted to modify canonical AiDN state.

No protocol component may directly modify:

- Wallet balances;
- locked balances;
- Stakes;
- Bonds;
- Hypervisor ownership;
- Service eligibility;
- Endpoint advertisement, offer, and lifecycle state;
- Session economic state;
- Certification state;
- Reputation Profiles;
- reward state;
- protocol parameters.

Every modification SHALL be caused by a finalized Ledger Operation defined by this catalog or a future versioned extension.

## 4. Operation Origin Types

Every Ledger Operation has one of the following origin types:

- `WALLET`
- `MULTI_PARTY`
- `PROTOCOL`
- `EVIDENCE_TRIGGERED`

### 4.1 WALLET

Submitted and signed by one Wallet.

Examples:

- Wallet Transfer;
- Hypervisor Registration;
- Endpoint Registration;
- Faucet Claim.

### 4.2 MULTI_PARTY

Contains authorization or signed evidence from more than one participant.

Examples:

- ordinary Session Settlement;
- ownership transfer in a future protocol version.

### 4.3 PROTOCOL

Generated deterministically by the AiDN State Machine or Epoch Engine.

Examples:

- Reward Mint;
- Epoch Transition;
- Reputation Update;
- Consensus Validator Set Update.

A Protocol Operation is not authorized by an ordinary Wallet signature.

Its validity derives from deterministic protocol state.

### 4.4 EVIDENCE_TRIGGERED

Submitted with cryptographic or reproducible evidence that authorizes a protocol consequence.

Examples:

- confirmed penalty;
- Validation Bond forfeiture;
- participant suspension;
- forced Session Settlement.

## 5. Common Operation Envelope

Every operation SHALL use the canonical envelope:

```yaml
ledger_operation:
  operation_id:
  operation_type:
  operation_version:
  protocol_version:
  origin_type:
  initiator_id:
  sender_wallet:
  sender_sequence:
  fee_payer:
  created_at:
  expires_at:
  target_epoch:
  payload:
  evidence_references:
  signatures:
```

Fields that do not apply SHALL be omitted according to the canonical schema.

They SHALL NOT be populated with arbitrary empty values.

## 6. Canonical Serialization

Every Ledger Operation SHALL use deterministic canonical serialization.

Canonical serialization SHALL define:

- field order;
- integer representation;
- fixed-point representation;
- string normalization;
- binary encoding;
- list ordering;
- omitted-field behavior;
- signature encoding.

Canonical Ledger Operations SHALL NOT depend on:

- JSON object iteration order;
- floating-point representation;
- locale;
- operating system;
- database engine;
- local timezone.

The reference implementation SHOULD use a deterministic binary schema.

Human-readable JSON or YAML MAY be produced for diagnostics but SHALL NOT be authoritative.

## 7. Operation Identity

`operation_id` SHALL be derived from the cryptographic hash of the canonical unsigned operation content plus all required authorization fields.

Conceptually:

```text
operation_id =
HASH(
  canonical_operation_body
  +
  authorization_context
)
```

Changing any signed field SHALL produce a different Operation ID.

Two finalized operations SHALL NOT share the same Operation ID.

### 7.1 Finalized Operation Replay Registry

The reference Ledger SHALL maintain a deterministic finalized-operation replay
registry derived from the canonical operation log. Each entry binds:

- `operation_id`;
- `operation_type`;
- `sequence_id`;
- the SHA-256 digest of the complete immutable operation record.

The registry SHALL reject:

- a duplicate operation ID;
- the same operation ID with a different record digest;
- two finalized records with the same sequence ID;
- evidence references to an operation absent from the registry.

The operation log remains the committed source of truth. The registry is a
rebuildable index and SHALL be reconstructed during restart or Snapshot/State
Sync restore. Rebuilding it from the restored operation log SHALL produce the
same entries and SHALL fail closed on any identity, digest or sequence conflict.

An identical operation redelivery is idempotent at the consensus admission
boundary; it SHALL not execute a second state transition or create a second
economic effect. A conflicting payload cannot reuse the original operation ID,
because the operation ID is bound to the canonical unsigned envelope.

## 8. Wallet Sequence

Every Wallet-authorized operation SHALL include a monotonically increasing `sender_sequence`.

The expected sequence is stored in Ledger state.

An operation is valid only when:

```text
operation.sender_sequence = wallet.next_sequence
```

After successful final execution, the Wallet sequence advances by one.

The sequence prevents:

- replay attacks;
- duplicate transfers;
- ambiguous operation ordering;
- repeated Faucet Claims using the same signed operation.

## 9. Sequence Consumption on Failure

An operation rejected before block inclusion does not consume a Wallet sequence.

An operation included in a finalized block consumes its sequence when:

- it applies successfully; or
- it reaches deterministic execution and is rejected after admission.

This prevents repeated submission of an included failing operation.

The exact result remains visible in the block result.

## 10. Operation Time

Consensus-provided block time is authoritative.

Local clocks SHALL NOT determine Ledger validity.

Time-dependent operations MAY use:

- `created_at`;
- `expires_at`;
- `target_epoch`;
- finalized block time;
- block height.

An operation submitted after `expires_at` SHALL be rejected.

## 11. Fee Classes

The MVP defines the following fee classes:

- `STANDARD`
- `SESSION`
- `PROTOCOL_SPONSORED`
- `ONBOARDING_EXEMPT`
- `FAUCET_EXEMPT`

### 11.1 STANDARD

Uses the current standard Network Fee.

Recommended initial value:

`0.01Q`

### 11.2 SESSION

The fee is charged from the Session Deposit or explicitly declared Session fee payer.

### 11.3 PROTOCOL_SPONSORED

No participant fee is charged.

The operation is produced as part of authorized protocol work.

### 11.4 ONBOARDING_EXEMPT

A narrowly defined one-time fee exemption for initial network onboarding.

### 11.5 FAUCET_EXEMPT

Faucet Claims do not require an existing `Q` balance.

Otherwise, receiving free `Q` would first require already owning `Q`, which would be an impressively circular onboarding experience.

## 12. Network Fee Handling

Network Fees SHALL be removed from circulation.

They SHALL:

- be deducted from the fee payer;
- be recorded as recyclable protocol removals;
- become eligible for redistribution according to `ECO-0005`;
- not be paid directly to a specific Registry or Consensus Service.

A fee charged during a finalized execution failure remains removed.

A request rejected before block inclusion incurs no Ledger fee.

## 13. Validation Stages

Every operation passes through two validation stages.

### 13.1 Admission Validation

Performed before mempool acceptance.

It checks:

- schema;
- operation version;
- protocol version;
- operation size;
- signature format;
- basic sequence validity;
- expiration;
- minimum fee;
- obvious authorization errors.

Admission validation SHALL remain inexpensive.

### 13.2 Final Execution Validation

Performed against canonical state during block finalization.

It checks:

- current ownership;
- current balance;
- current object status;
- exact expected sequence;
- referenced object versions;
- current Epoch;
- required evidence;
- all operation-specific preconditions.

Passing Admission Validation does not guarantee successful execution.

## 14. Execution Results

Every finalized operation produces a deterministic result:

```yaml
operation_result:
  operation_id:
  status:
  error_code:
  error_details_hash:
  fee_charged:
  state_changes_root:
  emitted_events:
```

Supported statuses:

- `APPLIED`
- `REJECTED`
- `NO_OP`

`APPLIED`

The business transition completed.

`REJECTED`

The operation reached final execution but failed a deterministic precondition.

`NO_OP`

The operation was valid but produced no additional state change.

`NO_OP` SHALL be used only when explicitly permitted by the operation specification.

## 15. Atomicity

The business transition of every operation SHALL be atomic.

It either applies completely or does not apply.

The Network Fee MAY remain charged when final execution rejects the business transition.

Compound actions requiring all-or-nothing behavior SHALL be represented as one operation or one deterministic protocol batch.

## 16. State Object Versioning

Mutable Ledger objects SHALL have a monotonically increasing version.

Examples include:

- Hypervisor record;
- Service record;
- Endpoint record;
- Advertisement active pointer;
- Session state;
- Certification state;
- Reputation Profile;
- protocol parameter set.

Operations modifying a mutable object SHOULD include its expected current version.

An operation referencing a stale version SHALL be rejected with:

`STALE_OBJECT_VERSION`

## 17. Content Hashes

Execution-relevant objects SHALL use immutable hashes.

Examples:

- `endpoint_configuration_hash`;
- `accounting_contract_hash`;
- `pricing_policy_hash`;
- `session_policy_hash`;
- `validation_report_hash`;
- `usage_report_hash`;
- `snapshot_hash`.

Certification SHALL remain bound to the applicable execution configuration hash.

Commercial pricing changes SHALL not automatically invalidate technical Certification unless they also alter execution behavior.

## 18. Operation Categories

The MVP catalog contains the following categories:

1. Hypervisor Identity Operations
2. Service Operations
3. Endpoint Operations
4. Marketplace Advertisement, Offer, and Endpoint Lifecycle Operations
5. Wallet and Economic Operations
6. Session Operations
7. Validation Operations
8. Verification and Reputation Operations
9. Epoch and Reward Operations
10. Consensus and Snapshot Operations
11. Enforcement Operations

## 19. Catalog Summary

| Operation | Origin | Fee Class |
| --- | --- | --- |
| `HYPERVISOR_REGISTER` | Wallet | Onboarding Exempt or Standard |
| `HYPERVISOR_UPDATE` | Wallet | Standard |
| `HYPERVISOR_KEY_ROTATE` | Wallet | Standard |
| `HYPERVISOR_RETIRE` | Wallet | Standard |
| `SERVICE_REGISTER` | Wallet | Standard |
| `SERVICE_UPDATE` | Wallet | Standard |
| `SERVICE_RETIRE` | Wallet | Standard |
| `ENDPOINT_REGISTER` | Wallet | Standard or Onboarding Exempt |
| `ENDPOINT_UPDATE` | Wallet | Standard |
| `ENDPOINT_ADVERTISEMENT_PUBLISH` | Wallet | Standard |
| `ENDPOINT_ADVERTISEMENT_WITHDRAW` | Wallet | Standard |
| `ENDPOINT_OFFER_PUBLISH` | Wallet | Standard |
| `ENDPOINT_OFFER_WITHDRAW` | Wallet | Standard |
| `ENDPOINT_SUSPEND` | Evidence-triggered | Protocol Sponsored |
| `ENDPOINT_REINSTATE` | Protocol | Protocol Sponsored |
| `ENDPOINT_RETIRE` | Wallet or Protocol | Standard or Protocol Sponsored |
| `WALLET_TRANSFER` | Wallet | Standard |
| `TREASURY_FUND` | Protocol | Protocol Sponsored |
| `STAKE_LOCK` | Wallet | Standard |
| `UNSTAKE_REQUEST` | Wallet | Standard |
| `STAKE_RELEASE` | Protocol | Protocol Sponsored |
| `SESSION_OPEN` | Wallet | Session |
| `SESSION_ACCEPT` | Wallet | Session |
| `SESSION_REJECT` | Wallet | Session |
| `SESSION_CANCEL` | Wallet | Session |
| `SESSION_DEPOSIT_EXTEND` | Wallet | Session |
| `SESSION_SETTLE` | Multi-party | Session |
| `SESSION_EXPIRE` | Protocol | Protocol Sponsored |
| `SESSION_FAILURE_EVIDENCE` | Evidence-triggered | Session |
| `SESSION_FORCE_SETTLE` | Evidence-triggered | Session |
| `VALIDATION_REQUEST` | Wallet | Standard |
| `VALIDATION_ASSIGNMENT_CREATE` | Protocol | Protocol Sponsored |
| `VALIDATION_REPORT_COMMIT` | Wallet + Assignment Evidence | Protocol Sponsored |
| `VALIDATION_REPORT_STORAGE_RECEIPT` | Endpoint Hypervisor | Protocol Sponsored |
| `VALIDATION_REPORT_STORAGE_FAILURE` | Validator + Transfer Evidence | Protocol Sponsored |
| `VALIDATION_REPORT_AVAILABILITY_COMMIT` | Protocol-assigned Actor | Protocol Sponsored |
| `VALIDATION_REPORT_CUSTODY_RELEASE` | Protocol | Protocol Sponsored |
| `CERTIFICATION_STATE_UPDATE` | Protocol | Protocol Sponsored |
| `VALIDATION_BOND_REFUND` | Protocol | Protocol Sponsored |
| `VALIDATION_BOND_FORFEIT` | Evidence-triggered | Protocol Sponsored |
| `SERVICE_VERIFICATION_COMMIT` | Wallet + Assignment Evidence | Protocol Sponsored |
| `REPUTATION_PROFILE_UPDATE` | Protocol | Protocol Sponsored |
| `EPOCH_TRANSITION` | Protocol | Protocol Sponsored |
| `REWARD_MINT` | Protocol | Protocol Sponsored |
| `CONSENSUS_VALIDATOR_SET_UPDATE` | Protocol | Protocol Sponsored |
| `SNAPSHOT_COMMIT` | Protocol | Protocol Sponsored |
| `PARTICIPANT_SUSPEND` | Evidence-triggered | Protocol Sponsored |
| `PARTICIPANT_REINSTATE` | Protocol | Protocol Sponsored |
| `PENALTY_APPLY` | Evidence-triggered | Protocol Sponsored |

## 20. Hypervisor Registration

`HYPERVISOR_REGISTER`

Registers a new Hypervisor Identity.

Authorization

Signed by the owner Wallet and the new Hypervisor Node Identity.

Required Payload

```yaml
hypervisor_id:
node_public_key:
owner_wallet:
reward_beneficiary_wallet:
protocol_version:
network_endpoints:
metadata_hash:
```

Preconditions

- Hypervisor ID does not exist;
- Node public key is not already assigned;
- owner Wallet signature is valid;
- Node Identity signature is valid;
- protocol version is supported.

State Changes

- creates Hypervisor record;
- binds owner Wallet;
- binds Reward Beneficiary;
- records registration Epoch;
- sets state to `REGISTERED`;
- initializes Hypervisor object version;
- initializes Faucet and eligibility history.

Fee

The first Hypervisor registered by a Wallet MAY use `ONBOARDING_EXEMPT`.

Additional registrations use `STANDARD`.

## 21. Hypervisor Update

`HYPERVISOR_UPDATE`

Updates non-key Hypervisor metadata.

Permitted Fields

- network addresses;
- metadata reference;
- supported protocol transports;
- Reward Beneficiary;
- operator-declared information.

Preconditions

- Hypervisor exists;
- sender Wallet owns the Hypervisor;
- expected object version matches;
- Hypervisor is not retired.

State Changes

- increments object version;
- updates permitted fields;
- Reward Beneficiary changes take effect at the next Epoch boundary.

Restrictions

This operation SHALL NOT change:

- Node Identity key;
- owner Wallet;
- historical Maturity;
- historical Reputation.

## 22. Hypervisor Key Rotation

`HYPERVISOR_KEY_ROTATE`

Replaces the active Node Identity key.

Authorization

Requires:

- owner Wallet signature;
- old Node Identity signature;
- new Node Identity proof of possession.

If the old key is unavailable, a delayed recovery procedure MAY be used in a future protocol version.

Preconditions

- Hypervisor exists;
- current owner is valid;
- new key is unused;
- no unresolved key-rotation operation exists.

State Changes

- deactivates old key;
- activates new key;
- increments Hypervisor version;
- preserves ownership, Reputation and Maturity;
- records rotation history.

## 23. Hypervisor Retirement

`HYPERVISOR_RETIRE`

Retires a Hypervisor from future participation.

Preconditions

- sender owns the Hypervisor;
- no prohibited active obligations remain;
- Consensus and Service exit rules are satisfied;
- active Stakes begin or completed their unbonding process.

State Changes

- sets Hypervisor state to `RETIRED`;
- prevents new Services and Endpoints;
- prevents future Faucet Claims;
- preserves historical data;
- initiates applicable Service retirement procedures.

Retirement SHALL NOT erase prior protocol history.

## 24. Service Registration

`SERVICE_REGISTER`

Registers a Service instance on a Hypervisor.

Required Payload

```yaml
service_id:
hypervisor_id:
service_type:
service_public_key:
service_version:
configuration_hash:
reward_beneficiary_wallet:
```

Preconditions

- Hypervisor exists and is not retired;
- sender Wallet owns the Hypervisor;
- Service ID is unique;
- Service type is supported;
- service key proof is valid.

State Changes

- creates Service record;
- binds Service to Hypervisor;
- initializes state as `ACTIVATING`;
- initializes Maturity at zero;
- initializes Service Reputation Profile.

Registration does not grant reward eligibility.

## 25. Service Update

`SERVICE_UPDATE`

Updates a registered Service.

Permitted Changes

- Service version;
- network address;
- configuration hash;
- declared capabilities;
- protocol compatibility;
- Reward Beneficiary effective next Epoch.

State Effects

Execution-relevant changes MAY:

- reset current Health;
- require re-verification;
- pause eligibility;
- preserve or partially preserve Maturity according to service policy.

## 26. Service Retirement

`SERVICE_RETIRE`

Voluntarily retires a Service.

Preconditions

- owner authorization;
- no unresolved assignments;
- role-specific exit requirements satisfied;
- required unbonding has begun.

State Changes

- sets Service to `RETIRED`;
- removes future reward eligibility;
- preserves historical Reputation and proofs;
- begins applicable Stake release delay.

## 27. Endpoint Registration

`ENDPOINT_REGISTER`

Creates an Endpoint object.

Required Payload

```yaml
endpoint_id:
hypervisor_id:
service_id:
capability_id:
runtime_id:
endpoint_configuration_hash:
pricing_policy_hash:
accounting_contract_hash:
session_policy_hash:
visibility:
access_policy_hash:
proxy_policy_hash:
retry_policy_hash:
failover_policy_hash:
data_handling_policy_hash:
metadata_hash:
```

Preconditions

- Hypervisor exists;
- Compute Service exists and is active;
- sender owns the Hypervisor;
- Runtime and Capability references are valid;
- Endpoint ID is unique;
- referenced policies are retrievable or committed by hash.

State Changes

- creates Endpoint object;
- sets state to `ACTIVE`;
- initializes Endpoint Reputation Profile;
- records configuration and commercial policy versions.

Onboarding Exception

The first Endpoint registered by the first Hypervisor of a Wallet MAY use `ONBOARDING_EXEMPT`.

This provides a deterministic path to Faucet eligibility without requiring pre-existing `Q`.

## 28. Endpoint Update

`ENDPOINT_UPDATE`

Updates an existing Endpoint.

Required Fields

- Endpoint ID;
- expected Endpoint version;
- changed policy or configuration references;
- new hashes.
- Proxy policy hashes MAY include `proxy_policy_hash`, `retry_policy_hash`, `failover_policy_hash`, and `data_handling_policy_hash`.

State Changes

- increments Endpoint version;
- replaces changed active references;
- emits `Endpoint Updated` event.

Certification Effects

If the execution configuration hash changes:

- previous Certification no longer applies;
- state becomes `UNCERTIFIED` or `VALIDATION_PENDING`;
- Maintenance history remains visible.

Material Proxy-policy changes through `ENDPOINT_UPDATE` SHALL be treated as execution-relevant changes when they alter:

- retry behavior;
- failover behavior;
- data handling;
- upstream-selection behavior;
- transformation behavior.

If only pricing or commercial policy changes:

- Certification MAY remain valid;
- active Sessions retain their accepted pricing version.

## 29. Endpoint Advertisement Publication

`ENDPOINT_ADVERTISEMENT_PUBLISH`

Publishes a discoverable Advertisement for an Endpoint.

Advertisement publication creates the immutable Advertisement object or canonical reference to that object; Offer publication separately creates or activates the commercial Offer scope that references one published Advertisement.

Required Payload

```yaml
advertisement_id:
endpoint_id:
owner_wallet:
visibility:
advertisement_version:
previous_advertisement_id:
configuration_hash:
content_hash:
valid_from:
expiration:
```

Preconditions

- referenced Endpoint exists and is not retired;
- sender owns or is authorized to advertise the Endpoint;
- content signature is valid;
- Configuration Hash matches the current Endpoint configuration;
- referenced policy and Capability definitions are retrievable;
- Advertisement ID is unique.

State Changes

- creates the immutable Advertisement object or canonical reference to that object;
- records the published Advertisement for later Offer binding;
- makes public or restricted discovery of the Advertisement object possible where policy allows.

Advertisements are immutable.

Updates are new publication operations referencing the previous version.

## 30. Endpoint Advertisement Withdrawal

`ENDPOINT_ADVERTISEMENT_WITHDRAW`

Marks a published Advertisement inactive.

Required Fields

- Advertisement ID;
- Endpoint ID;
- effective boundary;
- reason.

State Changes

- clears any active Offer bindings to the withdrawn Advertisement at the effective boundary;
- preserves immutable Advertisement history;
- does not withdraw the underlying Endpoint automatically;
- accepted Sessions remain bound to their accepted Advertisement version.

## 31. Endpoint Offer Publication and Lifecycle Operations

`ENDPOINT_OFFER_PUBLISH`

Publishes a distinct Offer ID and access scope for an Endpoint Advertisement.

Required Payload

```yaml
offer_id:
endpoint_id:
advertisement_id:
access_scope:
pricing_policy_hash:
accounting_contract_hash:
session_policy_hash:
failure_policy_hash:
data_handling_policy_hash:
visibility:
```

Preconditions

- referenced Endpoint exists and is not suspended or retired;
- referenced Advertisement exists for the same Endpoint;
- Offer ID is unique within the Endpoint scope;
- sender is authorized to publish the offer.

State Changes

- creates or activates the canonical commercial Offer scope for the targeted `offer_id`;
- binds future Sessions to the published `offer_id` and `advertisement_id`;
- preserves prior offer history.

### Endpoint Offer Withdrawal

`ENDPOINT_OFFER_WITHDRAW`

Makes one Offer ID inactive for new Sessions without withdrawing unrelated offers on the same Endpoint.

State Changes

- deactivates the targeted Offer ID for new Sessions;
- preserves historical offer references for audits and Session disputes;
- leaves the underlying Endpoint and other offers unchanged unless separately withdrawn.

### Endpoint Suspension

`ENDPOINT_SUSPEND`

Temporarily disables an Endpoint for new Sessions and Marketplace discovery.

Preconditions

- objective finalized evidence or authorized enforcement action exists;
- the suspension scope and minimum recovery condition are defined.

State Changes

- sets Endpoint state to `SUSPENDED`;
- makes active Advertisements and Offers unavailable for new Sessions;
- preserves historical records and accepted Session references.

### Endpoint Reinstatement

`ENDPOINT_REINSTATE`

Restores a suspended Endpoint after recovery conditions are satisfied.

Preconditions

- recovery conditions are satisfied;
- required delay elapsed;
- required verification or operator remediation completed.

State Changes

- removes the active suspension;
- allows Advertisements and Offers to become active again at the defined boundary;
- does not restore lost availability retroactively.

### Endpoint Retirement

`ENDPOINT_RETIRE`

Voluntarily or administratively retires an Endpoint.

Preconditions

- owner authorization or protocol authority exists;
- no unresolved Endpoint-specific exit constraints remain.

State Changes

- sets Endpoint state to `RETIRED`;
- makes all Advertisements and Offers inactive for new Sessions;
- preserves historical evidence and Session references;
- ends future Endpoint reward eligibility where applicable.

## 32. Wallet Transfer

`WALLET_TRANSFER`

Transfers existing `Q` between Wallets.

Required Payload

```yaml
recipient_wallet:
amount:
memo_hash:
```

The MVP consensus profile uses `STANDARD_NETWORK_FEE_Q_ATOMS = 10,000`
(`0.01Q`). The fee is derived from the `STANDARD` fee class and is not
caller-controlled; it is recorded in the recyclable removal accumulator.

Preconditions

- sender has sufficient available balance;
- amount is positive;
- recipient is valid;
- sender sequence is correct;
- sender can also pay the Network Fee.

State Changes

```text
sender.available_balance -= amount + fee
recipient.available_balance += amount
recycle_accumulator += fee
```

Transfer amount does not affect total supply.

The current ABCI and deterministic block-execution paths apply this transfer
atomically: they debit `amount + 10,000` from the sender, credit `amount` to
the recipient, recycle the fee, and persist the operation in the replay
registry. Snapshot restoration preserves both balances and the recyclable
accumulator. A duplicate operation cannot repeat the transfer.

## 33. Deprecated Faucet Claim (Inactive)

`FAUCET_CLAIM`

This historical operation is not part of the active implementation profile and
MUST be rejected by strict consensus. Faucet distribution is external to the
Hypervisor/Ledger and uses a dedicated Treasury Wallet plus ordinary
`WALLET_TRANSFER`. The current post-Genesis Treasury allocation uses the
separate `TREASURY_FUND` transition described by ECO-0008.

Claims the current Epoch Faucet Share.

Authorization

Requires:

- owner or authorized Wallet signature;
- eligible Hypervisor Node Identity signature.

Required Payload

```yaml
hypervisor_id:
claim_epoch:
destination_wallet:
eligibility_snapshot_hash:
```

Preconditions

- Hypervisor was Faucet-eligible at Epoch start;
- Hypervisor has not claimed in the current Epoch;
- destination Wallet matches authorized reward destination;
- Faucet Share was calculated;
- Faucet Pool authorization remains sufficient.

State Changes

- No active state change is permitted. The section is retained only as a
  historical schema reference for migration and rejection tests.

Fee

`FAUCET_EXEMPT`.

## 34. Stake Lock

`STAKE_LOCK`

Locks `Q` for a protocol role.

Supported Stake Types

- Consensus Stake;
- Validation Stake;
- Registry Bond;
- future Node Activation Bond.

Required Payload

```yaml
stake_id:
stake_type:
amount:
beneficiary_object_id:
lock_policy_version:
```

Preconditions

- Wallet owns sufficient available `Q`;
- target object exists;
- amount satisfies role rules;
- no conflicting Stake exists.

State Changes

- reduces available balance;
- increases locked Stake balance;
- creates Stake object;
- records activation or eligibility delay.

The current consensus execution path debits the sender Wallet, persists the
Stake object in canonical Ledger state and includes it in Snapshot and app
hash commitments.

## 35. Unstake Request

`UNSTAKE_REQUEST`

Requests release of locked Stake.

Preconditions

- sender controls the Stake;
- Stake is not already unbonding;
- no unresolved penalty or role obligation blocks release.

State Changes

- Stake enters `UNBONDING`;
- release height or Epoch is calculated;
- participant may lose relevant eligibility immediately or at the next Epoch.

The MVP uses the fixed `UnbondingPeriod = 14 Epochs` and records the exact
release Epoch in the Stake object. A request cannot be submitted by another
Wallet or for an already unbonding/released Stake.

## 36. Stake Release

`STAKE_RELEASE`

Protocol-generated release after unbonding completes.

Preconditions

- Stake is `UNBONDING`;
- release deadline reached;
- no finalized penalty applies.

State Changes

- decreases locked Stake;
- credits owner Wallet;
- marks Stake as `RELEASED`.

No new `Q` is minted.

The current consensus execution path credits only the recorded Stake owner
after the release Epoch and preserves the `RELEASED` state for replay and
Snapshot recovery.

## 37. Session Open

`SESSION_OPEN`

Creates the canonical non-economic Session lifecycle projection after the
initial Funding Account has already been locked. `SESSION_OPEN` SHALL NOT
debit a Consumer Wallet, move a reserve or act as an alias for
`SESSION_ESCROW_LOCK`.

The strict MVP order is:

```text
SESSION_ESCROW_LOCK (finalized)
        ->
SESSION_OPEN
```

The dependency SHALL be finalized before the block containing
`SESSION_OPEN`; a same-block lock/open shortcut is invalid.

Required Payload

```yaml
session_id:
consumer_hypervisor_id:
provider_hypervisor_id:
endpoint_id:
endpoint_version:
endpoint_configuration_hash:
pricing_policy_hash:
accounting_contract_hash:
session_policy_hash:
session_contract_hash:
effective_terms_hash:
endpoint_payment_beneficiary:
consumer_refund_beneficiary:
deposit_amount_q_atoms:
funding_lock_operation_id:
funding_state_reference:
open_expiration:
```

Preconditions

- Consumer owns or controls the initiating Hypervisor;
- `funding_lock_operation_id` references a finalized `SESSION_ESCROW_LOCK`;
- the lock and `funding_state_reference` are present in the evidence list;
- the lock belongs to the same Session and Session Contract;
- Endpoint and Consumer Refund beneficiaries match the locked Funding Account;
- `deposit_amount_q_atoms` matches the locked Funding Account;
- no duplicate Session ID exists.

State Changes

- records Session in the canonical `OPEN_PENDING` lifecycle projection;
- records accepted Endpoint, pricing, accounting and policy hashes;
- binds the Session to the finalized Funding Account and lock operation;
- advances the wallet operation sequence for the lifecycle authorization;
- performs no Q debit, credit, reserve movement or Network Fee recycling.

`SESSION_ESCROW_LOCK` owns the atomic prepaid debit and reserve creation.
Local compatibility services MAY still emit a legacy `SESSION_OPEN` domain
record while preparing a Session, but that record is not a validator
transition and cannot replace the strict canonical lock/open sequence.

Session execution SHALL NOT begin before acceptance.

## 38. Session Accept

`SESSION_ACCEPT`

The Endpoint accepts a pending Session after the canonical
`SESSION_OPEN` projection. `SESSION_ACCEPT` is lifecycle-only and SHALL NOT
debit a Wallet, release or expand escrow, or create a second funding effect.

Required Payload

```yaml
session_id:
session_open_operation_id:
session_contract_hash:
effective_terms_hash:
endpoint_id:
endpoint_configuration_hash:
provider_hypervisor_id:
accepted_by:
accepted_at:
```

Authorization

Signed by the Provider Hypervisor or authorized Endpoint execution identity.

Preconditions

- `session_open_operation_id` is finalized before the containing block;
- the operation is referenced in the evidence list;
- Session, Contract and Endpoint hashes match the finalized `SESSION_OPEN`;
- the sender is the locked Endpoint Payment beneficiary;
- Session funding remains `LOCKED`;
- acceptance has not expired;
- Endpoint remains active;
- Endpoint configuration still matches;
- requested concurrency is available;
- Provider is authorized.

State Changes

- Session becomes `ACTIVE`;
- activation time is recorded;
- Session slot becomes reserved.

The consensus Ledger records only the acceptance projection. Runtime
allocation and local slot reservation remain Hypervisor/Session-service
effects after canonical acceptance; no Q balance or Funding reserve changes.

## 39. Session Reject

`SESSION_REJECT`

Provider rejects a pending Session.

Preconditions

- Session is pending;
- Provider authorization is valid.

State Changes

- Session becomes `REJECTED`;
- Deposit is unlocked and returned;
- already removed Network Fee remains removed;
- rejection reason code is recorded.

## 40. Session Cancel

`SESSION_CANCEL`

Consumer cancels a pending Session before acceptance.

Preconditions

- Session is still pending;
- Consumer is authorized.

State Changes

- Session becomes `CANCELLED`;
- Deposit is unlocked;
- Network Fee remains removed.

An active Session cannot use ordinary cancellation.

## 41. Session Deposit Extension

`SESSION_DEPOSIT_EXTEND`

This legacy name is not a consensus alias in the strict MVP profile. The
canonical economic operation is `SESSION_ESCROW_EXTEND`, which carries the
complete next Funding Account, binds the exact predecessor and applies one
atomic Consumer debit. A validator SHALL reject `SESSION_DEPOSIT_EXTEND`
rather than risk a second implementation of the same funding mutation.

The legacy domain operation MAY remain in compatibility services, but it SHALL
not create canonical Q movement. The following fields describe that local
projection only; they are not a strict validator transition.

Preconditions

- sender controls the Consumer Wallet;
- Session permits extension;
- amount is positive;
- Wallet has sufficient available `Q`.

State Changes

- reduces Consumer available balance;
- increases Session locked Deposit;
- records Deposit extension sequence.

The extension becomes usable only after operation finalization.

## 42. Ordinary Session Settlement

`SESSION_SETTLE`

This legacy name is not a consensus alias in the strict MVP profile. The
canonical economic path is the typed `SESSION_SETTLEMENT_PROPOSE` ->
`SESSION_SETTLEMENT_ACCEPT` -> `SESSION_SETTLEMENT_FINALIZE` family (or the
explicit dispute/forced variants). A validator SHALL reject `SESSION_SETTLE`
instead of selecting an undocumented settlement shortcut. The remainder of
this section describes the legacy local projection and is not consensus
authorization.

Origin

`MULTI_PARTY`.

Required Evidence

- Provider-signed final Usage Report;
- Consumer Usage Acknowledgement;
- Provider-signed Invoice;
- final accepted checkpoint;
- applicable policy hashes.

Preconditions

- Session is active or closing;
- no unresolved Confirmed Mismatch exists;
- Usage chain is valid;
- Invoice derives from accepted usage and pricing;
- total payment does not exceed Deposit;
- Settlement has not already occurred.

State Changes

- pays the Endpoint Payment Beneficiary;
- removes Session fee where applicable;
- refunds unused Deposit;
- closes Session;
- stores Settlement references;
- emits Reputation events.

Settlement SHALL be idempotent by Session ID.

Only one final Settlement may apply.

## 43. Session Expiration

`SESSION_EXPIRE`

Protocol-generated expiration.

Applicable Cases

- pending acceptance timeout;
- expired Session without activity;
- Session maximum duration reached;
- protocol-defined inactivity timeout.

State Changes

Depend on Session state and policy.

For pending Sessions:

- unlock Deposit;
- mark `EXPIRED`.

For active Sessions:

- transition to the forced-settlement workflow;
- preserve last accepted Usage checkpoint.

## 44.1 Session Failure Evidence

`SESSION_FAILURE_EVIDENCE`

Commits the compact, Session-bound evidence reference consumed by a Forced
Settlement. The full Failure Evidence and Failure Report remain in the
durable Hypervisor snapshot or restricted evidence storage.

Origin

`EVIDENCE_TRIGGERED`.

Required Payload

```yaml
session_id:
failure_class:
failure_evidence_root:
details: optional
```

Required Evidence

- `failure_evidence_root`;
- the local or restricted RFC-0060 evidence object identified by that root.

State Changes

- records an immutable evidence commitment;
- creates no payment or refund;
- may be referenced by idempotent Forced Settlement attempts for the same
  Session and root.

Consensus Validation

- requires `EVIDENCE_TRIGGERED` origin and `session` fee class;
- requires the `session_id` to match `initiator_id`;
- requires the evidence root to appear in `evidence_references`;
- rejects unsupported failure classes and conflicting reuse of one
  Session/root pair.

The operation SHALL be finalized before a consensus `SESSION_FORCE_SETTLE`
operation that references it. A conflicting Session, failure class or root is
rejected.

## 44. Forced Session Settlement

`SESSION_FORCE_SETTLE`

Terminates a Session without ordinary dual-party completion.

Origin

`EVIDENCE_TRIGGERED`.

Possible Causes

- Consumer disappearance;
- Provider disappearance;
- confirmed Usage Mismatch;
- timeout;
- Deposit exhaustion;
- forced Provider termination;
- unrecoverable Session state.

Required Evidence

Defined by `RFC-0060`.

At minimum:

- Session state;
- last accepted Usage checkpoint;
- timeout or mismatch evidence;
- applicable policy;
- reporting party signature.

State Changes

- pays only deterministically authorized amounts;
- refunds remaining undisputed Deposit;
- records unresolved or attributed failure;
- closes Session;
- emits Reputation events.

For a multi-Request Session, the payload SHALL also commit the Request
Settlement Root, Usage Chain Root, Checkpoint Root and per-Request evidence.
The operation applies an already evaluated Settlement Input Set and does not
replace Request-level ceilings or Usage-chain conflict handling.

## 45. Validation Request

`VALIDATION_REQUEST`

Requests Initial or Maintenance Validation.

Authorization

Signed by Endpoint owner for Initial Validation.

Maintenance Validation MAY be protocol-triggered.

Required Payload

```yaml
validation_request_id:
endpoint_id:
endpoint_configuration_hash:
validation_type:
capability_id:
bond_reference:
request_expiration:
```

Preconditions

- Endpoint exists;
- Configuration Hash matches;
- requester is authorized;
- required Validation Bond is locked for Initial Validation;
- no conflicting active request exists.

State Changes

- creates Validation Request;
- sets Endpoint Certification state to `VALIDATION_PENDING` where applicable;
- adds request to the validation scheduling queue.

Publication does not automatically create an assignment.

## 46. Validation Assignment Creation

`VALIDATION_ASSIGNMENT_CREATE`

Protocol-generated assignment commitment.

Privacy Requirement

The operation SHALL NOT expose the Validator identity before report publication.

Required Payload

```yaml
assignment_id:
assignment_commitment:
validation_request_id:
endpoint_id:
capability_id:
assignment_epoch:
deadline:
escrow_authorization_hash:
```

State Changes

- reserves one Validation assignment;
- binds it to the Validation Request;
- records opaque assignment commitment;
- records deadline.

Assignment acceptance and decline MAY occur off-chain through the Validation Escrow protocol.

## 47. Validation Report Commit

`VALIDATION_REPORT_COMMIT`

Publishes the canonical commitment to a completed Validation Report.

Required Payload

```yaml
report_id:
report_hash:
report_size:
report_schema_version:
validation_request_id:
assignment_id:
endpoint_id:
endpoint_configuration_hash:
capability_id:
capability_version:
validator_service_id:
conclusion_summary:
limitation_codes:
failure_codes:
observation_codes:
evidence_root:
report_locator:
access_class:
retention_policy_id:
endpoint_storage_receipt_hash:
storage_failure_reference:
```

Authorization

Signed by the revealed Validator Service.

The signature and report SHALL prove that the Validator matches the previously opaque assignment commitment.

Preconditions

- assignment exists;
- report is within deadline or accepted grace period;
- Validator was eligible;
- report schema is valid;
- report hash and size match the signed report envelope;
- exactly one of a valid Endpoint Storage Receipt or an allowed Storage Failure reference is supplied;
- assignment has not already been completed.

State Changes

- marks assignment completed;
- records report commitment;
- reveals Validator identity;
- makes report eligible for Certification derivation and rewards.

The operation does not directly decide Certification.

### Validation Report Storage Receipt

`VALIDATION_REPORT_STORAGE_RECEIPT`

Records the validated Endpoint Hypervisor's signed acceptance of origin custody. The receipt SHALL bind the Validation ID, Endpoint ID, Configuration Hash, Report Hash, size, stable logical locator and Retention Policy ID. It does not express agreement with the conclusion.

### Validation Report Storage Failure

`VALIDATION_REPORT_STORAGE_FAILURE`

Records objective evidence that a valid report could not be transferred to or accepted by the validated Endpoint Hypervisor. This operation SHALL NOT suppress the report conclusion. A positive result without a receipt cannot create Certification; adverse and inconclusive evidence remain processable under `RFC-0065`.

### Validation Report Availability Commit

`VALIDATION_REPORT_AVAILABILITY_COMMIT`

Commits a bounded custody challenge result, including Report Hash, challenged locator, actor identity, observed state, attempt boundary and evidence root. Duplicate observations from the same challenge count once.

### Validation Report Custody Release

`VALIDATION_REPORT_CUSTODY_RELEASE`

Records the deterministic end of mandatory origin custody after Endpoint retirement and the configured grace period. It does not delete the canonical commitment, report hash, Certification history or Reputation history.

## 48. Certification State Update

`CERTIFICATION_STATE_UPDATE`

Protocol-generated Certification transition.

Possible States

- `UNCERTIFIED`;
- `VALIDATION_PENDING`;
- `CERTIFIED`;
- `CERTIFIED_WITH_OBSERVATIONS`;
- `DEGRADED`;
- `CERTIFICATION_REVOKED`;
- `INCONCLUSIVE`.

Preconditions

- applicable Validation Report set is finalized;
- Configuration Hash matches;
- Certification derivation rules produce the stated result.

State Changes

- updates Certification state;
- records supporting report IDs;
- records effective Epoch and expiration where applicable.

## 49. Validation Bond Refund

`VALIDATION_BOND_REFUND`

Returns a protocol-defined portion of the remaining Validation Bond.

Preconditions

- applicable successful Maintenance Validation finalized;
- refund schedule permits release;
- Bond remains locked;
- no Critical failure exists.

State Changes

- reduces locked Bond;
- credits owner Wallet;
- records remaining Bond.

Recommended schedule:

`refund = 50% of remaining Bond`

## 50. Validation Bond Forfeiture

`VALIDATION_BOND_FORFEIT`

Removes the remaining Validation Bond after a qualifying failure.

Required Evidence

- finalized Maintenance Validation Report;
- Critical issue or qualifying failure;
- matching Endpoint Configuration Hash;
- deterministic forfeiture rule.

State Changes

- remaining Bond becomes recyclable removed `Q`;
- Certification is revoked or suspended;
- related Reputation events are emitted.

Previously refunded Bond portions remain with the operator.

## 51. Service Verification Commit

`SERVICE_VERIFICATION_COMMIT`

Commits a Service Verification Report.

Applicable Services

- Registry;
- Consensus where additional verification is required;
- future infrastructure Services.

Required Payload

```yaml
verification_report_id:
service_id:
service_type:
report_hash:
evidence_root:
verification_epoch:
result_summary:
registry_reference:
```

State Changes

- records verification evidence;
- updates current Health inputs;
- marks Duty Proof status;
- makes Service eligible or ineligible for current reward calculation.

The MVP consensus boundary requires protocol origin, non-empty report and
evidence hashes, a non-negative verification Epoch matching the envelope
target, a structured result summary and a non-empty Registry reference.  A
second operation for the same verification report is rejected.  This
operation is evidence-only: it does not credit a Wallet or create a
`REWARD_MINT`.  Consensus-finality validation of the referenced evidence stays
with the Registry/consensus integration and is not delegated to a generic
operation handler.

## 52. Reputation Profile Update

`REPUTATION_PROFILE_UPDATE`

Protocol-generated update to one Reputation Profile.

Required Payload

```yaml
object_id:
object_type:
previous_profile_hash:
new_profile_hash:
metric_deltas:
  <dimension_id>:
    positive_mass_milli:
    negative_mass_milli:
    event_count:
evidence_root:
effective_epoch:
formula_version:
```

Preconditions

- all referenced events are finalized;
- formula version matches protocol state;
- resulting profile is deterministic.

`positive_mass_milli`, `negative_mass_milli` and `event_count` are
non-negative integer fixed-point accumulators. The Ledger commits these
profile inputs and their evidence root; it does not calculate Reputation
scores or independently assign a participant rating. The MVP formula version
is `reputation.v1`, and each profile object forms a strictly increasing
`effective_epoch` hash chain.

State Changes

- commits the new profile-root update and its evidence references;
- preserves historical profile-root references for the profile engine;
- does not calculate a score, mutate Reputation state, or create a payment.

Reputation SHALL NOT be manually assigned.

## 53. Epoch Transition

`EPOCH_TRANSITION`

Finalizes one Epoch and activates the next.

Required Payload

```yaml
closing_epoch:
opening_epoch:
closing_state_root:
epoch_task_result_root:
eligibility_snapshot_root:
reward_calculation_root:
next_protocol_parameters_hash:
```

Preconditions

- all mandatory closing tasks reached terminal state;
- transition is expected at the current block time or height;
- roots are deterministic.

State Changes

- closes current Epoch;
- activates next eligibility snapshot;
- activates scheduled parameter changes;
- resets Epoch-scoped counters;
- opens the next Epoch.

The MVP consensus boundary requires `opening_epoch = closing_epoch + 1`, a
protocol origin without a Wallet sender, all transition roots, a typed pool
budget map and, when present, a non-empty reference for every pool budget.
The target Epoch must match `closing_epoch`, and a second transition for the
same closing Epoch is rejected.  Both ABCI and deterministic local block
execution apply this validation before recording the operation.

## 53.1 Epoch Result Manifest Commit

`EPOCH_RESULT_MANIFEST_COMMIT`

Commits the immutable RFC-0048 Epoch Result Manifest that aggregates the
finalized evidence roots and budget references required by a later
`EPOCH_TRANSITION`.

The current historical-chain-bound payload is
`aidn.epoch-result-manifest.v2`. Nodes MAY replay the earlier `v1` payload for
backward-compatible state restoration, but a legacy manifest without closing
block/state/AppHash commitments MUST NOT make an epoch transition `READY`.

Required Payload

```yaml
manifest:
  manifest_version:
  manifest_state: FINALIZED
  epoch_number:
  start_height:
  closing_height:
  start_time:
  closing_time:
  closing_block_hash:
  closing_state_root:
  source_app_hash:
  protocol_version:
  parameter_version:
  task_set_version:
  epoch_schedule_version:
  epoch_schedule_hash:
  scheduled_end_time:
  frozen_evidence_root:
  participant_snapshot_root:
  service_snapshot_root:
  task_result_root:
  eligibility_root:
  reputation_root:
  penalty_root:
  recycle_root:
  reward_authorization_root:
  reward_result_root:
  faucet_root:
  validator_set_update_root:
  reward_calculation_root:
  next_protocol_parameters_hash:
  pool_budgets: {}
  pool_budget_references: {}
  next_epoch_reference:
  previous_epoch_result_hash:
  manifest_hash:
```

Preconditions

- operation origin is Protocol, the fee class is `PROTOCOL_SPONSORED`, and no
  Wallet sender is present;
- the manifest is `FINALIZED`, hash-bound to the canonical manifest schema,
  and its closing height is not before its start height;
- every pool budget has exactly one non-empty canonical reference and every
  budget is a non-negative integer amount in Q atoms;
- only one manifest may be committed for an Epoch number.

State Changes

- records the immutable manifest and emits `EpochResultManifestCommitted`;
- creates no Wallet balance effect, pool spend, reward authorization or
  protocol-parameter activation;
- makes the manifest available to the read-only Epoch Transition Input
  preflight.

When a transition includes `epoch_result_manifest_hash` and
`epoch_result_manifest_operation_id`, the referenced manifest MUST already be
finalized before the block containing the transition begins. A manifest and a
dependent transition in the same block are rejected in both ABCI and
deterministic execution. The transition MUST reproduce the manifest's task,
eligibility, reward, parameter, schedule and pool-budget bindings exactly.

Read-only ABCI Projection

Validators SHALL expose a public identity projection at:

```text
epoch/result-manifest/<epoch_number>
```

The projection MAY be queried by quorum and release-gate tooling. It SHALL
contain only the finalized operation identity (`operation_id`,
`operation_type`, `sequence_id`, `record_digest`), `manifest_hash`, epoch
number, historical closing height/time/block hash/state root, source AppHash,
and epoch-schedule bindings. It SHALL not expose the manifest payload,
signatures or private evidence. An absent, stale or conflicting projection
MUST fail closed for any transition-readiness decision.

## 54. Reward Mint

`REWARD_MINT`

Creates `Q` from an authorized reward pool.

Supported Reward Types

- Consensus Reward;
- Registry Reward;
- Validation Reward;
- future authorized protocol reward.

External Faucet payments are ordinary signed `WALLET_TRANSFER` operations and
are never represented by `REWARD_MINT`.

Required Payload

```yaml
reward_id:
reward_type:
reward_epoch:
recipient_wallet:
amount:
pool_id:
pool_budget_reference:
contribution_evidence_root:
calculation_version:
reward_calculation_root:
calculation_operation_id:
```

Compatibility-only Preconditions

- reward calculation is finalized;
- recipient was eligible;
- amount matches deterministic formula;
- pool has sufficient authorization;
- reward was not previously minted;
- total Epoch Mint remains within `ECO-0005` limits.
- `calculation_operation_id` identifies an existing `EPOCH_TRANSITION`;
- verified consensus finality exists for that exact operation;
- the transition commits the same `reward_calculation_root`, Epoch and pool
  budget;
- all previous `REWARD_MINT` operations under that calculation root remain
  within the committed pool budget.

State Changes

- increases recipient balance;
- increases Total Supply;
- reduces remaining pool authorization;
- records reward provenance.

No Wallet may submit `REWARD_MINT`.

The MVP Ledger boundary is idempotent by `reward_id`.  A repeated identical
request returns the existing operation without crediting the recipient twice;
a conflicting retry is rejected.  A Registry Service or local Epoch worker may
prepare a calculation, but only the consensus-authorized protocol path may
create this operation and apply the Q balance effect.

The MVP consensus execution boundary applies the same rule in both supported
block entrypoints (`ABCI` and the deterministic `ExecutionEngine`): the
`calculation_operation_id` must be present in the finalized operation set that
existed before the block started.  A transition and its dependent mint in one
block is rejected, and a registered generic operation handler cannot bypass the
`REWARD_MINT` validation or wallet-credit path.  This closes the local
consensus execution boundary for Registry rewards; it does not claim that all
RFC-0059 operation families already have specialized consensus handlers.

The validator production profile is fail-closed for catalog entries without a
specialized transition. Such an operation is rejected before mempool/proposal
acceptance rather than being recorded by the generic admitted-envelope path.
The current implemented and declared-but-unimplemented sets are maintained in
the [consensus operation coverage matrix](../development/consensus-operation-coverage.md).

`SESSION_ESCROW_LOCK` is the first typed Session funding boundary in both
entrypoints. Its payload carries the complete locked `SessionFundingAccount`,
including both reserves, beneficiaries and `funding_state_hash`. Admission
reconstructs the account, verifies conservation and Consumer-wallet ownership,
checks prepaid balance, then debits the wallet and persists the account as one
atomic state transition. A generic handler cannot record this operation without
applying the escrow debit, and Snapshot restoration preserves both the wallet
balance and Funding Account.

`SESSION_OPEN` is the next typed Session lifecycle boundary in both entrypoints.
It requires the exact finalized lock operation, the lock's Funding state hash,
matching Session Contract and beneficiaries, and a complete Session/Endpoint
metadata binding. Applying it records only the lifecycle operation; it does not
touch wallet balances or Funding reserves. The implementation rebuilds this
projection from the canonical operation log during Snapshot restore, so a
restart cannot create a second economic lock or lose the open binding.

`SESSION_ACCEPT` is the following typed lifecycle transition. It is signed by
the Endpoint Payment beneficiary, requires a finalized `SESSION_OPEN` and
matching Session/Endpoint hashes, and records only the accepted lifecycle
projection. Its application does not debit the Endpoint, Consumer or Funding
Account; local Runtime allocation follows only after this canonical record.

The next typed Session funding boundaries are also implemented in both
entrypoints:

- `SESSION_ESCROW_EXTEND` accepts only a prepaid extension, binds the resulting
  complete Funding Account to the exact prior Funding state and finalized
  predecessor, verifies that only the two reserves and their unsettled portions
  increased, then debits the additional Consumer amount atomically;
- `SESSION_ESCROW_RELEASE` is an MVP co-authorized refund path. It requires
  both participant authorizations, can consume only currently unsettled payment
  and fee reserves, cannot consume a dispute reserve or pay the Endpoint, and
  updates the Consumer refund and Funding state atomically;
- `SESSION_CHECKPOINT_COMMIT` persists an integer `q_atoms` exposure checkpoint
  only while funding is locked. It enforces monotonic sequence/exposure,
  exact deposit conservation, prior Funding binding and evidence references,
  without moving funds.

The checkpoint and funding state are included in Ledger snapshots. Same-block
funding predecessor shortcuts are rejected because all predecessor operations
must be finalized before the dependent block.

## 55. Consensus Validator Set Update

`CONSENSUS_VALIDATOR_SET_UPDATE`

Protocol-generated update to the active CometBFT Validator Set.

Required Payload

```yaml
activation_epoch:
validator_additions:
  - node_id:
    operator_id:
    consensus_address:
    consensus_public_key:
    stake:
    voting_power:
validator_removals:
  - node_id:
voting_power_updates:
  - node_id:
    voting_power:
validator_set_hash:
eligibility_evidence_root:
participant_suspension_root:
```

Preconditions

- operation origin is Protocol and no Wallet sender is present;
- `activation_epoch` is a non-negative integer and matches the envelope
  target Epoch when one is supplied;
- at least one addition, removal or voting-power update is present;
- additions contain a node, operator, consensus address, positive Stake and
  positive voting power, and a valid 32-byte Ed25519 consensus public key;
- removals and voting-power updates contain a node identity and updates use
  positive voting power;
- one node identity does not occur in more than one update category;
- the Validator Set hash and eligibility evidence root are non-empty;
- `participant_suspension_root` is present when the schedule was built with a
  participant suspension snapshot;
- the application reconstructs the resulting Validator Set from the current
  active set and rejects a hash mismatch;
- no other update is already committed for the same activation Epoch.

Compatibility-only State Changes

- records one protocol-authorized Validator Set schedule;
- emits `ValidatorSetUpdateScheduled` for consensus adapter processing;
- does not credit a Wallet or activate CometBFT during schedule admission;
- at the matching `EPOCH_TRANSITION`, applies a previously finalized schedule
  to the canonical active set and emits CometBFT validator updates, including
  zero-power updates for removals.

The MVP consensus boundary validates and records the schedule in both ABCI and
deterministic local execution. Candidate selection, Known Control Group limits,
and higher-level eligibility policy remain separate checks defined by
`RFC-0047` and `ECO-0006`; the deterministic schedule builder binds those
checks to the immediately preceding finalized Eligibility snapshot and its
canonical evidence root. It also binds the canonical participant-suspension
root and excludes a participant whose suspension is effective at the target
activation Epoch. A schedule from the same block as its transition is not
eligible for activation because only pre-block-finalized schedules may change
the active set.

## 56. Snapshot Commit

`SNAPSHOT_COMMIT`

Commits a State Snapshot to Ledger history.

Required Payload

```yaml
snapshot_id:
block_height:
epoch:
application_state_hash:
snapshot_hash:
chunk_root:
protocol_version:
registry_references:
```

Preconditions

- operation origin is Protocol and no Wallet sender is present;
- `snapshot_id`, application-state hash, Snapshot content hash, Chunk Root and
  protocol version are non-empty;
- block height and Epoch are non-negative integers;
- the envelope target Epoch, when present, matches the payload Epoch;
- at least one typed Registry reference is present;
- the Snapshot ID has not already been committed.

State Changes

- records one metadata-only Snapshot commitment;
- emits `SnapshotCommitted` for Registry and State Sync indexing;
- does not credit a Wallet or transfer Q.

The Snapshot payload remains off-chain.

The MVP consensus boundary validates structural identity and replay protection.
It does not independently prove external finality, producer availability, chunk
contents or restoration correctness. Snapshot metadata commitment,
distribution, trusted-checkpoint handling and restoration semantics are defined
by `RFC-0062`.

## 57. Participant Suspension

`PARTICIPANT_SUSPEND`

Suspends a Hypervisor, Service or Endpoint from a defined protocol function.

Required Payload

```yaml
target_id:
target_type:
scope:
reason_code:
evidence_root:
effective_epoch:
minimum_recovery_epoch:
evidence_operation_id:
```

Preconditions

- objective finalized evidence exists;
- the evidence operation was finalized before the suspension block;
- the evidence operation ID and evidence root are envelope references;
- suspension rule is defined;
- scope is proportional to the violation.

State Changes

- updates relevant eligibility state;
- prevents affected rewards or actions;
- preserves unrelated functions unless broader suspension is justified.

## 58. Participant Reinstatement

`PARTICIPANT_REINSTATE`

Restores suspended eligibility.

Preconditions

- recovery conditions are satisfied;
- required delay elapsed;
- collateral restored where applicable;
- required verification succeeded.

The MVP requires a prior-finalized recovery evidence operation and refuses
reinstatement before `minimum_recovery_epoch`. Suspension and reinstatement
are persisted as participant state and do not themselves debit or mint Q.

State Changes

- removes applicable suspension;
- restores eligible state at the defined Epoch boundary;
- does not restore lost rewards retroactively.

## 59. Penalty Application

`PENALTY_APPLY`

Applies a protocol-defined economic penalty.

Required Payload

```yaml
penalty_id:
target_wallet_or_lock:
penalty_type:
amount:
evidence_root:
evidence_operation_id:
recyclable:
```

Preconditions

- objective evidence finalized;
- `evidence_operation_id` is already finalized before the block containing
  `PENALTY_APPLY`;
- both the evidence operation ID and `evidence_root` are present in the
  operation envelope evidence references;
- penalty rule exists;
- amount does not exceed the applicable Wallet balance or locked Stake amount;
- penalty not previously applied.

The MVP accepts `wallet:<wallet-id>` targets and `lock:<stake-id>` targets.
Wallet targets debit available Q; lock targets reduce the canonical locked
Stake without debiting the Wallet a second time. A partial slash keeps the
Stake in its current locked or unbonding state with a reduced amount; a full
slash marks it `SLASHED` and prevents release. The MVP penalty classes are
`CONSENSUS_SLASH`, `DOUBLE_SIGNING`,
`FORGED_CONSENSUS_EVIDENCE`, `UNAUTHORIZED_VALIDATOR_SET_MANIPULATION` and
`REPUTATION_PENALTY`.

State Changes

- removes `Q` from available or locked balance;
- adds amount to recyclable removal or permanent burn accounting;
- emits Reputation and eligibility events.

Ordinary subjective disagreement SHALL NOT authorize a penalty.

## 60. Omitted Protocol Messages

The following are not Ledger Operations in the MVP:

- `HELLO`;
- `PING`;
- `PONG`;
- `SESSION_DATA`;
- `SESSION_PROGRESS`;
- Runtime `HEALTH`;
- Runtime `EXECUTE`;
- Registry read queries;
- Validator assignment decline;
- Validator test prompts;
- Marketplace search;
- peer discovery.

These messages remain off-chain unless a separate finalized event requires a Ledger commitment.

## 61. Standard Error Codes

The MVP SHALL define at least:

- `INVALID_SCHEMA`
- `UNSUPPORTED_OPERATION_VERSION`
- `UNSUPPORTED_PROTOCOL_VERSION`
- `INVALID_SIGNATURE`
- `INVALID_SEQUENCE`
- `DUPLICATE_OPERATION`
- `OPERATION_EXPIRED`
- `INSUFFICIENT_BALANCE`
- `INSUFFICIENT_LOCKED_BALANCE`
- `INSUFFICIENT_FEE`
- `UNAUTHORIZED`
- `OBJECT_NOT_FOUND`
- `OBJECT_ALREADY_EXISTS`
- `STALE_OBJECT_VERSION`
- `INVALID_OBJECT_STATE`
- `INVALID_REFERENCE`
- `INVALID_EVIDENCE`
- `EVIDENCE_ALREADY_USED`
- `POOL_EXHAUSTED`
- `REWARD_ALREADY_MINTED`
- `FAUCET_ALREADY_CLAIMED`
- `NOT_ELIGIBLE`
- `SESSION_ALREADY_SETTLED`
- `SESSION_POLICY_MISMATCH`
- `ACCOUNTING_CONTRACT_MISMATCH`
- `CONFIGURATION_HASH_MISMATCH`
- `STAKE_LOCKED`
- `UNBONDING_NOT_COMPLETE`
- `PROTOCOL_INVARIANT_VIOLATION`

Error semantics SHALL be stable within an operation version.

## 62. Event Emission

Applied operations MAY emit deterministic events.

Examples:

- `HypervisorRegistered`;
- `ServiceActivated`;
- `EndpointAdvertisementPublished`;
- `SessionOpened`;
- `SessionSettled`;
- `ValidationReportCommitted`;
- `CertificationChanged`;
- `RewardMinted`;
- `ParticipantSuspended`;
- `SnapshotCommitted`.

Events support:

- Registry indexing;
- Marketplace updates;
- local notifications;
- Reputation calculations;
- monitoring.

Events do not independently modify state.

## 63. Evidence Replay Protection

Every evidence object used to authorize a state transition SHALL have a unique identifier.

The Ledger SHALL record consumed evidence where required.

The same evidence SHALL NOT be used twice to obtain:

- duplicate reward;
- duplicate refund;
- duplicate penalty;
- duplicate Settlement;
- duplicate Certification transition.

## 64. Protocol-Generated Operation Determinism

A Protocol Operation SHALL be derivable from finalized state and versioned protocol rules.

Every honest Consensus Service SHALL independently derive the same:

- operation type;
- payload;
- recipients;
- amounts;
- object versions;
- result.

Protocol Operations SHALL NOT depend on a privileged server assembling arbitrary instructions.

## 65. Mint Invariants

The State Machine SHALL reject any Mint operation that violates:

- `Mint amount > remaining authorized pool`
- `Reward already paid`
- `Recipient not eligible`
- `Evidence root invalid`
- `Epoch Mint limit exceeded`
- `Unknown reward type`

No administrator key SHALL be able to bypass these checks in ordinary operation.

## 66. Balance Invariants

After every finalized block:

- `Available Balance >= 0`
- `Locked Balance >= 0`
- `Total Wallet Balances + Total Locked Balances = Total Supply`

subject to explicitly modeled protocol holding states.

Recyclable emission authorization is not existing `Q` and SHALL NOT be counted in Total Supply.

## 67. Session Invariants

For every Session:

`Endpoint Payment + Refund + Session Fees + Applicable Penalties = Locked Deposit`

No final Session Settlement may distribute more `Q` than was locked.

Only one terminal Settlement may exist per Session.

## 68. Stake and Bond Invariants

For each Stake or Bond:

`Initial Locked Amount = Current Locked Amount + Released Amount + Removed Amount`

The same locked `Q` SHALL NOT secure multiple obligations unless an explicit protocol rule permits pooled collateral.

## 69. Object Ownership Invariants

Every owned object SHALL have exactly one active owner Wallet unless the protocol introduces an explicit multi-owner type.

Changing ownership requires a dedicated ownership-transfer operation.

Metadata updates SHALL NOT silently change ownership.

## 70. Upgrade Compatibility

New operations require:

- a new operation type or version;
- canonical schema;
- activation Epoch;
- deterministic migration rules;
- compatibility handling.

Existing operation semantics SHALL NOT be silently reinterpreted.

## 71. MVP Mandatory Operations

The MVP SHALL implement at minimum:

- `HYPERVISOR_REGISTER`;
- `HYPERVISOR_UPDATE`;
- `HYPERVISOR_RETIRE`;
- `SERVICE_REGISTER`;
- `SERVICE_UPDATE`;
- `SERVICE_RETIRE`;
- `ENDPOINT_REGISTER`;
- `ENDPOINT_UPDATE`;
- `ENDPOINT_ADVERTISEMENT_PUBLISH`;
- `ENDPOINT_ADVERTISEMENT_WITHDRAW`;
- `ENDPOINT_OFFER_PUBLISH`;
- `ENDPOINT_OFFER_WITHDRAW`;
- `ENDPOINT_SUSPEND`;
- `ENDPOINT_REINSTATE`;
- `ENDPOINT_RETIRE`;
- `WALLET_TRANSFER`;
- `TREASURY_FUND`;
- `STAKE_LOCK`;
- `UNSTAKE_REQUEST`;
- `STAKE_RELEASE`;
- `SESSION_OPEN`;
- `SESSION_ACCEPT`;
- `SESSION_REJECT`;
- `SESSION_CANCEL`;
- `SESSION_DEPOSIT_EXTEND`;
- `SESSION_SETTLE`;
- `SESSION_EXPIRE`;
- `VALIDATION_REQUEST`;
- `VALIDATION_ASSIGNMENT_CREATE`;
- `VALIDATION_REPORT_COMMIT`;
- `VALIDATION_REPORT_STORAGE_RECEIPT`;
- `VALIDATION_REPORT_STORAGE_FAILURE`;
- `VALIDATION_REPORT_AVAILABILITY_COMMIT`;
- `VALIDATION_REPORT_CUSTODY_RELEASE`;
- `CERTIFICATION_STATE_UPDATE`;
- `VALIDATION_BOND_REFUND`;
- `VALIDATION_BOND_FORFEIT`;
- `SERVICE_VERIFICATION_COMMIT`;
- `REPUTATION_PROFILE_UPDATE`;
- `EPOCH_RESULT_MANIFEST_COMMIT`;
- `EPOCH_TRANSITION`;
- `REWARD_MINT`;
- `CONSENSUS_VALIDATOR_SET_UPDATE`;
- `SNAPSHOT_COMMIT`;
- `PROTOCOL_UPGRADE_PROPOSE`;
- `PROTOCOL_UPGRADE_AUTHORIZE`;
- `PROTOCOL_UPGRADE_SCHEDULE`;
- `PROTOCOL_READINESS_SIGNAL`;
- `PROTOCOL_READINESS_WITHDRAW`;
- `PROTOCOL_UPGRADE_POSTPONE`;
- `PROTOCOL_UPGRADE_CANCEL`;
- `PROTOCOL_UPGRADE_ACTIVATE`;
- `EMERGENCY_ACTION_AUTHORIZE`;
- `EMERGENCY_ACTION_ACTIVATE`;
- `EMERGENCY_ACTION_EXTEND`;
- `EMERGENCY_ACTION_END`;
- `STATE_REPAIR_COMMIT`;
- `STATE_REPAIR_APPLY`;
- `NETWORK_RECOVERY_MANIFEST_COMMIT`;
- `GOVERNANCE_PROPOSAL_SUBMIT`;
- `GOVERNANCE_PROPOSAL_WITHDRAW`;
- `GOVERNANCE_PROPOSAL_SPONSOR`;
- `GOVERNANCE_PROPOSAL_UNSPONSOR`;
- `GOVERNANCE_REVIEW_OPEN`;
- `GOVERNANCE_VOTING_OPEN`;
- `GOVERNANCE_VOTE`;
- `GOVERNANCE_VOTE_WITHDRAW`;
- `GOVERNANCE_VOTING_FINALIZE`;
- `GOVERNANCE_ECONOMIC_SIGNAL`;
- `GOVERNANCE_ECONOMIC_SIGNAL_WITHDRAW`;
- `GOVERNANCE_AUTHORIZATION_COMMIT`;
- `GOVERNANCE_PROPOSAL_REJECT`;
- `GOVERNANCE_PROPOSAL_EXPIRE`;
- `GOVERNANCE_PROPOSAL_CANCEL`;
- `GOVERNANCE_COUNCIL_UPDATE`;
- `GOVERNANCE_MODE_TRANSITION`;
- `GOVERNANCE_SHORT_SAFETY_PAUSE`;
- `GOVERNANCE_EMERGENCY_AUTHORIZE`;
- `PARTICIPANT_SUSPEND`;
- `PARTICIPANT_REINSTATE`;
- `PENALTY_APPLY`.

`SESSION_FORCE_SETTLE` remains explicitly bound to the failure evidence, timeout, checkpoint, and forced-settlement rules defined in [RFC-0060 Session Failure, Recovery and Forced Settlement](./RFC-0060-session-failure-recovery-and-forced-settlement.md).

Upgrade, emergency-recovery, and state-repair semantics for these operations are defined by [RFC-0066 Protocol Upgrade and Emergency Recovery](./RFC-0066-protocol-upgrade-and-emergency-recovery.md).

Governance proposal, sponsorship, voting, chamber-snapshot, and authorization-certificate semantics for the governance operations are defined by [RFC-0067 Protocol Governance and Authorization Policy](./RFC-0067-protocol-governance-and-authorization-policy.md).

## 72. Deferred Operations

The MVP MAY postpone:

- Wallet multisignature;
- delegated spending;
- Hypervisor ownership transfer;
- Endpoint ownership transfer;
- scheduled Wallet transfers;
- recurring transfers;
- governance proposals;
- governance voting;
- protocol upgrade voting;
- cross-chain operations;
- confidential transfers;
- organizational Wallets;
- collaborative Validation rewards.

Deferred operations SHALL NOT be simulated through unrelated existing operations.

### 72.1 ECO-0007 Development Reward Operations

The following operation names are reserved by ECO-0007. They are registered
in the catalog. The current profile applies the following narrow transitions:
`DEVELOPMENT_REWARD_CALCULATE` as an evidence-only commitment,
`DEVELOPMENT_POOL_ALLOCATE` as a source-bound reserve record,
`DEVELOPMENT_POOL_CARRYOVER` as a source-epoch-bound carryover record,
`DEVELOPMENT_BOUNTY_CREATE`, `DEVELOPMENT_BOUNTY_RESERVE`,
`DEVELOPMENT_BOUNTY_RELEASE` and `DEVELOPMENT_BOUNTY_EXPIRE` as a
budget-bound bounty lifecycle,
`DEVELOPMENT_REWARD_RESERVE` as a schedule-bound reserve record, and
`DEVELOPMENT_REWARD_PAY_IMMEDIATE` and `DEVELOPMENT_REWARD_PAY_MATURITY` as
source-bound payment transitions, plus
`DEVELOPMENT_REWARD_MARK_UNCLAIMED` as a source-bound unclaimed-stage record,
`DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED` as a carryover-return transition, and
`DEVELOPMENT_REWARD_FINALIZE_COMMITMENT` as an evidence-only close:

- `DEVELOPMENT_POOL_ALLOCATE`;
- `DEVELOPMENT_POOL_CARRYOVER`;
- `DEVELOPMENT_BOUNTY_CREATE`;
- `DEVELOPMENT_BOUNTY_RESERVE`;
- `DEVELOPMENT_BOUNTY_RELEASE`;
- `DEVELOPMENT_BOUNTY_EXPIRE`;
- `DEVELOPMENT_REWARD_RESERVE`;
- `DEVELOPMENT_REWARD_PAY_IMMEDIATE`;
- `DEVELOPMENT_REWARD_PAY_MATURITY`;
- `DEVELOPMENT_REWARD_MARK_UNCLAIMED`;
- `DEVELOPMENT_REWARD_CLAIM`;
- `DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED`;
- `DEVELOPMENT_REWARD_FINALIZE_COMMITMENT`;
- `DEVELOPMENT_REWARD_CANCEL_UNVESTED`;
- `DEVELOPMENT_REWARD_CORRECT`.

Typed envelopes require the exact ECO-0007 policy hash, activation approval,
and dry-run commitment to match. `DEVELOPMENT_REWARD_CALCULATE` records the
full calculation evidence and remains non-emitting: it cannot reserve, mint,
or transfer Q. `DEVELOPMENT_POOL_ALLOCATE` requires a finalized prior-block
`EPOCH_TRANSITION` with the exact pool budget, a finalized prior-block
calculation, and an activation approval explicitly scoped to
`POOL_ALLOCATION` or `DEVELOPMENT_RESERVES`. It persists an immutable
allocation record with all budget still available; it does not credit a Wallet
or mint Q. `DEVELOPMENT_REWARD_RESERVE` requires finalized calculation and
pool-allocation source operations, binds the exact schedule identified by
`reward_id` and `schedule_hash`, and records a bounded reserve without a
Wallet effect. `DEVELOPMENT_REWARD_PAY_IMMEDIATE` requires those finalized
predecessors plus the exact payable payment hash, role, stage, amount and
verified Wallet binding. It materializes one immutable payment record, credits
only that amount, and rejects a repeated `(reserve_id, payment_hash, stage)`
with `DEVELOPMENT_REWARD_PAYMENT_DUPLICATE`. `DEVELOPMENT_REWARD_PAY_MATURITY`
additionally requires a finalized epoch transition whose opening epoch reaches
the exact stage boundary and accepts only a reserved maturity stage. The
payment transitions are not aliases for `REWARD_MINT` and do not accept a
different source or Wallet. `DEVELOPMENT_REWARD_MARK_UNCLAIMED` requires the
same finalized sources, an exact `UNCLAIMED` payment with no Wallet, and
persists a claim-expiration record without debiting the reserve or crediting a
Wallet; duplicate stage identities are rejected. Carryover validates the source
epoch transition and conservation split. Bounty lifecycle operations validate
the source pool allocation, bounded active reservations, release/expiry
conservation and immutable aggregate state. Reward cancellation and correction
validate an immutable source snapshot and append-only history; they can change
only unpaid maturity/unclaimed buckets and never rewrite paid history. Other
catalog operations not described as supported below remain rejected until a
future version defines their state transitions, replay rules, reserve
conservation, snapshot behavior, and multi-validator conformance.
`DEVELOPMENT_REWARD_CLAIM` requires the
finalized unclaimed record, a finalized epoch transition whose opening epoch
falls inside the immutable claim window, and an RFC-0068 signed Wallet
binding. It creates a separate immutable `CLAIMED` record, consumes exactly
the unclaimed stage, credits only the bound Wallet, preserves the original
`UNCLAIMED` evidence, and rejects duplicate claims. `DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED`
requires a finalized epoch transition after the claim window, returns exactly
one unclaimed stage to carryover availability, and preserves the original
unclaimed record. `DEVELOPMENT_REWARD_FINALIZE_COMMITMENT` records exact
source-operation IDs and deterministic roots for the calculation, allocation,
reserve, payment, unclaimed, claim and expiry evidence set. It is replay
protected and has no Wallet or Q effect. None of these operations SHALL be
aliased to
`REWARD_MINT`, `WALLET_TRANSFER`, or any existing operation.

## 73. Open Questions

The following require further specifications:

- exact forced Session Settlement rules;
- ownership transfer semantics;
- Service-specific Stake amounts;
- Consensus voting-power formula;
- exact reward weight formulas;
- challenge and appeal operations;
- Faucet carryover cap;
- complaint submission;
- emergency protocol halt;
- protocol-governance operations;
- confidential evidence handling.

## 74. Design Invariants

- Every canonical state change is caused by a Ledger Operation.
- Every operation has deterministic serialization.
- Every Wallet operation is signed and sequenced.
- Every finalized operation has a deterministic result.
- Operations are atomic.
- Mint Operations are protocol-generated only.
- Reward Mint never exceeds authorized pool budgets.
- Network Fees are removed and recycled.
- Off-chain traffic remains outside the Ledger.
- Large artifacts are committed by hash rather than stored in blocks.
- Object ownership cannot change through metadata updates.
- Every reward, refund, penalty and Settlement is replay-protected.
- Protocol Operations are independently derivable by every honest Consensus Service.
- Operation semantics change only through explicit versioning.

## RFC-0037 Settlement Operation Family

The canonical Session Settlement family additionally defines:

- `SESSION_ESCROW_LOCK` and `SESSION_ESCROW_EXTEND` for separate Endpoint
  Payment and Network Fee reserves;
- `SESSION_ESCROW_RELEASE` for bounded authorized release;
- `SESSION_SETTLEMENT_READY_COMMIT` for the immutable Settlement Input Root;
- `SESSION_SETTLEMENT_PROPOSE` and `SESSION_SETTLEMENT_ACCEPT` for exact amount
  and root agreement;
- `SESSION_SETTLEMENT_DISPUTE` for a bounded disputed amount and Evidence Root;
- `SESSION_SETTLEMENT_PARTIAL_FINALIZE` for atomic undisputed release;
- `SESSION_FORCED_SETTLEMENT_REQUEST` and
  `SESSION_FORCED_SETTLEMENT_RESOLVE` for RFC-0060 handling;
- `SESSION_SETTLEMENT_FINALIZE` for one replay-protected final transition;
- `SESSION_SETTLEMENT_CORRECT` for an authorized historical delta.

Every finalization operation binds Session ID, Settlement sequence, Input Root,
Endpoint Payment Beneficiary, Consumer Refund Beneficiary, prior releases,
Network Fees and reserve conservation. Transport acknowledgment is not
Settlement authorization or Ledger finality.

The MVP consensus execution profile now specializes seven Settlement operations
in both ABCI and the deterministic local Execution Engine:

- `SESSION_SETTLEMENT_READY_COMMIT` records an immutable, hash-bound
  Settlement Input commitment before proposal. It binds the current Funding
  predecessor, Session Contract, beneficiaries and request/Usage/Checkpoint
  roots, moves no Q, is replay-protected and survives Snapshot/State Sync.
  When present, a later typed proposal must reference and match the finalized
  readiness commitment exactly.

- `SESSION_SETTLEMENT_PROPOSE` reconstructs the typed proposal, binds it to the
  exact latest finalized Funding predecessor (`SESSION_ESCROW_LOCK`,
  `SESSION_ESCROW_EXTEND` or `SESSION_ESCROW_RELEASE`), current Funding state
  hash and beneficiaries, requires that predecessor and Input Root as evidence
  references, and checks both reserve-conservation equations before persisting
  it. A
  `PARTIAL_UNDISPUTED` proposal must carry equal, non-zero disputed amount and
  dispute reserve values; other modes must carry zero values;
- `SESSION_SETTLEMENT_ACCEPT` requires a previously finalized proposal,
  Consumer wallet binding, exact amounts, the proposal operation as evidence,
  and the proposal Input Root;
- `SESSION_SETTLEMENT_DISPUTE` accepts one exact dispute for a Settlement. It
  binds the dispute to the finalized proposal, Session/Input Root, participant
  claimant, dispute hash and Evidence Root, and does not move funds;
- `SESSION_SETTLEMENT_PARTIAL_FINALIZE` requires finalized proposal,
  acceptance and dispute dependencies. It atomically credits only undisputed
  Endpoint/Consumer amounts, consumes declared Network Fees and persists the
  Funding Account as `DISPUTE_RESERVED` with the bounded reserve intact;
- `SESSION_SETTLEMENT_CORRECT` is the narrow MVP reserve-resolution operation.
  It requires both participant signatures, the finalized partial-finalization
  dependency and exact prior transition hash, then consumes the active reserve
  once into Endpoint Payment and/or Consumer Payment Refund. It cannot change
  Network Fees or claw back prior credits, and the correction object is retained
  in snapshots;
- `SESSION_SETTLEMENT_FINALIZE` requires finalized proposal and acceptance
  dependencies and evidence references, verifies the complete
  `AtomicSettlementTransition`, rejects a non-zero dispute reserve, then
  credits Endpoint/Consumer wallets and updates Funding state atomically;
- `SESSION_FORCE_SETTLE` currently supports only finalized Endpoint failure
  evidence whose Session, failure class and evidence root match the finalized
  evidence operation, with zero Endpoint Payment and refund of the remaining
  locked exposure. Requested payment claims are not used as authorization.
  The transition Settlement ID is also evidence-bound for replay protection.

Dependencies are required to be finalized before the block containing the
dependent operation. Same-block proposal/acceptance/dispute/finalization
shortcuts are therefore rejected. The MVP deliberately supports one dispute per
Settlement and one reserve-resolution correction; multi-request dispute
aggregation, general post-finalization corrections and non-zero Forced
Settlement calculation remain later profiles.
