# RFC-0065 Endpoint Certification Derivation and Lifecycle Protocol

Status: `Draft`

Version: `0.1`

Depends on:

- `ECO-0003 Validation Economics`
- `ECO-0004 Protocol Service Reward Distribution`
- `RFC-0035 Validation Escrow System`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0040 Service Verification Framework`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0045 Capability Architecture`
- `RFC-0048 Epoch Engine`
- `RFC-0051 Usage Reporting and Verification Protocol`
- `RFC-0057 Validation Report Specification`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0059 Ledger Operation Catalog`
- `RFC-0064 Validation Assignment, Concealed Session and Escrow Protocol`

## 1. Purpose

This document defines how AiDN derives and maintains Endpoint Certification from finalized Validation Reports.

It specifies:

- Certification meaning and scope;
- Certification states;
- Initial Certification rules;
- Maintenance Validation effects;
- report eligibility;
- report conclusions;
- single-report Certification;
- multi-report policies;
- conflicting report handling;
- Certification degradation;
- Certification revocation;
- Certification expiration;
- configuration-change effects;
- Triggered Validation;
- recovery after failure;
- Certification history;
- deterministic Ledger transitions.

## 2. Core Principle

Endpoint Certification is a protocol statement about observed Endpoint behavior under a specific configuration.

Certification SHALL NOT claim proof of:

- hidden model identity;
- exact model weights;
- Provider identity;
- local execution;
- remote execution;
- internal Runtime architecture;
- hardware ownership;
- undisclosed upstream services.

Certification means that one or more eligible Validators executed bounded representative tests and published reports that support the applicable Certification state.

## 3. Observable Certification

AiDN validates what the Endpoint observably does.

Depending on Capability, observable properties MAY include:

- Endpoint reachability;
- protocol compatibility;
- request acceptance;
- meaningful response production;
- output format;
- artifact validity;
- latency observations;
- Usage Reporting;
- Accounting Mode disclosure;
- error handling;
- response consistency;
- obvious defects;
- obvious unusable output.

The protocol SHALL not convert incomplete observability into fictional certainty.

## 4. Certification Is Not a Warranty

Certification does not guarantee:

- future availability;
- future output quality;
- exact result correctness;
- absence of hallucination;
- suitability for a particular Consumer;
- permanent consistency;
- legal or regulatory compliance;
- hidden model authenticity.

Certification is one trust signal among:

- Validation Reports;
- Endpoint Reputation;
- operator history;
- Session outcomes;
- user feedback;
- pricing;
- Capability metadata.

## 5. Certification Scope

Every Certification SHALL bind to:

`Endpoint ID`

`+`

`Endpoint Configuration Hash`

`+`

`Capability ID`

`+`

`Certification Policy Version`

A Certification applies only to the exact execution-relevant configuration tested.

## 6. Certification Record

A Certification Record SHALL contain:

```yaml
certification_record:
  certification_id:
  endpoint_id:
  endpoint_configuration_hash:
  capability_id:
  certification_state:
  certification_policy_version:
  risk_class:
  supporting_report_ids:
  conflicting_report_ids:
  unresolved_observations:
  effective_epoch:
  expiration_epoch:
  last_maintenance_epoch:
  next_maintenance_window:
  derivation_evidence_root:
  previous_certification_id:
```

## 7. Certification States

The protocol defines:

- `UNCERTIFIED`
- `VALIDATION_PENDING`
- `CERTIFIED`
- `CERTIFIED_WITH_OBSERVATIONS`
- `INCONCLUSIVE`
- `DEGRADED`
- `REVALIDATION_REQUIRED`
- `CERTIFICATION_REVOKED`
- `EXPIRED`

## 8. UNCERTIFIED

The Endpoint has no currently valid Certification for its active Configuration Hash.

This may mean:

- Validation has never occurred;
- previous Certification expired;
- configuration changed;
- Certification was revoked;
- no conclusive report exists.

An uncertified Endpoint MAY remain publicly accessible unless Marketplace or access policy says otherwise.

## 9. VALIDATION_PENDING

A valid Validation Request exists and is awaiting:

- assignment;
- execution;
- report publication;
- report finalization;
- Certification derivation.

This state does not imply likely success.

## 10. CERTIFIED

The available eligible Validation evidence supports normal Endpoint operation without material unresolved observations.

`CERTIFIED` means:

- the Endpoint responded;
- the response was meaningful for the declared Capability;
- no disqualifying protocol failure was observed;
- required report evidence exists.

## 11. CERTIFIED_WITH_OBSERVATIONS

The Endpoint is operational and usable, but one or more non-disqualifying observations exist.

Examples include:

- high latency;
- minor artifacts;
- occasional recoverable errors;
- incomplete optional metadata;
- limited Usage Verification;
- `Proxy-Opaque` accounting;
- quality limitations;
- non-critical protocol deviations.

The observations SHALL be visible to Consumers.

## 12. INCONCLUSIVE

Validation occurred but did not produce enough evidence for Certification or rejection.

Possible causes include:

- broad network failure;
- incomplete artifact delivery;
- Validator tool failure;
- insufficient observation window;
- protocol ambiguity;
- conflicting non-critical evidence.

`INCONCLUSIVE` does not mean the Endpoint failed.

## 13. DEGRADED

A previously Certified Endpoint has new adverse evidence, but the evidence is not yet sufficient for immediate revocation.

The Endpoint remains visible as previously Certified but under active concern.

`DEGRADED` SHALL trigger additional Validation.

## 14. REVALIDATION_REQUIRED

The Endpoint must complete a new Validation before its Certification can continue.

This state MAY result from:

- significant configuration change;
- material Proxy-policy change;
- unresolved report conflict;
- policy-version change;
- prolonged lack of Maintenance Validation;
- repeated Session failures;
- material accounting anomaly.

## 15. CERTIFICATION_REVOKED

The Endpoint no longer satisfies Certification requirements.

Revocation MAY result from:

- conclusive negative Validation;
- repeated confirmed unavailability;
- critical protocol violation;
- fabricated Endpoint evidence;
- material configuration mismatch;
- repeated failure after degradation;
- qualifying Maintenance Validation failure.

## 16. EXPIRED

The Certification validity period ended without a qualifying Maintenance Validation.

Expiration is not necessarily evidence of Endpoint failure.

It means current Certification evidence is too old.

## 17. Report Conclusions

Eligible Validation Reports use:

- `CERTIFY`
- `CERTIFY_WITH_OBSERVATIONS`
- `DO_NOT_CERTIFY`
- `INCONCLUSIVE`

The conclusion is a Validator recommendation.

The final Certification state is derived by protocol rules.

## 18. Report Eligibility

A report affects Certification only when:

- its assignment was valid;
- the Validator was eligible;
- the report was committed;
- assignment reveal was valid;
- the report matches the current Endpoint Configuration Hash;
- required evidence exists;
- the report is within the applicable time window;
- no fabrication evidence exists;
- the Validator is not in the same Known Control Group as the Endpoint.

## 19. Ineligible Reports

An ineligible report MAY remain visible in Registry history.

It SHALL NOT directly alter Certification.

Reasons include:

- invalid assignment;
- self-validation;
- expired assignment;
- wrong Configuration Hash;
- invalid report signature;
- missing evidence;
- report fabrication;
- report duplication;
- unsupported report version.

## 20. Single-Report Default

For the MVP, one eligible Validation Report SHALL normally be sufficient for Initial Certification of a standard Endpoint.

This reflects the intentionally permissive trust model:

```text
One valid assignment
+
One meaningful bounded test
+
One useful report
=
Initial Certification decision
```

The protocol SHALL not require artificial repetition where one report already establishes ordinary Endpoint operation.

## 21. Why One Report Is Usually Enough

Validation cannot objectively prove hidden implementation identity.

Requiring five Validators to perform similar subjective tests would:

- increase cost;
- delay Endpoint activation;
- consume Validator capacity;
- create an illusion of certainty;
- encourage formulaic low-value testing.

Additional reports are more useful when evidence conflicts or risk is elevated.

## 22. Initial Certification Derivation

For a standard-risk Endpoint with no conflicting evidence:

| Eligible Report Conclusion | Certification Result |
| --- | --- |
| `CERTIFY` | `CERTIFIED` |
| `CERTIFY_WITH_OBSERVATIONS` | `CERTIFIED_WITH_OBSERVATIONS` |
| `DO_NOT_CERTIFY` | `UNCERTIFIED` |
| `INCONCLUSIVE` | `INCONCLUSIVE` |

## 23. Meaningful Response Requirement

A report MAY recommend Certification when the Endpoint returns a meaningful response appropriate to its Capability.

Examples:

Text Endpoint

- readable and relevant output;
- no obvious protocol corruption;
- valid response structure.

Image Endpoint

- valid decodable image;
- expected dimensions or declared dimensions;
- output is not an empty, blank or clearly corrupted artifact;
- no severe unexplained artifacts.

STT Endpoint

- produces non-empty transcription from valid speech input;
- output is not unrelated noise or protocol garbage.

TTS Endpoint

- produces valid audio;
- output is not silence, static or corrupted media unless requested.

## 24. Negative Certification Conditions

A report MAY recommend `DO_NOT_CERTIFY` when:

- Endpoint is persistently unavailable;
- requests consistently fail;
- output is empty or unusable;
- result is protocol-invalid;
- artifact is corrupted;
- declared Capability is not observably provided;
- Usage Reporting is materially deceptive;
- Endpoint behavior contradicts its declared configuration;
- critical safety or protocol failure is observed.

## 25. Endpoint Unavailability

Repeated Endpoint unavailability during a valid assignment MAY be sufficient for `DO_NOT_CERTIFY`.

Capability Guidelines SHALL define a reasonable number of attempts or observation period.

A single transient transport failure SHOULD normally produce:

- another attempt;
- or `INCONCLUSIVE`;

rather than immediate rejection.

## 26. Validator Judgment

Validation Reports necessarily contain bounded expert or operator judgment.

The protocol SHALL not require every observation to be reducible to one universal score.

A Validator MAY describe:

- artifacts;
- latency;
- coherence;
- usability;
- protocol behavior;
- suspicious responses;
- limitations.

The report SHALL distinguish:

`Observed fact`

from:

`Validator interpretation`

## 27. No Model-Identity Certification

A report SHALL NOT state that hidden model identity has been cryptographically proven unless a separate attestation mechanism genuinely provides such proof.

Permitted wording includes:

- "behavior is consistent with the declared Capability";
- "the Endpoint produced plausible responses";
- "the reported model identity was not independently verified";
- "the Endpoint appears to proxy an upstream service";
- "hidden Provider identity is unknown."

## 28. Certification Risk Classes

A Certification Policy MAY assign:

- `STANDARD`
- `ELEVATED`
- `RESTRICTED`

risk classes.

`STANDARD`

One eligible report is normally sufficient.

`ELEVATED`

Additional report or shorter validity MAY be required.

`RESTRICTED`

Certification may require specialized rules, multiple independent reports or additional attestation.

The MVP SHOULD default ordinary AI Capabilities to `STANDARD`.

## 29. Elevated-Risk Policy

An Elevated-risk Endpoint MAY require:

```text
RequiredIndependentReports = 2
```

Examples MAY include:

- Capability with irreversible external side effects;
- high-cost autonomous agent execution;
- sensitive infrastructure control;
- specialized regulatory integration.

Risk classification SHALL be based on declared Capability behavior rather than operator popularity.

## 30. Restricted Certification

Restricted Certification is outside the ordinary MVP path.

A Restricted Endpoint MAY remain:

`UNCERTIFIED`

or:

`REVALIDATION_REQUIRED`

until its Capability-specific policy is available.

The protocol SHALL not pretend that a generic image-generation test validates a surgical robot.

## 31. Independent Reports

When multiple reports are required, they SHALL come from independent Validator Services.

Validators SHALL not belong to the same Known Control Group.

Repeated reports from one Validator do not satisfy an independent-report requirement.

## 32. Supporting Report Set

A Certification Record SHALL preserve all eligible reports used in derivation.

The protocol SHALL not replace report history with only the final state.

Consumers MAY inspect:

- requests;
- observations;
- evidence;
- conclusions;
- Validator identity;
- report age.

## 33. Certification Derivation Is Deterministic

The State Machine SHALL derive Certification using:

- report eligibility;
- report conclusion;
- report finalization order;
- applicable Certification Policy;
- current Configuration Hash;
- existing Certification state;
- objective Critical Evidence.

No administrator manually selects the resulting state.

## 34. Report Weight

For Certification conflict handling, report weight MAY consider:

```text
ReportWeight
=
ReportQuality
×
EvidenceFactor
×
ValidatorReliability
×
FreshnessFactor
```

Report weight SHALL not be based on:

- Validator Wallet balance;
- Stake above the minimum;
- social popularity;
- favorable conclusion;
- Endpoint payment.

## 35. Weight Is Not Truth

A higher report weight indicates stronger protocol confidence.

It does not prove that the report is factually perfect.

Certification SHALL preserve conflicting reports instead of silently deleting the lower-weight report.

## 36. Conflicting Reports

Reports conflict when eligible reports for the same Configuration Hash contain materially incompatible conclusions.

Examples:

`CERTIFY`

vs

`DO_NOT_CERTIFY`

or:

`CERTIFIED_WITH_OBSERVATIONS`

vs

critical protocol failure

Minor differences in commentary do not create formal conflict.

## 37. Initial Certification Conflict

If an uncertified Endpoint receives conflicting eligible reports:

- it SHALL NOT become fully `CERTIFIED`;
- state becomes `INCONCLUSIVE` or remains `VALIDATION_PENDING`;
- an additional independent Validation Request is created;
- all conflicting reports remain visible.

## 38. Existing Certification Conflict

If a Certified Endpoint receives one materially negative report conflicting with prior positive evidence:

```text
CERTIFIED
->
DEGRADED
```

The protocol SHALL schedule additional Validation.

One ordinary negative report SHALL not automatically erase established Certification unless it contains objective Critical Evidence.

## 39. Conflict Resolution Report

A conflict-resolution assignment SHALL be offered to a Validator that:

- is independent from previous Validators;
- supports the Capability;
- has no Known Control Group conflict;
- has not recently validated the Endpoint.

The Validator receives access to the applicable Validation Guidelines.

It MAY receive prior report summaries only after completing its own independent observations, depending on policy.

## 40. Resolution by Additional Report

For a standard Endpoint, the additional report normally resolves the conflict.

Examples:

```text
CERTIFY
DO_NOT_CERTIFY
CERTIFY
```

may produce:

`CERTIFIED_WITH_OBSERVATIONS`

with all reports attached.

```text
CERTIFY
DO_NOT_CERTIFY
DO_NOT_CERTIFY
```

may produce:

`CERTIFICATION_REVOKED`

or remain uncertified.

## 41. No Blind Majority

The protocol SHALL not derive Certification only by counting report conclusions.

A low-evidence report SHALL not equal a detailed reproducible report merely because both occupy one database row.

Conflict derivation SHALL consider:

- objective evidence;
- report eligibility;
- report quality;
- criticality;
- independent confirmation;
- freshness.

## 42. Objective Critical Evidence

Objective Critical Evidence MAY cause immediate revocation or refusal without waiting for another report.

Examples include:

- invalid cryptographic Endpoint identity;
- forged Usage Reports;
- conflicting signed accounting records;
- malicious protocol responses;
- artifact intentionally mismatched to committed hash;
- consistent proof that the Endpoint is not serving its declared Capability;
- repeated deterministic protocol corruption.

## 43. Subjective Negative Evidence

Subjective observations such as:

- mediocre style;
- unconvincing image;
- weak answer quality;
- high but permitted latency;

SHALL NOT normally trigger immediate revocation.

They may result in:

`CERTIFIED_WITH_OBSERVATIONS`

or:

`DEGRADED`

## 44. Certification Validity

Certification SHALL be time-limited.

Recommended initial standard validity:

```text
CertificationValidity = 30 Epochs
```

With 24-hour Epochs, this is approximately 30 days.

The value is a protocol parameter.

## 45. Validity by Risk Class

Recommended initial periods:

| Risk Class | Validity |
| --- | --- |
| `Standard` | `30 Epochs` |
| `Elevated` | `14 Epochs` |
| `Restricted` | `Capability-specific` |

Shorter validity provides more frequent observation for higher-risk Endpoints.

## 46. Maintenance Validation

A Certified Endpoint SHALL periodically undergo Maintenance Validation.

Maintenance Validation confirms that the Endpoint still:

- responds;
- provides the Capability;
- behaves compatibly;
- reports usage appropriately;
- has not materially degraded.

Maintenance Validation is concealed and non-compensated under `RFC-0064`.

## 47. Maintenance Scheduling

Maintenance Validation SHOULD occur at an unpredictable time inside a configured window.

Example:

```text
Certification effective: Epoch 100
Expiration: Epoch 130
Maintenance window: Epochs 118-126
```

The exact assignment time remains concealed.

## 48. Successful Maintenance

An eligible Maintenance Report with:

`CERTIFY`

normally:

- preserves or renews `CERTIFIED`;
- updates `last_maintenance_epoch`;
- extends expiration;
- may trigger Validation Bond refund.

## 49. Maintenance With Observations

A Maintenance Report with:

`CERTIFY_WITH_OBSERVATIONS`

normally produces:

`CERTIFIED_WITH_OBSERVATIONS`

or preserves that state.

Material observations MAY shorten the next validity period.

## 50. Failed Maintenance

A Maintenance Report with:

`DO_NOT_CERTIFY`

normally causes:

```text
CERTIFIED
->
DEGRADED
```

and schedules a confirmation Validation.

Immediate revocation occurs only when:

- Critical Evidence exists;
- Certification Policy explicitly permits one-report revocation;
- failure is independently deterministic;
- Endpoint is repeatedly unreachable under required attempts.

## 51. Confirmed Maintenance Failure

If a second independent eligible report confirms material failure:

```text
DEGRADED
->
CERTIFICATION_REVOKED
```

The remaining Validation Bond MAY be forfeited according to `ECO-0003`.

## 52. Maintenance Inconclusive

An `INCONCLUSIVE` Maintenance Report SHALL not immediately revoke Certification.

The protocol MAY:

- keep the current status temporarily;
- shorten remaining validity;
- schedule another Validation;
- move to `REVALIDATION_REQUIRED` near expiration.

## 53. Certification Expiration

If no qualifying Maintenance Report is finalized before expiration:

```text
CERTIFIED
->
EXPIRED
```

or:

```text
CERTIFIED_WITH_OBSERVATIONS
->
EXPIRED
```

Expiration does not require a negative report.

## 54. Grace Period

The protocol MAY define a bounded Maintenance Grace Period when:

- no eligible Validator was available;
- Validation Escrow capacity was insufficient;
- consensus was halted;
- protocol failure prevented assignment.

Recommended initial grace period:

`3 Epochs`

The public state SHALL show that Certification is operating under grace.

## 55. No Grace for Endpoint Avoidance

Grace SHALL NOT apply when the Endpoint:

- repeatedly rejected concealed Sessions;
- remained unavailable;
- changed configuration strategically;
- withdrew during assignment;
- prevented required Validation.

Such behavior may cause degradation or expiration normally.

## 56. Configuration Change

An execution-relevant Endpoint change SHALL invalidate Certification for the previous Configuration Hash.

Examples include:

- model change;
- Provider change affecting behavior;
- Runtime change affecting output;
- tokenizer change;
- Capability version change;
- accounting behavior change;
- request schema change;
- output schema change;
- safety-policy change materially affecting execution.

## 57. Commercial-Only Change

A change limited to:

- price;
- minimum ordinary Session Deposit;
- Marketplace description;
- display name;
- ordinary availability schedule;

does not automatically invalidate technical Certification.

The change still creates a new commercial policy version.

## 58. Ambiguous Change

If it is unclear whether a configuration change affects execution:

```text
Certification
->
REVALIDATION_REQUIRED
```

The operator MAY provide deterministic compatibility evidence.

A later protocol version may support Configuration Compatibility Claims.

## 59. Configuration Hash Restoration

Reverting to an older previously Certified Configuration Hash does not automatically restore Certification indefinitely.

Restoration MAY be allowed only when:

- previous Certification has not expired;
- no revocation applies;
- the exact configuration is reproducible;
- policy permits restoration.

Otherwise, new Validation is required.

## 60. Endpoint Version History

Certification history SHALL preserve:

- every Configuration Hash;
- every Certification Record;
- every supporting report;
- every expiration;
- every degradation;
- every revocation;
- every recovery.

An operator cannot erase previous failed versions by publishing a new Endpoint version.

## 61. Triggered Validation

Triggered Validation MAY be created from:

- repeated Session failures;
- repeated Consumer complaints;
- accounting mismatch patterns;
- abnormal error rates;
- Registry or Runtime verification failures;
- suspicious configuration changes;
- random protocol sampling.

A Trigger alone does not prove Endpoint failure.

## 62. Complaint Threshold

A single subjective complaint SHALL not normally alter Certification.

Complaint-triggered Validation SHOULD consider:

- independent complainant count;
- complainant Reputation;
- complaint evidence;
- Session references;
- repeated failure pattern;
- severity.

Complaint economics and abuse protection may be defined separately.

## 63. Emergency Degradation

Objective urgent evidence MAY immediately move:

```text
CERTIFIED
->
DEGRADED
```

before a new Validation Report completes.

Examples include:

- widespread Endpoint failure;
- compromised Endpoint key;
- invalid signed Usage Reports;
- critical security incident.

Emergency degradation SHALL be evidence-backed and auditable.

## 64. Emergency Suspension

A Capability-specific safety policy MAY temporarily suspend public Certification visibility or access.

Emergency suspension is distinct from permanent revocation.

It SHALL require:

- objective evidence;
- defined scope;
- defined recovery path;
- public Ledger record.

## 65. Recovery Validation

A revoked or expired Endpoint MAY request Recovery Validation.

Recovery Validation SHALL bind to:

- current Configuration Hash;
- correction summary;
- previous failure references;
- current Validation Bond state.

## 66. Recovery Certification

A successful Recovery Report MAY produce:

```text
CERTIFICATION_REVOKED
->
CERTIFIED_WITH_OBSERVATIONS
```

or:

```text
EXPIRED
->
CERTIFIED
```

depending on:

- previous failure severity;
- current evidence;
- Certification Policy;
- whether independent confirmation is required.

## 67. Recovery After Critical Failure

After Critical failure, one positive report MAY be insufficient.

The policy MAY require:

- two independent reports;
- new Endpoint key;
- configuration change;
- new Validation Bond;
- additional activation delay;
- specialized verification.

## 68. Validation Bond Relationship

Certification derivation MAY trigger Validation Bond operations.

Examples:

First Successful Certification

`Refund 50% of remaining Validation Bond`

Successful Maintenance

`Refund 50% of remaining Validation Bond`

Qualifying Confirmed Failure

`Forfeit remaining Validation Bond`

Exact Bond policy is governed by `ECO-0003` and `RFC-0035`.

## 69. No Bond Effect From Inconclusive Report

An `INCONCLUSIVE` report SHALL not normally:

- refund Bond;
- forfeit Bond;
- count as successful Maintenance.

The request remains unresolved or is rescheduled.

## 70. No Bond Forfeiture From One Weak Report

A low-quality, ambiguous or subjective negative report SHALL not forfeit the Endpoint Bond.

Bond forfeiture requires:

- eligible evidence;
- qualifying failure class;
- applicable Certification transition;
- deterministic economic rule.

## 71. Validator Reward Independence

Certification result SHALL not affect Validator reward direction.

A Validator is rewarded for report quality, not for producing:

- Certification;
- rejection;
- observations;
- a particular Bond outcome.

This reduces incentives for Validators to favor Endpoint operators or maximize penalties.

## 72. Endpoint Payment Independence

Certification derivation SHALL not depend on Endpoint payment because Validation Sessions pay:

`0Q to the Endpoint`

under `RFC-0064`.

The Endpoint cannot purchase a favorable result through validation pricing.

## 73. Certification State Update

Certification changes occur through:

`CERTIFICATION_STATE_UPDATE`

The operation SHALL include:

```yaml
certification_state_update:
  certification_id:
  endpoint_id:
  endpoint_configuration_hash:
  previous_state:
  new_state:
  policy_version:
  supporting_report_ids:
  conflicting_report_ids:
  derivation_evidence_root:
  effective_epoch:
  expiration_epoch:
```

## 74. Protocol-Generated Derivation

`CERTIFICATION_STATE_UPDATE` SHALL be protocol-generated.

No Endpoint operator or Validator may directly choose the Certification state.

Participants may submit reports and evidence.

The State Machine derives the result.

## 75. Derivation Timing

Certification derivation occurs after:

- report commitment;
- assignment reveal;
- report eligibility validation;
- evidence window;
- conflict detection.

The Epoch Engine MAY derive Certification:

- immediately after finalization;
- in deterministic rounds;
- during Epoch closing tasks.

## 76. Evidence Challenge Window

Before final Certification derivation, the protocol MAY provide a short objective evidence window.

Valid challenges include:

- report does not match assignment;
- wrong Configuration Hash;
- invalid Validator reveal;
- missing Registry object;
- forged evidence;
- self-validation conflict;
- report duplication.

Disagreement with Validator judgment alone is not an objective protocol challenge.

## 77. Report Commentary Remains Immutable

An operator MAY publish a response to a Validation Report.

The response:

- does not modify the report;
- does not erase observations;
- may include corrective context;
- may reference a new configuration;
- may request Recovery Validation.

## 78. Certification Explanation

Every Certification state SHOULD expose a human-readable derivation summary.

Example:

Certified based on one Standard Initial Validation Report.
Endpoint responded successfully.
Validator reported elevated latency and unverifiable upstream token usage.

The summary is informational.

Canonical state remains the structured Certification Record.

## 79. Marketplace Presentation

Marketplace clients SHOULD display:

- Certification state;
- age;
- expiration;
- Configuration Hash;
- supporting report count;
- unresolved observations;
- degraded state;
- last Maintenance Validation;
- Validator identities after reveal.

Marketplace SHALL not display `CERTIFIED` as a universal guarantee of quality.

## 80. Reputation Relationship

Certification and Reputation are separate.

Certification answers:

Was this Endpoint observably functional under one or more bounded validations?

Reputation answers:

How has this Endpoint behaved over time?

A newly Certified Endpoint may have little Reputation history.

A high-Reputation Endpoint may temporarily become `DEGRADED`.

## 81. Certification Does Not Reset Reputation

A successful Recovery Validation SHALL not erase:

- previous failures;
- revocation history;
- Session mismatch history;
- operator history.

Current Certification may improve while historical Reputation remains visible.

## 82. Certification Transfer

Certification SHALL not automatically transfer to:

- another Endpoint ID;
- another owner;
- another Hypervisor;
- another Configuration Hash;
- another Capability.

A future ownership-transfer protocol MAY define limited retention rules.

## 83. Endpoint Cloning

Two Endpoints with identical configuration declarations require separate Certification unless protocol rules establish verifiable shared execution identity.

A copied Configuration Hash alone does not prove identical behavior.

## 84. Shared Runtime Endpoints

Multiple Endpoints backed by one Runtime or Provider remain separate protocol objects.

The protocol MAY later support grouped validation when:

- execution identity is verifiably shared;
- policy and accounting are identical;
- failure domain is identical.

Grouped Certification is deferred from the MVP.

## 85. Certification Policy Versions

Certification rules SHALL be versioned.

A Certification Record SHALL identify the policy under which it was derived.

A later policy upgrade SHALL not silently reinterpret historical Certification.

## 86. Policy Upgrade

A policy upgrade MAY require:

- no action for existing Certification;
- shorter remaining validity;
- `REVALIDATION_REQUIRED`;
- new Maintenance Validation;
- immediate invalidation only for critical incompatibility.

Migration behavior SHALL be explicit.

## 87. Certification Metrics

The network SHOULD publish:

- Certified Endpoint count;
- Certified With Observations count;
- Degraded count;
- Revoked count;
- Expired count;
- median Certification age;
- Validation conflict rate;
- additional-validation rate;
- recovery rate;
- Maintenance failure rate;
- report conclusion distribution;
- time from request to Certification.

## 88. No Global Quality Score

The MVP SHALL not reduce Certification to one global numeric score.

Different Consumers care about different properties:

- latency;
- style;
- price;
- accounting transparency;
- output quality;
- availability;
- privacy.

Reports and Reputation provide richer evidence than one decorative decimal.

## 89. Capability-Specific Extensions

A Capability MAY define additional Certification observations.

Examples:

Image Generation

- dimensions;
- decodability;
- artifact severity;
- blank-output detection.

Speech

- audio validity;
- transcription presence;
- silence detection;
- duration handling.

Agent Execution

- side-effect reporting;
- tool-call transparency;
- workspace behavior;
- cancellation.

Capability extensions SHALL not claim hidden implementation proof without real attestation.

## 90. Certification Derivation Table

For a standard Endpoint without prior Certification:

| Report Set | Result |
| --- | --- |
| One `CERTIFY` | `CERTIFIED` |
| One `CERTIFY_WITH_OBSERVATIONS` | `CERTIFIED_WITH_OBSERVATIONS` |
| One strong `DO_NOT_CERTIFY` | `UNCERTIFIED` |
| One `INCONCLUSIVE` | `INCONCLUSIVE` |
| Conflicting reports | `VALIDATION_PENDING` or `INCONCLUSIVE`; additional Validation |

For an existing Certified Endpoint:

| New Evidence | Result |
| --- | --- |
| Successful Maintenance | Certification renewed |
| Observations | `CERTIFIED_WITH_OBSERVATIONS` |
| One ordinary negative report | `DEGRADED`; confirmation scheduled |
| Confirmed independent failure | `CERTIFICATION_REVOKED` |
| Critical objective evidence | Immediate degradation or revocation |
| No timely Maintenance | `EXPIRED` |

## 91. Epoch Tasks

`RFC-0048` tasks include:

- Freeze Eligible Validation Reports;
- Validate Report Assignments;
- Detect Report Conflicts;
- Evaluate Critical Evidence;
- Derive Initial Certifications;
- Evaluate Maintenance Results;
- Schedule Conflict Resolution;
- Apply Degradation;
- Apply Revocation;
- Apply Expiration;
- Calculate Next Maintenance Windows;
- Generate Certification State Updates;
- Trigger Validation Bond Refunds;
- Trigger Validation Bond Forfeitures;
- Publish Certification Metrics.

## 92. Ledger Operations

This protocol uses:

- `VALIDATION_REQUEST`;
- `VALIDATION_REPORT_COMMIT`;
- `CERTIFICATION_STATE_UPDATE`;
- `VALIDATION_BOND_REFUND`;
- `VALIDATION_BOND_FORFEIT`;
- `PARTICIPANT_SUSPEND`;
- `EPOCH_TRANSITION`.

## 93. Error Codes

The MVP SHALL define at least:

- `CERTIFICATION_REPORT_NOT_ELIGIBLE`
- `CERTIFICATION_CONFIGURATION_MISMATCH`
- `CERTIFICATION_POLICY_MISMATCH`
- `CERTIFICATION_REPORT_CONFLICT`
- `CERTIFICATION_INSUFFICIENT_REPORTS`
- `CERTIFICATION_REPORT_TOO_OLD`
- `CERTIFICATION_ALREADY_DERIVED`
- `CERTIFICATION_STATE_TRANSITION_INVALID`
- `CERTIFICATION_CRITICAL_EVIDENCE_INVALID`
- `CERTIFICATION_MAINTENANCE_OVERDUE`
- `CERTIFICATION_BOND_RULE_NOT_SATISFIED`
- `CERTIFICATION_RECOVERY_REQUIREMENT_NOT_MET`

## 94. Idempotency

Certification derivation SHALL be idempotent.

The same finalized report set and policy version SHALL produce the same Certification state.

Repeated execution SHALL not create:

- duplicate Certification records;
- duplicate Bond refunds;
- duplicate forfeitures;
- duplicate Maintenance Requests.

## 95. MVP Requirements

The MVP SHALL implement:

- all Certification states;
- Configuration Hash binding;
- one-report Initial Certification;
- `CERTIFY_WITH_OBSERVATIONS`;
- negative and inconclusive outcomes;
- time-limited Certification;
- random Maintenance windows;
- degradation before ordinary revocation;
- independent confirmation for ordinary failure;
- Critical Evidence handling;
- conflicting report detection;
- additional validation scheduling;
- Certification expiration;
- Recovery Validation;
- Bond refund and forfeiture triggers;
- Certification history;
- Marketplace status exposure;
- deterministic State Updates.

## 96. Deferred Features

The MVP MAY postpone:

- formal model attestation;
- trusted execution environment evidence;
- grouped Endpoint Certification;
- private Certification Reports;
- zero-knowledge Validation evidence;
- regulator-specific Certification;
- Consumer-defined Certification filters;
- cross-network Certification portability;
- automatic semantic model fingerprinting;
- specialized safety Certification;
- insurance based on Certification.

## 97. Open Protocol Parameters

The following remain configurable:

- Certification validity period;
- validity by risk class;
- Maintenance window;
- Maintenance grace period;
- required report count by risk class;
- conflict-resolution report count;
- ordinary revocation threshold;
- Critical Evidence classes;
- report freshness period;
- report-weight factors;
- complaint threshold;
- Recovery requirements;
- policy-upgrade transition behavior;
- Bond refund and forfeiture triggers.

## 98. Certification Invariants

```text
Certification applies to one Endpoint Configuration Hash
One eligible report is normally sufficient for Standard Initial Certification
Certification does not prove hidden model identity
Conflicting reports remain visible
One ordinary negative Maintenance Report normally causes degradation before revocation
Critical objective evidence may cause immediate revocation
Expired evidence does not remain current Certification forever
Validator Reward does not depend on favorable conclusion
Endpoint Payment does not affect Certification
```

## 99. Security Invariants

- Self-validation reports are ineligible.
- Reports are bound to exact assignments.
- Reports are bound to exact Configuration Hashes.
- Invalid or fabricated reports do not alter Certification.
- Endpoint operators cannot directly choose Certification state.
- Validators cannot directly revoke Certification.
- One weak subjective report cannot ordinarily confiscate the Validation Bond.
- Critical actions require objective evidence.
- Certification history cannot be erased by version changes.
- Policy upgrades do not silently rewrite historical results.

## 100. Design Invariants

- Certification is an observable-behavior trust signal.
- Validation remains flexible rather than rigidly benchmark-driven.
- One useful report normally enables Initial Certification.
- Additional Validators are used when risk or conflicting evidence justifies them.
- Certification states preserve uncertainty.
- Observations remain visible to Consumers.
- Previously Certified Endpoints degrade before ordinary revocation.
- Certification expires without Maintenance.
- Configuration changes require reevaluation.
- Certification and Reputation remain separate.
- Validation Reports remain the primary human-readable evidence.
- The protocol does not pretend to know hidden implementation details it cannot verify.
