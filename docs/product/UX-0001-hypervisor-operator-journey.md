# UX-0001 Hypervisor Operator Journey

Status: `Draft`

Version: `0.1`

## Purpose

This document defines the intended operator experience when interacting with the AiDN Hypervisor.

Unlike RFC documents, this specification describes the product from the operator's perspective. It serves as the primary reference for UI/UX design, onboarding, and workflow implementation.

All implementation decisions should preserve this user journey whenever reasonably possible.

## 1. Core Philosophy

The Hypervisor is the product.

The operator should never be required to understand the internal architecture of AiDN.

Concepts such as Providers, Bundles, Validators, and Registry are implementation details exposed only when necessary.

The primary goal is that a new operator can install a Hypervisor and publish their first Endpoint within minutes.

## 2. Installation

The operator downloads the Hypervisor from the official repository.

Installation produces a single executable system.

After startup the operator opens the Web UI.

On first launch the Hypervisor enters onboarding mode.

No network functionality is available until a Wallet has been configured.

## 3. Wallet

The Wallet represents ownership.

It is independent from any particular Hypervisor.

The operator may:

- create a new Wallet;
- import an existing Wallet.

Creating a Wallet generates:

- a private key;
- a public key.

Importing a Wallet requires the private key.

The Wallet becomes the owner of the Hypervisor.

All management operations are signed using the Wallet.

Future versions may support transferring ownership of Hypervisors between Wallets.

## 4. Hypervisor Identity

Every Hypervisor possesses its own permanent Node Identity.

Node Identity is distinct from Wallet identity.

One Wallet may own multiple Hypervisors.

Example:

`Wallet -> Home Hypervisor -> Office Hypervisor -> Cloud Hypervisor`

Each Hypervisor accumulates its own operational reputation.

Compromise or failure of one Hypervisor must not affect the reputation of others owned by the same Wallet.

## 5. Dashboard

After Wallet configuration the operator is presented with the main dashboard.

The dashboard provides access to:

- Providers;
- Bundles;
- Endpoints;
- Remote Endpoints;
- Wallet;
- Validation;
- Marketplace;
- Metrics;
- MCP Integration;
- Settings.

The dashboard is the primary interface for operating the Hypervisor.

## 6. Providers

The operator may attach execution Providers.

Supported installation methods include:

- automatic detection;
- provider manifest import;
- manual configuration.

Examples:

- llama.cpp
- Ollama
- vLLM
- ComfyUI
- Whisper

Providers may initially contain no models.

## 7. Bundles and Models

Providers may execute Bundles immediately or remain empty.

The operator may:

- download models;
- import models;
- leave the Provider empty.

An Endpoint may explicitly allow future users to upload their own compatible model.

Model storage and Endpoint publication are independent operations.

## 8. Faucet

The Hypervisor provides direct access to the development Faucet.

The operator may request test tokens.

Example:

`100Q`

Rate limits apply.

The Faucet exists exclusively to simplify onboarding and development.

## 9. Endpoints

The operator may create any number of Endpoints.

Each Endpoint defines:

- Bundle;
- Provider;
- Model Class;
- pricing;
- privacy policy;
- runtime configuration.

Endpoints may be:

- private;
- shared with selected Wallets;
- publicly accessible.

Endpoint publication does not imply validation.

## 10. Privacy

Visibility, accessibility, and validation are independent concepts.

Examples:

### Private Endpoint

- visible only locally;
- no external access;
- no validation.

### Shared Endpoint

- accessible only to approved Wallets;
- no validation.

### Public Endpoint

- publicly accessible;
- validation optional.

The Hypervisor SHALL NOT expose whether an incoming request originates from a Validator or an ordinary client.

Validation requests MUST be indistinguishable from production traffic.

## 11. Validation

Validation is initiated explicitly by the operator.

Publishing an Endpoint SHALL NOT automatically request validation.

Validation remains optional.

An operator may permanently operate unvalidated Endpoints.

Validation is intended for operators wishing to provide publicly trusted services.

## 12. Validation Stake

Requesting validation locks a configurable stake.

Stake requirements may depend on Endpoint characteristics.

Examples include:

- Model Class;
- Capability;
- required resources.

Stake remains locked while the validated Endpoint continues operating without execution-relevant modifications.

Changing the Endpoint configuration creates a new Configuration Snapshot and requires a new validation request.

## 13. Validation Failure

If validation fails:

- the operator receives the published validation report;
- the operator may correct the Endpoint;
- the operator may explicitly request validation again.

The retry is never automatic.

The operator decides when the Endpoint is ready for re-validation.

## 14. Validators

Only qualified Validators may validate Endpoints.

Validators must satisfy the competency requirements defined for the corresponding Model Class and Capability.

For LLMs, Validator models are expected to be approximately equivalent to or stronger than the validated Model Class.

Equivalent competency frameworks will be defined for speech, image, and video Capabilities.

## 15. Remote Endpoints

The operator may discover and add remote Endpoints.

Remote Endpoints become available for local routing and orchestration.

The Hypervisor maintains a local catalogue of preferred remote Endpoints.

Operators may freely mix:

- local execution;
- remote execution;
- proxy execution.

## 16. Proxy Endpoints

An operator may publish a Proxy Endpoint.

A Proxy Endpoint forwards requests to another Provider.

The underlying execution may be:

- local;
- remote;
- commercial;
- self-hosted.

Consumers interact only with the published Endpoint.

The underlying execution topology remains private.

Execution privacy is a fundamental architectural principle.

## 17. MCP Integration

The Hypervisor exposes an MCP interface.

Agents may:

- create Endpoints;
- remove Endpoints;
- publish Endpoints;
- manage Providers;
- install Bundles;
- discover remote Endpoints;
- manage Wallet operations;
- spawn task-specific sub-agents.

Agents become first-class Hypervisor operators.

## 18. Marketplace

The Hypervisor includes a Marketplace view.

Operators may:

- discover public Endpoints;
- compare pricing;
- compare validation status;
- compare reputation;
- bookmark Endpoints;
- connect Endpoints to local workflows.

A newly installed Hypervisor should provide immediate value even before publishing its own services.

## 19. Design Principles

- Wallet ownership and Hypervisor identity are independent.
- Publishing and validation are independent actions.
- Validation is always optional.
- Validation traffic is indistinguishable from production traffic.
- Endpoint implementation remains private.
- Operators retain full control over when validation is requested.
- Local, remote, and proxy execution are treated as equal execution strategies.
- The Hypervisor remains useful even without publishing any Endpoints.

## 20. Product Vision

The Hypervisor should feel less like infrastructure software and more like an operating system for AI resources.

A new operator should be able to install it, connect execution backends, discover remote intelligence, publish trusted services, and automate the entire node through agents without needing to understand the internal architecture of the AiDN network.
