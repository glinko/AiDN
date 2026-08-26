"""Deterministic accounting for the temporary Testnet participation program.

This module intentionally does not mint Q and does not mutate a Wallet.  It
turns finalized Node Identity heartbeat evidence into one hash-bound daily
settlement plan that a later consensus operation may execute exactly once.
"""

from __future__ import annotations

import hashlib
import json
import math
import tomllib
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.ledger.service import STANDARD_NETWORK_FEE_Q_ATOMS

TESTNET_PARTICIPATION_VERSION = "aidn.testnet-participation.v1"
MAX_TESTNET_PARTICIPATION_PROGRAM_BYTES = 128 * 1024
Q_ATOMS_PER_Q = 1_000_000
BASIS_POINTS = 10_000


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(
        (TESTNET_PARTICIPATION_VERSION + ":").encode("utf-8") + encoded
    ).hexdigest()


def _timestamp(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


class TestnetParticipationProgram(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = TESTNET_PARTICIPATION_VERSION
    program_id: str = Field(min_length=1)
    network_id: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    active_from_epoch: int = Field(ge=0)
    active_until_epoch: int | None = Field(default=None, ge=0)
    participation_window_seconds: int = Field(default=600, ge=60)
    heartbeat_interval_seconds: int = Field(default=30, ge=1)
    minimum_presence_bps: int = Field(default=8_000, ge=1, le=BASIS_POINTS)
    minimum_enrollment_seconds: int = Field(default=1_800, ge=0)
    reward_per_eligible_window_q_atoms: int = Field(default=Q_ATOMS_PER_Q, ge=0)
    settlement_period_seconds: int = Field(default=86_400, ge=600)
    compatible_protocol_versions: list[str] = Field(min_length=1)
    funding_source: Literal["TESTNET_INCENTIVE_TREASURY"] = (
        "TESTNET_INCENTIVE_TREASURY"
    )
    sunset: Literal["ACTIVE_UNTIL_EPOCH", "GOVERNANCE_TERMINATION"] = (
        "GOVERNANCE_TERMINATION"
    )

    @model_validator(mode="after")
    def validate_program(self) -> TestnetParticipationProgram:
        if self.schema_version != TESTNET_PARTICIPATION_VERSION:
            raise ValueError("TESTNET_PARTICIPATION_VERSION_INVALID")
        if self.settlement_period_seconds % self.participation_window_seconds:
            raise ValueError("PARTICIPATION_WINDOW_MUST_DIVIDE_SETTLEMENT_PERIOD")
        if self.participation_window_seconds % self.heartbeat_interval_seconds:
            raise ValueError("HEARTBEAT_INTERVAL_MUST_DIVIDE_PARTICIPATION_WINDOW")
        if (
            self.active_until_epoch is not None
            and self.active_until_epoch < self.active_from_epoch
        ):
            raise ValueError("PARTICIPATION_PROGRAM_EPOCH_RANGE_INVALID")
        if self.sunset == "ACTIVE_UNTIL_EPOCH" and self.active_until_epoch is None:
            raise ValueError("PARTICIPATION_PROGRAM_SUNSET_EPOCH_REQUIRED")
        return self

    @property
    def windows_per_settlement(self) -> int:
        return self.settlement_period_seconds // self.participation_window_seconds

    @property
    def expected_heartbeats_per_window(self) -> int:
        return self.participation_window_seconds // self.heartbeat_interval_seconds

    @property
    def required_heartbeat_slots(self) -> int:
        return math.ceil(
            self.expected_heartbeats_per_window
            * self.minimum_presence_bps
            / BASIS_POINTS
        )

    @property
    def policy_hash(self) -> str:
        return _canonical_hash(self.model_dump(mode="json"))


def load_testnet_participation_program(
    path: str | Path,
) -> TestnetParticipationProgram:
    """Load the reviewed temporary program policy from operator-readable TOML."""

    target = Path(path).expanduser()
    try:
        if target.stat().st_size > MAX_TESTNET_PARTICIPATION_PROGRAM_BYTES:
            raise ValueError("PARTICIPATION_PROGRAM_TOO_LARGE")
        with target.open("rb") as stream:
            document = tomllib.load(stream)
    except FileNotFoundError as exc:
        raise ValueError(f"participation program does not exist: {target}") from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"could not load participation program {target}: {exc}") from exc
    if set(document) != {"schema_version", "program"} or not isinstance(
        document.get("program"), dict
    ):
        raise ValueError("PARTICIPATION_PROGRAM_DOCUMENT_INVALID")
    try:
        return TestnetParticipationProgram.model_validate(
            {
                "schema_version": document["schema_version"],
                **document["program"],
            }
        )
    except ValueError as exc:
        raise ValueError(f"invalid participation program {target}: {exc}") from exc


class TestnetParticipantEnrollment(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1)
    owner_wallet: str = Field(min_length=1)
    reward_wallet: str = Field(min_length=1)
    registered_at: str
    registered_epoch: int = Field(ge=0)
    node_identity_verified: bool = True
    registration_finalized: bool = True
    banned: bool = False
    retired_at: str | None = None

    @model_validator(mode="after")
    def validate_times(self) -> TestnetParticipantEnrollment:
        _timestamp(self.registered_at, field_name="registered_at")
        if self.retired_at is not None:
            if _timestamp(self.retired_at, field_name="retired_at") <= _timestamp(
                self.registered_at, field_name="registered_at"
            ):
                raise ValueError("PARTICIPANT_RETIREMENT_INVALID")
        return self


class TestnetHeartbeatEvidence(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    network_id: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    observed_at: str
    protocol_version: str = Field(min_length=1)
    finalized: bool = True
    identity_signature_verified: bool = True
    evidence_hash: str = Field(min_length=1)
    identity_signature: str = ""

    @model_validator(mode="after")
    def validate_evidence(self) -> TestnetHeartbeatEvidence:
        _timestamp(self.observed_at, field_name="observed_at")
        if self.evidence_hash != _canonical_hash(self.unsigned_payload()):
            raise ValueError("PARTICIPATION_HEARTBEAT_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            exclude={
                "evidence_hash",
                "identity_signature",
                "identity_signature_verified",
            },
        )

    def signing_bytes(self) -> bytes:
        return json.dumps(
            {
                "domain": "aidn.testnet-participation-heartbeat.v1",
                "evidence_hash": self.evidence_hash,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def verify_integrity(self) -> bool:
        return self.evidence_hash == _canonical_hash(self.unsigned_payload())


def build_testnet_heartbeat_evidence(
    *,
    evidence_id: str,
    node_id: str,
    network_id: str,
    chain_id: str,
    observed_at: str,
    protocol_version: str,
    finalized: bool = True,
    identity_signature_verified: bool = True,
    identity_signature: str = "",
) -> TestnetHeartbeatEvidence:
    payload = {
        "evidence_id": evidence_id,
        "node_id": node_id,
        "network_id": network_id,
        "chain_id": chain_id,
        "observed_at": observed_at,
        "protocol_version": protocol_version,
        "finalized": finalized,
        "identity_signature_verified": identity_signature_verified,
        "identity_signature": identity_signature,
    }
    evidence_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"identity_signature_verified", "identity_signature"}
    }
    return TestnetHeartbeatEvidence(
        **payload,
        evidence_hash=_canonical_hash(evidence_payload),
    )


class TestnetParticipationAccrual(BaseModel, frozen=True):
    node_id: str
    reward_wallet: str
    eligible_window_indices: list[int]
    rejected_window_count: int = Field(ge=0)
    reward_q_atoms: int = Field(ge=0)


class TestnetParticipationSettlement(BaseModel, frozen=True):
    schema_version: str = TESTNET_PARTICIPATION_VERSION
    settlement_id: str
    program_id: str
    network_id: str
    chain_id: str
    protocol_epoch: int = Field(ge=0)
    source_epoch_transition_operation_id: str = Field(min_length=1)
    program_policy_hash: str = Field(min_length=1)
    period_start: str
    period_end: str
    funding_source: Literal["TESTNET_INCENTIVE_TREASURY"]
    evidence_root: str
    accruals: list[TestnetParticipationAccrual]
    total_reward_q_atoms: int = Field(ge=0)
    settlement_hash: str

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"settlement_hash"})

    def verify_integrity(self) -> bool:
        return self.settlement_hash == _canonical_hash(self.unsigned_payload())


class TestnetParticipationTransferBatch(BaseModel, frozen=True):
    """Deterministic treasury transfers derived from one finalized settlement."""

    schema_version: str = TESTNET_PARTICIPATION_VERSION
    settlement_id: str
    settlement_hash: str
    treasury_wallet: str
    transfers: list[LedgerOperationEnvelope]
    total_reward_q_atoms: int = Field(ge=0)
    total_network_fee_q_atoms: int = Field(ge=0)
    total_treasury_debit_q_atoms: int = Field(ge=0)
    batch_hash: str

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"batch_hash"})

    def verify_integrity(self) -> bool:
        return self.batch_hash == _canonical_hash(self.unsigned_payload())


def build_testnet_participation_transfer_batch(
    settlement: TestnetParticipationSettlement,
    *,
    treasury_wallet: str,
    first_sender_sequence: int,
    signer: Callable[[bytes], str],
    available_treasury_q_atoms: int | None = None,
) -> TestnetParticipationTransferBatch:
    """Turn a finalized daily plan into replay-stable treasury transfers.

    The existing ``WALLET_TRANSFER`` consensus path performs the actual debit
    and credit.  A daily settlement produces at most one transfer per earning
    Node Identity, so heartbeat frequency never becomes transaction frequency.
    Rebuilding a batch with the same settlement and starting sequence yields
    the same operation IDs.
    """

    if not settlement.verify_integrity():
        raise ValueError("PARTICIPATION_SETTLEMENT_INTEGRITY_INVALID")
    if settlement.funding_source != "TESTNET_INCENTIVE_TREASURY":
        raise ValueError("PARTICIPATION_SETTLEMENT_FUNDING_SOURCE_INVALID")
    if not treasury_wallet.strip():
        raise ValueError("PARTICIPATION_TREASURY_WALLET_REQUIRED")
    if first_sender_sequence < 1:
        raise ValueError("PARTICIPATION_TREASURY_SEQUENCE_INVALID")

    positive_accruals = sorted(
        (item for item in settlement.accruals if item.reward_q_atoms > 0),
        key=lambda item: (item.node_id, item.reward_wallet),
    )
    if len({item.node_id for item in positive_accruals}) != len(positive_accruals):
        raise ValueError("PARTICIPATION_SETTLEMENT_NODE_DUPLICATE")

    transfers: list[LedgerOperationEnvelope] = []
    created_at = settlement.period_end
    for offset, accrual in enumerate(positive_accruals):
        if accrual.reward_wallet == treasury_wallet:
            raise ValueError("PARTICIPATION_REWARD_WALLET_IS_TREASURY")
        unsigned = LedgerOperationEnvelope(
            operation_type="WALLET_TRANSFER",
            operation_version="1.0.0",
            protocol_version="0.1",
            origin_type="wallet",
            initiator_id=f"testnet-participation:{settlement.program_id}",
            sender_wallet=treasury_wallet,
            sender_sequence=first_sender_sequence + offset,
            fee_payer=treasury_wallet,
            fee_class="standard",
            created_at=created_at,
            target_epoch=str(settlement.protocol_epoch),
            payload={
                "recipient_wallet": accrual.reward_wallet,
                "amount": accrual.reward_q_atoms,
                "source": settlement.funding_source,
                "program_id": settlement.program_id,
                "settlement_id": settlement.settlement_id,
                "settlement_hash": settlement.settlement_hash,
                "evidence_root": settlement.evidence_root,
                "program_policy_hash": settlement.program_policy_hash,
                "source_epoch_transition_operation_id": (
                    settlement.source_epoch_transition_operation_id
                ),
                "node_id": accrual.node_id,
                "eligible_window_count": len(accrual.eligible_window_indices),
            },
            evidence_references=[
                settlement.evidence_root,
                settlement.settlement_hash,
                settlement.program_policy_hash,
                settlement.source_epoch_transition_operation_id,
            ],
            signatures=[],
        )
        signature = signer(unsigned.signing_bytes())
        if not isinstance(signature, str) or not signature.strip():
            raise ValueError("PARTICIPATION_TREASURY_SIGNATURE_INVALID")
        transfers.append(
            unsigned.model_copy(update={"signatures": [signature]})
        )

    total_reward = sum(item.reward_q_atoms for item in positive_accruals)
    if total_reward != settlement.total_reward_q_atoms:
        raise ValueError("PARTICIPATION_SETTLEMENT_TOTAL_INVALID")
    total_fees = len(transfers) * STANDARD_NETWORK_FEE_Q_ATOMS
    total_debit = total_reward + total_fees
    if (
        available_treasury_q_atoms is not None
        and available_treasury_q_atoms < total_debit
    ):
        raise ValueError("PARTICIPATION_TREASURY_BALANCE_INSUFFICIENT")

    payload = {
        "schema_version": TESTNET_PARTICIPATION_VERSION,
        "settlement_id": settlement.settlement_id,
        "settlement_hash": settlement.settlement_hash,
        "treasury_wallet": treasury_wallet,
        "transfers": [item.model_dump(mode="json") for item in transfers],
        "total_reward_q_atoms": total_reward,
        "total_network_fee_q_atoms": total_fees,
        "total_treasury_debit_q_atoms": total_debit,
    }
    return TestnetParticipationTransferBatch(
        **payload,
        batch_hash=_canonical_hash(payload),
    )


class TestnetParticipationCalculator:
    """Calculate one daily, non-emitting settlement from finalized evidence."""

    def calculate(
        self,
        program: TestnetParticipationProgram,
        *,
        protocol_epoch: int,
        source_epoch_transition_operation_id: str,
        period_start: str,
        enrollments: Iterable[TestnetParticipantEnrollment],
        heartbeats: Iterable[TestnetHeartbeatEvidence],
    ) -> TestnetParticipationSettlement:
        if protocol_epoch < program.active_from_epoch or (
            program.active_until_epoch is not None
            and protocol_epoch > program.active_until_epoch
        ):
            raise ValueError("PARTICIPATION_PROGRAM_INACTIVE")
        if not source_epoch_transition_operation_id.strip():
            raise ValueError("PARTICIPATION_SOURCE_EPOCH_TRANSITION_REQUIRED")
        start = _timestamp(period_start, field_name="period_start")
        end = start + timedelta(seconds=program.settlement_period_seconds)
        enrollment_by_node: dict[str, TestnetParticipantEnrollment] = {}
        for enrollment in enrollments:
            if enrollment.node_id in enrollment_by_node:
                raise ValueError("PARTICIPANT_ENROLLMENT_DUPLICATE")
            enrollment_by_node[enrollment.node_id] = enrollment

        slots: dict[tuple[str, int], set[int]] = defaultdict(set)
        accepted_evidence: list[TestnetHeartbeatEvidence] = []
        unique_evidence: dict[str, TestnetHeartbeatEvidence] = {}
        for evidence in heartbeats:
            if not evidence.verify_integrity():
                raise ValueError("PARTICIPATION_HEARTBEAT_INTEGRITY_INVALID")
            existing = unique_evidence.get(evidence.evidence_id)
            if existing is not None and existing.evidence_hash != evidence.evidence_hash:
                raise ValueError("PARTICIPATION_HEARTBEAT_ID_CONFLICT")
            unique_evidence[evidence.evidence_id] = evidence
        for evidence in sorted(unique_evidence.values(), key=lambda item: item.evidence_id):
            observed = _timestamp(evidence.observed_at, field_name="observed_at")
            if not start <= observed < end:
                continue
            if (
                evidence.network_id != program.network_id
                or evidence.chain_id != program.chain_id
                or evidence.protocol_version not in program.compatible_protocol_versions
                or not evidence.finalized
                or not evidence.identity_signature_verified
                or evidence.node_id not in enrollment_by_node
            ):
                continue
            offset = int((observed - start).total_seconds())
            window_index = offset // program.participation_window_seconds
            slot_index = (
                offset % program.participation_window_seconds
            ) // program.heartbeat_interval_seconds
            slots[(evidence.node_id, window_index)].add(slot_index)
            accepted_evidence.append(evidence)

        accruals: list[TestnetParticipationAccrual] = []
        for node_id in sorted(enrollment_by_node):
            enrollment = enrollment_by_node[node_id]
            eligible_windows: list[int] = []
            registration = _timestamp(enrollment.registered_at, field_name="registered_at")
            qualified_at = registration + timedelta(
                seconds=program.minimum_enrollment_seconds
            )
            retired_at = (
                _timestamp(enrollment.retired_at, field_name="retired_at")
                if enrollment.retired_at
                else None
            )
            identity_eligible = (
                enrollment.node_identity_verified
                and enrollment.registration_finalized
                and not enrollment.banned
                and enrollment.registered_epoch <= protocol_epoch
            )
            for index in range(program.windows_per_settlement):
                window_start = start + timedelta(
                    seconds=index * program.participation_window_seconds
                )
                window_end = window_start + timedelta(
                    seconds=program.participation_window_seconds
                )
                if (
                    identity_eligible
                    and qualified_at <= window_start
                    and (retired_at is None or retired_at >= window_end)
                    and len(slots[(node_id, index)]) >= program.required_heartbeat_slots
                ):
                    eligible_windows.append(index)
            reward = (
                len(eligible_windows) * program.reward_per_eligible_window_q_atoms
            )
            accruals.append(
                TestnetParticipationAccrual(
                    node_id=node_id,
                    reward_wallet=enrollment.reward_wallet,
                    eligible_window_indices=eligible_windows,
                    rejected_window_count=(
                        program.windows_per_settlement - len(eligible_windows)
                    ),
                    reward_q_atoms=reward,
                )
            )

        evidence_root = _canonical_hash(
            [item.evidence_hash for item in accepted_evidence]
        )
        total = sum(item.reward_q_atoms for item in accruals)
        period_start_value = start.isoformat().replace("+00:00", "Z")
        period_end_value = end.isoformat().replace("+00:00", "Z")
        settlement_id = _canonical_hash(
            {
                "program_id": program.program_id,
                "protocol_epoch": protocol_epoch,
                "source_epoch_transition_operation_id": (
                    source_epoch_transition_operation_id
                ),
                "program_policy_hash": program.policy_hash,
                "period_start": period_start_value,
                "period_end": period_end_value,
                "evidence_root": evidence_root,
            }
        )
        payload = {
            "schema_version": TESTNET_PARTICIPATION_VERSION,
            "settlement_id": settlement_id,
            "program_id": program.program_id,
            "network_id": program.network_id,
            "chain_id": program.chain_id,
            "protocol_epoch": protocol_epoch,
            "source_epoch_transition_operation_id": (
                source_epoch_transition_operation_id
            ),
            "program_policy_hash": program.policy_hash,
            "period_start": period_start_value,
            "period_end": period_end_value,
            "funding_source": program.funding_source,
            "evidence_root": evidence_root,
            "accruals": [item.model_dump(mode="json") for item in accruals],
            "total_reward_q_atoms": total,
        }
        return TestnetParticipationSettlement(
            **payload,
            settlement_hash=_canonical_hash(payload),
        )


__all__ = [
    "BASIS_POINTS",
    "MAX_TESTNET_PARTICIPATION_PROGRAM_BYTES",
    "Q_ATOMS_PER_Q",
    "TESTNET_PARTICIPATION_VERSION",
    "TestnetHeartbeatEvidence",
    "TestnetParticipantEnrollment",
    "TestnetParticipationAccrual",
    "TestnetParticipationCalculator",
    "TestnetParticipationProgram",
    "TestnetParticipationSettlement",
    "TestnetParticipationTransferBatch",
    "build_testnet_participation_transfer_batch",
    "build_testnet_heartbeat_evidence",
    "load_testnet_participation_program",
]
