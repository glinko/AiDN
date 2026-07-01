# UX-0002 Endpoint Session and Payment Flow

Status: `Draft`

Version: `0.1`

## Purpose

This document defines how operators and users interact with paid Endpoints.

The objective is to make AI resource usage predictable, fair, and economically secure for both parties.

This document complements [UX-0001 Hypervisor Operator Journey](./UX-0001-hypervisor-operator-journey.md).

`UX-0001` explains how operators create, publish, and manage Endpoints.

`UX-0002` explains how consumers reserve, pay for, and use those Endpoints through explicit Sessions.

## 1. Core Principle

An Endpoint is not purchased.

An Endpoint is reserved for a paid Session.

A Session grants temporary execution rights according to the Endpoint policy.

## 2. Session

Before sending requests the client creates a Session.

Creating a Session:

- reserves one execution slot;
- locks a deposit;
- creates an exclusive execution context.

Every request during the Session belongs to the same Session.

## 3. Session Capacity

Each Endpoint publishes its maximum number of concurrent Sessions.

Example:

`max_concurrent_sessions: 1`

Exclusive Endpoint.

Only one client may use the Endpoint.

Example:

`max_concurrent_sessions: 8`

Shared Endpoint.

Eight independent Sessions may execute simultaneously.

The operator determines the appropriate value based on available hardware and expected workload.

## 4. Session Deposit

Before a Session begins, the client locks a deposit.

The Endpoint publishes:

- `minimum_deposit`
- `recommended_deposit`
- `maximum_session_duration`

The client may increase the deposit above the recommended value.

Larger deposits reduce the likelihood of premature Session termination due to insufficient funds.

## 5. Deposit Confirmation

Before opening a Session the Hypervisor displays:

- Endpoint name;
- pricing information;
- minimum deposit;
- recommended deposit;
- selected deposit;
- idle fee;
- idle timeout.

The client explicitly confirms the deposit.

Only then are the funds locked.

## 6. Locked Funds

Locked funds remain under network control.

Neither the client nor the provider may spend them directly.

After the Session completes:

- the provider receives payment for actual usage;
- the remaining balance is automatically refunded to the client.

## 7. Exclusive Reservation

Each active Session occupies one execution slot.

When all available slots are occupied:

- new clients wait in a queue; or
- receive a `busy` response.

Queue policy is defined by the Endpoint operator.

## 8. Request Execution

Every request references the active Session.

The Provider reports resource usage after each request.

Examples include:

- input tokens;
- output tokens;
- execution time;
- generated images;
- processed audio duration.

Settlement is based on actual usage.

## 9. Idle State

A Session enters the `Idle` state when no requests are received.

The Endpoint publishes:

- `idle_timeout`
- `idle_fee_per_minute`

Example:

`idle_timeout: 10m`
`idle_fee_per_minute: 1Q`

Idle time is billable.

This compensates the operator for reserved computing capacity.

## 10. Automatic Session Release

If no requests are received before the Idle Timeout expires:

- the Session closes automatically;
- final settlement is calculated;
- remaining funds are refunded.

This prevents abandoned Sessions from permanently occupying Endpoint resources.

## 11. Manual Session Release

The client may close the Session at any time.

Closing a Session immediately:

- releases the execution slot;
- performs settlement;
- refunds unused funds.

Clients are encouraged to close Sessions when work is complete.

## 12. No Request Scenario

If a Session is created but no requests are sent:

- the provider receives the minimum Session fee;
- the remaining deposit is refunded.

This prevents abuse through repeated reservation of Endpoint capacity without actual usage.

## 13. Endpoint Pricing Policy

Each Endpoint publishes:

```yaml
pricing:
  billing_unit:
  input_price:
  output_price:
session:
  minimum_deposit:
  recommended_deposit:
  idle_fee_per_minute:
  idle_timeout:
  max_concurrent_sessions:
  maximum_session_duration:
```

These values define the commercial contract before the Session begins.

## 14. Design Principles

- Sessions are explicitly created and closed.
- Funds are locked before execution begins.
- Providers are guaranteed payment.
- Clients are guaranteed automatic refunds of unused funds.
- Idle resource reservation is billable.
- Endpoint operators determine concurrency limits.
- Exclusive access is an economically valuable resource.
- Session behavior is completely transparent before the client commits funds.
