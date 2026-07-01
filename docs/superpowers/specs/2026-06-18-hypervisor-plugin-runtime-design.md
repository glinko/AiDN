# Hypervisor Plugin Runtime Design

## Summary

This spec defines the first executable scope for AiDN: a local hypervisor that manages local AI providers and models in manual and automatic modes, with explicit orchestration of constrained node resources (`CPU`, `RAM`, `VRAM`) and queue-based admission control.

The MVP is not a multi-node network scheduler. It is a single-node control plane that can:

- register local provider/model bundles;
- start and stop local provider runtimes;
- accept `llm_text` and `speech_to_text` tasks;
- decide whether a task can run immediately or must wait in queue;
- route a task either by explicit bundle selection or automatically by policy.

The design must preserve a plugin-based provider model so new runtimes can be added without rewriting the hypervisor core.

## Goals

- Build a local hypervisor with a unified API for task submission and runtime control.
- Support both manual and automatic task routing.
- Support two workload classes in MVP:
  - `llm_text.generate`
  - `audio.transcribe`
- Support plugin adapters for at least:
  - `llama.cpp`
  - `Ollama`
  - `Whisper`
- Introduce explicit resource accounting for `CPU`, `RAM`, and `VRAM`.
- Introduce a queue and admission controller that only starts work when sufficient resources are available.
- Support hybrid runtime policy:
  - some bundles remain warm;
  - some bundles start on demand.

## Non-Goals

- Multi-node orchestration.
- Cross-node trust and economics.
- Running-task preemption.
- Distributed consensus or durable distributed queues.
- Perfect hardware telemetry in v1.
- Hot plugin install/uninstall without restart.

## Recommended Stack

- Language: `Python`
- API framework: `FastAPI`
- Data validation: `Pydantic`
- Test runner: `pytest`
- Async runtime: `asyncio`
- Process management: Python subprocess APIs

This stack optimizes for fast iteration on process orchestration, queueing, provider integration, and testability.

## Architecture

The MVP is a core hypervisor process with pluggable provider adapters and externally managed provider runtimes.

### Core Components

#### 1. Hypervisor API

Accepts operator commands and task submissions.

Responsibilities:

- create and query tasks;
- cancel queued or running tasks where allowed by policy;
- expose bundle, runtime, queue, plugin, and resource state;
- trigger manual bundle start and stop;
- route manual and automatic invocation requests into the scheduler.

#### 2. Task Queue

Stores submitted tasks and tracks execution state.

Responsibilities:

- enqueue incoming tasks;
- order them by effective priority;
- move tasks across lifecycle states;
- expose queue visibility for operators and API clients.

#### 3. Scheduler

Determines which bundle can satisfy a task and whether execution should begin now.

Responsibilities:

- filter candidate bundles by workload type and task constraints;
- honor explicit `bundle_override` in manual mode;
- compute bundle preference order in auto mode;
- request resource admission before runtime startup or task execution;
- reschedule waiting tasks when resources change.

#### 4. Resource Orchestrator

Tracks node capacity, reservations, and bundle/runtime demand.

Responsibilities:

- maintain a view of total and free `CPU`, `RAM`, and `VRAM`;
- distinguish cold-start resource needs from steady-state runtime needs;
- distinguish runtime residency cost from per-request execution cost;
- reserve resources before state transitions into `starting` or `running`;
- release reservations after completion, failure, or cancellation;
- decide when idle warm runtimes should be evicted.

#### 5. Plugin Runtime Registry

Stores installed plugin metadata and configured bundle definitions.

Responsibilities:

- load plugin adapters on hypervisor startup;
- validate configured bundles;
- expose bundle capabilities and policies to the scheduler;
- persist bundle configuration on disk.

#### 6. Provider Process Manager

Controls external provider runtime processes.

Responsibilities:

- launch provider processes using plugin launch specs;
- perform readiness and health checks;
- track process handles and runtime status;
- stop runtimes gracefully and escalate if needed;
- reconnect to surviving runtimes after hypervisor restart when possible.

#### 7. Provider Plugins

Each provider type is represented by an adapter that implements the shared plugin contract.

Responsibilities:

- describe provider capabilities;
- validate bundle configuration;
- estimate resources;
- build launch commands or remote-local transport config;
- invoke inference using a normalized interface;
- stop or detach from managed runtimes.

### Control Flow

The normal task flow is:

1. Client submits task through API.
2. Task enters queue as `queued`.
3. Scheduler selects candidate bundles.
4. Resource orchestrator checks whether the task can be admitted.
5. If runtime is not warm, process manager starts it and waits for healthy state.
6. Task transitions to `running`.
7. Plugin invokes provider runtime.
8. Result is returned and task moves to terminal state.
9. Request-scoped resources are released.
10. Runtime is either kept warm or evicted according to warm policy and resource pressure.

## Execution Modes

### Manual Mode

The requester explicitly names a bundle or provider target.

Rules:

- the scheduler only considers the requested bundle;
- if the bundle is unavailable or lacks resources, the task waits or fails according to submission policy;
- operators may manually start and stop bundles through API endpoints.

### Automatic Mode

The requester submits a task without a bundle override.

Rules:

- the scheduler selects among compatible bundles;
- selection considers workload type, readiness, warm status, resource availability, and policy preference;
- if no candidate can be admitted now, the task remains queued.

### Hybrid Warm Policy

Bundle warm behavior is controlled independently from task routing.

Allowed values:

- `always`: keep warm whenever possible;
- `auto`: keep warm for a time window after recent use;
- `never`: stop after request completion or stay off until needed.

## Resource Model

Resource accounting is central to the design.

### Node Capacity

The node exposes:

- `cpu_cores`
- `ram_mb`
- `gpu_devices`
- `vram_mb` per device
- optional `provider_concurrency_limits`

The MVP may source these values from configured capacity plus lightweight runtime observation rather than full hardware telemetry.

### Bundle Resource Profile

Each bundle defines or derives a resource profile:

- `cold_start_cpu`
- `cold_start_ram_mb`
- `cold_start_vram_mb`
- `steady_cpu`
- `steady_ram_mb`
- `steady_vram_mb`
- `per_request_cpu`
- `per_request_ram_mb`
- `per_request_vram_mb`
- `max_parallel_requests`
- `startup_time_ms`
- `workload_type`

This separation is required because runtime startup and request execution have different resource behavior.

### Reservations

The resource orchestrator tracks at least three reservation classes:

- `runtime_resident`: resources consumed by a warm runtime;
- `startup_transient`: temporary resources needed during provider boot;
- `request_active`: per-request execution resources.

Task admission requires that all necessary reservations fit simultaneously.

### Admission Rule

A task may only move into `starting` or `running` when:

- an eligible bundle exists;
- the bundle is not over its concurrency limit;
- all required startup and/or request resources can be reserved;
- device affinity constraints can be satisfied.

If any condition fails, the task remains queued.

## Queue and Scheduling Policy

### Task Lifecycle

Tasks move through these states:

- `queued`
- `admitted`
- `starting`
- `running`
- `completed`
- `failed`
- `cancelled`

`admitted` means the scheduler has selected a bundle and resource reservations are held.

### Ordering

Tasks are ordered by:

1. effective priority descending;
2. creation time ascending.

The effective priority may increase slowly with waiting time to reduce starvation.

### Scheduling Behavior

When a new task is evaluated:

1. derive candidate bundles;
2. discard incompatible bundles;
3. prefer already warm healthy runtimes;
4. otherwise prefer bundles with lower startup cost and available resources;
5. admit the first bundle that fits;
6. if none fits, leave the task queued.

The scheduler is event-driven and should re-evaluate waiting tasks on:

- task completion;
- runtime stop;
- startup failure;
- task cancellation;
- manual bundle state change.

### Eviction Policy

Under resource pressure, the hypervisor may reclaim idle warm runtimes in this order:

1. idle bundles with `warm_policy=auto`;
2. idle bundles with `warm_policy=always` when required for a higher-priority admitted task.

The MVP does not interrupt active tasks.

## Plugin Contract

Provider plugins must implement a single contract so the core scheduler and runtime manager remain provider-agnostic.

### Required Methods

#### `describe()`

Returns:

- `plugin_id`
- `provider_type`
- supported `workload_types`
- supported transport and launch modes
- plugin-specific config schema hints

#### `validate_bundle(bundle_config)`

Checks:

- required fields are present;
- paths, endpoints, ports, and device config are coherent;
- launch mode is supported by the plugin.

#### `estimate_resources(task, bundle_config, runtime_state)`

Returns estimated:

- startup transient resources;
- runtime residency resources;
- per-request active resources;
- concurrency limits if plugin-specific.

#### `build_launch_spec(bundle_config)`

Returns launch metadata:

- executable or command;
- args;
- env;
- working directory if needed;
- health probe details;
- readiness timeout.

#### `health_check(runtime_handle)`

Confirms the runtime can actually accept work.

#### `invoke(task, runtime_handle)`

Executes inference and returns a normalized result shape.

#### `stop(runtime_handle)`

Stops or detaches from the runtime according to management mode.

### Plugin Model

The MVP supports two plugin operating styles:

- `managed_process`: hypervisor starts and stops the runtime;
- `attached_service`: hypervisor connects to an already-running local service but still accounts for its bundle as a schedulable execution target.

This distinction is necessary because `llama.cpp` often behaves like a directly managed process, while `Ollama` may behave as a locally attached service.

## Bundle Model

Each bundle is a specific runnable provider/model configuration.

Required fields:

- `bundle_id`
- `plugin_id`
- `provider_type`
- `workload_type`
- `model_id`
- `launch_mode`
- `endpoint` or `launch_spec_override`
- `device_affinity`
- `resource_profile`
- `warm_policy`
- `priority_class`
- `max_parallel_requests`
- `enabled`

Optional fields may include:

- `tags`
- `health_timeout_ms`
- `idle_ttl_ms`
- `metadata`

## Task Model

The hypervisor accepts a single task envelope with workload-specific payloads.

### Common Fields

- `task_id`
- `task_type`
- `mode`
- `bundle_override`
- `priority`
- `constraints`
- `payload`
- `created_at`

### MVP Task Types

#### `llm_text.generate`

Payload includes:

- `prompt`
- optional generation parameters such as `temperature`, `max_tokens`, `top_p`

#### `audio.transcribe`

Payload includes:

- `audio_ref`
- optional transcription parameters such as language hints or response format

### Constraints

The task envelope may express:

- preferred device class;
- provider allow-list or deny-list;
- timeout budget;
- maximum acceptable startup mode.

The MVP only needs to support a small validated subset of constraints, not arbitrary scheduling expressions.

## API Surface

### Task Endpoints

- `POST /tasks`
  - submit a task
- `GET /tasks/{task_id}`
  - fetch task status and result
- `POST /tasks/{task_id}/cancel`
  - cancel a task if still cancellable

### Queue Endpoint

- `GET /queue`
  - inspect queued, admitted, and running tasks

### Bundle Endpoints

- `GET /bundles`
  - list bundle definitions and current status
- `POST /bundles/{bundle_id}/start`
  - manually start a bundle runtime
- `POST /bundles/{bundle_id}/stop`
  - manually stop a bundle runtime

### Runtime and Resource Endpoints

- `GET /runtimes`
  - list active runtimes and health status
- `GET /resources`
  - expose total, reserved, and free resources

### Plugin Endpoint

- `GET /plugins`
  - list installed plugins and supported workload types

## State and Persistence

The MVP should keep operational state in memory and persist only the data required to reboot safely.

Persisted artifacts:

- bundle configuration;
- plugin registration metadata if needed;
- task execution logs;
- event journal for debugging and replay insight.

On restart:

1. reload bundle registry;
2. reload persisted metadata;
3. probe known runtimes if recoverable;
4. mark in-flight tasks from the previous process as either:
   - `failed`, or
   - `queued` for retry if configured and safe.

The default MVP behavior should be conservative: unknown in-flight work becomes `failed` unless the plugin explicitly supports safe reconciliation.

## Failure Handling

The hypervisor must surface failures clearly at these layers:

- invalid task submission;
- bundle validation failure;
- no compatible bundle;
- insufficient resources;
- startup timeout;
- health check failure;
- invocation failure;
- cancellation before start;
- abnormal provider exit.

Failure requirements:

- release all held reservations;
- update task and runtime state deterministically;
- retain enough structured context for operator debugging.

## Security and Isolation

The MVP is local-first and operator-controlled, but still needs basic safety boundaries.

- bundle definitions must explicitly declare launch commands and paths;
- plugins may not arbitrarily mutate scheduler state;
- process manager must keep launch environment explicit;
- local file references used by tasks must be validated before provider invocation.

This release does not attempt full sandboxing of provider processes.

## Observability

The hypervisor should emit structured logs for:

- task creation and completion;
- scheduling decisions;
- resource admission decisions;
- runtime startup and shutdown;
- plugin errors;
- queue wait duration and runtime startup duration.

Minimal metrics or counters should be easy to add later, but logs are sufficient for the MVP.

## Testing Strategy

### Unit Tests

- scheduler candidate filtering;
- scheduler selection preference;
- admission control success and failure;
- reservation and release accounting;
- warm-pool eviction ordering;
- task priority aging.

### Integration Tests

- fake managed-process plugin lifecycle;
- fake attached-service plugin lifecycle;
- queue behavior when resources are exhausted;
- cold start to healthy to invoke to release;
- multiple queued tasks contending for a single constrained GPU resource;
- manual bundle override with unavailable resources.

### Contract Tests

Every plugin must pass a common adapter suite validating:

- `describe`;
- `validate_bundle`;
- `estimate_resources`;
- `build_launch_spec`;
- `health_check`;
- `invoke`;
- `stop`.

## MVP Boundaries

The first implementation should stop at:

- one local node;
- plugin-based providers;
- queue plus admission control;
- hybrid warm policy;
- `llm_text.generate` and `audio.transcribe`;
- resource-aware manual and automatic routing.

It should not include:

- distributed scheduling;
- economic accounting;
- trust scoring;
- runtime preemption;
- speculative overcommit;
- advanced autoscaling.

## Implementation Guidance

The codebase should be split into focused modules, not a single large file.

Recommended top-level responsibilities:

- API layer
- task domain models
- bundle and plugin registry
- scheduler
- resource orchestrator
- process manager
- provider plugins
- persistence and logging
- tests

The hypervisor core should depend on plugin interfaces, not provider-specific logic.
