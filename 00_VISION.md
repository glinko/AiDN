# Vision

Primary roadmap: see [ROADMAP.md](./ROADMAP.md)

Detailed network architecture spec: see [docs/superpowers/specs/2026-06-19-network-registry-wallet-rating-design.md](./docs/superpowers/specs/2026-06-19-network-registry-wallet-rating-design.md)

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

## Delivery Strategy

The target is a distributed network, but delivery is phased:

1. local hypervisor first
2. centralized registry and discovery second
3. wallet and pricing interfaces next
4. rating and reputation publication after that
5. federated or distributed registry later
