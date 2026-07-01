from datetime import datetime, timedelta, timezone

from aidn_hypervisor.bundle_registry import FileBundleRegistry
from aidn_hypervisor.domain.models import AllocationRequest, BundleConfig, NodeCapacity, ResourceProfile
from aidn_hypervisor.main import build_app
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.wallet import quote_usage_q
from fastapi.testclient import TestClient


def _bundle(bundle_id: str, workload_type: str) -> BundleConfig:
    return BundleConfig(
        bundle_id=bundle_id,
        plugin_id="fake-managed",
        provider_type="fake",
        workload_type=workload_type,
        model_id=f"{bundle_id}-model",
        launch_mode="managed_process",
        device_affinity="cpu",
        resource_profile=ResourceProfile(),
        warm_policy="auto",
    )


class UsageMeteringPlugin(FakeManagedPlugin):
    plugin_id = "fake-usage-metering"

    def invoke(self, task, runtime_handle) -> dict:
        return {
            "ok": True,
            "task_type": task.task_type,
            "usage": {
                "input_tokens": 250_000,
                "output_tokens": 500_000,
                "fixed_request_count": 1,
                "measurement_kind": "exact",
                "measurement_source": "provider_api",
            },
        }


class InvalidUsageMeteringPlugin(FakeManagedPlugin):
    plugin_id = "fake-invalid-usage-metering"

    def invoke(self, task, runtime_handle) -> dict:
        return {
            "ok": True,
            "task_type": task.task_type,
            "usage": {
                "input_tokens": 250_000,
                "output_tokens": 500_000,
                "fixed_request_count": 1,
                "measurement_kind": "approximate",
                "measurement_source": "provider_api",
            },
        }


class StrictInvalidUsageMeteringPlugin(InvalidUsageMeteringPlugin):
    plugin_id = "fake-strict-invalid-usage-metering"

    def usage_contract(self) -> dict:
        return {
            "supports_exact": True,
            "supports_estimated": True,
            "default_measurement_source": "provider_api",
            "fallback_measurement_source": "provider_api_partial",
            "fallback_policy": "partial_response_estimate",
            "missing_usage_behavior": "strict_accounting",
        }


class StrictMissingUsageMeteringPlugin(FakeManagedPlugin):
    plugin_id = "fake-strict-missing-usage-metering"

    def invoke(self, task, runtime_handle) -> dict:
        return {"ok": True, "task_type": task.task_type}

    def usage_contract(self) -> dict:
        return {
            "supports_exact": True,
            "supports_estimated": True,
            "default_measurement_source": "provider_api",
            "fallback_measurement_source": "provider_api_partial",
            "fallback_policy": "partial_response_estimate",
            "missing_usage_behavior": "strict_accounting",
        }


def _service(
    *,
    plugin=None,
    bundle: BundleConfig | None = None,
    wallet_usage_retention_limit: int | None = None,
    wallet_allocation_grace_period_seconds: int = 300,
) -> HypervisorService:
    plugins = PluginRegistry()
    active_plugin = plugin or FakeManagedPlugin()
    plugins.register(active_plugin)
    active_bundle = bundle or _bundle("phi4-local", "llm_text")
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(cpu_cores=8.0, ram_mb=16384, vram_mb={"gpu0": 8192})
        ),
        bundles=[active_bundle],
        plugins=plugins,
        runtimes=ProviderProcessManager(),
        bundle_registry=FileBundleRegistry("bundles.json"),
        node_id="node-a",
        operator_id="operator-a",
        pricing={
            "unit": "q_per_1kk_tokens",
            "input": 12,
            "output": 18,
            "fixed_request": 4,
        },
        wallet_usage_retention_limit=wallet_usage_retention_limit,
        wallet_allocation_grace_period_seconds=wallet_allocation_grace_period_seconds,
    )


def test_quote_usage_q_calculates_q_from_input_output_and_fixed_request() -> None:
    quote = quote_usage_q(
        pricing={
            "unit": "q_per_1kk_tokens",
            "input": 12,
            "output": 18,
            "fixed_request": 4,
        },
        input_tokens=250_000,
        output_tokens=500_000,
        fixed_request_count=2,
    )

    assert quote["pricing"]["input"] == 12
    assert quote["charges"] == {
        "input_q": 3.0,
        "output_q": 9.0,
        "fixed_q": 8.0,
        "total_q": 20.0,
    }


def test_service_records_wallet_usage_event_and_emits_journal_event() -> None:
    service = _service()

    event = service.record_wallet_usage(
        owner_id="agent-a",
        bundle_id="phi4-local",
        workload_type="llm_text",
        input_tokens=250_000,
        output_tokens=500_000,
        fixed_request_count=1,
    )

    assert event["owner_id"] == "agent-a"
    assert event["node_id"] == "node-a"
    assert event["bundle_id"] == "phi4-local"
    assert event["quote"]["charges"]["total_q"] == 16.0
    assert service.list_wallet_usage_events() == [event]
    assert service.event_journal(limit=1)[0].event_type == "wallet.usage_recorded"


def test_service_snapshot_and_restore_preserves_wallet_usage_events() -> None:
    service = _service()
    event = service.record_wallet_usage(
        owner_id="agent-a",
        bundle_id="phi4-local",
        workload_type="llm_text",
        input_tokens=100_000,
        output_tokens=200_000,
    )
    snapshot = service.snapshot_state()

    restored = _service()
    restored.restore_state(snapshot)

    assert restored.list_wallet_usage_events() == [event]


def test_operator_wallet_quote_and_usage_endpoints() -> None:
    service = _service()
    client = TestClient(build_app(service=service))

    quote_response = client.post(
        "/operators/wallet/quote",
        json={
            "input_tokens": 250000,
            "output_tokens": 500000,
            "fixed_request_count": 1,
        },
    )

    assert quote_response.status_code == 200
    assert quote_response.json()["charges"]["total_q"] == 16.0

    record_response = client.post(
        "/operators/wallet/usage",
        json={
            "owner_id": "agent-a",
            "bundle_id": "phi4-local",
            "workload_type": "llm_text",
            "input_tokens": 250000,
            "output_tokens": 500000,
            "fixed_request_count": 1,
            "source": "manual",
        },
    )

    assert record_response.status_code == 201
    assert record_response.json()["quote"]["charges"]["total_q"] == 16.0

    list_response = client.get("/operators/wallet/usage")

    assert list_response.status_code == 200
    assert list_response.json()[0]["owner_id"] == "agent-a"


def test_service_automatically_records_wallet_usage_from_completed_task() -> None:
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(update={"plugin_id": "fake-usage-metering"}),
    )

    task = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"wallet_owner_id": "agent-a"},
        )
    )

    usage_events = service.list_wallet_usage_events()

    assert service.get_task(task.task_id).status == "completed"
    assert len(usage_events) == 1
    assert usage_events[0]["owner_id"] == "agent-a"
    assert usage_events[0]["task_id"] == task.task_id
    assert usage_events[0]["measurement_kind"] == "exact"
    assert usage_events[0]["measurement_source"] == "provider_api"
    assert usage_events[0]["quote"]["charges"]["total_q"] == 16.0


def test_service_automatically_records_allocation_id_from_completed_task() -> None:
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )

    task = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={
                "wallet_owner_id": "agent-a",
                "allocation_id": allocation["allocation_id"],
            },
        )
    )

    usage_events = service.list_wallet_usage_events()

    assert service.get_task(task.task_id).status == "completed"
    assert usage_events[0]["allocation_id"] == allocation["allocation_id"]


def test_service_derives_wallet_owner_from_allocation_when_task_owner_constraint_is_missing() -> None:
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )

    task = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )

    usage_events = service.list_wallet_usage_events()

    assert service.get_task(task.task_id).status == "completed"
    assert len(usage_events) == 1
    assert usage_events[0]["owner_id"] == "agent-a"
    assert usage_events[0]["allocation_id"] == allocation["allocation_id"]
    assert usage_events[0]["task_id"] == task.task_id


def test_service_emits_wallet_allocation_activation_hook_on_create() -> None:
    service = _service(
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={"endpoint": "http://127.0.0.1:8080"}
        )
    )

    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    activation_events = [
        event
        for event in service.event_journal()
        if event.event_type == "wallet.allocation_activated"
    ]

    assert len(activation_events) == 1
    assert activation_events[0].details["sequence_id"] == 1
    assert activation_events[0].details["event_id"]
    assert activation_events[0].details["activation_source"] == "create"
    assert activation_events[0].details["allocation_id"] == allocation["allocation_id"]
    assert activation_events[0].details["owner_id"] == "agent-a"
    assert activation_events[0].details["bundle_id"] == "phi4-local"
    assert activation_events[0].details["workload_type"] == "llm_text"
    assert activation_events[0].details["runtime_id"] == allocation["runtime_id"]
    assert activation_events[0].details["endpoint"] == "http://127.0.0.1:8080"
    assert activation_events[0].details["lease_seconds"] == 300


def test_service_emits_wallet_allocation_activation_hook_when_pending_lease_activates() -> None:
    service = _service(
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "endpoint": "http://127.0.0.1:8080",
                "resource_profile": ResourceProfile(
                    steady_cpu=2.0,
                    steady_ram_mb=2048,
                ),
            }
        )
    )
    service.resources.reserve("busy", cpu=7.0, ram_mb=15000, vram_mb=0)

    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
            policy="wait",
        )
    )

    assert allocation["status"] == "pending"
    assert [
        event
        for event in service.event_journal()
        if event.event_type == "wallet.allocation_activated"
    ] == []

    service.resources.release("busy")
    activated = service.get_allocation(allocation["allocation_id"])
    activation_events = [
        event
        for event in service.event_journal()
        if event.event_type == "wallet.allocation_activated"
    ]

    assert activated["status"] == "active"
    assert len(activation_events) == 1
    assert activation_events[0].details["sequence_id"] == 1
    assert activation_events[0].details["event_id"]
    assert activation_events[0].details["activation_source"] == "pending_reconcile"
    assert activation_events[0].details["allocation_id"] == allocation["allocation_id"]
    assert activation_events[0].details["owner_id"] == "agent-a"
    assert activation_events[0].details["bundle_id"] == "phi4-local"
    assert activation_events[0].details["workload_type"] == "llm_text"
    assert activation_events[0].details["runtime_id"] == activated["runtime_id"]
    assert activation_events[0].details["endpoint"] == "http://127.0.0.1:8080"
    assert activation_events[0].details["lease_seconds"] == 300


def test_service_lists_wallet_allocation_activation_events() -> None:
    service = _service(
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={"endpoint": "http://127.0.0.1:8080"}
        )
    )
    first = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    second = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-b",
            bundle_id="phi4-local",
        )
    )

    events = service.list_wallet_allocation_activation_events()

    assert len(events) == 2
    assert events[0]["allocation_id"] == first["allocation_id"]
    assert events[0]["activation_source"] == "create"
    assert events[1]["allocation_id"] == second["allocation_id"]
    assert events[1]["owner_id"] == "agent-b"


def test_service_records_wallet_allocation_finalization_on_release() -> None:
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )

    service.release_allocation(allocation["allocation_id"])
    finalization_events = service.list_wallet_allocation_events()

    assert len(finalization_events) == 1
    assert finalization_events[0]["allocation_id"] == allocation["allocation_id"]
    assert finalization_events[0]["owner_id"] == "agent-a"
    assert finalization_events[0]["status"] == "released"
    assert finalization_events[0]["settlement_status"] == "grace"
    assert finalization_events[0]["grace_expires_at"] is not None
    assert finalization_events[0]["closed_at"] is None
    assert finalization_events[0]["usage_event_count"] == 1
    assert finalization_events[0]["usage_total_q"] == 16.0


def test_service_records_wallet_allocation_finalization_on_expiry() -> None:
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )
    service._allocations[allocation["allocation_id"]]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()

    expired = service.get_allocation(allocation["allocation_id"])
    finalization_events = service.list_wallet_allocation_events()

    assert expired["status"] == "expired"
    assert len(finalization_events) == 1
    assert finalization_events[0]["allocation_id"] == allocation["allocation_id"]
    assert finalization_events[0]["status"] == "expired"
    assert finalization_events[0]["settlement_status"] == "grace"
    assert finalization_events[0]["usage_event_count"] == 1
    assert finalization_events[0]["usage_total_q"] == 16.0


def test_service_closes_wallet_allocation_finalization_after_grace_period(
    monkeypatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
        wallet_allocation_grace_period_seconds=30,
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )

    service.release_allocation(allocation["allocation_id"])
    during_grace = dict(service.list_wallet_allocation_events()[0])
    current_time[0] += 31
    after_grace = dict(service.list_wallet_allocation_events()[0])

    assert during_grace["settlement_status"] == "grace"
    assert after_grace["settlement_status"] == "closed"
    assert after_grace["closed_at"] is not None


def test_service_reopens_closed_wallet_allocation_finalization_with_new_grace_period(
    monkeypatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
        wallet_allocation_grace_period_seconds=30,
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )

    service.release_allocation(allocation["allocation_id"])
    current_time[0] += 31
    closed = dict(service.list_wallet_allocation_events()[0])

    reopened = service.reopen_wallet_allocation_event(
        closed["event_id"], reason="late provider usage"
    )
    current_time[0] += 31
    reclosed = dict(service.list_wallet_allocation_events()[0])

    assert closed["settlement_status"] == "closed"
    assert reopened["settlement_status"] == "grace"
    assert reopened["closed_at"] is None
    assert reopened["reopened_at"] is not None
    assert reopened["reopen_reason"] == "late provider usage"
    assert reopened["reopen_count"] == 1
    assert reopened["grace_expires_at"] != closed["grace_expires_at"]
    assert reclosed["settlement_status"] == "closed"
    assert reclosed["closed_at"] is not None


def test_service_opens_dispute_during_grace_and_prevents_auto_close_until_resolved(
    monkeypatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
        wallet_allocation_grace_period_seconds=30,
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )

    service.release_allocation(allocation["allocation_id"])
    disputed = service.dispute_wallet_allocation_event(
        service.list_wallet_allocation_events()[0]["event_id"],
        reason="provider usage mismatch",
    )
    original_grace_expiry = disputed["grace_expires_at"]
    current_time[0] += 31
    still_disputed = dict(service.list_wallet_allocation_events()[0])
    resolved = service.resolve_wallet_allocation_dispute(
        disputed["event_id"],
        resolution="accepted",
        reason="late usage accepted",
    )
    current_time[0] += 31
    reclosed = dict(service.list_wallet_allocation_events()[0])

    assert disputed["settlement_status"] == "grace"
    assert disputed["closed_at"] is None
    assert disputed["grace_expires_at"] == original_grace_expiry
    assert disputed["dispute_status"] == "open"
    assert disputed["dispute_id"] is not None
    assert disputed["dispute_opened_at"] is not None
    assert disputed["dispute_reason"] == "provider usage mismatch"
    assert disputed["dispute_opened_by"] == "operator-a"
    assert still_disputed["settlement_status"] == "grace"
    assert still_disputed["dispute_status"] == "open"
    assert resolved["settlement_status"] == "grace"
    assert resolved["dispute_status"] == "resolved"
    assert resolved["dispute_resolution"] == "accepted"
    assert resolved["dispute_resolution_reason"] == "late usage accepted"
    assert resolved["dispute_resolved_at"] is not None
    assert resolved["reopened_at"] is not None
    assert resolved["grace_expires_at"] is not None
    assert reclosed["settlement_status"] == "closed"
    assert reclosed["closed_at"] is not None


def test_operator_wallet_usage_export_supports_after_event_cursor() -> None:
    service = _service()
    first = service.record_wallet_usage(
        owner_id="agent-a",
        bundle_id="phi4-local",
        workload_type="llm_text",
        input_tokens=10_000,
        output_tokens=20_000,
    )
    second = service.record_wallet_usage(
        owner_id="agent-b",
        bundle_id="phi4-local",
        workload_type="llm_text",
        input_tokens=30_000,
        output_tokens=40_000,
    )
    client = TestClient(build_app(service=service))

    response = client.get(
        "/operators/wallet/usage/export",
        params={"after_event_id": first["event_id"], "limit": 10},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [second],
        "next_after_event_id": second["event_id"],
        "next_after_sequence": second["sequence_id"],
        "retained_from_sequence": first["sequence_id"],
        "retained_through_sequence": second["sequence_id"],
        "watermark_sequence": second["sequence_id"],
        "has_more": False,
        "cursor_status": "ok",
    }


def test_operator_wallet_allocation_export_reports_finalization_events() -> None:
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )
    finalization = service.release_allocation(allocation["allocation_id"])
    client = TestClient(build_app(service=service))

    response = client.get("/operators/wallet/allocations/export", params={"limit": 10})

    assert finalization["status"] == "released"
    assert response.status_code == 200
    assert response.json() == {
        "items": [service.list_wallet_allocation_events()[0]],
        "next_after_event_id": service.list_wallet_allocation_events()[0]["event_id"],
        "next_after_sequence": service.list_wallet_allocation_events()[0]["sequence_id"],
        "retained_from_sequence": service.list_wallet_allocation_events()[0]["sequence_id"],
        "retained_through_sequence": service.list_wallet_allocation_events()[0]["sequence_id"],
        "watermark_sequence": service.list_wallet_allocation_events()[0]["sequence_id"],
        "has_more": False,
        "cursor_status": "ok",
    }


def test_operator_wallet_allocation_activation_export_reports_events() -> None:
    service = _service(
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={"endpoint": "http://127.0.0.1:8080"}
        )
    )
    first = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    second = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-b",
            bundle_id="phi4-local",
        )
    )
    client = TestClient(build_app(service=service))

    response = client.get(
        "/operators/wallet/allocations/activations/export",
        params={"after_sequence": 1, "limit": 10},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [service.list_wallet_allocation_activation_events()[1]],
        "next_after_event_id": service.list_wallet_allocation_activation_events()[1]["event_id"],
        "next_after_sequence": service.list_wallet_allocation_activation_events()[1]["sequence_id"],
        "retained_from_sequence": service.list_wallet_allocation_activation_events()[0]["sequence_id"],
        "retained_through_sequence": service.list_wallet_allocation_activation_events()[1]["sequence_id"],
        "watermark_sequence": service.list_wallet_allocation_activation_events()[1]["sequence_id"],
        "has_more": False,
        "cursor_status": "ok",
    }
    assert first["allocation_id"] != second["allocation_id"]


def test_operator_wallet_allocation_reopen_endpoint_reopens_closed_finalization(
    monkeypatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
        wallet_allocation_grace_period_seconds=30,
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )
    service.release_allocation(allocation["allocation_id"])
    current_time[0] += 31
    event_id = service.list_wallet_allocation_events()[0]["event_id"]
    client = TestClient(build_app(service=service))

    response = client.post(
        f"/operators/wallet/allocations/{event_id}/reopen",
        json={"reason": "operator dispute"},
    )

    assert response.status_code == 200
    assert response.json()["event_id"] == event_id
    assert response.json()["settlement_status"] == "grace"
    assert response.json()["closed_at"] is None
    assert response.json()["reopen_reason"] == "operator dispute"
    assert response.json()["reopen_count"] == 1


def test_operator_wallet_allocation_dispute_endpoints_manage_settlement(
    monkeypatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
        wallet_allocation_grace_period_seconds=30,
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )
    service.release_allocation(allocation["allocation_id"])
    current_time[0] += 31
    event_id = service.list_wallet_allocation_events()[0]["event_id"]
    client = TestClient(build_app(service=service))

    current_time[0] += 31
    dispute_response = client.post(
        f"/operators/wallet/allocations/{event_id}/dispute",
        json={"reason": "operator dispute"},
    )
    resolve_response = client.post(
        f"/operators/wallet/allocations/{event_id}/dispute/resolve",
        json={"resolution": "rejected", "reason": "manual settlement override"},
    )

    assert dispute_response.status_code == 200
    assert dispute_response.json()["event_id"] == event_id
    assert dispute_response.json()["settlement_status"] == "closed"
    assert dispute_response.json()["dispute_status"] == "open"
    assert dispute_response.json()["dispute_reason"] == "operator dispute"
    assert dispute_response.json()["dispute_id"] is not None
    assert resolve_response.status_code == 200
    assert resolve_response.json()["event_id"] == event_id
    assert resolve_response.json()["settlement_status"] == "closed"
    assert resolve_response.json()["dispute_status"] == "resolved"
    assert resolve_response.json()["dispute_resolution"] == "rejected"
    assert (
        resolve_response.json()["dispute_resolution_reason"]
        == "manual settlement override"
    )


def test_operator_wallet_allocation_dispute_export_reports_open_and_resolve_events(
    monkeypatch,
) -> None:
    current_time = [1_781_827_800.0]
    monkeypatch.setattr("aidn_hypervisor.service.time.time", lambda: current_time[0])
    service = _service(
        plugin=UsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={
                "plugin_id": "fake-usage-metering",
                "endpoint": "http://127.0.0.1:8080",
            }
        ),
        wallet_allocation_grace_period_seconds=30,
    )
    allocation = service.create_allocation(
        AllocationRequest(
            workload_type="llm_text",
            owner_id="agent-a",
            bundle_id="phi4-local",
        )
    )
    service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"allocation_id": allocation["allocation_id"]},
        )
    )
    service.release_allocation(allocation["allocation_id"])
    event_id = service.list_wallet_allocation_events()[0]["event_id"]
    client = TestClient(build_app(service=service))

    client.post(
        f"/operators/wallet/allocations/{event_id}/dispute",
        json={"reason": "operator dispute"},
    )
    client.post(
        f"/operators/wallet/allocations/{event_id}/dispute/resolve",
        json={"resolution": "accepted", "reason": "late usage accepted"},
    )
    response = client.get(
        "/operators/wallet/allocations/disputes/export",
        params={"limit": 10},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["event_type"] == "opened"
    assert response.json()["items"][1]["event_type"] == "resolved"
    assert response.json()["items"][0]["allocation_event_id"] == event_id
    assert response.json()["items"][1]["allocation_event_id"] == event_id


def test_operator_wallet_usage_export_reports_retention_window_metadata() -> None:
    service = _service(wallet_usage_retention_limit=2)
    first = service.record_wallet_usage(
        owner_id="agent-a",
        bundle_id="phi4-local",
        workload_type="llm_text",
        input_tokens=10_000,
        output_tokens=20_000,
    )
    second = service.record_wallet_usage(
        owner_id="agent-b",
        bundle_id="phi4-local",
        workload_type="llm_text",
        input_tokens=30_000,
        output_tokens=40_000,
    )
    third = service.record_wallet_usage(
        owner_id="agent-c",
        bundle_id="phi4-local",
        workload_type="llm_text",
        input_tokens=50_000,
        output_tokens=60_000,
    )
    client = TestClient(build_app(service=service))

    response = client.get("/operators/wallet/usage/export", params={"limit": 10})

    assert response.status_code == 200
    assert response.json() == {
        "items": [second, third],
        "next_after_event_id": third["event_id"],
        "next_after_sequence": third["sequence_id"],
        "retained_from_sequence": second["sequence_id"],
        "retained_through_sequence": third["sequence_id"],
        "watermark_sequence": third["sequence_id"],
        "has_more": False,
        "cursor_status": "ok",
    }
    assert all(item["event_id"] != first["event_id"] for item in response.json()["items"])


def test_operator_wallet_usage_export_marks_stale_after_sequence_cursor() -> None:
    service = _service(wallet_usage_retention_limit=2)
    first = service.record_wallet_usage(
        owner_id="agent-a",
        bundle_id="phi4-local",
        workload_type="llm_text",
        input_tokens=10_000,
        output_tokens=20_000,
    )
    second = service.record_wallet_usage(
        owner_id="agent-b",
        bundle_id="phi4-local",
        workload_type="llm_text",
        input_tokens=30_000,
        output_tokens=40_000,
    )
    third = service.record_wallet_usage(
        owner_id="agent-c",
        bundle_id="phi4-local",
        workload_type="llm_text",
        input_tokens=50_000,
        output_tokens=60_000,
    )
    fourth = service.record_wallet_usage(
        owner_id="agent-d",
        bundle_id="phi4-local",
        workload_type="llm_text",
        input_tokens=70_000,
        output_tokens=80_000,
    )
    client = TestClient(build_app(service=service))

    response = client.get(
        "/operators/wallet/usage/export",
        params={"after_sequence": first["sequence_id"], "limit": 10},
    )

    assert response.status_code == 200
    assert response.json() == {
        "items": [third, fourth],
        "next_after_event_id": fourth["event_id"],
        "next_after_sequence": fourth["sequence_id"],
        "retained_from_sequence": third["sequence_id"],
        "retained_through_sequence": fourth["sequence_id"],
        "watermark_sequence": fourth["sequence_id"],
        "has_more": False,
        "cursor_status": "stale",
    }


def test_operator_wallet_usage_endpoint_accepts_allocation_id() -> None:
    service = _service()
    client = TestClient(build_app(service=service))

    response = client.post(
        "/operators/wallet/usage",
        json={
            "owner_id": "agent-a",
            "allocation_id": "alloc-123",
            "bundle_id": "phi4-local",
            "workload_type": "llm_text",
            "input_tokens": 1000,
            "output_tokens": 2000,
            "fixed_request_count": 1,
            "measurement_kind": "estimated",
            "measurement_source": "tokenizer_guess",
            "source": "manual",
        },
    )

    assert response.status_code == 201
    assert response.json()["allocation_id"] == "alloc-123"
    assert response.json()["measurement_kind"] == "estimated"
    assert response.json()["measurement_source"] == "tokenizer_guess"


def test_service_skips_invalid_provider_usage_contract_without_failing_task() -> None:
    service = _service(
        plugin=InvalidUsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={"plugin_id": "fake-invalid-usage-metering"}
        ),
    )

    task = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"wallet_owner_id": "agent-a"},
        )
    )

    assert service.get_task(task.task_id).status == "completed"
    assert service.list_wallet_usage_events() == []
    assert service.event_journal(limit=1)[0].event_type == "wallet.usage_skipped"


def test_service_marks_task_unbillable_when_strict_accounting_rejects_invalid_usage() -> None:
    service = _service(
        plugin=StrictInvalidUsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={"plugin_id": "fake-strict-invalid-usage-metering"}
        ),
    )

    task = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"wallet_owner_id": "agent-a"},
        )
    )

    result = service.task_result(task.task_id)
    journal_event = service.event_journal(limit=1)[0]

    assert service.get_task(task.task_id).status == "completed"
    assert service.list_wallet_usage_events() == []
    assert result is not None
    assert result["wallet_accounting"] == {
        "status": "unbillable",
        "settlement_status": "blocked",
        "reason": "invalid_provider_usage_contract",
    }
    assert journal_event.event_type == "wallet.usage_skipped"
    assert journal_event.details["billing_status"] == "unbillable"
    assert journal_event.details["settlement_status"] == "blocked"
    assert journal_event.details["reason"] == "invalid_provider_usage_contract"


def test_service_marks_task_unbillable_when_strict_accounting_usage_is_missing() -> None:
    service = _service(
        plugin=StrictMissingUsageMeteringPlugin(),
        bundle=_bundle("phi4-local", "llm_text").model_copy(
            update={"plugin_id": "fake-strict-missing-usage-metering"}
        ),
    )

    task = service.submit(
        TaskRequest(
            task_type="llm_text.generate",
            payload={"prompt": "hello"},
            constraints={"wallet_owner_id": "agent-a"},
        )
    )

    result = service.task_result(task.task_id)
    journal_event = service.event_journal(limit=1)[0]

    assert service.get_task(task.task_id).status == "completed"
    assert service.list_wallet_usage_events() == []
    assert result is not None
    assert result["wallet_accounting"] == {
        "status": "unbillable",
        "settlement_status": "blocked",
        "reason": "missing_provider_usage",
    }
    assert journal_event.event_type == "wallet.usage_skipped"
    assert journal_event.details["billing_status"] == "unbillable"
    assert journal_event.details["settlement_status"] == "blocked"
    assert journal_event.details["reason"] == "missing_provider_usage"
