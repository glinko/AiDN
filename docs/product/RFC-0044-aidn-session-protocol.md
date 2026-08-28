# RFC-0044 — AiDN Session Protocol

Status: Draft

Version: 1.0

Revision note: paid request admission now uses the Endpoint's refillable minimum
escrow deposit; an explicit Consumer top-up authorizes continued execution.

Supersedes:

* RFC-0044 Version 0.8

Depends on:

* RFC-0036 AiDN Ledger State Machine
* RFC-0037 Settlement Engine
* RFC-0039 Hypervisor Service Model
* RFC-0042 Hypervisor Network Protocol
* RFC-0045 Capability Architecture
* RFC-0049 Distributed Marketplace and Advertisement Registry
* RFC-0051 Usage Reporting and Verification Protocol
* RFC-0053 Capability Runtime Specification
* RFC-0054 Capability Runtime Protocol
* RFC-0055 Provider Plugin System and Directory
* RFC-0056 Provider Plugin Runtime Interface
* RFC-0059 Ledger Operation Catalog
* RFC-0060 Session Failure, Recovery and Forced Settlement
* RFC-0063 Proxy Endpoint Protocol
* RFC-0064 Validation Assignment, Concealed Session and Escrow Protocol
* RFC-0065 Endpoint Certification Derivation and Lifecycle Protocol
* RFC-0066 Protocol Upgrade and Emergency Recovery

---

## 1. Purpose

This document defines the AiDN Session Protocol.

A Session is a bounded execution and economic agreement between a Consumer and an Endpoint.

Execution of an accepted Session SHALL terminate at an authorized Runtime
Binding or Runtime Adapter surface.

Neither the Consumer nor the Hypervisor Session layer speaks a provider-native
API directly.

The protocol defines how participants:

* select an Endpoint;
* negotiate immutable Session terms;
* lock or prove sufficient collateral;
* accept or reject a Session;
* submit one or more Requests;
* reserve Request exposure;
* execute and stream work;
* deliver artifacts;
* report usage;
* acknowledge economic checkpoints;
* cancel Requests or Sessions;
* recover after interruption;
* settle completed work;
* refund unused collateral;
* prevent duplicate execution and duplicate Settlement.

Every economic Session Checkpoint SHALL reference the accepted RFC-0051 Usage
Report ID, chain-head Hash and Sequence, Accounting Contract Hash, calculated
charge, current Session exposure and remaining Deposit. Checkpoint
acknowledgment permits continued bounded exposure; it does not assert that the
Consumer independently reproduced Provider-metered units. Settlement uses the
last accepted chain head and SHALL NOT treat Runtime Request acceptance as
completed or billable work.

---

## 2. Normative Language

The terms:

SHALL
SHALL NOT
SHOULD
SHOULD NOT
MAY

are normative.

A protocol implementation claiming conformance SHALL satisfy all applicable SHALL and SHALL NOT requirements.

---

## 3. Core Principle

Every accepted Session SHALL be governed by one immutable Session Contract.

The Session Contract binds:

Consumer Identity
+
Endpoint Identity
+
Endpoint Configuration Hash
+
Capability
+
Pricing Policy
+
Accounting Contract
+
Session Policy
+
Failure Policy
+
Data Handling Policy
+
Funding Authorization
+
Maximum Economic Exposure
+
Protocol Versions

Neither party may silently replace these terms after acceptance.

---

## 4. Session Is Not a Transport Connection

A Session is a protocol object.

It is not identical to:

* a TCP connection;
* a WebSocket;
* one Runtime process;
* one upstream Provider session;
* one Hypervisor process;
* one Request.

Transport connections and Runtime processes MAY disconnect, restart or migrate while the same Session remains active.

---

## 5. Session Is Not a Request

A Session MAY contain:

* one Request;
* multiple independent Requests;
* a stateful conversation;
* one long-running task;
* several artifact-producing operations;
* a bounded agent workspace.

Every Request has its own:

* identity;
* sequence;
* charge ceiling;
* exposure reservation;
* execution state;
* Usage evidence;
* result commitment.

---

## 6. Session Participants

The protocol involves:

Consumer

Requests execution and authorizes spending.

Endpoint

Publishes the Consumer-facing service contract.

Endpoint Operator

Is responsible for Endpoint behavior.

Hypervisor

Routes Session control and data-plane messages.

Capability Runtime

Executes Requests behind the Endpoint.

Funding Source

Provides Session collateral.

Ledger

Locks collateral and finalizes economic state.

Registry

Stores large evidence objects and historical references where required.

---

## 7. Endpoint Responsibility

The Endpoint remains responsible for the complete Consumer-facing Session regardless of whether execution uses:

* a local Runtime;
* a remote Runtime;
* another AiDN Endpoint;
* an external API;
* an OAuth-connected service;
* a Proxy chain;
* several failover Providers.

Internal delegation does not alter the accepted Consumer contract.

---

## 8. Session Identity

Every Session SHALL have a globally unique Session ID.

Recommended derivation:

```text
session_id
=
HASH(
    network_id
    +
    chain_id
    +
    network_revision
    +
    consumer_wallet
    +
    endpoint_id
    +
    consumer_session_nonce
)
```

A Session ID SHALL never be reused.

---

## 9. Domain Separation

Every signed Session control message SHALL be bound to:

network_id
+
chain_id
+
network_revision
+
session_id
+
message_type

This prevents replay across:

* networks;
* chains;
* Network Revisions;
* Sessions;
* message classes.

---

## 10. Session Identities and Keys

The protocol distinguishes:

Consumer Wallet Identity
Consumer Session Identity
Endpoint Identity
Endpoint Session Identity
Hypervisor Identity
Runtime Identity
Funding Source Identity

Ephemeral Session keys MAY be used for high-frequency messages.

Session keys SHALL NOT authorize arbitrary Wallet spending.

---

## 11. Session Contract

A Session Contract SHALL contain:

```yaml
session_contract:
  session_id:
  consumer_id:
  consumer_wallet:
  consumer_session_key:
  endpoint_id:
  endpoint_operator:
  endpoint_payment_beneficiary:
  consumer_refund_beneficiary:
  endpoint_session_key:
  endpoint_configuration_hash:
  advertisement_reference:
  advertisement_id:
  offer_id: # optional when the Session has no distinct accepted Offer
  capability_id:
  capability_version:
  pricing_policy_hash:
  accounting_contract_hash:
  session_policy_hash:
  failure_policy_hash:
  data_handling_policy_hash:
  funding_authorization_hash:
  settlement_resolver_commitment:
  locked_deposit:
  maximum_session_charge:
  initial_unallocated_exposure:
  request_limits:
  concurrency_limits:
  artifact_limits:
  execution_limits:
  session_protocol_version:
  accounting_protocol_version:
  capability_protocol_version:
  acceptance_deadline:
  session_expiration:
  consumer_signature:
  endpoint_signature:
```

`advertisement_reference` identifies the accepted Advertisement locator or lookup reference used to retrieve the exact offered terms at Session open. It remains inside the Session Contract for auditability and recovery so later settlement stages can reproduce the accepted lookup context. `advertisement_id` is the immutable accepted Advertisement identity bound into the Session Contract.

---

## 12. Contract Immutability

After Session acceptance, the following SHALL remain immutable:

* Endpoint ID;
* Endpoint Configuration Hash;
* Endpoint Payment Beneficiary;
* Consumer Refund Beneficiary;
* accepted Advertisement identity (`advertisement_id`);
* accepted Offer identity (`offer_id`), where present;
* Capability and version;
* Pricing Policy;
* Accounting Contract;
* Failure Policy;
* Data Handling Policy;
* Funding Authorization;
* Settlement Resolver Commitment;
* maximum Session charge;
* protocol interpretation.

Every accepted Session binds to one exact Advertisement or Offer scope through `advertisement_id` and optional `offer_id`.

Settlement and later protocol stages SHALL NOT reinterpret a Session under a later Advertisement version.

Permitted amendments are defined separately.

---

## 13. Session Contract Hash

The Session Contract SHALL have a canonical hash:

```text
session_contract_hash
=
HASH(canonical_session_contract)
```

Every subsequent Session message SHALL reference:

* Session ID;
* Session Contract Hash.

---

## 14. Supported Session Funding Classes

The protocol defines:

DIRECT_CONSUMER_DEPOSIT
SPONSORED_DEPOSIT
PROTOCOL_ESCROW_DEPOSIT
CONCEALED_SPONSORED_DEPOSIT

Funding class does not by itself determine Endpoint Payment.

Settlement is determined by the accepted Settlement Resolver.

---

## 15. Direct Consumer Deposit

The Consumer locks Q from its own Wallet.

Unused collateral returns to the Consumer Wallet.

---

## 16. Sponsored Deposit

A third-party Wallet funds the Session.

Unused collateral returns to the sponsor unless the Funding Authorization defines another valid destination.

The Consumer does not gain ownership of unused sponsored collateral.

---

## 17. Protocol Escrow Deposit

A protocol-managed Escrow authorizes bounded Session collateral.

The authorization SHALL be:

* single-use;
* Session-bound;
* Endpoint-bound;
* amount-bounded;
* expiration-bound;
* replay-protected.

---

## 18. Concealed Sponsored Deposit

A Concealed Sponsored Deposit proves sufficient collateral without revealing the final Settlement Resolver before execution.

It MAY be used for:

* concealed Validation Sessions;
* future protocol-sponsored Sessions;
* other authorized sponsored workflows.

The external credential SHOULD use a generic sponsored form rather than expose a validation-specific marker.

---

## 19. Settlement Resolver

Every Session SHALL bind to one Settlement Resolver.

Initial resolver classes are:

ORDINARY_CONSUMER_SETTLEMENT
ORDINARY_SPONSORED_SETTLEMENT
PROTOCOL_SPONSORED_SETTLEMENT
COMMITTED_CONCEALED_SETTLEMENT

The resolver determines:

* Endpoint Payment rules;
* refund destination;
* fee handling;
* reveal requirements;
* timeout behavior.

---

## 20. Concealed Resolver Commitment

For a concealed resolver:

```text
settlement_resolver_commitment
=
HASH(
    resolver_type
    +
    resolver_reference
    +
    resolver_nonce
)
```

The Endpoint receives the commitment before execution.

The exact resolver details remain hidden until valid reveal or protocol timeout resolution.

---

## 21. No Unilateral Pre-Reveal Settlement

A Session using COMMITTED_CONCEALED_SETTLEMENT SHALL NOT permit unilateral ordinary Endpoint Settlement before:

* valid resolver reveal;
* or deterministic protocol timeout resolution.

Sufficient collateral is visible.

Immediate ownership of that collateral is not granted.

---

## 22. Session Lifecycle

The canonical Session lifecycle is:

```text
PROPOSED
    ↓
OPEN_PENDING
    ↓
OPEN
    ↓
ACCEPTED
    ↓
ACTIVE
    ↓
DRAINING
    ↓
CLOSING
    ↓
SETTLEMENT_PENDING
    ↓
SETTLED
    ↓
CLOSED
```

Alternative terminal or recovery states include:

REJECTED
OPEN_EXPIRED
SESSION_EXPIRED
CANCELLED
FAILED
RECOVERING
ABORTED
FORCE_SETTLEMENT_PENDING

---

## 23. PROPOSED

The Consumer has constructed a local proposal.

No canonical collateral lock exists.

The Endpoint has no obligation.

---

## 24. OPEN_PENDING

SESSION_OPEN has been submitted but is not finalized.

The Endpoint SHALL NOT execute economically significant work based only on mempool presence.

For the strict MVP consensus profile, `SESSION_OPEN` is a lifecycle
projection, not the funding mutation. Its payload SHALL reference a finalized
`SESSION_ESCROW_LOCK` and the exact Funding state hash. The canonical order is
therefore `SESSION_ESCROW_LOCK` in one finalized block followed by
`SESSION_OPEN` in a later block; a same-block dependency is rejected.

---

## 25. OPEN

The Session collateral and Contract proposal are finalized.

The `SESSION_ESCROW_LOCK` operation is the sole MVP transition that creates
the locked economic exposure. `SESSION_OPEN` only binds that exposure to the
Session/Endpoint metadata and does not debit the Consumer again.

The Endpoint may accept or reject the Session.

---

## 26. ACCEPTED

The Endpoint has signed the exact Session Contract.

The accepted contract is binding.

In the strict MVP consensus profile, `SESSION_ACCEPT` must reference a
finalized `SESSION_OPEN` and is authorized by the locked Endpoint Payment
beneficiary. It records the lifecycle acceptance only; escrow, beneficiaries
and charge ceilings remain those fixed by the earlier Funding/Contract
records.

The Runtime may be allocated.

---

## 27. ACTIVE

New Requests may be submitted within the accepted limits.

---

## 28. DRAINING

No new Requests are accepted.

Already accepted Requests may:

* complete;
* cancel;
* fail;
* enter recovery.

---

## 29. CLOSING

All Requests have terminal or explicitly recoverable states.

Usage and result evidence are reconciled.

---

## 30. SETTLEMENT_PENDING

A Settlement transition has been proposed or generated but is not finalized.

Collateral remains locked.

---

## 31. SETTLED

The Session economic state has finalized.

No additional billable execution may be added.

---

## 32. CLOSED

All ordinary protocol obligations are complete.

Evidence retention, Reputation processing and correction procedures MAY continue.

---

## 33. Advertisement Selection

Before opening a Session, the Consumer SHOULD retrieve:

* active Advertisement;
* Endpoint Configuration Hash;
* Capability;
* Pricing Policy;
* Accounting Contract;
* Failure Policy;
* Data Handling Policy;
* Certification;
* Reputation;
* current Endpoint availability.

Advertisement is an offer, not proof of future acceptance.

---

## 34. Stale Advertisement Protection

A Session proposal MAY be rejected when it references:

* withdrawn Advertisement;
* expired Advertisement;
* outdated Configuration Hash;
* unsupported Capability version;
* superseded Pricing Policy;
* incompatible Session Protocol version.

---

## 35. Session Opening

The Consumer opens a Session through:

SESSION_OPEN

The operation SHALL:

* establish Session ID;
* bind the proposed Session Contract;
* lock or reserve collateral;
* establish maximum Session charge;
* consume a unique Consumer Session nonce;
* establish acceptance and expiration deadlines.

---

## 36. Consumer Spending Authorization

The Consumer or sponsor SHALL authorize:

* exact Session ID;
* Endpoint ID;
* Deposit amount;
* maximum Session charge;
* policy hashes;
* expiration;
* applicable Network Fees;
* refund destination.

The Hypervisor SHALL NOT increase authorized spending.

---

## 37. Initial Deposit Requirement

For ordinary Sessions:

```text
LockedDeposit
≥
EndpointMinimumSessionDeposit
```

unless the active Endpoint policy accepts another Funding Authorization.

---

## 38. Deposit Is Collateral

The Deposit is not automatically Provider revenue.

Actual deductions occur only through a valid Settlement.

---

## 39. Maximum Session Charge

Every Session SHALL define:

```text
MaximumSessionCharge
≤
LockedDeposit
```

Endpoint Payment SHALL never exceed the accepted maximum.

---

## 40. Economic State Components

A live Session SHALL track:

LockedDeposit
AcceptedCumulativeCharge
PendingExposure
AvailableExposure

where:

```text
AvailableExposure
=
MaximumSessionCharge
-
AcceptedCumulativeCharge
-
PendingExposure
```

---

## 41. Pending Exposure

PendingExposure is the maximum still-unresolved charge of accepted non-terminal Requests.

It prevents several concurrent Requests from collectively exceeding the Session maximum.

---

## 42. Request Exposure Reservation

Before accepting a Request, the Endpoint SHALL reserve:

```text
request_reserved_exposure
≤
request_charge_ceiling
```

The reservation SHALL also satisfy:

```text
request_reserved_exposure
≤
AvailableExposure
```

---

## 43. Concurrent Request Safety

For all accepted non-terminal Requests:

```text
Σ RequestReservedExposure
=
PendingExposure
```

The Endpoint SHALL NOT accept another Request when its reservation would make:

```text
AcceptedCumulativeCharge
+
PendingExposure
>
MaximumSessionCharge
```

---

## 44. Exposure Release

When a Request reaches a terminal state:

```text
ReleasedExposure
=
RequestReservedExposure
-
FinalAcceptedRequestCharge
```

Released exposure becomes available for later Requests.

---

## 45. Deposit Extension

The Consumer or sponsor MAY extend collateral through:

SESSION_DEPOSIT_EXTEND

An extension SHALL:

* be explicitly authorized;
* increase locked collateral;
* define any increase to Maximum Session Charge;
* preserve prior accepted terms;
* take effect only after finalization.

For a paid Endpoint, the immutable Session policy SHALL contain the minimum
escrow deposit advertised by the operator. After each accepted invoice, the
Endpoint SHALL reject another Request while the remaining available Deposit is
below that minimum. The Consumer MAY restore the Deposit with an explicitly
authorized extension. The minimum is a refill threshold and SHALL NOT be
interpreted as a maximum request price.

The node SHOULD derive the minimum from a high-usage request estimate under the
published Rate Card and immutable Runtime limits. For an LLM this includes the
accepted context window, maximum permitted output tokens, fixed request fees,
and input/output token rates. The default safety margin is 20 percent.

The Endpoint SHOULD also publish a recommended Deposit equal to five minimum
Deposits. A Consumer MAY lock any larger amount. Requests may continue without
replenishment while the remaining Deposit stays at or above the minimum; the
recommended value is therefore a convenience working balance, not a new charge
or authorization boundary.

---

## 46. No Automatic Unbounded Top-Up

The Endpoint, Hypervisor or Runtime SHALL NOT debit arbitrary additional Q.

No component SHALL debit the Consumer wallet during request execution. The
maximum collectible amount is the collateral already locked in the Session
Deposit. Session closure SHALL settle the final accepted invoice and return the
unused remainder to the Consumer.

A bounded automatic top-up MAY exist only when explicitly authorized in the Session Contract.

---

## 47. Session Acceptance

The Endpoint accepts through:

SESSION_ACCEPT

The acceptance SHALL bind to:

* Session ID;
* Session Contract Hash;
* Endpoint Configuration Hash;
* accepted Runtime allocation;
* Endpoint Session key;
* acceptance timestamp;
* Endpoint signature.

---

## 48. Endpoint Acceptance Checks

Before acceptance, the Endpoint SHOULD verify:

* SESSION_OPEN finality;
* Funding Authorization validity;
* sufficient Deposit;
* current Configuration Hash;
* Capability compatibility;
* policy compatibility;
* Runtime availability;
* concurrency limits;
* Session expiration;
* Data Handling constraints.

---

## 49. Session Rejection

The Endpoint MAY reject because of:

* insufficient collateral;
* Runtime unavailable;
* capacity exhausted;
* incompatible policy;
* unsupported Capability;
* stale configuration;
* data restriction;
* maintenance;
* protocol mismatch.

The rejection SHOULD use a stable reason code.

---

## 50. Rejection Economics

A rejected Session SHALL normally return all unused collateral minus:

* finalized Network Fees;
* explicitly accepted bounded opening costs.

The Endpoint SHALL normally receive no rejection payment.

---

## 51. Acceptance Timeout

If the Endpoint does not accept before the acceptance deadline:

OPEN
→
OPEN_EXPIRED

Unused collateral is released according to Funding Authorization.

Silence is not acceptance.

---

## 52. Runtime Allocation

The Endpoint SHALL NOT accept a Session without a plausible execution path.

The execution path MAY be:

* immediately available Runtime;
* bounded queue;
* reserved Runtime slot;
* approved Proxy route;
* declared failover set.

---

## 53. Session Data Plane

Ordinary Requests and results SHOULD remain off-chain.

The Ledger stores economic and lifecycle commitments.

The Registry MAY store:

* large evidence;
* reports;
* result manifests;
* artifact descriptors;
* encrypted dispute material.

---

## 54. Session Token

After acceptance, the Endpoint MAY issue an ephemeral Session Token.

It SHALL be:

* scoped to one Session;
* Capability-bound;
* expiration-bound;
* revocable;
* unable to authorize Wallet transfers.

---

## 55. Request Identity

Every Request SHALL have a unique Request ID.

Recommended derivation:

```text
request_id
=
HASH(
    session_id
    +
    consumer_request_sequence
    +
    request_nonce
)
```

---

## 56. Consumer Request Sequence

Every Session SHALL maintain a monotonically increasing Consumer Request Sequence.

A replayed Request with identical content is idempotent.

A repeated sequence with different content is invalid.

---

## 57. Request Envelope

```yaml
session_request:
  session_id:
  session_contract_hash:
  request_id:
  request_sequence:
  idempotency_key:
  capability_id:
  request_schema_version:
  request_class:
  payload_hash:
  payload_reference:
  requested_output_limits:
  request_charge_ceiling:
  request_deadline:
  side_effect_policy_reference:
  consumer_signature:
```

---

## 58. Request Charge Ceiling

Every Request SHALL declare:

```text
RequestCharge
≤
RequestChargeCeiling
```

The Request ceiling SHALL also remain within available Session exposure.

---

## 59. Request Preflight

Before acceptance, the Endpoint SHALL evaluate whether the Request:

* matches the Capability;
* satisfies schema rules;
* satisfies content limits;
* fits output limits;
* fits request charge ceiling;
* fits available Session exposure;
* can satisfy deadline;
* satisfies side-effect policy;
* satisfies Data Handling Policy.

---

## 60. Request Acceptance

The Endpoint SHOULD return:

REQUEST_ACCEPT

including:

```yaml
request_acceptance:
  session_id:
  request_id:
  request_sequence:
  accepted_request_class:
  request_reserved_exposure:
  accepted_output_limits:
  execution_deadline:
  runtime_execution_reference:
  endpoint_signature:
```

---

## 61. Request Rejection

A Request MAY be rejected without terminating the Session.

A rejected Request SHALL not reserve exposure after rejection finalization.

---

## 62. Request Lifecycle

A Request follows:

```text
SUBMITTED
    ↓
ACCEPTED
    ↓
QUEUED
    ↓
EXECUTING
    ↓
STREAMING
    ↓
COMPLETED
```

Alternative states include:

REJECTED
CANCEL_REQUESTED
CANCELLED
FAILED
EXPIRED
PARTIAL
RECOVERING

---

## 63. Request Classification

When price depends on Request Class, the class SHALL be determinable before execution from accepted observable properties.

The Endpoint SHALL NOT retroactively reclassify completed work into a more expensive class.

---

## 64. Request Queueing

Queueing is permitted only when:

* Session Policy permits it;
* maximum queue time is declared;
* queue-time billing treatment is declared;
* Request deadline remains satisfiable.

---

## 65. Queue Time

Queue time SHALL be distinguishable from:

* active execution;
* upstream waiting;
* retry delay;
* Consumer waiting;
* operator intervention.

It is billable only when the Pricing Policy explicitly says so.

---

## 66. Request Execution Start

The Endpoint SHOULD emit:

REQUEST_EXECUTION_STARTED

This event SHALL include:

* Request ID;
* event sequence;
* Runtime reference;
* start timestamp or canonical timing reference;
* Endpoint signature.

---

## 67. Idempotency

A repeated Request with identical:

* Session ID;
* Request ID;
* idempotency key;
* payload hash;
* contract hash;

SHALL NOT create duplicate execution.

The Endpoint SHALL return the current Request state or existing result.

---

## 68. Conflicting Request Replay

The same Request ID with different content is invalid.

The Endpoint SHALL:

* reject the conflicting message;
* preserve evidence;
* not start a second execution.

---

## 69. Internal Retries

The Endpoint or Proxy MAY retry internal execution according to the accepted policy.

Internal retries SHALL NOT automatically create multiple Consumer charges.

Any attempt-based billing SHALL be:

* declared before execution;
* bounded by Request ceiling;
* visible in Usage Reports.

---

## 70. Stateful Sessions

A stateful Session MAY preserve:

* conversation context;
* agent workspace;
* Provider thread;
* tool state;
* Runtime cache;
* file state;
* task graph.

The Session Policy SHALL define persistence guarantees.

---

## 71. Session Affinity

A stateful Session SHOULD remain bound to a compatible Runtime or upstream context.

If affinity is lost:

* the Endpoint SHALL not silently pretend continuity;
* recovery, reconstruction or reset SHALL be explicit.

---

## 72. Stateless Requests

A stateless Endpoint MAY route every Request independently.

The Advertisement and Session Policy SHALL not imply hidden continuity.

---

## 73. Context Ownership

The Session Contract SHALL identify whether context is:

CONSUMER_SUPPLIED
RUNTIME_STORED
PROXY_UPSTREAM_STORED
RECONSTRUCTIBLE
EPHEMERAL

---

## 74. Streaming

A Capability MAY support ordered streaming.

Every chunk SHALL include:

```yaml
response_chunk:
  session_id:
  request_id:
  stream_id:
  chunk_sequence:
  chunk_hash:
  cumulative_observable_output:
  payload:
  endpoint_authentication:
```

---

## 75. Stream Ordering

The Consumer SHALL be able to detect:

* missing chunks;
* duplicate chunks;
* reordering;
* conflicting chunks;
* incomplete streams.

---

## 76. Chunk Acknowledgment

The Consumer MAY acknowledge one or more chunks.

Acknowledgment MAY contribute to:

* delivery evidence;
* partial-result billing;
* recovery position;
* result-root confirmation.

---

## 77. Stream Completion

A completed stream SHALL end with:

STREAM_COMPLETE

including:

* final sequence;
* result root;
* completion status;
* final Usage Report reference.

---

## 78. Partial Stream

A partial stream is billable only according to the accepted:

* Pricing Policy;
* Failure Policy;
* acknowledgment evidence;
* Last Accepted Checkpoint.

Unacknowledged output SHALL not automatically become billable.

---

## 79. Artifact Delivery

A Request MAY produce content-addressed artifacts.

Examples include:

* images;
* audio;
* video;
* files;
* code patches;
* archives;
* datasets.

---

## 80. Artifact Descriptor

```yaml
artifact_descriptor:
  artifact_id:
  session_id:
  request_id:
  content_type:
  content_hash:
  content_size:
  encoding:
  storage_reference:
  access_policy_hash:
  retention_deadline:
  endpoint_signature:
```

---

## 81. Artifact Completion

An artifact counts as delivered only when:

* its descriptor is valid;
* content matches the hash;
* the Consumer can retrieve or receive it;
* required delivery evidence exists.

A descriptor pointing to missing content is not successful delivery.

---

## 82. Tool Execution

Capabilities with tools SHALL expose tool-call evidence sufficient to determine:

* selected tool;
* input commitment;
* side-effect class;
* approval status;
* execution result;
* output commitment;
* failure state.

---

## 83. Side-Effect Classes

Initial side-effect classes are:

READ_ONLY
REVERSIBLE
EXTERNAL_WRITE
IRREVERSIBLE
FINANCIAL
SECURITY_SENSITIVE

---

## 84. Explicit Side-Effect Approval

The Session Policy MAY require an additional Consumer approval token before:

* external writes;
* publishing;
* sending messages;
* deployment;
* financial action;
* irreversible modification.

---

## 85. Retry Safety

Non-idempotent side effects SHALL NOT be retried blindly.

A retry requires:

* stable upstream idempotency;
* proof the prior attempt did not execute;
* or explicit Consumer authorization.

---

## 86. Request Cancellation

The Consumer MAY submit:

REQUEST_CANCEL

Cancellation SHALL reference:

* Session ID;
* Request ID;
* cancellation sequence;
* reason;
* Consumer signature.

---

## 87. Cancellation Result

The Endpoint SHALL report one of:

CANCELLATION_ACCEPTED
CANCELLATION_TOO_LATE
CANCELLATION_UNSUPPORTED
REQUEST_ALREADY_COMPLETED

---

## 88. Cancellation Pricing

The accepted policy SHALL define whether the Consumer may be charged for:

* completed work;
* acknowledged partial results;
* active execution time;
* fixed attempt fee;
* irreversible external costs.

The Request ceiling remains binding.

---

## 89. Endpoint-Initiated Termination

The Endpoint MAY terminate a Request because of:

* Deposit exhaustion;
* Runtime failure;
* upstream failure;
* policy violation;
* deadline;
* security risk;
* invalid Consumer behavior.

The Endpoint SHALL publish a stable failure class.

---

## 90. Accounting Modes

The Session Contract SHALL identify the Accounting Mode.

Initial modes include:

DETERMINISTIC
OBSERVABLE
PROVIDER_METERED
PROXY_OPAQUE
FIXED_PRICE
HYBRID

---

## 91. Exact Token Billing

Token billing is authoritative only when based on:

* a shared deterministic tokenizer and version;
* or an authoritative upstream usage report accepted by the Accounting Contract.

Locally estimated tokens SHALL not be represented as authoritative upstream usage.

---

## 92. Proxy-Opaque Accounting

When upstream usage is unavailable:

* unknown values remain unknown;
* diagnostic estimates MAY be reported;
* estimates SHALL be marked non-authoritative;
* billing SHALL use fixed or observable accepted units.

---

## 93. Usage Reports

Every billable Session SHALL produce signed Usage Reports.

A Usage Report SHALL distinguish:

* measured values;
* observable values;
* estimated values;
* unavailable values;
* billable values.

---

## 94. Usage Report Sequence

Usage Reports SHALL use a monotonic sequence.

Every report SHOULD commit to:

* previous Usage Report hash;
* cumulative billable state;
* cumulative result or artifact root.

---

## 95. Usage Checkpoint

A Usage Checkpoint SHALL contain:

```yaml
usage_checkpoint:
  session_id:
  checkpoint_sequence:
  last_request_sequence:
  usage_report_hash:
  cumulative_billable_charge:
  cumulative_result_root:
  pending_exposure:
  available_exposure:
  endpoint_signature:
```

---

## 96. Consumer Checkpoint Acknowledgment

The Consumer MAY acknowledge a Checkpoint.

```yaml
checkpoint_acknowledgment:
  session_id:
  checkpoint_hash:
  accepted_cumulative_charge:
  accepted_result_root:
  consumer_signature:
```

---

## 97. Last Accepted Checkpoint

The Last Accepted Checkpoint is the strongest ordinary mutual economic baseline.

Forced Settlement MAY consider later objective evidence only under RFC-0060.

---

## 98. Checkpoint Does Not Waive Fraud

Acknowledgment does not waive challenges based on:

* invalid signatures;
* duplicate billing;
* conflicting reports;
* cryptographic fraud;
* protocol-invalid accounting.

---

## 99. Checkpoint Frequency

Checkpoint frequency SHOULD increase with:

* cumulative charge;
* execution duration;
* output volume;
* side-effect risk;
* artifact delivery;
* unacknowledged exposure.

---

## 100. Maximum Unacknowledged Exposure

A Session Policy SHOULD define:

MaximumUnacknowledgedExposure

The Endpoint SHOULD stop or pause further execution when unacknowledged exposure exceeds that amount.

This limits risk for both parties.

---

## 101. Deposit-Low Warning

Before available exposure becomes insufficient, the Endpoint SHOULD emit:

DEPOSIT_LOW

including:

* accepted cumulative charge;
* pending exposure;
* available exposure;
* required top-up;
* Requests at risk.

---

## 102. Deposit Exhaustion

When:

```text
AvailableExposure = 0
```

the Endpoint SHALL NOT accept new billable Requests.

Active Requests may continue only within their already reserved exposure.

---

## 103. No Negative Consumer Balance

Session execution SHALL NOT produce a negative Consumer Wallet balance.

Execution beyond accepted collateral remains Endpoint risk unless another explicit funding mechanism exists.

---

## 104. Session Heartbeats

Long Sessions MAY use heartbeats.

Heartbeat data MAY include:

* Session state;
* active Request count;
* last event sequence;
* last Usage Report;
* last Checkpoint;
* Runtime state.

Heartbeats are not billable usage.

---

## 105. Idle Timeout

The Session Policy MAY define an Idle Timeout.

After timeout, the Session MAY enter:

DRAINING

or:

CLOSING

No arbitrary collateral deduction follows from inactivity unless explicitly accepted.

---

## 106. Absolute Expiration

Every Session SHALL have an absolute expiration.

Expiration prevents indefinite:

* collateral lock;
* Runtime reservation;
* unresolved Session state;
* stale authorization.

---

## 107. Session Amendment

The MVP MAY permit amendments for:

* Deposit extension;
* maximum Session charge increase;
* expiration extension;
* Request-count increase;
* artifact-limit increase.

An amendment SHALL be signed by all economically affected parties.

The local MVP represents an accepted amendment as an immutable
`session-amendment.v1` Registry Object and stores the ordered objects in the
Session snapshot. Each amendment contains:

* `amendment_id` and contiguous `sequence`;
* `previous_effective_terms_hash` and optional `previous_amendment_hash`;
* `amendment_kind` and canonical `changes`;
* Consumer and Endpoint signatures;
* `effective_terms_hash` for the new contract head;
* `amendment_hash` for the complete acceptance evidence;
* the Registry `object_id`.

The initial `effective_terms_hash` equals `session_contract_hash`. A valid
amendment replaces neither the original Session Contract hash nor completed
Request terms. It advances only the effective-terms head. Re-submitting an
existing `amendment_id` is idempotent when the signed content is identical;
conflicting content is rejected.

For an MVP Session, both signatures are verified against the registered
Consumer and Endpoint Wallet identities over the canonical amendment signing
payload. A local non-economic Session without registered Wallet keys remains
compatibility-readable, but a public MVP amendment fails closed when either
identity is unavailable.

The MVP applies expiration, Request-limit and artifact-limit amendments at
the local Session boundary. Deposit and maximum-charge amendments require a
predecessor-bound canonical funding proof from `SESSION_ESCROW_EXTEND`; the
application verifier checks the operation, Funding Account and successor
funding hash before updating the local Session/Deposit projection. The Ledger
remains the authority for the actual escrow mutation.

---

## 107.1 Session Contract Exchange

A Hypervisor MAY exchange the accepted Session Contract with another authorized
participant as an immutable evidence package. The exchange package SHALL bind:

```yaml
session_contract_exchange:
  session_id:
  session_contract_object_id:
  session_contract_object_version:
  session_contract_namespace:
  session_contract_hash:
  session_contract:
  amendments:
  amendment_sequence:
  effective_terms_hash:
  exchange_hash:
```

The package SHALL include the canonical base Session Contract payload and the
complete ordered amendment chain. Its `exchange_hash` SHALL commit to every
field except itself. The receiver SHALL verify:

* the base payload hash and Registry Object identity;
* the Session ID inside the payload;
* contiguous amendment sequence and predecessor hashes;
* the effective-terms head and amendment object identities;
* the exchange hash when supplied.

An export SHALL fail when the local Session projection, base Registry Object or
amendment chain is inconsistent. An import SHALL be idempotent for identical
Registry Objects and SHALL preserve conflict evidence for any differing object
with the same identity.

Importing an exchange package stages immutable Session Contract evidence in the
local Registry. It SHALL NOT:

* activate or accept a Session;
* overwrite a local Session projection;
* change funding, charge ceilings or Settlement state;
* authorize execution on behalf of a missing participant.

If a local Session with the same ID already exists, its base hash, amendment
chain and effective-terms head SHALL match the package or the import SHALL fail
closed. Transport authentication, peer authorization and replay protection are
provided by the applicable network or Registry channel; this object-level
validation remains mandatory regardless of transport.

---

## 108. Prohibited Amendment

An amendment SHALL NOT retroactively:

* increase a completed Request charge;
* replace delivered-result terms;
* reduce an earned Consumer refund;
* change already accepted Failure Policy;
* change Settlement Resolver;
* transform an ordinary Session into a concealed Validation Session.

---

## 109. Session Draining

Either party MAY request draining.

During draining:

* no new Requests are accepted;
* accepted Requests reach terminal states;
* final Usage evidence is produced;
* Session close begins.

---

## 110. Cooperative Close

Either party MAY submit:

SESSION_CLOSE_REQUEST

The counterparty MAY respond with:

SESSION_CLOSE_ACK

---

## 111. Close Request

A Close Request SHALL include:

* final known Request sequence;
* active Request summary;
* proposed final Usage Checkpoint;
* proposed result root;
* close reason;
* signature.

---

## 112. Close Reconciliation

Before cooperative Settlement, each Request SHALL be classified as:

COMPLETED
CANCELLED
FAILED
EXPIRED
PARTIAL

No Request may remain ambiguously billable.

---

## 113. Settlement

Every Session SHALL terminate through one valid Settlement transition.

Initial Settlement types are:

SESSION_SETTLE
SESSION_FORCE_SETTLE
VALIDATION_SESSION_SETTLE

---

## 114. Settlement Conservation

Every Settlement SHALL satisfy:

```text
LockedDeposit
=
ProviderPayment
+
Refund
+
NetworkFees
+
ProtocolCosts
+
FinalizedPenalties
```

The refund recipient depends on Funding Authorization.

---

## 115. Ordinary Consumer Settlement

For an ordinary Consumer-funded Session:

```text
ProviderPayment
=
min(
    AcceptedBillableCharge,
    MaximumSessionCharge
)
```

and:

```text
ConsumerRefund
=
LockedDeposit
-
AuthorizedDeductions
```

---

## 116. Ordinary Sponsored Settlement

For an ordinary sponsored Session:

* Provider receives the accepted billable amount;
* unused collateral returns to the sponsor or declared refund destination;
* Consumer does not receive unrelated sponsor funds.

---

## 117. Concealed Validation Settlement

For a valid concealed Validation Session:

```text
ProviderPayment = 0Q
```

and:

```text
EscrowRefund
=
LockedDeposit
-
NetworkFees
-
AuthorizedProtocolCosts
-
FinalizedPenalties
```

The result follows RFC-0064.

---

## 118. Validation Session Usage

Usage Reports remain required during Validation Sessions.

They serve as:

* accounting observations;
* protocol evidence;
* maximum-limit evidence;
* Validation Report inputs.

They do not create Endpoint Payment.

---

## 119. Resolver Reveal

A concealed resolver MAY be resolved through:

* valid Assignment reveal;
* valid protocol authority reveal;
* deterministic timeout resolution;
* emergency State Repair where the original resolver is defective.

---

## 120. Resolver Withholding

Failure by a Validator or another actor to publish a report SHALL NOT lock Session collateral indefinitely.

After the declared deadline, the protocol SHALL resolve the Session according to the committed resolver.

---

## 121. Ordinary Settlement Prohibition

Once a Session is proven to use a concealed Validation resolver, ordinary SESSION_SETTLE SHALL be rejected.

A Session may settle only once.

---

## 122. Forced Settlement

When cooperative close fails, RFC-0060 defines:

* evidence collection;
* recovery window;
* Last Accepted Checkpoint use;
* later objective evidence;
* Endpoint Payment;
* refund;
* failure attribution.

---

## 123. Conservative Settlement Baseline

In the absence of stronger objective evidence:

Last Accepted Checkpoint

is the default economic baseline for Forced Settlement.

---

## 124. Duplicate Settlement Prevention

One Session economic state SHALL be consumed exactly once.

Repeated Settlement submission is idempotent or invalid.

---

## 125. Conflicting Settlement Evidence

Conflicting signed Settlement or Usage claims SHALL be preserved as protocol evidence.

Only one canonical Settlement may finalize.

---

## 126. Consumer Disconnection

Consumer disconnection does not automatically:

* cancel Requests;
* transfer Deposit;
* close the Session.

The accepted recovery and timeout policy applies.

---

## 127. Endpoint Disconnection

Endpoint disconnection SHALL:

* stop new Request acceptance;
* preserve evidence;
* enter recovery where permitted;
* eventually trigger failure handling.

---

## 128. Runtime Failure

Runtime failure does not erase Endpoint responsibility.

The Endpoint MAY:

* reconnect the Runtime;
* replace the Runtime;
* resume execution;
* fail Requests;
* drain the Session.

---

## 129. Session Recovery State

A recoverable Session SHALL preserve:

* Session Contract;
* Request sequence;
* Request states;
* stream position;
* artifact commitments;
* Usage Report chain;
* Last Accepted Checkpoint;
* Pending Exposure;
* Settlement state.

---

## 130. Session Resume

A resumed Session SHALL reconcile:

* Consumer Request Sequence;
* Endpoint event sequence;
* Request terminal states;
* last Usage Report;
* last Checkpoint;
* delivered chunks;
* artifact availability;
* economic exposure.

---

## 131. Divergent Recovery State

When parties report incompatible recovery state:

* new billable work SHALL pause;
* signed evidence is compared;
* Forced Settlement or explicit recovery resolution applies.

---

## 132. Runtime Replacement

A replacement Runtime may continue a Session only when it can preserve:

* Capability semantics;
* Session context;
* Request identities;
* Usage chain;
* output commitments;
* side-effect safety.

Otherwise, affected Requests SHALL fail or require Consumer-approved restart.

---

## 133. Cross-Epoch Sessions

A Session MAY span multiple Epochs.

The Session remains bound to the policy versions accepted at Session opening.

Epoch transitions SHALL NOT retroactively reprice it.

---

## 134. Epoch Evidence Attribution

Session events belong to the Epoch in which their canonical commitments finalize.

Examples:

* Session opens in Epoch 10;
* Request completes in Epoch 11;
* Settlement finalizes in Epoch 12.

The Contract remains unchanged.

---

## 135. Protocol Upgrade

A compatible upgrade MAY allow active Sessions to continue under old semantics during a Compatibility Window.

An incompatible upgrade SHALL:

* drain Sessions;
* settle them under old rules;
* or apply an explicitly authorized deterministic migration.

---

## 136. Endpoint Configuration Change

A new Endpoint Configuration Hash affects new Sessions.

Existing Sessions remain bound to the accepted Configuration Hash.

---

## 137. Endpoint Withdrawal

Withdrawal stops new Session acceptance.

Existing Sessions follow their accepted:

* continuation;
* draining;
* failure;
* Settlement rules.

---

## 138. Proxy Sessions

A Proxy Session follows RFC-0063.

The outer Endpoint remains responsible for:

* Request execution;
* Usage Reports;
* retries;
* failover;
* maximum charge;
* Settlement;
* upstream failure.

---

## 139. Proxy Chain Economics

Internal Proxy costs SHALL NOT create unbounded outer Consumer liability.

```text
OuterConsumerCharge
≤
OuterMaximumSessionCharge
```

---

## 140. Validation Sessions

Concealed Validation Sessions reuse ordinary:

* Session opening;
* Request execution;
* Usage Reporting;
* evidence;
* failure handling.

They differ in:

* Funding Authorization;
* concealed resolver;
* Endpoint Payment;
* Assignment reveal;
* Validation Report linkage.

---

## 141. Data Handling Policy

Every Session SHALL bind to a Data Handling Policy when data may be:

* retained;
* logged;
* sent upstream;
* processed outside the Hypervisor;
* used by tools;
* transferred across regions.

---

## 142. Data Minimization

Public Ledger and Registry state SHOULD store:

* hashes;
* commitments;
* signed summaries;
* economic state;
* object references;

rather than raw prompts and outputs.

---

## 143. Private Transport

Request and response payloads SHOULD use authenticated encrypted transport.

Wallet signatures are not required for every data chunk.

---

## 144. Evidence Privacy

Dispute and Validation evidence SHOULD reveal only what is necessary.

Sensitive evidence MAY be:

* encrypted;
* selectively disclosed;
* hash-committed;
* access-controlled.

---

## 145. Session Message Sequencing

Each party SHALL maintain monotonic control-message sequencing where ordering matters.

Separate sequences MAY exist for:

* Consumer control messages;
* Endpoint control messages;
* Requests;
* Usage Reports;
* stream chunks;
* amendments.

---

## 146. Message Idempotency

Retransmittable messages SHALL be idempotent.

This includes:

* Session acceptance;
* Request acceptance;
* cancellation;
* Usage Reports;
* Checkpoint acknowledgment;
* close messages;
* Settlement proposals.

---

## 147. Backpressure

The data plane SHOULD support:

WINDOW_UPDATE
PAUSE
RESUME
RATE_LIMITED
RETRY_AFTER

Ignoring valid backpressure MAY terminate the affected Request.

---

## 148. Rate Limits

The Endpoint MAY enforce accepted limits for:

* Requests per Session;
* concurrent Requests;
* input size;
* output size;
* artifacts;
* tool calls;
* stream frequency;
* active execution time.

---

## 149. Stable Error Classes

Provider-specific failures SHALL be mapped to stable AiDN error classes.

Raw upstream diagnostics MAY be included only after secret removal.

---

## 150. Required Error Codes

The MVP SHALL define at least:

SESSION_NOT_FOUND
SESSION_ALREADY_EXISTS
SESSION_CONTRACT_INVALID
SESSION_CONFIGURATION_MISMATCH
SESSION_POLICY_MISMATCH
SESSION_CAPABILITY_MISMATCH
SESSION_FUNDING_INVALID
SESSION_DEPOSIT_INSUFFICIENT
SESSION_DEPOSIT_EXTENSION_INVALID
SESSION_MAXIMUM_CHARGE_EXCEEDED
SESSION_PENDING_EXPOSURE_EXCEEDED
SESSION_ACCEPTANCE_EXPIRED
SESSION_ALREADY_ACCEPTED
SESSION_REJECTED
SESSION_EXPIRED
SESSION_NOT_ACTIVE
SESSION_DRAINING
SESSION_ALREADY_SETTLED
REQUEST_NOT_FOUND
REQUEST_DUPLICATE
REQUEST_CONFLICT
REQUEST_SEQUENCE_INVALID
REQUEST_SCHEMA_INVALID
REQUEST_LIMIT_EXCEEDED
REQUEST_EXPOSURE_UNAVAILABLE
REQUEST_CHARGE_CEILING_EXCEEDED
REQUEST_DEADLINE_EXPIRED
REQUEST_CANCELLATION_TOO_LATE
REQUEST_SIDE_EFFECT_APPROVAL_REQUIRED
REQUEST_RETRY_UNSAFE
STREAM_SEQUENCE_INVALID
STREAM_CHUNK_CONFLICT
ARTIFACT_HASH_MISMATCH
ARTIFACT_UNAVAILABLE
USAGE_REPORT_INVALID
USAGE_SEQUENCE_INVALID
CHECKPOINT_CONFLICT
UNACKNOWLEDGED_EXPOSURE_LIMIT
SETTLEMENT_INVALID
SETTLEMENT_CONFLICT
SETTLEMENT_CONSERVATION_FAILURE
SETTLEMENT_RESOLVER_INVALID
SETTLEMENT_RESOLVER_NOT_REVEALED
ORDINARY_SETTLEMENT_PROHIBITED
RECOVERY_STATE_MISMATCH
SESSION_PROTOCOL_VERSION_UNSUPPORTED

## Runtime Acceptance Binding

A Session route SHALL retain the accepted Endpoint Configuration Hash and its
authorized Runtime Binding Hash or compatible Runtime set. Stateful Sessions
SHOULD remain pinned to one Runtime lineage and State Generation. Route
reconnect SHALL NOT silently migrate Session state. Runtime failover requires
contract-compatible behavior, preserved Request IDs and Usage continuity, or
the Session enters explicit RFC-0060 recovery.

`RUNTIME_REQUEST_ACCEPT` records execution responsibility but SHALL NOT advance
the Session to completed or payable state. Session Request state follows
RFC-0054 progress and becomes terminal only after a valid `RUNTIME_RESULT` plus
applicable Usage processing. `PARTIAL`, `CANCELLED`, `FAILED`, `EXPIRED` and
`UNRECOVERABLE` results enter the corresponding Session and RFC-0060 policy.

---

## 151. Ledger Operations

RFC-0059 SHALL support:

SESSION_OPEN
SESSION_ACCEPT
SESSION_REJECT
SESSION_DEPOSIT_EXTEND
SESSION_AMEND
SESSION_CLOSE_REQUEST
SESSION_CLOSE_ACK
SESSION_SETTLE
SESSION_FORCE_SETTLE
VALIDATION_SESSION_SETTLE

Most Request-level traffic remains off-chain.

---

## 152. Registry Objects

Registry Services MAY store:

* Session Contract;
* Usage Reports;
* Checkpoints;
* result manifests;
* artifact descriptors;
* failure reports;
* resolver reveals;
* Settlement evidence;
* encrypted dispute evidence.

---

## 153. Reputation Events

Session behavior MAY create Reputation Events for:

* successful completion;
* Endpoint unavailability;
* request duplication;
* Usage mismatch;
* Settlement conflict;
* artifact failure;
* successful recovery;
* repeated abandonment;
* protocol abuse.

Reputation processing does not replace economic Settlement.

---

## 154. Security Threats

The protocol SHALL account for:

* Session replay;
* Request replay;
* duplicate execution;
* duplicate Settlement;
* Deposit exhaustion;
* concurrent exposure overflow;
* Usage inflation;
* concealed-resolver downgrade;
* invalid resolver reveal;
* stream-chunk conflict;
* artifact substitution;
* cancellation races;
* unsafe retry;
* side-effect duplication;
* Session-key compromise;
* stale policy acceptance;
* cross-revision replay.

---

## 155. No Reward for Session Registration

Opening or accepting a Session does not create protocol emission.

Ordinary Endpoint revenue comes from valid Settlement of Consumer or sponsored collateral.

---

## 156. Session Metrics

Implementations SHOULD expose:

* active Sessions;
* pending acceptance;
* locked Deposit;
* accepted cumulative charge;
* Pending Exposure;
* available exposure;
* active Requests;
* queue depth;
* unacknowledged exposure;
* recovery state;
* Settlement backlog;
* failure distribution.

---

## 157. Consumer Visibility

The Consumer SHOULD be able to inspect:

* Session Contract;
* locked Deposit;
* maximum Session charge;
* accepted cumulative charge;
* Pending Exposure;
* active Requests;
* Usage Reports;
* Last Accepted Checkpoint;
* expiration;
* final Settlement.

---

## 158. Endpoint Visibility

The Endpoint SHOULD be able to inspect:

* valid Funding Authorization;
* accepted limits;
* Request sequence;
* reserved exposure;
* cumulative charge;
* active Requests;
* close state;
* Settlement state.

Concealed resolver details may remain hidden until resolution.

---

## 159. Conformance Testing

Implementations SHALL be tested for:

* duplicate Session Open;
* stale Configuration Hash;
* insufficient Deposit;
* acceptance timeout;
* parallel exposure overflow;
* duplicate Request;
* conflicting Request;
* internal retry;
* unsafe side effect;
* stream gaps;
* artifact corruption;
* Deposit extension;
* Deposit exhaustion;
* cancellation race;
* reconnect;
* conflicting Checkpoints;
* ordinary Settlement;
* sponsored Settlement;
* Validation Settlement;
* Forced Settlement;
* protocol upgrade compatibility.

---

## 160. MVP Requirements

The MVP SHALL implement:

* immutable Session Contract;
* unique Session and Request IDs;
* network and revision domain separation;
* direct and sponsored Deposit;
* generic concealed sponsored credential;
* Session Open, Accept and Reject;
* maximum Session charge;
* Pending Exposure;
* per-Request exposure reservation;
* multiple Requests;
* Request idempotency;
* Request charge ceilings;
* streaming;
* artifact descriptors;
* cancellation;
* side-effect approval hooks;
* Usage Reports;
* Checkpoints;
* Consumer acknowledgments;
* Last Accepted Checkpoint;
* Deposit extension;
* cooperative close;
* ordinary Settlement;
* Forced Settlement integration;
* Validation Settlement integration;
* Session recovery;
* cross-Epoch operation;
* protocol-version binding;
* deterministic fixed-point accounting.

---

## 161. Deferred Features

The MVP MAY postpone:

* automatic bounded Deposit top-up;
* multi-Consumer Sessions;
* multi-Endpoint atomic Sessions;
* streaming micropayment release;
* zero-knowledge Usage proofs;
* confidential Settlement amounts;
* Session ownership transfer;
* cross-network Sessions;
* generalized contract scripting;
* transferable active agent workspaces.

---

## 162. Open Protocol Parameters

The following remain configurable:

* minimum Session Deposit;
* acceptance timeout;
* Session expiration;
* Idle Timeout;
* recovery window;
* maximum Requests;
* maximum concurrent Requests;
* checkpoint frequency;
* Maximum Unacknowledged Exposure;
* Deposit-low threshold;
* artifact retention;
* stream window;
* Resolver reveal timeout;
* Settlement challenge window;
* maximum amendment count;
* maximum Session duration.

---

## 163. Economic Invariants

```text
ProviderPayment
≤
MaximumSessionCharge

MaximumSessionCharge
≤
LockedDeposit

AcceptedCumulativeCharge
+
PendingExposure
≤
MaximumSessionCharge

SettlementOutputs
=
LockedDeposit

UnknownUsage
≠
ExactBillableUsage

DuplicateRequest
DoesNotCreateDuplicatePayment

ValidationSessionProviderPayment
=
0Q
```

---

## 164. Contract Invariants

* Accepted Session policies are immutable.
* Existing Sessions retain their Configuration Hash.
* Existing Sessions are not retroactively repriced.
* Every accepted Session binds to one exact Advertisement or Offer scope through `advertisement_id` and optional `offer_id`.
* Every Request belongs to one Session.
* Every Request has one stable identity.
* One Session has one Settlement Resolver.
* One Session settles at most once.
* Amendments do not rewrite completed work.
* Settlement does not reinterpret a Session under a later Advertisement version.

---

## 165. Request Invariants

* Request acceptance reserves maximum exposure.
* Concurrent Requests cannot exceed Session exposure.
* Duplicate Requests are idempotent.
* Conflicting Request replays are rejected.
* Request charges cannot exceed their ceilings.
* Side effects are not retried blindly.
* Terminal Requests release unused exposure.

---

## 166. Security Invariants

* Session messages are replay-protected.
* Session keys cannot spend arbitrary Wallet funds.
* Endpoint cannot exceed locked collateral.
* Consumer cannot obtain duplicate execution through retransmission.
* Concealed Settlement cannot be downgraded to ordinary Settlement.
* Resolver withholding cannot lock collateral indefinitely.
* Stream conflicts are detectable.
* Artifacts are content-addressed.
* Recovery does not create a second economic Session.
* Cross-Revision replay is rejected.

---

## 167. Design Invariants

* A Session is both an execution contract and an economic boundary.
* Transport loss does not automatically destroy Session state.
* Endpoint remains responsible for Runtime and upstream behavior.
* Data-plane work remains mostly off-chain.
* Economic commitments remain canonical.
* Deposit is collateral rather than automatic Provider revenue.
* Usage Reports describe work.
* Checkpoints establish accepted economic baselines.
* Settlement resolves ownership of collateral.
* Failure recovery is conservative.
* Proxy Sessions preserve the outer contract.
* Concealed Validation reuses the ordinary data plane but uses a different Settlement Resolver.

Основные изменения относительно v0.2

1. Добавлен PendingExposure

Раньше было достаточно проверять:

AcceptedCharge ≤ Deposit

Но при трёх параллельных запросах каждый мог зарезервировать почти весь остаток. Поэтому новая формула:

AcceptedCumulativeCharge
+
PendingExposure
≤
MaximumSessionCharge

Пример:

Maximum Session Charge: 20Q
Already accepted: 5Q
Request A reserved: 8Q
Request B reserved: 6Q

Получаем:

5 + 8 + 6 = 19Q

Следующий Request можно принять максимум с резервом 1Q.

Это не даёт Endpoint выполнить работ на 30Q, а потом с трагическим достоинством обнаружить, что в Deposit лежало только 20Q.

2. Funding и Settlement окончательно разделены

Теперь:

Funding Authorization

отвечает на вопрос:

Достаточно ли обеспечения для запуска Session?

А:

Settlement Resolver

отвечает:

Кому и на каких основаниях достанется обеспечение после работы?

Это позволяет одной Session-модели поддерживать:

* обычную оплату Consumer;
* оплату спонсором;
* протокольный Escrow;
* concealed Validation.

3. Validation больше не выглядит особым типом Session

Endpoint не получает поле:

is_validation: true

Он видит общий sponsored credential и достаточный Deposit.

После выполнения раскрывается Resolver:

VALIDATION_SESSION_SETTLE
Endpoint Payment = 0Q

Если Validator исчезнет и не опубликует отчёт, Deposit всё равно не зависает навсегда: действует Resolver reveal timeout.

4. Request теперь имеет собственный экономический лимит

Помимо общего Session maximum:

MaximumSessionCharge

каждый Request имеет:

RequestChargeCeiling

и:

RequestReservedExposure

Endpoint не может провести дешёвый Request как дорогой только потому, что в общей Session ещё хватает денег.

5. Checkpoint не равен Usage Report

Usage Report

является заявлением Endpoint.

Checkpoint acknowledgment

является подтверждением Consumer.

Именно последний подтверждённый Checkpoint становится основой обычного Forced Settlement, если стороны после этого перестали общаться как взрослые распределённые процессы.

6. Усилена защита от повторных side effects

Повторный текстовый запрос обычно создаёт лишний текст.

Повторный агентный запрос может:

* второй раз отправить письмо;
* второй раз создать Pull Request;
* дважды выполнить deployment;
* повторить финансовую операцию.

Поэтому Request ID и idempotency обязательны, а действия с side effects требуют дополнительных правил повторного запуска.

7. Документ теперь задаёт правильную границу

RFC-0044 отвечает за:

* Contract;
* Deposit;
* Request;
* Usage;
* Checkpoint;
* Settlement.

Он не должен подробно определять:

* как Runtime запускает модель;
* как Proxy выбирает upstream;
* как Validator пишет отчёт;
* как Forced Settlement оценивает каждый класс отказа.

Эти детали остаются в специализированных RFC, а Session Protocol задаёт общий каркас, чтобы они не создавали каждый собственную несовместимую разновидность "сессии".
