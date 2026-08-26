"""Hash-bound live evidence inputs for an RFC-0048 result manifest.

The Epoch Result Manifest is intentionally an immutable commitment to roots
calculated outside the manifest signer.  This module supplies the missing
bridge for an Epoch Engine: it validates a boundary quorum, binds an
evidence bundle to that quorum, and only then builds the manifest consumed by
the existing consensus path.

The controlled-localnet no-work builder is deliberately narrow.  It is a
calibration profile for an epoch with no application work and a zero
development budget.  It must not be used to represent a production epoch or
to manufacture reward evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aidn_hypervisor.consensus.epoch_result_manifest import (
    EpochResultManifest,
    build_epoch_result_manifest,
)
from aidn_hypervisor.consensus.epoch_transition_inputs import EpochTransitionInputReport
from aidn_hypervisor.reward.development_distribution import (
    DevelopmentPoolInput,
    DevelopmentRewardCalculator,
    DevelopmentRewardPolicy,
)

EPOCH_RESULT_EVIDENCE_BUNDLE_VERSION = "aidn.epoch-result-evidence.v1"
CONTROLLED_LOCALNET_NO_WORK = "CONTROLLED_LOCALNET_NO_WORK"
CONTROLLED_LOCALNET_ECO_0005 = "CONTROLLED_LOCALNET_ECO_0005"
CONTROLLED_LOCALNET_ECO_0005_PROFILE_VERSION = "aidn.controlled-localnet-eco-0005.v1"
ECO_0005_BASE_EMISSION_Q_ATOMS = 5_000_000_000


def epoch_result_evidence_hash(value: Any) -> str:
    """Return the canonical hash for one evidence payload."""

    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(
        (EPOCH_RESULT_EVIDENCE_BUNDLE_VERSION + ":").encode("utf-8") + encoded
    ).hexdigest()


def controlled_localnet_eco0005_profile_hash(
    profile: ControlledLocalnetEco0005Profile,
) -> str:
    """Hash the approved controlled-localnet emission profile."""

    return epoch_result_evidence_hash(profile.unsigned_payload())


def build_controlled_localnet_eco0005_profile(
    *,
    network_id: str,
    chain_id: str,
    effective_epoch: int,
    epoch_schedule_hash: str,
    authority_policy_hash: str,
    source_document: str,
    source_document_version: str,
    source_document_hash: str,
) -> ControlledLocalnetEco0005Profile:
    """Build the fixed ECO-0005 controlled-localnet profile."""

    payload = {
        "schema_version": CONTROLLED_LOCALNET_ECO_0005_PROFILE_VERSION,
        "profile_id": "controlled-localnet-eco-0005-v1",
        "network_id": network_id,
        "chain_id": chain_id,
        "effective_epoch": effective_epoch,
        "epoch_schedule_hash": epoch_schedule_hash,
        "authority_policy_hash": authority_policy_hash,
        "source_document": source_document,
        "source_document_version": source_document_version,
        "source_document_hash": source_document_hash,
        "base_emission_q_atoms": ECO_0005_BASE_EMISSION_Q_ATOMS,
        "development_share_bps": 6_000,
        "security_pool_share_bps": 1_500,
        "documentation_pool_share_bps": 500,
        "carryover_in_q_atoms": 0,
        "dedicated_development_grants_q_atoms": 0,
        "returned_unclaimed_rewards_q_atoms": 0,
        "returned_cancelled_rewards_q_atoms": 0,
        "maturity_reserve_in_q_atoms": 0,
        "approved_bounty_reservations_q_atoms": 0,
        "pool_id": "GENERAL_DEVELOPMENT",
    }
    return ControlledLocalnetEco0005Profile(
        **payload,
        profile_hash=controlled_localnet_eco0005_profile_hash(
            ControlledLocalnetEco0005Profile.model_construct(**payload, profile_hash="pending")
        ),
    )


class EpochResultEvidenceBundle(BaseModel):
    """All immutable inputs required to build one manifest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = EPOCH_RESULT_EVIDENCE_BUNDLE_VERSION
    source_kind: Literal[
        "FINALIZED_LEDGER_EVIDENCE",
        "CONTROLLED_LOCALNET_NO_WORK",
        "CONTROLLED_LOCALNET_ECO_0005",
    ]
    network_id: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    epoch_number: int = Field(ge=0)
    start_height: int = Field(ge=1)
    start_time: str = Field(min_length=1)
    closing_height: int = Field(ge=1)
    closing_time: str = Field(min_length=1)
    closing_block_hash: str = Field(min_length=1)
    closing_state_root: str = Field(min_length=1)
    source_app_hash: str = Field(min_length=1)
    protocol_version: str = Field(min_length=1)
    parameter_version: str = Field(min_length=1)
    task_set_version: str = Field(min_length=1)
    epoch_schedule_version: str = Field(min_length=1)
    epoch_schedule_hash: str = Field(min_length=1)
    scheduled_end_time: str = Field(min_length=1)
    frozen_evidence_root: str = Field(min_length=1)
    participant_snapshot_root: str = Field(min_length=1)
    service_snapshot_root: str = Field(min_length=1)
    task_result_root: str = Field(min_length=1)
    eligibility_root: str = Field(min_length=1)
    reputation_root: str = Field(min_length=1)
    penalty_root: str = Field(min_length=1)
    recycle_root: str = Field(min_length=1)
    reward_authorization_root: str = Field(min_length=1)
    reward_result_root: str = Field(min_length=1)
    faucet_root: str = Field(min_length=1)
    validator_set_update_root: str = Field(min_length=1)
    reward_calculation_root: str = Field(min_length=1)
    next_protocol_parameters_hash: str = Field(min_length=1)
    pool_budgets: dict[str, int] = Field(default_factory=dict)
    pool_budget_references: dict[str, str] = Field(default_factory=dict)
    next_epoch_reference: str = Field(min_length=1)
    previous_epoch_result_hash: str | None = None
    source_references: list[str] = Field(min_length=1)
    bundle_hash: str

    @model_validator(mode="after")
    def validate_bundle(self) -> EpochResultEvidenceBundle:
        if self.schema_version != EPOCH_RESULT_EVIDENCE_BUNDLE_VERSION:
            raise ValueError("EPOCH_RESULT_EVIDENCE_VERSION_INVALID")
        if self.closing_height < self.start_height:
            raise ValueError("EPOCH_RESULT_EVIDENCE_HEIGHT_RANGE_INVALID")
        if set(self.pool_budgets) != set(self.pool_budget_references):
            raise ValueError("EPOCH_RESULT_EVIDENCE_POOL_REFERENCE_MISMATCH")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in self.pool_budgets.values()
        ):
            raise ValueError("EPOCH_RESULT_EVIDENCE_POOL_BUDGET_INVALID")
        if any(not item.strip() for item in self.source_references):
            raise ValueError("EPOCH_RESULT_EVIDENCE_SOURCE_REFERENCE_INVALID")
        if self.source_kind == CONTROLLED_LOCALNET_NO_WORK and any(
            value != 0 for value in self.pool_budgets.values()
        ):
            raise ValueError("EPOCH_RESULT_EVIDENCE_NO_WORK_BUDGET_MUST_BE_ZERO")
        if self.bundle_hash != epoch_result_evidence_hash(self.unsigned_payload()):
            raise ValueError("EPOCH_RESULT_EVIDENCE_BUNDLE_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"bundle_hash"})

    def verify_integrity(self) -> bool:
        return self.bundle_hash == epoch_result_evidence_hash(self.unsigned_payload())

    def manifest_values(self) -> dict[str, Any]:
        """Return the exact field set consumed by ``EpochResultManifest``."""

        return {
            key: getattr(self, key)
            for key in (
                "epoch_number",
                "start_height",
                "closing_height",
                "start_time",
                "closing_time",
                "closing_block_hash",
                "closing_state_root",
                "source_app_hash",
                "protocol_version",
                "parameter_version",
                "task_set_version",
                "epoch_schedule_version",
                "epoch_schedule_hash",
                "scheduled_end_time",
                "frozen_evidence_root",
                "participant_snapshot_root",
                "service_snapshot_root",
                "task_result_root",
                "eligibility_root",
                "reputation_root",
                "penalty_root",
                "recycle_root",
                "reward_authorization_root",
                "reward_result_root",
                "faucet_root",
                "validator_set_update_root",
                "reward_calculation_root",
                "next_protocol_parameters_hash",
                "pool_budgets",
                "pool_budget_references",
                "next_epoch_reference",
                "previous_epoch_result_hash",
            )
        }


class ControlledLocalnetEco0005Profile(BaseModel):
    """Approved ECO-0005 source parameters for the controlled localnet.

    This profile is intentionally narrower than the general emission policy.
    It is a deployment calibration artifact, not a user-supplied amount. The
    authority-signed manifest still provides the canonical consensus approval.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = CONTROLLED_LOCALNET_ECO_0005_PROFILE_VERSION
    profile_id: str = Field(min_length=1)
    network_id: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    effective_epoch: int = Field(ge=0)
    epoch_schedule_hash: str = Field(min_length=1)
    authority_policy_hash: str = Field(min_length=1)
    source_document: str = Field(min_length=1)
    source_document_version: str = Field(min_length=1)
    source_document_hash: str = Field(min_length=1)
    base_emission_q_atoms: int = ECO_0005_BASE_EMISSION_Q_ATOMS
    development_share_bps: int = 6_000
    security_pool_share_bps: int = 1_500
    documentation_pool_share_bps: int = 500
    carryover_in_q_atoms: int = 0
    dedicated_development_grants_q_atoms: int = 0
    returned_unclaimed_rewards_q_atoms: int = 0
    returned_cancelled_rewards_q_atoms: int = 0
    maturity_reserve_in_q_atoms: int = 0
    approved_bounty_reservations_q_atoms: int = 0
    pool_id: str = "GENERAL_DEVELOPMENT"
    profile_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_profile(self) -> ControlledLocalnetEco0005Profile:
        if self.schema_version != CONTROLLED_LOCALNET_ECO_0005_PROFILE_VERSION:
            raise ValueError("CONTROLLED_LOCALNET_ECO_0005_PROFILE_VERSION_INVALID")
        if self.base_emission_q_atoms != ECO_0005_BASE_EMISSION_Q_ATOMS:
            raise ValueError("CONTROLLED_LOCALNET_ECO_0005_BASE_EMISSION_INVALID")
        if self.development_share_bps != 6_000:
            raise ValueError("CONTROLLED_LOCALNET_ECO_0005_DEVELOPMENT_SHARE_INVALID")
        if self.security_pool_share_bps != 1_500 or self.documentation_pool_share_bps != 500:
            raise ValueError("CONTROLLED_LOCALNET_ECO_0005_RESERVE_SHARE_INVALID")
        if any(
            value != 0
            for value in (
                self.carryover_in_q_atoms,
                self.dedicated_development_grants_q_atoms,
                self.returned_unclaimed_rewards_q_atoms,
                self.returned_cancelled_rewards_q_atoms,
                self.maturity_reserve_in_q_atoms,
                self.approved_bounty_reservations_q_atoms,
            )
        ):
            raise ValueError("CONTROLLED_LOCALNET_ECO_0005_UNAPPROVED_POOL_INPUT")
        if self.pool_id != "GENERAL_DEVELOPMENT":
            raise ValueError("CONTROLLED_LOCALNET_ECO_0005_POOL_INVALID")
        if self.profile_hash != controlled_localnet_eco0005_profile_hash(self):
            raise ValueError("CONTROLLED_LOCALNET_ECO_0005_PROFILE_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"profile_hash"})

    def verify_integrity(self) -> bool:
        return self.profile_hash == controlled_localnet_eco0005_profile_hash(self)


def build_epoch_result_evidence_bundle(**values: Any) -> EpochResultEvidenceBundle:
    """Build one immutable evidence bundle and calculate its hash."""

    payload = {
        "schema_version": EPOCH_RESULT_EVIDENCE_BUNDLE_VERSION,
        **values,
    }
    payload.pop("bundle_hash", None)
    return EpochResultEvidenceBundle(
        **payload,
        bundle_hash=epoch_result_evidence_hash(payload),
    )


def _hash_empty_evidence(label: str, *, epoch: int, closing_height: int) -> str:
    return epoch_result_evidence_hash(
        {
            "kind": label,
            "epoch": epoch,
            "closing_height": closing_height,
            "items": [],
        }
    )


def _hash_snapshot(label: str, *, epoch: int, closing_height: int, items: Sequence[Any]) -> str:
    return epoch_result_evidence_hash(
        {
            "kind": label,
            "epoch": epoch,
            "closing_height": closing_height,
            "items": list(items),
        }
    )


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("EPOCH_RESULT_EVIDENCE_TIMESTAMP_MUST_BE_UTC")
    return parsed.astimezone(UTC)


def build_controlled_localnet_no_work_evidence(
    *,
    report: EpochTransitionInputReport,
    network_id: str,
    chain_id: str,
    start_height: int,
    start_time: str,
    epoch_schedule: Mapping[str, Any],
    participant_snapshot: Sequence[Any] = (),
    service_snapshot: Sequence[Any] = (),
    source_references: Sequence[str] = ("controlled-localnet:no-work",),
) -> EpochResultEvidenceBundle:
    """Build a zero-budget calibration bundle from a finalized boundary.

    This function is not a generic fallback.  It only accepts a BLOCKED
    transition report whose sole missing inputs are the result artifacts.  A
    caller cannot use it to turn a broken chain or a partially observed
    quorum into a manifest.
    """

    if report.epoch_boundary_reached is not True:
        raise ValueError("EPOCH_RESULT_EVIDENCE_EPOCH_BOUNDARY_REQUIRED")
    if report.closing_epoch is None or report.opening_epoch != report.closing_epoch + 1:
        raise ValueError("EPOCH_RESULT_EVIDENCE_EPOCH_BOUNDARY_INVALID")
    if report.status != "BLOCKED":
        raise ValueError("EPOCH_RESULT_EVIDENCE_NO_WORK_REQUIRES_BLOCKED_REPORT")
    allowed_missing = {
        "epoch_task_result_root",
        "eligibility_snapshot_root",
        "reward_calculation_root",
        "next_protocol_parameters_hash",
        "epoch_result_manifest",
        "pool_budgets",
    }
    if set(report.missing_inputs) - allowed_missing:
        raise ValueError("EPOCH_RESULT_EVIDENCE_REPORT_HAS_UNSUPPORTED_MISSING_INPUTS")
    if any(
        value in (None, "")
        for value in (
            report.closing_height,
            report.closing_block_hash,
            report.closing_state_root,
            report.source_app_hash,
            report.canonical_block_time,
            report.scheduled_end_time,
            report.epoch_schedule_version,
            report.epoch_schedule_hash,
        )
    ):
        raise ValueError("EPOCH_RESULT_EVIDENCE_BOUNDARY_FIELDS_MISSING")
    if epoch_schedule.get("schema_version") != report.epoch_schedule_version:
        raise ValueError("EPOCH_RESULT_EVIDENCE_SCHEDULE_VERSION_MISMATCH")
    if epoch_schedule.get("schedule_hash") != report.epoch_schedule_hash:
        raise ValueError("EPOCH_RESULT_EVIDENCE_SCHEDULE_HASH_MISMATCH")
    if epoch_schedule.get("parameter_version") in (None, ""):
        raise ValueError("EPOCH_RESULT_EVIDENCE_PARAMETER_VERSION_MISSING")
    if epoch_schedule.get("protocol_version") in (None, ""):
        raise ValueError("EPOCH_RESULT_EVIDENCE_PROTOCOL_VERSION_MISSING")
    if epoch_schedule.get("task_set_version") in (None, ""):
        raise ValueError("EPOCH_RESULT_EVIDENCE_TASK_SET_VERSION_MISSING")
    if not network_id.strip() or not chain_id.strip():
        raise ValueError("EPOCH_RESULT_EVIDENCE_NETWORK_ID_REQUIRED")
    if start_height < 1 or start_height > report.closing_height:
        raise ValueError("EPOCH_RESULT_EVIDENCE_START_HEIGHT_INVALID")

    closing_height = report.closing_height
    epoch = report.closing_epoch
    task_result_root = _hash_empty_evidence(
        "task-results", epoch=epoch, closing_height=closing_height
    )
    participant_root = _hash_snapshot(
        "participants",
        epoch=epoch,
        closing_height=closing_height,
        items=participant_snapshot,
    )
    service_root = _hash_snapshot(
        "services",
        epoch=epoch,
        closing_height=closing_height,
        items=service_snapshot,
    )
    eligibility_root = _hash_snapshot(
        "eligibility",
        epoch=epoch,
        closing_height=closing_height,
        items=participant_snapshot,
    )
    empty_roots = {
        label: _hash_empty_evidence(label, epoch=epoch, closing_height=closing_height)
        for label in (
            "reputation",
            "penalties",
            "recycle",
            "reward-authorization",
            "faucet",
            "validator-set-updates",
        )
    }
    policy = DevelopmentRewardPolicy()
    calculation = DevelopmentRewardCalculator(policy).calculate(
        DevelopmentPoolInput(
            epoch=epoch,
            distributable_epoch_emission_q_atoms=0,
        ),
        (),
    )
    pool_reference = epoch_result_evidence_hash(
        {
            "pool_id": "GENERAL_DEVELOPMENT",
            "epoch": epoch,
            "budget_q_atoms": 0,
            "calculation_root": calculation.calculation_root,
        }
    )
    next_parameters_hash = epoch_result_evidence_hash(
        {
            "parameter_version": epoch_schedule["parameter_version"],
            "protocol_version": epoch_schedule["protocol_version"],
            "task_set_version": epoch_schedule["task_set_version"],
            "epoch_schedule_hash": report.epoch_schedule_hash,
            "development_policy": policy.model_dump(mode="json"),
            "pool_budgets": {"GENERAL_DEVELOPMENT": 0},
        }
    )
    reward_result_root = epoch_result_evidence_hash(
        {
            "calculation_root": calculation.calculation_root,
            "accepted_gross_reward_q_atoms": calculation.accepted_gross_reward_q_atoms,
        }
    )
    frozen_evidence_root = epoch_result_evidence_hash(
        {
            "source_kind": CONTROLLED_LOCALNET_NO_WORK,
            "network_id": network_id,
            "chain_id": chain_id,
            "epoch": epoch,
            "closing_height": closing_height,
            "task_result_root": task_result_root,
            "participant_snapshot_root": participant_root,
            "service_snapshot_root": service_root,
            "eligibility_root": eligibility_root,
            "reward_calculation_root": calculation.calculation_root,
        }
    )
    bundle = build_epoch_result_evidence_bundle(
        source_kind=CONTROLLED_LOCALNET_NO_WORK,
        network_id=network_id,
        chain_id=chain_id,
        epoch_number=epoch,
        start_height=start_height,
        start_time=start_time,
        closing_height=closing_height,
        closing_time=report.canonical_block_time,
        closing_block_hash=report.closing_block_hash,
        closing_state_root=report.closing_state_root,
        source_app_hash=report.source_app_hash,
        protocol_version=str(epoch_schedule["protocol_version"]),
        parameter_version=str(epoch_schedule["parameter_version"]),
        task_set_version=str(epoch_schedule["task_set_version"]),
        epoch_schedule_version=str(epoch_schedule["schema_version"]),
        epoch_schedule_hash=report.epoch_schedule_hash,
        scheduled_end_time=report.scheduled_end_time,
        frozen_evidence_root=frozen_evidence_root,
        participant_snapshot_root=participant_root,
        service_snapshot_root=service_root,
        task_result_root=task_result_root,
        eligibility_root=eligibility_root,
        reputation_root=empty_roots["reputation"],
        penalty_root=empty_roots["penalties"],
        recycle_root=empty_roots["recycle"],
        reward_authorization_root=empty_roots["reward-authorization"],
        reward_result_root=reward_result_root,
        faucet_root=empty_roots["faucet"],
        validator_set_update_root=empty_roots["validator-set-updates"],
        reward_calculation_root=calculation.calculation_root,
        next_protocol_parameters_hash=next_parameters_hash,
        pool_budgets={"GENERAL_DEVELOPMENT": 0},
        pool_budget_references={"GENERAL_DEVELOPMENT": pool_reference},
        next_epoch_reference=f"epoch:{epoch + 1}",
        previous_epoch_result_hash=None,
        source_references=list(source_references),
    )
    end = _parse_timestamp(bundle.scheduled_end_time)
    start = _parse_timestamp(bundle.start_time)
    duration = epoch_schedule.get("epoch_duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
        raise ValueError("EPOCH_RESULT_EVIDENCE_SCHEDULE_DURATION_INVALID")
    if end - start != timedelta(seconds=duration):
        raise ValueError("EPOCH_RESULT_EVIDENCE_START_TIME_DOES_NOT_MATCH_SCHEDULE")
    return bundle


def build_controlled_localnet_eco0005_evidence(
    *,
    report: EpochTransitionInputReport,
    profile: ControlledLocalnetEco0005Profile,
    start_height: int,
    start_time: str,
    epoch_schedule: Mapping[str, Any],
    participant_snapshot: Sequence[Any] = (),
    service_snapshot: Sequence[Any] = (),
) -> EpochResultEvidenceBundle:
    """Build non-zero controlled-localnet evidence from the fixed ECO-0005 profile.

    The function derives the budget with the production ECO-0007 calculator;
    callers cannot provide a budget or reserve amount. Consensus authorities
    must still sign the resulting manifest before it can affect the chain.
    """

    if not profile.verify_integrity():
        raise ValueError("CONTROLLED_LOCALNET_ECO_0005_PROFILE_HASH_INVALID")
    if report.epoch_boundary_reached is not True:
        raise ValueError("EPOCH_RESULT_EVIDENCE_EPOCH_BOUNDARY_REQUIRED")
    if report.closing_epoch is None or report.opening_epoch != report.closing_epoch + 1:
        raise ValueError("EPOCH_RESULT_EVIDENCE_EPOCH_BOUNDARY_INVALID")
    if report.status != "BLOCKED":
        raise ValueError("EPOCH_RESULT_EVIDENCE_ECO_0005_REQUIRES_BLOCKED_REPORT")
    allowed_missing = {
        "epoch_task_result_root",
        "eligibility_snapshot_root",
        "reward_calculation_root",
        "next_protocol_parameters_hash",
        "epoch_result_manifest",
        "pool_budgets",
    }
    if set(report.missing_inputs) - allowed_missing:
        raise ValueError("EPOCH_RESULT_EVIDENCE_REPORT_HAS_UNSUPPORTED_MISSING_INPUTS")
    if any(
        value in (None, "")
        for value in (
            report.closing_height,
            report.closing_block_hash,
            report.closing_state_root,
            report.source_app_hash,
            report.canonical_block_time,
            report.scheduled_end_time,
            report.epoch_schedule_version,
            report.epoch_schedule_hash,
        )
    ):
        raise ValueError("EPOCH_RESULT_EVIDENCE_BOUNDARY_FIELDS_MISSING")
    if epoch_schedule.get("schema_version") != report.epoch_schedule_version:
        raise ValueError("EPOCH_RESULT_EVIDENCE_SCHEDULE_VERSION_MISMATCH")
    if epoch_schedule.get("schedule_hash") != report.epoch_schedule_hash:
        raise ValueError("EPOCH_RESULT_EVIDENCE_SCHEDULE_HASH_MISMATCH")
    if profile.epoch_schedule_hash != report.epoch_schedule_hash:
        raise ValueError("CONTROLLED_LOCALNET_ECO_0005_PROFILE_SCHEDULE_MISMATCH")
    if profile.effective_epoch > report.closing_epoch:
        raise ValueError("CONTROLLED_LOCALNET_ECO_0005_PROFILE_NOT_EFFECTIVE")
    if not profile.network_id.strip() or not profile.chain_id.strip():
        raise ValueError("CONTROLLED_LOCALNET_ECO_0005_NETWORK_ID_REQUIRED")
    if start_height < 1 or start_height > report.closing_height:
        raise ValueError("EPOCH_RESULT_EVIDENCE_START_HEIGHT_INVALID")
    for field in ("parameter_version", "protocol_version", "task_set_version"):
        if epoch_schedule.get(field) in (None, ""):
            raise ValueError(f"EPOCH_RESULT_EVIDENCE_{field.upper()}_MISSING")

    closing_height = report.closing_height
    epoch = report.closing_epoch
    task_result_root = _hash_empty_evidence(
        "task-results", epoch=epoch, closing_height=closing_height
    )
    participant_root = _hash_snapshot(
        "participants", epoch=epoch, closing_height=closing_height, items=participant_snapshot
    )
    service_root = _hash_snapshot(
        "services", epoch=epoch, closing_height=closing_height, items=service_snapshot
    )
    eligibility_root = _hash_snapshot(
        "eligibility", epoch=epoch, closing_height=closing_height, items=participant_snapshot
    )
    empty_roots = {
        label: _hash_empty_evidence(label, epoch=epoch, closing_height=closing_height)
        for label in (
            "reputation",
            "penalties",
            "recycle",
            "reward-authorization",
            "faucet",
            "validator-set-updates",
        )
    }
    policy = DevelopmentRewardPolicy(
        development_share_bps=profile.development_share_bps,
        security_pool_share_bps=profile.security_pool_share_bps,
        documentation_pool_share_bps=profile.documentation_pool_share_bps,
    )
    calculation = DevelopmentRewardCalculator(policy).calculate(
        DevelopmentPoolInput(
            epoch=epoch,
            distributable_epoch_emission_q_atoms=profile.base_emission_q_atoms,
            carryover_in_q_atoms=profile.carryover_in_q_atoms,
            dedicated_development_grants_q_atoms=profile.dedicated_development_grants_q_atoms,
            returned_unclaimed_rewards_q_atoms=profile.returned_unclaimed_rewards_q_atoms,
            returned_cancelled_rewards_q_atoms=profile.returned_cancelled_rewards_q_atoms,
            maturity_reserve_in_q_atoms=profile.maturity_reserve_in_q_atoms,
            approved_bounty_reservations_q_atoms=profile.approved_bounty_reservations_q_atoms,
        ),
        (),
    )
    pool_budget = calculation.pool.base_allocation_q_atoms
    pool_reference = epoch_result_evidence_hash(
        {
            "pool_id": profile.pool_id,
            "epoch": epoch,
            "budget_q_atoms": pool_budget,
            "calculation_root": calculation.calculation_root,
        }
    )
    next_parameters_hash = epoch_result_evidence_hash(
        {
            "parameter_version": epoch_schedule["parameter_version"],
            "protocol_version": epoch_schedule["protocol_version"],
            "task_set_version": epoch_schedule["task_set_version"],
            "epoch_schedule_hash": report.epoch_schedule_hash,
            "development_policy": policy.model_dump(mode="json"),
            "eco_0005_profile_hash": profile.profile_hash,
            "pool_budgets": {profile.pool_id: pool_budget},
        }
    )
    reward_result_root = epoch_result_evidence_hash(
        {
            "calculation_root": calculation.calculation_root,
            "accepted_gross_reward_q_atoms": calculation.accepted_gross_reward_q_atoms,
        }
    )
    frozen_evidence_root = epoch_result_evidence_hash(
        {
            "source_kind": CONTROLLED_LOCALNET_ECO_0005,
            "profile_hash": profile.profile_hash,
            "network_id": profile.network_id,
            "chain_id": profile.chain_id,
            "epoch": epoch,
            "closing_height": closing_height,
            "task_result_root": task_result_root,
            "participant_snapshot_root": participant_root,
            "service_snapshot_root": service_root,
            "eligibility_root": eligibility_root,
            "reward_calculation_root": calculation.calculation_root,
        }
    )
    bundle = build_epoch_result_evidence_bundle(
        source_kind=CONTROLLED_LOCALNET_ECO_0005,
        network_id=profile.network_id,
        chain_id=profile.chain_id,
        epoch_number=epoch,
        start_height=start_height,
        start_time=start_time,
        closing_height=closing_height,
        closing_time=report.canonical_block_time,
        closing_block_hash=report.closing_block_hash,
        closing_state_root=report.closing_state_root,
        source_app_hash=report.source_app_hash,
        protocol_version=str(epoch_schedule["protocol_version"]),
        parameter_version=str(epoch_schedule["parameter_version"]),
        task_set_version=str(epoch_schedule["task_set_version"]),
        epoch_schedule_version=str(epoch_schedule["schema_version"]),
        epoch_schedule_hash=report.epoch_schedule_hash,
        scheduled_end_time=report.scheduled_end_time,
        frozen_evidence_root=frozen_evidence_root,
        participant_snapshot_root=participant_root,
        service_snapshot_root=service_root,
        task_result_root=task_result_root,
        eligibility_root=eligibility_root,
        reputation_root=empty_roots["reputation"],
        penalty_root=empty_roots["penalties"],
        recycle_root=empty_roots["recycle"],
        reward_authorization_root=empty_roots["reward-authorization"],
        reward_result_root=reward_result_root,
        faucet_root=empty_roots["faucet"],
        validator_set_update_root=empty_roots["validator-set-updates"],
        reward_calculation_root=calculation.calculation_root,
        next_protocol_parameters_hash=next_parameters_hash,
        pool_budgets={profile.pool_id: pool_budget},
        pool_budget_references={profile.pool_id: pool_reference},
        next_epoch_reference=f"epoch:{epoch + 1}",
        previous_epoch_result_hash=None,
        source_references=[
            f"controlled-localnet:eco-0005:{profile.profile_hash}",
            f"eco-0005:{profile.source_document}:{profile.source_document_version}:{profile.source_document_hash}",
            f"epoch-schedule:{report.epoch_schedule_hash}",
            f"authority-policy:{profile.authority_policy_hash}",
        ],
    )
    end = _parse_timestamp(bundle.scheduled_end_time)
    start = _parse_timestamp(bundle.start_time)
    duration = epoch_schedule.get("epoch_duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0:
        raise ValueError("EPOCH_RESULT_EVIDENCE_SCHEDULE_DURATION_INVALID")
    if end - start != timedelta(seconds=duration):
        raise ValueError("EPOCH_RESULT_EVIDENCE_START_TIME_DOES_NOT_MATCH_SCHEDULE")
    return bundle


def build_manifest_from_evidence(
    bundle: EpochResultEvidenceBundle,
    report: EpochTransitionInputReport,
) -> EpochResultManifest:
    """Bind a bundle to one observed transition boundary and build a manifest."""

    if not bundle.verify_integrity():
        raise ValueError("EPOCH_RESULT_EVIDENCE_BUNDLE_HASH_INVALID")
    if report.epoch_boundary_reached is not True:
        raise ValueError("EPOCH_RESULT_EVIDENCE_BOUNDARY_NOT_REACHED")
    expected = {
        "epoch_number": report.closing_epoch,
        "closing_height": report.closing_height,
        "closing_block_hash": report.closing_block_hash,
        "closing_state_root": report.closing_state_root,
        "source_app_hash": report.source_app_hash,
        "epoch_schedule_version": report.epoch_schedule_version,
        "epoch_schedule_hash": report.epoch_schedule_hash,
        "scheduled_end_time": report.scheduled_end_time,
        "closing_time": report.canonical_block_time,
    }
    for field, value in expected.items():
        if getattr(bundle, field if field != "epoch_number" else "epoch_number") != value:
            raise ValueError(f"EPOCH_RESULT_EVIDENCE_REPORT_MISMATCH:{field}")
    if bundle.epoch_number + 1 != report.opening_epoch:
        raise ValueError("EPOCH_RESULT_EVIDENCE_OPENING_EPOCH_MISMATCH")
    return build_epoch_result_manifest(**bundle.manifest_values())


__all__ = [
    "CONTROLLED_LOCALNET_ECO_0005",
    "CONTROLLED_LOCALNET_ECO_0005_PROFILE_VERSION",
    "CONTROLLED_LOCALNET_NO_WORK",
    "ECO_0005_BASE_EMISSION_Q_ATOMS",
    "EPOCH_RESULT_EVIDENCE_BUNDLE_VERSION",
    "ControlledLocalnetEco0005Profile",
    "EpochResultEvidenceBundle",
    "build_controlled_localnet_eco0005_evidence",
    "build_controlled_localnet_eco0005_profile",
    "build_controlled_localnet_no_work_evidence",
    "build_epoch_result_evidence_bundle",
    "build_manifest_from_evidence",
    "controlled_localnet_eco0005_profile_hash",
    "epoch_result_evidence_hash",
]
