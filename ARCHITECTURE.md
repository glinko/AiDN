# ARCHITECTURE.md

# AiDN Architecture Principles

This document defines the architectural principles of the AiDN project.

Every implementation decision SHALL follow these principles.

When implementation conflicts with these principles, the architecture SHALL be discussed before code is merged.

---

# 1. Hypervisor is the Product

The Hypervisor is the primary AiDN product.

Everything else exists to support the Hypervisor.

The network is composed of Hypervisors.

---

# 2. One Hypervisor is One Complete Node

A default Hypervisor installation SHALL be capable of participating in the network without requiring additional mandatory services.

Registry, Wallet and Validator are optional embedded services.

Scaling out must never complicate the default installation.

---

# 3. Everything is an Endpoint

Users interact with Endpoints.

The network discovers Endpoints.

Validators validate Endpoints.

Reputation belongs to Endpoints.

Providers and Bundles exist to support Endpoints.

---

# 4. Bundles are Immutable

A Bundle is a versioned execution artifact.

Bundles SHALL never be modified.

Every modification creates a new BundleHash.

Historical Bundles remain valid forever.

---

# 5. Endpoint Identity is Persistent

Endpoint identity survives implementation changes.

Configuration changes create a new Configuration Snapshot.

Reputation is adjusted, but Endpoint identity remains stable.

---

# 6. Model Classes Define Expected Behaviour

Every public Endpoint SHALL declare a Model Class.

Model Classes define:

* expected behaviour;
* Validation Specification;
* Competency requirements.

Model Classes do not define implementation.

---

# 7. Execution is Private

The Hypervisor SHALL NOT disclose:

* Provider implementation;
* execution topology;
* provider chain;
* local versus remote execution;
* orchestration strategy.

The network evaluates observable behaviour only.

---

# 8. Observable Behaviour Wins

Operators publish declarations.

The network publishes observations.

Trust is derived from observed behaviour, not from operator claims.

---

# 9. Providers are Replaceable

Providers implement execution.

The Hypervisor implements orchestration.

Providers SHALL remain interchangeable.

Replacing a Provider SHALL NOT require changes to Hypervisor business logic.

---

# 10. Scheduler Owns Execution

The Scheduler is the only authority responsible for:

* Endpoint lifecycle;
* resource allocation;
* execution decisions;
* workload dispatch.

No external protocol controls local execution.

---

# 11. Services Own Their State

Every service exclusively owns its internal state.

Other services communicate only through:

* public interfaces;
* immutable events.

Direct modification of another service's state is prohibited.

---

# 12. Events are Observations

Events describe things that have already happened.

Events are immutable.

Events are never commands.

Publishers never know Subscribers.

---

# 13. Interfaces Before Implementations

Architecture SHALL define interfaces before implementations.

Business logic SHALL depend on interfaces rather than concrete implementations.

---

# 14. Local First

Every Hypervisor SHALL continue operating during temporary network failures.

Network connectivity improves functionality.

It SHALL NOT be required for local execution.

---

# 15. Billing is Capability-Aware

Pricing SHALL be expressed using Billing Units.

Examples include:

* tokens;
* seconds;
* images;
* pages;
* requests.

Wallets calculate settlements from Usage Events and Billing Units.

Hypervisors never calculate settlements directly.

---

# 16. Validation is Distributed

Validation is performed by independent Validators.

Validation is reproducible.

Validation is publicly verifiable.

Validation history is append-only.

---

# 17. Reputation is Earned

Neither operators nor Hypervisors may directly modify reputation.

Reputation emerges from:

* observed behaviour;
* Validator attestations;
* operational history;
* Configuration Snapshot history.

---

# 18. Privacy by Default

Implementation details belong to the operator.

Observable behaviour belongs to the network.

Private information SHALL never be published unless explicitly configured by the operator.

---

# 19. Simplicity Before Features

The simplest correct architecture SHALL be preferred.

Future extensions SHALL NOT complicate the default implementation.

Features belong in future RFCs until they are required.

---

# 20. Stability Before Optimization

Correctness is more important than performance.

Clear ownership is more important than convenience.

Maintainability is more important than cleverness.

The architecture SHALL optimize for long-term evolution rather than short-term implementation speed.

---

# Final Principle

Every new feature should answer one question:

**Does it make the Hypervisor a better autonomous AI node?**

If the answer is no,

it probably belongs somewhere else.
