# Provider Deployment, Marketplace Authoring, And Ubuntu Onboarding Implementation Plan

**Goal:** Ship the three operator journeys defined in the matching
[design](../specifications/2026-08-14-provider-marketplace-bootstrap-slices-design.md).

**Architecture:** Preserve the current immutable plan/approval/job contracts.
Add a specialized exact-allowlist executor for reviewed Ubuntu Provider
runtimes, a server-sanitized Marketplace description contract, and post-install
wallet/agent onboarding on top of the existing one-line bootstrap.

## Phase 1: Reviewed Ubuntu Provider Catalog (started)

- [x] Add an exact Provider dispatcher with no arbitrary command or script path.
- [x] Add pinned `install/start/status/stop` scripts for Whisper, Ollama,
  llama.cpp, and vLLM.
- [x] Keep runtime installation separate from model configuration/download.
- [x] Force managed Provider HTTP listeners to loopback.
- [x] Add `ProviderRuntimeInstallerDescriptor` validation to Plugin manifests.
- [x] Mark the generic executor path `RECORDED_ONLY`; do not place host commands
  in its `InstallationPlan.processes` collection.
- [x] Add focused manifest and shell-contract tests.
- [ ] Add checksum/signature verification for downloaded installer/bootstrap
  payloads where upstream distribution supports it; archive verified digests.
- [ ] Run destructive-free smoke tests on fresh Ubuntu 22.04 and 24.04 VMs for
  CPU Ollama, CPU llama.cpp, NVIDIA vLLM, and Docker-backed Whisper.

## Phase 2: Allowlisted Runtime Executor

- [x] Add typed Provider runtime invocation/result models and reject unknown
  fields or generic `command`/`shell` arguments.
- [x] Add an injected broker adapter that builds only the reviewed dispatcher
  argv and bounds timeout/output; its runner is explicit and never uses a
  shell.
- [ ] Add a root-owned local runtime broker with OS-peer authentication and an
  exact compiled map from Provider/action to repository-owned implementation.
- [ ] Add an unprivileged Hypervisor client for the broker; no generic shell or
  subprocess inputs cross the API boundary.
- [ ] Bind every invocation to approval ID, plan/configuration hashes, pinned
  version, installation generation, and operator identity.
- [ ] Persist bounded progress events and state transitions on the existing job
  record; add polling and cancellation endpoints.
- [ ] Make install/start/status/stop idempotent and add rollback semantics per
  Provider.
- [ ] Add failure-injection tests: download failure, sudo/broker denial, port
  collision, unsupported GPU, health timeout, cancellation, and restart replay.
- [ ] Add Linux integration tests proving argument tampering and arbitrary
  command/script/environment injection fail closed.

## Phase 3: One-click Providers Workspace

- [ ] Add a catalog read model with install support, reviewed version,
  prerequisites, resource fit, installed state, and backend readiness.
- [ ] Add reviewed Provider cards/list and selection state.
- [ ] Add compact preflight/permission review and one primary `Install` action.
- [ ] Show durable job progress and precise actionable failures.
- [ ] On success, refresh Provider inventory and present secondary `Configure
  model` and `Create Runtime Binding` actions.
- [ ] Move `Attach existing Provider` to the advanced path without removing it.
- [ ] Cover keyboard navigation, focus management, narrow layouts, reduced
  motion, loading, empty, offline, and retry states.
- [ ] Do not enable the button when only the recorded executor is configured.

## Phase 4: Marketplace HTML Description Backend

- [x] Add the versioned Marketplace description model to Endpoint configuration.
- [x] Define and pin the v1 server-side sanitizer; its element,
  attribute, and URL-scheme allowlist in one server module.
- [x] Enforce source/output byte limits and nesting limits.
- [x] Compute `content_hash` from sanitizer version and sanitized HTML.
- [x] Add a server-side sanitize/preview endpoint; the existing Endpoint draft
  create/update API accepts the validated description model.
- [x] Bind Endpoint publish/advertisement to the exact sanitized description
  hash and preserve immutable published versions.
- [x] Add XSS regression fixtures for scripts, event handlers, SVG, malformed
  tags, encoded protocols, CSS URLs, data URLs, and oversized input.
- [x] Verify older Endpoint records without HTML remain readable.

## Phase 5: Marketplace Authoring UI

- [x] Add HTML source editor and server-generated preview.
- [x] Keep structured profile fields as accessible metadata alongside HTML.
- [x] Render only server-returned sanitized HTML in the dashboard preview.
- [ ] Add explicit validation, unsaved-change, publish-in-progress, published,
  and failed states.
- [ ] Confirm Endpoint version, visibility, price, policy, and description hash
  before publication.
- [ ] Add browser tests proving stored XSS cannot execute.

## Phase 6: Wallet And Agent Onboarding Commands

- [x] Inventory and reuse the canonical wallet create/import APIs and MCP enrollment
  approval path; do not add a second identity store.
- [x] Add CLI commands for wallet status, create, and import with `/dev/tty`
  secret input and atomic `0600` state persistence.
- [x] Add CLI commands for enrollment status/list/approve/reject using the
  existing MCP credential and permission models; agent request creation stays
  with the agent's own enrollment key.
- [x] Make wallet and enrollment commands idempotent where mutation is
  possible and return bounded machine-readable output plus concise guidance.
- [x] Add tests that imported private keys and enrollment retrieval secrets do
  not enter CLI output; pairing remains a deliberate one-time local display.

## Phase 7: Bootstrap Wizard Integration

- [ ] Split the current script into named, restartable steps with a local
  completion-state file containing no secrets.
- [ ] Add preflight and final execution summary before the first mutation.
- [x] After service health succeeds, offer wallet create/import/skip.
- [x] Create a one-time dashboard pairing code and show its expiry.
- [x] Guide agent enrollment and approval through the existing MCP boundary,
  with an explicit skip path.
- [x] Print URLs, service commands, public identity paths, and a secret-free
  onboarding summary.
- [ ] Publish a one-line command pinned to a reviewed release rather than
  `main`, including a documented verification path.
- [ ] Validate fresh install, interrupted rerun, existing-identity reuse,
  non-interactive mode, and uninstall/recovery on Ubuntu 22.04 and 24.04.

## Release Gate

- [ ] Run Python lint and targeted/full relevant test suites.
- [ ] Run ShellCheck and Bash syntax checks on all Ubuntu scripts.
- [ ] Complete fresh-VM acceptance with evidence for all four Provider profiles.
- [ ] Complete browser acceptance for Provider install and Marketplace publish.
- [ ] Confirm roadmap and operator documentation match actual enabled behavior.
