# Reasoning Router and Intelligence Provider Registry

This is the first RFC-0075 implementation slice. It is intentionally a
selection boundary, not an inference executor.

## What is implemented

`aidn_hypervisor.reasoning_router` contains two bounded components:

- `ReasoningProviderRegistry` stores non-secret metadata for local resident,
  local model, AiDN endpoint, and external API providers. Provider records are
  capped, validated, snapshot-safe, and reject credential-like metadata keys.
- `ReasoningRouter` evaluates every registered provider and returns a stable,
  explainable decision. It checks capability, task complexity, context length, data class,
  trust, external-provider policy, latency budget, per-request Q cost,
  delegated Q budget, and Resource Broker admission.

The ranking is deterministic:

1. local providers before AiDN/external providers;
2. higher operator priority;
3. exact capability match;
4. lower latency;
5. lower Q cost;
6. stable provider ID.

No route decision invokes a model, makes a network request, reserves a lease,
or mutates a Bundle/Endpoint. The selected provider is an eligible suggestion;
the later Escalation Task and normal MCP policy still control execution.

## API and MCP surfaces

Operator API:

- `GET /operators/dashboard/steward/reasoning/providers`
- `POST /operators/dashboard/steward/reasoning/providers`
- `POST /operators/dashboard/steward/reasoning/route`

Read-only MCP tools:

- `aidn.steward.reasoning.providers`
- `aidn.steward.reasoning.route`

The MCP route automatically applies the current Control Session delegated
budget as `budget_remaining_q_atoms`. A client cannot increase that value by
omitting it. The route result includes `decision_id`, selected provider,
candidate ranking, rejection codes, and `execution.started: false`.

The read model is also available at:

`aidn://steward/reasoning/providers`

## Fail-closed behavior

If the Resource Broker is unavailable and a provider requires resources, that
provider is rejected with `RESOURCE_ADMISSION_UNAVAILABLE`. If no provider
survives all checks, the result is `NO_ELIGIBLE_PROVIDER` / `ROUTE_UNAVAILABLE`.
The router never falls back by silently relaxing privacy, budget, context, or
external-provider restrictions.

## Provider metadata rules

Provider metadata must describe capability and placement only. Raw API keys,
tokens, passwords, private keys, and credentials are rejected. Endpoint
authentication belongs to the later provider adapter/SecretStore boundary and
must never be placed in the registry or route request.

The built-in `resident-local` record is refreshed from the current Resident
Inference Adapter state. It is unavailable until the operator has enabled and
prepared the local model; registering metadata never starts it.

## Next slice

The next RFC-0075 slice is durable Escalation Task storage: bind a route
decision to a bounded redacted context, idempotency key, plan hash, provider
attempts, approval handoff, and postcondition verification.
