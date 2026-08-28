# RFC-0040 — AiDN Service Verification Framework

Status: Draft

Version: 0.4

Supersedes:

* RFC-0040 Version 0.1

Depends on:

* RFC-0036 AiDN Ledger State Machine
* RFC-0039 Hypervisor Service Model
* RFC-0041 Reputation Profile Engine
* RFC-0042 Hypervisor Network Protocol
* RFC-0045 AiDN Capability Architecture
* RFC-0047 CometBFT Consensus Integration
* RFC-0048 Epoch Engine
* RFC-0053 Capability Runtime Specification
* RFC-0054 Capability Runtime Protocol
* RFC-0055 Provider Plugin System and Directory
* RFC-0056 Provider Plugin Runtime Interface
* RFC-0058 Participant Eligibility and Sybil Resistance
* RFC-0059 Ledger Operation Catalog
* RFC-0061 Registry Replication Protocol
* RFC-0062 Snapshot and State Sync Protocol
* RFC-0063 Proxy Endpoint Protocol
* RFC-0064 Validation Assignment, Concealed Session and Escrow Protocol
* RFC-0066 Protocol Upgrade and Emergency Recovery
* RFC-0067 Protocol Governance and Authorization Policy

---

## 1. Purpose

This document defines the AiDN Service Verification Framework.

It specifies how the network determines whether a registered Service:

* controls its declared Service Identity;
* is reachable;
* supports the declared protocol role;
* uses compatible protocol versions;
* satisfies role-specific conformance requirements;
* can perform required protocol duties;
* provides required evidence;
* maintains sufficient operational Health;
* remains eligible after configuration or protocol changes;
* can recover after failure.

The framework covers infrastructure and execution Services operated through a Hypervisor.

---

## 2. Core Principle

Service registration is a declaration.

Service Verification is evidence that the declared Service can perform its protocol role.

Registered
≠
Verified
Verified
≠
Currently Healthy
Verified
≠
Reward-Eligible Forever

Verification SHALL be role-specific, evidence-based, time-bounded and repeatable.

---

## 3. Scope

The framework applies to:

HYPERVISOR_NODE
CONSENSUS_SERVICE
REGISTRY_SERVICE
VALIDATION_SERVICE
CAPABILITY_RUNTIME

Future protocol roles MAY define additional Service Verification Profiles.

Endpoint Certification is outside the primary scope of this RFC.

---

## 4. Service Verification and Endpoint Validation

The protocol SHALL distinguish:

Service Verification

Determines whether an infrastructure or Runtime Service correctly supports its declared protocol role.

Endpoint Validation

Determines whether a particular Consumer-facing Endpoint observably provides its declared Capability.

Service Verification is defined by this RFC.

Endpoint Validation is defined by RFC-0057, RFC-0064 and RFC-0065.

---

## 5. Example of the Distinction

A Capability Runtime may pass Service Verification because it:

* authenticates correctly;
* implements the required Runtime Protocol;
* supports llm.chat;
* validates Request schemas;
* produces Usage Reports;
* handles cancellation;
* recovers correctly.

A specific Endpoint backed by that Runtime may still fail Endpoint Validation because it:

* returns unusable output;
* is unavailable;
* publishes incorrect limits;
* returns corrupted artifacts;
* violates its Endpoint Configuration.

Provider installation or attachment is not itself a Verification target.

Provider Plugins, Provider Instances and Model Deployments are preparatory
Hypervisor-local execution objects.

Service Verification begins only once a Runtime Binding or equivalent Runtime
Service surface exists and can be checked for:

* identity control;
* protocol conformance;
* usage and evidence behavior;
* recovery behavior;
* configuration binding.

---

## 6. Verification Does Not Prove Hidden Implementation

Service Verification SHALL NOT claim proof of:

* proprietary source code;
* exact hardware ownership;
* exact hidden model weights;
* legal authorization;
* undisclosed upstream identity;
* absence of all future failures.

It verifies observable and protocol-relevant properties.

---

## 7. Verification Subjects

Every verification binds to one exact subject:

```yaml
verification_subject:
  subject_type:
  subject_id:
  service_role:
  operator_hypervisor_id:
  owner_wallet:
  configuration_hash:
  verification_profile_version:
```

A verification result SHALL NOT automatically apply to another Service Identity or Configuration Hash.

---

## 8. Verification Profile

Every Service role SHALL define a versioned Verification Profile.

```yaml
service_verification_profile:
  profile_id:
  service_role:
  profile_version:
  required_checks:
  optional_checks:
  maintenance_checks:
  recovery_checks:
  required_evidence:
  challenge_limits:
  success_conditions:
  limitation_conditions:
  failure_conditions:
  expiration_policy:
  conformance_test_root:
  profile_hash:
```

---

## 9. Verification Profile Purpose

A Verification Profile defines:

* what is checked;
* how evidence is collected;
* what is mandatory;
* what is advisory;
* how long verification remains valid;
* which changes require reverification;
* what failures affect eligibility.

---

## 10. Verification Classes

The protocol defines:

BASELINE
MAINTENANCE
TRIGGERED
RECOVERY
UPGRADE

---

## 11. BASELINE

Performed before a Service first becomes verified.

It confirms the minimum functional and protocol requirements for the declared role.

---

## 12. MAINTENANCE

Performed periodically to confirm continued operation.

Maintenance Verification MAY use:

* scheduled checks;
* random challenges;
* Duty Proof;
* finalized operational evidence;
* Epoch Health calculations.

---

## 13. TRIGGERED

Created after evidence of possible failure or inconsistency.

Triggers MAY include:

* repeated protocol failures;
* challenge failures;
* configuration mismatch;
* abnormal Health;
* Reputation events;
* incompatible software;
* suspicious signed evidence.

---

## 14. RECOVERY

Performed after:

* Service suspension;
* critical failure;
* configuration correction;
* key rotation after compromise;
* failed previous verification;
* prolonged unavailability.

---

## 15. UPGRADE

Performed when a protocol or Service upgrade changes verification-relevant behavior.

An Upgrade Verification MAY be:

* full;
* incremental;
* compatibility-based;
* automatically satisfied by conformance evidence.

---

## 16. Verification Dimensions

Service Verification MAY evaluate:

IDENTITY_CONTROL
PROTOCOL_COMPATIBILITY
REACHABILITY
ROLE_CONFORMANCE
DUTY_CAPABILITY
EVIDENCE_CAPABILITY
STATE_CONSISTENCY
SECURITY_BOUNDARY
RESOURCE_LIMITS
RECOVERY_CAPABILITY
UPGRADE_COMPATIBILITY

Not every dimension applies to every Service role.

---

## 17. Identity Control

Identity Control verifies that the Service controls the private authority corresponding to its registered Service Identity.

The check SHALL use:

* nonce challenge;
* Service signature;
* network and revision domain separation;
* expiration;
* replay protection.

---

## 18. Operator Authorization

Verification SHALL confirm that the operating Hypervisor is authorized to operate the Service.

A technically functional but unauthorized Service SHALL not pass verification.

---

## 19. Protocol Compatibility

The Service SHALL demonstrate compatibility with:

* Network ID;
* Chain ID;
* Network Revision;
* active Protocol Version;
* Service Protocol Version;
* required message schemas;
* required cryptographic domains.

---

## 20. Reachability

Reachability verifies that the Service can be contacted through its declared protocol path.

It MAY include:

* peer connection;
* authenticated handshake;
* request and response;
* timeout behavior;
* reconnect behavior.

One failed connection attempt SHALL not automatically prove persistent unavailability.

---

## 21. Role Conformance

Role Conformance verifies mandatory behavior defined for the Service role.

Examples include:

* Consensus vote-message handling;
* Registry object proof responses;
* Validation Report schema support;
* Runtime Request validation.

---

## 22. Duty Capability

Duty Capability verifies that the Service can perform the duties for which it seeks eligibility.

It does not prove that the Service will complete every future duty.

---

## 23. Evidence Capability

The Service SHALL demonstrate its ability to generate required evidence.

Examples include:

* signed Duty Proof;
* signed Health Reports;
* Registry manifests;
* Usage Reports;
* Validation Reports;
* state commitments;
* recovery checkpoints.

---

## 24. State Consistency

State Consistency verifies that the Service's declared operational state is consistent with canonical protocol state where applicable.

Examples include:

* correct Consensus height;
* correct State Root;
* correct Registry segment root;
* correct Capability Definition Hash;
* correct Endpoint Configuration binding.

---

## 25. Security Boundary

A Verification Profile MAY require evidence that the Service respects role-specific security boundaries.

Examples include:

* Runtime cannot authorize Wallet transfers;
* Registry does not receive Provider credentials;
* Validation Service does not receive Consensus keys;
* Session keys are scoped;
* control and data planes are separated.

Verification of security boundaries may be limited to observable behavior and declarations unless stronger attestation exists.

---

## 26. Resource Limits

A Service MAY be required to declare and demonstrate bounded resource behavior.

Examples include:

* maximum concurrent duties;
* storage profile;
* Request limits;
* maximum queue;
* response-size limits;
* timeout limits.

Verification SHALL NOT require disclosure of all private infrastructure details.

---

## 27. Recovery Capability

Recovery checks MAY verify:

* reconnect;
* state reconstruction;
* checkpoint restoration;
* Session continuation;
* Registry repair synchronization;
* Runtime restart;
* evidence-chain continuity.

---

## 28. Verification Evidence Classes

Verification evidence is classified as:

CANONICAL
CRYPTOGRAPHIC
ACTIVE_CHALLENGE
CONFORMANCE_TEST
MULTI_SOURCE_OBSERVATION
SELF_REPORTED

---

## 29. CANONICAL

Derived from finalized Ledger or Consensus state.

Examples include:

* valid votes;
* finalized Registry challenges;
* finalized Runtime registration;
* completed Service duties.

---

## 30. CRYPTOGRAPHIC

Supported by signed or hash-verifiable evidence.

Examples include:

* nonce signatures;
* manifest commitments;
* State Root matches;
* signed report chains;
* conflicting signed statements.

---

## 31. ACTIVE_CHALLENGE

Generated by a bounded protocol challenge.

Examples include:

* serve a Registry object;
* respond to a role-specific message;
* perform a Runtime schema test;
* sign a fresh nonce.

---

## 32. CONFORMANCE_TEST

Generated through an approved deterministic or bounded test suite.

Conformance tests SHALL bind to:

* profile version;
* test version;
* exact configuration;
* result root.

---

## 33. MULTI_SOURCE_OBSERVATION

Produced by several sufficiently independent observers.

This MAY support availability or persistent failure conclusions.

---

## 34. SELF_REPORTED

Produced only by the Service or its operator.

Self-reported evidence MAY support diagnostics.

It SHALL NOT alone establish canonical verification.

---

## 35. Verification Actors

Verification MAY be performed by:

* the deterministic State Machine;
* the Epoch Engine;
* selected eligible peer Services;
* approved conformance harnesses;
* eligible Validation Services where the role profile permits;
* several independent observers.

No single actor class is mandatory for every verification dimension.

---

## 36. No Universal Verifier Service

The MVP SHALL NOT require one privileged central Verification Service.

Different checks naturally use different actors.

Examples:

* Consensus participation is proven through Consensus evidence;
* Registry completeness uses Registry challenges;
* Runtime conformance uses a Capability harness;
* identity control uses cryptographic challenge.

---

## 37. Self-Test

A Service MAY run local self-tests.

Self-test results MAY:

* support readiness;
* prevent invalid registration;
* assist operators;
* accompany a Verification Request.

A self-test SHALL NOT alone create VERIFIED status.

---

## 38. Verification Request

A Service Owner or operator MAY submit:

SERVICE_VERIFICATION_REQUEST

The request SHALL include:

```yaml
service_verification_request:
  verification_request_id:
  verification_class:
  subject_type:
  subject_id:
  service_role:
  configuration_hash:
  verification_profile_id:
  verification_profile_version:
  requested_epoch:
  expiration_epoch:
  operator_signature:
  owner_authorization_reference:
```

---

## 39. Protocol-Generated Verification Request

The protocol MAY generate Maintenance, Triggered, Recovery or Upgrade Verification Requests automatically.

A Service operator does not need to approve a protocol-required Maintenance Verification separately after accepting the obligations of its role.

---

## 40. Verification Obligation

A Service seeking or retaining public eligibility SHALL accept bounded role-specific verification.

A Service MAY refuse verification.

Refusal may result in:

* remaining unverified;
* loss of eligibility;
* expiration of verified status;
* public limitation state.

Refusal alone is not necessarily misconduct.

---

## 41. Verification Lifecycle

CREATED
    ↓
QUEUED
    ↓
PREPARING
    ↓
EXECUTING
    ↓
EVIDENCE_PENDING
    ↓
EVALUATING
    ↓
COMPLETED

Alternative states include:

EXPIRED
CANCELLED
SUPERSEDED
BLOCKED
INCONCLUSIVE

---

## 42. Verification Result States

The protocol defines:

UNVERIFIED
VERIFICATION_PENDING
VERIFIED
VERIFIED_WITH_LIMITATIONS
INCONCLUSIVE
DEGRADED
FAILED
EXPIRED

---

## 43. UNVERIFIED

No currently valid verification exists for the active Service Configuration Hash.

---

## 44. VERIFICATION_PENDING

A valid Verification Request is active.

This state does not imply likely success.

---

## 45. VERIFIED

All mandatory checks passed without material unresolved limitations.

---

## 46. VERIFIED_WITH_LIMITATIONS

Mandatory core checks passed, but one or more non-disqualifying limitations exist.

Examples include:

* optional protocol feature unavailable;
* reduced capacity;
* limited recovery capability;
* non-critical synchronization lag;
* constrained storage profile.

---

## 47. INCONCLUSIVE

Verification could not produce sufficient evidence.

Possible causes include:

* network-wide outage;
* challenge actor failure;
* ambiguous test result;
* missing Registry evidence;
* incompatible test harness.

INCONCLUSIVE does not prove Service failure.

---

## 48. DEGRADED

The Service was previously verified but currently has material adverse evidence.

Degraded status MAY trigger:

* reduced eligibility;
* additional challenges;
* shorter verification validity;
* public warnings.

---

## 49. FAILED

Mandatory verification requirements were not satisfied.

Failure MAY cause:

* ineligibility;
* removal from duty selection;
* loss of public verified status;
* Recovery Verification requirement.

---

## 50. EXPIRED

The verification validity period ended.

Expiration does not necessarily indicate Service failure.

It means current evidence is too old.

---

## 51. Verification Record

```yaml
service_verification_record:
  verification_id:
  verification_request_id:
  subject_type:
  subject_id:
  service_role:
  configuration_hash:
  verification_class:
  profile_id:
  profile_version:
  check_results:
  evidence_root:
  limitation_codes:
  failure_codes:
  verification_state:
  effective_epoch:
  expiration_epoch:
  previous_verification_id:
  result_hash:
```

---

## 52. Check Result

Every mandatory or optional check SHALL produce:

```yaml
verification_check_result:
  check_id:
  check_version:
  status:
  evidence_class:
  evidence_reference:
  observed_value:
  expected_condition:
  limitation_code:
  failure_code:
```

---

## 53. Check Status

Initial statuses are:

PASS
PASS_WITH_LIMITATION
FAIL
INCONCLUSIVE
NOT_APPLICABLE

---

## 54. Verification Derivation

The final result SHALL be derived deterministically from:

* Verification Profile;
* mandatory Check Results;
* limitation policy;
* failure policy;
* evidence validity;
* current Configuration Hash.

An operator or verifier SHALL NOT manually choose the final canonical state.

---

## 55. Mandatory Check Failure

One failed mandatory check normally produces:

FAILED

unless the Verification Profile explicitly defines:

* bounded retry;
* temporary degraded state;
* inconclusive treatment.

---

## 56. Optional Check Failure

Failure of an optional check MAY produce:

* VERIFIED_WITH_LIMITATIONS;
* advisory warning;
* feature restriction;
* no effect.

The result is profile-specific.

---

## 57. Critical Failure

A critical objective failure MAY immediately produce:

FAILED

or:

SUSPENDED

through a separate Service-state rule.

Examples include:

* invalid Service Identity signature;
* wrong Network Revision;
* conflicting signed state;
* Registry manifest equivocation;
* Consensus double-sign evidence;
* fabricated verification evidence.

---

## 58. Verification Failure Is Not Automatically Misconduct

A Service may fail because it is:

* misconfigured;
* offline;
* under-resourced;
* outdated;
* not yet implemented correctly.

Failure alone SHALL NOT automatically slash Stake or apply a penalty.

Penalties require a separate objective violation rule.

---

## 59. Verification and Eligibility

Role-specific eligibility MAY require:

* current VERIFIED status;
* or VERIFIED_WITH_LIMITATIONS compatible with the requested duty.

A Service SHALL NOT receive role duties it has not demonstrated it can perform.

---

## 60. Verification and Rewards

Verification alone SHALL NOT earn protocol rewards.

Passing Verification
≠
Performing Useful Rewardable Work

Verification may be a prerequisite for reward eligibility.

---

## 61. Verification and Reputation

Verification events MAY create Reputation Events.

Examples include:

* successful Maintenance Verification;
* repeated failure;
* conflicting evidence;
* successful Recovery Verification;
* challenge non-response.

The verification result remains distinct from the Reputation Profile.

---

## 62. Verification and Health

Verification is a bounded assessment.

Health represents current operational state.

A Service may be:

VERIFIED
+
Current Health: DEGRADED

The network SHALL not treat historical verification as proof of present availability.

---

## 63. Configuration Binding

Verification SHALL bind to one exact Configuration Hash.

A material configuration change MAY invalidate or limit the current Verification Record.

---

## 64. Material Configuration Changes

Changes normally requiring reverification include:

* Service role behavior;
* protocol version;
* Runtime Capability binding;
* Registry storage profile;
* Consensus key;
* Validation tool profile;
* security boundary;
* recovery model;
* accounting behavior;
* required dependency model.

---

## 65. Non-Material Changes

Changes that MAY preserve verification include:

* hardware replacement with equivalent behavior;
* performance optimization;
* internal database engine change;
* logging changes;
* internal monitoring;
* private cost changes.

The role profile determines compatibility.

---

## 66. Verification Compatibility Claim

A Service MAY submit a compatibility claim stating that a new Configuration Hash preserves all verification-relevant behavior.

The claim SHALL include:

```yaml
verification_compatibility_claim:
  subject_id:
  previous_configuration_hash:
  new_configuration_hash:
  unchanged_verification_dimensions:
  changed_dimensions:
  supporting_evidence_root:
  operator_signature:
```

The protocol MAY accept, reject or require partial reverification.

---

## 67. Verification Expiration

Every Verification Profile SHALL define a validity period or continued-evidence rule.

Recommended initial baseline:

Baseline Verification Validity = 30 Epochs

Role-specific profiles MAY use shorter or longer periods.

---

## 68. Continuous Verification

Some roles MAY maintain verification through continuous canonical evidence.

Examples include:

* active Consensus participation;
* repeated Registry challenges;
* recurring Runtime conformance probes;
* completed Validation assignments.

A role MAY not require a full scheduled baseline test when sufficient continuous evidence exists.

---

## 69. Maintenance Window

Maintenance Verification SHOULD occur during a bounded, partially unpredictable window.

This reduces strategic behavior limited to known test times.

---

## 70. Verification Grace Period

A bounded grace period MAY apply when verification could not complete because of:

* network-wide failure;
* insufficient challenge capacity;
* protocol halt;
* test-harness defect;
* Registry unavailability unrelated to the subject.

Grace SHALL NOT apply when the subject itself avoided verification.

---

## 71. Triggered Verification

Triggered Verification MAY be created from:

* repeated duty failure;
* abnormal Reputation events;
* configuration mismatch;
* protocol-version mismatch;
* challenge non-response;
* security incident;
* user-facing failure patterns;
* upgrade incompatibility.

A trigger is not proof of failure.

---

## 72. Recovery Verification

Recovery Verification SHALL focus on:

* correction of the previous failure;
* restored role conformance;
* evidence continuity;
* security remediation;
* state reconstruction;
* current protocol compatibility.

---

## 73. Recovery After Critical Integrity Failure

A critical integrity failure MAY require:

* key rotation;
* new configuration;
* extended observation;
* several independent checks;
* new Bond or Stake conditions;
* governance or protocol authorization.

One successful ping SHALL not repair a signed-equivalence incident.

---

## 74. Verification Challenges

A Verification Profile MAY define active Challenges.

Every Challenge SHALL be:

* bounded;
* role-relevant;
* replay-protected;
* deadline-bound;
* evidence-producing;
* non-destructive.

---

## 75. Challenge Object

```yaml
service_verification_challenge:
  challenge_id:
  verification_request_id:
  subject_id:
  service_role:
  challenge_type:
  challenge_payload_hash:
  challenge_limits:
  issued_at:
  response_deadline:
  challenge_actor_commitment:
  protocol_signature:
```

---

## 76. Challenge Response

```yaml
service_verification_response:
  challenge_id:
  subject_id:
  response_status:
  response_payload_hash:
  evidence_reference:
  observed_configuration_hash:
  response_time:
  service_signature:
```

---

## 77. Challenge Privacy

A Challenge SHALL not require unnecessary disclosure of:

* private keys;
* OAuth tokens;
* Provider credentials;
* private network topology;
* raw customer data;
* unrelated Session content.

---

## 78. Challenge Load Limits

The protocol SHALL limit verification workload.

Limits MAY include:

* maximum Challenges per Epoch;
* maximum response size;
* maximum storage retrieval;
* maximum Runtime execution time;
* maximum bandwidth;
* maximum concurrent verification work.

---

## 79. Challenge Abuse

Verification actors SHALL NOT use Challenges to:

* extract useful production work;
* exhaust Service resources;
* retrieve unrelated private data;
* perform denial of service;
* obtain free model output beyond conformance needs.

Abuse MAY create Reputation or suspension consequences.

---

## 80. Challenge Assignment

Where active actors are required, assignments SHOULD be:

* deterministic;
* unpredictable before the assignment window;
* independent from the Service owner;
* bounded by actor capacity;
* conflict-checked.

---

## 81. Self-Verification Prohibition

A Service operator SHALL NOT provide the only independent evidence for its own verification.

Canonical evidence and approved deterministic test harnesses remain valid regardless of who executes the software, provided results are independently verifiable.

---

## 82. Known Control Group Conflict

A peer actor in the same Known Control Group SHALL NOT count as independent verification evidence.

Such evidence MAY still be retained as diagnostic information.

---

## 83. Duplicate Evidence

The same challenge, duty or event SHALL not be counted repeatedly.

Deduplication SHALL use:

* Challenge ID;
* Duty ID;
* Service ID;
* evidence hash;
* Epoch;
* incident root.

---

## 84. Correlated Failure

Failures caused by one common incident SHOULD be grouped.

Examples include:

* network-wide Consensus halt;
* common cloud outage;
* protocol bug;
* Registry-wide schema incompatibility;
* shared upstream failure.

Correlated failure may affect Health without being treated as several independent integrity failures.

---

## 85. Hypervisor Node Verification Profile

Hypervisor Node Verification MAY include:

* Hypervisor Identity challenge;
* protocol handshake;
* Service authorization control;
* routing correctness;
* network and revision compatibility;
* reconnect behavior;
* Service isolation declarations;
* canonical-state reconciliation.

---

## 86. Hypervisor Verification Limit

Hypervisor Verification SHALL NOT imply that every child Service is verified.

Each child Service maintains its own Verification Record.

---

## 87. Consensus Service Verification Profile

Consensus Service Verification MAY include:

* valid Consensus Identity and key;
* current Network Revision;
* supported consensus adapter version;
* synchronization to an acceptable height;
* State Root agreement;
* block validation capability;
* vote-message conformance;
* evidence handling;
* readiness signaling;
* recovery from restart.

---

## 88. Consensus Verification and Active Set

Passing Consensus Service Verification does not automatically place the Service in the Active Validator Set.

Active selection is governed by ECO-0006, RFC-0047 and RFC-0048.

---

## 89. Consensus Duty Proof

Ongoing Consensus Verification SHOULD primarily use canonical evidence such as:

* expected votes;
* valid votes;
* proposal duties;
* missed duties;
* conflicting signatures;
* synchronization state.

---

## 90. Registry Service Verification Profile

Registry Service Verification MAY include:

* Identity and protocol handshake;
* declared Registry Profile;
* required object retrieval;
* object-hash correctness;
* segment-proof response;
* manifest consistency;
* completeness threshold;
* synchronization lag;
* Snapshot availability where declared;
* repair synchronization.

---

## 91. Registry Profiles

Verification SHALL account for Registry type:

FULL
ARCHIVE
CACHE
SNAPSHOT_PROVIDER

A Cache Registry SHALL not be failed for lacking Archive data it never declared.

---

## 92. Registry Completeness

Completeness SHALL be evaluated against the declared Registry Profile and canonical commitments.

Self-reported storage size is not sufficient evidence.

---

## 93. Registry Equivocation

Conflicting signed Registry manifests for the same canonical scope constitute critical objective evidence.

This MAY produce immediate verification failure and Reputation consequences.

---

## 94. Validation Service Verification Profile

Validation Service Verification MAY include:

* Service Identity;
* supported Capability Validation Profiles;
* report-schema conformance;
* evidence storage and referencing;
* assignment-message handling;
* concealed credential handling;
* report commitment support;
* identity-reveal support;
* privacy controls;
* manual, automated or hybrid execution declaration.

---

## 95. Validation Service Verification Does Not Validate Judgment

The framework can verify that a Validation Service:

* receives assignments;
* follows schemas;
* publishes evidence;
* respects limits.

It cannot objectively prove that every future human or agent judgment will be correct.

Report quality is evaluated through Reputation and later evidence.

---

## 96. Capability Runtime Verification Profile

Capability Runtime Verification MAY include:

* Runtime Identity;
* Capability ID and Definition Hash;
* Runtime Protocol handshake;
* Request-schema validation;
* response-schema conformance;
* supported features;
* limit enforcement;
* streaming sequence;
* cancellation;
* idempotency;
* Usage Reporting;
* artifact integrity;
* recovery;
* side-effect approval hooks.

---

## 97. Runtime Verification and Endpoint Certification

Runtime Verification evidence SHALL bind `runtime_id`, `runtime_generation`,
`runtime_configuration_hash`, exact Capability Definition Hash and applicable
Adapter, Provider and Model references. A Route Generation change alone does
not invalidate Runtime Verification. A material Runtime configuration or
Runtime Generation change requires compatibility evaluation and, where
applicable, reverification.

A Runtime passing verification means it can implement the Capability contract.

It does not mean every Endpoint backed by that Runtime is Certified.

An Endpoint may publish:

* different limits;
* different price;
* different Proxy policy;
* different features;
* different Provider behavior.

---

## 98. Runtime Test Endpoint

Runtime Verification MAY use a non-public test Endpoint or direct Runtime conformance channel.

The test SHALL not create an ordinary Marketplace Endpoint or paid Consumer Session unless required by the profile.

---

## 99. Proxy Runtime Verification

A Proxy Runtime MAY be checked for:

* upstream failure mapping;
* PROXY_OPAQUE reporting;
* maximum-charge enforcement;
* retry limits;
* failover declarations;
* OAuth status handling;
* quota handling;
* chain-depth protection;
* cycle detection.

---

## 100. Proxy Verification Limitation

Verification SHALL NOT claim proof of hidden upstream identity when the Proxy declares an opaque upstream.

It MAY verify that the Runtime honestly reports the upstream as opaque.

---

## 101. Capability-Specific Runtime Tests

Runtime Verification SHALL use the Capability Conformance Profile from RFC-0045.

Examples include:

* valid and invalid Requests;
* optional features;
* streaming;
* cancellation;
* artifacts;
* side-effect approval;
* Usage Report structure.

---

## 102. Service Verification Result Commitment

Completed verification SHALL be committed through:

SERVICE_VERIFICATION_COMMIT

The operation SHALL include:

```yaml
service_verification_commit:
  verification_id:
  verification_request_id:
  subject_id:
  service_role:
  configuration_hash:
  profile_id:
  profile_version:
  verification_state:
  evidence_root:
  limitation_root:
  failure_root:
  effective_epoch:
  expiration_epoch:
  result_hash:
```

---

## 103. Service State Update

A Verification Result MAY trigger:

SERVICE_STATE_UPDATE

Examples include:

REGISTERED
→
VERIFIED
VERIFIED
→
DEGRADED
DEGRADED
→
VERIFIED
VERIFIED
→
VERIFICATION_PENDING

---

## 104. Verification Does Not Directly Modify Ownership

Verification SHALL NOT directly change:

* Service Owner;
* operator authorization;
* Reward Beneficiary;
* Wallet balance;
* Stake ownership.

Separate authorized operations are required.

---

## 105. Verification Does Not Directly Apply Penalties

A Verification failure MAY provide evidence for a Penalty Operation.

The Verification Result itself SHALL NOT arbitrarily confiscate Q.

---

## 106. Verification Task Integration

RFC-0048 SHALL support tasks including:

Freeze Verification Requests
Calculate Verification Due Set
Generate Maintenance Challenges
Assign Verification Actors
Expire Verification Challenges
Validate Verification Evidence
Derive Verification Results
Apply Verification Expiration
Schedule Recovery Verification
Update Service Eligibility
Publish Verification Metrics

---

## 107. Verification Scheduling

Scheduling SHOULD consider:

* Verification Class;
* expiration risk;
* Service role;
* Service risk;
* recent failures;
* protocol upgrades;
* available challenge capacity;
* Service age.

---

## 108. Scheduling Priority

Recommended priority:

1. critical Triggered Verification;
2. Recovery Verification;
3. Maintenance near expiration;
4. Upgrade Verification;
5. Baseline Verification;
6. non-urgent random checks.

---

## 109. Randomized Maintenance

Maintenance checks SHOULD include an unpredictable component.

The randomness SHALL derive from RFC-0048 with domain separation.

---

## 110. Verification Capacity

The protocol SHALL not schedule more active verification workload than available actors and infrastructure can safely process.

Insufficient verification capacity may delay verification.

It SHALL not automatically produce subject failure.

---

## 111. Verification Expiration During Delay

When expiration is caused by network verification-capacity shortage rather than subject avoidance, a grace policy MAY apply.

The public state SHALL disclose grace status.

---

## 112. Verification Actor Economics

This RFC does not create a separate Service Verification reward pool.

Verification work MAY be:

* part of Consensus duties;
* part of Registry duties;
* part of Validation Service duties;
* automated protocol conformance;
* funded by a future economic policy.

No reward is implied merely because a challenge was sent.

---

## 113. Verification Fees

A Service operator MAY pay ordinary Network Fees for:

* Verification Request commitment;
* Registry evidence storage;
* result commitment.

Network Fees do not buy a successful result.

---

## 114. No Pay-to-Verify Outcome

The result SHALL be derived from evidence.

Paying a fee, locking Stake or operating expensive hardware SHALL NOT by itself create VERIFIED status.

---

## 115. Evidence Retention

Registry Services SHOULD retain:

* Verification Requests;
* Challenges;
* Responses;
* conformance results;
* evidence objects;
* Verification Records;
* limitation descriptions;
* failure descriptions;
* correction records.

---

## 116. Public and Restricted Evidence

Verification evidence MAY be:

PUBLIC
HASH_COMMITTED
RESTRICTED
ENCRYPTED

The Verification Record SHALL expose enough public information to explain the result without unnecessarily revealing secrets.

---

## 117. Verification Explanation

A Verification Result SHOULD include a human-readable summary.

Example:

Registry Service passed identity, protocol, object-integrity and
challenge-response checks. Archive completeness was not tested because
the Service is registered as a Full Registry rather than an Archive Registry.
Synchronization lag exceeded the preferred threshold but remained within
the permitted limit.

Canonical state remains the structured Verification Record.

---

## 118. Correction

An incorrect finalized Verification Record SHALL NOT be silently rewritten.

Correction requires:

* a new correction record;
* reference to the original Verification ID;
* objective correction reason;
* corrected derivation;
* resulting Service-state update.

---

## 119. Challenge of Verification Result

A participant MAY challenge objective processing errors such as:

* wrong Configuration Hash;
* invalid evidence;
* duplicate Challenge;
* expired response counted as valid;
* Known Control Group conflict;
* wrong Verification Profile;
* arithmetic or derivation error.

Disagreement with an allowed subjective limitation does not automatically invalidate the result.

---

## 120. Protocol Upgrade

Verification Profiles SHALL be versioned.

A protocol upgrade MAY:

* preserve existing verification;
* shorten remaining validity;
* require incremental checks;
* require complete reverification;
* invalidate incompatible Services.

Migration behavior SHALL be explicit.

---

## 121. Network Revision

Every Verification Request, Challenge, Response and Result SHALL bind to the active Network Revision.

Old-revision evidence SHALL not be replayed as fresh verification evidence.

---

## 122. Service Relocation

A Service may relocate between Hypervisors while preserving verification only when:

* Service Identity remains valid;
* operator authorization is updated;
* configuration compatibility holds;
* verification-relevant behavior is unchanged;
* relocation checks pass.

---

## 123. Service Key Rotation

Key rotation SHALL normally require at least:

* Identity Control reverification;
* authorization verification;
* replay-domain update;
* confirmation that old-key obligations remain attributable.

---

## 124. Service Retirement

Retiring a Service:

* ends future verification scheduling;
* preserves Verification history;
* does not erase failures;
* does not cancel pending evidence or penalties.

---

## 125. Reactivation

A retired Service MAY require:

* new operator authorization;
* current protocol compatibility;
* Baseline or Recovery Verification;
* current configuration binding.

Old Verification Records do not automatically become current again.

---

## 126. Verification Metrics

The network SHOULD publish:

* verified Services by role;
* pending Verification Requests;
* failure rate;
* limitation rate;
* expiration rate;
* average verification delay;
* challenge success;
* challenge non-response;
* Recovery Verification success;
* actor concentration;
* verification-capacity backlog.

---

## 127. No Universal Service Score

The framework SHALL NOT reduce all verification dimensions into one universal Service score.

The result is:

* role-specific;
* profile-specific;
* evidence-backed;
* state-based.

Reputation provides longer-term scoring separately.

---

## 128. Required Ledger Operations

RFC-0059 SHOULD support:

SERVICE_VERIFICATION_REQUEST
SERVICE_VERIFICATION_CANCEL
SERVICE_VERIFICATION_CHALLENGE_COMMIT
SERVICE_VERIFICATION_RESPONSE_COMMIT
SERVICE_VERIFICATION_COMMIT
SERVICE_VERIFICATION_CORRECT
SERVICE_STATE_UPDATE

---

## 129. Error Codes

The MVP SHALL define at least:

SERVICE_VERIFICATION_REQUEST_NOT_FOUND
SERVICE_VERIFICATION_SUBJECT_NOT_FOUND
SERVICE_VERIFICATION_PROFILE_NOT_FOUND
SERVICE_VERIFICATION_PROFILE_MISMATCH
SERVICE_VERIFICATION_CONFIGURATION_MISMATCH
SERVICE_VERIFICATION_CLASS_INVALID
SERVICE_VERIFICATION_CHALLENGE_INVALID
SERVICE_VERIFICATION_CHALLENGE_EXPIRED
SERVICE_VERIFICATION_RESPONSE_INVALID
SERVICE_VERIFICATION_RESPONSE_EXPIRED
SERVICE_VERIFICATION_RESPONSE_REPLAYED
SERVICE_VERIFICATION_ACTOR_NOT_ELIGIBLE
SERVICE_VERIFICATION_CONTROL_GROUP_CONFLICT
SERVICE_VERIFICATION_EVIDENCE_INVALID
SERVICE_VERIFICATION_EVIDENCE_DUPLICATE
SERVICE_VERIFICATION_RESULT_CONFLICT
SERVICE_VERIFICATION_RESULT_ALREADY_COMMITTED
SERVICE_VERIFICATION_DERIVATION_FAILED
SERVICE_VERIFICATION_CORRECTION_INVALID
SERVICE_VERIFICATION_STATE_TRANSITION_INVALID
SERVICE_VERIFICATION_EXPIRED

---

## 130. Idempotency

The following SHALL be idempotent:

* Verification Request submission;
* Challenge commitment;
* Response commitment;
* conformance-result commitment;
* Verification Result commitment;
* correction submission;
* Service-state update.

One Challenge SHALL affect one verification result at most once.

---

## 131. Security Threats

The framework SHALL account for:

* self-verification;
* colluding verification actors;
* challenge replay;
* challenge flooding;
* selective response;
* secret extraction;
* resource-exhaustion challenges;
* fabricated evidence;
* stale Configuration verification;
* old-revision evidence;
* verification-result bribery;
* Service identity cycling;
* actor concentration.

---

## 132. Challenge Flood Protection

A Service SHALL be able to verify that a Challenge:

* is authorized;
* belongs to an active Verification Request;
* fits profile limits;
* has not been replayed;
* does not exceed current challenge capacity.

Unauthorized test traffic SHALL not receive privileged Verification treatment.

---

## 133. Selective Availability

Randomized or continuous verification SHOULD reduce the value of operating a Service only during predictable checks.

Ongoing Duty Proof remains more important than one scheduled test.

---

## 134. Verification Actor Collusion

Protection MAY include:

* deterministic actor assignment;
* Known Control Group filtering;
* multiple evidence sources;
* canonical conformance tests;
* public result history;
* challenge replay audits.

The protocol cannot eliminate all undisclosed off-chain collusion.

---

## 135. Fabricated Evidence

Objectively fabricated verification evidence MAY cause:

* failed verification;
* critical Reputation event;
* Service suspension;
* penalty where an explicit economic rule exists.

---

## 136. Verification and Governance

Changes to Standard Verification Profiles require protocol governance.

Service-role-specific adjustments SHOULD be classified as Service Policy proposals unless they alter:

* Consensus validity;
* economic formulas;
* canonical State Machine behavior.

---

## 137. MVP Requirements

The MVP SHALL implement:

* versioned Service Verification Profiles;
* Baseline Verification;
* Maintenance Verification;
* Triggered Verification;
* Recovery Verification;
* identity-control checks;
* protocol-compatibility checks;
* role-specific conformance;
* Configuration Hash binding;
* Verification Requests;
* bounded Challenges;
* replay-protected Responses;
* deterministic Result derivation;
* VERIFIED_WITH_LIMITATIONS;
* verification expiration;
* grace handling;
* role-specific eligibility integration;
* Reputation event integration;
* Registry evidence retention;
* fixed Network Revision binding;
* correction records;
* complete Verification history.

---

## 138. Deferred Features

The MVP MAY postpone:

* zero-knowledge Service conformance proofs;
* hardware-backed remote attestation;
* confidential infrastructure proofs;
* private verification actors;
* cross-network verification portability;
* market-priced verification assignments;
* formal verification of Runtime implementations;
* proof-of-physical-resource ownership;
* automated legal-compliance checks;
* universal Service security certification.

---

## 139. Open Protocol Parameters

The following remain role-specific or configurable:

* Baseline Verification validity;
* Maintenance window;
* grace period;
* Challenge frequency;
* Challenge limits;
* minimum actor independence;
* maximum verification backlog;
* conformance-test version;
* limitation thresholds;
* failure thresholds;
* Recovery requirements;
* configuration-compatibility rules;
* evidence retention;
* correction challenge window.

---

## 140. Verification Invariants

Registration
≠
Verification
Verification
≠
Permanent Eligibility
Verification
≠
Current Health
Verification
≠
Endpoint Certification
Passing Verification
≠
Rewardable Work
Self-Reported Health
≠
Independent Verification

---

## 141. Role Invariants

* Every Service role has its own Verification Profile.
* A Hypervisor verification does not verify all child Services.
* Runtime verification does not certify all Endpoints.
* Consensus verification does not grant an Active Validator slot.
* Registry verification respects the declared Registry Profile.
* Validation Service verification does not prove future subjective judgment quality.
* Proxy verification does not prove hidden upstream identity.

---

## 142. Evidence Invariants

* Every Verification Result binds to exact evidence.
* Every Challenge is replay-protected.
* Duplicate evidence is counted once.
* Known Control Group actors do not count as independent.
* Self-reported evidence cannot independently produce canonical verification.
* Critical signed conflicts remain historically visible.
* Restricted evidence remains hash-committed.

---

## 143. Economic Invariants

* Verification does not create an automatic reward.
* Verification Fees do not purchase success.
* Failure does not automatically slash Stake.
* Penalties require a separate objective rule.
* Registration without useful work earns no Q.
* Verification workload remains bounded.

---

## 144. Security Invariants

* Verification does not expose private keys or Provider credentials.
* Challenges cannot bypass Service authorization.
* Challenges cannot exceed profile workload limits.
* Old-revision evidence cannot be replayed.
* Stale Configuration verification cannot apply to new behavior.
* A single actor cannot arbitrarily choose the canonical result.
* Finalized errors are corrected explicitly.
* Service retirement does not erase verification history.

---

## 145. Design Invariants

* Infrastructure Services are verified through role-specific observable behavior.
* Protocol conformance can be tested more strictly than subjective Endpoint quality.
* Verification is periodic rather than permanent.
* Continuous duty evidence may replace repetitive formal tests.
* Current Health, long-term Reputation and Verification remain separate.
* Verification failure usually means ineligibility, not automatic misconduct.
* The framework verifies what the network can actually observe.
* It does not certify metaphysical properties of software merely because an operator wrote them into a manifest.

Комментарии к решениям

1. Service Verification и Endpoint Validation окончательно разделены

Это главное изменение.

Service Verification проверяет:

поддерживает ли Registry нужные объекты;
умеет ли Consensus Service участвовать в протоколе;
умеет ли Runtime исполнять Capability contract;
умеет ли Validation Service принимать Assignment и публиковать Report.

Endpoint Validation проверяет:

доступен ли конкретный Endpoint;
возвращает ли он осмысленный результат;
соответствует ли он опубликованному Capability;
не повреждены ли артефакты;
работает ли Usage Reporting.

Runtime может быть технически исправным, но Endpoint на нём может быть плохо настроен. И наоборот, временно работающий Endpoint ещё не доказывает, что Runtime корректно реализует все cancellation, recovery и accounting semantics.

---

2. Здесь тесты могут быть значительно строже

При проверке скрытой модели мы не можем надёжно доказать, что внутри действительно заявленный Qwen или Claude.

Но для инфраструктурного Service вполне можно объективно проверить:

* подпись;
* схему сообщения;
* State Root;
* наличие объекта;
* правильность hash;
* последовательность Usage Reports;
* обработку duplicate Request;
* поддержку cancellation;
* соответствие Capability Definition Hash.

То есть здесь строгая conformance-модель уместна. Наконец-то область, где тест действительно может ответить на вопрос, а не только создать уверенный PDF.

---

3. Не нужен один универсальный Verifier

Разные роли уже производят подходящие доказательства:

Consensus
→ finalized votes and state commitments
Registry
→ object challenges and manifests
Runtime
→ Capability conformance harness
Validation Service
→ assignment and report protocol tests

Создавать отдельную касту "главных проверяющих всё" было бы лишней централизацией.

---

4. Verification не приносит награду сама по себе

Проверка отвечает:

Может ли Service выполнять роль?

Награда отвечает:

Выполнил ли он полезную работу в этой роли?

Поэтому:

Registry passed verification

не означает, что он получает Registry reward.

Он ещё должен:

* хранить нужные данные;
* отвечать на challenges;
* подтверждать completeness;
* выполнять Duty Proof.

Иначе сеть платила бы за успешный экзамен вместо фактической работы. Академические институты кожанных уже заняли эту бизнес-модель.

---

5. VERIFIED_WITH_LIMITATIONS нужен обязательно

Не каждая проблема должна превращаться в полный провал.

Например, Registry может:

* правильно хранить обязательный профиль;
* отвечать на запросы;
* иметь повышенный lag, но оставаться в допустимых пределах.

Runtime может:

* поддерживать базовый llm.chat;
* не поддерживать optional tool calls;
* иметь только best-effort recovery.

Если ограничения честно опубликованы и не нарушают core contract, Service остаётся пригодным для части задач.

---

6. Verification и Health не одно и то же

VERIFIED

означает, что Service прошёл проверку в определённый момент или поддерживает достаточную цепочку текущих доказательств.

Health: DEGRADED

означает, что прямо сейчас у него проблема.

Например, Runtime может быть Verified, но его upstream OAuth истёк пять минут назад. Проверка архитектуры никуда не исчезла, но Health должен немедленно ухудшиться.

---

7. Continuous Verification лучше повторения формального экзамена

Для Consensus уже есть ежедневные доказательства:

* votes;
* proposals;
* missed duties;
* State Root consistency.

Нет смысла каждые 30 дней запускать отдельный тест "умеет ли он подписывать vote", если он только что подписал несколько тысяч реальных votes.

То же касается Registry, который постоянно отвечает на случайные challenges.

Поэтому role profile может продлевать Verification через реальную деятельность.

---

8. Failure не должен автоматически означать мошенничество

Service может не пройти проверку из-за:

* неверной конфигурации;
* старой версии;
* недостатка ресурсов;
* сетевой ошибки;
* обычного бага.

Результат:

FAILED
→ нет eligibility

Но не обязательно:

FAILED
→ slash

Штраф появляется только при объективном нарушении:

* подделке evidence;
* конфликтующих подписях;
* equivocation;
* намеренном ложном заявлении, если для него есть формальное доказательство.

---

9. Runtime Verification не должен оценивать качество текста

Runtime Conformance проверяет:

* Request schema;
* Response schema;
* streaming;
* cancellation;
* idempotency;
* Usage Reports;
* artifacts;
* recovery.

Но не обязан решать, хороший ли получился рассказ о коте.

Качество конкретного Endpoint проверяется через Endpoint Validation, Reputation и пользовательские Sessions.

---

10. Proxy можно проверить, не зная его upstream

Для Proxy Runtime можно объективно проверить:

* честно ли указан PROXY_OPAQUE;
* соблюдается ли Maximum Charge;
* видны ли retries;
* корректно ли отображаются upstream failures;
* не превышается ли chain depth;
* не происходит ли обычный Settlement поверх concealed validation.

Но нельзя доказать, что за ним действительно OpenAI, Codex или специально обученный гном с терминалом. Поэтому upstream identity остаётся disclosure claim, если нет отдельной attestation.

---

11. Что теперь нужно синхронизировать

После принятия RFC-0040 v0.2:

* RFC-0039: заменить общий переход VERIFICATION_PENDING → VERIFIED ссылкой на Verification Record;
* RFC-0041: добавить Verification Events и различать failure от misconduct;
* RFC-0048: включить задачи из раздела 106;
* RFC-0053: Runtime Verification должен использовать Capability Conformance Profile;
* RFC-0054: добавить сообщения challenge, response и conformance result;
* RFC-0058: применять Known Control Group к независимым Verification Actors;
* RFC-0059: добавить операции из раздела 128;
* RFC-0061: Registry challenges должны считаться Continuous Verification evidence;
* RFC-0063: Proxy Runtime verification должна ссылаться на RFC-0040;
* RFC-0066: Upgrade Verification становится формальным классом проверки.

Следующим из восстанавливаемых документов логично сделать RFC-0042 - Hypervisor Network Protocol. Теперь уже определено, какие Service, Verification, Session и Runtime сообщения он обязан маршрутизировать, а значит можно описать сетевой слой без гадания по кофейной гуще протокольных зависимостей.
