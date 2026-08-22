# Interactive Hypervisor installation

This document describes the first CLI slice of the Node Steward assisted
installation flow. The entry point is
`tools/aidn-operator-bootstrap-ubuntu.sh`.

## Two modes

The first interactive question is:

```text
Installation mode (manual/ai_assisted)
```

`manual` keeps the existing step-by-step operator flow. `ai_assisted` does not
remove or infer any required value. The installer still asks for and validates
the node identity, storage, consensus, wallet, dashboard, API, and Registry
choices. This prevents an assistant from silently choosing a network identity,
opening a listener, or creating a wallet on the operator's behalf.

After the required questions, AI-assisted mode offers a bounded continuation:

1. reviewed Provider (`ollama`, `llama.cpp`, `vllm`, or `skip`);
2. model identifier and HTTPS/`hf://` source;
3. private Endpoint action (`skip`, `draft`, or `start`);
4. handoff (`continue` with the Resident Steward or `dashboard`).

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
- Model download requires explicit operator review and resource checks.
- Endpoint publication still requires validation and existing Hypervisor
  policy.
- The Resident Steward cannot execute arbitrary shell commands or mutate state
  merely because assisted mode was selected.

When assisted mode is selected, the generated service exports
`AIDN_INSTALLATION_SETUP_MODE=ai_assisted` and configures the CPU-first Resident
Steward profile. The current Steward slice is intentionally a control-plane
boundary (`NOT_STARTED` inference adapter): it can receive bounded context and
prepare/inspect a plan, but it does not silently download a model or reserve
VRAM. This keeps installation safe while the inference adapter and Resource
Broker lease integration are completed.

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
it re-reads the file, rejects legacy or tampered plans, and only queues a model
install when the selected Provider is already installed. Provider installation,
Bundle creation, Runtime activation, validation and publication remain separate
policy-gated actions. If the provider is not ready, the card links to Provider
setup instead of attempting a hidden host mutation.

The Dashboard read endpoint is:

```text
GET /operators/dashboard/installation-plan
```

The protected apply operation is:

```text
POST /operators/dashboard/access/operations/installation-plan/apply
{
  "plan_hash": "sha256:...",
  "actor": "operator-dashboard",
  "idempotency_key": "dashboard-..."
}
```

The operation is intentionally narrow and resumable. A successful response
records `MODEL_INSTALL_QUEUED`, the broker `install_id`, and the next action in
the owner-only plan file. For a normal manual install, omit the assisted flags
or use `--setup-mode manual`.

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
