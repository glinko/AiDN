from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from aidn_hypervisor.validation.custody_signing import (
    storage_receipt_signing_payload,
    verify_storage_receipt,
)
from aidn_hypervisor.validation.escrow import (
    LocalOperatorBondEscrowAdapter,
    LocalValidatorEscrowPoolAdapter,
)
from aidn_hypervisor.validation.models import (
    ValidationAssignment,
    ValidationAuthorization,
    ValidationBond,
    ValidationCustodyObservationRole,
    ValidationDetectedIssue,
    ValidationEpoch,
    ValidationReport,
    ValidationReportCommitment,
    ValidationReportCustodyChallenge,
    ValidationReportCustodyCheckTask,
    ValidationReportCustodyObject,
    ValidationReportCustodyRetirement,
    ValidationReportCustodyState,
    ValidationReportStorageFailure,
    ValidationReportStorageReceipt,
    ValidationReportTransferEnvelope,
    ValidationRequest,
    ValidationStatusSnapshot,
    ValidationValidatorEntry,
    ValidationValidatorKeyBinding,
    canonical_validation_hash,
    validation_report_integrity,
)
from aidn_hypervisor.validation.transfer_signing import (
    transfer_envelope_signing_payload,
    validate_transfer_public_key,
    verify_report_transfer_envelope,
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
        transfer_signer=None,
        custody_access_checker=None,
        require_signed_transfer_envelope: bool = False,
        require_canonical_validator_transfer_identity: bool = False,
        require_storage_receipt_for_positive_certification: bool = False,
        enforce_custody_certification_lifecycle: bool = False,
        custody_grace_period_seconds: int = 3600,
        custody_failure_threshold: int = 2,
        custody_retirement_grace_period_seconds: int = 86400,
        custody_challenge_quorum: int = 1,
        custody_known_control_groups: dict[str, str] | None = None,
        dispatcher_store=None,
    ) -> None:
        self.store = store
        self.dispatcher_store = dispatcher_store
        self.bond_escrow = bond_escrow or LocalOperatorBondEscrowAdapter()
        self.validator_escrow = validator_escrow or LocalValidatorEscrowPoolAdapter()
        self.event_recorder = event_recorder
        self.operation_recorder = operation_recorder
        self.custody_store = custody_store
        self.custody_signer = custody_signer
        self.transfer_signer = transfer_signer
        self.custody_access_checker = custody_access_checker
        self.require_signed_transfer_envelope = require_signed_transfer_envelope
        self.require_canonical_validator_transfer_identity = (
            require_canonical_validator_transfer_identity
        )
        self.require_storage_receipt_for_positive_certification = (
            require_storage_receipt_for_positive_certification
        )
        if custody_grace_period_seconds < 0:
            raise ValueError("custody_grace_period_seconds must be non-negative")
        if custody_failure_threshold < 1:
            raise ValueError("custody_failure_threshold must be positive")
        if custody_retirement_grace_period_seconds < 0:
            raise ValueError(
                "custody_retirement_grace_period_seconds must be non-negative"
            )
        if custody_challenge_quorum < 1:
            raise ValueError("custody_challenge_quorum must be positive")
        self.enforce_custody_certification_lifecycle = (
            enforce_custody_certification_lifecycle
        )
        self.custody_grace_period_seconds = custody_grace_period_seconds
        self.custody_failure_threshold = custody_failure_threshold
        self.custody_retirement_grace_period_seconds = (
            custody_retirement_grace_period_seconds
        )
        self.custody_challenge_quorum = custody_challenge_quorum
        self.custody_known_control_groups = dict(custody_known_control_groups or {})

    def request_validation(
        self,
        *,
        endpoint_id: str,
        owner_wallet: str,
        configuration_hash: str,
        minimum_session_deposit_q: float,
        evidence_access_class: str = "public",
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
            evidence_access_class=evidence_access_class,
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
        canonical_entries: list[ValidationValidatorEntry] = []
        for entry in entries:
            registered_key = next(
                (
                    item
                    for item in self.store.list_validator_key_bindings()
                    if item.validator_id == entry.validator_id and item.status == "active"
                ),
                None,
            )
            if registered_key is not None:
                if (
                    entry.transfer_public_key is not None
                    and entry.transfer_public_key != registered_key.transfer_public_key
                ):
                    raise ValueError(
                        f"validator transfer key does not match registry: {entry.validator_id}"
                    )
                entry = entry.model_copy(
                    update={"transfer_public_key": registered_key.transfer_public_key}
                )
            elif self.require_canonical_validator_transfer_identity:
                raise ValueError(
                    f"validator transfer key is not registered: {entry.validator_id}"
                )
            canonical_entries.append(entry)
        entries = canonical_entries
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

    def register_validator_transfer_key(
        self,
        *,
        validator_id: str,
        transfer_public_key: str,
        registered_at: str | None = None,
    ) -> ValidationValidatorKeyBinding:
        """Register the canonical key used by one validator for report transfer."""
        if not validator_id.strip():
            raise ValueError("validator_id is required")
        validate_transfer_public_key(transfer_public_key)
        existing = next(
            (
                item
                for item in self.store.list_validator_key_bindings()
                if item.validator_id == validator_id
            ),
            None,
        )
        if existing is not None:
            if (
                existing.status == "active"
                and existing.transfer_public_key == transfer_public_key
            ):
                return existing
            raise ValueError(f"validator transfer key already registered: {validator_id}")
        registered_at = registered_at or self._now()
        binding_seed = canonical_validation_hash(
            {
                "validator_id": validator_id,
                "transfer_public_key": transfer_public_key,
                "registered_at": registered_at,
            }
        )
        binding = ValidationValidatorKeyBinding(
            binding_id=f"validator-key-{binding_seed.removeprefix('sha256:')}",
            validator_id=validator_id,
            transfer_public_key=transfer_public_key,
            registered_at=registered_at,
        )
        self.store.save_validator_key_binding(binding)
        if self.operation_recorder is not None:
            self.operation_recorder(
                operation_type="VALIDATION_VALIDATOR_KEY_REGISTER",
                origin_type="protocol",
                fee_class="protocol_sponsored",
                initiator_id=validator_id,
                payload=binding.model_dump(mode="json"),
                created_at=registered_at,
                emitted_events=["ValidationValidatorTransferKeyRegistered"],
            )
        return binding

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
        assignment = next(
            (
                item
                for item in self.store.list_assignments()
                if item.assignment_id == request.assignment_id
            ),
            None,
        )
        report = ValidationReport(
            report_id=self._new_id("report"),
            request_id=request.request_id,
            endpoint_id=request.endpoint_id,
            configuration_hash=request.configuration_hash,
            report_kind="initial",
            validator_id=assignment.validator_id if assignment is not None else None,
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
        certification_status = self._certification_status_for_report(report)
        request_status = (
            "passed" if certification_status != "uncertified" else "failed"
        )
        snapshot_status = _canonical_validation_status_for(certification_status)
        validated_at = (
            report.created_at
            if certification_status in {"certified", "certified_with_issues"}
            else None
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
        reports[-1] if reports else None
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
        storage_failures = [
            item
            for item in self.store.list_report_storage_failures()
            if item.report_hash in report_hashes and item.endpoint_id == endpoint_id
        ]
        custody_states = [
            item
            for item in self.store.list_report_custody_states()
            if item.report_hash in report_hashes and item.endpoint_id == endpoint_id
        ]
        custody_challenges = [
            item
            for item in self.store.list_report_custody_challenges()
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
            "report_storage_failures": [
                item.model_dump(mode="json") for item in storage_failures
            ],
            "report_custody_states": [
                item.model_dump(mode="json") for item in custody_states
            ],
            "report_custody_challenges": [
                item.model_dump(mode="json") for item in custody_challenges
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
        certification_status = self._certification_status_for_report(report)
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
                    "validated_at": (
                        report.created_at
                        if certification_status
                        in {"certified", "certified_with_issues"}
                        else snapshot.validated_at
                    ),
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

    def get_custody_report_by_locator(
        self,
        report_locator: str,
        *,
        requester_endpoint_id: str | None = None,
        configuration_hash: str | None = None,
        requester_subject: str | None = None,
    ) -> dict:
        """Resolve a stable locator with Endpoint and configuration scope checks."""
        parsed = urlsplit(report_locator)
        segments = parsed.path.strip("/").split("/")
        if (
            parsed.scheme != "aidn"
            or parsed.netloc != "endpoint"
            or parsed.query
            or parsed.fragment
            or len(segments) != 3
            or segments[1] != "validation"
            or not all(segments)
        ):
            raise ValueError("invalid Validation Report locator")
        endpoint_id, _validation_marker, report_hash = segments
        commitment = next(
            (
                item
                for item in self.store.list_report_commitments()
                if item.report_locator == report_locator
            ),
            None,
        )
        if commitment is None or commitment.report_hash != report_hash:
            raise KeyError(report_locator)
        if requester_endpoint_id is not None and requester_endpoint_id != endpoint_id:
            raise ValueError("Validation Report locator Endpoint scope mismatch")
        if commitment.endpoint_id != endpoint_id:
            raise ValueError("Validation Report locator commitment scope mismatch")
        if configuration_hash is not None and commitment.configuration_hash != configuration_hash:
            raise ValueError("Validation Report locator configuration scope mismatch")
        if commitment.evidence_access_class == "hash_committed":
            raise PermissionError("Validation Report body is hash-committed only")
        if commitment.evidence_access_class in {"encrypted", "restricted"}:
            if self.custody_access_checker is None or not self.custody_access_checker(
                requester_subject=requester_subject,
                commitment=commitment,
            ):
                raise PermissionError("Validation Report custody access is not authorized")
        return self.get_custody_report_body(report_hash)

    def report_custody_metadata(self, *, report_id: str) -> dict:
        """Return operator-visible custody metadata without exposing report bytes."""
        report = self.store.get_report(report_id)
        commitment = self.store.get_report_commitment(report_id)
        custody_object = next(
            (
                item
                for item in self.store.list_report_custody_objects()
                if item.report_hash == commitment.report_hash
            ),
            None,
        )
        custody_state = next(
            (
                item
                for item in self.store.list_report_custody_states()
                if item.report_hash == commitment.report_hash
            ),
            None,
        )
        receipts = [
            item
            for item in self.store.list_report_storage_receipts()
            if item.report_hash == commitment.report_hash
        ]
        failures = [
            item
            for item in self.store.list_report_storage_failures()
            if item.report_hash == commitment.report_hash
        ]
        challenges = [
            item
            for item in self.store.list_report_custody_challenges()
            if item.report_hash == commitment.report_hash
        ]
        return {
            "report_id": report.report_id,
            "endpoint_id": report.endpoint_id,
            "configuration_hash": report.configuration_hash,
            "commitment": commitment.model_dump(mode="json"),
            "custody_object": (
                custody_object.model_dump(mode="json")
                if custody_object is not None
                else None
            ),
            "custody_state": (
                custody_state.model_dump(mode="json")
                if custody_state is not None
                else None
            ),
            "storage_receipts": [item.model_dump(mode="json") for item in receipts],
            "storage_failures": [item.model_dump(mode="json") for item in failures],
            "custody_challenges": [item.model_dump(mode="json") for item in challenges],
            "custody_retirements": [
                item.model_dump(mode="json")
                for item in self.store.list_report_custody_retirings()
                if item.report_hash == commitment.report_hash
            ],
        }

    def custody_summary(
        self,
        endpoint_id: str,
        *,
        configuration_hash: str | None = None,
    ) -> dict:
        """Return a public-safe aggregate custody view for one Endpoint scope."""
        reports = [
            item
            for item in self.store.list_reports_for_endpoint(endpoint_id)
            if configuration_hash is None or item.configuration_hash == configuration_hash
        ]
        states = [
            item
            for item in self.store.list_report_custody_states()
            if item.endpoint_id == endpoint_id
            and (
                configuration_hash is None
                or item.configuration_hash == configuration_hash
            )
        ]
        status_counts: dict[str, int] = {}
        for state in states:
            status_counts[state.status] = status_counts.get(state.status, 0) + 1

        checked_report_count = len(states)
        available_report_count = status_counts.get("available", 0)
        attention_report_count = checked_report_count - available_report_count
        if not reports:
            custody_status = "not_reported"
        elif not states:
            custody_status = "not_checked"
        elif checked_report_count < len(reports):
            custody_status = "partially_checked"
        elif attention_report_count:
            custody_status = "attention_required"
        else:
            custody_status = "available"

        checked_at = [item.last_checked_at for item in states if item.last_checked_at]
        retirements = [
            item
            for item in self.store.list_report_custody_retirings()
            if item.endpoint_id == endpoint_id
            and (
                configuration_hash is None
                or item.configuration_hash == configuration_hash
            )
        ]
        summary = {
            "custody_status": custody_status,
            "report_count": len(reports),
            "checked_report_count": checked_report_count,
            "available_report_count": available_report_count,
            "attention_report_count": attention_report_count,
            "latest_checked_at": max(checked_at) if checked_at else None,
        }
        if retirements:
            summary.update(
                {
                    "retirement_pending_count": sum(
                        1 for item in retirements if item.status == "pending"
                    ),
                    "retirement_released_count": sum(
                        1 for item in retirements if item.status == "released"
                    ),
                }
            )
        return summary

    def build_report_transfer_envelope(
        self,
        *,
        report_id: str,
    ) -> ValidationReportTransferEnvelope:
        """Build the RFC-0064 payload binding a report to its assignment scope."""
        report = self.store.get_report(report_id)
        request = self.store.get_request(report.request_id)
        if request.assignment_id is None or request.authorization_id is None:
            raise ValueError("validation report has no assignment-scoped authorization")
        assignment = next(
            (
                item
                for item in self.store.list_assignments()
                if item.assignment_id == request.assignment_id
            ),
            None,
        )
        authorization = next(
            (
                item
                for item in self.store.list_authorizations()
                if item.authorization_id == request.authorization_id
            ),
            None,
        )
        if assignment is None or assignment.request_id != request.request_id:
            raise ValueError("validation assignment does not bind to report request")
        if authorization is None or authorization.request_id != request.request_id:
            raise ValueError("validation authorization does not bind to report request")
        if authorization.status != "issued":
            raise ValueError("validation authorization is not active")
        if datetime.fromisoformat(authorization.expires_at) <= datetime.now(UTC):
            raise ValueError("validation authorization is expired")
        commitment = self.store.get_report_commitment(report_id)
        validator_entry = next(
            (
                item
                for item in self.store.list_validator_entries()
                if item.validator_id == assignment.validator_id
            ),
            None,
        )
        registered_key = next(
            (
                item
                for item in self.store.list_validator_key_bindings()
                if item.validator_id == assignment.validator_id and item.status == "active"
            ),
            None,
        )
        expected_transfer_key = (
            registered_key.transfer_public_key
            if registered_key is not None
            else validator_entry.transfer_public_key if validator_entry is not None else None
        )
        if self.require_canonical_validator_transfer_identity:
            if self.transfer_signer is None:
                raise ValueError("canonical validator transfer signer is not configured")
            if registered_key is None or not expected_transfer_key:
                raise ValueError("assigned validator transfer key is not registered")
            if self.transfer_signer.public_key != expected_transfer_key:
                raise ValueError("configured transfer signer does not match assigned validator")
        transfer_seed = canonical_validation_hash(
            {
                "report_id": report.report_id,
                "request_id": request.request_id,
                "assignment_id": assignment.assignment_id,
                "authorization_id": authorization.authorization_id,
                "endpoint_id": report.endpoint_id,
                "endpoint_configuration_hash": report.configuration_hash,
                "report_hash": commitment.report_hash,
            }
        )
        unsigned_envelope = ValidationReportTransferEnvelope(
            transfer_id=f"report-transfer-{transfer_seed.removeprefix('sha256:')}",
            report_id=report.report_id,
            request_id=request.request_id,
            assignment_id=assignment.assignment_id,
            validator_id=assignment.validator_id,
            authorization_id=authorization.authorization_id,
            endpoint_id=report.endpoint_id,
            endpoint_configuration_hash=report.configuration_hash,
            report_hash=commitment.report_hash,
            report_size=commitment.report_size,
            report_locator=commitment.report_locator,
            created_at=self._now(),
        )
        if self.transfer_signer is None:
            return unsigned_envelope
        envelope = unsigned_envelope.model_copy(
            update={"validator_public_key": self.transfer_signer.public_key}
        )
        envelope = envelope.model_copy(
            update={
                "validator_signature": self.transfer_signer.sign(
                    transfer_envelope_signing_payload(envelope)
                )
            }
        )
        verify_report_transfer_envelope(envelope)
        return envelope

    def accept_report_transfer(
        self,
        *,
        envelope: ValidationReportTransferEnvelope,
        report: ValidationReport,
    ) -> ValidationReportCustodyObject:
        """Validate and durably accept a report transferred over the Validation channel."""
        if self.require_signed_transfer_envelope and not envelope.validator_signature:
            raise ValueError("signed validation report transfer envelope is required")
        verify_report_transfer_envelope(envelope)
        request = self.store.get_request(envelope.request_id)
        if request.assignment_id != envelope.assignment_id:
            raise ValueError("validation transfer assignment does not match request")
        if request.authorization_id != envelope.authorization_id:
            raise ValueError("validation transfer authorization does not match request")
        if request.endpoint_id != envelope.endpoint_id:
            raise ValueError("validation transfer endpoint does not match request")
        if request.configuration_hash != envelope.endpoint_configuration_hash:
            raise ValueError("validation transfer configuration does not match request")
        if report.report_id != envelope.report_id or report.request_id != request.request_id:
            raise ValueError("validation transfer report does not match envelope")
        assignment = next(
            (
                item
                for item in self.store.list_assignments()
                if item.assignment_id == request.assignment_id
            ),
            None,
        )
        if assignment is None or assignment.request_id != request.request_id:
            raise ValueError("validation transfer assignment is not registered")
        if envelope.validator_id is None:
            if self.require_canonical_validator_transfer_identity:
                raise ValueError("validation transfer validator identity is required")
        elif envelope.validator_id != assignment.validator_id:
            raise ValueError("validation transfer validator does not match assignment")
        if report.validator_id is not None and report.validator_id != assignment.validator_id:
            raise ValueError("validation transfer report validator does not match assignment")
        validator_entry = next(
            (
                item
                for item in self.store.list_validator_entries()
                if item.validator_id == assignment.validator_id
            ),
            None,
        )
        registered_key = next(
            (
                item
                for item in self.store.list_validator_key_bindings()
                if item.validator_id == assignment.validator_id and item.status == "active"
            ),
            None,
        )
        expected_transfer_key = (
            registered_key.transfer_public_key
            if registered_key is not None
            else validator_entry.transfer_public_key if validator_entry is not None else None
        )
        if self.require_canonical_validator_transfer_identity and registered_key is None:
            raise ValueError("assigned validator transfer key is not registered")
        if expected_transfer_key is not None:
            if envelope.validator_public_key != expected_transfer_key:
                raise ValueError("validation transfer key does not match assigned validator")
        elif self.require_canonical_validator_transfer_identity:
            raise ValueError("assigned validator transfer key is not registered")
        if report.endpoint_id != request.endpoint_id:
            raise ValueError("validation transfer report endpoint does not match request")
        if report.configuration_hash != request.configuration_hash:
            raise ValueError("validation transfer report configuration does not match request")
        report_hash, report_size = validation_report_integrity(report)
        if report_hash != envelope.report_hash or report_size != envelope.report_size:
            raise ValueError("validation transfer report integrity does not match envelope")
        if self.custody_store is None:
            raise ValueError("Validation report custody store is not configured")
        custody_object = self.custody_store.store_report(report)
        self.store.save_report(report)
        self.store.save_report_custody_object(custody_object)
        commitment = self._create_report_commitment(request=request, report=report)
        if (
            commitment.report_hash != envelope.report_hash
            or commitment.report_locator != envelope.report_locator
        ):
            raise ValueError("validation transfer commitment does not match envelope")
        self.store.save_report_commitment(commitment)
        self._emit(
            event_type="validation_report_transfer_accepted",
            message="validation report transfer accepted into endpoint custody",
            details={
                "transfer_id": envelope.transfer_id,
                "report_id": report.report_id,
                "report_hash": report_hash,
                "endpoint_id": report.endpoint_id,
            },
        )
        return custody_object

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
        self._finalize_certification_after_storage_receipt(report)
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

    def _certification_status_for_report(self, report: ValidationReport) -> str:
        status = _derive_certification_status(
            request_kind=report.report_kind,
            recommendation=report.recommendation,
            critical_issue_count=report.critical_issue_count,
        )
        if not self.require_storage_receipt_for_positive_certification:
            return status
        if status not in {"certified", "certified_with_issues"}:
            return status
        return (
            "pending_initial"
            if report.report_kind == "initial"
            else "maintenance_in_progress"
        )

    def _finalize_certification_after_storage_receipt(
        self,
        report: ValidationReport,
    ) -> None:
        if not self.require_storage_receipt_for_positive_certification:
            return
        certification_status = _derive_certification_status(
            request_kind=report.report_kind,
            recommendation=report.recommendation,
            critical_issue_count=report.critical_issue_count,
        )
        if certification_status not in {"certified", "certified_with_issues"}:
            return
        snapshot = self.store.get_snapshot(
            report.endpoint_id,
            report.configuration_hash,
        )
        if snapshot.latest_report_id != report.report_id:
            return
        if snapshot.certification_status == certification_status:
            return
        updated_snapshot = snapshot.model_copy(
            update={
                "certification_status": certification_status,
                "validation_status": _canonical_validation_status_for(
                    certification_status
                ),
                "validated_at": report.created_at,
            }
        )
        self.store.save_snapshot(updated_snapshot)
        self._record_certification_state_update(
            endpoint_id=report.endpoint_id,
            configuration_hash=report.configuration_hash,
            certification_status=certification_status,
            latest_request_id=report.request_id,
            latest_report_id=report.report_id,
            created_at=report.created_at,
        )
        self._emit(
            event_type="validation_certification_finalized_after_custody",
            message="positive Certification finalized after storage receipt",
            details={
                "endpoint_id": report.endpoint_id,
                "report_id": report.report_id,
                "certification_status": certification_status,
            },
        )

    def record_report_storage_failure(
        self,
        *,
        report_id: str,
        failure_code: str,
        failure_details: dict | None = None,
        reported_by: str | None = None,
        attempted_at: str | None = None,
    ) -> ValidationReportStorageFailure:
        """Record an endpoint custody refusal without changing report conclusion."""
        report = self.store.get_report(report_id)
        commitment = self.store.get_report_commitment(report_id)
        if any(
            item.endpoint_id == report.endpoint_id
            and item.endpoint_configuration_hash == report.configuration_hash
            and item.report_hash == commitment.report_hash
            for item in self.store.list_report_storage_receipts()
        ):
            raise ValueError("cannot record storage failure after a storage receipt")
        failure_seed = canonical_validation_hash(
            {
                "validation_id": report.request_id,
                "endpoint_id": report.endpoint_id,
                "endpoint_configuration_hash": report.configuration_hash,
                "report_hash": commitment.report_hash,
                "failure_code": failure_code,
            }
        )
        failure = ValidationReportStorageFailure(
            failure_id=f"storage-failure-{failure_seed.removeprefix('sha256:')}",
            validation_id=report.request_id,
            endpoint_id=report.endpoint_id,
            endpoint_configuration_hash=report.configuration_hash,
            report_hash=commitment.report_hash,
            report_size=commitment.report_size,
            report_locator=commitment.report_locator,
            failure_code=failure_code,
            failure_evidence_root=canonical_validation_hash(failure_details or {}),
            reported_by=reported_by,
            attempted_at=attempted_at or self._now(),
        )
        existing = next(
            (
                item
                for item in self.store.list_report_storage_failures()
                if item.failure_id == failure.failure_id
            ),
            None,
        )
        if existing is not None:
            return existing
        self.store.save_report_storage_failure(failure)
        if self.operation_recorder is not None:
            self.operation_recorder(
                operation_type="VALIDATION_REPORT_STORAGE_FAILURE",
                origin_type="evidence_triggered",
                fee_class="protocol_sponsored",
                initiator_id=reported_by or report.report_id,
                payload={
                    "failure_id": failure.failure_id,
                    "validation_id": failure.validation_id,
                    "endpoint_id": failure.endpoint_id,
                    "endpoint_configuration_hash": failure.endpoint_configuration_hash,
                    "report_hash": failure.report_hash,
                    "report_size": failure.report_size,
                    "report_locator": failure.report_locator,
                    "retention_policy_id": commitment.retention_policy_id,
                    "failure_code": failure.failure_code,
                    "failure_evidence_root": failure.failure_evidence_root,
                    "reported_by": failure.reported_by,
                },
                created_at=failure.attempted_at,
                emitted_events=["ValidationReportStorageFailureCommitted"],
            )
        self._emit(
            event_type="validation_report_custody_failed",
            message="validation report storage was refused or failed",
            details={
                "report_id": report.report_id,
                "report_hash": commitment.report_hash,
                "failure_id": failure.failure_id,
                "failure_code": failure.failure_code,
            },
        )
        return failure

    def check_report_custody(
        self,
        *,
        report_id: str,
        challenge_id: str | None = None,
        challenger_id: str | None = None,
        independence_key: str | None = None,
        checked_at: str | None = None,
    ) -> ValidationReportCustodyState:
        """Verify local report availability without changing Certification state."""
        if self.custody_store is None:
            raise ValueError("Validation report custody store is not configured")
        report = self.store.get_report(report_id)
        commitment = self.store.get_report_commitment(report_id)
        checked_at = checked_at or self._now()
        previous = next(
            (
                item
                for item in self.store.list_report_custody_states()
                if item.report_hash == commitment.report_hash
            ),
            None,
        )
        try:
            custody_object = self.custody_store.verify_report(commitment.report_hash)
            if custody_object.report_size != commitment.report_size:
                raise ValueError("Validation report custody size does not match commitment")
            state = ValidationReportCustodyState(
                report_hash=commitment.report_hash,
                endpoint_id=report.endpoint_id,
                configuration_hash=report.configuration_hash,
                status="available",
                last_checked_at=checked_at,
                last_available_at=checked_at,
                grace_expires_at=None,
                failure_streak=0,
                latest_challenge_id=challenge_id,
            )
        except KeyError:
            grace_expires_at = (
                previous.grace_expires_at if previous is not None else None
            )
            if grace_expires_at is None:
                grace_expires_at = (
                    datetime.fromisoformat(checked_at)
                    + timedelta(seconds=self.custody_grace_period_seconds)
                ).isoformat()
            state = ValidationReportCustodyState(
                report_hash=commitment.report_hash,
                endpoint_id=report.endpoint_id,
                configuration_hash=report.configuration_hash,
                status="temporarily_unavailable",
                last_checked_at=checked_at,
                last_available_at=(
                    previous.last_available_at if previous is not None else None
                ),
                grace_expires_at=grace_expires_at,
                failure_streak=(previous.failure_streak if previous is not None else 0)
                + 1,
                latest_challenge_id=challenge_id,
            )
        except ValueError:
            state = ValidationReportCustodyState(
                report_hash=commitment.report_hash,
                endpoint_id=report.endpoint_id,
                configuration_hash=report.configuration_hash,
                status="corrupted",
                last_checked_at=checked_at,
                last_available_at=(
                    previous.last_available_at if previous is not None else None
                ),
                grace_expires_at=None,
                failure_streak=(previous.failure_streak if previous is not None else 0)
                + 1,
                latest_challenge_id=challenge_id,
            )
        self.store.save_report_custody_state(state)
        self._apply_custody_certification_lifecycle(report=report, state=state)
        if self.operation_recorder is not None:
            self.operation_recorder(
                operation_type="VALIDATION_REPORT_AVAILABILITY_COMMIT",
                origin_type="protocol",
                fee_class="protocol_sponsored",
                initiator_id=report.endpoint_id,
                payload={
                    "report_id": report.report_id,
                    "report_hash": state.report_hash,
                    "endpoint_id": state.endpoint_id,
                    "endpoint_configuration_hash": state.configuration_hash,
                    "report_size": commitment.report_size,
                    "report_locator": commitment.report_locator,
                    "retention_policy_id": commitment.retention_policy_id,
                    "custody_status": state.status,
                    "failure_streak": state.failure_streak,
                    "challenge_id": state.latest_challenge_id,
                    "challenger_id": challenger_id,
                    "independence_key": independence_key,
                },
                created_at=checked_at,
                emitted_events=["ValidationReportAvailabilityCommitted"],
            )
        return state

    def challenge_report_custody(
        self,
        *,
        report_id: str,
        challenge_id: str,
        challenger_id: str,
        observation_role: ValidationCustodyObservationRole = "origin",
        checked_at: str | None = None,
    ) -> ValidationReportCustodyChallenge:
        """Run and persist one idempotent custody challenge."""
        if not challenge_id.strip():
            raise ValueError("challenge_id is required")
        if not challenger_id.strip():
            raise ValueError("challenger_id is required")
        report = self.store.get_report(report_id)
        commitment = self.store.get_report_commitment(report_id)
        independence_key = self._custody_independence_key(challenger_id)
        existing = next(
            (
                item
                for item in self.store.list_report_custody_challenges()
                if item.challenge_id == challenge_id
            ),
            None,
        )
        if existing is not None:
            if (
                existing.report_id != report_id
                or existing.report_hash != commitment.report_hash
                or existing.challenger_id != challenger_id
                or existing.observation_role != observation_role
            ):
                raise ValueError("Validation custody challenge conflicts with prior identity")
            return existing
        if commitment.evidence_access_class in {"encrypted", "restricted"}:
            if self.custody_access_checker is None or not self.custody_access_checker(
                requester_subject=challenger_id,
                commitment=commitment,
            ):
                raise PermissionError("Validation custody challenge access is not authorized")
        checked_at = checked_at or self._now()
        state = self.check_report_custody(
            report_id=report_id,
            challenge_id=challenge_id,
            challenger_id=challenger_id,
            independence_key=independence_key,
            checked_at=checked_at,
        )
        observed_report_size: int | None = None
        if state.status == "available":
            if self.custody_store is None:
                raise ValueError("Validation report custody store is not configured")
            observed_report_size = self.custody_store.verify_report(
                commitment.report_hash
            ).report_size
        evidence_root = canonical_validation_hash(
            {
                "challenge_id": challenge_id,
                "report_id": report_id,
                "report_hash": commitment.report_hash,
                "endpoint_id": report.endpoint_id,
                "configuration_hash": report.configuration_hash,
                "custody_status": state.status,
                "observation_role": observation_role,
                "observed_report_size": observed_report_size,
                "checked_at": checked_at,
                "independence_key": independence_key,
            }
        )
        challenge = ValidationReportCustodyChallenge(
            challenge_id=challenge_id,
            report_id=report_id,
            report_hash=commitment.report_hash,
            endpoint_id=report.endpoint_id,
            configuration_hash=report.configuration_hash,
            challenger_id=challenger_id,
            requested_at=self._now(),
            checked_at=checked_at,
            outcome=state.status,
            observation_role=observation_role,
            observed_report_size=observed_report_size,
            evidence_root=evidence_root,
            independence_key=independence_key,
        )
        self.store.save_report_custody_challenge(challenge)
        self._emit(
            event_type="validation_report_custody_challenged",
            message="Validation Report custody challenge completed",
            details={
                "challenge_id": challenge_id,
                "report_id": report_id,
                "report_hash": commitment.report_hash,
                "challenger_id": challenger_id,
                "outcome": state.status,
                "evidence_root": evidence_root,
                "quorum": self.custody_challenge_summary(report_id=report_id),
            },
        )
        return challenge

    def custody_challenge_summary(self, *, report_id: str) -> dict:
        """Return independent custody observations without changing state."""
        report = self.store.get_report(report_id)
        commitment = self.store.get_report_commitment(report_id)
        challenges = [
            item
            for item in self.store.list_report_custody_challenges()
            if item.report_id == report_id
        ]
        independent_keys = {
            item.independence_key or f"subject:{item.challenger_id}"
            for item in challenges
        }
        role_independent_keys: dict[str, set[str]] = {"origin": set(), "mirror": set()}
        outcome_counts: dict[str, int] = {}
        outcome_counts_by_role: dict[str, dict[str, int]] = {
            "origin": {},
            "mirror": {},
        }
        for item in challenges:
            role_independent_keys[item.observation_role].add(
                item.independence_key or f"subject:{item.challenger_id}"
            )
            outcome_counts[item.outcome] = outcome_counts.get(item.outcome, 0) + 1
            role_counts = outcome_counts_by_role[item.observation_role]
            role_counts[item.outcome] = role_counts.get(item.outcome, 0) + 1
        independent_observation_count = len(independent_keys)
        origin_independent_observation_count = len(role_independent_keys["origin"])
        mirror_independent_observation_count = len(role_independent_keys["mirror"])
        return {
            "report_id": report.report_id,
            "report_hash": commitment.report_hash,
            "endpoint_id": report.endpoint_id,
            "configuration_hash": report.configuration_hash,
            "quorum_required": self.custody_challenge_quorum,
            "independent_observation_count": independent_observation_count,
            "quorum_state": (
                "confirmed"
                if origin_independent_observation_count >= self.custody_challenge_quorum
                else "pending"
            ),
            "origin_independent_observation_count": origin_independent_observation_count,
            "mirror_independent_observation_count": mirror_independent_observation_count,
            "origin_quorum_state": (
                "confirmed"
                if origin_independent_observation_count >= self.custody_challenge_quorum
                else "pending"
            ),
            "mirror_quorum_state": (
                "confirmed"
                if mirror_independent_observation_count >= self.custody_challenge_quorum
                else "pending"
            ),
            "outcome_counts": outcome_counts,
            "outcome_counts_by_role": outcome_counts_by_role,
            "challenge_count": len(challenges),
        }

    def schedule_custody_challenges(
        self,
        *,
        epoch_id: str,
        seed: str,
        observer_ids: list[str],
        observer_roles: dict[str, ValidationCustodyObservationRole] | None = None,
        scheduled_at: str | None = None,
        max_tasks: int | None = None,
    ) -> list[ValidationReportCustodyCheckTask]:
        """Create deterministic, durable custody observation tasks.

        Scheduling only commits work assignments. It does not read report
        bodies, derive Certification, or apply Reputation consequences.
        """
        if not epoch_id.strip():
            raise ValueError("epoch_id is required")
        if not seed.strip():
            raise ValueError("seed is required")
        if not observer_ids or any(not observer_id.strip() for observer_id in observer_ids):
            raise ValueError("observer_ids must contain non-empty identities")
        if max_tasks is not None and max_tasks < 1:
            raise ValueError("max_tasks must be positive")
        normalized_observers = sorted(set(observer_ids))
        normalized_roles = dict(observer_roles or {})
        unknown_roles = set(normalized_roles).difference(normalized_observers)
        if unknown_roles:
            raise ValueError("observer_roles contains an unknown observer")
        scheduled_value = self._normalize_custody_timestamp(
            scheduled_at or self._now()
        ).isoformat()
        commitments = sorted(
            (
                item
                for item in self.store.list_report_commitments()
                if item.evidence_access_class != "hash_committed"
            ),
            key=lambda item: (item.report_hash, item.report_id),
        )
        assignments: list[
            tuple[ValidationReportCommitment, str, str, ValidationCustodyObservationRole]
        ] = []
        for commitment in commitments:
            candidates = sorted(
                normalized_observers,
                key=lambda observer_id: canonical_validation_hash(
                    {
                        "epoch_id": epoch_id,
                        "seed": seed,
                        "report_hash": commitment.report_hash,
                        "observer_id": observer_id,
                    }
                ),
            )
            selected: list[tuple[str, str]] = []
            seen_independence_keys: set[str] = set()
            for observer_id in candidates:
                independence_key = self._custody_independence_key(observer_id)
                if independence_key in seen_independence_keys:
                    continue
                seen_independence_keys.add(independence_key)
                selected.append((observer_id, independence_key))
                if len(selected) == self.custody_challenge_quorum:
                    break
            if len(selected) < self.custody_challenge_quorum:
                raise ValueError(
                    "insufficient independent custody observers for configured quorum"
                )
            assignments.extend(
                (
                    commitment,
                    observer_id,
                    independence_key,
                    normalized_roles.get(observer_id, "origin"),
                )
                for observer_id, independence_key in selected
            )
            if max_tasks is not None and len(assignments) >= max_tasks:
                break

        tasks: list[ValidationReportCustodyCheckTask] = []
        for commitment, observer_id, independence_key, observation_role in assignments[:max_tasks]:
            task_id = "custody-task-" + canonical_validation_hash(
                {
                    "epoch_id": epoch_id,
                    "seed": seed,
                    "report_id": commitment.report_id,
                    "report_hash": commitment.report_hash,
                    "endpoint_id": commitment.endpoint_id,
                    "configuration_hash": commitment.configuration_hash,
                    "observer_id": observer_id,
                    "independence_key": independence_key,
                    "required_quorum": self.custody_challenge_quorum,
                    "observation_role": observation_role,
                }
            ).removeprefix("sha256:")
            try:
                existing = self.store.get_report_custody_task(task_id)
            except KeyError:
                existing = None
            if existing is not None:
                tasks.append(existing)
                continue
            challenge_id = "custody-challenge-" + task_id.removeprefix(
                "custody-task-"
            )
            task_evidence_root = canonical_validation_hash(
                {
                    "task_id": task_id,
                    "epoch_id": epoch_id,
                    "seed": seed,
                    "report_id": commitment.report_id,
                    "report_hash": commitment.report_hash,
                    "endpoint_id": commitment.endpoint_id,
                    "configuration_hash": commitment.configuration_hash,
                    "observer_id": observer_id,
                    "independence_key": independence_key,
                    "required_quorum": self.custody_challenge_quorum,
                    "observation_role": observation_role,
                    "scheduled_at": scheduled_value,
                }
            )
            task = ValidationReportCustodyCheckTask(
                task_id=task_id,
                epoch_id=epoch_id,
                seed=seed,
                report_id=commitment.report_id,
                report_hash=commitment.report_hash,
                endpoint_id=commitment.endpoint_id,
                configuration_hash=commitment.configuration_hash,
                observer_id=observer_id,
                independence_key=independence_key,
                challenge_id=challenge_id,
                required_quorum=self.custody_challenge_quorum,
                observation_role=observation_role,
                scheduled_at=scheduled_value,
                task_evidence_root=task_evidence_root,
            )
            self.store.save_report_custody_task(task)
            self._emit(
                event_type="validation_report_custody_task_scheduled",
                message="Validation Report custody challenge scheduled",
                details={
                    "task_id": task.task_id,
                    "epoch_id": task.epoch_id,
                    "report_id": task.report_id,
                    "report_hash": task.report_hash,
                    "observer_id": task.observer_id,
                    "independence_key": task.independence_key,
                    "challenge_id": task.challenge_id,
                    "required_quorum": task.required_quorum,
                    "observation_role": task.observation_role,
                    "task_evidence_root": task.task_evidence_root,
                },
            )
            tasks.append(task)
        return tasks

    def run_scheduled_custody_challenge(
        self,
        *,
        task_id: str,
        checked_at: str | None = None,
    ) -> ValidationReportCustodyCheckTask:
        """Execute one scheduled custody task with crash-safe replay semantics."""
        task = self.store.get_report_custody_task(task_id)
        if task.status == "completed":
            return task
        challenge = self.challenge_report_custody(
            report_id=task.report_id,
            challenge_id=task.challenge_id,
            challenger_id=task.observer_id,
            observation_role=task.observation_role,
            checked_at=checked_at,
        )
        completed = task.model_copy(
            update={
                "status": "completed",
                "completed_at": checked_at or challenge.checked_at,
                "outcome": challenge.outcome,
                "challenge_evidence_root": challenge.evidence_root,
            }
        )
        self.store.save_report_custody_task(completed)
        self._emit(
            event_type="validation_report_custody_task_completed",
            message="Validation Report custody challenge task completed",
            details={
                "task_id": completed.task_id,
                "challenge_id": completed.challenge_id,
                "report_id": completed.report_id,
                "outcome": completed.outcome,
                "challenge_evidence_root": completed.challenge_evidence_root,
                "quorum": self.custody_challenge_summary(report_id=completed.report_id),
            },
        )
        return completed

    def request_endpoint_retirement(
        self,
        *,
        endpoint_id: str,
        requested_at: str | None = None,
        release_reason: str = "endpoint_retired",
    ) -> list[ValidationReportCustodyRetirement]:
        """Schedule report custody release after the Endpoint grace period.

        Retirement is deliberately non-destructive: commitments, report hashes,
        custody objects and Certification history remain available after the
        release commitment is emitted.
        """
        if not endpoint_id.strip():
            raise ValueError("endpoint_id is required")
        if not release_reason.strip():
            raise ValueError("release_reason is required")
        requested_dt = self._normalize_custody_timestamp(requested_at or self._now())
        requested_value = requested_dt.isoformat()
        eligible_value = (
            requested_dt
            + timedelta(seconds=self.custody_retirement_grace_period_seconds)
        ).isoformat()
        commitments = sorted(
            (
                item
                for item in self.store.list_report_commitments()
                if item.endpoint_id == endpoint_id
            ),
            key=lambda item: item.report_id,
        )
        scheduled: list[ValidationReportCustodyRetirement] = []
        for commitment in commitments:
            existing = next(
                (
                    item
                    for item in self.store.list_report_custody_retirings()
                    if item.report_hash == commitment.report_hash
                    and item.endpoint_id == endpoint_id
                    and item.configuration_hash == commitment.configuration_hash
                ),
                None,
            )
            if existing is not None:
                scheduled.append(existing)
                continue
            retirement_id = "retirement-" + canonical_validation_hash(
                {
                    "report_id": commitment.report_id,
                    "report_hash": commitment.report_hash,
                    "endpoint_id": endpoint_id,
                    "configuration_hash": commitment.configuration_hash,
                }
            ).removeprefix("sha256:")
            evidence_root = canonical_validation_hash(
                {
                    "retirement_id": retirement_id,
                    "report_id": commitment.report_id,
                    "report_hash": commitment.report_hash,
                    "endpoint_id": endpoint_id,
                    "configuration_hash": commitment.configuration_hash,
                    "requested_at": requested_value,
                    "eligible_at": eligible_value,
                    "release_reason": release_reason,
                }
            )
            retirement = ValidationReportCustodyRetirement(
                retirement_id=retirement_id,
                report_id=commitment.report_id,
                report_hash=commitment.report_hash,
                endpoint_id=endpoint_id,
                configuration_hash=commitment.configuration_hash,
                requested_at=requested_value,
                eligible_at=eligible_value,
                release_reason=release_reason,
                evidence_root=evidence_root,
            )
            self.store.save_report_custody_retirement(retirement)
            self._emit(
                event_type="validation_report_custody_retirement_requested",
                message="Validation Report custody retirement scheduled",
                details={
                    "retirement_id": retirement.retirement_id,
                    "report_id": retirement.report_id,
                    "report_hash": retirement.report_hash,
                    "endpoint_id": retirement.endpoint_id,
                    "configuration_hash": retirement.configuration_hash,
                    "eligible_at": retirement.eligible_at,
                    "release_reason": retirement.release_reason,
                },
            )
            scheduled.append(retirement)
        return scheduled

    def sweep_custody_retirements(
        self,
        *,
        now: str | None = None,
    ) -> list[ValidationReportCustodyRetirement]:
        """Emit due custody release commitments and return newly released items."""
        now_dt = self._normalize_custody_timestamp(now or self._now())
        released: list[ValidationReportCustodyRetirement] = []
        for retirement in sorted(
            self.store.list_report_custody_retirings(),
            key=lambda item: item.retirement_id,
        ):
            if retirement.status != "pending":
                continue
            if now_dt < self._normalize_custody_timestamp(retirement.eligible_at):
                continue
            commitment = self.store.get_report_commitment(retirement.report_id)
            released_at = retirement.eligible_at
            payload = {
                "report_id": retirement.report_id,
                "validation_id": commitment.request_id,
                "report_hash": retirement.report_hash,
                "endpoint_id": retirement.endpoint_id,
                "endpoint_configuration_hash": retirement.configuration_hash,
                "report_size": commitment.report_size,
                "report_locator": commitment.report_locator,
                "retention_policy_id": commitment.retention_policy_id,
                "release_reason": retirement.release_reason,
                "released_at": released_at,
            }
            operation = None
            if self.operation_recorder is not None:
                operation = self.operation_recorder(
                    operation_type="VALIDATION_REPORT_CUSTODY_RELEASE",
                    origin_type="protocol",
                    fee_class="protocol_sponsored",
                    initiator_id=retirement.endpoint_id,
                    payload=payload,
                    created_at=released_at,
                    emitted_events=["ValidationReportCustodyReleased"],
                )
            updated = retirement.model_copy(
                update={
                    "status": "released",
                    "released_at": released_at,
                    "release_operation_id": (
                        operation.get("operation_id")
                        if isinstance(operation, dict)
                        else None
                    ),
                }
            )
            self.store.save_report_custody_retirement(updated)
            self._emit(
                event_type="validation_report_custody_released",
                message="Validation Report custody retirement grace completed",
                details={
                    "retirement_id": updated.retirement_id,
                    "report_id": updated.report_id,
                    "report_hash": updated.report_hash,
                    "endpoint_id": updated.endpoint_id,
                    "configuration_hash": updated.configuration_hash,
                    "released_at": updated.released_at,
                    "release_operation_id": updated.release_operation_id,
                },
            )
            released.append(updated)
        return released

    def _apply_custody_certification_lifecycle(
        self,
        *,
        report: ValidationReport,
        state: ValidationReportCustodyState,
    ) -> None:
        if not self.enforce_custody_certification_lifecycle:
            return
        snapshot = self.store.get_snapshot(
            report.endpoint_id,
            report.configuration_hash,
        )
        if snapshot.latest_report_id != report.report_id:
            return
        positive_status = _derive_certification_status(
            request_kind=report.report_kind,
            recommendation=report.recommendation,
            critical_issue_count=report.critical_issue_count,
        )
        if positive_status not in {"certified", "certified_with_issues"}:
            return
        current_status = snapshot.certification_status
        target_status = current_status
        if state.status == "available":
            has_receipt = any(
                item.report_hash == state.report_hash
                and item.endpoint_id == report.endpoint_id
                and item.endpoint_configuration_hash == report.configuration_hash
                for item in self.store.list_report_storage_receipts()
            )
            if current_status in {"pending_initial", "maintenance_in_progress"}:
                if (
                    not self.require_storage_receipt_for_positive_certification
                    or has_receipt
                ):
                    target_status = positive_status
        elif state.status == "temporarily_unavailable":
            grace_expired = False
            if state.grace_expires_at:
                grace_expires_at = datetime.fromisoformat(state.grace_expires_at)
                checked_at = datetime.fromisoformat(state.last_checked_at or self._now())
                grace_expired = checked_at >= grace_expires_at
            if (
                current_status in {"certified", "certified_with_issues"}
                and state.failure_streak >= self.custody_failure_threshold
                and grace_expired
            ):
                target_status = "maintenance_in_progress"
        elif state.status in {"withheld", "lost", "corrupted", "access_restricted"}:
            if current_status in {"certified", "certified_with_issues"}:
                target_status = "maintenance_in_progress"

        if target_status == current_status:
            return
        validated_at = snapshot.validated_at
        if target_status in {"certified", "certified_with_issues"}:
            validated_at = report.created_at
        elif target_status == "pending_initial":
            validated_at = None
        updated_snapshot = snapshot.model_copy(
            update={
                "certification_status": target_status,
                "validation_status": _canonical_validation_status_for(target_status),
                "validated_at": validated_at,
            }
        )
        self.store.save_snapshot(updated_snapshot)
        self._record_certification_state_update(
            endpoint_id=report.endpoint_id,
            configuration_hash=report.configuration_hash,
            certification_status=target_status,
            latest_request_id=report.request_id,
            latest_report_id=report.report_id,
            created_at=state.last_checked_at or self._now(),
        )
        self._emit(
            event_type="validation_certification_custody_transition",
            message="Certification changed because of Validation Report custody state",
            details={
                "endpoint_id": report.endpoint_id,
                "report_id": report.report_id,
                "custody_status": state.status,
                "previous_certification_status": current_status,
                "certification_status": target_status,
                "failure_streak": state.failure_streak,
                "grace_expires_at": state.grace_expires_at,
            },
        )

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
            evidence_access_class=request.evidence_access_class,
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
        return datetime.now(UTC).isoformat()

    def _custody_independence_key(self, challenger_id: str) -> str:
        control_group = self.custody_known_control_groups.get(challenger_id)
        if control_group is not None and control_group.strip():
            return f"control-group:{control_group}"
        return f"subject:{challenger_id}"

    @staticmethod
    def _normalize_custody_timestamp(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("custody timestamp must be ISO-8601") from error
        if parsed.tzinfo is None:
            raise ValueError("custody timestamp must include a timezone")
        return parsed.astimezone(UTC)

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid4().hex[:12]}"
