# Session Contract Object Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist an immutable `session_contract` Registry Object at session open time and bind `SESSION_OPEN` / `SESSION_SETTLE` evidence plus session/API reads to that same contract reference.

**Architecture:** Extend `SessionService` rather than building a new registry subsystem. The service will derive one canonical session-contract payload, persist it through the existing standalone `RegistryService` object store, store explicit object references on `EndpointSession`, and reuse those references in ledger payloads and session/operator reads.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, pytest, existing `SessionService`, `RegistryService`, and Hypervisor ledger/event plumbing.

---

## File Structure

- Modify `src/aidn_hypervisor/sessions/models.py`
  - Add explicit `session_contract_object_*` fields on `EndpointSession`.
- Modify `src/aidn_hypervisor/sessions/service.py`
  - Add canonical payload helpers, registry-object persistence, and session/ledger propagation.
- Modify `src/aidn_hypervisor/main.py`
  - Build one shared default `RegistryService` and wire it into both API routes and the default `SessionService`.
- Modify `tests/sessions/test_service.py`
  - Add session-open persistence and restart-stable contract-object coverage.
- Modify `tests/ledger/test_service.py`
  - Extend ledger payload assertions for `SESSION_OPEN` / `SESSION_SETTLE`.
- Modify `tests/test_api.py`
  - Add API coverage for session detail/list references and operator registry object access to stored `session_contract` objects.
- Modify `ROADMAP.md`
  - Mark session contracts as first-class registry-backed objects once implemented.
- Modify `docs/superpowers/specs/2026-07-13-rfc-implementation-alignment-audit.md`
  - Update the RFC alignment row for `Session contract binding` and `Settlement evidence`.

## Task 1: Persist A Canonical Session Contract Object During Session Open

**Files:**
- Modify: `src/aidn_hypervisor/sessions/models.py`
- Modify: `src/aidn_hypervisor/sessions/service.py`
- Test: `tests/sessions/test_service.py`

- [ ] **Step 1: Write the failing Session persistence tests**

Add these tests in `tests/sessions/test_service.py` after the existing marketplace-contract session tests:

```python
from pathlib import Path

from aidn_hypervisor.registry_service import RegistryService
```

```python
def test_open_session_persists_session_contract_registry_object(tmp_path: Path) -> None:
    registry = RegistryService(snapshot_path=tmp_path / "registry-objects.json")
    service = SessionService(SessionStore(), registry_service=registry)
    contract = AccountingContract(
        contract_version="acct-v1",
        capability_id="llm.chat",
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
        advertisement_id="adv-ep-1-v1",
        offer_id="offer-public",
        pricing_policy_hash="sha256:pricing-v1",
    )

    assert opened.session.session_contract_object_id.startswith("sha256:")
    assert opened.session.session_contract_object_version == "session-contract.v1"
    assert opened.session.session_contract_namespace == "session"
    assert opened.session.session_contract_hash.startswith("sha256:")

    stored = registry.get_registry_object(
        opened.session.session_contract_object_id,
        include_payload=True,
    )

    assert stored["object_type"] == "session_contract"
    assert stored["object_version"] == "session-contract.v1"
    assert stored["namespace"] == "session"
    assert stored["payload_hash"] == opened.session.session_contract_hash
    assert stored["payload"]["session_id"] == opened.session.session_id
    assert stored["payload"]["advertisement_id"] == "adv-ep-1-v1"
    assert stored["payload"]["offer_id"] == "offer-public"
    assert (
        stored["payload"]["accounting_contract_object_id"]
        == opened.session.accounting_contract_object_id
    )
```

```python
def test_open_session_reuses_persisted_session_contract_object_after_registry_restart(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "registry-objects.json"
    contract = AccountingContract(
        contract_version="acct-v1",
        capability_id="llm.chat",
        pricing_version="pricing-v1",
        billable_units=[],
        checkpoint_policy="per_request",
        maximum_request_charge=25.0,
    )
    first_registry = RegistryService(snapshot_path=snapshot_path)
    service = SessionService(SessionStore(), registry_service=first_registry)

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
        accounting_contract=contract.model_dump(mode="json"),
        advertisement_id="adv-ep-1-v1",
        offer_id="offer-public",
        pricing_policy_hash="sha256:pricing-v1",
    )

    restarted_registry = RegistryService(snapshot_path=snapshot_path)
    fetched = restarted_registry.get_registry_object(
        opened.session.session_contract_object_id,
        include_payload=True,
    )

    assert fetched["payload_hash"] == opened.session.session_contract_hash
    assert fetched["payload"]["session_id"] == opened.session.session_id
    assert fetched["payload"]["deposit_locked_q"] == 10.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```powershell
python -m pytest tests\sessions\test_service.py::test_open_session_persists_session_contract_registry_object tests\sessions\test_service.py::test_open_session_reuses_persisted_session_contract_object_after_registry_restart -q
```

Expected: fail because `SessionService` does not accept `registry_service` and `EndpointSession` does not expose `session_contract_object_*` fields.

- [ ] **Step 3: Implement canonical session-contract persistence**

In `src/aidn_hypervisor/sessions/models.py`, add explicit references on `EndpointSession` next to the existing accounting-contract references:

```python
    session_contract_object_id: str | None = None
    session_contract_object_version: str | None = None
    session_contract_namespace: str | None = None
```

In `src/aidn_hypervisor/sessions/service.py`, add the new import:

```python
from aidn_hypervisor.registry_service import RegistryService
```

Update `SessionService.__init__` so the session domain can persist to a shared registry store:

```python
    def __init__(
        self,
        store,
        event_recorder=None,
        operation_recorder=None,
        network_fee_q: float = 0.01,
        registry_service: RegistryService | None = None,
    ) -> None:
        self.store = store
        self.event_recorder = event_recorder
        self.operation_recorder = operation_recorder
        self.network_fee_q = max(0.0, float(network_fee_q))
        self.registry_service = registry_service or RegistryService()
```

Add canonical helpers above `open_session()`:

```python
def _registry_object_id(*, object_type: str, object_version: str, payload_hash: str) -> str:
    return _hash_payload(
        {
            "object_type": object_type,
            "object_version": object_version,
            "payload_hash": payload_hash,
        }
    )
```

```python
    def _session_contract_payload(
        self,
        *,
        session_id: str,
        endpoint_id: str,
        client_wallet: str,
        provider_wallet: str,
        node_id: str,
        deposit_q: float,
        advertisement_id: str | None,
        offer_id: str | None,
        pricing_policy_hash: str | None,
        accounting_contract_hash: str,
        accounting_contract_snapshot: dict,
        session_policy_snapshot: dict,
        accepted_at: str,
    ) -> dict:
        return {
            "session_id": session_id,
            "endpoint_id": endpoint_id,
            "client_wallet": client_wallet,
            "provider_wallet": provider_wallet,
            "node_id": node_id,
            "deposit_locked_q": deposit_q,
            "advertisement_id": advertisement_id,
            "offer_id": offer_id,
            "pricing_policy_hash": pricing_policy_hash,
            "accounting_contract_hash": accounting_contract_hash,
            "accounting_contract_object_id": accounting_contract_snapshot.get(
                "registry_object_id"
            ),
            "accounting_contract_object_version": accounting_contract_snapshot.get(
                "registry_object_version"
            ),
            "accounting_contract_namespace": accounting_contract_snapshot.get(
                "registry_namespace"
            ),
            "session_policy_snapshot": session_policy_snapshot,
            "accepted_at": accepted_at,
            "session_contract_version": "session-contract.v1",
        }
```

```python
    def _persist_session_contract_object(
        self,
        *,
        payload: dict,
        source_reference: str,
    ) -> dict:
        payload_hash = _hash_payload(payload)
        return self.registry_service.upsert_registry_object(
            {
                "object_id": _registry_object_id(
                    object_type="session_contract",
                    object_version="session-contract.v1",
                    payload_hash=payload_hash,
                ),
                "object_type": "session_contract",
                "object_version": "session-contract.v1",
                "namespace": "session",
                "payload_hash": payload_hash,
                "payload_encoding": "canonical_json",
                "source_reference": source_reference,
                "payload": payload,
            }
        )
```

Replace the current inline `session_contract_hash = _hash_payload({...})` block in `open_session()` with:

```python
        session_contract_payload = self._session_contract_payload(
            session_id=session_id,
            endpoint_id=endpoint_id,
            client_wallet=client_wallet,
            provider_wallet=provider_wallet,
            node_id=node_id,
            deposit_q=deposit_q,
            advertisement_id=advertisement_id,
            offer_id=offer_id,
            pricing_policy_hash=pricing_policy_hash,
            accounting_contract_hash=accepted_accounting_contract_hash,
            accounting_contract_snapshot=accounting_contract_snapshot,
            session_policy_snapshot=session_policy_snapshot,
            accepted_at=now.isoformat(),
        )
        session_contract_record = self._persist_session_contract_object(
            payload=session_contract_payload,
            source_reference=session_id,
        )
        session_contract_hash = str(session_contract_record["payload_hash"])
```

Then store the new references on `EndpointSession`:

```python
            session_contract_object_id=str(session_contract_record["object_id"]),
            session_contract_object_version=str(
                session_contract_record["object_version"]
            ),
            session_contract_namespace=str(session_contract_record["namespace"]),
```

- [ ] **Step 4: Run the targeted Session tests**

Run:

```powershell
python -m pytest tests\sessions\test_service.py::test_open_session_preserves_accounting_contract_snapshot tests\sessions\test_service.py::test_open_session_binds_accepted_marketplace_contract tests\sessions\test_service.py::test_open_session_persists_session_contract_registry_object tests\sessions\test_service.py::test_open_session_reuses_persisted_session_contract_object_after_registry_restart -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add src/aidn_hypervisor/sessions/models.py src/aidn_hypervisor/sessions/service.py tests/sessions/test_service.py
git commit -m "Persist session contract registry objects"
```

## Task 2: Bind Ledger Session Open And Settle Evidence To The Contract Object

**Files:**
- Modify: `src/aidn_hypervisor/sessions/service.py`
- Test: `tests/ledger/test_service.py`

- [ ] **Step 1: Extend the failing ledger test**

Update `tests/ledger/test_service.py::test_session_open_and_settle_record_canonical_ledger_operations` to require the contract object reference:

```python
    assert operations[0]["payload"]["session_contract_object_id"] == (
        opened.session.session_contract_object_id
    )
    assert operations[1]["payload"]["session_contract_object_id"] == (
        opened.session.session_contract_object_id
    )
```

Add one more assertion to prove the object hash and payload hash are not being mixed:

```python
    assert operations[0]["payload"]["session_contract_object_id"] != (
        opened.session.session_contract_hash
    )
```

- [ ] **Step 2: Run the ledger test to verify it fails**

Run:

```powershell
python -m pytest tests\ledger\test_service.py::test_session_open_and_settle_record_canonical_ledger_operations -q
```

Expected: fail on missing `session_contract_object_id` in one or both payloads.

- [ ] **Step 3: Add contract-object references to ledger payloads**

In `src/aidn_hypervisor/sessions/service.py`, update the `SESSION_OPEN` payload block:

```python
                payload={
                    "session_id": session.session_id,
                    "consumer_hypervisor_id": node_id,
                    "provider_hypervisor_id": node_id,
                    "endpoint_id": endpoint_id,
                    "advertisement_id": session.advertisement_id,
                    "offer_id": session.offer_id,
                    "pricing_policy_hash": session.pricing_policy_hash,
                    "session_policy_hash": f"sha256:{session_policy_hash}",
                    "accounting_contract_hash": session.accounting_contract_hash,
                    "session_contract_hash": session.session_contract_hash,
                    "session_contract_object_id": session.session_contract_object_id,
                    "deposit_amount": deposit_q,
                    "open_expiration": session.expires_at,
                },
```

Update the `SESSION_SETTLE` payload block inside `_settle_and_close_session(...)`:

```python
                payload={
                    "session_id": session.session_id,
                    "endpoint_id": session.endpoint_id,
                    "client_wallet": session.client_wallet,
                    "provider_wallet": session.provider_wallet,
                    "advertisement_id": session.advertisement_id,
                    "offer_id": session.offer_id,
                    "session_contract_hash": session.session_contract_hash,
                    "session_contract_object_id": session.session_contract_object_id,
                    "settlement_evidence_root": settlement_evidence_root,
                    "charged_q": settlement.charged_q,
                    "refunded_q": settlement.refunded_q,
                    "payout_q": settlement.payout_q,
                    "last_accepted_report_sequence": session.last_accepted_report_sequence,
                },
```

- [ ] **Step 4: Run the targeted ledger regression**

Run:

```powershell
python -m pytest tests\ledger\test_service.py::test_session_open_and_settle_record_canonical_ledger_operations tests\ledger\test_service.py::test_session_accounting_report_and_acknowledgement_record_canonical_ledger_operations -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add src/aidn_hypervisor/sessions/service.py tests/ledger/test_service.py
git commit -m "Bind session ledger events to contract objects"
```

## Task 3: Share The Registry Store Across The App And Expose Contract References Through API Surfaces

**Files:**
- Modify: `src/aidn_hypervisor/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Add the failing API tests**

Add this session-detail assertion test to `tests/test_api.py` near the existing session accounting/detail coverage:

```python
def test_session_detail_exposes_session_contract_object_references() -> None:
    registry_service = RegistryService()
    session_service = SessionService(SessionStore(), registry_service=registry_service)
    service = _service(with_runtime=False, use_process_manager=True)
    client = TestClient(
        build_app(
            service=service,
            registry_service=registry_service,
            session_service=session_service,
        )
    )

    opened = session_service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy={
            "minimum_deposit": 10.0,
            "recommended_deposit": 25.0,
            "idle_fee_per_minute": 1.0,
            "idle_timeout_seconds": 600,
            "max_concurrent_sessions": 1,
            "maximum_session_duration_seconds": 3600,
            "queue_policy": "busy",
            "minimum_session_fee": 2.0,
        },
        accounting_contract={
            "contract_version": "acct-v1",
            "pricing_version": "pricing-v1",
        },
        advertisement_id="adv-ep-1-v1",
        offer_id="offer-public",
        pricing_policy_hash="sha256:pricing-v1",
    )

    response = client.get(f"/api/v1/sessions/{opened.session.session_id}")

    assert response.status_code == 200
    session_payload = response.json()["data"]["session"]
    assert session_payload["session_contract_object_id"] == opened.session.session_contract_object_id
    assert session_payload["session_contract_object_version"] == "session-contract.v1"
    assert session_payload["session_contract_namespace"] == "session"
```

Add this operator-registry visibility test nearby the existing `/operators/registry/objects` tests:

```python
def test_operator_registry_objects_endpoint_lists_session_contract_objects() -> None:
    registry_service = RegistryService()
    session_service = SessionService(SessionStore(), registry_service=registry_service)
    service = _service(with_runtime=False, use_process_manager=True)
    session_service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id=service.node_id,
        deposit_q=10.0,
        session_policy={
            "minimum_deposit": 10.0,
            "recommended_deposit": 25.0,
            "idle_fee_per_minute": 1.0,
            "idle_timeout_seconds": 600,
            "max_concurrent_sessions": 1,
            "maximum_session_duration_seconds": 3600,
            "queue_policy": "busy",
            "minimum_session_fee": 2.0,
        },
        accounting_contract={
            "contract_version": "acct-v1",
            "pricing_version": "pricing-v1",
        },
        advertisement_id="adv-ep-1-v1",
        offer_id="offer-public",
        pricing_policy_hash="sha256:pricing-v1",
    )
    client = TestClient(
        build_app(
            service=service,
            registry_service=registry_service,
            session_service=session_service,
        )
    )

    response = client.get("/operators/registry/objects?include_payload=true")

    assert response.status_code == 200
    session_contract = next(
        item
        for item in response.json()["objects"]
        if item["object_type"] == "session_contract"
    )
    assert session_contract["namespace"] == "session"
    assert session_contract["payload"]["advertisement_id"] == "adv-ep-1-v1"
```

- [ ] **Step 2: Run the API tests to verify they fail**

Run:

```powershell
python -m pytest tests\test_api.py::test_session_detail_exposes_session_contract_object_references tests\test_api.py::test_operator_registry_objects_endpoint_lists_session_contract_objects -q
```

Expected: fail because the default app wiring does not yet guarantee a shared registry service for session-created objects.

- [ ] **Step 3: Wire one shared registry service through build_app and keep API fallback coherent**

In `src/aidn_hypervisor/main.py`, add a default registry builder:

```python
def _build_default_registry_service(
    *,
    state_store: FileStateStore | None = None,
) -> RegistryService:
    if state_store is None:
        return RegistryService()
    registry_snapshot_path = state_store.path.parent / "registry-objects.json"
    return RegistryService(snapshot_path=registry_snapshot_path)
```

In `build_app(...)`, resolve registry before the session service and make it shared:

```python
    resolved_registry_service = registry_service or _build_default_registry_service(
        state_store=state_store
    )
```

```python
    resolved_session_service = (
        session_service
        or _build_default_session_service(
            state_store=state_store,
            registry_service=resolved_registry_service,
        )
    )
    resolved_session_service.registry_service = resolved_registry_service
```

Update `_build_default_session_service(...)`:

```python
def _build_default_session_service(
    *,
    state_store: FileStateStore | None = None,
    registry_service: RegistryService | None = None,
) -> SessionService:
    if state_store is None:
        state_store = _default_state_store()
    return SessionService(
        SessionStore(state_store),
        registry_service=registry_service,
    )
```

Pass the resolved registry service into the API router:

```python
        build_api_router(
            resolved_service,
            registry_service=resolved_registry_service,
            endpoint_service=resolved_endpoint_service,
            endpoint_publication_service=resolved_endpoint_publication_service,
            remote_endpoint_service=resolved_remote_endpoint_service,
            session_service=resolved_session_service,
            validation_service=resolved_validation_service,
        )
```

- [ ] **Step 4: Run the API regression**

Run:

```powershell
python -m pytest tests\test_api.py::test_session_detail_exposes_session_contract_object_references tests\test_api.py::test_operator_registry_objects_endpoint_lists_session_contract_objects tests\test_api.py::test_operator_registry_object_endpoint_returns_object_by_id -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add src/aidn_hypervisor/main.py tests/test_api.py
git commit -m "Expose session contract objects through shared registry wiring"
```

## Task 4: Sync Roadmap And RFC Alignment Notes

**Files:**
- Modify: `ROADMAP.md`
- Modify: `docs/superpowers/specs/2026-07-13-rfc-implementation-alignment-audit.md`

- [ ] **Step 1: Update the roadmap wording**

In `ROADMAP.md`, replace the current session-contract gap wording with:

```markdown
- paid Session contracts now preserve accepted Marketplace identity through `advertisement_id`, optional `offer_id`, pricing/accounting hashes, deterministic `session_contract_hash`, and immutable `session_contract` Registry Object references shared by Session and Settlement evidence;
```

In the "What is still missing" section, tighten the gap to:

```markdown
- implementation of `RFC-0044` remains partial beyond the local MVP boundary:
  - accepted Session contracts persist as immutable local Registry Objects, with ordered amendment/version chains and portable contract exchange;
  - the exchange stages validated evidence but does not activate or overwrite a local Session;
  - authenticated network transport, distributed Contract acceptance and full checkpoint/dispute Forced Settlement semantics remain open.
```

- [ ] **Step 2: Update the RFC alignment audit**

In `docs/superpowers/specs/2026-07-13-rfc-implementation-alignment-audit.md`, update the `Session contract binding` row to:

```markdown
| Session contract binding | RFC-0044 | `EndpointSession` stores `advertisement_id`, optional `offer_id`, accounting contract references, deterministic `session_contract_hash`, immutable `session_contract` Registry Object references, and an ordered amendment/effective-terms chain. | Partial | Authenticated transport, authoritative cross-node activation and broader distributed Contract acceptance remain incomplete. |
```

Update the `Settlement evidence` row to:

```markdown
| Settlement evidence | RFC-0037, RFC-0060 | `SESSION_SETTLE` payloads now include accepted Advertisement/Offer identity, `session_contract_hash`, `session_contract_object_id`, settlement evidence roots, charged/refunded/payout values, and last accepted report sequence. | Partial | There is still no invoice object or broader network-visible settlement evidence object lifecycle beyond local ledger/event payloads. |
```

- [ ] **Step 3: Verify docs mention the new boundary cleanly**

Run:

```powershell
rg -n "session_contract_object_id|immutable `session_contract` Registry Object|RFC-0044" ROADMAP.md docs/superpowers/specs/2026-07-13-rfc-implementation-alignment-audit.md
```

Expected: both files mention the new session-contract object boundary and still describe the remaining gaps as partial.

- [ ] **Step 4: Commit**

```powershell
git add ROADMAP.md docs/superpowers/specs/2026-07-13-rfc-implementation-alignment-audit.md
git commit -m "Sync docs for session contract objects"
```

## Final Verification

- [ ] **Step 1: Run the focused regression suite**

Run:

```powershell
python -m pytest tests\sessions\test_service.py tests\ledger\test_service.py tests\test_api.py -q
```

Expected: all targeted tests pass.

- [ ] **Step 2: Run the full project suite**

Run:

```powershell
python -m pytest -q
```

Expected: full suite passes with no new failures.

- [ ] **Step 3: Run whitespace sanity check**

Run:

```powershell
git diff --check
```

Expected: no whitespace or patch-format errors.
