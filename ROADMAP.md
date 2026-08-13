# AiDN Roadmap

Last updated: `2026-08-12`

This is the main public roadmap for the repository.

## 2026-08-12 Protocol Authority Boundary

Completed in this slice:

- [x] Add hash-bound Ed25519 threshold authorization for protocol-owned
  `EPOCH_TRANSITION` operations. Strict validator mode rejects missing policy,
  mismatched policy hashes, invalid signatures and duplicated signer evidence
  at both `CheckTx` and block execution; deterministic replay execution uses
  the same boundary. See [protocol authority policy](./docs/development/protocol-authority-policy.md).
- [x] Roll out commit `8145166` to validators `128`, `129`, and `130` without
  resetting ledger or CometBFT state. The rollout acceptance record is
  [here](./docs/development/protocol-authority-rollout-acceptance-2026-08-12.md).
- [x] Add the offline-only authorized epoch-transition builder. It validates
  the same Ledger payload rules, binds every signer to the public policy and
  threshold, and never broadcasts or mutates local state. See
  [the builder runbook](./docs/development/authorized-epoch-transition-builder.md).
- [x] Add a coordinated public-policy rollout helper with dry-run, state-mount
  validation, atomic file installation, per-host health verification, and
  rollback. See [the rollout runbook](./docs/development/protocol-authority-policy-rollout.md).

Next required economic-network work:

- [ ] Publish and distribute one identical protocol authority policy hash to
  validators `128`, `129` and `130` through a coordinated network/config
  change.
- [ ] Generate and finalize a signed canonical `EPOCH_TRANSITION` containing
  the `GENERAL_DEVELOPMENT` pool budget; no local process may invent this
  transition or bypass the authority quorum.
- [ ] Re-run quorum preflight, then build and execute the first real ECO-0007
  development reward batch with independent reproduction and finality evidence.

It should stay current and answer four questions:

1. What are we building?
2. What stage are we in now?
3. What milestones come next?
4. What has to be true before we move to the next stage?

The roadmap must also stay aligned with the product-level operator journey defined in [docs/product/UX-0001-hypervisor-operator-journey.md](./docs/product/UX-0001-hypervisor-operator-journey.md).

## 2026-08-12 Bundle Workspace Slice

Completed in this slice:

- [x] Upgrade the React `Bundles` workspace from a list to an operator control
  surface with lifecycle metrics, search, lifecycle/provider/Endpoint filters,
  explicit result feedback, and real enable/pause/retry/cooldown actions.
- [x] Add a right-side Bundle inspector showing immutable identity and ancestry,
  content hash, Provider -> Model -> Runtime -> Endpoint relationships, runtime
  health/error evidence, resource profile, and navigation to the owning
  workspaces.
- [x] Add read-only activation preflight that derives `ready`, `blocked`,
  `unknown`, and informational checks from canonical readiness, Provider/model/
  Runtime Binding inventories, host capacity, Bundle lifecycle, and Endpoint
  relationship state. The UI does not invent missing capacity or validation.
- [x] Add field-level comparison for two immutable Bundle records and keep the
  revision factory as the only configuration mutation path.
- [x] Extend Bundle dashboard read models with revision ancestry, content hash,
  launch/resource policy, runtime identity and runtime health/error fields.

Next planned Bundle work:

- [ ] Add a canonical backend preflight endpoint with evidence IDs and a
  server-side resource-fit decision; the current UI preflight remains an
  explicitly read-only projection of existing read models.
- [ ] Expose runtime generation, active Session counts, drain/retire operations,
  and their recovery/finality rules from the canonical service API before adding
  corresponding buttons to the dashboard.
- [ ] Complete the endpoint-first migration so Bundle remains the immutable
  execution revision while Endpoint draft/publish/validation owns consumer-facing
  trust and publication state.

Paid endpoint consumption and client-facing execution economics must also stay aligned with [docs/product/UX-0002-endpoint-session-and-payment-flow.md](./docs/product/UX-0002-endpoint-session-and-payment-flow.md).

Network-wide economic assumptions, `Q` utility, Session deposits, Network Fees, and operator reward boundaries must also stay aligned with [docs/product/ECO-0000-economic-principles.md](./docs/product/ECO-0000-economic-principles.md).

Epoch reward allocation, recyclable fee/removal handling, and service-pool competition must stay aligned with [docs/product/ECO-0005-q-emission-recycling-and-epoch-reward-allocation.md](./docs/product/ECO-0005-q-emission-recycling-and-epoch-reward-allocation.md). The external Faucet Treasury, its replaceable payout policy, its dedicated supply boundary, and canonical activation proof must stay aligned with [docs/product/ECO-0008-faucet-treasury-and-policy-execution.md](./docs/product/ECO-0008-faucet-treasury-and-policy-execution.md) and [ECO-0009](./docs/product/ECO-0009-treasury-activation-and-canonical-funding-proof.md).

Service-pool weight formulas, diversity controls, concentration caps, and deterministic reward-mint derivation must also stay aligned with [docs/product/ECO-0004-protocol-service-reward-distribution.md](./docs/product/ECO-0004-protocol-service-reward-distribution.md).

Consensus Stake, active-set selection, equal voting power, validator rotation, unbonding, and objective slashing rules must also stay aligned with [docs/product/ECO-0006-consensus-economics-and-validator-eligibility.md](./docs/product/ECO-0006-consensus-economics-and-validator-eligibility.md).

Wallet ownership, signing semantics, and the separation between Wallet identity and Hypervisor node identity must also stay aligned with [docs/product/RFC-0016-wallet-and-identity.md](./docs/product/RFC-0016-wallet-and-identity.md).

Participant eligibility, reward-bound identity layers, Faucet claimant anti-abuse constraints, and future reward/voting concentration controls must also stay aligned with [docs/product/RFC-0058-participant-eligibility-and-sybil-resistance.md](./docs/product/RFC-0058-participant-eligibility-and-sybil-resistance.md) and ECO-0008.

Validation-status issuance, maintenance revalidation, and Validator incentives must also stay aligned with [docs/product/ECO-0003-validation-economics.md](./docs/product/ECO-0003-validation-economics.md).

Wallet balances, escrow state, validation bonds, and future on-chain settlement semantics must also stay aligned with [docs/product/RFC-0036-aidn-ledger-state-machine.md](./docs/product/RFC-0036-aidn-ledger-state-machine.md).

Session settlement semantics, invoice handling, refund rules, and accounting-state transitions must also stay aligned with [docs/product/RFC-0037-settlement-engine.md](./docs/product/RFC-0037-settlement-engine.md).

Session failure classification, recovery windows, disappearance handling, mismatch termination, and evidence-backed forced settlement must also stay aligned with [docs/product/RFC-0060-session-failure-recovery-and-forced-settlement.md](./docs/product/RFC-0060-session-failure-recovery-and-forced-settlement.md).

Canonical Ledger operation envelopes, state-transition semantics, fees, idempotency, and replay protection must also stay aligned with [docs/product/RFC-0059-ledger-operation-catalog.md](./docs/product/RFC-0059-ledger-operation-catalog.md).

Usage reporting, accounting transparency, checkpoint acknowledgement, mismatch handling, and opaque proxy billing must also stay aligned with [docs/product/RFC-0051-usage-reporting-and-verification-protocol.md](./docs/product/RFC-0051-usage-reporting-and-verification-protocol.md).

Capability Runtime service boundaries, Runtime identity, Runtime ownership, and Runtime isolation rules must also stay aligned with [docs/product/RFC-0053-capability-runtime-specification.md](./docs/product/RFC-0053-capability-runtime-specification.md).

Hypervisor-to-Runtime registration, Session execution, streaming, usage-report transport, health, and recovery semantics must also stay aligned with [docs/product/RFC-0054-capability-runtime-protocol.md](./docs/product/RFC-0054-capability-runtime-protocol.md).

Agent control-plane lifecycle, scopes, plan/apply semantics, resource exposure,
approval boundaries, and MCP transport behavior must also stay aligned with
[the MCP-0001 implementation profile](./docs/product/MCP-0001-node-control-server-implementation-profile.md)
and the attached MCP-0001 normative document pack.

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

Current implementation slice:
- [x] Ubuntu operator bootstrap now provisions the pinned CometBFT toolchain,
  creates a fixed user-systemd unit, starts the Hypervisor ABCI listener before
  consensus, verifies RPC health, and persists management metadata for the
  Readiness Wizard. Fresh nodes no longer require a separate manual
  “start CometBFT” step. Existing `genesis.json` state is validated and never
  overwritten; joining a multi-validator network still requires an approved
  network profile.
- [x] Consensus-enabled MVP Forced Settlement now uses an ordered, idempotent
  `SESSION_ESCROW_LOCK` -> `SESSION_FAILURE_EVIDENCE` -> `SESSION_FORCE_SETTLE`
  chain. Local preparation is separated from local economic application, and
  the Hypervisor applies the terminal projection only after verified canonical
  finality.
- [x] The force-finalization API exposes `202 CONSENSUS_PENDING` until the
  required stage is finalized and returns `200` only after local projection;
  the existing non-consensus path remains synchronous.
- [x] Regression coverage proves repeated calls advance one stage at a time,
  preserve balances before finality, and finish with one terminal refund.
- [x] Resolve validator-local Session opening: a validator Hypervisor creates a
  `PENDING_FINALITY` Session and persists the exact canonical escrow-lock
  envelope without mutating local balances. Repeated open calls reconcile the
  same operation, return `202` until verified finality, and bind `FINALIZED`
  funding only after the local canonical projection matches the envelope.
  Execution is blocked while funding is pending; the regression suite covers
  missing authentication, one-time wallet debit, finality resume, and the
  execution gate.
- [x] Define and implement the canonical non-zero/consumer-timeout Settlement
  projection for completed fixed-price Requests. Consensus requires terminal
  Request evidence, Final Usage and record hashes, referenced Settlement and
  Usage roots, no dispute, exact Request-charge aggregation and a transition
  whose Endpoint payment and Consumer refund match the locked reserves. The
  remaining unsupported profiles are provider-metered, partial, checkpoint-
  based and disputed non-zero calculations.
- [x] Close the validator HTTP write boundary: ordinary wallet, registry,
  provider, endpoint and cooperative-settlement writes are rejected unless they
  enter through a canonical consensus transaction. Validator Session-open and
  the staged force-finalize route are the only current HTTP exceptions.
- [x] Keep pre-finality failure/force projections outside the canonical Ledger
  operation log. Pending projections survive Hypervisor restart for retry, while
  ABCI app-hash state contains only canonical operation identities; final local
  application uses the finalized CometBFT force operation ID.
- [x] Make cooperative Settlement recovery fail closed on conflicting pending
  envelopes. A restart may reuse the exact staged operation, but a changed
  Settlement identity or economic payload for the same Session and stage is
  rejected instead of producing a second operation ID.
- [x] Run the same consensus boundary against the controlled four-validator
  LAN profile and preserve verified finality evidence. All four RPC nodes
  converged at one height and AppHash; validator 127 was recovered from the
  canonical peer state without changing its validator or node keys. The drill
  also exposed and fixed the bounded State Sync retention configuration.
- [x] Make State Sync retention transfer-safe: the ABCI source keeps a bounded
  eight-snapshot window by default, leases a snapshot after its first chunk is
  requested, exposes the lease duration through operator configuration, and
  requires a consumer to restart from a complete advertised snapshot after
  lease expiry or release rather than silently switching snapshot identity.
- [x] Harden external multi-RPC acceptance so all canonical finality evidence
  fields are compared, not only height/block/app roots. Divergent commit hash,
  finalization time, proof version or operation identity fails closed, while
  RPC/verifier ownership remains explicitly `NOT_PROVEN_BY_PROTOCOL`.
- [x] Permit non-validator Hypervisors to consume the same verified single- or
  multi-RPC finality source without a local ABCI application; validator mode
  retains the additional local block/AppHash commitment boundary.
- [x] Wire the verified multi-RPC finality boundary into the default Hypervisor
  startup through an operator-owned JSON deployment profile. The profile
  requires a trusted checkpoint, unique credential-free RPC endpoints and an
  explicit quorum; validator mode also binds the source to the local ABCI
  Ledger, while absent configuration preserves the existing MVP behavior.
- [x] Add a release-gate evidence validator for independent-operator acceptance:
  it verifies the SHA-256 manifest, requires exactly one successful Registry
  replication report and one successful external-finality report, checks the
  required peer/finality evidence shape, rejects duplicates or mutations, and
  preserves `ownership_evidence: NOT_PROVEN_BY_PROTOCOL`. The acceptance runner
  now emits the derived validation report separately from the checksummed source
  evidence.
- [x] Add an explicit consensus operation-coverage matrix and fail-closed
  validator profile. Specialized transitions are now listed and tested against
  the catalog; known operations without a deterministic transition are rejected
  before mempool/proposal/canonical-log processing when
  `AIDN_CONSENSUS_STRICT_OPERATION_COVERAGE` is enabled. Validator bootstrap
  enables that profile by default, while embedded compatibility instances remain
  permissive. See [consensus operation coverage](./docs/development/consensus-operation-coverage.md).
- [x] Implement the first previously declared catalog operation,
  `WALLET_TRANSFER`, in both ABCI and deterministic block execution. The MVP
  applies the fixed `0.01Q` standard fee, recycles it, persists the balance
  transition, and protects it with replay, insufficiency and snapshot-boundary
  tests.
- [x] Make the controlled four-validator drill reproducible as a manual
  Ubuntu release gate. The dedicated consensus job installs its own package
  environment, runs the strict unsupported-operation probe and canonical
  failure chain plus the finalized `SESSION_ESCROW_LOCK` -> `SESSION_OPEN` ->
  `SESSION_ACCEPT` lifecycle chain, persists machine-readable evidence,
  uploads the report, and preserves all validator logs on failure. The
  verifier also exercises the `SERVICE_VERIFICATION_COMMIT` ->
  `REPUTATION_PROFILE_UPDATE` evidence chain and requires all four validator
  RPC views to converge at one height and AppHash before and after the
  transaction batch and after restart. The actual GitHub Actions run is still
  required for external Docker evidence; local Windows verification cannot
  substitute for that run because Docker is unavailable here.
- [x] Execute the strict four-host Ubuntu acceptance against the live LAN
  profile. The run finalized eight externally submitted operations, verified
  every CometBFT transaction inclusion proof, rejected an unsupported
  `REGISTRY_UPSERT` before canonical execution, and recovered one remotely
  restarted validator with an unchanged AppHash. The evidence deliberately
  remains `ownership_evidence: NOT_PROVEN_BY_PROTOCOL`; independent operator
  ownership and public-network finality are separate gates. See
  [the 2026-08-02 acceptance record](./docs/development/cometbft-lan-acceptance-2026-08-02.md).
- [x] Add a finality-aware Reputation read model. Registry consumers can poll
  `not_found` or `pending_finality` without receiving an unfinalized profile
  root, and receive the immutable `consensus_finalized` projection only after
  operation-bound verified consensus evidence matches the committed update.

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
- epoch reward allocation and recyclable protocol removals are now defined at the product level, while Faucet payouts are explicitly owned by the separate Treasury service and do not enter epoch pool allocation;
- service-pool reward formulas are now documented in `ECO-0004`, so future Consensus, Registry, and Validation reward implementation can share one deterministic weighting, diversity, and cap model instead of embedding separate payout heuristics in each subsystem;
- consensus validator economics are now documented in `ECO-0006`, so future Validator Set selection, equal voting-power enforcement, Stake lifecycle, downtime handling, and slashing implementation can build on one deterministic eligibility model instead of scattering security rules across consensus adapters and app logic;
- participant identity hierarchy, Hypervisor/Service eligibility states, and anti-Sybil design constraints are now documented in `RFC-0058`; the external Faucet additionally uses signed Wallet proof, quota state, and Treasury policy from `ECO-0008`;
- the canonical Ledger operation inventory is now documented in `RFC-0059`, so consensus, settlement, reward, external Faucet Treasury funding, validation, and suspension work can land on one state-transition catalog instead of duplicating operation semantics across RFCs;
- the Capability Runtime service model is now documented in `RFC-0053`, so future runtime packaging, runtime authorization, runtime replacement, and multi-runtime capability work can share one architectural contract before wire-level protocol details;
- the Hypervisor-to-Runtime boundary is now documented in `RFC-0054`, and its first durable protocol core now enforces approved Binding/route identity, handshake version negotiation, semantic replay protection, Request admission/idempotency, Usage chains and explicit recovery plans/results;
- the first `MCP-0001` node-control slice is now implemented as a local stdio JSON-RPC server plus an opt-in bearer-token HTTP gateway over the existing Hypervisor service. It exposes scope-filtered read models and Bundle plan/apply mutations with persistent Control Sessions, atomic plans/idempotency, revision checks, hash-linked audit events, a separate operator approval channel, and an operator emergency stop. The production HTTP profile now adds mandatory mTLS, TLS 1.2+, HTTPS enforcement, private-key permission checks, a single-worker launcher, Secret Manager-backed TLS handles, hash-only rotation detection, valid-bundle gating, and graceful certificate reload; QUIC hardening, shell execution, wallet signing, public Endpoint actions, and consensus writes remain deferred. See [the MCP implementation profile](./docs/product/MCP-0001-node-control-server-implementation-profile.md) and [the quickstart](./docs/development/mcp-server-quickstart.md);
- the production MCP TLS profile has controlled Ubuntu acceptance on `192.168.88.127`: a real client certificate, encrypted Secret Manager handles, certificate serial rotation, graceful restart, stale transport-session rejection and new-session reconnect all passed. The evidence is [MCP TLS rotation acceptance](./docs/development/mcp-tls-rotation-acceptance-2026-08-04.md); it is technical interoperability evidence only and does not prove organizational independence;
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
- MVP-0001 persistence now preserves Runtime evidence, canonical funding, settlement operations, forced-settlement records, Endpoint manifests, closed/force-settled Session snapshots and released Deposit snapshots across app-level restore, with duplicate cooperative and forced finalization rejected after restart; RFC-0060 recovery metadata now persists failure attribution and exact deadlines, re-registers recovering Sessions after restart, expires legacy missing-deadline state fail-closed, rejects stale recovery callbacks after terminal Settlement, and round-trips Failure Evidence/Failure Reports through the durable Hypervisor snapshot with conflict rejection; configured local MVP force-finalize now binds the computed evidence root into the canonical force operation and terminal Session snapshot;
- MVP-0001 task execution now records a compatibility Runtime evidence envelope from real completed endpoint tasks, producing a terminal Runtime Request plus mandatory Final Usage Report for the existing finalize API without seeded test evidence, while rejecting a second Runtime Request for the same MVP Session;
- MVP-0001 now has a one-call paid smoke API that opens a fixed-price Session, submits the first endpoint task, returns Result/Runtime evidence/Final Usage/Settlement readiness, and can either auto-finalize or leave the Session ready for explicit finalize;
- the operator dashboard `Endpoints` workspace now exposes the one-call `MVP-0001` paid smoke path with fixed-price defaults, auto/manual finalization mode, visible Task Result, Runtime evidence, Final Usage, Settlement readiness, cooperative finalize, and completed fixed-price timeout force-finalize controls;
- the operator dashboard `Sessions` workspace now exposes the MVP-0001 Endpoint-unavailable timeout refund path for no-request Sessions with canonical funding, including force-after/now controls and explicit eligibility diagnostics;
- canonical capability definitions now ship with stable definition hashes, and published endpoint advertisements now bind to projected feature, limit, and implementation profile hashes inside registry-visible canonical overlays;
- canonical overlay and node advertisement payloads now also expose immutable local Registry Object envelopes for capability definitions, endpoint profiles, and accounting contracts, giving later persistence and replication work a stable object identity layer to build on;
- registry-backed object views now support deduplicated `object_id` lookup, filtered listing, durable local snapshot persistence, a versioned local completeness summary, deterministic payload-free inventory manifests with segment/content roots, and persisted retention expiry state; the authenticated peer replicator now exchanges verified inventory manifests, plans bounded catch-up/repair batches, and carries signed deterministic Proof of Registry challenge/response evidence;
- registry-backed object views now also support opt-in canonical payload retrieval for projected capability, profile, and accounting objects, so object inspection no longer stops at envelope metadata;
- `RegistryService` now also maintains a standalone local Registry Object store with snapshot-backed durable persistence, and local operator object routes ingest projected canonical objects into that store while preserving local node provenance for returned sources;
- the operator dashboard now includes a dedicated `Sessions` workspace with reservation composer, session control actions, session-bound task launch, activity timeline, and settlement preview telemetry;
- wallet exports now include a unified replay-safe ledger stream that stitches session settlement events together with usage and allocation-family wallet events;
- proxy-backed paid Sessions now preserve upstream session policy snapshots, lazily broker remote Session opens, propagate remote Session close on manual and idle-driven release, and expose proxy-session bindings through task and operator-session APIs;
- endpoint lifecycle now supports symmetric proxy attach and detach actions, so operators can revert a proxied Endpoint back to local execution without editing manifests manually;
- preferred remote routes can now be detached explicitly, but live local proxy endpoints still protect their upstream dependency until the operator detaches the proxy route first;
- the canonical `SESSION_FORCE_SETTLE` Ledger path now preserves RFC-0060 failure class, timeout, checkpoint, usage, evidence-root, Request Settlement Root and deterministic per-Request evidence; the public MVP remains limited to conservative fixed-price cases, while the underlying Ledger now supports bounded multi-request forced evaluation without bypassing Request/Session ceilings;

What is still missing in the current stage:
- bind derived canonical Settlement terms (including scaled `audio_input_seconds` milliseconds) into a separately accepted variable-price Session profile; the current public `MVP-0001` profile remains fixed-price;
- RFC-0051/RFC-0037 alignment remains partial beyond the new evidence and deterministic Settlement cores: legacy Session reports and float-Q close paths are still compatibility projections, while canonical bridge ingestion, network proposal/acceptance, consensus Ledger finality, Checkpoint/correction/dispute workflows, statistics and Marketplace transparency remain incomplete;
- rating publication, reputation policy, and validation economics implementation;
- Validation Report custody migration: deterministic compact commitments, report hashes, stable logical locators with Endpoint/Configuration scope checks, snapshot metadata, a controlled local content-addressed report store, opt-in Ed25519 Storage Receipts, Assignment-bound validator transfer identity, a persisted canonical validator-key registry, opt-in grace/failure Certification lifecycle, access-aware retrieval, persisted local custody challenge evidence, a durable Endpoint-retirement queue, local RFC-0042 VALIDATION custody retrieval and body-free `VALIDATION_REPORT_CUSTODY_CHALLENGE` routes, origin/mirror-separated quorum evidence, and evidence-only consensus projections for report/receipt/failure/availability/release commitments now exist alongside legacy local reports; full report custody still duplicates compatibility data in the general Hypervisor state snapshot, submission still derives Certification in one call, while cross-host transport acceptance and canonical Reputation finality remain under `docs/superpowers/plans/2026-07-18-validation-report-custody.md`;
- Validation Report custody now also has a local evidence-only quorum projection, durable epoch/seed scheduler and an explicit opt-in Reputation adapter: repeated challenges are idempotent, Known Control Groups collapse to one independent observation, observer identity is carried in availability evidence, scheduled tasks survive restart, and custody outcomes can be projected into availability, retention, integrity and disclosure events without mutating Reputation until an operator explicitly applies them; network dispatch, canonical Reputation finality and cross-host transport acceptance remain open;
- `REPUTATION_PROFILE_UPDATE` is now a consensus-finalized, evidence-only profile-root commitment with fixed-point metric deltas, strict effective-epoch hash chaining, finalized-evidence references, ABCI/deterministic execution coverage and replay-safe tests; a read-only `ReputationProfileFinalityAdapter` exposes the root only after matching operation-bound consensus evidence, while score calculation, canonical cross-host scheduling and external acceptance remain outside this local boundary;
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
- registry-object alignment is now complete for the planned Registry Duty evidence slice:
  - the repo has deterministic Registry Object envelopes plus registry-backed list/query/get, opt-in payload retrieval, standalone local snapshot-backed durable object persistence, versioned local retention enforcement for capability/profile/accounting artifacts, authenticated manifest exchange, bounded repair/catch-up, full segment Merkle inclusion proofs, quorum-bound multi-peer repair with conflict evidence, signed non-response confirmation, and consensus-finality-bound Registry Duty Evidence;
  - Registry eligibility now records fixed-point Proof Success, Completeness, Availability, Health, Maturity, Latency, Reliability, collateral, beneficiary and Known Control Group inputs;
  - `SERVICE_VERIFICATION_COMMIT` is idempotently recorded as evidence only; Registry code cannot mint Q or submit `REWARD_MINT`.
- implementation of `RFC-0044` is now partially implemented beyond the local
  contract scaffolding:
  - accepted Session contracts persist as immutable local Registry Objects;
  - ordered, hash-bound `session-amendment.v1` objects are persisted in the
    Session snapshot with idempotent API/service acceptance;
  - expiration, Request-limit and artifact-limit amendments advance the local
    effective-terms head, while economic amendments fail closed unless the
    application verifies canonical `SESSION_ESCROW_EXTEND` funding proof;
  - public MVP amendments verify both registered Wallet signatures and fail
    closed when either identity is unavailable;
  - Runtime Request/terminal evidence and MVP Settlement Input now bind to
    `effective_terms_hash`;
  - Session Contract exchange now exports and imports a hash-checked base
    contract plus complete amendment chain, stages immutable Registry evidence
    idempotently, and refuses to overwrite a conflicting local Session;
  - conservative Forced Settlement now has an idempotent terminal
    `force_settled` projection with persisted settlement snapshot and
    evidence-root conflict rejection; multi-request checkpoint/dispute/
    correction resolution remains outside the public MVP profile.
- RFC-0060 local MVP evidence-root binding is implemented for the configured
  `SessionFailureHandler` path, including durable restore and terminal snapshot
  binding. The path now emits a compact `SESSION_FAILURE_EVIDENCE` operation
  and references it from `SESSION_FORCE_SETTLE`. Both ABCI and deterministic
  block execution now validate that evidence operation as a typed immutable
  commitment. The consensus service now has an opt-in CometBFT HTTP
  `broadcast_tx_sync` submission boundary with transaction-hash checking and
  idempotent admission, plus reconciliation that applies `FINALIZED` only
  from a matching-chain `ConsensusFinalitySource`; the local lock, evidence
  and force records now have explicit projection/orchestration support that
  creates fresh canonical identities, retains local correlation, requires
  canonical dependency IDs and gates each dependent submission on verified
  finality. The controlled four-validator acceptance drill now exercises the
  complete canonical failure chain and restart continuity. Public
  independently operated finality remains a post-MVP rollout boundary.
- implementation of `RFC-0058` is now partially implemented for Registry duty:
  - Wallet ownership and separate Hypervisor node identity exist, and Registry Duty Evidence binds reward beneficiary, activation age, collateral, service eligibility, Health, Proof, Completeness and Known Control Group inputs through an immutable Eligibility Snapshot;
  - the Registry epoch calculator now aggregates those snapshots with deterministic diversity and concentration caps;
  - generic cross-service Known Control Group discovery, full collateral lifecycle and network-wide anti-Sybil enforcement remain separate work.
- implementation of `ECO-0004` now includes the Registry reward calculation slice:
  - finalized Registry Duty inputs are aggregated per Epoch with fixed-point Diversity Factor, Known Control Group cap/redistribution, deterministic integer allocation and an order-independent `REWARD_CALCULATION_ROOT`;
  - `EpochTransitionEngine` consumes the allocated Registry pool without minting; both consensus block entrypoints validate canonical `EPOCH_TRANSITION` roots/sequential Epochs/pool budgets and enforce that Ledger `REWARD_MINT` requires an exact pre-block-finalized transition, matching root, pool budget and idempotent reward identity;
  - Consensus and Validation pool calculators, full consensus operation execution and public multi-validator rollout remain separate work.
- implementation of `ECO-0006` now includes the typed Validator Set schedule
  boundary:
  - both consensus entrypoints validate protocol-only
    `CONSENSUS_VALIDATOR_SET_UPDATE` payloads, Epoch binding, typed additions,
    removals and voting-power updates, positive Stake/power, non-overlap and
    one schedule per activation Epoch;
  - the Ledger records the schedule as evidence and emits
    `ValidatorSetUpdateScheduled` without wallet effects or premature
    CometBFT activation;
  - a previously finalized schedule is now activated only at the matching
    `EPOCH_TRANSITION`, persisted in Snapshot/State Sync state, and translated
    into ABCI `validator_updates` with zero-power removals; same-block schedule
    and activation is rejected;
  - the pure `ValidatorScheduleBuilder` now derives a deterministic schedule
    from a finalized Candidate snapshot, retains the configured incumbent
    fraction, enforces the Known Control Group slot cap, rejects duplicate
    consensus keys and emits equal voting power; its eligibility adapter binds
    the immediately preceding finalized Eligibility snapshot and canonical
    evidence root, while Ledger admission reconstructs the final-set hash;
  - deterministic downtime/suspension/unbonding and the evidence-driven
    slashing flow now have typed local boundaries; full Epoch-to-active-set
    orchestration and Stake-target slashing remain separate rollout work;
  - the typed `PENALTY_APPLY` execution boundary is now implemented in both
    ABCI and the deterministic Execution Engine: only finalized prior
    evidence may authorize it, same-block evidence shortcuts are rejected,
    wallet and locked-Stake targets are bounded, partial/full Stake slash
    states are persisted, recyclable/burned accounting is snapshot-safe, and
    fatal block rollback restores penalty state.
  - ECO-0006 downtime handling now has a deterministic integer-basis-point
    policy for 90/80/67% boundaries, persistent three-Epoch suspension and
    abandonment classification; ordinary downtime never authorizes slashing;
  - removing duty decisions now have a pure adapter to typed,
    evidence-bound `PARTICIPANT_SUSPEND` envelopes; it does not mutate state or
    authorize slashing;
  - `SESSION_ESCROW_LOCK` now has a typed execution boundary in both ABCI and
    deterministic local block execution: the complete Funding Account,
    beneficiaries, reserve conservation and `funding_state_hash` are verified
    before the Consumer Wallet is debited, and Snapshot restore preserves the
    lock without duplicating the debit;
  - `SESSION_SETTLEMENT_PROPOSE`, `SESSION_SETTLEMENT_ACCEPT` and
    `SESSION_SETTLEMENT_FINALIZE` now have typed, pre-block-finality-bound
    execution in both consensus entrypoints, with exact Input Root,
    beneficiaries, reserve conservation, wallet credits/refunds and replay
    protection; the initial `SESSION_FORCE_SETTLE` profile only refunds
    remaining exposure for finalized Endpoint failure evidence and never pays
    an unacknowledged claim;
  - the ordinary local cooperative Settlement application path now creates one
    immutable `SESSION_SETTLEMENT_READY_COMMIT` before its proposal. The
    commitment binds the current Funding predecessor, Contract/effective-terms
    hashes, beneficiaries, Settlement Input roots and close reference, is
    idempotent across retries and does not move Q. Consensus-enabled
    cooperative Settlement now submits the same readiness, proposal,
    acceptance and finalization boundaries in dependency order, waits for
    verified finality, and applies only missing canonical projections;
    validator-local economic writes remain fail-closed before that boundary.
    Retries match readiness, proposal and acceptance by canonical payload
    identity rather than envelope timestamps, so reconnect cannot create a
    second economic operation for the same Settlement;
  - cooperative Settlement now persists the exact pending consensus envelopes
    in the Hypervisor snapshot before submission and removes them only after
    the local canonical projection is present. A restart can therefore retry
    the same operation ID, including when the network reports a duplicate
    transaction but finality evidence is already available;
  - `SESSION_ESCROW_EXTEND` and `SESSION_ESCROW_RELEASE` now provide typed,
    predecessor-bound Funding mutations: extensions debit only additional
    prepaid reserves, while releases refund only unsettled reserves under two-
    participant authorization and cannot consume dispute reserve;
  - `SESSION_CHECKPOINT_COMMIT` now persists monotonic integer exposure
    checkpoints with exact Funding state/evidence bindings, and checkpoint
    state survives ABCI, local-engine and Hypervisor snapshot restoration;
  - typed Settlement disputes now bind one `SESSION_SETTLEMENT_DISPUTE` to an
    exact finalized proposal, participant claimant, dispute hash and Evidence
    Root; `SESSION_SETTLEMENT_PARTIAL_FINALIZE` releases only undisputed
    amounts in both consensus entrypoints and preserves the bounded reserve as
    `DISPUTE_RESERVED`, including snapshot/restore and replay protection;
  - `SESSION_SETTLEMENT_CORRECT` now resolves that active reserve exactly once
    from a finalized partial transition, permits only Endpoint/Consumer
    allocation without Network Fee mutation or clawback, and persists the
    correction through snapshots;
  - Settlement proposals now bind the latest finalized Funding predecessor,
    including `SESSION_ESCROW_EXTEND` and partial `SESSION_ESCROW_RELEASE`,
    while legacy initial-lock payloads remain compatibility-readable;
  - typed Stake lifecycle operations now execute in both consensus entrypoints:
    `STAKE_LOCK`, `UNSTAKE_REQUEST` and `STAKE_RELEASE` debit/lock, persist a
    fixed 14-Epoch unbonding boundary and release only to the recorded owner;
  - typed `PARTICIPANT_SUSPEND` and `PARTICIPANT_REINSTATE` now persist
    evidence-bound suspension state, prior-finalized recovery evidence and
    minimum recovery Epoch checks, including Snapshot/rollback coverage.
  - the deterministic Validator Schedule builder now consumes canonical
    participant suspension state, excludes effective suspensions before
    retention/addition selection, and commits a suspension-state root into
    schedule evidence.
- implementation of `RFC-0061` now includes the authenticated replication and Registry Duty evidence slices:
  - the repo has centralized registry advertisement, discovery APIs, freshness tracking, endpoint publication visibility, deterministic Inventory Roots/segment manifests with Merkle inclusion paths, authenticated TLS plus Ed25519 peer replication, bounded manifest-driven catch-up/repair, quorum-bound multi-peer source selection with conflict evidence, signed single-object Proof of Registry challenges, and signed independent non-response confirmation;
  - consensus-finalized Registry duty evidence, fixed-point eligibility, and the non-minting `SERVICE_VERIFICATION_COMMIT` boundary are implemented;
  - the Epoch Engine now aggregates committed Registry inputs with diversity/cap distribution, and the Ledger exposes a consensus-finality-bound, budget-checked `REWARD_MINT` boundary;
  - the Registry reward mint boundary is now wired in both ABCI and deterministic local block execution, including same-block transition/mint rejection and wallet-credit application through the budget-checked Ledger path;
  - `SERVICE_VERIFICATION_COMMIT` is now a typed evidence-only consensus operation in both entrypoints, with report identity, Registry binding and duplicate-report protection, and it cannot credit a Wallet;
  - remaining work is the 11 catalog operations still outside the strict
    consensus transition matrix plus independent multi-validator rollout, not
    local Registry authority.
- implementation of `RFC-0062` now includes the local MVP Snapshot pipeline and a
  typed consensus commitment boundary:
  - portable Snapshot production, chunk verification, Registry distribution,
    staging restoration, trusted-checkpoint selection and atomic activation are
    covered by the M10 implementation and its integration tests;
  - both consensus entrypoints now validate metadata-only `SNAPSHOT_COMMIT`
    operations, including required content/state bindings, Epoch targeting,
    Registry references, duplicate Snapshot IDs and protocol-only origin;
  - external multi-validator finality, production trust-anchor governance and
    the remaining declared operation transitions and external multi-validator
    rollout remain separate public-network work.
- implementation of `RFC-0059` is also still pending beyond partial local scaffolding:
  - a canonical local ledger-operation stream now covers session, validation, endpoint lifecycle, endpoint Advertisement and Offer publication, epoch transition, reward mint, ordinary Wallet transfer, and dedicated Faucet Treasury funding; the deprecated in-core Faucet Claim path is inactive;
  - the Ledger now derives a deterministic finalized-operation replay registry
    from that canonical stream, binding operation ID, type, sequence and full
    record digest; duplicate IDs, conflicting identities and duplicate
    sequences fail closed on insertion and Snapshot/State Sync restore;
  - the local Ledger now also enforces the `REWARD_MINT` calculation-root, exact finalized `EPOCH_TRANSITION`, pool budget and reward-id idempotency boundary;
  - specialized consensus execution for canonical `SERVICE_VERIFICATION_COMMIT`, `EPOCH_TRANSITION` and transition-bound `REWARD_MINT` is now covered by ABCI and deterministic local block execution, including evidence binding, pre-block finality, sequential Epoch, root and budget checks;
  - typed consensus execution now also covers `SESSION_ESCROW_LOCK`,
    `SESSION_SETTLEMENT_READY_COMMIT`, `SESSION_SETTLEMENT_PROPOSE`,
    `SESSION_SETTLEMENT_ACCEPT`,
    `SESSION_SETTLEMENT_FINALIZE` and the conservative evidence-bound
    `SESSION_FORCE_SETTLE` subset in both ABCI and deterministic local block
    execution. The readiness commitment is immutable evidence only and is
    snapshot/replay protected; a proposal that opts into it must match all
    committed Settlement Input roots and Funding bindings;
  - the strict profile now closes the remaining 11 declared-but-unimplemented
    catalog operations instead of silently recording them; implementing those
    transitions and completing independent multi-validator rollout remain open.
- [x] Separate the canonical Session lifecycle from its economic funding
  mutation: `SESSION_ESCROW_LOCK` is the only MVP debit/reserve transition;
  finalized `SESSION_OPEN` binds the lock to Session Contract, Endpoint
  metadata and beneficiaries without moving funds. Same-block dependencies,
  duplicate opens, binding conflicts and Snapshot/restart reconstruction are
  covered by ABCI and deterministic Execution tests.
- [x] Add canonical lifecycle acceptance after finalized `SESSION_OPEN`.
  `SESSION_ACCEPT` is signed by the Endpoint Payment beneficiary, checks exact
  Session/Endpoint bindings and records no economic movement; same-block,
  duplicate and unauthorized acceptance paths are covered by both execution
  entrypoints.
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
1. Complete production Registry peer transport operation. The Replicator now has an opt-in fail-closed Ed25519 handshake gate with nonce replay protection for inbound and outbound exchange; operator-managed peer keys persist in the Registry snapshot, survive restart, and key rotation or disablement revokes the active replication session. A transport session now requires verified TLS, owns the outer message sequence, carries the signed handshake and resets authorization on reconnect. A bounded outbound reconnect supervisor now retries only approved peers, requires a fresh handshake after every new transport, and backs off on connection, frame or handshake-timeout failure. The listener, reconnect supervisor and outbox flushing are now composed by an explicitly injected `RegistryReplicationRuntime` and follow the Hypervisor lifespan without implicitly opening a port or loading a signing key. Operator deployment configuration and encrypted local Secret Manager handles are implemented. On `2026-07-29`, a controlled two-host Linux deployment proved persistent snapshot replication of an immutable object, followed by a forced server restart, fresh mTLS plus Ed25519 authentication and a second inventory exchange without runtime errors. On `2026-08-01`, the persistent controlled-testnet profile was also provisioned on `hv-node10` (`192.168.88.126`) and `node4` (`192.168.88.127`): both independent encrypted Secret Manager stores generated local Ed25519/mTLS identities, both peers were mutually approved, both listeners authenticated on TCP `9444`, both dedicated Hypervisor APIs passed `/health` on `8767`, and a seeded immutable object transferred from `.126` to `.127`. The profiles were migrated to systemd with restart-on-failure; restarting the `hv-node10` unit produced a fresh peer authentication timestamp on `node4` and preserved the replicated object. This is controlled operational evidence only; independent operator validation remains required before network-wide directory claims.
2. Package-backed Plugin Hosts now reject `UNSANDBOXED_HOST` and run only with `SANDBOX_REQUIRED` through a Docker boundary: read-only verified package mount, non-root UID, dropped capabilities, no-new-privileges, bounded PID/memory and no network. Activation credentials may persist through the Secret Manager, are absent from API/status records, and reach package Hosts only through a short-lived read-only secret-file mount rather than Docker environment variables. `PLUGIN_DATA_ONLY` now has an enforceable separate read-write mount at `/var/lib/aidn/plugin-data`. `DECLARED_EGRESS` now has an enforceable per-host supervisor boundary: the Plugin Host is isolated on a Docker internal network and reaches only an exact public DNS `host:port` TCP allowlist through a non-root HTTP CONNECT/absolute-form proxy sidecar; setup, signal and exit cleanup are covered by unit/protocol tests and a real Docker acceptance harness. `PRIVATE_ONLY`, `MODEL_STORAGE_ONLY` and arbitrary `CONTROLLED_PATHS` remain rejected. A privileged local Docker operator remains trusted because it can inspect bind mounts.
3. Bind Endpoint Configuration publications to a real Ed25519 owner-wallet signature. New owner wallets and API publications use a verifiable signature over the complete published record; public paid Session admission requires the signature to match the canonical owner identity. Public Registry advertisements carry that proof only for external-facing Endpoints, and Remote Endpoint attachment verifies the proof, summary binding and synchronized owner identity before creating a Proxy target. The verified owner public key, publication signature and verification state now persist in the Remote Endpoint reference, Proxy target and configuration snapshot. Legacy local records remain readable but are explicitly unverified and cannot open a public paid Proxy Session. Proxy publication hashes include the exact remote target fingerprint, and public admission reconciles the persisted Proxy target against the current remote catalog to reject stale proof. When the owner identity is absent locally, Remote attach performs a bounded root-only HTTP(S) peer sync and requires a hash-bound Ed25519 envelope matching the expected Registry node, operator and owner wallet before importing it. Authenticated Registry replication and peer transport authentication are implemented; independent-peer deployment validation remains pending.
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
   The software boundary is now fail-closed: local consensus submission state
   is exposed only as `locally_observed_finalized`, while Registry and economic
   evidence can claim `consensus_finalized` only from an operation-bound,
   externally verified source with matching local ABCI block/app commitments.
   The finality regression suite covers absent, mismatched, quorum-ambiguous
   and valid evidence. A public, independently operated multi-validator
   testnet remains the next operational acceptance step before public
   network-finality claims. A signed `PublicMultiValidatorNetworkProfile` and
   fail-closed acceptance tool now bind validator manifests, HTTPS RPC
   endpoints, distinct operator/control-group thresholds, trusted checkpoint
   input and release-authority signatures. The tool can emit the existing
   multi-RPC finality deployment only after out-of-band independence evidence
   is present; it does not claim that cryptographic RPC agreement proves
   organizational independence. See
   `docs/development/public-multivalidator-rollout.md`.

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

### GATE-0001 release status (local verification, 2026-08-03)

The deterministic and controlled operational portions of the release gate are
now executable and fail closed. The verified local evidence is bound to the
latest clean release-candidate commit and profile commitment
`sha256:4ebeab687d3871534b96399b77d26ccd8e53414a7c1882631e82e6dbb30af190`.

- [x] G0 Build Integrity: clean-tree package build, artifact hashes, signed
  release manifest, profile/catalog/fixture bindings, and dependency/license
  evidence.
- [x] G1 Deterministic Protocol: strict FIX-0001 fixtures, 49/49 active
  operation coverage, unsupported-version rejection, idempotency,
  predecessor, monetary-boundary and canonical-vector probes; 660 scoped
  consensus/settlement/ledger tests pass.
- [x] G2 State/Snapshot Integrity: controlled local snapshot restore and State
  Sync acceptance with identical StateRoot/AppHash and next-block transition.
- [x] G3 Multi-Node Consensus: four-validator controlled Ubuntu LAN evidence,
  transaction inclusion proofs, AppHash convergence and restart continuity.
- [x] G5 Fault Recovery: graceful restart, abrupt termination, host reboot,
  snapshot restore, State Sync, invalid snapshot and stale-predecessor drills;
  the aggregate and live reports are now hash-bound and require structured
  four-validator convergence, target identity/chain continuity and explicit
  host-reboot recovery evidence. Existing pre-hardening live reports must be
  recollected rather than edited.
- [ ] G4 Public Networking: live public RPC/P2P, bootstrap diversity and
  public finality evidence are still absent.
- [x] G4 collection plumbing: a read-only HTTPS `/status` and `/net_info`
  collector now emits hash-bound deployment checks and rejects unreferenced
  boolean/failed observations and non-credential-free RPC URLs; live public
  endpoints are still required.
- [x] G6 review plumbing: EVD-0001 supports a signed
  `attestations/independence-review.json`; the verifier requires a trusted
  reviewer key and exact operator, control-group and evidence-root binding.
  Live independent-operator evidence is still required.
- [ ] G6 Independent Operator: out-of-band attestations from distinct operator
  identities/control groups are still absent. The functional controlled-testnet
  MVP assumption for `hv-node10` remains narrower than this public-release gate.
- [ ] G7 Evidence Publication: final EVD-0001 bundle cannot be published until
  G4 and G6 evidence is available and the release-gate result is PASS.
- [x] G7 publication plumbing: `tools/build-release-evidence-bundle.py` now
  verifies G0-G6 before building, writes the excluded release-gate control file,
  and reruns strict EVD-0001 verification. This closes the implementation
  path, but does not manufacture the missing G4/G6 evidence.

Order of work right now:

1. Operator deployment configuration and encrypted local Secret Manager-backed certificate/signing-key handles now compose the explicitly injected Registry replication runtime. Automated local acceptance proves real mTLS, signed peer authentication, inventory exchange and object transfer between distinct local secret stores, and fixed timeout/sequence/concurrent-close defects. A host-separated Windows-to-Linux acceptance harness now proves the same flow over an SSH-forwarded mTLS connection with independently generated test credentials. A production verifier now runs the actual configured runtime against its durable Registry snapshot, requires authenticated inventory exchange and can require a declared immutable object transfer; its report explicitly does not claim organizational independence. A peer owned by an independent operator remains required before a directory trust claim.
2. Obtain independent-operator Registry peer evidence before allowing directory trust claims; the host-separated acceptance harness is ready.
3. Deploy signed remote-snapshot anchoring against an independently operated multi-validator testnet before making public network-finality claims. The controlled four-validator RPC/Merkle/restart drill is now passing; it is not independent-operator evidence. A controlled LAN deployment has now also proven one CometBFT v0.38.19 validator and one AiDN ABCI process on each of four distinct Ubuntu hosts: all four nodes reached the same height and application hash, each held three P2P peers, and the external transaction/Merkle/restart drill passed while one physical validator restarted. The controlled-LAN verifier now gates further drills on four private RPC views, unique validator identities, P2P quorum, synchronized height and one application hash; its output explicitly excludes independent-ownership claims. A separate read-only external-testnet verifier now requires at least two HTTPS RPC views, an operator-provided trusted checkpoint and one exact finalized operation; it cryptographically checks the transaction, Merkle proof and validator transition before rejecting divergent endpoint evidence. Independent validator ownership still requires out-of-band operator evidence.
4. Complete external acceptance of the declared-egress Plugin Host boundary on the Ubuntu operator node, then keep unsupported `PRIVATE_ONLY`, `MODEL_STORAGE_ONLY` and arbitrary `CONTROLLED_PATHS` policies blocked until their own enforcement backends exist. Controlled acceptance on `192.168.88.127` now passes both the no-network/scoped-data and declared-public-egress Docker harnesses, including cleanup verification; evidence is recorded in [plugin-host-egress-acceptance-2026-08-02.md](./docs/development/plugin-host-egress-acceptance-2026-08-02.md) and does not claim independent operator ownership.
5. Use the independent-operator onboarding kit for the preceding Registry and finality evidence: [guide](./docs/development/independent-operator-onboarding-and-acceptance.md), one-command Ubuntu loopback bootstrap, secret-free workspace generator, read-only acceptance runner, and reviewed systemd template. Its reports intentionally do not establish independent ownership by themselves.
6. Controlled testnet peer identity provisioning, systemd-managed replication-enabled Hypervisors, and restart/reconnect evidence on `hv-node10` and `node4` are complete. The remaining step is to collect production Registry acceptance evidence from an independently operated peer; a verifier run must use a dedicated listener or an idle peer because one Registry peer identity permits one active transport session at a time.

## Post-MVP Protocol Work

### Development contribution accounting and rewards

This work is intentionally outside the functional MVP. It must not alter current Endpoint economics, escrow, or Validator rewards until its independent Governance and tokenomics decisions are approved.

1. Implement [RFC-0068](./docs/product/RFC-0068-development-contribution-accounting-and-attribution-protocol.md) with an evidence-first boundary: eligible repositories, protected-branch merge verification, Contributor Identity, signed Wallet binding, immutable merged-commit Wallet claims, contribution attestations, ECU/CU calculation, contributor groups, role allocation, challenge windows, and maturity records. The executable slice is documented in [rfc-0068-evidence-mode.md](./docs/development/rfc-0068-evidence-mode.md); GitHub evidence still cannot mint Q.
2. Approve [ECO-0007](./docs/product/ECO-0007-development-reward-pool-and-distribution-policy.md) before any development-reward transfer. The fixed-point simulator, deterministic launch matrix, and RFC-0068-to-ECO-0007 preview/consensus-plan bridge are implemented and documented in [development-contribution-reward-bridge.md](./docs/development/development-contribution-reward-bridge.md); activation still requires Governance approval and parameter selection.
3. Implemented the non-emitting Governance activation gate in `reward/development_activation.py`. It binds an exact ECO-0007 policy hash to an effective epoch, authority set, quorum, and Ed25519 approvals; it rejects missing approvals, mismatched policy versions, premature epochs, revoked approvals, and invalid signatures before any Ledger integration.
4. The non-emitting dry-run commitment builder is implemented for policy, pool, allocation, schedule, and payment-state roots; it remains explicitly simulation-only and cannot reserve or transfer Q.
5. `DEVELOPMENT_REWARD_CALCULATE` now commits a self-contained, activation-bound calculation as non-emitting Ledger evidence in both ABCI and deterministic execution; it cannot reserve, mint or transfer Q.
6. `DEVELOPMENT_POOL_ALLOCATE` is now implemented as a source-bound, non-emitting reserve record. It requires a finalized `EPOCH_TRANSITION` budget and a finalized calculation from prior blocks, an explicit `POOL_ALLOCATION` Governance scope, replay protection, and snapshot persistence. It does not credit Wallets or mint Q.
7. `DEVELOPMENT_REWARD_RESERVE` is now implemented as a schedule-bound, non-emitting reserve record. It requires finalized calculation and pool-allocation sources, an explicit `DEVELOPMENT_RESERVES` Governance scope, exact schedule/hash binding, bounded aggregate reservations, replay protection, and snapshot persistence. It does not credit Wallets or mint Q.
8. `DEVELOPMENT_REWARD_PAY_IMMEDIATE` is now implemented as a source-bound consensus transition. It requires finalized calculation, pool-allocation and reward-reserve predecessors, exact payment-hash/role/stage/amount/Wallet binding, replay protection, snapshot persistence, and credits only the verified immediate stage; it is not a `REWARD_MINT` alias.
9. `DEVELOPMENT_REWARD_PAY_MATURITY` is now implemented for stage one and stage two. It requires the same finalized calculation/pool/reserve sources plus a finalized `EPOCH_TRANSITION` whose opening epoch reaches the exact maturity boundary; only `RESERVED` maturity stages are payable, and replay/conservation/snapshot behavior is covered in ABCI and deterministic execution.
10. `DEVELOPMENT_REWARD_MARK_UNCLAIMED` is now implemented as a source-bound, non-crediting transition. It accepts only an exact `UNCLAIMED` stage without a Wallet, persists a claim-expiration record, leaves the reward reserve unchanged, and rejects duplicate stage identities.
11. `DEVELOPMENT_REWARD_CLAIM` is now implemented as a source-bound Wallet transition. It requires the finalized unclaimed record, a finalized epoch boundary inside the immutable claim window, and an RFC-0068 Ed25519 Wallet binding; it creates a separate immutable `CLAIMED` record, consumes exactly one stage, credits only the bound Wallet, and rejects replay. Forge data remains evidence, not a payment authority.
12. `DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED` is now implemented as a source-bound, non-crediting carryover transition. It requires a finalized claim-window boundary after expiry, preserves the original unclaimed evidence, returns exactly one stage to the allocation's available budget, and rejects claim/expiry replay with snapshot-safe conservation checks.
13. `DEVELOPMENT_REWARD_FINALIZE_COMMITMENT` is now implemented as an evidence-only close of the exact calculation, allocation, reserve, payment, unclaimed, claim and expiry set. It stores deterministic roots and is replay-protected without minting, paying or changing Wallet balances.
14. A signed ECO-0007 rollout profile now provides a fail-closed boundary for epoch reward atoms, contribution count and optionally per-contributor reward. The profile is bound into the activation approval and calculation commitment; calculations above the active cap are rejected before reserve/payment transitions.
15. Pool carryover, bounty create/reserve/release/expiry, unvested cancellation, and reward correction are now implemented as immutable, source-bound, non-emitting transitions in both ABCI and deterministic execution. Snapshot/restore, replay protection, conservation checks, and strict operation coverage are included. Forge data remains evidence, not a payment authority.
16. Signed public multi-validator profile/acceptance infrastructure is implemented: validator manifests, CometBFT checkpoint binding, profile-signature quorum, static acceptance reports, and finality-config projection. It does not claim live public deployment or organizational independence. Live HTTPS RPC observations, a canonical genesis/trust-anchor release bundle, production deployment/fault-drill evidence, and out-of-band operator attestations remain explicit public-network gates.

17. Added the executable implementation and operator specification pack under
    [docs/development/executable-spec-pack](./docs/development/executable-spec-pack/README.md).
    It is the bridge from architecture RFCs to implementation claims, fixture
    coverage, migration rules, release gates, and public evidence. The pack is
    Draft: command names and fixture manifests become release-authoritative only
    after the corresponding tooling and machine-readable profile are checked in.
18. Added the first executable verification slice for that pack: a deterministic
    machine-readable Implementation Profile generator, strict FIX-0001 manifest
    and ABCI fixture runner, EVD-0001 public evidence verifier with Merkle root
    and Ed25519 operator attestation checks, and a fail-closed release-gate CLI.
    The current profile remains `DRAFT_CANDIDATE`; the gate reports the 11 known
    consensus operations without strict transitions and all missing operational
    evidence instead of claiming a public release.
19. Classified the 11 historical operation names that were superseded by typed
    Session, escrow, stake, validation and epoch transitions as explicit
    `legacy_operation_types`. They remain reject-only at strict runtime and are
    no longer mistaken for missing active MVP transitions; G1 now measures the
    active profile without introducing unsafe aliases.
20. Added the executable controlled-local G2 snapshot acceptance harness. It
    proves durable export, direct restore, chunked State Sync, corrupt-snapshot
    rejection, identical StateRoot/AppHash at the snapshot height, and one
    identical next-block transition. Snapshot restore now rebuilds admission
    wallet sequences while the restored Ledger remains the replay authority; a
    restored node cannot claim a matching AppHash and then reject the next
    valid transaction. This evidence is intentionally not a substitute for
    live multi-validator or independent operator evidence.

21. Added the immutable merged-commit Wallet claim verifier and the
    `DevelopmentContributionRewardService`, plus
    `tools/create-contributor-wallet-claim.py`. Finalized RFC-0068
    attestations now produce an ECO-0007 preview and an activation/pool-bound
    ordered operation plan. The plan is inspectable but not submitted by the
    HTTP evidence API; live payout requires Governance activation and
    finalized epoch evidence.
22. Added the external `services/aidn-faucet` implementation slice for
    ECO-0008: hash-bound Treasury manifest loading, fixed-daily and
    accumulating policies, signed Wallet challenges, SQLite idempotency,
    signed ordinary `WALLET_TRANSFER` envelopes, and explicit admitted versus
    finalized claim handling. The service now also ships a CometBFT submission
    adapter with exact-envelope RPC failover, canonical sequence/balance
    quorum reads, verified finality reconciliation, and separate creator
    pause/resume/low-balance controls. The CLI now has a built-in production
    factory that binds the manifest to an operator-approved multi-RPC finality
    file, and exposes consensus rejection separately from transport
    unavailability. Signer rotation remains a new Treasury lineage, not an
    online mutable setting.
23. Added the one-time `TREASURY_FUND` consensus transition for an already
    finalized network. It requires a configured CONSENSUS Treasury manifest,
    exact `10,000,000 Q`, creator/recovery authorization, envelope
    authentication and replay-safe Treasury identity checks. A signed envelope
    can be generated with `tools/create-faucet-treasury-funding.py`; it is not
    submitted by the tool.
24. Added a separate Faucet control plane: an authenticated `/mcp` endpoint
    with agent/creator tool separation, auto-renewing bearer-bound MCP
    sessions, status/policy resources, creator pause/resume/watermark controls,
    sanitized claim inspection and exact-claim reconciliation. Added a minimal
    responsive creator UI at `/`; its token remains browser-memory-only and it
    never exposes Treasury key material or signed envelopes.
25. Added ECO-0009 and the canonical Treasury activation boundary. The Faucet
    now fails closed unless a hash-bound proof matches the manifest, chain and
    Wallet, proves the exact finalized `TREASURY_FUND` (or canonical Genesis
    manifest), and includes a quorum-consistent current balance. The ABCI
    application exposes the canonical `faucet/treasury-manifest` query and the
    Faucet UI reports activation state and its diagnostic reason.

26. Added the production-bound ECO-0007 reward batch layer. A signed,
    future-effective production profile now binds network/chain identity,
    Development Pool, activation approval, operation scope and batch limits.
    The production batch builder verifies the profile, finalized epoch/pool
    references, contribution and Q caps, then emits an inspectable ordered
    consensus plan without submitting transactions or minting Q. The operator
    workflow is documented in
    `docs/development/eco-0007-production-reward-batch.md`.
27. Added the idempotent ECO-0007 production batch executor. It accepts only
    the exact hash-bound batch envelopes, persists the current envelope before
    submission, waits for verified consensus finality after every predecessor,
    and resumes after restart without replacing operation identities. It does
    not create keys, mint Q locally, or bypass Governance/operator policy.
28. Added the canonical ECO-0007 epoch/pool preflight query and quorum CLI.
    Validators now expose only the finalized epoch transition reference, exact
    pool budget and pool-budget reference needed by a production batch. The
    read-only quorum collector blocks on stale/old validators, missing budgets,
    catching-up nodes and divergent projections instead of selecting one local
    snapshot. The production batch now embeds a typed, hash-bound quorum
    preflight and rejects source-operation, budget-reference or allocation
    amount substitution. The controlled three-validator rollout is recorded in
    `docs/development/eco-0007-validator-rollout-acceptance-2026-08-12.md`;
    the payout gate remains closed until the live query reports a finalized
    epoch transition and pool budget.
29. Added the operator execution CLI for ECO-0007 production batches. It
    rechecks the canonical quorum preflight before every retry, binds the
    batch to the approved multi-RPC finality configuration, persists exact
    in-flight envelope diagnostics, and exits successfully only after every
    ordered operation is finalized. It never creates keys or credits local Q.

### Current post-MVP implementation gate

- [x] ECO-0007 carryover and bounty lifecycle transitions are consensus-applied and persisted.
- [x] ECO-0007 unvested cancellation and correction transitions are consensus-applied, append-only, and persisted.
- [x] Define ECO-0008 and bind the secret-free Faucet Treasury manifest into
  Genesis or the one-time consensus funding boundary. The Faucet policy
  remains outside Hypervisor/Ledger and spends only through signed canonical
  `WALLET_TRANSFER` operations.
- [x] Implement the external Faucet policy/signing/idempotency slice under
  `services/aidn-faucet`, including the default CometBFT submitter/finality
  wiring, exact-envelope failover, creator controls, and explicit rejection
  diagnostics.
- [x] Add the separate Faucet MCP and minimal creator UI surfaces with
  token-separated agent/creator capabilities and no secret-material exposure.
- [x] Add ECO-0009 Treasury activation proof, canonical Genesis manifest query,
  exact consensus funding-operation binding and fail-closed claim enforcement.
- [x] Extend the Faucet live-acceptance runner with an optional required
  external-finality mode that verifies the exact `WALLET_TRANSFER` through the
  configured CometBFT RPC quorum and trusted checkpoint; the live deployment
  result remains an operational gate and is not inferred from local tests.
- [x] Stabilize Faucet CometBFT submission against structured JSON-RPC errors:
  idempotent `tx already exists in cache` responses remain admitted, ordinary
  CheckTx errors remain rejected, and the upgrade helper prevents stale
  `site-packages` copies from shadowing the reviewed checkout.
- [x] Verify Treasury activation and one payout against a live canonical
  multi-validator network; see [Faucet live payout/finality acceptance](./docs/development/faucet-live-payout-finality-acceptance-2026-08-12.md).
- [x] Prove Faucet payout finality across at least two validators, including
  restart/reconciliation and exact-envelope RPC failover evidence. The
  controlled-localnet result is recorded in the acceptance report; it does not
  claim public-network or independent-operator readiness.
- [x] Add the replay-safe one-time consensus funding path for `10,000,000 Q`
  on networks whose Genesis is already finalized; it never edits Genesis or
  credits a database directly.
- [x] Merged-commit Wallet claims and RFC-0068 to ECO-0007 reward planning are implemented.
- [x] Add the hash-bound ECO-0007 production profile and bounded production
  reward-batch builder; keep the resulting plan non-submitting until live
  finality evidence is available.
- [x] Add the idempotent production batch executor with exact-envelope
  persistence, ordered predecessor checks, and verified-finality gating.
- [x] Add the canonical epoch/pool read-only preflight and quorum CLI; keep
  production reward execution blocked until all target validators expose it.
- [x] Add a resumable operator execution CLI with fresh preflight checks and
  multi-RPC finality binding; keep live execution fail-closed on stale batch or
  unavailable validators.
- [x] Roll out the ECO-0007-aware ABCI image sequentially to the controlled
  validators and verify health, preserved state mounts, rollback containers,
  CometBFT quorum and the live read-only preflight; see
  [validator rollout acceptance](./docs/development/eco-0007-validator-rollout-acceptance-2026-08-12.md).
- [ ] Activate a production ECO-0007 reward profile and execute a finalized contribution payout batch against a real epoch pool.
- [x] Public multi-validator profiles are signed, hash-bound, quorum-checked, and projected into the existing CometBFT finality configuration.
- [x] Generate and verify the current Implementation Profile and execute the
  checked-in FIX-0001 ABCI vector deterministically.
- [x] Verify EVD-0001 artifact hashes, Merkle root, safe publication paths and
  Ed25519 operator attestation; expose incomplete GATE-0001 status explicitly.
- [x] Run controlled-local G2 snapshot/State Sync acceptance and verify its
  report through the release-gate CLI.
- [ ] Collect live public RPC observations and bind them to the accepted profile.
- [ ] Publish a canonical genesis/config/trusted-checkpoint release bundle and verify it during deployment.
- [ ] Complete production deployment, restart/state-sync/fault-drill evidence across independently operated validators.
- [ ] Obtain and retain out-of-band operator/control-group independence attestations before making public trust claims.

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
- Faucet Treasury and policy execution: [docs/product/ECO-0008-faucet-treasury-and-policy-execution.md](./docs/product/ECO-0008-faucet-treasury-and-policy-execution.md)
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

## Latest Acceptance Update

- Registry replication now starts inventory exchange automatically after every authenticated inbound or outbound connection, scopes outbox flushing to the intended peer, and exposes sanitized runtime diagnostics at `GET /registry/replication/status`.
- The controlled LAN profile was extended to `hv-node10` (`192.168.88.126`) and `node3-independent` (`192.168.88.128`) with one outbound initiator, bidirectional object convergence, and restart/re-authentication evidence. Snapshot persistence is serialized to prevent concurrent peer handlers from racing on the shared temporary file. This remains technical evidence under one operator context, not proof of organizational independence.
- MVP acceptance policy (2026-08-01): the project explicitly accepts `hv-node10` (`192.168.88.126`) as an independent operator for the functional controlled-testnet MVP. This closes the MVP operator-independence gate and waives additional external-operator testing for MVP. It does not change protocol verification: reports continue to use `ownership_evidence: NOT_PROVEN_BY_PROTOCOL`, and public directory trust or public multi-validator finality still require separate evidence and Governance approval. See [MVP Operator Independence Assumption](./docs/development/mvp-operator-independence-assumption.md).
- Functional `MVP-0001` acceptance (2026-08-01): signed wallet-identity sync is pinned, reconciled and restart-persistent; live llama.cpp, vLLM and Ollama conformance passed; provider-specific restart/recovery tests passed without duplicate execution or payment. The detailed evidence is in [MVP Acceptance Report](./docs/development/mvp-acceptance-2026-08-01.md).
- Controlled four-validator LAN acceptance (2026-08-02): strict ABCI operation
  coverage, escrow/failure/Session lifecycle and Reputation evidence chains,
  CometBFT Merkle proofs, four-way AppHash convergence and remote validator
  restart continuity all passed on the live Ubuntu hosts. This is controlled
  lab evidence only; the detailed record is [here](./docs/development/cometbft-lan-acceptance-2026-08-02.md).
- MCP TLS rotation acceptance (2026-08-04): the actual Secret Manager-backed
  production HTTP launcher passed certificate rotation and MCP reconnect on
  `192.168.88.127`; the detailed record is [here](./docs/development/mcp-tls-rotation-acceptance-2026-08-04.md).
- Operator readiness wizard (2026-08-05): the Hypervisor Overview now exposes
  one canonical, read-only readiness projection for Consensus RPC, owner
  Wallet, host capacity, Provider Instance, Model Deployment, Runtime Binding,
  Bundle and Endpoint. It separates local execution readiness from network
  readiness, gives bounded next actions, and explicitly reports unavailable
  probes instead of guessing. See [UX-0003](./docs/product/UX-0003-operator-readiness-wizard.md).
- Consensus provisioning (2026-08-05): both Ubuntu operator entry points now
  install and manage CometBFT automatically. Legacy nodes without management
  metadata receive a concrete migration instruction; the dashboard remains
  read-only and does not expose arbitrary host command execution. See
  [operator consensus provisioning](./docs/development/operator-consensus-provisioning.md).
- Validator AppHash compatibility now treats empty post-MVP Ledger extensions as absent during canonical hashing, so upgrades do not invalidate historical snapshots merely by adding empty stake, penalty, checkpoint, dispute, or correction fields; populated extensions remain committed.
- The functional controlled-testnet MVP gate is now closed. Remaining priorities in this section are public-network/post-MVP claims: independent-operator evidence, public directory authority, external multi-validator finality, and enforceable production trust policy.

## Maintenance Rule

Every meaningful architecture or milestone change should update this file in the same branch.
