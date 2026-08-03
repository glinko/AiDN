# RFC-0037 AiDN Settlement and Escrow Engine

Status: `Draft`

Version: `0.3`

Revision note: Settlement moves Q only from accepted terms and committed
execution evidence. It evaluates each Request before Session aggregation,
separates Endpoint Payment from Network Fees, supports bounded partial
finalization and never performs subjective Result-quality judgment.

Supersedes:

- `RFC-0037 Version 0.2`

Depends on:

- `RFC-0016 Wallet and Identity`
- `RFC-0036 AiDN Ledger State Machine`
- `ECO-0000 Economic Principles`

Extended by:

- `RFC-0041 Reputation Profile Engine`
- `RFC-0042 AiDN Hypervisor Network Protocol and Dispatcher Architecture`
- `RFC-0044 AiDN Session Lifecycle, Execution and Settlement Protocol`
- `RFC-0045 AiDN Capability Architecture`
- `RFC-0048 Epoch Engine`
- `RFC-0049 Distributed Marketplace and Endpoint Advertisement Registry`
- `RFC-0051 Usage Reporting, Accounting Evidence and Verification Protocol`
- `RFC-0053 AiDN Capability Runtime Specification`
- `RFC-0054 AiDN Capability Runtime Protocol`
- `RFC-0058 Participant Eligibility and Sybil Resistance`
- `RFC-0059 Ledger Operation Catalog`
- `RFC-0060 Session Failure, Recovery and Forced Settlement`
- `RFC-0063 Proxy Endpoint Protocol`
- `RFC-0064 Validation Assignment, Concealed Session and Escrow Protocol`
- `RFC-0066 Protocol Upgrade and Emergency Recovery`
- `RFC-0067 Protocol Governance and Authorization Policy`

## 1. Purpose

The Settlement and Escrow Engine converts an accepted Session agreement and
its execution evidence into deterministic economic effects:

```text
Session Contract + Accepted Amendments
+ Request terminal states + Usage chain heads
+ Checkpoints + Failure/Cancellation policies
-> Endpoint Payment + Consumer Refund + Network Fees + Dispute Reserve
```

It defines Session Funding Accounts, Request-first charge evaluation,
cooperative and forced settlement, bounded disputes, partial finalization,
corrections, finality, privacy commitments and Ledger transitions.

## 2. Non-Responsibilities

Settlement SHALL NOT create or change price, Accounting Contract, charge
ceiling, maximum Session charge, beneficiary, failure policy, cancellation
policy or funding obligation. All are accepted before execution.

Settlement SHALL NOT decide whether text is intelligent, an image is
attractive, a model is useful or an Endpoint deserves Reputation. Subjective
quality belongs to Validation, Reputation, Consumer feedback and explicit
objective dispute terms.

A Usage Report is evidence, not payment. Upstream Provider cost is the Endpoint
operator's private business cost and SHALL NOT replace Consumer-facing terms.

## 3. Terminology

The normative term is `Endpoint Payment`: payment for the Consumer-facing
Endpoint service to an `endpoint_payment_beneficiary`. `Provider Payment` is
deprecated because Provider identifies internal systems such as Ollama, vLLM
or an upstream API.

The Consumer refund is paid to the pre-bound
`consumer_refund_beneficiary`. Later Advertisement or Endpoint changes SHALL
NOT redirect either beneficiary for an accepted Session.

## 4. Integer Accounting

Canonical Settlement uses integer smallest units named `q_atoms`. Binary
floating-point arithmetic SHALL NOT be used for canonical economic effects.
Unit transformations and rounding are versioned and deterministic.

Each Request and Session remains bounded:

```text
FinalRequestCharge <= RequestChargeCeiling
FinalEndpointPayment <= MaximumSessionCharge <= EndpointPaymentReserve
```

Execution cost above either accepted ceiling is `EndpointAbsorbedAmount` and
does not expand Consumer liability.

## 5. Session Funding Account

```yaml
session_funding_account:
  session_id:
  funding_class:
  consumer_funding_account:
  endpoint_payment_beneficiary:
  consumer_refund_beneficiary:
  total_locked_amount_q_atoms:
  endpoint_payment_reserve_q_atoms:
  network_fee_reserve_q_atoms:
  active_dispute_reserve_q_atoms:
  released_to_endpoint_q_atoms:
  consumer_payment_refund_q_atoms:
  consumed_network_fees_q_atoms:
  consumer_fee_refund_q_atoms:
  unsettled_payment_reserve_q_atoms:
  unsettled_fee_reserve_q_atoms:
  funding_state:
  funding_state_hash:
```

Funding classes are `ESCROW_PREPAID`, `TRUSTED_POSTPAID`, `FREE`, `INTERNAL`
and `VALIDATION`. Postpaid creates an obligation within an accepted credit
limit and SHALL NOT fabricate escrow.

The payment and fee reserves are independent. Every state satisfies:

```text
TotalLocked = EndpointPaymentReserve + NetworkFeeReserve
EndpointPaymentReserve = Released + PaymentRefund + Dispute + UnsettledPayment
NetworkFeeReserve = ConsumedFees + FeeRefund + UnsettledFees
```

Deposit extension cannot authorize new exposure before canonical funding. A
Deposit cannot be reduced below accepted and pending exposure, dispute reserve
and required fees. Session escrow is isolated from bonds, governance deposits,
Validator rewards and unrelated Sessions.

## 6. Settlement Input Set

Settlement evaluates an immutable, hash-bound Input Set:

```yaml
settlement_input_set:
  session_id:
  session_contract_hash:
  effective_terms_hash:
  endpoint_payment_beneficiary:
  consumer_refund_beneficiary:
  funding_state_reference:
  request_settlement_records:
  request_settlement_root:
  final_usage_chain_heads:
  usage_chain_root:
  accepted_checkpoint_references:
  checkpoint_root:
  dispute_references:
  failure_references:
  artifact_commitments:
  session_close_reference:
  settlement_input_root:
```

Effective terms are the initial Session Contract plus the ordered valid
Amendment chain. The `effective_terms_hash` in this Input Set SHALL equal the
current Session amendment-chain head; it is distinct from the immutable
`session_contract_hash`. Invalid, conflicting, cross-Session or retroactive
Amendments are excluded. Runtime Requests and terminal evidence that carry an
Effective Terms hash SHALL match this same head. Identical valid inputs SHALL
produce identical roots and amounts.

## 7. Request-First Evaluation

Every accepted Request produces one Request Settlement Record containing its
terminal state, exact Accounting Contract Hash, Final Usage Report identity,
raw charge, policy-adjusted charge, capped charge, absorbed excess, billable
and diagnostic components, limitations and dispute state.

Evaluation order is normative:

1. Verify Session and Accounting Contract identity.
2. Verify Request Charge Ceiling and terminal state.
3. Validate Final Usage chain and conflict state.
4. Select only declared billable dimensions.
5. Validate Availability, Authority and source requirements.
6. Apply deterministic transformations, unit prices and fixed components.
7. Apply retry rules and terminal-state policy.
8. Apply minimum charge where the accepted execution boundary permits it.
9. Apply Request Charge Ceiling.
10. Record Endpoint-absorbed excess and bounded dispute exposure.

Diagnostic dimensions cannot create liability. `UNAVAILABLE` is not zero.
Missing or incompatible required dimensions use only the accepted fallback:
fixed, observable, partial, zero-variable or dispute review. The Engine SHALL
not invent Usage or choose the report yielding the highest payment.

## 8. Terminal-State Policies

Terminal states are `COMPLETED`, `PARTIAL`, `CANCELLED`, `REJECTED`, `FAILED`,
`EXPIRED` and `UNRECOVERABLE`. A non-terminal accepted Request must recover,
cancel, become unrecoverable or enter Forced Settlement before final ordinary
Settlement.

Completed work uses ordinary calculation. Other states use the exact accepted
policy, such as no charge, accrued Usage, fixed charge, objective proportional
charge or dispute review. Cancellation does not erase already incurred
billable Usage. A rejected Request is normally zero unless a pre-accepted
admission fee exists.

## 9. Session Aggregation

After Request evaluation:

```text
GrossSessionCharge = sum(CappedRequestCharge) + DeclaredSessionFixedCharges
CappedSessionCharge = min(GrossSessionCharge, MaximumSessionCharge)
RemainingEndpointPayment = CappedSessionCharge - PreviouslyReleasedToEndpoint
```

Refunds cannot be negative. Previously released or refunded amounts are part of
conservation and cannot be paid twice. Atomic finalization credits the Endpoint
beneficiary, refunds the Consumer beneficiary, consumes Network Fees, retains a
bounded dispute reserve and closes the Funding Account in one Ledger effect.

## 10. Settlement Modes

Modes are `COOPERATIVE_FINAL`, `COOPERATIVE_ZERO`, `PARTIAL_UNDISPUTED`,
`FORCED`, `POSTPAID_OBLIGATION`, `VALIDATION_ZERO` and `CORRECTION`.

Cooperative Settlement uses one exact Settlement ID, Input Root and amount set.
Endpoint and Consumer signatures plus canonical bounds allow settlement without
publishing private prompts or Results.

## 11. Checkpoints

The latest valid accepted Checkpoint may establish a presumptively undisputed
exposure and Forced Settlement anchor. It references exact Usage chain heads,
Accounting Contract and bounded exposure.

A Checkpoint is not absolute finality. Forgery, wrong Session binding,
arithmetic error, Usage conflict or ceiling violation can invalidate it.
Subjective dissatisfaction cannot.

The MVP consensus profile represents a Checkpoint as an integer
`SessionUsageCheckpoint` with an explicit Usage Report hash, provider and
Consumer signatures, monotonic sequence, current exposure and remaining
deposit. `SESSION_CHECKPOINT_COMMIT` does not move funds; it only records a
bounded accepted exposure while the Funding Account remains locked. The
checkpoint binds to a finalized prior Funding operation and its exact state
hash. Float-based legacy accounting checkpoints remain compatibility data and
are not canonical consensus evidence.

## 12. Bounded Disputes and Partial Finalization

A dispute identifies exact Requests, Usage Reports, Checkpoints, evidence root
and a bounded amount. A small disputed component SHALL NOT automatically lock
the full Session reserve.

`PARTIAL_UNDISPUTED` may atomically pay the undisputed Endpoint amount, refund
the undisputed Consumer amount and consume undisputed fees while retaining only
the bounded dispute reserve. Later resolution accounts for every prior release.

The MVP consensus profile permits one typed dispute per Settlement. The dispute
must match the proposal's non-zero `disputed_amount_q_atoms` and
`dispute_reserve_q_atoms`, bind to the finalized proposal operation and include
its own dispute hash and Evidence Root. `SESSION_SETTLEMENT_PARTIAL_FINALIZE`
then credits only the proposal's undisputed Endpoint/Consumer amounts, consumes
the declared Network Fees and leaves the Funding Account in
`DISPUTE_RESERVED`. Ordinary `SESSION_SETTLEMENT_FINALIZE` cannot consume a
non-zero dispute reserve.

## 13. Forced Settlement

RFC-0060 extends Forced Settlement triggers, authorities and evidence rules.
Priority is Contract/funding verification, prior releases, accepted
Checkpoints, deterministic charges, objectively delivered partial work,
failure/cancellation policies, bounded dispute reserve and refund of unsupported
liability.

Missing Usage invokes the accepted fallback. Without a valid fallback, an
unsupported variable component is excluded or disputed; it is never guessed.
Consumer silence does not erase valid authorized exposure, and Endpoint silence
does not retain unsupported reserve.

For a multi-Request Session, Forced Settlement consumes the same ordered
Request Settlement Records used by ordinary evaluation. Its canonical
`SESSION_FORCE_SETTLE` authorization commits the Request Settlement Root,
Usage Chain Root, Checkpoint Root and per-Request evidence before applying the
bounded payment, refund and dispute reserve. A failed or conflicting Request
does not erase independently supported completed work.

## 14. Validation Settlement

An uncompensated concealed Validation Session uses `VALIDATION_ZERO`:

```text
EndpointPayment = 0
```

Operational Usage remains evidence. Validator reward and Validation Network
Fees are funded separately under RFC-0064 and economic specifications.
Validation status SHALL NOT be disclosed to the Runtime by Settlement.

## 15. Network Fees and Penalties

Network Fees are separate from Endpoint Payment and follow published operation
fee rules. Their burn, recycling or distribution is defined by ECO documents,
not improvised by Settlement.

Penalties and slashing are separate authorized Ledger effects requiring an
objective violation. Poor subjective output alone SHALL NOT create a penalty.

## 16. State Machine and Operations

Settlement states are `NOT_READY`, `READY`, `PROPOSED`, `ACCEPTED`, `DISPUTED`,
`PARTIALLY_FINALIZED`, `FORCED_PENDING`, `FINALIZATION_PENDING`, `FINALIZED`,
`CORRECTION_PENDING`, `CORRECTED`, `VOID` and `FAILED`.

RFC-0059 defines operations equivalent to:

- `SESSION_ESCROW_LOCK`
- `SESSION_ESCROW_EXTEND`
- `SESSION_ESCROW_RELEASE`
- `SESSION_CHECKPOINT_COMMIT`
- `SESSION_SETTLEMENT_READY_COMMIT`
- `SESSION_SETTLEMENT_PROPOSE`
- `SESSION_SETTLEMENT_ACCEPT`
- `SESSION_SETTLEMENT_DISPUTE`
- `SESSION_SETTLEMENT_PARTIAL_FINALIZE`
- `SESSION_FORCE_SETTLE`
- `SESSION_SETTLEMENT_FINALIZE`
- `SESSION_SETTLEMENT_CORRECT`

The typed MVP consensus profile covers readiness commitment, proposal, acceptance, one bounded
dispute, partial finalization, ordinary finalization and conservative Forced
Settlement in both ABCI and the deterministic local Execution Engine. Proposal,
acceptance and dispute dependencies must be finalized before the block
containing their dependent operation. Partial finalization is replay-protected,
credits only undisputed amounts, and preserves the active dispute reserve in
snapshots. Ordinary finalization is rejected while a non-zero reserve exists.
The readiness commitment is evidence-only and cannot move funds. When a
proposal uses it, all Settlement Input roots and Funding bindings must match
the finalized commitment exactly. Canonical Ledger state overrides stale local
Settlement state.

The ordinary local cooperative Settlement application path creates this
commitment immediately before recording `SESSION_SETTLEMENT_PROPOSE`. The
operation is idempotent across proposal retries and records the exact local
Funding predecessor used for the current Funding state hash. When consensus is
enabled, the application layer submits `SESSION_SETTLEMENT_READY_COMMIT`,
`SESSION_SETTLEMENT_PROPOSE`, `SESSION_SETTLEMENT_ACCEPT` and
`SESSION_SETTLEMENT_FINALIZE` in dependency order and waits for verified
finality before applying any missing local projection. Retries reuse canonical
readiness, proposal and signed acceptance payloads by semantic identity; a
changed transport timestamp does not create a second economic operation for
the same Settlement. Validator-mode cooperative Settlement remains fail-closed
before that boundary; it must not mutate validator-local economic state.
The Hypervisor persists exact pending envelopes before submission and removes
them only after the matching local canonical projection is present. On restart,
the same envelope can be resubmitted and reconciled against finality evidence;
a duplicate network submission does not override already verified finality.

## 17. Finality, Corrections and Privacy

A finalized Settlement is economically final under active Ledger rules.
Correction is a new authorized delta record for objective faults such as
duplicate Ledger effects, arithmetic implementation bugs, forged authorization
or emergency recovery. It preserves the original record and Q conservation.

The Ledger SHOULD store a compact commitment containing Settlement ID, Session
ID, Contract Hash, Input Root, Endpoint Payment, refund, fees, dispute state,
mode and result hash. Private payloads, Results, Provider receipts and logs
remain access-controlled evidence.

The MVP typed `SESSION_SETTLEMENT_CORRECT` profile is limited to resolving the
active reserve left by `PARTIAL_UNDISPUTED`. It references the finalized partial
transition and immutable correction object, consumes the reserve exactly once,
and may allocate it only to the Endpoint Payment or Consumer Payment Refund.
It SHALL not change Network Fees, claw back an already released amount, or
rewrite the prior Settlement/Usage evidence. The resulting Funding Account is
`RELEASED` or `REFUNDED` with zero active dispute reserve.

## 18. Stable Errors

The MVP includes stable errors for identity, Input Root, beneficiary, funding,
reserve conservation, maximum charge, Request ceiling, terminal state, Usage
chain, Accounting Contract, rounding, Checkpoint, proposal, dispute, Forced
Settlement, partial finalization, double payment, refund, fee, correction,
Network Revision and internal failures.

## 19. MVP Requirements

The MVP implements integer Q accounting, Funding Accounts, separate payment and
fee reserves, Request Settlement Records, all RFC-0051 Accounting Modes,
terminal policies, Usage-chain validation, Checkpoints, cooperative Settlement,
bounded disputes, partial undisputed finalization, Forced Settlement
integration, refunds, Endpoint payments, Validation zero, compact commitments,
correction records and conformance tests.

Generalized postpaid collection, continuous micropayments, multi-currency,
insurance, external arbitration, zero-knowledge Usage proofs and cross-network
escrow are deferred.

## 20. Invariants

- Settlement uses only accepted immutable terms and committed evidence.
- Endpoint and refund beneficiaries are fixed before execution.
- Canonical arithmetic uses integer `q_atoms` and deterministic rounding.
- Only declared compatible Usage dimensions are billable.
- Request and Session ceilings cannot be expanded by Usage or upstream cost.
- Endpoint Payment, Consumer Refund, Network Fees and dispute reserve conserve
  all locked funds.
- Network Fees, Validator rewards, upstream cost and penalties are distinct.
- Undisputed funds need not remain locked with a bounded dispute.
- One Session has one replay-protected final Settlement lineage.
- Corrections preserve original history and cannot express buyer's remorse.
- Settlement moves Q according to Contract and evidence, not subjective quality
  or the dramatic intensity of an error message.
