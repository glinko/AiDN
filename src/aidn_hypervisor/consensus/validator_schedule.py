"""Deterministic Validator Set schedule generation for the MVP consensus path."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from aidn_hypervisor.eligibility.models import EligibilitySnapshot, EligibilityState

if TYPE_CHECKING:
    from aidn_hypervisor.consensus.models import LedgerOperationEnvelope


def derive_epoch_selection_seed(
    *,
    previous_epoch_final_block_hash: str,
    previous_epoch_state_root: str,
    opening_epoch: int,
) -> str:
    """Derive the deterministic ECO-0006 selection seed."""
    if (
        not previous_epoch_final_block_hash.strip()
        or not previous_epoch_state_root.strip()
        or isinstance(opening_epoch, bool)
        or opening_epoch < 0
    ):
        raise ValueError("epoch selection seed inputs are invalid")
    preimage = (
        f"{previous_epoch_final_block_hash}"
        f"{previous_epoch_state_root}"
        f"{opening_epoch}"
    )
    return "sha256:" + hashlib.sha256(preimage.encode()).hexdigest()


def _validate_ed25519_public_key(value: str) -> None:
    if not value.startswith("ed25519:"):
        raise ValueError("validator candidate public key must use ed25519 encoding")
    try:
        decoded = base64.b64decode(value.removeprefix("ed25519:"), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("validator candidate public key is invalid") from error
    if len(decoded) != 32:
        raise ValueError("validator candidate public key must contain 32 bytes")


class ValidatorCandidate(BaseModel):
    """A finalized, externally-derived candidate eligible for selection."""

    node_id: str
    participant_id: str | None = None
    operator_id: str
    consensus_address: str
    consensus_public_key: str
    stake: int = Field(gt=0)
    kcg_id: str | None = None
    eligible: bool = True

    model_config = {"frozen": True}

    @field_validator(
        "node_id",
        "operator_id",
        "consensus_address",
        "consensus_public_key",
    )
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("validator candidate text field is required")
        return value

    @field_validator("consensus_public_key")
    @classmethod
    def _valid_public_key(cls, value: str) -> str:
        _validate_ed25519_public_key(value)
        return value

    @field_validator("participant_id")
    @classmethod
    def _valid_participant_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("validator candidate participant ID is invalid")
        return value


def compute_participant_suspension_root(
    participant_suspensions: Mapping[str, Mapping[str, object]] | None = None,
) -> str:
    """Commit to the participant suspension state used by schedule selection."""
    entries: list[dict[str, object]] = []
    for raw_target_id, raw_record in sorted((participant_suspensions or {}).items()):
        target_id = str(raw_target_id)
        if not target_id.strip() or not isinstance(raw_record, Mapping):
            raise ValueError("participant suspension state is invalid")
        record = dict(raw_record)
        record_target_id = record.get("target_id", target_id)
        if record_target_id != target_id:
            raise ValueError("participant suspension target ID is inconsistent")
        state = record.get("state")
        if state not in {"ACTIVE", "SUSPENDED"}:
            raise ValueError("participant suspension state is invalid")
        effective_epoch = record.get("effective_epoch", 0)
        recovery_epoch = record.get("minimum_recovery_epoch", 0)
        if (
            isinstance(effective_epoch, bool)
            or not isinstance(effective_epoch, int)
            or effective_epoch < 0
            or isinstance(recovery_epoch, bool)
            or not isinstance(recovery_epoch, int)
            or recovery_epoch < effective_epoch
        ):
            raise ValueError("participant suspension epochs are invalid")
        record["target_id"] = target_id
        entries.append(record)
    try:
        canonical = ValidatorScheduleBuilder._canonical_json(entries)
    except (TypeError, ValueError) as error:
        raise ValueError("participant suspension state is not serializable") from error
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compute_eligibility_evidence_root(
    *,
    snapshots: Iterable[EligibilitySnapshot],
    candidate_metadata: Mapping[str, ValidatorCandidate],
) -> str:
    """Compute the canonical commitment for one finalized eligibility snapshot."""
    snapshot_list = list(snapshots)
    snapshot_by_service: dict[str, EligibilitySnapshot] = {}
    for snapshot in snapshot_list:
        if snapshot.service_id in snapshot_by_service:
            raise ValueError("eligibility snapshot service IDs are not unique")
        snapshot_by_service[snapshot.service_id] = snapshot

    if set(snapshot_by_service) != set(candidate_metadata):
        raise ValueError("candidate metadata does not match eligibility snapshot")

    entries = []
    for service_id in sorted(snapshot_by_service):
        snapshot = snapshot_by_service[service_id]
        candidate = candidate_metadata[service_id]
        if candidate.participant_id is not None and candidate.participant_id != service_id:
            raise ValueError("candidate participant ID does not match eligibility snapshot")
        canonical_candidate = candidate.model_copy(
            update={
                "eligible": (
                    snapshot.state == EligibilityState.ACTIVE
                    and snapshot.has_duty_proof
                ),
                "participant_id": candidate.participant_id or service_id,
            }
        )
        entries.append(
            {
                "candidate": canonical_candidate.model_dump(mode="json"),
                "eligibility_snapshot": snapshot.model_dump(mode="json"),
            }
        )

    return "sha256:" + hashlib.sha256(
        ValidatorScheduleBuilder._canonical_json(entries).encode("utf-8")
    ).hexdigest()


def compute_validator_set_hash(
    validators: Iterable[Mapping[str, object]],
) -> str:
    """Compute the canonical commitment for a final Validator Set."""
    normalized: list[dict[str, object]] = []
    node_ids: set[str] = set()
    public_keys: set[str] = set()
    required_text_fields = (
        "node_id",
        "operator_id",
        "consensus_address",
        "consensus_public_key",
    )
    for raw_entry in validators:
        if not isinstance(raw_entry, Mapping):
            raise ValueError("validator set entry is invalid")
        entry = {field_name: raw_entry.get(field_name) for field_name in required_text_fields}
        for field_name, value in entry.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"validator set field is invalid: {field_name}")
        _validate_ed25519_public_key(str(entry["consensus_public_key"]))
        node_id = str(entry["node_id"])
        public_key = str(entry["consensus_public_key"])
        if node_id in node_ids or public_key in public_keys:
            raise ValueError("validator set identities are not unique")
        node_ids.add(node_id)
        public_keys.add(public_key)

        stake = raw_entry.get("stake")
        voting_power = raw_entry.get("voting_power")
        for field_name, value in (("stake", stake), ("voting_power", voting_power)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"validator set field is invalid: {field_name}")
        normalized.append(
            {
                **entry,
                "stake": stake,
                "voting_power": voting_power,
            }
        )
    normalized.sort(key=lambda entry: str(entry["node_id"]))
    return "sha256:" + hashlib.sha256(
        ValidatorScheduleBuilder._canonical_json(normalized).encode("utf-8")
    ).hexdigest()


class ValidatorScheduleConfig(BaseModel):
    """Bounded selection parameters for one deterministic schedule."""

    target_validator_count: int = Field(gt=0)
    minimum_stake: int = Field(gt=0)
    max_validators_per_kcg: int = Field(gt=0)
    retained_active_fraction_numerator: int = Field(ge=0)
    retained_active_fraction_denominator: int = Field(gt=0)
    equal_voting_power: int = Field(gt=0)

    model_config = {"frozen": True}


class ValidatorSchedule(BaseModel):
    """Canonical selection result ready for Ledger admission."""

    activation_epoch: int
    selected_candidates: list[ValidatorCandidate]
    selected_node_ids: list[str]
    retained_node_ids: list[str]
    payload: dict

    model_config = {"frozen": True}

    def to_envelope(
        self,
        *,
        created_at: str,
        expires_at: str | None = None,
        initiator_id: str = "epoch-engine",
        protocol_version: str = "0.1",
        evidence_references: Iterable[str] = (),
        signatures: Iterable[str] = (),
    ) -> LedgerOperationEnvelope:
        """Create a protocol envelope without recording or activating it."""
        from aidn_hypervisor.consensus.models import LedgerOperationEnvelope

        references = {
            self.payload["eligibility_evidence_root"],
            self.payload.get("participant_suspension_root", ""),
            *(str(reference) for reference in evidence_references),
        }
        return LedgerOperationEnvelope(
            operation_type="CONSENSUS_VALIDATOR_SET_UPDATE",
            operation_version="1.0.0",
            protocol_version=protocol_version,
            origin_type="protocol",
            initiator_id=initiator_id,
            created_at=created_at,
            expires_at=expires_at,
            target_epoch=str(self.activation_epoch),
            payload=dict(self.payload),
            evidence_references=sorted(reference for reference in references if reference),
            signatures=sorted({str(signature) for signature in signatures if str(signature)}),
        )


class ValidatorScheduleBuilder:
    """Build a deterministic schedule without mutating consensus state."""

    def __init__(self, config: ValidatorScheduleConfig) -> None:
        if (
            config.retained_active_fraction_numerator
            > config.retained_active_fraction_denominator
        ):
            raise ValueError("retained active fraction is invalid")
        self.config = config

    def build_schedule_from_eligibility_snapshots(
        self,
        *,
        snapshots: Iterable[EligibilitySnapshot],
        candidate_metadata: Mapping[str, ValidatorCandidate],
        active_validator_set: Mapping[str, Mapping[str, object]],
        activation_epoch: int,
        selection_seed: str,
        eligibility_evidence_root: str,
        participant_suspensions: Mapping[str, Mapping[str, object]] | None = None,
    ) -> ValidatorSchedule:
        """Build a schedule from the immediately preceding finalized snapshot."""
        if isinstance(activation_epoch, bool) or activation_epoch < 1:
            raise ValueError("validator schedule activation epoch is invalid")

        snapshot_list = list(snapshots)
        expected_snapshot_epoch = activation_epoch - 1
        for snapshot in snapshot_list:
            if snapshot.epoch != expected_snapshot_epoch:
                raise ValueError("eligibility snapshot epoch does not match activation epoch")
            if snapshot.state == EligibilityState.ACTIVE and not snapshot.has_duty_proof:
                raise ValueError("active eligibility snapshot is missing duty proof")
            candidate = candidate_metadata.get(snapshot.service_id)
            if candidate is None:
                raise ValueError("candidate metadata does not match eligibility snapshot")
            if candidate.kcg_id != snapshot.kcg_id:
                raise ValueError("candidate KCG does not match eligibility snapshot")

        bound_candidate_metadata = {
            service_id: self._bind_participant_id(
                candidate_metadata[service_id],
                participant_id=service_id,
            )
            for service_id in sorted(candidate_metadata)
        }
        computed_root = compute_eligibility_evidence_root(
            snapshots=snapshot_list,
            candidate_metadata=bound_candidate_metadata,
        )
        if computed_root != eligibility_evidence_root:
            raise ValueError("eligibility evidence root does not match snapshot")

        candidates = [
            bound_candidate_metadata[snapshot.service_id].model_copy(
                update={
                    "eligible": (
                        snapshot.state == EligibilityState.ACTIVE
                        and snapshot.has_duty_proof
                    )
                }
            )
            for snapshot in snapshot_list
        ]
        schedule = self.build_schedule(
            candidates=candidates,
            active_validator_set=active_validator_set,
            activation_epoch=activation_epoch,
            selection_seed=selection_seed,
            eligibility_evidence_root=computed_root,
            participant_suspensions=participant_suspensions,
        )
        return schedule.model_copy(
            update={
                "payload": {
                    **schedule.payload,
                    "eligibility_snapshot_epoch": expected_snapshot_epoch,
                }
            }
        )

    def build_schedule(
        self,
        *,
        candidates: Iterable[ValidatorCandidate],
        active_validator_set: Mapping[str, Mapping[str, object]],
        activation_epoch: int,
        selection_seed: str,
        eligibility_evidence_root: str,
        participant_suspensions: Mapping[str, Mapping[str, object]] | None = None,
    ) -> ValidatorSchedule:
        if isinstance(activation_epoch, bool) or activation_epoch < 0:
            raise ValueError("validator schedule activation epoch is invalid")
        if not selection_seed.strip():
            raise ValueError("validator selection seed is required")
        if not eligibility_evidence_root.strip():
            raise ValueError("validator eligibility evidence root is required")

        candidate_list = list(candidates)
        by_node: dict[str, ValidatorCandidate] = {}
        by_public_key: dict[str, str] = {}
        for candidate in candidate_list:
            if candidate.node_id in by_node:
                raise ValueError("validator candidate node IDs are not unique")
            if candidate.consensus_public_key in by_public_key:
                raise ValueError("validator candidate public keys are not unique")
            by_node[candidate.node_id] = candidate
            by_public_key[candidate.consensus_public_key] = candidate.node_id

        participant_suspension_root = compute_participant_suspension_root(
            participant_suspensions
        )
        suspended_participants = self._suspended_participants(
            participant_suspensions,
            activation_epoch=activation_epoch,
        )

        eligible = [
            candidate
            for candidate in candidate_list
            if (
                candidate.eligible
                and candidate.stake >= self.config.minimum_stake
                and self._participant_id(candidate) not in suspended_participants
            )
        ]
        ordered = sorted(
            eligible,
            key=lambda candidate: (
                self._selection_rank(selection_seed, candidate.node_id),
                candidate.node_id,
            ),
        )

        active_ids = {str(node_id) for node_id in active_validator_set}
        self._validate_active_snapshot(active_validator_set)
        incumbents = [candidate for candidate in ordered if candidate.node_id in active_ids]
        retention_fraction = (
            self.config.target_validator_count
            * self.config.retained_active_fraction_numerator
        ) // self.config.retained_active_fraction_denominator
        if self.config.retained_active_fraction_numerator > 0:
            retention_fraction = max(1, retention_fraction)
        retention_limit = min(
            len(incumbents),
            retention_fraction,
        )

        selected: list[ValidatorCandidate] = []
        selected_group_counts: dict[str, int] = {}

        for candidate in incumbents:
            if len(selected) >= retention_limit:
                break
            group_key = self._group_key(candidate)
            if selected_group_counts.get(group_key, 0) >= self.config.max_validators_per_kcg:
                continue
            selected.append(candidate)
            selected_group_counts[group_key] = selected_group_counts.get(group_key, 0) + 1

        for candidate in ordered:
            if len(selected) >= self.config.target_validator_count:
                break
            if candidate in selected:
                continue
            group_key = self._group_key(candidate)
            if selected_group_counts.get(group_key, 0) >= self.config.max_validators_per_kcg:
                continue
            selected.append(candidate)
            selected_group_counts[group_key] = selected_group_counts.get(group_key, 0) + 1

        selected = sorted(selected, key=lambda candidate: candidate.node_id)
        selected_ids = {candidate.node_id for candidate in selected}
        selected_public_keys = {
            candidate.consensus_public_key: candidate.node_id for candidate in selected
        }
        active_public_keys = {
            str(entry["consensus_public_key"]): str(node_id)
            for node_id, entry in active_validator_set.items()
        }
        for public_key, node_id in selected_public_keys.items():
            previous_node_id = active_public_keys.get(public_key)
            if previous_node_id is not None and previous_node_id != node_id:
                raise ValueError("validator consensus public key is already active")

        additions = [
            {
                "node_id": candidate.node_id,
                "operator_id": candidate.operator_id,
                "consensus_address": candidate.consensus_address,
                "consensus_public_key": candidate.consensus_public_key,
                "stake": candidate.stake,
                "voting_power": self.config.equal_voting_power,
            }
            for candidate in selected
            if candidate.node_id not in active_ids
        ]
        removals = [
            {"node_id": node_id}
            for node_id in sorted(active_ids - selected_ids)
        ]
        voting_power_updates = [
            {"node_id": candidate.node_id, "voting_power": self.config.equal_voting_power}
            for candidate in selected
            if candidate.node_id in active_ids
            and self._active_voting_power(active_validator_set[candidate.node_id])
            != self.config.equal_voting_power
        ]

        selected_commitment = [
            {
                "node_id": candidate.node_id,
                "operator_id": candidate.operator_id,
                "consensus_address": candidate.consensus_address,
                "consensus_public_key": candidate.consensus_public_key,
                "stake": candidate.stake,
                "voting_power": self.config.equal_voting_power,
            }
            for candidate in selected
        ]
        validator_set_hash = compute_validator_set_hash(selected_commitment)
        payload = {
            "activation_epoch": activation_epoch,
            "candidate_selection_seed": selection_seed,
            "validator_additions": additions,
            "validator_removals": removals,
            "voting_power_updates": voting_power_updates,
            "validator_set_hash": validator_set_hash,
            "eligibility_evidence_root": eligibility_evidence_root,
            "participant_suspension_root": participant_suspension_root,
        }
        return ValidatorSchedule(
            activation_epoch=activation_epoch,
            selected_candidates=selected,
            selected_node_ids=[candidate.node_id for candidate in selected],
            retained_node_ids=sorted(
                candidate.node_id for candidate in selected if candidate.node_id in active_ids
            ),
            payload=payload,
        )

    @staticmethod
    def _selection_rank(selection_seed: str, node_id: str) -> bytes:
        return hashlib.sha256(f"{selection_seed}:{node_id}".encode()).digest()

    @staticmethod
    def _group_key(candidate: ValidatorCandidate) -> str:
        return candidate.kcg_id or f"independent:{candidate.node_id}"

    @staticmethod
    def _participant_id(candidate: ValidatorCandidate) -> str:
        return candidate.participant_id or candidate.node_id

    @staticmethod
    def _bind_participant_id(
        candidate: ValidatorCandidate,
        *,
        participant_id: str,
    ) -> ValidatorCandidate:
        if candidate.participant_id is not None and candidate.participant_id != participant_id:
            raise ValueError("validator candidate participant ID does not match snapshot")
        return candidate.model_copy(update={"participant_id": participant_id})

    @classmethod
    def _suspended_participants(
        cls,
        participant_suspensions: Mapping[str, Mapping[str, object]] | None,
        *,
        activation_epoch: int,
    ) -> set[str]:
        suspended: set[str] = set()
        for raw_target_id, record in (participant_suspensions or {}).items():
            target_id = str(raw_target_id)
            if not isinstance(record, Mapping):
                raise ValueError("participant suspension state is invalid")
            state = record.get("state")
            effective_epoch = record.get("effective_epoch", 0)
            if (
                state == "SUSPENDED"
                and isinstance(effective_epoch, int)
                and not isinstance(effective_epoch, bool)
                and effective_epoch <= activation_epoch
            ):
                suspended.add(target_id)
        return suspended

    @staticmethod
    def _canonical_json(value: object) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @staticmethod
    def _validate_active_snapshot(
        active_validator_set: Mapping[str, Mapping[str, object]],
    ) -> None:
        public_keys: set[str] = set()
        for raw_node_id, entry in active_validator_set.items():
            node_id = str(raw_node_id)
            if not node_id.strip() or not isinstance(entry, Mapping):
                raise ValueError("active validator snapshot is invalid")
            public_key = entry.get("consensus_public_key")
            if not isinstance(public_key, str):
                raise ValueError("active validator snapshot public keys are invalid")
            _validate_ed25519_public_key(public_key)
            if public_key in public_keys:
                raise ValueError("active validator snapshot public keys are invalid")
            public_keys.add(public_key)
            voting_power = entry.get("voting_power")
            if (
                isinstance(voting_power, bool)
                or not isinstance(voting_power, int)
                or voting_power <= 0
            ):
                raise ValueError("active validator snapshot voting power is invalid")

    @staticmethod
    def _active_voting_power(entry: Mapping[str, object]) -> int:
        voting_power = entry.get("voting_power")
        if isinstance(voting_power, bool) or not isinstance(voting_power, int):
            raise ValueError("active validator snapshot voting power is invalid")
        return voting_power
