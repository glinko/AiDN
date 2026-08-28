# Interactive Hypervisor installation

This document describes the first CLI slice of the Node Steward assisted
installation flow. The entry point is
`tools/aidn-operator-bootstrap-ubuntu.sh`.

## Two modes

The first interactive question is:

```text
Installation mode (manual/ai_assisted)
  1) Manual
  2) AI-assisted
Enter the number:
```

All finite-choice questions use the same numbered interaction. The operator
can enter `1`, `2`, `3`, and so on instead of typing a long value; pressing
Enter selects the marked default. The previous textual values remain accepted
for compatibility with operators who already use them in scripts or muscle
memory. Free-form fields (paths, IDs, RPC URLs, and custom model references)
still require text input.

`manual` keeps the existing step-by-step operator flow. `ai_assisted` does not
remove or infer any required value. The installer still asks for and validates
the node identity, storage, consensus, wallet, dashboard, API, and Registry
choices. This prevents an assistant from silently choosing a network identity,
opening a listener, or creating a wallet on the operator's behalf.

After the required questions, AI-assisted mode offers a bounded continuation:

1. reviewed Provider (`ollama`, `llama.cpp`, `vllm`, or `skip`);
2. numbered model catalog with an estimated download size, VRAM/RAM budget,
   and a conservative context profile;
3. private Endpoint action (`skip`, `draft`, or `start`);
4. handoff (`continue` with the Resident Steward or `dashboard`).

The built-in catalog currently contains Apache-2.0 Qwen3 GGUF choices:

| Choice | Approx. artifact | Estimated VRAM | Estimated RAM | Intended use |
| --- | ---: | ---: | ---: | --- |
| Qwen3 0.6B Q8_0 | 0.64 GB | ~1.5 GB | ~2 GB | lightweight resident Steward and checks |
| Qwen3 1.7B Q4_K_M | ~1.1 GB | ~2.5 GB | ~4 GB | fast local control tasks |
| Qwen3 4B Q4_K_M | ~2.5 GB | ~4–6 GB | ~8 GB | balanced general local model |
| Qwen3 8B Q4_K_M | ~5.0 GB | ~7–10 GB | ~12 GB | stronger local reasoning on a single GPU |
| Qwen3 14B Q4_K_M | ~9.0 GB | ~12–16 GB | ~20 GB | only when the node has sufficient headroom |

These are planning estimates for one active request and roughly 8K context;
larger context windows, batching, and KV-cache growth require additional
capacity. The operator can choose `Custom model` to enter another bounded
model ID and public source. Built-in entries resolve immutable Hugging Face
revisions and are accepted only when both the exact byte count and SHA-256
match the catalog below:

| Model | Hugging Face revision | Exact bytes | SHA-256 |
| --- | --- | ---: | --- |
| Qwen3 0.6B Q8_0 | `23749fefcc72300e3a2ad315e1317431b06b590a` | `639446688` | `9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031` |
| Qwen3 1.7B Q4_K_M | `daeb8e2d528a760970442092f6bf1e55c3b659eb` | `1282439264` | `d2387ca2dbfee2ffabce7120d3770dadca0b293052bc2f0e138fdc940d9bc7b5` |
| Qwen3 4B Q4_K_M | `bc640142c66e1fdd12af0bd68f40445458f3869b` | `2497280256` | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` |
| Qwen3 8B Q4_K_M | `7c41481f57cb95916b40956ab2f0b139b296d974` | `5027783488` | `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785` |
| Qwen3 14B Q4_K_M | `530227a7d994db8eca5ab5ced2fb692b614357fd` | `9001752960` | `500a8806e85ee9c83f3ae08420295592451379b4f8cf2d0f41c15dffeb6b81f0` |

Once a concrete `llama.cpp` artifact is selected, the installer performs a
free-space preflight before starting the bounded background cache prefetch. It
reserves the artifact size, any existing target being replaced, and a safety
margin for the temporary file. A pinned artifact is never moved into the final
cache path until its size and SHA-256 pass; the state marker records
`integrity_mode: pinned`. Custom sources remain supported: they use the same
atomic download and byte-limit path, but are marked `computed_only` unless the
source exactly matches a built-in catalog entry. A custom Hugging Face source
may include `@<40-hex-revision>` to avoid a moving `main` reference. This
prefetch does not install a provider, register a model, start a runtime, or
publish an Endpoint; those lifecycle actions remain explicit and reviewable.

### Background model prefetch

The prefetch worker downloads only public HTTPS/Hugging Face artifacts and
writes atomically to the selected node data directory. It keeps an owner-only
state marker next to the final model path and updates `status`, byte counts,
percent, PID, expected integrity metadata, and SHA-256. On rerun it re-hashes
an existing completed target before reusing it, so a corrupted cache is never
silently adopted. The CLI renders a snapshot progress bar between questions so
the input prompt is never overwritten by a competing writer.
When the later model-install action runs, the Hypervisor adopts a matching
completed prefetch instead of downloading the same artifact a second time. A
failed or stale prefetch safely falls back to the normal model-install worker;
the installer carries pinned size/SHA-256 metadata into that job, so the
fallback is also fail-closed before an artifact can become `completed`.
The default prefetch ceiling is 64 GiB and can be changed for a controlled
installation with `AIDN_PREFETCH_MAX_BYTES`.

Every optional question explains its consequence. A model reference is never
treated as executable code, and a URL containing credentials, query strings,
or fragments is rejected.

## Durable handoff

The installer writes an owner-only plan at:

```text
<data-dir>/installation-plan.json
```

It also records the plan path and the selected mode in
`<data-dir>/bootstrap-state.json`. The plan is resumable and contains no
private keys, wallet material, or agent token. It records authority boundaries:

- Provider installation requires explicit operator review.
- A selected llama.cpp artifact may be prefetched in the background; model
  registration and runtime activation still require explicit operator review
  and resource checks.
- Endpoint publication still requires validation and existing Hypervisor
  policy.
- The Resident Steward cannot execute arbitrary shell commands or mutate state
  merely because assisted mode was selected; its installation tool can only
  advance the allowlisted, plan-bound private workflow below.

When assisted mode is selected, the generated service exports
`AIDN_INSTALLATION_SETUP_MODE=ai_assisted` and configures the CPU-first Resident
Steward profile. The Resident inference adapter and Resource Broker integration
are implemented. The installer remains a control-plane boundary: the Steward
may advance only the reviewed private workflow through the same policy-bound
  service actions as the Dashboard. The selected artifact may already be
  cached by the installer, but the Steward still does not silently register
  it, reserve VRAM, or publish an Endpoint; those changes continue through
  their dedicated approval, admission and validation paths.

## Non-interactive use

Existing automation remains manual by default. An explicit assisted plan can
be supplied without opening prompts:

```bash
bash tools/aidn-operator-bootstrap-ubuntu.sh \
  --non-interactive \
  --setup-mode ai_assisted \
  --setup-provider llama.cpp \
  --setup-model unsloth/Qwen3.8-27B-GGUF \
  --setup-model-source hf://unsloth/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-Q4_K_XL.gguf \
  --setup-endpoint draft \
  --setup-handoff dashboard
```

The command stages the plan; it does not publish an Endpoint. On the Overview
page the Dashboard now shows an **Assisted setup** review card when the plan is
available. The card exposes the selected provider, model, endpoint intent and
integrity status. `Review and continue` is a plan-hash-bound operator action:
it re-reads the file, rejects legacy or tampered plans, and persists an
idempotent, secret-free **Provider review**. Once the operator approves that
exact Provider plan in the normal Provider workflow, the card can submit the
approval to the privileged broker. Provider installation, model
registration/materialization, Bundle creation, Runtime activation, validation
and publication remain separate policy-gated actions. The review never attempts
a hidden host mutation and cannot turn a model URL into a permission grant.

The Dashboard read endpoint is:

```text
GET /operators/dashboard/installation-plan
```

The Resident Steward receives the same bounded projection through the
read-only MCP tool `aidn.steward.installation_workflow` or resource
`aidn://steward/installation`. It exposes the plan hash, observed stages,
`next_action`, completion summary and authority boundaries, but never exposes
private keys or turns a workflow observation into permission to mutate the
host. A separately scoped `STEWARD:EXECUTE` session may call
`aidn.steward.installation_apply` after creating an MCP plan. The tool accepts
only the current next action and forwards the persisted installation-plan hash
to the Hypervisor; it cannot create an operator approval, install an unreviewed
Provider, or publish an Endpoint.

For a compact polling target, the same service exposes the derived workflow
only:

```text
GET /operators/dashboard/installation-workflow
```

It returns the current `stages`, required-step progress, and one `next_action`.
The projection is recomputed from observed provider instances, model-install
jobs, Bundles and Endpoints after every read; it does not mark a step complete
because the plan merely requested it. A future event-driven Steward can use
this endpoint after reconnecting, while retaining a recovery poll for missed
events.

The protected apply operation is:

```text
POST /operators/dashboard/access/operations/installation-plan/apply
{
  "plan_hash": "sha256:...",
  "actor": "operator-dashboard",
  "idempotency_key": "dashboard-...",
  "action": "prepare_review"
}
```

The operation is intentionally narrow and resumable. A successful response
records `PROVIDER_REVIEW_REQUIRED` and `approve_provider_installation` in the
owner-only plan file (or `COMPLETED` when the operator chose `skip`). The
review projects only the Provider plan ID, summary, required permissions and
health checks; secrets and arbitrary runtime configuration are excluded. When a
Provider is already attached and approved, the same operation can advance
explicitly with `"action": "request_model_install"`. That action only queues
the existing model-install job, records its `install_id`, and returns
`process_model_install`. The next explicit action is:

```json
{
  "action": "process_model_install",
  "plan_hash": "sha256:...",
  "idempotency_key": "dashboard-process-model-..."
}
```

This targeted action invokes the existing worker only for the install ID bound
to the plan; it cannot consume another queued model on the node. The worker
adopts a matching completed installer prefetch when available, otherwise it
performs the download/materialization and provider-specific verification. A
running job returns `wait_model_install`; a failed job remains visible with its
bounded error and must be inspected before retry. After the worker reports that
install as `completed` (or `registered` after Bundle creation), use
`"action": "create_bundle"` to register a loopback-preferred local Bundle. The
runtime port allocator still chooses the actual free listener during activation;
this step does not start a process or create a public Endpoint.
When the operator is ready, `"action": "create_private_endpoint"` uses the
same Endpoint application boundary as the Dashboard to create an owner-only
draft (`private`, not discoverable, validation disabled, external requests
off). The next explicit action is
`"action": "forecast_private_endpoint"`. It is read-only: the selected
Provider estimator and Resource Broker report required/free capacity,
shortfall, leases, and an `ADMIT` or `RESOURCE_WAIT` decision without
reserving anything. A resource wait is a normal retryable state, not a runtime
failure. `"action": "start_private_endpoint"` is intentionally separate and
requires an `ADMIT` forecast: it passes Bundle activation through the Resource
Broker again (protecting against races), lets the port allocator choose the
listener, and records the fresh readiness probe. If capacity changes between
forecast and start, the plan returns to `PRIVATE_ENDPOINT_RESOURCE_WAIT` with
the broker explanation instead of starting an unsafe process. A healthy start
also returns a structured `workflow.completion` summary with the provider,
model, Bundle, Endpoint, runtime and readiness IDs, plus an explicit
`NOT_PUBLISHED` handoff. No assisted action calls the public publish path.
For a normal manual install, omit the assisted flags or use
`--setup-mode manual`.

Provider approval is deliberately a two-step boundary. After review, the
operator approves the exact Provider installation plan in the Provider catalog.
Only then may the Dashboard or a Steward session submit:

```json
{
  "action": "apply_provider_installation",
  "plan_hash": "sha256:...",
  "idempotency_key": "dashboard-provider-..."
}
```

The service matches the approval by Provider ID and Provider-plan hash before
creating a durable broker job. A mismatched, missing, or stale approval is
rejected; an agent cannot manufacture approval by supplying an MCP token or
approval reference. The workflow then exposes `wait_provider_installation` and
recomputes the next step from the observed broker job/provider inventory after
restart.

## Resume and handoff semantics

The plan is the source of truth for what the operator requested during the
installer run. A stopped or interrupted install can resume from the plan path;
it must not repeat wallet creation or re-run a network transition blindly.
Dashboard and future Steward consumers should treat the plan as a proposal and
re-check current state, capabilities, resource availability, port allocation,
and operator policy before every mutation. The Dashboard applies only a
verified, freshly read hash; editing the JSON by hand produces a `STALE` plan,
and old plans without a hash require regeneration/review. No plan field is a
credential or permission grant.
