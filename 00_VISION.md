# Vision

Primary roadmap: see [ROADMAP.md](./ROADMAP.md)

Detailed network architecture spec: see [docs/superpowers/specs/2026-06-19-network-registry-wallet-rating-design.md](./docs/superpowers/specs/2026-06-19-network-registry-wallet-rating-design.md)

Primary operator experience reference: see [docs/product/UX-0001-hypervisor-operator-journey.md](./docs/product/UX-0001-hypervisor-operator-journey.md)

Primary paid-consumption reference: see [docs/product/UX-0002-endpoint-session-and-payment-flow.md](./docs/product/UX-0002-endpoint-session-and-payment-flow.md)

Primary validation-economics reference: see [docs/product/ECO-0003-validation-economics.md](./docs/product/ECO-0003-validation-economics.md)

Primary economic-principles reference: see [docs/product/ECO-0000-economic-principles.md](./docs/product/ECO-0000-economic-principles.md)

Primary wallet-and-identity reference: see [docs/product/RFC-0016-wallet-and-identity.md](./docs/product/RFC-0016-wallet-and-identity.md)

Primary ledger-state reference: see [docs/product/RFC-0036-aidn-ledger-state-machine.md](./docs/product/RFC-0036-aidn-ledger-state-machine.md)

Primary governance-and-authorization reference: see [docs/product/RFC-0067-protocol-governance-and-authorization-policy.md](./docs/product/RFC-0067-protocol-governance-and-authorization-policy.md)

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

### 4. Capability And Runtime Driven

The network should expose capabilities and runtimes as its canonical execution model.

Provider stacks such as `llama.cpp`, `vLLM`, `Ollama`, `Whisper`, and future adapters remain implementation details behind capability runtimes rather than primary public protocol objects.

### 5. Model Agnostic

The network should support multiple provider stacks behind one interface, including:
- `llama.cpp`
- `vLLM`
- `Ollama`
- `SGLang`
- `Whisper`
- `TTS`
- `Video`

### 6. Verification First

Every advertised model or capability should be verifiable.

### 7. Hypervisor As Product

The Hypervisor is not only infrastructure.

It should feel like an operator-facing operating system for AI resources, where wallet setup, provider attachment, endpoint publication, marketplace discovery, and automation are understandable without requiring knowledge of internal AiDN architecture.

It should also expose a predictable paid-execution contract, where clients reserve Endpoint Sessions explicitly, lock deposits up front, and receive automatic refunds for unused balance.

Its economic behavior should remain utility-first, where `Q` represents access to computation rather than a speculative asset.

## Network Governance And The Path To DAO

AiDN is intended to become a decentralized autonomous protocol: a network in
which the rules for shared state, rewards, upgrades, and critical network
services are proposed, reviewed, authorized, and activated through transparent
protocol processes rather than by the unilateral decision of a maintainer or
one node operator.

This is a delivery path, not a label claimed on day one. Early testnet operation
may use a declared, bounded Bootstrap Governance Council while the network has
too few independent participants for meaningful broad governance. Its members,
authority threshold, decisions, and sunset path must be public and auditable.
Bootstrap authority must never be presented as decentralized governance.

### Separate The Layers Of Authority

Different decisions belong to different layers and must not be conflated:

| Layer | Purpose | Canonical source |
| --- | --- | --- |
| CometBFT consensus | Finalizes blocks and canonical state. | Validator set and voting power in `genesis.json`, then on-chain Validator Set updates. |
| Network profile | Identifies a network and its verified connectivity and release information. | Signed public Network Profile, with a locally applied TOML projection. |
| Protocol authority | Authorizes narrowly defined protocol-owned actions during bootstrap and controlled operation. | Threshold-signed Protocol Authority Policy. |
| Governance | Authorizes durable policy, economic, and protocol decisions. | On-chain Governance Proposals, Chamber Snapshots, Votes, and Authorization Certificates. |

The local Hypervisor configuration is not a source of authority. An operator
may choose local ports, peers, runtime configuration, and endpoint prices, but
must not be able to rewrite the canonical network, validator set, governance
threshold, reward policy, or protocol rules from a Settings page.

### Consensus Safety Is Not An Ordinary Vote

For a CometBFT validator set with equal voting power, block finality requires
more than two-thirds of the active voting power. With four equal validators,
that means three validators. This is a safety property of Byzantine fault
tolerant consensus, not an application preference that may be casually reduced
to 60 percent through a parameter edit.

Changing `chain_id`, replacing Genesis, or adopting consensus semantics that
violate the greater-than-two-thirds safety model is a coordinated network
revision or hard fork. It must be explicit, replay-safe, versioned, and treated
as a new network history when required; it is not an ordinary configuration
change.

### From Proposal To Activation

Every durable network change should follow one visible lifecycle:

```text
Draft RFC and implementation plan
        ->
Immutable Governance Proposal
        ->
Sponsorship and public review
        ->
Fixed eligibility snapshot
        ->
Chamber voting under the current policy
        ->
Authorization Certificate
        ->
Technical readiness and operator release
        ->
Scheduled activation at a future Epoch
```

Each proposal version is immutable and content-addressed. It identifies the
exact affected policy, implementation, security analysis, economic analysis,
migration plan, and activation Epoch. A material change creates a new proposal
version and requires renewed review and voting. Approval is therefore not a
general permission to change something later; it authorizes one precise,
auditable change.

The current policy governs its own amendment. For example, a proposal to lower
a 75 percent constitutional threshold to 60 percent must itself reach the
current 75 percent threshold before it can take effect. The proposed lower
threshold only applies after its scheduled activation. This prevents a small
group from granting itself broader powers by editing the rule it is voting on.

### Distributed Governance

As AiDN gains independent operators, governance should transition from the
Bootstrap Council to a DAO-like distributed model with two binding chambers:

- **Consensus Chamber:** active Consensus Validators vote using the frozen
  CometBFT voting-power snapshot. It protects finality, canonical state
  execution, and consensus-critical upgrades.
- **Infrastructure Chamber:** each eligible Known Control Group has one vote,
  regardless of how many nodes, endpoints, Registries, or Validator identities
  it operates. It represents the compute, validation, Registry, and operator
  infrastructure on which the network depends.

The two chambers prevent either validators alone or a large collection of
service identities alone from governing the whole network. `Q` ownership does
not directly purchase binding protocol control in the initial model. Economic
signals may inform decisions, but they do not replace the required technical
and infrastructure authorization.

Ordinary service-policy changes can use lower, declared thresholds. Economic,
consensus-critical, and state-migration changes require stronger approval.
Constitutional changes -- including chamber design, governance eligibility,
and voting thresholds -- require the strongest ordinary supermajority in both
chambers. Eligibility and voting power are frozen before voting opens so that
new identities, transferred services, or last-minute stake movements cannot
change the electorate during a decision.

### Safe Upgrades And Emergency Boundaries

Governance authorization and software activation are distinct. A network may
authorize a change only after the implementation, reproducible artifacts,
operator migration plan, and deterministic state transition are ready. Nodes
then activate the approved version at a future Epoch, not in the middle of an
unreviewed block sequence.

Emergency authority exists only to contain clearly bounded harm. A short safety
pause may temporarily stop a risky operation, but cannot move balances, mint
`Q`, change the Validator Set, or permanently amend governance rules. Every
emergency action has a defined scope, evidence, expiration, and public record.
If canonical consensus is unavailable, no party may pretend that an off-chain
meeting is an on-chain vote; recovery follows an explicit network-revision
process.

### What DAO Means For AiDN

The desired end state is not an unbounded token vote. It is a protocol whose
shared decisions are:

- proposed by any eligible participant under anti-spam rules;
- reviewed publicly with technical, security, and economic evidence;
- approved by independent roles using transparent, snapshot-based rules;
- activated predictably and only after technical readiness;
- recorded permanently so that operators can verify why a rule exists; and
- constrained by consensus safety, cryptography, and explicit emergency limits.

That is the governance foundation for a network where maintainers continue to
build software, operators continue to operate infrastructure, and no single
role silently becomes the owner of the protocol.

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
