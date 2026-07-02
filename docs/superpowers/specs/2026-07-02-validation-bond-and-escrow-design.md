# Validation Bond And Escrow Design

## Summary

This spec defines the first implementation slice for `M5.1` validation trust:

- operator-requested validation bound to a concrete `configuration_hash`;
- operator-side Validation Bond economics from `ECO-0003`;
- validator-side Validation Escrow Pool envelope from `RFC-0035`;
- a local, deterministic implementation shape that can later be replaced by distributed Validator infrastructure.

The key design correction in this slice is that two different economic systems must coexist:

1. the operator's Validation Bond, which is locked against one endpoint configuration and gradually refunded or forfeited;
2. the Validators' Escrow Pool, which backs anonymous validation Sessions and capacity assignment for an Epoch.

They are related, but they are not the same object.

## Current Repository Context

The repository already has:

- endpoint manifests and immutable configuration snapshots;
- wallet-owned endpoint publication records and live endpoint proof;
- session-based paid execution and a unified wallet ledger export;
- operator-facing endpoint controls with a placeholder validation posture;
- remote and proxy execution flows that already preserve privacy around execution topology.

What is missing is the first real trust contract behind validation:

- a Validation Bond lifecycle;
- validation request, assignment, and report persistence;
- maintenance revalidation and bond recovery/forfeit rules;
- a future-proof Validator Escrow envelope that keeps validator identity out of endpoint traffic.

## Authoritative References

- [UX-0001 Hypervisor Operator Journey](../../product/UX-0001-hypervisor-operator-journey.md)
- [ECO-0003 Validation Economics](../../product/ECO-0003-validation-economics.md)
- [RFC-0035 Validation Escrow Protocol](../../product/RFC-0035-validation-escrow-protocol.md)
- [Endpoint Configuration Publication Design](./2026-06-30-endpoint-configuration-publication-design.md)
- [Endpoint Session And Payment Flow Design](./2026-07-01-endpoint-session-payment-flow-design.md)

## Design Decision

### Selected Direction

Build a `dual-layer validation contract`:

- `Operator Bond Layer` for endpoint-owner economics and long-term trust incentives;
- `Validator Escrow Layer` for anonymous validation capacity, Session guarantee, and deterministic assignment;
- one `ValidationService` orchestration layer that binds the two together around a specific endpoint configuration.

The first implementation slice is local and deterministic, but the contract shape must already match the future distributed protocol.

### Why

This preserves the distinctions required by the product and economics documents:

- publishing and validation remain separate operator actions;
- Validation Bond economics stay attached to the endpoint owner and `configuration_hash`;
- validator-side payment guarantees come from a pool, not a validator's personal wallet balance;
- endpoint traffic remains blind to validator identity;
- future distributed validator selection can replace local stubs without changing endpoint semantics.

### Rejected Alternatives

#### 1. Single Escrow Model For Both Bond And Validation Traffic

Rejected because `ECO-0003` and `RFC-0035` describe two different responsibilities.

The operator bond incentivizes long-term endpoint quality.

The validator escrow pool guarantees anonymous validation execution capacity.

Combining them would blur forfeiture, refund, and anonymity rules.

#### 2. Local Validation Status Without Bond Or Escrow Semantics

Rejected because it would produce a temporary implementation that conflicts with the actual product and protocol model.

This repository has already reached the point where trust state must be economically meaningful, not just a UI flag.

#### 3. Immediate Distributed Validator Pool Implementation

Rejected for this slice because it would combine trust-state design with network-distributed coordination and slow down delivery.

The current goal is to lock the domain model and state machine first.

## Product Goals

This slice must let the system:

- request validation explicitly for a specific endpoint configuration;
- lock a Validation Bond owned by the endpoint operator;
- track validation state independently from publication state;
- persist validation request history and signed-like report artifacts;
- run maintenance revalidation with exponential bond recovery;
- forfeit remaining bond on maintenance failure;
- model validator assignment through local Epoch, Share, and Authorization records that match `RFC-0035`;
- guarantee that validation Sessions do not become endpoint revenue events.

This slice must let the operator:

- see whether a given configuration is unvalidated, pending, validated, failed, or superseded;
- request validation without silently publishing or modifying endpoint runtime;
- inspect the latest validation report and bond state;
- understand that validation trust belongs to the published or local `configuration_hash`, not to the endpoint label alone.

## Non-Goals

This slice does not:

- implement a distributed validator network;
- implement real on-chain or external-contract escrow execution;
- implement validator rewards beyond recording the economic placeholder events;
- implement ranking or discovery sorting by validation trust;
- implement full dashboard UX for validator operations;
- make validation traffic cryptographically opaque on the wire yet.

## Core Model

The design has four layers:

1. endpoint validation state;
2. operator bond state;
3. validator escrow Epoch state;
4. validation report history.

### 1. Endpoint Validation State

Validation always binds to:

- `endpoint_id`
- `configuration_hash`

Validation never binds only to a mutable endpoint label or current runtime pointer.

Execution-relevant endpoint changes rotate `configuration_hash`, supersede the old validated snapshot, and require a new validation request.

### 2. Operator Bond State

The operator side holds one `ValidationBond` per validation attempt family for a specific `endpoint_id + configuration_hash`.

The bond records:

- ownership;
- locked amount;
- remaining locked amount;
- refunded amount;
- forfeited amount;
- current bond status;
- escrow reference for future external settlement.

In `M5.1`, the bond is managed through a local adapter.

The service contract must still expose a stable `escrow_reference` so an external contract can replace the local adapter later.

### 3. Validator Escrow Epoch State

Validator-side economics are represented separately through:

- `ValidationEpoch`
- `ValidationValidatorEntry`
- `ValidationShare`
- `ValidationAuthorization`
- `ValidationAssignment`

The local implementation uses deterministic in-process records, but the contract intentionally mirrors `RFC-0035`:

- validators contribute `Q` into a pool;
- shares are expanded into an assignment list;
- the list is deterministically shuffled;
- authorizations are minted per validation Session without exposing validator wallet identity to the endpoint.

### 4. Validation Report History

Each validation attempt produces a report artifact that records:

- request identity;
- validator capability envelope;
- report outcome;
- evidence summary;
- published timestamp;
- maintenance or initial mode;
- signature-like metadata for future protocol replacement.

The first slice may use local signatures or stub signer metadata, but the record shape must support eventual cryptographic validator proofs.

## Validation State Machines

### Validation Request Status

`ValidationRequest.status` values:

- `draft`
- `bond_locked`
- `queued`
- `assigned`
- `authorization_issued`
- `report_submitted`
- `passed`
- `failed`
- `superseded`
- `revoked`
- `forfeited`

Notes:

- `draft` is internal and short-lived;
- `authorization_issued` captures the RFC-0035 step where the validator can execute one anonymous validation Session;
- `forfeited` is terminal for the remaining bond after maintenance failure.

### Endpoint Validation Snapshot Status

`ValidationStatusSnapshot.status` values:

- `unvalidated`
- `pending_initial`
- `validated`
- `maintenance_due`
- `maintenance_in_progress`
- `validation_failed`
- `revoked`
- `superseded`

### State Transitions

Initial request:

- operator requests validation for current `configuration_hash`;
- service locks the operator bond;
- request moves `draft -> bond_locked -> queued`;
- endpoint validation snapshot moves `unvalidated -> pending_initial`.

Assignment:

- current Epoch assignment selects an eligible validator entry;
- validator escrow authorization is issued;
- request moves `queued -> assigned -> authorization_issued`.

Initial success:

- report accepted;
- request moves `authorization_issued -> report_submitted -> passed`;
- endpoint validation snapshot moves `pending_initial -> validated`.

Initial failure:

- report accepted with fail outcome;
- request moves `authorization_issued -> report_submitted -> failed`;
- endpoint validation snapshot moves `pending_initial -> validation_failed`.

For the first slice, initial failure does not automatically forfeit the bond.

The bond remains locked against that configuration until the operator either retries explicitly or abandons the configuration through later lifecycle changes.

Configuration change:

- any execution-relevant configuration change supersedes the prior active validation snapshot;
- prior validation snapshot becomes `superseded`;
- any active request tied to the old `configuration_hash` becomes `superseded`;
- new configuration starts at `unvalidated`.

Maintenance pass:

- validated snapshot is selected for maintenance;
- snapshot moves `validated -> maintenance_due -> maintenance_in_progress -> validated`;
- request history records maintenance outcome;
- remaining bond refunds `50%` of current locked amount.

Maintenance fail:

- validated snapshot moves `validated -> maintenance_due -> maintenance_in_progress -> validation_failed`;
- remaining locked bond is forfeited;
- request or maintenance event records terminal `forfeited` outcome for the bond remainder.

Publication revoke:

- publication state may change independently;
- validation history remains;
- validation does not automatically disappear from history;
- network-visible trust marker may stop being discoverable when publication is revoked, but validation state itself is still attached to that configuration record.

## Bond Economics

### Operator Validation Bond

Initial default:

- `500 Q`

The bond is attached to:

- `owner_wallet`
- `endpoint_id`
- `configuration_hash`

The bond supports:

- lock;
- partial refund;
- forfeiture;
- close.

### Initial Failure Handling

For `M5.1`, initial validation failure keeps the bond locked.

Reasons:

- `ECO-0003` explicitly defines forfeiture for maintenance failure;
- the operator journey expects explicit retry after correction;
- forcing a brand-new bond on first failure would introduce a harsher economic rule than the current product text declares.

### Maintenance Refund Schedule

Each successful maintenance validation refunds:

`refund_q = remaining_locked_q * 0.5`

Then:

`remaining_locked_q = remaining_locked_q - refund_q`

This yields the exponential decay described in `ECO-0003`.

### Maintenance Failure

On maintenance failure:

- validation status is revoked;
- the remaining locked bond is forfeited;
- previously refunded amounts are never reclaimed.

## Validator Escrow Protocol Envelope

### Separate From Wallet Ownership

Validator Escrow is not a wallet balance surface.

It is a protocol pool used to guarantee validation Sessions while hiding validator-specific financial state from the endpoint.

### Local Epoch Model For M5.1

The local implementation introduces:

- `ValidationEpoch`
- `ValidationValidatorEntry`
- `ValidationAssignment`
- `ValidationAuthorization`

Each validator entry declares:

- an opaque validator identity;
- share count;
- capability profile;
- epoch eligibility;
- local escrow contribution metadata.

### Share Expansion And Deterministic Shuffle

At Epoch start:

1. collect eligible validators;
2. expand each validator into a list sized by share count;
3. shuffle deterministically using epoch seed;
4. assign queued validation requests sequentially.

This must be reproducible from persisted epoch data and seed.

### Session Authorization

Each assignment yields one `ValidationAuthorization` that confirms:

- epoch validity;
- sufficient escrow backing;
- permission for one validation session;
- redacted validator identity.

The authorization must not expose:

- validator wallet;
- validator pool balance;
- share count.

### Endpoint Revenue Rule

Validation Sessions do not create endpoint revenue.

They may reuse the session infrastructure shape, but settlement classification must mark them as validation traffic so:

- endpoint revenue is not credited;
- validator identity is not exposed;
- accounting stays distinct from ordinary paid usage.

## Service Architecture

### Validation Service

The repository should introduce a dedicated `ValidationService` responsible for:

- validation request creation;
- bond lock and refund orchestration;
- Epoch assignment orchestration;
- authorization minting;
- report submission and outcome application;
- maintenance scheduling and resolution;
- publication of validation-related wallet ledger events.

This service should consume endpoint and publication data rather than re-own them.

### Operator Bond Escrow Adapter

Use an `OperatorBondEscrowAdapter` abstraction with methods equivalent to:

- `lock_bond(...)`
- `refund_bond(...)`
- `forfeit_bond(...)`
- `close_bond(...)`

`M5.1` uses a local implementation, but the adapter contract must preserve an `escrow_reference` for later external-contract execution.

### Validator Escrow Pool Adapter

Use a separate `ValidatorEscrowPoolAdapter` abstraction for:

- Epoch capacity registration;
- share expansion;
- authorization issue;
- validation-session guarantee metadata.

The local implementation is deterministic and in-process.

The future implementation may point to an external pool or protocol service without changing endpoint validation semantics.

## API Surface

The first implementation slice should expose:

- `POST /api/v1/endpoints/{endpoint_id}/request-validation`
- `GET /api/v1/endpoints/{endpoint_id}/validation`
- `GET /api/v1/endpoints/{endpoint_id}/validation/history`
- `POST /api/v1/validation/epochs`
- `POST /api/v1/validation/requests/{request_id}/reports`
- `POST /api/v1/validation/requests/{request_id}/maintenance`

Endpoint validation summary payloads should include at least:

- `endpoint_id`
- `configuration_hash`
- `validation_status`
- `latest_request_id`
- `latest_report_id`
- `bond_state`
- `validated_at`
- `superseded_at`

## Persistence

Root state persistence should store:

- validation requests;
- validation reports;
- validation bonds;
- validation status snapshots;
- validation epochs;
- validator entries;
- validation assignments;
- validation authorizations.

Persistence must preserve deterministic replay for:

- epoch shuffle order;
- maintenance refund math;
- wallet ledger export.

## Wallet Ledger Integration

Validation must appear in the unified wallet ledger as audit events, not as escrow authority.

Expected event families:

- `validation_bond_locked`
- `validation_bond_refunded`
- `validation_bond_forfeited`
- `validation_request_passed`
- `validation_request_failed`
- `maintenance_validation_passed`
- `maintenance_validation_failed`

The wallet ledger reports what happened economically.

It does not own validator escrow capacity and does not decide validation assignment.

## Testing Strategy

The first implementation slice must cover five areas.

### 1. Domain Tests

- request and snapshot status transitions;
- supersede on `configuration_hash` rotation;
- maintenance decay math;
- maintenance forfeiture math.

### 2. Service Tests

- request validation locks operator bond;
- initial pass sets validated status;
- initial fail keeps bond locked;
- maintenance pass refunds `50%` of remaining locked bond;
- maintenance fail forfeits remaining locked bond.

### 3. Validator Escrow Tests

- share expansion from validator contributions;
- deterministic shuffle reproducibility;
- authorization creation without validator wallet exposure;
- validation traffic classification separate from ordinary paid sessions.

### 4. API Tests

- request validation endpoint;
- endpoint validation summary and history endpoints;
- report submission endpoint;
- maintenance trigger endpoint.

### 5. Persistence And Wallet Tests

- validation state round-trips through persisted snapshots;
- validation events appear in unified wallet ledger export;
- replay after reload preserves Epoch order and bond state.

## Expected Outcome

After this slice:

- validation is no longer only a placeholder endpoint flag;
- the repository has an explicit trust-state machine tied to `configuration_hash`;
- operator bond economics and validator escrow semantics are modeled separately;
- future distributed validator coordination can replace local adapters without changing endpoint-facing validation meaning.
