# RFC-0073 — AiDN Resource Broker, Admission Control and Runtime Scheduler

Status: Draft

Version: 0.2

Category: Hypervisor / Runtime / Scheduling

Depends on:

- RFC-0054 Capability Runtime Protocol
- RFC-0056 Provider Lifecycle Management
- RFC-0060 Endpoint Lifecycle
- RFC-0069 Bundle Architecture
- RFC-0072 Hypervisor Event and Agent Hook Protocol
- MCP-0001 AiDN Node Control MCP Server
- UI-0001 Hypervisor Dashboard Specification

## 1. Purpose

This RFC defines the AiDN Hypervisor Resource Broker and local Runtime
Scheduler. The Broker discovers physical resources, tracks actual and reserved
usage, reserves resources before Runtime activation, prevents impossible
launches, and coordinates independent Endpoint queues.

The Resource Broker SHALL be authoritative for local resource admission. No
Provider Plugin, Endpoint, Bundle, Agent, or external request MAY independently
assume that local resources are available.

## 2. Problem Statement

Endpoints backed by different models have different resource requirements. A
24 GB GPU may run a 12 GB and an 8 GB Runtime while leaving approximately 4 GB.
A waiting 10 GB Endpoint cannot start. When a running Endpoint finishes, its
Runtime may remain WARM and retain its allocation, or become eligible for
eviction and release it.

The Scheduler MUST reconsider all eligible Endpoint queues and warm idle
Runtimes whenever resource state changes. It SHALL NOT only advance the queue
whose Request just completed.

## 3. Core Scheduling Model

AiDN uses per-Endpoint queues, a global admission scheduler, a Resource Broker,
and a Runtime Instance Manager:

    Requests
      |-- Endpoint A Queue
      |-- Endpoint B Queue
      |-- Endpoint C Queue
      v
    Global Admission Scheduler
      v
    Resource Broker
      |-- Grant Resource Lease -> Runtime Start -> Execute
      +-- Deny / Wait

## 4. Resource Broker

The Broker maintains the canonical local view of CPU, Host RAM, GPU devices,
VRAM per GPU, storage, and network capacity. Optional dimensions include NUMA
and PCIe topology, NVLink, CUDA/ROCm capability, GPU temperature, power,
bandwidth, IOPS, shared memory, and CPU affinity.

## 5. Resource Accounting States

Every resource class SHALL distinguish:

    PHYSICAL
    SAFETY_RESERVED
    LEASE_RESERVED
    ALLOCATED
    MEASURED_USED
    EXTERNALLY_USED
    FREE_ALLOCATABLE

The Scheduler SHALL use actual FREE_ALLOCATABLE capacity, not only declared
leases.

## 6. Safety Margin

The Hypervisor SHALL maintain configurable safety headroom. A recommended
policy is max(1 GB, 5%) for VRAM and max(4 GB, 10%) for Host RAM. Headroom
protects against dynamic CUDA reservations, fragmentation, imperfect
estimates, KV-cache growth, workspace variation, and external processes.
Normal workloads SHALL NOT consume the safety margin.

## 7. Hard and Soft Resources

VRAM, required accelerator count, specific accelerator requirements, and
topology constraints are hard resources by default. CPU, network bandwidth,
disk bandwidth, and some Host RAM MAY be soft resources under explicit policy.
VRAM SHALL be hard-admission by default.

## 8. Resource Profile

Every Bundle Revision SHALL have a Resource Profile:

    resource_profile:
      cpu:
        minimum_cores:
        preferred_cores:
      ram:
        minimum_bytes:
        estimated_peak_bytes:
      gpu:
        required:
        gpu_count:
        minimum_vram_bytes:
        estimated_peak_vram_bytes:
        compute_capability:
      storage:
        model_bytes:
        working_bytes:
      runtime:
        maximum_context:
        maximum_output:
        maximum_concurrent_sequences:
        maximum_batch:

## 9. Resource Profile Confidence

Requirements MAY be DECLARED by a Bundle or Provider Plugin, ESTIMATED by the
Hypervisor, MEASURED during operation, or VALIDATED by repeatable validation or
benchmarking. The Broker SHOULD use the most conservative high-confidence
value.

## 10. Effective Requirement

Conceptually:

    EffectiveRequirement =
      max(DeclaredMinimum, EstimatedPeak, AdjustedMeasuredPeak, ValidatedPeak)
      + SafetyAllowance

The exact policy MAY vary by resource class.

## 11. LLM VRAM Model

LLM VRAM includes:

    ModelWeights + KVCache + RuntimeWorkspace
      + ProviderOverhead + FragmentationAllowance

Model weight size alone is never a sufficient admission estimate.

## 12. KV Cache

KV-cache depends on context length, active sequences, layers, KV dimensions,
and precision:

    KV ~= Tokens * Layers * KVHeads * HeadDimension
         * 2 * BytesPerElement

Provider Plugins SHOULD expose accurate estimators.

## 13. Context Is a Resource Commitment

An Endpoint maximum_context is part of the Resource Profile. A change such as
32K to 64K SHALL create a new Bundle Revision and may materially change VRAM
admission:

    Endpoint config -> Bundle Revision -> Resource Profile -> Admission

## 14. Concurrency Is a Resource Commitment

The Broker SHALL account for maximum concurrent sequences, batch size, and
simultaneous Requests. A model that fits one sequence may not fit eight.

## 15. Runtime Instance

A Runtime Instance is an executable realization of a Bundle Revision. States:

    COLD
    STARTING
    WARM_IDLE
    WARM_ACTIVE
    BUSY
    EVICTION_CANDIDATE
    DRAINING
    STOPPING
    STOPPED
    FAILED

## 16. Cold Runtime

A COLD Runtime has no active model allocation on an accelerator and consumes no
substantial VRAM.

## 17. Warm Runtime

A WARM Runtime has loaded model weights and runtime state. It consumes allocated
resources even while processing no Request. Idle does not mean free.

## 18. WARM_IDLE

A Runtime is WARM_IDLE when loaded, without active Requests, with an empty
execution queue, and retained for possible future work. It is eligible for
eviction according to policy.

## 19. WARM_ACTIVE

A Runtime is WARM_ACTIVE when loaded and either queued, recently active within
the retention window, or intentionally pinned warm. It may or may not be
immediately evictable.

## 20. Runtime Busy State

A Runtime is BUSY while actively executing work. Its resources SHALL be
considered occupied.

## 21. Resource Lease

Every Runtime Instance SHALL obtain a Resource Lease before activation:

    resource_lease:
      lease_id:
      bundle_id:
      bundle_revision:
      runtime_instance_id:
      gpu:
        device_id:
        reserved_vram_bytes:
      ram:
        reserved_bytes:
      cpu:
        reserved_units:
      created_at:
      expires_at:

No valid Lease means no start.

## 22. Lease Lifecycle

The normal lifecycle is:

    REQUESTED -> GRANTED -> ACTIVE -> RELEASED

Other states are DENIED, EXPIRED, and REVOKED.

## 23. Atomic Reservation

Multi-resource allocation SHALL be atomic. A workload requiring 20 GB VRAM,
8 GB RAM, and 4 CPU cores receives all resources or none. Partial reservations
are prohibited.

## 24. GPU-Specific Accounting

VRAM SHALL be tracked per physical GPU. Eight GB free on GPU0 and eight GB free
on GPU1 do not imply that a 16 GB single-GPU workload fits.

## 25. Multi-GPU Runtime

A Bundle MAY declare:

    gpu:
      count: 2
      minimum_vram_per_gpu: 20GB
      preferred_topology: NVLINK

The Broker SHALL reserve the compatible GPU set atomically.

## 26. Host RAM

Host RAM is tracked separately from VRAM. Consumers include model staging,
CPU offload, tokenization, preprocessing, runtime cache, mmap buffers,
Provider processes, and temporary working memory.

## 27. External Processes

The Broker SHALL account for resources consumed outside AiDN. If Blender uses
5 GB VRAM, that memory is unavailable to AiDN. The Hypervisor SHALL NOT kill
unrelated local processes by default.

## 28. Local Owner Priority

External local workloads SHOULD be treated as owner workloads. AiDN shares
unused capacity and does not confiscate the operator's machine.

## 29. Endpoint Queue

Each Endpoint SHALL maintain an independent logical Request queue. FIFO SHOULD
be the default within one queue unless another policy is configured.

## 30. Why Queues Must Remain Separate

A global FIFO would let a large request block a small one. For example, with
4 GB free, an 18 GB LLM request must not block an independent 0.5 GB Whisper
request. AiDN SHALL avoid this head-of-line blocking.

## 31. Two-Level Scheduling

Level 1, Endpoint Queue Scheduling, orders work inside one Endpoint. Level 2,
Hypervisor Admission Scheduling, chooses which Endpoint workload receives
resources next.

## 32. Execution Queue and Activation Queue

The Hypervisor SHOULD distinguish an Execution Queue for Requests runnable on
an existing Runtime from an Activation Demand Queue for work requiring a
Runtime start or reactivation.

## 33. Warm Runtime Fast Path

If a compatible Runtime is running and has execution capacity, a Request enters
its internal queue and executes without a new Lease beyond its current
allocation.

## 34. Cold Endpoint Path

For an inactive Runtime:

    Request -> Endpoint Queue -> Activation Demand
      -> Global Admission Scheduler
      -> Lease -> Runtime starts -> WARM/BUSY -> execute

If it does not fit, the Request enters WAITING_FOR_RESOURCES.

## 35. WAITING_FOR_RESOURCES

A Request with unavailable resources SHALL remain queued without repeatedly
attempting unsafe startup. This is a scheduling state, not an execution failure.

## 36. Candidate Set

At every scheduling pass the Scheduler SHALL build a Candidate Set containing
the head Request of each eligible Endpoint queue, work runnable on warm
Runtimes, and eligible activation demands.

## 37. Fit-Aware Scheduling

A candidate is runnable when its additional requirement fits in free
allocatable resources or it can execute inside an existing compatible Lease.

## 38. No Global Head-of-Line Blocking

A Request that cannot fit SHALL NOT prevent an independent Request that can fit.
For example, with 3 GB free, an 18 GB candidate waits while a 0.7 GB candidate
runs.

## 39. Resource Reconciliation Cycle

A Resource Reconciliation Cycle recomputes real hardware state, external
processes, active Leases, Runtime states, Endpoint queue heads, warm runnable
work, cold activation candidates, and idle Runtime eviction candidates.

## 40. Reconciliation Triggers

Reconciliation SHALL be triggered by material changes including Request
arrival/completion/cancellation, Runtime start/idle/stop/failure, Lease
grant/release/revocation, VRAM/RAM/CPU changes, external GPU process changes,
owner workload changes, sharing policy changes, Bundle changes, and Endpoint
changes.

## 41. Global Re-evaluation Requirement

When a material event occurs, the Scheduler SHALL reconsider every eligible
Endpoint queue. It SHALL NOT reconsider only the queue associated with the
event.

## 42. Reconciliation Algorithm

The recommended algorithm is:

1. Refresh hardware state.
2. Reconcile processes and active Leases.
3. Recalculate FREE, RESERVED, ALLOCATED, USED, and EXTERNAL.
4. Dispatch work to compatible warm Runtimes.
5. Build a Candidate Set from all eligible Endpoint queues.
6. Determine candidates that fit immediately.
7. Rank runnable candidates.
8. Grant an atomic Lease to the best candidate.
9. Start or activate the Runtime.
10. Repeat if state changed.
11. If no runnable cold candidate exists, evaluate warm idle eviction.
12. Build possible eviction plans.
13. If an eviction enables a higher-priority or preferred workload, drain and
    stop the selected Runtime, release its Lease, and restart reconciliation.
14. Stop when no useful placement or execution transition remains.

## 43. Stable Scheduling State

A cycle completes only when no immediately runnable Request remains unscheduled,
no policy-beneficial eviction plan exists, and no pending immediate resource
transition is expected. This is the local scheduling fixed point.

## 44. Iterative Scheduling

The Scheduler SHALL iterate after each placement or eviction. One eviction may
free enough memory to start a large model, after which a smaller independent
workload may also fit in the remaining capacity.

## 45. Example: Two Active Endpoints

With a 24 GB GPU, Endpoint A uses 12 GB and Endpoint B uses 8 GB. Four GB
remain. Endpoint C requires 10 GB and is therefore WAITING_FOR_RESOURCES.

## 46. Endpoint A Finishes

When A finishes its last Request it becomes WARM_IDLE but still occupies 12 GB.
Reconciliation confirms that C still does not fit and evaluates eviction.

## 47. Eviction Evaluation

If A has an empty queue, is not pinned, and has no active Session dependency,
it may become EVICTION_CANDIDATE. Evicting it releases 12 GB and makes C
admissible.

## 48. Eviction Transition

The transition is:

    WARM_IDLE -> EVICTION_CANDIDATE -> DRAINING
      -> STOPPING -> STOPPED -> Lease released
      -> reconciliation -> C runnable -> Lease -> start

## 49. Important Distinction

Request completion does not automatically release resources. It only makes a
Runtime eligible to become idle; release depends on retention and eviction
policy.

## 50. Warm Retention

The Hypervisor MAY retain an idle Runtime, for example with warm_timeout equal
to 300 seconds, to avoid repeated model reload costs.

## 51. Warm Timeout Is Not Absolute

A Runtime MAY be evicted before timeout when a waiting workload has higher
priority, utilization improves, local owner resources are required, fairness
requires capacity, or operator policy permits it.

## 52. Pinned Runtime

An operator MAY mark a Runtime PINNED_WARM. It SHALL not be automatically
evicted unless a higher-level safety policy requires it.

## 53. Eviction Cost

The Scheduler SHOULD estimate:

    EvictionCost =
      future reload probability * startup cost
      + current drain cost + lost warm-cache value

This avoids pointless thrashing.

## 54. Startup Cost

Each Runtime SHOULD expose model load time, Provider startup time, VRAM
allocation time, and warmup time estimates. These MAY influence ranking.

## 55. Churn Protection

The Scheduler SHALL prevent rapid A/B loading oscillation. Safeguards SHOULD
include minimum residency, minimum eviction benefit, cooldown, activation
hysteresis, and an eviction penalty.

## 56. Fairness

Fit-aware scheduling MUST be combined with fairness so many small jobs cannot
permanently prevent a large workload from obtaining capacity.

## 57. Wait-Time Aging

Waiting workloads SHOULD gain priority:

    EffectivePriority = BasePriority + AgingFactor * WaitingTime

## 58. Large Workload Reservation Window

Advanced policy MAY temporarily stop admitting small lower-priority work when
a long-waiting large workload is close to becoming runnable and expected
capacity is about to be released. This prevents starvation through fragmentation.

## 59. Priority Classes

Suggested classes are:

    LOCAL_CRITICAL
    LOCAL_INTERACTIVE
    NETWORK_PREMIUM
    NETWORK_NORMAL
    BACKGROUND

## 60. Default Priority Policy

The recommended default is:

    LOCAL_FIRST + FAIR_SHARE + FIT_AWARE + WAIT_TIME_AGING

## 61. Scheduling Score

A candidate MAY be ranked by:

    Score = BasePriority + WaitTime + WarmAffinity + ResourceFit
      + EconomicValue + Locality
      - StartupCost - EvictionCost - FragmentationPenalty

Weights are implementation policy.

## 62. Resource Fit

Resource Fit SHOULD favor useful capacity utilization without pathological
fragmentation. It SHALL not indefinitely override starvation protection.

## 63. Fragmentation Example

With 8 GB free, candidates requiring 7 GB, 3 GB, and 3 GB may be better served
by the two smaller jobs, but fairness and waiting time still apply.

## 64. Greedy MVP

The MVP may use a greedy scheduler:

1. Prefer warm executable work.
2. Filter by fit.
3. Rank by priority and age.
4. Allocate the best candidate.
5. Repeat reconciliation.

## 65. Future Packing Scheduler

A future scheduler MAY optimize useful scheduled work subject to VRAM, RAM,
CPU, topology, priority, latency, fairness, startup cost, and eviction cost.

## 66. Local Owner Resource Reclamation

When the owner needs resources:

    stop admitting remote work
      -> identify reclaimable Runtimes
      -> drain
      -> release resources
      -> reconcile
      -> admit local workload

## 67. Runtime Preemption Classes

Runtime policy MAY declare:

    NON_PREEMPTIBLE
    DRAINABLE
    CHECKPOINTABLE
    IMMEDIATELY_PREEMPTIBLE

## 68. Idle Runtime Eviction

A WARM_IDLE Runtime is generally IMMEDIATELY_PREEMPTIBLE unless operator or
Bundle policy says otherwise.

## 69. Active Runtime Draining

A busy Runtime SHOULD complete current work or drain gracefully. Immediate kill
is reserved for explicit operator action, critical pressure, unsafe state, or
a contract that permits immediate preemption.

## 70. Admission Failure Is Not Runtime Failure

Unavailable resources result in RESOURCE_WAIT, not FAILED. Resource contention
and execution failure are distinct concepts.

## 71. Reputation

Legitimate queueing caused by resource contention SHALL not automatically reduce
Endpoint reputation. Repeatedly advertising unrealistic immediate capacity MAY
affect scheduling or reputation policy.

## 72. Capacity Honesty

Published Endpoints SHOULD expose dynamic availability:

    READY | BUSY | QUEUED | COLD | RESOURCE_WAIT | DRAINING | UNAVAILABLE

## 73. Dynamic Capacity Advertisement

The Hypervisor MAY advertise warm/cold state, queue depth, estimated wait, and
current admission availability without exposing private hardware details.

## 74. Network Dispatcher Interaction

The Network Dispatcher SHOULD prefer READY Endpoints or acceptable queue
conditions, but it is not the Resource Broker. The Broker remains authoritative
for local admission.

## 75. Provisional Admission

For some Sessions:

    Network request -> preliminary Endpoint acceptance
      -> Broker resource check -> provisional Lease/queue slot
      -> Session accepted

## 76. Provisional Lease

A provisional Lease MAY have a short TTL, for example five seconds. If the
Session does not finalize, the Lease is released and reconciliation runs.

## 77. Request Deadline

A Request MAY specify maximum_queue_time or a deadline. If the Scheduler
estimates that the deadline cannot be met, it MAY reject early instead of
holding the Request indefinitely.

## 78. Queue Cancellation

Cancelling a queued Request removes it, releases provisional resources, and
triggers reconciliation.

## 79. Queue Reprocessing Rule

Whenever resource availability changes, the entire eligible Candidate Set SHALL
be recomputed, including all Endpoint queues.

## 80. First Fitting Candidate

First fitting means the highest-ranked candidate under current policy among all
candidates that fit. It does not mean global arrival order unless strict FIFO
is explicitly configured.

## 81. Queue Example

With a 24 GB GPU, A and B use 10 GB each, and C (12 GB), D (2 GB), and E
(6 GB) wait, D starts first because it fits. When B becomes idle and is
evicted, C and E are reconsidered by priority, age, and policy.

## 82. Reconciliation After Completion

Every Request completion SHALL trigger at least a lightweight reevaluation
because it may change BUSY to WARM_IDLE, queue depth, concurrency slots,
memory, cache state, or eviction eligibility.

## 83. Reconciliation After Partial Resource Release

If a Provider releases memory without stopping and measured allocatable
capacity increases materially, reconciliation SHALL run.

## 84. Real-Time Hardware Truth

Before cold activation, the Broker SHOULD compare expected free capacity with
actual device free capacity. If the discrepancy exceeds tolerance, it SHALL
refresh state, deny unsafe activation, and emit an event.

## 85. OOM Feedback

An OOM crash SHALL record Bundle revision, Provider version, GPU type, model,
context, concurrency, reserved VRAM, and measured peak, and emit:

    aidn.resource.admission_estimate_failed

Future estimates SHOULD become more conservative.

## 86. Learning Resource Estimator

A future advisory estimator MAY model:

    PeakVRAM = f(model, quantization, context,
                 concurrent_sequences, provider, GPU architecture)

Hard admission SHALL remain conservative.

## 87. Resource Events

RFC-0072 SHALL include:

    aidn.resource.state_changed
    aidn.resource.lease_requested
    aidn.resource.lease_granted
    aidn.resource.lease_denied
    aidn.resource.lease_released
    aidn.resource.runtime_idle
    aidn.resource.runtime_eviction_candidate
    aidn.resource.runtime_evicted
    aidn.resource.activation_waiting
    aidn.resource.capacity_available
    aidn.resource.vram_pressure
    aidn.resource.ram_pressure
    aidn.resource.reconciliation_started
    aidn.resource.reconciliation_completed
    aidn.resource.admission_estimate_failed

## 88. Hooks

Agents MAY subscribe to resource pressure, long-waiting workloads, repeated
admission denial, OOM estimate failure, eviction, and queue starvation.
Agents MAY adjust policy, but normal scheduling SHALL NOT depend on Agent
availability.

## 89. Why the Agent Is Not the Scheduler

Admission is a fast, always-available, predictable, and safe systems problem.
An Agent may reason about policy; the Resource Broker decides whether 19 GB fits
into 4 GB. Core admission is independent of LLM latency.

## 90. MCP Tools

MCP-0001 SHALL add:

    aidn.resource_broker.status
    aidn.resource_broker.devices
    aidn.resource_broker.leases
    aidn.resource_broker.forecast
    aidn.resource_broker.explain_denial
    aidn.scheduler.status
    aidn.scheduler.queues
    aidn.scheduler.candidates
    aidn.scheduler.reconcile
    aidn.scheduler.explain_decision
    aidn.runtime.instances
    aidn.runtime.drain
    aidn.runtime.stop
    aidn.runtime.pin
    aidn.runtime.unpin

## 91. Manual Reconciliation

aidn.scheduler.reconcile MAY request immediate reevaluation but SHALL NOT bypass
policy. Normal system events trigger reconciliation automatically.

## 92. Forecast

An agent can ask whether a Bundle can start now. A DENIED response SHOULD
identify required and available resources, possible evictions, and the result
after each candidate eviction:

    result: DENIED
    resource:
      type: VRAM
      required: 21GB
      available: 4GB
    possible_evictions:
      - runtime_id: runtime-A
        releases: 12GB
        state: WARM_IDLE
    result_after_eviction:
      available: 16GB
      still_insufficient: true

The response MAY instead report would_fit: true when the plan is sufficient.

## 93. Scheduler Explainability

Every major decision SHOULD be explainable, including required VRAM, free
allocatable VRAM, why a smaller workload ran, why a warm Runtime was evicted,
and which waiting workloads became admissible after the transition.

## 94. UI — Resources

Advanced UI SHOULD expose:

    Resources
      GPUs
      RAM
      CPU
      Leases
      Runtime Instances
      Queues
      Scheduler

## 95. GPU View

The GPU view SHOULD show physical, safety, leased, measured, external, and
free values, for example:

    GPU0 RTX3090
    24 GB
    Physical: 24.0 GB
    Safety:    1.0 GB
    Leased:   20.0 GB
    Measured: 19.1 GB
    External:  0.5 GB
    Free:      3.5 GB

## 96. Runtime View

The Runtime view SHOULD show model, state, allocation, and eviction eligibility:

    Qwen       WARM_ACTIVE  12 GB
    Embedding  WARM_IDLE     4 GB  Eviction eligible
    Whisper    BUSY          0.7 GB

## 97. Queue View

The Queue view SHOULD show Endpoint, state, waiting count, and Runtime:

    Endpoint   State          Waiting   Runtime
    Qwen       WARM_ACTIVE       3      runtime-1
    DeepSeek   RESOURCE_WAIT     2      -
    Whisper    BUSY              1      runtime-3
    Embedding  WARM_IDLE         0      runtime-2

## 98. Reconciliation View

Advanced UI SHOULD show the last reconciliation timestamp, trigger,
candidate count, runnable count, eviction candidates, and the resulting
decision, such as starting Whisper while keeping DeepSeek waiting.

## 99. Metrics

The Broker SHALL expose physical, allocatable, leased, measured, and external
VRAM; physical, allocated, and used RAM; active and warm idle Runtimes;
pending Requests and activations; reconciliation count and duration;
admission denials; evictions; starts and reloads; OOM events; and queue wait
P50/P95.

## 100. Persistence

Resource Leases are Runtime state. After restart the Hypervisor SHALL reconcile
actual hardware, actual processes, persisted Runtime state, and persisted
Leases before allowing new admission.

## 101. Startup Reconciliation

Startup sequence:

    discover devices
      -> discover processes
      -> discover GPU allocations
      -> identify AiDN Runtimes
      -> reconstruct Leases
      -> mark unknown allocations external
      -> full reconciliation
      -> enable Scheduler

## 102. Failure Safety

If Broker state is uncertain, new cold Runtime activation SHALL be denied until
reconciliation restores trustworthy state. Safe refusal is preferable to an
optimistic OOM.

## 103. Scheduler Policy Profiles

Suggested presets:

    LOCAL_FIRST
    MAX_UTILIZATION
    LOW_LATENCY
    FAIR_SHARE
    NETWORK_PROVIDER

Profiles MAY combine behaviors.

## 104. Recommended Default

The recommended default is:

    LOCAL_FIRST + FIT_AWARE + FAIR_SHARE
      + WAIT_TIME_AGING + WARM_RUNTIME_EVICTION

## 105. MVP Components

The first implementation SHALL include:

- Hardware Monitor;
- Resource Broker;
- Resource Profile Store;
- Resource Lease Manager;
- Runtime Instance Manager;
- Endpoint Queue Manager;
- Global Admission Scheduler;
- Resource Reconciliation Engine;
- warm Runtime eviction;
- Resource Events;
- MCP inspection tools.

## 106. MVP Scheduler Behavior

The MVP algorithm SHALL:

1. Reconcile on every material resource change.
2. Send Requests to compatible warm Runtimes with execution slots.
3. Build a Candidate Set from every eligible Endpoint queue.
4. Filter by current fit.
5. Rank by priority, wait-time aging, and fit.
6. Grant a Lease to the best candidate.
7. Start the Runtime.
8. Re-run reconciliation.
9. If none fits, inspect WARM_IDLE Runtimes.
10. Evaluate whether eviction enables waiting work.
11. Evict a policy-selected Runtime where beneficial.
12. Re-run reconciliation.
13. Stop at a stable scheduling state.

## 107. Deferred Features

The following MAY be postponed:

- optimal bin packing;
- machine-learned scheduling;
- predictive workload arrival;
- distributed Hypervisor resource pooling;
- live model migration;
- cross-node checkpoint migration;
- advanced economic optimization.

## 108. Core Interaction Model

    Request arrives
      -> Endpoint Queue
      -> Reconciliation
      -> warm Runtime available?
         -> yes: run
         -> no: Activation Candidate
            -> fits?
               -> yes: Lease -> start -> run
               -> no: RESOURCE_WAIT -> inspect idle Runtimes
                  -> eviction useful?
                     -> yes: evict -> release Lease -> reconcile
                     -> no: wait

## 109. Design Invariants

The following SHALL always hold:

- VRAM is a first-class hard schedulable resource.
- Host RAM is independently tracked.
- Context and concurrency affect admission.
- Warm idle models still consume resources.
- Every Runtime requires a Resource Lease.
- Endpoint queues remain logically independent.
- No single global FIFO controls all workloads.
- Any material resource change triggers reconciliation.
- Reconciliation reevaluates all eligible Endpoint queues.
- Scheduling continues until a stable local state is reached.
- A non-runnable workload cannot block an unrelated runnable workload.
- Fairness and aging prevent permanent starvation.
- Idle warm Runtimes may be evicted to enable waiting work.
- Request completion does not necessarily release resources.
- Local owner workloads retain priority.
- External processes reduce allocatable capacity.
- Admission denial is not Runtime failure.
- Resource contention is observable and explainable.
- Agents may influence policy but are not required for admission.
- The Resource Broker is the final local authority on Runtime start.

## 110. Normative Summary

Every meaningful change in local resource availability causes a new global
scheduling reconciliation. During reconciliation, the Hypervisor reevaluates
all Endpoint queues, active Runtime Instances, resource Leases, and eligible
warm-runtime eviction options. The Scheduler repeatedly admits the
highest-ranked workload that fits until no further beneficial placement is
possible.

This rule is the foundation of local AiDN Runtime scheduling.
