"""Signed non-response confirmation primitives for RFC-0061."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from .proof import (
    RegistryChallenge,
    verify_ed25519_signature,
)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


class RegistryRequestEvidence(BaseModel, frozen=True):
    """Signed evidence that a challenge was sent to its target."""

    evidence_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1)
    challenge_id: str = Field(min_length=1)
    target_registry_id: str = Field(min_length=1)
    target_inventory_root: str = Field(min_length=1)
    challenger_id: str = Field(min_length=1)
    request_hash: str = Field(min_length=1)
    sent_at: float
    response_deadline: float
    transport_session_id: str = ""
    transport_state: str = "request_sent"
    challenger_signature: str = ""


class RegistryNonResponseObservation(BaseModel, frozen=True):
    """One signed observation made after a challenge response deadline."""

    observation_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1)
    challenge_id: str = Field(min_length=1)
    target_registry_id: str = Field(min_length=1)
    observer_id: str = Field(min_length=1)
    observer_role: str = "independent_verifier"
    request_hash: str = Field(min_length=1)
    attempt_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1)
    observed_at: float
    response_received: bool = False
    response_hash: str = ""
    transport_state: str = "no_response"
    network_condition: str = "healthy"
    observer_signature: str = ""


class RegistryFailureReport(BaseModel, frozen=True):
    """Canonical report resulting from independent non-response confirmation."""

    report_id: str = Field(min_length=1)
    target_registry_id: str = Field(min_length=1)
    challenge_id: str = Field(min_length=1)
    failure_type: str = "challenge_non_response"
    request_evidence: dict[str, Any]
    confirmation_evidence: list[dict[str, Any]] = Field(default_factory=list)
    verifier_ids: list[str] = Field(default_factory=list)
    network_condition_summary: str = "healthy"
    result: str = "confirmed_non_response"
    evidence_root: str = Field(min_length=1)
    report_signer_id: str = Field(min_length=1)
    signatures: dict[str, str] = Field(default_factory=dict)
    created_at: float


class RegistryFailureVerificationResult(BaseModel, frozen=True):
    """Stable verification result for a Registry Failure Report."""

    valid: bool
    report_id: str
    result: str
    reason: str = ""


def request_evidence_signing_bytes(evidence: RegistryRequestEvidence) -> bytes:
    return _canonical_bytes(evidence.model_dump(mode="json", exclude={"challenger_signature"}))


def observation_signing_bytes(observation: RegistryNonResponseObservation) -> bytes:
    return _canonical_bytes(observation.model_dump(mode="json", exclude={"observer_signature"}))


def failure_report_signing_bytes(report: RegistryFailureReport) -> bytes:
    return _canonical_bytes(report.model_dump(mode="json", exclude={"signatures"}))


class NonResponseConfirmationEngine:
    """Create and verify bounded, signed non-response evidence."""

    def __init__(
        self,
        *,
        registry_id: str,
        signer: Callable[[bytes], str] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not registry_id:
            raise ValueError("registry_id is required")
        self._registry_id = registry_id
        self._signer = signer
        self._clock = clock

    def create_request_evidence(
        self,
        *,
        challenge: RegistryChallenge,
        transport_session_id: str = "",
    ) -> RegistryRequestEvidence:
        if challenge.challenger_id != self._registry_id:
            raise ValueError("challenge challenger does not match local Registry")
        request_hash = "sha256:" + _digest(
            {"challenge": challenge.model_dump(mode="json")}
        )
        evidence = RegistryRequestEvidence(
            challenge_id=challenge.challenge_id,
            target_registry_id=challenge.target_registry_id,
            target_inventory_root=challenge.target_inventory_root,
            challenger_id=challenge.challenger_id,
            request_hash=request_hash,
            sent_at=self._clock(),
            response_deadline=challenge.response_deadline,
            transport_session_id=transport_session_id,
        )
        return self._sign_request(evidence)

    def create_observation(
        self,
        *,
        request_evidence: RegistryRequestEvidence,
        challenge: RegistryChallenge,
        response_received: bool = False,
        response_hash: str = "",
        transport_state: str = "no_response",
        network_condition: str = "healthy",
        observer_role: str = "independent_verifier",
        attempt_id: str | None = None,
    ) -> RegistryNonResponseObservation:
        if request_evidence.challenge_id != challenge.challenge_id:
            raise ValueError("request evidence challenge mismatch")
        if request_evidence.target_registry_id != challenge.target_registry_id:
            raise ValueError("request evidence target mismatch")
        if not observer_role:
            raise ValueError("observer_role is required")
        observation = RegistryNonResponseObservation(
            challenge_id=challenge.challenge_id,
            target_registry_id=challenge.target_registry_id,
            observer_id=self._registry_id,
            observer_role=observer_role,
            request_hash=request_evidence.request_hash,
            attempt_id=attempt_id or str(uuid.uuid4()),
            observed_at=self._clock(),
            response_received=response_received,
            response_hash=response_hash,
            transport_state=transport_state,
            network_condition=network_condition,
        )
        return self._sign_observation(observation)

    def build_failure_report(
        self,
        *,
        challenge: RegistryChallenge,
        request_evidence: RegistryRequestEvidence,
        observations: Sequence[RegistryNonResponseObservation],
        known_control_groups: Mapping[str, str] | None = None,
        minimum_independent_observers: int = 2,
        created_at: float | None = None,
    ) -> RegistryFailureReport:
        if self._signer is None:
            raise ValueError("a report signer is required")
        structural = self._validate_evidence(
            challenge=challenge,
            request_evidence=request_evidence,
            observations=observations,
            known_control_groups=known_control_groups,
            minimum_independent_observers=minimum_independent_observers,
        )
        if not structural.valid:
            raise ValueError(structural.reason)
        ordered = sorted(observations, key=lambda item: (item.observer_id, item.attempt_id))
        request_data = request_evidence.model_dump(mode="json")
        confirmation_data = [item.model_dump(mode="json") for item in ordered]
        evidence_payload = {
            "request_evidence": request_data,
            "confirmation_evidence": confirmation_data,
            "verifier_ids": sorted({item.observer_id for item in ordered}),
            "target_registry_id": challenge.target_registry_id,
            "challenge_id": challenge.challenge_id,
        }
        evidence_root = "sha256:" + _digest(evidence_payload)
        conditions = sorted({item.network_condition for item in ordered})
        report_without_signature = RegistryFailureReport(
            report_id="sha256:" + _digest(
                {
                    "evidence_root": evidence_root,
                    "failure_type": "challenge_non_response",
                    "target_registry_id": challenge.target_registry_id,
                    "challenge_id": challenge.challenge_id,
                }
            ),
            target_registry_id=challenge.target_registry_id,
            challenge_id=challenge.challenge_id,
            request_evidence=request_data,
            confirmation_evidence=confirmation_data,
            verifier_ids=sorted({item.observer_id for item in ordered}),
            network_condition_summary=conditions[0] if len(conditions) == 1 else "mixed_healthy_degraded",
            evidence_root=evidence_root,
            report_signer_id=self._registry_id,
            created_at=self._clock() if created_at is None else created_at,
        )
        signature = self._signer(failure_report_signing_bytes(report_without_signature))
        if not isinstance(signature, str) or not signature.startswith("ed25519:"):
            raise ValueError("Registry failure report signer must return an ed25519 signature")
        return report_without_signature.model_copy(
            update={"signatures": {self._registry_id: signature}}
        )

    def verify_failure_report(
        self,
        *,
        challenge: RegistryChallenge,
        report: RegistryFailureReport,
        verifier_public_keys: Mapping[str, str],
        known_control_groups: Mapping[str, str] | None = None,
        minimum_independent_observers: int = 2,
    ) -> RegistryFailureVerificationResult:
        def failure(reason: str) -> RegistryFailureVerificationResult:
            return RegistryFailureVerificationResult(
                valid=False,
                report_id=report.report_id,
                result=report.result,
                reason=reason,
            )

        try:
            request = RegistryRequestEvidence.model_validate(report.request_evidence)
            observations = [
                RegistryNonResponseObservation.model_validate(item)
                for item in report.confirmation_evidence
            ]
        except (TypeError, ValueError):
            return failure("failure_report_evidence_invalid")
        structural = self._validate_evidence(
            challenge=challenge,
            request_evidence=request,
            observations=observations,
            known_control_groups=known_control_groups,
            minimum_independent_observers=minimum_independent_observers,
        )
        if not structural.valid:
            return failure(structural.reason)
        if (
            report.target_registry_id != challenge.target_registry_id
            or report.challenge_id != challenge.challenge_id
            or report.failure_type != "challenge_non_response"
            or report.result != "confirmed_non_response"
        ):
            return failure("failure_report_binding_invalid")
        if not request.challenger_signature:
            return failure("request_evidence_signature_missing")
        challenger_key = verifier_public_keys.get(request.challenger_id)
        if challenger_key is None or not verify_ed25519_signature(
            public_key=challenger_key,
            signature=request.challenger_signature,
            payload=request_evidence_signing_bytes(request),
        ):
            return failure("request_evidence_signature_invalid")
        for observation in observations:
            key = verifier_public_keys.get(observation.observer_id)
            if key is None or not observation.observer_signature:
                return failure("observation_signature_missing")
            if not verify_ed25519_signature(
                public_key=key,
                signature=observation.observer_signature,
                payload=observation_signing_bytes(observation),
            ):
                return failure("observation_signature_invalid")
        evidence_payload = {
            "request_evidence": request.model_dump(mode="json"),
            "confirmation_evidence": [
                item.model_dump(mode="json")
                for item in sorted(observations, key=lambda item: (item.observer_id, item.attempt_id))
            ],
            "verifier_ids": sorted({item.observer_id for item in observations}),
            "target_registry_id": challenge.target_registry_id,
            "challenge_id": challenge.challenge_id,
        }
        expected_root = "sha256:" + _digest(evidence_payload)
        if report.evidence_root != expected_root:
            return failure("failure_evidence_root_mismatch")
        expected_verifier_ids = sorted({item.observer_id for item in observations})
        if report.verifier_ids != expected_verifier_ids:
            return failure("failure_verifier_ids_mismatch")
        conditions = sorted({item.network_condition for item in observations})
        expected_condition_summary = (
            conditions[0] if len(conditions) == 1 else "mixed_healthy_degraded"
        )
        if report.network_condition_summary != expected_condition_summary:
            return failure("failure_network_summary_mismatch")
        expected_report_id = "sha256:" + _digest(
            {
                "evidence_root": expected_root,
                "failure_type": "challenge_non_response",
                "target_registry_id": challenge.target_registry_id,
                "challenge_id": challenge.challenge_id,
            }
        )
        if report.report_id != expected_report_id:
            return failure("failure_report_id_mismatch")
        report_key = verifier_public_keys.get(report.report_signer_id)
        report_signature = report.signatures.get(report.report_signer_id, "")
        if report_key is None or not report_signature or not verify_ed25519_signature(
            public_key=report_key,
            signature=report_signature,
            payload=failure_report_signing_bytes(report),
        ):
            return failure("failure_report_signature_invalid")
        return RegistryFailureVerificationResult(
            valid=True,
            report_id=report.report_id,
            result=report.result,
            reason="verified",
        )

    def _sign_request(self, evidence: RegistryRequestEvidence) -> RegistryRequestEvidence:
        if self._signer is None:
            return evidence
        signature = self._signer(request_evidence_signing_bytes(evidence))
        if not isinstance(signature, str) or not signature.startswith("ed25519:"):
            raise ValueError("Registry request evidence signer must return an ed25519 signature")
        return evidence.model_copy(update={"challenger_signature": signature})

    def _sign_observation(
        self,
        observation: RegistryNonResponseObservation,
    ) -> RegistryNonResponseObservation:
        if self._signer is None:
            return observation
        signature = self._signer(observation_signing_bytes(observation))
        if not isinstance(signature, str) or not signature.startswith("ed25519:"):
            raise ValueError("Registry observation signer must return an ed25519 signature")
        return observation.model_copy(update={"observer_signature": signature})

    @staticmethod
    def _validate_evidence(
        *,
        challenge: RegistryChallenge,
        request_evidence: RegistryRequestEvidence,
        observations: Sequence[RegistryNonResponseObservation],
        known_control_groups: Mapping[str, str] | None,
        minimum_independent_observers: int,
    ) -> RegistryFailureVerificationResult:
        if minimum_independent_observers < 2:
            return RegistryFailureVerificationResult(
                valid=False,
                report_id="",
                result="inconclusive",
                reason="minimum_independent_observers_must_include_confirmation",
            )
        if request_evidence.challenge_id != challenge.challenge_id:
            return RegistryFailureVerificationResult(
                valid=False, report_id="", result="inconclusive", reason="challenge_id_mismatch"
            )
        if request_evidence.target_registry_id != challenge.target_registry_id:
            return RegistryFailureVerificationResult(
                valid=False, report_id="", result="inconclusive", reason="target_registry_id_mismatch"
            )
        if request_evidence.target_inventory_root != challenge.target_inventory_root:
            return RegistryFailureVerificationResult(
                valid=False, report_id="", result="inconclusive", reason="inventory_root_mismatch"
            )
        if request_evidence.response_deadline != challenge.response_deadline:
            return RegistryFailureVerificationResult(
                valid=False, report_id="", result="inconclusive", reason="response_deadline_mismatch"
            )
        if request_evidence.sent_at > challenge.response_deadline:
            return RegistryFailureVerificationResult(
                valid=False, report_id="", result="inconclusive", reason="request_sent_after_deadline"
            )
        if not observations:
            return RegistryFailureVerificationResult(
                valid=False, report_id="", result="inconclusive", reason="observations_missing"
            )
        if len({item.observer_id for item in observations}) != len(observations):
            return RegistryFailureVerificationResult(
                valid=False, report_id="", result="inconclusive", reason="duplicate_observer"
            )
        groups = known_control_groups or {}
        independent_groups = {groups.get(item.observer_id, item.observer_id) for item in observations}
        if len(independent_groups) < minimum_independent_observers:
            return RegistryFailureVerificationResult(
                valid=False, report_id="", result="inconclusive", reason="independent_quorum_missing"
            )
        if not any(item.observer_role == "independent_verifier" for item in observations):
            return RegistryFailureVerificationResult(
                valid=False, report_id="", result="inconclusive", reason="independent_verifier_missing"
            )
        if any(
            item.observer_id == request_evidence.challenger_id
            and item.observer_role == "independent_verifier"
            for item in observations
        ):
            return RegistryFailureVerificationResult(
                valid=False,
                report_id="",
                result="inconclusive",
                reason="challenger_cannot_be_independent_verifier",
            )
        for item in observations:
            if item.challenge_id != challenge.challenge_id or item.target_registry_id != challenge.target_registry_id:
                return RegistryFailureVerificationResult(
                    valid=False, report_id="", result="inconclusive", reason="observation_binding_mismatch"
                )
            if item.request_hash != request_evidence.request_hash:
                return RegistryFailureVerificationResult(
                    valid=False, report_id="", result="inconclusive", reason="observation_request_mismatch"
                )
            if item.observed_at < request_evidence.response_deadline:
                return RegistryFailureVerificationResult(
                    valid=False, report_id="", result="inconclusive", reason="observation_before_deadline"
                )
            if item.response_received:
                return RegistryFailureVerificationResult(
                    valid=False, report_id="", result="not_confirmed", reason="response_received"
                )
            if item.network_condition not in {"healthy", "degraded"}:
                return RegistryFailureVerificationResult(
                    valid=False, report_id="", result="inconclusive", reason="network_condition_unreliable"
                )
            if item.transport_state not in {"no_response", "request_sent", "connected"}:
                return RegistryFailureVerificationResult(
                    valid=False, report_id="", result="inconclusive", reason="transport_state_unreliable"
                )
        return RegistryFailureVerificationResult(
            valid=True, report_id="", result="confirmed_non_response", reason="evidence_sufficient"
        )
