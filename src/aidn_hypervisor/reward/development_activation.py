"""Governance activation boundary for ECO-0007.

This module verifies an explicit, policy-hash-bound approval. It deliberately
does not call a Ledger, Wallet, epoch transition, or mint operation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import (
    DEVELOPMENT_REWARD_CALCULATION_VERSION,
    DevelopmentRewardCalculation,
    DevelopmentRewardPolicy,
)
from aidn_hypervisor.reward.development_rollout import (
    DevelopmentRewardRolloutProfile,
    validate_development_reward_rollout,
)

DEVELOPMENT_ACTIVATION_VERSION = "eco-0007-activation.v1"
DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_VERSION = "eco-0007-activation-scope-extension.v1"


def _hash_payload(domain: str, payload: Any) -> str:
    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _public_key_bytes(value: str) -> bytes:
    if not value.startswith("ed25519:"):
        raise ValueError("DEVELOPMENT_ACTIVATION_PUBLIC_KEY_INVALID")
    try:
        decoded = bytes.fromhex(value.removeprefix("ed25519:"))
    except ValueError as error:
        raise ValueError("DEVELOPMENT_ACTIVATION_PUBLIC_KEY_INVALID") from error
    if len(decoded) != 32:
        raise ValueError("DEVELOPMENT_ACTIVATION_PUBLIC_KEY_INVALID")
    return decoded


class DevelopmentRewardAuthority(BaseModel, frozen=True):
    authority_id: str = Field(min_length=1)
    public_key: str = Field(min_length=1)


class DevelopmentRewardApprovalSignature(BaseModel, frozen=True):
    authority_id: str = Field(min_length=1)
    signature: str = Field(min_length=1)
    approval_note: str | None = None


class DevelopmentRewardActivationApproval(BaseModel, frozen=True):
    activation_id: str = Field(min_length=1)
    policy_hash: str = Field(min_length=1)
    effective_epoch: int = Field(ge=0)
    eligible_authorities: list[DevelopmentRewardAuthority] = Field(min_length=1)
    quorum_threshold: int = Field(ge=1)
    approvals: list[DevelopmentRewardApprovalSignature] = Field(default_factory=list)
    authorized_operation_types: list[str] = Field(
        default_factory=lambda: ["DEVELOPMENT_REWARD_CALCULATE"],
        min_length=1,
    )
    economic_effect_profile: Literal[
        "EVIDENCE_ONLY",
        "POOL_ALLOCATION",
        "DEVELOPMENT_RESERVES",
        "DEVELOPMENT_PAYMENTS",
    ] = "EVIDENCE_ONLY"
    rollout_profile: DevelopmentRewardRolloutProfile | None = None
    state: Literal["APPROVED", "REVOKED"] = "APPROVED"
    approval_hash: str | None = None

    @model_validator(mode="after")
    def validate_authorities(self) -> DevelopmentRewardActivationApproval:
        authority_ids = [item.authority_id for item in self.eligible_authorities]
        if len(set(authority_ids)) != len(authority_ids):
            raise ValueError("DEVELOPMENT_ACTIVATION_AUTHORITY_DUPLICATE")
        if self.quorum_threshold > len(authority_ids):
            raise ValueError("DEVELOPMENT_ACTIVATION_QUORUM_INVALID")
        approval_ids = [item.authority_id for item in self.approvals]
        if len(set(approval_ids)) != len(approval_ids):
            raise ValueError("DEVELOPMENT_ACTIVATION_APPROVAL_DUPLICATE")
        operation_types = [item.strip() for item in self.authorized_operation_types]
        if any(not item for item in operation_types) or len(set(operation_types)) != len(operation_types):
            raise ValueError("DEVELOPMENT_ACTIVATION_OPERATION_SCOPE_INVALID")
        if "DEVELOPMENT_REWARD_CALCULATE" not in operation_types:
            raise ValueError("DEVELOPMENT_ACTIVATION_CALCULATION_SCOPE_REQUIRED")
        if "DEVELOPMENT_POOL_ALLOCATE" in operation_types and self.economic_effect_profile not in {
            "POOL_ALLOCATION",
            "DEVELOPMENT_RESERVES",
            "DEVELOPMENT_PAYMENTS",
        }:
            raise ValueError("DEVELOPMENT_ACTIVATION_POOL_SCOPE_INVALID")
        if any(
            operation_type in operation_types
            for operation_type in {
                "DEVELOPMENT_POOL_CARRYOVER",
                "DEVELOPMENT_BOUNTY_CREATE",
                "DEVELOPMENT_BOUNTY_RESERVE",
                "DEVELOPMENT_BOUNTY_RELEASE",
                "DEVELOPMENT_BOUNTY_EXPIRE",
            }
        ) and self.economic_effect_profile not in {"POOL_ALLOCATION", "DEVELOPMENT_RESERVES", "DEVELOPMENT_PAYMENTS"}:
            raise ValueError("DEVELOPMENT_ACTIVATION_POOL_SCOPE_INVALID")
        if "DEVELOPMENT_REWARD_RESERVE" in operation_types and self.economic_effect_profile not in {
            "DEVELOPMENT_RESERVES",
            "DEVELOPMENT_PAYMENTS",
        }:
            raise ValueError("DEVELOPMENT_ACTIVATION_REWARD_RESERVE_SCOPE_INVALID")
        if (
            "DEVELOPMENT_REWARD_PAY_IMMEDIATE" in operation_types
            and self.economic_effect_profile != "DEVELOPMENT_PAYMENTS"
        ):
            raise ValueError("DEVELOPMENT_ACTIVATION_PAYMENT_SCOPE_INVALID")
        if (
            "DEVELOPMENT_REWARD_PAY_MATURITY" in operation_types
            and self.economic_effect_profile != "DEVELOPMENT_PAYMENTS"
        ):
            raise ValueError("DEVELOPMENT_ACTIVATION_MATURITY_PAYMENT_SCOPE_INVALID")
        if (
            "DEVELOPMENT_REWARD_MARK_UNCLAIMED" in operation_types
            and self.economic_effect_profile != "DEVELOPMENT_PAYMENTS"
        ):
            raise ValueError("DEVELOPMENT_ACTIVATION_UNCLAIMED_SCOPE_INVALID")
        if "DEVELOPMENT_REWARD_CLAIM" in operation_types and self.economic_effect_profile != "DEVELOPMENT_PAYMENTS":
            raise ValueError("DEVELOPMENT_ACTIVATION_CLAIM_SCOPE_INVALID")
        if (
            "DEVELOPMENT_REWARD_EXPIRE_UNCLAIMED" in operation_types
            and self.economic_effect_profile != "DEVELOPMENT_PAYMENTS"
        ):
            raise ValueError("DEVELOPMENT_ACTIVATION_EXPIRY_SCOPE_INVALID")
        if "DEVELOPMENT_REWARD_FINALIZE_COMMITMENT" in operation_types and self.economic_effect_profile not in {
            "DEVELOPMENT_PAYMENTS",
            "EVIDENCE_ONLY",
        }:
            raise ValueError("DEVELOPMENT_ACTIVATION_FINALIZED_COMMITMENT_SCOPE_INVALID")
        if any(
            operation_type in operation_types
            for operation_type in {
                "DEVELOPMENT_REWARD_CANCEL_UNVESTED",
                "DEVELOPMENT_REWARD_CORRECT",
            }
        ) and self.economic_effect_profile not in {"DEVELOPMENT_RESERVES", "DEVELOPMENT_PAYMENTS"}:
            raise ValueError("DEVELOPMENT_ACTIVATION_ADJUSTMENT_SCOPE_INVALID")
        if self.rollout_profile is not None:
            if self.rollout_profile.effective_epoch < self.effective_epoch:
                raise ValueError("DEVELOPMENT_ACTIVATION_ROLLOUT_EPOCH_INVALID")
            if not self.rollout_profile.verify_integrity():
                raise ValueError("DEVELOPMENT_ACTIVATION_ROLLOUT_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        payload = {
            "activation_id": self.activation_id,
            "policy_hash": self.policy_hash,
            "effective_epoch": self.effective_epoch,
            "eligible_authorities": [
                item.model_dump(mode="json")
                for item in sorted(self.eligible_authorities, key=lambda item: item.authority_id)
            ],
            "quorum_threshold": self.quorum_threshold,
            "approvals": [
                item.model_dump(mode="json") for item in sorted(self.approvals, key=lambda item: item.authority_id)
            ],
            "authorized_operation_types": sorted(self.authorized_operation_types),
            "economic_effect_profile": self.economic_effect_profile,
            "state": self.state,
        }
        if self.rollout_profile is not None:
            payload["rollout_profile"] = self.rollout_profile.model_dump(mode="json")
        return payload

    def verify_integrity(self) -> bool:
        return self.approval_hash == activation_approval_hash(self)


class DevelopmentRewardActivationScopeExtension(BaseModel, frozen=True):
    """An authority-signed additive scope for an existing commitment.

    The base activation remains immutable. An extension can only add operation
    types and must retain the exact authority set, policy and economic scope.
    """

    extension_version: str = DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_VERSION
    extension_id: str = Field(min_length=1)
    base_activation_id: str = Field(min_length=1)
    base_approval_hash: str = Field(min_length=1)
    policy_hash: str = Field(min_length=1)
    base_effective_epoch: int = Field(ge=0)
    effective_epoch: int = Field(ge=0)
    base_authorized_operation_types: list[str] = Field(min_length=1)
    additional_operation_types: list[str] = Field(min_length=1)
    eligible_authorities: list[DevelopmentRewardAuthority] = Field(min_length=1)
    quorum_threshold: int = Field(ge=1)
    approvals: list[DevelopmentRewardApprovalSignature] = Field(default_factory=list)
    economic_effect_profile: Literal[
        "POOL_ALLOCATION",
        "DEVELOPMENT_RESERVES",
        "DEVELOPMENT_PAYMENTS",
    ] = "DEVELOPMENT_PAYMENTS"
    state: Literal["APPROVED", "REVOKED"] = "APPROVED"
    extension_hash: str | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> DevelopmentRewardActivationScopeExtension:
        if self.extension_version != DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_VERSION:
            raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_VERSION_INVALID")
        if self.effective_epoch < self.base_effective_epoch:
            raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_EPOCH_INVALID")
        base_operations = [item.strip() for item in self.base_authorized_operation_types]
        additions = [item.strip() for item in self.additional_operation_types]
        if (
            any(not item for item in base_operations)
            or len(set(base_operations)) != len(base_operations)
            or any(not item for item in additions)
            or len(set(additions)) != len(additions)
            or set(base_operations) & set(additions)
        ):
            raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_OPERATION_SCOPE_INVALID")
        if any(not item.startswith("DEVELOPMENT_") for item in additions):
            raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_OPERATION_SCOPE_INVALID")
        authority_ids = [item.authority_id for item in self.eligible_authorities]
        if len(set(authority_ids)) != len(authority_ids):
            raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_AUTHORITY_DUPLICATE")
        if self.quorum_threshold > len(authority_ids):
            raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_QUORUM_INVALID")
        approval_ids = [item.authority_id for item in self.approvals]
        if len(set(approval_ids)) != len(approval_ids):
            raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_APPROVAL_DUPLICATE")
        if self.extension_hash is not None and not self.extension_hash.strip():
            raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return {
            "extension_version": self.extension_version,
            "extension_id": self.extension_id,
            "base_activation_id": self.base_activation_id,
            "base_approval_hash": self.base_approval_hash,
            "policy_hash": self.policy_hash,
            "base_effective_epoch": self.base_effective_epoch,
            "effective_epoch": self.effective_epoch,
            "base_authorized_operation_types": sorted(self.base_authorized_operation_types),
            "additional_operation_types": sorted(self.additional_operation_types),
            "eligible_authorities": [
                item.model_dump(mode="json")
                for item in sorted(self.eligible_authorities, key=lambda item: item.authority_id)
            ],
            "quorum_threshold": self.quorum_threshold,
            "approvals": [
                item.model_dump(mode="json") for item in sorted(self.approvals, key=lambda item: item.authority_id)
            ],
            "economic_effect_profile": self.economic_effect_profile,
            "state": self.state,
        }

    def verify_integrity(self) -> bool:
        return self.extension_hash == activation_scope_extension_hash(self)


class DevelopmentRewardActivationDecision(BaseModel, frozen=True):
    activation_id: str = Field(min_length=1)
    approval_hash: str = Field(min_length=1)
    policy_hash: str = Field(min_length=1)
    calculation_root: str = Field(min_length=1)
    effective_epoch: int = Field(ge=0)
    current_epoch: int = Field(ge=0)
    state: Literal["ACTIVE"] = "ACTIVE"
    decision_hash: str = Field(min_length=1)

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"decision_hash"})

    def verify_integrity(self) -> bool:
        return self.decision_hash == activation_decision_hash(self)


def development_reward_policy_hash(policy: DevelopmentRewardPolicy) -> str:
    """Return the exact policy commitment accepted by Governance."""

    return _hash_payload(
        "aidn.eco-0007.policy.v1",
        policy.model_dump(mode="json"),
    )


def activation_decision_hash(decision: DevelopmentRewardActivationDecision) -> str:
    return _hash_payload(
        "aidn.eco-0007.activation-decision.v1",
        decision.unsigned_payload(),
    )


def activation_authorization_payload(
    *,
    activation_id: str,
    policy_hash: str,
    effective_epoch: int,
    eligible_authorities: list[DevelopmentRewardAuthority],
    quorum_threshold: int,
    authority_id: str,
    authorized_operation_types: list[str] | None = None,
    economic_effect_profile: Literal[
        "EVIDENCE_ONLY",
        "POOL_ALLOCATION",
        "DEVELOPMENT_RESERVES",
        "DEVELOPMENT_PAYMENTS",
    ] = "EVIDENCE_ONLY",
    rollout_profile: DevelopmentRewardRolloutProfile | None = None,
) -> bytes:
    operation_types = sorted(item.strip() for item in (authorized_operation_types or ["DEVELOPMENT_REWARD_CALCULATE"]))
    payload = {
        "activation_id": activation_id,
        "policy_hash": policy_hash,
        "effective_epoch": effective_epoch,
        "eligible_authorities": [
            item.model_dump(mode="json") for item in sorted(eligible_authorities, key=lambda item: item.authority_id)
        ],
        "quorum_threshold": quorum_threshold,
        "authority_id": authority_id,
        "authorized_operation_types": operation_types,
        "economic_effect_profile": economic_effect_profile,
    }
    if rollout_profile is not None:
        payload["rollout_profile"] = rollout_profile.model_dump(mode="json")
    return json.dumps(
        {"domain": "aidn.eco-0007.activation-approval.v1", "payload": payload},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def activation_id_for(
    *,
    policy_hash: str,
    effective_epoch: int,
    eligible_authorities: list[DevelopmentRewardAuthority],
    quorum_threshold: int,
    authorized_operation_types: list[str] | None = None,
    economic_effect_profile: Literal[
        "EVIDENCE_ONLY",
        "POOL_ALLOCATION",
        "DEVELOPMENT_RESERVES",
        "DEVELOPMENT_PAYMENTS",
    ] = "EVIDENCE_ONLY",
    rollout_profile: DevelopmentRewardRolloutProfile | None = None,
) -> str:
    payload = {
        "policy_hash": policy_hash,
        "effective_epoch": effective_epoch,
        "eligible_authorities": [
            item.model_dump(mode="json") for item in sorted(eligible_authorities, key=lambda item: item.authority_id)
        ],
        "quorum_threshold": quorum_threshold,
        "authorized_operation_types": sorted(
            item.strip() for item in (authorized_operation_types or ["DEVELOPMENT_REWARD_CALCULATE"])
        ),
        "economic_effect_profile": economic_effect_profile,
    }
    if rollout_profile is not None:
        payload["rollout_profile"] = rollout_profile.model_dump(mode="json")
    return _hash_payload(
        "aidn.eco-0007.activation-id.v1",
        payload,
    )


def activation_approval_hash(approval: DevelopmentRewardActivationApproval) -> str:
    return _hash_payload(
        "aidn.eco-0007.activation-approval-record.v1",
        approval.unsigned_payload(),
    )


def activation_scope_extension_id_for(
    *,
    base_activation_id: str,
    base_approval_hash: str,
    policy_hash: str,
    base_effective_epoch: int,
    effective_epoch: int,
    base_authorized_operation_types: list[str],
    additional_operation_types: list[str],
    eligible_authorities: list[DevelopmentRewardAuthority],
    quorum_threshold: int,
    economic_effect_profile: str,
) -> str:
    return _hash_payload(
        "aidn.eco-0007.activation-scope-extension-id.v1",
        {
            "base_activation_id": base_activation_id,
            "base_approval_hash": base_approval_hash,
            "policy_hash": policy_hash,
            "base_effective_epoch": base_effective_epoch,
            "effective_epoch": effective_epoch,
            "base_authorized_operation_types": sorted(base_authorized_operation_types),
            "additional_operation_types": sorted(additional_operation_types),
            "eligible_authorities": [
                item.model_dump(mode="json")
                for item in sorted(eligible_authorities, key=lambda item: item.authority_id)
            ],
            "quorum_threshold": quorum_threshold,
            "economic_effect_profile": economic_effect_profile,
        },
    )


def activation_scope_extension_authorization_payload(
    *,
    extension_id: str,
    base_activation_id: str,
    base_approval_hash: str,
    policy_hash: str,
    base_effective_epoch: int,
    effective_epoch: int,
    base_authorized_operation_types: list[str],
    additional_operation_types: list[str],
    eligible_authorities: list[DevelopmentRewardAuthority],
    quorum_threshold: int,
    authority_id: str,
    economic_effect_profile: str,
) -> bytes:
    payload = {
        "extension_id": extension_id,
        "base_activation_id": base_activation_id,
        "base_approval_hash": base_approval_hash,
        "policy_hash": policy_hash,
        "base_effective_epoch": base_effective_epoch,
        "effective_epoch": effective_epoch,
        "base_authorized_operation_types": sorted(base_authorized_operation_types),
        "additional_operation_types": sorted(additional_operation_types),
        "eligible_authorities": [
            item.model_dump(mode="json")
            for item in sorted(eligible_authorities, key=lambda item: item.authority_id)
        ],
        "quorum_threshold": quorum_threshold,
        "authority_id": authority_id,
        "economic_effect_profile": economic_effect_profile,
    }
    return json.dumps(
        {"domain": "aidn.eco-0007.activation-scope-extension.v1", "payload": payload},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def activation_scope_extension_hash(
    extension: DevelopmentRewardActivationScopeExtension,
) -> str:
    return _hash_payload(
        "aidn.eco-0007.activation-scope-extension-record.v1",
        extension.unsigned_payload(),
    )


def build_development_reward_activation_scope_extension(
    *,
    base_approval: DevelopmentRewardActivationApproval,
    effective_epoch: int,
    additional_operation_types: list[str],
    approvals: list[DevelopmentRewardApprovalSignature],
) -> DevelopmentRewardActivationScopeExtension:
    verify_development_reward_activation_approval(base_approval)
    base_operations = sorted(base_approval.authorized_operation_types)
    additions = sorted(item.strip() for item in additional_operation_types)
    extension_id = activation_scope_extension_id_for(
        base_activation_id=base_approval.activation_id,
        base_approval_hash=base_approval.approval_hash or "",
        policy_hash=base_approval.policy_hash,
        base_effective_epoch=base_approval.effective_epoch,
        effective_epoch=effective_epoch,
        base_authorized_operation_types=base_operations,
        additional_operation_types=additions,
        eligible_authorities=base_approval.eligible_authorities,
        quorum_threshold=base_approval.quorum_threshold,
        economic_effect_profile=base_approval.economic_effect_profile,
    )
    extension = DevelopmentRewardActivationScopeExtension(
        extension_id=extension_id,
        base_activation_id=base_approval.activation_id,
        base_approval_hash=base_approval.approval_hash or "",
        policy_hash=base_approval.policy_hash,
        base_effective_epoch=base_approval.effective_epoch,
        effective_epoch=effective_epoch,
        base_authorized_operation_types=base_operations,
        additional_operation_types=additions,
        eligible_authorities=base_approval.eligible_authorities,
        quorum_threshold=base_approval.quorum_threshold,
        approvals=approvals,
        economic_effect_profile=base_approval.economic_effect_profile,
    )
    return extension.model_copy(update={"extension_hash": activation_scope_extension_hash(extension)})


def verify_development_reward_activation_scope_extension(
    extension: DevelopmentRewardActivationScopeExtension,
    *,
    base_approval: DevelopmentRewardActivationApproval,
) -> None:
    verify_development_reward_activation_approval(base_approval)
    if extension.state != "APPROVED":
        raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_REVOKED")
    if not extension.verify_integrity():
        raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_HASH_INVALID")
    if (
        extension.base_activation_id != base_approval.activation_id
        or extension.base_approval_hash != base_approval.approval_hash
        or extension.policy_hash != base_approval.policy_hash
        or extension.base_effective_epoch != base_approval.effective_epoch
        or extension.base_authorized_operation_types != sorted(base_approval.authorized_operation_types)
        or extension.economic_effect_profile != base_approval.economic_effect_profile
    ):
        raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_BASE_MISMATCH")
    expected_id = activation_scope_extension_id_for(
        base_activation_id=extension.base_activation_id,
        base_approval_hash=extension.base_approval_hash,
        policy_hash=extension.policy_hash,
        base_effective_epoch=extension.base_effective_epoch,
        effective_epoch=extension.effective_epoch,
        base_authorized_operation_types=extension.base_authorized_operation_types,
        additional_operation_types=extension.additional_operation_types,
        eligible_authorities=extension.eligible_authorities,
        quorum_threshold=extension.quorum_threshold,
        economic_effect_profile=extension.economic_effect_profile,
    )
    if extension.extension_id != expected_id:
        raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_ID_INVALID")
    if extension.eligible_authorities != base_approval.eligible_authorities:
        raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_AUTHORITY_SET_INVALID")
    if extension.quorum_threshold != base_approval.quorum_threshold:
        raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_QUORUM_INVALID")
    authority_by_id = {item.authority_id: item for item in extension.eligible_authorities}
    if len(extension.approvals) < extension.quorum_threshold:
        raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_QUORUM_MISSING")
    for item in extension.approvals:
        authority = authority_by_id.get(item.authority_id)
        if authority is None or not item.signature.startswith("ed25519:"):
            raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_SIGNATURE_INVALID")
        try:
            Ed25519PublicKey.from_public_bytes(_public_key_bytes(authority.public_key)).verify(
                bytes.fromhex(item.signature.removeprefix("ed25519:")),
                activation_scope_extension_authorization_payload(
                    extension_id=extension.extension_id,
                    base_activation_id=extension.base_activation_id,
                    base_approval_hash=extension.base_approval_hash,
                    policy_hash=extension.policy_hash,
                    base_effective_epoch=extension.base_effective_epoch,
                    effective_epoch=extension.effective_epoch,
                    base_authorized_operation_types=extension.base_authorized_operation_types,
                    additional_operation_types=extension.additional_operation_types,
                    eligible_authorities=extension.eligible_authorities,
                    quorum_threshold=extension.quorum_threshold,
                    authority_id=item.authority_id,
                    economic_effect_profile=extension.economic_effect_profile,
                ),
            )
        except (InvalidSignature, ValueError, TypeError) as error:
            raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_SIGNATURE_INVALID") from error


def build_development_reward_activation_approval(
    *,
    policy_hash: str,
    effective_epoch: int,
    eligible_authorities: list[DevelopmentRewardAuthority],
    quorum_threshold: int,
    approvals: list[DevelopmentRewardApprovalSignature],
    authorized_operation_types: list[str] | None = None,
    economic_effect_profile: Literal[
        "EVIDENCE_ONLY",
        "POOL_ALLOCATION",
        "DEVELOPMENT_RESERVES",
        "DEVELOPMENT_PAYMENTS",
    ] = "EVIDENCE_ONLY",
    rollout_profile: DevelopmentRewardRolloutProfile | None = None,
    state: Literal["APPROVED", "REVOKED"] = "APPROVED",
) -> DevelopmentRewardActivationApproval:
    operation_types = [item.strip() for item in (authorized_operation_types or ["DEVELOPMENT_REWARD_CALCULATE"])]
    activation_id = activation_id_for(
        policy_hash=policy_hash,
        effective_epoch=effective_epoch,
        eligible_authorities=eligible_authorities,
        quorum_threshold=quorum_threshold,
        authorized_operation_types=operation_types,
        economic_effect_profile=economic_effect_profile,
        rollout_profile=rollout_profile,
    )
    approval = DevelopmentRewardActivationApproval(
        activation_id=activation_id,
        policy_hash=policy_hash,
        effective_epoch=effective_epoch,
        eligible_authorities=eligible_authorities,
        quorum_threshold=quorum_threshold,
        approvals=approvals,
        authorized_operation_types=operation_types,
        economic_effect_profile=economic_effect_profile,
        rollout_profile=rollout_profile,
        state=state,
    )
    return approval.model_copy(update={"approval_hash": activation_approval_hash(approval)})


def verify_development_reward_activation_approval(
    approval: DevelopmentRewardActivationApproval,
) -> None:
    if approval.state != "APPROVED":
        raise ValueError("DEVELOPMENT_ACTIVATION_REVOKED")
    if not approval.verify_integrity():
        raise ValueError("DEVELOPMENT_ACTIVATION_APPROVAL_HASH_INVALID")

    authority_by_id = {item.authority_id: item for item in approval.eligible_authorities}
    expected_id = activation_id_for(
        policy_hash=approval.policy_hash,
        effective_epoch=approval.effective_epoch,
        eligible_authorities=approval.eligible_authorities,
        quorum_threshold=approval.quorum_threshold,
        authorized_operation_types=approval.authorized_operation_types,
        economic_effect_profile=approval.economic_effect_profile,
        rollout_profile=approval.rollout_profile,
    )
    if approval.activation_id != expected_id:
        raise ValueError("DEVELOPMENT_ACTIVATION_ID_INVALID")
    if len(approval.approvals) < approval.quorum_threshold:
        raise ValueError("DEVELOPMENT_ACTIVATION_QUORUM_MISSING")

    for item in approval.approvals:
        authority = authority_by_id.get(item.authority_id)
        if authority is None:
            raise ValueError("DEVELOPMENT_ACTIVATION_AUTHORITY_UNKNOWN")
        if not item.signature.startswith("ed25519:"):
            raise ValueError("DEVELOPMENT_ACTIVATION_SIGNATURE_INVALID")
        try:
            Ed25519PublicKey.from_public_bytes(_public_key_bytes(authority.public_key)).verify(
                bytes.fromhex(item.signature.removeprefix("ed25519:")),
                activation_authorization_payload(
                    activation_id=approval.activation_id,
                    policy_hash=approval.policy_hash,
                    effective_epoch=approval.effective_epoch,
                    eligible_authorities=approval.eligible_authorities,
                    quorum_threshold=approval.quorum_threshold,
                    authority_id=item.authority_id,
                    authorized_operation_types=approval.authorized_operation_types,
                    economic_effect_profile=approval.economic_effect_profile,
                    rollout_profile=approval.rollout_profile,
                ),
            )
        except (InvalidSignature, ValueError, TypeError) as error:
            raise ValueError("DEVELOPMENT_ACTIVATION_SIGNATURE_INVALID") from error


class DevelopmentRewardActivationGate:
    """Validate activation authorization without performing economic effects."""

    @staticmethod
    def assert_active(
        *,
        calculation: DevelopmentRewardCalculation,
        approval: DevelopmentRewardActivationApproval | None,
        current_epoch: int,
    ) -> DevelopmentRewardActivationDecision:
        if approval is None:
            raise ValueError("DEVELOPMENT_ACTIVATION_APPROVAL_REQUIRED")
        if current_epoch < approval.effective_epoch:
            raise ValueError("DEVELOPMENT_ACTIVATION_NOT_EFFECTIVE")
        if calculation.epoch < approval.effective_epoch:
            raise ValueError("DEVELOPMENT_ACTIVATION_CALCULATION_BEFORE_EFFECTIVE_EPOCH")
        if calculation.calculation_version != DEVELOPMENT_REWARD_CALCULATION_VERSION:
            raise ValueError("DEVELOPMENT_ACTIVATION_CALCULATION_VERSION_INVALID")
        validate_development_reward_rollout(calculation, approval.rollout_profile)

        expected_policy_hash = development_reward_policy_hash(calculation.policy)
        if approval.policy_hash != expected_policy_hash:
            raise ValueError("DEVELOPMENT_ACTIVATION_POLICY_MISMATCH")

        verify_development_reward_activation_approval(approval)
        payload = {
            "activation_id": approval.activation_id,
            "approval_hash": approval.approval_hash,
            "policy_hash": approval.policy_hash,
            "calculation_root": calculation.calculation_root,
            "effective_epoch": approval.effective_epoch,
            "current_epoch": current_epoch,
            "state": "ACTIVE",
        }
        return DevelopmentRewardActivationDecision(
            **payload,
            decision_hash=_hash_payload("aidn.eco-0007.activation-decision.v1", payload),
        )


__all__ = [
    "DEVELOPMENT_ACTIVATION_VERSION",
    "DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_VERSION",
    "DevelopmentRewardActivationApproval",
    "DevelopmentRewardActivationScopeExtension",
    "DevelopmentRewardActivationDecision",
    "DevelopmentRewardActivationGate",
    "DevelopmentRewardApprovalSignature",
    "DevelopmentRewardAuthority",
    "activation_approval_hash",
    "activation_authorization_payload",
    "activation_decision_hash",
    "activation_id_for",
    "activation_scope_extension_authorization_payload",
    "activation_scope_extension_hash",
    "activation_scope_extension_id_for",
    "build_development_reward_activation_approval",
    "build_development_reward_activation_scope_extension",
    "development_reward_policy_hash",
    "verify_development_reward_activation_scope_extension",
    "verify_development_reward_activation_approval",
]
