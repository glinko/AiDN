"""Consensus-finalized Registry Duty evidence and reward input boundary.

This module deliberately stops before reward minting.  A Registry can produce
evidence and a deterministic eligibility decision, but only the epoch/ledger
pipeline may calculate a pool distribution or create ``REWARD_MINT``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.consensus.finality import (
    ConsensusFinalityEvidence,
    ConsensusFinalitySource,
)

FIXED_POINT_SCALE = 1_000_000
DEFAULT_MINIMUM_ACTIVATION_AGE_EPOCHS = 10
DEFAULT_MINIMUM_HEALTH = 700_000
DEFAULT_MINIMUM_PROOF_SUCCESS = 900_000
DEFAULT_MINIMUM_COMPLETENESS = 950_000
DEFAULT_MAX_ADDITIONAL_WORK_UNITS = 500_000
DEFAULT_BASE_WORK_UNITS = FIXED_POINT_SCALE
DEFAULT_MAX_LATENCY_FACTOR = FIXED_POINT_SCALE


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _scaled_ratio(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return min(
        FIXED_POINT_SCALE,
        max(0, (int(numerator) * FIXED_POINT_SCALE) // int(denominator)),
    )


def _scaled_product(values: list[int]) -> int:
    result = FIXED_POINT_SCALE
    for value in values:
        result = (result * int(value)) // FIXED_POINT_SCALE
    return result


class RegistryDutyEvidence(BaseModel, frozen=True):
    """One immutable, epoch-scoped Registry Duty evidence object.

    Counts and factors are carried as integers.  This prevents a local
    Registry from changing reward eligibility through platform-dependent
    floating-point behavior.
    """

    evidence_version: str = "registry-duty-evidence.v1"
    evidence_id: str = ""
    evidence_hash: str = ""
    registry_service_id: str = Field(min_length=1)
    service_type: str = "registry"
    epoch: int = Field(ge=0)
    finalized_operation_id: str = Field(min_length=1)
    finality_evidence: dict[str, Any]
    profile_version: str = Field(min_length=1)
    profile_hash: str = Field(min_length=1)
    inventory_manifest_id: str = Field(min_length=1)
    inventory_root: str = Field(min_length=1)
    inventory_generation: int = Field(ge=1)
    completeness_manifest_hash: str = Field(min_length=1)
    initial_sync_complete: bool
    profile_compliant: bool
    reachable: bool
    mandatory_challenge_count: int = Field(ge=0)
    successful_mandatory_challenge_count: int = Field(ge=0)
    required_object_count: int = Field(ge=0)
    verified_required_object_count: int = Field(ge=0)
    availability_observation_count: int = Field(ge=0)
    availability_success_count: int = Field(ge=0)
    latency_factor_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    reliability_factor_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    health_factor_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    maturity_factor_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    registry_work_units_millionths: int = Field(
        ge=0,
        le=DEFAULT_BASE_WORK_UNITS + DEFAULT_MAX_ADDITIONAL_WORK_UNITS,
    )
    additional_work_units_millionths: int = Field(
        ge=0,
        le=DEFAULT_MAX_ADDITIONAL_WORK_UNITS,
    )
    activation_epoch: int = Field(ge=0)
    activation_age_epochs: int = Field(ge=0)
    required_activation_age_epochs: int = Field(
        ge=0,
        default=DEFAULT_MINIMUM_ACTIVATION_AGE_EPOCHS,
    )
    collateral_q_atoms: int = Field(ge=0)
    required_collateral_q_atoms: int = Field(ge=0)
    operator_wallet: str = Field(min_length=1)
    reward_beneficiary: str = Field(min_length=1)
    known_control_group_id: str | None = None
    protocol_version: str = Field(min_length=1)
    required_protocol_version: str = Field(min_length=1)
    suspended: bool = False
    unresolved_conflict_count: int = Field(ge=0)
    evidence_references: list[str] = Field(default_factory=list)
    generated_at: str = Field(min_length=1)
    signature: str = ""

    @model_validator(mode="after")
    def validate_counts_and_binding(self) -> RegistryDutyEvidence:
        finality_operation_id = self.finality_evidence.get("operation_id")
        if finality_operation_id != self.finalized_operation_id:
            raise ValueError("finality evidence is bound to another operation")
        if self.successful_mandatory_challenge_count > self.mandatory_challenge_count:
            raise ValueError("successful mandatory challenges exceed total challenges")
        if self.verified_required_object_count > self.required_object_count:
            raise ValueError("verified required objects exceed required objects")
        if self.availability_success_count > self.availability_observation_count:
            raise ValueError("availability successes exceed observations")
        if self.registry_work_units_millionths != (
            DEFAULT_BASE_WORK_UNITS + self.additional_work_units_millionths
        ):
            raise ValueError("Registry work units do not match base plus additional work")
        if self.service_type != "registry":
            raise ValueError("Registry Duty evidence has an invalid service type")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        """Return the payload covered by the evidence identity."""
        return self.model_dump(
            mode="json",
            exclude={"evidence_id", "evidence_hash", "signature"},
        )

    def signing_payload(self) -> dict[str, Any]:
        """Return the identity-bound payload covered by the operator signature."""
        return self.model_dump(mode="json", exclude={"signature"})

    def verify_integrity(self) -> bool:
        expected_id = _digest(self.unsigned_payload())
        expected_hash = _digest({"evidence_id": expected_id, "payload": self.unsigned_payload()})
        return self.evidence_id == expected_id and self.evidence_hash == expected_hash

    @classmethod
    def create(
        cls,
        *,
        finality_evidence: ConsensusFinalityEvidence,
        signer: Callable[[bytes], str] | None = None,
        **fields: Any,
    ) -> RegistryDutyEvidence:
        """Build deterministic evidence and optionally sign it."""
        payload = dict(fields)
        payload["finality_evidence"] = finality_evidence.model_dump()
        payload.setdefault("finalized_operation_id", finality_evidence.operation_id)
        draft = cls.model_validate(payload)
        evidence_id = _digest(draft.unsigned_payload())
        evidence_hash = _digest(
            {"evidence_id": evidence_id, "payload": draft.unsigned_payload()}
        )
        evidence = draft.model_copy(
            update={"evidence_id": evidence_id, "evidence_hash": evidence_hash}
        )
        if signer is not None:
            evidence = evidence.model_copy(
                update={"signature": signer(registry_duty_signing_bytes(evidence))}
            )
        return evidence


def registry_duty_signing_bytes(evidence: RegistryDutyEvidence) -> bytes:
    return _canonical_bytes(evidence.signing_payload())


class RegistryEligibilityGate(BaseModel, frozen=True):
    gate: str = Field(min_length=1)
    passed: bool
    detail: str = ""


class RegistryDutyVerificationResult(BaseModel, frozen=True):
    """Deterministic eligibility result for one finalized evidence object."""

    result_version: str = "registry-duty-verification.v1"
    evidence_id: str = Field(min_length=1)
    registry_service_id: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    valid: bool
    eligible: bool
    gates: list[RegistryEligibilityGate] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    proof_success_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    completeness_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    availability_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    raw_weight_millionths: int = Field(ge=0)
    evidence_root: str = Field(min_length=1)
    finality_operation_id: str = Field(min_length=1)
    decision_hash: str = ""

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"decision_hash"})

    def with_hash(self) -> RegistryDutyVerificationResult:
        return self.model_copy(update={"decision_hash": _digest(self.unsigned_payload())})


class RegistryRewardInput(BaseModel, frozen=True):
    """Fixed-point input passed from Registry verification to epoch rewards."""

    input_version: str = "registry-reward-input.v1"
    service_id: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    reward_pool: str = "registry"
    reward_beneficiary: str = Field(min_length=1)
    known_control_group_id: str | None = None
    work_units_millionths: int = Field(ge=0)
    maturity_factor_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    health_factor_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    proof_success_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    completeness_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    availability_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    latency_factor_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    reliability_factor_millionths: int = Field(ge=0, le=FIXED_POINT_SCALE)
    raw_weight_millionths: int = Field(ge=0)
    evidence_id: str = Field(min_length=1)
    evidence_hash: str = Field(min_length=1)
    eligibility_decision_hash: str = Field(min_length=1)
    eligibility_snapshot_id: str = Field(min_length=1)
    finalized_operation_id: str = Field(min_length=1)


class RegistryDutyVerifier:
    """Verify finality-bound Registry evidence and derive reward inputs."""

    def __init__(
        self,
        *,
        finality_source: ConsensusFinalitySource | None,
        expected_registry_service_id: str | None = None,
        required_profile_version: str | None = None,
        required_protocol_version: str = "1.0.0",
        minimum_activation_age_epochs: int = DEFAULT_MINIMUM_ACTIVATION_AGE_EPOCHS,
        minimum_collateral_q_atoms: int = 0,
        minimum_health_millionths: int = DEFAULT_MINIMUM_HEALTH,
        minimum_proof_success_millionths: int = DEFAULT_MINIMUM_PROOF_SUCCESS,
        minimum_completeness_millionths: int = DEFAULT_MINIMUM_COMPLETENESS,
        require_signature: bool = True,
        signature_verifier: Callable[[RegistryDutyEvidence], bool] | None = None,
    ) -> None:
        if minimum_activation_age_epochs < 0:
            raise ValueError("minimum activation age must be non-negative")
        if minimum_collateral_q_atoms < 0:
            raise ValueError("minimum collateral must be non-negative")
        for name, value in {
            "minimum health": minimum_health_millionths,
            "minimum proof success": minimum_proof_success_millionths,
            "minimum completeness": minimum_completeness_millionths,
        }.items():
            if not 0 <= value <= FIXED_POINT_SCALE:
                raise ValueError(f"{name} must be within fixed-point bounds")
        self._finality_source = finality_source
        self._expected_registry_service_id = expected_registry_service_id
        self._required_profile_version = required_profile_version
        self._required_protocol_version = required_protocol_version
        self._minimum_activation_age_epochs = minimum_activation_age_epochs
        self._minimum_collateral_q_atoms = minimum_collateral_q_atoms
        self._minimum_health_millionths = minimum_health_millionths
        self._minimum_proof_success_millionths = minimum_proof_success_millionths
        self._minimum_completeness_millionths = minimum_completeness_millionths
        self._require_signature = require_signature
        self._signature_verifier = signature_verifier

    def evaluate(
        self,
        evidence: RegistryDutyEvidence,
        *,
        expected_epoch: int | None = None,
        expected_inventory_manifest: Any | None = None,
    ) -> RegistryDutyVerificationResult:
        """Evaluate evidence; invalid finality is distinct from ineligibility."""
        gates: list[RegistryEligibilityGate] = []
        reasons: list[str] = []

        def gate(name: str, passed: bool, detail: str, reason: str | None = None) -> None:
            gates.append(RegistryEligibilityGate(gate=name, passed=passed, detail=detail))
            if not passed and reason is not None:
                reasons.append(reason)

        valid = evidence.verify_integrity()
        if not valid:
            reasons.append("evidence_integrity_invalid")

        finality = self._finality_for(evidence.finalized_operation_id)
        finality_matches = finality is not None and (
            finality.model_dump() == evidence.finality_evidence
        )
        gate(
            "consensus_finality",
            finality_matches,
            "verified" if finality_matches else "missing_or_mismatched",
            "consensus_finality_missing",
        )
        if not finality_matches:
            valid = False

        if expected_epoch is not None:
            epoch_matches = evidence.epoch == int(expected_epoch)
            gate(
                "epoch_binding",
                epoch_matches,
                f"evidence={evidence.epoch}, expected={expected_epoch}",
                "epoch_mismatch",
            )
            if not epoch_matches:
                valid = False
        else:
            gate("epoch_binding", True, f"epoch={evidence.epoch}")

        service_matches = (
            self._expected_registry_service_id is None
            or evidence.registry_service_id == self._expected_registry_service_id
        )
        gate(
            "service_identity",
            service_matches,
            evidence.registry_service_id,
            "service_identity_mismatch",
        )
        if not service_matches:
            valid = False

        profile_matches = (
            self._required_profile_version is None
            or evidence.profile_version == self._required_profile_version
        ) and evidence.profile_compliant
        gate("required_profile", profile_matches, evidence.profile_version, "profile_not_compliant")

        inventory_valid = bool(evidence.inventory_manifest_id and evidence.inventory_root)
        if expected_inventory_manifest is not None:
            try:
                inventory_valid = inventory_valid and bool(expected_inventory_manifest.verify())
                inventory_valid = inventory_valid and (
                    expected_inventory_manifest.manifest_id == evidence.inventory_manifest_id
                    and expected_inventory_manifest.inventory_root.root_hash == evidence.inventory_root
                )
            except (AttributeError, TypeError, ValueError):
                inventory_valid = False
        gate("inventory_commitment", inventory_valid, evidence.inventory_root, "inventory_commitment_invalid")

        gate(
            "initial_sync",
            evidence.initial_sync_complete,
            "complete" if evidence.initial_sync_complete else "incomplete",
            "initial_sync_incomplete",
        )
        gate(
            "reachable",
            evidence.reachable,
            "reachable" if evidence.reachable else "unreachable",
            "registry_unreachable",
        )
        gate(
            "activation_age",
            evidence.activation_age_epochs >= max(
                evidence.required_activation_age_epochs,
                self._minimum_activation_age_epochs,
            ),
            f"age={evidence.activation_age_epochs}",
            "activation_age_not_met",
        )
        gate(
            "collateral",
            evidence.collateral_q_atoms >= max(
                evidence.required_collateral_q_atoms,
                self._minimum_collateral_q_atoms,
            ),
            f"collateral={evidence.collateral_q_atoms}",
            "collateral_requirement_not_met",
        )
        protocol_matches = (
            evidence.protocol_version
            == evidence.required_protocol_version
            == self._required_protocol_version
        )
        gate(
            "protocol_version",
            protocol_matches,
            evidence.protocol_version,
            "protocol_version_mismatch",
        )
        gate(
            "not_suspended",
            not evidence.suspended,
            "clear" if not evidence.suspended else "suspended",
            "service_suspended",
        )
        gate(
            "no_unresolved_conflicts",
            evidence.unresolved_conflict_count == 0,
            str(evidence.unresolved_conflict_count),
            "unresolved_registry_conflicts",
        )
        gate(
            "health",
            evidence.health_factor_millionths >= self._minimum_health_millionths,
            str(evidence.health_factor_millionths),
            "health_below_threshold",
        )

        proof_success = _scaled_ratio(
            evidence.successful_mandatory_challenge_count,
            evidence.mandatory_challenge_count,
        )
        completeness = _scaled_ratio(
            evidence.verified_required_object_count,
            evidence.required_object_count,
        )
        availability = _scaled_ratio(
            evidence.availability_success_count,
            evidence.availability_observation_count,
        )
        gate(
            "mandatory_proof",
            evidence.mandatory_challenge_count > 0
            and proof_success >= self._minimum_proof_success_millionths,
            str(proof_success),
            "proof_success_below_threshold",
        )
        gate(
            "completeness",
            evidence.required_object_count > 0
            and completeness >= self._minimum_completeness_millionths,
            str(completeness),
            "completeness_below_threshold",
        )
        gate(
            "availability_observations",
            evidence.availability_observation_count > 0 and availability > 0,
            str(availability),
            "availability_evidence_missing",
        )
        beneficiary_valid = bool(evidence.operator_wallet and evidence.reward_beneficiary)
        gate("reward_beneficiary", beneficiary_valid, evidence.reward_beneficiary, "reward_beneficiary_missing")

        signature_valid = True
        if self._require_signature:
            signature_verifier = self._signature_verifier
            signature_valid = bool(evidence.signature) and signature_verifier is not None
            if signature_valid and signature_verifier is not None:
                try:
                    signature_valid = bool(signature_verifier(evidence))
                except Exception:
                    signature_valid = False
        gate(
            "evidence_signature",
            signature_valid,
            "verified" if signature_valid else "missing_or_invalid",
            "evidence_signature_invalid",
        )
        if not signature_valid:
            valid = False

        eligible = valid and all(item.passed for item in gates)
        if eligible:
            raw_weight = self.raw_weight_millionths(
                evidence=evidence,
                proof_success_millionths=proof_success,
                completeness_millionths=completeness,
                availability_millionths=availability,
            )
        else:
            raw_weight = 0
        result = RegistryDutyVerificationResult(
            evidence_id=evidence.evidence_id,
            registry_service_id=evidence.registry_service_id,
            epoch=evidence.epoch,
            valid=valid,
            eligible=eligible,
            gates=gates,
            reasons=reasons,
            proof_success_millionths=proof_success,
            completeness_millionths=completeness,
            availability_millionths=availability,
            raw_weight_millionths=raw_weight,
            evidence_root=evidence.evidence_hash,
            finality_operation_id=evidence.finalized_operation_id,
        )
        return result.with_hash()

    @staticmethod
    def raw_weight_millionths(
        *,
        evidence: RegistryDutyEvidence,
        proof_success_millionths: int,
        completeness_millionths: int,
        availability_millionths: int,
    ) -> int:
        quality = _scaled_product(
            [
                evidence.maturity_factor_millionths,
                evidence.health_factor_millionths,
                availability_millionths,
                proof_success_millionths,
                completeness_millionths,
                evidence.latency_factor_millionths,
                evidence.reliability_factor_millionths,
            ]
        )
        return (evidence.registry_work_units_millionths * quality) // FIXED_POINT_SCALE

    def build_reward_input(
        self,
        evidence: RegistryDutyEvidence,
        result: RegistryDutyVerificationResult | None = None,
    ) -> RegistryRewardInput:
        result = result or self.evaluate(evidence)
        if not result.valid:
            raise ValueError("cannot create Registry reward input from invalid evidence")
        if not result.eligible:
            raise ValueError("cannot create Registry reward input for ineligible Registry")
        snapshot = self.build_eligibility_snapshot(evidence, result)
        return RegistryRewardInput(
            service_id=evidence.registry_service_id,
            epoch=evidence.epoch,
            reward_beneficiary=evidence.reward_beneficiary,
            known_control_group_id=evidence.known_control_group_id,
            work_units_millionths=evidence.registry_work_units_millionths,
            maturity_factor_millionths=evidence.maturity_factor_millionths,
            health_factor_millionths=evidence.health_factor_millionths,
            proof_success_millionths=result.proof_success_millionths,
            completeness_millionths=result.completeness_millionths,
            availability_millionths=result.availability_millionths,
            latency_factor_millionths=evidence.latency_factor_millionths,
            reliability_factor_millionths=evidence.reliability_factor_millionths,
            raw_weight_millionths=result.raw_weight_millionths,
            evidence_id=evidence.evidence_id,
            evidence_hash=evidence.evidence_hash,
            eligibility_decision_hash=result.decision_hash,
            eligibility_snapshot_id=snapshot.snapshot_id,
            finalized_operation_id=evidence.finalized_operation_id,
        )

    def build_eligibility_snapshot(
        self,
        evidence: RegistryDutyEvidence,
        result: RegistryDutyVerificationResult | None = None,
    ) -> RegistryEligibilitySnapshot:
        """Freeze the epoch decision used by reward aggregation."""
        result = result or self.evaluate(evidence)
        if not result.valid:
            raise ValueError("cannot snapshot invalid Registry Duty evidence")
        return RegistryEligibilitySnapshot.create(
            evidence=evidence,
            decision=result,
        )

    def _finality_for(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        if self._finality_source is None:
            return None
        try:
            evidence = self._finality_source.finality_evidence(operation_id)
        except Exception:
            return None
        if not isinstance(evidence, ConsensusFinalityEvidence):
            return None
        return evidence if evidence.operation_id == operation_id else None


class RegistryEligibilitySnapshot(BaseModel, frozen=True):
    """Immutable Registry eligibility boundary consumed by an Epoch Task."""

    snapshot_version: str = "registry-eligibility-snapshot.v1"
    snapshot_id: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    service_id: str = Field(min_length=1)
    state: str = Field(pattern="^(eligible|ineligible)$")
    evidence_id: str = Field(min_length=1)
    evidence_hash: str = Field(min_length=1)
    decision_hash: str = Field(min_length=1)
    reward_beneficiary: str = Field(min_length=1)
    known_control_group_id: str | None = None
    raw_weight_millionths: int = Field(ge=0)
    finalized_operation_id: str = Field(min_length=1)

    @classmethod
    def create(
        cls,
        *,
        evidence: RegistryDutyEvidence,
        decision: RegistryDutyVerificationResult,
    ) -> RegistryEligibilitySnapshot:
        payload = {
            "snapshot_version": "registry-eligibility-snapshot.v1",
            "epoch": evidence.epoch,
            "service_id": evidence.registry_service_id,
            "state": "eligible" if decision.eligible else "ineligible",
            "evidence_id": evidence.evidence_id,
            "evidence_hash": evidence.evidence_hash,
            "decision_hash": decision.decision_hash,
            "reward_beneficiary": evidence.reward_beneficiary,
            "known_control_group_id": evidence.known_control_group_id,
            "raw_weight_millionths": decision.raw_weight_millionths,
            "finalized_operation_id": evidence.finalized_operation_id,
        }
        snapshot_id = _digest(payload)
        return cls.model_validate({"snapshot_id": snapshot_id, **payload})


__all__ = [
    "DEFAULT_BASE_WORK_UNITS",
    "DEFAULT_MAX_ADDITIONAL_WORK_UNITS",
    "DEFAULT_MINIMUM_ACTIVATION_AGE_EPOCHS",
    "DEFAULT_MINIMUM_COMPLETENESS",
    "DEFAULT_MINIMUM_HEALTH",
    "DEFAULT_MINIMUM_PROOF_SUCCESS",
    "FIXED_POINT_SCALE",
    "RegistryDutyEvidence",
    "RegistryDutyVerificationResult",
    "RegistryDutyVerifier",
    "RegistryEligibilitySnapshot",
    "RegistryEligibilityGate",
    "RegistryRewardInput",
    "registry_duty_signing_bytes",
]
