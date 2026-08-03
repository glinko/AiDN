# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary users are AiDN Hypervisor operators managing one or more local or
remote execution nodes. They need to attach Providers, create and operate
Bundles, publish Endpoint offers, review capacity and health, and control
Wallet-backed network operations. Consumers use separate Marketplace and
Session flows to reserve and execute against Endpoint offers.

## Product Purpose

AiDN Hypervisor is an operating control plane for AI resources. It lets an
operator connect execution backends, make a coherent Bundle deployment,
publish compatible Endpoint offers, observe runtime health and capacity, and
manage the resulting sessions and settlement evidence.

## Positioning

The Hypervisor makes a protocol-backed execution chain operable as one
deployment unit while preserving the distinct ownership of Provider, Runtime,
Bundle, Endpoint, Session, Wallet, and Validation objects.

## Operating Context

Operators use the Dashboard during installation, Wallet setup, provider and
model onboarding, Bundle activation, endpoint publication, validation,
incident response, and daily capacity monitoring. A single Wallet may own
multiple Hypervisors; Node Identity and Wallet Identity remain separate.

## Capabilities and Constraints

- Bundle is the primary operator-facing deployment unit.
- Endpoint remains the consumer-facing commercial offer and is never hidden
  inside a Bundle.
- Published or active Bundles are immutable; edits create a cloned revision
  and show validation, resource, routing, and Endpoint consequences first.
- Basic Mode must keep ordinary operator work approachable. Advanced Mode may
  reveal Provider Plugin, Provider Instance, Model Deployment, Runtime
  Binding, Validation, Network, and diagnostic detail without duplicating
  domain-object ownership.
- The dashboard uses existing Hypervisor APIs and must not create a parallel
  configuration model or expose secrets, private topology, or cross-session
  data.
- Session creation is explicit and displays Endpoint price, deposit, capacity,
  idle policy, and settlement consequences before funds lock.

## Brand Commitments

AiDN is a serious operational product, closer to a professional virtualization
control plane than an AI chat interface. The supplied UI-0001 reference is a
binding visual direction: a dark, dense, legible workspace with persistent
Hypervisor context and honest health signals.

## Evidence on Hand

- `docs/product/UI-0001-hypervisor-dashboard-specification.md`
- `docs/product/UX-0001-hypervisor-operator-journey.md`
- `docs/product/UX-0002-endpoint-session-and-payment-flow.md`
- `src/aidn_hypervisor/static/operator_dashboard.html`
- User-supplied dashboard reference image in the current task.

## Product Principles

- One domain object has one canonical surface; cross-links never duplicate it.
- Bundle is the operator's center of gravity, while Endpoint stays visibly
  distinct as the customer-facing offer.
- Critical operational and economic consequences appear before confirmation.
- Health, readiness, validation, and economic status remain explicit rather
  than inferred from a green process indicator.
- The interface remains useful for a local-only operator and grows into
  Advanced Mode without a different workflow.

## Accessibility & Inclusion

The Dashboard must support keyboard navigation, visible focus, readable
contrast, responsive layouts, non-color-only status cues, and honest loading,
empty, blocked, and error states.
