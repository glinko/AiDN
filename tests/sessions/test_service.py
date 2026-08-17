import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aidn_hypervisor.accounting.models import (
    AccountingContract,
    UsageAcknowledgement,
    UsageReport,
)
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.session_application_service import SessionApplicationService
from aidn_hypervisor.sessions.models import (
    ProxySessionBinding,
    SessionContractExchange,
)
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore
from aidn_hypervisor.settlement.models import SessionFundingAccount


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
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


def test_open_owner_agent_session_allows_zero_escrow_and_zero_cost_budget() -> None:
    service = _session_service()

    opened = service.open_session(
        endpoint_id="ep-owner-agent",
        client_wallet="wallet-owner",
        provider_wallet="wallet-owner",
        node_id="node-1",
        deposit_q=0.0,
        deposit_q_atoms=0,
        economic_profile="OWNER_AGENT",
        session_policy=_session_policy(minimum_deposit=12.0, minimum_session_fee=0.0),
        accounting_contract={"maximum_request_charge": 0.0, "profile": "OWNER_AGENT"},
    )

    assert opened.deposit.locked_q == 0.0
    assert service.require_request_budget(
        endpoint_id="ep-owner-agent",
        session_id=opened.session.session_id,
    ) == opened.session


def test_open_session_rejects_zero_escrow_outside_owner_agent() -> None:
    with pytest.raises(ValueError, match="positive outside OWNER_AGENT"):
        _session_service().open_session(
            endpoint_id="ep-1",
            client_wallet="wallet-client",
            provider_wallet="wallet-provider",
            node_id="node-1",
            deposit_q=0.0,
            session_policy=_session_policy(minimum_deposit=0.0),
        )


def test_validator_pending_session_does_not_record_local_open_operation() -> None:
    recorded: list[dict] = []
    service = SessionService(
        SessionStore(),
        operation_recorder=lambda **kwargs: recorded.append(kwargs),
        record_open_operation=False,
    )

    service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        deposit_q_atoms=10_000_000,
        fixed_price_q_atoms=1_000_000,
        request_charge_ceiling_q_atoms=1_000_000,
        economic_profile="MVP-0001",
        canonical_funding_status="PENDING_FINALITY",
        session_policy=_session_policy(),
    )

    assert recorded == []


def test_runtime_terminal_evidence_is_session_bound_and_replay_safe() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
        accounting_contract_hash="acct-hash",
        endpoint_configuration_hash="endpoint-config-hash",
    )
    session = opened.session
    evidence = {
        "request_id": "request-1",
        "runtime_binding_id": "rtb-1",
        "runtime_id": "runtime-1",
        "runtime_generation": 1,
        "runtime_configuration_hash": "runtime-config-hash",
        "route_generation": 1,
        "endpoint_id": session.endpoint_id,
        "endpoint_configuration_hash": session.endpoint_configuration_hash,
        "session_id": session.session_id,
        "session_contract_hash": session.session_contract_hash,
        "accounting_contract_hash": session.accounting_contract_hash,
        "terminal_state": "COMPLETED",
        "result_hash": "result-hash",
        "final_usage_report_id": "usage-1",
        "final_usage_report_hash": "usage-hash",
        "recorded_at": "2026-07-21T00:00:00+00:00",
    }

    recorded = service.record_runtime_terminal_evidence(
        session.session_id,
        evidence=evidence,
    )

    assert recorded.runtime_terminal_evidence[0].request_id == "request-1"
    assert (
        service.record_runtime_terminal_evidence(
            session.session_id,
            evidence=evidence,
        )
        == recorded
    )
    with pytest.raises(ValueError, match="conflicts"):
        service.record_runtime_terminal_evidence(
            session.session_id,
            evidence={**evidence, "result_hash": "different-result-hash"},
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
    assert closed.settlement.endpoint_payment_q == 2.0
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
    assert closed.settlement.endpoint_payment_q == 6.5
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

    swept = service.sweep_idle_sessions(now=datetime(2026, 7, 1, 0, 10, 0, tzinfo=UTC))

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

    swept = service.sweep_idle_sessions(now=datetime(2026, 7, 1, 0, 10, 0, tzinfo=UTC))

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
        endpoint_configuration_hash="cfg-accepted",
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
        endpoint_configuration_hash="cfg-accepted",
    )

    assert opened.session.session_contract_object_id.startswith("sha256:")
    assert opened.session.session_contract_object_version == "session-contract.v2"
    assert opened.session.endpoint_payment_beneficiary == "wallet-provider"
    assert opened.session.consumer_refund_beneficiary == "wallet-a"
    assert opened.session.session_contract_namespace == "session"
    assert opened.session.session_contract_hash.startswith("sha256:")

    stored = registry.get_registry_object(
        opened.session.session_contract_object_id,
        include_payload=True,
    )

    assert stored["object_type"] == "session_contract"
    assert stored["object_version"] == "session-contract.v2"
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
    assert stored["payload"]["endpoint_configuration_hash"] == "cfg-accepted"
    assert stored["payload"]["endpoint_payment_beneficiary"] == "wallet-provider"
    assert stored["payload"]["consumer_refund_beneficiary"] == "wallet-a"
    assert stored["payload"]["session_contract_version"] == "session-contract.v2"
    assert opened.session.endpoint_configuration_hash == "cfg-accepted"
    assert stored["payload"]["accounting_contract_object_id"] == opened.session.accounting_contract_object_id


def test_open_session_binds_explicit_payment_and_refund_beneficiaries() -> None:
    service = _session_service()

    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-consumer",
        provider_wallet="legacy-provider-wallet",
        endpoint_payment_beneficiary="wallet-treasury",
        consumer_refund_beneficiary="wallet-refunds",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
    )

    assert opened.session.provider_wallet == "legacy-provider-wallet"
    assert opened.session.endpoint_payment_beneficiary == "wallet-treasury"
    assert opened.session.consumer_refund_beneficiary == "wallet-refunds"


def test_session_amendment_chain_is_hash_bound_and_idempotent(tmp_path: Path) -> None:
    registry = RegistryService(snapshot_path=tmp_path / "registry-objects.json")
    service = SessionService(SessionStore(), registry_service=registry)
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-consumer",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
        session_id="session-amendment-1",
    )

    updated = service.accept_session_amendment(
        opened.session.session_id,
        amendment_id="amendment-1",
        amendment_kind="EXPIRATION_EXTENSION",
        changes={"expires_at": "2030-01-01T00:00:00+00:00"},
        consumer_signature="consumer-signature",
        endpoint_signature="endpoint-signature",
        accepted_at="2026-07-21T00:00:00+00:00",
    )

    assert updated.session_amendment_sequence == 1
    assert updated.effective_terms_hash != opened.session.session_contract_hash
    assert updated.expires_at == "2030-01-01T00:00:00+00:00"
    amendments = service.get_session_amendments(opened.session.session_id)
    assert len(amendments) == 1
    amendment = amendments[0]
    assert amendment.previous_effective_terms_hash == opened.session.session_contract_hash
    assert amendment.effective_terms_hash == updated.effective_terms_hash

    stored = registry.get_registry_object(amendment.object_id, include_payload=True)
    assert stored["object_type"] == "session_contract_amendment"
    assert stored["payload_hash"] == _canonical_hash(stored["payload"])
    assert stored["payload_hash"] == amendment.amendment_hash

    retried = service.accept_session_amendment(
        opened.session.session_id,
        amendment_id="amendment-1",
        amendment_kind="EXPIRATION_EXTENSION",
        changes={"expires_at": "2030-01-01T00:00:00+00:00"},
        consumer_signature="consumer-signature",
        endpoint_signature="endpoint-signature",
    )
    assert retried == updated

    with pytest.raises(ValueError, match="conflicts"):
        service.accept_session_amendment(
            opened.session.session_id,
            amendment_id="amendment-1",
            amendment_kind="EXPIRATION_EXTENSION",
            changes={"expires_at": "2031-01-01T00:00:00+00:00"},
            consumer_signature="consumer-signature",
            endpoint_signature="endpoint-signature",
        )


def test_session_contract_exchange_round_trips_and_rejects_tampering(
    tmp_path: Path,
) -> None:
    source_registry = RegistryService(snapshot_path=tmp_path / "source-registry.json")
    source = SessionService(SessionStore(), registry_service=source_registry)
    opened = source.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-consumer",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
        session_id="session-contract-exchange-1",
    )
    source.accept_session_amendment(
        opened.session.session_id,
        amendment_id="exchange-amendment-1",
        amendment_kind="EXPIRATION_EXTENSION",
        changes={"expires_at": "2030-01-01T00:00:00+00:00"},
        consumer_signature="consumer-signature",
        endpoint_signature="endpoint-signature",
        accepted_at="2026-07-21T00:00:00+00:00",
    )

    exchange = source.export_session_contract(opened.session.session_id)
    assert isinstance(exchange, SessionContractExchange)
    assert exchange.amendment_sequence == 1
    assert exchange.effective_terms_hash == source.get_session(
        opened.session.session_id
    ).session.effective_terms_hash

    peer_registry = RegistryService(snapshot_path=tmp_path / "peer-registry.json")
    peer = SessionService(SessionStore(), registry_service=peer_registry)
    imported = peer.import_session_contract_exchange(exchange)
    assert imported["status"] == "IMPORTED"
    assert imported["imported_object_count"] == 2
    duplicate = peer.import_session_contract_exchange(exchange.model_dump(mode="json"))
    assert duplicate["status"] == "DUPLICATE"
    assert duplicate["imported_object_count"] == 0

    tampered = exchange.model_dump(mode="json")
    tampered["session_contract"]["endpoint_id"] = "ep-tampered"
    with pytest.raises(ValueError, match="payload hash"):
        peer.import_session_contract_exchange(tampered)


def test_session_contract_exchange_does_not_overwrite_conflicting_local_session(
    tmp_path: Path,
) -> None:
    source = SessionService(
        SessionStore(),
        registry_service=RegistryService(snapshot_path=tmp_path / "source-registry.json"),
    )
    source_session = source.open_session(
        endpoint_id="ep-source",
        client_wallet="wallet-consumer",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
        session_id="session-contract-conflict-1",
    )
    exchange = source.export_session_contract(source_session.session.session_id)

    peer = SessionService(
        SessionStore(),
        registry_service=RegistryService(snapshot_path=tmp_path / "peer-registry.json"),
    )
    peer.open_session(
        endpoint_id="ep-other",
        client_wallet="wallet-consumer",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
        session_id=exchange.session_id,
    )

    with pytest.raises(ValueError, match="local Session Contract hash conflicts"):
        peer.import_session_contract_exchange(exchange)
    with pytest.raises(KeyError):
        peer.registry_service.get_registry_object(
            exchange.session_contract_object_id,
            include_payload=True,
        )


def test_forced_settlement_is_terminal_idempotent_and_snapshot_persistent() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-consumer",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        deposit_q_atoms=10_000_000,
        fixed_price_q_atoms=9_000_000,
        request_charge_ceiling_q_atoms=9_000_000,
        session_policy=_session_policy(),
        economic_profile="MVP-0001",
        session_id="session-force-terminal-1",
    )

    forced = service.mark_canonical_settlement_finalized(
        opened.session.session_id,
        settlement_evidence_root="sha256:forced-evidence",
        endpoint_payment_q_atoms=9_000_000,
        consumer_refund_q_atoms=1_000_000,
        close_reason="forced_endpoint_unavailable",
    )
    assert forced.session.status == "force_settled"
    assert forced.session.settlement_snapshot["settlement_evidence_root"] == (
        "sha256:forced-evidence"
    )

    repeated = service.mark_canonical_settlement_finalized(
        opened.session.session_id,
        settlement_evidence_root="sha256:forced-evidence",
        endpoint_payment_q_atoms=9_000_000,
        consumer_refund_q_atoms=1_000_000,
        close_reason="forced_endpoint_unavailable",
    )
    assert repeated.session == forced.session
    assert repeated.deposit == forced.deposit
    closed = service.close_session(opened.session.session_id)
    assert closed.session.status == "force_settled"
    assert closed.settlement is not None

    with pytest.raises(ValueError, match="different settlement evidence"):
        service.mark_canonical_settlement_finalized(
            opened.session.session_id,
            settlement_evidence_root="sha256:other-evidence",
            endpoint_payment_q_atoms=9_000_000,
            consumer_refund_q_atoms=1_000_000,
        )


def test_force_closing_session_closes_as_force_settled_with_snapshot() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-consumer",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        deposit_q_atoms=10_000_000,
        fixed_price_q_atoms=9_000_000,
        request_charge_ceiling_q_atoms=9_000_000,
        session_policy=_session_policy(),
        economic_profile="MVP-0001",
        session_id="session-force-closing-1",
    )
    service.store.save_session(
        opened.session.model_copy(update={"status": "force_closing"})
    )

    closed = service.close_session(opened.session.session_id)

    assert closed.session.status == "force_settled"
    assert closed.session.close_reason == "forced_recovery_expired"
    assert closed.session.settlement_snapshot["settlement_evidence_root"] == (
        closed.settlement.settlement_evidence_root
        if closed.settlement is not None
        else None
    )
    repeated = service.close_session(opened.session.session_id)
    assert repeated.session.status == "force_settled"
    assert repeated.settlement == closed.settlement


def test_economic_session_amendment_requires_canonical_funding_evidence() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-consumer",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        session_policy=_session_policy(),
        economic_profile="MVP-0001",
        session_id="session-economic-amendment-1",
    )

    with pytest.raises(ValueError, match="canonical funding evidence"):
        service.accept_session_amendment(
            opened.session.session_id,
            amendment_id="amendment-economic-1",
            amendment_kind="DEPOSIT_EXTENSION",
            changes={"additional_endpoint_payment_q_atoms": 1_000_000},
            consumer_signature="consumer-signature",
            endpoint_signature="endpoint-signature",
        )


def test_application_verifies_escrow_extension_before_economic_amendment() -> None:
    service = _session_service()
    opened = service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-consumer",
        provider_wallet="wallet-provider",
        node_id="node-1",
        deposit_q=10.0,
        deposit_q_atoms=10_000_000,
        fixed_price_q_atoms=5_000_000,
        request_charge_ceiling_q_atoms=5_000_000,
        session_policy=_session_policy(),
        session_id="session-economic-amendment-verified",
    )
    current_funding = SessionFundingAccount(
        session_id=opened.session.session_id,
        session_contract_hash=opened.session.session_contract_hash,
        funding_class="ESCROW_PREPAID",
        consumer_funding_account="wallet-consumer",
        endpoint_payment_beneficiary="wallet-provider",
        consumer_refund_beneficiary="wallet-consumer",
        total_locked_amount_q_atoms=10_000_000,
        endpoint_payment_reserve_q_atoms=9_000_000,
        network_fee_reserve_q_atoms=1_000_000,
        unsettled_payment_reserve_q_atoms=9_000_000,
        unsettled_fee_reserve_q_atoms=1_000_000,
    )
    next_funding = SessionFundingAccount(
        session_id=opened.session.session_id,
        session_contract_hash=opened.session.session_contract_hash,
        funding_class="ESCROW_PREPAID",
        consumer_funding_account="wallet-consumer",
        endpoint_payment_beneficiary="wallet-provider",
        consumer_refund_beneficiary="wallet-consumer",
        total_locked_amount_q_atoms=12_000_000,
        endpoint_payment_reserve_q_atoms=11_000_000,
        network_fee_reserve_q_atoms=1_000_000,
        unsettled_payment_reserve_q_atoms=11_000_000,
        unsettled_fee_reserve_q_atoms=1_000_000,
    )
    service.store.save_session(
        opened.session.model_copy(
            update={"canonical_funding_state_hash": current_funding.funding_state_hash}
        )
    )

    class FakeLedger:
        def list_operations(self):
            return [
                {
                    "operation_id": "extension-operation-1",
                    "operation_type": "SESSION_ESCROW_EXTEND",
                    "payload": {
                        "session_id": opened.session.session_id,
                        "funding_state_reference": current_funding.funding_state_hash,
                        "funding": next_funding.model_dump(mode="json"),
                        "added_endpoint_payment_reserve_q_atoms": 2_000_000,
                        "added_network_fee_reserve_q_atoms": 0,
                    },
                }
            ]

    class FakeHypervisor:
        ledger_operation_service = FakeLedger()

        def get_session_funding_account(self, session_id: str):
            assert session_id == opened.session.session_id
            return next_funding

    application = SessionApplicationService(
        hypervisor_service=FakeHypervisor(),
        session_service=service,
    )
    updated = application.accept_session_amendment(
        session_id=opened.session.session_id,
        amendment_id="economic-amendment-verified",
        amendment_kind="DEPOSIT_EXTENSION",
        changes={
            "additional_endpoint_payment_q_atoms": 2_000_000,
            "additional_network_fee_q_atoms": 0,
            "funding_operation_id": "extension-operation-1",
            "previous_funding_state_hash": current_funding.funding_state_hash,
            "next_funding_state_hash": next_funding.funding_state_hash,
        },
        consumer_signature="consumer-signature",
        endpoint_signature="endpoint-signature",
    )

    assert updated["effective_terms_hash"] == service.get_session(
        opened.session.session_id
    ).session.effective_terms_hash
    assert service.get_session(opened.session.session_id).deposit.locked_q == 12.0


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
    assert store.get_deposit_for_session(opened.session.session_id).session_id == (opened.session.session_id)
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
    assert updated.accounting_checkpoint["last_accepted_report_id"] == "rep-1"
    assert updated.accounting_checkpoint["accounting_contract_hash"] == (opened.session.accounting_contract_hash)
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
    assert updated.accounting_checkpoint["last_report_id"] == "rep-1"
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
    assert (
        updated.accounting_checkpoint["last_accepted_report_hash"] == pending.accounting_checkpoint["last_report_hash"]
    )
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
        now=datetime(2026, 7, 10, 0, 2, 0, tzinfo=UTC),
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
