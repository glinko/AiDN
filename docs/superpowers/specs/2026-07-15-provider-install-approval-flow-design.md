# Provider Install Approval and Apply Flow Design

Date: 2026-07-15

Status: Draft

## Goal

Add a complete MVP lifecycle for provider plugin installation plans:

1. preview a declarative plan;
2. approve the exact plan/configuration/permission set;
3. apply the approved plan through a controlled execution boundary;
4. persist the apply job and result;
5. surface the installed Provider Instance in the operator workspace.

The slice implements the product workflow end-to-end, but keeps real host
mutation behind an executor interface. The MVP executor records declarative
actions and creates a Provider Instance; it does not run shell, start Docker,
download models, or hand arbitrary code root privileges.

## Problem

The Provider Plugin Directory now exposes plugin metadata and preview-only
installation plans. Preview is useful, but the operator still cannot complete
the core story:

`Browse plugin -> review plan -> approve -> apply -> provider appears`

Jumping directly from preview to real host changes would be unsafe. Provider
plugins are community code and may request filesystem, network, container,
secret, or GPU access. The first apply slice therefore needs an auditable
execution boundary before adding real container/process/download adapters.

## Approved Approach

Implement a local controlled apply workflow.

The Hypervisor stores:

- `ProviderInstallationApproval`: operator approval bound to exact plan and
  configuration hashes;
- `ProviderInstallationJob`: durable local apply attempt bound to one approval;
- `ProviderInstallationStepResult`: normalized execution result for each
  declarative plan section.

Apply requires an existing `APPROVED` approval. The service rebuilds the plan
from the current plugin and submitted/current configuration, recomputes the
plan hash, and refuses to apply if the hash differs from the approval.

The MVP executor is `RecordedProviderInstallationExecutor`. It validates and
records declarative actions from the plan, marks the job succeeded, and creates
a local `ProviderInstance` from the approved configuration. Future host
executors can replace this component without changing API, persistence, or UI
contracts.

## Non-Goals

This slice explicitly does not implement:

- real shell execution;
- Docker/container start/stop;
- model downloads;
- package manager execution;
- GitHub repository checkout;
- arbitrary plugin installer code;
- secret value materialization;
- Ledger operations;
- Registry objects;
- Endpoint publication;
- model deployment installation.

The UI may say `Apply` because the lifecycle is real, but it must also say the
MVP executor is controlled and does not perform host mutations.

## Data Model

### ProviderInstallationApproval

```yaml
provider_installation_approval:
  approval_id:
  plugin_id:
  plan_id:
  plan_hash:
  configuration_hash:
  approved_permissions:
  acknowledged_secret_requirements:
  operator_note:
  status:
  created_at:
```

Statuses:

- `APPROVED`
- `REVOKED`

### ProviderInstallationJob

```yaml
provider_installation_job:
  job_id:
  approval_id:
  plugin_id:
  plan_id:
  plan_hash:
  configuration_hash:
  status:
  executor_id:
  step_results:
  provider_instance_id:
  error_code:
  error_message:
  created_at:
  started_at:
  completed_at:
```

Statuses:

- `QUEUED`
- `RUNNING`
- `SUCCEEDED`
- `FAILED`
- `CANCELLED`

The MVP creates and processes jobs synchronously through the service method. The
status model still includes `QUEUED` and `RUNNING` so the same persisted shape
can support async workers later.

### ProviderInstallationStepResult

```yaml
provider_installation_step_result:
  step_id:
  step_type:
  status:
  summary:
  details:
```

Statuses:

- `RECORDED`
- `SKIPPED`
- `FAILED`

The recorded executor creates one step result per declarative action category,
for example `containers`, `volumes`, `networks`, `environment`,
`model_downloads`, and `health_checks`.

## Hashing

The service computes deterministic hashes with canonical JSON:

- `plan_hash = sha256(canonical_json(InstallationPlan))`
- `configuration_hash = sha256(canonical_json(configuration))`

Approval creation and apply both compute hashes server-side. Apply never trusts
a client-provided plan hash.

Apply is permitted only when:

- approval status is `APPROVED`;
- current plan hash equals approval plan hash;
- current configuration hash equals approval configuration hash;
- plan is declarative-only;
- plugin still supports `CAN_INSTALL_PROVIDER`.

## Service Flow

### Preview

Existing flow remains:

`plugin_id + configuration -> InstallationPlan`

No approval or job is created by preview alone.

### Approve

1. Operator submits `plugin_id`, `configuration`, optional `operator_note`.
2. Service rebuilds the installation plan.
3. Service validates the plan through `InstallationPlan`.
4. Service extracts permission IDs and secret requirement summaries.
5. Service computes `plan_hash` and `configuration_hash`.
6. Service stores `ProviderInstallationApproval`.
7. API returns approval.

### Apply

1. Operator submits `approval_id`.
2. Service loads approval.
3. Service rejects missing, revoked, or already-incompatible approvals.
4. Service rebuilds the plan from approved plugin/configuration context.
5. Service recomputes hashes and rejects mismatch.
6. Service creates a `ProviderInstallationJob` in `QUEUED`.
7. Service marks job `RUNNING` and passes plan to executor.
8. Executor records step results and returns installed provider metadata.
9. Service creates or updates a local `ProviderInstance`.
10. Service marks job `SUCCEEDED` or `FAILED`.
11. API returns job record.

The MVP can process synchronously because the executor is local and non-host
mutating. The API shape must not prevent future async behavior.

## Executor Boundary

Define a narrow executor interface:

```python
class ProviderInstallationExecutor(Protocol):
    executor_id: str

    def apply(self, *, approval, plan, configuration) -> ProviderInstallationExecutionResult:
        ...
```

The executor returns:

```yaml
provider_installation_execution_result:
  step_results:
  provider_instance:
```

The MVP implementation:

- does not call shell;
- does not import plugin installer code;
- does not start containers;
- does not write files;
- does not download models;
- does not materialize secrets;
- derives a `ProviderInstance` from plugin manifest and configuration.

Future implementations may add real adapters only after explicit permission and
sandbox design:

- container plan executor;
- process plan executor;
- model download executor;
- health check executor;
- remote deployment agent executor.

## Provider Instance Creation

On successful MVP apply, create a local `ProviderInstance` with:

- deterministic or stable `provider_instance_id` derived from approval/job;
- `plugin_id`;
- first manifest provider family, or `"unknown"` when absent;
- display name from configuration `display_name`, fallback to manifest display
  name;
- `connection_mode = "managed"`;
- original approved configuration;
- `operational_state = "ready"`.

This represents a controlled local lifecycle record, not proof that Ollama,
vLLM, or any external process is actually running.

## API

Existing:

`POST /operators/provider-plugins/{plugin_id}/installation-plan`

New:

`POST /operators/provider-plugins/{plugin_id}/installation-approvals`

Request:

```json
{
  "configuration": {},
  "operator_note": "Approved for local fake provider"
}
```

New:

`GET /operators/provider-installation-approvals`

New:

`POST /operators/provider-installation-approvals/{approval_id}/apply`

Request:

```json
{
  "operator_note": "Apply controlled MVP executor"
}
```

Response:

```json
{
  "job_id": "pij-...",
  "approval_id": "pia-...",
  "plugin_id": "fake-managed",
  "status": "SUCCEEDED",
  "executor_id": "recorded-declarative-v1",
  "provider_instance_id": "pi-...",
  "step_results": []
}
```

New:

`GET /operators/provider-installation-jobs`

Errors:

- unknown plugin: `404`;
- unknown approval: `404`;
- invalid/non-installable plan: `409`;
- revoked approval: `409`;
- hash mismatch: `409`;
- malformed request: `422`.

## Persistence

Provider inventory store owns approvals and jobs because they are local provider
lifecycle state.

For this slice:

- `InMemoryProviderInventoryStore` stores approvals and jobs;
- Hypervisor snapshot/restore includes approvals and jobs;
- successfully applied Provider Instances are already included through provider
  inventory snapshots.

No separate database or file format is added.

## Operator UI

Providers workspace should show:

- plugin install plan preview;
- approval count;
- job count and latest job status;
- `Approved, ready to apply` when an approval exists without a job;
- `Applied with controlled executor` when the job succeeds;
- copy explaining that MVP apply records declarative execution and creates a
  Provider Instance, but does not mutate host resources.

The UI may expose an `Apply approved plan` control. It must not claim that a
real provider binary/container/model has been installed.

## Security Rules

- Apply requires a stored approval.
- Apply recomputes and matches plan/configuration hashes.
- Apply is denied for revoked approvals.
- Apply is denied for attach-only plugins without `CAN_INSTALL_PROVIDER`.
- Apply is denied for non-declarative plans.
- Executor does not receive plaintext secret values in this slice.
- Plugin-supplied strings remain escaped in dashboard rendering.
- Apply result is local operational state, not protocol Verification,
  Certification, Reputation, Ledger, or Registry evidence.

## Testing Strategy

Add tests at five levels:

1. Model tests for approval, job, and step result shapes.
2. Store tests for approval/job persistence and listing.
3. Provider service tests for approval, apply success, hash mismatch, revoked
   approval rejection, and non-declarative plan rejection.
4. Hypervisor/API tests for approval/apply/list routes and persistence through
   snapshot/restore.
5. Operator view/dashboard tests for approval/job summary and controlled
   executor copy.

## Success Criteria

This slice is complete when:

- a plugin installation plan can be previewed;
- the exact plan can be approved;
- the approval can be applied through the controlled executor;
- apply creates a durable job record;
- successful apply creates a local Provider Instance;
- approval and job records survive snapshot/restore;
- hash mismatches, revoked approvals, attach-only plugins, and
  non-declarative plans are rejected;
- Providers workspace exposes approval and job state;
- tests pass without adding real host mutation.
