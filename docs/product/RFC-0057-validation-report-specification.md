# RFC-0057 Validation Report Specification

Status: `Draft`

Version: `0.2`

Supersedes:

- `RFC-0057 Version 0.1`

Depends on:

- `RFC-0035 Validation Escrow System`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0051 Usage Reporting and Verification Protocol`
- `RFC-0040 Service Verification Framework`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0044 Session Protocol`
- `RFC-0045 Capability Architecture`
- `RFC-0046 Registry Architecture`
- `RFC-0048 Epoch Engine`

## 1. Purpose

This document defines the structure, lifecycle, and interpretation of Endpoint Validation Reports within the AiDN network.

A Validation Report records observable behavior collected by a Validator during interaction with an Endpoint.

Validation Reports provide evidence.

They do not prove the identity of the underlying model, Provider, or implementation.

## 2. Validation Philosophy

AiDN Validation certifies observable operational behavior.

Validation SHALL NOT claim to prove:

- the exact model implementation;
- the exact Provider;
- local or remote execution;
- model ownership;
- hidden execution topology;
- internal orchestration.

Validation MAY establish that an Endpoint:

- is reachable;
- accepts valid Session requests;
- implements the declared Capability;
- returns meaningful output;
- follows protocol rules;
- reports usage in a verifiable format;
- behaves consistently with its published description.

## 3. Primary Output

The primary output of Endpoint Validation is a signed Validation Report.

The primary output is not a binary decision.

Certification Status is derived from one or more Validation Reports according to deterministic protocol rules.

## 4. Report Object

Every Validation Report SHALL contain:

```yaml
validation_report:
  report_id:
  report_hash:
  report_size:
  report_version:
  validation_assignment_id:
  endpoint_id:
  endpoint_configuration_hash:
  advertisement_id:
  capability_id:
  capability_version:
  model_class:
  validator_service_id:
  validator_signature:
  epoch:
  started_at:
  completed_at:
  execution_mode:
  request_records:
  response_records:
  observations:
  measurements:
  protocol_compliance:
  accounting_verification:
  issues:
  conclusion:
  limitation_codes:
  failure_codes:
  observation_codes:
  evidence_bundle_root:
  evidence_access_class:
  evidence_references:
```

All fields affecting interpretation SHALL be covered by the Validator signature.

## 5. Report Identity

`report_hash` SHALL be derived from the canonical serialized report body excluding `report_id`, `report_hash`, `report_size`, transport locators, Storage Receipts and signatures. The Validator signature SHALL cover `report_hash` together with the assignment and network domain.

For the MVP, `report_id` SHOULD equal the content-addressed `report_hash` or use a versioned domain-separated derivation from it.

A modified report produces a different identifier.

Reports are immutable after publication.

Corrections require a new report referencing the previous report.

## 6. Endpoint Binding

Every report SHALL bind observations to:

- Endpoint ID;
- Configuration Hash;
- Capability ID;
- Advertisement version.

A report SHALL NOT automatically apply to a later Configuration Snapshot.

Any execution-relevant Endpoint modification MAY invalidate existing certification applicability.

## 7. Validator Identity

The published report SHALL contain the identity of the validating service.

Validator anonymity is required while validation traffic is in progress.

Validator identity MAY become public when the report is finalized and published.

The Endpoint SHALL NOT receive Validator identity before report publication.

## 8. Execution Mode

A Validator MAY perform validation through:

- automated agent execution;
- manual operator execution;
- hybrid execution.

The report SHALL declare:

```yaml
execution_mode:
  type: automated | manual | hybrid
  agent_id:
  agent_version:
  operator_attestation:
```

Automated and manual reports are protocol-equivalent if they satisfy the same evidence requirements.

## 9. Voluntary Assignment

Receiving a Validation Assignment does not force the Validator to execute it.

A Validator MAY:

- accept the assignment;
- decline the assignment;
- allow the assignment to expire.

A declined assignment generates no Validation Reward.

Declining before acceptance SHALL NOT be treated as misconduct.

After accepting an assignment, the Validator is expected to complete it within the assignment deadline.

Repeated accepted-but-unfinished assignments MAY reduce Validation Service Health and Reputation.

## 10. Assignment Acceptance

Assignment acceptance SHALL produce a signed protocol event containing:

- Assignment ID;
- Validator Service ID;
- acceptance timestamp;
- expected completion deadline.

Once accepted, the assignment is reserved for that Validator until:

- completion;
- explicit release;
- expiration;
- protocol reassignment.

## 11. Validation Request Design

Validators MAY design their own representative requests.

Validation requests SHALL remain within the declared Capability and published Endpoint policy.

Requests SHOULD test:

- basic functionality;
- meaningful response generation;
- protocol compatibility;
- declared formats;
- obvious failure conditions;
- relevant advertised features.

The protocol SHALL NOT require one universal fixed test for all Endpoints.

## 12. Capability Guidelines

Each Capability SHALL define broad Validation Guidelines.

Guidelines SHALL specify:

- permissible request types;
- minimum evidence requirements;
- critical failure conditions;
- recommended observations;
- capability-specific measurements.

Guidelines SHOULD avoid excessive rigidity.

They define boundaries, not one mandatory prompt or test case.

## 13. Request Records

Every report SHALL include sufficient information to understand what was tested.

A Request Record includes:

```yaml
request_record:
  request_id:
  request_type:
  request_summary:
  request_hash:
  parameters:
  submitted_at:
```

Full request payload MAY be omitted when it contains:

- private data;
- copyrighted material;
- security-sensitive content;
- excessive binary data.

When omitted, the report SHALL include a hash and meaningful summary.

## 14. Response Records

Every tested request SHALL reference a corresponding Response Record.

```yaml
response_record:
  request_id:
  response_status:
  response_summary:
  response_hash:
  content_type:
  received_at:
  latency:
  artifact_references:
```

Large outputs SHOULD be stored off-chain.

The report SHALL reference them using immutable content identifiers or hashes.

## 15. Privacy

Validation Reports SHALL NOT publish private Session payloads unnecessarily.

Validators SHALL minimize exposed content.

Reports SHOULD publish:

- summaries;
- hashes;
- measurements;
- selected non-sensitive evidence;
- artifact references.

Sensitive raw prompts or outputs MAY remain encrypted or omitted according to Capability policy.

## 16. Observations

Observations describe the Validator’s interpretation of the Endpoint response.

Each observation SHALL include:

```yaml
observation:
  category:
  severity:
  description:
  supporting_evidence:
  confidence:
```

Observation categories MAY include:

- availability;
- response validity;
- capability compatibility;
- output coherence;
- artifact quality;
- latency;
- protocol behavior;
- accounting behavior;
- advertised-feature behavior.

## 17. Observation Severity

Initial severity levels are:

- `INFO`
- `MINOR`
- `MAJOR`
- `CRITICAL`

`INFO`

Descriptive observation without detected failure.

`MINOR`

Non-critical issue that does not prevent ordinary use.

`MAJOR`

Significant degradation or mismatch affecting expected use.

`CRITICAL`

Failure preventing certification.

## 18. Critical Conditions

Critical conditions MAY include:

- Endpoint unavailable throughout the validation window;
- Session cannot be opened;
- repeated protocol errors;
- response is empty or unusable;
- declared Capability is not implemented;
- output type is invalid;
- accounting cannot be verified;
- obvious malicious protocol behavior;
- response consistently consists of meaningless data;
- Endpoint fails all representative requests.

Capability Guidelines MAY define additional critical conditions.

## 19. Meaningful Output

A meaningful output is one that plausibly corresponds to the submitted request and declared Capability.

Examples:

LLM

- coherent textual response;
- expected response format;
- non-empty output;
- no persistent protocol corruption.

Image Generation

- valid image artifact;
- declared dimensions or format;
- visually non-empty result;
- output plausibly related to the request.

STT

- valid transcription;
- output corresponds meaningfully to submitted audio;
- output is not empty or random text.

TTS

- valid audio;
- audible speech;
- speech plausibly corresponds to submitted text;
- output is not silence or white noise.

Meaningful output does not imply excellent output.

It establishes basic operational validity.

## 20. Measurements

Reports SHOULD contain objective measurements where available.

Examples include:

- response latency;
- time to first token;
- token throughput;
- image dimensions;
- file format;
- audio duration;
- video duration;
- resolution;
- error count;
- retry count;
- successful request ratio.

Measurements SHALL distinguish observed values from Validator interpretation.

## 21. Protocol Compliance

The report SHALL evaluate protocol compliance.

Possible checks include:

- valid Session lifecycle;
- authenticated messages;
- supported protocol version;
- correct response schema;
- valid content type;
- orderly Session termination;
- required metadata;
- timeout behavior.

Protocol violations SHALL be recorded separately from output-quality observations.

## 22. Accounting Verification

The report SHALL include accounting observations where applicable.

Initial status values are:

- `NOT_TESTED`
- `VERIFIED`
- `MISMATCH`
- `UNVERIFIABLE`

Detailed accounting verification is defined by `RFC-0051`.

An accounting mismatch MAY constitute a Critical issue.

## 23. Issue Record

Every detected issue SHALL contain:

```yaml
issue:
  issue_id:
  category:
  severity:
  description:
  affected_request_ids:
  evidence_references:
  reproducible:
  validator_confidence:
```

Issues SHALL be factual and specific.

Validators SHOULD avoid unsupported claims about hidden implementation details.

## 24. Conclusion

Every Validation Report SHALL contain a structured conclusion.

```yaml
conclusion:
  operational_status:
  capability_status:
  protocol_status:
  accounting_status:
  recommendation:
  summary:
```

Suggested values include:

Operational Status

- `OPERATIONAL`
- `DEGRADED`
- `UNAVAILABLE`
- `INCONCLUSIVE`

Capability Status

- `CONSISTENT`
- `PARTIALLY_CONSISTENT`
- `INCONSISTENT`
- `INCONCLUSIVE`

Protocol Status

- `COMPLIANT`
- `MINOR_VIOLATIONS`
- `MAJOR_VIOLATIONS`
- `NON_COMPLIANT`

Recommendation

- `CERTIFY`
- `CERTIFY_WITH_OBSERVATIONS`
- `DO_NOT_CERTIFY`
- `INCONCLUSIVE`

The recommendation is part of the report.

The final Certification Status is derived by protocol rules.

## 25. Model Class Interpretation

A report MAY assess whether observed behavior is broadly consistent with the declared Model Class.

A report SHALL NOT claim cryptographic proof of model identity.

Allowed statement:

Observed behavior is broadly consistent with the declared model class.

Disallowed statement:

The Endpoint definitively runs Model X.

Model Class validation is behavioral, not implementation-identifying.

## 26. Certification Derivation

An Endpoint MAY receive Certified status when:

- at least one valid Initial Validation Report exists;
- no Critical issue is present;
- the report recommendation is `CERTIFY` or `CERTIFY_WITH_OBSERVATIONS`;
- required accounting checks pass or are not applicable;
- the Validator was eligible at assignment time;
- the report was finalized through the Ledger.

The initial MVP MAY derive certification from one completed report.

Future protocol versions MAY require multiple independent reports for selected Capability or Model Classes.

## 27. Certification States

Initial Certification States are:

- `UNCERTIFIED`
- `VALIDATION_PENDING`
- `CERTIFIED`
- `CERTIFIED_WITH_OBSERVATIONS`
- `DEGRADED`
- `CERTIFICATION_REVOKED`
- `INCONCLUSIVE`

Certification State SHALL be derived from report history and current Configuration Hash.

It SHALL NOT be set manually by the operator.

## 28. Failed Initial Validation

If an Initial Validation Report recommends `DO_NOT_CERTIFY`:

- the Endpoint remains Uncertified;
- the report is published;
- the operator MAY correct the Endpoint;
- the operator MAY request another validation;
- a new Configuration Hash SHALL be used if execution behavior changed.

Failure does not erase previous reports.

## 29. Maintenance Validation

Maintenance Validation produces the same report format as Initial Validation.

Maintenance reports SHOULD emphasize:

- availability changes;
- latency changes;
- error-rate changes;
- protocol regressions;
- accounting inconsistencies;
- advertised-feature changes;
- obvious output degradation.

Maintenance Validation MAY be scheduled due to:

- random sampling;
- reduced Reputation Metrics;
- user reports;
- increased error rates;
- abnormal latency;
- Configuration changes.

## 30. Maintenance Failure

A Maintenance Report containing a Critical issue SHALL:

- revoke or suspend Certification Status;
- forfeit the remaining Validation Bond according to `ECO-0003`;
- update relevant Reputation Metrics;
- publish the report and evidence references.

Previously refunded portions of the Validation Bond remain with the operator.

## 31. Inconclusive Reports

A Validator MAY publish an Inconclusive Report.

Examples include:

- intermittent network failure;
- insufficient evidence;
- ambiguous Capability behavior;
- unavailable verification tools;
- incomplete execution before deadline.

An Inconclusive Report does not certify or invalidate the Endpoint.

Validator compensation for Inconclusive Reports MAY be reduced or withheld according to protocol rules.

This prevents richly formatted nothingness from becoming a profitable industry.

## 32. Validator Reward Eligibility

A Validator receives a Validation Reward only if the report:

- corresponds to an assigned Endpoint;
- was accepted within the assignment window;
- satisfies the required schema;
- includes the minimum required evidence;
- is signed;
- is published before the deadline;
- passes protocol-level report validation.

Reward eligibility SHALL NOT depend on whether the conclusion is positive or negative.

## 33. Report Quality

Report quality MAY be evaluated through:

- schema completeness;
- evidence completeness;
- reproducibility;
- consistency with attached artifacts;
- later reports from independent Validators;
- confirmed false statements;
- repeated low-information reports.

Report-quality metrics contribute to the Validation Service Reputation Profile.

## 34. False or Malicious Reports

A report MAY be challenged when it contains evidence of:

- fabricated requests;
- fabricated responses;
- invalid artifact hashes;
- contradictory signed data;
- impossible measurements;
- deliberate misrepresentation.

Challenges SHALL include cryptographic or reproducible evidence.

Confirmed malicious reporting MAY result in:

- Validator Reward cancellation;
- Reputation reduction;
- temporary suspension;
- Validator Stake slashing;
- removal from the Validator pool.

Subjective disagreement about output quality alone SHALL NOT constitute malicious reporting.

## 35. Conflicting Reports

Different Validators MAY produce different observations.

Conflicting reports SHALL remain visible.

The Registry SHALL NOT delete or overwrite them.

Certification derivation MAY consider:

- report recency;
- Validator Reputation Profile;
- evidence quality;
- Configuration Hash;
- issue severity;
- number of independent reports.

Conflicting subjective opinions do not automatically invalidate either report.

Conflicting objective protocol facts require further verification.

## 36. Report Aggregation

The Marketplace MAY present an aggregate Validation Summary.

Aggregation MAY include:

- number of reports;
- last validation time;
- observed availability;
- Critical issue count;
- Minor issue count;
- accounting-verification history;
- common observations.

Aggregate summaries SHALL link to underlying reports.

They SHALL NOT replace the reports.

## 37. Registry Storage

Validation Reports are immutable content-addressed protocol objects, but Full Registry replication of every complete report is not required.

The validated Endpoint Hypervisor SHALL be the mandatory origin custodian for every committed report concerning that Endpoint. Registry Services SHALL store or index the compact Validation Commitment and MAY mirror the complete report or its Evidence Bundle.

The origin locator SHALL be a stable logical AiDN locator rather than a transport URL:

```text
aidn://endpoint/<endpoint_id>/validation/<report_hash>
```

Registry indexes and optional mirrors SHALL preserve:

- canonical report metadata;
- report hash;
- Validator signature;
- evidence references;
- canonical conclusion and limitation codes;
- related Configuration Hash.

Large artifacts MAY be stored separately and referenced by content hash.

An optional mirror does not release the Endpoint from its origin-custody obligation.

## 38. Ledger Integration

The full Validation Report and Evidence Bundle SHALL remain off-chain.

The Ledger SHALL store at minimum:

- Validation ID and Assignment ID;
- Endpoint ID and Configuration Hash;
- Capability ID and version;
- Validator Service ID;
- validation Epoch;
- canonical conclusion;
- objective failure, limitation and observation codes required for deterministic Certification derivation;
- Report ID, hash, size, schema version and logical locator;
- Evidence Bundle root and access class;
- Retention Policy ID;
- Endpoint Storage Receipt hash when custody was accepted;
- Validator signature;
- Endpoint signature when a Storage Receipt exists.

The compact commitment SHALL contain enough structured information to derive Certification even when the complete report is temporarily unavailable. The report supplies explanation and auditable evidence; it SHALL NOT be the only location of a state-machine input.

### Validation Report Storage Receipt

After validating and durably storing a report, the Endpoint Hypervisor SHALL issue:

```yaml
validation_report_storage_receipt:
  validation_id:
  endpoint_id:
  endpoint_configuration_hash:
  report_hash:
  report_size:
  stored_at:
  report_locator:
  retention_policy_id:
  endpoint_public_key:
  endpoint_signature:
```

The receipt proves acceptance of custody, not agreement with the report conclusion.

Where Validator identity remains concealed until commitment, the transfer envelope SHALL use an assignment-scoped signature or proof bound to the concealed Assignment Commitment. The permanent Validator Service signature may remain sealed until identity reveal; the finalized Public Report SHALL expose it afterwards.

An Endpoint refusal SHALL NOT suppress the Validator's canonical conclusion. The Validator MAY commit the report result together with `REPORT_STORAGE_REFUSED`; positive Certification requires accepted custody, while adverse or inconclusive evidence remains eligible according to Certification policy.

## 39. Epoch Integration

The Epoch Engine schedules Validation Report assignments.

Relevant Epoch Tasks include:

- Generate Validation Assignments
- Accept Validation Assignments
- Collect Validation Reports
- Verify Storage Receipts
- Schedule Report Availability Challenges
- Apply Custody Grace Periods
- Verify Report Eligibility
- Derive Certification States
- Calculate Validator Rewards
- Update Reputation Profiles

Task order SHALL be determined through `RFC-0048` dependencies.

## 40. Report Publication Timing

Validator identity and report contents SHALL remain unpublished while testing is active.

The complete report SHALL be published only after:

- validation execution completes;
- evidence is finalized;
- the Validator signs the report.

The Validator SHALL transfer the immutable report through an assignment-authorized envelope to the Endpoint Hypervisor before ordinary completion. It SHALL retain a temporary immutable copy until the Storage Receipt and commitment finalize or the applicable dispute window ends.

This reduces the Endpoint’s ability to detect and adapt to active validation.

## 41. Retention

Every committed report SHALL remain logically addressable by Report Hash.

The Endpoint Hypervisor SHALL retain the complete Public Validation Report while the Endpoint exists and for the configured Retirement Grace Period afterwards. Evidence Bundles SHALL follow their committed access and retention policy, which SHALL not be shortened retroactively.

Report hashes and Certification State transitions SHALL remain verifiable through Ledger history.

Custody availability states are:

- `AVAILABLE`;
- `TEMPORARILY_UNAVAILABLE`;
- `WITHHELD`;
- `LOST`;
- `CORRUPTED`;
- `ACCESS_RESTRICTED`.

One failed retrieval SHALL normally produce only `TEMPORARILY_UNAVAILABLE`. `WITHHELD`, `LOST`, `CORRUPTED` and unauthorized access restriction require objective evidence or repeated checks after a bounded grace period.

### Public Report and Evidence Bundle

The Public Validation Report SHALL contain the signed structured conclusion, safe observations, usage summary, limitation and failure codes, and evidence hashes needed to explain Certification. It SHALL avoid unnecessary raw private Session content.

Large or sensitive material SHALL be placed in a separate Evidence Bundle with one of:

- `PUBLIC`;
- `ENCRYPTED`;
- `RESTRICTED`;
- `HASH_COMMITTED`.

Availability checks SHALL respect the committed access class. Restricted evidence is challenged by authorized actors and is not made public merely to prove custody.

## 42. Capability Extensions

Each Capability MAY extend the report with namespaced fields.

Example:

```yaml
capability_observations:
  image.generate:
    width:
    height:
    visual_artifacts:
    prompt_alignment:
```

Unknown optional fields SHALL be preserved by Registry implementations where practical.

Core report semantics SHALL remain unchanged.

## 43. Human-Readable Reports

Every report SHOULD contain a human-readable summary suitable for Marketplace display.

The summary SHALL distinguish:

- measured facts;
- Validator observations;
- subjective interpretation;
- protocol conclusion.

Machine-readable fields remain authoritative for protocol processing.

## 44. Design Invariants

- Validation Reports record observable behavior.
- Reports do not prove hidden model identity.
- Validators publish evidence rather than absolute truth.
- Manual and automated validation are both permitted.
- Validators may decline unaccepted assignments.
- Accepted assignments are expected to be completed.
- Certification is derived from reports.
- Report history is immutable.
- The Endpoint is the mandatory origin custodian, not the editor, of its reports.
- Storage refusal cannot erase an adverse Validation result.
- Canonical Certification inputs remain available in the compact commitment.
- Subjective quality differences alone do not cause protocol failure.
- Critical operational or protocol failures prevent certification.
- Rewards compensate valid report production, not positive outcomes.
- Every published conclusion remains traceable to evidence.
