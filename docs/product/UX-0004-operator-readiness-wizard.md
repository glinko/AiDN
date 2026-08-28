# UX-0004 — Operator Readiness Wizard

Status: `Draft`

Version: `0.1`

Depends on:

- [UI-0001 Hypervisor Dashboard Specification](UI-0001-hypervisor-dashboard-specification.md)
- [UX-0001 Hypervisor Operator Journey](UX-0001-hypervisor-operator-journey.md)
- RFC-0053 Capability Runtime Specification
- RFC-0054 Capability Runtime Protocol
- MCP-0001 AiDN Node Control Server

## 1. Purpose

The Operator Readiness Wizard is the single guided path for taking a freshly
installed Hypervisor from host prerequisites to a publishable Endpoint.

It is an inline Overview workflow. It does not replace the canonical pages for
Wallet, Provider Instance, Model Deployment, Runtime Binding, Bundle or
Endpoint.

## 2. Readiness Model

The wizard evaluates these independent checks:

1. Consensus RPC
2. Operator Wallet
3. Host Capacity
4. Provider Instance
5. Model Deployment
6. Runtime Binding
7. Bundle
8. Endpoint Offer

Each check exposes:

- observed status: `ready`, `blocked`, `attention` or `manual`;
- a short explanation;
- bounded evidence fields;
- one next action, or an explicit manual instruction.

`UNAVAILABLE` and `0` remain distinct. A missing resource probe is a blocker,
not an empty machine. A model visible in an upstream Provider is not a Model
Deployment until Hypervisor inventory contains it.

The execution checks also recognize the direct managed-process path created by
model installation. An enabled managed Bundle with a materialized model and a
local runtime endpoint is itself the executable boundary; it does not need a
separate Provider Instance, Model Deployment or Runtime Binding record. The
wizard reports those checks as ready with an explicit explanation rather than
showing false blockers. Attached-service Bundles continue to require the full
Provider/Model/Binding chain.

## 3. Safety Boundary

The wizard SHALL NOT:

- expose wallet private keys or secret handles;
- execute shell commands or install host services;
- claim that an MCP mutation exists when it is not advertised;
- infer Runtime Binding, Bundle or Endpoint readiness from Provider reachability;
- publish an Endpoint without the existing explicit operator action.

Interactive actions navigate to existing operator routes, open the Wallet
console, refresh the readiness projection, or invoke the existing model
discovery route. Fresh Ubuntu installation is responsible for host-level
consensus provisioning: the reviewed operator bootstrap installs the pinned
CometBFT toolchain, creates a fixed user-systemd unit, starts the Hypervisor
ABCI listener before CometBFT, and verifies RPC health. The dashboard never
executes arbitrary host commands. A legacy node without managed consensus
metadata receives a concrete migration instruction instead of a misleading
in-dashboard shell action.

The bootstrap supports `validator`, `non_validator` and `disabled` modes. A
local CometBFT runtime and ABCI service are installed only for `validator`.
`non_validator` is an external-RPC observer: it requires a verified private
source RPC, does not create a local genesis or noop application, and keeps
local P2P/service controls disabled. A new local genesis is created only when
the validator CometBFT home is empty; an existing `genesis.json` is checked
against the requested chain ID and is never rewritten by a rerun.

## 4. Readiness Projection

The dashboard consumes:

`GET /operators/dashboard/readiness`

The response is a non-secret read model with:

- `overall_state`;
- `execution_ready`;
- `network_ready`;
- progress counters;
- ordered `steps`;
- `next_action`;
- bounded inventory counts.

The same projection is suitable for a future read-only MCP resource or tool.

## 5. Completion Definition

The node is locally execution-ready when either the attached-service chain
(Provider Instance, Model Deployment, Runtime Binding and Bundle) is ready, or
an enabled managed-process Bundle with its materialized model and local runtime
endpoint is ready.

The node is network-ready only when Consensus RPC, Wallet and a published
Endpoint offer are ready as well. Validation is deliberately not part of the
minimum readiness gate; it remains an independent operator decision.
