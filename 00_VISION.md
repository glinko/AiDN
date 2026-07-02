# Vision

Primary roadmap: see [ROADMAP.md](./ROADMAP.md)

Detailed network architecture spec: see [docs/superpowers/specs/2026-06-19-network-registry-wallet-rating-design.md](./docs/superpowers/specs/2026-06-19-network-registry-wallet-rating-design.md)

Primary operator experience reference: see [docs/product/UX-0001-hypervisor-operator-journey.md](./docs/product/UX-0001-hypervisor-operator-journey.md)

Primary paid-consumption reference: see [docs/product/UX-0002-endpoint-session-and-payment-flow.md](./docs/product/UX-0002-endpoint-session-and-payment-flow.md)

Primary validation-economics reference: see [docs/product/ECO-0003-validation-economics.md](./docs/product/ECO-0003-validation-economics.md)

## Goal

Build a decentralized network of trusted AI compute where:
- node operators provide compute resources;
- agents and users consume AI workloads through the network;
- workloads can be routed across nodes automatically;
- trust, verification, and rating support safe routing;
- network economics encourage supply growth.

## Core Principles

### 1. Network First

The client works with the network, not with one hard-coded node.

### 2. Agent Native

The primary consumer of compute is the agent, not the human operator.

### 3. Trust Driven

Node selection should depend on:
- trust
- quality
- latency
- price

### 4. Model Agnostic

The network should support multiple provider stacks behind one interface, including:
- `llama.cpp`
- `vLLM`
- `Ollama`
- `SGLang`
- `Whisper`
- `TTS`
- `Video`

### 5. Verification First

Every advertised model or capability should be verifiable.

### 6. Hypervisor As Product

The Hypervisor is not only infrastructure.

It should feel like an operator-facing operating system for AI resources, where wallet setup, provider attachment, endpoint publication, marketplace discovery, and automation are understandable without requiring knowledge of internal AiDN architecture.

It should also expose a predictable paid-execution contract, where clients reserve Endpoint Sessions explicitly, lock deposits up front, and receive automatic refunds for unused balance.

## Delivery Strategy

The target is a distributed network, but delivery is phased:

1. local hypervisor first
2. centralized registry and discovery second
3. wallet and pricing interfaces next
4. rating, reputation, and validation economics after that
5. federated or distributed registry later

Within those milestones, product sequencing should follow the operator journey in `UX-0001`:

1. install and onboard the Hypervisor
2. configure wallet ownership
3. attach providers and models
4. create and publish endpoints
5. define how those endpoints can be consumed through paid Sessions as described in `UX-0002`
6. discover, consume, and proxy remote endpoints
7. automate the node through MCP and agents
