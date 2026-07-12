# ECO-0000 Economic Principles

Status: `Draft`

Version: `0.1`

## Purpose

This document defines the fundamental economic principles of the AiDN network.

Unlike implementation documents, this specification describes the incentives governing participants and establishes the economic philosophy upon which all higher-level protocols are built.

All economic mechanisms SHALL remain compatible with the principles defined herein.

This document is the root economic reference for the current product-doc stack.

Session economics, validation economics, wallet flows, ledger state, and future marketplace rules should all remain compatible with `ECO-0000`.

## 1. Philosophy

AiDN is not a cryptocurrency.

AiDN is a distributed computing economy.

The purpose of the network is not to trade digital assets.

The purpose of the network is to exchange computational resources.

`Q` exists solely to account for contributions to and consumption of those resources.

## 2. Q

`Q` is the native accounting unit of the AiDN protocol.

`Q` represents the right to consume distributed computational resources.

`Q` is not positioned as a fiat currency substitute.

Future protocol revisions MAY introduce exchange mechanisms with external assets.

Such mechanisms are outside the scope of the MVP.

## 3. Economic Cycle

The fundamental economic cycle is:

`Operator contributes computation -> Network rewards contribution -> Operator accumulates Q -> Operator consumes computation provided by other operators`

Every participant may simultaneously be both provider and consumer.

## 4. Utility

The value of `Q` derives from its utility.

`Q` enables:

- opening Sessions;
- consuming distributed AI resources;
- transferring value between Wallets;
- obtaining Endpoint Validation;
- staking protocol roles.

The protocol SHALL avoid encouraging speculative behavior.

Utility SHALL always take precedence over speculation.

## 5. Free Market

The protocol does not regulate pricing.

Every Endpoint operator independently determines:

- Session pricing;
- token pricing;
- image pricing;
- audio pricing;
- idle pricing;
- deposit requirements.

The marketplace determines economic equilibrium.

Free Endpoints are explicitly supported.

Competition is encouraged.

## 6. Hypervisor

The Hypervisor is an infrastructure component.

The Hypervisor itself never earns `Q`.

Economic rewards belong exclusively to Endpoint operators.

## 7. Network Fee

Economically significant protocol operations require a Network Fee.

Initial recommended value:

`0.01 Q`

Examples include:

- opening a Session;
- publishing an Endpoint;
- publishing an Advertisement;
- Wallet transfers;
- Validation requests.

The Network Fee exists to:

- discourage spam;
- finance protocol infrastructure;
- contribute recyclable protocol revenue for later Epoch reward allocation.

## 8. Sessions

All computation occurs within Sessions.

Every Session defines an economic contract between client and Endpoint.

A Session specifies:

- deposit;
- pricing;
- idle policy;
- timeout;
- settlement.

Sessions are economically independent.

Nested or chained workflows create multiple independent Sessions.

## 9. Deposits

Every Session requires a Deposit.

The Deposit guarantees payment.

Suggested defaults:

Minimum Deposit:

`10 Q`

Recommended Deposit:

`50 Q`

Operators MAY define larger requirements.

Clients MAY increase Deposits during an active Session.

## 10. Validation

Validation is an optional certification service.

Validation exists to establish trust.

Validation is not required for private Endpoints.

Validation does not generate direct revenue for Endpoint operators.

The principal economic benefit of Validation is increased trust and discoverability.

## 11. Validation Bond

Initial Validation requires a Validation Bond.

Suggested default:

`500 Q`

The Bond demonstrates long-term commitment to maintaining a reliable Endpoint.

The Bond is gradually returned through successful Maintenance Validation.

Failure during Maintenance Validation removes the remaining locked Bond from operator control and hands it to the protocol-defined forfeiture and recycling path unless a future rule explicitly marks it as permanent burn.

## 12. Validators

Validators provide a protocol service.

Validators receive `Q` for performing validation work.

Compensation depends on successful execution of the validation process rather than the validation outcome.

Validators are selected deterministically by the protocol.

## 13. Registry

Registry operators provide storage and discovery services.

Registry operators receive protocol reward distributions only when they satisfy the applicable service-eligibility and proof requirements.

Only Registry nodes satisfying protocol requirements participate in reward distribution.

Proof mechanisms are defined separately.

## 14. Wallets

Wallets represent ownership.

Wallet balances are public Ledger state.

Wallet private keys remain secret.

Cryptographic wallet structure, key control, and ownership-signing semantics are defined separately in [RFC-0016 Wallet and Identity](./RFC-0016-wallet-and-identity.md).

Future protocol revisions MAY introduce operational subaccounts.

## 15. Transfers

Wallets may transfer `Q` directly.

Transfers are Ledger Operations.

Transfer fees follow Network Fee rules.

Future protocol revisions MAY introduce:

- multisignature transfers;
- delegated transfers;
- scheduled transfers.

## 16. Emission

New `Q` may be introduced only through protocol-defined Ledger Operations.

Initial supported emission sources:

- Faucet payments;
- Consensus rewards;
- Registry rewards;
- Validation rewards.

Recycled protocol removals MAY increase later Epoch reward authorization, but removal alone does not mint new `Q`.

No participant may independently create `Q`.

## 17. Burn

`Q` may permanently leave circulation through protocol-defined burn mechanisms.

Examples include:

- future governance decisions.

Burn operations are irreversible.

Unless explicitly marked as permanent, MVP protocol deductions are treated as recyclable removals rather than permanent burns.

## 18. Long-Term Incentives

The protocol rewards:

- reliable infrastructure;
- long-term participation;
- honest validation;
- useful computation;
- operational stability.

The protocol discourages:

- disposable infrastructure;
- spam;
- short-term exploitation;
- manipulation of economic rules.

## 19. Design Principles

- Utility precedes speculation.
- Computation is the network's primary product.
- Markets determine pricing.
- Trust must be earned continuously.
- Rewards follow useful work.
- Long-term reliability is economically preferable to short-term profit.
- Economic rules shall discourage abuse without restricting legitimate participation.

## 20. Future Work

Future documents define:

- Session Economics
- Marketplace Economics
- Validation Economics
- Consensus Economics
- Registry Economics
- Token Lifecycle
- Governance Economics

These specifications SHALL remain consistent with the principles established in `ECO-0000`.
