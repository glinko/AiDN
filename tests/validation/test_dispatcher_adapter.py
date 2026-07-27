"""Tests for ValidationDispatcherAdapter — VALIDATION_REPORT_TRANSFER through submit→drain_once."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from aidn_hypervisor.dispatcher import NetworkDispatcher
from aidn_hypervisor.dispatcher.store import DispatcherStore
from aidn_hypervisor.validation.channel import (
    ValidationReportTransferChannel,
    ValidationReportTransferMessage,
)
from aidn_hypervisor.validation.custody_store import ValidationReportCustodyStore
from aidn_hypervisor.validation.dispatcher_adapter import ValidationDispatcherAdapter
from aidn_hypervisor.validation.models import (
    ValidationReport,
    ValidationReportTransferEnvelope,
    validation_report_integrity,
)
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_validation_service(tmp_path: Path):
    """ValidationService with custody_store, a queued+authorized request ready for transfer."""
    custody_root = tmp_path / "custody"
    custody_root.mkdir()
    custody_store = ValidationReportCustodyStore(custody_root)

    store = ValidationStore()
    dispatcher_store = DispatcherStore()
    service = ValidationService(store, custody_store=custody_store, dispatcher_store=dispatcher_store)

    # Create and authorize a validation request
    req_outcome = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    assign_outcome = service.assign_epoch_requests(
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
    return service, req_outcome, assign_outcome


def _build_report_and_envelope(
    request,
    assignment,
    authorization,
) -> tuple[ValidationReport, ValidationReportTransferEnvelope]:
    """Build a ValidationReport + TransferEnvelope matching the stored request."""
    now = datetime.now(UTC).isoformat()
    report = ValidationReport(
        report_id=f"report-{uuid4().hex[:8]}",
        request_id=request.request_id,
        endpoint_id=request.endpoint_id,
        configuration_hash=request.configuration_hash,
        report_kind="initial",
        validator_label="validator-a",
        recommendation="certify",
        evidence_summary="all checks passed",
        created_at=now,
    )
    report_hash, report_size = validation_report_integrity(report)
    envelope = ValidationReportTransferEnvelope(
        transfer_id=f"transfer-{uuid4().hex[:8]}",
        report_id=report.report_id,
        request_id=request.request_id,
        assignment_id=assignment.assignment_id,
        authorization_id=authorization.authorization_id,
        endpoint_id=request.endpoint_id,
        endpoint_configuration_hash=request.configuration_hash,
        report_hash=report_hash,
        report_size=report_size,
        report_locator=f"aidn://endpoint/{request.endpoint_id}/validation/{report_hash}",
        created_at=now,
    )
    return report, envelope


def _make_dispatcher() -> NetworkDispatcher:
    return NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidationDispatcherAdapter:
    """VALIDATION_REPORT_TRANSFER routed through NetworkDispatcher.submit() + drain_once()."""

    def test_submit_queues_message(self, tmp_path: Path) -> None:
        service, req_out, assign_out = _build_validation_service(tmp_path)
        channel = ValidationReportTransferChannel(service)
        dispatcher = _make_dispatcher()
        adapter = ValidationDispatcherAdapter(dispatcher, channel)

        report, envelope = _build_report_and_envelope(
            req_out.request,
            assign_out.assignments[0],
            assign_out.authorizations[0],
        )

        result = adapter.submit_validation_report(
            envelope=envelope.model_dump(),
            report=report.model_dump(),
        )

        assert result["delivery_state"] == "QUEUED"
        assert dispatcher.queue_depth == 1

    def test_drain_once_delivers_and_invokes_channel_handler(self, tmp_path: Path) -> None:
        service, req_out, assign_out = _build_validation_service(tmp_path)
        channel = ValidationReportTransferChannel(service)
        dispatcher = _make_dispatcher()
        adapter = ValidationDispatcherAdapter(dispatcher, channel)

        report, envelope = _build_report_and_envelope(
            req_out.request,
            assign_out.assignments[0],
            assign_out.authorizations[0],
        )

        adapter.submit_validation_report(
            envelope=envelope.model_dump(),
            report=report.model_dump(),
        )

        result = adapter.drain_validation_results()
        assert result is not None
        record, handler_result = result

        assert record["delivery_state"] == "APPLICATION_ACCEPTED"
        assert handler_result["acknowledgment"] == "PROCESSED"
        assert handler_result["replayed"] is False
        assert dispatcher.queue_depth == 0

    def test_drain_empty_queue_returns_none(self, tmp_path: Path) -> None:
        service, _, _ = _build_validation_service(tmp_path)
        channel = ValidationReportTransferChannel(service)
        dispatcher = _make_dispatcher()
        adapter = ValidationDispatcherAdapter(dispatcher, channel)

        assert adapter.drain_validation_results() is None

    def test_submit_then_drain_full_pipeline(self, tmp_path: Path) -> None:
        """End-to-end: submit → drain_once → handler processes report."""
        service, req_out, assign_out = _build_validation_service(tmp_path)
        channel = ValidationReportTransferChannel(service)
        dispatcher = _make_dispatcher()
        adapter = ValidationDispatcherAdapter(dispatcher, channel)

        report, envelope = _build_report_and_envelope(
            req_out.request,
            assign_out.assignments[0],
            assign_out.authorizations[0],
        )

        # Submit
        submit_result = adapter.submit_validation_report(
            envelope=envelope.model_dump(),
            report=report.model_dump(),
        )
        assert submit_result["delivery_state"] == "QUEUED"

        # Drain
        result = adapter.drain_validation_results()
        assert result is not None
        record, handler_result = result
        assert record["delivery_state"] == "APPLICATION_ACCEPTED"
        assert handler_result["acknowledgment"] == "PROCESSED"

        # Verify the report was actually stored
        stored_report = service.store.get_report(report.report_id)
        assert stored_report.report_id == report.report_id

    def test_duplicate_message_returns_duplicate_state(self, tmp_path: Path) -> None:
        """Submitting the same message_id twice after drain returns DUPLICATE."""
        service, req_out, assign_out = _build_validation_service(tmp_path)
        channel = ValidationReportTransferChannel(service)
        dispatcher = _make_dispatcher()
        adapter = ValidationDispatcherAdapter(dispatcher, channel)

        report, envelope = _build_report_and_envelope(
            req_out.request,
            assign_out.assignments[0],
            assign_out.authorizations[0],
        )

        # First submit + drain
        first = adapter.submit_validation_report(
            message_id="dup-msg-1",
            envelope=envelope.model_dump(),
            report=report.model_dump(),
        )
        assert first["delivery_state"] == "QUEUED"

        drained = adapter.drain_validation_results()
        assert drained is not None
        assert drained[0]["delivery_state"] == "APPLICATION_ACCEPTED"

        # Re-submit same message_id after processing → DUPLICATE
        second = adapter.submit_validation_report(
            message_id="dup-msg-1",
            envelope=envelope.model_dump(),
            report=report.model_dump(),
        )

        assert second["delivery_state"] == "DUPLICATE"

    def test_drain_all_processes_multiple_messages(self, tmp_path: Path) -> None:
        """Multiple submits are drained in order."""
        service, req_out, assign_out = _build_validation_service(tmp_path)
        channel = ValidationReportTransferChannel(service)
        dispatcher = _make_dispatcher()
        adapter = ValidationDispatcherAdapter(dispatcher, channel)

        report_a, envelope_a = _build_report_and_envelope(
            req_out.request,
            assign_out.assignments[0],
            assign_out.authorizations[0],
        )
        report_b, envelope_b = _build_report_and_envelope(
            req_out.request,
            assign_out.assignments[0],
            assign_out.authorizations[0],
        )

        adapter.submit_validation_report(
            message_id="msg-a",
            envelope=envelope_a.model_dump(),
            report=report_a.model_dump(),
        )
        adapter.submit_validation_report(
            message_id="msg-b",
            envelope=envelope_b.model_dump(),
            report=report_b.model_dump(),
        )

        assert dispatcher.queue_depth == 2

        results = adapter.drain_all()
        assert len(results) == 2
        assert all(r[0]["delivery_state"] == "APPLICATION_ACCEPTED" for r in results)
        assert dispatcher.queue_depth == 0

    def test_adapter_registers_validation_route(self, tmp_path: Path) -> None:
        """The adapter registers the VALIDATION channel route on init."""
        service, _, _ = _build_validation_service(tmp_path)
        channel = ValidationReportTransferChannel(service)
        dispatcher = _make_dispatcher()

        route_before = dispatcher.route(
            destination_type="VALIDATION_TARGET",
            destination_id="validation_handler",
        )
        assert route_before is None

        ValidationDispatcherAdapter(dispatcher, channel)

        route_after = dispatcher.route(
            destination_type="VALIDATION_TARGET",
            destination_id="validation_handler",
        )
        assert route_after is not None
        assert route_after.route_state == "ACTIVE"
        assert "VALIDATION_REPORT_TRANSFER" in route_after.allowed_message_types
        assert "VALIDATION" in route_after.allowed_channel_classes

    def test_channel_replay_detected_via_dispatcher(self, tmp_path: Path) -> None:
        """Re-sending the same message_id after drain returns replayed=True."""
        service, req_out, assign_out = _build_validation_service(tmp_path)
        channel = ValidationReportTransferChannel(service)
        dispatcher = _make_dispatcher()
        adapter = ValidationDispatcherAdapter(dispatcher, channel)

        report, envelope = _build_report_and_envelope(
            req_out.request,
            assign_out.assignments[0],
            assign_out.authorizations[0],
        )

        # First delivery
        adapter.submit_validation_report(
            message_id="replay-msg",
            envelope=envelope.model_dump(),
            report=report.model_dump(),
        )
        result1 = adapter.drain_validation_results()
        assert result1 is not None
        assert result1[1]["replayed"] is False

        # Re-submit same message_id — dispatcher sees it as duplicate
        dup = adapter.submit_validation_report(
            message_id="replay-msg",
            envelope=envelope.model_dump(),
            report=report.model_dump(),
        )
        assert dup["delivery_state"] == "DUPLICATE"

    def test_replay_survives_dispatcher_store_restore(self, tmp_path: Path) -> None:
        """Replay records persist through DispatcherStore flush/restore cycle."""
        from aidn_hypervisor.persistence import FileStateStore

        custody_root = tmp_path / "custody"
        custody_root.mkdir()
        custody_store = ValidationReportCustodyStore(custody_root)
        state_store = FileStateStore(tmp_path / "state.json")

        # Phase 1: first service instance processes a message
        store1 = ValidationStore(state_store)
        dstore1 = DispatcherStore(state_store)
        service1 = ValidationService(store1, custody_store=custody_store, dispatcher_store=dstore1)
        req_out = service1.request_validation(
            endpoint_id="ep-1",
            owner_wallet="wallet-1",
            configuration_hash="cfg-1",
            minimum_session_deposit_q=25.0,
        )
        assign_out = service1.assign_epoch_requests(
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

        report, envelope = _build_report_and_envelope(
            req_out.request,
            assign_out.assignments[0],
            assign_out.authorizations[0],
        )

        channel1 = ValidationReportTransferChannel(service1)
        result = channel1.handle(
            ValidationReportTransferMessage(
                message_id="persist-replay-1",
                envelope=envelope,
                report=report,
            )
        )
        assert result["replayed"] is False

        # Phase 2: restore both stores from persistence
        store2 = ValidationStore(state_store)
        dstore2 = DispatcherStore(state_store)
        service2 = ValidationService(store2, custody_store=custody_store, dispatcher_store=dstore2)

        channel2 = ValidationReportTransferChannel(service2)
        result2 = channel2.handle(
            ValidationReportTransferMessage(
                message_id="persist-replay-1",
                envelope=envelope,
                report=report,
            )
        )
        assert result2["replayed"] is True
