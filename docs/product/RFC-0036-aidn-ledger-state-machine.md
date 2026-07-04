# RFC-0036 AiDN Ledger State Machine

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0016 Wallet`
- `ECO-0000 Economic Principles`
- `ECO-0003 Validation Economics`

## 1. Purpose

The Ledger is the canonical state of the AiDN network.

Consensus orders operations.

The Ledger defines their meaning.

`ECO-0000` defines why those economic operations exist.

`RFC-0036` defines how they become deterministic network state.

Detailed economic execution semantics for deposits, invoices, refunds, fees, rewards, and bond transitions are defined separately in [RFC-0037 Settlement Engine](./RFC-0037-settlement-engine.md).

The Consensus Engine never interprets network logic.

It only guarantees that every node executes the same operations in the same order.

## 2. Design Philosophy

The Ledger is a deterministic state machine.

Every node executes the same sequence of operations.

Given the same initial state and the same ordered operations, every node SHALL produce the identical final state.

No node may modify the state outside the Ledger.

## 3. Ledger State

The Ledger maintains the global network state.

Examples include:

- Wallet balances
- Escrow balances
- Validator Stakes
- Validation Bonds
- Endpoint metadata
- Reputation
- Session state
- Validation state

The Ledger SHALL NOT store temporary runtime information.

GPU utilization, RAM usage, and Provider internals are outside Ledger scope.

## 4. Wallet

A Wallet stores only cryptographic identity.

Detailed Wallet ownership, key control, signing, and Hypervisor identity-separation semantics are defined in [RFC-0016 Wallet and Identity](./RFC-0016-wallet-and-identity.md).

A Wallet does not store its own balance.

Balances are derived from Ledger operations.

Example:

`Wallet -> Public Key -> Private Key`

Balance is computed from Ledger history.

## 5. Ledger Operations

Every state transition SHALL be represented by a Ledger Operation.

Examples:

- Faucet Reward
- Wallet Transfer
- Session Open
- Session Close
- Session Settlement
- Validation Bond
- Validation Reward
- Validation Refund
- Validator Stake
- Advertisement Publish
- Endpoint Publish
- Reputation Update

No other mechanism may modify network state.

## 6. Operation Structure

Every Ledger Operation SHALL contain:

- `OperationID`
- `Timestamp`
- `Epoch`
- `OperationType`
- `Inputs`
- `Outputs`
- `Metadata`
- `Required Signatures`

Operation payloads are deterministic.

## 7. State Transition

Nodes SHALL execute operations sequentially.

Example:

`Genesis -> Operation 1 -> Operation 2 -> Operation 3 -> Current State`

Every node reaches the identical state.

## 8. Determinism

Ledger execution SHALL NOT depend on:

- local clocks;
- hardware;
- execution speed;
- operating system;
- random generators.

Every operation SHALL produce identical results on every node.

## 9. Minting

`Q` may only be created through explicitly defined Ledger Operations.

Initial supported operations:

- Faucet Reward
- Validation Reward

No node may mint `Q` independently.

## 10. Burning

`Q` may only disappear through Ledger Operations.

Examples:

- Validation Bond forfeiture
- future protocol upgrades

Destroyed `Q` SHALL be removed from total supply.

## 11. Transfers

Wallet transfers SHALL be ordinary Ledger Operations.

Transfers SHALL require signatures from the sending Wallet.

Future versions may support:

- multisignature;
- delegated signatures;
- scheduled transfers.

## 12. Sessions

Opening a Session creates a Ledger Operation.

Closing a Session creates another Ledger Operation.

Settlement is represented as an independent Ledger Operation.

Session execution itself is not recorded on-chain.

Only economically significant events are recorded.

## 13. Escrow

Escrow balances are Ledger objects.

Escrow operations include:

- deposit;
- reservation;
- release;
- settlement.

Escrow never owns funds.

It temporarily controls them according to protocol rules.

## 14. Validation

Validation produces Ledger Operations.

Examples:

- Validation Requested
- Validation Completed
- Validation Failed
- Validation Reward
- Validation Bond Refund

Validation Reports themselves may be stored off-chain.

Only their cryptographic reference is stored in the Ledger.

The Settlement Engine computes the corresponding deterministic balance transitions before they are materialized as Ledger Operations, as defined in [RFC-0037 Settlement Engine](./RFC-0037-settlement-engine.md).

## 15. Reputation

Reputation is Ledger state.

Reputation changes only through deterministic Ledger Operations.

Every Reputation Update SHALL be reproducible.

## 16. Snapshots

Nodes MAY maintain state snapshots.

Snapshots exist only to accelerate synchronization.

The canonical source of truth remains the ordered Ledger Operations.

## 17. State Verification

Any node SHALL be able to reconstruct the complete network state solely from:

- Genesis;
- ordered Ledger Operations.

Snapshots are optional.

Verification SHALL NOT depend on snapshots.

## 18. Consensus Separation

Consensus is responsible only for:

- ordering operations;
- preventing forks;
- finalizing blocks.

Consensus SHALL NOT contain AiDN business logic.

All business rules belong exclusively to the Ledger State Machine.

## 19. Design Invariants

- The Ledger is the single source of truth.
- Wallets contain keys, not balances.
- Every state transition is represented by a Ledger Operation.
- `Q` exists only as Ledger state.
- Consensus orders operations but never interprets them.
- Every honest node independently reaches the identical network state.
