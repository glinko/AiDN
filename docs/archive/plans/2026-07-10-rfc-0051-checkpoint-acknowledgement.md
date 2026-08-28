# RFC-0051 Checkpoint Acknowledgement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `UsageAcknowledgement` and last-accepted-checkpoint settlement semantics to paid Sessions.

**Architecture:** Extend session state with lightweight accounting checkpoint fields, then update runtime metering flow so each session-scoped `UsageReport` is auto-acknowledged locally with `accepted_unverified` unless a mismatch is recorded. Session settlement will use the last accepted checkpoint amount instead of blindly trusting the latest metered usage.

**Tech Stack:** Python, Pydantic, pytest, existing `aidn_hypervisor` session/service/wallet flow

---

### Task 1: Persist Session Accounting Checkpoints

**Files:**
- Modify: `src/aidn_hypervisor/sessions/models.py`
- Modify: `src/aidn_hypervisor/sessions/service.py`
- Test: `tests/sessions/test_service.py`

- [ ] Add session fields for latest report snapshot, latest acknowledgement snapshot, accounting status, last accepted report sequence, and last accepted charged amount.
- [ ] Add a session-service method that records a `UsageReport` checkpoint and derives a `UsageAcknowledgement`.
- [ ] Support both accepted and mismatch acknowledgements.
- [ ] Verify mismatch leaves the previous accepted checkpoint intact.

### Task 2: Settle From Last Accepted Checkpoint

**Files:**
- Modify: `src/aidn_hypervisor/sessions/models.py`
- Modify: `src/aidn_hypervisor/sessions/service.py`
- Test: `tests/sessions/test_service.py`

- [ ] Update close-session settlement so charged usage comes from the last accepted checkpoint when one exists.
- [ ] Preserve current behavior for sessions with no accepted checkpoints and no requests.
- [ ] Add a regression test where a later mismatch prevents newer usage from entering settlement.

### Task 3: Wire Runtime Usage Reports Into Session Acknowledgement

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/test_wallet.py`

- [ ] Update automatic task metering flow so session-scoped `UsageReport` generation is followed by local acknowledgement.
- [ ] Attach both `usage_report` and `usage_acknowledgement` to the task result.
- [ ] Verify paid session tasks emit an accepted acknowledgement and settlement uses that checkpoint.
