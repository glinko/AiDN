# Resident Inference Adapter

The Resident Steward is a CPU-first control-plane component. A model install
does not start inference by itself. The operator must explicitly enable the
Steward, prepare the completed model job, and start the adapter.

## Lifecycle

```text
model install completed
        |
        v
READY_TO_START  -- operator start -->  Resource Broker admission
        |                                  |
        |                                  +-- denied -> RESOURCE_WAIT
        |                                  +-- GPU_BURST denied -> CPU_RESIDENT fallback
        v
STARTING -> RUNNING -> stop/error -> lease released
```

`prepare` validates the local artifact and Provider Plugin but never reserves
resources or launches a process. `start` obtains the stable
`steward:<node_id>:inference` lease before calling the existing provider
launch boundary. Each inference request obtains a short-lived request lease
and releases it in a `finally` block.

## Operator API

The paired operator API exposes:

* `GET /operators/dashboard/steward/inference`
* `POST /operators/dashboard/steward/enabled` with `{ "enabled": true|false }`
* `POST /operators/dashboard/steward/inference/prepare`
* `POST /operators/dashboard/steward/inference/start`
* `POST /operators/dashboard/steward/inference/stop`
* `POST /operators/dashboard/steward/inference/invoke`

The prepare payload includes the local `model_path`, provider/plugin, an
execution profile (`CPU_RESIDENT`, `IGPU_RESIDENT`, `GPU_RESIDENT`, or
`GPU_BURST`), resource estimates, fallback policy, and the normalized runtime
parameter policy. Model downloads remain a separate installation operation.

For `llama.cpp`, `CPU_RESIDENT` and `IGPU_RESIDENT` are strict no-VRAM
profiles: the adapter pins the operator-owned `gpu_layers` parameter to `0`
when preparing the runtime and reapplies that rule at start. This also protects
older persisted configurations that were created while the generic llama.cpp
default was `gpu_layers=99`. GPU profiles keep their explicit layer policy and
continue to be admitted by the Resource Broker.

## Installation-plan handoff

When an assisted installation plan requests `endpoint_action: start`, the
plan apply step marks the model job as `resident_adapter_requested`. Processing
the completed job prepares the adapter and reports `READY_TO_START`; it does
not launch a runtime implicitly. This keeps installation, resource admission,
and autonomous execution as separate policy boundaries.

## Failure behavior

* `INFERENCE_RESOURCE_WAIT` means no runtime was started and no residency lease
  remains active.
* A failed launch releases the lease before returning
  `INFERENCE_RUNTIME_FAILED`.
* A stopped runtime releases its residency lease. A revoked `GPU_BURST` lease
  is reconciled on the next status/request pass and re-admitted on CPU when
  the broker still cannot provide VRAM; `GPU_RESIDENT` remains fail-closed.
* Every residency/request lease transition notifies the global scheduler so
  other endpoint queues can be reconsidered.
* Model paths and provider diagnostics are bounded; secrets and launch command
  details are not returned by the status projection.
