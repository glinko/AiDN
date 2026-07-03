# RFC-0016 Wallet and Identity

Status: `Draft`

Version: `0.1`

Depends on:

- `RFC-0036 AiDN Ledger State Machine`
- `ECO-0000 Economic Principles`

## 1. Purpose

The Wallet defines the cryptographic identity of every participant in the AiDN network.

A Wallet represents ownership.

A Wallet does not store economic state.

Economic state is maintained exclusively by the Ledger.

## 2. Design Philosophy

Wallets identify participants.

The Ledger tracks ownership.

The Consensus validates transitions.

These responsibilities SHALL remain independent.

## 3. Wallet Identity

Every Wallet consists of:

- `Public Key`
- `Private Key`

The Public Key uniquely identifies the Wallet within the network.

The Private Key authorizes Ledger Operations.

## 4. Ownership

A Wallet may own:

- Hypervisors;
- Endpoints;
- Bundles;
- Validator Stakes;
- Validation Bonds;
- Escrow Deposits.

Ownership is established through Ledger Operations.

## 5. Wallet Creation

Wallet creation generates:

- one Public Key;
- one Private Key.

Wallet generation is performed locally.

Private Keys SHALL never leave the owner's device unless explicitly exported.

## 6. Wallet Import

Existing Wallets may be imported using the Private Key.

Importing a Wallet restores ownership.

The Ledger remains the source of truth.

Importing a Wallet does not restore balances.

Balances are reconstructed from the Ledger.

## 7. Wallet Export

Wallet export SHALL include only cryptographic identity.

Export SHALL NOT include:

- balances;
- Session state;
- Endpoint state;
- runtime configuration.

## 8. Ledger Relationship

Wallets never modify balances directly.

Every balance change SHALL occur through a Ledger Operation.

Examples:

- Transfer
- Faucet Reward
- Validation Reward
- Settlement
- Bond Deposit
- Bond Refund

Wallets authorize operations.

The Ledger applies them.

## 9. Balance

Wallet balances are public Ledger state.

Wallets do not internally maintain balances.

Any node SHALL be capable of calculating a Wallet balance solely by replaying the Ledger.

State Snapshots MAY accelerate this process.

Snapshots SHALL never replace Ledger history.

## 10. Authentication

Every protocol operation requiring ownership SHALL be signed.

The signature proves:

- identity;
- authorization;
- integrity.

Unsigned operations SHALL be rejected.

## 11. Transfers

Wallets may transfer `Q` directly.

Transfers SHALL be represented as Ledger Operations.

Transfers require:

- sender signature;
- sufficient Ledger balance.

Future protocol revisions MAY support:

- multisignature transfers;
- delegated transfers;
- recurring transfers;
- scheduled transfers.

## 12. Escrow

Wallets may temporarily lock `Q` into Escrow.

Escrow never owns funds.

Escrow temporarily controls funds according to protocol rules.

Examples include:

- Session Deposits;
- Validation Escrow;
- Validator Stakes;
- Validation Bonds.

## 13. Validator Participation

Validators participate using ordinary Wallets.

Validation Escrow SHALL anonymize Validators during validation.

Endpoints SHALL never observe:

- Validator Wallet;
- Validator balance;
- Validator identity.

## 14. Recovery

Wallet recovery requires the Private Key.

The protocol SHALL not implement password-based recovery.

Loss of the Private Key permanently prevents further control of the Wallet.

Future protocol revisions MAY introduce optional recovery mechanisms.

## 15. Privacy

Wallet ownership is public.

Wallet balances are public.

Private Keys remain secret.

The protocol SHALL never expose Private Keys.

The protocol SHALL never transmit Private Keys.

## 16. Hypervisor Relationship

One Wallet MAY own multiple Hypervisors.

Every Hypervisor possesses an independent Node Identity.

Node Identity and Wallet Identity SHALL remain independent.

Compromise of one Hypervisor SHALL NOT affect ownership of other Hypervisors belonging to the same Wallet.

## 17. Future Extensions

Future protocol revisions MAY introduce:

- operational subaccounts;
- delegated spending limits;
- organizational Wallets;
- hierarchical Wallet structures;
- hardware-backed identities.

The MVP SHALL implement a single Wallet identity.

## 18. Design Invariants

- Wallets represent identity.
- Wallets do not represent balances.
- The Ledger is the sole source of economic truth.
- Every economic action is authorized by a Wallet.
- Every economic state transition occurs through the Ledger.
- Wallet ownership and Hypervisor identity remain independent.
- Private Keys never leave owner control unless explicitly exported.
