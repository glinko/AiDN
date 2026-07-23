import stat
from datetime import datetime, timedelta, timezone

import pytest

from aidn_hypervisor.validation.custody_store import ValidationReportCustodyStore
from aidn_hypervisor.validation.channel import (
    ValidationReportTransferChannel,
    ValidationReportTransferMessage,
)
from aidn_hypervisor.dispatcher import (
    DispatcherRoute,
    NetworkDispatcher,
    NetworkMessage,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.models import canonical_payload_bytes
from aidn_hypervisor.dispatcher.store import DispatcherStore
from aidn_hypervisor.validation.custody_signing import (
    Ed25519ValidationReportCustodySigner,
    verify_storage_receipt,
)
from aidn_hypervisor.validation.transfer_signing import (
    Ed25519ValidationReportTransferSigner,
    verify_report_transfer_envelope,
)
from aidn_hypervisor.validation.models import ValidationReport, validation_report_integrity
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


def _report(*, report_id: str = "report-1", signature: str = "signature-1") -> ValidationReport:
    return ValidationReport(
        report_id=report_id,
        request_id="req-1",
        endpoint_id="ep-1",
        configuration_hash="cfg-1",
        report_kind="initial",
        validator_label="validator-a",
        recommendation="certify",
        evidence_summary="all checks passed",
        signed_payload={"signature": signature},
        created_at="2026-07-18T00:00:00+00:00",
    )


def test_custody_store_promotes_and_reads_immutable_report_body(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    first = custody.store_report(_report())
    second = custody.store_report(_report(report_id="report-2", signature="signature-2"))

    assert first.report_hash == second.report_hash
    assert first.storage_relative_path == second.storage_relative_path
    assert custody.read_report_body(first.report_hash) == {
        "accounting_verification": {},
        "capability_id": None,
        "configuration_hash": "cfg-1",
        "created_at": "2026-07-18T00:00:00+00:00",
        "critical_issue_count": 0,
        "detected_issues": [],
        "endpoint_id": "ep-1",
        "evidence_summary": "all checks passed",
        "measured_metrics": {},
        "observations": [],
        "protocol_compliance": {},
        "recommendation": "certify",
        "report_kind": "initial",
        "request_id": "req-1",
        "request_summary": None,
        "response_summary": None,
        "test_description": None,
        "validator_id": None,
        "validator_label": "validator-a",
        "warning_issue_count": 0,
    }


def test_custody_store_detects_corrupted_payload(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    stored = custody.store_report(_report())
    payload_path = tmp_path / "custody" / stored.storage_relative_path
    payload_path.chmod(stat.S_IREAD | stat.S_IWRITE)
    payload_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="content hash mismatch"):
        custody.verify_report(stored.report_hash)


def test_custody_store_rejects_invalid_hash_before_path_resolution(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")

    with pytest.raises(ValueError, match="sha256"):
        custody.read_report_body("../../outside")


def test_validation_service_writes_custody_object_when_configured(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    service = ValidationService(ValidationStore(), custody_store=custody)
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

    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    report_hash, report_size = validation_report_integrity(outcome.report)

    assert outcome.custody_object is not None
    assert outcome.custody_object.report_hash == report_hash
    assert outcome.custody_object.report_size == report_size
    assert service.store.get_report_custody_object(report_hash) == outcome.custody_object
    assert service.get_custody_report_body(report_hash)["endpoint_id"] == "ep-1"


def test_custody_metadata_survives_file_state_restore(tmp_path) -> None:
    state_store = FileStateStore(tmp_path / "state.json")
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    service = ValidationService(ValidationStore(state_store), custody_store=custody)
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
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )

    restored = ValidationStore(state_store)

    assert outcome.custody_object is not None
    assert restored.list_report_custody_objects() == [outcome.custody_object]


def test_storage_receipt_is_signed_and_idempotent(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    signer = Ed25519ValidationReportCustodySigner("11" * 32)
    operations: list[dict] = []
    service = ValidationService(
        ValidationStore(),
        custody_store=custody,
        custody_signer=signer,
        operation_recorder=lambda **item: operations.append(item),
    )
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
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )

    first = service.create_report_storage_receipt(report_id=outcome.report.report_id)
    second = service.create_report_storage_receipt(report_id=outcome.report.report_id)

    verify_storage_receipt(first)
    assert second == first
    assert len(service.store.list_report_storage_receipts()) == 1
    assert first.report_hash == outcome.commitment.report_hash
    assert operations[-1]["operation_type"] == "VALIDATION_REPORT_STORAGE_RECEIPT"
    assert operations[-1]["payload"]["receipt_id"] == first.receipt_id


def test_positive_certification_can_require_storage_receipt(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    signer = Ed25519ValidationReportCustodySigner("44" * 32)
    service = ValidationService(
        ValidationStore(),
        custody_store=custody,
        custody_signer=signer,
        require_storage_receipt_for_positive_certification=True,
    )
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
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )

    pending = service.validation_summary("ep-1", configuration_hash="cfg-1")
    service.create_report_storage_receipt(report_id=outcome.report.report_id)
    finalized = service.validation_summary("ep-1", configuration_hash="cfg-1")

    assert outcome.snapshot.certification_status == "pending_initial"
    assert pending["certification_status"] == "pending_initial"
    assert pending["validated_at"] is None
    assert finalized["certification_status"] == "certified"
    assert finalized["validated_at"] == outcome.report.created_at


def test_report_transfer_envelope_binds_assignment_and_authorization(tmp_path) -> None:
    service = ValidationService(
        ValidationStore(),
        custody_store=ValidationReportCustodyStore(tmp_path / "custody"),
    )
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    assigned = service.assign_epoch_requests(
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
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )

    envelope = service.build_report_transfer_envelope(report_id=outcome.report.report_id)

    assert envelope.assignment_id == assigned.assignments[0].assignment_id
    assert envelope.authorization_id == assigned.authorizations[0].authorization_id
    assert envelope.report_hash == outcome.commitment.report_hash


def test_report_transfer_envelope_can_be_signed_by_validator(tmp_path) -> None:
    service = ValidationService(
        ValidationStore(),
        custody_store=ValidationReportCustodyStore(tmp_path / "custody"),
        transfer_signer=Ed25519ValidationReportTransferSigner("55" * 32),
    )
    requested = service.request_validation(
        endpoint_id="ep-1",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
    )
    service.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[{"validator_id": "val-1", "validator_label": "validator-a", "shares": 1, "capability_profiles": ["llm_text"], "contribution_q": 500.0}],
        seed="seed-1",
    )
    outcome = service.submit_validation_report(request_id=requested.request.request_id, outcome="pass", validator_label="validator-a", evidence_summary="all checks passed")

    envelope = service.build_report_transfer_envelope(report_id=outcome.report.report_id)

    verify_report_transfer_envelope(envelope)
    assert envelope.validator_public_key is not None
    assert envelope.validator_signature is not None


def test_receiver_accepts_signed_report_transfer_into_custody(tmp_path) -> None:
    signer = Ed25519ValidationReportTransferSigner("66" * 32)
    sender = ValidationService(
        ValidationStore(),
        custody_store=ValidationReportCustodyStore(tmp_path / "sender-custody"),
        transfer_signer=signer,
    )
    requested = sender.request_validation(endpoint_id="ep-1", owner_wallet="wallet-1", configuration_hash="cfg-1", minimum_session_deposit_q=25.0)
    sender.assign_epoch_requests(epoch_id="epoch-1", validator_entries=[{"validator_id": "val-1", "validator_label": "validator-a", "shares": 1, "capability_profiles": ["llm_text"], "contribution_q": 500.0}], seed="seed-1")
    outcome = sender.submit_validation_report(request_id=requested.request.request_id, outcome="pass", validator_label="validator-a", evidence_summary="all checks passed")
    envelope = sender.build_report_transfer_envelope(report_id=outcome.report.report_id)

    receiver = ValidationService(
        ValidationStore(),
        custody_store=ValidationReportCustodyStore(tmp_path / "receiver-custody"),
        require_signed_transfer_envelope=True,
    )
    receiver.store.save_request(sender.store.get_request(requested.request.request_id))
    receiver.store.save_assignment(sender.store.list_assignments()[0])
    receiver.store.save_authorization(sender.store.list_authorizations()[0])

    accepted = receiver.accept_report_transfer(envelope=envelope, report=outcome.report)

    assert accepted.report_hash == outcome.commitment.report_hash
    assert receiver.get_custody_report_body(accepted.report_hash)["endpoint_id"] == "ep-1"
    assert receiver.store.get_report_commitment(outcome.report.report_id).report_hash == accepted.report_hash


def test_validation_channel_transfer_is_idempotent_and_rejects_conflict(tmp_path) -> None:
    signer = Ed25519ValidationReportTransferSigner("77" * 32)
    sender = ValidationService(ValidationStore(), custody_store=ValidationReportCustodyStore(tmp_path / "sender"), transfer_signer=signer)
    requested = sender.request_validation(endpoint_id="ep-1", owner_wallet="wallet-1", configuration_hash="cfg-1", minimum_session_deposit_q=25.0)
    sender.assign_epoch_requests(epoch_id="epoch-1", validator_entries=[{"validator_id": "val-1", "validator_label": "validator-a", "shares": 1, "capability_profiles": ["llm_text"], "contribution_q": 500.0}], seed="seed-1")
    outcome = sender.submit_validation_report(request_id=requested.request.request_id, outcome="pass", validator_label="validator-a", evidence_summary="all checks passed")
    receiver = ValidationService(ValidationStore(), custody_store=ValidationReportCustodyStore(tmp_path / "receiver"), require_signed_transfer_envelope=True, dispatcher_store=DispatcherStore())
    receiver.store.save_request(sender.store.get_request(requested.request.request_id))
    receiver.store.save_assignment(sender.store.list_assignments()[0])
    receiver.store.save_authorization(sender.store.list_authorizations()[0])
    channel = ValidationReportTransferChannel(receiver)
    message = ValidationReportTransferMessage(message_id="msg-1", envelope=sender.build_report_transfer_envelope(report_id=outcome.report.report_id), report=outcome.report)

    first = channel.handle(message)
    replayed = channel.handle(message)
    conflicting = message.model_copy(update={"report": outcome.report.model_copy(update={"evidence_summary": "tampered"})})

    assert first["replayed"] is False
    assert replayed["replayed"] is True
    with pytest.raises(ValueError, match="replay conflicts"):
        channel.handle(conflicting)


def test_validation_channel_replay_survives_store_restore(tmp_path) -> None:
    state_store = FileStateStore(tmp_path / "state.json")
    signer = Ed25519ValidationReportTransferSigner("88" * 32)
    sender = ValidationService(ValidationStore(), custody_store=ValidationReportCustodyStore(tmp_path / "sender"), transfer_signer=signer)
    requested = sender.request_validation(endpoint_id="ep-1", owner_wallet="wallet-1", configuration_hash="cfg-1", minimum_session_deposit_q=25.0)
    sender.assign_epoch_requests(epoch_id="epoch-1", validator_entries=[{"validator_id": "val-1", "validator_label": "validator-a", "shares": 1, "capability_profiles": ["llm_text"], "contribution_q": 500.0}], seed="seed-1")
    outcome = sender.submit_validation_report(request_id=requested.request.request_id, outcome="pass", validator_label="validator-a", evidence_summary="all checks passed")
    receiver_store = ValidationStore(state_store)
    receiver_store.save_request(sender.store.get_request(requested.request.request_id))
    receiver_store.save_assignment(sender.store.list_assignments()[0])
    receiver_store.save_authorization(sender.store.list_authorizations()[0])
    dispatcher_store = DispatcherStore(state_store)
    receiver = ValidationService(receiver_store, custody_store=ValidationReportCustodyStore(tmp_path / "receiver"), require_signed_transfer_envelope=True, dispatcher_store=dispatcher_store)
    message = ValidationReportTransferMessage(message_id="msg-persistent", envelope=sender.build_report_transfer_envelope(report_id=outcome.report.report_id), report=outcome.report)

    assert ValidationReportTransferChannel(receiver).handle(message)["replayed"] is False
    restored_dispatcher_store = DispatcherStore(state_store)
    restored_receiver = ValidationService(ValidationStore(state_store), custody_store=ValidationReportCustodyStore(tmp_path / "receiver"), require_signed_transfer_envelope=True, dispatcher_store=restored_dispatcher_store)

    assert ValidationReportTransferChannel(restored_receiver).handle(message)["replayed"] is True


def test_validation_transfer_runs_through_network_dispatcher(tmp_path) -> None:
    signer = Ed25519ValidationReportTransferSigner("99" * 32)
    sender = ValidationService(ValidationStore(), custody_store=ValidationReportCustodyStore(tmp_path / "sender"), transfer_signer=signer)
    requested = sender.request_validation(endpoint_id="ep-1", owner_wallet="wallet-1", configuration_hash="cfg-1", minimum_session_deposit_q=25.0)
    sender.assign_epoch_requests(epoch_id="epoch-1", validator_entries=[{"validator_id": "val-1", "validator_label": "validator-a", "shares": 1, "capability_profiles": ["llm_text"], "contribution_q": 500.0}], seed="seed-1")
    outcome = sender.submit_validation_report(request_id=requested.request.request_id, outcome="pass", validator_label="validator-a", evidence_summary="all checks passed")
    receiver = ValidationService(ValidationStore(), custody_store=ValidationReportCustodyStore(tmp_path / "receiver"), require_signed_transfer_envelope=True, dispatcher_store=DispatcherStore())
    receiver.store.save_request(sender.store.get_request(requested.request.request_id))
    receiver.store.save_assignment(sender.store.list_assignments()[0])
    receiver.store.save_authorization(sender.store.list_authorizations()[0])
    channel = ValidationReportTransferChannel(receiver)
    transfer = ValidationReportTransferMessage(message_id="inner-msg-1", envelope=sender.build_report_transfer_envelope(report_id=outcome.report.report_id), report=outcome.report)
    payload = transfer.model_dump(mode="json")
    dispatcher = NetworkDispatcher(network_id="aidn-test", chain_id="chain-test", network_revision="rev-1")
    dispatcher.register_local_route(DispatcherRoute(destination_type="ENDPOINT", destination_id="ep-1", route_type="LOCAL_PROTOCOL_HANDLER", route_generation=1, allowed_source_types={"SERVICE"}, allowed_channel_classes={"VALIDATION"}, allowed_message_types={"VALIDATION_REPORT_TRANSFER"}, created_at="2026-07-18T00:00:00+00:00"), channel.dispatcher_handler)
    now = datetime.now(timezone.utc)
    network_message = NetworkMessage(message_id="network-msg-1", message_type="VALIDATION_REPORT_TRANSFER", network_id="aidn-test", chain_id="chain-test", network_revision="rev-1", channel_id="validation-1", channel_class="VALIDATION", source_subject={"subject_type": "SERVICE", "subject_id": "val-1"}, destination_subject={"subject_type": "ENDPOINT", "subject_id": "ep-1"}, source_sequence=1, route_generation=1, created_at=now.isoformat(), expiration=(now + timedelta(minutes=5)).isoformat(), payload_hash=canonical_payload_hash(payload), payload_length=len(canonical_payload_bytes(payload)), payload=payload)

    assert dispatcher.submit(network_message).delivery_state == "QUEUED"
    delivered, result = dispatcher.drain_once()

    assert delivered.delivery_state == "APPLICATION_ACCEPTED"
    assert result["acknowledgment"] == "PROCESSED"
    assert receiver.get_custody_report_body(outcome.commitment.report_hash)["endpoint_id"] == "ep-1"


def test_storage_receipt_rejects_tampered_custody_payload(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    signer = Ed25519ValidationReportCustodySigner("22" * 32)
    service = ValidationService(
        ValidationStore(),
        custody_store=custody,
        custody_signer=signer,
    )
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
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    assert outcome.custody_object is not None
    payload_path = tmp_path / "custody" / outcome.custody_object.storage_relative_path
    payload_path.chmod(stat.S_IREAD | stat.S_IWRITE)
    payload_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="content hash mismatch"):
        service.create_report_storage_receipt(report_id=outcome.report.report_id)


def test_validation_read_models_expose_custody_metadata_without_report_body(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    signer = Ed25519ValidationReportCustodySigner("33" * 32)
    service = ValidationService(
        ValidationStore(),
        custody_store=custody,
        custody_signer=signer,
    )
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
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    receipt = service.create_report_storage_receipt(report_id=outcome.report.report_id)

    summary = service.validation_summary("ep-1", configuration_hash="cfg-1")
    history = service.validation_history("ep-1")

    assert summary["latest_report_commitment"]["report_hash"] == outcome.commitment.report_hash
    assert summary["latest_report_custody"]["report_hash"] == outcome.commitment.report_hash
    assert summary["latest_report_storage_receipt"]["receipt_id"] == receipt.receipt_id
    assert summary["custody_object_present"] is True
    assert summary["storage_receipt_present"] is True
    assert history["report_commitments"] == [outcome.commitment.model_dump(mode="json")]
    assert history["report_custody_objects"] == [outcome.custody_object.model_dump(mode="json")]
    assert history["report_storage_receipts"] == [receipt.model_dump(mode="json")]
    assert "report_body" not in history


def test_storage_failure_is_idempotent_and_preserves_negative_report(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    operations: list[dict] = []
    service = ValidationService(
        ValidationStore(),
        custody_store=custody,
        operation_recorder=lambda **item: operations.append(item),
    )
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
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="fail",
        validator_label="validator-a",
        evidence_summary="schema mismatch",
    )

    first = service.record_report_storage_failure(
        report_id=outcome.report.report_id,
        failure_code="REPORT_STORAGE_REFUSED",
        failure_details={"reason": "endpoint refused custody"},
        reported_by="val-1",
    )
    second = service.record_report_storage_failure(
        report_id=outcome.report.report_id,
        failure_code="REPORT_STORAGE_REFUSED",
        failure_details={"reason": "retry details do not duplicate event"},
        reported_by="val-1",
    )

    assert first == second
    assert outcome.snapshot.certification_status == "uncertified"
    assert operations[-1]["operation_type"] == "VALIDATION_REPORT_STORAGE_FAILURE"
    assert service.validation_history("ep-1")["report_storage_failures"] == [
        first.model_dump(mode="json")
    ]


def test_custody_check_distinguishes_available_missing_and_corrupted(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    service = ValidationService(ValidationStore(), custody_store=custody)
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
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    assert outcome.custody_object is not None

    available = service.check_report_custody(
        report_id=outcome.report.report_id,
        challenge_id="challenge-1",
    )
    payload_path = tmp_path / "custody" / outcome.custody_object.storage_relative_path
    payload_path.chmod(stat.S_IREAD | stat.S_IWRITE)
    payload_path.unlink()
    missing = service.check_report_custody(report_id=outcome.report.report_id)
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_text("{}", encoding="utf-8")
    corrupted = service.check_report_custody(report_id=outcome.report.report_id)

    assert available.status == "available"
    assert missing.status == "temporarily_unavailable"
    assert missing.failure_streak == 1
    assert corrupted.status == "corrupted"
    assert corrupted.failure_streak == 2
