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
| `FAUCET_CLAIM` | Wallet + Hypervisor | Faucet Exempt |
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

## 33. Faucet Claim

`FAUCET_CLAIM`

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

- mints the fixed Faucet Share;
- credits destination Wallet;
- marks Hypervisor as claimed for the Epoch;
- reduces current Faucet authorization;
- updates Faucet carryover accounting.

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

## 37. Session Open

`SESSION_OPEN`

Creates a pending Session and locks the initial Deposit.

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
deposit_amount:
open_expiration:
```

Preconditions

- Consumer owns or controls the initiating Hypervisor;
- Endpoint is active and accessible;
- Endpoint version and policy hashes match current state;
- Deposit meets published minimum;
- Consumer has sufficient available `Q`;
- no duplicate Session ID exists.

State Changes

- creates Session in `PENDING_ACCEPTANCE`;
- locks Deposit;
- records accepted policy versions;
- records pending expiration;
- removes Session Network Fee into the recycle accumulator.

Session execution SHALL NOT begin before acceptance.

## 38. Session Accept

`SESSION_ACCEPT`

Provider accepts a pending Session.

Authorization

Signed by the Provider Hypervisor or authorized Endpoint execution identity.

Preconditions

- Session is pending;
- acceptance has not expired;
- Endpoint remains active;
- Endpoint configuration still matches;
- requested concurrency is available;
- Provider is authorized.

State Changes

- Session becomes `ACTIVE`;
- activation time is recorded;
- Session slot becomes reserved.

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

Adds `Q` to an active or pending Session Deposit.

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

Settles an ordinarily completed Session.

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
evidence_root:
effective_epoch:
```

Preconditions

- all referenced events are finalized;
- formula version matches protocol state;
- resulting profile is deterministic.

State Changes

- replaces active Reputation Profile;
- preserves historical profile references.

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

## 54. Reward Mint

`REWARD_MINT`

Creates `Q` from an authorized reward pool.

Supported Reward Types

- Consensus Reward;
- Registry Reward;
- Validation Reward;
- Faucet payment where not directly represented by `FAUCET_CLAIM`;
- future authorized protocol reward.

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
```

Preconditions

- reward calculation is finalized;
- recipient was eligible;
- amount matches deterministic formula;
- pool has sufficient authorization;
- reward was not previously minted;
- total Epoch Mint remains within `ECO-0005` limits.

State Changes

- increases recipient balance;
- increases Total Supply;
- reduces remaining pool authorization;
- records reward provenance.

No Wallet may submit `REWARD_MINT`.

## 55. Consensus Validator Set Update

`CONSENSUS_VALIDATOR_SET_UPDATE`

Protocol-generated update to the active CometBFT Validator Set.

Required Payload

```yaml
activation_epoch:
validator_additions:
validator_removals:
voting_power_updates:
validator_set_hash:
eligibility_evidence_root:
```

Preconditions

- Consensus eligibility calculation finalized;
- voting-power limits satisfied;
- Stake requirements satisfied;
- Known Control Group rules satisfied.

State Changes

- schedules or activates Validator Set changes;
- updates Consensus role state;
- emits adapter instructions for CometBFT.

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

- block and state hash are finalized;
- Snapshot format is supported;
- chunk root is valid.

State Changes

- records trusted Snapshot commitment;
- makes Snapshot available for Registry distribution and State Sync.

The Snapshot payload remains off-chain.

Snapshot metadata commitment, distribution, and restoration semantics are defined by `RFC-0062`.

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
effective_time:
minimum_recovery_epoch:
```

Preconditions

- objective finalized evidence exists;
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
recyclable:
```

Preconditions

- objective evidence finalized;
- penalty rule exists;
- amount does not exceed applicable balance or lock;
- penalty not previously applied.

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
- `FAUCET_CLAIM`;
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
