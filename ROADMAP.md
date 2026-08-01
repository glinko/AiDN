# AiDN Roadmap

Last updated: `2026-07-29`

This is the main public roadmap for the repository.

It should stay current and answer four questions:

1. What are we building?
2. What stage are we in now?
3. What milestones come next?
4. What has to be true before we move to the next stage?

The roadmap must also stay aligned with the product-level operator journey defined in [docs/product/UX-0001-hypervisor-operator-journey.md](./docs/product/UX-0001-hypervisor-operator-journey.md).

Paid endpoint consumption and client-facing execution economics must also stay aligned with [docs/product/UX-0002-endpoint-session-and-payment-flow.md](./docs/product/UX-0002-endpoint-session-and-payment-flow.md).

Network-wide economic assumptions, `Q` utility, Session deposits, Network Fees, and operator reward boundaries must also stay aligned with [docs/product/ECO-0000-economic-principles.md](./docs/product/ECO-0000-economic-principles.md).

Epoch reward allocation, recyclable fee/removal handling, Faucet carryover, and service-pool competition must also stay aligned with [docs/product/ECO-0005-q-emission-recycling-and-epoch-reward-allocation.md](./docs/product/ECO-0005-q-emission-recycling-and-epoch-reward-allocation.md).

Service-pool weight formulas, diversity controls, concentration caps, and deterministic reward-mint derivation must also stay aligned with [docs/product/ECO-0004-protocol-service-reward-distribution.md](./docs/product/ECO-0004-protocol-service-reward-distribution.md).

Consensus Stake, active-set selection, equal voting power, validator rotation, unbonding, and objective slashing rules must also stay aligned with [docs/product/ECO-0006-consensus-economics-and-validator-eligibility.md](./docs/product/ECO-0006-consensus-economics-and-validator-eligibility.md).

Wallet ownership, signing semantics, and the separation between Wallet identity and Hypervisor node identity must also stay aligned with [docs/product/RFC-0016-wallet-and-identity.md](./docs/product/RFC-0016-wallet-and-identity.md).

Participant eligibility, reward-bound identity layers, Faucet anti-Sybil constraints, and future reward/voting concentration controls must also stay aligned with [docs/product/RFC-0058-participant-eligibility-and-sybil-resistance.md](./docs/product/RFC-0058-participant-eligibility-and-sybil-resistance.md).

Validation-status issuance, maintenance revalidation, and Validator incentives must also stay aligned with [docs/product/ECO-0003-validation-economics.md](./docs/product/ECO-0003-validation-economics.md).

Wallet balances, escrow state, validation bonds, and future on-chain settlement semantics must also stay aligned with [docs/product/RFC-0036-aidn-ledger-state-machine.md](./docs/product/RFC-0036-aidn-ledger-state-machine.md).

Session settlement semantics, invoice handling, refund rules, and accounting-state transitions must also stay aligned with [docs/product/RFC-0037-settlement-engine.md](./docs/product/RFC-0037-settlement-engine.md).

Session failure classification, recovery windows, disappearance handling, mismatch termination, and evidence-backed forced settlement must also stay aligned with [docs/product/RFC-0060-session-failure-recovery-and-forced-settlement.md](./docs/product/RFC-0060-session-failure-recovery-and-forced-settlement.md).

Canonical Ledger operation envelopes, state-transition semantics, fees, idempotency, and replay protection must also stay aligned with [docs/product/RFC-0059-ledger-operation-catalog.md](./docs/product/RFC-0059-ledger-operation-catalog.md).

Usage reporting, accounting transparency, checkpoint acknowledgement, mismatch handling, and opaque proxy billing must also stay aligned with [docs/product/RFC-0051-usage-reporting-and-verification-protocol.md](./docs/product/RFC-0051-usage-reporting-and-verification-protocol.md).

Capability Runtime service boundaries, Runtime identity, Runtime ownership, and Runtime isolation rules must also stay aligned with [docs/product/RFC-0053-capability-runtime-specification.md](./docs/product/RFC-0053-capability-runtime-specification.md).

Hypervisor-to-Runtime registration, Session execution, streaming, usage-report transport, health, and recovery semantics must also stay aligned with [docs/product/RFC-0054-capability-runtime-protocol.md](./docs/product/RFC-0054-capability-runtime-protocol.md).

Provider-plugin manifests, Provider Instance lifecycle, Model Deployment lifecycle, installation recipes, and plugin trust boundaries must also stay aligned with [docs/product/RFC-0055-provider-plugin-system-and-directory.md](./docs/product/RFC-0055-provider-plugin-system-and-directory.md).

Provider-plugin control-plane and execution-plane runtime adapter semantics must also stay aligned with [docs/product/RFC-0056-provider-plugin-runtime-interface.md](./docs/product/RFC-0056-provider-plugin-runtime-interface.md).

Registry peer replication, deterministic inventories, completeness manifests, and Proof of Registry challenge mechanics must also stay aligned with [docs/product/RFC-0061-registry-replication-protocol.md](./docs/product/RFC-0061-registry-replication-protocol.md).

Snapshot production, commitment, trusted-checkpoint State Sync, and atomic state restoration must also stay aligned with [docs/product/RFC-0062-snapshot-and-state-sync-protocol.md](./docs/product/RFC-0062-snapshot-and-state-sync-protocol.md).

Authenticated messaging, Route Generation, bounded queues, delivery tracking,
persistent deduplication, Dead Letter handling and Provider Plugin network
isolation must also stay aligned with
[docs/product/RFC-0042-aidn-hypervisor-network-protocol.md](./docs/product/RFC-0042-aidn-hypervisor-network-protocol.md).

Milestones still describe technical delivery order, but feature sequencing and UI priorities should preserve that operator journey whenever reasonably possible.

## North Star

AiDN is moving toward a decentralized network of trusted AI compute nodes.

In the target system:
- any hypervisor node can join the network;
- each node can publish its resources, installed models, providers, pricing, and operational status;
- agents discover the best execution target through the network, not by hard-coding a single node;
- routing depends on availability, trust, latency, price, and policy;
- node operators earn `q` compute units for useful work;
- trust, rating, and wallet settlement support sustainable network growth.

The distributed registry is a target architecture, not the first milestone.

## Current Stage

Status: `M1-M10 complete, M8 target architecture`

Product alignment summary:
- the new RFC set is now authoritative for service, capability, runtime, registry, marketplace, verification, reputation, ledger, and settlement architecture;
- the current repo is introducing a compatibility-first overlay so existing bundle/provider execution keeps working while canonical service/capability/runtime models become the primary public contract;
- the current operator-facing architecture slice is now a Provider Plugin System with first-class `ProviderPlugin`, `ProviderInstance`, `ModelDeployment`, and `RuntimeBinding` entities layered over the current execution core;
- bundle registration remains important in the current codebase, but it should now be treated as a compatibility execution projection rather than the long-term public operator contract;
- future registry, marketplace, verification, reputation, and epoch work should build on canonical advertisements and service/runtime records rather than deepening bundle-centric contracts;
- the repo now has a strong local hypervisor and operator-dashboard foundation;
- guided onboarding now lands operators inside a working endpoint-first bootstrap loop;
- `Home`, `Providers`, and `Bundles` now behave as endpoint-first agenda and preparation surfaces that hand deep lifecycle control into `Endpoints`, and `Providers` now exposes the first guided `plugin -> provider instance -> model deployment -> runtime binding -> endpoint` setup flow while preserving bundle compatibility underneath;
- the next product layer after this shell consolidation is trust, rating, validation publication, and richer market depth on top of the canonical endpoint workspace;
- the next product-critical gap is no longer the bare first-run bootstrap loop or shell ownership ambiguity, but trust/reputation publication and endpoint lifecycle depth on top of the consolidated operator surface;
- endpoint publication is now a first trust layer, and paid consumption now has a working first Session contract;
- validation economics and maintenance-validation policy are now defined at the product level, and the first computed reputation publication layer now projects trust through registry, discovery, and operator market surfaces;
- epoch reward allocation, recyclable protocol removals, and Faucet carryover are now defined at the product level, so upcoming consensus/registry reward work can land on one supply model instead of mixing direct fee passthrough with pool-based issuance;
- service-pool reward formulas are now documented in `ECO-0004`, so future Consensus, Registry, and Validation reward implementation can share one deterministic weighting, diversity, and cap model instead of embedding separate payout heuristics in each subsystem;
- consensus validator economics are now documented in `ECO-0006`, so future Validator Set selection, equal voting-power enforcement, Stake lifecycle, downtime handling, and slashing implementation can build on one deterministic eligibility model instead of scattering security rules across consensus adapters and app logic;
- participant identity hierarchy, Hypervisor/Service eligibility states, and anti-Sybil design constraints are now documented in `RFC-0058`, so future Faucet, Registry, Validation, and Consensus reward work can share one eligibility model instead of each inventing local heuristics;
- the canonical Ledger operation inventory is now documented in `RFC-0059`, so future consensus, settlement, reward, Faucet, validation, and suspension work can land on one state-transition catalog instead of duplicating operation semantics across RFCs;
- the Capability Runtime service model is now documented in `RFC-0053`, so future runtime packaging, runtime authorization, runtime replacement, and multi-runtime capability work can share one architectural contract before wire-level protocol details;
- the Hypervisor-to-Runtime boundary is now documented in `RFC-0054`, and its first durable protocol core now enforces approved Binding/route identity, handshake version negotiation, semantic replay protection, Request admission/idempotency, Usage chains and explicit recovery plans/results;
- registry replication is now documented in `RFC-0061`, so future Full Registry eligibility, anti-entropy, completeness proofs, challenge evidence, and repair synchronization can build on one deterministic storage and retrieval model instead of scattered service-local heuristics;
- snapshot and fast State Sync are now documented in `RFC-0062`, so future node bootstrap, corruption recovery, trusted checkpoint handling, and portable state restoration can build on one verification-first protocol instead of ad hoc database-copy assumptions;
- validation, marketplace, remote execution, and paid sessions should stay explicit operator actions layered on top of that core flow, not replace it.
- RFC-0042 v0.3 makes the Network Dispatcher the next infrastructure layer: the
  first implementation slice covers transport-independent envelopes, domain and
  payload validation, Route Generation, bounded admission, local delivery,
  delivery records, replay protection and Dead Letter metadata before physical
  QUIC/TLS gateways are added.

We already have a working local hypervisor foundation:
- local task queue and admission control;
- local resource accounting for `CPU`, `RAM`, and `VRAM`;
- provider-plugin adapter infrastructure plus bundle-compatibility execution abstraction;
- first-class Provider Plugin, Provider Instance, Model Deployment, and Runtime Binding inventory with snapshot/restore persistence;
- schema-driven Provider install forms, Installation Recipe prefill, approval records, permission acknowledgement, explicit permission/sandbox upgrade review acknowledgement, signed package verification, package-identity binding, sandbox-policy binding, executor-declared sandbox boundary compatibility, bounded declarative subset enforcement for `networks`, `health_checks`, and `resource_limits`, secret-handle selection, dry-run diagnostics, executor-level local-import readiness diagnostics, controlled local artifact staging/list/remove APIs, controlled staged-archive extraction, a shared immutable Model Artifact Store with SHA-256 promotion/deduplication, immutable multi-file Model Artifact Sets, deployment binding, reference-aware removal, and explicit fail-closed grace-period GC, plus `model-artifact://` materialization and persisted per-Provider-Instance Artifact Set materialization records, rollback preview, rollback execution/job replay for terminal install jobs, rollback step/timestamp persistence, apply jobs, a first opt-in host-mutating `ControlledFilesystemProviderInstallationExecutor` that prepares controlled volume directories, staged model-download manifests, bounded local artifact imports, and bounded staged-archive extraction inside one root path, and a non-host-mutating `SandboxEnforcedProviderInstallationExecutor` default path;
- Model Deployment artifact-materialization readiness now gates Runtime Binding creation for artifact-backed deployments, while artifact-free deployments remain compatible and the Provider dashboard exposes missing/ready/failed materialization state before operators create a Runtime Binding;
- Endpoint Draft creation from Runtime Binding now uses a single provider-to-endpoint admission result covering Runtime readiness, Artifact materialization, compatibility bundle projection, owner wallet, Capability compatibility, pricing warnings and publication-policy blockers, with API `409` details and dashboard readiness chips before operators create the draft;
- Endpoint Configuration publication now has a separate fail-closed readiness gate: owner/signature binding, visibility and external-access consistency, proxy target binding and validation-policy compatibility block invalid signed publications, while missing external pricing, paid-deposit policy and public discoverability remain explicit operator warnings in API and dashboard views;
- guided provider setup handoff from approved/apply Provider plan to model discovery, Runtime Binding creation, and Endpoint draft creation;
- subprocess-backed runtime lifecycle and operator controls;
- agent allocation leases;
- agent capability catalog for local discovery, including endpoint readiness, resource fit, node pricing/custom-model policy, and bundle provider/model identity;
- install job execution for local model artifacts.
- centralized registry advertisement, heartbeat freshness, and discovery API;
- registry discovery now preserves bundle plugin identity alongside provider/model metadata, so agents can distinguish adapter families without a second node-local lookup;
- registry discovery now also exposes a flattened `candidates` view so agents can consume node-plus-bundle execution options without walking nested `nodes[].bundles[]` payloads;
- flattened registry candidates now support execution-readiness filtering for allocation support, queue support, and ready endpoint availability;
- the operator dashboard now ships as a terminal-style multi-node control room with `Home / Fleet / Market`, a persistent command rail, right-side selection inspector, and lower-band operational cards on top of the current hypervisor and registry contracts;
- the operator dashboard wallet surface is now a live inline console with `Usage / Settlements / Disputes / Quote` tabs, opening from the rail or lower operations band without leaving the main shell;
- the operator dashboard now also includes a live `Requests` workspace for queue triage, recent-task inspection, admission visibility, persisted spillover policy, and market spillover preview inside the main operator shell;
- the operator dashboard now also includes a first `Endpoints` workspace, so visibility, publication, and validation can be reviewed as separate operator decisions instead of being folded into bundle or market views;
- a parallel endpoint-first package now exists with snapshot-backed manifest storage, lifecycle service methods, and a versioned `/api/v1/endpoints` API on the main app surface;
- the `Endpoints` dashboard workspace can now prefer the endpoint-first service and versioned API for visibility, publication, and validation actions, while legacy bootstrap routes remain as transition fallback;
- guided dashboard onboarding now persists operator bootstrap state, derives a canonical onboarding read model, advances through wallet/provider/bundle/endpoint milestones, and returns to `Home` after the first published local Endpoint;
- the first Provider workspace transition now reframes the setup path as `provider plugin -> provider instance -> model deployment -> runtime binding -> endpoint`, while the older bundle path remains as a compatibility execution surface;
- wallet-signed endpoint configuration publication now exists as a first trust layer with publish/revoke/export APIs, registry-visible current configuration hashes, and live proof comparison surfaces;
- the operator dashboard `Endpoints` workspace now exposes local-vs-published configuration sync state, so operators can see whether local edits have drifted from the last published network-visible claim;
- basic node pricing publication in registry discovery;
- operator wallet quote, usage event, and export contract;
- automatic wallet metering from task execution when usage metadata is available;
- usage events linked to `task_id` and `allocation_id` for stronger lease attribution.
- wallet attribution can now derive owner identity from an active allocation lease when `wallet_owner_id` is not passed explicitly;
- task submission with `allocation_id` now routes through the active lease bundle and rejects inactive allocations;
- allocation activation now emits a wallet-facing journal hook with lease metadata for both direct activations and pending-lease promotion;
- allocation activation is now exported through a dedicated replay-safe wallet stream with the same cursor contract used by usage and settlement exports;
- allocation `release` and `expire` now emit settlement-facing wallet finalization events with aggregated spend snapshots;
- allocation finalization now uses a grace period before settlement closure, so late spend can still be absorbed before the event becomes `closed`;
- closed allocation settlement events can now be reopened manually into a fresh grace window with dispute metadata, so operators can absorb late usage corrections without rewriting history;
- allocation settlement now supports a longer-lived dispute overlay plus a dedicated replay-safe dispute stream, so operators can freeze auto-closure, record dispute lifecycle changes, and resolve them without changing the core `grace/closed` contract;
- real `ollama`, `llama.cpp`, and `whisper` adapters now emit provider-facing `usage` contracts with explicit `exact` vs `estimated` measurement metadata;
- provider adapters now publish a declarative `usage_contract` in plugin descriptions so operators and future routers can see exact/estimated metering capability before execution;
- validated metering metadata with `measurement_kind` and `measurement_source`;
- invalid provider usage payloads skipped safely without failing completed tasks.
- provider contracts can now opt into `missing_usage_behavior=strict_accounting`, which keeps the task completed but marks the result `unbillable` and settlement-blocked when usage is missing or invalid;
- settlement export now exposes monotonic `sequence_id` cursors, retention window metadata, and stale-cursor detection.
- paid endpoint sessions now support explicit create/close lifecycle, deposit lock/release, queue-vs-busy admission, no-request minimum fee, idle timeout auto-close, and usage-linked refund settlement;
- paid Session contracts now preserve accepted Marketplace identity through `advertisement_id`, optional `offer_id`, pricing/accounting hashes, deterministic `session_contract_hash`, and immutable `session_contract` Registry Object references shared by Session and Settlement evidence;
- accounting contracts now ship as deterministic registry-style objects with stable object IDs, payload hashes, pricing policy references, and Session-level object-reference preservation alongside local snapshots;
- RFC-0051 now has a first canonical evidence core: four-state Usage Availability, dimension-specific Authority, Runtime Usage Profiles, pre-admission Contract/Profile compatibility, fixed and variable charge evaluation, signed RFC-0054 acknowledgments, durable conflict evidence and mandatory Final Usage before terminal Runtime transition;
- RFC-0037 now has a canonical integer-`q_atoms` Settlement core with separate Endpoint Payment and Network Fee reserves, request-first charge records, terminal/fallback policy enforcement, Request/Session ceilings, Endpoint-absorbed excess, bounded dispute reserves, atomic conservation and Validation-zero evaluation; canonical escrow locks and settlement transitions now mutate persisted `q_atoms` wallet balances through idempotent Ledger operations, while Session Contract v2 explicitly binds Endpoint Payment and Consumer refund beneficiaries;
- MVP-0001 now narrows the paid launch profile to one fixed-price Request per prepaid Session, Final Usage, canonical escrow, cooperative proposal/accept/finalize, and conservative timeout settlement; unsupported metered, multi-request and legacy float-Q bridge paths are explicit rather than implied;
- MVP-0001 fixed-price Sessions now hash-bind exact `fixed_price_q_atoms` and `request_charge_ceiling_q_atoms`, derive canonical Request Settlement inputs from terminal Runtime Result plus accepted Final Usage, and finalize cooperative settlement through ledger proposal/accept/finalize while closing the local Session snapshot;
- MVP-0001 now exposes a public finalize API and end-to-end paid-session smoke path for `Endpoint -> MVP Session -> Runtime Result -> Final Usage -> cooperative Settlement`, including exact q_atoms wallet release/refund checks;
- MVP-0001 finalize paths now reject missing Final Usage, Usage conflicts, wrong Endpoint/Session bindings and duplicate payouts, and expose timeout-based forced settlement for Endpoint-unavailable refunds and completed fixed-price Consumer timeouts;
- MVP-0001 persistence now preserves Runtime evidence, canonical funding, settlement operations, forced-settlement records, Endpoint manifests, closed Session snapshots and released Deposit snapshots across app-level restore, with duplicate cooperative and forced finalization rejected after restart;
- MVP-0001 task execution now records a compatibility Runtime evidence envelope from real completed endpoint tasks, producing a terminal Runtime Request plus mandatory Final Usage Report for the existing finalize API without seeded test evidence, while rejecting a second Runtime Request for the same MVP Session;
- MVP-0001 now has a one-call paid smoke API that opens a fixed-price Session, submits the first endpoint task, returns Result/Runtime evidence/Final Usage/Settlement readiness, and can either auto-finalize or leave the Session ready for explicit finalize;
- the operator dashboard `Endpoints` workspace now exposes the one-call `MVP-0001` paid smoke path with fixed-price defaults, auto/manual finalization mode, visible Task Result, Runtime evidence, Final Usage, Settlement readiness, cooperative finalize, and completed fixed-price timeout force-finalize controls;
- the operator dashboard `Sessions` workspace now exposes the MVP-0001 Endpoint-unavailable timeout refund path for no-request Sessions with canonical funding, including force-after/now controls and explicit eligibility diagnostics;
- canonical capability definitions now ship with stable definition hashes, and published endpoint advertisements now bind to projected feature, limit, and implementation profile hashes inside registry-visible canonical overlays;
- canonical overlay and node advertisement payloads now also expose immutable local Registry Object envelopes for capability definitions, endpoint profiles, and accounting contracts, giving later persistence and replication work a stable object identity layer to build on;
- registry-backed object views now support deduplicated `object_id` lookup, filtered listing, durable local snapshot persistence, and a versioned local completeness summary over the standalone store, while manifest identity, retention policy enforcement, and replication remain the next gaps;
- registry-backed object views now also support opt-in canonical payload retrieval for projected capability, profile, and accounting objects, so object inspection no longer stops at envelope metadata;
- `RegistryService` now also maintains a standalone local Registry Object store with snapshot-backed durable persistence, and local operator object routes ingest projected canonical objects into that store while preserving local node provenance for returned sources;
- the operator dashboard now includes a dedicated `Sessions` workspace with reservation composer, session control actions, session-bound task launch, activity timeline, and settlement preview telemetry;
- wallet exports now include a unified replay-safe ledger stream that stitches session settlement events together with usage and allocation-family wallet events;
- proxy-backed paid Sessions now preserve upstream session policy snapshots, lazily broker remote Session opens, propagate remote Session close on manual and idle-driven release, and expose proxy-session bindings through task and operator-session APIs;
- endpoint lifecycle now supports symmetric proxy attach and detach actions, so operators can revert a proxied Endpoint back to local execution without editing manifests manually;
- preferred remote routes can now be detached explicitly, but live local proxy endpoints still protect their upstream dependency until the operator detaches the proxy route first;
- session failure, recovery, and forced-settlement semantics are now documented in `RFC-0060`, so the next session-hardening slice can implement `SESSION_FORCE_SETTLE` against one authoritative checkpoint, timeout, and evidence model instead of local heuristics;

What is still missing in the current stage:
- bind derived canonical Settlement terms (including scaled `audio_input_seconds` milliseconds) into a separately accepted variable-price Session profile; the current public `MVP-0001` profile remains fixed-price;
- RFC-0051/RFC-0037 alignment remains partial beyond the new evidence and deterministic Settlement cores: legacy Session reports and float-Q close paths are still compatibility projections, while canonical bridge ingestion, network proposal/acceptance, consensus Ledger finality, Checkpoint/correction/dispute workflows, statistics and Marketplace transparency remain incomplete;
- rating publication, reputation policy, and validation economics implementation;
- Validation Report custody migration: deterministic compact commitments, report hashes, stable logical locators, snapshot metadata, a controlled local content-addressed report store and opt-in Ed25519 Storage Receipts now exist alongside legacy local reports; full report custody still duplicates compatibility data in the general Hypervisor state snapshot, submission still derives Certification in one call, and assignment-key transfer/custody challenges remain to be implemented under `docs/superpowers/plans/2026-07-18-validation-report-custody.md`;
- network-visible custom model onboarding workflow.
- broad host-mutating Provider install executors remain deferred: the repo now has an opt-in controlled-filesystem executor that writes installation state, prepares controlled volume directories, stages model-download manifests, promotes local files into a shared immutable Model Artifact Store, and materializes them into provider volumes only inside one configured root path; shell, container, download, package-manager, and plugin-installer execution still need a broader sandboxed apply backend before enablement;
- final onboarding polish across the remaining operator workspaces, so the new guided layer feels native outside `Home` and handoffs stay consistent across `Providers / Models / Endpoints` even while `Bundles` remains as a compatibility execution surface;
- full endpoint-first persistence and API beyond the current bootstrap/dashboard slice, so privacy, sharing, publication, and validation remain distinct all the way through the service contract;
- complete dashboard migration of older bundle-centric affordances onto the endpoint-first trust layer, so bootstrap fallback logic can eventually be removed cleanly;
- remote endpoint and proxy endpoint workflows framed as operator routing tools, not only discovery data.
- full client-facing payment confirmation and paid-session workflow polish across bootstrap, remote/proxy, and future marketplace paths.
- capability/profile alignment is still partial:
  - canonical capability definitions and endpoint profile hashes now exist in local projections and node advertisements;
  - but they currently exist only as locally persisted projected Registry Objects, not yet as authoritative RFC-native objects validated through Service Verification or enforced as the sole Capability/Marketplace policy source.
- registry-object alignment is still partial:
  - the repo now has deterministic Registry Object envelopes plus registry-backed list/query/get, opt-in payload retrieval, and standalone local snapshot-backed durable object persistence for capability/profile/accounting artifacts;
  - but it still lacks manifests, retention policy enforcement, and replication of those objects as first-class protocol data.
- implementation of `RFC-0044` is still pending beyond partial local scaffolding:
  - accepted Session contracts now persist as immutable local Registry Objects and settlement/open payloads reference those objects;
  - but amendment/version chains, remote contract exchange, and full forced-settlement lifecycle semantics remain unimplemented.
- implementation of `RFC-0058` is still pending beyond partial local scaffolding:
  - Wallet ownership and separate Hypervisor node identity exist;
  - local Faucet claim flow now exists at the app level;
  - but reward beneficiary wallets, activation age, service-level eligibility states, known-control-group aggregation, concentration caps, and collateral-driven anti-Sybil enforcement are not implemented yet.
- implementation of `ECO-0004` is still pending beyond current reward scaffolding:
  - the repo already has epoch transition records, reward-mint records, Faucet payout flow, validation reputation inputs, and the first ledger-shaped reward stream;
  - but there is still no deterministic service-pool calculator for Consensus, Registry, and Validation weights, no diversity-factor reduction, no capped proportional distribution by Known Control Group, and no finalized reward-calculation commitment root matching one shared economic spec.
- implementation of `ECO-0006` is still pending beyond the current consensus scaffolding:
  - the repo already has consensus integration architecture, validator-set update operations, stake-shaped ledger concepts, and product-level rules for consensus rewards and suspension consequences;
  - but there is still no finalized Candidate-to-Active selection engine, no equal-voting-power active-set enforcement by Known Control Group, no deterministic downtime/suspension/unbonding pipeline, and no complete evidence-driven slashing flow matching one canonical consensus-economic spec.
- implementation of `RFC-0061` is still pending beyond current registry and discovery scaffolding:
  - the repo already has centralized registry advertisement, discovery APIs, freshness tracking, endpoint publication visibility, and reward-facing Registry concepts at the product layer;
  - but there is still no authenticated Registry peer replication protocol, no deterministic Inventory Root and segment-manifest system, no completeness manifest pipeline, no formal Proof of Registry challenge/confirmation flow, and no repair/catch-up replication engine matching one canonical protocol spec.
- implementation of `RFC-0062` is still pending beyond current snapshot mentions:
  - the repo already has product-level Snapshot commitments, state-hash concepts, and consensus-side acknowledgment that verified Snapshots can accelerate synchronization;
  - but there is still no portable canonical Snapshot format, no trusted-checkpoint State Sync flow, no chunked multi-source Snapshot transfer, no staging restoration pipeline, and no atomic verified activation path matching one canonical state-sync protocol.
- implementation of `RFC-0059` is also still pending beyond partial local scaffolding:
  - a canonical local ledger-operation stream now exists for Faucet, session, validation, endpoint lifecycle, endpoint Advertisement and Offer publication, epoch transition, and faucet reward mint flows;
  - but there is still no finalized evidence replay-protection registry, full operation-by-operation consensus execution engine, or complete `SESSION_FORCE_SETTLE` and enforcement implementation.
- implementation of `RFC-0053` is still pending beyond current runtime abstractions:
  - the repo now has canonical Runtime IDs separate from Runtime Binding IDs and Instance IDs, explicit Runtime Generation, deterministic Runtime Configuration and Binding hashes, implementation classes, Plugin/Provider/Model/Adapter provenance, and Dispatcher checks that reject stale Runtime and Route Generations;
  - existing snapshots remain compatibility-loaded as Runtime Generation 1, and current bundle execution remains a transitional projection;
  - Runtime Instance persistence, full readiness/Health profiles, one-capability conformance, state generation, Runtime verification and authenticated execution-plane registration remain to be implemented.
- implementation of `RFC-0054` is now partially complete:
  - the repo has an authenticated, externally verified Runtime handshake over pre-approved Runtime Bindings and Dispatcher routes, protocol negotiation, Runtime/Configuration/Binding/Route checks, semantic Runtime Message IDs and monotonic replay protection;
  - durable execution admission now validates external Session/Endpoint/Accounting authorization, exact Capability binding, deadlines, required features and conflicting Request IDs;
  - dimension-specific Usage authority, ordered Usage hash chains, acknowledgments, Recovery State/Plan/Result persistence and explicit Route Generation rebinding are implemented;
  - Runtime Ready, multidimensional Health and Capacity records now validate approved connection/runtime/route identity, enforce monotonic observation sequences and persist across restart; signed Runtime Result objects require matching accepted Final Usage Reports, persist across restart and arrive through the scoped Local IPC/Dispatcher authorization pipeline. Cancellation commands and honest Runtime cancellation results are durable and idempotent, distinguish output suppression from confirmed Provider stop, and cannot replace the Final Usage/Result evidence required for Settlement. Signed stream open/chunk/close events enforce strict ordering, content hashes and a deterministic close root before a Runtime Result may reference streamed output. Content-addressed Artifact declarations persist through Local IPC/Dispatcher ingress and a Result can reference only an Artifact declared for its own Request. Session-scoped State Checkpoints and signed Recovery State are durable, sequence-checked and restored across restart; resumed Requests may reference only matching checkpoints. Runtime Drain and Shutdown commands are durable: draining blocks new assignments while allowing terminal evidence, and graceful shutdown requires Drain Complete. A reusable Runtime Protocol Conformance Harness records success, expected protocol errors, semantic redelivery checks and expected transport failures for Adapter profiles. It now exercises a lost Usage-acknowledgment retry against the real service, proving one durable report and a duplicate acknowledgment, plus stale-route rejection. Windows Named Pipe and Unix socket Local IPC profiles now use bounded JSON NetworkMessage frames through the same ingress/Dispatcher boundary; Named Pipe additionally authenticates its pipe with authkey. Direct remote Runtime routes now have an explicit `REMOTE_RUNTIME` type and scoped sender registration through the same Dispatcher queue, replay and generation checks. Remote Runtime profiles now also have a bounded framed-JSON mTLS listener: TLS 1.2+, validated server identity and mandatory client certificates protect transport, while all accepted envelopes still use the same scoped ingress/Dispatcher boundary. The llama.cpp Adapter now translates OpenAI SSE completions into ordered RFC-0054 stream evidence, a deterministic final root and observable delivered-byte Usage; it records only `CANCELLATION_PENDING` with unknown Provider state for ordinary `/v1/completions`, redelivers an existing final Result without another upstream request, and supports a durable terminal-only Recovery State/Plan/Result cycle. Ollama and vLLM now have explicit approved-dispatch boundaries through their native and OpenAI-compatible protocols, with attached-service discovery, Health, Runtime Binding projection and provider-specific Usage provenance. Their execution timeout is independent from short Health/discovery probes. Native-adapter fault profiles now prove that Ollama, vLLM and standard llama.cpp completion APIs never claim confirmed cancellation or in-flight recovery without a Provider operation handle; the Proxy adapter retains confirmed cancellation and status recovery only when such a handle is actually supplied.
  - Real-provider conformance now proves the public `MVP-0001` paid path against attached llama.cpp, vLLM and Ollama: signed publication and Session authorization, fixed-price escrow, approved Runtime execution, durable restart and cooperative Settlement all complete without re-executing or paying a Request twice. Ollama Runtime Binding projection now maps Capability `llm.chat` to scheduler workload `llm_text`, closing the native-adapter admission mismatch discovered by the live smoke.
- implementation of `RFC-0055` and `RFC-0056` is now partially implemented:
  - the repo now has first-class Provider Plugin metadata, immutable Plugin Release records, package-bound local Installed Plugin approval records with deterministic permission hashes and Installation Generation, Provider Instance and Model Deployment inventory, Runtime Binding objects, declarative install/attach schemas, Installation Recipes, approval/apply job records, permission/sandbox upgrade acknowledgement, sandbox-policy binding, executor-declared sandbox boundary compatibility, runtime-binding-to-bundle compatibility projection, model discovery, Runtime Binding creation, Endpoint draft handoff from the Provider workspace, controlled local artifact staging, bounded staged-archive extraction, shared immutable Model Artifact Store promotion/deduplication, multi-file Model Artifact Sets, deployment binding, reference-aware removal, explicit fail-closed grace-period garbage collection, `model-artifact://` provider-volume materialization, persisted per-Provider-Instance Artifact Set materialization records, and fail-closed Runtime Binding admission for artifact-backed Model Deployments whose Artifact Set has not been materialized;
  - RFC-0056 v0.4 now defines staged Plugin Host conformance, install-specific local authentication, one RFC-0042 envelope, persistent Plugin Operations and an RFC-0053-bound, separately authenticated RFC-0054 Runtime Adapter identity;
  - Release registration records signed metadata only. It does not download, unpack, load or execute a package. Existing in-process adapters remain explicitly transitional and must not be represented as sandboxed community packages;
  - optional in-memory and durable local filesystem content-addressed Package Stores now verify staged package bytes against the declared SHA-256 digest, atomically persist verified bytes, re-verify them at read time and fail-close package activation when configured. Trusted Ed25519-signed Plugin Releases now retain their verification state and may be acquired through a bounded, credential-free HTTPS source with redirects rejected before content-addressed staging. Public immutable Plugin Release metadata is deterministically projected into the Registry `plugin` namespace and can be batch-published without exposing local installation or credential state. A bounded operator-initiated peer pull now imports hash-verified public Plugin Release objects while resetting trust to local `UNVERIFIED`; a peer cannot grant its packages local execution trust. The Registry Replicator now performs bounded inventory-to-object retrieval, validates received immutable envelopes and can invoke a typed Plugin Release subscriber only after storage; imported metadata still cannot install, launch or promote trust for a package. Operators can also reconcile Plugin Releases already present in the local Registry through one explicit endpoint. The Hypervisor now also provides a scoped Plugin Host identity/handshake contract, ephemeral or Secret Manager-backed install-scoped activation secrets with HMAC proof verification and nonce replay rejection, bounded JSON wire adapter, Windows Named Pipe and Unix-socket Local IPC listeners, persistent connection recovery, stale-generation revocation, constrained Provider/model/Runtime Binding control commands, and read-only operator status without credential-key disclosure. Legacy built-in Plugin Hosts may launch an operator-supplied private managed process with the activation secret delivered only through its environment, never through dashboard or status payloads. A `PACKAGE` installation now derives its launch only from a signed package-relative Python entrypoint: it requires a trusted Ed25519 release, durable filesystem package storage, `SANDBOX_REQUIRED`, a verified bounded ZIP extraction and revalidation of the content-addressed runtime tree before each launch. It runs through a restrictive Docker boundary with a read-only package mount, non-root UID, no network and dropped capabilities; unsupported filesystem, egress and secret policies fail closed. The descriptor is replicated as immutable release metadata but an imported peer release remains locally untrusted.

Immediate priorities:
0. Finish the public paid-MVP hardening pass on top of the new Wallet Identity
   Binding slice: replicate canonical `wallet_identity` objects from the
   local durable registry view into authoritative network state before
   multi-node paid launch. Local registry-backed resolution, write-through
   publication, durable conflict evidence and fail-closed cross-node conflict
   rejection now exist, and a minimal peer export/import sync path can already
   transfer wallet identity objects plus known conflict evidence, including a
   peer-initiated pull sync call. Known peers can now be durably configured and
   repaired through one bounded automated pass with per-peer sync status, and
   the composed Hypervisor peer-pull control path can now require expected
   remote node, operator and owner-wallet identities. When present, those
   values require a hash-bound Ed25519 envelope and reject a mismatch before
   any import; a controlled two-host deployment has verified successful signed
   import and fail-closed node mismatch rejection. This is not independent
   authority or consensus-finality evidence. Persisted configured peers now
   forward their pins during automated repair; unpinned peers remain a local
   compatibility path, not a public directory authority. Registry node
   advertisements can now bootstrap that inventory while excluding the local
   node. Operators can
   also inspect a bounded wallet
   registry node advertisements can now bootstrap that inventory while
   excluding the local node. Operators can also inspect a bounded wallet
   identity reconciliation report instead of raw object/conflict state and can
   now apply a durable local conflict resolution for one selected wallet
   binding. A minimal quorum proposal/approval flow now also exists for that
   same wallet binding, and those quorum proposal/approval/final-resolution
   records now replicate through the same wallet-identity sync path as
   hash-bound identity objects. Quorum proposals and approvals are now
   fail-closed on Ed25519 signatures verified against the registered wallet
   identity bound to each voting node's `operator_id`, and quorum admission
   now derives the authoritative voter set from the current source nodes
   advertising the chosen wallet binding. Each authoritative voter node must
   now also advertise `owner_wallet_id`, and that owner wallet identity must
   resolve to the same public key as the node's `operator_id` identity before
   quorum authority is accepted. The Registry now also exposes a local wallet
    identity governance policy that snapshots the active voter-status and quorum
    floor rules used by each proposal. Quorum finalization now emits a portable
    Governance Certificate that commits the policy hash, voter keys, candidate,
    quorum and signed vote set; it is replicated as a Registry object and
    re-verified before an imported Resolution changes local identity state.
    In the composed Hypervisor application, finalization also creates an
    idempotent `GOVERNANCE_AUTHORIZATION_COMMIT` Ledger operation and records
    that reference in the Certificate. A strict local policy can now require
    both quorum evidence and a locally known Ledger commitment before applying
    a Resolution. A certificate can now be revoked only by a second quorum of
    the original voter set; the revocation is replicated as a Registry object,
    emits `GOVERNANCE_AUTHORIZATION_REVOKE` and removes the affected Resolution.
    Operators can retrieve local Ledger proofs for both certificates and
    revocations and compare their deterministic commitment subjects with each
    configured Registry peer. Peer reports reject malformed records and
    classify matching, mismatched, unavailable and invalid observations. Registry
    and Hypervisor read models now have a fail-closed verified-finality source
    boundary: local `ConsensusService` submission state is exposed only as
    `locally_observed_finalized`, while `consensus_finalized: true` requires
    exact operation-bound evidence returned by an independently verified source.
    A bounded CometBFT RPC adapter now resolves the exact submitted transaction
    through `/tx?prove=true` and its block through `/commit`; it refuses an
    answer unless a caller-provided trusted verifier validates both the
    transaction-inclusion proof and the validator commit. `ConsensusService`
    retains the exact submitted transaction hash for that lookup. A production
    checkpoint-bound light-client state machine now enforces trust-period
    expiry, `>2/3` commit power, validator-set/header binding, adjacent
    transitions, non-adjacent trusted-set overlap and atomic trusted-checkpoint
    rotation. A strict Ed25519 backend now produces CometBFT v0.38 protobuf
    `VoteSignBytes`, exact `SimpleValidator` Merkle roots and validates RPC
    precommits against derived validator addresses. The standard and ZIP-215
    Ed25519 variants are both available; unsupported keys still fail closed.
   `ABCICommittedFinalitySource` now admits external light-client evidence only
   when the local ABCI commitment has the same height, block hash and app hash.
   The RPC validator-set provider now fetches all bounded pages at both `H`
   and `H+1`, rejects changing totals and is wired directly into the light
   client bridge. A production multi-RPC finality source now requires a
   configured quorum of matching operation-bound evidence before the local ABCI
   commitment is accepted; insufficient evidence and ambiguous ties fail
   closed. Committed transaction-data Merkle proof verification,
   production transport and state-sync operation remain required before a
   public multi-node authority claim.
1. Complete production Registry peer transport operation. The Replicator now has an opt-in fail-closed Ed25519 handshake gate with nonce replay protection for inbound and outbound exchange; operator-managed peer keys persist in the Registry snapshot, survive restart, and key rotation or disablement revokes the active replication session. A transport session now requires verified TLS, owns the outer message sequence, carries the signed handshake and resets authorization on reconnect. A bounded outbound reconnect supervisor now retries only approved peers, requires a fresh handshake after every new transport, and backs off on connection, frame or handshake-timeout failure. The listener, reconnect supervisor and outbox flushing are now composed by an explicitly injected `RegistryReplicationRuntime` and follow the Hypervisor lifespan without implicitly opening a port or loading a signing key. Operator deployment configuration and encrypted local Secret Manager handles are implemented. On `2026-07-29`, a controlled two-host Linux deployment proved persistent snapshot replication of an immutable object, followed by a forced server restart, fresh mTLS plus Ed25519 authentication and a second inventory exchange without runtime errors. This is controlled operational evidence only; independent operator validation remains required before network-wide directory claims.
2. Package-backed Plugin Hosts now reject `UNSANDBOXED_HOST` and run only with `SANDBOX_REQUIRED` through a Docker boundary: read-only verified package mount, non-root UID, dropped capabilities, no-new-privileges, bounded PID/memory and no network. Activation credentials may persist through the Secret Manager, are absent from API/status records, and reach package Hosts only through a short-lived read-only secret-file mount rather than Docker environment variables. A privileged local Docker operator remains trusted because it can inspect bind mounts; declared egress and scoped writable data remain future hardening work and fail closed today.
3. Bind Endpoint Configuration publications to a real Ed25519 owner-wallet signature. New owner wallets and API publications use a verifiable signature over the complete published record; public paid Session admission requires the signature to match the canonical owner identity. Public Registry advertisements carry that proof only for external-facing Endpoints, and Remote Endpoint attachment verifies the proof, summary binding and synchronized owner identity before creating a Proxy target. When the owner identity is absent locally, Remote attach performs a bounded root-only HTTP(S) peer sync and requires a hash-bound Ed25519 envelope matching the expected Registry node, operator and owner wallet before importing it. Legacy local records remain readable but are explicitly unverified. Authenticated Registry replication and peer transport authentication are implemented; independent-peer deployment validation remains pending.
4. Validate the complete RPC/light-client/ABCI path against an upstream
   testnet. A controlled CometBFT v0.38.0 single-validator devnet now proves
   the full external proof path for an actual `LedgerOperationEnvelope`:
   `/tx?prove=true` transaction binding, base64 TxProof branches, committed
   `data_hash`, canonical header `block_id`, ZIP-215 precommit verification and
   checkpoint transition all succeed. That compatibility run corrected four
   real RPC-boundary defects: omitted zero-valued `version.app`, empty initial
   `app_hash`, base64 proof hashes, and the ZIP-215 base-point coordinate.
   A bounded v0.38 TCP ABCI socket server now translates `Info`, `CheckTx`,
   proposal processing, `FinalizeBlock`, `Commit`, queries, snapshots and vote
   extensions to the AiDN application. A separate single-validator CometBFT
   run completed the real socket handshake, accepted and finalized an AiDN
   operation, and committed the resulting application root in the block header.
   A controlled four-validator CometBFT v0.38.19 devnet passed the complete
   external transaction admission, `/tx?prove=true` Merkle inclusion,
   one-validator restart and continued-quorum check without application-hash
   regression on `aa1b1bb`. This drill also found and corrected an actual
   `CheckTx(RECHECK)` bug that could make CometBFT evict a valid transaction
   before proposal. The reproducible command is documented in
   `docs/development/cometbft-multivalidator-acceptance-drill.md` and is an
   opt-in release-verification workflow gate.
   The production finality factory still requires an operator-approved trusted
   checkpoint and exact local ABCI commitment. The ABCI application now
   atomically persists canonical JSON state after each finalized block, restores
   it fail-closed on restart, retains bounded hash-verified State Sync chunks,
   and serves/offers/applies those chunks through the v0.38 socket protocol.
   The local validator proposal bridge also propagates per-transaction ABCI
   outcomes and never marks a rejected or non-durably-finalized operation as
   `FINALIZED`.
   Signed remote-snapshot trust anchoring is now available through an opt-in
   HTTPS deployment configuration: anchors are Ed25519-verified against an
   operator keyring before durable storage and are projected into checkpoint
   sync only after identity, revision, age and explicit-expiry checks pass.
   A public, independently operated multi-validator testnet remains required
   before public network-finality claims.

## Milestones

### M1: Local Hypervisor MVP

Goal: make one node useful as a standalone execution hypervisor.

Status: `Complete`

Checkpoints:
- [x] Local queue and scheduler
- [x] Resource admission and reservations
- [x] Bundle and plugin registry
- [x] Manual and automatic routing
- [x] Agent allocation leases
- [x] Agent capability catalog
- [x] Model install jobs
- [x] Install artifact download and completion automation
- [x] Register installed model as schedulable bundle
- [x] Production-ready provider process execution

Exit criteria:
- a node can advertise its local capabilities through a stable API;
- an operator can install or register local models without direct code edits;
- an agent can request a usable local endpoint from the hypervisor;
- runtime startup and shutdown are backed by real execution control, not only in-memory handles.

### M2: Centralized Registry And Discovery

Goal: make multiple nodes discoverable through one shared registry service.

Status: `Complete`

Checkpoints:
- [x] Registry service for node registration
- [x] Node heartbeat and health status
- [x] Published node metadata:
  - resources
  - installed models
  - providers
  - `can_host_custom_model`
  - pricing in `q per 1kk tokens`
- [x] Discovery API for agents and routers
- [x] Basic registry-side filtering by workload, provider, model, and policy

Exit criteria:
- any node can register and refresh its state in the registry;
- agents can query one discovery endpoint instead of a specific node;
- registry records pricing and onboarding capability per node.

### M3: Wallet And Pricing Interface

Goal: introduce `q` as the network compute unit and define how work is priced.

Status: `Complete`

Checkpoints:
- [x] Initial `q per 1kk tokens` pricing contract
- [x] Operator wallet quote calculator
- [x] Manual usage event recording contract
- [x] Automatic usage metering from real executions
- [x] Provider metering contract for `exact` vs `estimated` usage
- [x] Wallet-facing accounting export interface
- [x] Cost declaration per node:
  - input token price
  - output token price
  - optional fixed task price
- [x] Metering contract for usage reporting
- [x] Settlement-ready event model
- [x] Settlement export replay and retention contract
- [x] Operator-facing wallet console for quote, settlement reopen, and dispute resolution workflows

Exit criteria:
- the system can describe the price of work in `q`;
- a wallet layer can consume usage events and calculate spend;
- pricing is part of discovery, not hidden in node-local config only.

### M4: Endpoint Sessions And Paid Execution

Goal: make endpoint consumption explicit, reserved, and economically safe through session-based execution.

Status: `Complete`

Checkpoints:
- [x] Session create/close contract
- [x] Deposit lock and refund lifecycle
- [x] Endpoint-declared session policy:
  - `minimum_deposit`
  - `recommended_deposit`
  - `idle_fee_per_minute`
  - `idle_timeout`
  - `max_concurrent_sessions`
  - `maximum_session_duration`
- [x] Session-scoped request execution
- [x] Busy vs queue policy for saturated endpoints
- [x] No-request minimum fee rule
- [x] Idle timeout auto-close and idle-fee settlement
- [x] Operator and client-facing confirmation UX for opening paid Sessions
- [x] Operator-facing Sessions workspace with reservation, task launch, and telemetry
- [x] Session settlement export stitched into the wallet ledger
- [x] Remote/proxy-aware paid session propagation

Exit criteria:
- clients must create a Session before using a paid Endpoint;
- the system can reserve endpoint capacity through explicit concurrent-session slots;
- locked funds are settled against actual usage and refunded automatically when unused;
- idle reservation behavior is operator-controlled and visible before the client commits funds;
- session economics can be exported through the same replay-safe ledger model used by the wallet layer.

### M5: Rating, Reputation, And Validation Trust

Goal: publish trust, validation, and quality signals for node selection.

Status: `In progress`

Checkpoints:
- [x] Rating model for nodes
- [x] Core metrics:
  - uptime
  - success rate
  - latency
  - operator reliability
  - dispute or penalty history
- [x] Registry publication of rating data
- [x] Selection policy that can combine price and rating
- [x] Validation Bond, Validator Reward, and Maintenance Validation contract
- [x] Validator qualification and deterministic selection policy
- [x] Endpoint-origin Validation Report custody with signed Storage Receipts
- [x] Compact canonical Validation Commitments with deterministic Certification inputs in local persistence and ledger projections
- [x] Report availability challenges, custody grace periods, and retention Reputation
- [x] Marketplace report-custody freshness and warning surfaces

Exit criteria:
- nodes and validated Endpoints are ranked by structured signals instead of static preference only;
- validated status can be issued, maintained, or revoked through explicit economic rules rather than one-time manual claims;
- discovery clients can filter or sort by trust and price together.

### M6: Custom Model Onboarding

Goal: let nodes advertise and execute whether they can download and host custom models.

Status: `Complete`

Checkpoints:
- [x] Operator model install workflow
- [x] Node flag `can_host_custom_model`
- [x] Install job lifecycle
- [x] Bundle creation from installed artifacts
- [x] Registry publication of onboarding capability

Exit criteria:
- a node can explicitly declare whether it accepts custom model onboarding;
- the registry can expose that capability to agents or operators.

### M7: CometBFT Consensus And Ledger Finality

Goal: move from local-first protocol state to finalized canonical network state ordered by CometBFT and interpreted by the AiDN Ledger State Machine.

Status: `Target architecture`

Checkpoints:
- [ ] Deterministic Ledger Operation envelope with `operation_id`, protocol version, wallet sender, and sender sequence
- [ ] AiDN ABCI application boundary for admission, proposal validation, finalization, and state commitment
- [ ] Consensus Service as an optional Hypervisor service with local configuration and keys
- [ ] Finalized state commitment and snapshot synchronization model
- [ ] Consensus Validator role, stake, and validator-set activation boundaries
- [ ] Non-validator submission, inclusion monitoring, and safe resubmission flow
- [ ] Epoch-task integration through explicit finalized Ledger Operations

Exit criteria:
- canonical protocol state is derived only from finalized ordered operations rather than local mutation alone;
- honest consensus services derive the same application state hash from the same chain data;
- non-consensus hypervisors can still submit signed operations and verify finalization without running a validator.

### M8: Federated Or Distributed Registry

Goal: move from a single registry service to a federated or distributed discovery layer.

Status: `Target architecture`

Checkpoints:
- [ ] Federation model and trust boundaries
- [ ] Signed node advertisements
- [ ] Cross-registry replication or exchange
- [ ] Conflict resolution and freshness model
- [ ] Discovery behavior under partial partition

Exit criteria:
- network discovery no longer depends on one central registry instance;
- node metadata and ratings can propagate across trusted registry peers.

### M9: Network Transport And Registry Replication

Goal: implement the network transport layer and registry replication protocol for distributed peer-to-peer communication.

Status: `MVP complete`

Checkpoints:
- [x] Registry network message types (inventory, object transfer, bloom filters, sync status, announcements)
- [x] Channel and route binding with authorization and rate-limiting
- [x] Replication transport with RegistryReplicator controller
- [x] gRPC transport profile with proto specification
- [x] Peer discovery and auto-synchronization
- [x] Integration and end-to-end replication tests

Exit criteria:
- registry peers can discover, connect, and synchronize inventory via bloom filters;
- object transfer completes with hash verification and anti-entropy convergence;
- network transport layer provides bidirectional streaming with keepalive and backpressure.

### M10: Snapshot And State Sync Protocol

Goal: implement the snapshot production, distribution, discovery, download, verification, restoration, and activation pipeline for decentralized node bootstrapping.

Status: `MVP complete`

Checkpoints:
- [x] Snapshot models, manifest, and identity (RFC-0062 §1-§21)
- [x] Chunking, Merkle tree, and chunk verification (RFC-0062 §22-§25)
- [x] Snapshot producer and portable encoding (RFC-0062 §26-§36)
- [x] Trust anchor management and sync mode selection (RFC-0062 §55-§67)
- [x] Snapshot discovery, selection, and multi-source download (RFC-0062 §37-§44)
- [x] Staging restoration, invariant verification, and atomic activation (RFC-0062 §45-§51)
- [x] Later-block replay and sync completion (RFC-0062 §52-§54, §88-§89)
- [x] Integration and end-to-end pipeline tests

Exit criteria:
- snapshot lifecycle: produce → distribute → discover → download → verify → restore → activate → replay;
- multi-source download with fallback on verification failure;
- Merkle chunk roots for integrity, portable encoding with namespace ordering;
- trust anchor management for sync modes, staging restoration with invariant validation;
- atomic activation with crash recovery, block replay with state hash verification.

## Immediate Priorities

Order of work right now:

1. Operator deployment configuration and encrypted local Secret Manager-backed certificate/signing-key handles now compose the explicitly injected Registry replication runtime. Automated local acceptance proves real mTLS, signed peer authentication, inventory exchange and object transfer between distinct local secret stores, and fixed timeout/sequence/concurrent-close defects. A host-separated Windows-to-Linux acceptance harness now proves the same flow over an SSH-forwarded mTLS connection with independently generated test credentials. A production verifier now runs the actual configured runtime against its durable Registry snapshot, requires authenticated inventory exchange and can require a declared immutable object transfer; its report explicitly does not claim organizational independence. A peer owned by an independent operator remains required before a directory trust claim.
2. Obtain independent-operator Registry peer evidence before allowing directory trust claims; the host-separated acceptance harness is ready.
3. Deploy signed remote-snapshot anchoring against an independently operated multi-validator testnet before making public network-finality claims. The controlled four-validator RPC/Merkle/restart drill is now passing; it is not independent-operator evidence. A controlled LAN deployment has now also proven one CometBFT v0.38.19 validator and one AiDN ABCI process on each of four distinct Ubuntu hosts: all four nodes reached the same height and application hash, each held three P2P peers, and the external transaction/Merkle/restart drill passed while one physical validator restarted. The controlled-LAN verifier now gates further drills on four private RPC views, unique validator identities, P2P quorum, synchronized height and one application hash; its output explicitly excludes independent-ownership claims. A separate read-only external-testnet verifier now requires at least two HTTPS RPC views, an operator-provided trusted checkpoint and one exact finalized operation; it cryptographically checks the transaction, Merkle proof and validator transition before rejecting divergent endpoint evidence. Independent validator ownership still requires out-of-band operator evidence.
4. Extend Plugin Host isolation only with enforceable declared egress controls and scoped writable data; unsupported policies remain blocked.
5. Use the independent-operator onboarding kit for the preceding Registry and finality evidence: [guide](./docs/development/independent-operator-onboarding-and-acceptance.md), one-command Ubuntu loopback bootstrap, secret-free workspace generator, read-only acceptance runner, and reviewed systemd template. Its reports intentionally do not establish independent ownership by themselves.

## Post-MVP Protocol Work

### Development contribution accounting and rewards

This work is intentionally outside the functional MVP. It must not alter current Endpoint economics, escrow, or Validator rewards until its independent Governance and tokenomics decisions are approved.

1. Implement [RFC-0068](./docs/product/RFC-0068-development-contribution-accounting-and-attribution-protocol.md) in a non-emitting evidence mode: eligible repositories, protected-branch merge verification, Contributor Identity, signed Wallet binding, contribution attestations, ECU/CU calculation, contributor groups, role allocation, challenge windows, and maturity records.
2. Approve [ECO-0007](./docs/product/ECO-0007-development-reward-pool-and-distribution-policy.md) before any development-reward transfer. It is now a draft policy that defines the Development Pool budget source, Q conversion, caps, vesting, carryover, and treatment of unclaimed or cancelled rewards; activation still requires Governance approval and economic simulation.
3. Only after both documents are approved, add the corresponding Ledger operations, deterministic epoch distribution, auditable commitments, and a capped rollout. Forge data remains evidence, not a payment authority.

### Dashboard design and information architecture

1. Use [UI-0001](./docs/product/UI-0001-hypervisor-dashboard-specification.md) as the post-MVP Dashboard architecture: Bundle is the operator's central deployment unit, while Endpoint remains the distinct Consumer-facing offer and Runtime/Provider identities remain explicit.
2. Create a route and domain-object inventory before visual redesign so existing `Home`, `Providers`, `Bundles`, `Endpoints`, `Sessions`, `Market`, and Wallet surfaces migrate without duplicate ownership or parallel configuration state.
3. Implement immutable Bundle revision/clone UX, resource and validation preflight, and visible publication/session consequences before allowing operators to modify a live deployment through the new shell.
4. Introduce Basic/Advanced mode only after the canonical Bundle/Endpoint paths are usable; Advanced pages reveal Provider Plugin, Provider Instance, Model Deployment, and Runtime Binding detail without creating another workflow.

## Source Documents

- Vision: [00_VISION.md](./00_VISION.md)
- Terms: [01_TERMS.md](./01_TERMS.md)
- Operator journey: [docs/product/UX-0001-hypervisor-operator-journey.md](./docs/product/UX-0001-hypervisor-operator-journey.md)
- Session and payment journey: [docs/product/UX-0002-endpoint-session-and-payment-flow.md](./docs/product/UX-0002-endpoint-session-and-payment-flow.md)
- Economic principles: [docs/product/ECO-0000-economic-principles.md](./docs/product/ECO-0000-economic-principles.md)
- Protocol service reward distribution: [docs/product/ECO-0004-protocol-service-reward-distribution.md](./docs/product/ECO-0004-protocol-service-reward-distribution.md)
- Emission, recycling, and epoch reward allocation: [docs/product/ECO-0005-q-emission-recycling-and-epoch-reward-allocation.md](./docs/product/ECO-0005-q-emission-recycling-and-epoch-reward-allocation.md)
- Consensus economics and validator eligibility: [docs/product/ECO-0006-consensus-economics-and-validator-eligibility.md](./docs/product/ECO-0006-consensus-economics-and-validator-eligibility.md)
- Development reward pool and distribution: [docs/product/ECO-0007-development-reward-pool-and-distribution-policy.md](./docs/product/ECO-0007-development-reward-pool-and-distribution-policy.md)
- Wallet and identity: [docs/product/RFC-0016-wallet-and-identity.md](./docs/product/RFC-0016-wallet-and-identity.md)
- Validation economics: [docs/product/ECO-0003-validation-economics.md](./docs/product/ECO-0003-validation-economics.md)
- Validation escrow system: [docs/product/RFC-0035-validation-escrow-system.md](./docs/product/RFC-0035-validation-escrow-system.md)
- Ledger state machine: [docs/product/RFC-0036-aidn-ledger-state-machine.md](./docs/product/RFC-0036-aidn-ledger-state-machine.md)
- Settlement engine: [docs/product/RFC-0037-settlement-engine.md](./docs/product/RFC-0037-settlement-engine.md)
- Economic MVP profile: [docs/product/MVP-0001-economic-execution-profile.md](./docs/product/MVP-0001-economic-execution-profile.md)
- Ledger operation catalog: [docs/product/RFC-0059-ledger-operation-catalog.md](./docs/product/RFC-0059-ledger-operation-catalog.md)
- Usage reporting and verification: [docs/product/RFC-0051-usage-reporting-and-verification-protocol.md](./docs/product/RFC-0051-usage-reporting-and-verification-protocol.md)
- Capability runtime specification: [docs/product/RFC-0053-capability-runtime-specification.md](./docs/product/RFC-0053-capability-runtime-specification.md)
- Capability runtime protocol: [docs/product/RFC-0054-capability-runtime-protocol.md](./docs/product/RFC-0054-capability-runtime-protocol.md)
- Provider plugin system and directory: [docs/product/RFC-0055-provider-plugin-system-and-directory.md](./docs/product/RFC-0055-provider-plugin-system-and-directory.md)
- Provider plugin runtime interface: [docs/product/RFC-0056-provider-plugin-runtime-interface.md](./docs/product/RFC-0056-provider-plugin-runtime-interface.md)
- Registry replication protocol: [docs/product/RFC-0061-registry-replication-protocol.md](./docs/product/RFC-0061-registry-replication-protocol.md)
- Snapshot and State Sync protocol: [docs/product/RFC-0062-snapshot-and-state-sync-protocol.md](./docs/product/RFC-0062-snapshot-and-state-sync-protocol.md)
- Session failure, recovery, and forced settlement: [docs/product/RFC-0060-session-failure-recovery-and-forced-settlement.md](./docs/product/RFC-0060-session-failure-recovery-and-forced-settlement.md)
- CometBFT consensus integration: [docs/product/RFC-0047-cometbft-consensus-integration.md](./docs/product/RFC-0047-cometbft-consensus-integration.md)
- Validation report specification: [docs/product/RFC-0057-validation-report-specification.md](./docs/product/RFC-0057-validation-report-specification.md)
- Participant eligibility and Sybil resistance: [docs/product/RFC-0058-participant-eligibility-and-sybil-resistance.md](./docs/product/RFC-0058-participant-eligibility-and-sybil-resistance.md)
- Development contribution accounting and attribution: [docs/product/RFC-0068-development-contribution-accounting-and-attribution-protocol.md](./docs/product/RFC-0068-development-contribution-accounting-and-attribution-protocol.md)
- Hypervisor dashboard specification: [docs/product/UI-0001-hypervisor-dashboard-specification.md](./docs/product/UI-0001-hypervisor-dashboard-specification.md)
- M5 validation bond and escrow design: [docs/superpowers/specs/2026-07-02-validation-bond-and-escrow-design.md](./docs/superpowers/specs/2026-07-02-validation-bond-and-escrow-design.md)
- Current hypervisor execution plan: [docs/superpowers/plans/2026-06-19-agent-resource-discovery-and-model-onboarding.md](./docs/superpowers/plans/2026-06-19-agent-resource-discovery-and-model-onboarding.md)
- Network architecture spec: [docs/superpowers/specs/2026-06-19-network-registry-wallet-rating-design.md](./docs/superpowers/specs/2026-06-19-network-registry-wallet-rating-design.md)
- M2 registry contract: [docs/superpowers/specs/2026-06-19-m2-centralized-registry-and-discovery-design.md](./docs/superpowers/specs/2026-06-19-m2-centralized-registry-and-discovery-design.md)
- Operator dashboard spec: [docs/superpowers/specs/2026-06-20-operator-fleet-market-dashboard-design.md](./docs/superpowers/specs/2026-06-20-operator-fleet-market-dashboard-design.md)
- Operator dashboard terminal redesign spec: [docs/superpowers/specs/2026-06-20-operator-dashboard-terminal-redesign-design.md](./docs/superpowers/specs/2026-06-20-operator-dashboard-terminal-redesign-design.md)
- Operator dashboard terminal redesign plan: [docs/superpowers/plans/2026-06-20-operator-dashboard-terminal-redesign.md](./docs/superpowers/plans/2026-06-20-operator-dashboard-terminal-redesign.md)
- M3 pricing and metering plan: [docs/superpowers/plans/2026-06-19-m3-wallet-pricing-and-usage-metering.md](./docs/superpowers/plans/2026-06-19-m3-wallet-pricing-and-usage-metering.md)
- M4 endpoint session and payment design: [docs/superpowers/specs/2026-07-01-endpoint-session-payment-flow-design.md](./docs/superpowers/specs/2026-07-01-endpoint-session-payment-flow-design.md)
- M4 endpoint session and payment plan: [docs/superpowers/plans/2026-07-01-endpoint-session-payment-flow.md](./docs/superpowers/plans/2026-07-01-endpoint-session-payment-flow.md)
- Provider plugin system MVP plan: [docs/superpowers/plans/2026-07-14-provider-plugin-system-mvp.md](./docs/superpowers/plans/2026-07-14-provider-plugin-system-mvp.md)
- Provider install approval and apply flow plan: [docs/superpowers/plans/2026-07-15-provider-install-approval-flow.md](./docs/superpowers/plans/2026-07-15-provider-install-approval-flow.md)

## Maintenance Rule

Every meaningful architecture or milestone change should update this file in the same branch.
