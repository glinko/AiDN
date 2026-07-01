# Endpoint Session And Payment Flow Design

## Summary

This spec defines the first product and architecture slice for paid endpoint consumption through explicit Sessions.

The repository already has:
- endpoint manifests and configuration snapshots;
- endpoint publication and proof flows;
- wallet metering, usage export, and settlement lifecycle primitives;
- operator dashboard surfaces for endpoints, market, requests, and wallet activity.

What is still missing is the execution contract between a consumer and a paid Endpoint:
- how a client reserves capacity before inference begins;
- how funds are locked before execution;
- how an Endpoint declares concurrency and idle policy;
- how reserved but unused capacity is priced fairly;
- how the system refunds unused balance automatically.

Authoritative references:
- [UX-0001 Hypervisor Operator Journey](../../product/UX-0001-hypervisor-operator-journey.md)
- [UX-0002 Endpoint Session and Payment Flow](../../product/UX-0002-endpoint-session-and-payment-flow.md)
- [Endpoint Configuration Publication Design](./2026-06-30-endpoint-configuration-publication-design.md)

## Design Decision

### Selected Direction

Build an `endpoint session ledger + deposit reservation + session-scoped execution` model.

That means:
- a paid Endpoint is consumed through explicit Sessions, not ad hoc task calls;
- opening a Session reserves one endpoint slot;
- opening a Session locks a deposit before execution;
- every request during the reservation period references the Session;
- settlement is derived from actual usage plus idle reservation policy;
- unused balance is refunded automatically when the Session closes.

### Why

This matches the product promises in `UX-0002`:
- exclusive or shared access becomes an explicit economic resource;
- providers know that reserved capacity is paid for;
- clients see the contract before funds are locked;
- session queue/busy behavior can be reasoned about independently from raw task queue internals.

It also fits the current endpoint-first architecture:
- endpoint manifests already describe public runtime and pricing metadata;
- wallet primitives already describe usage, settlement, dispute, and replay-safe export;
- the next missing layer is the reservation unit that connects endpoint policy to wallet movement.

### Rejected Alternatives

#### 1. Pay Per Task Without Sessions

Rejected because it does not model reserved capacity.

It cannot express:
- exclusive access;
- queueing against endpoint slots;
- idle reservation billing;
- no-request minimum session fee.

#### 2. Reuse Allocation Leases Directly As Client Sessions

Rejected for the first paid endpoint slice because allocation leases are currently internal hypervisor routing and ownership primitives.

They are close to the needed behavior, but they are not yet:
- endpoint-facing;
- deposit-backed;
- explicitly client-confirmed;
- shaped around idle billing and refund rules.

They may later share lower-level machinery, but the public contract should be modeled as `Session`, not leaked as `Allocation`.

## Product Goals

This slice must let the system:
- open a paid Session for a published Endpoint;
- reserve one concurrency slot per active Session;
- lock a client deposit before execution begins;
- apply usage-based settlement within the Session;
- apply operator-defined idle billing during reservation;
- close and refund Sessions automatically or manually.

This slice must let the operator:
- publish commercial session policy on the Endpoint;
- decide whether saturated demand queues or gets a busy response;
- control concurrent session limits based on hardware;
- see active Sessions and locked deposits in the Hypervisor UI.

This slice must let the client:
- inspect the financial contract before committing funds;
- choose a deposit amount at or above the minimum;
- understand idle timeout and idle fee;
- close the Session explicitly when work is complete;
- receive automatic refund of unused balance.

## Non-Goals

This slice does not:
- define on-chain escrow implementation details;
- define final blockchain wallet integration;
- redesign the existing operator settlement/dispute console;
- solve multi-hop marketplace routing for paid Sessions;
- define validator-specific pricing;
- replace low-level task queue primitives everywhere in one step.

## Core Model

The design introduces four new concepts:

1. `EndpointSessionPolicy`
2. `EndpointSession`
3. `LockedDeposit`
4. `SessionSettlement`

### 1. EndpointSessionPolicy

This is published as part of endpoint-visible commercial metadata.

Fields:
- `minimum_deposit`
- `recommended_deposit`
- `idle_fee_per_minute`
- `idle_timeout_seconds`
- `max_concurrent_sessions`
- `maximum_session_duration_seconds`
- `queue_policy`
- `minimum_session_fee`

`queue_policy` should initially allow:
- `busy`
- `queue`

### 2. EndpointSession

This is the active reservation unit.

Fields:
- `session_id`
- `endpoint_id`
- `client_wallet`
- `provider_wallet`
- `node_id`
- `status`
- `created_at`
- `started_at`
- `last_activity_at`
- `expires_at`
- `idle_deadline_at`
- `deposit_locked_q`
- `reserved_slot_index`
- `queue_policy_snapshot`
- `session_policy_snapshot`

Statuses should initially be:
- `pending_funding`
- `queued`
- `active`
- `idle`
- `closing`
- `closed`
- `expired`
- `cancelled`

### 3. LockedDeposit

This is the wallet-facing economic reservation for a Session.

Fields:
- `deposit_id`
- `session_id`
- `wallet_id`
- `locked_q`
- `consumed_q`
- `refunded_q`
- `status`

The initial implementation may store this in local state with explicit future extension to network-controlled escrow.

### 4. SessionSettlement

This is the settlement-facing aggregate for the Session lifecycle.

It should track:
- metered usage charges;
- idle charges;
- minimum session fee if no work occurred;
- final provider payout;
- final client refund.

## Request Flow

### Session Open

1. Client selects a published Endpoint.
2. Hypervisor loads Endpoint pricing and session policy.
3. Hypervisor shows confirmation:
   - endpoint name
   - pricing
   - minimum deposit
   - recommended deposit
   - selected deposit
   - idle fee
   - idle timeout
4. Client confirms.
5. Deposit is locked.
6. Session becomes `active` if a slot is free, otherwise:
   - enters `queued`; or
   - returns `busy`
   according to endpoint queue policy.

### Session Request

Each request must carry `session_id`.

The hypervisor:
- verifies session ownership and state;
- executes through the endpoint/provider path;
- records usage against that Session;
- updates `last_activity_at`;
- updates deposit consumption and settlement counters.

### Session Idle

If no request arrives:
- session enters `idle` after the active request window ends;
- idle fee accrues based on endpoint policy;
- idle timeout closes the Session automatically when the threshold is exceeded.

### Session Close

A Session closes when:
- the client closes it manually;
- idle timeout expires;
- the session duration reaches maximum policy;
- deposit is exhausted and policy cannot continue execution.

Close triggers:
- slot release;
- final settlement calculation;
- provider payout booking;
- automatic refund booking for unused balance.

## Interaction With Existing Systems

### Endpoint Model

Endpoint manifests and published endpoint payloads should grow to include:
- session policy block;
- queue/busy saturation policy;
- session-enabled commercial metadata.

This should remain separate from:
- validation state;
- proof hash logic;
- remote proxy topology.

### Wallet Layer

The current wallet usage and settlement primitives remain useful, but sessions add a new upstream contract:
- lock funds first;
- meter usage against a specific reservation;
- settle from the locked balance instead of only post-facto usage totals.

This means the wallet layer will need:
- deposit lock events;
- refund events;
- session settlement summary export.

### Task Queue

The current task queue remains the runtime execution substrate.

Session semantics sit above it:
- session slot admission happens before or alongside task submission;
- queued Sessions are not the same as queued tasks;
- endpoint slot saturation is a new resource dimension distinct from CPU/RAM/VRAM pressure.

### Operator Dashboard

The dashboard will need a new paid execution surface or session panel showing:
- active sessions;
- queued sessions;
- locked balances;
- idle timers;
- slot saturation;
- busy vs queue policy.

The current wallet and request views should be extended, not replaced.

## API Direction

The first API slice should add endpoint-session routes such as:

- `POST /api/v1/endpoints/{endpoint_id}/sessions`
- `GET /api/v1/sessions`
- `GET /api/v1/sessions/{session_id}`
- `POST /api/v1/sessions/{session_id}/close`

Task execution routes for paid endpoints should accept:
- `session_id`

Session open request should include:
- `client_wallet`
- `deposit_q`

Session open response should include:
- `session_id`
- `status`
- `locked_deposit_q`
- `idle_timeout_seconds`
- `idle_fee_per_minute`
- `reserved_slot_state`

## Failure And Edge Cases

The first implementation must define behavior for:
- deposit below minimum;
- endpoint saturation with `busy` policy;
- endpoint saturation with `queue` policy;
- session created but never used;
- session duration limit reached;
- idle timeout reached;
- missing provider usage payload during paid session;
- strict-accounting settlement block during session close.

The product should prefer explicit closure with intelligible reason codes rather than silent session disappearance.

## Phasing

This should be implemented in three sub-slices:

### Slice A: Session Policy And Open/Close Contract

Add:
- endpoint session policy metadata;
- session open/close primitives;
- slot accounting;
- deposit lock record;
- basic dashboard visibility.

### Slice B: Session-Scoped Execution And Settlement

Add:
- request execution bound to `session_id`;
- usage attribution into session settlement;
- no-request minimum fee handling;
- refund calculation.

### Slice C: Idle Billing And Saturation UX

Add:
- idle timers and fee accrual;
- queue vs busy behavior;
- richer operator and client-facing dashboard surfaces.

## Acceptance Signals

This slice is successful when:
- a paid Endpoint can explicitly advertise session policy;
- a client must reserve a Session before using it;
- the Hypervisor can explain the full financial contract before locking funds;
- reserved capacity is released automatically when abandoned;
- providers are paid only from pre-locked session balance;
- unused balance is refunded deterministically.
