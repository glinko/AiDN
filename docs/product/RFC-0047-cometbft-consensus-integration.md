# RFC-0047 CometBFT Consensus Integration

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0016 Wallet and Identity`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0039 Hypervisor Service Model`
- `RFC-0042 Hypervisor Network Protocol`
- `RFC-0046 Registry Architecture`
- `RFC-0048 Epoch Engine`

## 1. Purpose

This document defines how the AiDN Ledger State Machine integrates with CometBFT.

CometBFT provides:

- Byzantine Fault Tolerant consensus;
- deterministic ordering of Ledger Operations;
- block production;
- block finalization;
- peer-to-peer transaction propagation;
- consensus-validator coordination.

AiDN provides:

- Ledger Operation definitions;
- operation validation;
- economic rules;
- Wallet balances;
- Escrow state;
- Session state;
- Endpoint state;
- Reputation Profiles;
- Epoch processing;
- Protocol Rewards.

CometBFT SHALL NOT implement AiDN business logic.

AiDN SHALL NOT implement its own consensus algorithm.

## 2. Design Philosophy

The architecture separates consensus from application state.

`Hypervisors -> Ledger Operations -> CometBFT Consensus -> Ordered Finalized Blocks -> AiDN Ledger State Machine -> Canonical Network State`

CometBFT determines the order in which valid operations are applied.

The AiDN Ledger State Machine determines what those operations mean.

Given:

- the same Genesis state;
- the same ordered blocks;
- the same protocol version;

every honest Consensus Service SHALL derive identical AiDN state.

## 3. Consensus Service

Consensus functionality is implemented as an optional Hypervisor Service.

An operator enables the Consensus Service through ordinary Hypervisor configuration.

The Consensus Service includes:

- a CometBFT node;
- an AiDN ABCI application adapter;
- Ledger State Machine access;
- consensus keys;
- block and state storage;
- synchronization components.

A Hypervisor without an enabled Consensus Service MAY still:

- own Wallets;
- host Endpoints;
- open Sessions;
- submit Ledger Operations;
- use Marketplace and Registry Services.

It SHALL NOT:

- propose blocks;
- vote on blocks;
- participate in finalization.

## 4. Terminology

AiDN uses two distinct validator concepts.

Consensus Validator

A Consensus Validator participates in CometBFT block consensus.

Its responsibilities include:

- proposing blocks;
- voting on blocks;
- maintaining consensus availability;
- signing finalized block commitments.

Endpoint Validator

An Endpoint Validator performs operational certification of Endpoints and produces Validation Reports.

Consensus Validators and Endpoint Validators are independent roles.

A Hypervisor MAY enable both services.

The protocol SHALL NOT assume that the two validator sets are identical.

## 5. Integration Boundary

The integration boundary between CometBFT and AiDN is the Application Blockchain Interface.

The AiDN application exposes deterministic handlers for:

- application initialization;
- transaction admission;
- proposal preparation;
- proposal validation;
- block finalization;
- state commitment;
- state queries;
- snapshot creation;
- snapshot restoration.

The adapter SHALL translate CometBFT requests into AiDN Ledger State Machine operations.

No AiDN protocol component SHALL modify CometBFT internals.

## 6. Ledger Operation Submission

A Hypervisor submits a signed Ledger Operation to one or more Consensus Services.

Examples include:

- Wallet Transfer;
- Session Open;
- Deposit Lock;
- Session Settlement;
- Endpoint Publication;
- Advertisement Publication;
- Validation Request;
- Validation Report Publication;
- Validator Stake;
- Service Registration.

Submission does not guarantee inclusion.

A submitted operation progresses through:

`Created -> Signed -> Submitted -> Admission Checked -> Mempool -> Proposed -> Finalized -> Applied`

Only finalized operations modify canonical Ledger state.

## 7. Operation Envelope

Every operation submitted to consensus SHALL use a common envelope.

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

The operation envelope SHALL be deterministically serialized.

The same logical operation SHALL always produce the same serialized bytes.

The authoritative operation envelope and per-operation catalog are defined in [RFC-0059 Ledger Operation Catalog](./RFC-0059-ledger-operation-catalog.md). This section describes the consensus boundary, not a competing operation-schema source of truth.

## 8. Operation Identity

`operation_id` SHALL be derived cryptographically from the canonical serialized operation.

The identifier SHALL include all signed fields.

A modified operation produces a different identifier.

Duplicate finalized Operation IDs SHALL be rejected.

## 9. Sender Sequence

Every Wallet maintains a monotonically increasing Ledger sequence.

An operation SHALL include the expected next sequence for its sender.

The sequence protects against:

- replay attacks;
- duplicate submissions;
- ambiguous ordering of Wallet operations.

An operation with an invalid sequence SHALL be rejected.

Parallel Wallet operations MAY require local queueing or future sequence-reservation mechanisms.

## 10. Admission Validation

Before an operation enters the active transaction pool, the AiDN application SHALL perform lightweight deterministic validation.

Admission validation includes:

- operation format;
- protocol version;
- signature validity;
- sender sequence;
- operation expiration;
- basic authorization;
- sufficient available balance where applicable;
- minimum Network Fee;
- payload size limits.

Admission validation SHALL NOT perform expensive external work.

It SHALL NOT:

- contact remote Hypervisors;
- execute Capability workloads;
- query non-consensus services;
- depend on local wall-clock time beyond consensus-provided values.

Passing admission validation does not guarantee final execution.

State may change before block finalization.

## 11. Proposal Preparation

When preparing a block proposal, the AiDN application MAY:

- remove operations that are no longer valid;
- order dependent operations deterministically;
- enforce per-type limits;
- enforce block resource limits;
- reserve space for mandatory protocol operations;
- reject duplicate operations.

Proposal ordering SHALL be deterministic.

Preferred ordering rules MAY include:

1. mandatory protocol operations;
2. expired-state cleanup;
3. Epoch boundary operations;
4. ordinary user operations;
5. lower-priority informational publications.

Fee-based ordering MAY be introduced later.

The MVP SHOULD avoid opaque auction-based ordering.

## 12. Proposal Validation

Every Consensus Validator SHALL independently validate the proposed operation list.

Proposal validation includes:

- canonical serialization;
- operation uniqueness;
- deterministic ordering;
- block limits;
- mandatory operation presence;
- dependency correctness;
- protocol-version compatibility.

A proposal violating AiDN rules SHALL be rejected.

## 13. Block Finalization

After CometBFT finalizes a block, the AiDN application applies its operations sequentially.

For each operation:

1. Revalidate against current block state.
2. Execute the deterministic state transition.
3. Record the operation result.
4. Emit protocol events.
5. Update application state.

An operation MAY have passed mempool admission but fail during final execution because an earlier operation changed relevant state.

Such failure SHALL be deterministic and recorded in the block result.

## 14. Atomicity

Each individual Ledger Operation SHALL execute atomically.

An operation either:

- applies completely; or
- produces no state change.

Operations within the same block are applied sequentially.

The failure of one ordinary operation SHALL NOT invalidate unrelated valid operations in the same block unless block-level validity rules were violated.

Compound economic actions requiring all-or-nothing behavior SHALL be represented as a single atomic Ledger Operation.

## 15. Application State

The committed AiDN state includes at minimum:

- Wallet balances;
- Wallet sequences;
- locked balances;
- Session Deposits;
- Escrow objects;
- Validation Bonds;
- Validator Stakes;
- Endpoint publication state;
- Advertisement references;
- Service registration state;
- Reputation Profiles;
- current Epoch state;
- Consensus Validator Set metadata;
- protocol parameters.

Large artifacts SHALL NOT be stored directly in consensus state.

Examples of off-chain objects include:

- prompts;
- model responses;
- images;
- audio;
- video;
- complete Validation Report artifacts;
- benchmark datasets;
- Runtime logs.

Consensus state stores cryptographic references where required.

## 16. State Commitment

After applying a finalized block, the AiDN application produces a deterministic application state hash.

The state hash commits to the complete canonical AiDN state at that block height.

All honest Consensus Services SHALL produce the same state hash.

A differing state hash indicates:

- nondeterministic application behavior;
- corrupted state;
- incompatible protocol implementation;
- invalid software version.

A Consensus Service producing inconsistent application state SHALL stop participating until recovered.

## 17. Block Contents

An AiDN block contains:

- CometBFT block header;
- previous block reference;
- finalized Ledger Operations;
- consensus evidence;
- consensus signatures;
- resulting application state commitment.

Block contents SHALL NOT include ordinary Session payload traffic.

Blocks contain only operations that modify or attest to long-term protocol state.

## 18. Block Time

Blocks SHALL be produced continuously.

Epoch duration is independent of block duration.

Initial targets MAY use:

`Target Block Interval: 2-5 seconds`

`Epoch Duration: 24 hours`

The exact block interval is an implementation and network parameter.

Protocol correctness SHALL NOT depend on an exact block interval.

## 19. Epoch Integration

The Epoch Engine does not replace block consensus.

CometBFT continues finalizing blocks throughout the Epoch.

Epoch Tasks generate deterministic Ledger Operations according to `RFC-0048`.

At an Epoch boundary:

1. The previous Epoch state is finalized.
2. Eligible Epoch Tasks derive their outputs.
3. Resulting system operations are included in finalized blocks.
4. Reputation Profiles are updated at the beginning of the new Epoch.
5. Rewards for the completed Epoch become payable according to the configured delay.
6. The next Validator and service scheduling state becomes active.

Epoch transition SHALL be represented by explicit Ledger Operations.

No node may independently mutate state merely because its local clock reached midnight.

## 20. Protocol Time

Consensus-provided block time is the authoritative protocol time.

Local system clocks SHALL NOT independently trigger Ledger transitions.

Time-dependent rules SHALL derive from:

- finalized block time;
- block height;
- Epoch number.

Examples include:

- operation expiration;
- Session deadlines;
- Epoch boundaries;
- reward availability;
- unstaking delays.

## 21. Consensus Validator Set

The Consensus Validator Set is maintained by the AiDN application and enacted through CometBFT validator updates.

A Validator Set entry includes:

```yaml
consensus_validator:
  hypervisor_id:
  owner_wallet:
  consensus_public_key:
  voting_power:
  activation_epoch:
  status:
```

Validator changes become active only at deterministic protocol boundaries.

The MVP SHOULD apply Validator Set changes at Epoch boundaries.

## 22. Consensus Eligibility

Consensus eligibility is independent from Endpoint Validation eligibility.

Initial requirements SHOULD include:

- enabled Consensus Service;
- compatible protocol version;
- stable network connectivity;
- required Consensus Stake;
- minimum Consensus Reputation Profile;
- successful synchronization;
- valid consensus public key;
- absence of active suspension.

Exact thresholds SHALL be defined in the consensus economics specification.

For the MVP, that specification is `ECO-0006`.

## 23. Voting Power

The MVP SHALL avoid unlimited wealth-proportional voting power.

A large Wallet balance SHALL NOT permit one operator to dominate consensus merely by depositing more `Q`.

For the MVP, `ECO-0006` defines equal voting power per active Consensus Validator together with Known Control Group limits and deterministic active-set selection.

Future protocol versions MAY define another bounded voting-power model only through explicit economic specification and upgrade.

The total voting power controlled by one Wallet or related operator group SHOULD be capped where enforceable.

Participant-grouping, Reward Beneficiary aggregation, and broader Sybil-resistance principles are defined separately in [RFC-0058 Participant Eligibility and Sybil Resistance](./RFC-0058-participant-eligibility-and-sybil-resistance.md).

## 24. Consensus Stake

Consensus Validators SHALL lock a protocol-defined Stake.

Stake serves as collateral for consensus misconduct.

Stake SHALL NOT itself generate authority outside the configured voting-power rules.

Stake remains locked while the Consensus Service is active and for an unbonding period after voluntary exit.

The exact amount and unbonding duration are defined separately.

For the MVP, `ECO-0006` defines the Consensus Stake, unbonding, objective slashable misconduct, and validator-rotation rules.

## 25. Consensus Misconduct

Consensus misconduct includes objective cryptographic violations such as:

- double-signing conflicting blocks;
- signing conflicting votes at the same height and round;
- submitting invalid consensus evidence;
- protocol-key misuse.

Provable misconduct MAY result in:

- immediate suspension;
- loss of Consensus Rewards;
- Stake slashing;
- Consensus Reputation reduction;
- removal from the Validator Set.

Ordinary downtime SHOULD primarily reduce rewards and reputation rather than immediately burn Stake.

This avoids turning brief network failure into economic execution by firing squad, a tradition distributed systems can live without.

## 26. Consensus Liveness

The Consensus Service SHALL track:

- blocks proposed;
- votes expected;
- votes submitted;
- missed participation;
- synchronization status;
- signing reliability.

These metrics update the Consensus Reputation Profile.

Repeated absence MAY cause temporary suspension or removal from the active Validator Set.

## 27. Consensus Rewards

Consensus Services MAY receive Protocol Rewards for maintaining Ledger finality and availability.

Rewards SHALL depend on proven participation.

A Consensus Service receives no reward merely because it is configured.

Eligible evidence includes:

- signed consensus votes;
- successful proposals;
- participation ratio;
- availability during the Epoch.

Reward calculation is performed by an Epoch Task.

Detailed economics SHALL be defined separately.

## 28. Non-Consensus Hypervisors

A Hypervisor without Consensus Service submits operations through available Consensus or Gateway peers.

It SHALL:

- sign every operation locally;
- retain the Operation ID;
- monitor inclusion;
- verify finalization;
- retry submission when appropriate.

It SHALL NOT trust an unconfirmed response as final.

The submitting Hypervisor SHOULD verify:

- block inclusion proof;
- finalized block header;
- application state commitment where relevant.

## 29. Transaction Submission Reliability

The transaction pool is not durable storage.

A submitted operation may disappear before inclusion if receiving nodes fail.

Therefore, submitting Hypervisors SHALL:

- persist pending operations locally;
- monitor operation status;
- resubmit safely when not finalized;
- stop resubmitting once finalized or expired.

Resubmission of the same Operation ID SHALL remain safe.

## 30. Queries

Read-only Ledger queries do not require consensus.

A Hypervisor MAY query:

- Consensus Services;
- Registry Services;
- local synchronized state.

Query responses SHOULD include verifiable proofs where practical.

A query result does not modify state.

## 31. State Synchronization

New or recovering Consensus Services MAY synchronize through trusted state snapshots.

Synchronization includes:

1. discovering a recent Snapshot;
2. verifying the corresponding finalized block and validator set;
3. downloading Snapshot chunks;
4. applying the Snapshot to the AiDN state machine;
5. replaying later finalized blocks;
6. verifying the latest application state commitment.

Snapshot providers SHALL NOT be trusted solely by identity.

Snapshot correctness SHALL be cryptographically verified against finalized consensus state.

Detailed Snapshot creation, trusted-checkpoint selection, State Sync restoration, and later-block replay rules are defined by `RFC-0062`.

## 32. Snapshot Production

The Snapshot Manager registers Snapshot Generation as an Epoch Task.

Snapshots SHOULD be produced at regular finalized heights.

A Snapshot includes:

- protocol version;
- block height;
- application state hash;
- chunk metadata;
- creation Epoch;
- required verification metadata.

The canonical Snapshot manifest and State Sync semantics are defined by `RFC-0062`.

Consensus Services MAY retain only recent snapshots.

Registry Services MAY preserve broader Snapshot history.

## 33. Registry Relationship

CometBFT and Registry have different responsibilities.

CometBFT

Provides:

- consensus;
- finalized block order;
- current canonical chain;
- consensus evidence.

Registry

Provides:

- durable historical access;
- archived blocks;
- historical Ledger Operations;
- Validation Reports;
- Advertisements;
- State Snapshots;
- protocol-object lookup.

Consensus Services MAY use pruning policies.

Registry Services provide long-term history.

## 34. Genesis

The Genesis document establishes the initial network state.

Genesis SHALL define:

- network identifier;
- chain identifier;
- initial protocol version;
- initial Consensus Validator Set;
- initial Wallet allocations, if any;
- initial protocol parameters;
- initial application state hash rules;
- initial Epoch configuration.

CometBFT validates consensus-level Genesis fields.

The AiDN application validates AiDN-specific Genesis state.

## 35. Protocol Upgrades

Protocol upgrades SHALL be activated through deterministic Ledger state.

An upgrade definition includes:

- target protocol version;
- activation height or Epoch;
- required migration identifier;
- compatibility requirements.
- upgrade activation reference;
- resulting post-migration state root where applicable.

Consensus Services SHALL reject blocks produced under an incompatible application version after activation.

Upgrade logic SHALL be deterministic.

The activation block or activation reference SHALL remain part of canonical finalized history once finalized.

Emergency upgrades are outside the MVP unless required to address a critical network vulnerability.

## 36. Failure Modes

Application Crash

CometBFT SHALL NOT finalize new AiDN blocks while its application is unavailable.

The node recovers application state and resumes.

Consensus Service Crash

Other Consensus Validators continue if sufficient voting power remains online.

Network Partition

CometBFT safety SHALL be preferred over availability.

The minority partition SHALL NOT independently finalize conflicting AiDN state.

State Divergence

A node detecting a mismatched application state hash SHALL stop consensus participation and recover from a verified state.

Consensus Halt

Hypervisors MAY continue local computation.

New canonical Ledger transitions and Settlements remain pending until consensus resumes.

Recovery from ordinary halt SHALL restart from the last finalized height and state root.

If the last Validator Set cannot finalize the recovery path, continuation becomes an explicit Network Revision continuity event rather than an ordinary canonical restart.

## 37. Security Requirements

The integration SHALL defend against:

- replayed Ledger Operations;
- duplicate Operation IDs;
- forged Wallet signatures;
- invalid sender sequences;
- double spending;
- unauthorized minting;
- unauthorized Escrow release;
- inconsistent state execution;
- malicious proposals;
- invalid Validator Set updates;
- stale protocol versions;
- oversized operations;
- transaction spam.

Business-rule validation remains the responsibility of the AiDN application.

Consensus-rule validation remains the responsibility of CometBFT.

## 38. Determinism Requirements

AiDN consensus execution SHALL NOT depend on:

- operating-system behavior;
- map iteration order;
- floating-point ambiguity;
- external APIs;
- local databases outside committed state;
- local time;
- random-number generators without protocol-provided seeds;
- network responses;
- Capability Runtime state.

Economic calculations SHOULD use fixed-point integer arithmetic.

Canonical serialization SHALL be mandatory.

## 39. Observability

Consensus Services SHALL expose operational metrics, including:

- current block height;
- finalized block time;
- peer count;
- validator status;
- voting participation;
- proposal participation;
- mempool size;
- application state hash;
- synchronization state.

Consensus metrics SHALL feed the Consensus Reputation Profile where supported by verifiable events.

Local diagnostic metrics SHALL NOT directly modify Ledger Reputation.

## 40. Implementation Model

The reference implementation SHOULD run CometBFT as an independent local service connected to the Hypervisor application through ABCI.

An in-process deployment MAY be supported where technically appropriate.

The integration contract SHALL remain identical in either deployment mode.

The Hypervisor owns AiDN application configuration.

CometBFT owns consensus-specific configuration and keys.

## 41. MVP Scope

The MVP SHALL implement:

- CometBFT-based block consensus;
- AiDN ABCI application;
- signed Ledger Operation submission;
- sender sequences;
- operation admission validation;
- deterministic block execution;
- state commitment;
- Consensus Validator Set updates;
- state synchronization through Snapshots;
- non-validator transaction submission;
- basic consensus participation metrics.

The MVP MAY postpone:

- advanced fee markets;
- encrypted mempools;
- delegated stake;
- governance-controlled upgrades;
- sophisticated voting-power delegation;
- cross-chain interoperability.

## 42. Open Protocol Parameters

The following values remain to be defined:

- target block interval;
- maximum block size;
- maximum operation size;
- Consensus Stake;
- unbonding period;
- minimum Consensus Reputation;
- active Validator Set size;
- voting-power formula;
- Consensus Reward curve;
- downtime thresholds;
- slashing percentages;
- pruning depth;
- Snapshot frequency.

These parameters SHALL NOT be hardcoded across unrelated components.

They SHALL be maintained as versioned protocol configuration.

## 43. Design Invariants

- CometBFT orders and finalizes operations.
- The AiDN Ledger State Machine interprets operations.
- Consensus never contains Capability-specific logic.
- Wallet signatures authorize user operations.
- Only finalized operations modify canonical state.
- Every honest Consensus Service derives the same application state hash.
- Consensus Validators and Endpoint Validators are separate roles.
- Epoch transitions are explicit Ledger events.
- Local clocks never independently change Ledger state.
- Consensus Stake does not permit arbitrary `Q` creation.
- Registry stores history; consensus establishes canonical order.
- Hypervisors without Consensus Service remain full economic participants.
- AiDN SHALL reuse mature consensus technology rather than implement a novel BFT algorithm.
