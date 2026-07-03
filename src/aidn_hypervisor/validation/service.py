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
    ValidationEpoch,
    ValidationReport,
    ValidationRequest,
    ValidationStatusSnapshot,
    ValidationValidatorEntry,
)


DEFAULT_VALIDATION_BOND_Q = 500.0


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
    ) -> None:
        self.store = store
        self.bond_escrow = bond_escrow or LocalOperatorBondEscrowAdapter()
        self.validator_escrow = validator_escrow or LocalValidatorEscrowPoolAdapter()
        self.event_recorder = event_recorder

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
            status="pending_initial",
            latest_request_id=request_id,
        )
        self.store.save_request(request)
        self.store.save_bond(bond)
        self.store.save_snapshot(snapshot)
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
        return ValidationRequestOutcome(request=request, bond=bond, snapshot=snapshot)

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
        outcome: str,
        validator_label: str,
        evidence_summary: str,
    ) -> ValidationReportOutcome:
        request = self.store.get_request(request_id)
        if request.status in {"passed", "failed", "forfeited", "revoked", "superseded"}:
            raise ValueError(f"Request is already terminal: {request_id}")
        if request.status != "authorization_issued":
            raise ValueError(
                f"Request must be authorization_issued before report submission: {request_id}"
            )
        bond = self.store.get_bond(request.bond_id)
        report = ValidationReport(
            report_id=self._new_id("report"),
            request_id=request.request_id,
            endpoint_id=request.endpoint_id,
            configuration_hash=request.configuration_hash,
            outcome=outcome,
            report_kind="initial",
            validator_label=validator_label,
            evidence_summary=evidence_summary,
            created_at=self._now(),
        )
        request_status = "passed" if outcome == "pass" else "failed"
        snapshot_status = "validated" if outcome == "pass" else "validation_failed"
        validated_at = report.created_at if outcome == "pass" else None
        updated_request = request.model_copy(update={"status": request_status})
        updated_snapshot = self.store.get_snapshot(
            request.endpoint_id,
            request.configuration_hash,
        ).model_copy(
            update={
                "status": snapshot_status,
                "latest_request_id": request.request_id,
                "latest_report_id": report.report_id,
                "validated_at": validated_at,
            }
        )
        self.store.save_report(report)
        self.store.save_request(updated_request)
        self.store.save_snapshot(updated_snapshot)
        self._emit(
            event_type=(
                "validation_request_passed"
                if outcome == "pass"
                else "validation_request_failed"
            ),
            message="validation report submitted",
            details={
                "request_id": request.request_id,
                "report_id": report.report_id,
                "endpoint_id": request.endpoint_id,
                "outcome": outcome,
            },
        )
        return ValidationReportOutcome(
            request=updated_request,
            bond=bond,
            snapshot=updated_snapshot,
            report=report,
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
        request_ids = {item.request_id for item in requests}
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
        resolved_configuration_hash = configuration_hash or (
            current_snapshot.configuration_hash
            if current_snapshot is not None
            else latest_request.configuration_hash
            if latest_request is not None
            else None
        )
        latest_bond = (
            self.store.get_bond(latest_request.bond_id)
            if latest_request is not None
            else None
        )
        return {
            "endpoint_id": endpoint_id,
            "configuration_hash": resolved_configuration_hash,
            "validation_status": (
                current_snapshot.status
                if current_snapshot is not None
                else "unvalidated"
            ),
            "latest_request_id": (
                current_snapshot.latest_request_id
                if current_snapshot is not None
                else latest_request.request_id
                if latest_request is not None
                else None
            ),
            "latest_report_id": (
                current_snapshot.latest_report_id
                if current_snapshot is not None
                else None
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
            "request_count": len(requests),
            "report_count": len(reports),
            "assigned_request_count": sum(
                1 for item in requests if item.assignment_id is not None
            ),
            "validated_request_count": sum(
                1 for item in requests if item.status == "passed"
            ),
            "failed_request_count": sum(
                1 for item in requests if item.status == "failed"
            ),
            "active_request_ids": [
                item.request_id
                for item in requests
                if item.status in {"queued", "authorization_issued"}
            ],
            "assignment_count": sum(
                1
                for item in self.store.list_assignments()
                if item.request_id in request_ids
            ),
            "authorization_count": sum(
                1
                for item in self.store.list_authorizations()
                if item.request_id in request_ids
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
                "status": "superseded",
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
            "snapshots": [item.model_dump(mode="json") for item in snapshots],
            "epochs": [item.model_dump(mode="json") for item in epochs],
            "request_count": len(request_ids),
        }

    def resolve_maintenance_by_request(
        self,
        *,
        request_id: str,
        outcome: str,
        validator_label: str,
        evidence_summary: str,
    ) -> ValidationReportOutcome:
        request = self.store.get_request(request_id)
        return self.resolve_maintenance(
            endpoint_id=request.endpoint_id,
            configuration_hash=request.configuration_hash,
            outcome=outcome,
            validator_label=validator_label,
            evidence_summary=evidence_summary,
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
                "status": "validated",
                "latest_request_id": request_id,
                "latest_report_id": report_id,
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
        outcome: str,
        validator_label: str,
        evidence_summary: str,
    ) -> ValidationReportOutcome:
        snapshot = self.store.get_snapshot(endpoint_id, configuration_hash)
        request = self.store.latest_request_for_snapshot(endpoint_id, configuration_hash)
        if snapshot.status != "validated" or request.status != "passed":
            raise ValueError(
                "Maintenance resolution requires a validated snapshot and passed request"
            )
        bond = self.store.get_bond(request.bond_id)
        report = ValidationReport(
            report_id=self._new_id("report"),
            request_id=request.request_id,
            endpoint_id=endpoint_id,
            configuration_hash=configuration_hash,
            outcome=outcome,
            report_kind="maintenance",
            validator_label=validator_label,
            evidence_summary=evidence_summary,
            created_at=self._now(),
        )
        self.store.save_report(report)
        if outcome == "pass":
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
                    "status": "validated",
                    "latest_request_id": request.request_id,
                    "latest_report_id": report.report_id,
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
                    "status": "validation_failed",
                    "latest_request_id": request.request_id,
                    "latest_report_id": report.report_id,
                    "maintenance_count": snapshot.maintenance_count + 1,
                    "validated_at": None,
                }
            )
            updated_request = request.model_copy(update={"status": "failed"})
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
                "outcome": outcome,
            },
        )
        return ValidationReportOutcome(
            request=updated_request,
            bond=updated_bond,
            snapshot=updated_snapshot,
            report=report,
        )

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

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}-{uuid4().hex[:12]}"
