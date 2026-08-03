import stat
from datetime import UTC, datetime, timedelta

import pytest

from aidn_hypervisor.dispatcher import (
    DispatcherRoute,
    NetworkDispatcher,
    NetworkMessage,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.models import canonical_payload_bytes
from aidn_hypervisor.dispatcher.store import DispatcherStore
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.validation.channel import (
    ValidationReportTransferChannel,
    ValidationReportTransferMessage,
)
from aidn_hypervisor.validation.custody_signing import (
    Ed25519ValidationReportCustodySigner,
    verify_storage_receipt,
)
from aidn_hypervisor.validation.custody_store import ValidationReportCustodyStore
from aidn_hypervisor.validation.models import ValidationReport, validation_report_integrity
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore
from aidn_hypervisor.validation.transfer_signing import (
    Ed25519ValidationReportTransferSigner,
    transfer_envelope_signing_payload,
    verify_report_transfer_envelope,
)


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
    metadata = service.report_custody_metadata(report_id=outcome.report.report_id)
    assert metadata["commitment"]["report_hash"] == report_hash
    assert metadata["custody_object"] == outcome.custody_object.model_dump(mode="json")
    assert metadata["custody_state"] is None


def test_public_custody_summary_is_aggregate_and_scope_bound(tmp_path) -> None:
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

    before_check = service.custody_summary("ep-1", configuration_hash="cfg-1")
    service.check_report_custody(report_id=outcome.report.report_id)
    after_check = service.custody_summary("ep-1", configuration_hash="cfg-1")

    assert before_check["custody_status"] == "not_checked"
    assert after_check == {
        "custody_status": "available",
        "report_count": 1,
        "checked_report_count": 1,
        "available_report_count": 1,
        "attention_report_count": 0,
        "latest_checked_at": after_check["latest_checked_at"],
    }
    assert after_check["latest_checked_at"] is not None
    assert "report_hash" not in after_check
    assert service.custody_summary("ep-1", configuration_hash="cfg-other")[
        "custody_status"
    ] == "not_reported"


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
    requested = sender.request_validation(
        endpoint_id="ep-1", owner_wallet="wallet-1", configuration_hash="cfg-1", minimum_session_deposit_q=25.0
    )
    sender.assign_epoch_requests(
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
    outcome = sender.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
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


def test_canonical_transfer_identity_binds_signature_to_assigned_validator(tmp_path) -> None:
    signer = Ed25519ValidationReportTransferSigner("aa" * 32)
    sender = ValidationService(
        ValidationStore(),
        custody_store=ValidationReportCustodyStore(tmp_path / "sender-custody"),
        transfer_signer=signer,
        require_canonical_validator_transfer_identity=True,
    )
    requested = sender.request_validation(
        endpoint_id="ep-1", owner_wallet="wallet-1", configuration_hash="cfg-1", minimum_session_deposit_q=25.0
    )
    binding = sender.register_validator_transfer_key(
        validator_id="val-1",
        transfer_public_key=signer.public_key,
        registered_at="2026-08-02T00:00:00+00:00",
    )
    sender.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {
                "validator_id": "val-1",
                "validator_label": "validator-a",
                "shares": 1,
            }
        ],
        seed="seed-1",
    )
    outcome = sender.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    envelope = sender.build_report_transfer_envelope(report_id=outcome.report.report_id)
    assert envelope.validator_id == "val-1"
    assert outcome.report.validator_id == "val-1"

    receiver = ValidationService(
        ValidationStore(),
        custody_store=ValidationReportCustodyStore(tmp_path / "receiver-custody"),
        require_signed_transfer_envelope=True,
        require_canonical_validator_transfer_identity=True,
    )
    receiver.store.save_request(sender.store.get_request(requested.request.request_id))
    receiver.store.save_assignment(sender.store.list_assignments()[0])
    receiver.store.save_authorization(sender.store.list_authorizations()[0])
    receiver.store.save_validator_entry(sender.store.list_validator_entries()[0])
    receiver.store.save_validator_key_binding(binding)

    accepted = receiver.accept_report_transfer(envelope=envelope, report=outcome.report)
    assert accepted.report_hash == outcome.commitment.report_hash

    attacker = Ed25519ValidationReportTransferSigner("bb" * 32)
    forged = envelope.model_copy(
        update={
            "validator_public_key": attacker.public_key,
            "validator_signature": None,
        }
    )
    forged = forged.model_copy(
        update={"validator_signature": attacker.sign(transfer_envelope_signing_payload(forged))}
    )
    with pytest.raises(ValueError, match="key does not match assigned validator"):
        receiver.accept_report_transfer(envelope=forged, report=outcome.report)


def test_validator_transfer_key_registry_is_idempotent_and_restart_persistent(tmp_path) -> None:
    state_store = FileStateStore(tmp_path / "state.json")
    signer = Ed25519ValidationReportTransferSigner("cc" * 32)
    service = ValidationService(ValidationStore(state_store))

    first = service.register_validator_transfer_key(
        validator_id="val-1",
        transfer_public_key=signer.public_key,
        registered_at="2026-08-02T00:00:00+00:00",
    )
    assert service.register_validator_transfer_key(
        validator_id="val-1",
        transfer_public_key=signer.public_key,
        registered_at="2026-08-02T00:00:00+00:00",
    ) == first
    with pytest.raises(ValueError, match="already registered"):
        service.register_validator_transfer_key(
            validator_id="val-1",
            transfer_public_key=Ed25519ValidationReportTransferSigner("dd" * 32).public_key,
        )
    with pytest.raises(ValueError, match="public key is invalid"):
        service.register_validator_transfer_key(
            validator_id="val-2",
            transfer_public_key="not-a-key",
        )

    restored = ValidationStore(state_store)
    assert restored.get_validator_key_binding("val-1") == first


def test_validation_channel_transfer_is_idempotent_and_rejects_conflict(tmp_path) -> None:
    signer = Ed25519ValidationReportTransferSigner("77" * 32)
    sender = ValidationService(
        ValidationStore(), custody_store=ValidationReportCustodyStore(tmp_path / "sender"), transfer_signer=signer
    )
    requested = sender.request_validation(
        endpoint_id="ep-1", owner_wallet="wallet-1", configuration_hash="cfg-1", minimum_session_deposit_q=25.0
    )
    sender.assign_epoch_requests(
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
    outcome = sender.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    receiver = ValidationService(
        ValidationStore(),
        custody_store=ValidationReportCustodyStore(tmp_path / "receiver"),
        require_signed_transfer_envelope=True,
        dispatcher_store=DispatcherStore(),
    )
    receiver.store.save_request(sender.store.get_request(requested.request.request_id))
    receiver.store.save_assignment(sender.store.list_assignments()[0])
    receiver.store.save_authorization(sender.store.list_authorizations()[0])
    channel = ValidationReportTransferChannel(receiver)
    message = ValidationReportTransferMessage(
        message_id="msg-1",
        envelope=sender.build_report_transfer_envelope(report_id=outcome.report.report_id),
        report=outcome.report,
    )

    first = channel.handle(message)
    replayed = channel.handle(message)
    conflicting = message.model_copy(
        update={"report": outcome.report.model_copy(update={"evidence_summary": "tampered"})}
    )

    assert first["replayed"] is False
    assert replayed["replayed"] is True
    with pytest.raises(ValueError, match="replay conflicts"):
        channel.handle(conflicting)


def test_validation_channel_replay_survives_store_restore(tmp_path) -> None:
    state_store = FileStateStore(tmp_path / "state.json")
    signer = Ed25519ValidationReportTransferSigner("88" * 32)
    sender = ValidationService(
        ValidationStore(), custody_store=ValidationReportCustodyStore(tmp_path / "sender"), transfer_signer=signer
    )
    requested = sender.request_validation(
        endpoint_id="ep-1", owner_wallet="wallet-1", configuration_hash="cfg-1", minimum_session_deposit_q=25.0
    )
    sender.assign_epoch_requests(
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
    outcome = sender.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    receiver_store = ValidationStore(state_store)
    receiver_store.save_request(sender.store.get_request(requested.request.request_id))
    receiver_store.save_assignment(sender.store.list_assignments()[0])
    receiver_store.save_authorization(sender.store.list_authorizations()[0])
    dispatcher_store = DispatcherStore(state_store)
    receiver = ValidationService(
        receiver_store,
        custody_store=ValidationReportCustodyStore(tmp_path / "receiver"),
        require_signed_transfer_envelope=True,
        dispatcher_store=dispatcher_store,
    )
    message = ValidationReportTransferMessage(
        message_id="msg-persistent",
        envelope=sender.build_report_transfer_envelope(report_id=outcome.report.report_id),
        report=outcome.report,
    )

    assert ValidationReportTransferChannel(receiver).handle(message)["replayed"] is False
    restored_dispatcher_store = DispatcherStore(state_store)
    restored_receiver = ValidationService(
        ValidationStore(state_store),
        custody_store=ValidationReportCustodyStore(tmp_path / "receiver"),
        require_signed_transfer_envelope=True,
        dispatcher_store=restored_dispatcher_store,
    )

    assert ValidationReportTransferChannel(restored_receiver).handle(message)["replayed"] is True


def test_validation_transfer_runs_through_network_dispatcher(tmp_path) -> None:
    signer = Ed25519ValidationReportTransferSigner("99" * 32)
    sender = ValidationService(
        ValidationStore(), custody_store=ValidationReportCustodyStore(tmp_path / "sender"), transfer_signer=signer
    )
    requested = sender.request_validation(
        endpoint_id="ep-1", owner_wallet="wallet-1", configuration_hash="cfg-1", minimum_session_deposit_q=25.0
    )
    sender.assign_epoch_requests(
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
    outcome = sender.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    receiver = ValidationService(
        ValidationStore(),
        custody_store=ValidationReportCustodyStore(tmp_path / "receiver"),
        require_signed_transfer_envelope=True,
        dispatcher_store=DispatcherStore(),
    )
    receiver.store.save_request(sender.store.get_request(requested.request.request_id))
    receiver.store.save_assignment(sender.store.list_assignments()[0])
    receiver.store.save_authorization(sender.store.list_authorizations()[0])
    channel = ValidationReportTransferChannel(receiver)
    transfer = ValidationReportTransferMessage(
        message_id="inner-msg-1",
        envelope=sender.build_report_transfer_envelope(report_id=outcome.report.report_id),
        report=outcome.report,
    )
    payload = transfer.model_dump(mode="json")
    dispatcher = NetworkDispatcher(network_id="aidn-test", chain_id="chain-test", network_revision="rev-1")
    dispatcher.register_local_route(
        DispatcherRoute(
            destination_type="ENDPOINT",
            destination_id="ep-1",
            route_type="LOCAL_PROTOCOL_HANDLER",
            route_generation=1,
            allowed_source_types={"SERVICE"},
            allowed_channel_classes={"VALIDATION"},
            allowed_message_types={"VALIDATION_REPORT_TRANSFER"},
            created_at="2026-07-18T00:00:00+00:00",
        ),
        channel.dispatcher_handler,
    )
    now = datetime.now(UTC)
    network_message = NetworkMessage(
        message_id="network-msg-1",
        message_type="VALIDATION_REPORT_TRANSFER",
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
        channel_id="validation-1",
        channel_class="VALIDATION",
        source_subject={"subject_type": "SERVICE", "subject_id": "val-1"},
        destination_subject={"subject_type": "ENDPOINT", "subject_id": "ep-1"},
        source_sequence=1,
        route_generation=1,
        created_at=now.isoformat(),
        expiration=(now + timedelta(minutes=5)).isoformat(),
        payload_hash=canonical_payload_hash(payload),
        payload_length=len(canonical_payload_bytes(payload)),
        payload=payload,
    )

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


def test_stable_custody_locator_enforces_endpoint_and_configuration_scope(tmp_path) -> None:
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

    body = service.get_custody_report_by_locator(
        outcome.commitment.report_locator,
        requester_endpoint_id="ep-1",
        configuration_hash="cfg-1",
    )
    assert body["endpoint_id"] == "ep-1"
    with pytest.raises(ValueError, match="Endpoint scope mismatch"):
        service.get_custody_report_by_locator(
            outcome.commitment.report_locator,
            requester_endpoint_id="ep-other",
            configuration_hash="cfg-1",
        )
    with pytest.raises(ValueError, match="configuration scope mismatch"):
        service.get_custody_report_by_locator(
            outcome.commitment.report_locator,
            requester_endpoint_id="ep-1",
            configuration_hash="cfg-other",
        )
    with pytest.raises(ValueError, match="invalid Validation Report locator"):
        service.get_custody_report_by_locator(
            outcome.commitment.report_locator + "?raw=1",
            requester_endpoint_id="ep-1",
        )


def test_custody_access_class_requires_authority_and_hash_only_never_serves_body(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    denied = ValidationService(
        ValidationStore(),
        custody_store=custody,
        custody_access_checker=lambda **_: False,
    )
    requested = denied.request_validation(
        endpoint_id="ep-restricted",
        owner_wallet="wallet-1",
        configuration_hash="cfg-1",
        minimum_session_deposit_q=25.0,
        evidence_access_class="restricted",
    )
    denied.assign_epoch_requests(
        epoch_id="epoch-1",
        validator_entries=[
            {"validator_id": "val-1", "validator_label": "validator-a", "shares": 1}
        ],
        seed="seed-1",
    )
    restricted = denied.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="restricted evidence",
    )
    with pytest.raises(PermissionError, match="access is not authorized"):
        denied.get_custody_report_by_locator(
            restricted.commitment.report_locator,
            requester_endpoint_id="ep-restricted",
            requester_subject="validator-1",
        )

    authorized = ValidationService(
        denied.store,
        custody_store=custody,
        custody_access_checker=lambda **_: True,
    )
    body = authorized.get_custody_report_by_locator(
        restricted.commitment.report_locator,
        requester_endpoint_id="ep-restricted",
        requester_subject="validator-1",
    )
    assert body["endpoint_id"] == "ep-restricted"

    hash_only_requested = authorized.request_validation(
        endpoint_id="ep-hash-only",
        owner_wallet="wallet-1",
        configuration_hash="cfg-2",
        minimum_session_deposit_q=25.0,
        evidence_access_class="hash_committed",
    )
    authorized.assign_epoch_requests(
        epoch_id="epoch-2",
        validator_entries=[
            {"validator_id": "val-2", "validator_label": "validator-b", "shares": 1}
        ],
        seed="seed-2",
    )
    hash_only = authorized.submit_validation_report(
        request_id=hash_only_requested.request.request_id,
        outcome="pass",
        validator_label="validator-b",
        evidence_summary="hash only",
    )
    with pytest.raises(PermissionError, match="hash-committed only"):
        authorized.get_custody_report_by_locator(
            hash_only.commitment.report_locator,
            requester_endpoint_id="ep-hash-only",
        )


def test_custody_challenge_is_idempotent_conflict_safe_and_persistent(tmp_path) -> None:
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
            {"validator_id": "val-1", "validator_label": "validator-a", "shares": 1}
        ],
        seed="seed-1",
    )
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )

    first = service.challenge_report_custody(
        report_id=outcome.report.report_id,
        challenge_id="challenge-1",
        challenger_id="validator-independent-1",
        checked_at="2026-08-02T00:00:00+00:00",
    )
    second = service.challenge_report_custody(
        report_id=outcome.report.report_id,
        challenge_id="challenge-1",
        challenger_id="validator-independent-1",
        checked_at="2026-08-02T00:01:00+00:00",
    )
    assert second == first
    assert first.outcome == "available"
    assert first.observed_report_size == outcome.commitment.report_size
    with pytest.raises(ValueError, match="conflicts with prior identity"):
        service.challenge_report_custody(
            report_id=outcome.report.report_id,
            challenge_id="challenge-1",
            challenger_id="validator-independent-2",
        )

    restored = ValidationStore(state_store)
    assert restored.get_report_custody_challenge("challenge-1") == first


def test_custody_challenge_quorum_collapses_known_control_groups(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    operations: list[dict] = []
    service = ValidationService(
        ValidationStore(),
        custody_store=custody,
        custody_challenge_quorum=2,
        custody_known_control_groups={
            "validator-a": "group-1",
            "validator-b": "group-1",
            "validator-c": "group-2",
        },
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
            {"validator_id": "val-1", "validator_label": "validator-a", "shares": 1}
        ],
        seed="seed-1",
    )
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )

    first = service.challenge_report_custody(
        report_id=outcome.report.report_id,
        challenge_id="challenge-a",
        challenger_id="validator-a",
        checked_at="2026-08-02T00:00:00+00:00",
    )
    second = service.challenge_report_custody(
        report_id=outcome.report.report_id,
        challenge_id="challenge-b",
        challenger_id="validator-b",
        checked_at="2026-08-02T00:01:00+00:00",
    )
    pending = service.custody_challenge_summary(report_id=outcome.report.report_id)
    assert first.independence_key == "control-group:group-1"
    assert second.independence_key == "control-group:group-1"
    assert pending["independent_observation_count"] == 1
    assert pending["quorum_state"] == "pending"

    third = service.challenge_report_custody(
        report_id=outcome.report.report_id,
        challenge_id="challenge-c",
        challenger_id="validator-c",
        checked_at="2026-08-02T00:02:00+00:00",
    )
    confirmed = service.custody_challenge_summary(report_id=outcome.report.report_id)
    assert third.independence_key == "control-group:group-2"
    assert confirmed["independent_observation_count"] == 2
    assert confirmed["quorum_state"] == "confirmed"
    assert confirmed["challenge_count"] == 3
    assert confirmed["outcome_counts"] == {"available": 3}

    availability = [
        item
        for item in operations
        if item["operation_type"] == "VALIDATION_REPORT_AVAILABILITY_COMMIT"
    ]
    assert [item["payload"]["independence_key"] for item in availability] == [
        "control-group:group-1",
        "control-group:group-1",
        "control-group:group-2",
    ]


def test_scheduled_custody_tasks_are_deterministic_persistent_and_idempotent(tmp_path) -> None:
    state_store = FileStateStore(tmp_path / "state.json")
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    service = ValidationService(
        ValidationStore(state_store),
        custody_store=custody,
        custody_challenge_quorum=2,
        custody_known_control_groups={
            "validator-a": "group-1",
            "validator-b": "group-1",
            "validator-c": "group-2",
        },
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
            {"validator_id": "val-1", "validator_label": "validator-a", "shares": 1}
        ],
        seed="seed-1",
    )
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )

    first = service.schedule_custody_challenges(
        epoch_id="custody-epoch-1",
        seed="custody-seed-1",
        observer_ids=["validator-a", "validator-b", "validator-c"],
        scheduled_at="2026-08-02T00:00:00+00:00",
    )
    second = service.schedule_custody_challenges(
        epoch_id="custody-epoch-1",
        seed="custody-seed-1",
        observer_ids=["validator-c", "validator-b", "validator-a"],
        scheduled_at="2026-08-02T01:00:00+00:00",
    )
    assert len(first) == 2
    assert second == first
    assert {item.independence_key for item in first} == {
        "control-group:group-1",
        "control-group:group-2",
    }
    assert all(item.status == "scheduled" for item in first)
    assert all(item.report_id == outcome.report.report_id for item in first)

    restored = ValidationService(
        ValidationStore(state_store),
        custody_store=custody,
        custody_challenge_quorum=2,
        custody_known_control_groups={
            "validator-a": "group-1",
            "validator-b": "group-1",
            "validator-c": "group-2",
        },
    )
    completed = restored.run_scheduled_custody_challenge(
        task_id=first[0].task_id,
        checked_at="2026-08-02T00:05:00+00:00",
    )
    replayed = restored.run_scheduled_custody_challenge(task_id=first[0].task_id)
    assert completed.status == "completed"
    assert completed.outcome == "available"
    assert completed.challenge_evidence_root is not None
    assert replayed == completed
    persisted = ValidationStore(state_store).get_report_custody_task(first[0].task_id)
    assert persisted == completed


def test_origin_and_mirror_observations_have_separate_quorum_views(tmp_path) -> None:
    service = ValidationService(
        ValidationStore(),
        custody_store=ValidationReportCustodyStore(tmp_path / "custody"),
        custody_challenge_quorum=1,
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
            {"validator_id": "val-1", "validator_label": "validator-a", "shares": 1}
        ],
        seed="seed-1",
    )
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    service.challenge_report_custody(
        report_id=outcome.report.report_id,
        challenge_id="origin-challenge-1",
        challenger_id="origin-observer",
        observation_role="origin",
        checked_at="2026-08-02T00:00:00+00:00",
    )
    service.challenge_report_custody(
        report_id=outcome.report.report_id,
        challenge_id="mirror-challenge-1",
        challenger_id="mirror-observer",
        observation_role="mirror",
        checked_at="2026-08-02T00:01:00+00:00",
    )

    summary = service.custody_challenge_summary(report_id=outcome.report.report_id)
    assert summary["origin_independent_observation_count"] == 1
    assert summary["mirror_independent_observation_count"] == 1
    assert summary["origin_quorum_state"] == "confirmed"
    assert summary["mirror_quorum_state"] == "confirmed"
    assert summary["quorum_state"] == "confirmed"
    assert summary["outcome_counts_by_role"] == {
        "origin": {"available": 1},
        "mirror": {"available": 1},
    }


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
    assert service.validation_history("ep-1")["report_storage_failures"] == [first.model_dump(mode="json")]


def test_endpoint_retirement_queue_survives_restart_and_never_deletes_report(
    tmp_path,
) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    state_store = FileStateStore(tmp_path / "state.json")
    operations: list[dict] = []

    def record_operation(**item):
        operations.append(item)
        return {"operation_id": f"op-{len(operations)}"}

    service = ValidationService(
        ValidationStore(state_store),
        custody_store=custody,
        custody_retirement_grace_period_seconds=60,
        operation_recorder=record_operation,
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

    first = service.request_endpoint_retirement(
        endpoint_id="ep-1",
        requested_at="2026-08-02T00:00:00+00:00",
    )
    second = service.request_endpoint_retirement(
        endpoint_id="ep-1",
        requested_at="2026-08-02T00:05:00+00:00",
    )
    assert second == first
    assert first[0].status == "pending"
    assert first[0].eligible_at == "2026-08-02T00:01:00+00:00"

    restored = ValidationService(
        ValidationStore(state_store),
        custody_store=custody,
        custody_retirement_grace_period_seconds=60,
        operation_recorder=record_operation,
    )
    assert restored.store.list_report_custody_retirings() == first
    assert restored.sweep_custody_retirements(
        now="2026-08-02T00:00:59+00:00"
    ) == []
    released = restored.sweep_custody_retirements(
        now="2026-08-02T00:01:00+00:00"
    )
    assert len(released) == 1
    assert released[0].status == "released"
    assert restored.sweep_custody_retirements(
        now="2026-08-02T00:02:00+00:00"
    ) == []
    assert len(
        [
            item
            for item in operations
            if item["operation_type"] == "VALIDATION_REPORT_CUSTODY_RELEASE"
        ]
    ) == 1
    assert restored.get_custody_report_body(outcome.commitment.report_hash)["endpoint_id"] == "ep-1"
    metadata = restored.report_custody_metadata(report_id=outcome.report.report_id)
    assert metadata["custody_retirements"][0]["status"] == "released"


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


def test_custody_lifecycle_applies_grace_and_restores_certification(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    service = ValidationService(
        ValidationStore(),
        custody_store=custody,
        custody_signer=Ed25519ValidationReportCustodySigner("ee" * 32),
        require_storage_receipt_for_positive_certification=True,
        enforce_custody_certification_lifecycle=True,
        custody_grace_period_seconds=60,
        custody_failure_threshold=2,
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
            {"validator_id": "val-1", "validator_label": "validator-a", "shares": 1}
        ],
        seed="seed-1",
    )
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="pass",
        validator_label="validator-a",
        evidence_summary="all checks passed",
    )
    service.create_report_storage_receipt(report_id=outcome.report.report_id)
    assert service.store.get_snapshot("ep-1", "cfg-1").certification_status == "certified"

    service.check_report_custody(
        report_id=outcome.report.report_id,
        checked_at="2026-08-02T00:00:00+00:00",
    )
    payload_path = tmp_path / "custody" / outcome.custody_object.storage_relative_path
    payload_path.chmod(stat.S_IREAD | stat.S_IWRITE)
    payload_path.unlink()

    first_missing = service.check_report_custody(
        report_id=outcome.report.report_id,
        checked_at="2026-08-02T00:00:10+00:00",
    )
    second_missing = service.check_report_custody(
        report_id=outcome.report.report_id,
        checked_at="2026-08-02T00:00:20+00:00",
    )
    assert first_missing.status == "temporarily_unavailable"
    assert second_missing.failure_streak == 2
    assert service.store.get_snapshot("ep-1", "cfg-1").certification_status == "certified"

    expired = service.check_report_custody(
        report_id=outcome.report.report_id,
        checked_at="2026-08-02T00:01:10+00:00",
    )
    assert expired.status == "temporarily_unavailable"
    assert service.store.get_snapshot("ep-1", "cfg-1").certification_status == (
        "maintenance_in_progress"
    )

    custody.store_report(outcome.report)
    restored = service.check_report_custody(
        report_id=outcome.report.report_id,
        checked_at="2026-08-02T00:01:20+00:00",
    )
    assert restored.status == "available"
    assert service.store.get_snapshot("ep-1", "cfg-1").certification_status == "certified"


def test_custody_lifecycle_does_not_change_negative_certification(tmp_path) -> None:
    custody = ValidationReportCustodyStore(tmp_path / "custody")
    service = ValidationService(
        ValidationStore(),
        custody_store=custody,
        enforce_custody_certification_lifecycle=True,
        custody_grace_period_seconds=0,
        custody_failure_threshold=1,
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
            {"validator_id": "val-1", "validator_label": "validator-a", "shares": 1}
        ],
        seed="seed-1",
    )
    outcome = service.submit_validation_report(
        request_id=requested.request.request_id,
        outcome="fail",
        validator_label="validator-a",
        evidence_summary="critical issue",
        detected_issues=[{"issue_id": "critical-1", "severity": "critical"}],
    )
    payload_path = tmp_path / "custody" / outcome.custody_object.storage_relative_path
    payload_path.chmod(stat.S_IREAD | stat.S_IWRITE)
    payload_path.unlink()

    service.check_report_custody(
        report_id=outcome.report.report_id,
        checked_at="2026-08-02T00:00:00+00:00",
    )
    assert service.store.get_snapshot("ep-1", "cfg-1").certification_status == "uncertified"
