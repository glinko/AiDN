from aidn_hypervisor.state import HypervisorStateSnapshot
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


class ValidationStore:
    def __init__(self, state_store=None) -> None:
        self._state_store = state_store
        self._requests: dict[str, ValidationRequest] = {}
        self._bonds: dict[str, ValidationBond] = {}
        self._reports: dict[str, ValidationReport] = {}
        self._snapshots: dict[tuple[str, str], ValidationStatusSnapshot] = {}
        self._epochs: dict[str, ValidationEpoch] = {}
        self._validator_entries: dict[str, ValidationValidatorEntry] = {}
        self._assignments: dict[str, ValidationAssignment] = {}
        self._authorizations: dict[str, ValidationAuthorization] = {}
        self.restore()

    def restore(self, snapshot: HypervisorStateSnapshot | None = None) -> None:
        if snapshot is None:
            if self._state_store is None:
                return
            snapshot = self._state_store.load()
        self._requests = {
            item.request_id: ValidationRequest.model_validate(item.model_dump(mode="json"))
            for item in snapshot.validation_requests
        }
        self._bonds = {
            item.bond_id: ValidationBond.model_validate(item.model_dump(mode="json"))
            for item in snapshot.validation_bonds
        }
        self._reports = {
            item.report_id: ValidationReport.model_validate(item.model_dump(mode="json"))
            for item in snapshot.validation_reports
        }
        self._snapshots = {
            (item.endpoint_id, item.configuration_hash): ValidationStatusSnapshot.model_validate(
                item.model_dump(mode="json")
            )
            for item in snapshot.validation_status_snapshots
        }
        self._epochs = {
            item.epoch_id: ValidationEpoch.model_validate(item.model_dump(mode="json"))
            for item in snapshot.validation_epochs
        }
        self._validator_entries = {
            item.validator_id: ValidationValidatorEntry.model_validate(
                item.model_dump(mode="json")
            )
            for item in snapshot.validation_validator_entries
        }
        self._assignments = {
            item.assignment_id: ValidationAssignment.model_validate(
                item.model_dump(mode="json")
            )
            for item in snapshot.validation_assignments
        }
        self._authorizations = {
            item.authorization_id: ValidationAuthorization.model_validate(
                item.model_dump(mode="json")
            )
            for item in snapshot.validation_authorizations
        }

    def save_request(
        self,
        request: ValidationRequest,
    ) -> None:
        self._requests[request.request_id] = request
        self._flush()

    def get_request(self, request_id: str) -> ValidationRequest:
        return self._requests[request_id]

    def list_requests(self, *, status: str | None = None) -> list[ValidationRequest]:
        requests = list(self._requests.values())
        if status is None:
            return requests
        return [item for item in requests if item.status == status]

    def list_requests_for_endpoint(self, endpoint_id: str) -> list[ValidationRequest]:
        return [item for item in self._requests.values() if item.endpoint_id == endpoint_id]

    def save_bond(self, bond: ValidationBond) -> None:
        self._bonds[bond.bond_id] = bond
        self._flush()

    def get_bond(self, bond_id: str) -> ValidationBond:
        return self._bonds[bond_id]

    def list_bonds(self) -> list[ValidationBond]:
        return list(self._bonds.values())

    def save_report(self, report: ValidationReport) -> None:
        self._reports[report.report_id] = report
        self._flush()

    def get_report(self, report_id: str) -> ValidationReport:
        return self._reports[report_id]

    def list_reports(self) -> list[ValidationReport]:
        return list(self._reports.values())

    def list_reports_for_endpoint(self, endpoint_id: str) -> list[ValidationReport]:
        return [item for item in self._reports.values() if item.endpoint_id == endpoint_id]

    def save_snapshot(self, snapshot: ValidationStatusSnapshot) -> None:
        self._snapshots[(snapshot.endpoint_id, snapshot.configuration_hash)] = snapshot
        self._flush()

    def get_snapshot(
        self,
        endpoint_id: str,
        configuration_hash: str,
    ) -> ValidationStatusSnapshot:
        return self._snapshots[(endpoint_id, configuration_hash)]

    def list_snapshots(self) -> list[ValidationStatusSnapshot]:
        return list(self._snapshots.values())

    def save_epoch(self, epoch: ValidationEpoch) -> None:
        self._epochs[epoch.epoch_id] = epoch
        self._flush()

    def list_epochs(self) -> list[ValidationEpoch]:
        return list(self._epochs.values())

    def save_validator_entry(self, entry: ValidationValidatorEntry) -> None:
        self._validator_entries[entry.validator_id] = entry
        self._flush()

    def list_validator_entries(self) -> list[ValidationValidatorEntry]:
        return list(self._validator_entries.values())

    def save_assignment(self, assignment: ValidationAssignment) -> None:
        self._assignments[assignment.assignment_id] = assignment
        self._flush()

    def list_assignments(self) -> list[ValidationAssignment]:
        return list(self._assignments.values())

    def save_authorization(self, authorization: ValidationAuthorization) -> None:
        self._authorizations[authorization.authorization_id] = authorization
        self._flush()

    def list_authorizations(self) -> list[ValidationAuthorization]:
        return list(self._authorizations.values())

    def minimum_session_deposit_for_request(self, request_id: str) -> float:
        return self.get_request(request_id).minimum_session_deposit_q

    def latest_request_for_snapshot(
        self,
        endpoint_id: str,
        configuration_hash: str,
    ) -> ValidationRequest:
        matching = [
            item
            for item in self._requests.values()
            if item.endpoint_id == endpoint_id
            and item.configuration_hash == configuration_hash
        ]
        if not matching:
            raise KeyError((endpoint_id, configuration_hash))
        matching.sort(key=lambda item: item.created_at)
        return matching[-1]

    def _flush(self) -> None:
        if self._state_store is None:
            return
        root = self._state_store.load()
        updated = root.model_copy(
            update={
                "validation_requests": list(self._requests.values()),
                "validation_bonds": list(self._bonds.values()),
                "validation_reports": list(self._reports.values()),
                "validation_status_snapshots": list(self._snapshots.values()),
                "validation_epochs": list(self._epochs.values()),
                "validation_validator_entries": list(self._validator_entries.values()),
                "validation_assignments": list(self._assignments.values()),
                "validation_authorizations": list(self._authorizations.values()),
            }
        )
        self._state_store.save(updated)
