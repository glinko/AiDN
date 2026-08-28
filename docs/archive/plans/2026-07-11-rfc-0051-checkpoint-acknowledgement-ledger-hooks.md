# RFC-0051 Checkpoint Acknowledgement And Ledger Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a session-first accounting spine with report/acknowledgement chains, a deterministic `Last Accepted Checkpoint`, explicit acknowledgement-timeout handling, dedicated session accounting APIs, and replay-safe ledger hooks.

**Architecture:** Extend the existing `accounting` and `sessions` models so session accounting state becomes a canonical chain plus checkpoint instead of latest snapshots only. Then thread that state through `SessionService`, expose it via `api.py`, and emit normalized accounting evidence into the existing local ledger-operation stream without implementing full forced settlement yet.

**Tech Stack:** Python, Pydantic, FastAPI, pytest, existing `aidn_hypervisor` session/service/api/ledger layers

---

## File Structure

### New Or Expanded Units

- `src/aidn_hypervisor/accounting/models.py`
  - add canonical hash helpers, checkpoint model, and validation for report/ack chain state.
- `src/aidn_hypervisor/sessions/models.py`
  - expand `EndpointSession` accounting fields from latest-snapshot storage to chain/checkpoint storage.
- `src/aidn_hypervisor/sessions/service.py`
  - split accounting writes into explicit `record_usage_report`, `record_usage_acknowledgement`, `expire_usage_acknowledgement`, and shared checkpoint rebuild/update helpers.
- `src/aidn_hypervisor/api.py`
  - add dedicated `/api/v1/sessions/{session_id}/usage-reports`, `/usage-acknowledgements`, and `/accounting` endpoints.
- `src/aidn_hypervisor/service.py`
  - normalize task/session accounting read models and wire task-driven local usage into the new two-step session accounting API.

### Existing Units To Reuse Without Broad Refactor

- `src/aidn_hypervisor/ledger/service.py`
  - keep the generic operation recorder as-is; use it from `SessionService`.
- `tests/accounting/test_models.py`
  - extend model-level coverage for checkpoint and hash continuity.
- `tests/sessions/test_service.py`
  - primary transition coverage for chain, ack, mismatch, timeout, and close baseline behavior.
- `tests/test_api.py`
  - API contract coverage for new session accounting endpoints.
- `tests/ledger/test_service.py`
  - verify session accounting transitions emit canonical ledger operations.
- `tests/test_wallet.py`
  - verify task-driven usage still populates a normalized `session_accounting` view.

### Scope Guardrails

- Do not redesign `LedgerOperationService` itself in this slice.
- Do not implement `SESSION_FORCE_SETTLE` calculation.
- Do not move remote-hypervisor protocol transport into this slice.
- Keep backward compatibility by preserving `last_usage_report_snapshot` and `last_usage_acknowledgement_snapshot` as derived summaries if existing readers still consume them.

### Task 1: Expand Accounting And Session Models

**Files:**
- Modify: `src/aidn_hypervisor/accounting/models.py:1-73`
- Modify: `src/aidn_hypervisor/sessions/models.py:6-42`
- Modify: `src/aidn_hypervisor/accounting/__init__.py:1-12`
- Test: `tests/accounting/test_models.py:1-69`

- [ ] **Step 1: Write the failing tests**

```python
from pydantic import ValidationError
import pytest

from aidn_hypervisor.accounting.models import (
    SessionAccountingCheckpoint,
    UsageAcknowledgement,
    UsageReport,
    usage_acknowledgement_hash,
    usage_report_hash,
)
from aidn_hypervisor.sessions.models import EndpointSession


def test_usage_report_hash_is_stable_for_equivalent_payloads() -> None:
    report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id="sess-1",
        endpoint_id="ep-1",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 12},
        measurement_sources={"input_tokens": "provider_api"},
        created_at="2026-07-11T00:00:00+00:00",
        signature="sig-1",
    )

    assert usage_report_hash(report) == usage_report_hash(report.model_copy(deep=True))


def test_session_accounting_checkpoint_rejects_accepted_sequence_ahead_of_report_head() -> None:
    with pytest.raises(ValidationError):
        SessionAccountingCheckpoint(
            last_report_sequence=1,
            last_report_hash="sha256:report-1",
            last_accepted_report_sequence=2,
            last_accepted_report_hash="sha256:report-2",
            last_accepted_usage_charged_q=4.0,
        )


def test_endpoint_session_accepts_ack_pending_and_force_settle_required_states() -> None:
    session = EndpointSession(
        session_id="sess-1",
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-1",
        status="active",
        created_at="2026-07-11T00:00:00+00:00",
        expires_at="2026-07-11T01:00:00+00:00",
        idle_deadline_at="2026-07-11T00:10:00+00:00",
        deposit_locked_q=20.0,
        queue_policy_snapshot="busy",
        accounting_status="ack_pending",
        accounting_checkpoint={
            "last_report_sequence": 1,
            "last_report_hash": "sha256:report-1",
            "ack_deadline_at": "2026-07-11T00:05:00+00:00",
        },
    )

    assert session.accounting_status == "ack_pending"
    assert session.accounting_checkpoint["last_report_sequence"] == 1


def test_usage_acknowledgement_hash_is_stable() -> None:
    ack = UsageAcknowledgement(
        session_id="sess-1",
        sequence=1,
        provider_report_hash="sha256:report-1",
        verification_status="accepted_unverified",
        signature="sig-ack-1",
    )

    assert usage_acknowledgement_hash(ack) == usage_acknowledgement_hash(ack.model_copy(deep=True))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/accounting/test_models.py -q`
Expected: FAIL with missing `SessionAccountingCheckpoint`, missing hash helpers, or invalid `EndpointSession` accounting-state support

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/accounting/models.py
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator

AccountingMode = Literal[
    "deterministic",
    "observable",
    "provider_metered",
    "fixed_price",
    "proxy_opaque",
]
VerificationStatus = Literal[
    "verified",
    "accepted_unverified",
    "statistically_plausible",
    "mismatch",
    "unable_to_verify",
    "unable_to_verify_upstream_usage",
]
AccountingValue = int | float | str | bool | None


def _canonical_json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def usage_report_hash(report: "UsageReport") -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(report.model_dump(mode='json')).encode('utf-8')).hexdigest()}"


def usage_acknowledgement_hash(ack: "UsageAcknowledgement") -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(ack.model_dump(mode='json')).encode('utf-8')).hexdigest()}"


class SessionAccountingCheckpoint(BaseModel):
    last_report_sequence: int | None = Field(default=None, ge=1)
    last_report_hash: str | None = None
    last_ack_sequence: int | None = Field(default=None, ge=1)
    last_ack_hash: str | None = None
    last_accepted_report_sequence: int | None = Field(default=None, ge=1)
    last_accepted_report_hash: str | None = None
    last_accepted_usage_charged_q: float = Field(default=0.0, ge=0.0)
    mismatch_open: bool = False
    ack_deadline_at: str | None = None

    @model_validator(mode="after")
    def _validate_checkpoint(self):
        if (
            self.last_report_sequence is not None
            and self.last_accepted_report_sequence is not None
            and self.last_accepted_report_sequence > self.last_report_sequence
        ):
            raise ValueError("accepted checkpoint cannot advance beyond the report head")
        if self.last_accepted_report_sequence is None and self.last_accepted_report_hash is not None:
            raise ValueError("accepted report hash requires accepted report sequence")
        if self.last_ack_sequence is None and self.last_ack_hash is not None:
            raise ValueError("ack hash requires ack sequence")
        return self
```

```python
# src/aidn_hypervisor/sessions/models.py
SessionAccountingStatus = Literal["open", "ack_pending", "mismatch", "force_settle_required"]


class EndpointSession(BaseModel):
    ...
    accounting_contract_snapshot: dict = Field(default_factory=dict)
    usage_report_chain: list[dict] = Field(default_factory=list)
    usage_acknowledgement_chain: list[dict] = Field(default_factory=list)
    accounting_checkpoint: dict = Field(default_factory=dict)
    last_usage_report_snapshot: dict = Field(default_factory=dict)
    last_usage_acknowledgement_snapshot: dict = Field(default_factory=dict)
    accounting_status: SessionAccountingStatus = "open"
    last_accepted_report_sequence: int | None = Field(default=None, ge=1)
    last_accepted_usage_charged_q: float = Field(default=0.0, ge=0.0)
    ...
```

```python
# src/aidn_hypervisor/accounting/__init__.py
from aidn_hypervisor.accounting.models import (
    AccountingContract,
    AccountingMode,
    AccountingUnitContract,
    SessionAccountingCheckpoint,
    UsageAcknowledgement,
    UsageReport,
    VerificationStatus,
    usage_acknowledgement_hash,
    usage_report_hash,
)

__all__ = [
    "AccountingContract",
    "AccountingMode",
    "AccountingUnitContract",
    "SessionAccountingCheckpoint",
    "UsageAcknowledgement",
    "UsageReport",
    "VerificationStatus",
    "usage_acknowledgement_hash",
    "usage_report_hash",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/accounting/test_models.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/accounting/__init__.py src/aidn_hypervisor/accounting/models.py src/aidn_hypervisor/sessions/models.py tests/accounting/test_models.py
git commit -m "feat: add session accounting checkpoint models"
```

### Task 2: Refactor SessionService Into Report, Ack, Timeout, And Close-Baseline Transitions

**Files:**
- Modify: `src/aidn_hypervisor/sessions/service.py:17-47`
- Modify: `src/aidn_hypervisor/sessions/service.py:101-199`
- Modify: `src/aidn_hypervisor/sessions/service.py:213-347`
- Modify: `src/aidn_hypervisor/sessions/service.py:474-488`
- Test: `tests/sessions/test_service.py:279-375`

- [ ] **Step 1: Write the failing tests**

```python
from datetime import datetime, timedelta, timezone

from aidn_hypervisor.accounting.models import UsageAcknowledgement, UsageReport


def test_record_usage_report_moves_session_to_ack_pending() -> None:
    service = _session_service()
    opened = _open_session(service)
    report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id=opened.session.endpoint_id,
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 20},
        measurement_sources={"input_tokens": "provider_api"},
        created_at="2026-07-11T00:00:00+00:00",
        signature="sig-1",
    )

    updated = service.record_usage_report(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )

    assert updated.accounting_status == "ack_pending"
    assert updated.accounting_checkpoint["last_report_sequence"] == 1
    assert updated.accounting_checkpoint["last_accepted_report_sequence"] is None


def test_record_usage_acknowledgement_advances_last_accepted_checkpoint() -> None:
    service = _session_service()
    opened = _open_session(service)
    report = _usage_report(opened.session, sequence=1)
    pending = service.record_usage_report(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )
    ack = UsageAcknowledgement(
        session_id=opened.session.session_id,
        sequence=1,
        provider_report_hash=pending.accounting_checkpoint["last_report_hash"],
        verification_status="accepted_unverified",
        signature="sig-ack-1",
    )

    updated = service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement=ack.model_dump(mode="json"),
        accepted_charge_q=6.5,
    )

    assert updated.accounting_status == "open"
    assert updated.last_accepted_report_sequence == 1
    assert updated.accounting_checkpoint["last_accepted_usage_charged_q"] == 6.5


def test_ack_timeout_marks_session_force_settle_required_without_advancing_baseline() -> None:
    service = _session_service()
    opened = _open_session(service)
    report = _usage_report(opened.session, sequence=1)
    pending = service.record_usage_report(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=1,
    )

    expired = service.expire_usage_acknowledgement(
        opened.session.session_id,
        now=datetime.now(timezone.utc) + timedelta(seconds=5),
    )

    assert expired.accounting_status == "force_settle_required"
    assert expired.last_accepted_report_sequence is None
    assert expired.accounting_checkpoint["last_report_hash"] == pending.accounting_checkpoint["last_report_hash"]


def test_close_session_preserves_last_accepted_checkpoint_when_newer_report_is_unacknowledged() -> None:
    service = _session_service()
    opened = _open_session(service)
    first = service.record_usage_report(
        opened.session.session_id,
        usage_report=_usage_report(opened.session, sequence=1).model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )
    accepted = service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement=UsageAcknowledgement(
            session_id=opened.session.session_id,
            sequence=1,
            provider_report_hash=first.accounting_checkpoint["last_report_hash"],
            verification_status="accepted_unverified",
            signature="sig-ack-1",
        ).model_dump(mode="json"),
        accepted_charge_q=4.0,
    )
    service.record_usage_report(
        opened.session.session_id,
        usage_report=_usage_report(opened.session, sequence=2, previous_report_hash=accepted.accounting_checkpoint["last_accepted_report_hash"]).model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )

    closed = service.close_session(opened.session.session_id)

    assert closed.session.last_accepted_report_sequence == 1
    assert closed.settlement is not None
    assert closed.settlement.usage_charged_q == 4.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/sessions/test_service.py -k "usage_report or usage_acknowledgement or force_settle_required or preserves_last_accepted_checkpoint" -q`
Expected: FAIL because `SessionService` only exposes `record_usage_checkpoint()` and has no timeout-driven accounting transitions

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/sessions/service.py
from aidn_hypervisor.accounting.models import (
    SessionAccountingCheckpoint,
    UsageAcknowledgement,
    UsageReport,
    VerificationStatus,
    usage_acknowledgement_hash,
    usage_report_hash,
)


def _checkpoint_from_session(session: EndpointSession) -> SessionAccountingCheckpoint:
    payload = dict(session.accounting_checkpoint or {})
    if not payload:
        payload = {
            "last_accepted_report_sequence": session.last_accepted_report_sequence,
            "last_accepted_usage_charged_q": session.last_accepted_usage_charged_q,
        }
    return SessionAccountingCheckpoint.model_validate(payload)


def _replace_accounting_state(
    self,
    current: EndpointSession,
    *,
    report_chain: list[dict] | None = None,
    acknowledgement_chain: list[dict] | None = None,
    checkpoint: SessionAccountingCheckpoint,
    accounting_status: str,
) -> EndpointSession:
    latest_report = report_chain[-1] if report_chain else current.last_usage_report_snapshot
    latest_ack = acknowledgement_chain[-1] if acknowledgement_chain else current.last_usage_acknowledgement_snapshot
    updated = current.model_copy(
        update={
            "usage_report_chain": list(report_chain if report_chain is not None else current.usage_report_chain),
            "usage_acknowledgement_chain": list(
                acknowledgement_chain if acknowledgement_chain is not None else current.usage_acknowledgement_chain
            ),
            "accounting_checkpoint": checkpoint.model_dump(mode="json"),
            "last_usage_report_snapshot": dict(latest_report or {}),
            "last_usage_acknowledgement_snapshot": dict(latest_ack or {}),
            "accounting_status": accounting_status,
            "last_accepted_report_sequence": checkpoint.last_accepted_report_sequence,
            "last_accepted_usage_charged_q": checkpoint.last_accepted_usage_charged_q,
        }
    )
    self.store.save_session(updated)
    return updated


def record_usage_report(
    self,
    session_id: str,
    *,
    usage_report: dict,
    acknowledgement_timeout_seconds: int,
) -> EndpointSession:
    current = self.store.get_session(session_id)
    report = UsageReport.model_validate(usage_report)
    report_hash = usage_report_hash(report)
    checkpoint = _checkpoint_from_session(current)
    report_chain = list(current.usage_report_chain)

    if report_chain:
        head = report_chain[-1]
        if int(report.sequence) == int(head["sequence"]) and report_hash == head["report_hash"]:
            return current
        if int(report.sequence) != int(head["sequence"]) + 1:
            checkpoint.mismatch_open = True
            return _replace_accounting_state(self, current, checkpoint=checkpoint, accounting_status="mismatch")
        if report.previous_report_hash != head["report_hash"]:
            checkpoint.mismatch_open = True
            return _replace_accounting_state(self, current, checkpoint=checkpoint, accounting_status="mismatch")
    elif report.sequence != 1:
        checkpoint.mismatch_open = True
        return _replace_accounting_state(self, current, checkpoint=checkpoint, accounting_status="mismatch")

    report_payload = report.model_dump(mode="json") | {"report_hash": report_hash}
    report_chain.append(report_payload)
    checkpoint.last_report_sequence = report.sequence
    checkpoint.last_report_hash = report_hash
    checkpoint.mismatch_open = False
    checkpoint.ack_deadline_at = (
        datetime.now(timezone.utc) + timedelta(seconds=max(1, int(acknowledgement_timeout_seconds)))
    ).isoformat()
    updated = _replace_accounting_state(
        self,
        current,
        report_chain=report_chain,
        checkpoint=checkpoint,
        accounting_status="ack_pending",
    )
    self._emit(
        event_type="session.usage_report_recorded",
        message="session usage report recorded",
        details={"session_id": session_id, "report_id": report.report_id, "sequence": report.sequence, "report_hash": report_hash},
    )
    return updated


def record_usage_acknowledgement(
    self,
    session_id: str,
    *,
    usage_acknowledgement: dict,
    accepted_charge_q: float,
) -> EndpointSession:
    current = self.store.get_session(session_id)
    ack = UsageAcknowledgement.model_validate(usage_acknowledgement)
    checkpoint = _checkpoint_from_session(current)
    report_chain = list(current.usage_report_chain)
    if not report_chain:
        raise ValueError(f"cannot acknowledge usage without a report chain: {session_id}")
    head = report_chain[-1]
    if ack.provider_report_hash != head["report_hash"] or int(ack.sequence) != int(head["sequence"]):
        raise ValueError("usage acknowledgement does not match the current report head")

    ack_hash = usage_acknowledgement_hash(ack)
    acknowledgement_chain = list(current.usage_acknowledgement_chain)
    if acknowledgement_chain:
        last_ack = acknowledgement_chain[-1]
        if int(last_ack["sequence"]) == int(ack.sequence) and last_ack["ack_hash"] == ack_hash:
            return current

    acknowledgement_chain.append(ack.model_dump(mode="json") | {"ack_hash": ack_hash})
    checkpoint.last_ack_sequence = ack.sequence
    checkpoint.last_ack_hash = ack_hash
    checkpoint.ack_deadline_at = None

    next_status = "mismatch" if ack.verification_status == "mismatch" else "open"
    if ack.verification_status == "mismatch":
        checkpoint.mismatch_open = True
    else:
        checkpoint.mismatch_open = False
        checkpoint.last_accepted_report_sequence = ack.sequence
        checkpoint.last_accepted_report_hash = ack.provider_report_hash
        checkpoint.last_accepted_usage_charged_q = max(0.0, float(accepted_charge_q))

    updated = _replace_accounting_state(
        self,
        current,
        acknowledgement_chain=acknowledgement_chain,
        checkpoint=checkpoint,
        accounting_status=next_status,
    )
    self._emit(
        event_type="session.usage_acknowledgement_recorded",
        message="session usage acknowledgement recorded",
        details={"session_id": session_id, "sequence": ack.sequence, "verification_status": ack.verification_status, "ack_hash": ack_hash},
    )
    return updated


def expire_usage_acknowledgement(self, session_id: str, *, now: datetime | None = None) -> EndpointSession:
    current = self.store.get_session(session_id)
    checkpoint = _checkpoint_from_session(current)
    if current.accounting_status != "ack_pending" or not checkpoint.ack_deadline_at:
        return current
    if datetime.fromisoformat(checkpoint.ack_deadline_at) > (now or datetime.now(timezone.utc)):
        return current
    checkpoint.ack_deadline_at = None
    updated = _replace_accounting_state(
        self,
        current,
        checkpoint=checkpoint,
        accounting_status="force_settle_required",
    )
    self._emit(
        event_type="session.accounting_force_settlement_required",
        message="session accounting requires forced settlement",
        details={"session_id": session_id, "last_report_sequence": checkpoint.last_report_sequence},
    )
    return updated
```

```python
# src/aidn_hypervisor/sessions/service.py inside _settle_and_close_session payload
"usage_charged_q": (
    float(session.last_accepted_usage_charged_q)
    if session.last_accepted_report_sequence is not None
    else 0.0
),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/sessions/test_service.py -k "usage_report or usage_acknowledgement or force_settle_required or preserves_last_accepted_checkpoint" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/sessions/service.py tests/sessions/test_service.py
git commit -m "feat: add session accounting checkpoint transitions"
```

### Task 3: Expose Dedicated Session Accounting API And Normalize Read Models

**Files:**
- Modify: `src/aidn_hypervisor/api.py:1032-1098`
- Modify: `src/aidn_hypervisor/api.py:413-425`
- Modify: `src/aidn_hypervisor/service.py:4317-4440`
- Test: `tests/test_api.py`
- Test: `tests/test_wallet.py:434-458`

- [ ] **Step 1: Write the failing tests**

```python
def test_session_usage_report_endpoint_returns_ack_pending_checkpoint(client: TestClient) -> None:
    session_id = _open_paid_session(client)

    response = client.post(
        f"/api/v1/sessions/{session_id}/usage-reports",
        json={
            "report_id": "rep-1",
            "report_version": "0.1",
            "session_id": session_id,
            "endpoint_id": "endpoint-local",
            "pricing_version": "pricing-v1",
            "accounting_contract_version": "acct-v1",
            "accounting_modes": {"input_tokens": "provider_metered"},
            "sequence": 1,
            "cumulative_usage": {"input_tokens": 11},
            "measurement_sources": {"input_tokens": "provider_api"},
            "created_at": "2026-07-11T00:00:00+00:00",
            "signature": "sig-1",
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["session"]["accounting_status"] == "ack_pending"
    assert body["accounting"]["checkpoint"]["last_report_sequence"] == 1


def test_session_usage_acknowledgement_endpoint_advances_checkpoint(client: TestClient) -> None:
    session_id = _open_paid_session(client)
    report_hash = _submit_session_usage_report(client, session_id)

    response = client.post(
        f"/api/v1/sessions/{session_id}/usage-acknowledgements",
        json={
            "session_id": session_id,
            "sequence": 1,
            "provider_report_hash": report_hash,
            "verification_status": "accepted_unverified",
            "signature": "sig-ack-1",
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["session"]["last_accepted_report_sequence"] == 1
    assert body["accounting"]["checkpoint"]["last_accepted_report_hash"] == report_hash


def test_get_session_accounting_endpoint_returns_canonical_read_model(client: TestClient) -> None:
    session_id = _open_paid_session(client)
    _submit_session_usage_report(client, session_id)

    response = client.get(f"/api/v1/sessions/{session_id}/accounting")

    assert response.status_code == 200
    body = response.json()["data"]
    assert set(body.keys()) >= {"session_id", "status", "checkpoint", "report_head", "acknowledgement_head"}


def test_task_result_session_accounting_is_normalized_to_checkpoint_shape() -> None:
    service = _configured_service()
    result = _run_paid_session_task(service)

    assert set(result["session_accounting"].keys()) >= {"status", "checkpoint", "report_head", "acknowledgement_head"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api.py tests/test_wallet.py -k "session_accounting or usage_report_endpoint or usage_acknowledgement_endpoint or get_session_accounting" -q`
Expected: FAIL because the session accounting endpoints do not exist and task results still use the old ad hoc `session_accounting` shape

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/service.py
def _build_session_accounting_view(self, session) -> dict:
    checkpoint = dict(session.accounting_checkpoint or {})
    report_head = dict(session.last_usage_report_snapshot or {})
    acknowledgement_head = dict(session.last_usage_acknowledgement_snapshot or {})
    return {
        "session_id": session.session_id,
        "status": session.accounting_status,
        "checkpoint": checkpoint,
        "report_head": report_head,
        "acknowledgement_head": acknowledgement_head,
    }
```

```python
# src/aidn_hypervisor/service.py inside _record_session_usage_acknowledgement_for_task
updated_session = session_service.record_usage_report(
    str(session_id),
    usage_report=usage_report,
    acknowledgement_timeout_seconds=30,
)
updated_session = session_service.record_usage_acknowledgement(
    str(session_id),
    usage_acknowledgement={
        "session_id": str(session_id),
        "sequence": int(updated_session.accounting_checkpoint["last_report_sequence"]),
        "provider_report_hash": str(updated_session.accounting_checkpoint["last_report_hash"]),
        "verification_status": "accepted_unverified",
        "signature": f"local-ack:{usage_report['report_id']}",
    },
    accepted_charge_q=float(session_charge_result.deposit.consumed_q),
)
if isinstance(result, dict):
    result["usage_acknowledgement"] = dict(updated_session.last_usage_acknowledgement_snapshot)
    result["session_accounting"] = self._build_session_accounting_view(updated_session)
```

```python
# src/aidn_hypervisor/api.py
@router.post("/api/v1/sessions/{session_id}/usage-reports")
async def record_session_usage_report(session_id: str, payload: dict) -> JSONResponse:
    if session_service is None:
        return _error(503, "session_service_unavailable", "Session service is not configured")
    try:
        updated = session_service.record_usage_report(
            session_id,
            usage_report=payload,
            acknowledgement_timeout_seconds=30,
        )
    except KeyError:
        return _error(404, "session_not_found", f"Unknown session: {session_id}")
    except ValueError as error:
        return _error(409, "session_accounting_conflict", str(error))
    return _ok(
        {
            "session": updated.model_dump(mode="json"),
            "accounting": service._build_session_accounting_view(updated),
        }
    )


@router.post("/api/v1/sessions/{session_id}/usage-acknowledgements")
async def record_session_usage_acknowledgement(session_id: str, payload: dict) -> JSONResponse:
    if session_service is None:
        return _error(503, "session_service_unavailable", "Session service is not configured")
    try:
        updated = session_service.record_usage_acknowledgement(
            session_id,
            usage_acknowledgement=payload,
            accepted_charge_q=float(
                session_service.get_session(session_id).deposit.consumed_q
            ),
        )
    except KeyError:
        return _error(404, "session_not_found", f"Unknown session: {session_id}")
    except ValueError as error:
        return _error(409, "session_accounting_conflict", str(error))
    return _ok(
        {
            "session": updated.model_dump(mode="json"),
            "accounting": service._build_session_accounting_view(updated),
        }
    )


@router.get("/api/v1/sessions/{session_id}/accounting")
async def get_session_accounting(session_id: str) -> JSONResponse:
    if session_service is None:
        return _error(503, "session_service_unavailable", "Session service is not configured")
    try:
        session = session_service.get_session(session_id).session
    except KeyError:
        return _error(404, "session_not_found", f"Unknown session: {session_id}")
    return _ok(service._build_session_accounting_view(session))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api.py tests/test_wallet.py -k "session_accounting or usage_report_endpoint or usage_acknowledgement_endpoint or get_session_accounting" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/api.py src/aidn_hypervisor/service.py tests/test_api.py tests/test_wallet.py
git commit -m "feat: expose session accounting endpoints"
```

### Task 4: Emit Replay-Safe Ledger Hooks For Accounting Evidence

**Files:**
- Modify: `src/aidn_hypervisor/sessions/service.py:172-198`
- Modify: `src/aidn_hypervisor/sessions/service.py:290-347`
- Modify: `src/aidn_hypervisor/main.py:84-90`
- Test: `tests/ledger/test_service.py`
- Test: `tests/ledger/test_api.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_usage_report_and_acknowledgement_record_canonical_ledger_operations() -> None:
    session_service, service = _ledger_bound_session_service()
    opened = _open_session(session_service)

    pending = session_service.record_usage_report(
        opened.session.session_id,
        usage_report=_usage_report(opened.session, sequence=1).model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )
    session_service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement={
            "session_id": opened.session.session_id,
            "sequence": 1,
            "provider_report_hash": pending.accounting_checkpoint["last_report_hash"],
            "verification_status": "accepted_unverified",
            "signature": "sig-ack-1",
        },
        accepted_charge_q=4.0,
    )

    operation_types = [item["operation_type"] for item in service.list_ledger_operations()]

    assert "SESSION_USAGE_REPORT" in operation_types
    assert "SESSION_USAGE_ACKNOWLEDGEMENT" in operation_types
    assert "SESSION_CHECKPOINT_ACCEPT" in operation_types


def test_ack_timeout_records_force_settlement_required_operation() -> None:
    session_service, service = _ledger_bound_session_service()
    opened = _open_session(session_service)
    session_service.record_usage_report(
        opened.session.session_id,
        usage_report=_usage_report(opened.session, sequence=1).model_dump(mode="json"),
        acknowledgement_timeout_seconds=1,
    )

    session_service.expire_usage_acknowledgement(
        opened.session.session_id,
        now=datetime.now(timezone.utc) + timedelta(seconds=5),
    )

    operation = service.list_ledger_operations()[-1]
    assert operation["operation_type"] == "SESSION_ACCOUNTING_FORCE_SETTLE_REQUIRED"
    assert operation["payload"]["session_id"] == opened.session.session_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/ledger/test_service.py -k "USAGE_REPORT or USAGE_ACKNOWLEDGEMENT or FORCE_SETTLE_REQUIRED" -q`
Expected: FAIL because `SessionService` does not currently emit accounting-specific ledger operations

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/sessions/service.py
def _record_accounting_operation(
    self,
    *,
    operation_type: str,
    session: EndpointSession,
    payload: dict,
    emitted_events: list[str],
) -> None:
    if self.operation_recorder is None:
        return
    self.operation_recorder(
        operation_type=operation_type,
        origin_type="multi_party",
        fee_class="session",
        initiator_id=session.session_id,
        fee_payer=session.client_wallet,
        payload=payload,
        created_at=datetime.now(timezone.utc).isoformat(),
        emitted_events=emitted_events,
    )
```

```python
# src/aidn_hypervisor/sessions/service.py inside record_usage_report
self._record_accounting_operation(
    operation_type="SESSION_USAGE_REPORT",
    session=updated,
    payload={
        "session_id": session_id,
        "endpoint_id": updated.endpoint_id,
        "sequence": report.sequence,
        "report_hash": report_hash,
        "previous_report_hash": report.previous_report_hash,
        "accounting_contract_version": report.accounting_contract_version,
        "accepted_checkpoint_sequence": checkpoint.last_accepted_report_sequence,
    },
    emitted_events=["SessionUsageReportRecorded"],
)
```

```python
# src/aidn_hypervisor/sessions/service.py inside record_usage_acknowledgement
self._record_accounting_operation(
    operation_type="SESSION_USAGE_ACKNOWLEDGEMENT",
    session=updated,
    payload={
        "session_id": session_id,
        "endpoint_id": updated.endpoint_id,
        "sequence": ack.sequence,
        "report_hash": ack.provider_report_hash,
        "ack_hash": ack_hash,
        "verification_status": ack.verification_status,
        "accepted_checkpoint_sequence": checkpoint.last_accepted_report_sequence,
        "accepted_usage_charged_q": checkpoint.last_accepted_usage_charged_q,
    },
    emitted_events=["SessionUsageAcknowledged"],
)
if ack.verification_status != "mismatch":
    self._record_accounting_operation(
        operation_type="SESSION_CHECKPOINT_ACCEPT",
        session=updated,
        payload={
            "session_id": session_id,
            "sequence": ack.sequence,
            "report_hash": ack.provider_report_hash,
            "accepted_usage_charged_q": checkpoint.last_accepted_usage_charged_q,
        },
        emitted_events=["SessionLastAcceptedCheckpointAdvanced"],
    )
```

```python
# src/aidn_hypervisor/sessions/service.py inside expire_usage_acknowledgement
self._record_accounting_operation(
    operation_type="SESSION_ACCOUNTING_FORCE_SETTLE_REQUIRED",
    session=updated,
    payload={
        "session_id": session_id,
        "endpoint_id": updated.endpoint_id,
        "last_report_sequence": checkpoint.last_report_sequence,
        "last_report_hash": checkpoint.last_report_hash,
        "accepted_checkpoint_sequence": checkpoint.last_accepted_report_sequence,
    },
    emitted_events=["SessionAccountingForceSettlementRequired"],
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/ledger/test_service.py -k "USAGE_REPORT or USAGE_ACKNOWLEDGEMENT or FORCE_SETTLE_REQUIRED" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/sessions/service.py src/aidn_hypervisor/main.py tests/ledger/test_service.py tests/ledger/test_api.py
git commit -m "feat: record session accounting ledger operations"
```

### Task 5: Tighten Conflict Cases, Compatibility, And End-To-End Coverage

**Files:**
- Modify: `tests/sessions/test_service.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_wallet.py`
- Modify: `src/aidn_hypervisor/service.py:4274-4440`
- Modify: `src/aidn_hypervisor/sessions/service.py:290-347`

- [ ] **Step 1: Write the failing tests**

```python
def test_duplicate_identical_usage_report_is_idempotent() -> None:
    service = _session_service()
    opened = _open_session(service)
    report = _usage_report(opened.session, sequence=1)

    first = service.record_usage_report(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )
    second = service.record_usage_report(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )

    assert len(second.usage_report_chain) == 1
    assert second.accounting_checkpoint["last_report_hash"] == first.accounting_checkpoint["last_report_hash"]


def test_conflicting_same_sequence_report_sets_mismatch() -> None:
    service = _session_service()
    opened = _open_session(service)
    service.record_usage_report(
        opened.session.session_id,
        usage_report=_usage_report(opened.session, sequence=1, cumulative_usage={"input_tokens": 10}).model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )

    mismatched = service.record_usage_report(
        opened.session.session_id,
        usage_report=_usage_report(opened.session, sequence=1, cumulative_usage={"input_tokens": 99}).model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )

    assert mismatched.accounting_status == "mismatch"


def test_usage_ack_endpoint_returns_409_for_non_head_report_hash(client: TestClient) -> None:
    session_id = _open_paid_session(client)
    _submit_session_usage_report(client, session_id)

    response = client.post(
        f"/api/v1/sessions/{session_id}/usage-acknowledgements",
        json={
            "session_id": session_id,
            "sequence": 1,
            "provider_report_hash": "sha256:not-the-current-head",
            "verification_status": "accepted_unverified",
            "signature": "sig-ack-bad",
        },
    )

    assert response.status_code == 409
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/sessions/test_service.py tests/test_api.py tests/test_wallet.py -k "idempotent or conflicting_same_sequence or non_head_report_hash or session_accounting" -q`
Expected: FAIL because duplicate/conflicting chain behavior and normalized compatibility paths are not fully enforced yet

- [ ] **Step 3: Write minimal implementation**

```python
# src/aidn_hypervisor/sessions/service.py inside record_usage_report
if report_chain:
    head = report_chain[-1]
    if int(report.sequence) == int(head["sequence"]):
        if report_hash == head["report_hash"]:
            return current
        checkpoint.mismatch_open = True
        updated = _replace_accounting_state(
            self,
            current,
            checkpoint=checkpoint,
            accounting_status="mismatch",
        )
        self._emit(
            event_type="session.accounting_mismatch_recorded",
            message="session accounting mismatch recorded",
            details={"session_id": session_id, "sequence": report.sequence, "report_hash": report_hash},
        )
        return updated
```

```python
# src/aidn_hypervisor/service.py inside task-result compatibility path
if isinstance(result, dict):
    result["session_accounting"] = self._build_session_accounting_view(updated_session)
    result["usage_acknowledgement"] = dict(updated_session.last_usage_acknowledgement_snapshot)
    result["usage_report"] = dict(updated_session.last_usage_report_snapshot)
```

- [ ] **Step 4: Run focused and full verification**

Run: `python -m pytest tests/sessions/test_service.py tests/test_api.py tests/test_wallet.py -k "idempotent or conflicting_same_sequence or non_head_report_hash or session_accounting" -q`
Expected: PASS

Run: `python -m pytest`
Expected: PASS for the full repository test suite

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/sessions/service.py src/aidn_hypervisor/service.py tests/sessions/test_service.py tests/test_api.py tests/test_wallet.py
git commit -m "test: harden session accounting chain conflicts"
```

## Self-Review

### Spec Coverage

- Report chain and acknowledgement chain: covered by Tasks 1 and 2.
- Explicit `Last Accepted Checkpoint`: covered by Tasks 1 and 2.
- Acknowledgement timeout and `force_settle_required`: covered by Task 2.
- Dedicated API surface: covered by Task 3.
- Replay-safe ledger hooks: covered by Task 4.
- Compatibility and idempotency hardening: covered by Task 5.

No major spec gaps remain for this slice.

### Placeholder Scan

- No `TBD`, `TODO`, or “implement later” placeholders remain.
- Every code-changing step includes explicit code.
- Every run step includes an exact command and expected outcome.

### Type Consistency

- `SessionAccountingCheckpoint` is introduced once in Task 1 and reused consistently.
- `record_usage_report`, `record_usage_acknowledgement`, and `expire_usage_acknowledgement` are named consistently across Tasks 2-5.
- `force_settle_required` is used consistently as the post-timeout accounting state.
