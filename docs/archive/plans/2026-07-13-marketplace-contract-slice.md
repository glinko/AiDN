# Marketplace Contract Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind accepted Marketplace Advertisement and Offer identity into Session, Ledger, Settlement, and publication operations.

**Architecture:** Keep the slice local-first and compatibility-preserving. Extend existing Session and endpoint publication models with accepted marketplace identifiers and deterministic hashes, then surface those values in ledger operation payloads and tests.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, existing in-memory services and stores.

---

## File Structure

- Modify `src/aidn_hypervisor/sessions/models.py` to store accepted marketplace identifiers and deterministic contract/evidence hashes on `EndpointSession` and `SessionSettlementSummary`.
- Modify `src/aidn_hypervisor/sessions/service.py` to accept marketplace identifiers at Session open, derive `session_contract_hash`, derive `settlement_evidence_root`, and include these values in ledger operation payloads.
- Modify `src/aidn_hypervisor/endpoint_publications/service.py` to emit RFC-0059-aligned operation names for Advertisement publish/withdraw and a simple default Offer publish operation.
- Modify `src/aidn_hypervisor/canonical_models.py` and `src/aidn_hypervisor/canonical_projection.py` only if canonical advertisement projection needs `offer_id`.
- Modify `tests/sessions/test_service.py`, `tests/ledger/test_service.py`, and `tests/endpoint_publications/test_service.py` with red-first coverage for the new contract fields.

## Task 1: Session Accepted Marketplace Identity

**Files:**
- Modify: `src/aidn_hypervisor/sessions/models.py`
- Modify: `src/aidn_hypervisor/sessions/service.py`
- Test: `tests/sessions/test_service.py`

- [ ] **Step 1: Write failing Session test**

Add a test showing `open_session()` preserves `advertisement_id`, optional `offer_id`, `pricing_policy_hash`, explicit `accounting_contract_hash`, and derived `session_contract_hash`.

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests\sessions\test_service.py::test_open_session_binds_accepted_marketplace_contract -q
```

Expected: fail because `EndpointSession` does not yet expose those fields.

- [ ] **Step 3: Implement minimal Session fields**

Add optional fields to `EndpointSession` and parameters to `SessionService.open_session()`. Derive `accounting_contract_hash` from the accepted accounting contract when not supplied, and derive `session_contract_hash` from the accepted Session identity payload.

- [ ] **Step 4: Verify green**

Run:

```powershell
python -m pytest tests\sessions\test_service.py::test_open_session_binds_accepted_marketplace_contract -q
```

Expected: pass.

## Task 2: Ledger Session Open And Settlement Payloads

**Files:**
- Modify: `src/aidn_hypervisor/sessions/service.py`
- Test: `tests/ledger/test_service.py`

- [ ] **Step 1: Write failing Ledger test**

Add coverage that `SESSION_OPEN` includes accepted `advertisement_id`, optional `offer_id`, `pricing_policy_hash`, `accounting_contract_hash`, and `session_contract_hash`.

Add coverage that `SESSION_SETTLE` includes accepted `advertisement_id`, optional `offer_id`, `session_contract_hash`, and `settlement_evidence_root`.

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests\ledger\test_service.py -q
```

Expected: fail on missing payload fields.

- [ ] **Step 3: Implement ledger payload propagation**

Use the stored Session fields in `SESSION_OPEN` and `SESSION_SETTLE` operation payloads. Derive `settlement_evidence_root` from deterministic settlement evidence at close.

- [ ] **Step 4: Verify green**

Run:

```powershell
python -m pytest tests\ledger\test_service.py -q
```

Expected: pass.

## Task 3: Endpoint Advertisement And Offer Operations

**Files:**
- Modify: `src/aidn_hypervisor/endpoint_publications/service.py`
- Test: `tests/endpoint_publications/test_service.py`

- [ ] **Step 1: Write failing publication operation test**

Update tests to expect `ENDPOINT_ADVERTISEMENT_PUBLISH`, `ENDPOINT_OFFER_PUBLISH`, and `ENDPOINT_ADVERTISEMENT_WITHDRAW`.

- [ ] **Step 2: Verify red**

Run:

```powershell
python -m pytest tests\endpoint_publications\test_service.py -q
```

Expected: fail because old operation names are still emitted and no offer publish operation exists.

- [ ] **Step 3: Implement operation name and default offer payload**

Change publish/withdraw operation names to RFC-0059 names. Emit a default `ENDPOINT_OFFER_PUBLISH` after Advertisement publish with `offer_id` derived from the publication ID and `advertisement_id` bound to the publication.

- [ ] **Step 4: Verify green**

Run:

```powershell
python -m pytest tests\endpoint_publications\test_service.py -q
```

Expected: pass.

## Task 4: Slice Verification

**Files:**
- No additional production files expected.

- [ ] **Step 1: Run targeted acceptance gate**

Run:

```powershell
python -m pytest tests\sessions tests\ledger tests\endpoint_publications tests\test_canonical_projection.py tests\test_registry_service.py -q
```

Expected: pass.

- [ ] **Step 2: Run formatting sanity check**

Run:

```powershell
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 3: Review status**

Run:

```powershell
git status --short --branch
```

Expected: only intended audit, plan, source, and test changes are present.
