# RFC-0067 Protocol Governance and Authorization Policy

Status: `Draft`

Version: `0.1`

Depends on:

- `ECO-0000 Economic Principles`
- `ECO-0004 Protocol Service Reward Distribution`
- `ECO-0005 Q Emission, Recycling and Epoch Reward Allocation`
- `ECO-0006 Consensus Economics and Validator Eligibility`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0047 CometBFT Consensus Integration`
- `RFC-0048 Epoch Engine`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0059 Ledger Operation Catalog`
- `RFC-0061 Registry Replication Protocol`
- `RFC-0062 Snapshot and State Sync Protocol`
- `RFC-0066 Protocol Upgrade and Emergency Recovery`

## 1. Purpose

This document defines the AiDN governance and protocol-authorization system.

It specifies:

- governance participants;
- governance modes;
- Governance Chambers;
- proposal classes;
- proposal submission;
- proposal sponsorship;
- review and voting periods;
- voting eligibility;
- voting power;
- approval thresholds;
- economic signaling;
- bootstrap governance;
- distributed governance;
- emergency authorization;
- governance-policy upgrades;
- Governance Council replacement;
- conflict-of-interest disclosure;
- governance attack resistance;
- integration with protocol upgrades and Ledger Operations.

This document determines who may authorize protocol actions.

`RFC-0066` determines how an authorized action is activated and executed.

## 2. Core Principle

AiDN governance SHALL separate:

- proposal creation;
- public review;
- political authorization;
- technical readiness;
- protocol activation.

No participant SHALL receive unilateral authority over all stages.

The ordinary lifecycle is:

```text
Proposal
    ->
Sponsorship
    ->
Public Review
    ->
Chamber Voting
    ->
Authorization
    ->
Technical Readiness
    ->
Protocol Activation
```

Authorization does not itself activate a protocol change.

## 3. Governance Scope

Protocol governance MAY authorize:

- protocol upgrades;
- economic parameter changes;
- Ledger Operation Set changes;
- State Schema migrations;
- Consensus parameter changes;
- Registry Profile changes;
- Certification-policy changes;
- emergency protocol actions;
- State Repair authorization;
- Governance Policy changes;
- replacement of governance authorities.

## 4. Matters Outside Protocol Governance

The following do not normally require protocol governance:

- local software configuration;
- operator pricing;
- Endpoint creation;
- Runtime selection;
- ordinary Session decisions;
- Validator offer acceptance;
- Marketplace ranking algorithms outside canonical protocol;
- documentation corrections that do not change protocol meaning;
- implementation optimizations preserving deterministic behavior.

Governance SHALL not micromanage ordinary network operation.

## 5. Governance Limitations

Protocol governance SHALL NOT claim to establish:

- one-human-one-vote identity;
- perfect independence between operators;
- immunity from bribery;
- immunity from social coordination;
- automatic legitimacy;
- legal authority outside the protocol.

Governance defines canonical authorization rules.

It does not eliminate the social layer of distributed systems.

## 6. Governance Modes

AiDN defines three governance modes:

- `BOOTSTRAP_GOVERNANCE`
- `DISTRIBUTED_GOVERNANCE`
- `RECOVERY_GOVERNANCE`

## 7. BOOTSTRAP_GOVERNANCE

Used during early network operation when:

- few independent Validators exist;
- infrastructure participation is concentrated;
- Chamber voting would be easily captured;
- protocol development remains rapid.

Bootstrap Governance uses:

- a declared Bootstrap Governance Council;
- Consensus Validator approval where applicable;
- public review;
- technical readiness requirements.

## 8. DISTRIBUTED_GOVERNANCE

Used after the network reaches sufficient independent participation.

Distributed Governance uses two binding Chambers:

`Consensus Chamber`

`Infrastructure Chamber`

Certain proposals also require:

- extended review;
- economic signaling;
- two-stage ratification;
- higher supermajority thresholds.

## 9. RECOVERY_GOVERNANCE

Used only when ordinary canonical governance cannot operate because Consensus cannot finalize.

Recovery Governance is defined by the Network Revision Recovery mechanism in `RFC-0066`.

It is not an ordinary alternative voting path.

## 10. Governance Objects

The governance system uses:

- Governance Proposal;
- Proposal Version;
- Proposal Bond;
- Sponsorship Record;
- Chamber Snapshot;
- Governance Vote;
- Economic Signal;
- Authorization Certificate;
- Governance Policy;
- Governance Council Record;
- Emergency Authorization Record.

## 11. Governance Proposal

A Governance Proposal is an immutable request for a canonical protocol decision.

```yaml
governance_proposal:
  proposal_id:
  proposal_version:
  proposal_class:
  title:
  summary:
  rationale:
  affected_protocol_documents:
  affected_parameters:
  affected_operation_types:
  affected_state_namespaces:
  security_analysis_hash:
  economic_analysis_hash:
  implementation_manifest_hash:
  migration_manifest_hash:
  proposed_activation_epoch:
  minimum_review_period:
  voting_period:
  expiration_epoch:
  proposal_bond:
  proposer_wallet:
  proposer_signature:
```

## 12. Proposal Immutability

A published Proposal Version SHALL be immutable.

A material change requires:

- a new Proposal Version;
- a new canonical hash;
- renewed sponsorship where required;
- renewed votes.

Votes cast for one version SHALL not authorize another version.

## 13. Proposal Classes

The protocol defines:

- `STANDARD_PROTOCOL`
- `SERVICE_POLICY`
- `ECONOMIC_PARAMETER`
- `CONSENSUS_CRITICAL`
- `STATE_MIGRATION`
- `GOVERNANCE_CONSTITUTIONAL`
- `EMERGENCY_ACTION`
- `STATE_REPAIR`
- `NETWORK_RECOVERY_SIGNAL`

## 14. STANDARD_PROTOCOL

Used for:

- ordinary protocol extensions;
- non-economic message changes;
- compatible object-schema extensions;
- operational protocol rules not affecting core invariants.

## 15. SERVICE_POLICY

Used for rules primarily affecting one Service class.

Examples include:

- Registry Profile requirements;
- Validation assignment limits;
- Certification validity;
- Runtime conformance requirements.

## 16. ECONOMIC_PARAMETER

Used for changes affecting:

- Q emission;
- reward-pool allocation;
- Faucet rules;
- Network Fees;
- Stake requirements;
- Bond requirements;
- slashing percentages;
- reward formulas;
- recyclable-Q handling.

## 17. CONSENSUS_CRITICAL

Used for changes affecting:

- block validity;
- State Machine execution;
- Validator Set rules;
- Consensus evidence;
- application-state hashing;
- finality behavior;
- consensus adapter semantics.

## 18. STATE_MIGRATION

Used for deterministic canonical-state migrations.

State Migration proposals SHALL satisfy `RFC-0066`.

## 19. GOVERNANCE_CONSTITUTIONAL

Used for changes to:

- Governance Chambers;
- voting eligibility;
- voting thresholds;
- Governance Modes;
- emergency powers;
- Council powers;
- finality principles;
- Network Revision rules;
- governance invariants.

These proposals require the strongest ordinary authorization.

## 20. EMERGENCY_ACTION

Used for time-bounded emergency actions under `RFC-0066`.

Emergency proposals SHALL not be used to enact permanent policy.

## 21. STATE_REPAIR

Used to authorize a deterministic State Repair Manifest.

It SHALL identify:

- exact affected state;
- repair algorithm;
- supply effect;
- affected objects;
- expected State Root.

## 22. NETWORK_RECOVERY_SIGNAL

Used only as a public governance signal during Network Revision Recovery.

It does not become a canonical Ledger authorization when Consensus is unavailable.

## 23. Proposal Submission Eligibility

Any Wallet MAY submit a Governance Proposal when it:

- pays or locks the required Proposal Bond;
- uses a valid Wallet sequence;
- supplies all mandatory manifests;
- passes schema validation;
- does not duplicate an active Proposal;
- satisfies proposal-size limits.

Protocol participation is not restricted to existing Chamber members.

## 24. Proposal Bond

A Proposal Bond discourages unlimited proposal spam.

Recommended initial value:

`ProposalBond = 100Q`

The Bond is locked during sponsorship and review.

It is not a fee for purchasing political consideration.

## 25. Proposal Bond Return

The Proposal Bond SHALL be returned when:

- the proposal reaches the formal voting stage;
- the proposal is withdrawn before review begins under permitted rules;
- the proposal is rejected after a valid vote;
- the proposal is approved;
- the proposal expires after completing required review.

Bond return SHALL not depend on political outcome.

## 26. Proposal Bond Forfeiture

A defined portion MAY be forfeited when:

- the proposal is malformed after repeated correction opportunity;
- the proposal contains invalid references;
- the proposal is an exact replay of a recently rejected version without material change;
- objective spam rules are satisfied;
- the proposer submits conflicting signed proposal content under one Proposal ID.

Political unpopularity SHALL not cause Bond forfeiture.

## 27. Proposal Sponsorship

A submitted proposal enters:

`SPONSORING`

before public review.

Sponsorship demonstrates that the proposal has minimum network interest.

## 28. Sponsorship Eligibility

A Sponsor SHALL be an eligible member of:

- Consensus Chamber;
- Infrastructure Chamber;
- Bootstrap Governance Council during Bootstrap Mode.

A participant may sponsor without committing to vote for approval later.

## 29. Sponsorship Threshold

Recommended initial threshold:

`3 independent Infrastructure Chamber groups`

or:

`10% of eligible Infrastructure Chamber voting units`

whichever is greater but not more than the Chamber's feasible membership.

Consensus-critical proposals SHOULD also require at least:

`2 active Consensus Validators`

as Sponsors.

## 30. Failed Sponsorship

If the proposal does not reach the Sponsorship threshold before expiration:

- it does not enter formal review;
- it becomes `UNSPONSORED_EXPIRED`;
- the Proposal Bond treatment follows protocol parameters;
- it may be resubmitted with material improvement.

## 31. Proposal Lifecycle

A Governance Proposal follows:

```text
DRAFT
    ->
SUBMITTED
    ->
SPONSORING
    ->
PUBLIC_REVIEW
    ->
VOTING
    ->
AUTHORIZED
    ->
SCHEDULED
    ->
ACTIVATED
```

Alternative states include:

- `UNSPONSORED_EXPIRED`
- `REJECTED`
- `WITHDRAWN`
- `CANCELLED`
- `SUPERSEDED`
- `EXPIRED`
- `ACTIVATION_FAILED`

## 32. Public Review

Every binding Proposal SHALL have a public review period.

Review materials SHALL be available through Registry references.

Public review SHOULD include:

- rationale;
- technical design;
- economic impact;
- security analysis;
- migration plan;
- alternatives;
- implementation status;
- known risks;
- operator instructions.

## 33. Minimum Review Periods

Recommended initial minimums:

| Proposal class | Minimum review |
| --- | --- |
| Standard Protocol | `7 Epochs` |
| Service Policy | `7 Epochs` |
| Economic Parameter | `14 Epochs` |
| Consensus Critical | `21 Epochs` |
| State Migration | `21 Epochs` |
| Governance Constitutional | `30 Epochs` |
| State Repair | `7 Epochs` |
| Emergency Action | shortened |

## 34. Review Extension

A review period MAY be extended when:

- material implementation changes occur;
- security analysis changes;
- migration results differ;
- proposal dependencies change;
- public reviewers identify unresolved critical issues.

Extension SHALL not alter Proposal content.

A modified proposal requires a new version.

## 35. Governance Chambers

Distributed Governance has two binding Chambers:

`Consensus Chamber`

`Infrastructure Chamber`

Each Chamber represents a different protocol responsibility.

Approval from one Chamber SHALL not automatically imply approval from the other.

## 36. Consensus Chamber

The Consensus Chamber consists of active Consensus Validators from the proposal's fixed Chamber Snapshot.

Its purpose is to represent participants directly responsible for:

- finality;
- canonical State Machine execution;
- Validator Set safety;
- protocol activation.

## 37. Consensus Chamber Voting Power

Consensus Chamber voting power SHALL equal the active CometBFT voting power in the Chamber Snapshot.

Under `ECO-0006`:

```text
One active Validator
=
One equal voting-power unit
```

Known Control Group active-slot limits already apply.

## 38. Infrastructure Chamber

The Infrastructure Chamber consists of eligible Known Control Groups performing qualifying network work.

A group receives one Infrastructure voting unit regardless of the number of identities or Services it operates.

## 39. Infrastructure Chamber Purpose

The Infrastructure Chamber represents operators responsible for:

- Registry availability;
- Validation work;
- Compute and Endpoint operation;
- Consensus candidacy;
- protocol infrastructure;
- user-facing network capacity.

It prevents the active Validator Set from becoming the sole author of every rule affecting the rest of the network.

## 40. Infrastructure Chamber Eligibility

A Known Control Group qualifies when it satisfies at least one Contribution Path.

Initial Contribution Paths include:

Consensus Path

- eligible Consensus Candidate or Active Validator;
- minimum operational age;
- required Stake;
- acceptable Health.

Registry Path

- reward-eligible Full Registry;
- successful Duty Proof;
- acceptable completeness and Health.

Validation Path

- eligible Validation Service;
- at least one qualifying report within the recent activity window;
- acceptable Health and Reputation.

Compute Path

- at least one active Endpoint;
- minimum operational age;
- minimum completed independent paid Sessions;
- acceptable Endpoint or operator Reputation;
- no active suspension.

## 41. Infrastructure Activity Window

Eligibility SHALL use a recent activity window.

Recommended initial value:

`InfrastructureActivityWindow = 30 Epochs`

A group that registered infrastructure but performed no qualifying work SHALL not receive a governance vote.

## 42. Minimum Infrastructure Age

Recommended initial minimum:

`MinimumInfrastructureGovernanceAge = 10 qualifying Epochs`

This limits last-minute identity creation before major votes.

## 43. One Group, One Vote

Each eligible Known Control Group receives:

`InfrastructureVotingPower = 1`

Operating:

- ten Registries;
- five Validators;
- one hundred Endpoints;

does not multiply Infrastructure Chamber voting power.

Useful additional work may earn economic rewards, but not unlimited political authority.

## 44. Multiple Contribution Paths

A group satisfying several Contribution Paths still receives one Infrastructure vote.

Its eligibility record SHALL show all qualifying paths.

This encourages service diversity without allowing service multiplication to dominate governance.

## 45. Unknown Common Ownership

The protocol cannot identify all undisclosed common ownership.

Known Control Group aggregation uses finalized relationships.

Unverified signals MAY support public analysis but SHALL not automatically remove voting rights.

Governance remains economically Sybil-resistant rather than perfectly person-unique.

## 46. Chamber Snapshot

Voting eligibility and voting power SHALL be frozen in a Chamber Snapshot before voting begins.

```yaml
governance_chamber_snapshot:
  proposal_id:
  snapshot_epoch:
  consensus_members:
  consensus_power_root:
  infrastructure_groups:
  infrastructure_power_root:
  eligibility_evidence_root:
```

## 47. Snapshot Purpose

The Chamber Snapshot prevents participants from changing voting power during the vote by:

- creating identities;
- moving Services;
- transferring beneficiary Wallets;
- changing Stake;
- retiring and recreating nodes.

## 48. Snapshot Duration

The same Chamber Snapshot remains active for the complete voting period.

A new Proposal Version requires a new Snapshot.

## 49. Suspended Participant During Vote

A participant objectively suspended for critical misconduct after the Snapshot MAY have its vote invalidated when the applicable governance policy explicitly permits it.

Ordinary downtime or temporary ineligibility SHALL not retroactively rewrite the Snapshot.

## 50. Governance Identity

Each Chamber participant SHALL designate a Governance Signing Key.

The Governance Key is separate from:

- Consensus key;
- Wallet spending key where desired;
- Hypervisor Node key;
- Runtime keys.

The owner Wallet authorizes Governance Key registration and rotation.

## 51. Governance Key Rotation

Governance Key rotation SHALL:

- require owner authorization;
- preserve historical votes;
- take effect at a future block or Epoch;
- not alter already cast valid votes unless the policy allows recasting.

## 52. Vote Choices

A Governance Vote supports:

- `APPROVE`
- `REJECT`
- `ABSTAIN`

A participant MAY also submit:

`WITHDRAW_VOTE`

before voting closes.

## 53. Vote Changes

A participant MAY replace its vote during the voting period.

The latest finalized valid vote counts.

After voting closes, votes are immutable.

## 54. Public Votes

MVP governance votes SHALL be public and signed.

The Registry SHALL expose:

- voter identity;
- Chamber;
- vote choice;
- Proposal Version;
- timestamp;
- signature.

Secret ballots are deferred.

## 55. Abstention

`ABSTAIN` indicates participation without supporting either outcome.

Abstention MAY contribute to quorum where quorum is separately required.

It does not contribute to approval.

## 56. Approval Against Total Eligible Power

Binding approval thresholds SHALL be calculated against total eligible Chamber voting power, not merely votes cast.

Conceptually:

```text
ApprovalFraction
=
ApprovePower
/
TotalEligiblePower
```

This prevents a small low-turnout group from changing protocol rules.

## 57. Standard Approval Matrix

Recommended Distributed Governance thresholds:

| Proposal class | Consensus Chamber | Infrastructure Chamber |
| --- | --- | --- |
| Standard Protocol | `> 2/3` | `> 1/2` |
| Service Policy | `> 1/2` | `> 2/3` |
| Economic Parameter | `> 2/3` | `> 2/3` |
| Consensus Critical | `> 2/3` | `> 2/3` |
| State Migration | `> 2/3` | `> 2/3` |
| Governance Constitutional | `>= 3/4` | `>= 3/4` |
| State Repair | `>= 3/4` | `> 2/3` |

Thresholds apply to total eligible power.

## 58. Consensus Chamber Requirement

Any proposal changing canonical State Machine execution SHALL require Consensus Chamber authorization.

The Infrastructure Chamber cannot independently activate consensus rules.

## 59. Infrastructure Chamber Requirement

Any proposal materially affecting:

- reward distribution;
- infrastructure obligations;
- Certification;
- Registry requirements;
- Validation;
- Endpoint participation;
- operator eligibility;

SHALL require Infrastructure Chamber authorization.

## 60. Service-Specific Signal

A Service Policy proposal SHOULD collect an affected-Service signal.

Examples:

- Registry operators signal on Registry Profile changes;
- Validators signal on Validation Protocol changes;
- Endpoint operators signal on Proxy or Capability rules.

The signal MAY be advisory in the MVP.

It SHALL be published with the final authorization result.

## 61. Economic Stakeholder Signal

Q holders MAY participate in a non-binding Economic Stakeholder Signal.

The signal exists to measure economic support or concern without converting Q directly into protocol control.

## 62. Economic Signal Lock

A Wallet submitting an Economic Signal SHALL lock Q for a configured period.

Recommended initial value:

`EconomicSignalLock = 7 Epochs`

Locking demonstrates economic exposure.

It does not create binding governance authority in the MVP.

## 63. Bounded Economic Signal Weight

Economic signaling SHOULD use bounded nonlinear weight.

Example:

```text
SignalWeight
=
min(
    MaximumSignalWeight,
    floor(
        sqrt(
            LockedSignalQ
            /
            SignalUnitQ
        )
    )
)
```

This reduces but does not eliminate wealth concentration.

## 64. Economic Signal Is Advisory

In the MVP:

- Economic Signal does not authorize a proposal;
- Economic Signal does not override Chamber approval;
- Economic Signal does not veto an authorized proposal.

It SHALL be prominently included in the proposal result.

## 65. Why Q Is Not One Vote Per Unit

Pure Q-weighted governance would allow:

- wealthy participants to purchase control;
- early recipients to dominate policy;
- exchanges or custodians to accumulate voting power;
- economic concentration to become political concentration.

Q is a network economic unit.

It is not proof of independent operation or unique personhood.

## 66. Future Binding Economic Chamber

A future protocol MAY create a binding Economic Chamber.

Such an upgrade SHALL define:

- custody handling;
- delegation;
- lock duration;
- concentration caps;
- Known Control Group aggregation;
- exchange voting;
- borrowed-Q resistance;
- vote-buying considerations.

It is deferred from the MVP.

## 67. Proposal Voting Period

Recommended initial voting periods:

| Proposal class | Voting period |
| --- | --- |
| Standard Protocol | `7 Epochs` |
| Service Policy | `7 Epochs` |
| Economic Parameter | `14 Epochs` |
| Consensus Critical | `14 Epochs` |
| State Migration | `14 Epochs` |
| Governance Constitutional | `21 Epochs` |
| State Repair | `7 Epochs` |

## 68. Vote Finalization

At voting close, the Epoch Engine calculates:

- total eligible power;
- Approve power;
- Reject power;
- Abstain power;
- invalid votes;
- Chamber thresholds;
- Economic Signal;
- affected-Service signals.

## 69. Authorization Certificate

An approved proposal produces:

```yaml
governance_authorization_certificate:
  authorization_id:
  proposal_id:
  proposal_version:
  chamber_snapshot_root:
  consensus_vote_root:
  infrastructure_vote_root:
  economic_signal_root:
  consensus_approval:
  infrastructure_approval:
  required_thresholds:
  authorization_epoch:
  expiration_epoch:
  governance_policy_version:
```

`RFC-0066` SHALL accept only a valid Authorization Certificate.

## 70. Authorization Expiration

Authorization SHALL expire when:

- activation is not scheduled before the expiration Epoch;
- the proposal is superseded;
- critical implementation details change;
- a required manifest changes;
- the proposal is cancelled.

Expired authorization cannot activate a later modified release.

## 71. Rejected Proposal

A proposal is rejected when any required Chamber fails its threshold.

A rejected proposal MAY be resubmitted only as:

- a materially changed version;
- a new Proposal ID;
- or after a configured cooldown.

## 72. Rejection Cooldown

Recommended initial cooldown:

`RejectedProposalCooldown = 5 Epochs`

The cooldown prevents immediate identical resubmission.

## 73. No Governance Reward

The MVP SHALL not pay Q merely for:

- sponsoring;
- voting;
- abstaining;
- reviewing;
- serving on the Bootstrap Council.

Governance participation is a responsibility attached to network influence.

This avoids creating low-information voting farms.

## 74. Review Contributors

Public reviewers MAY publish:

- security reports;
- economic analysis;
- implementation tests;
- migration results;
- objections;
- alternatives.

Their work may receive external or future rewards, but not automatic governance emission in the MVP.

## 75. Bootstrap Governance Council

Bootstrap Governance uses a fixed Council declared in Genesis.

Recommended initial configuration:

`BootstrapCouncilSize = 5`

`BootstrapApprovalThreshold = 3-of-5`

`BootstrapConstitutionalThreshold = 4-of-5`

Council members SHALL use independent keys.

## 76. Bootstrap Council Record

```yaml
bootstrap_governance_council:
  council_version:
  members:
  member_public_keys:
  ordinary_threshold:
  constitutional_threshold:
  emergency_threshold:
  activation_epoch:
  sunset_epoch:
```

## 77. Bootstrap Upgrade Authorization

During Bootstrap Governance:

Standard and Service Policy

Requires:

- Bootstrap Council ordinary threshold;
- public review;
- technical readiness where applicable.

Economic, Consensus Critical and State Migration

Requires:

- Bootstrap Council ordinary threshold;
- more than two-thirds Consensus Chamber approval;
- technical readiness under `RFC-0066`.

Governance Constitutional

Requires:

- Bootstrap Council constitutional threshold;
- at least two-thirds Consensus Chamber approval;
- extended review.

## 78. Bootstrap Infrastructure Signal

Infrastructure Chamber voting MAY initially be advisory until enough independent groups exist.

Its results SHALL still be recorded publicly.

When the configured independence threshold is reached, Infrastructure approval becomes binding.

## 79. Bootstrap Emergency Authorization

Recommended initial emergency threshold:

`4-of-5 Bootstrap Council`

Where time permits, emergency action SHOULD also obtain:

`> 2/3 active Consensus voting power`

A short Consensus safety pause may use the separate mechanism defined later in this document.

## 80. Bootstrap Council Limits

The Bootstrap Council SHALL NOT unilaterally:

- transfer Wallet balances;
- Mint arbitrary Q;
- change finalized history;
- assign arbitrary voting power;
- bypass State Repair rules;
- permanently suspend participants without evidence;
- change its own thresholds without Constitutional authorization.

## 81. Bootstrap Sunset

Genesis SHALL define a Bootstrap Governance Sunset Epoch.

Recommended approach:

`BootstrapSunsetReview = every 90 Epochs`

and an absolute target sunset.

The Council SHALL not remain silently permanent.

## 82. Distributed Governance Readiness

The network becomes eligible for Distributed Governance when all configured conditions are met.

Recommended initial conditions:

`At least 7 independent active Consensus groups`

`At least 15 eligible Infrastructure Chamber groups`

`Conditions sustained for 30 consecutive Epochs`

`Registry and Snapshot diversity targets satisfied`

## 83. Governance Mode Transition

Transition from Bootstrap to Distributed Governance requires a Constitutional Proposal.

It SHALL define:

- activation Epoch;
- final Bootstrap Council powers;
- emergency transition behavior;
- active Chamber policy;
- Council-key archival;
- unresolved Proposal handling.

## 84. Post-Sunset Council Role

After Distributed Governance activation, the Bootstrap Council SHALL normally become inactive.

It MAY retain only a narrowly scoped, time-limited recovery-signaling role if explicitly authorized.

It SHALL not retain hidden ordinary upgrade power.

## 85. Council Replacement

Before Sunset, a Council member MAY be replaced through a Governance Proposal.

Replacement SHALL require:

- reason;
- new public key;
- effective Epoch;
- current Council threshold;
- Consensus Chamber approval for critical periods.

One Council member SHALL not replace another unilaterally.

## 86. Council Key Loss

If a Council key is lost:

- the member is marked unavailable;
- threshold requirements remain unchanged unless governance authorizes replacement;
- the Council cannot silently lower its own threshold;
- Recovery Governance MAY be needed if the remaining threshold becomes impossible.

## 87. Constitutional Governance

Governance Constitutional proposals require:

`Consensus approval >= 75%`

`Infrastructure approval >= 75%`

of total eligible power.

During Bootstrap Mode, the Bootstrap constitutional threshold also applies.

## 88. Two-Stage Constitutional Ratification

A Constitutional Proposal SHALL be approved twice.

```text
First Ratification
    ->
Constitutional Delay
    ->
Second Ratification
```

Recommended delay:

`ConstitutionalRatificationDelay = 7 Epochs`

## 89. Second Ratification Snapshot

The second ratification SHALL use a new Chamber Snapshot.

This confirms that support remains after:

- public review;
- operational changes;
- participant turnover;
- implementation testing.

## 90. Constitutional Activation Delay

Recommended minimum activation delay after second ratification:

`14 Epochs`

Emergency powers SHALL not be used to bypass this delay for ordinary governance redesign.

## 91. Monetary Policy Protection

Changes to the following SHALL be treated as high-impact Economic or Constitutional proposals:

- base Epoch emission;
- maximum supply rules if introduced;
- recyclable-Q treatment;
- Faucet allocation;
- reward-pool percentages;
- arbitrary Mint authority;
- penalty destination.

Recommended threshold:

`Consensus Chamber >= 75%`

`Infrastructure Chamber >= 75%`

for changes materially increasing emission authority.

## 92. No Arbitrary Mint Governance

Governance SHALL not authorize an unrestricted discretionary Mint key.

Every Mint authority SHALL remain:

- rule-bound;
- pool-bound;
- amount-bounded;
- Epoch-bound;
- auditable.

Governance may change future formulas.

It SHALL not create an administrator-controlled money printer and call it flexibility.

## 93. Emergency Governance

Emergency Governance permits rapid, scoped containment.

It SHALL distinguish:

- `SHORT_SAFETY_PAUSE`
- `EXTENDED_EMERGENCY_ACTION`
- `EMERGENCY_STATE_REPAIR`

## 94. Short Safety Pause

A Short Safety Pause MAY be authorized by:

`more than one-third active Consensus voting power`

The pause:

- lasts no more than one Epoch;
- may pause selected risky operations;
- cannot transfer balances;
- cannot Mint Q;
- cannot change Validator Set;
- cannot modify governance thresholds;
- cannot apply State Repair.

## 95. Why One-Third May Pause

More than one-third voting power can already prevent CometBFT finalization.

Allowing that group to request a narrow canonical safety pause provides a controlled alternative to an unstructured halt.

The power is limited to temporary containment.

## 96. Short Pause Scope

A Short Safety Pause MAY affect:

- Reward Mint;
- Faucet Claims;
- new Sessions;
- Session Deposit extensions;
- Stake Release;
- Validation assignments;
- one defective Operation type;
- one planned upgrade.

## 97. Extended Emergency Action

An Extended Emergency Action requires:

`Consensus Chamber > 2/3`

and:

`Infrastructure Chamber > 1/2`

in Distributed Governance.

During Bootstrap Governance it additionally requires the Bootstrap emergency threshold.

## 98. Extended Emergency Duration

Recommended maximum:

`7 Epochs`

Further extension requires a new authorization.

## 99. Emergency State Repair

Emergency State Repair requires the normal State Repair threshold:

`Consensus Chamber >= 75%`

`Infrastructure Chamber > 2/3`

It SHALL follow `RFC-0066`.

A temporary pause threshold cannot authorize balance modification.

## 100. Emergency Action Expiration

Every Emergency Action SHALL expire automatically.

Expiration SHALL:

- restore ordinary operation;
- or transition into a newly authorized replacement action.

No manual forgotten flag may keep the network paused indefinitely.

## 101. Emergency Transparency

Emergency records SHALL include:

- incident description;
- evidence root;
- approving participants;
- affected operations;
- maximum duration;
- recovery conditions;
- extension history;
- final incident report.

## 102. Consensus Halt

If Consensus cannot finalize, no new canonical Governance Vote or Emergency Action can be recorded.

Participants MAY:

- stop local services;
- publish signed recovery signals;
- preserve evidence;
- coordinate Recovery Governance.

Canonical continuation follows `RFC-0066`.

## 103. Governance During Network Revision Recovery

A Recovery Manifest SHOULD collect signatures or public signals from:

- last active Validators;
- Infrastructure Chamber groups;
- Bootstrap Council where still applicable;
- major Registry providers;
- software maintainers;
- public economic stakeholders.

These signals inform branch selection.

They do not magically recreate unavailable canonical Consensus.

## 104. Conflict-of-Interest Disclosure

Proposal authors, Sponsors and voters SHOULD disclose material conflicts.

Examples include:

- direct financial benefit;
- affected operator ownership;
- vendor relationship;
- implementation contract;
- related upstream service;
- security-audit compensation.

Disclosure is public metadata.

## 105. Undisclosed Conflict

Failure to disclose a conflict SHALL not automatically invalidate a vote unless:

- disclosure was mandatory under an explicit policy;
- the conflict involved objective fraud;
- the vote authorization was obtained through false signed statements.

Governance cannot reliably infer every private relationship.

## 106. Vote Buying

The protocol cannot fully prevent off-chain vote buying.

Public votes allow observers to identify suspicious coordination.

Future versions MAY explore:

- commit-reveal voting;
- private ballots;
- anti-bribery cryptography;
- delayed vote revelation.

These are deferred.

## 107. Delegation

Vote delegation is not supported in the MVP.

Each eligible participant casts its own vote.

Delegation introduces:

- concentration;
- custodial control;
- stale mandates;
- hidden brokerage;
- governance cartels.

A future protocol may define bounded delegation.

## 108. Custodial Q Signals

Custodians and exchanges SHALL not automatically signal on behalf of underlying Q holders.

Economic Signal ownership represents control of the signaling Wallet.

It does not prove beneficial ownership.

## 109. Governance Participation Metrics

The network SHOULD publish:

- number of active Proposals;
- sponsorship rates;
- Chamber participation;
- approval distribution;
- abstention rate;
- voter concentration;
- Known Control Group count;
- Proposal Bond statistics;
- emergency-action frequency;
- Bootstrap Council actions;
- Economic Signal distribution;
- upgrade success and failure rates.

## 110. Governance Reputation

The MVP SHALL not create a universal Governance Reputation score.

Protocol history MAY expose:

- proposal authorship;
- vote history;
- readiness accuracy;
- conflicting signatures;
- emergency actions;
- review contributions.

Consumers may evaluate behavior without one official ideological rating.

## 111. Conflicting Governance Votes

A Governance Key signing incompatible votes for the same Proposal Version and voting sequence creates objective conflicting evidence.

The State Machine SHALL count only the latest valid finalized vote under ordinary replacement rules.

Fabricated or impossible vote histories MAY trigger suspension from governance participation.

## 112. Governance Spam

Spam protection MAY include:

- Proposal Bond;
- sponsorship threshold;
- proposal cooldown;
- maximum active Proposals per Wallet;
- content-size limits;
- duplicate detection;
- review queue limits.

Spam rules SHALL remain objective.

## 113. Proposal Bundling

A Proposal SHOULD contain one coherent change.

Unrelated changes SHOULD be split.

A Constitutional or economic change SHALL not be hidden inside a minor implementation proposal.

The protocol MAY reject improperly classified bundles.

## 114. Proposal Classification Challenge

During review, participants MAY challenge Proposal Class.

If a proposal is classified too weakly:

- voting SHALL pause;
- classification is reevaluated;
- required thresholds and review period are updated;
- a material classification change MAY require a new Proposal Version.

## 115. Highest Applicable Threshold

When a proposal spans multiple classes, the highest applicable threshold SHALL apply.

Example:

`Registry Profile update`

`+`

`reward formula change`

is treated at least as an Economic Parameter proposal.

## 116. Implementation Dependency

Governance authorization SHALL not activate an incomplete implementation.

`RFC-0066` readiness remains mandatory.

A politically approved proposal may expire without activation when no safe implementation exists.

## 117. Maintainer Role

Software maintainers MAY:

- write code;
- publish releases;
- propose changes;
- provide analysis;
- operate governance participants.

Maintainer status alone SHALL not grant protocol authorization.

## 118. Auditor Role

Auditors MAY publish:

- security reports;
- migration verification;
- reproducible-build results;
- economic analysis;
- State Root comparisons.

Auditors do not receive automatic veto power in the MVP.

## 119. Security Review Hold

A critical reproducible security report MAY trigger:

- Short Safety Pause;
- proposal postponement;
- readiness withdrawal;
- Emergency Action.

One unauthenticated claim SHALL not permanently block governance.

## 120. Governance Ledger Operations

`RFC-0059` SHALL support:

- `GOVERNANCE_PROPOSAL_SUBMIT`
- `GOVERNANCE_PROPOSAL_WITHDRAW`
- `GOVERNANCE_PROPOSAL_SPONSOR`
- `GOVERNANCE_PROPOSAL_UNSPONSOR`
- `GOVERNANCE_REVIEW_OPEN`
- `GOVERNANCE_VOTING_OPEN`
- `GOVERNANCE_VOTE`
- `GOVERNANCE_VOTE_WITHDRAW`
- `GOVERNANCE_VOTING_FINALIZE`
- `GOVERNANCE_ECONOMIC_SIGNAL`
- `GOVERNANCE_ECONOMIC_SIGNAL_WITHDRAW`
- `GOVERNANCE_AUTHORIZATION_COMMIT`
- `GOVERNANCE_PROPOSAL_REJECT`
- `GOVERNANCE_PROPOSAL_EXPIRE`
- `GOVERNANCE_PROPOSAL_CANCEL`
- `GOVERNANCE_COUNCIL_UPDATE`
- `GOVERNANCE_MODE_TRANSITION`
- `GOVERNANCE_SHORT_SAFETY_PAUSE`
- `GOVERNANCE_EMERGENCY_AUTHORIZE`

## 121. GOVERNANCE_PROPOSAL_SUBMIT

Creates a Governance Proposal record and locks the Proposal Bond.

It does not begin voting automatically.

## 122. GOVERNANCE_PROPOSAL_SPONSOR

Adds one eligible Sponsor to the Proposal.

Sponsorship is replay-protected.

One eligible group may sponsor once.

## 123. GOVERNANCE_VOTE

Records one Chamber vote.

The operation SHALL include:

```yaml
governance_vote:
  proposal_id:
  proposal_version:
  chamber:
  chamber_snapshot_hash:
  voter_id:
  vote_choice:
  vote_sequence:
  conflict_disclosure_hash:
  signature:
```

## 124. GOVERNANCE_VOTING_FINALIZE

Protocol-generated finalization calculates Chamber results.

The initiator cannot choose the outcome.

## 125. GOVERNANCE_AUTHORIZATION_COMMIT

Creates the Authorization Certificate after all required thresholds succeed.

`RFC-0066` uses this certificate for scheduling.

## 126. GOVERNANCE_MODE_TRANSITION

Changes Governance Mode after Constitutional authorization.

It SHALL define:

- previous mode;
- new mode;
- activation Epoch;
- Council powers after transition;
- active Governance Policy Version.

## 127. Epoch Tasks

`RFC-0048` SHALL include:

- Freeze Governance Eligibility;
- Create Chamber Snapshots;
- Evaluate Proposal Sponsorship;
- Open Public Review;
- Open Governance Voting;
- Validate Governance Votes;
- Finalize Chamber Results;
- Calculate Economic Signals;
- Generate Authorization Certificates;
- Expire Proposal Authorizations;
- Process Council Updates;
- Evaluate Governance Mode Transition;
- Expire Emergency Actions;
- Publish Governance Metrics.

## 128. Governance Error Codes

The MVP SHALL define at least:

- `GOVERNANCE_PROPOSAL_NOT_FOUND`
- `GOVERNANCE_PROPOSAL_VERSION_MISMATCH`
- `GOVERNANCE_PROPOSAL_DUPLICATE`
- `GOVERNANCE_PROPOSAL_CLASS_INVALID`
- `GOVERNANCE_PROPOSAL_BOND_INSUFFICIENT`
- `GOVERNANCE_SPONSOR_NOT_ELIGIBLE`
- `GOVERNANCE_ALREADY_SPONSORED`
- `GOVERNANCE_REVIEW_NOT_COMPLETE`
- `GOVERNANCE_VOTING_NOT_OPEN`
- `GOVERNANCE_VOTING_CLOSED`
- `GOVERNANCE_VOTER_NOT_ELIGIBLE`
- `GOVERNANCE_CHAMBER_SNAPSHOT_MISMATCH`
- `GOVERNANCE_VOTE_SEQUENCE_INVALID`
- `GOVERNANCE_THRESHOLD_NOT_MET`
- `GOVERNANCE_AUTHORIZATION_EXPIRED`
- `GOVERNANCE_COUNCIL_THRESHOLD_NOT_MET`
- `GOVERNANCE_MODE_TRANSITION_INVALID`
- `GOVERNANCE_EMERGENCY_SCOPE_INVALID`
- `GOVERNANCE_EMERGENCY_DURATION_EXCEEDED`
- `GOVERNANCE_CONSTITUTIONAL_RATIFICATION_INCOMPLETE`

## 129. Idempotency

The following SHALL be idempotent:

- Proposal submission;
- sponsorship;
- vote submission with the same sequence;
- vote withdrawal;
- Economic Signal;
- voting finalization;
- Authorization Certificate creation;
- Council update;
- Governance Mode transition;
- emergency authorization.

One Proposal Version SHALL not produce multiple independent authorizations.

## 130. Governance History

Registry Services SHALL retain:

- all Proposal Versions;
- sponsorship records;
- review documents;
- votes;
- Chamber Snapshots;
- Economic Signals;
- Authorization Certificates;
- Council records;
- Governance Mode transitions;
- emergency actions;
- activation outcomes.

Governance history SHALL remain auditable.

## 131. MVP Requirements

The MVP SHALL implement:

- Bootstrap Governance Mode;
- Bootstrap Governance Council;
- Consensus Chamber;
- advisory Infrastructure Chamber during early bootstrap;
- binding Infrastructure Chamber after transition;
- Proposal Bonds;
- sponsorship;
- immutable Proposal Versions;
- public review;
- public signed votes;
- Chamber Snapshots;
- approval against total eligible power;
- Proposal-class thresholds;
- advisory Economic Stakeholder Signal;
- Authorization Certificates;
- Constitutional two-stage ratification;
- Short Safety Pause;
- Extended Emergency Authorization;
- Governance Mode transition;
- Council replacement;
- complete governance history.

## 132. Deferred Features

The MVP MAY postpone:

- secret ballots;
- vote delegation;
- binding Economic Chamber;
- quadratic voting;
- proof-of-personhood;
- anonymous governance;
- governance reward pool;
- automated legal-entity verification;
- anti-bribery cryptography;
- delegated Council seats;
- capability-specific binding Chambers;
- liquid governance locks;
- cross-network governance.

## 133. Open Protocol Parameters

The following remain configurable:

- Proposal Bond;
- Bond forfeiture fraction;
- sponsorship threshold;
- proposal cooldown;
- review periods;
- voting periods;
- Chamber thresholds;
- Infrastructure Activity Window;
- minimum governance age;
- Compute Path Session threshold;
- Economic Signal Unit;
- maximum Economic Signal weight;
- Economic Signal lock duration;
- Bootstrap Council size;
- Bootstrap Council thresholds;
- Bootstrap Sunset Epoch;
- Distributed Governance readiness thresholds;
- Constitutional ratification delay;
- emergency-action duration;
- Short Safety Pause scope;
- authorization expiration;
- maximum active Proposals.

## 134. Governance Invariants

```text
Proposal Submission
!=
Proposal Authorization
Proposal Authorization
!=
Technical Readiness
Technical Readiness
!=
Protocol Activation
One Infrastructure Control Group
=
One Infrastructure Vote
Additional Service Identities
Do Not Multiply Governance Power
Q Balance Alone
Does Not Grant Binding Governance Control in the MVP
Votes Apply to One Exact Proposal Version
Authorization Uses Fixed Chamber Snapshots
```

## 135. Bootstrap Invariants

- Bootstrap Council membership is public.
- Bootstrap Council thresholds are fixed by canonical policy.
- One Council key cannot authorize critical changes.
- The Council cannot lower its own threshold unilaterally.
- Critical upgrades require Validator approval.
- Bootstrap authority has a declared Sunset process.
- Council activity remains auditable.
- Bootstrap Governance is not presented as fully decentralized governance.

## 136. Distributed Governance Invariants

- Consensus and Infrastructure Chambers are independent.
- Consensus-critical changes require Consensus approval.
- Infrastructure-affecting changes require Infrastructure approval.
- Constitutional changes require at least 75% in both Chambers.
- Chamber voting power is frozen before voting.
- Known Control Groups do not multiply Infrastructure votes.
- Failed proposals do not change protocol state.
- Approval thresholds are calculated against total eligible power.

## 137. Emergency Invariants

- Short Safety Pause is temporary and scoped.
- Short Safety Pause cannot move balances or Mint Q.
- Extended Emergency Action requires stronger authorization.
- Emergency State Repair uses State Repair thresholds.
- Emergency powers expire automatically.
- Emergency authority does not replace ordinary governance.
- Consensus halt cannot create a fictional canonical vote.

## 138. Economic Governance Invariants

- Economic changes are explicit.
- Historical rewards are not recalculated silently.
- Q emission changes require high authorization thresholds.
- No unrestricted Mint key may be created.
- Proposal Bonds do not buy approval.
- Losing a political vote does not forfeit the Proposal Bond merely for losing.
- Economic Signals remain advisory in the MVP.
- Governance does not guarantee protection from poor economic decisions.

## 139. Security Invariants

- Governance messages are signed and replay-protected.
- Proposal Versions are immutable.
- Votes cannot be transferred between Proposal Versions.
- Governance Key rotation preserves history.
- One Wallet cannot obtain additional Infrastructure votes by registering more Services in the same Known Control Group.
- Council-key compromise is limited by threshold authorization.
- Emergency actions are bounded.
- State Repair remains deterministic.
- Governance cannot rewrite finalized history through ordinary authorization.
- Network Revision Recovery remains explicit.

## 140. Design Invariants

- Governance authority is separated from technical activation.
- Early centralization is declared rather than disguised.
- Bootstrap authority has bounded powers and a transition path.
- Active Validators do not govern the entire network alone.
- Infrastructure operators receive independent representation.
- Token wealth does not directly purchase protocol control in the MVP.
- Constitutional changes are harder than ordinary parameter changes.
- Governance participation is public and auditable.
- Governance cannot eliminate the social choice involved in catastrophic recovery.
- The protocol serializes authority, but does not pretend that serialization creates legitimacy by itself.
