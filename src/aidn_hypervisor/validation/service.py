from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.validation.escrow import (
    LocalOperatorBondEscrowAdapter,
    LocalValidatorEscrowPoolAdapter,
)
from aidn_hypervisor.validation.models import (
    ValidationAssignment,
    ValidationAuthorization,
    ValidationBond,
    ValidationDetectedIssue,
    ValidationEpoch,
    ValidationReport,
    ValidationReportCommitment,
    ValidationReportCustodyObject,
    ValidationReportStorageReceipt,
    ValidationRequest,
    ValidationStatusSnapshot,
    ValidationValidatorEntry,
    canonical_validation_hash,
    validation_report_integrity,
)
from aidn_hypervisor.validation.custody_signing import (
    storage_receipt_signing_payload,
    verify_storage_receipt,
)


DEFAULT_VALIDATION_BOND_Q = 500.0


def _compat_validation_status_for(certification_status: str) -> str:
    return {
        "uncertified": "unvalidated",
        "pending_initial": "pending_initial",
        "maintenance_due": "pending_maintenance",
        "maintenance_in_progress": "pending_maintenance",
        "certified": "validated",
        "certified_with_issues": "validated",
        "revoked": "validation_failed",
        "superseded": "superseded",
    }[certification_status]


def _canonical_validation_status_for(certification_status: str) -> str:
    compat = _compat_validation_status_for(certification_status)
    return {
        "unvalidated": "unvalidated",
        "pending_initial": "pending_initial",
        "pending_maintenance": "validated",
        "validated": "validated",
        "validation_failed": "validated",
        "superseded": "validated",
    }[compat]


def _derive_certification_status(
    *,
    request_kind: str,
    recommendation: str,
    critical_issue_count: int,
) -> str:
    if recommendation == "do_not_certify" or critical_issue_count > 0:
        return "revoked" if request_kind == "maintenance" else "uncertified"
    if recommendation == "certify_with_issues":
        return "certified_with_issues"
    return "certified"


@dataclass(frozen=True)
class ValidationRequestOutcome:
    request: ValidationRequest
    bond: ValidationBond
    snapshot: ValidationStatusSnapshot


@dataclass(frozen=True)
class ValidationReportOutcome:
    request: ValidationRequest
    bond: ValidationBond
    snapshot: ValidationStatusSnapshot
    report: ValidationReport
    commitment: ValidationReportCommitment
    custody_object: ValidationReportCustodyObject | None = None


@dataclass(frozen=True)
class ValidationAssignmentOutcome:
    epoch: ValidationEpoch
    assignments: list[ValidationAssignment]
    authorizations: list[ValidationAuthorization]


class ValidationService:
    def __init__(
        self,
        store,
        *,
        bond_escrow=None,
        validator_escrow=None,
        event_recorder=None,
        operation_recorder=None,
        custody_store=None,
        custody_signer=None,
    ) -> None:
        self.store = store
        self.bond_escrow = bond_escrow or LocalOperatorBondEscrowAdapter()
        self.validator_escrow = validator_escrow or LocalValidatorEscrowPoolAdapter()
        self.event_recorder = event_recorder
        self.operation_recorder = operation_recorder
        self.custody_store = custody_store
        self.custody_signer = custody_signer

    def request_validation(
        self,
        *,
        endpoint_id: str,
        owner_wallet: str,
        configuration_hash: str,
        minimum_session_deposit_q: float,
    ) -> ValidationRequestOutcome:
        if minimum_session_deposit_q < 0.0:
            raise ValueError("minimum_session_deposit_q must be greater than or equal to 0")
        now = self._now()
        request_id = self._new_id("req")
        bond_id = self._new_id("bond")
        lock = self.bond_escrow.lock_bond(
            owner_wallet,
            DEFAULT_VALIDATION_BOND_Q,
            {
                "endpoint_id": endpoint_id,
                "configuration_hash": configuration_hash,
                "minimum_session_deposit_q": minimum_session_deposit_q,
            },
        )
        request = ValidationRequest(
            request_id=request_id,
            endpoint_id=endpoint_id,
            configuration_hash=configuration_hash,
            owner_wallet=owner_wallet,
            minimum_session_deposit_q=minimum_session_deposit_q,
            request_kind="initial",
            status="queued",
            created_at=now,
            bond_id=bond_id,
        )
        bond = ValidationBond(
            bond_id=bond_id,
            owner_wallet=owner_wallet,
            endpoint_id=endpoint_id,
            configuration_hash=configuration_hash,
            amount_q=lock.amount_q,
            remaining_locked_q=lock.amount_q,
            released_q=0.0,
            forfeited_q=0.0,
            escrow_adapter=self.bond_escrow.adapter_name,
            escrow_reference=lock.escrow_reference,
            status="locked",
        )
        snapshot = ValidationStatusSnapshot(
            endpoint_id=endpoint_id,
            configuration_hash=configuration_hash,
            certification_status="pending_initial",
            validation_status="pending_initial",
            latest_request_id=request_id,
        )
        self.store.save_request(request)
        self.store.save_bond(bond)
        self.store.save_snapshot(snapshot)
        if self.operation_recorder is not None:
            self.operation_recorder(
                operation_type="VALIDATION_REQUEST",
                origin_type="wallet",
                fee_class="standard",
                initiator_id=owner_wallet,
                sender_wallet=owner_wallet,
                fee_payer=owner_wallet,
                payload={
                    "validation_request_id": request_id,
                    "endpoint_id": endpoint_id,
                    "endpoint_configuration_hash": configuration_hash,
                    "validation_type": "initial",
                    "bond_reference": bond_id,
                    "minimum_session_deposit_q": minimum_session_deposit_q,
                },
                created_at=now,
                emitted_events=["ValidationRequested"],
            )
        self._emit(
            event_type="validation_bond_locked",
            message="validation bond locked",
            details={
                "request_id": request_id,
                "bond_id": bond_id,
                "endpoint_id": endpoint_id,
                "owner_wallet": owner_wallet,
                "amount_q": lock.amount_q,
            },
        )
        return ValidationRequestOutcome(
            request=request,
            bond=bond,
            snapshot=snapshot,
        )

    def assign_epoch_requests(
        self,
        *,
        epoch_id: str,
        validator_entries: list[dict],
        seed: str,
    ) -> ValidationAssignmentOutcome:
        now = self._now()
        epoch = ValidationEpoch(
            epoch_id=epoch_id,
            seed=seed,
            status="assigned",
            created_at=now,
        )
        entries = [ValidationValidatorEntry(**item) for item in validator_entries]
        expanded = self.validator_escrow.expand_assignment_list(entries)
        shuffled = self.validator_escrow.deterministic_shuffle(expanded, seed)
        queued_requests = sorted(
            self.store.list_requests(status="queued"),
            key=lambda item: item.created_at,
        )
        if queued_requests and not shuffled:
            raise ValueError("No validator capacity available")
        if len(queued_requests) > len(shuffled):
            raise ValueError(
                "Queued requests exceed available validator share capacity for epoch"
            )
        assignments: list[ValidationAssignment] = []
        authorizations = []
        for index, request in enumerate(queued_requests):
            validator_id = shuffled[index]
            assignment = ValidationAssignment(
                assignment_id=self._new_id("assign"),
                epoch_id=epoch_id,
                request_id=request.request_id,
                validator_id=validator_id,
                assigned_at=now,
            )
            authorization = self.validator_escrow.issue_authorization(
                request_id=request.request_id,
                epoch_id=epoch_id,
                guarantee_q=self.store.minimum_session_deposit_for_request(
                    request.request_id
                ),
                issued_at=now,
            )
            updated_request = request.model_copy(
                update={
                    "status": "authorization_issued",
                    "epoch_id": epoch_id,
                    "assignment_id": assignment.assignment_id,
                    "authorization_id": authorization.authorization_id,
                }
            )
            self.store.save_request(updated_request)
            self.store.save_assignment(assignment)
            self.store.save_authorization(authorization)
            assignments.append(assignment)
            authorizations.append(authorization)
        self.store.save_epoch(epoch)
        for entry in entries:
            self.store.save_validator_entry(entry)
        return ValidationAssignmentOutcome(
            epoch=epoch,
            assignments=assignments,
            authorizations=authorizations,
        )

    def create_validation_epoch(
        self,
        *,
        epoch_id: str,
        seed: str,
        validator_entries: list[dict],
    ) -> ValidationAssignmentOutcome:
        return self.assign_epoch_requests(
            epoch_id=epoch_id,
            validator_entries=validator_entries,
            seed=seed,
        )

    def submit_validation_report(
        self,
        *,
        request_id: str,
        recommendation: str | None = None,
        validator_label: str,
        evidence_summary: str,
        detected_issues: list[dict | ValidationDetectedIssue] | None = None,
        outcome: str | None = None,
    ) -> ValidationReportOutcome:
        request = self.store.get_request(request_id)
        if request.status in {"passed", "failed", "forfeited", "revoked", "superseded"}:
            raise ValueError(f"Request is already terminal: {request_id}")
        if request.status != "authorization_issued":
            raise ValueError(
                f"Request must be authorization_issued before report submission: {request_id}"
            )
        bond = self.store.get_bond(request.bond_id)
        resolved_recommendation = self._normalize_recommendation(
            recommendation=recommendation,
            outcome=outcome,
        )
        resolved_detected_issues = self._normalize_detected_issues(detected_issues)
        report = ValidationReport(
            report_id=self._new_id("report"),
            request_id=request.request_id,
            endpoint_id=request.endpoint_id,
            configuration_hash=request.configuration_hash,
            report_kind="initial",
            validator_label=validator_label,
            detected_issues=resolved_detected_issues,
            critical_issue_count=self._count_issues(
                resolved_detected_issues, severity="critical"
            ),
            warning_issue_count=self._count_issues(
                resolved_detected_issues, severity="warning"
            ),
            recommendation=resolved_recommendation,
            evidence_summary=evidence_summary,
            created_at=self._now(),
        )
        custody_object = self._store_report_custody(report)
        commitment = self._create_report_commitment(request=request, report=report)
        certification_status = _derive_certification_status(
            request_kind="initial",
            recommendation=report.recommendation,
            critical_issue_count=report.critical_issue_count,
        )
        request_status = (
            "passed" if certification_status != "uncertified" else "failed"
        )
        snapshot_status = _canonical_validation_status_for(certification_status)
        validated_at = (
            report.created_at if certification_status != "uncertified" else None
        )
        updated_request = request.model_copy(update={"status": request_status})
        updated_snapshot = self.store.get_snapshot(
            request.endpoint_id,
            request.configuration_hash,
        ).model_copy(
            update={
                "certification_status": certification_status,
                "validation_status": snapshot_status,
                "latest_request_id": request.request_id,
                "latest_report_id": report.report_id,
                "latest_report_at": report.created_at,
                "validated_at": validated_at,
            }
        )
        self.store.save_report(report)
        if custody_object is not None:
            self.store.save_report_custody_object(custody_object)
        self.store.save_report_commitment(commitment)
        self.store.save_request(updated_request)
        self.store.save_snapshot(updated_snapshot)
        if self.operation_recorder is not None:
            self._record_validation_report_commitment(commitment, report)
            self._record_certification_state_update(
                endpoint_id=request.endpoint_id,
                configuration_hash=request.configuration_hash,
                certification_status=certification_status,
                latest_request_id=request.request_id,
                latest_report_id=report.report_id,
                created_at=report.created_at,
            )
        compat_validation_status = _compat_validation_status_for(certification_status)
        self._emit(
            event_type=(
                "validation_request_passed"
                if compat_validation_status == "validated"
                else "validation_request_failed"
            ),
            message="validation report submitted",
            details={
                "request_id": request.request_id,
                "report_id": report.report_id,
                "endpoint_id": request.endpoint_id,
                "recommendation": report.recommendation,
            },
        )
        return ValidationReportOutcome(
            request=updated_request,
            bond=bond,
            snapshot=updated_snapshot,
            report=report,
            commitment=commitment,
            custody_object=custody_object,
        )

    def validation_summary(
        self,
        endpoint_id: str,
        *,
        configuration_hash: str | None = None,
    ) -> dict:
        requests = sorted(
            [
                item
                for item in self.store.list_requests_for_endpoint(endpoint_id)
                if configuration_hash is None
                or item.configuration_hash == configuration_hash
            ],
            key=lambda item: item.created_at,
        )
        reports = sorted(
            [
                item
                for item in self.store.list_reports_for_endpoint(endpoint_id)
                if configuration_hash is None
                or item.configuration_hash == configuration_hash
            ],
            key=lambda item: item.created_at,
        )
        snapshots = [
            item
            for item in self.store.list_snapshots()
            if item.endpoint_id == endpoint_id
            and (
                configuration_hash is None
                or item.configuration_hash == configuration_hash
            )
        ]
        current_snapshot = snapshots[-1] if snapshots else None
        latest_request = requests[-1] if requests else None
        latest_report = reports[-1] if reports else None
        resolved_configuration_hash = configuration_hash or (
            current_snapshot.configuration_hash
            if current_snapshot is not None
            else latest_request.configuration_hash
            if latest_request is not None
            else None
        )
        scoped_requests = [
            item
            for item in requests
            if resolved_configuration_hash is None
            or item.configuration_hash == resolved_configuration_hash
        ]
        scoped_reports = [
            item
            for item in reports
            if resolved_configuration_hash is None
            or item.configuration_hash == resolved_configuration_hash
        ]
        latest_request_for_configuration = (
            scoped_requests[-1] if scoped_requests else None
        )
        latest_report_for_configuration = scoped_reports[-1] if scoped_reports else None
        scoped_report_ids = {report.report_id for report in scoped_reports}
        scoped_commitments = sorted(
            [
                item
                for item in self.store.list_report_commitments()
                if item.report_id in scoped_report_ids
            ],
            key=lambda item: item.created_at,
        )
        latest_commitment = scoped_commitments[-1] if scoped_commitments else None
        custody_objects_by_hash = {
            item.report_hash: item
            for item in self.store.list_report_custody_objects()
        }
        latest_custody_object = (
            custody_objects_by_hash.get(latest_commitment.report_hash)
            if latest_commitment is not None
            else None
        )
        latest_storage_receipt = next(
            (
                item
                for item in self.store.list_report_storage_receipts()
                if latest_commitment is not None
                and item.report_hash == latest_commitment.report_hash
                and item.endpoint_id == endpoint_id
                and item.endpoint_configuration_hash == resolved_configuration_hash
            ),
            None,
        )
        scoped_request_ids = {request.request_id for request in scoped_requests}
        latest_bond = (
            self.store.get_bond(latest_request_for_configuration.bond_id)
            if latest_request_for_configuration is not None
            else None
        )
        return {
            "endpoint_id": endpoint_id,
            "configuration_hash": resolved_configuration_hash,
            "certification_status": (
                current_snapshot.certification_status
                if current_snapshot is not None
                else "uncertified"
            ),
            "validation_status": (
                _compat_validation_status_for(current_snapshot.certification_status)
                if current_snapshot is not None
                else "unvalidated"
            ),
            "latest_request_id": (
                current_snapshot.latest_request_id
                if current_snapshot is not None
                else latest_request_for_configuration.request_id
                if latest_request_for_configuration is not None
                else None
            ),
            "latest_report_id": (
                current_snapshot.latest_report_id
                if current_snapshot is not None
                else None
            ),
            "latest_report_at": (
                current_snapshot.latest_report_at
                if current_snapshot is not None
                else None
            ),
            "latest_report_commitment": (
                latest_commitment.model_dump(mode="json")
                if latest_commitment is not None
                else None
            ),
            "latest_report_custody": (
                latest_custody_object.model_dump(mode="json")
                if latest_custody_object is not None
                else None
            ),
            "latest_report_storage_receipt": (
                latest_storage_receipt.model_dump(mode="json")
                if latest_storage_receipt is not None
                else None
            ),
            "custody_object_present": latest_custody_object is not None,
            "storage_receipt_present": latest_storage_receipt is not None,
            "latest_recommendation": (
                latest_report_for_configuration.recommendation
                if latest_report_for_configuration is not None
                else None
            ),
            "critical_issue_count": (
                latest_report_for_configuration.critical_issue_count
                if latest_report_for_configuration is not None
                else 0
            ),
            "warning_issue_count": (
                latest_report_for_configuration.warning_issue_count
                if latest_report_for_configuration is not None
                else 0
            ),
            "maintenance_report_count": sum(
                1 for item in scoped_reports if item.report_kind == "maintenance"
            ),
            "bond_state": (
                latest_bond.model_dump(mode="json")
                if latest_bond is not None
                else None
            ),
            "validated_at": (
                current_snapshot.validated_at if current_snapshot is not None else None
            ),
            "superseded_at": (
                current_snapshot.superseded_at if current_snapshot is not None else None
            ),
            "current_snapshot": (
                current_snapshot.model_dump(mode="json")
                if current_snapshot is not None
                else None
            ),
            "request_count": len(scoped_requests),
            "report_count": len(scoped_reports),
            "assigned_request_count": sum(
                1 for item in scoped_requests if item.assignment_id is not None
            ),
            "validated_request_count": sum(
                1 for item in scoped_requests if item.status == "passed"
            ),
            "failed_request_count": sum(
                1 for item in scoped_requests if item.status in {"failed", "revoked"}
            ),
            "active_request_ids": [
                item.request_id
                for item in scoped_requests
                if item.status in {"queued", "authorization_issued"}
            ],
            "assignment_count": sum(
                1
                for item in self.store.list_assignments()
                if item.request_id in scoped_request_ids
            ),
            "authorization_count": sum(
                1
                for item in self.store.list_authorizations()
                if item.request_id in scoped_request_ids
            ),
        }

    def supersede_configuration(
        self,
        *,
        endpoint_id: str,
        previous_configuration_hash: str,
        replacement_configuration_hash: str,
        superseded_at: str,
    ) -> None:
        if previous_configuration_hash == replacement_configuration_hash:
            return
        try:
            snapshot = self.store.get_snapshot(
                endpoint_id,
                previous_configuration_hash,
            )
        except KeyError:
            return
        updated_snapshot = snapshot.model_copy(
            update={
                "certification_status": "superseded",
                "validation_status": _canonical_validation_status_for("superseded"),
                "superseded_at": superseded_at,
            }
        )
        self.store.save_snapshot(updated_snapshot)
        try:
            request = self.store.latest_request_for_snapshot(
                endpoint_id,
                previous_configuration_hash,
            )
        except KeyError:
            request = None
        if request is not None:
            self.store.save_request(
                request.model_copy(
                    update={
                        "status": "superseded",
                        "superseded_at": superseded_at,
                    }
                )
            )
        self._emit(
            event_type="validation_configuration_superseded",
            message="validation configuration superseded",
            details={
                "endpoint_id": endpoint_id,
                "previous_configuration_hash": previous_configuration_hash,
                "replacement_configuration_hash": replacement_configuration_hash,
                "superseded_at": superseded_at,
            },
        )

    def validation_history(self, endpoint_id: str) -> dict:
        requests = sorted(
            self.store.list_requests_for_endpoint(endpoint_id),
            key=lambda item: item.created_at,
        )
        request_ids = {item.request_id for item in requests}
        assignment_ids = {
            item.assignment_id for item in requests if item.assignment_id is not None
        }
        authorization_ids = {
            item.authorization_id
            for item in requests
            if item.authorization_id is not None
        }
        assignments = [
            item
            for item in self.store.list_assignments()
            if item.assignment_id in assignment_ids
        ]
        authorizations = [
            item
            for item in self.store.list_authorizations()
            if item.authorization_id in authorization_ids
        ]
        reports = sorted(
            self.store.list_reports_for_endpoint(endpoint_id),
            key=lambda item: item.created_at,
        )
        report_ids = {item.report_id for item in reports}
        commitments = sorted(
            [
                item
                for item in self.store.list_report_commitments()
                if item.report_id in report_ids
            ],
            key=lambda item: item.created_at,
        )
        report_hashes = {item.report_hash for item in commitments}
        custody_objects = [
            item
            for item in self.store.list_report_custody_objects()
            if item.report_hash in report_hashes
        ]
        storage_receipts = [
            item
            for item in self.store.list_report_storage_receipts()
            if item.report_hash in report_hashes and item.endpoint_id == endpoint_id
        ]
        custody_states = [
            item
            for item in self.store.list_report_custody_states()
            if item.report_hash in report_hashes and item.endpoint_id == endpoint_id
        ]
        snapshots = [
            item
            for item in self.store.list_snapshots()
            if item.endpoint_id == endpoint_id
        ]
        epochs = [
            item
            for item in self.store.list_epochs()
            if any(assignment.epoch_id == item.epoch_id for assignment in assignments)
        ]
        return {
            "endpoint_id": endpoint_id,
            "requests": [item.model_dump(mode="json") for item in requests],
            "assignments": [item.model_dump(mode="json") for item in assignments],
            "authorizations": [
                item.model_dump(mode="json") for item in authorizations
            ],
            "reports": [item.model_dump(mode="json") for item in reports],
            "report_commitments": [
                item.model_dump(mode="json") for item in commitments
            ],
            "report_custody_objects": [
                item.model_dump(mode="json") for item in custody_objects
            ],
            "report_storage_receipts": [
                item.model_dump(mode="json") for item in storage_receipts
            ],
            "report_custody_states": [
                item.model_dump(mode="json") for item in custody_states
            ],
            "snapshots": [item.model_dump(mode="json") for item in snapshots],
            "epochs": [item.model_dump(mode="json") for item in epochs],
            "request_count": len(request_ids),
        }

    def resolve_maintenance_by_request(
        self,
        *,
        request_id: str,
        recommendation: str | None = None,
        validator_label: str,
        evidence_summary: str,
        detected_issues: list[dict | ValidationDetectedIssue] | None = None,
        outcome: str | None = None,
    ) -> ValidationReportOutcome:
        request = self.store.get_request(request_id)
        return self.resolve_maintenance(
            endpoint_id=request.endpoint_id,
            configuration_hash=request.configuration_hash,
            recommendation=recommendation,
            outcome=outcome,
            validator_label=validator_label,
            evidence_summary=evidence_summary,
            detected_issues=detected_issues,
        )

    def force_mark_validated(
        self,
        *,
        request_id: str,
        report_id: str,
        validated_at: str,
    ) -> ValidationRequestOutcome:
        request = self.store.get_request(request_id)
        updated_request = request.model_copy(update={"status": "passed"})
        updated_snapshot = self.store.get_snapshot(
            request.endpoint_id,
            request.configuration_hash,
        ).model_copy(
            update={
                "certification_status": "certified",
                "validation_status": _canonical_validation_status_for("certified"),
                "latest_request_id": request_id,
                "latest_report_id": report_id,
                "latest_report_at": validated_at,
                "validated_at": validated_at,
            }
        )
        self.store.save_request(updated_request)
        self.store.save_snapshot(updated_snapshot)
        bond = self.store.get_bond(request.bond_id)
        return ValidationRequestOutcome(
            request=updated_request,
            bond=bond,
            snapshot=updated_snapshot,
        )

    def resolve_maintenance(
        self,
        *,
        endpoint_id: str,
        configuration_hash: str,
        recommendation: str | None = None,
        validator_label: str,
        evidence_summary: str,
        detected_issues: list[dict | ValidationDetectedIssue] | None = None,
        outcome: str | None = None,
    ) -> ValidationReportOutcome:
        snapshot = self.store.get_snapshot(endpoint_id, configuration_hash)
        request = self.store.latest_request_for_snapshot(endpoint_id, configuration_hash)
        if (
            snapshot.certification_status not in {"certified", "certified_with_issues"}
            or request.status != "passed"
        ):
            raise ValueError(
                "Maintenance resolution requires a validated snapshot and passed request"
            )
        bond = self.store.get_bond(request.bond_id)
        resolved_recommendation = self._normalize_recommendation(
            recommendation=recommendation,
            outcome=outcome,
        )
        resolved_detected_issues = self._normalize_detected_issues(detected_issues)
        report = ValidationReport(
            report_id=self._new_id("report"),
            request_id=request.request_id,
            endpoint_id=endpoint_id,
            configuration_hash=configuration_hash,
            report_kind="maintenance",
            validator_label=validator_label,
            detected_issues=resolved_detected_issues,
            critical_issue_count=self._count_issues(
                resolved_detected_issues, severity="critical"
            ),
            warning_issue_count=self._count_issues(
                resolved_detected_issues, severity="warning"
            ),
            recommendation=resolved_recommendation,
            evidence_summary=evidence_summary,
            created_at=self._now(),
        )
        custody_object = self._store_report_custody(report)
        commitment = self._create_report_commitment(request=request, report=report)
        self.store.save_report(report)
        if custody_object is not None:
            self.store.save_report_custody_object(custody_object)
        self.store.save_report_commitment(commitment)
        if self.operation_recorder is not None:
            self._record_validation_report_commitment(commitment, report)
        certification_status = _derive_certification_status(
            request_kind="maintenance",
            recommendation=report.recommendation,
            critical_issue_count=report.critical_issue_count,
        )
        compat_validation_status = _compat_validation_status_for(certification_status)
        if certification_status != "revoked":
            refund_q = round(bond.remaining_locked_q * 0.5, 6)
            self.bond_escrow.refund_bond(bond.bond_id, refund_q)
            remaining_locked_q = round(bond.remaining_locked_q - refund_q, 6)
            updated_bond = bond.model_copy(
                update={
                    "remaining_locked_q": remaining_locked_q,
                    "released_q": round(bond.released_q + refund_q, 6),
                    "status": (
                        "released"
                        if remaining_locked_q == 0.0
                        else "partially_released"
                    ),
                }
            )
            updated_snapshot = snapshot.model_copy(
                update={
                    "certification_status": certification_status,
                    "validation_status": _canonical_validation_status_for(
                        certification_status
                    ),
                    "latest_request_id": request.request_id,
                    "latest_report_id": report.report_id,
                    "latest_report_at": report.created_at,
                    "maintenance_count": snapshot.maintenance_count + 1,
                    "validated_at": report.created_at,
                }
            )
            updated_request = request.model_copy(update={"status": "passed"})
            event_type = "maintenance_validation_passed"
            self._emit(
                event_type="validation_bond_refunded",
                message="validation bond refunded",
                details={
                    "bond_id": bond.bond_id,
                    "request_id": request.request_id,
                    "endpoint_id": endpoint_id,
                    "owner_wallet": bond.owner_wallet,
                    "amount_q": refund_q,
                    "remaining_locked_q": remaining_locked_q,
                },
            )
            if self.operation_recorder is not None:
                self._record_certification_state_update(
                    endpoint_id=endpoint_id,
                    configuration_hash=configuration_hash,
                    certification_status=certification_status,
                    latest_request_id=request.request_id,
                    latest_report_id=report.report_id,
                    created_at=report.created_at,
                )
                self.operation_recorder(
                    operation_type="VALIDATION_BOND_REFUND",
                    origin_type="protocol",
                    fee_class="protocol_sponsored",
                    initiator_id=bond.bond_id,
                    payload={
                        "bond_id": bond.bond_id,
                        "endpoint_id": endpoint_id,
                        "configuration_hash": configuration_hash,
                        "validation_request_id": request.request_id,
                        "refund_q": refund_q,
                        "report_id": report.report_id,
                    },
                    created_at=report.created_at,
                    emitted_events=["ValidationBondRefunded"],
                )
        else:
            forfeit_q = bond.remaining_locked_q
            self.bond_escrow.forfeit_bond(bond.bond_id, forfeit_q, "validator_pool")
            updated_bond = bond.model_copy(
                update={
                    "remaining_locked_q": 0.0,
                    "forfeited_q": round(bond.forfeited_q + forfeit_q, 6),
                    "status": "forfeited",
                }
            )
            updated_snapshot = snapshot.model_copy(
                update={
                    "certification_status": certification_status,
                    "validation_status": _canonical_validation_status_for(
                        certification_status
                    ),
                    "latest_request_id": request.request_id,
                    "latest_report_id": report.report_id,
                    "latest_report_at": report.created_at,
                    "maintenance_count": snapshot.maintenance_count + 1,
                    "validated_at": None,
                }
            )
            updated_request = request.model_copy(update={"status": "revoked"})
            event_type = "maintenance_validation_failed"
            self._emit(
                event_type="validation_bond_forfeited",
                message="validation bond forfeited",
                details={
                    "bond_id": bond.bond_id,
                    "request_id": request.request_id,
                    "endpoint_id": endpoint_id,
                    "owner_wallet": bond.owner_wallet,
                    "amount_q": forfeit_q,
                },
            )
            if self.operation_recorder is not None:
                self._record_certification_state_update(
                    endpoint_id=endpoint_id,
                    configuration_hash=configuration_hash,
                    certification_status=certification_status,
                    latest_request_id=request.request_id,
                    latest_report_id=report.report_id,
                    created_at=report.created_at,
                )
                self.operation_recorder(
                    operation_type="VALIDATION_BOND_FORFEIT",
                    origin_type="evidence_triggered",
                    fee_class="protocol_sponsored",
                    initiator_id=bond.bond_id,
                    payload={
                        "bond_id": bond.bond_id,
                        "endpoint_id": endpoint_id,
                        "configuration_hash": configuration_hash,
                        "validation_request_id": request.request_id,
                        "amount_q": forfeit_q,
                        "report_id": report.report_id,
                    },
                    created_at=report.created_at,
                    emitted_events=["ValidationBondForfeited"],
                )
        self.store.save_bond(updated_bond)
        self.store.save_request(updated_request)
        self.store.save_snapshot(updated_snapshot)
        self._emit(
            event_type=event_type,
            message="validation maintenance resolved",
            details={
                "request_id": request.request_id,
                "report_id": report.report_id,
                "endpoint_id": endpoint_id,
                "owner_wallet": bond.owner_wallet,
                "recommendation": report.recommendation,
                "validation_status": compat_validation_status,
            },
        )
        return ValidationReportOutcome(
            request=updated_request,
            bond=updated_bond,
            snapshot=updated_snapshot,
            report=report,
            commitment=commitment,
            custody_object=custody_object,
        )

    def get_custody_report_body(self, report_hash: str) -> dict:
        if self.custody_store is None:
            raise ValueError("Validation report custody store is not configured")
        return self.custody_store.read_report_body(report_hash)

    def create_report_storage_receipt(
        self,
        *,
        report_id: str,
    ) -> ValidationReportStorageReceipt:
        if self.custody_store is None or self.custody_signer is None:
            raise ValueError("Validation report custody signing is not configured")
        report = self.store.get_report(report_id)
        commitment = self.store.get_report_commitment(report_id)
        custody_object = self.store.get_report_custody_object(commitment.report_hash)
        verified_object = self.custody_store.verify_report(commitment.report_hash)
        if verified_object.report_size != commitment.report_size:
            raise ValueError("Validation report custody metadata does not match commitment")
        existing = next(
            (
                item
                for item in self.store.list_report_storage_receipts()
                if item.endpoint_id == report.endpoint_id
                and item.endpoint_configuration_hash == report.configuration_hash
                and item.report_hash == commitment.report_hash
            ),
            None,
        )
        if existing is not None:
            verify_storage_receipt(existing)
            return existing

        receipt_seed = canonical_validation_hash(
            {
                "validation_id": report.request_id,
                "endpoint_id": report.endpoint_id,
                "endpoint_configuration_hash": report.configuration_hash,
                "report_hash": commitment.report_hash,
                "report_locator": commitment.report_locator,
                "retention_policy_id": commitment.retention_policy_id,
            }
        )
        unsigned_receipt = ValidationReportStorageReceipt(
            receipt_id=f"receipt-{receipt_seed.removeprefix('sha256:')}",
            validation_id=report.request_id,
            endpoint_id=report.endpoint_id,
            endpoint_configuration_hash=report.configuration_hash,
            report_hash=commitment.report_hash,
            report_size=custody_object.report_size,
            stored_at=self._now(),
            report_locator=commitment.report_locator,
            retention_policy_id=commitment.retention_policy_id,
            endpoint_public_key=self.custody_signer.public_key,
            endpoint_signature="",
        )
        receipt = unsigned_receipt.model_copy(
            update={
                "endpoint_signature": self.custody_signer.sign(
                    storage_receipt_signing_payload(unsigned_receipt)
                )
            }
        )
        verify_storage_receipt(receipt)
        self.store.save_report_storage_receipt(receipt)
        if self.operation_recorder is not None:
            self.operation_recorder(
                operation_type="VALIDATION_REPORT_STORAGE_RECEIPT",
                origin_type="protocol",
                fee_class="protocol_sponsored",
                initiator_id=report.endpoint_id,
                payload={
                    "receipt_id": receipt.receipt_id,
                    "validation_id": receipt.validation_id,
                    "endpoint_id": receipt.endpoint_id,
                    "endpoint_configuration_hash": receipt.endpoint_configuration_hash,
                    "report_hash": receipt.report_hash,
                    "report_size": receipt.report_size,
                    "report_locator": receipt.report_locator,
                    "retention_policy_id": receipt.retention_policy_id,
                    "endpoint_public_key": receipt.endpoint_public_key,
                    "receipt_hash": canonical_validation_hash(
                        receipt.model_dump(mode="json")
                    ),
                },
                created_at=receipt.stored_at,
                emitted_events=["ValidationReportStorageReceiptCommitted"],
            )
        self._emit(
            event_type="validation_report_custody_accepted",
            message="validation report stored with a signed custody receipt",
            details={
                "report_id": report.report_id,
                "report_hash": receipt.report_hash,
                "receipt_id": receipt.receipt_id,
                "endpoint_id": receipt.endpoint_id,
            },
        )
        return receipt

    def _store_report_custody(
        self,
        report: ValidationReport,
    ) -> ValidationReportCustodyObject | None:
        if self.custody_store is None:
            return None
        custody_object = self.custody_store.store_report(report)
        report_hash, report_size = validation_report_integrity(report)
        if (
            custody_object.report_hash != report_hash
            or custody_object.report_size != report_size
        ):
            raise ValueError("Validation report custody store returned invalid metadata")
        return custody_object

    def _create_report_commitment(
        self,
        *,
        request: ValidationRequest,
        report: ValidationReport,
    ) -> ValidationReportCommitment:
        report_hash, report_size = validation_report_integrity(report)
        assignment = next(
            (
                item
                for item in self.store.list_assignments()
                if item.assignment_id == request.assignment_id
            ),
            None,
        )

        def issue_codes(severity: str) -> list[str]:
            return sorted(
                {
                    item.summary or item.issue_id
                    for item in report.detected_issues
                    if item.severity == severity
                }
            )

        return ValidationReportCommitment(
            commitment_id=f"vcommit-{report_hash.removeprefix('sha256:')}",
            report_id=report.report_id,
            report_hash=report_hash,
            report_size=report_size,
            request_id=request.request_id,
            assignment_id=request.assignment_id,
            endpoint_id=report.endpoint_id,
            configuration_hash=report.configuration_hash,
            capability_id=report.capability_id,
            validator_service_id=(
                assignment.validator_id if assignment is not None else report.validator_id
            ),
            validation_epoch_id=request.epoch_id,
            conclusion=report.recommendation,
            limitation_codes=issue_codes("warning"),
            failure_codes=issue_codes("critical"),
            evidence_root=canonical_validation_hash(
                {
                    "evidence_summary": report.evidence_summary,
                    "signed_payload": report.signed_payload,
                }
            ),
            report_locator=(
                f"aidn://endpoint/{report.endpoint_id}/validation/{report_hash}"
            ),
            created_at=report.created_at,
        )

    def _record_validation_report_commitment(
        self,
        commitment: ValidationReportCommitment,
        report: ValidationReport,
    ) -> None:
        if self.operation_recorder is None:
            return
        self.operation_recorder(
            operation_type="VALIDATION_REPORT_COMMIT",
            origin_type="protocol",
            fee_class="protocol_sponsored",
            initiator_id=report.report_id,
            payload={
                "report_id": commitment.report_id,
                "report_hash": commitment.report_hash,
                "report_size": commitment.report_size,
                "validation_request_id": commitment.request_id,
                "assignment_id": commitment.assignment_id,
                "endpoint_id": commitment.endpoint_id,
                "endpoint_configuration_hash": commitment.configuration_hash,
                "validator_service_id": commitment.validator_service_id,
                "conclusion_summary": commitment.conclusion,
                "limitation_codes": commitment.limitation_codes,
                "failure_codes": commitment.failure_codes,
                "observation_codes": commitment.observation_codes,
                "evidence_root": commitment.evidence_root,
                "evidence_access_class": commitment.evidence_access_class,
                "report_locator": commitment.report_locator,
                "retention_policy_id": commitment.retention_policy_id,
                "storage_receipt_hash": commitment.storage_receipt_hash,
                "storage_failure_reference": commitment.storage_failure_reference,
                "evidence_summary": report.evidence_summary,
            },
            created_at=report.created_at,
            emitted_events=["ValidationReportCommitted"],
        )

    def _normalize_recommendation(
        self,
        *,
        recommendation: str | None,
        outcome: str | None,
    ) -> str:
        if recommendation is not None:
            return recommendation
        if outcome == "pass":
            return "certify"
        if outcome == "fail":
            return "do_not_certify"
        raise ValueError("recommendation or outcome is required")

    def _normalize_detected_issues(
        self,
        detected_issues: list[dict | ValidationDetectedIssue] | None,
    ) -> list[ValidationDetectedIssue]:
        normalized: list[ValidationDetectedIssue] = []
        for item in detected_issues or []:
            if isinstance(item, ValidationDetectedIssue):
                normalized.append(item)
                continue
            details = {
                key: value
                for key, value in item.items()
                if key not in {"issue_id", "severity", "summary"}
            }
            normalized.append(
                ValidationDetectedIssue(
                    issue_id=str(item.get("issue_id") or self._new_id("issue")),
                    severity=item.get("severity"),
                    summary=item.get("summary") or item.get("code"),
                    details=details,
                )
            )
        return normalized

    def _count_issues(
        self,
        detected_issues: list[ValidationDetectedIssue],
        *,
        severity: str,
    ) -> int:
        return sum(1 for item in detected_issues if item.severity == severity)

    def _emit(
        self,
        *,
        event_type: str,
        message: str,
        details: dict,
    ) -> None:
        if self.event_recorder is None:
            return
        self.event_recorder(
            event_type=event_type,
            message=message,
            details=details,
        )

    def _record_certification_state_update(
        self,
        *,
        endpoint_id: str,
        configuration_hash: str,
        certification_status: str,
        latest_request_id: str,
        latest_report_id: str,
        created_at: str,
    ) -> None:
        if self.operation_recorder is None:
            return
        self.operation_recorder(
            operation_type="CERTIFICATION_STATE_UPDATE",
            origin_type="protocol",
            fee_class="protocol_sponsored",
            initiator_id=endpoint_id,
            payload={
                "endpoint_id": endpoint_id,
                "configuration_hash": configuration_hash,
                "certification_status": certification_status,
                "latest_request_id": latest_request_id,
                "latest_report_id": latest_report_id,
            },
            created_at=created_at,
            emitted_events=["CertificationStateUpdated"],
        )

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid4().hex[:12]}"
