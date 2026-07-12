# RFC-0051 Accounting Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce the first executable `RFC-0051` protocol surface by adding canonical accounting models and attaching an accounting-contract snapshot to paid Sessions.

**Architecture:** Add a small `aidn_hypervisor.accounting` module for protocol models and a derivation helper that maps today’s provider `usage_contract` plus endpoint pricing/session data into a conservative `AccountingContract`. Thread that contract into session-open flow so every paid Session persists the commercial/accounting basis accepted at open time.

**Tech Stack:** Python, Pydantic, pytest, existing `aidn_hypervisor` session/service/api layers

---

### Task 1: Add Canonical Accounting Models

**Files:**
- Create: `src/aidn_hypervisor/accounting/__init__.py`
- Create: `src/aidn_hypervisor/accounting/models.py`
- Test: `tests/accounting/test_models.py`

- [ ] **Step 1: Write the failing tests**

```python
from pydantic import ValidationError
import pytest

from aidn_hypervisor.accounting.models import (
    AccountingContract,
    AccountingUnitContract,
    UsageAcknowledgement,
    UsageReport,
)


def test_accounting_contract_accepts_multiple_unit_modes() -> None:
    contract = AccountingContract(
        contract_version="acct-v1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        billable_units=[
            AccountingUnitContract(
                unit="input_tokens",
                mode="provider_metered",
                price=12.0,
                measurement_source="provider_api",
                verification_method="provider_report",
            ),
            AccountingUnitContract(
                unit="request_fee",
                mode="fixed_price",
                price=4.0,
                measurement_source="endpoint_policy",
                verification_method="fixed_contract",
            ),
        ],
        checkpoint_policy="per_request",
        maximum_request_charge=25.0,
    )

    assert contract.billable_units[0].mode == "provider_metered"
    assert contract.billable_units[1].mode == "fixed_price"


def test_usage_report_requires_positive_sequence() -> None:
    with pytest.raises(ValidationError):
        UsageReport(
            report_id="rep-1",
            report_version="0.1",
            session_id="sess-1",
            endpoint_id="ep-1",
            pricing_version="pricing-v1",
            accounting_contract_version="acct-v1",
            accounting_modes={"input_tokens": "provider_metered"},
            sequence=0,
            cumulative_usage={"input_tokens": 10},
            measurement_sources={"input_tokens": "provider_api"},
            created_at="2026-07-10T00:00:00+00:00",
            signature="sig-1",
        )


def test_usage_acknowledgement_tracks_verification_status() -> None:
    ack = UsageAcknowledgement(
        session_id="sess-1",
        sequence=2,
        provider_report_hash="sha256:abc",
        verification_status="accepted_unverified",
        consumer_measurements={"output_tokens": 120},
        signature="sig-ack",
    )

    assert ack.verification_status == "accepted_unverified"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/accounting/test_models.py -q`
Expected: FAIL with `ModuleNotFoundError` or missing model names from `aidn_hypervisor.accounting.models`

- [ ] **Step 3: Write minimal implementation**

```python
from typing import Literal

from pydantic import BaseModel, Field

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


class AccountingUnitContract(BaseModel):
    unit: str = Field(min_length=1)
    mode: AccountingMode
    price: float = Field(ge=0.0)
    measurement_source: str = Field(min_length=1)
    verification_method: str = Field(min_length=1)
    tolerance: str | None = None
    rounding: str | None = None


class AccountingContract(BaseModel):
    contract_version: str = Field(min_length=1)
    capability_id: str | None = None
    pricing_version: str = Field(min_length=1)
    billable_units: list[AccountingUnitContract] = Field(default_factory=list)
    checkpoint_policy: str = Field(min_length=1)
    maximum_unreported_usage: float | None = Field(default=None, ge=0.0)
    maximum_request_charge: float | None = Field(default=None, ge=0.0)
    failure_pricing_policy: str = "reject_unpriced_usage"


class UsageReport(BaseModel):
    report_id: str = Field(min_length=1)
    report_version: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    endpoint_id: str = Field(min_length=1)
    capability_id: str | None = None
    pricing_version: str = Field(min_length=1)
    accounting_contract_version: str = Field(min_length=1)
    accounting_modes: dict[str, AccountingMode] = Field(default_factory=dict)
    sequence: int = Field(ge=1)
    cumulative_usage: dict[str, int | float | str | bool | None] = Field(default_factory=dict)
    request_usage: list[dict] = Field(default_factory=list)
    measurement_sources: dict[str, str] = Field(default_factory=dict)
    estimated_usage: dict[str, int | float | str | bool | None] = Field(default_factory=dict)
    previous_report_hash: str | None = None
    created_at: str = Field(min_length=1)
    signature: str = Field(min_length=1)


class UsageAcknowledgement(BaseModel):
    session_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    provider_report_hash: str = Field(min_length=1)
    verification_status: VerificationStatus
    consumer_measurements: dict[str, int | float | str | bool | None] = Field(default_factory=dict)
    observations: dict[str, int | float | str | bool | None] = Field(default_factory=dict)
    signature: str = Field(min_length=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/accounting/test_models.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/accounting/__init__.py src/aidn_hypervisor/accounting/models.py tests/accounting/test_models.py
git commit -m "feat: add rfc-0051 accounting models"
```

### Task 2: Attach Accounting Contract Snapshot To Sessions

**Files:**
- Modify: `src/aidn_hypervisor/sessions/models.py`
- Modify: `src/aidn_hypervisor/sessions/service.py`
- Modify: `src/aidn_hypervisor/service.py`
- Modify: `src/aidn_hypervisor/endpoints/api.py`
- Test: `tests/sessions/test_service.py`
- Test: `tests/test_wallet.py`

- [ ] **Step 1: Write the failing tests**

```python
from aidn_hypervisor.accounting.models import AccountingContract


def test_open_session_preserves_accounting_contract_snapshot() -> None:
    service = _session_service()
    contract = AccountingContract(
        contract_version="acct-v1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        billable_units=[],
        checkpoint_policy="per_request",
        maximum_request_charge=25.0,
    )

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
        accounting_contract=contract.model_dump(mode="json"),
    )

    assert opened.session.accounting_contract_snapshot["contract_version"] == "acct-v1"
    assert opened.session.accounting_contract_snapshot["maximum_request_charge"] == 25.0
```

```python
def test_service_builds_provider_metered_accounting_contract_for_paid_endpoint() -> None:
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(update={"plugin_id": "fake-usage-metering"}),
    )
    endpoint_service = EndpointService(EndpointStore())
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="phi4-local",
            bundle_hash="bundle-hash-a",
            display_name="Paid Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            pricing={"billing_unit": "token", "input_price": 12.0, "output_price": 18.0, "fixed_price": 4.0},
            session={"minimum_deposit": 10.0, "recommended_deposit": 25.0},
        )
    )

    contract = service.accounting_contract_for_endpoint(created.endpoint)

    assert contract["contract_version"].startswith("acct-")
    assert {item["unit"] for item in contract["billable_units"]} >= {"input_tokens", "output_tokens"}
    assert any(item["mode"] == "provider_metered" for item in contract["billable_units"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/sessions/test_service.py tests/test_wallet.py -k "accounting_contract" -q`
Expected: FAIL because `open_session` lacks `accounting_contract` and `HypervisorService` lacks `accounting_contract_for_endpoint`

- [ ] **Step 3: Write minimal implementation**

```python
class EndpointSession(BaseModel):
    ...
    accounting_contract_snapshot: dict = Field(default_factory=dict)
```

```python
def open_session(..., accounting_contract: dict | None = None) -> SessionResult:
    ...
    session = EndpointSession(
        ...
        accounting_contract_snapshot=dict(accounting_contract or {}),
    )
```

```python
def accounting_contract_for_endpoint(self, endpoint) -> dict:
    bundle = self._get_bundle(endpoint.bundle_id)
    usage_contract = self._provider_usage_contract_for_bundle(bundle)
    billable_units = []
    if endpoint.pricing.input_price is not None:
        billable_units.append(...)
    if endpoint.pricing.output_price is not None:
        billable_units.append(...)
    if endpoint.pricing.fixed_price is not None:
        billable_units.append(...)
    if endpoint.session.idle_fee_per_minute > 0:
        billable_units.append(...)
    return AccountingContract(...).model_dump(mode="json")
```

```python
result = session_service.open_session(
    ...,
    accounting_contract=service.accounting_contract_for_endpoint(endpoint),
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/sessions/test_service.py tests/test_wallet.py -k "accounting_contract" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aidn_hypervisor/sessions/models.py src/aidn_hypervisor/sessions/service.py src/aidn_hypervisor/service.py src/aidn_hypervisor/endpoints/api.py tests/sessions/test_service.py tests/test_wallet.py
git commit -m "feat: attach accounting contracts to paid sessions"
```
