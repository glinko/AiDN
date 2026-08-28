# ECO-0005 Epoch Reward Accounting Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first executable `ECO-0005` foundation by tracking recyclable protocol removals and deriving deterministic epoch reward budgets from base emission, recyclable removals, and Faucet carryover.

**Architecture:** Introduce a small economics model surface for recyclable-removal records, epoch reward pool configuration, and derived epoch reward budgets. Thread that surface through validation-bond forfeiture and fee-style ledger events first, then expose the derived summary through state and service APIs without attempting full epoch scheduling or consensus execution yet.

**Tech Stack:** Python, Pydantic, pytest, existing `aidn_hypervisor` state/service/validation layers

---

### Task 1: Add Canonical ECO-0005 Models

**Files:**
- Create: `src/aidn_hypervisor/economics/__init__.py`
- Create: `src/aidn_hypervisor/economics/models.py`
- Test: `tests/economics/test_models.py`

- [ ] Define recyclable-removal, reward-pool, and epoch-budget models with deterministic totals and invariant checks.
- [ ] Cover:
  - recyclable removal categories such as `network_fee`, `validation_bond_forfeiture`, and `penalty`;
  - fixed pool shares summing to `1.0`;
  - faucet carryover and recycle backlog fields;
  - derived per-pool allocations for `consensus`, `registry`, `validation`, and `faucet`.

### Task 2: Persist Epoch-Economic State

**Files:**
- Modify: `src/aidn_hypervisor/state.py`
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/economics/test_service.py`

- [ ] Add snapshot models for recyclable removals and derived epoch reward budgets.
- [ ] Extend `HypervisorStateSnapshot` and service export/restore paths so the new economic state survives persistence and reload.
- [ ] Keep the state surface additive and backward-compatible with existing snapshots.

### Task 3: Record Recyclable Removals From Existing Flows

**Files:**
- Modify: `src/aidn_hypervisor/validation/models.py`
- Modify: `src/aidn_hypervisor/validation/service.py`
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/validation/test_service.py`
- Test: `tests/economics/test_service.py`

- [ ] Treat maintenance-validation bond forfeiture as a recyclable removal event instead of a terminal burn-only concept.
- [ ] Add a HypervisorService-side helper to record recyclable removals into both the internal store and the wallet-ledger style export stream.
- [ ] Preserve existing validation-bond wallet events while adding explicit economic provenance for later epoch accounting.

### Task 4: Derive The Next Epoch Reward Budget

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/economics/test_service.py`

- [ ] Add a deterministic derivation helper that computes the next epoch reward budget from:
  - base emission;
  - recyclable removals from the previous epoch;
  - recycle backlog;
  - faucet carryover.
- [ ] Return both pool budgets and top-level supply-accounting totals needed by later registry/consensus work.
- [ ] Expose a read-model method so dashboard/API work can consume it later without re-deriving economics ad hoc.

### Task 5: Verify

**Files:**
- Test: `tests/economics/test_models.py`
- Test: `tests/economics/test_service.py`
- Test: `tests/validation/test_service.py`

- [ ] Run targeted pytest coverage for the new economics models/service hooks.
- [ ] Confirm validation-bond forfeiture still behaves correctly while now producing recyclable-removal accounting.
