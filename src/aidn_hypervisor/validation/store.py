from aidn_hypervisor.state import HypervisorStateSnapshot
from aidn_hypervisor.validation.models import (
    ValidationAssignment,
    ValidationAuthorization,
    ValidationBond,
    ValidationReportCommitment,
    ValidationReportCustodyObject,
    ValidationReportCustodyState,
    ValidationEpoch,
    ValidationReport,
    ValidationReportStorageFailure,
    ValidationReportStorageReceipt,
    ValidationReportTransferReplay,
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
        self._report_commitments: dict[str, ValidationReportCommitment] = {}
        self._report_storage_receipts: dict[str, ValidationReportStorageReceipt] = {}
        self._report_storage_failures: dict[str, ValidationReportStorageFailure] = {}
        self._report_transfer_replays: dict[str, ValidationReportTransferReplay] = {}
        self._report_custody_states: dict[str, ValidationReportCustodyState] = {}
        self._report_custody_objects: dict[str, ValidationReportCustodyObject] = {}
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
        self._report_commitments = {
            item.report_id: ValidationReportCommitment.model_validate(
                item.model_dump(mode="json")
            )
            for item in snapshot.validation_report_commitments
        }
        self._report_storage_receipts = {
            item.receipt_id: ValidationReportStorageReceipt.model_validate(
                item.model_dump(mode="json")
            )
            for item in snapshot.validation_report_storage_receipts
        }
        self._report_storage_failures = {
            item.failure_id: ValidationReportStorageFailure.model_validate(
                item.model_dump(mode="json")
            )
            for item in snapshot.validation_report_storage_failures
        }
        self._report_transfer_replays = {
            item.message_id: ValidationReportTransferReplay.model_validate(
                item.model_dump(mode="json")
            )
            for item in snapshot.validation_report_transfer_replays
        }
        self._report_custody_states = {
            item.report_hash: ValidationReportCustodyState.model_validate(
                item.model_dump(mode="json")
            )
            for item in snapshot.validation_report_custody_states
        }
        self._report_custody_objects = {
            item.report_hash: ValidationReportCustodyObject.model_validate(
                item.model_dump(mode="json")
            )
            for item in snapshot.validation_report_custody_objects
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

    def save_report_commitment(self, commitment: ValidationReportCommitment) -> None:
        existing = self._report_commitments.get(commitment.report_id)
        if existing is not None and existing != commitment:
            raise ValueError(f"Validation report commitment conflict: {commitment.report_id}")
        self._report_commitments[commitment.report_id] = commitment
        self._flush()

    def get_report_commitment(self, report_id: str) -> ValidationReportCommitment:
        return self._report_commitments[report_id]

    def list_report_commitments(self) -> list[ValidationReportCommitment]:
        return list(self._report_commitments.values())

    def save_report_storage_receipt(
        self,
        receipt: ValidationReportStorageReceipt,
    ) -> None:
        existing = self._report_storage_receipts.get(receipt.receipt_id)
        if existing is not None and existing != receipt:
            raise ValueError(f"Validation report storage receipt conflict: {receipt.receipt_id}")
        self._report_storage_receipts[receipt.receipt_id] = receipt
        self._flush()

    def list_report_storage_receipts(self) -> list[ValidationReportStorageReceipt]:
        return list(self._report_storage_receipts.values())

    def save_report_storage_failure(
        self,
        failure: ValidationReportStorageFailure,
    ) -> None:
        existing = self._report_storage_failures.get(failure.failure_id)
        if existing is not None and existing != failure:
            raise ValueError(f"Validation report storage failure conflict: {failure.failure_id}")
        self._report_storage_failures[failure.failure_id] = failure
        self._flush()

    def list_report_storage_failures(self) -> list[ValidationReportStorageFailure]:
        return list(self._report_storage_failures.values())

    def get_report_transfer_replay(
        self,
        message_id: str,
    ) -> ValidationReportTransferReplay | None:
        return self._report_transfer_replays.get(message_id)

    def save_report_transfer_replay(
        self,
        replay: ValidationReportTransferReplay,
    ) -> None:
        existing = self._report_transfer_replays.get(replay.message_id)
        if existing is not None and existing != replay:
            raise ValueError(
                f"Validation report transfer replay conflict: {replay.message_id}"
            )
        self._report_transfer_replays[replay.message_id] = replay
        self._flush()

    def save_report_custody_state(self, state: ValidationReportCustodyState) -> None:
        self._report_custody_states[state.report_hash] = state
        self._flush()

    def list_report_custody_states(self) -> list[ValidationReportCustodyState]:
        return list(self._report_custody_states.values())

    def save_report_custody_object(
        self,
        custody_object: ValidationReportCustodyObject,
    ) -> None:
        existing = self._report_custody_objects.get(custody_object.report_hash)
        if existing is not None and (
            existing.report_size != custody_object.report_size
            or existing.storage_relative_path != custody_object.storage_relative_path
        ):
            raise ValueError(
                "Validation report custody object conflicts with existing report hash"
            )
        self._report_custody_objects[custody_object.report_hash] = custody_object
        self._flush()

    def get_report_custody_object(
        self,
        report_hash: str,
    ) -> ValidationReportCustodyObject:
        return self._report_custody_objects[report_hash]

    def list_report_custody_objects(self) -> list[ValidationReportCustodyObject]:
        return list(self._report_custody_objects.values())

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

    def latest_report_for_snapshot(
        self,
        endpoint_id: str,
        configuration_hash: str,
    ) -> ValidationReport:
        matching = [
            item
            for item in self._reports.values()
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
                "validation_report_commitments": list(
                    self._report_commitments.values()
                ),
                "validation_report_storage_receipts": list(
                    self._report_storage_receipts.values()
                ),
                "validation_report_storage_failures": list(
                    self._report_storage_failures.values()
                ),
                "validation_report_transfer_replays": list(
                    self._report_transfer_replays.values()
                ),
                "validation_report_custody_states": list(
                    self._report_custody_states.values()
                ),
                "validation_report_custody_objects": list(
                    self._report_custody_objects.values()
                ),
                "validation_status_snapshots": list(self._snapshots.values()),
                "validation_epochs": list(self._epochs.values()),
                "validation_validator_entries": list(self._validator_entries.values()),
                "validation_assignments": list(self._assignments.values()),
                "validation_authorizations": list(self._authorizations.values()),
            }
        )
        self._state_store.save(updated)
