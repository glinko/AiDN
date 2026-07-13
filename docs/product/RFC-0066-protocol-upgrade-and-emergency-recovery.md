# RFC-0066 Protocol Upgrade and Emergency Recovery

Status: `Draft`

Version: `0.1`

Depends on:

- `ECO-0000 Economic Principles`
- `ECO-0004 Protocol Service Reward Distribution`
- `ECO-0005 Q Emission, Recycling and Epoch Reward Allocation`
- `ECO-0006 Consensus Economics and Validator Eligibility`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0037 Settlement Engine`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0042 Hypervisor Network Protocol`
- `RFC-0044 Session Protocol`
- `RFC-0047 CometBFT Consensus Integration`
- `RFC-0048 Epoch Engine`
- `RFC-0054 Capability Runtime Protocol`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0059 Ledger Operation Catalog`
- `RFC-0060 Session Failure, Recovery and Forced Settlement`
- `RFC-0061 Registry Replication Protocol`
- `RFC-0062 Snapshot and State Sync Protocol`
- `RFC-0064 Validation Assignment, Concealed Session and Escrow Protocol`
- `RFC-0065 Endpoint Certification Derivation and Lifecycle Protocol`

## 1. Purpose

This document defines how AiDN performs:

- planned protocol upgrades;
- consensus-critical software upgrades;
- protocol-parameter changes;
- Ledger Operation version changes;
- application-state schema migrations;
- compatibility transitions;
- Validator readiness signaling;
- upgrade activation;
- upgrade postponement and cancellation;
- emergency protocol pauses;
- emergency software recovery;
- deterministic state repair;
- recovery from failed migrations;
- recovery from prolonged consensus halt;
- explicit network continuity changes.

The protocol SHALL distinguish between:

- changing software;
- changing protocol rules;
- migrating canonical state;
- repairing a protocol defect;
- rewriting finalized history.

Finalized history SHALL not be rewritten through ordinary upgrade procedures.

## 2. Core Principle

Protocol upgrades are forward state transitions.

They SHALL NOT silently reinterpret or modify previously finalized Ledger history.

A planned upgrade follows:

```text
Proposal
    ->
Review
    ->
Authorization
    ->
Scheduling
    ->
Readiness
    ->
Activation
    ->
Verification
```

An emergency recovery follows:

```text
Incident Detection
    ->
Containment
    ->
Recovery Plan
    ->
Authorization
    ->
Deterministic Repair or Software Restart
    ->
Verification
    ->
Return to Normal Operation
```

## 3. Finality Boundary

Once a block is finalized through canonical Consensus:

- its operations remain finalized;
- its operation results remain finalized;
- its state transition remains part of canonical history;
- its block hash remains immutable;
- its evidence commitments remain immutable.

A later upgrade MAY:

- change future rules;
- correct future behavior;
- create compensating operations;
- deterministically repair current state;
- settle affected unresolved objects.

It SHALL NOT make a finalized block disappear.

## 4. Forward-Only Correction

When an already finalized transition produced an undesirable result because of a protocol defect, correction SHALL occur through a new auditable state transition.

Examples include:

- compensating Wallet transfer;
- deterministic Session settlement batch;
- corrected reward calculation;
- restored object state;
- corrected parameter activation;
- state migration.

The correction SHALL reference:

- the original affected objects;
- the defect class;
- the repair rule;
- the authorization;
- the resulting state changes.

## 5. Version Dimensions

AiDN SHALL track distinct version dimensions.

```yaml
version_state:
  protocol_version:
  application_version:
  operation_set_version:
  state_schema_version:
  consensus_adapter_version:
  registry_profile_version:
  runtime_protocol_version:
  network_revision:
```

These versions SHALL not be collapsed into one ambiguous software version.

## 6. Protocol Version

`protocol_version` defines network-visible protocol semantics, including:

- message rules;
- Session rules;
- Endpoint behavior;
- validation behavior;
- accounting semantics;
- economic invariants;
- compatibility requirements.

## 7. Application Version

`application_version` identifies the implementation of the AiDN deterministic State Machine.

Different implementations MAY use different software package versions while implementing the same protocol and application semantics.

## 8. Operation Set Version

`operation_set_version` identifies:

- supported Ledger Operation types;
- operation schemas;
- validation semantics;
- state transitions;
- error-code meanings.

Existing Operation semantics SHALL not change without an explicit version transition.

## 9. State Schema Version

`state_schema_version` identifies the logical layout of canonical application state.

A schema change MAY require deterministic migration.

Physical database layout does not by itself define the State Schema Version.

## 10. Consensus Adapter Version

`consensus_adapter_version` identifies the interface between:

- CometBFT;
- AiDN application state;
- Validator Set updates;
- evidence handling;
- block proposal and execution.

A Consensus Adapter update MAY be consensus-critical.

## 11. Network Revision

`network_revision` identifies an explicit continuity branch of the AiDN network.

Ordinary upgrades do not change Network Revision.

Network Revision changes only when the network must continue from a finalized checkpoint without ordinary authorization from the previous active consensus process.

A Network Revision change is an explicit continuity event and may create a competing network branch.

## 12. Upgrade Classes

The protocol defines:

- `IMPLEMENTATION_UPDATE`
- `COMPATIBLE_PROTOCOL_EXTENSION`
- `PARAMETER_UPDATE`
- `OPERATION_SET_UPGRADE`
- `STATE_SCHEMA_MIGRATION`
- `CONSENSUS_CRITICAL_UPGRADE`
- `EMERGENCY_PATCH`
- `NETWORK_REVISION_RECOVERY`

## 13. Implementation Update

An Implementation Update changes software without changing canonical protocol behavior.

Examples include:

- performance improvements;
- memory optimizations;
- logging changes;
- database-driver updates;
- local UI changes;
- non-consensus bug fixes.

It does not require a protocol activation when it preserves identical deterministic results.

## 14. Compatible Protocol Extension

A Compatible Protocol Extension adds optional behavior without invalidating existing compliant nodes.

Examples include:

- optional message fields;
- new diagnostic messages;
- additional Registry query methods;
- new Runtime transport support.

Unknown optional fields SHALL remain safely ignorable.

## 15. Parameter Update

A Parameter Update changes versioned protocol parameters.

Examples include:

- reward thresholds;
- Stake requirements;
- timeout limits;
- Validator Set target size;
- Snapshot frequency;
- Certification validity;
- Faucet limits.

Parameter updates SHALL activate at a declared Epoch.

## 16. Operation Set Upgrade

An Operation Set Upgrade adds or changes Ledger Operations.

It SHALL define:

- new operation schemas;
- authorization rules;
- validation rules;
- state transitions;
- error codes;
- replay protection;
- compatibility behavior;
- activation Epoch.

## 17. State Schema Migration

A State Schema Migration changes canonical application-state representation or semantics.

It SHALL include:

- source schema version;
- target schema version;
- migration algorithm;
- migration code hash;
- migration test vectors;
- preconditions;
- expected invariants;
- failure handling;
- activation point.

## 18. Consensus-Critical Upgrade

A Consensus-Critical Upgrade may change:

- State Machine execution;
- block validity;
- Validator Set interpretation;
- evidence handling;
- application-state hashing;
- consensus adapter behavior;
- deterministic arithmetic.

All active Validators SHALL use compatible semantics at activation.

## 19. Emergency Patch

An Emergency Patch addresses an urgent defect while preserving the current Network Revision.

It MAY use shortened review and activation periods.

It SHALL still define:

- exact defect;
- affected versions;
- deterministic behavior;
- activation conditions;
- state impact;
- recovery procedure.

## 20. Network Revision Recovery

Network Revision Recovery is used only when ordinary canonical upgrade finalization cannot be safely completed.

Examples include:

- permanent loss of sufficient Validator voting power;
- irrecoverable Validator Set corruption;
- consensus-critical defect preventing all block finalization;
- loss of required signing infrastructure;
- incompatible network split with no canonical recovery path.

This procedure is equivalent to an explicit hard-fork continuity decision.

Marketplace activity is revision-scoped.

An active Marketplace offer or Advertisement from the previous Network Revision SHALL be republished under the new Network Revision, or explicitly migrated through a defined protocol migration path, before it may open new Sessions.

Old-revision Advertisements remain historical objects and SHALL NOT automatically regain active status on the recovery branch.

## 21. Upgrade Proposal

Every protocol-changing upgrade SHALL begin with an Upgrade Proposal.

```yaml
upgrade_proposal:
  proposal_id:
  proposal_version:
  upgrade_class:
  title:
  rationale:
  affected_components:
  security_impact:
  economic_impact:
  current_versions:
  target_versions:
  compatibility_window:
  proposed_activation_epoch:
  minimum_activation_delay:
  expiration_epoch:
  release_manifest_hash:
  migration_manifest_hash:
  test_vector_root:
  source_reference:
  documentation_reference:
  authorization_policy:
  proposer_identity:
  proposer_signature:
```

## 22. Proposal Identity

`proposal_id` SHALL be derived from the canonical proposal content.

A material proposal change creates a new Proposal ID or Proposal Version.

Signatures approving an older version SHALL not approve later modified content.

## 23. Release Manifest

Every protocol-changing release SHALL have a Release Manifest.

```yaml
release_manifest:
  release_id:
  proposal_id:
  protocol_version:
  application_version:
  operation_set_version:
  state_schema_version:
  consensus_adapter_version:
  source_commit:
  source_tree_hash:
  build_instructions_hash:
  release_artifacts:
  artifact_hashes:
  supported_platforms:
  configuration_schema_hash:
  compatibility_matrix:
  known_limitations:
  security_notes:
  operator_runbook_hash:
  publisher_signatures:
```

## 24. Artifact Verification

Operators SHALL verify release artifacts using cryptographic hashes.

Protocol activation SHALL not depend on downloading an unsigned binary from one server.

The project SHOULD support:

- signed source releases;
- reproducible builds;
- multiple artifact mirrors;
- independent build verification;
- source-to-binary provenance.

## 25. Reproducible Builds

Consensus software SHOULD support reproducible builds where practical.

A production-like release SHOULD be independently rebuilt by multiple parties.

A binary hash being signed by one maintainer proves only that the maintainer signed that binary.

## 26. Migration Manifest

A State Schema Migration SHALL include:

```yaml
migration_manifest:
  migration_id:
  proposal_id:
  source_state_schema:
  target_state_schema:
  migration_code_hash:
  migration_entrypoint:
  expected_inputs:
  generated_outputs:
  preserved_invariants:
  modified_namespaces:
  prohibited_changes:
  test_state_roots:
  test_result_roots:
  maximum_execution_bounds:
  failure_behavior:
```

## 27. Deterministic Migration

Every Validator SHALL derive the same post-migration state from the same pre-migration state.

Migration SHALL NOT depend on:

- local wall-clock time;
- nondeterministic iteration order;
- external API;
- local filesystem contents;
- random source not committed by protocol;
- locale;
- floating-point behavior;
- operator input.

## 28. Migration State Root

At activation:

```text
PreMigrationStateRoot
    ->
Deterministic Migration
    ->
PostMigrationStateRoot
```

Every honest node SHALL calculate the same Post-Migration State Root.

The result SHALL be committed in canonical Ledger state.

## 29. Upgrade Authorization Policy

Every network SHALL declare one active Upgrade Authorization Policy.

Supported policy classes MAY include:

- `BOOTSTRAP_THRESHOLD_AUTHORITY`
- `CONSENSUS_SUPERMAJORITY`
- `GOVERNANCE_DECISION`
- `COMBINED_AUTHORIZATION`

The active authorization policy SHALL produce or require a governance-grade Authorization Certificate where governance is available under `RFC-0067`.

Bootstrap and recovery exceptions SHALL remain explicit.

This document defines how an authorized decision becomes a deterministic protocol transition.

## 30. Bootstrap Threshold Authority

Early testnets MAY use a threshold set of Upgrade Authorities.

Example:

`3-of-5 Upgrade Authority signatures`

A single administrative key SHOULD NOT authorize consensus-critical upgrades.

Bootstrap authority SHALL be:

- declared in Genesis;
- publicly visible;
- replaceable through a versioned upgrade;
- unsuitable as an unacknowledged permanent governance mechanism.

## 31. Consensus Supermajority Authorization

A network MAY require authorization from more than two-thirds of current active voting power.

Consensus authorization SHALL be distinct from ordinary block inclusion.

The authorization message SHALL bind to the exact Proposal ID and version.

## 32. Combined Authorization

Production-like networks SHOULD consider independent gates.

Example:

```text
Governance or Upgrade Authority approval
+
Active Validator supermajority authorization
+
Readiness threshold
```

Approval determines that the upgrade is permitted.

Readiness determines that activation is operationally safe.

## 33. Authorization Is Not Readiness

A Validator may approve an upgrade proposal but not yet be technically ready to run it.

Likewise, a Validator may install software without agreeing that the upgrade should activate.

The protocol SHALL maintain separate records for:

`UPGRADE_APPROVAL`

`UPGRADE_READINESS`

## 34. Proposal Lifecycle

An Upgrade Proposal follows:

```text
DRAFT
    ->
PUBLISHED
    ->
REVIEWING
    ->
AUTHORIZED
    ->
SCHEDULED
    ->
READY
    ->
ACTIVATING
    ->
ACTIVE
```

Alternative states include:

- `REJECTED`
- `EXPIRED`
- `POSTPONED`
- `CANCELLED`
- `ACTIVATION_FAILED`
- `SUPERSEDED`

## 35. Review Period

A planned consensus-critical upgrade SHALL have a minimum public review period.

Recommended initial values:

| Upgrade class | Minimum review |
| --- | --- |
| Compatible extension | `3 Epochs` |
| Parameter update | `7 Epochs` |
| Operation Set upgrade | `14 Epochs` |
| State migration | `14 Epochs` |
| Consensus-critical upgrade | `21 Epochs` |
| Emergency patch | protocol-dependent |

These values are configurable.

## 36. Security Review

Consensus-critical upgrades SHOULD include:

- architecture review;
- deterministic execution review;
- economic review;
- security analysis;
- migration review;
- failure-mode analysis;
- rollback and recovery runbook;
- testnet execution;
- shadow replay results.

## 37. Test Vectors

Every consensus-critical upgrade SHALL provide deterministic test vectors.

Test vectors SHOULD include:

- valid operations;
- invalid operations;
- edge cases;
- migration inputs;
- migration outputs;
- expected state roots;
- error codes;
- replay-protection cases;
- arithmetic boundary cases.

## 38. Shadow Replay

Before activation, independent nodes SHOULD replay historical or current blocks using the new software.

Shadow replay compares:

- operation results;
- state transitions;
- state roots;
- emitted events;
- reward calculations;
- migration behavior.

Unexpected divergence SHALL block readiness.

## 39. Testnet Activation

A production-like consensus upgrade SHOULD activate on a test network before production activation.

Testnet success is evidence, not proof of safety.

The production network SHALL still apply its own authorization and readiness requirements.

## 40. Scheduled Activation

An authorized proposal SHALL specify:

```yaml
activation_schedule:
  activation_epoch:
  activation_block_condition:
  minimum_readiness_threshold:
  maximum_postponements:
  postponement_interval:
  compatibility_end_epoch:
```

Epoch activation is preferred for broad protocol upgrades.

## 41. No Retroactive Activation

An upgrade SHALL not activate at an Epoch that has already begun unless it is an explicitly authorized emergency action.

Ordinary upgrades SHALL be scheduled for a future Epoch.

## 42. Validator Readiness Signal

Each Consensus Validator MAY publish:

```yaml
upgrade_readiness:
  proposal_id:
  validator_service_id:
  installed_release_id:
  verified_artifact_hash:
  migration_test_result:
  current_sync_status:
  ready_for_activation:
  reported_at_height:
  signature:
```

## 43. Readiness Validity

A readiness signal is valid only when:

- Validator remains active or eligible;
- release hash matches the proposal;
- required self-tests passed;
- protocol version is compatible;
- the signal has not expired;
- no later withdrawal exists.

## 44. Readiness Withdrawal

A Validator MAY withdraw readiness before activation.

Reasons MAY include:

- discovered defect;
- failed migration test;
- infrastructure failure;
- incompatible dependency;
- security concern.

Withdrawal SHALL be visible.

## 45. Consensus Readiness Threshold

A consensus-critical upgrade SHALL not activate unless readiness exceeds the safety threshold.

Hard minimum:

`Ready Voting Power > 2/3`

Recommended operational threshold:

`Ready Voting Power >= 80%`

The higher threshold provides margin for failure during activation.

## 46. Registry Readiness

An upgrade affecting Registry formats or required profiles SHOULD require:

- compatible Full Registry Providers;
- Snapshot availability;
- new object-schema support;
- multiple independent provider groups.

Recommended target:

`At least 3 independent Full Registry groups ready`

## 47. Snapshot Readiness

Before a State Migration or Consensus-Critical Upgrade, the network SHOULD have:

- a stable pre-upgrade Snapshot;
- multiple Snapshot Providers;
- verified restoration tooling;
- migration rehearsal;
- sufficient post-upgrade storage capacity.

## 48. Runtime and Hypervisor Readiness

Upgrades affecting Endpoint or Runtime contracts MAY collect readiness from:

- Hypervisors;
- Capability Runtimes;
- Registry Services;
- Validators.

Only consensus readiness controls block validity.

Other readiness metrics determine compatibility risk and operator warnings.

## 49. Automatic Postponement

If the readiness threshold is not satisfied at the activation deadline:

```text
Upgrade
->
POSTPONED
```

It SHALL NOT partially activate.

A postponed upgrade MAY move to the next configured activation window.

## 50. Maximum Postponements

An Upgrade Proposal SHALL define a maximum number of automatic postponements.

After the limit:

- the proposal expires; or
- requires explicit rescheduling authorization.

This prevents abandoned upgrades from waiting indefinitely.

## 51. Upgrade Cancellation

A scheduled upgrade MAY be cancelled before activation when:

- a critical defect is found;
- readiness collapses;
- security review fails;
- migration cannot reproduce expected results;
- the proposal is superseded.

Cancellation SHALL require the active Authorization Policy.

## 52. Activation Boundary

At activation, all Consensus Validators SHALL evaluate the same:

- Proposal ID;
- release version;
- protocol parameters;
- migration code;
- activation height;
- pre-migration state root.

A node running incompatible rules SHALL not participate safely in consensus.

## 53. Activation Block

The first block under the new protocol SHALL include or reference:

```yaml
protocol_upgrade_activate:
  proposal_id:
  activation_epoch:
  activation_height:
  previous_protocol_version:
  new_protocol_version:
  previous_state_schema:
  new_state_schema:
  pre_upgrade_state_root:
  post_migration_state_root:
  release_manifest_hash:
  migration_manifest_hash:
  readiness_root:
```

## 54. Atomic Activation

Protocol activation SHALL be atomic from the State Machine perspective.

It SHALL not leave some namespaces migrated and others unmigrated.

Activation either:

- completes and produces the expected post-migration state; or
- fails before a new canonical block is finalized.

## 55. Migration Failure Before Finality

If nodes cannot agree on the activation transition before finalization:

- the activation block does not finalize;
- consensus may halt;
- operators SHALL inspect divergence;
- the upgrade MAY be cancelled or replaced;
- nodes MAY return to the previous compatible software at the same finalized height.

No finalized history is rolled back.

## 56. Migration Failure After Finality

If the activation block finalized, the migration is canonical.

A later discovered defect SHALL be corrected through:

- Emergency Patch;
- deterministic State Repair;
- compensating operations;
- later migration.

The network SHALL not erase the finalized activation block.

## 57. Software Rollback

A binary rollback is permitted only when the older software:

- supports the active Protocol Version;
- supports the active State Schema;
- reproduces the current canonical State Root;
- does not reinterpret finalized operations.

Otherwise, the correct response is a forward patch, not a rollback.

## 58. Compatibility Window

An upgrade MAY define a bounded Compatibility Window.

During the window, nodes MAY support:

- old and new message versions;
- old Session contracts;
- old Registry object reads;
- old Runtime versions;
- old operation decoding where safe.

Consensus execution SHALL still use exactly one active rule set at each height.

## 59. Existing Sessions

Sessions opened before activation SHALL remain bound to their accepted:

- Pricing Policy;
- Accounting Contract;
- Session Policy;
- Endpoint Configuration Hash;
- protocol interpretation.

An upgrade SHALL not retroactively change their economic contract.

## 60. Session Drain Requirement

If the new protocol cannot safely preserve existing Sessions:

- new Session creation SHALL stop before activation;
- existing Sessions SHALL enter graceful drain;
- unresolved Sessions SHALL be settled under the old rules;
- activation SHALL wait for the declared drain condition.

## 61. Session Migration

A future protocol MAY migrate active Sessions only when:

- migration behavior is deterministic;
- both parties' accepted rights are preserved;
- Deposit conservation holds;
- accounting history remains intact;
- Forced Settlement remains available.

The MVP SHOULD prefer draining over complex Session migration.

## 62. Pending Ledger Operations

At activation:

- operations valid under the old version but not finalized MAY expire;
- clients SHALL resubmit using the new version;
- sequence handling SHALL prevent replay;
- no operation receives validity merely because it entered an old mempool.

## 63. Endpoint Compatibility

An upgrade MAY place Endpoints into:

- `ACTIVE`
- `COMPATIBILITY_MODE`
- `REVALIDATION_REQUIRED`
- `INCOMPATIBLE`

depending on:

- Runtime Protocol;
- Capability schema;
- Accounting Contract;
- Session behavior;
- Certification policy.

## 64. Certification Across Upgrade

Certification SHALL not automatically expire after every protocol upgrade.

It MAY remain valid when Endpoint behavior is unchanged.

A material validation-policy or execution-contract change MAY cause:

```text
CERTIFIED
->
REVALIDATION_REQUIRED
```

Migration behavior SHALL be explicit.

## 65. Reward Formula Upgrades

Economic formula changes SHALL activate only for future Epochs.

Rewards for closed Epochs SHALL use the formula version active for those Epochs.

Finalized rewards SHALL not be silently recalculated.

## 66. Stake Requirement Upgrades

An increase in required Stake SHALL include:

- announcement period;
- top-up deadline;
- effective Epoch;
- behavior for deficient participants;
- unbonding implications.

A parameter increase SHALL not immediately confiscate existing Stake.

## 67. Emergency Incident Classes

The protocol defines:

- `CONSENSUS_SAFETY_INCIDENT`
- `CONSENSUS_LIVENESS_INCIDENT`
- `STATE_MACHINE_DEFECT`
- `ECONOMIC_INVARIANT_DEFECT`
- `SECURITY_KEY_INCIDENT`
- `MIGRATION_FAILURE`
- `REGISTRY_INTEGRITY_INCIDENT`
- `SESSION_SETTLEMENT_DEFECT`
- `REWARD_MINT_DEFECT`
- `PROTOCOL_SUPPLY_CHAIN_INCIDENT`

## 68. Emergency Priorities

Emergency response SHALL prioritize:

1. preserving finalized state;
2. preventing new economic damage;
3. preventing conflicting finality;
4. preserving evidence;
5. restoring deterministic operation;
6. minimizing service disruption.

Convenience SHALL not override safety.

## 69. Emergency Action Types

Initial emergency actions include:

- `PAUSE_NEW_SESSIONS`
- `PAUSE_SESSION_DEPOSIT_EXTENSIONS`
- `PAUSE_ENDPOINT_PUBLICATION`
- `PAUSE_VALIDATION_ASSIGNMENTS`
- `PAUSE_REWARD_MINT`
- `PAUSE_FAUCET_CLAIMS`
- `PAUSE_STAKE_RELEASE`
- `PAUSE_PARAMETER_ACTIVATION`
- `PAUSE_PROTOCOL_UPGRADE`
- `PAUSE_SELECTED_OPERATION_TYPE`
- `REQUIRE_SAFE_MODE`

## 70. Scoped Emergency Action

An emergency action SHALL define:

```yaml
emergency_action:
  action_id:
  incident_id:
  action_type:
  affected_operation_types:
  affected_object_types:
  scope:
  start_condition:
  expiration_condition:
  maximum_duration:
  evidence_root:
  authorization_policy:
```

## 71. No Arbitrary Wallet Freeze

Emergency actions SHALL not provide unrestricted authority to freeze arbitrary Wallet balances.

Wallet or participant-specific restrictions SHALL use:

- objective evidence;
- existing suspension rules;
- applicable Penalty Operations;
- dedicated authorized state transitions.

A generic emergency switch is not a convenient confiscation API.

## 72. Automatic Safety Guard

The State Machine MAY contain predetermined automatic safety guards.

Examples include:

- reject Mint above authorized budget;
- reject negative balances;
- reject duplicate Settlement;
- reject invalid State Root;
- reject operation under paused type;
- stop upgrade activation when readiness is insufficient.

Automatic guards SHALL be defined before the incident.

## 73. Emergency Authorization

Emergency actions SHALL use the active Emergency Authorization Policy.

A production-like policy SHOULD require threshold authorization.

The threshold MAY be higher than ordinary upgrade approval.

## 74. Emergency Duration

Every emergency pause SHALL have:

- maximum duration;
- expiration behavior;
- review requirement;
- extension procedure.

An emergency pause SHALL not quietly become permanent protocol policy.

## 75. Emergency Extension

Extending an emergency action requires a new authorization.

The extension SHALL reference:

- original incident;
- remaining risk;
- recovery progress;
- new expiration.

## 76. Emergency Action During Working Consensus

When Consensus still finalizes blocks, emergency actions SHALL be recorded through canonical Ledger Operations.

All nodes derive the same paused behavior.

## 77. Emergency Action During Consensus Halt

When Consensus cannot finalize:

- no new canonical emergency operation can be created;
- operators MAY stop local services conservatively;
- no local pause becomes canonical state;
- recovery coordination occurs out of band;
- canonical changes resume only after consensus recovery or Network Revision Recovery.

## 78. Local Safe Mode

A node MAY enter Local Safe Mode without Ledger authorization.

Local Safe Mode MAY:

- stop proposing blocks;
- stop submitting new operations;
- stop accepting new Sessions;
- preserve evidence;
- maintain read-only service.

Local Safe Mode SHALL not modify canonical state.

## 79. Consensus Liveness Recovery

If consensus halts but the active Validator Set remains intact, recovery SHOULD use:

- the last finalized block;
- the same Network Revision;
- the same Validator Set;
- compatible fixed software;
- preserved consensus keys;
- no state rollback.

Validators restart from the last finalized height.

## 80. Consensus Safety Incident

If conflicting finality is suspected:

- Validators SHALL stop signing;
- nodes SHALL preserve conflicting evidence;
- operators SHALL identify the canonical safety status;
- no automated chain selection SHALL occur based only on Registry peer count;
- recovery may require explicit Network Revision decision.

## 81. Failed Upgrade Recovery

If a scheduled upgrade causes liveness failure before activation finality:

- return to the last finalized pre-upgrade state;
- run previous compatible software;
- cancel or supersede the upgrade;
- preserve failed activation evidence.

This does not roll back finalized state because the activation never finalized.

## 82. Emergency Software Patch

An Emergency Patch MAY activate with shortened delay when:

- current rules remain unsafe;
- the defect is well-scoped;
- deterministic behavior is documented;
- authorization threshold is satisfied;
- sufficient Validator readiness exists.

The patch SHALL still have a Proposal ID and Release Manifest.

## 83. State Repair

A State Repair is a deterministic canonical transition that corrects current state affected by a protocol defect.

A State Repair SHALL use a State Repair Manifest.

```yaml
state_repair_manifest:
  repair_id:
  incident_id:
  affected_state_root:
  affected_object_selector:
  repair_algorithm_hash:
  expected_invariants:
  supply_effect:
  authorization_reference:
  test_vector_root:
```

## 84. State Repair Restrictions

A State Repair SHALL NOT:

- alter unrelated Wallet balances;
- create undisclosed Q;
- erase audit history;
- delete misconduct evidence;
- bypass supply invariants;
- permit arbitrary operator choices;
- depend on local manual edits.

## 85. Supply Effect

Every State Repair SHALL declare one of:

- `NO_SUPPLY_CHANGE`
- `AUTHORIZED_COMPENSATING_MINT`
- `AUTHORIZED_REMOVAL`
- `BALANCE_REALLOCATION`

Any supply change SHALL reference the economic rule authorizing it.

A repair cannot label surprise inflation as "database maintenance".

## 86. Deterministic Object Selection

Affected objects SHALL be selected using deterministic predicates.

Examples:

- all Sessions with a specified defect version;
- all rewards generated by one invalid formula version;
- all operations within a finalized height range;
- all objects referencing one corrupted policy hash.

A human-maintained list MAY be used only when the exact list is committed and independently auditable.

## 87. Emergency Session Settlement Batch

A protocol defect affecting many Sessions MAY use a deterministic batch settlement.

The batch SHALL define:

- affected Session selector;
- accepted evidence baseline;
- Provider payment rule;
- Consumer refund rule;
- fee treatment;
- Deposit conservation;
- Reputation treatment.

The same rule SHALL apply to every matching Session.

## 88. Reward Repair

An invalid reward calculation MAY be repaired through:

- omitted reward Mint;
- compensating Mint;
- Penalty Operation;
- future reward offset.

The repair SHALL preserve:

- pool authorization;
- supply accounting;
- participant evidence;
- public audit history.

## 89. No Silent Database Editing

Operators SHALL NOT directly edit canonical databases to recover the network.

Manual database modification creates unverifiable state divergence.

Recovery SHALL use:

- verified Snapshot;
- deterministic migration;
- State Repair transition;
- canonical block replay;
- explicit Network Revision recovery.

## 90. Snapshot-Based Recovery

Emergency recovery SHOULD use `RFC-0062`.

A node MAY restore:

- the last stable pre-incident Snapshot;
- a verified post-repair Snapshot;
- a Snapshot corresponding to the last finalized height.

The node SHALL still reproduce the canonical State Root.

## 91. Registry-Based Evidence Recovery

Missing historical evidence MAY be restored through `RFC-0061`.

Registry recovery SHALL not independently alter current application state.

State-affecting restoration requires canonical commitments.

## 92. Unrecoverable Local State

If one node loses local state but the network remains healthy:

- the node is not a network emergency;
- it SHALL State Sync from canonical data;
- it SHALL not request a network rollback;
- it SHALL regain eligibility only after synchronization and verification.

## 93. Lost Consensus Quorum

If the network permanently loses enough Validator keys to finalize blocks, ordinary recovery may be impossible.

Examples include:

- more than one-third permanent loss causing liveness halt;
- catastrophic infrastructure loss;
- unrecoverable key destruction;
- operators abandoning the network.

The protocol cannot produce a canonical Validator Set update without canonical consensus.

## 94. Last-Set Recovery Signatures

Where possible, recovery SHOULD obtain signatures from more than two-thirds of the last finalized Validator voting power.

Such signatures MAY authorize:

- fixed software version;
- recovery checkpoint;
- replacement Validator Set;
- restart height.

If this threshold is available, ordinary Network Revision change may not be necessary.

## 95. Insufficient Last-Set Signatures

If sufficient last-set signatures cannot be obtained, there is no purely protocol-derived method to prove one recovery branch canonical.

Continuation requires an external trust decision.

This SHALL be represented as:

`NETWORK_REVISION_RECOVERY`

## 96. Recovery Manifest

Network Revision Recovery SHALL use:

```yaml
network_recovery_manifest:
  recovery_id:
  previous_network_revision:
  new_network_revision:
  previous_chain_id:
  recovery_chain_id:
  last_finalized_height:
  last_finalized_block_hash:
  last_finalized_state_root:
  last_validator_set_hash:
  new_validator_set:
  protocol_version:
  application_version:
  state_schema_version:
  recovery_rationale:
  incident_evidence_root:
  state_repair_reference:
  trusted_checkpoint:
  authorization_signatures:
  publication_time:
```

## 97. Recovery Chain Identity

A Network Revision Recovery SHALL bind the new network identity to:

- previous chain;
- last finalized block;
- previous State Root;
- new revision number;
- new recovery authority;
- new Validator Set.

Clients SHALL not confuse the recovery branch with an ordinary seamless upgrade.

## 98. Possible Network Split

Multiple valid-looking Recovery Manifests may appear.

The protocol cannot prevent social disagreement from producing multiple continuation networks.

Wallets, operators and clients SHALL select a Network Revision through a trusted checkpoint or declared governance decision.

The documentation SHALL describe this honestly rather than declaring that the preferred fork is canonical by emotional intensity.

## 99. Q Supply Across Recovery

A Network Revision Recovery SHALL begin from the last declared canonical State Root or an explicitly authorized deterministic repair.

It SHALL not independently reset Q balances or supply.

Any supply repair SHALL be separately declared and auditable.

## 100. Replay Protection Across Revisions

Every signed protocol object SHALL include or derive its domain from:

```text
network_id
+
chain_id
+
network_revision
```

An operation from an older Network Revision SHALL not be replayable on a newer revision unless explicitly migrated.

## 101. Session Handling Across Revision

Active Sessions at the recovery checkpoint SHALL be handled by a declared recovery rule.

Possible rules include:

- deterministic Forced Settlement;
- return unused Deposits;
- preserve accepted checkpoints;
- mark Sessions unrecoverable and batch-settle;
- resume only when both parties reconfirm.

The rule SHALL apply consistently.

Marketplace offers and Advertisements at the recovery checkpoint SHALL follow an equally explicit recovery rule.

They MAY remain queryable as historical objects, but they SHALL NOT authorize new Session opening on the new Network Revision until they are republished under that revision, or explicitly migrated through a defined protocol migration path.

## 102. Upgrade Verification Period

After activation, the network SHALL enter an Upgrade Verification Period.

During this period, nodes monitor:

- state-root agreement;
- consensus participation;
- operation rejection rate;
- Session failures;
- Registry compatibility;
- reward calculations;
- migration invariants;
- memory and storage behavior.

## 103. Verification Duration

Recommended initial duration:

`UpgradeVerificationPeriod = 2 Epochs`

A critical anomaly during this period MAY trigger an Emergency Patch or pause.

The upgrade remains active unless corrected forward.

## 104. Post-Upgrade Snapshot

After successful activation and stability verification, the network SHOULD produce a new Snapshot.

The Snapshot SHALL include:

- new Protocol Version;
- new State Schema Version;
- activation reference;
- verified State Root.

## 105. Upgrade Completion

An upgrade becomes `COMPLETED` when:

- activation finalized;
- State Root remained consistent;
- mandatory post-upgrade tasks completed;
- required Snapshot exists;
- critical verification alerts are resolved;
- compatibility transition is proceeding as scheduled.

## 106. Compatibility End

After the Compatibility Window:

- obsolete protocol messages MAY be rejected;
- unsupported operation versions SHALL be rejected;
- incompatible Runtimes MAY become unavailable;
- old Registry profiles MAY lose reward eligibility;
- old software SHOULD no longer participate.

## 107. Upgrade Observability

The network SHALL publish:

- active Proposal;
- proposal state;
- activation schedule;
- authorization signatures;
- Validator readiness;
- Registry readiness;
- release hashes;
- migration hashes;
- postponements;
- cancellations;
- active Protocol Version;
- active State Schema Version;
- current Network Revision.

## 108. Operator Warnings

Operators SHOULD receive warnings for:

- outdated software;
- incompatible Protocol Version;
- missing migration support;
- invalid release hash;
- insufficient disk space;
- failed shadow replay;
- impending activation;
- readiness withdrawal;
- emergency pause.

## 109. Client Behavior

Clients SHALL verify:

- chain identity;
- Network Revision;
- active Protocol Version;
- operation version;
- trusted checkpoint where applicable.

A client SHALL not silently follow a different recovery branch.

## 110. Ledger Operations

`RFC-0059` SHALL be extended with:

- `PROTOCOL_UPGRADE_PROPOSE`
- `PROTOCOL_UPGRADE_AUTHORIZE`
- `PROTOCOL_UPGRADE_SCHEDULE`
- `PROTOCOL_READINESS_SIGNAL`
- `PROTOCOL_READINESS_WITHDRAW`
- `PROTOCOL_UPGRADE_POSTPONE`
- `PROTOCOL_UPGRADE_CANCEL`
- `PROTOCOL_UPGRADE_ACTIVATE`
- `EMERGENCY_ACTION_AUTHORIZE`
- `EMERGENCY_ACTION_ACTIVATE`
- `EMERGENCY_ACTION_EXTEND`
- `EMERGENCY_ACTION_END`
- `STATE_REPAIR_COMMIT`
- `STATE_REPAIR_APPLY`
- `NETWORK_RECOVERY_MANIFEST_COMMIT`

## 111. PROTOCOL_UPGRADE_PROPOSE

Creates a canonical Upgrade Proposal record.

It does not authorize or schedule activation.

## 112. PROTOCOL_UPGRADE_AUTHORIZE

Records authorization under the active Upgrade Authorization Policy.

The operation SHALL bind to one exact Proposal ID and version.

## 113. PROTOCOL_UPGRADE_SCHEDULE

Schedules an authorized upgrade for a future Epoch.

It SHALL define readiness requirements and postponement behavior.

## 114. PROTOCOL_READINESS_SIGNAL

Records a Validator or Service readiness claim.

Readiness claims are signed and revocable before activation.

## 115. PROTOCOL_UPGRADE_ACTIVATE

Performs the deterministic activation transition.

No Wallet may independently submit an arbitrary activation operation.

## 116. EMERGENCY_ACTION_ACTIVATE

Activates one authorized, bounded emergency action.

It SHALL include scope and expiration.

## 117. STATE_REPAIR_APPLY

Applies a previously committed deterministic State Repair Manifest.

It SHALL verify:

- current affected State Root;
- Repair ID;
- algorithm version;
- invariants;
- authorization.

## 118. Epoch Integration

`RFC-0048` SHALL define tasks including:

- Freeze Upgrade Proposal State;
- Evaluate Upgrade Authorization;
- Collect Readiness Signals;
- Calculate Readiness Thresholds;
- Evaluate Registry and Snapshot Readiness;
- Postpone or Cancel Upgrade;
- Drain Incompatible Sessions;
- Generate Pre-Upgrade Snapshot;
- Activate Protocol Upgrade;
- Execute State Migration;
- Verify Post-Migration State Root;
- Open Upgrade Verification Period;
- Generate Post-Upgrade Snapshot;
- Expire Compatibility Window;
- Evaluate Emergency Actions;
- End Expired Emergency Actions.

## 119. Error Codes

The MVP SHALL define at least:

- `UPGRADE_PROPOSAL_NOT_FOUND`
- `UPGRADE_PROPOSAL_VERSION_MISMATCH`
- `UPGRADE_NOT_AUTHORIZED`
- `UPGRADE_ALREADY_SCHEDULED`
- `UPGRADE_ACTIVATION_TOO_EARLY`
- `UPGRADE_READINESS_INSUFFICIENT`
- `UPGRADE_RELEASE_HASH_MISMATCH`
- `UPGRADE_MIGRATION_HASH_MISMATCH`
- `UPGRADE_STATE_ROOT_MISMATCH`
- `UPGRADE_INCOMPATIBLE_STATE_SCHEMA`
- `UPGRADE_TEST_VECTOR_FAILURE`
- `UPGRADE_EXPIRED`
- `UPGRADE_CANCELLED`
- `UPGRADE_ACTIVATION_FAILED`
- `EMERGENCY_ACTION_UNAUTHORIZED`
- `EMERGENCY_ACTION_SCOPE_INVALID`
- `EMERGENCY_ACTION_EXPIRED`
- `EMERGENCY_ACTION_ALREADY_ACTIVE`
- `STATE_REPAIR_ROOT_MISMATCH`
- `STATE_REPAIR_INVARIANT_FAILURE`
- `STATE_REPAIR_SUPPLY_VIOLATION`
- `STATE_REPAIR_SELECTOR_INVALID`
- `NETWORK_REVISION_MISMATCH`
- `RECOVERY_MANIFEST_INVALID`
- `RECOVERY_CHECKPOINT_INVALID`
- `RECOVERY_AUTHORIZATION_INSUFFICIENT`

## 120. Idempotency

The following SHALL be idempotent:

- proposal publication;
- authorization submission;
- readiness signaling;
- readiness withdrawal;
- scheduling;
- postponement;
- cancellation;
- emergency action activation;
- State Repair application;
- Recovery Manifest publication.

A Proposal or Repair ID SHALL not execute twice.

## 121. Audit History

The Registry SHALL retain:

- all Upgrade Proposals;
- release manifests;
- migration manifests;
- authorization signatures;
- readiness signals;
- activation results;
- emergency actions;
- State Repair manifests;
- Recovery Manifests;
- post-incident reports.

Upgrade history SHALL remain publicly auditable.

## 122. Security Threats

The protocol SHALL account for:

- malicious release artifacts;
- compromised Upgrade Authority keys;
- Validator readiness spoofing;
- downgrade attacks;
- migration divergence;
- partial activation;
- supply-changing repair abuse;
- emergency-pause abuse;
- malicious Recovery Manifest;
- long-range recovery forks;
- stale checkpoint use;
- replay across Network Revisions;
- dependency supply-chain compromise.

## 123. Downgrade Protection

After a protocol activation:

- new operations SHALL bind to the active version;
- Validators SHALL reject obsolete consensus rules;
- clients SHALL reject incompatible chain responses;
- automatic software downgrade SHALL not bypass version checks.

## 124. Authority Key Compromise

A compromised Upgrade Authority key SHALL not alone activate an upgrade when threshold authorization is required.

Key rotation SHALL:

- use canonical operations;
- preserve historical signatures;
- require the existing authorization policy;
- take effect at a future Epoch unless emergency conditions apply.

## 125. Validator Readiness Fraud

A Validator falsely signaling readiness may cause:

- failed participation;
- downtime;
- removal from Active Set;
- Reputation reduction.

Readiness fraud is slashable only when objective malicious evidence and a defined penalty rule exist.

## 126. Emergency Power Abuse

Emergency mechanisms SHALL be:

- scoped;
- threshold-authorized;
- time-bounded;
- publicly visible;
- non-retroactive;
- independently auditable.

Emergency authority SHALL not silently become ordinary governance.

## 127. MVP Requirements

The MVP SHALL implement:

- distinct version dimensions;
- Upgrade Proposal lifecycle;
- Release Manifests;
- Parameter Updates;
- Operation Set upgrades;
- deterministic State Migrations;
- future-Epoch activation;
- Validator readiness signals;
- readiness threshold;
- automatic postponement;
- pre-upgrade Snapshot;
- atomic activation;
- post-upgrade State Root verification;
- post-upgrade Snapshot;
- Compatibility Window;
- emergency operation pauses;
- deterministic State Repair;
- failed-upgrade recovery before finality;
- forward-only correction after finality;
- Network Revision identity;
- Recovery Manifest format;
- replay protection across revisions;
- complete upgrade audit history.

## 128. Deferred Features

The MVP MAY postpone:

- fully decentralized governance voting;
- automatic proposal deposits;
- delegated governance;
- on-chain code execution;
- automatic binary distribution;
- zero-knowledge migration proofs;
- formal verification of complete State Machine migrations;
- decentralized release-build networks;
- automatic social-fork resolution;
- cross-chain recovery coordination;
- insurance for upgrade incidents.

## 129. Open Protocol Parameters

The following remain configurable:

- Upgrade Authorization Policy;
- Emergency Authorization Policy;
- review periods;
- activation delays;
- readiness threshold;
- Registry readiness target;
- Snapshot provider target;
- postponement interval;
- maximum postponements;
- Compatibility Window;
- Upgrade Verification Period;
- emergency-action maximum duration;
- Recovery Manifest authorization;
- State Repair challenge period;
- Stake transition period;
- Session drain period.

## 130. Upgrade Invariants

```text
Finalized History Is Not Rewritten
Protocol Activation Occurs at a Deterministic Boundary
Consensus-Critical Activation Requires More Than Two-Thirds Ready Voting Power
State Migration Produces One Deterministic State Root
Old Session Contracts Are Not Retroactively Repriced
Closed Epoch Rewards Use Their Original Formula Version
Unready Upgrade Does Not Partially Activate
Emergency Actions Are Scoped and Time-Bounded
```

## 131. State Repair Invariants

```text
State Repair References One Exact Affected State Root
State Repair Does Not Modify Unselected Objects
Supply Effect Is Explicit
Manual Database Editing Is Not Canonical Recovery
Every Repair Is Auditable
The Same Repair Manifest Produces the Same Result on Every Honest Node
```

## 132. Recovery Invariants

- Ordinary recovery preserves the current Network Revision.
- Recovery begins from a finalized checkpoint.
- Consensus restart does not reset Wallet balances.
- Lost local state is repaired through State Sync.
- Insufficient consensus signatures cannot magically authorize a new Validator Set.
- Recovery without sufficient old-set authorization is an explicit Network Revision.
- Network Revision changes are replay-separated.
- Multiple recovery branches may exist and must be selected through trusted policy.
- Active Sessions receive one deterministic recovery treatment.
- Active Marketplace offers require republish or explicit migration before new-revision Session opening.
- Q supply remains anchored to the declared recovery State Root.

## 133. Security Invariants

- One key cannot silently activate a production consensus upgrade.
- Release artifacts are hash-verified.
- Upgrade approval and technical readiness are separate.
- State migration does not use external nondeterministic data.
- A failed unfinalized activation does not modify canonical history.
- A finalized defective activation is corrected forward.
- Emergency pauses do not grant arbitrary confiscation power.
- Recovery manifests bind to the last finalized block.
- Old-revision operations cannot be replayed on a new revision.
- Old-revision Advertisements remain historical and do not silently regain active Session-opening status.
- Registry peer majority does not choose the canonical recovery branch.

## 134. Design Invariants

- Protocol rules are versioned.
- Protocol changes are explicit and auditable.
- Planned upgrades activate at future deterministic boundaries.
- Validators signal readiness before consensus-critical activation.
- Snapshot and migration tooling are part of the upgrade process.
- Emergency mechanisms prioritize safety over liveness.
- Finality is respected even when the finalized result later requires correction.
- Canonical repairs are state transitions, not database edits.
- Ordinary software rollback is allowed only when semantically compatible.
- Loss of consensus quorum exposes a social trust boundary rather than concealing it.
- A Network Revision is an explicit hard-fork continuity event.
- The protocol does not pretend that governance disappears merely because its signatures are serialized.
