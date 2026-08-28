# RFC-0075 Resident Node Agent — implementation profile

The Resident Node Agent (Node Steward) is the small, local control loop that
stays beside a Hypervisor. It consumes bounded RFC-0072 events, performs
routine read-only diagnosis, and can execute only the allow-listed actions
approved by the local policy. Larger models are advisors: they are reached
through the Reasoning Router and never receive direct machine authority.

## Current implementation

The reference implementation now includes all six MVP layers:

1. `ResidentWorker` runs the event loop, emits heartbeats, persists bounded
   state, and supports systemd watchdog/restart recovery.
2. `ResidentInferenceAdapter` owns the local model lifecycle: prepare, start,
   readiness probe, bounded request/stream metadata, per-request leases,
   stop, and CPU fallback when GPU_BURST loses admission.
3. `ResidentModelManager` performs explicit local/HTTPS artifact preparation,
   atomic writes, byte limits, Hugging Face host allow-listing, and optional
   SHA-256 verification. Starting a model never downloads implicitly.
4. `ReasoningAdapterRegistry` executes the provider selected by the
   deterministic `ReasoningRouter`. Resident-local callbacks and bounded HTTP
   adapters support local, AiDN, and external providers; external providers
   require HTTPS and operator-controlled environment credentials.
5. `resident_agent_execute_action` is the only Steward mutation path. It
   builds a hash-bound plan, checks policy/approval, claims the automation
   guard, executes through Hypervisor services, verifies the postcondition, and
   emits result events.
6. The dashboard Agents workspace exposes Steward enablement, action policy,
   rate limit, model profile/path, explicit download/prepare, start/stop, and
   durable escalation evidence.

The layers are intentionally separate. A worker restart does not start a
model, a model start does not grant mutation authority, and a reasoning
provider selection does not bypass the Resource Broker or policy.

## Reference local model

The default reference model is
[`Qwen/Qwen2.5-0.5B-Instruct-GGUF`](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF)
with the `Q4_K_M` quantization tag. The official model card declares an
Apache-2.0 license and documents llama.cpp loading. We ship metadata only;
operators explicitly prepare the artifact and review its path/checksum before
starting the Steward.

## Configuration

```text
AIDN_STEWARD_ENABLED=false
AIDN_STEWARD_EXECUTION_PROFILE=CPU_RESIDENT
AIDN_STEWARD_MODEL_REPO=Qwen/Qwen2.5-0.5B-Instruct-GGUF
AIDN_STEWARD_MODEL_QUANT=Q4_K_M
AIDN_STEWARD_RAM_BUDGET_MB=1024
AIDN_STEWARD_WORKER_ENABLED=false
AIDN_STEWARD_WORKER_INTERVAL_SECONDS=5
```

`AIDN_STEWARD_MODEL_PATH` is metadata until the operator uses the dashboard or
the explicit prepare API. `GPU_RESIDENT` is hard-admission. `GPU_BURST` may
fall back to CPU when the Resource Broker revokes or denies the GPU lease.

## Read and control paths

Read-only:

* `GET /operators/dashboard/steward`
* `GET /operators/dashboard/steward/context`
* `GET /operators/dashboard/steward/action-policy`
* `GET /operators/dashboard/steward/inference`
* `GET /operators/dashboard/steward/reasoning/providers`
* `GET /operators/dashboard/steward/escalations?limit=64`
* MCP `aidn.steward.status`, `aidn.steward.context`,
  `aidn.steward.reasoning.providers`, `aidn.steward.reasoning.route`

Explicit operator/model controls:

* `POST /operators/dashboard/steward/enabled`
* `POST /operators/dashboard/steward/action-policy`
* `POST /operators/dashboard/steward/inference/model/prepare`
* `POST /operators/dashboard/steward/inference/model/verify`
* `POST /operators/dashboard/steward/inference/prepare`
* `POST /operators/dashboard/steward/inference/start`
* `POST /operators/dashboard/steward/inference/stop`
* `POST /operators/dashboard/steward/reasoning/invoke`
* MCP `aidn.steward.action_guard`,
  `aidn.steward.reasoning.invoke` (scope `STEWARD:REASON`)

The prepare endpoint accepts a local model path or an HTTPS source URL. Remote
sources are restricted to the configured allow-list, written to a temporary
file, checksum-checked when requested, and atomically renamed into place.

## Worker and restart behavior

The worker binds one durable event-bus subscription per node, deduplicates by
event ID, and writes bounded snapshots. The systemd unit uses `Type=notify`
when available and sends watchdog heartbeats; environments without a notify
socket still operate with the same bounded loop. Startup restores policy,
cooldowns, event cursor, action history, and model metadata, but never restores
an active process or Resource Lease. A fresh status pass must reconcile those
runtime facts before execution.

## Context and privacy

`resident_agent_context()` projects only current node identity, resource
availability, queue counters, and bounded Provider/Model/Bundle/Runtime
inventory. It omits transcripts, provider logs, credentials, signing
material, and secrets. External reasoning adapters may receive only the
explicit prompt and route-approved data class.

## Policy and safety

The action catalog is finite. Each action is `AUTO`, `OPERATOR_CONFIRMATION`,
or `DISABLED`; the dashboard changes these assignments without touching
Bundles or Endpoints. Automation depth, per-target cooldowns, and a global
hourly action limit prevent event-action loops. A plan hash binds the approval
to the exact action and target. Every applied action emits start/completed or
failed events with causation metadata and a verification result.

## Operations checklist

1. Install the provider plugin and place the reviewed GGUF artifact on the
   node, or supply an allow-listed HTTPS source.
2. Use Agents → Steward operations to enable the service, set the policy, and
   Prepare model. Verify the returned SHA-256 and Resource Broker profile.
3. Start the model explicitly. Confirm `READY`/`RUNNING`, readiness evidence,
   and an active lease before routing reasoning to `resident-local`.
4. Subscribe the Steward to `aidn.provider.failed`, resource pressure, and
   validation events through RFC-0072 Hooks as needed.
5. Inspect escalation tasks. Apply a plan only after the operator reviews its
   plan hash, dependencies, approval state, and postconditions.

## Known future work

* true token streaming from providers instead of bounded stream metadata;
* benchmark-driven model/provider selection and latency telemetry;
* signed webhooks/runtime wake adapters for disconnected external agents;
* operator-configured external provider credentials through a dedicated secret
  store rather than environment-only resolution;
* multi-node Steward federation and cross-Hypervisor event routing.
