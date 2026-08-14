"""Consensus envelope for additive ECO-0007 activation scope extensions."""

from __future__ import annotations

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.reward.development_activation import (
    DevelopmentRewardActivationApproval,
    DevelopmentRewardActivationScopeExtension,
    verify_development_reward_activation_scope_extension,
)
from aidn_hypervisor.reward.development_distribution import canonical_hash

DEVELOPMENT_REWARD_ACTIVATION_SCOPE_EXTEND_OPERATION = "DEVELOPMENT_REWARD_ACTIVATION_SCOPE_EXTEND"


def build_development_reward_activation_scope_extension_operation(
    *,
    base_approval: DevelopmentRewardActivationApproval,
    extension: DevelopmentRewardActivationScopeExtension,
    base_calculation_operation_id: str,
    created_at: str,
) -> LedgerOperationEnvelope:
    """Build a protocol-sponsored, evidence-only extension envelope."""

    if not base_calculation_operation_id.strip():
        raise ValueError("DEVELOPMENT_ACTIVATION_SCOPE_EXTENSION_CALCULATION_REQUIRED")
    verify_development_reward_activation_scope_extension(extension, base_approval=base_approval)
    payload = {
        "extension_version": extension.extension_version,
        "scope_extension": extension.model_dump(mode="json"),
        "extension_id": extension.extension_id,
        "extension_hash": extension.extension_hash,
        "base_activation_id": base_approval.activation_id,
        "base_approval_hash": base_approval.approval_hash,
        "base_calculation_operation_id": base_calculation_operation_id,
    }
    payload["payload_hash"] = canonical_hash(payload)
    return LedgerOperationEnvelope(
        operation_type=DEVELOPMENT_REWARD_ACTIVATION_SCOPE_EXTEND_OPERATION,
        operation_version="1.0.0",
        protocol_version="0.1",
        origin_type="protocol",
        initiator_id="development-reward-governance",
        fee_class="protocol_sponsored",
        created_at=created_at,
        target_epoch=str(extension.effective_epoch),
        payload=payload,
        evidence_references=sorted(
            {
                extension.extension_id,
                extension.extension_hash or "",
                base_approval.activation_id,
                base_approval.approval_hash or "",
                base_calculation_operation_id,
            }
        ),
    )


__all__ = [
    "DEVELOPMENT_REWARD_ACTIVATION_SCOPE_EXTEND_OPERATION",
    "build_development_reward_activation_scope_extension_operation",
]
