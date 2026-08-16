# WEB-0001 AiDN Public Website and Web Application Specification

Status: `Draft`

Version: `0.1`

Type: `Product / UX / Content Specification`

Implementation plan: [WEB-0001 Implementation Plan](../development/web-0001-implementation-plan.md)

Target Website API: [WEB-0001 Website API OpenAPI](./WEB-0001-website-api.openapi.yaml)

Related product documents:

- [UI-0001 Hypervisor Dashboard Specification](./UI-0001-hypervisor-dashboard-specification.md)
- [UX-0001 Hypervisor Operator Journey](./UX-0001-hypervisor-operator-journey.md)
- [MCP-0001 Node Control Server Implementation Profile](./MCP-0001-node-control-server-implementation-profile.md)
- [ECO-0008 Faucet Treasury and Policy Execution](./ECO-0008-faucet-treasury-and-policy-execution.md)
- [MVP-0001 Economic Execution Profile](./MVP-0001-economic-execution-profile.md)

## 1. Authority and purpose

This document is the product and content source of truth for the official AiDN public website and its public Web Application. It is intentionally not an RFC. Protocol RFCs remain normative for network behavior, identities, consensus, accounting, validation, and security. `WEB-0001` defines how a visitor understands and uses those capabilities.

When implementation materials disagree, use this precedence:

1. security and protocol invariants in accepted RFCs and economic profiles;
2. the product boundaries, user journeys, routes, copy intent, and acceptance criteria in `WEB-0001`;
3. the concrete repository mapping in the implementation plan;
4. visual mockups and implementation details.

The website must let a new visitor answer, within minutes:

1. What is AiDN?
2. Why does the network exist?
3. How does local and network compute work?
4. What can I use from the network?
5. What can I provide to the network?
6. How do I install a Hypervisor and run a node?
7. How do I obtain initial Q and perform a first operation?
8. Where are the documentation, source, releases, and developer tools?

The governing product principle is:

> Explain the idea first. Prove that the network can be used second. Offer the shortest truthful path to action third.

The website must not summarize the RFC corpus page by page and must not invent capabilities to fill a visual layout.

## 2. Product positioning

### 2.1 Core message

> Your compute when you need it. The network's compute when you do not have enough.

AiDN is an open distributed network for mutual access to AI compute. A participant can:

- use local GPUs;
- make idle resources available to other participants;
- use remote resources when local capacity is unavailable or insufficient;
- connect local and external inference Providers;
- deploy models and publish network-visible Endpoints;
- run AI agents over local and network resources;
- account for provided and consumed compute in Q.

AiDN must be presented as a network for shared access to AI compute, not as another centralized cloud AI API and not as an investment product.

### 2.2 Approved short-form copy

Primary positioning:

> AI compute, shared.

Supporting statement:

> Connect your hardware, use compute across the network, and let AI agents choose the resources they need.

Q positioning:

> Accounting for shared compute.

Agent positioning:

> Compute for autonomous agents.

Node positioning:

> Turn your hardware into an AiDN node.

### 2.3 Claims policy

The website must not claim:

- guaranteed availability, earnings, yield, returns, or profitability;
- a production capability that exists only as research or an RFC proposal;
- aggregate capacity that the Network API cannot verify;
- independent validation when only a local projection exists;
- finalized Q settlement when only transaction admission is known;
- support for a platform or installation method that has not passed its release gate.

## 3. Audiences and primary actions

| Audience | Primary goal | Primary CTA | Success condition |
| --- | --- | --- | --- |
| Operator | Connect hardware and provide compute | `Run a Node` | Reaches the reviewed Hypervisor installation path |
| Consumer | Find and use AI compute | `Use the Network` | Reaches the Explorer and understands Q requirements |
| Agent Developer | Give an agent controlled access to compute | `Build with AiDN` | Reaches MCP/API integration documentation |
| Contributor | Work on Hypervisor, protocol, Providers, tools, or UI | `Contribute` | Reaches source, contribution guide, and roadmap |

Every page must maintain one dominant question and one dominant next action. Secondary links may support the journey but must not compete with the page goal.

## 4. Product boundaries

The official domain is divided into three applications with distinct responsibilities:

```text
aidn.network
  Public Website
    Home
    How It Works
    Network
    Run a Node
    Build
    Agents
    Research
    Download
    Docs entry

  Web App
    Faucet
    Network Explorer
    Wallet and network utilities (reserved)

  Hypervisor Dashboard
    Separate node-local application
    Operator control plane
```

The Public Website explains and routes. The Web App performs bounded public network interactions. The Hypervisor Dashboard controls an operator's node and must never be embedded into the public website or share its navigation state.

The Public Website and Web App use one design system. The Hypervisor Dashboard may reuse the same component primitives and visual identity while preserving its separate application boundary.

## 5. Canonical route map

| Route | Zone | Purpose | MVP |
| --- | --- | --- | --- |
| `/` | Public | Explain why AiDN matters and route by role | Required |
| `/how-it-works` | Public | Explain the system from install to use | Required |
| `/network` | Public | Show verified network condition and provenance | Required |
| `/run-a-node` | Public | Convert an operator to the installation path | Required |
| `/build` | Public | Route developers to APIs, MCP, and Provider SDK | Required |
| `/agents` | Public | Explain agent discovery and controlled execution | Required, concise |
| `/research` | Public | Separate experiments from production capabilities | Minimal MVP |
| `/download` | Public | Show reviewed releases and supported install methods | Required |
| `/docs` | Public | Task-oriented documentation entry | Required |
| `/app` | App | Web App landing and utilities index | Required |
| `/app/faucet` | App | Obtain initial Q through a wallet-proof flow | Required |
| `/app/explorer` | App | Search published network Endpoints | Read-only MVP |
| `/app/wallet` | App | Reserved for future wallet utilities | Not in MVP |
| `/status` | Shared | Show Website Backend dependency health | Required |

Unknown routes render a useful `404` with links to Home, Docs, Run a Node, and Network. Dependency failures render bounded error states without replacing the whole site with a generic exception page.

## 6. Global navigation

Desktop primary navigation:

```text
AiDN | How It Works | Network | Run a Node | Build | Research | Docs | Open App
```

Mobile navigation must expose the same destinations through a standard accessible menu. `Open App` is visually distinct but not louder than the main `Run a Node` conversion on the Home page.

The footer contains:

```text
Product
  Network
  Run a Node
  Faucet
  Download

Developers
  Documentation
  API
  MCP
  GitHub

Project
  Research
  Governance
  Roadmap

Community
  Approved community links

Legal
  Privacy
  Terms
```

Missing community or legal destinations must not be represented by dead links. Hide them until a real destination exists.

## 7. Home page

The Home page answers: **Why should I care?** It is deliberately short and must not become a network control panel.

### 7.1 Hero

Headline:

> AI compute, shared.

Subheadline:

> Connect your hardware, use compute across the network, and let AI agents choose the resources they need.

Actions:

- primary: `Run a Node` -> `/run-a-node`;
- secondary: `Explore AiDN` -> `/how-it-works`;
- text link: `Read the Docs` -> `/docs`.

The hero may show a restrained topology or hardware/resource visualization. It must not show coins, token prices, fake terminal output, or fabricated live metrics.

### 7.2 Network principle visualization

The first explanatory visual shows reciprocal access:

```text
YOUR COMPUTE
     |
     v
+-------------+
|    AiDN     |
|   Network   |
+-------------+
     ^   |
     |   v
OTHER COMPUTE
```

The enhanced topology contains a local node, remote nodes, an agent, and a Provider. Interaction animates one sequence at a time:

```text
discovery -> request -> execution -> result -> Q accounting
```

Animation is explanatory, not ambient decoration. Keyboard focus and reduced-motion users receive the same information as labeled static states.

### 7.3 Why AiDN

Exactly three short blocks:

**Use**

> Need more compute? Use available AI resources across the network.

**Share**

> GPU sitting idle? Make it available when you are not using it.

**Build**

> Building autonomous agents? Let them discover and select compute dynamically.

### 7.4 Local-first block

Heading:

> Your hardware stays yours.

Body intent: AiDN should use a local resource where it is suitable and permitted. When it is unavailable or insufficient, a user or agent can discover an appropriate network Endpoint.

```text
Task
  |
  v
Local resource suitable and available?
  |-- yes --> local execution
  `-- no  --> AiDN Network --> best eligible Endpoint
```

This section must not imply that remote fallback occurs without user policy, cost limits, permissions, or Endpoint eligibility checks.

### 7.5 Role routes

The final Home section presents the four audience routes from section 3. Each route contains one sentence and one CTA. It must not duplicate the full content of the destination page.

## 8. How It Works

This page answers: **How does AiDN work?**

The primary story has four stages:

1. **Connect** — Install the AiDN Hypervisor. It measures visible hardware and prepares a node-local control plane.
2. **Deploy** — Install a Provider, materialize a model, and create a reproducible Bundle and Runtime Binding.
3. **Publish** — Create an Endpoint offer. Network-visible publication, validation, and finality are distinct states and must be described separately.
4. **Use** — Users and agents discover eligible Endpoints, open Sessions, execute tasks, and account for compute in Q.

The canonical execution relationship is:

```text
Provider Plugin
  -> Provider Instance
  -> Model Deployment
  -> Runtime Binding
  -> Bundle revision
  -> Endpoint configuration/publication
  -> Session
```

The page may simplify labels for a newcomer, but details and tooltips must preserve these identities. A Bundle is not an Endpoint and a published Endpoint is not proof of current runtime health.

## 9. Run a Node

This page answers: **How do I contribute hardware?** It is the primary conversion page.

Heading:

> Turn your hardware into an AiDN node.

The page contains:

1. a support matrix using only release-gated platforms;
2. minimum host requirements and a clear `GPU optional / workload dependent` distinction;
3. the reviewed one-command Ubuntu installation;
4. an explanation of loopback versus trusted-LAN Dashboard access;
5. the post-install path;
6. links to checksums, release notes, and operator documentation.

The current supported public installation target is Ubuntu 24.04 or later. Until another platform completes its release gate, Linux, Docker, and Source tabs may explain status but only Ubuntu is labeled `Supported`.

Reviewed install command template:

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/glinko/AiDN/<reviewed-ref>/tools/aidn-operator-bootstrap-ubuntu.sh \
  | bash -s -- --ref <reviewed-ref>
```

The production website must substitute `<reviewed-ref>` with an immutable reviewed release tag or commit. It must never render `main` as the recommended production install source.

The visual post-install journey is:

```text
Install Hypervisor
  -> connect to the intended network
  -> install Provider
  -> deploy model
  -> create Bundle revision
  -> create Endpoint
  -> request validation where required
  -> publish
```

The page must explain that the installer defaults to loopback, does not modify the firewall, and keeps Provider runtimes loopback-only. A LAN Dashboard bind is for a controlled private network and is not an Internet deployment pattern.

## 10. Providers and Bundles content

Provider explanation:

> AiDN does not require one inference engine. Provider Plugins connect the Hypervisor to local runtimes and external APIs through a bounded integration contract.

Examples may include Ollama, vLLM, llama.cpp, Whisper, external APIs, and community Providers. An example is not automatically a claim of current production support; use the status labels in section 17.

Bundle explanation:

> A Bundle is a complete reproducible description of an AI service deployment.

```text
Provider + Model + Runtime configuration + Endpoint-related deployment inputs
```

Public Endpoint configuration and Bundle revision remain separate identities. A change that affects public behavior creates a new relevant revision and may require new validation or publication. Node-local permissions such as Local Agent Use are not part of Bundle or published Endpoint configuration.

## 11. Network page

This page answers: **Does the network actually exist?**

It shows only metrics returned by the Website Network API with source and freshness metadata. Candidate metrics:

- active Hypervisors;
- active published Endpoints;
- available GPUs by reported class;
- reported available VRAM;
- distinct published models/capabilities;
- verified available compute capacity;
- finalized requests during the last 24 hours;
- finalized Q settled during the last 24 hours.

Each metric carries:

- `value` or `null`;
- `status`: `available`, `partial`, or `unavailable`;
- `observed_at`;
- `source_count` where meaningful;
- a short provenance note.

The UI renders `Not reported` for unavailable data. It must never turn an absent metric into zero. Stale data remains visible only with an explicit stale label and last-observed time.

The page links to `/app/explorer` and to a human-readable status section that explains dependency failures.

## 12. Network Explorer

The Explorer answers: **What can I use?** It is read-only in the MVP.

Supported filters are enabled only when their backing data is authoritative:

- model or capability;
- Provider type;
- GPU class;
- context size;
- price;
- measured or reported latency;
- certification/validation state;
- availability;
- operator reputation.

An Endpoint result contains, when available:

- model/display name;
- Provider type;
- capabilities;
- context and execution limits;
- performance evidence and its source;
- Q price and billing unit;
- validation/certification summary;
- operator reputation summary;
- availability and freshness;
- a `Details` action.

Unknown values render as `Not reported`. Client-side filters must not infer GPU class, latency, context, validation, or availability from display names.

Endpoint details distinguish:

- immutable publication identity;
- current availability observation;
- validation/certification evidence;
- operator identity and reputation;
- pricing/accounting terms;
- source and observation timestamps.

## 13. Agents and MCP

The Agents page explains this loop:

```text
discover -> compare -> select -> execute -> verify -> account
```

Selection factors include capability, model, latency, context, validation, reputation, availability, policy, and Q price.

The page must state that agent autonomy remains constrained by operator policy. An agent must not silently bypass budget, permission, validation, or local-resource rules.

The Build page contains an MCP section with this heading:

> Give your agent control of an AiDN node.

The MCP section may describe approved capabilities such as hardware inspection, Provider installation, model onboarding, Bundle/Endpoint workflows, network status, maintenance, and bounded Q budgets. It must link to `MCP-0001` and the task-oriented MCP quickstart. Financial mutations are always constrained by explicit operator permissions and policy.

## 14. Q content

Heading:

> Accounting for shared compute.

Core explanation:

```text
Provide useful compute -> earn Q
Use network compute    -> spend Q
```

The page or section must explain Q as the network's accounting unit for shared compute. It must not use token-price charts, speculative language, exchange framing, or promises of financial return.

Canonical accounting uses integer `q_atoms`; the website may format values as Q for humans. Admission, pending finality, and finalized settlement are distinct UI states.

## 15. Faucet Web App

The Faucet answers: **How do I get started without Q?**

Route: `/app/faucet`

The visual flow begins with a simple wallet field, but the actual claim requires proof of Wallet control:

```text
Enter Wallet ID and public key
  -> validate their deterministic relationship
  -> request one-time challenge
  -> sign challenge in the user's Wallet/Hypervisor
  -> submit signature and idempotent request ID
  -> policy and budget checks
  -> submit exact network transaction
  -> reconcile until finalized or rejected
```

Current Wallet IDs use the form `wallet-<12 lowercase hexadecimal characters>` and are derived from an `ed25519:<64 hexadecimal characters>` public key. The MVP must not display `aidn1...` as a valid placeholder until a protocol change introduces that address format.

The primary UI is a compact step flow:

1. **Wallet** — Wallet ID and public key, with local format and relationship validation.
2. **Prove control** — challenge, expiry, signing instructions, signature input, and restart action.
3. **Request Q** — amount/policy preview, request action, and non-optimistic progress.
4. **Result** — amount, Wallet ID, request ID, operation ID, transaction hash, and finality status.

The page also shows:

- service state;
- current policy identifier/version;
- paused or low-balance state;
- Treasury activation state;
- next eligible time when the policy exposes it;
- an explanation that a transaction hash is not finality.

The browser never receives the Faucet signer key, Faucet agent token, creator token, signed Treasury envelope, or internal SQLite state.

## 16. Faucet state and error model

Required public UI states:

| State | Meaning | User action |
| --- | --- | --- |
| `ready` | Service and Treasury policy can accept a proof flow | Continue |
| `paused` | Creator paused new claims | Wait; show bounded reason |
| `low_balance` | Treasury watermark blocks claims | Wait; do not retry aggressively |
| `challenge_issued` | Proof challenge is active | Sign before expiry |
| `submitting` | Claim request is in flight | Do not submit a duplicate |
| `pending_finality` | Exact transaction is admitted or unresolved | Reconcile the same request ID |
| `approved` | Transfer reached required finality | Show evidence and next action |
| `quota_exhausted` | Wallet policy denies another claim | Show policy-aware recovery time if available |
| `already_claimed` | Idempotent or policy-equivalent claim exists | Show existing result |
| `rejected` | Proof, policy, or network rejected the request | Show safe reason and permitted recovery |
| `unknown` | Submission result is not yet known | Reconcile; never create a replacement automatically |

Client-side validation improves feedback but never replaces server wallet-proof, policy, abuse, budget, or finality checks.

## 17. Capability maturity labels

All product and research content uses one of these labels:

- `Production` — release-gated and supported in the documented environment;
- `Experimental` — implemented but not a stable production commitment;
- `Research` — hypothesis, prototype, or active investigation;
- `Planned` — approved direction without a working implementation.

Research examples may include distributed model execution, heterogeneous inference, modular neural networks, distributed MoE, state-space architectures, and native distributed AI architectures. They must never appear in Network capacity totals or production CTAs unless their maturity changes through an explicit product update.

## 18. Docs information architecture

Docs are organized by user task. RFCs remain the normative specification layer.

```text
Getting Started
  Install Hypervisor
  Connect to Network
  Get Q

Operators
  Providers
  Models
  Bundles
  Endpoints
  Validation

Developers
  API
  CometBFT
  MCP
  Provider SDK
  Bundle Specification

Network
  Consensus
  Q
  Validation
  Governance

Research
  Distributed Models
  DiPaCo
  Experiments

Specifications
  RFC Index
```

Every task page contains: purpose, prerequisites, one canonical path, verification, common failures, safety notes, and links to deeper specifications.

## 19. Download page

The Download page detects the visitor platform only to select a tab; it never starts a download automatically.

Each release entry contains:

- version or immutable reviewed ref;
- release date;
- support status;
- install command or artifact;
- SHA-256 checksum;
- signature and verification instructions when published;
- release notes;
- known limitations.

If the release feed cannot provide checksum or signature data, the UI states that it is unavailable and does not fabricate a verification badge.

## 20. Design direction

The visual language is infrastructure software, not crypto marketing.

Use:

- calm technical color in both dark and light themes;
- topology diagrams and hardware/resource visualization;
- real network metrics with provenance;
- restrained monospace typography for IDs, code, hashes, and measurements;
- short motion that explains request, execution, result, or accounting state;
- familiar product controls and accessible interaction patterns.

Avoid:

- neon overload;
- generic space backgrounds;
- 3D coins and token-price widgets;
- meaningless terminal text;
- unsupported metric counters;
- vague claims about democratizing AI without explaining the mechanism;
- excessive cards that turn each sentence into a separate container.

The site must meet WCAG 2.2 AA for color contrast, keyboard navigation, focus visibility, semantic structure, form labels, errors, and motion preferences.

## 21. Content system

Product copy lives in version-controlled content modules or MDX, not inside reusable visual components. Each content entry records:

- title and description;
- maturity label where applicable;
- last reviewed date;
- owning product area;
- source links for factual implementation claims.

Rules:

- one section answers one primary question;
- sentences are short and concrete;
- technical terms link to task-oriented explanations;
- normative words such as `MUST` and `SHALL` are reserved for real requirements;
- source code, RPC paths, and commands are copied from reviewed release metadata, not handwritten in several components;
- metrics and release facts are server data, not content strings.

## 22. SEO, metadata, and sharing

Every public route defines a unique title, description, canonical URL, Open Graph metadata, and social image. The MVP provides:

- `robots.txt`;
- generated `sitemap.xml`;
- organization and software JSON-LD where factual;
- semantic heading order;
- stable human-readable URLs;
- no indexing of error pages, preview deployments, or token-bearing callback URLs.

The Web App may be indexed at its landing level, but transaction and result states must not be indexable or encoded with secrets in URLs.

## 23. Analytics and privacy

Analytics must be non-invasive and cookieless by default. The MVP may record aggregate page views, CTA transitions, Web Vitals, route errors, and Faucet funnel stage counts. It must not record:

- Wallet public keys, signatures, challenge values, bearer tokens, request payloads, or transaction proofs;
- full IP addresses in product analytics;
- Hypervisor local addresses;
- free-form operator input;
- cross-site advertising identifiers.

Security and abuse logs are separate backend records with their own retention policy.

## 24. Performance and resilience

Targets for public pages on a representative mobile connection:

- Largest Contentful Paint at or below 2.5 seconds at the 75th percentile;
- Interaction to Next Paint at or below 200 milliseconds at the 75th percentile;
- Cumulative Layout Shift at or below 0.1;
- minimal client JavaScript for content-only routes;
- diagrams and charts lazy-loaded below the fold;
- cached public content remains readable during Network API or Faucet failure.

Network and Faucet failures must not take down the Home, Run a Node, Docs, or Download content.

## 25. MVP scope

Required:

- Home;
- How It Works;
- Run a Node;
- Network;
- Build and concise Agents content;
- Faucet;
- read-only Explorer;
- Docs entry and task taxonomy;
- Download and GitHub/release integration;
- responsive layout;
- dark and light themes;
- accessibility baseline;
- basic SEO;
- non-invasive analytics;
- status, empty, loading, stale, and error states.

Minimal in MVP:

- Research;
- Explorer details beyond authoritative current data;
- community directory.

Out of scope for MVP:

- browser custody of a Wallet private key;
- trading or exchange UI;
- public Hypervisor Dashboard hosting;
- write actions in Explorer;
- speculative earnings calculator;
- social login as a substitute for Wallet proof;
- automatic remote execution without an accepted Session and policy.

## 26. Main user journey

```text
Landing Page
  -> understand AiDN
  -> choose role
       |-- Use ------> Explorer -> Wallet prerequisites -> Faucet -> first Session
       |-- Run Node -> Install -> Wallet -> Faucet -> connect -> first Endpoint
       |-- Build ----> Docs/API/MCP -> integration quickstart
       `-- Contribute -> GitHub -> contribution guide -> roadmap
```

The key quality measure is time from “What is this?” to the first real, verifiable action without requiring the user to read an RFC first.

## 27. Acceptance criteria

`WEB-0001` is implemented when a new user can, without external guidance:

1. explain AiDN as mutual access to local and network AI compute;
2. understand the local-first model and its policy/cost boundary;
3. identify the Operator, Consumer, Agent Developer, and Contributor routes;
4. find the reviewed Hypervisor installation command and support status;
5. understand the real Wallet ID and public-key requirements;
6. complete or correctly begin the Faucet challenge/signature flow;
7. distinguish admitted, pending, rejected, and finalized Q results;
8. find operator and developer documentation by task;
9. see network state with freshness and provenance;
10. distinguish Production, Experimental, Research, and Planned capabilities;
11. reach a working Hypervisor node path without entering the public Web App's internal implementation details;
12. use every critical flow with keyboard navigation and reduced motion;
13. continue reading public content when Network or Faucet dependencies fail.

## 28. Open inputs required before public launch

The implementation may begin without these items, but launch cannot claim completion until they exist:

- approved wordmark/logo and favicon assets;
- final production domain and canonical URL policy;
- public Network Indexer/API deployment and CORS/origin policy;
- Faucet Website Backend credential and abuse-control deployment;
- reviewed immutable Hypervisor release ref;
- published checksum/signature source;
- final privacy and terms destinations;
- approved analytics provider or self-hosted configuration;
- production status-page ownership and escalation path.
