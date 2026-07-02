from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from aidn_hypervisor.validation.escrow import (
    LocalOperatorBondEscrowAdapter,
    LocalValidatorEscrowPoolAdapter,
)
from aidn_hypervisor.validation.models import (
    ValidationAssignment,
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
    authorizations: list


class ValidationService:
    def __init__(
        self,
        store,
        *,
        bond_escrow=None,
        event_recorder=None,
    ) -> None:
        self.store = store
        self.bond_escrow = bond_escrow or LocalOperatorBondEscrowAdapter()
        self.validator_escrow = LocalValidatorEscrowPoolAdapter()
        self.event_recorder = event_recorder

    def request_validation(
        self,
        *,
        endpoint_id: str,
        owner_wallet: str,
        configuration_hash: str,
        minimum_session_deposit_q: float,
    ) -> ValidationRequestOutcome:
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
        self.store.save_request(
            request,
            minimum_session_deposit_q=minimum_session_deposit_q,
        )
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
        assignments: list[ValidationAssignment] = []
        authorizations = []
        for index, request in enumerate(queued_requests):
            validator_id = shuffled[index % len(shuffled)]
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

    def submit_validation_report(
        self,
        *,
        request_id: str,
        outcome: str,
        validator_label: str,
        evidence_summary: str,
    ) -> ValidationReportOutcome:
        request = self.store.get_request(request_id)
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
                }
            )
            updated_request = request.model_copy(update={"status": "failed"})
            event_type = "maintenance_validation_failed"
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
