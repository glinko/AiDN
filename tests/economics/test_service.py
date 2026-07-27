from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


def _service() -> HypervisorService:
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        node_id="node-a",
        operator_id="operator-a",
    )


def test_record_recyclable_removal_is_snapshotted_and_restored() -> None:
    service = _service()

    removal = service.record_recyclable_removal(
        category="network_fee",
        amount_q=2.5,
        owner_id="wallet-1",
        source_event_type="session_network_fee_charged",
        source_reference="session-1",
        source_epoch_id="epoch-10",
    )

    snapshot = service.snapshot_state()
    restored = _service()
    restored.restore_state(snapshot)

    assert removal["category"] == "network_fee"
    assert restored.list_recyclable_removals() == [removal]
    economics_events = [
        event for event in restored.list_wallet_ledger_events() if event["stream"] == "economics"
    ]
    assert len(economics_events) == 1
    assert economics_events[0]["amount_q"] == 2.5
    assert economics_events[0]["payload"]["category"] == "network_fee"


def test_derive_next_epoch_reward_budget_uses_previous_epoch_removals_and_carryover() -> None:
    service = _service()
    service.record_recyclable_removal(
        category="network_fee",
        amount_q=10.0,
        owner_id="wallet-1",
        source_event_type="session_network_fee_charged",
        source_reference="session-1",
        source_epoch_id="epoch-10",
    )
    service.record_recyclable_removal(
        category="validation_bond_forfeiture",
        amount_q=500.0,
        owner_id="wallet-2",
        source_event_type="validation_bond_forfeited",
        source_reference="bond-1",
        source_epoch_id="epoch-10",
    )

    budget = service.derive_epoch_reward_budget(
        epoch_id="epoch-11",
        source_epoch_id="epoch-10",
        recycle_backlog_q=25.0,
        faucet_carryover_q=40.0,
        active_hypervisor_count=25,
    )

    assert budget["eligible_removed_q"] == 510.0
    assert budget["recycle_backlog_q"] == 25.0
    assert budget["recyclable_amount_q"] == 535.0
    assert budget["total_authorized_q"] == 5535.0
    assert budget["faucet_budget_q"] == 593.5
    assert budget["faucet_share_q"] == 23.74


def test_validation_bond_forfeiture_records_recyclable_removal() -> None:
    hypervisor = _service()
    validation_service = ValidationService(ValidationStore())
    hypervisor.bind_validation_service(validation_service)

    requested = validation_service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-10T00:00:00+00:00",
    )

    validation_service.resolve_maintenance(
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        outcome="fail",
        validator_label="validator-a",
        evidence_summary="failed maintenance",
    )

    removals = hypervisor.list_recyclable_removals()

    assert len(removals) == 1
    assert removals[0]["category"] == "validation_bond_forfeiture"
    assert removals[0]["amount_q"] == 500.0
    assert removals[0]["source_reference"] == requested.bond.bond_id


def test_session_settlement_records_network_fee_recyclable_removal() -> None:
    hypervisor = _service()
    session_service = SessionService(SessionStore(), event_recorder=hypervisor.record_event)
    hypervisor.session_service = session_service

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
    )

    closed = session_service.close_session(opened.session.session_id)
    removals = hypervisor.list_recyclable_removals()

    assert closed.settlement is not None
    assert closed.settlement.network_fee_q == 0.01
    assert len(removals) == 1
    assert removals[0]["category"] == "network_fee"
    assert removals[0]["amount_q"] == 0.01
    assert removals[0]["source_reference"] == opened.session.session_id


def test_economics_summary_aggregates_removals_and_latest_budget() -> None:
    service = _service()
    first = service.record_recyclable_removal(
        category="network_fee",
        amount_q=10.0,
        owner_id="wallet-1",
        source_event_type="session_network_fee_charged",
        source_reference="session-1",
        source_epoch_id="epoch-10",
    )
    second = service.record_recyclable_removal(
        category="validation_bond_forfeiture",
        amount_q=500.0,
        owner_id="wallet-2",
        source_event_type="validation_bond_forfeited",
        source_reference="bond-1",
        source_epoch_id="epoch-10",
    )
    budget = service.derive_epoch_reward_budget(
        epoch_id="epoch-11",
        source_epoch_id="epoch-10",
        recycle_backlog_q=25.0,
        faucet_carryover_q=40.0,
        active_hypervisor_count=25,
    )

    summary = service.get_wallet_economics_summary()

    assert summary["base_emission_q"] == 5000.0
    assert summary["pool_shares"] == {
        "consensus": 0.3,
        "registry": 0.3,
        "validation": 0.3,
        "faucet": 0.1,
    }
    assert summary["removals"] == {
        "count": 2,
        "total_q": 510.0,
        "by_category": {
            "network_fee": 10.0,
            "validation_bond_forfeiture": 500.0,
        },
        "by_epoch": {"epoch-10": 510.0},
        "latest_removed_at": second["removed_at"],
    }
    assert summary["latest_budget"] == budget
    assert summary["recent_removals"] == [second, first]
    assert summary["recycling"] == {
        "eligible_removed_q": 510.0,
        "recycle_backlog_q": 25.0,
        "recyclable_amount_q": 535.0,
    }
    assert summary["faucet"] == {
        "carryover_q": 40.0,
        "budget_q": 593.5,
        "active_hypervisor_count": 25,
        "share_q": 23.74,
        "claimed": False,
        "claimed_q": 0.0,
        "remaining_q": 23.74,
        "claim": None,
    }
    assert summary["pools"] == {
        "consensus_budget_q": 1660.5,
        "registry_budget_q": 1660.5,
        "validation_budget_q": 1660.5,
        "faucet_budget_q": 593.5,
    }
    assert summary["latest_budget_breakdown"] == {
        "epoch_id": "epoch-11",
        "total_authorized_q": 5535.0,
        "faucet_share_q": 23.74,
    }


def test_economics_summary_respects_zero_recent_limit() -> None:
    service = _service()
    service.record_recyclable_removal(
        category="network_fee",
        amount_q=1.0,
        owner_id="wallet-1",
        source_event_type="session_network_fee_charged",
        source_reference="session-1",
    )

    summary = service.get_wallet_economics_summary(recent_limit=0)

    assert summary["recent_removals"] == []


def test_economics_export_stitches_removals_and_epoch_budgets() -> None:
    service = _service()
    removal = service.record_recyclable_removal(
        category="network_fee",
        amount_q=10.0,
        owner_id="wallet-1",
        source_event_type="session_network_fee_charged",
        source_reference="session-1",
        source_epoch_id="epoch-10",
    )
    budget = service.derive_epoch_reward_budget(
        epoch_id="epoch-11",
        source_epoch_id="epoch-10",
        recycle_backlog_q=25.0,
        faucet_carryover_q=40.0,
        active_hypervisor_count=25,
    )

    exported = service.export_wallet_economics_events(limit=10)

    assert [item["event_type"] for item in exported["items"]] == [
        "recyclable_removed",
        "epoch_reward_budget_derived",
    ]
    assert exported["items"][0]["payload"]["removal_id"] == removal["removal_id"]
    assert exported["items"][1]["payload"]["epoch_id"] == budget["epoch_id"]
    assert exported["retained_from_sequence"] == exported["items"][0]["sequence_id"]
    assert exported["retained_through_sequence"] == exported["items"][-1]["sequence_id"]
    assert exported["watermark_sequence"] == exported["items"][-1]["sequence_id"]
    assert exported["cursor_status"] == "ok"


def test_faucet_claim_updates_summary_and_economics_export() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    service.endpoint_service = endpoint_service
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Active Endpoint",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    endpoint_service.start_endpoint(created.endpoint.endpoint_id)
    service.derive_epoch_reward_budget(
        epoch_id="epoch-21",
        source_epoch_id="epoch-20",
        active_hypervisor_count=4,
    )

    preview = service.get_faucet_claim_preview()
    claimed = service.claim_faucet_share()
    summary = service.get_wallet_economics_summary()
    exported = service.export_wallet_economics_events(limit=10)

    assert preview["eligible"] is True
    assert preview["reason"] == "eligible"
    assert preview["share_q"] == 125.0
    assert preview["active_local_endpoint_count"] == 1
    assert claimed["claimed"] is True
    assert claimed["eligible"] is False
    assert claimed["reason"] == "already_claimed"
    assert claimed["claimed_q"] == 125.0
    assert claimed["remaining_q"] == 0.0
    assert claimed["claim"]["epoch_id"] == "epoch-21"
    assert claimed["claim"]["amount_q"] == 125.0
    assert summary["faucet"]["share_q"] == 125.0
    assert summary["faucet"]["claimed"] is True
    assert summary["faucet"]["claimed_q"] == 125.0
    assert summary["faucet"]["remaining_q"] == 0.0
    assert summary["faucet"]["claim"]["claim_id"] == claimed["claim"]["claim_id"]
    assert [item["event_type"] for item in exported["items"]] == [
        "epoch_reward_budget_derived",
        "faucet_claimed",
    ]
    assert exported["items"][-1]["payload"]["claim_id"] == claimed["claim"]["claim_id"]


def test_faucet_claim_records_protocol_reward_mint() -> None:
    service = _service()
    endpoint_service = EndpointService(EndpointStore())
    service.endpoint_service = endpoint_service
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="bundle-a",
            bundle_hash="bundle-hash-a",
            display_name="Active Endpoint",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    endpoint_service.start_endpoint(created.endpoint.endpoint_id)
    service.derive_epoch_reward_budget(
        epoch_id="epoch-21",
        source_epoch_id="epoch-20",
        active_hypervisor_count=4,
    )

    claimed = service.claim_faucet_share()
    operation = service.list_ledger_operations()[-1]

    assert claimed["claim"]["amount_q"] == 125.0
    assert operation["operation_type"] == "REWARD_MINT"
    assert operation["origin_type"] == "protocol"
    assert operation["payload"]["reward_type"] == "faucet"
    assert operation["payload"]["reward_epoch"] == "epoch-21"
    assert operation["payload"]["recipient_wallet"] == service.owner_wallet_state()["wallet_id"]
    assert operation["payload"]["amount"] == 125.0


def test_faucet_preview_reports_ineligible_without_active_endpoint() -> None:
    service = _service()
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    service.derive_epoch_reward_budget(
        epoch_id="epoch-21",
        source_epoch_id="epoch-20",
        active_hypervisor_count=4,
    )

    preview = service.get_faucet_claim_preview()

    assert preview["eligible"] is False
    assert preview["reason"] == "no_active_endpoints"
    assert preview["claimed"] is False
    assert preview["remaining_q"] == 125.0


def test_derive_epoch_reward_budget_records_protocol_epoch_transition() -> None:
    service = _service()
    service.record_recyclable_removal(
        category="network_fee",
        amount_q=25.0,
        owner_id="wallet-1",
        source_event_type="session_network_fee_charged",
        source_reference="session-1",
        source_epoch_id="epoch-10",
    )

    budget = service.derive_epoch_reward_budget(
        epoch_id="epoch-11",
        source_epoch_id="epoch-10",
        recycle_backlog_q=15.0,
        faucet_carryover_q=40.0,
        active_hypervisor_count=25,
    )
    operation = service.list_ledger_operations()[-1]

    assert budget["epoch_id"] == "epoch-11"
    assert operation["operation_type"] == "EPOCH_TRANSITION"
    assert operation["origin_type"] == "protocol"
    assert operation["payload"]["closing_epoch"] == "epoch-10"
    assert operation["payload"]["opening_epoch"] == "epoch-11"
    assert operation["payload"]["reward_budget_reference"] == "epoch-11"
