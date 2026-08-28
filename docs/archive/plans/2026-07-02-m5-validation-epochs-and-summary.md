# M5 Validation Epochs And Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the remaining `M5.1` validation surface by adding explicit epoch creation, spec-complete validation summaries, and validation state embedded into operator endpoint payloads.

**Architecture:** Keep `ValidationService` as the bounded context for request, epoch, bond, and report orchestration. Extend the service with richer read models and one new epoch API entrypoint; then project those read models into `api.py` operator/dashboard payloads instead of duplicating validation logic in multiple places.

**Tech Stack:** Python, FastAPI, Pydantic, existing `ValidationService` / `ValidationStore`, existing operator dashboard payload builders, `pytest`.

---

## File Structure

**Modify**
- `src/aidn_hypervisor/validation/service.py`
  Add explicit epoch creation helper plus spec-complete endpoint validation summary read model.
- `src/aidn_hypervisor/api.py`
  Add `POST /api/v1/validation/epochs` and project richer validation summaries into endpoint/dashboard payloads.
- `tests/validation/test_service.py`
  Cover direct epoch creation behavior and richer summary semantics.
- `tests/test_api.py`
  Cover epoch API, spec-complete validation summary payload, and operator dashboard validation projection.

## Task 1: Add Failing Tests For Epoch API And Full Validation Summary

**Files:**
- Modify: `tests/validation/test_service.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add failing service test for explicit epoch creation**

Add a test that requests validation twice, calls a new `create_validation_epoch(...)`, and asserts:
- returned `epoch.seed` matches input;
- two assignments are created;
- both requests transition to `authorization_issued`.

- [ ] **Step 2: Add failing API test for `POST /api/v1/validation/epochs`**

Add a test that:
- creates a `ValidationService`,
- queues one validation request,
- calls `POST /api/v1/validation/epochs`,
- asserts `200`,
- asserts one assignment and one authorization are returned.

- [ ] **Step 3: Add failing API test for spec-complete validation summary**

Add a test that:
- creates an endpoint,
- requests validation,
- calls `GET /api/v1/endpoints/{endpoint_id}/validation`,
- asserts presence of:
  - `endpoint_id`
  - `configuration_hash`
  - `validation_status`
  - `latest_request_id`
  - `latest_report_id`
  - `bond_state`
  - `validated_at`
  - `superseded_at`

- [ ] **Step 4: Add failing operator dashboard projection test**

Add a test that:
- creates an endpoint,
- requests validation,
- fetches `/operators/dashboard/endpoints`,
- asserts endpoint item includes a `validation_summary` object with matching `validation_status` and `bond_state`.

## Task 2: Implement Epoch Creation And Full Validation Read Models

**Files:**
- Modify: `src/aidn_hypervisor/validation/service.py`
- Modify: `tests/validation/test_service.py`

- [ ] **Step 1: Implement `create_validation_epoch(...)` as the public service entrypoint**

Add a small wrapper around current assignment logic so API code can call one explicit method instead of reaching directly into internal assignment semantics.

- [ ] **Step 2: Expand `validation_summary(endpoint_id)` to match spec**

Return a flat summary containing:
- `endpoint_id`
- `configuration_hash`
- `validation_status`
- `latest_request_id`
- `latest_report_id`
- `bond_state`
- `validated_at`
- `superseded_at`

Also keep current aggregate counters if already useful.

- [ ] **Step 3: Re-run focused validation service tests**

Run:

```bash
python -m pytest --import-mode=importlib tests\validation\test_service.py -k "epoch or summary" -q
```

Expected: PASS.

## Task 3: Add Epoch Route And Embed Validation Summary Into Operator Endpoint Payloads

**Files:**
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Add `POST /api/v1/validation/epochs`**

Accept:
- `epoch_id`
- `seed`
- `validator_entries`

Return:
- `epoch`
- `assignments`
- `authorizations`

- [ ] **Step 2: Reuse `validation_summary(endpoint_id)` inside endpoint routes**

For `/api/v1/endpoints/{endpoint_id}/validation`, return the richer service summary directly.

- [ ] **Step 3: Embed `validation_summary` into `/operators/dashboard/endpoints` items**

For each endpoint item, include a `validation_summary` object when `validation_service` is configured. Keep existing `validation` and `validation_mode` fields for UI compatibility.

- [ ] **Step 4: Re-run focused API tests**

Run:

```bash
python -m pytest --import-mode=importlib tests\test_api.py -k "validation epoch or validation summary or dashboard validation projection" -q
```

Expected: PASS.

## Task 4: Run Broader Regression And Commit

**Files:**
- Modify: `src/aidn_hypervisor/validation/service.py`
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `tests/validation/test_service.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Run broader suites**

Run:

```bash
python -m pytest --import-mode=importlib tests\validation -q
python -m pytest --import-mode=importlib tests\test_api.py -k "validation" -q
```

Expected: PASS.

- [ ] **Step 2: Commit**

```bash
git add src/aidn_hypervisor/validation/service.py src/aidn_hypervisor/api.py tests/validation/test_service.py tests/test_api.py docs/archive/plans/2026-07-02-m5-validation-epochs-and-summary.md
git commit -m "complete validation epoch and summary surfaces"
```

## Plan Review Notes

Spec coverage:
- explicit `POST /api/v1/validation/epochs`: Task 3
- spec-complete summary payload: Tasks 1-3
- operator-facing validation projection in endpoint surfaces: Task 3

Placeholder scan:
- no deferred placeholders remain in the plan body.

Type consistency:
- the plan uses `create_validation_epoch(...)` as the new public service method and keeps `validation_summary(...)` as the read-model entrypoint everywhere else.
