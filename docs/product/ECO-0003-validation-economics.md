# ECO-0003 Validation Economics

Status: `Draft`

Version: `0.1`

## Purpose

This document defines the economic model governing Endpoint certification, maintenance validation, and Validator incentives.

The objective is to create long-term incentives for operators to maintain reliable Endpoints while preventing abuse of the validation process.

This document complements [UX-0001 Hypervisor Operator Journey](./UX-0001-hypervisor-operator-journey.md).

`UX-0001` defines when validation is requested and how it appears in the operator journey.

`ECO-0003` defines the bond, reward, revalidation, and forfeiture rules behind that trust layer.

## 1. Design Goals

The Validation Economy SHALL:

- reward useful validation work;
- encourage long-term Endpoint maintenance;
- prevent validation farming;
- discourage disposable Endpoints;
- avoid revealing validation traffic;
- remain economically sustainable.

Validation is a certification service.

It is not a revenue source for Endpoint operators.

## 2. Initial Validation

Validation is always initiated explicitly by the Endpoint operator.

Publishing an Endpoint SHALL NOT automatically request validation.

Validation remains optional.

Private Endpoints never require validation.

## 3. Validation Bond

To request Initial Validation the operator locks a Validation Bond.

Initial value:

`500 Q`

The Bond belongs to the Endpoint Configuration Snapshot.

Changing the Endpoint configuration creates a new Configuration Snapshot and requires a new Validation Bond.

## 4. Validation Result

Validation may produce one of two outcomes.

`PASS`

The Endpoint receives Validation Status.

`FAIL`

The Endpoint receives a Validation Report.

The operator may correct the Endpoint and request validation again.

## 5. Validation Reward

Validators are rewarded for performing validation work.

Validation Reward does not depend on `PASS` or `FAIL`.

Useful work consists of:

- generating validation requests;
- executing validation;
- evaluating responses;
- publishing signed reports.

The Validator is rewarded for honest work, not for a particular outcome.

## 6. Validation Status

Validation Status is the primary reward received by the Endpoint.

Validation increases:

- trust;
- discoverability;
- reputation;
- likelihood of being selected by users.

Validation does not directly generate `Q` for the Endpoint.

## 7. Maintenance Validation

Validation is not permanent.

Already validated Endpoints may be revalidated automatically.

Maintenance Validation may be triggered by:

- decreasing reputation;
- increased latency;
- increased error rate;
- suspicious behaviour;
- random epoch selection.

Every epoch SHALL include:

- all newly submitted Validation requests;
- a random sample of validated Endpoints;
- Endpoints selected because of degraded operational metrics.

## 8. Validation Bond Recovery

The Validation Bond is gradually returned as the Endpoint continuously proves its quality.

Recovery occurs only after successful Maintenance Validation.

The returned amount is calculated using exponential decay.

Example:

Initial Bond:

`500 Q`

Successful Maintenance Validation `#1`

Refund:

`250 Q`

Remaining Bond:

`250 Q`

Maintenance Validation `#2`

Refund:

`125 Q`

Remaining Bond:

`125 Q`

Maintenance Validation `#3`

Refund:

`62.5 Q`

Remaining Bond:

`62.5 Q`

The process continues until the remaining Bond approaches zero.

The Bond is therefore recovered quickly at first, while a small portion remains locked for a long period as an incentive to maintain long-term quality.

## 9. Validation Failure During Maintenance

If a validated Endpoint fails any Maintenance Validation:

- Validation Status is revoked;
- the remaining Validation Bond is permanently forfeited;
- a Validation Report is published.

Previously refunded amounts are never reclaimed.

Only the remaining locked Bond is lost.

## 10. Validator Qualification

A Validator SHALL satisfy the following minimum requirements:

- uptime of at least `10` consecutive days;
- at least one successfully validated Endpoint;
- reputation score of at least `90`;
- an operational Validation Agent;
- the required Capability Profile;
- the required Validator Stake.

Initial Validator Stake:

`500 Q`

Validators automatically leave the Validator Pool if these requirements are no longer satisfied.

## 11. Validator Selection

Validators are selected deterministically by the protocol.

Selection considers:

- Capability compatibility;
- Model Class requirements;
- current workload;
- deterministic epoch randomness;
- conflict-of-interest avoidance.

Neither the Endpoint operator nor the Validator chooses the other party.

## 12. Validation Privacy

Validation traffic SHALL be indistinguishable from ordinary client traffic.

Endpoints SHALL NOT be able to determine whether requests originate from:

- users;
- agents;
- Validators.

Only the Settlement Engine is aware of validation-specific accounting.

## 13. Economic Properties

This model provides the following incentives:

For Endpoint operators:

- maintain long-term service quality;
- avoid disposable Endpoints;
- continuously improve reliability.

For Validators:

- perform honest validation;
- remain available;
- maintain required competency.

For the network:

- continuously monitor Endpoint quality;
- discourage abuse;
- minimize validation farming.

## 14. Future Extensions

Future revisions may introduce:

- Capability-specific Validation Bonds;
- adaptive Bond sizes;
- variable Validator Rewards;
- reputation-weighted Validation selection;
- delegated Validation.

These extensions SHALL remain compatible with the principles defined in this document.

## 15. Design Principles

- Validation is optional.
- Validation is never automatic.
- Validators are paid for work, not outcomes.
- Validation Status is the primary reward for Endpoint operators.
- Validation Bonds encourage long-term reliability.
- Maintenance Validation continuously protects network trust.
- Economic incentives shall always favor honest long-term participation over short-term exploitation.
