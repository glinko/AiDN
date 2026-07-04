# RFC-0037 Settlement Engine

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0035 Validation Escrow System`
- `RFC-0036 AiDN Ledger State Machine`
- `RFC-0016 Wallet and Identity`
- `ECO-0000 Economic Principles`
- `ECO-0003 Validation Economics`

## 1. Purpose

The Settlement Engine is responsible for all economic state transitions within the AiDN protocol.

Its responsibilities include:

- locking deposits;
- releasing deposits;
- processing Session invoices;
- distributing payments;
- refunding unused funds;
- settling Validation Bonds;
- distributing protocol rewards.

The Settlement Engine never creates business rules.

It only executes protocol-defined economic transitions.

`ECO-0000` defines why those transitions matter economically.

`RFC-0036` defines how the resulting state transitions become canonical Ledger state.

`RFC-0037` defines how those economic transitions are computed and applied deterministically.

## 2. Design Principles

Settlement SHALL be:

- deterministic;
- reproducible;
- atomic;
- auditable.

Every honest node SHALL compute identical Settlement results from identical Ledger Operations.

## 3. Settlement Scope

Settlement applies to:

- Session Deposits;
- Session Invoices;
- Validation Bonds;
- Validation Refunds;
- Validator Rewards;
- Registry Rewards;
- Wallet Transfers;
- Network Fees;
- Escrow release.

No protocol component may modify balances outside Settlement.

## 4. Session Lifecycle

A Session progresses through the following economic states:

`Created -> Deposit Locked -> Executing -> Invoice Submitted -> Settlement -> Closed`

Only one Settlement Operation may exist for a Session.

## 5. Deposit Lock

Opening a Session locks the client Deposit.

Example:

`Wallet 100 Q -> Open Session -> Available 50 Q / Locked 50 Q`

Locked funds remain unavailable until Settlement completes.

## 6. Invoice

When a Session ends, the Endpoint submits an Invoice.

The Invoice SHALL include:

- Session ID;
- usage summary;
- total amount;
- protocol metadata;
- Endpoint signature.

The Invoice never transfers funds directly.

Settlement validates the Invoice before execution.

## 7. Settlement

Settlement performs:

1. Invoice verification.
2. Network Fee calculation.
3. Provider payment.
4. Refund calculation.
5. Escrow release.
6. Ledger update.

Settlement SHALL either complete entirely or fail entirely.

Partial Settlement is prohibited.

## 8. Refund

Unused Deposit SHALL automatically return to the originating Wallet.

Example:

`Deposit: 50 Q`

`Invoice: 27 Q`

`Refund: 23 Q`

Refund is processed automatically.

## 9. Network Fee

Every Session Settlement includes the Network Fee.

Recommended default:

`0.01 Q`

Network Fee is transferred to the protocol distribution mechanism.

Fee collection is independent of Endpoint pricing.

## 10. Validation Settlement

Validation Sessions are economically distinct from ordinary Sessions.

Validation follows the ordinary Session protocol.

However:

- the Endpoint receives no Session revenue;
- Validation Status is awarded separately;
- Validator Rewards are distributed after Epoch completion.

Settlement SHALL recognize Validation Sessions through protocol metadata.

Validator anonymity, Escrow guarantees, and Epoch-scoped authorization flow are defined separately in [RFC-0035 Validation Escrow System](./RFC-0035-validation-escrow-system.md).

## 11. Validation Bond

Validation Bonds are Ledger objects.

Successful Maintenance Validation triggers a Bond Refund.

Refund schedule:

First successful Maintenance Validation:

`50%` of remaining Bond.

Every subsequent successful Maintenance Validation:

`50%` of the remaining locked Bond.

Example:

`Initial Bond: 500 Q`

`Maintenance #1 -> Refund 250 Q -> Remaining 250 Q`

`Maintenance #2 -> Refund 125 Q -> Remaining 125 Q`

The process continues until the remaining Bond approaches zero.

## 12. Validation Failure

If an Endpoint fails any Maintenance Validation:

- Validation Status is revoked;
- the remaining Validation Bond is burned;
- previously refunded amounts remain with the operator.

Burning is irreversible.

## 13. Validator Rewards

Validator Rewards are generated only after Epoch finalization.

Rewards are independent of:

- Endpoint pricing;
- Session invoices;
- Validation outcome.

Rewards compensate Validators for completed validation work.

## 14. Registry Rewards

Collected Network Fees are distributed among eligible Registry Nodes.

Eligibility requirements are defined separately.

Settlement only executes the resulting Ledger Operations.

## 15. Wallet Transfers

Wallet Transfers are settled through the same Settlement Engine.

Settlement verifies:

- sufficient balance;
- valid signatures;
- protocol fees.

Successful Transfers become Ledger Operations.

## 16. Escrow Release

After successful Settlement:

- unused Escrow is released;
- locked Deposits become available;
- Validation Escrow returns to Validators after Epoch completion.

Escrow never permanently owns funds.

## 17. Failure Recovery

Settlement SHALL be idempotent.

Repeated execution of the same Settlement Operation SHALL produce identical Ledger state.

Interrupted Settlement SHALL safely resume without duplicating transfers.

## 18. Auditability

Every Settlement produces a deterministic Ledger Operation.

Any node SHALL be capable of independently reproducing:

- Provider payments;
- Refunds;
- Fee distribution;
- Bond updates;
- Reward generation.

## 19. Design Invariants

- Settlement is the only mechanism that moves `Q`.
- Settlement never creates business rules.
- Settlement executes only deterministic protocol logic.
- Every Settlement is atomic.
- Every Settlement is reproducible.
- Every Settlement is independently auditable.
- No balance changes occur outside Settlement.
