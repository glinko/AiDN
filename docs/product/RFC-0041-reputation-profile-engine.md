# RFC-0041 Reputation Profile Engine

Status: `Draft`

Version: `0.3`

Supersedes:

- `RFC-0041 Version 0.2`

Depends on:

- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0039 Hypervisor Service Model`
- `RFC-0040 Service Verification Framework`

## 1. Purpose

This document defines the AiDN Reputation Profile Engine.

The engine:

- records protocol-relevant behavior;
- creates separate Reputation Profiles for different participant roles;
- converts finalized evidence into deterministic reputation metrics;
- distinguishes current operational condition from long-term history;
- supports eligibility, Marketplace presentation and risk analysis;
- prevents unrelated positive behavior from hiding role-specific failures;
- preserves serious historical incidents;
- allows gradual recovery after ordinary failures.

Reputation is a structured evidence profile.

It is not a single universal score.

## 2. Core Principle

AiDN SHALL evaluate participants according to the specific role in which an event occurred.

A participant may operate:

- a reliable Registry;
- an unreliable Endpoint;
- a healthy Hypervisor;
- a poor Validation Service;
- an eligible Consensus Service.

These observations SHALL remain distinguishable.

A good result in one role SHALL NOT automatically erase or conceal failures in another role.

## 3. Reputation Profile Types

The protocol defines separate Reputation Profiles for:

- `HYPERVISOR`
- `CONSENSUS_SERVICE`
- `REGISTRY_SERVICE`
- `VALIDATION_SERVICE`
- `ENDPOINT`

Additional role-specific profiles MAY be introduced through a versioned protocol upgrade.

## 4. No Universal Reputation Identity

A Wallet, operator or Hypervisor may control several Services.

The protocol SHALL NOT combine all behavior into one authoritative universal reputation number.

Instead, it maintains:

- individual role profiles;
- ownership and control references;
- relevant propagated risk events;
- an optional advisory summary.

## 5. Profile Subject

Every Reputation Profile SHALL bind to one exact protocol subject.

```yaml
reputation_subject:
  subject_type:
  subject_id:
  owner_reference:
  hypervisor_reference:
  service_role:
  profile_version:
```

The subject identifier SHALL be immutable.

A change of owner does not erase the subject's historical Reputation.

## 6. Profile Structure

A Reputation Profile contains:

```yaml
reputation_profile:
  subject:
  profile_state:
  dimensions:
  dimension_confidence:
  advisory_overall_score:
  active_flags:
  historical_flags:
  recent_events_root:
  full_history_reference:
  last_updated_epoch:
  profile_version:
```

## 7. Structured Profile

The Reputation Profile SHALL expose independent dimensions.

Initial common dimensions include:

- `AVAILABILITY`
- `RELIABILITY`
- `PROTOCOL_COMPLIANCE`
- `ACCOUNTING_CONSISTENCY`
- `EVIDENCE_INTEGRITY`
- `RECOVERY_RELIABILITY`

Role-specific profiles MAY add further dimensions.

## 8. Availability

Availability represents whether the subject was reachable and able to perform its expected role.

Availability MAY include:

- successful protocol contact;
- assigned-duty availability;
- Session acceptance;
- heartbeat success;
- service-response success;
- synchronization availability.

Availability SHALL not be based only on self-reported uptime.

## 9. Reliability

Reliability represents whether accepted responsibilities were completed correctly and consistently.

Examples include:

- completed Sessions;
- delivered results;
- completed Consensus duties;
- completed Validation assignments;
- successful Registry responses;
- successful recovery after interruption.

## 10. Protocol Compliance

Protocol Compliance represents adherence to required protocol behavior.

Examples include:

- valid message schemas;
- valid signatures;
- correct state transitions;
- timeout handling;
- retry behavior;
- Session close behavior;
- supported protocol versions;
- correct evidence publication.

## 11. Accounting Consistency

Accounting Consistency represents the reliability of economic and Usage Reporting behavior.

Examples include:

- consistent Usage Reports;
- Deposit-limit compliance;
- matching checkpoints;
- correct Settlement claims;
- absence of duplicate billing;
- correct fixed-price reporting;
- disclosure of unknown or opaque usage.

Unknown usage SHALL not be treated as incorrect merely because it cannot be independently verified.

## 12. Evidence Integrity

Evidence Integrity represents whether the subject produces truthful, internally consistent protocol evidence.

Examples include:

- non-conflicting signed records;
- valid report hashes;
- valid proof responses;
- accurate manifests;
- consistent Session histories;
- non-fabricated Validation evidence.

Evidence Integrity is a critical dimension.

## 13. Recovery Reliability

Recovery Reliability represents behavior after operational failure.

It MAY include:

- successful reconnect;
- correct Session recovery;
- Runtime recovery;
- State Sync success;
- restoration from a valid checkpoint;
- correct failure reporting;
- completion of pending Settlement after recovery.

Recovery does not erase the underlying failure event.

## 14. Advisory Overall Score

A Reputation Profile MAY expose an advisory Overall Score.

The Overall Score:

- is calculated from role-specific dimensions;
- is intended for display and broad filtering;
- SHALL NOT replace individual dimensions;
- SHALL NOT hide critical flags;
- SHALL NOT be used where a role-specific dimension is required.

The canonical Reputation Profile is the structured profile, not the Overall Score.

## 15. Overall Score Calculation

The initial advisory formula MAY use:

```text
OverallScore
=
Σ (
    DimensionScore(d)
    ×
    DimensionWeight(d)
)
/
Σ DimensionWeight(d)
```

Each Profile Type SHALL define its own Dimension Weights.

Critical-dimension caps MAY limit the displayed Overall Score.

## 16. Critical Dimension Cap

A high average SHALL not conceal a critical weakness.

Example:

```text
Availability = 0.98
Reliability = 0.97
Accounting Consistency = 0.20
```

The Profile SHALL not appear highly trustworthy merely because the first two dimensions are strong.

Profile-specific rules MAY cap Overall Score or derive a warning state when a critical dimension is below threshold.

## 17. Score Range

Reputation dimension scores SHALL use deterministic fixed-point values in:

`0.0 <= Score <= 1.0`

Interpretation MAY be displayed approximately as:

| Score | General interpretation |
| --- | --- |
| `0.90-1.00` | Strong |
| `0.75-0.90` | Acceptable |
| `0.50-0.75` | Developing or inconsistent |
| `0.25-0.50` | Poor |
| `0.00-0.25` | Critical |

These labels are informational.

Role-specific eligibility thresholds are defined separately.

## 18. Score and Confidence Separation

Every dimension SHALL expose:

`Dimension Score`

`+`

`Evidence Confidence`

A score based on little evidence SHALL not be presented as equally reliable to a score based on sustained history.

Example:

```text
Availability Score: 1.00
Confidence: 0.08
```

means the Service has succeeded so far but has little history.

## 19. New Profile Prior

A new Profile begins with:

```text
Score = 0.50
Confidence = 0.00
State = INSUFFICIENT_DATA
```

The neutral prior SHALL not be interpreted as proven average performance.

The Profile gains confidence through qualifying evidence.

## 20. Evidence Accumulators

For each dimension d, the engine maintains:

`PositiveEvidenceMass(d)`

`NegativeEvidenceMass(d)`

Each finalized Reputation Event contributes evidence mass according to:

- event class;
- severity;
- confidence;
- role relevance;
- freshness;
- duplication rules.

## 21. Raw Dimension Score

An initial deterministic model is:

```text
RawScore(d)
=
PriorPositiveMass
+
PositiveEvidenceMass(d)
----------------------------------------------
PriorPositiveMass
+
PriorNegativeMass
+
PositiveEvidenceMass(d)
+
NegativeEvidenceMass(d)
```

The protocol SHALL define fixed-point precision and rounding.

## 22. Dimension Confidence

```text
EvidenceConfidence(d)
=
min(
    1,
    TotalEvidenceMass(d)
    /
    TargetEvidenceMass(d)
)
```

where:

```text
TotalEvidenceMass(d)
=
PositiveEvidenceMass(d)
+
NegativeEvidenceMass(d)
```

Target Evidence Mass is role-specific.

## 23. Effective Dimension Score

The effective score MAY be calculated as:

```text
EffectiveScore(d)
=
PriorScore
+
EvidenceConfidence(d)
×
(
    RawScore(d)
    -
    PriorScore
)
```

This prevents one or two events from producing artificial certainty.

## 24. Reputation Event

All score changes SHALL originate from finalized Reputation Events.

```yaml
reputation_event:
  event_id:
  subject_type:
  subject_id:
  profile_dimension:
  event_class:
  direction:
  severity:
  evidence_confidence:
  evidence_root:
  source_type:
  source_reference:
  observed_epoch:
  finalized_epoch:
  decay_policy:
  propagation_policy:
  event_version:
```

## 25. Event Direction

A Reputation Event has one of:

- `POSITIVE`
- `NEGATIVE`
- `NEUTRAL`

Neutral events may affect:

- Confidence;
- profile history;
- active flags;
- eligibility review;

without directly changing a score.

## 26. Event Classes

Initial Event Classes include:

- `AVAILABILITY_EVENT`
- `EXECUTION_EVENT`
- `PROTOCOL_EVENT`
- `ACCOUNTING_EVENT`
- `EVIDENCE_EVENT`
- `RECOVERY_EVENT`
- `CERTIFICATION_EVENT`
- `SECURITY_EVENT`
- `FEEDBACK_EVENT`
- `ADMINISTRATIVE_EVENT`

## 27. Event Severity

Initial severity levels are:

- `INFORMATIONAL`
- `MINOR`
- `MODERATE`
- `MAJOR`
- `CRITICAL`

Severity SHALL be determined by a versioned event rule.

A reporter SHALL not choose arbitrary economic severity.

## 28. Evidence Confidence Classes

Initial confidence classes are:

- `FINALIZED_PROTOCOL`
- `CRYPTOGRAPHIC`
- `REPRODUCIBLE`
- `MULTI_SOURCE`
- `STATISTICAL`
- `OBSERVATIONAL`
- `SUBJECTIVE`

## 29. FINALIZED_PROTOCOL

Derived directly from finalized canonical state.

Examples include:

- finalized Settlement;
- finalized Validator participation;
- finalized suspension;
- finalized Certification transition;
- finalized Penalty Operation.

This is the strongest ordinary evidence class.

## 30. CRYPTOGRAPHIC

Supported by objectively verifiable signed evidence.

Examples include:

- conflicting signed Usage Reports;
- double-signing;
- conflicting Registry manifests;
- forged or invalid signatures;
- duplicate signed records.

## 31. REPRODUCIBLE

Another eligible participant can reproduce the result using defined inputs and rules.

Examples include:

- invalid artifact hash;
- deterministic protocol failure;
- missing required object;
- reproducible accounting mismatch.

## 32. MULTI_SOURCE

Supported by several sufficiently independent observation sources.

Examples include:

- repeated service unavailability;
- independent failed challenge attempts;
- correlated Consumer failures;
- repeated external observations.

## 33. STATISTICAL

Derived from a pattern rather than one conclusive event.

Examples include:

- abnormal failure rate;
- reporting anomaly;
- unusual latency distribution;
- repeated discrepancy against comparable Endpoints.

Statistical evidence may trigger review.

It SHALL not automatically prove misconduct.

## 34. OBSERVATIONAL

Reported by one protocol participant using ordinary operational evidence.

Examples include:

- connection timeout;
- poor response quality;
- incomplete Session;
- local transport error.

Observational evidence has bounded direct impact.

## 35. SUBJECTIVE

Represents opinion or preference.

Examples include:

- output style;
- perceived quality;
- user satisfaction;
- usefulness for one task.

Subjective evidence SHALL have limited canonical weight.

## 36. Event Impact

An event's evidence contribution MAY be calculated from:

```text
EventMass
=
BaseEventWeight
×
SeverityFactor
×
EvidenceConfidenceFactor
×
RoleRelevanceFactor
```

All factors SHALL be bounded and versioned.

## 37. No Self-Assigned Event Weight

Event submitters provide evidence.

They do not choose:

- final Severity Factor;
- canonical Event Mass;
- propagation amount;
- Reputation consequence.

The State Machine or authorized Epoch process derives these values.

## 38. Duplicate Evidence

The same underlying incident SHALL not produce unlimited Reputation impact through repeated submission.

Duplicate detection SHALL use:

- Session ID;
- Assignment ID;
- Request ID;
- challenge ID;
- evidence hash;
- incident root;
- operation reference.

## 39. Correlated Failures

Many events caused by one external incident SHOULD be grouped.

Examples include:

- regional network outage;
- upstream Provider outage;
- Consensus halt;
- Registry-wide protocol defect;
- cloud-provider failure.

Correlated events may reduce current Health strongly without being counted as independent misconduct incidents.

## 40. Current Health and Long-Term Reputation

Current operational Health and long-term Reputation are related but distinct.

Health represents current condition.

Reputation represents accumulated history.

A Service MAY have:

`High historical Reputation`

`+`

`Current degraded Health`

or:

`Low historical confidence`

`+`

`Current healthy operation`

## 41. Profile State

A Reputation Profile MAY derive one of:

- `INSUFFICIENT_DATA`
- `ESTABLISHING`
- `NORMAL`
- `WATCH`
- `DEGRADED`
- `CRITICAL`
- `DISQUALIFIED`
- `RETIRED`

Profile State is role-specific and derived from:

- dimension scores;
- evidence confidence;
- active flags;
- current Health;
- objective misconduct.

## 42. INSUFFICIENT_DATA

The Profile lacks sufficient evidence for a reliable assessment.

This state is not positive or negative.

## 43. ESTABLISHING

The subject is accumulating evidence and has no critical incidents.

New Services typically remain Establishing until role-specific maturity or confidence requirements are met.

## 44. NORMAL

The subject has sufficient evidence and satisfies the role's ordinary Reputation requirements.

## 45. WATCH

Recent concerns exist, but evidence is not sufficient for severe classification.

The state MAY trigger:

- additional monitoring;
- Triggered Validation;
- shorter challenge intervals;
- Marketplace warning.

## 46. DEGRADED

Material recent failures or low dimension scores exist.

The subject may remain operational with reduced eligibility or public warning.

## 47. CRITICAL

Serious failures or objective integrity concerns exist.

The subject may become:

- ineligible;
- suspended;
- removed from recommendations;
- subject to additional verification.

## 48. DISQUALIFIED

The subject cannot satisfy role eligibility because of an active disqualifying event.

Disqualification SHALL derive from a defined protocol rule.

Reputation alone SHALL not create an undefined permanent ban.

## 49. RETIRED

The subject is no longer active.

Its Reputation history remains available.

Retirement does not erase prior events.

## 50. Hypervisor Reputation Profile

The Hypervisor Profile MAY contain:

- `NETWORK_AVAILABILITY`
- `SERVICE_COORDINATION_RELIABILITY`
- `HYPERVISOR_PROTOCOL_COMPLIANCE`
- `KEY_AND_IDENTITY_INTEGRITY`
- `RECOVERY_RELIABILITY`
- `CHILD_SERVICE_RISK`

## 51. Hypervisor Network Availability

Measures whether the Hypervisor:

- remains reachable;
- maintains protocol connections;
- performs required routing;
- supports registered Services;
- restores connectivity correctly.

## 52. Service Coordination Reliability

Measures whether the Hypervisor correctly:

- registers Services;
- routes Sessions;
- applies Service state;
- handles Runtime disconnects;
- forwards Usage Reports;
- enforces Deposit limits;
- initiates appropriate Settlement.

## 53. Hypervisor Key and Identity Integrity

Includes:

- valid identity use;
- key-rotation history;
- conflicting signatures;
- unauthorized Service registration;
- identity-compromise evidence.

Critical identity incidents SHALL remain historically visible.

## 54. Consensus Service Reputation Profile

The Consensus Profile MAY contain:

- `VOTE_PARTICIPATION`
- `SIGNING_RELIABILITY`
- `PROPOSAL_CORRECTNESS`
- `SYNCHRONIZATION_RELIABILITY`
- `CONSENSUS_RECOVERY`
- `CONSENSUS_INTEGRITY`

## 55. Consensus Participation

Consensus participation SHALL derive from canonical CometBFT evidence.

Self-reported uptime SHALL not replace:

- expected votes;
- valid votes;
- proposer duties;
- synchronization evidence.

## 56. Consensus Integrity

Consensus Integrity includes:

- absence of double-signing;
- absence of conflicting votes;
- valid Validator Set behavior;
- valid state commitments;
- correct consensus-key usage.

Confirmed double-signing creates a permanent historical flag.

## 57. Registry Service Reputation Profile

The Registry Profile MAY contain:

- `REGISTRY_AVAILABILITY`
- `PROOF_SUCCESS`
- `COMPLETENESS_RELIABILITY`
- `OBJECT_INTEGRITY`
- `SYNCHRONIZATION_RELIABILITY`
- `QUERY_SERVICE_RELIABILITY`

## 58. Registry Completeness

Completeness Reputation SHALL derive from:

- required profile checks;
- randomized challenge results;
- segment-root consistency;
- synchronization lag;
- missing-object history.

Declared storage size alone SHALL not improve Reputation.

## 59. Registry Object Integrity

Object Integrity includes:

- correct hashes;
- valid manifests;
- valid canonical references;
- non-conflicting signed roots;
- correct object serving.

Signed manifest equivocation is a critical event.

## 60. Validation Service Reputation Profile

The Validation Profile MAY contain:

- `ASSIGNMENT_RELIABILITY`
- `REPORT_COMPLETENESS`
- `EVIDENCE_QUALITY`
- `REPORT_CONSISTENCY`
- `VALIDATION_INTEGRITY`
- `VALIDATION_TIMELINESS`

## 61. Validation Assignment Reliability

Measures whether the Validator:

- responds to accepted assignments;
- formally releases assignments when necessary;
- completes accepted work;
- publishes required reports;
- avoids repeated abandonment.

Declining an unaccepted assignment SHALL not reduce Reputation.

## 62. Validation Report Quality

Report-quality Reputation MAY consider:

- evidence completeness;
- observation clarity;
- correct distinction between fact and interpretation;
- protocol schema compliance;
- useful issue descriptions;
- privacy compliance;
- conclusion consistency.

A favorable conclusion SHALL not receive greater Reputation weight merely for being favorable.

## 63. Validation Integrity

Critical Validation events include:

- fabricated evidence;
- conflicting signed reports;
- self-validation;
- hidden assignment resale;
- intentional false response claims;
- collusion supported by objective evidence.

Subjective disagreement with another Validator is not an integrity violation.

## 64. Endpoint Reputation Profile

The Endpoint Profile MAY contain:

- `ENDPOINT_AVAILABILITY`
- `REQUEST_EXECUTION_RELIABILITY`
- `RESULT_DELIVERY_RELIABILITY`
- `PROTOCOL_COMPLIANCE`
- `USAGE_REPORTING_CONSISTENCY`
- `SETTLEMENT_CONSISTENCY`
- `CERTIFICATION_HISTORY`
- `RECOVERY_RELIABILITY`
- `VALIDATION_REPORT_AVAILABILITY`
- `VALIDATION_REPORT_RETENTION`
- `VALIDATION_REPORT_INTEGRITY`
- `VALIDATION_DISCLOSURE_RELIABILITY`

## 65. Endpoint Availability

Endpoint Availability MAY use:

- Session acceptance;
- successful connection;
- request execution;
- Maintenance Validation availability;
- failure and recovery evidence.

Rejected requests outside advertised availability SHALL not count as failures.

## 66. Request Execution Reliability

Measures whether accepted requests:

- begin correctly;
- remain within limits;
- produce results;
- respect cancellation;
- handle failures;
- avoid duplicate execution.

## 67. Result Delivery Reliability

Measures:

- result delivery;
- artifact integrity;
- streaming completion;
- response-hash consistency;
- completion status;
- partial-result behavior.

## 68. Endpoint Usage Reporting Consistency

Includes:

- timely Usage Reports;
- correct report sequence;
- stable Accounting Mode;
- maximum-charge compliance;
- consistency with accepted checkpoints;
- proper unknown-value disclosure.

`PROXY_OPAQUE` usage is not negative when correctly declared.

## 69. Certification History

Certification is a Reputation input but does not replace Reputation.

The Profile SHALL preserve:

- Certification success;
- observations;
- degradation;
- expiration;
- revocation;
- recovery.

A new Certification SHALL not delete previous failures.

## 69A. Validation Report Custody Reputation

Endpoint custody Reputation SHALL distinguish:

- one temporary retrieval outage, which normally affects current Health only;
- repeated unavailability, which reduces report availability confidence;
- report loss after migration or storage failure, which reduces retention reliability;
- deliberate withholding or unauthorized access restriction, which creates a strong negative disclosure event;
- content that fails the committed hash, which creates a critical integrity event;
- successful restoration, which repairs current availability without erasing historical events.

An optional Registry mirror may preserve report access, but it does not erase an Endpoint origin-custody failure. A Hypervisor-wide storage incident MAY also create a Hypervisor Reputation Event when objective evidence binds the failure to shared infrastructure.

## 70. Protocol Evidence First

Canonical Reputation SHOULD prioritize:

1. finalized protocol events;
2. cryptographic evidence;
3. reproducible evidence;
4. independent repeated observations;
5. statistical evidence;
6. single observations;
7. subjective feedback.

Lower evidence levels SHALL not override stronger contradictory evidence automatically.

## 71. Consumer Feedback

Consumers MAY submit feedback about completed Sessions.

Feedback SHALL bind to:

- Session ID;
- Consumer identity;
- Endpoint ID;
- feedback category;
- optional evidence;
- timestamp;
- signature.

One Session SHALL authorize at most one active feedback record per Consumer.

## 72. Feedback Categories

Initial categories MAY include:

- `SUCCESSFUL`
- `FAILED`
- `UNHELPFUL`
- `HIGH_QUALITY`
- `LOW_QUALITY`
- `SLOW`
- `ACCOUNTING_CONCERN`
- `PROTOCOL_CONCERN`
- `OTHER`

Free-form commentary MAY remain off-chain or in Registry.

## 73. Feedback Weight

Subjective Consumer feedback SHALL have bounded effect.

Recommended principle:

`Maximum direct subjective contribution <= 10% of Endpoint advisory Reputation influence`

Objective Session evidence remains primary.

## 74. Feedback Is Not a Penalty Operation

One negative review SHALL not:

- slash Stake;
- forfeit Bond;
- revoke Certification;
- suspend an Endpoint;
- prove fraud.

Feedback MAY:

- affect a bounded user-feedback dimension;
- contribute to statistical patterns;
- trigger review;
- trigger Validation when thresholds are met.

## 75. Self-Feedback

Feedback from a Consumer in the same known control relationship as the Endpoint SHALL not count as independent feedback.

Unknown ownership relationships cannot always be detected.

The protocol SHALL use only finalized control relationships for automatic exclusion.

## 76. Feedback Manipulation

Possible manipulation includes:

- self-generated Sessions;
- feedback farms;
- repeated low-value transactions;
- coordinated false reviews;
- retaliatory feedback.

Protection MAY include:

- verified Session requirement;
- one feedback per Session;
- minimum Session significance;
- control-group filtering;
- statistical anomaly detection;
- bounded subjective weight.

## 77. Negative Evidence Propagation

Negative evidence MAY propagate from a Service to its parent Hypervisor when it indicates:

- shared infrastructure failure;
- Hypervisor routing failure;
- operator-level misconduct;
- key compromise;
- repeated cross-Service problems;
- failure to supervise registered Services.

## 78. Upward Propagation

Conceptually:

```text
Child Service Negative Event
        ->
Role-Specific Service Profile
        ->
Bounded Parent Hypervisor Risk Event
```

The propagation factor SHALL be less than or equal to the original event weight.

## 79. No Automatic Positive Downward Propagation

Positive Hypervisor or operator history SHALL NOT automatically improve a new Service or Endpoint.

Therefore:

```text
Reliable Hypervisor
!=
Automatically Reliable New Endpoint
Good Registry
!=
Automatically Good Validation Service
```

Every new Service SHALL establish its own role-specific Reputation.

## 80. Positive Upward Contribution

Sustained positive Service history MAY improve the parent Hypervisor's Service Coordination or operational-history confidence.

This contribution SHALL be bounded.

It SHALL not create high confidence from one successful child Service alone.

## 81. Downward Negative Propagation

A parent-level negative event MAY affect child Services only when the event objectively creates shared risk.

Examples include:

- Hypervisor identity compromise;
- shared key compromise;
- corrupted routing layer;
- operator suspension;
- shared state divergence.

Generic poor Hypervisor Reputation SHALL not blindly overwrite all child profiles.

## 82. No Cross-Role Reputation Laundering

A participant SHALL not use strong Reputation in one role to erase failure in another.

Examples:

```text
Strong Consensus Reputation
Does Not Erase Endpoint Accounting Fraud
Strong Registry Reputation
Does Not Excuse Fabricated Validation Reports
```

## 83. Ownership Transfer

A Service or Endpoint ownership transfer SHALL preserve:

- subject Reputation;
- historical flags;
- event history;
- previous owner references.

The new owner MAY build new operator history.

The transferred subject does not become new merely because its beneficiary changed.

## 84. New Identity

A newly registered subject begins with:

- neutral prior;
- zero Confidence;
- no inherited positive Reputation;
- zero role-specific Maturity where applicable.

A participant cannot copy Reputation to a new Service Identity.

## 85. Identity Cycling

Repeated retirement and creation of new identities MAY be visible through:

- owner Wallet;
- Hypervisor;
- Reward Beneficiary;
- Known Control Group;
- configuration history;
- service-transfer history.

The protocol cannot perfectly link undisclosed ownership.

New identities still receive no inherited positive Reputation.

## 86. Event Freshness

Operational events MAY decay in influence with age.

The decay policy SHALL depend on Event Class.

Examples:

- ordinary downtime decays;
- successful recovery decays;
- old latency events decay;
- critical integrity events remain historical;
- Certification status follows its own lifecycle.

## 87. Operational Decay

An initial operational decay model MAY use:

```text
DecayedEventMass
=
OriginalEventMass
×
DecayFactor(age)
```

The function SHALL be deterministic and role-specific.

## 88. Decay Toward Neutrality

When operational evidence ages, the effective dimension score SHOULD gradually move toward the neutral prior unless replaced by recent evidence.

Decay SHALL not automatically move a Profile toward perfect Reputation.

Lack of recent failures is not equivalent to recent successful operation.

## 89. Critical Historical Events

Certain events SHALL not disappear through ordinary decay.

Examples include:

- double-signing;
- fabricated evidence;
- conflicting signed Usage Reports;
- signed Registry equivocation;
- deliberate Settlement fraud;
- confirmed identity compromise;
- critical governance signature conflict.

These events remain in `historical_flags`.

## 90. Active and Historical Flags

Profiles distinguish:

`ACTIVE_FLAGS`

`HISTORICAL_FLAGS`

An Active Flag currently affects:

- status;
- eligibility;
- Marketplace display;
- Service operation.

A Historical Flag remains visible after the active consequence ends.

## 91. Recovery

Ordinary Reputation damage SHALL be recoverable through sustained successful behavior.

Recovery MAY require:

- minimum successful-event count;
- qualifying operational period;
- successful Service Verification;
- successful Session completion;
- no repeated similar failures;
- applicable suspension completion.

## 92. Recovery Rate Limit

A Profile SHALL not recover from major failure through one trivial success.

The protocol SHALL define:

- maximum positive score movement per Epoch;
- minimum recovery evidence;
- cooldown periods;
- repeated-failure penalties.

## 93. Repeated Failure Escalation

Repeated similar failures MAY receive increasing significance.

Conceptually:

```text
RepeatedFailureFactor
=
min(
    MaximumEscalation,
    1
    +
    RepetitionIncrement
)
```

The repetition window and event similarity rules SHALL be versioned.

## 94. Successful Recovery Event

Successful recovery MAY create both:

- a positive Recovery Reliability event;
- continued visibility of the original failure.

Therefore:

```text
Failure
+
Successful Recovery
!=
Failure Erased
```

It means the subject failed and recovered correctly.

## 95. Reputation and Eligibility

Service-specific protocols MAY use Reputation dimensions for eligibility.

Examples include:

- Consensus Candidate eligibility;
- Registry reward eligibility;
- Validation assignment eligibility;
- Marketplace warnings;
- Certification review triggers.

The relevant protocol SHALL specify exact thresholds.

## 96. Dimension-Specific Eligibility

Eligibility SHOULD use the relevant dimensions rather than only Overall Score.

Example:

Validation Service eligibility

may require:

- Validation Integrity above threshold;
- Assignment Reliability above threshold;
- no active fabrication flag.

A strong Availability score SHALL not compensate for failed Validation Integrity.

## 97. Reputation and Rewards

Reputation MAY influence bounded quality or reliability factors in reward formulas.

Reputation SHALL NOT:

- create rewards without work;
- increase the size of a fixed reward pool;
- override Duty Proof;
- make duplicate evidence rewardable;
- guarantee selection.

## 98. Reputation and Penalties

Reputation scoring does not itself confiscate Q.

Stake or Bond penalties require:

- a defined violation;
- objective evidence where required;
- a separate Penalty Operation;
- an applicable economic rule.

A low score is not automatically a slashable offense.

## 99. Reputation and Certification

Endpoint Certification and Reputation are separate.

Certification represents bounded Validation evidence for a Configuration Hash.

Reputation represents behavior over time.

A newly Certified Endpoint may still have:

`Low Reputation Confidence`

A previously reliable Endpoint may become:

`DEGRADED`

after recent failures.

## 100. Reputation and Suspension

Suspension MAY create an Active Reputation Flag.

However, the reason for suspension remains authoritative.

A Reputation Profile SHALL not invent a suspension reason from a low aggregate score.

## 101. Canonical Update Timing

Reputation Profiles SHOULD be updated through deterministic Epoch processing.

The Epoch process SHALL:

1. freeze eligible events;
2. deduplicate evidence;
3. classify correlated incidents;
4. apply role-specific event rules;
5. update evidence accumulators;
6. apply decay;
7. calculate scores and Confidence;
8. derive profile state and flags;
9. commit new Profile roots.

Critical objective events MAY trigger immediate flags before the next full Epoch update.

## 102. Event Finalization Delay

Some events MAY require a confirmation or challenge period.

Examples include:

- unavailability claims;
- Consumer complaints;
- statistical anomalies;
- multi-source failures.

Cryptographically objective evidence MAY finalize more quickly.

## 103. Event Challenge

A participant MAY challenge an objective processing error such as:

- wrong subject;
- duplicate event;
- invalid evidence;
- wrong Event Class;
- incorrect propagation;
- incorrect formula version.

A participant cannot remove valid evidence merely by disagreeing with its meaning.

## 104. Corrections

Finalized Reputation history SHALL not be silently rewritten.

An error is corrected through a new correction event referencing:

- original Event ID;
- error class;
- corrected values;
- authorization;
- resulting score adjustment.

## 105. Reputation Profile Snapshot

At every Reputation update, the protocol MAY create:

```yaml
reputation_profile_snapshot:
  subject_type:
  subject_id:
  epoch:
  profile_version:
  dimensions:
  confidence:
  overall_score:
  profile_state:
  active_flags:
  historical_flags:
  positive_evidence_root:
  negative_evidence_root:
  recent_event_root:
  previous_profile_hash:
```

## 106. Ledger Storage

The Ledger SHALL store enough information to verify:

- current Profile;
- Profile version;
- score and Confidence;
- flags;
- event commitments;
- Profile history links.

Large evidence objects MAY remain in Registry.

## 107. Registry Storage

Registry Services MAY store:

- full Reputation Events;
- supporting evidence;
- challenge records;
- correction records;
- historical Profile snapshots;
- bounded Marketplace Summary metadata derived from canonical Profile fields.

Registry storage SHALL preserve canonical hashes.

## 108. Privacy

Reputation evidence SHALL minimize unnecessary disclosure.

Preferred evidence includes:

- hashes;
- Session references;
- event classes;
- timing;
- signed summaries;
- proof references.

Raw prompts, outputs and private artifacts SHALL not be published merely to support a routine Reputation event.

## 109. Restricted Evidence

Sensitive evidence MAY be:

- encrypted;
- access-controlled;
- committed by hash;
- reviewed through a specialized verification process.

The public Profile MAY expose the event class and consequence without exposing private content.

## 110. Marketplace Presentation

Marketplace clients SHOULD display:

- role-specific Profile;
- Confidence;
- Profile State;
- recent events;
- active warnings;
- Certification;
- relevant operational dimensions;
- historical critical flags.

The UI SHALL not display only a single star rating while hiding the rest of the Profile.

Reputation MAY also expose a bounded Marketplace Summary derived from the canonical structured Profile.

The Marketplace Summary MAY include:

- display labels;
- bounded explanation snippets;
- warning references;
- selected dimension excerpts;
- Certification and Profile references needed for presentation.

The Marketplace Summary SHALL NOT define a canonical Marketplace rank, recommendation tier or local composite score.

It is a presentation surface for Marketplace clients, not a replacement for canonical Reputation state.

## 111. User Filtering

Consumers MAY filter Endpoints by:

- Availability;
- Reliability;
- Accounting Consistency;
- Certification;
- Confidence;
- recent failure rate;
- Proxy disclosure;
- active warnings.

Different Consumers may prefer different risk tradeoffs.

## 112. Reputation Explanation

Every displayed score SHOULD include a human-readable explanation.

Example:

Endpoint availability is high based on 240 completed Sessions.
Accounting confidence is limited because upstream token usage is opaque.
One major Session recovery failure occurred 12 Epochs ago.

The explanation is informational.

The structured Profile remains canonical.

## 113. No Global Ranking Requirement

The protocol SHALL not require one canonical global ranking of all participants.

Marketplace implementations MAY create ranking algorithms using public Profile data.

Such rankings SHALL distinguish themselves from canonical protocol Reputation.

## 114. Local Risk Models

Consumers and Marketplace clients MAY apply local risk models.

A local model may emphasize:

- latency;
- accounting transparency;
- Certification;
- price;
- availability;
- privacy;
- historical integrity.

Local scores SHALL not modify canonical Reputation.

## 115. Governance Events

Objective governance events MAY be stored in participant history.

Examples include:

- signed vote;
- conflicting Governance signatures;
- readiness accuracy;
- emergency authorization participation.

The MVP SHOULD NOT create one ideological Governance Reputation score.

## 116. Profile Versioning

Reputation formulas SHALL be versioned.

Every Profile Snapshot SHALL identify:

- event-rule version;
- score-formula version;
- propagation version;
- decay version;
- Profile schema version.

## 117. Formula Upgrade

A formula upgrade SHALL affect future Profile calculations according to declared migration rules.

Historical events remain immutable.

A new formula MAY recalculate current derived scores from preserved event history when the upgrade explicitly defines this behavior.

## 118. No Hidden Formula

Canonical Reputation formulas and parameters SHALL be public.

The protocol SHALL expose:

- Event weights;
- Severity factors;
- Confidence factors;
- decay functions;
- propagation rules;
- thresholds;
- Profile weights.

Marketplace-local algorithms may remain implementation-specific.

## 119. Fixed-Point Arithmetic

All canonical Reputation calculations SHALL use deterministic fixed-point arithmetic.

The protocol SHALL define:

- precision;
- rounding;
- overflow behavior;
- accumulator limits;
- decay rounding;
- score clamping.

Floating-point arithmetic SHALL not determine canonical state.

## 120. Anti-Gaming Rules

The Reputation Engine SHALL resist:

- identity multiplication;
- self-generated traffic;
- feedback farming;
- trivial successful Sessions;
- event replay;
- report duplication;
- role laundering;
- retirement and recreation;
- low-value artificial work;
- collusive validation;
- repeated strategic unavailability.

## 121. Session Significance

The protocol MAY assign less Reputation mass to economically or computationally trivial Sessions.

This prevents operators from creating many insignificant successful Sessions to overwhelm a few meaningful failures.

Session significance MAY consider:

- accepted charge;
- task class;
- execution duration;
- Capability;
- output significance;
- independent counterparties.

## 122. Counterparty Diversity

Reputation confidence MAY consider independent counterparty diversity.

One thousand Sessions with one related Consumer SHALL not provide the same confidence as Sessions with many independent Consumers.

Known Control Group relationships SHALL be considered where available.

## 123. Maximum Event Contribution

One ordinary event SHALL have a bounded maximum impact.

Critical objective integrity events MAY use separate hard flags rather than an unbounded numeric score change.

## 124. Role Isolation

Every event SHALL identify the role it directly concerns.

An Endpoint request failure SHALL not directly reduce:

- Consensus Signing Reliability;
- Registry Completeness;
- Validation Evidence Quality.

Any propagation must use an explicit rule.

## 125. Retirement

When a subject retires:

- its Profile becomes `RETIRED`;
- active operational decay may stop or follow archival rules;
- historical flags remain;
- Profile history remains queryable;
- its Reputation cannot be transferred to a replacement identity.

## 126. Reactivation

A retired subject MAY reactivate only when its role protocol permits it.

Reactivation SHALL preserve:

- historical Reputation;
- flags;
- prior owner history;
- previous failures.

A long retirement MAY reduce current Confidence.

## 127. Profile Metrics

The network SHOULD publish aggregate metrics including:

- Profile count by type;
- Profile State distribution;
- score and Confidence distributions;
- event volume by class;
- critical-flag count;
- recovery rates;
- repeated-failure rates;
- feedback-to-objective-evidence ratio;
- propagation-event count;
- new-identity rate;
- retired-subject count.

## 128. Reputation Event Sources

Initial protocol event sources MAY include:

- Session Protocol;
- Settlement Engine;
- Consensus evidence;
- Registry challenges;
- Validation assignments;
- Validation Reports;
- Certification transitions;
- Service Verification;
- Hypervisor connectivity;
- Consumer feedback;
- Penalty Operations;
- recovery procedures.

## 129. Epoch Tasks

Reputation processing SHOULD include:

- Freeze Reputation Events
- Validate Event Evidence
- Deduplicate Events
- Group Correlated Incidents
- Classify Event Severity
- Apply Role Relevance
- Apply Event Propagation
- Update Evidence Mass
- Apply Reputation Decay
- Calculate Dimension Scores
- Calculate Confidence
- Derive Profile States
- Update Flags
- Commit Reputation Profile Roots
- Publish Reputation Metrics

## 130. Error Codes

The protocol SHALL define at least:

- `REPUTATION_SUBJECT_NOT_FOUND`
- `REPUTATION_PROFILE_TYPE_INVALID`
- `REPUTATION_EVENT_INVALID`
- `REPUTATION_EVENT_DUPLICATE`
- `REPUTATION_EVIDENCE_INVALID`
- `REPUTATION_EVENT_ROLE_MISMATCH`
- `REPUTATION_EVENT_SEVERITY_INVALID`
- `REPUTATION_PROPAGATION_INVALID`
- `REPUTATION_CORRECTION_INVALID`
- `REPUTATION_PROFILE_VERSION_MISMATCH`
- `REPUTATION_SCORE_OUT_OF_RANGE`
- `REPUTATION_CONFIDENCE_OUT_OF_RANGE`
- `REPUTATION_FORMULA_VERSION_UNSUPPORTED`
- `REPUTATION_EVENT_ALREADY_PROCESSED`

## 131. Idempotency

Reputation processing SHALL be idempotent.

The same Event ID SHALL not affect a Profile more than once.

Repeating an Epoch task with the same:

- event set;
- formula version;
- previous Profile;

SHALL produce the same new Profile.

## 132. MVP Requirements

The MVP SHALL implement:

- separate Hypervisor Profile;
- separate Consensus Service Profile;
- separate Registry Service Profile;
- separate Validation Service Profile;
- separate Endpoint Profile;
- structured dimensions;
- score and Confidence separation;
- neutral prior;
- finalized Reputation Events;
- objective evidence hierarchy;
- role-specific event rules;
- negative upward propagation;
- no automatic positive downward inheritance;
- bounded subjective feedback;
- operational decay;
- permanent historical critical flags;
- repeated-failure escalation;
- gradual recovery;
- deterministic Epoch updates;
- Profile snapshots;
- Registry evidence storage;
- Marketplace presentation;
- fixed-point arithmetic;
- complete event history.

## 133. Deferred Features

The MVP MAY postpone:

- private Reputation proofs;
- zero-knowledge feedback;
- formal proof-of-personhood;
- cross-network Reputation;
- transferable operator credentials;
- machine-learning Reputation formulas;
- hidden Marketplace rankings;
- decentralized moderation panels;
- universal dispute arbitration;
- binding Governance Reputation;
- insurance pricing derived from Reputation;
- portable Reputation across unrelated identities.

## 134. Open Protocol Parameters

The following remain configurable:

- dimension weights;
- prior evidence mass;
- Target Evidence Mass;
- Event Base Weights;
- Severity Factors;
- Evidence Confidence Factors;
- propagation factors;
- decay rates;
- repeated-failure windows;
- escalation limits;
- recovery-rate limits;
- critical-dimension thresholds;
- Profile State thresholds;
- subjective-feedback cap;
- Session significance rules;
- counterparty-diversity rules;
- challenge window;
- correction rules;
- Profile update frequency.

## 135. Reputation Invariants

```text
Reputation Is a Structured Profile
Not a Universal Score
Score Without Confidence
Does Not Represent Established Reputation
One Role's Positive History
Does Not Erase Another Role's Failure
New Services
Do Not Inherit Positive Reputation Automatically
Negative Evidence May Propagate Upward
Only Through Explicit Rules
Subjective Feedback
Cannot Independently Trigger Severe Economic Penalties
Low Reputation
Does Not Automatically Slash Stake
Critical Historical Evidence
Does Not Disappear Through Ordinary Decay
```

## 136. Security Invariants

- Reputation Events are replay-protected.
- Duplicate evidence does not multiply impact.
- Event submitters do not choose canonical weight.
- Objective evidence has greater weight than subjective claims.
- One review cannot revoke Certification or confiscate Stake by itself.
- Self-generated activity does not create unrestricted Reputation.
- Profile ownership changes do not erase history.
- Formula versions are public.
- Canonical calculations use deterministic arithmetic.
- Corrections are explicit and auditable.
- Local Marketplace scores do not alter canonical Reputation.

## 137. Design Invariants

- Every protocol role has its own Reputation Profile.
- Reputation represents evidence over time.
- Health represents current operational condition.
- Certification represents bounded validation evidence.
- These systems remain related but distinct.
- Positive behavior builds confidence gradually.
- Ordinary failures may recover gradually.
- Critical integrity incidents remain historically visible.
- Reputation informs eligibility but does not replace objective protocol rules.
- Reputation does not directly move Q.
- Reputation does not prove unique human identity.
- The protocol records what it can observe and does not invent certainty about what it cannot.
