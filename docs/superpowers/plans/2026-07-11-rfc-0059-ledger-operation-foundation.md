# RFC-0059 Ledger Operation Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first real `RFC-0059` implementation slice: a canonical ledger-operation stream with wallet sender sequences, deterministic operation IDs, persistence, and integration with existing Faucet and Session flows.

**Architecture:** Introduce a focused ledger-operation model/service layer inside the hypervisor app rather than attempting full consensus execution. Reuse existing Faucet and Session domain flows, but make them emit canonical `LedgerOperation` records so the current app-state starts converging toward the future finalized state machine instead of maintaining only ad-hoc wallet/event journals.

**Tech Stack:** Python, Pydantic, existing `HypervisorService`, `SessionService`, FastAPI, pytest

---

### Task 1: Add Canonical Ledger Operation Core

**Files:**
- Create: `src/aidn_hypervisor/ledger/models.py`
- Create: `src/aidn_hypervisor/ledger/service.py`
- Modify: `src/aidn_hypervisor/state.py`
- Test: `tests/ledger/test_service.py`

- [x] Define ledger operation envelope, fee class, origin type, result model, and snapshot model
- [x] Add deterministic canonical serialization and `operation_id` hashing
- [x] Add wallet sender-sequence tracking and duplicate `operation_id` protection
- [x] Persist operation stream and wallet sequence state through `HypervisorStateSnapshot`
- [x] Verify with focused pytest coverage for operation IDs, sender sequences, duplicate rejection, and snapshot restore

### Task 2: Integrate Faucet And Session Flows

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/sessions/service.py`
- Modify: `src/aidn_hypervisor/main.py`
- Modify: `src/aidn_hypervisor/api.py`
- Test: `tests/ledger/test_service.py`
- Test: `tests/economics/test_service.py`
- Test: `tests/sessions/test_service.py`
- Test: `tests/test_api.py`

- [x] Make `claim_faucet_share()` emit canonical `FAUCET_CLAIM`
- [x] Make session open emit canonical `SESSION_OPEN`
- [x] Make session close/settlement emit canonical `SESSION_SETTLE`
- [x] Expose read-only operator endpoints for ledger-operation list/export
- [x] Verify faucet/session flows still work and now produce canonical operations

### Task 3: Keep The Existing Wallet Streams Aligned

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Test: `tests/economics/test_service.py`
- Test: `tests/sessions/test_service.py`

- [x] Ensure the new ledger-operation stream coexists with current wallet/economics/session streams
- [x] Reuse existing journal hooks where possible instead of duplicating business logic
- [x] Verify network-fee recyclable removal still happens during session settlement

### Task 4: Extend Canonical Operations To Validation And Endpoint Lifecycle

**Files:**
- Modify: `src/aidn_hypervisor/validation/service.py`
- Modify: `src/aidn_hypervisor/endpoints/service.py`
- Modify: `src/aidn_hypervisor/endpoints/api.py`
- Modify: `src/aidn_hypervisor/main.py`
- Test: `tests/ledger/test_service.py`
- Test: `tests/ledger/test_api.py`
- Test: `tests/validation/test_service.py`
- Test: `tests/endpoints/test_service.py`
- Test: `tests/endpoints/test_endpoint_api.py`

- [x] Make validation requests emit canonical `VALIDATION_REQUEST`
- [x] Make validation report commit emit canonical `VALIDATION_REPORT_COMMIT`
- [x] Make certification transitions emit canonical `CERTIFICATION_STATE_UPDATE`
- [x] Make maintenance resolution emit canonical `VALIDATION_BOND_REFUND` and `VALIDATION_BOND_FORFEIT`
- [x] Make endpoint create/update flows emit canonical `ENDPOINT_PUBLISH` and `ENDPOINT_UPDATE`
- [x] Verify validation and endpoint API/service flows still work with ledger recording enabled

### Next Slice

- [x] Bind endpoint publication flows to canonical advertisement operations (`ADVERTISEMENT_PUBLISH`, `ADVERTISEMENT_WITHDRAW`)
- [x] Introduce protocol-generated epoch accounting where a real deterministic domain event already exists (`EPOCH_TRANSITION`)
- [x] Introduce protocol-generated mint accounting where a real reward payout event already exists (`REWARD_MINT`)
- [ ] Add first conservative enforcement hooks for suspension/penalty operations only where objective evidence already exists
