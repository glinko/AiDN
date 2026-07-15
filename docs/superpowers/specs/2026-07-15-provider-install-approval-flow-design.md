# Provider Install Approval Flow Design

Date: 2026-07-15

Status: Draft

## Goal

Add a durable local approval layer for provider installation plan previews.

The operator can preview a declarative installation plan, approve the exact
plan/configuration/permission set, and later see that approval in the Providers
workspace. The slice does not apply host changes, start containers, download
models, or execute installer code.

## Problem

The previous slice added rich Provider Plugin Directory metadata and
preview-only declarative installation plans. That is a safe inspection surface,
but it still lacks an audit boundary between "I looked at this plan" and "I
approve these permissions and secrets for a future install".

If approval remains a transient UI action, the next installer slice will have no
durable way to answer:

- which exact plan was approved;
- which permissions were accepted;
- which secret requirements were acknowledged;
- whether the plan changed after approval;
- whether approval survived restart or state restore.

Provider installation is a security boundary, so the approval record needs to be
durable before any future apply flow exists.

## Approved Approach

Implement a durable local `ProviderInstallationApproval` record.

The Hypervisor stores approval records in provider inventory state. An approval
binds to:

- `plugin_id`;
- deterministic `plan_hash`;
- deterministic `configuration_hash`;
- approved permission IDs;
- acknowledged secret requirement types/usages;
- optional operator note;
- status.

The approval is local Hypervisor state, not Ledger or Registry state. It is
auditable and persistent, but not canonical protocol evidence.

## Non-Goals

This slice explicitly does not implement:

- applying installation plans;
- host filesystem changes;
- shell execution;
- container start/stop;
- model downloads;
- secret value storage;
- Ledger operations;
- Registry objects;
- remote plugin directory publication.

## Data Model

Add `ProviderInstallationApproval` to provider models:

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

Initial statuses:

- `APPROVED`
- `REVOKED`

The MVP only creates `APPROVED`. `REVOKED` is reserved so a later slice can add
revocation without changing the persisted shape.

## Hashing

The service computes deterministic hashes with canonical JSON:

- `plan_hash = sha256(canonical_json(InstallationPlan))`
- `configuration_hash = sha256(canonical_json(configuration))`

The approval is valid for future apply only if the future plan hash and
configuration hash match exactly. This prevents a plugin from changing the plan
after approval and still reusing the old approval.

## Service Flow

### Preview

The existing preview flow remains:

`plugin_id + configuration -> InstallationPlan`

No approval is created by preview alone.

### Approve

New approval flow:

1. Operator submits `plugin_id`, `configuration`, optional `operator_note`.
2. Service rebuilds the installation plan from the current plugin and
   configuration.
3. Service validates the plan through `InstallationPlan`.
4. Service extracts permission IDs and secret requirement summaries from the
   plan and plugin manifest.
5. Service computes `plan_hash` and `configuration_hash`.
6. Service stores a `ProviderInstallationApproval`.
7. API returns the approval record.

The service does not trust client-provided plan hashes for creation. The client
may display a preview hash later, but the server remains authoritative.

## API

Add:

`POST /operators/provider-plugins/{plugin_id}/installation-approvals`

Request:

```json
{
  "configuration": {},
  "operator_note": "Approved for local fake provider dry run"
}
```

Response:

```json
{
  "approval_id": "pia-...",
  "plugin_id": "fake-managed",
  "plan_id": "plan-fake-managed",
  "plan_hash": "sha256:...",
  "configuration_hash": "sha256:...",
  "approved_permissions": ["network.private"],
  "acknowledged_secret_requirements": [],
  "operator_note": "Approved for local fake provider dry run",
  "status": "APPROVED",
  "created_at": "..."
}
```

Add:

`GET /operators/provider-installation-approvals`

Response:

```json
{
  "items": []
}
```

Errors follow the preview route:

- unknown plugin: `404`;
- invalid/non-installable plan: `409`;
- malformed request: `422`.

## Persistence

Provider inventory store owns approvals because they are local provider
lifecycle state.

For this slice:

- `InMemoryProviderInventoryStore` stores approvals in memory;
- Hypervisor snapshot/restore includes approvals so they survive persistence
  round trips already covered by state tests.

The implementation should not add a separate database or file format.

## Operator UI

Providers workspace should show:

- count of approved installation plans;
- latest approval status for installable plugin cards where available;
- copy that makes the boundary clear: `Approved, not applied`.

The dashboard should not show an `Apply` button in this slice.

## Security Rules

- Approval never stores secret values.
- Approval stores only secret requirement summaries.
- Approval binds to plan hash and configuration hash.
- Approval is denied for attach-only plugins without `CAN_INSTALL_PROVIDER`.
- Approval is denied for non-declarative plans.
- Plugin-supplied strings remain escaped in the dashboard.

## Testing Strategy

Add tests at four levels:

1. Model tests for approval shape and hash-like fields.
2. Provider service tests for create/list approval and rejection of attach-only
   plugins.
3. Hypervisor/API tests for POST/GET approval routes and persistence through
   snapshot/restore.
4. Operator view/dashboard tests for summary count and `Approved, not applied`
   copy.

## Success Criteria

This slice is complete when:

- a plugin installation plan can be approved without being applied;
- approval records are durable through snapshot/restore;
- approvals bind to exact plan/configuration hashes;
- attach-only and non-declarative plans cannot be approved;
- Providers workspace exposes approval state;
- full test suite passes.
