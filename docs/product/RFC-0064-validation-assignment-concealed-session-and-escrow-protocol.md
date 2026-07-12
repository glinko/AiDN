# RFC-0064 Validation Assignment, Concealed Session and Escrow Protocol

Status: `Draft`

Version: `0.2`

Supersedes:

- `RFC-0064 Version 0.1`

Depends on:

- `ECO-0003 Validation Economics`
- `ECO-0004 Protocol Service Reward Distribution`
- `ECO-0005 Q Emission, Recycling and Epoch Reward Allocation`
- `RFC-0035 Validation Escrow System`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0040 Service Verification Framework`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0044 Session Protocol`
- `RFC-0045 Capability Architecture`
- `RFC-0048 Epoch Engine`
- `RFC-0051 Usage Reporting and Verification Protocol`
- `RFC-0057 Validation Report Specification`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0059 Ledger Operation Catalog`
- `RFC-0060 Session Failure, Recovery and Forced Settlement`

## 1. Purpose

This document defines how AiDN:

- receives Endpoint Validation Requests;
- places requests into validation queues;
- selects eligible Validators;
- forms shared Validation Escrow;
- privately offers assignments;
- permits voluntary acceptance and decline;
- conceals Validator identity and assignment purpose;
- authorizes apparently funded validation Sessions;
- prevents Endpoint compensation for validation workload;
- returns validation Session collateral to Escrow;
- handles assignment completion, expiration and reassignment;
- commits Validation Reports;
- calculates Validator reward eligibility;
- prevents self-validation and validation-resource abuse.

This protocol governs assignment, concealed execution and validation-specific Session settlement.

Validation Report contents are defined by `RFC-0057`.

Certification derivation is defined separately.

## 2. Core Economic Principle

An Endpoint SHALL NOT receive Q for processing an authorized Validation Session.

Validation processing is an obligation accepted by the Endpoint operator when requesting or maintaining Certification.

The Validation Session Deposit exists to:

- conceal the validation purpose;
- demonstrate apparent payment capacity;
- satisfy ordinary Session admission requirements;
- limit protocol exposure;
- make the Session externally resemble an ordinary funded Session.

The Deposit is not compensation for validation computation.

After the assignment is revealed and the Validation Session is finalized:

```text
Endpoint Payment = 0Q
```

and the remaining Deposit returns to Validation Escrow, except for:

- finalized Network Fees;
- explicitly defined protocol costs;
- finalized penalties unrelated to Endpoint compensation.

## 3. Separation of Economic Flows

The protocol distinguishes four independent economic objects.

### 3.1 Validation Bond

Locked by the Endpoint operator as collateral for Certification obligations.

The Validation Bond:

- is not payment to the Validator;
- is not payment to the Endpoint;
- may be gradually refunded after successful Maintenance Validations;
- may be forfeited after qualifying validation failure.

### 3.2 Validation Escrow

Funded by eligible Validators through shared contributions.

Validation Escrow:

- backs concealed Session Deposits;
- provides assignment capacity;
- hides individual Validator balances;
- normally returns to Escrow after validation settlement.

### 3.3 Validation Session Deposit

Temporarily reserved from shared Escrow for one concealed Validation Session.

The Deposit:

- demonstrates sufficient funding;
- is single-use;
- is bounded;
- does not become Endpoint revenue.

### 3.4 Validator Activity Reward

Paid separately from the Validation Activity Pool.

The Validator earns reward for:

- executing the assignment;
- collecting evidence;
- publishing a useful Validation Report.

Validator reward does not come from the validation Session Deposit.

## 4. Validation Participation Obligation

An Endpoint operator requesting Certification SHALL accept the Validation Participation Obligation.

The obligation includes:

- processing bounded concealed Validation Sessions;
- producing ordinary Usage Reports;
- not receiving Q for validation workload;
- accepting validation-specific settlement;
- permitting Maintenance and Triggered Validation while Certification remains active;
- accepting consequences for repeated refusal or unavailability.

An operator unwilling to accept these terms SHALL not request or retain Certification.

## 5. No Free Public Compute

A Validation Session is economically free only to the validation mechanism.

It is not a general free-compute interface.

Only a valid protocol assignment may authorize zero-payment execution.

The following SHALL NOT receive validation treatment:

- ordinary Consumer Sessions;
- self-created Validator traffic;
- unassigned test requests;
- reused Session authorizations;
- requests exceeding assignment limits;
- requests unrelated to Validation Guidelines.

## 6. Validation Participants

The protocol involves:

Endpoint Operator

Owns or operates the Endpoint being validated.

Validation Request

Represents Initial, Maintenance, Triggered or Recovery Validation demand.

Validator Service

An eligible Service performing validation work.

Validation Assignment

A private and time-bounded authorization connecting a Validator to a Validation Request.

Validation Escrow

A shared source of temporary Session collateral.

Epoch Engine

Schedules offers, reservations, expiration and reassignment.

Registry

Stores reports and evidence.

Ledger

Stores commitments, reservations, assignment state and economic outcomes.

## 7. Validation Types

Initial types are:

- `INITIAL`
- `MAINTENANCE`
- `TRIGGERED`
- `RECOVERY`

`INITIAL`

Requested before first Certification.

`MAINTENANCE`

Confirms continued Endpoint operation.

`TRIGGERED`

Created because of:

- user complaints;
- repeated Session failures;
- accounting anomalies;
- Reputation changes;
- random risk sampling;
- protocol observations.

`RECOVERY`

Performed after:

- Endpoint correction;
- Certification revocation;
- configuration repair;
- failed previous validation;
- protocol migration.

## 8. Validation Request Lifecycle

```text
CREATED
    ->
QUEUED
    ->
OFFERING
    ->
ASSIGNED
    ->
EXECUTING
    ->
REPORT_PENDING
    ->
COMPLETED
```

Alternative states:

- `WAITING_FOR_CAPACITY`
- `WAITING_FOR_ESCROW`
- `NO_ELIGIBLE_VALIDATOR`
- `ASSIGNMENT_EXPIRED`
- `REASSIGNMENT_PENDING`
- `CANCELLED`
- `SUPERSEDED`

## 9. Assignment Lifecycle

```text
PLANNED
    ->
OFFERED
    ->
ACCEPTED
    ->
COLLATERAL_RESERVED
    ->
EXECUTING
    ->
REPORT_COMMITTED
    ->
VALIDATION_SETTLED
    ->
COMPLETED
```

Alternative states:

- `DECLINED`
- `OFFER_EXPIRED`
- `RELEASED`
- `EXECUTION_EXPIRED`
- `ABANDONED`
- `INVALIDATED`

## 10. Validation Request Creation

A Validation Request SHALL include:

```yaml
validation_request:
  validation_request_id:
  validation_type:
  endpoint_id:
  endpoint_configuration_hash:
  capability_id:
  request_epoch:
  request_expiration:
  validation_bond_reference:
  validation_policy_version:
  priority_class:
```

An Initial Request requires a valid Validation Bond.

Maintenance and Triggered Requests may be protocol-generated.

## 11. Configuration Binding

Every Validation Request SHALL bind to an exact:

`Endpoint Configuration Hash`

If execution-relevant configuration changes before report completion:

- the assignment becomes invalid;
- the request becomes `SUPERSEDED`;
- the Session cannot certify the new configuration;
- a new Validation Request is required.

A pricing-only change does not necessarily change technical configuration, but it may invalidate Session concealment or collateral sizing.

## 12. Validation Queue

Requests enter Capability-specific queues.

Queues MAY be partitioned by:

- Capability;
- Validation Type;
- required tools;
- complexity;
- artifact type;
- request age;
- priority;
- validation policy.

Queue ordering SHALL be deterministic.

## 13. Queue Priority

Initial priority MAY consider:

```text
Priority
=
ValidationTypePriority
+
QueueAge
+
RiskPriority
+
CertificationExpiryPriority
+
RecoveryPriority
```

Recommended ordering:

1. urgent Triggered Validation;
2. Maintenance near Certification expiry;
3. Recovery Validation;
4. Initial Validation;
5. random non-urgent Maintenance.

## 14. Validator Eligibility

A Validator may receive an offer only when it has:

- valid Validation Service Identity;
- valid Reward Beneficiary;
- required Validation Stake;
- minimum activation age;
- acceptable Validation Reputation;
- acceptable Health;
- compatible Capability profile;
- available assignment capacity;
- no applicable suspension;
- compatible protocol version.

## 15. Validator Capability Profile

```yaml
validator_capability_profile:
  validator_service_id:
  supported_capabilities:
  supported_artifact_types:
  automated_execution:
  manual_execution:
  hybrid_execution:
  maximum_concurrent_assignments:
  maximum_assignment_complexity:
  supported_accounting_checks:
  tool_profile_hash:
```

This profile determines assignment eligibility.

It does not reveal actual assignments.

## 16. Manual and Automated Validation

A Validator MAY validate through:

- `AUTOMATED`
- `MANUAL`
- `HYBRID`

All modes are valid when they satisfy:

- assignment boundaries;
- evidence requirements;
- report schema;
- deadlines;
- privacy rules;
- Session limits.

## 17. Validator Discretion

The Validator MAY create representative test requests within:

- Capability Validation Guidelines;
- Endpoint access policy;
- assignment limits;
- safety rules;
- time limits;
- request-count limits;
- artifact limits.

Validation SHALL not require one universal prompt or benchmark.

## 18. Validation Guidelines

Each Capability SHOULD define broad guidelines including:

- permitted test categories;
- recommended interactions;
- minimum attempts;
- artifact checks;
- accounting checks;
- critical failure conditions;
- privacy constraints;
- maximum workload;
- prohibited value-extraction tasks.

Guidelines constrain abuse without making validation artificially rigid.

## 19. Prohibited Validation Use

A Validator SHALL NOT use a Validation Assignment to obtain unrelated personal or commercial work.

Prohibited examples include:

- completing the Validator's own software project;
- generating unrelated media assets;
- performing unrelated research;
- using an agent Endpoint for private administration;
- extracting maximum output without validation purpose;
- forwarding work for another Consumer.

Validation work SHALL be reasonably connected to observable Endpoint evaluation.

## 20. Voluntary Offer Model

Assignments are offered privately.

A Validator MAY:

- accept;
- decline;
- ignore until expiration.

Declining an unaccepted offer is not misconduct.

No obligation exists before acceptance.

## 21. Validation Offer

```yaml
validation_offer:
  offer_id:
  assignment_commitment:
  validation_type:
  capability_id:
  complexity_class:
  permitted_request_budget:
  maximum_request_count:
  maximum_execution_window:
  report_deadline:
  offer_expiration:
```

The Endpoint identity MAY remain concealed until acceptance where practical.

## 22. Private Offer Delivery

Offers SHALL use:

- Validator encryption key;
- authenticated transport;
- sealed payload;
- replay-protected Offer ID.

Public state SHALL not reveal the selected Validator.

## 23. Assignment Commitment

```yaml
assignment_commitment:
  assignment_id:
  validation_request_id:
  assignment_epoch:
  encrypted_validator_commitment:
  escrow_reservation_commitment:
  report_deadline:
  commitment_hash:
```

The commitment proves an assignment existed without revealing its Validator.

## 24. Validator Acceptance

```yaml
assignment_acceptance:
  assignment_id:
  offer_id:
  validator_service_id:
  accepted_at:
  assignment_key:
  capability_profile_hash:
  signature:
```

Acceptance SHALL occur before Offer expiration.

## 25. Assignment Key

Every assignment uses a fresh Assignment Key.

It:

- authorizes validation-session actions;
- is unique to one assignment;
- is bound to the hidden commitment;
- does not expose the ordinary Validator key;
- expires after assignment completion.

## 26. Acceptance Consequences

After acceptance:

- Validator capacity is reserved;
- Escrow collateral is reserved;
- the assignment becomes exclusive;
- execution and report deadlines become binding;
- the Validator must complete or formally release the assignment.

Acceptance alone earns no reward.

## 27. Assignment Release

A Validator MAY release an assignment before execution.

Release SHALL:

- return the request to the queue;
- release Escrow collateral;
- release Validator capacity;
- expire Session credentials.

Occasional early release SHOULD have minimal Reputation impact.

## 28. Assignment Abandonment

An assignment is abandoned when the Validator:

- accepted it;
- failed to release it;
- failed to produce required evidence;
- allowed deadlines to expire.

Consequences include:

- no Validator reward;
- reassignment;
- reduced Assignment Reliability;
- temporary offer cooldown after repeated abandonment.

## 29. Post-Execution Abandonment

Post-execution abandonment occurs when:

- the Validator consumed Endpoint validation work;
- Session evidence shows meaningful execution;
- no valid Validation Report was published;
- no external failure justifies the omission.

This is more serious than abandonment before execution.

It MAY cause:

- loss of an Assignment Performance Bond;
- temporary Validation suspension;
- strong Assignment Reliability reduction;
- future assignment limits;
- protocol penalty when objective evidence exists.

This protects Endpoints from Validators using concealed Sessions as free personal compute.

## 30. Validation Escrow Purpose

Validation Escrow provides temporary Session collateral.

Its purposes are to:

- hide Validator Wallet balance;
- demonstrate sufficient apparent funding;
- satisfy Endpoint minimum Deposit requirements;
- authorize bounded concealed execution;
- limit assignment exposure;
- make validation traffic resemble ordinary Session traffic.

Validation Escrow is not a payment pool for Endpoints.

## 31. Escrow Is Protocol-Controlled

Validation Escrow SHALL be represented by canonical Ledger state.

It SHALL NOT depend on:

- one custodian Wallet;
- one centralized server;
- one operator holding pooled keys.

Reservations and releases derive from deterministic protocol rules.

## 32. Validator Escrow Contribution

A Validator MAY lock:

`x1`, `x2`, `x3`, ...

Validation Escrow Units.

The multiplier defines maximum assignment capacity.

Example:

```text
x1 = one assignment slot
x2 = two assignment slots
x3 = three assignment slots
```

It does not multiply reward automatically.

## 33. Validation Escrow Unit

For Epoch t:

```text
ValidationEscrowUnit(t)
=
max(
    ProtocolEscrowFloor,
    MedianRequiredValidationCollateral(t)
)
```

The median SHOULD use qualified queued Endpoints.

Capability-specific units MAY be calculated when costs differ substantially.

## 34. Required Validation Collateral

For Endpoint e:

```text
RequiredValidationCollateral(e)
=
max(
    EndpointMinimumSessionDeposit,
    ConcealmentCollateralFloor
)
+
ProtocolFeeReserve
```

This amount represents apparent Session funding.

It does not represent expected Endpoint revenue.

## 35. Why Published Pricing Still Matters

The validation mechanism may need to emulate an ordinary Session accepted under the Endpoint's public pricing policy.

Therefore, collateral sizing MAY consider:

- minimum Session Deposit;
- maximum request exposure;
- accepted request class;
- pricing policy;
- Session duration limits.

The final Endpoint payment remains zero because validation settlement overrides ordinary Provider compensation.

## 36. Capability-Specific Escrow Units

Separate Escrow Units MAY exist for:

- `llm.chat`
- `image.generate`
- `video.generate`
- `speech.stt`
- `speech.tts`
- `agent.execute`

This prevents expensive media Capabilities from setting collateral requirements for every text Validator.

## 37. Assignment Capacity

For Validator v:

```text
MaximumAssignments(v, t)
=
EscrowMultiplier(v, t)
```

A Validator may accept fewer assignments.

Unused capacity earns nothing.

## 38. Escrow Capacity Is Not Personal Balance

An assignment uses a reservation from shared Escrow.

The Endpoint SHALL not learn:

- Validator Wallet;
- Validator Q balance;
- Validator Stake;
- Escrow contribution;
- Escrow multiplier;
- total Validator holdings.

## 39. Validator Slot List

At scheduling time:

```text
Validator A: x1
Validator B: x3
Validator C: x2
```

produces:

```text
A, B, B, B, C, C
```

The list is deterministically shuffled.

## 40. Slot Shuffling

```text
AssignmentSeed
=
HASH(
    previous_epoch_final_block_hash
    +
    validation_queue_root
    +
    validator_eligibility_root
    +
    opening_epoch_number
)
```

Every honest node SHALL derive the same order.

## 41. Assignment Matching

The scheduler matches:

`Validator Slot`

`+`

`Validation Request`

`+`

`Available Escrow Reservation`

while enforcing:

- Capability compatibility;
- conflict-of-interest rules;
- assignment limits;
- request priority;
- Escrow availability;
- repeated-validator cooldown;
- configuration consistency.

## 42. Funding-Constrained Scheduling

The scheduler SHALL stop when:

```text
Reserved Validation Collateral
>
Available Validation Escrow
```

No assignment SHALL execute without finalized collateral reservation.

## 43. Multiple Escrow Units

An Endpoint with a high minimum Deposit MAY require several Escrow Units.

```text
RequiredEscrowUnits(e)
=
ceil(
    RequiredValidationCollateral(e)
    /
    ValidationEscrowUnit
)
```

This reduces available assignment capacity.

It does not increase Endpoint payment.

## 44. Per-Assignment Escrow Limit

Recommended initial limit:

```text
MaximumEscrowSharePerAssignment
=
10% of available Epoch Validation Escrow
```

An Endpoint exceeding the limit may:

- remain queued;
- lower its minimum Deposit;
- use a special high-collateral queue;
- wait for greater Escrow capacity.

Publishing an absurd minimum Deposit does not entitle an Endpoint to monopolize the pool.

## 45. Validation Bond and Escrow Separation

The Endpoint Validation Bond and Validator Escrow SHALL remain separate.

The Validation Bond:

- secures Endpoint compliance;
- supports Certification lifecycle consequences;
- is refunded according to validation history;
- may be forfeited.

Validation Escrow:

- secures concealed Session admission;
- normally returns after Session settlement;
- is contributed by Validators;
- determines assignment capacity.

## 46. Initial Validation

For Initial Validation:

- the Endpoint operator has already locked a Validation Bond;
- the Validator uses shared Escrow for concealed Session collateral;
- the Endpoint processes the Session without Q compensation;
- successful Certification may trigger the first Bond refund;
- failure may retain or forfeit Bond according to Validation Economics.

## 47. Maintenance Validation

For Maintenance Validation:

- the Endpoint remains subject to the Certification obligation;
- shared Escrow backs the concealed Session;
- the Endpoint receives no Session compensation;
- successful validation may refund part of the remaining Validation Bond;
- qualifying failure may forfeit the remaining Bond.

## 48. Validator Reward Is Separate

The Validator receives reward only from:

`Validation Activity Pool`

under `ECO-0004`.

The reward depends on:

- assignment validity;
- report quality;
- evidence quality;
- complexity;
- timeliness;
- usefulness.

It does not come from:

- Endpoint Validation Bond;
- Validation Session Deposit;
- Endpoint Wallet.

## 49. Endpoint Indistinguishability

Before reveal, the validation Session SHOULD resemble an ordinary funded Session.

The Endpoint SHOULD see:

- a valid Consumer identity;
- apparently sufficient Deposit authorization;
- ordinary Session negotiation;
- ordinary request traffic;
- ordinary Usage Reporting requirements.

The Endpoint SHALL NOT see:

- Validator Service ID;
- Assignment ID;
- Validation Type;
- report deadline;
- Validator Wallet;
- Escrow contribution;
- explicit validation marker.

## 50. Concealed Session Credential

The Validator receives a single-use Concealed Session Credential.

```yaml
concealed_session_credential:
  credential_id:
  assignment_commitment:
  ephemeral_consumer_id:
  endpoint_id:
  endpoint_configuration_hash:
  collateral_limit:
  execution_limits_hash:
  expiration:
  escrow_authorization_commitment:
  threshold_signature:
```

The Credential SHALL prove sufficient collateral without revealing the Validator or assignment purpose.

## 51. Credential Requirements

A Concealed Session Credential SHALL be:

- single-use;
- bounded by amount;
- bounded by Endpoint;
- bound to one configuration;
- time-limited;
- unlinkable to the Validator's ordinary Wallet where practical;
- verifiable by the Endpoint;
- revealable after execution.

## 52. Generic Sponsored Session Form

To reduce validation detectability, Concealed Session Credentials SHOULD use the same external form as other network-sponsored Session credentials.

The protocol SHALL avoid a unique validation-only funding signature visible before execution.

Otherwise, the Endpoint could identify validation by inspecting the Deposit paperwork.

## 53. Limits of Indistinguishability

The protocol cannot guarantee that an Endpoint will never infer validation.

Inference may arise from:

- unusual prompts;
- repeated checks;
- timing;
- artifact requests;
- Validator behavior.

The protocol guarantees concealment of:

- authoritative assignment metadata;
- Validator identity;
- Escrow contribution;
- validation settlement mode before reveal.

Perfect behavioral invisibility is not guaranteed.

## 54. Ephemeral Consumer Identity

Every assignment uses a fresh ephemeral Consumer identity.

It:

- authorizes only the assigned Session;
- is not linked publicly to the Validator before reveal;
- cannot claim Faucet rewards;
- cannot receive unrelated rewards;
- expires after assignment completion.

## 55. Validation Session Opening

The Validator opens a Session through the ordinary Session Protocol.

The Session SHALL bind to:

- Endpoint ID;
- Endpoint Configuration Hash;
- public Session Policy;
- public Accounting Contract;
- Concealed Session Credential;
- Escrow collateral limit;
- validation execution-limit commitment.

The remote Session SHALL not contain a public validation flag.

## 56. Session Acceptance

The Endpoint evaluates the Session as apparently funded.

It SHALL NOT be required to know the funding source.

The Endpoint MAY reject the Session according to ordinary availability and policy rules.

Repeated rejection or unavailability becomes validation evidence.

## 57. Validation Execution Limits

Every assignment SHALL define:

- maximum request count;
- maximum input size;
- maximum output size;
- maximum execution duration;
- maximum artifact size;
- permitted tools;
- permitted side effects;
- prohibited task categories.

The Validator SHALL not exceed these limits.

## 58. No Deposit Extension by Validator

The Validator SHALL not extend the validation Deposit from an unrelated personal Wallet.

Additional collateral requires a new protocol-authorized reservation.

This prevents assignment boundaries from being bypassed through private spending.

## 59. Usage Reporting

The Endpoint SHALL generate ordinary Usage Reports under `RFC-0051`.

Usage Reports are required because they allow the Validator to evaluate:

- reporting availability;
- accounting consistency;
- token or unit claims;
- maximum-limit compliance;
- failure behavior;
- `Proxy-Opaque` disclosure.

Usage Reports do not create Endpoint payment for Validation Sessions.

## 60. Non-Billable Validation Usage

All Usage Reports generated during a Validation Session SHALL be marked as:

```yaml
validation_usage:
  economically_billable_to_endpoint: false
  accounting_observation_only: true
```

This marker MAY remain concealed from the Endpoint until assignment reveal.

The measured usage remains valuable as validation evidence.

## 61. Validation Session Settlement

A Validation Session SHALL use validation-specific settlement.

After valid assignment reveal:

```text
Provider Payment = 0Q
Escrow Refund
=
Locked Validation Deposit
-
Network Fees
-
Finalized Protocol Costs
-
Finalized Penalties
```

The refunded amount returns to Validation Escrow.

## 62. Validation Settlement Operation

The Ledger Operation Catalog SHALL support:

`VALIDATION_SESSION_SETTLE`

The operation SHALL be protocol-generated or evidence-triggered.

Required references include:

```yaml
validation_session_settle:
  session_id:
  assignment_id:
  assignment_commitment:
  assignment_reveal_proof:
  endpoint_id:
  endpoint_configuration_hash:
  locked_deposit:
  endpoint_payment: 0
  network_fees:
  protocol_costs:
  escrow_refund:
  session_evidence_root:
  report_reference:
```

## 63. Ordinary Settlement Prohibition

A Session carrying a valid concealed validation commitment SHALL NOT be settled through ordinary Provider-payment rules after assignment reveal.

If an ordinary Settlement attempt conflicts with the revealed validation commitment:

- it SHALL be rejected;
- no Provider payment SHALL occur;
- conflicting evidence SHALL be preserved.

## 64. Pre-Reveal Settlement Protection

The concealed funding mechanism SHALL prevent the Endpoint from finalizing ordinary Provider payment before the assignment's settlement mode is resolved.

The MVP MAY implement this through:

- delayed Settlement authorization;
- commit-and-reveal settlement mode;
- generic sponsored Session credentials;
- threshold authorization;
- another protocol-approved mechanism.

The Endpoint may see sufficient collateral without receiving unilateral control over it.

## 65. Report Before Final Settlement

Ordinarily:

1. Validation execution ends.
2. Session evidence is finalized.
3. Validator prepares the report.
4. `VALIDATION_REPORT_COMMIT` is submitted.
5. Assignment identity is revealed.
6. `VALIDATION_SESSION_SETTLE` returns Deposit to Escrow.
7. Validator reward becomes eligible.

The protocol MAY combine steps 4-6 atomically.

## 66. Report Withholding

A Validator SHALL not be able to hold Escrow collateral indefinitely by withholding the report.

Every assignment has:

- execution deadline;
- report deadline;
- settlement deadline.

After timeout, the protocol SHALL finalize the Session conservatively.

## 67. Settlement After Validator Abandonment

If execution occurred but no report was published:

- Endpoint Payment remains `0Q`;
- remaining Deposit returns to Escrow;
- Session evidence is preserved;
- the assignment is marked abandoned;
- the Validator receives no reward;
- post-execution abandonment consequences apply.

The Endpoint's Certification is not automatically changed by an absent report.

## 68. Endpoint Failure

If the Endpoint:

- rejects the Session;
- remains unavailable;
- produces an error;
- returns unusable output;
- fails Usage Reporting;

the Validator records evidence.

Endpoint Payment remains:

`0Q`

The Session Deposit returns to Escrow minus protocol fees.

A valid failure report may still earn Validator reward.

## 69. Endpoint Success

If the Endpoint successfully processes all validation requests:

- Endpoint Payment remains `0Q`;
- the Deposit returns to Escrow;
- the Validator publishes observations;
- successful validation may affect Certification and Bond refund.

Execution success does not convert Validation work into a paid Session.

## 70. Partial Execution

Partial Endpoint execution remains non-compensated.

The Validator SHALL record:

- delivered output;
- incomplete portions;
- errors;
- Usage Reports;
- timing;
- artifacts.

The report conclusion depends on Capability Guidelines.

## 71. Network Fees

Network Fees incurred by validation operations MAY be paid from shared Escrow.

Fees are actual Escrow expenditure.

They SHALL be:

- bounded;
- recorded;
- recyclable under `ECO-0005`;
- excluded from Endpoint revenue.

## 72. Protocol Costs

Future versions MAY define bounded protocol costs such as:

- Registry evidence storage fees;
- threshold-signature costs;
- artifact-retention fees.

Such costs SHALL be declared in advance.

They SHALL not become hidden Endpoint compensation.

## 73. Assignment Execution Window

Assignments SHALL define:

- earliest execution time;
- latest Session-open time;
- execution deadline;
- report deadline;
- grace period.

The Validator may execute at any permitted time.

This reduces predictable validation timing.

## 74. Minimum Validation Attempts

Capability Guidelines MAY define minimum attempts before declaring unavailability.

The rules SHOULD distinguish:

- temporary network loss;
- Endpoint refusal;
- repeated protocol error;
- broad network outage;
- persistent Endpoint failure.

## 75. Report Preparation

The report SHALL include:

- Assignment ID;
- Endpoint Configuration Hash;
- request evidence;
- response evidence;
- accounting observations;
- execution timestamps;
- limitations;
- conclusion;
- Validator signature.

## 76. Report Commitment

`VALIDATION_REPORT_COMMIT` SHALL:

- reveal Validator Service ID;
- prove correspondence with the hidden Assignment Commitment;
- reference the Registry report;
- bind the report to exact Endpoint configuration;
- make validation settlement possible;
- close the assignment.

## 77. Identity Reveal

Validator identity becomes public only after execution ends and the report is committed.

The Endpoint SHALL not receive authoritative Validator identity earlier.

## 78. Assignment Completion

An assignment is complete when:

- execution ended;
- required Session evidence exists;
- report is stored;
- report commitment finalized;
- assignment reveal is valid;
- validation-specific Session settlement finalized.

## 79. Validator Reward Eligibility

A report is reward-eligible only when:

- assignment was valid;
- Validator was eligible;
- Escrow authorization was valid;
- request limits were respected;
- report schema is valid;
- minimum evidence exists;
- report is timely;
- no fabrication or unrelated-use evidence exists.

## 80. Outcome Neutrality

The following may earn equal reward:

- `CERTIFY`
- `CERTIFY_WITH_OBSERVATIONS`
- `DO_NOT_CERTIFY`

An `INCONCLUSIVE` report may earn reduced or full reward depending on cause and usefulness.

## 81. No Reward for Endpoint Payment

The Validator Reward SHALL not depend on:

- Endpoint receiving payment;
- reported Endpoint usage amount;
- Endpoint price;
- Session Deposit size.

High published pricing does not create a larger Validator reward by itself.

## 82. Reassignment

A request is reassigned when:

- offer expires;
- Validator declines;
- assignment is released;
- assignment expires;
- Validator becomes suspended;
- Escrow reservation fails;
- assignment is invalidated.

A new Assignment ID and Credential are required.

## 83. Repeated Validator Cooldown

The same Validator SHOULD not repeatedly validate the same Endpoint.

Recommended initial rule:

```text
No more than one of the last three Maintenance Validations
by the same Validator Service
```

## 84. Self-Validation Prohibition

A Validator SHALL not validate an Endpoint in the same Known Control Group.

Conflict checks include:

- owner Wallet;
- Reward Beneficiary;
- Hypervisor ownership;
- explicit delegation;
- finalized control relationships.

## 85. Endpoint Operator Influence

The Endpoint operator SHALL NOT:

- choose the Validator;
- see the offer list;
- influence offer order;
- pay a selected Validator directly;
- identify the assignment before execution through protocol metadata.

## 86. Strategic Endpoint Price Changes

If the Endpoint changes its minimum Deposit or Session policy before execution:

- the Credential may become invalid;
- collateral sizing SHALL be recalculated;
- the assignment may return to queue.

Repeated strategic changes around assignment periods MAY affect operational Reputation when objectively evidenced.

## 87. Endpoint Withdrawal

If the Endpoint is withdrawn before execution:

- assignment is invalidated;
- collateral is released;
- Validator incurs no penalty.

If withdrawal occurs during execution, `RFC-0060` applies, with Endpoint Payment still equal to zero.

## 88. Validator Suspension

If a Validator becomes suspended before execution:

- assignment is invalidated;
- collateral is released;
- request is reassigned.

If suspension occurs after report submission, report eligibility depends on the cause and evidence integrity.

## 89. Escrow Conservation

For Epoch t:

```text
Closing Validation Escrow
=
Opening Validation Escrow
+
New Contributions
-
Released Contributions
-
Network Fees
-
Protocol Costs
-
Finalized Penalties
```

Validation Session execution itself does not reduce Escrow principal through Endpoint payment.

## 90. Escrow Contribution Release

A Validator may request release of unused Escrow contribution.

Release SHALL respect:

- active assignments;
- collateral reservations;
- settlement deadlines;
- evidence windows;
- unbonding policy.

## 91. Assignment Performance Bond

The protocol MAY require a small Assignment Performance Bond when an offer is accepted.

The Bond:

- is separate from Session collateral;
- returns after valid report completion;
- may be forfeited after objective post-execution abandonment;
- does not increase Validator reward.

This protects against Validators consuming free validation work without publishing reports.

## 92. Scheduling Frequency

The Epoch Engine MAY run several deterministic offer rounds per Epoch.

Each round:

1. identifies queued requests;
2. identifies available Validator slots;
3. checks Escrow collateral;
4. performs deterministic matching;
5. sends private offers;
6. expires unanswered offers;
7. requeues unresolved requests.

## 93. Sequential Offers

The MVP SHOULD offer one assignment to one Validator at a time.

Parallel sealed offers are deferred.

## 94. Assignment Fairness

The scheduler SHOULD avoid:

- permanent preference for mature Validators;
- starvation of newcomers;
- repeated Validator-to-Endpoint pairs;
- selection by highest Stake;
- selection by Wallet balance;
- selection by fastest offer acceptance alone.

## 95. Maintenance Capacity

A configurable part of validation capacity SHALL be reserved for Maintenance and Triggered Validation.

Example:

```text
MaintenanceCapacityShare = 40%
InitialValidationCapacityShare = 60%
```

Unused capacity may be reassigned later in the Epoch.

## 96. Demand Overflow

If demand exceeds capacity:

- older requests gain priority;
- Certification-expiry risk gains priority;
- urgent Triggered Validation gains priority;
- requests remain queued;
- no additional Q is emitted automatically.

## 97. Assignment Privacy

Before report reveal, public metrics SHALL not expose:

- Validator-to-Endpoint mapping;
- offer order;
- exact execution time;
- ephemeral identity linkage;
- Assignment Key;
- settlement-mode reveal.

Aggregate queue and capacity data may be public.

## 98. Ledger Commitments

The Ledger SHALL store:

- Validation Request commitment;
- opaque Assignment Commitment;
- collateral reservation commitment;
- assignment-state transitions;
- Concealed Session Credential commitment;
- report commitment;
- identity reveal proof;
- validation-specific settlement;
- reward eligibility reference.

## 99. Registry Storage

Registry Services MAY store:

- encrypted offers;
- assignment lifecycle data;
- Session evidence;
- Validation Reports;
- settlement references;
- reveal proofs.

Sensitive data SHALL follow access and retention policy.

## 100. Assignment Messages

The MVP SHALL support:

- `VALIDATION_OFFER`
- `VALIDATION_OFFER_DECLINE`
- `VALIDATION_OFFER_ACCEPT`
- `VALIDATION_OFFER_EXPIRE`
- `VALIDATION_ASSIGNMENT_CONFIRMED`
- `VALIDATION_ASSIGNMENT_RELEASE`
- `VALIDATION_ASSIGNMENT_INVALIDATE`
- `VALIDATION_ASSIGNMENT_EXPIRE`
- `VALIDATION_COLLATERAL_RESERVED`
- `VALIDATION_COLLATERAL_FAILED`
- `CONCEALED_SESSION_CREDENTIAL`
- `VALIDATION_EXECUTION_STARTED`
- `VALIDATION_EXECUTION_COMPLETED`
- `VALIDATION_EXECUTION_FAILED`
- `VALIDATION_REPORT_READY`
- `VALIDATION_REPORT_COMMITTED`
- `VALIDATION_IDENTITY_REVEALED`
- `VALIDATION_SESSION_SETTLED`

## 101. Ledger Operations

This protocol uses:

- `VALIDATION_REQUEST`;
- `VALIDATION_ASSIGNMENT_CREATE`;
- `SESSION_OPEN`;
- `SESSION_ACCEPT`;
- `VALIDATION_REPORT_COMMIT`;
- `VALIDATION_SESSION_SETTLE`;
- `CERTIFICATION_STATE_UPDATE`;
- `REWARD_MINT`;
- `PARTICIPANT_SUSPEND`;
- `PENALTY_APPLY`.

Ordinary `SESSION_SETTLE` SHALL not create Endpoint payment for a revealed Validation Session.

## 102. Error Codes

The MVP SHALL define at least:

- `VALIDATION_REQUEST_NOT_FOUND`
- `VALIDATION_REQUEST_SUPERSEDED`
- `VALIDATION_REQUEST_EXPIRED`
- `VALIDATOR_NOT_ELIGIBLE`
- `VALIDATOR_CAPABILITY_MISMATCH`
- `VALIDATOR_CAPACITY_EXHAUSTED`
- `ASSIGNMENT_CONFLICT`
- `ASSIGNMENT_ALREADY_ACCEPTED`
- `ASSIGNMENT_OFFER_EXPIRED`
- `ASSIGNMENT_INVALIDATED`
- `ASSIGNMENT_DEADLINE_EXPIRED`
- `SELF_VALIDATION_PROHIBITED`
- `KNOWN_CONTROL_GROUP_CONFLICT`
- `ESCROW_INSUFFICIENT`
- `COLLATERAL_RESERVATION_EXPIRED`
- `CONCEALED_CREDENTIAL_INVALID`
- `CONCEALED_CREDENTIAL_ALREADY_USED`
- `ENDPOINT_CONFIGURATION_CHANGED`
- `VALIDATION_REPORT_INVALID`
- `VALIDATION_REPORT_ALREADY_COMMITTED`
- `IDENTITY_REVEAL_INVALID`
- `ORDINARY_SETTLEMENT_PROHIBITED`
- `VALIDATION_SETTLEMENT_INVALID`
- `VALIDATION_WORK_LIMIT_EXCEEDED`

## 103. Idempotency

The following SHALL be idempotent:

- offer delivery;
- offer decline;
- offer acceptance;
- assignment release;
- collateral reservation;
- Credential delivery;
- execution-state reporting;
- report commitment;
- identity reveal;
- Validation Session settlement.

Repeated messages SHALL not create duplicate:

- assignments;
- Sessions;
- reservations;
- reports;
- settlements;
- rewards.

## 104. Evidence Replay Protection

Every:

- Offer ID;
- Assignment ID;
- Assignment Key;
- collateral reservation;
- Concealed Session Credential;
- Session ID;
- Report ID;

SHALL be unique and replay-protected.

## 105. Reward Timing

Work performed in Epoch t normally becomes reward-eligible after evidence processing in Epoch t + 1.

The delay permits:

- report validation;
- reveal verification;
- abuse detection;
- calculation challenges;
- reward calculation.

## 106. No Reward for Offer or Acceptance

The following earn no Q:

- receiving an offer;
- accepting an assignment;
- reserving Escrow;
- opening a Session;
- sending test requests;
- producing an empty report.

Only useful completed report work is rewarded.

## 107. Certification Independence

Assignment completion does not itself certify the Endpoint.

The report becomes input to Certification Derivation.

Certification changes only through:

`CERTIFICATION_STATE_UPDATE`

## 108. Epoch Tasks

`RFC-0048` tasks include:

- Freeze Validation Requests;
- Calculate Validator Eligibility;
- Calculate Validation Escrow Units;
- Freeze Escrow Multipliers;
- Build Validator Slot List;
- Shuffle Validation Queues;
- Create Private Offers;
- Expire Offers;
- Reserve Collateral;
- Issue Concealed Session Credentials;
- Reassign Unaccepted Requests;
- Monitor Assignment Deadlines;
- Commit Validation Reports;
- Reveal Validator Identities;
- Settle Validation Sessions;
- Calculate Validation Rewards;
- Release Unused Collateral;
- Process Assignment Performance Bonds.

## 109. Required Amendments to RFC-0059

`RFC-0059` SHALL be amended to include:

`VALIDATION_SESSION_SETTLE`

The operation SHALL:

- settle one revealed Validation Session;
- pay `0Q` to the Endpoint;
- return remaining Deposit to Validation Escrow;
- remove applicable Network Fees;
- preserve Session evidence;
- prevent later ordinary Settlement.

`RFC-0059` SHALL also clarify that `SESSION_SETTLE` is invalid for a Session proven to contain a concealed validation commitment.

## 110. Required Amendments to RFC-0060

`RFC-0060` SHALL clarify that failure handling for Validation Sessions uses:

```text
Endpoint Payment = 0Q
```

in all terminal outcomes.

Forced Settlement SHALL return unused collateral to Validation Escrow after:

- fees;
- protocol costs;
- finalized penalties.

The Last Accepted Usage Checkpoint remains evidence, but it does not create Endpoint compensation.

## 111. MVP Requirements

The MVP SHALL implement:

- Initial and Maintenance Validation Requests;
- Capability-specific queues;
- Validator eligibility;
- voluntary private offers;
- accept, decline and expiration;
- fresh Assignment Keys;
- shared Validation Escrow;
- Escrow multipliers;
- deterministic slot scheduling;
- collateral reservations;
- Concealed Session Credentials;
- apparently funded Validation Sessions;
- ephemeral Consumer identities;
- concealed Validator identity;
- zero Endpoint payment;
- Escrow Deposit return;
- Usage Reporting for observation;
- report commitment and reveal;
- special Validation Session settlement;
- assignment expiration and reassignment;
- self-validation prohibition;
- repeated-validator cooldown;
- post-execution abandonment consequences;
- outcome-neutral Validator rewards;
- replay protection.

## 112. Deferred Features

The MVP MAY postpone:

- zero-knowledge settlement-mode proofs;
- parallel sealed offers;
- collaborative validation;
- cross-network Validators;
- private report conclusions;
- permanent anonymous Validator identities;
- dynamic Escrow lending;
- delegated Validator capacity;
- advanced unlinkable payment credentials;
- hardware-backed Assignment Keys.

## 113. Open Protocol Parameters

The following remain configurable:

- Validation Escrow floor;
- Capability-specific Escrow Units;
- Concealment Collateral Floor;
- Network Fee Reserve;
- maximum Escrow share per assignment;
- Offer timeout;
- number of offer rounds;
- execution window;
- report deadline;
- report grace period;
- Maintenance capacity share;
- repeated-validator cooldown;
- Assignment Performance Bond;
- abandonment cooldown;
- minimum Validation Reputation;
- minimum Health;
- maximum assignments;
- minimum validation attempts;
- high-collateral queue threshold;
- Escrow release delay;
- validation workload limits.

## 114. Economic Invariants

```text
Endpoint Payment for Validation Session = 0Q
Validation Session Deposit
Is Collateral, Not Endpoint Revenue
Validation Session Execution
Does Not Reduce Escrow Principal
Except for Fees, Protocol Costs and Penalties
Reserved Validation Collateral
<=
Available Validation Escrow
Assignment Count
<=
Available Validator Slots
One Completed Assignment
<=
One Validator Reward
Offer Acceptance
!=
Reward
Positive Validation Result
!=
Reward Requirement
Validator Activity Reward
Is Separate from Validation Session Deposit
```

## 115. Privacy Invariants

- Validator identity remains concealed during execution.
- Public commitments do not reveal Validator identity.
- Validation Sessions use ephemeral Consumer identities.
- Endpoint-facing messages contain no validation marker.
- Escrow authorization does not expose Validator balance.
- Settlement mode remains concealed until reveal.
- Identity is revealed only after execution.
- Perfect behavioral indistinguishability is not guaranteed.

## 116. Security Invariants

- Validators cannot validate their own Known Control Group.
- A Credential is single-use.
- One assignment binds to one Endpoint configuration.
- Configuration changes invalidate unfinished assignments.
- Uncollateralized assignments do not execute.
- Endpoint cannot choose its Validator.
- Validator cannot mint its own reward.
- Validation Session cannot become ordinary paid work.
- Ordinary Settlement cannot bypass validation-specific settlement.
- Validator cannot use assignments as unrelated free compute without consequences.
- Stake penalties require objective evidence.
- Declining an offer is not misconduct.
- Post-execution abandonment is more serious than pre-execution release.

## 117. Design Invariants

- Validation participation is voluntary for Validators.
- Validation participation is an accepted obligation for Certified Endpoints.
- Accepted Validator assignments create bounded obligations.
- Validation Escrow provides concealment collateral rather than Endpoint payment.
- Endpoint receives zero Q for validation processing.
- Validation Bond and Validation Escrow remain separate.
- Validator reward comes from the Validation Activity Pool.
- Usage Reporting remains required for validation evidence.
- Validation traffic resembles an ordinary funded Session before reveal.
- Negative reports are economically valuable.
- Assignment completion and Certification remain separate.
- Every validation Session and Escrow movement is auditable after reveal.
