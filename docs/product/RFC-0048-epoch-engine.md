# RFC-0048 — Epoch Engine

Status: Draft

Version: 0.2

Supersedes:

* RFC-0048 Version 0.1 - Reconstructed Edition

Depends on:

* RFC-0036 AiDN Ledger State Machine
* RFC-0037 Settlement Engine
* RFC-0039 Hypervisor Service Model
* RFC-0040 Service Verification Framework
* RFC-0041 Reputation Profile Engine
* RFC-0047 CometBFT Consensus Integration
* RFC-0059 Ledger Operation Catalog
* ECO-0004 Protocol Service Reward Distribution
* ECO-0005 Q Emission, Recycling and Epoch Reward Allocation
* ECO-0006 Consensus Economics and Validator Eligibility

---

## 1. Purpose

This document defines the AiDN Epoch Engine.

The Epoch Engine coordinates deterministic protocol work that is evaluated over bounded periods rather than during individual Ledger Operations.

It is responsible for:

* opening and closing Epochs;
* freezing Epoch evidence;
* executing deterministic Epoch Tasks;
* evaluating participant and Service eligibility;
* calculating protocol rewards;
* processing penalties and recyclable Q;
* calculating Faucet allocation;
* updating Service Maturity;
* updating Reputation Profiles;
* preparing Consensus Validator Set changes;
* committing Epoch results;
* opening the next Epoch;
* handling delayed or failed Epoch Tasks.

The Epoch Engine does not replace CometBFT consensus.

CometBFT orders and finalizes operations.

The Epoch Engine deterministically derives periodic protocol state from finalized history.

---

## 2. Epoch Definition

An Epoch is a bounded canonical protocol interval.

Each Epoch has:

```yaml
epoch:
  epoch_number:
  start_height:
  start_time:
  scheduled_end_time:
  closing_height:
  closing_time:
  parameter_version:
  task_set_version:
  status:
```

Epoch numbers SHALL increase monotonically.

---

## 3. Initial Epoch Duration

The recommended initial Epoch duration is:

24 hours

The exact duration is a versioned protocol parameter.

An Epoch is not closed by a local operating-system timer.

It closes only through a finalized canonical Epoch transition.

---

## 4. Canonical Time

Epoch scheduling SHALL use canonical block time under the active CometBFT rules.

Local Hypervisor clocks SHALL NOT independently determine:

* Epoch opening;
* Epoch closing;
* reward eligibility;
* assignment deadlines;
* Service Maturity;
* penalty windows.

---

## 5. Scheduled End

For Epoch t:

```text
ScheduledEndTime(t)
=
StartTime(t)
+
EpochDuration
```

The first valid Epoch transition finalized at or after the Scheduled End closes the Epoch.

---

## 6. Delayed Closing

An Epoch MAY close later than its Scheduled End because of:

* Consensus halt;
* temporary insufficient voting power;
* delayed transition proposal;
* protocol safety pause;
* activation failure;
* another canonical incident.

A late close does not create several artificial Epochs.

---

## 7. No Automatic Epoch Backfill

If Consensus is halted for several nominal Epoch durations, the network SHALL NOT create retroactive empty Epochs merely to catch up with wall-clock time.

Example:

Epoch 100 scheduled duration: 24 hours
Consensus halted for 72 hours

After recovery:

Epoch 100 closes once
Epoch 101 opens once

The protocol SHALL NOT automatically create Epochs 101, 102 and 103 with additional emission budgets.

---

## 8. Epoch Lifecycle

An Epoch follows:

```text
SCHEDULED
    ↓
OPEN
    ↓
CLOSING
    ↓
CLOSED
    ↓
PROCESSING
    ↓
FINALIZED
```

Failure-related states include:

```text
FINALIZATION_DELAYED
TASK_BLOCKED
CORRECTION_REQUIRED
```

---

## 9. SCHEDULED

The future Epoch exists in protocol scheduling state but has not yet opened.

Its active parameters MAY already be known.

---

## 10. OPEN

Ordinary protocol operations are accepted.

Services perform work.

Evidence and Ledger Operations accumulate.

---

## 11. CLOSING

The canonical closing transition is being prepared or finalized.

The evidence boundary is determined by the closing block.

---

## 12. CLOSED

The Epoch evidence set is immutable.

Operations finalized after the closing boundary belong to the next Epoch unless another protocol explicitly assigns them differently.

---

## 13. PROCESSING

Epoch Tasks derive:

* eligibility;
* rewards;
* Reputation changes;
* Service state;
* Validator Set changes;
* other periodic results.

Processing MAY continue after the next Epoch opens.

---

## 14. FINALIZED

All mandatory Epoch results have been committed.

The Epoch Result Root is canonical.

---

## 15. Epoch Boundary

The boundary between Epoch t and Epoch t + 1 is defined by one finalized transition.

```text
Closing block of Epoch t
        ↓
EPOCH_TRANSITION
        ↓
Opening state of Epoch t + 1
```

There SHALL be no block belonging to both Epochs.

---

## 16. Immediate Next-Epoch Opening

The next Epoch SHOULD open immediately when the previous Epoch closes.

The network SHALL not normally stop ordinary operation while all closed-Epoch calculations are completed.

This creates a pipeline:

```text
Epoch t work closes
        ↓
Epoch t+1 opens
        ↓
Epoch t results are processed
```

---

## 17. Epoch Processing Lag

Some Epoch results MAY require one or more later Epochs before finalization.

Examples include:

* reward challenges;
* misconduct evidence review;
* Validation Report verification;
* Registry non-response confirmation;
* correlated-failure analysis.

Every Task SHALL declare its maximum permitted finalization lag.

---

## 18. Epoch Transition Operation

The State Machine SHALL support:

`EPOCH_TRANSITION`

The operation is protocol-generated.

It SHALL include:

```yaml
epoch_transition:
  closing_epoch:
  opening_epoch:
  closing_height:
  closing_block_hash:
  closing_state_root:
  closing_time:
  next_epoch_start_time:
  next_epoch_scheduled_end_time:
  active_parameter_version:
  active_task_set_version:
  active_protocol_version:
  frozen_evidence_root:
  participant_snapshot_root:
  service_snapshot_root:
  randomness_commitment:
  transition_version:
```

---

## 18.1 Canonical Schedule Commitment

The State Machine SHALL support the one-time protocol operation:

`EPOCH_SCHEDULE_COMMIT`

It commits the hash-bound schedule used to calculate every canonical Epoch
boundary. A schedule supplied only through a validator environment or local
configuration is an implementation input, not consensus-final protocol state.

The operation SHALL:

- be finalized before the first `EPOCH_TRANSITION`;
- contain the complete `EpochSchedule` and its deterministic `schedule_hash`;
- carry the active protocol-authority policy hash and required authority
  threshold;
- be immutable and replay-protected;
- have no direct economic effect.

After finalization, transition input reports and `EPOCH_TRANSITION` payloads
SHALL include the exact schedule operation ID, finalized sequence ID and
record digest. The schedule query and state-sync recovery SHALL use the
canonical Ledger commitment, not an unverified local replacement. A schedule
commitment and a dependent transition in the same block SHALL not satisfy the
dependency: the transition must observe the schedule in a prior finalized
block.

---

## 19. Protocol-Generated Operation

No ordinary Wallet may construct an arbitrary valid Epoch transition.

The operation SHALL be generated and validated by deterministic State Machine rules.

A proposer may include the operation.

The proposer does not choose its contents.

---

## 20. Transition Eligibility

An Epoch transition is valid only when:

* the current Epoch is OPEN;
* Scheduled End has been reached;
* no transition already exists;
* the active protocol permits closing;
* required transition fields are deterministic;
* all mandatory pre-close conditions are satisfied.

---

## 21. Evidence Boundary

The Epoch evidence set consists only of evidence canonically finalized at or before the closing boundary.

Pending mempool operations do not count.

Uncommitted local observations do not count.

Registry objects count only when their canonical commitment was finalized within the permitted window.

---

## 22. Frozen Evidence Root

At closing, the State Machine calculates:

`FrozenEvidenceRoot(t)`

The root SHALL commit to all canonical evidence categories required by the active Epoch Task Set.

---

## 23. Evidence Categories

Initial evidence categories MAY include:

* Service registration state;
* participant eligibility state;
* Consensus votes;
* Consensus proposals;
* Registry challenges;
* Registry challenge responses;
* Service Verification results;
* Validation assignments;
* Validation Reports;
* Session outcomes;
* Usage Report commitments;
* Settlement results;
* Reputation Events;
* Stake and Bond state;
* fees;
* penalties;
* Faucet claims;
* configuration changes.

---

## 24. Late Evidence

Evidence finalized after the closing boundary SHALL normally belong to the next Epoch.

The protocol SHALL not reopen a closed Epoch merely because a participant submitted evidence late.

A Task MAY define a separate challenge or confirmation window without modifying the original evidence boundary.

---

## 25. Parameter Snapshot

All Epoch calculations SHALL use a fixed Parameter Snapshot.

```yaml
epoch_parameter_snapshot:
  epoch_number:
  protocol_version:
  economic_parameter_version:
  eligibility_parameter_version:
  reward_formula_version:
  reputation_formula_version:
  task_set_version:
  parameter_root:
```

---

## 26. No Mid-Epoch Economic Reinterpretation

A protocol parameter change activated during a later Epoch SHALL NOT reinterpret work performed under an earlier parameter version.

Examples include:

* reward percentages;
* Stake requirements;
* Health thresholds;
* Maturity formulas;
* Certification periods;
* Faucet allocation.

---

## 27. Participant Snapshot

The Epoch Engine SHALL create a Participant Snapshot containing:

* eligible Wallet identities;
* Known Control Groups;
* Reward Beneficiaries;
* active suspensions;
* Stakes;
* Bonds;
* governance or Service-role state where applicable.

This prevents identity changes during calculation from altering closed-Epoch outcomes.

---

## 28. Service Snapshot

The Service Snapshot contains the state of relevant:

* Consensus Services;
* Registry Services;
* Validation Services;
* Hypervisors;
* Endpoints;
* other protocol Services.

The snapshot SHALL identify:

* Service ID;
* owner;
* Known Control Group;
* Service state;
* configuration hash;
* activation age;
* Health;
* Maturity;
* applicable eligibility state.

---

## 29. Epoch Task

An Epoch Task is a deterministic periodic State Machine computation.

Every Task SHALL have:

```yaml
epoch_task:
  task_id:
  task_version:
  task_phase:
  dependency_task_ids:
  input_root:
  output_schema:
  failure_policy:
  finalization_lag:
  criticality:
```

---

## 30. Task Registry

The active Task Set SHALL be versioned.

The Task Registry defines:

* enabled Tasks;
* execution order;
* dependencies;
* formulas;
* input evidence;
* output objects;
* failure behavior.

A Task cannot appear through implementation-specific local configuration alone.

---

## 31. Task Dependency Graph

Epoch Tasks SHALL form a deterministic directed acyclic graph.

Example:

```text
Freeze Evidence
    ↓
Calculate Eligibility
    ↓
Apply Confirmed Penalties
    ↓
Calculate Reward Weights
    ↓
Allocate Reward Pools
    ↓
Generate Reward Mint Operations
```

A Task SHALL not execute before all mandatory dependencies complete.

---

## 32. Task Phases

Initial phases are:

`PRE_CLOSE`
`CLOSE`
`POST_CLOSE`
`DELAYED_FINALIZATION`
`NEXT_EPOCH_PREPARATION`

---

## 33. PRE_CLOSE

Used for deterministic preparation before the boundary.

Examples include:

* checking scheduled protocol activations;
* determining required transition fields;
* evaluating whether a safety pause blocks closing.

---

## 34. CLOSE

Executed as part of the Epoch transition.

Examples include:

* freezing evidence;
* freezing participant state;
* freezing Service state;
* calculating the Epoch randomness commitment;
* opening the next Epoch.

---

## 35. POST_CLOSE

Processes immutable evidence after closing.

Examples include:

* ordinary eligibility;
* Health;
* Service Maturity;
* preliminary reward weights;
* Reputation Events.

---

## 36. DELAYED_FINALIZATION

Used for results requiring:

* challenge windows;
* independent confirmation;
* additional evidence verification;
* penalty review.

---

## 37. NEXT_EPOCH_PREPARATION

Produces state required during the newly opened Epoch.

Examples include:

* Validator Set updates;
* Validation assignment slots;
* Registry challenge schedules;
* Maintenance Validation timing;
* Faucet allocation.

---

## 38. Task Input Immutability

A Task SHALL consume one exact committed Input Root.

Re-executing the same Task version with the same Input Root SHALL produce the same Output Root.

---

## 39. Task Result

Each Task produces:

```yaml
epoch_task_result:
  epoch_number:
  task_id:
  task_version:
  input_root:
  output_root:
  status:
  execution_height:
  error_code:
  previous_attempt_reference:
```

---

## 40. Task Status

Task status is one of:

`PENDING`
`READY`
`RUNNING`
`SUCCEEDED`
`FAILED_RETRYABLE`
`FAILED_BLOCKING`
`SKIPPED`
`SUPERSEDED`
`CORRECTED`

`RUNNING` may be an operational representation.

Canonical State Machine execution remains deterministic.

---

## 41. Mandatory and Optional Tasks

Tasks SHALL declare:

`MANDATORY`
`OPTIONAL`
`ADVISORY`

A failed Mandatory Task may block dependent canonical results.

A failed Optional Task does not block unrelated Epoch finalization.

An Advisory Task cannot directly alter economic state.

---

## 42. Core Mandatory Tasks

The initial core Task Set SHOULD include:

* `FREEZE_EPOCH_EVIDENCE`
* `FREEZE_PARTICIPANT_SNAPSHOT`
* `FREEZE_SERVICE_SNAPSHOT`
* `CALCULATE_EPOCH_RANDOMNESS`
* `CALCULATE_SERVICE_ELIGIBILITY`
* `CALCULATE_SERVICE_HEALTH`
* `UPDATE_SERVICE_MATURITY`
* `PROCESS_CONFIRMED_PENALTIES`
* `CALCULATE_RECYCLE_BACKLOG`
* `AUTHORIZE_EPOCH_REWARD_BUDGET`
* `CALCULATE_SERVICE_REWARD_WEIGHTS`
* `ALLOCATE_SERVICE_REWARDS`
* `GENERATE_REWARD_MINT_OPERATIONS`
* `CALCULATE_FAUCET_ALLOCATION`
* `UPDATE_REPUTATION_PROFILES`
* `PREPARE_VALIDATOR_SET_UPDATE`
* `COMMIT_EPOCH_RESULT`

---

## 43. Eligibility Calculation

Eligibility SHALL be derived from:

* the frozen Participant Snapshot;
* the frozen Service Snapshot;
* finalized Duty Proof;
* active protocol parameters;
* suspensions;
* Stake and Bond requirements;
* Health thresholds;
* Maturity requirements.

Eligibility is evaluated separately for each Service role.

---

## 44. No Retroactive Eligibility

A participant that becomes eligible after Epoch closing SHALL not receive rewards for the closed Epoch.

A participant that was eligible during the frozen snapshot remains evaluated using the frozen state, subject to later-confirmed misconduct rules.

---

## 45. Service Health Calculation

Health represents condition during the closed Epoch.

Health evidence MAY include:

* Availability;
* required Duty Proof;
* failure rate;
* synchronization state;
* report completion;
* protocol compliance.

Health calculation SHALL use protocol-verifiable evidence.

---

## 46. Service Maturity Update

Service Maturity SHALL update only after the Service's qualifying Epoch status is determined.

A Service SHALL not gain Maturity for an Epoch in which it:

* was ineligible;
* failed mandatory Duty Proof;
* remained suspended;
* failed the applicable minimum Health threshold.

---

## 47. Maturity Timing

Maturity earned for Epoch t becomes available for calculations beginning with a future declared Epoch.

It SHALL not increase its own reward retroactively for the same Epoch unless the active formula explicitly defines this behavior.

Recommended rule:

Maturity earned in Epoch t
affects rewards from Epoch t+1

---

## 48. Penalty Processing

Only confirmed protocol penalties SHALL affect canonical economic state.

Penalty processing SHALL:

* verify evidence;
* identify the target;
* determine the applicable rule version;
* calculate the deterministic amount;
* generate or apply `PENALTY_APPLY`;
* update recyclable-Q accounting where applicable.

---

## 49. Penalty Before Reward

When a confirmed penalty affects reward eligibility for the same Epoch, the Penalty Task SHALL execute before final reward allocation.

A participant SHALL not receive a reward that the active protocol explicitly forfeits.

---

## 50. Recyclable Q

The Epoch Engine SHALL calculate Q removed from active circulation through qualifying:

* Network Fees;
* penalties;
* forfeited Bonds;
* slashing;
* other recyclable mechanisms.

The result contributes to:

`RecycleBacklog`

according to ECO-0005.

---

## 51. No Double Recycling

One removed Q unit SHALL enter recyclable accounting at most once.

The Task SHALL track source Operations and consumed recycling references.

---

## 52. Epoch Reward Budget

The Epoch Reward Budget SHALL be authorized before individual rewards are calculated.

Conceptually:

```text
EpochRewardBudget
=
BaseEpochAuthorization
+
PermittedRecycleAllocation
```

The authorization is a maximum.

It is not a requirement to mint the entire amount.

---

## 53. Pool Allocation

The Epoch Engine SHALL allocate the authorized budget into protocol pools under ECO-0005.

Initial pools include:

* Consensus Service Pool
* Registry Service Pool
* Validation Activity Pool
* Faucet Pool

Pool allocation SHALL use the parameter version active for the reward Epoch.

---

## 54. Service Reward Weights

Service reward weights SHALL be calculated according to ECO-0004.

The Epoch Engine SHALL use:

* eligible Work Units;
* Maturity;
* Health;
* Duty Proof;
* Reliability;
* Known Control Groups;
* Diversity Factors;
* concentration limits.

---

## 55. Fixed Pool Principle

The number of eligible participants SHALL not increase the pool.

Participants divide the authorized pool according to qualifying contribution.

---

## 56. Unused Reward Authorization

Unused Base Emission authorization SHALL not be minted merely to exhaust the pool.

Unused recyclable allocation SHALL return to Recycle Backlog unless another active rule applies.

---

## 57. Reward Calculation Root

The Epoch Engine SHALL create:

```yaml
reward_calculation:
  reward_epoch:
  formula_version:
  pool_budgets:
  eligibility_root:
  work_unit_root:
  raw_weight_root:
  known_control_group_root:
  diversity_factor_root:
  concentration_cap_root:
  final_reward_root:
  unused_authorization:
  recycle_return:
```

---

## 58. Reward Finalization Delay

Rewards for work performed in Epoch t SHOULD finalize only after the applicable evidence and challenge period.

Recommended initial policy:

Work performed in Epoch t
is paid after Epoch t+1 closes

The exact delay is a versioned protocol parameter.

---

## 59. Reward Mint Generation

Final rewards create protocol-generated:

`REWARD_MINT`

operations.

A participant SHALL not generate its own valid reward Mint.

Every Mint SHALL reference:

* reward Epoch;
* authorized pool;
* recipient;
* amount;
* reward calculation root;
* formula version.

---

## 60. Faucet Calculation

The Epoch Engine SHALL calculate Faucet state using ECO-0005.

The calculation MAY include:

* Faucet Pool;
* eligible active Hypervisor count;
* prior carryover;
* per-Hypervisor claim amount;
* claim limits;
* remaining Faucet balance.

---

## 61. Active Hypervisor for Faucet

A Hypervisor is considered active for Faucet calculation only when it satisfies the applicable active-participant definition.

The initial definition SHOULD require at least one active Endpoint.

Registration without operational Endpoint activity SHALL not qualify automatically.

---

## 62. Faucet Carryover

Unused Faucet allocation MAY carry to the next Epoch according to ECO-0005.

Carryover SHALL be:

* explicit;
* bounded if a cap exists;
* included in canonical Faucet state;
* distinct from unminted Service Pool authorization.

---

## 63. Reputation Update

The Epoch Engine SHALL process Reputation Events under RFC-0041.

Processing includes:

* freezing eligible events;
* evidence validation;
* deduplication;
* correlated-incident grouping;
* role classification;
* score and Confidence updates;
* decay;
* flag updates;
* Profile Root commitment.

---

## 64. Reputation Finalization Order

Objective critical events MAY affect:

* eligibility;
* penalties;
* reward forfeiture;

before ordinary Reputation Profile calculation.

The numeric Reputation profile does not replace the underlying objective rule.

---

## 65. Validator Set Preparation

The Epoch Engine SHALL prepare Consensus Validator Set updates under ECO-0006.

The Task SHALL use:

* frozen Candidate eligibility;
* current Active Validator Set;
* Known Control Groups;
* retention rules;
* rotation fraction;
* deterministic randomness;
* suspension state;
* Consensus Reputation.

---

## 66. Validator Selection Randomness

Validator selection SHALL use a deterministic Epoch Seed.

The seed SHALL derive from finalized protocol data unavailable before the applicable commitment window closes.

A recommended construction is:

```text
EpochSeed(t+1)
=
HASH(
    network_id
    +
    epoch_number
    +
    closing_window_block_hash_root
    +
    closing_state_root
)
```

---

## 67. Randomness Use

Epoch randomness MAY be used for:

* Validator rotation;
* Validation assignment shuffling;
* Registry challenges;
* Maintenance Validation timing;
* randomized protocol sampling.

The same purpose SHALL use a domain-separated derived seed.

---

## 68. Randomness Domain Separation

Example:

```text
ValidatorSelectionSeed
=
HASH(EpochSeed + "validator-selection")
RegistryChallengeSeed
=
HASH(EpochSeed + "registry-challenges")
ValidationAssignmentSeed
=
HASH(EpochSeed + "validation-assignments")
```

---

## 69. Randomness Limitations

Block-derived randomness may be influenced within bounded limits by block proposers or liveness behavior.

The MVP MAY accept this limitation.

Future versions MAY introduce:

* threshold randomness;
* VRF commitments;
* distributed randomness beacons.

---

## 70. Validator Set Update

The resulting Validator Set SHALL be committed through:

`CONSENSUS_VALIDATOR_SET_UPDATE`

The update SHALL include:

* additions;
* removals;
* equal voting-power assignments;
* activation Epoch;
* selection seed;
* eligibility root;
* resulting set hash.

---

## 71. Cross-Epoch Sessions

A Session MAY remain active across Epoch boundaries.

Epoch closing SHALL not automatically terminate ordinary Sessions.

The Session remains bound to the policies accepted when it opened.

---

## 72. Session Evidence Attribution

Session-related evidence SHALL be attributed according to the finalized block containing the applicable event.

Examples:

* Session opened in Epoch 10;
* Usage Report finalized in Epoch 11;
* Settlement finalized in Epoch 12.

Each event belongs to its canonical Epoch.

---

## 73. No Mid-Session Repricing

An Epoch transition or economic parameter change SHALL not retroactively change:

* accepted Pricing Policy;
* Accounting Contract;
* Deposit;
* failure policy;
* maximum charge.

---

## 74. Pending Settlements

Pending Session Settlements continue across Epoch boundaries.

They SHALL not be discarded merely because a reward or Reputation window closed.

---

## 75. Validation Tasks

The Epoch Engine MAY execute Validation-related Tasks including:

* Freeze Validation Requests;
* Freeze Eligible Validation Reports;
* Calculate Validator Eligibility;
* Calculate Validation Escrow Units;
* Freeze Escrow Multipliers;
* Build Validator Slot List;
* Shuffle Validation Queues;
* Create Private Offers;
* Expire Offers;
* Reserve Collateral;
* Issue Concealed Session Credentials;
* Reassign Unaccepted Requests;
* Monitor Assignment Deadlines;
* Commit Validation Reports;
* Verify Validation Report Storage Receipts;
* Record Validation Report Storage Failures;
* Schedule Validation Report Availability Challenges;
* Evaluate Validation Report Availability;
* Apply Validation Report Custody Grace Periods;
* Generate Validation Report Retention Reputation Events;
* Validate Report Assignments;
* Detect Report Conflicts;
* Reveal Validator Identities;
* Settle Validation Sessions;
* Calculate Validation Rewards;
* Release Unused Collateral;
* Process Assignment Performance Bonds;
* Evaluate Critical Evidence;
* Derive Initial Certifications;
* Evaluate Maintenance Results;
* Schedule Conflict Resolution;
* Apply Degradation;
* Apply Revocation;
* Apply Expiration;
* Update Certification Report Availability State;
* Calculate Next Maintenance Windows;
* Generate Certification State Updates;
* Trigger Validation Bond Refunds;
* Trigger Validation Bond Forfeitures;
* Publish Certification Metrics.

Detailed Validation behavior belongs to its dedicated RFCs.

---

## 76. Registry and Marketplace Tasks

Registry- and Marketplace-related Epoch Tasks MAY include:

* Freeze Registry Eligibility;
* Finalize Closed Segment Manifests;
* Generate Registry Challenges;
* Collect Challenge Responses;
* Confirm Registry Failures;
* Calculate Registry Health;
* Calculate Registry Rewards;
* Commit Registry Evidence Root;
* Expire Endpoint Advertisements;
* Activate Scheduled Advertisements;
* Apply Advertisement Withdrawals;
* Apply Endpoint Suspensions;
* Detect Configuration Mismatches;
* Update Marketplace Freshness Roots;
* Publish Capability Supply Metrics;
* Publish Pricing Distribution Metrics;
* Publish Operator Diversity Metrics.

Detailed Registry behavior belongs to RFC-0061 and related Registry specifications.

Detailed Marketplace lifecycle behavior belongs to RFC-0049 and related Marketplace specifications.

---

## 77. Extended Protocol Tasks

The Epoch Engine MAY schedule Service Verification using:

* eligibility windows;
* Service age;
* random sampling;
* failure triggers;
* protocol upgrades;
* recovery state.

Service Verification results become future evidence.

Snapshot-related tasks MAY include:

* Select Snapshot Height;
* Generate Snapshot;
* Verify Snapshot Restoration;
* Commit Snapshot Metadata;
* Replicate Snapshot;
* Challenge Snapshot Availability;
* Update Recommended Snapshot;
* Calculate Registry Contribution;
* Prune Expired Snapshot Data.

Upgrade and emergency-recovery tasks MAY include:

* Freeze Upgrade Proposal State;
* Evaluate Upgrade Authorization;
* Collect Readiness Signals;
* Calculate Readiness Thresholds;
* Evaluate Registry and Snapshot Readiness;
* Postpone or Cancel Upgrade;
* Drain Incompatible Sessions;
* Generate Pre-Upgrade Snapshot;
* Activate Protocol Upgrade;
* Execute State Migration;
* Verify Post-Migration State Root;
* Open Upgrade Verification Period;
* Generate Post-Upgrade Snapshot;
* Expire Compatibility Window;
* Evaluate Emergency Actions;
* End Expired Emergency Actions.

Governance tasks MAY include:

* Freeze Governance Eligibility;
* Create Chamber Snapshots;
* Evaluate Proposal Sponsorship;
* Open Public Review;
* Open Governance Voting;
* Validate Governance Votes;
* Finalize Chamber Results;
* Calculate Economic Signals;
* Generate Authorization Certificates;
* Expire Proposal Authorizations;
* Process Council Updates;
* Evaluate Governance Mode Transition;
* Expire Emergency Actions;
* Publish Governance Metrics.

---

## 78. Task Failure Classes

Task failures are classified as:

* IMPLEMENTATION_FAILURE
* INVALID_INPUT
* MISSING_REQUIRED_EVIDENCE
* DEPENDENCY_FAILURE
* ARITHMETIC_INVARIANT_FAILURE
* STATE_INVARIANT_FAILURE
* TIMEOUT
* PROTOCOL_VERSION_MISMATCH

---

## 79. Deterministic Failure

A canonical Task failure SHALL itself be deterministic.

Every honest State Machine implementation SHALL derive the same failure result and error code from the same inputs.

---

## 80. Implementation Crash

A local process crash is not a canonical Task result.

The node SHALL:

* restart;
* replay canonical state;
* execute the same Task inputs;
* reproduce the expected result.

A local crash does not permit alternative Task output.

---

## 81. Retryable Task

A Task may be retried only when:

* its Failure Policy allows retry;
* the Input Root remains unchanged;
* Task version remains unchanged;
* retry count is bounded;
* output remains deterministic.

---

## 82. Missing External Evidence

Missing evidence after the cutoff SHALL normally produce:

* ineligibility;
* zero Work Units;
* an unresolved status;
* next-Epoch consideration;

rather than indefinite Task retry.

The network SHALL not wait forever for a participant who missed the deadline.

---

## 83. Blocking Failure

A failure is blocking when continuing would risk:

* Q supply violation;
* invalid reward Mint;
* incorrect Validator Set;
* inconsistent application state;
* duplicate economic processing.

Dependent Tasks SHALL remain blocked.

Unrelated tasks MAY continue.

---

## 84. Epoch Finalization Delay

A blocking Task failure MAY place the closed Epoch into:

`FINALIZATION_DELAYED`

The next Epoch MAY remain operational if its ordinary execution does not depend on the missing result.

---

## 85. Maximum Finalization Backlog

The protocol SHOULD define a maximum number of non-finalized historical Epochs.

If backlog exceeds the threshold, the network MAY pause:

* Reward Mint;
* Faucet Claims;
* new assignments;
* affected Service updates;
* other dependent operations.

Ordinary Ledger safety SHALL take priority over maintaining the appearance that periodic accounting is perfectly cheerful.

---

## 86. Task Correction

A finalized Task result SHALL not be silently rewritten.

An error SHALL be corrected through:

* a correction Task;
* compensating Ledger Operations;
* State Repair;
* protocol upgrade.

The correction SHALL reference the original Task Result.

---

## 87. Challenge Window

Selected Task results MAY have a bounded challenge period.

Challengeable results MAY include:

* reward calculation;
* eligibility omission;
* duplicated evidence;
* incorrect group aggregation;
* arithmetic error;
* incorrect formula version.

---

## 88. Objective Challenges

A challenge SHALL identify an objective protocol error.

Examples include:

* finalized evidence omitted;
* evidence counted twice;
* wrong Service owner;
* wrong Stake state;
* incorrect arithmetic;
* invalid Task version;
* wrong concentration cap.

Subjective dissatisfaction with reward size is not an objective challenge.

---

## 89. Challenge Result

A successful challenge SHALL produce:

* corrected pending Task Result;
* or a later explicit correction operation when the original result already finalized.

A failed challenge SHALL not alter the result.

---

## 90. Epoch Result Manifest

Every finalized Epoch SHALL produce:

```yaml
epoch_result_manifest:
  epoch_number:
  start_height:
  closing_height:
  start_time:
  closing_time:
  protocol_version:
  parameter_version:
  task_set_version:
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
  next_epoch_reference:
  previous_epoch_result_hash:
```

---

## 91. Epoch Result Chain

Each Epoch Result Manifest SHALL reference the previous finalized Epoch Result.

This creates an auditable chain of periodic protocol state.

---

## 92. Epoch Result Commitment

The Epoch Result Manifest SHALL be committed through canonical Ledger state.

Large supporting evidence MAY remain in Registry.

The Ledger stores enough commitments to independently verify the result.

---

## 93. Epoch Finalization

An Epoch becomes FINALIZED when:

* all Mandatory Tasks succeed;
* required challenge periods close;
* correction requirements are resolved;
* Epoch Result Manifest is committed;
* dependent protocol outputs are authorized.

---

## 94. Genesis Epoch

Genesis SHALL define:

```yaml
genesis_epoch:
  epoch_number: 0
  start_height:
  start_time:
  scheduled_end_time:
  initial_parameter_version:
  initial_task_set_version:
  initial_protocol_version:
```

Genesis MAY provide explicit bootstrap exceptions.

---

## 95. Epoch Parameter Changes

Epoch parameters SHALL change only through:

* an authorized protocol update;
* a declared activation Epoch;
* deterministic migration rules where necessary.

A node-local configuration SHALL not change canonical Epoch behavior.

---

## 96. Task Set Upgrade

Adding, removing or changing a canonical Epoch Task requires a versioned Task Set update.

The update SHALL define:

* previous Task Set;
* new Task Set;
* activation Epoch;
* dependency changes;
* state migration if required;
* compatibility behavior;
* test vectors.

---

## 97. Emergency Pause

An authorized emergency mechanism MAY pause selected Epoch outputs.

Examples include:

* Reward Mint;
* Faucet Claims;
* Validator Set activation;
* Stake Release;
* one defective Task.

An emergency pause SHALL not silently change the closed evidence set.

---

## 98. Consensus Halt

During Consensus halt:

* no Epoch transition finalizes;
* the current Epoch remains open or closing according to last canonical state;
* no new Epoch reward budget is created;
* no synthetic Epoch results are generated;
* finalized historical Epochs remain unchanged.

---

## 99. Recovery After Halt

After Consensus recovery:

* the current Epoch closes normally at the next valid transition;
* delayed evidence follows the canonical cutoff;
* no wall-clock Epoch backfill occurs;
* next Epoch begins from the recovered canonical state.

---

## 100. State Sync

A State Sync Snapshot SHALL include enough Epoch state to resume:

* current Epoch;
* scheduled end;
* active Parameter Version;
* active Task Set;
* pending Task Results;
* finalized Epoch Result chain;
* reward and recycling state.

---

## 101. Registry Retention

Registry Services SHOULD retain:

* Epoch transition objects;
* Task manifests;
* Task results;
* evidence roots;
* reward calculations;
* challenge records;
* corrections;
* Epoch Result Manifests.

---

## 102. Observability

The network SHALL expose:

* current Epoch number;
* start and scheduled end;
* current state;
* closing delay;
* pending Tasks;
* failed Tasks;
* finalization backlog;
* active parameter versions;
* reward-calculation status;
* next Validator Set status.

---

## 103. Epoch Metrics

The network SHOULD publish:

* actual Epoch duration;
* closing delay;
* Task execution delay;
* Task failure count;
* reward finalization delay;
* challenge count;
* correction count;
* unminted authorization;
* Recycle Backlog;
* Service eligibility counts;
* Validator rotation;
* Reputation event volume.

---

## 104. Conformance

State Machine implementations SHALL pass conformance tests covering:

* Epoch boundary calculation;
* late Consensus recovery;
* no backfilled Epochs;
* evidence cutoff;
* Participant and Service snapshots;
* Task dependency ordering;
* deterministic failure;
* reward authorization;
* unused pool handling;
* randomness derivation;
* Validator Set preparation;
* challenge processing;
* cross-Epoch Sessions;
* Task Set upgrade;
* Epoch Result commitment.

---

## 105. Test Vectors

The project SHOULD publish deterministic test vectors for:

* normal Epoch close;
* delayed close;
* Consensus halt;
* late evidence;
* duplicate evidence;
* failed Mandatory Task;
* reward rounding;
* Recycle Backlog;
* zero eligible participants;
* insufficient Validator candidates;
* challenge correction;
* task-version migration.

---

## 106. Initial Protocol Parameters

The following SHALL be versioned:

* EpochDuration
* EpochFinalizationLag
* RewardFinalizationDelay
* MaximumEpochBacklog
* ChallengeWindow
* TaskRetryLimit
* ClosingWindowSize
* RandomnessAlgorithm
* FaucetCarryoverPolicy
* ParameterActivationDelay
* TaskSetVersion

---

## 107. MVP Requirements

The MVP SHALL implement:

* canonical 24-hour Epoch scheduling;
* no wall-clock-only transitions;
* no automatic Epoch backfill;
* Epoch lifecycle states;
* `EPOCH_TRANSITION`;
* frozen evidence root;
* Participant Snapshot;
* Service Snapshot;
* versioned Parameter Snapshot;
* versioned Task Registry;
* Task dependency graph;
* deterministic Task Results;
* eligibility calculation;
* Service Health;
* Service Maturity;
* penalty processing;
* recyclable-Q accounting;
* reward-budget authorization;
* reward-pool allocation;
* reward calculations;
* Faucet state;
* Reputation updates;
* Validator Set preparation;
* Registry challenge, failure, reward and Marketplace lifecycle tasks, including Advertisement expiration, scheduled activation, withdrawal application, Endpoint suspension, freshness roots and Marketplace metrics;
* Snapshot selection, generation and metadata tasks;
* Validation assignment, report and settlement tasks;
* Certification derivation and maintenance tasks;
* upgrade authorization, readiness and activation tasks;
* governance snapshot, voting-finalization and authorization tasks;
* delayed result processing;
* challenge windows;
* Epoch Result Manifest;
* cross-Epoch Session support;
* deterministic fixed-point arithmetic.

---

## 108. Deferred Features

The MVP MAY postpone:

* threshold randomness beacon;
* VRF-based assignment randomness;
* parallel Task execution optimizations;
* zero-knowledge Task proofs;
* outsourced Task computation;
* adaptive Epoch duration;
* Capability-specific sub-Epochs;
* automatic economic parameter tuning;
* real-time reward streaming;
* cross-network Epoch coordination.

---

## 109. Economic Invariants

```text
Epoch Reward Mint
≤
Authorized Epoch Reward Budget

Pool Rewards
≤
Authorized Pool Budget

Unused Base Authorization
Is Not Minted Automatically

One Recyclable Q Unit
Is Counted At Most Once

No Epoch Backfill
Creates Additional Emission

Closed-Epoch Formulas
Use the Version Active for That Epoch
```

---

## 110. Task Invariants

* Every canonical Task is versioned.
* Every Task uses one exact Input Root.
* Task dependencies are acyclic.
* Same input and version produce the same output.
* Local process failure does not change canonical results.
* Missing late evidence does not reopen a closed Epoch.
* Failed Tasks do not silently produce partial economic state.
* Finalized Task errors are corrected explicitly.

---

## 111. Epoch Invariants

* Epoch numbers increase monotonically.
* One finalized transition closes one Epoch and opens one next Epoch.
* One block belongs to one Epoch.
* Epoch closing requires canonical consensus.
* Consensus halt does not generate synthetic Epochs.
* Next Epoch may open while previous results are processed.
* Cross-Epoch Sessions preserve their original contracts.
* Every finalized Epoch has one canonical Result Manifest.

---

## 112. Security Invariants

* Local clocks do not independently close Epochs.
* Block proposers do not choose reward formulas.
* Participants do not choose their own eligibility.
* Participants do not generate their own Reward Mint.
* Pending mempool data does not count as finalized evidence.
* Identity changes after the cutoff do not alter the frozen snapshot.
* Task retries do not change inputs.
* Randomness uses domain separation.
* A failed reward Task cannot exceed supply authorization.
* Emergency pauses do not rewrite frozen evidence.

---

## 113. Design Invariants

* Epochs coordinate periodic work but do not replace Consensus.
* Epoch transitions are deterministic Ledger state transitions.
* Work is measured in the Epoch in which its evidence finalizes.
* Epoch processing is pipelined to avoid stopping ordinary network operation.
* Protocol parameters remain fixed within one Epoch calculation.
* Service rewards depend on proven work rather than registration.
* Economic results are bounded before individual allocation.
* Closed history remains auditable.
* Periodic protocol work is extensible through a versioned Task Registry.

Комментарий

Что я смог подтвердить по истории

Документ действительно существовал под названием RFC-0048 - Epoch Engine. Его основная роль была именно такой:

финализированная история
→ заморозка данных эпохи
→ детерминированные задачи
→ расчёт результатов
→ переход к следующей эпохе

Также последующие RFC явно полагались на него как на место, где должны исполняться:

* reward calculations;
* Validator Set updates;
* Registry checks;
* Validation scheduling;
* Reputation updates;
* Snapshot tasks;
* protocol-upgrade tasks.

Самое важное решение в реконструкции

Я зафиксировал, что Epoch не создаются задним числом после Consensus halt.

Без этого при трёхдневной остановке сеть могла бы после восстановления создать три бюджета по 5000Q за эпохи, в которых никто ничего не обслуживал:

Consensus остановлен 3 дня
→ три фиктивных эпохи
→ 15 000Q разрешённой эмиссии

Такой календарь был бы весьма щедр к отсутствующей инфраструктуре.

Правильнее:

одна затянувшаяся эпоха
→ одно закрытие
→ один бюджет

Почему следующий Epoch открывается до завершения всех расчётов

Если сначала завершать:

* Reputation;
* все challenges;
* Validation Reports;
* Registry failures;
* rewards;

и только потом открывать новый Epoch, сеть будет регулярно останавливаться на бухгалтерское обслуживание.

Поэтому используется pipeline:

Epoch 10 закрыта
Epoch 11 сразу открыта
результаты Epoch 10 считаются в фоне канонических задач

"В фоне" здесь не означает вне блокчейна. Результаты всё равно детерминированно фиксируются Ledger, просто обычная работа сети не обязана ждать.

Почему rewards могут приходить с задержкой

В ECO-0004 мы позже закрепили:

работа в Epoch t
→ выплата после закрытия Epoch t+1

Это нужно, чтобы успеть проверить:

* дублированные доказательства;
* penalties;
* Known Control Groups;
* report fabrication;
* objective challenges.

Мгновенная награда удобнее, но потом приходится отдельно выцарапывать Q обратно у участника, который уже успел вдохновенно их потратить.

Что теперь нужно добавить в RFC-0048 v0.2

После базового RFC мы написали документы, которые добавили новые Epoch Tasks.

Из RFC-0061

Finalize Registry Segment Manifests
Generate Registry Challenges
Confirm Registry Failures
Calculate Registry Completeness

Из RFC-0062

Select Snapshot Height
Generate Snapshot
Commit Snapshot Metadata
Challenge Snapshot Availability
Select Recommended Snapshot

Из RFC-0064

Calculate Validation Escrow Units
Build Validator Slot List
Create Private Offers
Reserve Validation Collateral
Expire and Reassign Assignments
Settle Validation Sessions

Из RFC-0065

Detect Validation Report Conflicts
Derive Certification State
Schedule Maintenance Validation
Apply Certification Expiration
Trigger Validation Bond Refund or Forfeiture

Из RFC-0066

Evaluate Upgrade Authorization
Collect Readiness
Postpone or Activate Upgrade
Execute State Migration
Manage Emergency Actions

Из RFC-0067

Create Governance Chamber Snapshots
Open Governance Voting
Finalize Chamber Results
Generate Authorization Certificates
Process Governance Mode Transition

То есть базовый RFC-0048 существует и архитектурно остаётся верным, но теперь уже напрашивается RFC-0048 v0.2, в котором Task Registry будет полностью синхронизирован со всеми документами до RFC-0067.
