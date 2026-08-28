# RFC-0051 Maximum Request Charge Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce `maximum_request_charge` before a paid request starts so sessions cannot exceed accepted exposure.

**Architecture:** Reuse the accounting contract snapshot already persisted on the session. Add a session-service preflight budget guard that compares remaining locked deposit to the session’s `maximum_request_charge`, then call it from request validation before task submission.

**Tech Stack:** Python, pytest, existing `sessions` and `HypervisorService` flow

---

### Task 1: Add Session Budget Guard

**Files:**
- Modify: `src/aidn_hypervisor/sessions/service.py`
- Test: `tests/sessions/test_service.py`

- [ ] Add a `require_request_budget(...)` session-service method.
- [ ] Reject when `remaining deposit < maximum_request_charge`.
- [ ] Preserve current behavior when no `maximum_request_charge` was published.

### Task 2: Enforce Guard During Paid Request Validation

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/test_api.py`

- [ ] Call the new guard from `_validate_task_session(...)`.
- [ ] Return the existing request-rejected behavior path through `/tasks`.
- [ ] Add a regression test proving the second request is blocked once remaining deposit drops below the contract ceiling.
