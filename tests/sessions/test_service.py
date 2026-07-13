import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aidn_hypervisor.accounting.models import (
    AccountingContract,
    UsageAcknowledgement,
    UsageReport,
)
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.sessions.models import ProxySessionBinding
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _canonical_registry_object_id(
    *,
    object_type: str,
    object_version: str,
    payload_hash: str,
) -> str:
    return _canonical_hash(
        {
            "object_type": object_type,
            "object_version": object_version,
            "payload_hash": payload_hash,
        }
    )


def _session_service() -> SessionService:
    return SessionService(SessionStore())


def _session_policy(**overrides):
    policy = {
        "minimum_deposit": 10.0,
        "recommended_deposit": 25.0,
        "idle_fee_per_minute": 1.0,
        "idle_timeout_seconds": 600,
        "max_concurrent_sessions": 1,
        "maximum_session_duration_seconds": 3600,
        "queue_policy": "busy",
        "minimum_session_fee": 2.0,
    }
    policy.update(overrides)
    return policy


def test_open_session_rejects_deposit_below_minimum() -> None:
    service = _session_service()

    with pytest.raises(ValueError, match="minimum deposit"):
        service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=9.0,
            session_policy=_session_policy(),
        )


def test_open_session_rejects_when_endpoint_slots_are_full_and_policy_is_busy() -> None:
    service = _session_service()
    policy = _session_policy(max_concurrent_sessions=1, queue_policy="busy")

    first = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=policy,
    )

    assert first.session.status == "active"
    assert first.session.reserved_slot_index == 0
    with pytest.raises(ValueError, match="busy"):
        service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-b",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=10.0,
            session_policy=policy,
        )


def test_close_session_releases_slot_for_next_waiting_session() -> None:
    service = _session_service()
    policy = _session_policy(max_concurrent_sessions=1, queue_policy="queue")

    first = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=policy,
    )
    second = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-b",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=policy,
    )

    closed = service.close_session(first.session.session_id)
    promoted = service.get_session(second.session.session_id)

    assert closed.session.status == "closed"
    assert promoted.session.status == "active"
    assert promoted.session.reserved_slot_index == 0


def test_close_session_applies_minimum_session_fee_when_no_requests_were_sent() -> None:
    service = _session_service()

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(minimum_session_fee=2.0),
    )

    closed = service.close_session(opened.session.session_id)

    assert closed.deposit.status == "released"
    assert closed.deposit.consumed_q == 2.01
    assert closed.deposit.refunded_q == 7.99
    assert closed.settlement is not None
    assert closed.settlement.no_request is True
    assert closed.settlement.network_fee_q == 0.01
    assert closed.settlement.charged_q == 2.01
    assert closed.settlement.refunded_q == 7.99


def test_close_session_refunds_remaining_balance_after_usage_charge() -> None:
    service = _session_service()

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(minimum_session_fee=2.0),
    )
    service.record_usage_charge(opened.session.session_id, amount_q=6.5)

    closed = service.close_session(opened.session.session_id)

    assert closed.deposit.status == "released"
    assert closed.deposit.consumed_q == 6.51
    assert closed.deposit.refunded_q == 13.49
    assert closed.settlement is not None
    assert closed.settlement.no_request is False
    assert closed.settlement.usage_charged_q == 6.5
    assert closed.settlement.network_fee_q == 0.01
    assert closed.settlement.charged_q == 6.51
    assert closed.settlement.refunded_q == 13.49


def test_record_usage_charge_rejects_charge_above_locked_deposit() -> None:
    service = _session_service()

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
    )

    with pytest.raises(ValueError, match="deposit"):
        service.record_usage_charge(opened.session.session_id, amount_q=11.0)


def test_sweep_idle_sessions_auto_closes_timed_out_session_with_idle_fee() -> None:
    service = _session_service()

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=30.0,
        session_policy=_session_policy(idle_fee_per_minute=1.0, idle_timeout_seconds=600),
    )
    service.record_usage_charge(opened.session.session_id, amount_q=6.0)
    service.store.save_session(
        service.get_session(opened.session.session_id).session.model_copy(
            update={
                "last_activity_at": "2026-07-01T00:00:00+00:00",
                "idle_deadline_at": "2026-07-01T00:10:00+00:00",
            }
        )
    )

    swept = service.sweep_idle_sessions(
        now=datetime(2026, 7, 1, 0, 10, 0, tzinfo=timezone.utc)
    )

    assert len(swept) == 1
    assert swept[0].session.close_reason == "idle_timeout"
    assert swept[0].settlement is not None
    assert swept[0].settlement.idle_fee_charged_q == 10.0
    assert swept[0].settlement.network_fee_q == 0.01
    assert swept[0].settlement.charged_q == 16.01
    assert swept[0].deposit.refunded_q == 13.99


def test_sweep_idle_sessions_keeps_no_request_minimum_fee_rule() -> None:
    service = _session_service()

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(
            minimum_session_fee=2.0,
            idle_fee_per_minute=1.0,
            idle_timeout_seconds=600,
        ),
    )
    service.store.save_session(
        opened.session.model_copy(
            update={
                "last_activity_at": "2026-07-01T00:00:00+00:00",
                "idle_deadline_at": "2026-07-01T00:10:00+00:00",
            }
        )
    )

    swept = service.sweep_idle_sessions(
        now=datetime(2026, 7, 1, 0, 10, 0, tzinfo=timezone.utc)
    )

    assert len(swept) == 1
    assert swept[0].settlement is not None
    assert swept[0].settlement.no_request is True
    assert swept[0].settlement.minimum_session_fee_q == 2.0
    assert swept[0].settlement.idle_fee_charged_q == 0.0
    assert swept[0].settlement.network_fee_q == 0.01
    assert swept[0].deposit.consumed_q == 2.01


def test_session_service_round_trips_proxy_session_binding() -> None:
    service = _session_service()
    binding = ProxySessionBinding(
        local_session_id="sess-local",
        remote_endpoint_id="ep-remote",
        remote_session_id="sess-remote",
        remote_node_id="node-remote",
        source_base_url="https://remote.example",
        status="active",
        opened_at="2026-07-02T00:00:00+00:00",
        close_status="not_requested",
    )

    service.save_proxy_session_binding(binding)

    assert service.get_proxy_session_binding("sess-local").remote_session_id == "sess-remote"


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
    assert opened.session.accounting_contract_object_id.startswith("sha256:")
    assert opened.session.accounting_contract_object_version == "acctobj.v1"
    assert opened.session.accounting_contract_namespace == "usage"


def test_open_session_binds_accepted_marketplace_contract() -> None:
    service = _session_service()
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

    assert opened.session.advertisement_id == "adv-ep-1-v1"
    assert opened.session.offer_id == "offer-public"
    assert opened.session.pricing_policy_hash == "sha256:pricing-v1"
    assert opened.session.accounting_contract_object_id.startswith("sha256:")
    assert opened.session.accounting_contract_object_version == "acctobj.v1"
    assert opened.session.accounting_contract_namespace == "usage"
    assert opened.session.accounting_contract_hash == opened.session.accounting_contract_snapshot["payload_hash"]
    assert opened.session.session_contract_hash.startswith("sha256:")
    assert opened.session.session_contract_hash != opened.session.accounting_contract_hash


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
    expected_payload_hash = _canonical_hash(stored["payload"])
    expected_object_id = _canonical_registry_object_id(
        object_type=stored["object_type"],
        object_version=stored["object_version"],
        payload_hash=expected_payload_hash,
    )
    assert stored["payload_hash"] == expected_payload_hash
    assert stored["object_id"] == expected_object_id
    assert stored["payload_hash"] == opened.session.session_contract_hash
    assert stored["object_id"] == opened.session.session_contract_object_id
    assert stored["payload"]["session_id"] == opened.session.session_id
    assert stored["payload"]["advertisement_id"] == "adv-ep-1-v1"
    assert stored["payload"]["offer_id"] == "offer-public"
    assert (
        stored["payload"]["accounting_contract_object_id"]
        == opened.session.accounting_contract_object_id
    )


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


def test_open_session_rolls_back_session_state_when_deposit_save_fails(
    tmp_path: Path,
) -> None:
    class DepositSaveFailureStore:
        def __init__(self) -> None:
            self.sessions_by_id: dict[str, object] = {}
            self.deposits_by_id: dict[str, object] = {}
            self.last_saved_session_id: str | None = None

        def list_sessions(self) -> list[object]:
            return list(self.sessions_by_id.values())

        def save_session(self, session) -> None:
            self.last_saved_session_id = session.session_id
            self.sessions_by_id[session.session_id] = session

        def save_deposit(self, deposit) -> None:
            raise RuntimeError("deposit save failed")

        def get_session(self, session_id: str):
            return self.sessions_by_id[session_id]

        def get_deposit_for_session(self, session_id: str):
            return self.deposits_by_id[session_id]

        def discard_open_session(self, session_id: str) -> None:
            self.sessions_by_id.pop(session_id, None)
            self.deposits_by_id.pop(session_id, None)

    registry = RegistryService(snapshot_path=tmp_path / "registry-objects.json")
    store = DepositSaveFailureStore()
    service = SessionService(store, registry_service=registry)

    with pytest.raises(RuntimeError, match="deposit save failed"):
        service.open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-a",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=10.0,
            session_policy=_session_policy(),
            accounting_contract={
                "contract_version": "acct-v1",
                "pricing_version": "pricing-v1",
            },
            advertisement_id="adv-ep-1-v1",
            offer_id="offer-public",
            pricing_policy_hash="sha256:pricing-v1",
        )

    assert store.list_sessions() == []
    assert store.last_saved_session_id is not None
    with pytest.raises(KeyError):
        store.get_deposit_for_session(store.last_saved_session_id)
    assert registry.list_registry_objects(query={"include_payload": True}) == []


def test_open_session_succeeds_when_observability_side_effects_fail(
    tmp_path: Path,
) -> None:
    def failing_operation_recorder(**kwargs) -> None:
        raise RuntimeError("operation recorder failed")

    def failing_event_recorder(**kwargs) -> None:
        raise RuntimeError("event recorder failed")

    registry = RegistryService(snapshot_path=tmp_path / "registry-objects.json")
    store = SessionStore()
    service = SessionService(
        store,
        registry_service=registry,
        operation_recorder=failing_operation_recorder,
        event_recorder=failing_event_recorder,
    )

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
        accounting_contract={
            "contract_version": "acct-v1",
            "pricing_version": "pricing-v1",
        },
        advertisement_id="adv-ep-1-v1",
        offer_id="offer-public",
        pricing_policy_hash="sha256:pricing-v1",
    )

    assert store.get_session(opened.session.session_id).session_id == opened.session.session_id
    assert store.get_deposit_for_session(opened.session.session_id).session_id == (
        opened.session.session_id
    )
    stored = registry.get_registry_object(
        opened.session.session_contract_object_id,
        include_payload=True,
    )
    assert stored["payload"]["session_id"] == opened.session.session_id


def test_record_usage_checkpoint_creates_acknowledgement_and_updates_accepted_state() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(),
    )
    charged = service.record_usage_charge(opened.session.session_id, amount_q=6.5)
    report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )

    updated = service.record_usage_checkpoint(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        accepted_charge_q=charged.deposit.consumed_q,
    )

    assert updated.accounting_status == "open"
    assert updated.last_accepted_report_sequence == 1
    assert updated.last_accepted_usage_charged_q == 6.5
    assert updated.last_usage_acknowledgement_snapshot["verification_status"] == "accepted_unverified"


def test_record_usage_report_moves_session_to_ack_pending() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(),
    )
    report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )

    updated = service.record_usage_report(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=120,
    )

    assert updated.accounting_status == "ack_pending"
    assert updated.last_usage_report_snapshot["report_id"] == "rep-1"
    assert updated.last_usage_acknowledgement_snapshot == {}
    assert updated.accounting_checkpoint["last_report_sequence"] == 1
    assert updated.accounting_checkpoint["last_report_hash"].startswith("sha256:")
    assert updated.accounting_checkpoint["last_accepted_report_sequence"] is None
    assert updated.accounting_checkpoint["last_accepted_usage_charged_q"] == 0.0
    assert updated.accounting_checkpoint["ack_deadline_at"] == "2026-07-10T00:02:00+00:00"


def test_record_usage_acknowledgement_advances_last_accepted_checkpoint_and_reopens_session() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(),
    )
    report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )
    pending = service.record_usage_report(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=120,
    )
    acknowledgement = UsageAcknowledgement(
        session_id=opened.session.session_id,
        sequence=1,
        provider_report_hash=pending.accounting_checkpoint["last_report_hash"],
        verification_status="verified",
        signature="ack-1",
    )

    updated = service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement=acknowledgement.model_dump(mode="json"),
        accepted_charge_q=6.5,
    )

    assert updated.accounting_status == "open"
    assert updated.last_usage_acknowledgement_snapshot["verification_status"] == "verified"
    assert updated.last_accepted_report_sequence == 1
    assert updated.last_accepted_usage_charged_q == 6.5
    assert updated.accounting_checkpoint["last_ack_sequence"] == 1
    assert updated.accounting_checkpoint["last_accepted_report_sequence"] == 1
    assert updated.accounting_checkpoint["last_accepted_report_hash"] == pending.accounting_checkpoint["last_report_hash"]
    assert updated.accounting_checkpoint["last_accepted_usage_charged_q"] == 6.5
    assert updated.accounting_checkpoint["ack_deadline_at"] is None


def test_expire_usage_acknowledgement_marks_force_settle_required_without_advancing_baseline() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(),
    )
    report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )
    service.record_usage_report(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=120,
    )

    expired = service.expire_usage_acknowledgement(
        opened.session.session_id,
        now=datetime(2026, 7, 10, 0, 2, 0, tzinfo=timezone.utc),
    )

    assert expired.accounting_status == "force_settle_required"
    assert expired.last_accepted_report_sequence is None
    assert expired.last_accepted_usage_charged_q == 0.0
    assert expired.accounting_checkpoint["last_report_sequence"] == 1
    assert expired.accounting_checkpoint["last_accepted_report_sequence"] is None
    assert expired.accounting_checkpoint["last_accepted_usage_charged_q"] == 0.0
    assert expired.accounting_checkpoint["ack_deadline_at"] == "2026-07-10T00:02:00+00:00"


def test_invalid_chain_acknowledgement_does_not_advance_accepted_baseline() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(minimum_session_fee=0.0),
    )
    first_charge = service.record_usage_charge(opened.session.session_id, amount_q=6.5)
    first_report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )
    accepted = service.record_usage_checkpoint(
        opened.session.session_id,
        usage_report=first_report.model_dump(mode="json"),
        accepted_charge_q=first_charge.deposit.consumed_q,
    )
    second_charge = service.record_usage_charge(opened.session.session_id, amount_q=5.5)
    invalid_report = UsageReport(
        report_id="rep-2",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=2,
        cumulative_usage={"input_tokens": 180, "output_tokens": 80},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        previous_report_hash="sha256:not-the-real-previous-hash",
        created_at="2026-07-10T00:01:00+00:00",
        signature="sig-2",
    )

    mismatched = service.record_usage_report(
        opened.session.session_id,
        usage_report=invalid_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=120,
    )
    current = service.get_session(opened.session.session_id).session
    acknowledgement = UsageAcknowledgement(
        session_id=opened.session.session_id,
        sequence=2,
        provider_report_hash=current.accounting_checkpoint["last_report_hash"],
        verification_status="verified",
        signature="ack-2",
    )

    updated = service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement=acknowledgement.model_dump(mode="json"),
        accepted_charge_q=second_charge.deposit.consumed_q,
    )

    assert accepted.last_accepted_report_sequence == 1
    assert mismatched.accounting_status == "mismatch"
    assert updated.accounting_status == "mismatch"
    assert updated.last_accepted_report_sequence == 1
    assert updated.last_accepted_usage_charged_q == 6.5
    assert updated.accounting_checkpoint["last_accepted_report_sequence"] == 1
    assert updated.accounting_checkpoint["last_accepted_usage_charged_q"] == 6.5


def test_record_usage_report_duplicate_retry_is_idempotent() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(),
    )
    report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )

    first = service.record_usage_report(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=120,
    )
    retried = service.record_usage_report(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=120,
    )

    assert retried == first
    assert len(retried.usage_report_chain) == 1
    assert retried.accounting_status == "ack_pending"
    assert retried.accounting_checkpoint == first.accounting_checkpoint


def test_record_usage_report_conflicting_same_sequence_sets_mismatch() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(),
    )
    first_report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )
    conflicting_report = first_report.model_copy(
        update={
            "report_id": "rep-1-conflict",
            "cumulative_usage": {"input_tokens": 999, "output_tokens": 40},
            "signature": "sig-1-conflict",
        }
    )

    first = service.record_usage_report(
        opened.session.session_id,
        usage_report=first_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=120,
    )
    mismatched = service.record_usage_report(
        opened.session.session_id,
        usage_report=conflicting_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=120,
    )

    assert first.accounting_status == "ack_pending"
    assert mismatched.accounting_status == "mismatch"
    assert mismatched.accounting_checkpoint["mismatch_open"] is True
    assert mismatched.accounting_checkpoint["last_report_hash"] == first.accounting_checkpoint["last_report_hash"]
    assert len(mismatched.usage_report_chain) == 2


def test_record_usage_report_rejects_mismatched_payload_session_id() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(),
    )
    report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id="sess-other",
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )

    with pytest.raises(ValueError, match="session_id"):
        service.record_usage_report(
            opened.session.session_id,
            usage_report=report.model_dump(mode="json"),
            acknowledgement_timeout_seconds=120,
        )


def test_record_usage_report_rejects_mismatched_payload_endpoint_id() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(),
    )
    report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-other",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )

    with pytest.raises(ValueError, match="endpoint_id"):
        service.record_usage_report(
            opened.session.session_id,
            usage_report=report.model_dump(mode="json"),
            acknowledgement_timeout_seconds=120,
        )


def test_record_usage_acknowledgement_rejects_mismatched_payload_session_id() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(),
    )
    report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )
    pending = service.record_usage_report(
        opened.session.session_id,
        usage_report=report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=120,
    )
    acknowledgement = UsageAcknowledgement(
        session_id="sess-other",
        sequence=1,
        provider_report_hash=pending.accounting_checkpoint["last_report_hash"],
        verification_status="verified",
        signature="ack-1",
    )

    with pytest.raises(ValueError, match="session_id"):
        service.record_usage_acknowledgement(
            opened.session.session_id,
            usage_acknowledgement=acknowledgement.model_dump(mode="json"),
            accepted_charge_q=6.5,
        )


def test_close_session_preserves_last_accepted_checkpoint_when_newer_report_is_unacknowledged() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(minimum_session_fee=0.0),
    )
    first_charge = service.record_usage_charge(opened.session.session_id, amount_q=6.5)
    first_report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )
    accepted = service.record_usage_checkpoint(
        opened.session.session_id,
        usage_report=first_report.model_dump(mode="json"),
        accepted_charge_q=first_charge.deposit.consumed_q,
    )
    second_charge = service.record_usage_charge(opened.session.session_id, amount_q=5.5)
    second_report = UsageReport(
        report_id="rep-2",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=2,
        cumulative_usage={"input_tokens": 180, "output_tokens": 80},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        previous_report_hash=accepted.accounting_checkpoint["last_accepted_report_hash"],
        created_at="2026-07-10T00:01:00+00:00",
        signature="sig-2",
    )
    pending = service.record_usage_report(
        opened.session.session_id,
        usage_report=second_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=120,
    )

    closed = service.close_session(opened.session.session_id)

    assert pending.accounting_status == "ack_pending"
    assert pending.last_accepted_report_sequence == 1
    assert pending.last_accepted_usage_charged_q == 6.5
    assert second_charge.deposit.consumed_q == 12.0
    assert closed.deposit.consumed_q == 6.51
    assert closed.deposit.refunded_q == 13.49
    assert closed.settlement is not None
    assert closed.settlement.usage_charged_q == 6.5
    assert closed.settlement.network_fee_q == 0.01
    assert closed.settlement.charged_q == 6.51


def test_close_session_uses_last_accepted_checkpoint_when_later_usage_mismatches() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=20.0,
        session_policy=_session_policy(minimum_session_fee=0.0),
    )
    first_charge = service.record_usage_charge(opened.session.session_id, amount_q=6.5)
    first_report = UsageReport(
        report_id="rep-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 100, "output_tokens": 40},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:00:00+00:00",
        signature="sig-1",
    )
    service.record_usage_checkpoint(
        opened.session.session_id,
        usage_report=first_report.model_dump(mode="json"),
        accepted_charge_q=first_charge.deposit.consumed_q,
    )
    second_charge = service.record_usage_charge(opened.session.session_id, amount_q=5.5)
    second_report = UsageReport(
        report_id="rep-2",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id="ep-1",
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=2,
        cumulative_usage={"input_tokens": 180, "output_tokens": 80},
        measurement_sources={"input_tokens": "provider_api", "output_tokens": "provider_api"},
        created_at="2026-07-10T00:01:00+00:00",
        signature="sig-2",
    )

    mismatched = service.record_usage_checkpoint(
        opened.session.session_id,
        usage_report=second_report.model_dump(mode="json"),
        accepted_charge_q=second_charge.deposit.consumed_q,
        verification_status="mismatch",
    )
    closed = service.close_session(opened.session.session_id)

    assert mismatched.accounting_status == "mismatch"
    assert mismatched.last_accepted_report_sequence == 1
    assert closed.deposit.consumed_q == 6.51
    assert closed.deposit.refunded_q == 13.49
    assert closed.settlement is not None
    assert closed.settlement.network_fee_q == 0.01
    assert closed.settlement.charged_q == 6.51


def test_require_request_budget_rejects_when_remaining_deposit_is_below_maximum_request_charge() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-a",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=25.0,
        session_policy=_session_policy(),
        accounting_contract={
            "contract_version": "acct-v1",
            "pricing_version": "pricing-v1",
            "checkpoint_policy": "per_request",
            "maximum_request_charge": 15.0,
            "billable_units": [],
        },
    )
    service.record_usage_charge(opened.session.session_id, amount_q=12.0)

    with pytest.raises(ValueError, match="maximum request charge"):
        service.require_request_budget(
            endpoint_id="ep-1",
            session_id=opened.session.session_id,
        )
