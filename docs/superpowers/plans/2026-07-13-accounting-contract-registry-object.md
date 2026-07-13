# Accounting Contract Registry Object Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `AccountingContract` a deterministic immutable object with explicit registry-style metadata and propagate its object references through existing Session and API surfaces.

**Architecture:** Extend the current `AccountingContract` model rather than introducing a separate registry subsystem. Compute deterministic object metadata from the contract payload, keep snapshots for auditability, and add explicit object references where Sessions and APIs already carry accounting data.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, existing Hypervisor and Session services.

---

## File Structure

- Modify `src/aidn_hypervisor/accounting/models.py` to add deterministic immutable object metadata and canonical hashing helpers.
- Modify `src/aidn_hypervisor/service.py` so `accounting_contract_for_endpoint()` emits a complete object with registry-style references.
- Modify `src/aidn_hypervisor/sessions/models.py` and `src/aidn_hypervisor/sessions/service.py` so accepted Sessions keep explicit accounting object references alongside the snapshot.
- Modify `tests/accounting/test_models.py`, `tests/test_wallet.py`, and `tests/sessions/test_service.py` to cover deterministic metadata and propagation.

## Task 1: Deterministic Accounting Contract Object Metadata

**Files:**
- Modify: `src/aidn_hypervisor/accounting/models.py`
- Test: `tests/accounting/test_models.py`

- [ ] **Step 1: Write failing model tests**

Add coverage that `AccountingContract` derives stable:

- `registry_object_id`
- `registry_object_version`
- `registry_namespace`
- `payload_hash`
- `payload_encoding`

and that equivalent contracts produce the same identifiers regardless of field ordering.

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests\accounting\test_models.py -q
```

Expected: fail because the metadata fields and derivation do not exist.

- [ ] **Step 3: Implement metadata derivation**

Add canonical payload helpers and compute deterministic metadata from contract content. Keep the existing contract API stable for current callers.

- [ ] **Step 4: Verify green**

Run:

```powershell
python -m pytest tests\accounting\test_models.py -q
```

Expected: pass.

## Task 2: Hypervisor Accounting Contract Generation

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/test_wallet.py`

- [ ] **Step 1: Write failing service test**

Extend the existing wallet/service accounting contract test to expect registry-style object metadata and a stable pricing policy reference.

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests\test_wallet.py::test_service_builds_provider_metered_accounting_contract_for_paid_endpoint -q
```

Expected: fail on missing object metadata fields.

- [ ] **Step 3: Implement Hypervisor object generation**

Update `accounting_contract_for_endpoint()` to return a full immutable contract object with deterministic metadata and an explicit pricing policy reference/hash.

- [ ] **Step 4: Verify green**

Run:

```powershell
python -m pytest tests\test_wallet.py::test_service_builds_provider_metered_accounting_contract_for_paid_endpoint -q
```

Expected: pass.

## Task 3: Session Propagation Of Accounting Object References

**Files:**
- Modify: `src/aidn_hypervisor/sessions/models.py`
- Modify: `src/aidn_hypervisor/sessions/service.py`
- Test: `tests/sessions/test_service.py`

- [ ] **Step 1: Write failing Session propagation test**

Extend Session-opening coverage to expect:

- `accounting_contract_object_id`
- `accounting_contract_object_version`
- `accounting_contract_namespace`

alongside the existing snapshot and `accounting_contract_hash`.

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests\sessions\test_service.py::test_open_session_preserves_accounting_contract_snapshot -q
python -m pytest tests\sessions\test_service.py::test_open_session_binds_accepted_marketplace_contract -q
```

Expected: fail on missing Session fields or propagation.

- [ ] **Step 3: Implement Session propagation**

Store explicit accounting object references in `EndpointSession` and derive `accounting_contract_hash` from the contract `payload_hash` when available.

- [ ] **Step 4: Verify green**

Run:

```powershell
python -m pytest tests\sessions\test_service.py::test_open_session_preserves_accounting_contract_snapshot tests\sessions\test_service.py::test_open_session_binds_accepted_marketplace_contract -q
```

Expected: pass.

## Task 4: Verification

**Files:**
- No additional production files expected.

- [ ] **Step 1: Run targeted gate**

Run:

```powershell
python -m pytest tests\accounting tests\sessions tests\ledger tests\endpoint_publications tests\test_wallet.py tests\test_api.py -q
```

Expected: pass.

- [ ] **Step 2: Run full suite**

Run:

```powershell
python -m pytest -q
```

Expected: pass.

- [ ] **Step 3: Run whitespace sanity check**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.
