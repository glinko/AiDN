from datetime import datetime, timezone

import pytest

from aidn_hypervisor.accounting.models import (
    UsageAcknowledgement,
    UsageReport,
    usage_acknowledgement_hash,
    usage_report_hash,
)
from aidn_hypervisor.endpoints.models import CreateEndpointCommand, UpdateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


def _hypervisor() -> HypervisorService:
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        node_id="node-a",
        operator_id="operator-a",
    )
    session_service = SessionService(SessionStore(), event_recorder=service.record_event)
    session_service.operation_recorder = service.record_ledger_operation
    service.session_service = session_service
    return service


def test_record_ledger_wallet_operation_advances_sender_sequence() -> None:
    service = _hypervisor()

    first = service.record_ledger_operation(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        fee_class="standard",
        initiator_id="wallet-1",
        sender_wallet="wallet-1",
        fee_payer="wallet-1",
        payload={"recipient_wallet": "wallet-2", "amount": 5.0},
        created_at="2026-07-11T00:00:00+00:00",
    )
    second = service.record_ledger_operation(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        fee_class="standard",
        initiator_id="wallet-1",
        sender_wallet="wallet-1",
        fee_payer="wallet-1",
        payload={"recipient_wallet": "wallet-3", "amount": 6.0},
        created_at="2026-07-11T00:01:00+00:00",
    )

    assert first["sender_sequence"] == 1
    assert second["sender_sequence"] == 2
    assert second["wallet_next_sequence"] == 3
    assert first["result"]["status"] == "applied"
    assert second["result"]["status"] == "applied"


def test_record_ledger_wallet_operation_rejects_stale_expected_sequence() -> None:
    service = _hypervisor()
    service.record_ledger_operation(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        fee_class="standard",
        initiator_id="wallet-1",
        sender_wallet="wallet-1",
        fee_payer="wallet-1",
        payload={"recipient_wallet": "wallet-2", "amount": 5.0},
        created_at="2026-07-11T00:00:00+00:00",
    )

    with pytest.raises(ValueError, match="sequence"):
        service.record_ledger_operation(
            operation_type="WALLET_TRANSFER",
            origin_type="wallet",
            fee_class="standard",
            initiator_id="wallet-1",
            sender_wallet="wallet-1",
            fee_payer="wallet-1",
            payload={"recipient_wallet": "wallet-3", "amount": 6.0},
            created_at="2026-07-11T00:01:00+00:00",
            expected_sequence=1,
        )


def test_faucet_claim_records_canonical_ledger_operation() -> None:
    service = _hypervisor()
    service.configure_owner_wallet(mode="create", label="Primary Wallet")

    class _EndpointService:
        def list_endpoints(self):
            class _Manifest:
                status = "active"

            return [_Manifest()]

    service.endpoint_service = _EndpointService()
    service.derive_epoch_reward_budget(
        epoch_id="epoch-21",
        source_epoch_id="epoch-20",
        active_hypervisor_count=4,
    )

    claimed = service.claim_faucet_share()
    operations = service.list_ledger_operations()[-3:]

    assert claimed["claimed"] is True
    assert operations[0]["operation_type"] == "EPOCH_TRANSITION"
    assert operations[0]["origin_type"] == "protocol"
    assert operations[0]["payload"]["opening_epoch"] == "epoch-21"
    assert operations[1]["operation_type"] == "FAUCET_CLAIM"
    assert operations[1]["origin_type"] == "wallet"
    assert operations[1]["fee_class"] == "faucet_exempt"
    assert operations[1]["sender_wallet"] == service.owner_wallet_state()["wallet_id"]
    assert operations[1]["sender_sequence"] == 1
    assert operations[1]["payload"]["claim_epoch"] == "epoch-21"
    assert operations[2]["operation_type"] == "REWARD_MINT"
    assert operations[2]["origin_type"] == "protocol"
    assert operations[2]["payload"]["reward_type"] == "faucet"
    assert operations[2]["payload"]["reward_epoch"] == "epoch-21"
    assert operations[2]["payload"]["recipient_wallet"] == service.owner_wallet_state()["wallet_id"]


def test_session_open_and_settle_record_canonical_ledger_operations() -> None:
    service = _hypervisor()
    session_service = service.session_service

    opened = session_service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-a",
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
        accounting_contract={"contract_version": "acct-v1"},
        advertisement_id="adv-ep-1-v1",
        offer_id="offer-public",
        pricing_policy_hash="sha256:pricing-v1",
    )
    closed = session_service.close_session(opened.session.session_id)

    operations = service.list_ledger_operations()
    operation_types = [item["operation_type"] for item in operations]

    assert operation_types == ["SESSION_OPEN", "SESSION_SETTLE"]
    assert operations[0]["sender_wallet"] == "wallet-client"
    assert operations[0]["fee_class"] == "session"
    assert operations[0]["payload"]["advertisement_id"] == "adv-ep-1-v1"
    assert operations[0]["payload"]["offer_id"] == "offer-public"
    assert operations[0]["payload"]["pricing_policy_hash"] == "sha256:pricing-v1"
    assert operations[0]["payload"]["accounting_contract_hash"].startswith("sha256:")
    assert operations[0]["payload"]["session_contract_hash"] == opened.session.session_contract_hash
    assert operations[0]["payload"]["session_contract_object_id"] == (
        opened.session.session_contract_object_id
    )
    assert operations[0]["payload"]["session_contract_object_id"] != (
        opened.session.session_contract_hash
    )
    assert operations[1]["origin_type"] == "multi_party"
    assert operations[1]["payload"]["advertisement_id"] == "adv-ep-1-v1"
    assert operations[1]["payload"]["offer_id"] == "offer-public"
    assert operations[1]["payload"]["client_wallet"] == opened.session.client_wallet
    assert operations[1]["payload"]["provider_wallet"] == opened.session.provider_wallet
    assert operations[1]["payload"]["session_contract_hash"] == opened.session.session_contract_hash
    assert operations[1]["payload"]["session_contract_object_id"] == (
        opened.session.session_contract_object_id
    )
    assert operations[1]["payload"]["settlement_evidence_root"].startswith("sha256:")
    assert "close_reason" not in operations[1]["payload"]
    assert closed.settlement is not None
    assert closed.settlement.settlement_evidence_root == operations[1]["payload"]["settlement_evidence_root"]


def test_session_accounting_report_and_acknowledgement_record_canonical_ledger_operations() -> None:
    service = _hypervisor()
    session_service = service.session_service
    opened = session_service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-a",
        deposit_q=25.0,
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
        accounting_contract={"contract_version": "acct-v1"},
    )
    usage_report = UsageReport(
        report_id="report-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id=opened.session.endpoint_id,
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 250_000},
        measurement_sources={"input_tokens": "provider_api"},
        created_at="2026-07-12T12:00:00+00:00",
        signature="local:report-1",
    )

    pending = session_service.record_usage_report(
        opened.session.session_id,
        usage_report=usage_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )
    usage_acknowledgement = UsageAcknowledgement(
        session_id=opened.session.session_id,
        sequence=1,
        provider_report_hash=pending.accounting_checkpoint["last_report_hash"],
        verification_status="accepted_unverified",
        signature="local-ack:report-1",
    )
    session_service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement=usage_acknowledgement.model_dump(mode="json"),
        accepted_charge_q=4.0,
    )

    operations = service.list_ledger_operations()
    report_operation = next(
        item for item in operations if item["operation_type"] == "SESSION_USAGE_REPORT"
    )
    acknowledgement_operation = next(
        item
        for item in operations
        if item["operation_type"] == "SESSION_USAGE_ACKNOWLEDGEMENT"
    )
    checkpoint_operation = next(
        item for item in operations if item["operation_type"] == "SESSION_CHECKPOINT_ACCEPT"
    )

    assert report_operation["origin_type"] == "multi_party"
    assert report_operation["fee_class"] == "session"
    assert report_operation["payload"] == {
        "session_id": opened.session.session_id,
        "endpoint_id": opened.session.endpoint_id,
        "sequence": 1,
        "report_hash": usage_report_hash(usage_report),
        "previous_report_hash": None,
        "accounting_contract_version": "acct-v1",
        "accepted_checkpoint_sequence": None,
        "accepted_usage_charged_q": 0.0,
    }
    assert acknowledgement_operation["payload"] == {
        "session_id": opened.session.session_id,
        "endpoint_id": opened.session.endpoint_id,
        "sequence": 1,
        "report_hash": usage_report_hash(usage_report),
        "ack_hash": usage_acknowledgement_hash(usage_acknowledgement),
        "accepted_checkpoint_sequence": 1,
        "accepted_usage_charged_q": 4.0,
        "verification_status": "accepted_unverified",
    }
    assert checkpoint_operation["payload"] == {
        "session_id": opened.session.session_id,
        "endpoint_id": opened.session.endpoint_id,
        "accepted_checkpoint_sequence": 1,
        "report_hash": usage_report_hash(usage_report),
        "accepted_usage_charged_q": 4.0,
    }


def test_session_accounting_replays_do_not_duplicate_ledger_operations() -> None:
    service = _hypervisor()
    session_service = service.session_service
    opened = session_service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-a",
        deposit_q=25.0,
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
        accounting_contract={"contract_version": "acct-v1"},
    )
    usage_report = UsageReport(
        report_id="report-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id=opened.session.endpoint_id,
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 250_000},
        measurement_sources={"input_tokens": "provider_api"},
        created_at="2026-07-12T12:00:00+00:00",
        signature="local:report-1",
    )

    pending = session_service.record_usage_report(
        opened.session.session_id,
        usage_report=usage_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )
    session_service.record_usage_report(
        opened.session.session_id,
        usage_report=usage_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )
    usage_acknowledgement = UsageAcknowledgement(
        session_id=opened.session.session_id,
        sequence=1,
        provider_report_hash=pending.accounting_checkpoint["last_report_hash"],
        verification_status="accepted_unverified",
        signature="local-ack:report-1",
    )
    session_service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement=usage_acknowledgement.model_dump(mode="json"),
        accepted_charge_q=4.0,
    )
    session_service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement=usage_acknowledgement.model_dump(mode="json"),
        accepted_charge_q=4.0,
    )

    operation_types = [item["operation_type"] for item in service.list_ledger_operations()]

    assert operation_types.count("SESSION_USAGE_REPORT") == 1
    assert operation_types.count("SESSION_USAGE_ACKNOWLEDGEMENT") == 1
    assert operation_types.count("SESSION_CHECKPOINT_ACCEPT") == 1


def test_session_accounting_conflicting_report_replay_is_operation_silent() -> None:
    service = _hypervisor()
    session_service = service.session_service
    opened = session_service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-a",
        deposit_q=25.0,
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
        accounting_contract={"contract_version": "acct-v1"},
    )
    first_report = UsageReport(
        report_id="report-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id=opened.session.endpoint_id,
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 250_000},
        measurement_sources={"input_tokens": "provider_api"},
        created_at="2026-07-12T12:00:00+00:00",
        signature="local:report-1",
    )
    session_service.record_usage_report(
        opened.session.session_id,
        usage_report=first_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )
    conflicting_report = UsageReport(
        report_id="report-2",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id=opened.session.endpoint_id,
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=2,
        previous_report_hash="sha256:wrong",
        cumulative_usage={"input_tokens": 500_000},
        measurement_sources={"input_tokens": "provider_api"},
        created_at="2026-07-12T12:01:00+00:00",
        signature="local:report-2",
    )

    mismatched = session_service.record_usage_report(
        opened.session.session_id,
        usage_report=conflicting_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )
    replayed = session_service.record_usage_report(
        opened.session.session_id,
        usage_report=conflicting_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )

    operation_types = [item["operation_type"] for item in service.list_ledger_operations()]
    mismatch_events = [
        event for event in service.event_journal() if event.event_type == "session.accounting_mismatch"
    ]

    assert mismatched.accounting_status == "mismatch"
    assert replayed.accounting_status == "mismatch"
    assert len(replayed.usage_report_chain) == 2
    assert operation_types.count("SESSION_USAGE_REPORT") == 2
    assert mismatch_events == [mismatch_events[0]]


def test_session_accounting_mismatched_acknowledgement_replay_is_operation_silent() -> None:
    service = _hypervisor()
    session_service = service.session_service
    opened = session_service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-a",
        deposit_q=25.0,
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
        accounting_contract={"contract_version": "acct-v1"},
    )
    usage_report = UsageReport(
        report_id="report-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id=opened.session.endpoint_id,
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 250_000},
        measurement_sources={"input_tokens": "provider_api"},
        created_at="2026-07-12T12:00:00+00:00",
        signature="local:report-1",
    )
    pending = session_service.record_usage_report(
        opened.session.session_id,
        usage_report=usage_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )
    mismatched_acknowledgement = UsageAcknowledgement(
        session_id=opened.session.session_id,
        sequence=1,
        provider_report_hash="sha256:wrong",
        verification_status="mismatch",
        signature="local-ack:report-1",
    )

    mismatched = session_service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement=mismatched_acknowledgement.model_dump(mode="json"),
        accepted_charge_q=3.5,
    )
    replayed = session_service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement=mismatched_acknowledgement.model_dump(mode="json"),
        accepted_charge_q=3.5,
    )

    operation_types = [item["operation_type"] for item in service.list_ledger_operations()]
    mismatch_events = [
        event for event in service.event_journal() if event.event_type == "session.accounting_mismatch"
    ]

    assert pending.accounting_status == "ack_pending"
    assert mismatched.accounting_status == "mismatch"
    assert replayed.accounting_status == "mismatch"
    assert len(replayed.usage_acknowledgement_chain) == 1
    assert operation_types.count("SESSION_USAGE_ACKNOWLEDGEMENT") == 1
    assert operation_types.count("SESSION_CHECKPOINT_ACCEPT") == 0
    assert mismatch_events == [mismatch_events[0]]


def test_session_accounting_mismatched_acknowledgement_replay_conflicts_on_different_charge() -> None:
    service = _hypervisor()
    session_service = service.session_service
    opened = session_service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-a",
        deposit_q=25.0,
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
        accounting_contract={"contract_version": "acct-v1"},
    )
    usage_report = UsageReport(
        report_id="report-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id=opened.session.endpoint_id,
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 250_000},
        measurement_sources={"input_tokens": "provider_api"},
        created_at="2026-07-12T12:00:00+00:00",
        signature="local:report-1",
    )
    session_service.record_usage_report(
        opened.session.session_id,
        usage_report=usage_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )
    mismatched_acknowledgement = UsageAcknowledgement(
        session_id=opened.session.session_id,
        sequence=1,
        provider_report_hash="sha256:wrong",
        verification_status="mismatch",
        signature="local-ack:report-1",
    )
    session_service.record_usage_acknowledgement(
        opened.session.session_id,
        usage_acknowledgement=mismatched_acknowledgement.model_dump(mode="json"),
        accepted_charge_q=3.5,
    )

    with pytest.raises(ValueError, match="accepted charge"):
        session_service.record_usage_acknowledgement(
            opened.session.session_id,
            usage_acknowledgement=mismatched_acknowledgement.model_dump(mode="json"),
            accepted_charge_q=9.5,
        )


def test_session_accounting_timeout_records_force_settlement_required_operation() -> None:
    service = _hypervisor()
    session_service = service.session_service
    opened = session_service.open_session(
        endpoint_id="ep-1",
        client_wallet="wallet-client",
        provider_wallet="wallet-provider",
        node_id="node-a",
        deposit_q=25.0,
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
        accounting_contract={"contract_version": "acct-v1"},
    )
    usage_report = UsageReport(
        report_id="report-1",
        report_version="0.1",
        session_id=opened.session.session_id,
        endpoint_id=opened.session.endpoint_id,
        capability_id="llm_text.generate",
        pricing_version="pricing-v1",
        accounting_contract_version="acct-v1",
        accounting_modes={"input_tokens": "provider_metered"},
        sequence=1,
        cumulative_usage={"input_tokens": 250_000},
        measurement_sources={"input_tokens": "provider_api"},
        created_at="2026-07-12T12:00:00+00:00",
        signature="local:report-1",
    )
    report_hash = usage_report_hash(usage_report)

    session_service.record_usage_report(
        opened.session.session_id,
        usage_report=usage_report.model_dump(mode="json"),
        acknowledgement_timeout_seconds=30,
    )
    session_service.expire_usage_acknowledgement(
        opened.session.session_id,
        now=datetime(2026, 7, 12, 12, 0, 31, tzinfo=timezone.utc),
    )

    operation = service.list_ledger_operations()[-1]

    assert operation["operation_type"] == "SESSION_ACCOUNTING_FORCE_SETTLE_REQUIRED"
    assert operation["payload"] == {
        "session_id": opened.session.session_id,
        "endpoint_id": opened.session.endpoint_id,
        "last_report_sequence": 1,
        "last_report_hash": report_hash,
        "accepted_checkpoint_sequence": None,
        "accepted_usage_charged_q": 0.0,
    }


def test_ledger_operations_are_snapshotted_and_restored() -> None:
    service = _hypervisor()
    service.record_ledger_operation(
        operation_type="WALLET_TRANSFER",
        origin_type="wallet",
        fee_class="standard",
        initiator_id="wallet-1",
        sender_wallet="wallet-1",
        fee_payer="wallet-1",
        payload={"recipient_wallet": "wallet-2", "amount": 5.0},
        created_at="2026-07-11T00:00:00+00:00",
    )

    snapshot = service.snapshot_state()
    restored = _hypervisor()
    restored.restore_state(snapshot)

    operations = restored.list_ledger_operations()
    assert len(operations) == 1
    assert operations[0]["operation_type"] == "WALLET_TRANSFER"
    assert restored.wallet_next_operation_sequence("wallet-1") == 2


def test_validation_request_records_canonical_ledger_operation() -> None:
    service = _hypervisor()
    validation_service = ValidationService(ValidationStore())
    service.bind_validation_service(validation_service)

    requested = validation_service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    operation = service.list_ledger_operations()[-1]

    assert requested.request.status == "queued"
    assert operation["operation_type"] == "VALIDATION_REQUEST"
    assert operation["sender_wallet"] == "wallet-1"
    assert operation["sender_sequence"] == 1
    assert operation["payload"]["endpoint_id"] == "ep-1"
    assert operation["payload"]["bond_reference"] == requested.bond.bond_id


def test_validation_report_commit_records_canonical_ledger_operation() -> None:
    service = _hypervisor()
    validation_service = ValidationService(ValidationStore())
    service.bind_validation_service(validation_service)

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
    outcome = validation_service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    operations = service.list_ledger_operations()[-2:]

    assert outcome.request.status == "passed"
    assert operations[0]["operation_type"] == "VALIDATION_REPORT_COMMIT"
    assert operations[0]["origin_type"] == "protocol"
    assert operations[0]["payload"]["report_id"] == outcome.report.report_id
    assert (
        operations[0]["payload"]["validation_request_id"]
        == requested.request.request_id
    )
    assert operations[1]["operation_type"] == "CERTIFICATION_STATE_UPDATE"
    assert operations[1]["origin_type"] == "protocol"
    assert operations[1]["payload"]["certification_status"] == "certified"


def test_validation_bond_refund_records_canonical_ledger_operation() -> None:
    service = _hypervisor()
    validation_service = ValidationService(ValidationStore())
    service.bind_validation_service(validation_service)

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
    outcome = validation_service.resolve_maintenance(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="healthy",
    )
    operations = service.list_ledger_operations()[-2:]

    assert outcome.bond.remaining_locked_q == 250.0
    assert operations[0]["operation_type"] == "CERTIFICATION_STATE_UPDATE"
    assert operations[0]["payload"]["certification_status"] == "certified"
    assert operations[1]["operation_type"] == "VALIDATION_BOND_REFUND"
    assert operations[1]["origin_type"] == "protocol"
    assert operations[1]["payload"]["bond_id"] == requested.bond.bond_id
    assert operations[1]["payload"]["refund_q"] == 250.0


def test_validation_bond_forfeit_records_canonical_ledger_operation() -> None:
    service = _hypervisor()
    validation_service = ValidationService(ValidationStore())
    service.bind_validation_service(validation_service)

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
        outcome="fail",
        validator_label="validator-a",
        evidence_summary="failed maintenance",
    )
    operations = service.list_ledger_operations()[-2:]

    assert operations[0]["operation_type"] == "CERTIFICATION_STATE_UPDATE"
    assert operations[0]["payload"]["certification_status"] == "revoked"
    assert operations[1]["operation_type"] == "VALIDATION_BOND_FORFEIT"
    assert operations[1]["origin_type"] == "evidence_triggered"
    assert operations[1]["payload"]["bond_id"] == requested.bond.bond_id
    assert operations[1]["payload"]["endpoint_id"] == "ep-1"


def test_endpoint_publish_and_update_record_canonical_ledger_operations() -> None:
    service = _hypervisor()
    endpoint_service = EndpointService(EndpointStore())
    endpoint_service.operation_recorder = service.record_ledger_operation

    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet="wallet-1",
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    updated = endpoint_service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={"streaming": True, "timeout": 45},
        )
    )
    operations = service.list_ledger_operations()[-2:]

    assert created.endpoint.endpoint_id == updated.endpoint.endpoint_id
    assert operations[0]["operation_type"] == "ENDPOINT_PUBLISH"
    assert operations[0]["sender_wallet"] == "wallet-1"
    assert operations[0]["payload"]["endpoint_id"] == created.endpoint.endpoint_id
    assert (
        operations[0]["payload"]["endpoint_configuration_hash"]
        == created.endpoint.configuration_hash
    )
    assert operations[1]["operation_type"] == "ENDPOINT_UPDATE"
    assert operations[1]["sender_wallet"] == "wallet-1"
    assert operations[1]["payload"]["endpoint_id"] == created.endpoint.endpoint_id
    assert (
        operations[1]["payload"]["previous_configuration_hash"]
        == created.endpoint.configuration_hash
    )
    assert (
        operations[1]["payload"]["next_configuration_hash"]
        == updated.endpoint.configuration_hash
    )
