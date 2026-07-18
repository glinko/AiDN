# RFC-0060 Session Failure, Recovery and Forced Settlement

Status: `Draft`

Version: `0.6`

Revision note: Forced Settlement evaluates the last accepted RFC-0051 Usage
chain and explicit incomplete/conflicting Usage policy without inventing values.

Supersedes:

- `RFC-0060 Version 0.5`

Depends on:

- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0037 Settlement Engine`
- `RFC-0041 Reputation Profile Engine`
- `RFC-0042 Hypervisor Network Protocol`
- `RFC-0044 Session Protocol`
- `RFC-0047 CometBFT Consensus Integration`
- `RFC-0051 Usage Reporting and Verification Protocol`
- `RFC-0059 Ledger Operation Catalog`
- `ECO-0005 Q Emission, Recycling and Epoch Reward Allocation`

## 1. Purpose

This document defines deterministic behavior for Sessions that cannot complete through ordinary cooperative Settlement.

It specifies:

- failure classifications;
- Session recovery;
- timeout handling;
- disappearance of either participant;
- incomplete and partially completed requests;
- Deposit exhaustion;
- Provider-initiated termination;
- Consumer-initiated termination;
- accounting mismatch termination;
- Proxy Endpoint failure;
- Consensus interruption;
- forced Settlement;
- evidence requirements;
- Reputation consequences.

The protocol SHALL ensure that every Session eventually reaches a terminal state.

## 2. Core Principle

Forced Settlement SHALL pay only amounts that are:

- supported by valid protocol evidence;
- permitted by the accepted Session Policy;
- covered by the locked Session Deposit;
- attributable to completed or explicitly billable work.

Unverified claims SHALL NOT be paid automatically.

The last mutually accepted Usage Checkpoint defines the default uncontested accounting baseline.

## 3. Design Principles

Session failure handling SHALL be:

- deterministic;
- bounded;
- replay-protected;
- privacy-preserving;
- independent of subjective arbitration;
- conservative with disputed funds;
- compatible with temporary network failure;
- resistant to deliberate participant disappearance.

Neither party SHALL benefit automatically from causing a Session failure.

## 4. Participants

A Session includes:

Consumer Hypervisor

The participant purchasing access to an Endpoint Capability.

Provider Hypervisor

The participant publishing and operating the Endpoint.

Capability Runtime

The Provider-side service performing Capability-specific execution.

The Hypervisor-to-Runtime recovery and control boundary is defined separately by `RFC-0054`.

Ledger

The canonical source of:

- locked Deposit;
- accepted policies;
- Session state;
- finalized Settlement;
- protocol deadlines.

Registry

The storage layer for:

- signed Usage Reports;
- acknowledgements;
- failure evidence;
- Mismatch Reports;
- large off-chain artifacts.

## 5. Session State Machine

The complete Session state machine includes:

`PENDING_ACCEPTANCE -> ACTIVE -> CLOSING -> SETTLED`

Failure-related states include:

- `REJECTED`
- `CANCELLED`
- `EXPIRED`
- `RECOVERING`
- `PAUSED`
- `DEPOSIT_EXHAUSTED`
- `ACCOUNTING_MISMATCH`
- `PROVIDER_UNAVAILABLE`
- `CONSUMER_UNAVAILABLE`
- `FORCE_CLOSING`
- `FORCE_SETTLED`
- `UNRECOVERABLE`

Every Session SHALL reach exactly one terminal state.

Terminal states are:

- `SETTLED`
- `FORCE_SETTLED`
- `REJECTED`
- `CANCELLED`
- `EXPIRED`
- `UNRECOVERABLE`

`UNRECOVERABLE` SHALL still require final Deposit disposition.

## 6. Ordinary Settlement

Ordinary Settlement requires:

- final Provider Usage Report;
- Consumer acknowledgement;
- valid Invoice;
- matching Session and policy references;
- sufficient Deposit;
- no unresolved Confirmed Mismatch.

Ordinary Settlement is preferred whenever both parties remain available.

Forced Settlement SHALL not be used merely to bypass ordinary acknowledgement.

## 7. Forced Settlement

Forced Settlement is a deterministic Ledger procedure used when ordinary Settlement cannot complete.

It MAY be triggered by:

- participant disappearance;
- acknowledgement timeout;
- Usage Report timeout;
- Session timeout;
- Deposit exhaustion;
- confirmed accounting mismatch;
- Runtime failure;
- Endpoint withdrawal during an active Session;
- Provider force close;
- Consumer force close;
- unrecoverable state divergence;
- expired recovery window;
- prolonged Consensus interruption followed by recovery.

Forced Settlement SHALL use `SESSION_FORCE_SETTLE` as defined by `RFC-0059`.

## 8. Failure Classification

Every abnormal termination SHALL receive one primary Failure Class.

Initial classes are:

- `CONSUMER_DISCONNECTED`
- `PROVIDER_DISCONNECTED`
- `RUNTIME_FAILURE`
- `ENDPOINT_FAILURE`
- `UPSTREAM_PROXY_FAILURE`
- `ACCOUNTING_MISMATCH`
- `USAGE_REPORT_TIMEOUT`
- `ACKNOWLEDGEMENT_TIMEOUT`
- `DEPOSIT_EXHAUSTED`
- `SESSION_TIMEOUT`
- `IDLE_TIMEOUT`
- `CONSUMER_FORCE_CLOSE`
- `PROVIDER_FORCE_CLOSE`
- `PROTOCOL_INCOMPATIBILITY`
- `CONSENSUS_INTERRUPTION`
- `STATE_RECOVERY_FAILURE`
- `UNKNOWN_FAILURE`

Additional secondary causes MAY be recorded.

## 9. Failure Attribution

Failure Class and fault attribution are separate concepts.

Attribution values are:

- `CONSUMER_AT_FAULT`
- `PROVIDER_AT_FAULT`
- `BOTH_AT_FAULT`
- `EXTERNAL_FAILURE`
- `PROTOCOL_FAILURE`
- `INCONCLUSIVE`

A failure SHALL NOT automatically assign fault.

Example:

`PROVIDER_DISCONNECTED`

may result from:

- Provider negligence;
- temporary ISP outage;
- Hypervisor crash;
- regional network failure.

Evidence quality determines attribution.

## 10. Session Evidence

Each participant SHALL persist sufficient Session evidence to recover or force-settle the Session.

Required evidence includes:

- Session ID;
- Endpoint ID;
- accepted Endpoint version;
- accepted Session Policy;
- accepted Pricing Policy;
- accepted Accounting Contract;
- Deposit references;
- Usage Report chain;
- Usage acknowledgement chain;
- request identifiers;
- request and response hashes;
- failure timestamps;
- transport state;
- last known participant messages;
- Runtime execution status where available.

Evidence SHALL be signed where required by its originating participant.

## 11. Evidence Levels

Failure evidence is classified as:

Cryptographic Evidence

Examples:

- signed conflicting Usage Reports;
- signed acknowledgement;
- signed cancellation;
- finalized Ledger operation;
- signed Provider termination message.

Reproducible Evidence

Examples:

- invalid artifact hash;
- deterministic token mismatch;
- invalid report sequence;
- exceeded accepted maximum charge.

Observational Evidence

Examples:

- connection timeout;
- unavailable endpoint;
- missing response;
- local Runtime error.

Cryptographic evidence has greater protocol weight than observational evidence.

## 12. Last Accepted Checkpoint

The Last Accepted Checkpoint is the highest Usage Report sequence acknowledged by the Consumer.

An acknowledgement MAY have status:

- `VERIFIED`;
- `ACCEPTED_UNVERIFIED`;
- `STATISTICALLY_PLAUSIBLE`.

The Last Accepted Checkpoint defines:

- uncontested cumulative usage;
- minimum Provider payment;
- maximum ordinary refund before additional policy charges.

It SHALL be the default forced-settlement baseline.

## 13. Unacknowledged Usage

Usage occurring after the Last Accepted Checkpoint is unacknowledged.

Unacknowledged usage SHALL NOT automatically be paid.

It MAY be paid only if the accepted Session Policy defines a deterministic rule supported by evidence.

Examples include:

- fixed request fee authorized before execution;
- completed fixed-price request with a valid result hash;
- permitted maximum unacknowledged exposure;
- billable idle interval acknowledged by Session events.

## 14. Maximum Unacknowledged Exposure

Every Session SHALL define a maximum unacknowledged exposure.

```yaml
maximum_unacknowledged_exposure:
  amount_q:
  unit_limit:
  checkpoint_interval:
```

The Provider SHALL pause new work before this exposure can be exceeded.

Failure to enforce the limit SHALL make excess usage Provider risk.

The Consumer SHALL not be charged above the accepted limit without a later acknowledgement.

## 15. Pending Request State

Each request SHALL have one of the following execution states:

- `CREATED`
- `ACCEPTED`
- `EXECUTING`
- `RESULT_AVAILABLE`
- `DELIVERED`
- `ACKNOWLEDGED`
- `FAILED`
- `CANCELLED`
- `UNKNOWN`

Only request states supported by protocol evidence SHALL affect Settlement.

## 16. Completed Request

A request is considered completed when the Capability-specific completion condition is satisfied.

Examples include:

LLM

- final response or declared finish event delivered.

Image

- valid artifact delivered with matching hash.

STT

- transcription delivered.

TTS

- valid audio artifact delivered.

Fixed-Price Agent Task

- declared completion event and required output delivered.

Internal Provider computation alone does not establish completion.

## 17. Partial Result

A partial result MAY be billable only if:

- the Endpoint advertised partial-result billing;
- the Consumer accepted that policy;
- the delivered portion is independently identifiable;
- the billing method is deterministic;
- the amount does not exceed the Deposit.

Without an accepted partial-result policy, an incomplete request SHALL not receive the full completion fee.

## 18. Streaming Failure

If a streaming response fails before completion:

- delivered output units MAY be billable when observable or accepted;
- undelivered output SHALL not be billed;
- fixed completion fees SHALL follow the failure-pricing policy;
- duplicate retransmitted chunks SHALL not be billed twice.

The Provider SHALL publish the final delivered-output hash where practical.

## 19. Consumer Disconnection

A Consumer is considered disconnected when:

- the active transport is lost;
- reconnect attempts fail;
- the Consumer does not respond within the configured timeout.

Consumer disconnection SHALL first move the Session to:

`RECOVERING`

The Provider SHALL not immediately force-settle unless the recovery timeout expires or policy permits earlier closure.

## 20. Consumer Recovery Window

The Session Policy SHALL define:

```yaml
consumer_recovery:
  reconnect_timeout:
  acknowledgement_timeout:
  maximum_provider_hold_time:
```

During the recovery window:

- the Session slot MAY remain reserved;
- idle or reservation charges MAY apply if published;
- new execution SHALL not continue beyond authorized exposure;
- the Provider SHALL preserve Session state.

## 21. Consumer Does Not Return

If the Consumer does not return before the recovery deadline:

1. The Provider identifies the Last Accepted Checkpoint.
2. The Provider publishes a final failure record.
3. The Session enters `FORCE_CLOSING`.
4. `SESSION_FORCE_SETTLE` is submitted.
5. Accepted usage is paid.
6. valid policy-based timeout or reservation charges MAY be paid;
7. remaining Deposit is refunded.

Consumer disappearance SHALL not permit the Provider to claim arbitrary unacknowledged usage.

## 22. Consumer Refuses Acknowledgement

A Consumer may remain connected but refuse to acknowledge a valid Usage Report.

The Provider SHALL:

- pause additional work at the exposure limit;
- resend the same signed Usage Report;
- provide required verification metadata;
- start the acknowledgement timeout.

After timeout, the Provider MAY request Forced Settlement.

## 23. Acknowledgement Timeout Settlement

When the Consumer fails to acknowledge:

- the Last Accepted Checkpoint remains uncontested;
- later deterministic or observable usage MAY be included only under explicit Session Policy;
- Provider-Metered or Proxy-Opaque unacknowledged usage SHALL not automatically be paid;
- a refusal event is recorded.

Repeated unexplained acknowledgement refusal MAY affect Consumer Reputation.

## 24. Provider Disconnection

A Provider is considered disconnected when:

- Endpoint transport fails;
- Provider Hypervisor becomes unreachable;
- Runtime disconnects and no replacement Runtime resumes the Session;
- Provider does not return before the recovery deadline.

The Consumer SHALL preserve:

- last Provider Usage Report;
- last acknowledgement;
- request evidence;
- received partial results.

## 25. Provider Recovery Window

The Session Policy SHALL define:

```yaml
provider_recovery:
  reconnect_timeout:
  runtime_restart_timeout:
  session_resume_supported:
```

During this window:

- the Session enters `RECOVERING`;
- Consumer requests SHOULD pause;
- Provider MAY restore the Runtime;
- both parties exchange checkpoint hashes before resuming.

## 26. Provider Does Not Return

If the Provider does not recover:

1. The Consumer submits Provider-unavailable evidence.
2. The Session enters `FORCE_CLOSING`.
3. Accepted completed usage is paid.
4. uncompleted request charges follow failure policy;
5. unused Deposit is refunded;
6. Provider reliability metrics are updated.

The Consumer SHALL not receive already completed accepted work for free merely because the Provider later disappeared.

## 27. Provider Missing Final Usage Report

If the Provider delivered a result but failed to issue the required final Usage Report:

- the Consumer MAY close the Session;
- previously accepted usage is payable;
- the current request MAY be payable only under fixed-price or observable rules;
- unverifiable Provider-Metered usage is not automatically payable;
- the missing report affects Provider Reputation.

The Provider bears the accounting risk of failing to report required usage.

## 28. Runtime Failure

A Capability Runtime failure does not immediately terminate the Hypervisor.

The Runtime-side recovery and restart message flow is defined by `RFC-0054`.

The Provider Hypervisor SHALL attempt:

- Runtime restart;
- Runtime replacement;
- Session context restoration;
- checkpoint reconciliation.

If recovery succeeds within the Runtime recovery timeout, the Session MAY resume.

Where a Runtime is implemented by a Provider Plugin Adapter, the Hypervisor MAY
also reconcile Plugin management state under RFC-0056. That reconciliation does
not replace the Runtime recovery state required by RFC-0054.

The Runtime recovery snapshot SHOULD identify Runtime ID, current Dispatcher
Route Generation, Runtime Generation, Runtime Configuration Hash, State
Generation, active Request mappings, stream position and Usage chain head.

A Route Generation change alone MAY resume the same compatible Runtime lineage.
A Runtime Generation, Configuration Hash or State Generation mismatch SHALL
require explicit migration evidence or fail recovery. Plugin Manager
reconciliation is management evidence and cannot independently resume or settle
a Session.

The Hypervisor SHALL issue an explicit RFC-0054 Recovery Plan. Existing work
may continue, output or final Results/Usage may be redelivered, idempotent work
may restart, or work may be cancelled/failed. Missing acknowledgments alone do
not authorize re-execution. `UNRECOVERABLE` Runtime terminal state enters this
RFC's failure and Forced Settlement evaluation.
The snapshot is evidence for the Session recovery decision, not authority to
alter accepted Session terms.

## 29. Runtime Replacement

A replacement Runtime MAY resume a Session only when:

- it supports the same Capability version;
- it supports the accepted Accounting Contract;
- it receives the correct Session context;
- the Usage Report chain remains valid;
- the Consumer accepts or protocol policy permits transparent replacement.

A Runtime replacement SHALL not reset usage or pricing.

A Plugin Manager restart alone SHALL NOT increment Session identity or move a
Session. A material Runtime Adapter replacement requires Runtime reauthorization,
an explicit Route Generation transition and compatibility checks under RFC-0054.

## 30. Runtime Recovery Failure

If the Runtime cannot recover:

- active request becomes failed or partial;
- the Session enters `PROVIDER_UNAVAILABLE` or `RUNTIME_FAILURE`;
- Forced Settlement uses the Last Accepted Checkpoint;
- partial-result policy MAY apply;
- remaining Deposit is refunded.

## 31. Endpoint Withdrawal

Withdrawing an Endpoint prevents new Sessions.

It SHALL NOT silently terminate existing Sessions.

Existing Sessions SHALL:

- continue until ordinary close;
- enter graceful shutdown;
- or follow published Endpoint withdrawal policy.

The Provider MAY reject new requests while allowing current work to finish.

## 32. Provider Graceful Close

The Provider MAY request graceful Session closure.

Graceful closure means:

- no new requests are accepted;
- the current accepted request MAY finish;
- final Usage Report is published;
- ordinary Settlement is attempted.

Graceful closure does not incur a Provider penalty.

## 33. Provider Force Close

A Provider MAY force-close a Session before the ordinary termination condition.

Provider Force Close SHALL identify:

- reason;
- current request state;
- Last Accepted Checkpoint;
- whether graceful completion was attempted;
- affected Session Policy rule.

## 34. Provider Force Close Without Fault

The Provider MAY close without penalty when:

- Consumer exceeded idle timeout;
- Deposit is insufficient;
- Consumer violated protocol;
- Session maximum duration expired;
- accepted security policy was violated;
- Consumer failed required acknowledgement;
- Endpoint entered emergency maintenance after finishing current work.

Only supported charges may be paid.

## 35. Provider Force Close With Active Work

If the Provider force-closes during active work without Consumer fault:

- uncompleted work SHALL not receive a full completion fee;
- Provider MAY lose the base fee for the affected request;
- the Session's Provider earnings MAY be reduced according to policy;
- remaining Deposit SHALL be refunded;
- Provider Force Close metrics SHALL be updated.

A future economic specification MAY define an additional Provider penalty.

## 36. Consumer Graceful Close

The Consumer MAY request ordinary Session closure when no request is active.

The Provider SHALL:

- publish the final Usage Report;
- stop idle charging at the appropriate event;
- generate the Invoice;
- proceed to ordinary Settlement.

## 37. Consumer Force Close

A Consumer MAY force-close when:

- Provider violates protocol;
- Provider exceeds accepted limits;
- Provider fails to report usage;
- Provider becomes unavailable;
- result delivery fails;
- Consumer chooses to abandon the Session.

Consumer Force Close does not erase accepted usage.

## 38. Consumer Abandons Active Work

If the Consumer cancels an already accepted active request:

- cancellation rules from the accepted Session Policy apply;
- fixed cancellation fee MAY apply;
- observable delivered work MAY be billable;
- full completion fee SHALL not apply unless the request completed before cancellation;
- Provider SHALL stop work at the nearest safe boundary.

## 39. Idle Timeout

The Session Policy SHALL define:

```yaml
idle_policy:
  grace_period:
  billing_interval:
  price:
  provider_close_after:
```

Idle time begins from a protocol-defined event.

The Provider MAY force-close after the published idle timeout.

Idle fees SHALL not exceed the remaining Deposit.

## 40. Session Maximum Duration

Every public Endpoint SHOULD define a maximum Session duration.

At the limit:

- no new requests are accepted;
- active work MAY complete if policy permits;
- final Usage Reporting begins;
- ordinary or Forced Settlement follows.

The Consumer MAY extend the Session only through a permitted policy or new Session.

## 41. Deposit Exhaustion

A Session enters `DEPOSIT_EXHAUSTED` when remaining Deposit cannot cover the next permitted charge.

The Provider SHALL:

- stop new work;
- pause active work at a safe boundary where possible;
- request Deposit extension;
- start the extension timeout.

## 42. Deposit Extension Timeout

If no extension finalizes before the timeout:

- the Session enters `FORCE_CLOSING`;
- accepted usage is paid;
- no additional work is billed;
- any residual Deposit is refunded.

The Provider SHALL not rely on an unfinalized Deposit extension.

## 43. Deposit Exhaustion During Streaming

The Provider SHOULD estimate cost before beginning generation.

If a response reaches the permitted budget limit:

- generation SHOULD stop cleanly;
- the response SHALL indicate budget termination;
- delivered output MAY be billed;
- output beyond the budget SHALL not be generated intentionally.

If the Provider exceeds the accepted maximum, excess cost is Provider risk.

## 44. Accounting Mismatch

A Confirmed Accounting Mismatch moves the Session to:

`ACCOUNTING_MISMATCH`

No new billable work SHALL begin.

Both parties SHALL preserve:

- conflicting Usage Reports;
- acknowledgements;
- Accounting Contract;
- request and response hashes;
- measurement evidence.

## 45. Mismatch Settlement

The default Mismatch Settlement is:

`Provider payment = value of Last Accepted Checkpoint`

plus any independently proven and explicitly authorized fixed or observable charge.

Disputed Provider-Metered or Proxy-Opaque usage after the checkpoint SHALL not be paid automatically.

The unused Deposit SHALL be refunded.

## 46. Mismatch Attribution

Mismatch attribution MAY be:

- Provider at fault;
- Consumer at fault;
- protocol incompatibility;
- both inconsistent;
- inconclusive.

Attribution SHALL rely on objective evidence where possible.

A single inconclusive mismatch SHALL not trigger severe economic punishment.

Repeated patterns affect Reputation according to `RFC-0041` and `RFC-0051`.

## 47. Conflicting Signed Records

If one participant signs two different Usage Records for the same Session sequence:

- both records form objective conflicting evidence;
- the Session SHALL terminate;
- the signer MAY be suspended;
- a Penalty Operation MAY be authorized;
- the valid baseline falls back to the previous accepted sequence.

Conflicting signed records are stronger evidence than ordinary accounting disagreement.

## 48. Proxy Endpoint Failure

A Proxy Endpoint remains responsible for upstream failures.

Possible upstream failures include:

- `UPSTREAM_AUTH_EXPIRED`;
- `UPSTREAM_RATE_LIMITED`;
- `UPSTREAM_QUOTA_EXHAUSTED`;
- `UPSTREAM_UNAVAILABLE`;
- `UPSTREAM_TASK_CANCELLED`;
- `UPSTREAM_INVALID_RESPONSE`;
- `UPSTREAM_PROTOCOL_CHANGED`;
- `UPSTREAM_UNKNOWN_FAILURE`.

The upstream service has no direct obligation to the Consumer.

## 49. Proxy Request Failure Pricing

A Proxy Endpoint SHALL publish failure-pricing rules.

Possible policies include:

- `NO_CHARGE_ON_FAILURE`
- `BASE_FEE_ONLY`
- `OBSERVED_TIME_ONLY`
- `PARTIAL_RESULT_CHARGE`
- `FIXED_ATTEMPT_FEE`

The policy SHALL be accepted before execution.

An upstream failure SHALL not permit an undisclosed charge.

## 50. Proxy-Opaque Forced Settlement

For `PROXY_OPAQUE` accounting:

- estimated tokens are never authoritative;
- only fixed or observable accepted units are payable;
- maximum request charge remains binding;
- unknown upstream usage remains unknown;
- upstream failure cannot generate a token-based debt.

## 51. Consensus Interruption

A Consensus interruption may prevent:

- Deposit extension finalization;
- ordinary Settlement finalization;
- new Session Open operations;
- Forced Settlement finalization.

Existing off-chain execution MAY continue only within already finalized economic authorization.

## 52. Operation During Consensus Halt

During Consensus halt:

- Providers SHALL not rely on unfinalized Deposits;
- Providers SHALL not exceed existing locked authorization;
- Session policies MAY require execution pause;
- Usage Reporting continues locally;
- final Settlement remains pending.

A long Consensus halt MAY trigger Session pause or graceful closure.

## 53. Consensus Recovery

After Consensus resumes:

- pending operations are resubmitted safely;
- finalized Deposit state is rechecked;
- duplicate Settlement is prevented by Session ID;
- the latest valid Session evidence is used;
- expired Session deadlines are evaluated using finalized protocol time.

Consensus downtime alone SHALL not erase completed accepted usage.

## 54. Local Clock Disagreement

Local clocks are not authoritative for economic state.

Session transport timeouts MAY use local monotonic clocks operationally.

Ledger consequences SHALL use:

- finalized block time;
- block height;
- Epoch;
- signed event timestamps where explicitly permitted.

## 55. Recovery Handshake

After reconnect, both Hypervisors SHALL exchange:

```yaml
session_recovery:
  session_id:
  local_state:
  last_local_usage_report_hash:
  last_remote_usage_report_hash:
  last_acknowledged_sequence:
  active_request_id:
  active_request_state:
  pricing_policy_hash:
  accounting_contract_hash:
  signature:
```

The Session may resume only if the state chains are compatible.

## 56. Compatible Recovery

Recovery is compatible when:

- Session IDs match;
- policy hashes match;
- one report chain extends the other validly;
- acknowledgement sequence is consistent;
- no conflicting signed record exists;
- Deposit remains sufficient;
- Session has not already settled.

The parties SHALL adopt the highest mutually consistent checkpoint.

## 57. Incompatible Recovery

Recovery is incompatible when:

- policy hashes differ;
- report histories conflict;
- one party claims an unknown accepted checkpoint;
- the Session is terminal on one side;
- signed records conflict;
- execution state cannot be reconstructed.

The Session SHALL enter `FORCE_CLOSING`.

## 58. Recovery Attempts

The Session Policy MAY define:

- reconnect interval;
- maximum retry count;
- total recovery window;
- Runtime restart allowance;
- Session reservation charges during recovery.

Retry limits prevent indefinite resource reservation.

## 59. Forced Settlement Initiator

Either participant MAY submit `SESSION_FORCE_SETTLE`.

The protocol MAY also generate Forced Settlement after a finalized timeout.

The initiator does not control the outcome.

The State Machine derives Settlement from:

- canonical Session state;
- accepted policies;
- signed evidence;
- finalized deadlines;
- Deposit state.

## 60. Forced Settlement Operation

`SESSION_FORCE_SETTLE` SHALL include:

```yaml
session_force_settle:
  session_id:
  failure_class:
  requested_at:
  last_accepted_checkpoint:
  provider_usage_report_hash:
  consumer_ack_hash:
  failure_evidence_root:
  requested_payment:
  requested_refund:
  attribution_claim:
  initiator_signature:
```

Requested values are claims.

The State Machine SHALL independently calculate final values.

## 61. Forced Settlement Preconditions

The operation is valid only when:

- Session exists;
- Session is not already terminal;
- ordinary Settlement is unavailable or inappropriate;
- required timeout has elapsed or immediate failure evidence exists;
- referenced evidence is valid;
- policy hashes match the Session;
- Deposit remains locked.

## 62. Forced Settlement Calculation

The default calculation is:

`AcceptedUsagePayment = Pricing(LastAcceptedCheckpoint)`

Additional payable amounts MAY include:

- accepted fixed request fees;
- observable delivered usage;
- valid idle fees;
- valid reservation fees;
- valid cancellation fees;
- valid timeout charges.

Then:

`ProviderPayment = min(AcceptedUsagePayment + AdditionalAuthorizedCharges, LockedDeposit)`

`ConsumerRefund = LockedDeposit - ProviderPayment - NetworkFees - ApplicableFinalizedPenalties`

All calculations SHALL use deterministic fixed-point arithmetic.

## 63. Payment Priority

When the Deposit is insufficient, payment priority SHALL be:

1. finalized Network Fees;
2. previously acknowledged Provider usage;
3. explicitly accepted fixed charges;
4. observable post-checkpoint usage;
5. other authorized charges;
6. penalties if permitted from the same Deposit;
7. Consumer refund.

Unverified claims have no priority.

## 64. Forced Settlement Result

The finalized result SHALL include:

```yaml
forced_settlement_result:
  session_id:
  terminal_state:
  failure_class:
  attribution:
  provider_payment:
  consumer_refund:
  network_fees:
  penalties:
  last_accepted_sequence:
  paid_usage_summary:
  unpaid_claim_summary:
  evidence_root:
```

The result SHALL be immutable.

## 65. Duplicate Settlement Protection

Only one terminal Settlement operation may apply to a Session.

If ordinary Settlement finalizes first:

- later Forced Settlement becomes `NO_OP` or `REJECTED`.

If Forced Settlement finalizes first:

- later ordinary Settlement is rejected.

Session ID is the replay-protection key.

## 66. Settlement Challenge Window

The MVP SHOULD avoid subjective post-Settlement reversal.

Before Forced Settlement finalization, the protocol MAY define a short evidence window during which the counterparty can submit:

- a newer accepted checkpoint;
- conflicting signed evidence;
- proof that timeout conditions were not met;
- proof that ordinary Settlement already completed.

The window SHALL have deterministic duration.

## 67. No Arbitrary Arbitration

The protocol SHALL not require a human arbitrator to decide ordinary failure Settlement.

Human or community review MAY affect:

- future Reputation;
- Validator evaluation;
- protocol bug reporting;
- exceptional governance action.

It SHALL not ordinarily rewrite finalized Session payments.

## 68. Reputation Events

Failure handling MAY emit Reputation events including:

- Consumer Acknowledgement Timeout;
- Provider Usage Report Timeout;
- Provider Unavailability;
- Consumer Unavailability;
- Force Close;
- Deposit Exhaustion;
- Runtime Failure;
- Proxy Failure;
- Confirmed Accounting Mismatch;
- Successful Recovery;
- Conflicting Signed Evidence.

Reputation impact is calculated by `RFC-0041` rules.

## 69. Isolated Failure

One isolated failure SHOULD have limited Reputation impact when:

- evidence is inconclusive;
- recovery was attempted;
- economic exposure was limited;
- the participant otherwise behaves reliably.

Repeated similar failures carry increasing weight.

## 70. Successful Recovery

Successful Session recovery SHOULD positively affect resilience metrics.

Relevant metrics MAY include:

- recovery success rate;
- recovery duration;
- checkpoint consistency;
- Runtime restart success;
- Settlement completion after recovery.

Recovery success does not erase the underlying availability event.

## 71. Fault-Neutral Events

The following MAY be classified as external or fault-neutral:

- regional network failure;
- Consensus halt;
- upstream outage affecting many operators;
- protocol-version incompatibility caused by scheduled migration;
- verified infrastructure disaster.

Fault-neutral events may reduce current Health without strongly reducing long-term Reputation.

## 72. Penalties

Economic penalties require stronger evidence than ordinary failure.

Possible penalty-triggering behavior includes:

- conflicting signed Usage Reports;
- knowingly billing above maximum limits;
- fabricated acknowledgements;
- duplicate Settlement attempts;
- deliberate evidence manipulation;
- repeated malicious force-close behavior.

Ordinary downtime alone SHALL not automatically cause slashing.

## 73. Session Privacy

Failure evidence SHALL minimize disclosure of Session content.

Preferred evidence includes:

- hashes;
- Usage totals;
- timestamps;
- sequence numbers;
- policy references;
- artifact identifiers;
- signed status messages.

Raw prompts, outputs and private artifacts SHALL remain off-chain unless explicitly required and authorized.

## 74. Registry Storage

Registry Services MAY store:

- complete failure reports;
- Usage Report chains;
- acknowledgement chains;
- recovery handshakes;
- large evidence artifacts.

The Ledger SHALL store only necessary commitments and economic outcomes.

## 75. Ledger Commitments

The Ledger SHALL record at minimum:

- Session ID;
- terminal state;
- failure class;
- attribution state;
- Last Accepted Checkpoint;
- Provider payment;
- Consumer refund;
- fees;
- penalties;
- failure-evidence root;
- Forced Settlement operation ID.

## 76. Failure Report

A full Session Failure Report SHOULD contain:

```yaml
session_failure_report:
  report_id:
  session_id:
  failure_class:
  detected_at:
  reporter:
  session_state:
  active_request_state:
  last_accepted_checkpoint:
  policy_references:
  usage_evidence:
  transport_evidence:
  recovery_attempts:
  attribution_claim:
  summary:
  evidence_root:
  signature:
```

Failure Reports are immutable Registry objects.

## 77. Timeout Configuration

Every public Endpoint SHALL publish timeout parameters including:

- Session acceptance timeout;
- Consumer reconnect timeout;
- Provider reconnect timeout;
- Runtime recovery timeout;
- Usage Report timeout;
- acknowledgement timeout;
- Deposit extension timeout;
- idle timeout;
- forced-settlement evidence window.

Undefined infinite timeouts SHALL not be permitted for public Sessions.

## 78. Timeout Bounds

The protocol MAY define minimum and maximum timeout bounds.

This prevents policies such as:

`Acknowledgement timeout: 1 millisecond`

or:

`Provider may hold Deposit for 30 years`

Endpoint policies outside protocol bounds SHALL be rejected.

## 79. Capability-Specific Failure Rules

Capabilities MAY define additional failure behavior.

Examples:

Image Generation

- artifact completeness;
- corrupted output;
- image delivery failure.

Video Generation

- partial frame sequence;
- partial duration billing;
- encoding failure.

Agent Execution

- intermediate tool execution;
- partial task completion;
- workspace modifications;
- external side effects.

Capability rules SHALL not override core Deposit and evidence invariants.

## 80. External Side Effects

Agentic Capabilities may perform external actions.

Examples:

- modify a repository;
- send a message;
- create a file;
- invoke an external service.

The Session Policy SHALL define whether external side effects count as completed work.

Forced Settlement SHALL not attempt to reverse external systems.

The Provider SHALL report completed side effects before further execution where practical.

## 81. Irreversible Work

Some work may be irreversible even if result delivery fails.

Examples:

- submitted external transaction;
- sent email;
- changed repository;
- triggered deployment.

Such work MAY be billable only when:

- the side effect was explicitly authorized;
- completion evidence exists;
- the pricing policy defines the charge;
- the Consumer accepted the risk.

## 82. Multi-Request Sessions

Forced Settlement of a multi-request Session SHALL evaluate each request independently where evidence permits.

Completed acknowledged requests remain payable.

A failed final request SHALL not invalidate earlier completed work.

## 83. Session Reservation Charges

Exclusive Endpoint reservation MAY be billable during:

- active use;
- idle periods;
- recovery periods;
- temporary participant disconnection.

Reservation charging SHALL follow the accepted policy.

The Provider SHALL release the reserved slot after the maximum hold time.

## 84. Provider Slot Release

After terminal Session state:

- the Provider SHALL release all Session resources;
- idle charging stops;
- reservation charging stops;
- Runtime context MAY be archived or deleted;
- no further Usage Reports may increase the charge.

## 85. Consumer Resource Release

After terminal Settlement:

- Consumer local Session state MAY be archived;
- pending request retries SHALL stop;
- duplicate Deposit extensions SHALL not be submitted;
- the final Settlement result SHALL become authoritative.

## 86. Idempotency

The following actions SHALL be idempotent:

- recovery handshake;
- Session pause;
- final Usage Report resubmission;
- acknowledgement resubmission;
- failure report submission;
- Forced Settlement submission.

Resubmitting the same signed object SHALL not alter Settlement twice.

## 87. Concurrent Settlement Attempts

Both parties may submit competing Settlement operations.

Consensus ordering determines which valid operation executes first.

The first valid terminal Settlement consumes the Session terminal transition.

Later attempts SHALL not modify balances.

## 88. Protocol Bug Handling

If a Session cannot settle because of a confirmed protocol defect:

- the Session enters `UNRECOVERABLE`;
- funds remain locked until a versioned recovery rule activates;
- arbitrary manual balance edits are prohibited;
- an emergency protocol operation MAY resolve affected Sessions in a future upgrade.

The MVP SHOULD minimize such paths through exhaustive state-machine testing.

## 89. Emergency Settlement Batch

A future protocol version MAY define an emergency deterministic batch operation for Sessions affected by one protocol defect.

Such an operation SHALL:

- identify affected Session IDs;
- use one published calculation rule;
- be activated by protocol upgrade;
- preserve complete audit history;
- not permit selective operator discretion.

## 90. Metrics

The network SHOULD publish aggregate metrics including:

- ordinary Settlement rate;
- Forced Settlement rate;
- recovery success rate;
- Consumer disappearance rate;
- Provider disappearance rate;
- Runtime failure rate;
- Proxy failure rate;
- acknowledgement timeout rate;
- Usage Report timeout rate;
- Deposit exhaustion rate;
- mismatch rate;
- average forced-settlement delay;
- unpaid disputed usage.

These metrics support protocol improvement and Marketplace decisions.

## 91. MVP Requirements

The MVP SHALL implement:

- Session failure classifications;
- Last Accepted Checkpoint;
- recovery state;
- Consumer and Provider reconnect windows;
- Runtime recovery;
- Deposit exhaustion handling;
- idle timeout;
- Session maximum duration;
- acknowledgement timeout;
- Usage Report timeout;
- accounting mismatch termination;
- Provider and Consumer force close;
- deterministic Forced Settlement;
- duplicate Settlement protection;
- Failure Reports;
- Ledger evidence commitments;
- Reputation event generation;
- Proxy-Opaque failure policy;
- Consensus interruption handling.

## 92. Deferred Features

The MVP MAY postpone:

- subjective arbitration;
- human dispute panels;
- reversible finalized Settlement;
- insurance pools;
- third-party Session guarantors;
- zero-knowledge failure evidence;
- multi-party Sessions;
- cross-chain Settlement;
- automatic compensation beyond the locked Deposit;
- complex external side-effect rollback.

## 93. Open Protocol Parameters

The following remain versioned protocol parameters:

- Consumer reconnect timeout;
- Provider reconnect timeout;
- Runtime recovery timeout;
- acknowledgement timeout;
- Usage Report timeout;
- Deposit extension timeout;
- Session acceptance timeout;
- minimum and maximum idle timeout;
- maximum recovery hold time;
- forced-settlement evidence window;
- maximum unacknowledged exposure;
- partial-result rules;
- cancellation charges;
- failure-pricing bounds;
- Reputation event weights;
- penalty thresholds.

## 94. Economic Invariants

For every terminal Session:

`Provider Payment + Consumer Refund + Network Fees + Finalized Penalties = Locked Session Deposit`

`Provider Payment <= Accepted and Authorized Usage`

`Total Distribution <= Locked Deposit`

`One Session = One Terminal Settlement`

`Unverified Claims != Automatic Payment`

## 95. Recovery Invariants

- Recovery never resets accepted usage.
- Recovery never changes the accepted Pricing Policy.
- Recovery never changes the accepted Accounting Contract.
- Runtime replacement does not reset Session accounting.
- A conflicting signed history prevents Session resumption.
- Terminal Sessions cannot be recovered or reopened.

## 96. Forced Settlement Invariants

- The Last Accepted Checkpoint is the default uncontested baseline.
- Forced Settlement is deterministic.
- The initiator does not choose the final amount.
- Disappearing does not erase accepted obligations.
- Provider disappearance does not authorize free use of completed work.
- Consumer disappearance does not authorize arbitrary Provider billing.
- Unknown Proxy usage remains unknown.
- Maximum accepted charges remain binding.
- Unused Deposit returns to the Consumer.
- Every Forced Settlement is auditable.

## 97. Design Invariants

- Every Session eventually reaches a terminal state.
- Ordinary Settlement is preferred.
- Forced Settlement pays only evidence-backed amounts.
- Both participants preserve Session evidence.
- Temporary disconnection triggers recovery before final termination.
- New economic exposure stops when accounting or Deposit becomes unsafe.
- Completed accepted work remains payable.
- Incomplete work is paid only according to accepted policy.
- Provider-Metered and Proxy-Opaque claims require prior Consumer acceptance.
- Forced Settlement cannot distribute more than the locked Deposit.
- Fault attribution is separate from failure classification.
- Ordinary failures do not automatically cause slashing.
- Finalized Settlement is replay-protected and irreversible under ordinary protocol operation.

## RFC-0051 Incomplete Usage Handling

Forced Settlement uses the last accepted Usage chain head and the accepted
Accounting Contract fallback. Conflicting or out-of-sequence reports remain
evidence but do not extend payable Usage until resolved. `UNAVAILABLE` is never
converted to zero or an estimate. Fixed fallback, observable fallback, partial
charge, zero variable component or review may apply only when accepted before
execution. No result may exceed Request ceiling, Session exposure or Deposit.
