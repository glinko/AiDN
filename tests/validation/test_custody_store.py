import stat

import pytest

from aidn_hypervisor.validation.custody_store import ValidationReportCustodyStore
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
