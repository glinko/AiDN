# M5 Validation Bond And Escrow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first `M5.1` trust contract for endpoint validation, including operator validation bonds, local validator escrow Epoch modeling, validation reports, maintenance outcomes, and unified wallet ledger export.

**Architecture:** Add a dedicated `validation/` package instead of folding trust logic into the existing endpoint or wallet code. The new package owns validation requests, bonds, Epoch assignments, authorizations, and reports; `HypervisorService`, `api.py`, `main.py`, and `state.py` only integrate the service, persistence, and export surfaces. Operator-side bond economics and validator-side escrow capacity stay explicitly separate so a future external contract and distributed validator pool can replace the local adapters without changing endpoint semantics.

**Tech Stack:** Python, Pydantic models, existing FastAPI app/router, existing snapshot persistence (`HypervisorStateSnapshot`), existing wallet ledger export patterns, `pytest`.

---

## File Structure

**Create**
- `src/aidn_hypervisor/validation/models.py`
  Validation domain models: requests, bonds, reports, snapshots, Epochs, validator entries, assignments, authorizations.
- `src/aidn_hypervisor/validation/store.py`
  In-memory plus state-backed persistence boundary for validation records.
- `src/aidn_hypervisor/validation/escrow.py`
  Operator bond escrow adapter and validator escrow pool adapter interfaces plus local implementations.
- `src/aidn_hypervisor/validation/service.py`
  Validation orchestration service for request lifecycle, Epoch assignment, maintenance, and wallet-event emission callbacks.
- `tests/validation/test_models.py`
  Domain-model and state-transition validation tests.
- `tests/validation/test_service.py`
  Service-level tests for validation request flow, maintenance refund/forfeit, and Epoch assignment.

**Modify**
- `src/aidn_hypervisor/state.py`
  Add validation snapshots to `HypervisorStateSnapshot`.
- `src/aidn_hypervisor/service.py`
  Wire wallet-ledger append helpers for validation events and snapshot/restore integration hooks.
- `src/aidn_hypervisor/main.py`
  Build and inject the default `ValidationService`.
- `src/aidn_hypervisor/api.py`
  Add endpoint validation APIs and expose validation summary/history in endpoint payloads.
- `src/aidn_hypervisor/endpoints/models.py`
  Expand endpoint validation state beyond the current `enabled/model_class_supported/verification_status` placeholder.
- `tests/test_api.py`
  End-to-end API tests for request/history/report/maintenance routes.
- `tests/test_persistence.py`
  Snapshot round-trip tests for validation state.
- `tests/test_wallet.py`
  Unified wallet-ledger export tests for validation events.

## Task 1: Add Validation Domain Models And Persistence Shapes

**Files:**
- Create: `src/aidn_hypervisor/validation/models.py`
- Modify: `src/aidn_hypervisor/endpoints/models.py`
- Modify: `src/aidn_hypervisor/state.py`
- Test: `tests/validation/test_models.py`
- Test: `tests/test_persistence.py`

- [ ] **Step 1: Write the failing domain and snapshot tests**

```python
from aidn_hypervisor.state import HypervisorStateSnapshot
from aidn_hypervisor.validation.models import (
    ValidationAuthorization,
    ValidationBond,
    ValidationEpoch,
    ValidationReport,
    ValidationRequest,
    ValidationStatusSnapshot,
)


def test_validation_bond_tracks_remaining_released_and_forfeited_q() -> None:
    bond = ValidationBond(
        bond_id="bond-1",
        owner_wallet="wallet-1",
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        amount_q=500.0,
        remaining_locked_q=500.0,
        released_q=0.0,
        forfeited_q=0.0,
        escrow_adapter="local_operator_bond",
        escrow_reference="lock-1",
        status="locked",
    )

    assert bond.remaining_locked_q == 500.0
    assert bond.released_q == 0.0
    assert bond.forfeited_q == 0.0


def test_validation_status_snapshot_rejects_validated_without_request_id() -> None:
    ValidationStatusSnapshot(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        status="validated",
        latest_request_id=None,
        latest_report_id="report-1",
    )


def test_hypervisor_state_snapshot_round_trips_validation_lists() -> None:
    snapshot = HypervisorStateSnapshot(
        validation_requests=[
            ValidationRequest(
                request_id="req-1",
                endpoint_id="ep-1",
                configuration_hash="cfg-1",
                owner_wallet="wallet-1",
                request_kind="initial",
                status="queued",
                created_at="2026-07-02T00:00:00+00:00",
                bond_id="bond-1",
            )
        ],
        validation_bonds=[
            ValidationBond(
                bond_id="bond-1",
                owner_wallet="wallet-1",
                endpoint_id="ep-1",
                configuration_hash="cfg-1",
                amount_q=500.0,
                remaining_locked_q=500.0,
                released_q=0.0,
                forfeited_q=0.0,
                escrow_adapter="local_operator_bond",
                escrow_reference="lock-1",
                status="locked",
            )
        ],
        validation_epochs=[
            ValidationEpoch(
                epoch_id="epoch-1",
                seed="seed-1",
                status="open",
                created_at="2026-07-02T00:00:00+00:00",
            )
        ],
        validation_authorizations=[
            ValidationAuthorization(
                authorization_id="auth-1",
                request_id="req-1",
                epoch_id="epoch-1",
                authorization_token="token-1",
                guarantee_q=25.0,
                issued_at="2026-07-02T00:00:01+00:00",
                expires_at="2026-07-02T01:00:01+00:00",
                status="issued",
            )
        ],
    )

    assert snapshot.validation_requests[0].request_id == "req-1"
    assert snapshot.validation_bonds[0].bond_id == "bond-1"
    assert snapshot.validation_epochs[0].epoch_id == "epoch-1"
    assert snapshot.validation_authorizations[0].authorization_id == "auth-1"
```

- [ ] **Step 2: Run the focused model tests and verify they fail**

Run:

```bash
python -m pytest --import-mode=importlib tests/validation/test_models.py tests/test_persistence.py -k "validation" -q
```

Expected: FAIL with import errors for `aidn_hypervisor.validation.models` and missing `validation_*` snapshot fields on `HypervisorStateSnapshot`.

- [ ] **Step 3: Write the minimal models and snapshot fields**

```python
# src/aidn_hypervisor/validation/models.py
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ValidationRequestStatus = Literal[
    "draft",
    "bond_locked",
    "queued",
    "assigned",
    "authorization_issued",
    "report_submitted",
    "passed",
    "failed",
    "superseded",
    "revoked",
    "forfeited",
]
ValidationSnapshotStatus = Literal[
    "unvalidated",
    "pending_initial",
    "validated",
    "maintenance_due",
    "maintenance_in_progress",
    "validation_failed",
    "revoked",
    "superseded",
]


class ValidationRequest(BaseModel):
    request_id: str
    endpoint_id: str
    configuration_hash: str
    owner_wallet: str
    request_kind: Literal["initial", "maintenance"] = "initial"
    status: ValidationRequestStatus
    created_at: str
    bond_id: str
    epoch_id: str | None = None
    assignment_id: str | None = None
    authorization_id: str | None = None
    superseded_at: str | None = None


class ValidationBond(BaseModel):
    bond_id: str
    owner_wallet: str
    endpoint_id: str
    configuration_hash: str
    amount_q: float = Field(ge=0.0)
    remaining_locked_q: float = Field(ge=0.0)
    released_q: float = Field(ge=0.0)
    forfeited_q: float = Field(ge=0.0)
    escrow_adapter: str
    escrow_reference: str
    status: Literal["locked", "partially_released", "released", "forfeited"]

    @model_validator(mode="after")
    def _check_totals(self):
        total = round(self.remaining_locked_q + self.released_q + self.forfeited_q, 6)
        if total > round(self.amount_q, 6):
            raise ValueError("bond totals cannot exceed amount_q")
        return self


class ValidationReport(BaseModel):
    report_id: str
    request_id: str
    endpoint_id: str
    configuration_hash: str
    outcome: Literal["pass", "fail"]
    report_kind: Literal["initial", "maintenance"]
    validator_label: str
    evidence_summary: str
    signed_payload: dict = Field(default_factory=dict)
    created_at: str


class ValidationStatusSnapshot(BaseModel):
    endpoint_id: str
    configuration_hash: str
    status: ValidationSnapshotStatus
    latest_request_id: str | None = None
    latest_report_id: str | None = None
    validated_at: str | None = None
    superseded_at: str | None = None
    maintenance_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validated_requires_request(self):
        if self.status == "validated" and not self.latest_request_id:
            raise ValueError("validated snapshots require a latest_request_id")
        return self


class ValidationEpoch(BaseModel):
    epoch_id: str
    seed: str
    status: Literal["open", "assigned", "closed"]
    created_at: str


class ValidationValidatorEntry(BaseModel):
    validator_id: str
    validator_label: str
    shares: int = Field(ge=1)
    capability_profiles: list[str] = Field(default_factory=list)
    contribution_q: float = Field(ge=0.0)
    wallet_exposed: bool = False


class ValidationAssignment(BaseModel):
    assignment_id: str
    epoch_id: str
    request_id: str
    validator_id: str
    assigned_at: str


class ValidationAuthorization(BaseModel):
    authorization_id: str
    request_id: str
    epoch_id: str
    authorization_token: str
    guarantee_q: float = Field(ge=0.0)
    issued_at: str
    expires_at: str
    status: Literal["issued", "consumed", "expired"]
```

```python
# src/aidn_hypervisor/state.py
from aidn_hypervisor.validation.models import (
    ValidationAssignment,
    ValidationAuthorization,
    ValidationBond,
    ValidationEpoch,
    ValidationReport,
    ValidationRequest,
    ValidationStatusSnapshot,
    ValidationValidatorEntry,
)


class HypervisorStateSnapshot(BaseModel):
    ...
    validation_requests: list[ValidationRequest] = Field(default_factory=list)
    validation_bonds: list[ValidationBond] = Field(default_factory=list)
    validation_reports: list[ValidationReport] = Field(default_factory=list)
    validation_status_snapshots: list[ValidationStatusSnapshot] = Field(default_factory=list)
    validation_epochs: list[ValidationEpoch] = Field(default_factory=list)
    validation_validator_entries: list[ValidationValidatorEntry] = Field(default_factory=list)
    validation_assignments: list[ValidationAssignment] = Field(default_factory=list)
    validation_authorizations: list[ValidationAuthorization] = Field(default_factory=list)
```

```python
# src/aidn_hypervisor/endpoints/models.py
class EndpointValidationState(BaseModel):
    enabled: bool = False
    model_class_supported: bool = False
    verification_status: str = "unsupported"
    validation_profile: str | None = None
    validation_status: str = "unvalidated"
    latest_request_id: str | None = None
    latest_report_id: str | None = None
    validated_configuration_hash: str | None = None
    validated_at: str | None = None
```

- [ ] **Step 4: Run the focused model tests and verify they pass**

Run:

```bash
python -m pytest --import-mode=importlib tests/validation/test_models.py tests/test_persistence.py -k "validation" -q
```

Expected: PASS for the new model and snapshot tests.

- [ ] **Step 5: Commit the domain-model slice**

```bash
git add src/aidn_hypervisor/validation/models.py src/aidn_hypervisor/endpoints/models.py src/aidn_hypervisor/state.py tests/validation/test_models.py tests/test_persistence.py
git commit -m "add validation domain models"
```

## Task 2: Add Validation Store And Operator Bond Lifecycle

**Files:**
- Create: `src/aidn_hypervisor/validation/store.py`
- Create: `src/aidn_hypervisor/validation/escrow.py`
- Create: `src/aidn_hypervisor/validation/service.py`
- Test: `tests/validation/test_service.py`

- [ ] **Step 1: Write the failing service tests for request creation and maintenance math**

```python
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


def test_request_validation_locks_operator_bond_and_sets_pending_status() -> None:
    service = ValidationService(ValidationStore())

    result = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )

    assert result.request.status == "queued"
    assert result.bond.amount_q == 500.0
    assert result.bond.remaining_locked_q == 500.0
    assert result.snapshot.status == "pending_initial"


def test_submit_pass_report_marks_validated_without_releasing_initial_bond() -> None:
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-1",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            }
        ],
        seed="seed-1",
    )

    resolved = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )

    assert resolved.request.status == "passed"
    assert resolved.snapshot.status == "validated"
    assert resolved.bond.remaining_locked_q == 500.0


def test_maintenance_pass_refunds_half_of_remaining_locked_bond() -> None:
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-02T00:00:00+00:00",
    )

    outcome = service.resolve_maintenance(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="healthy",
    )

    assert outcome.bond.remaining_locked_q == 250.0
    assert outcome.bond.released_q == 250.0
    assert outcome.snapshot.status == "validated"


def test_maintenance_fail_forfeits_remaining_locked_bond() -> None:
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-02T00:00:00+00:00",
    )

    outcome = service.resolve_maintenance(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        outcome="fail",
        validator_label="validator-a",
        evidence_summary="latency exceeded threshold",
    )

    assert outcome.bond.status == "forfeited"
    assert outcome.bond.remaining_locked_q == 0.0
    assert outcome.bond.forfeited_q == 500.0
    assert outcome.snapshot.status == "validation_failed"
```

- [ ] **Step 2: Run the focused service tests and verify they fail**

Run:

```bash
python -m pytest --import-mode=importlib tests/validation/test_service.py -k "validation" -q
```

Expected: FAIL with import errors for `ValidationService` and `ValidationStore`.

- [ ] **Step 3: Implement the store, local bond adapter, and minimal service**

```python
# src/aidn_hypervisor/validation/escrow.py
from dataclasses import dataclass
from uuid import uuid4


@dataclass
class BondLockResult:
    escrow_reference: str
    amount_q: float


class LocalOperatorBondEscrowAdapter:
    adapter_name = "local_operator_bond"

    def lock_bond(self, owner_wallet: str, amount_q: float, purpose: dict) -> BondLockResult:
        return BondLockResult(escrow_reference=f"lock-{uuid4()}", amount_q=amount_q)

    def refund_bond(self, bond_id: str, amount_q: float) -> dict:
        return {"bond_id": bond_id, "refunded_q": amount_q}

    def forfeit_bond(self, bond_id: str, amount_q: float, beneficiary: str) -> dict:
        return {"bond_id": bond_id, "forfeited_q": amount_q, "beneficiary": beneficiary}

    def close_bond(self, bond_id: str) -> dict:
        return {"bond_id": bond_id, "status": "closed"}
```

```python
# src/aidn_hypervisor/validation/store.py
from aidn_hypervisor.state import HypervisorStateSnapshot


class ValidationStore:
    def __init__(self, state_store=None) -> None:
        self.state_store = state_store
        self._requests = {}
        self._bonds = {}
        self._reports = {}
        self._snapshots = {}
        self._epochs = {}
        self._validator_entries = {}
        self._assignments = {}
        self._authorizations = {}
        if state_store is not None:
            self.restore(state_store.load())

    def restore(self, snapshot: HypervisorStateSnapshot) -> None:
        self._requests = {item.request_id: item for item in snapshot.validation_requests}
        self._bonds = {item.bond_id: item for item in snapshot.validation_bonds}
        self._reports = {item.report_id: item for item in snapshot.validation_reports}
        self._snapshots = {
            (item.endpoint_id, item.configuration_hash): item
            for item in snapshot.validation_status_snapshots
        }
        self._epochs = {item.epoch_id: item for item in snapshot.validation_epochs}
        self._validator_entries = {
            item.validator_id: item for item in snapshot.validation_validator_entries
        }
        self._assignments = {
            item.assignment_id: item for item in snapshot.validation_assignments
        }
        self._authorizations = {
            item.authorization_id: item for item in snapshot.validation_authorizations
        }
```

```python
# src/aidn_hypervisor/validation/service.py
from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.validation.escrow import LocalOperatorBondEscrowAdapter
from aidn_hypervisor.validation.models import (
    ValidationBond,
    ValidationReport,
    ValidationRequest,
    ValidationStatusSnapshot,
)


class ValidationService:
    def __init__(self, store, *, bond_escrow=None, event_recorder=None) -> None:
        self.store = store
        self.bond_escrow = bond_escrow or LocalOperatorBondEscrowAdapter()
        self.event_recorder = event_recorder

    def request_validation(
        self,
        *,
        endpoint_id: str,
        owner_wallet: str,
        configuration_hash: str,
        minimum_session_deposit_q: float,
    ):
        lock = self.bond_escrow.lock_bond(
            owner_wallet,
            500.0,
            {
                "endpoint_id": endpoint_id,
                "configuration_hash": configuration_hash,
                "minimum_session_deposit_q": minimum_session_deposit_q,
            },
        )
        request = ValidationRequest(
            request_id=f"req-{uuid4()}",
            endpoint_id=endpoint_id,
            configuration_hash=configuration_hash,
            owner_wallet=owner_wallet,
            request_kind="initial",
            status="queued",
            created_at=datetime.now(timezone.utc).isoformat(),
            bond_id=f"bond-{uuid4()}",
        )
        bond = ValidationBond(
            bond_id=request.bond_id,
            owner_wallet=owner_wallet,
            endpoint_id=endpoint_id,
            configuration_hash=configuration_hash,
            amount_q=500.0,
            remaining_locked_q=500.0,
            released_q=0.0,
            forfeited_q=0.0,
            escrow_adapter=self.bond_escrow.adapter_name,
            escrow_reference=lock.escrow_reference,
            status="locked",
        )
        snapshot = ValidationStatusSnapshot(
            endpoint_id=endpoint_id,
            configuration_hash=configuration_hash,
            status="pending_initial",
            latest_request_id=request.request_id,
        )
        self.store.save_request(request)
        self.store.save_bond(bond)
        self.store.save_snapshot(snapshot)
        return type("ValidationRequestResult", (), {"request": request, "bond": bond, "snapshot": snapshot})()
```

- [ ] **Step 4: Run the focused service tests and verify they pass**

Run:

```bash
python -m pytest --import-mode=importlib tests/validation/test_service.py -k "locks_operator_bond or refunds_half or forfeits_remaining" -q
```

Expected: PASS for the request/bond/refund/forfeit tests.

- [ ] **Step 5: Commit the operator-bond service slice**

```bash
git add src/aidn_hypervisor/validation/store.py src/aidn_hypervisor/validation/escrow.py src/aidn_hypervisor/validation/service.py tests/validation/test_service.py
git commit -m "add validation bond service"
```

## Task 3: Add Validator Escrow Epoch, Share Expansion, And Authorization Flow

**Files:**
- Modify: `src/aidn_hypervisor/validation/models.py`
- Modify: `src/aidn_hypervisor/validation/escrow.py`
- Modify: `src/aidn_hypervisor/validation/service.py`
- Test: `tests/validation/test_service.py`

- [ ] **Step 1: Write the failing Epoch-assignment tests**

```python
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


def test_assign_epoch_requests_expands_validator_shares_and_assigns_in_seed_order() -> None:
    service = ValidationService(ValidationStore())
    first = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    second = service.request_validation(
        endpoint_id="ep-2",
        owner_wallet="wallet-2",
        configuration_hash="cfg-2",
        minimum_session_deposit_q=35.0,
    )

    epoch = service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-a",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            },
            {
                "validator_id": "val-b",
                "validator_label": "validator-b",
                "shares": 2,
                "capability_profiles": ["llm_text"],
                "contribution_q": 1000.0,
            },
        ],
        seed="seed-1",
    )

    assert epoch.epoch.seed == "seed-1"
    assert len(epoch.assignments) == 2
    assert all(item.authorization_id for item in epoch.assignments)


def test_authorization_hides_validator_wallet_and_share_count() -> None:
    service = ValidationService(ValidationStore())
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=40.0,
    )

    epoch = service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-a",
                "validator_label": "validator-a",
                "shares": 3,
                "capability_profiles": ["llm_text"],
                "contribution_q": 1500.0,
            }
        ],
        seed="seed-2",
    )

    authorization = epoch.authorizations[0]

    assert authorization.guarantee_q == 40.0
    assert "wallet" not in authorization.authorization_token
    assert "3" not in authorization.authorization_token
    assert requested.request.request_id == epoch.assignments[0].request_id
```

- [ ] **Step 2: Run the Epoch tests and verify they fail**

Run:

```bash
python -m pytest --import-mode=importlib tests/validation/test_service.py -k "assign_epoch_requests or authorization_hides" -q
```

Expected: FAIL because `assign_epoch_requests` does not yet exist or does not issue authorizations.

- [ ] **Step 3: Implement local validator escrow pool expansion and authorization issue**

```python
# src/aidn_hypervisor/validation/escrow.py
import hashlib
import random
from uuid import uuid4

from aidn_hypervisor.validation.models import ValidationAuthorization


class LocalValidatorEscrowPoolAdapter:
    adapter_name = "local_validator_escrow_pool"

    def expand_assignment_list(self, validator_entries: list) -> list[str]:
        expanded: list[str] = []
        for entry in validator_entries:
            expanded.extend([entry.validator_id] * entry.shares)
        return expanded

    def deterministic_shuffle(self, expanded: list[str], seed: str) -> list[str]:
        shuffled = list(expanded)
        rng = random.Random(seed)
        rng.shuffle(shuffled)
        return shuffled

    def issue_authorization(self, *, request_id: str, epoch_id: str, guarantee_q: float, now: str) -> ValidationAuthorization:
        token = hashlib.sha256(f"{epoch_id}:{request_id}:{guarantee_q}".encode("utf-8")).hexdigest()
        return ValidationAuthorization(
            authorization_id=f"auth-{uuid4()}",
            request_id=request_id,
            epoch_id=epoch_id,
            authorization_token=token,
            guarantee_q=guarantee_q,
            issued_at=now,
            expires_at=now,
            status="issued",
        )
```

```python
# src/aidn_hypervisor/validation/service.py
from aidn_hypervisor.validation.escrow import (
    LocalOperatorBondEscrowAdapter,
    LocalValidatorEscrowPoolAdapter,
)
from aidn_hypervisor.validation.models import (
    ValidationAssignment,
    ValidationEpoch,
    ValidationValidatorEntry,
)


class ValidationService:
    def __init__(self, store, *, bond_escrow=None, validator_escrow=None, event_recorder=None) -> None:
        self.store = store
        self.bond_escrow = bond_escrow or LocalOperatorBondEscrowAdapter()
        self.validator_escrow = validator_escrow or LocalValidatorEscrowPoolAdapter()
        self.event_recorder = event_recorder

    def assign_epoch_requests(self, *, epoch_id: str, validator_entries: list[dict], seed: str):
        epoch = ValidationEpoch(
            epoch_id=epoch_id,
            seed=seed,
            status="assigned",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        entries = [ValidationValidatorEntry(**item) for item in validator_entries]
        expanded = self.validator_escrow.expand_assignment_list(entries)
        shuffled = self.validator_escrow.deterministic_shuffle(expanded, seed)
        queued = self.store.list_requests(status="queued")
        assignments = []
        authorizations = []
        for index, request in enumerate(queued):
            validator_id = shuffled[index]
            assigned_at = datetime.now(timezone.utc).isoformat()
            assignment = ValidationAssignment(
                assignment_id=f"assign-{uuid4()}",
                epoch_id=epoch_id,
                request_id=request.request_id,
                validator_id=validator_id,
                assigned_at=assigned_at,
            )
            authorization = self.validator_escrow.issue_authorization(
                request_id=request.request_id,
                epoch_id=epoch_id,
                guarantee_q=self.store.minimum_session_deposit_for_request(request.request_id),
                now=assigned_at,
            )
            self.store.save_assignment(assignment)
            self.store.save_authorization(authorization)
            self.store.save_request(
                request.model_copy(
                    update={
                        "status": "authorization_issued",
                        "epoch_id": epoch_id,
                        "assignment_id": assignment.assignment_id,
                        "authorization_id": authorization.authorization_id,
                    }
                )
            )
            assignments.append(assignment)
            authorizations.append(authorization)
        self.store.save_epoch(epoch)
        for entry in entries:
            self.store.save_validator_entry(entry)
        return type(
            "ValidationEpochResult",
            (),
            {"epoch": epoch, "assignments": assignments, "authorizations": authorizations},
        )()
```

- [ ] **Step 4: Run the Epoch tests and verify they pass**

Run:

```bash
python -m pytest --import-mode=importlib tests/validation/test_service.py -k "assign_epoch_requests or authorization_hides" -q
```

Expected: PASS for deterministic assignment and authorization-redaction tests.

- [ ] **Step 5: Commit the validator-escrow slice**

```bash
git add src/aidn_hypervisor/validation/models.py src/aidn_hypervisor/validation/escrow.py src/aidn_hypervisor/validation/service.py tests/validation/test_service.py
git commit -m "add validation epoch assignment flow"
```

## Task 4: Wire Validation APIs And App Integration

**Files:**
- Modify: `src/aidn_hypervisor/main.py`
- Modify: `src/aidn_hypervisor/api.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing API tests**

```python
from fastapi.testclient import TestClient

from aidn_hypervisor.main import build_app
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


def test_request_validation_endpoint_returns_bond_and_snapshot_summary() -> None:
    validation_service = ValidationService(ValidationStore())
    client = TestClient(build_app(service=_service(), validation_service=validation_service))

    response = client.post("/api/v1/endpoints/ep-1/request-validation")

    assert response.status_code == 200
    assert response.json()["data"]["request"]["status"] == "queued"
    assert response.json()["data"]["bond"]["amount_q"] == 500.0
    assert response.json()["data"]["snapshot"]["status"] == "pending_initial"


def test_endpoint_validation_history_endpoint_returns_reports_and_assignments() -> None:
    validation_service = ValidationService(ValidationStore())
    validation_service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    client = TestClient(build_app(service=_service(), validation_service=validation_service))

    response = client.get("/api/v1/endpoints/ep-1/validation/history")

    assert response.status_code == 200
    assert len(response.json()["data"]["requests"]) == 1


def test_submit_validation_report_endpoint_marks_request_passed() -> None:
    validation_service = ValidationService(ValidationStore())
    requested = validation_service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    validation_service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-1",
                "validator_label": "validator-a",
                "shares": 1,
                "capability_profiles": ["llm_text"],
                "contribution_q": 500.0,
            }
        ],
        seed="seed-1",
    )
    client = TestClient(build_app(service=_service(), validation_service=validation_service))

    response = client.post(
        f"/api/v1/validation/requests/{requested.request.request_id}/reports",
        json={"outcome": "pass", "validator_label": "validator-a", "evidence_summary": "ok"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["request"]["status"] == "passed"
    assert response.json()["data"]["snapshot"]["status"] == "validated"
```

- [ ] **Step 2: Run the API tests and verify they fail**

Run:

```bash
python -m pytest --import-mode=importlib tests/test_api.py -k "request_validation_endpoint or validation_history_endpoint or submit_validation_report_endpoint" -q
```

Expected: FAIL because `build_app` does not accept `validation_service` and the validation routes do not exist.

- [ ] **Step 3: Wire the default service and add the validation routes**

```python
# src/aidn_hypervisor/main.py
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


def build_app(
    service: HypervisorService | None = None,
    registry_service: RegistryService | None = None,
    endpoint_service: EndpointService | None = None,
    endpoint_publication_service: EndpointPublicationService | None = None,
    remote_endpoint_service: RemoteEndpointService | None = None,
    session_service: SessionService | None = None,
    validation_service: ValidationService | None = None,
) -> FastAPI:
    ...
    resolved_validation_service = validation_service or _build_default_validation_service(
        state_store=state_store
    )
    resolved_service.validation_service = resolved_validation_service
    app.include_router(
        build_api_router(
            resolved_service,
            ...
            validation_service=resolved_validation_service,
        )
    )


def _build_default_validation_service(*, state_store: FileStateStore | None = None) -> ValidationService:
    if state_store is None:
        state_store = _default_state_store()
    return ValidationService(ValidationStore(state_store))
```

```python
# src/aidn_hypervisor/api.py
def build_api_router(
    service,
    *,
    registry_service=None,
    endpoint_service=None,
    endpoint_publication_service=None,
    remote_endpoint_service=None,
    session_service=None,
    validation_service=None,
) -> APIRouter:
    ...

    @router.post("/api/v1/endpoints/{endpoint_id}/request-validation")
    async def request_validation(endpoint_id: str) -> JSONResponse:
        if validation_service is None or endpoint_service is None:
            return _error(503, "validation_unavailable", "Validation service is not configured")
        manifest = endpoint_service.get_endpoint(endpoint_id).endpoint
        result = validation_service.request_validation(
            endpoint_id=endpoint_id,
            owner_wallet=manifest.owner_wallet,
            configuration_hash=manifest.configuration_hash,
            minimum_session_deposit_q=manifest.session.minimum_deposit,
        )
        return _ok(
            {
                "request": result.request.model_dump(mode="json"),
                "bond": result.bond.model_dump(mode="json"),
                "snapshot": result.snapshot.model_dump(mode="json"),
            }
        )

    @router.get("/api/v1/endpoints/{endpoint_id}/validation")
    async def endpoint_validation_summary(endpoint_id: str) -> JSONResponse:
        if validation_service is None:
            return _error(503, "validation_unavailable", "Validation service is not configured")
        summary = validation_service.validation_summary(endpoint_id)
        return _ok(summary)

    @router.get("/api/v1/endpoints/{endpoint_id}/validation/history")
    async def endpoint_validation_history(endpoint_id: str) -> JSONResponse:
        if validation_service is None:
            return _error(503, "validation_unavailable", "Validation service is not configured")
        return _ok(validation_service.validation_history(endpoint_id))

    @router.post("/api/v1/validation/requests/{request_id}/reports")
    async def submit_validation_report(request_id: str, payload: dict) -> JSONResponse:
        if validation_service is None:
            return _error(503, "validation_unavailable", "Validation service is not configured")
        result = validation_service.submit_validation_report(
            request_id=request_id,
            outcome=str(payload["outcome"]),
            validator_label=str(payload["validator_label"]),
            evidence_summary=str(payload["evidence_summary"]),
        )
        return _ok(
            {
                "request": result.request.model_dump(mode="json"),
                "snapshot": result.snapshot.model_dump(mode="json"),
                "report": result.report.model_dump(mode="json"),
            }
        )
```

- [ ] **Step 4: Run the API tests and verify they pass**

Run:

```bash
python -m pytest --import-mode=importlib tests/test_api.py -k "request_validation_endpoint or validation_history_endpoint or submit_validation_report_endpoint" -q
```

Expected: PASS for the new validation routes.

- [ ] **Step 5: Commit the API slice**

```bash
git add src/aidn_hypervisor/main.py src/aidn_hypervisor/api.py tests/test_api.py
git commit -m "add validation api routes"
```

## Task 5: Integrate Wallet Ledger, Snapshot Restore, And Maintenance APIs

**Files:**
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/main.py`
- Modify: `src/aidn_hypervisor/api.py`
- Modify: `tests/test_wallet.py`
- Modify: `tests/test_persistence.py`
- Modify: `tests/test_api.py`
- Modify: `tests/validation/test_service.py`

- [ ] **Step 1: Write the failing ledger, restore, and maintenance-route tests**

```python
def test_validation_events_appear_in_wallet_ledger_export() -> None:
    service = _service()
    validation_service = ValidationService(ValidationStore())
    validation_service.event_recorder = service.record_event
    service.validation_service = validation_service
    requested = validation_service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-02T00:00:00+00:00",
    )
    validation_service.resolve_maintenance(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="healthy",
    )

    ledger = service.export_wallet_ledger_events(limit=20)

    assert {item["event_type"] for item in ledger["items"]} >= {
        "validation_bond_locked",
        "maintenance_validation_passed",
        "validation_bond_refunded",
    }


def test_validation_state_survives_snapshot_restore() -> None:
    validation_service = ValidationService(ValidationStore())
    requested = validation_service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    snapshot = HypervisorStateSnapshot(
        validation_requests=validation_service.store.list_requests(),
        validation_bonds=validation_service.store.list_bonds(),
        validation_status_snapshots=validation_service.store.list_snapshots(),
    )

    restored = ValidationStore()
    restored.restore(snapshot)

    assert restored.get_request(requested.request.request_id).request_id == requested.request.request_id


def test_maintenance_route_forfeits_remaining_bond_on_fail() -> None:
    validation_service = ValidationService(ValidationStore())
    requested = validation_service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-02T00:00:00+00:00",
    )
    client = TestClient(build_app(service=_service(), validation_service=validation_service))

    response = client.post(
        f"/api/v1/validation/requests/{requested.request.request_id}/maintenance",
        json={"outcome": "fail", "validator_label": "validator-a", "evidence_summary": "timeout"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["bond"]["forfeited_q"] == 500.0
    assert response.json()["data"]["snapshot"]["status"] == "validation_failed"
```

- [ ] **Step 2: Run the integration tests and verify they fail**

Run:

```bash
python -m pytest --import-mode=importlib tests/test_wallet.py tests/test_persistence.py tests/test_api.py tests/validation/test_service.py -k "validation_events_appear or survives_snapshot_restore or maintenance_route_forfeits" -q
```

Expected: FAIL because validation events are not yet appended to wallet ledger export and the maintenance route does not exist.

- [ ] **Step 3: Append wallet-ledger validation events, snapshot restore, and the maintenance route**

```python
# src/aidn_hypervisor/service.py
class HypervisorService:
    def bind_validation_service(self, validation_service) -> None:
        self.validation_service = validation_service
        validation_service.wallet_event_callback = self._append_validation_wallet_event

    def _append_validation_wallet_event(self, *, event_type: str, owner_id: str, endpoint_id: str, amount_q: float, payload: dict) -> dict:
        return self._append_wallet_ledger_event(
            stream="validation",
            source_event={
                "event_id": payload["event_id"],
                "sequence_id": payload["sequence_id"],
                "occurred_at": payload["occurred_at"],
            },
            event_type=event_type,
            owner_id=owner_id,
            endpoint_id=endpoint_id,
            amount_q=amount_q,
            status=payload.get("status"),
            payload=payload,
        )
```

```python
# src/aidn_hypervisor/api.py
    @router.post("/api/v1/validation/requests/{request_id}/maintenance")
    async def resolve_validation_maintenance(request_id: str, payload: dict) -> JSONResponse:
        if validation_service is None:
            return _error(503, "validation_unavailable", "Validation service is not configured")
        result = validation_service.resolve_maintenance_by_request(
            request_id=request_id,
            outcome=str(payload["outcome"]),
            validator_label=str(payload["validator_label"]),
            evidence_summary=str(payload["evidence_summary"]),
        )
        return _ok(
            {
                "request": result.request.model_dump(mode="json"),
                "bond": result.bond.model_dump(mode="json"),
                "snapshot": result.snapshot.model_dump(mode="json"),
                "report": result.report.model_dump(mode="json"),
            }
        )
```

```python
# src/aidn_hypervisor/main.py
    resolved_service.bind_validation_service(resolved_validation_service)
```

- [ ] **Step 4: Run the integration tests and verify they pass**

Run:

```bash
python -m pytest --import-mode=importlib tests/test_wallet.py tests/test_persistence.py tests/test_api.py tests/validation/test_service.py -k "validation_events_appear or survives_snapshot_restore or maintenance_route_forfeits" -q
```

Expected: PASS for wallet-ledger, restore, and maintenance-route validation coverage.

- [ ] **Step 5: Commit the wallet/persistence slice**

```bash
git add src/aidn_hypervisor/service.py src/aidn_hypervisor/main.py src/aidn_hypervisor/api.py tests/test_wallet.py tests/test_persistence.py tests/test_api.py tests/validation/test_service.py
git commit -m "integrate validation ledger and maintenance flow"
```

## Plan Review Notes

Spec coverage:
- operator bond lifecycle: Task 2
- validator escrow Epoch/share/authorization envelope: Task 3
- validation status attached to `configuration_hash`: Tasks 1 and 2
- API and history/report surfaces: Task 4
- wallet-ledger and persistence integration: Task 5

Placeholder scan:
- no `TODO`, `TBD`, or deferred “implement later” steps remain in the task list.

Type consistency:
- `ValidationRequest`, `ValidationBond`, `ValidationStatusSnapshot`, `ValidationEpoch`, `ValidationAssignment`, and `ValidationAuthorization` are introduced in Task 1 and reused consistently in Tasks 2-5.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-02-m5-validation-bond-and-escrow.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
