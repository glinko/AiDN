#!/usr/bin/env python3
"""Build a source-bound ECO-0007 maturity payment from a finalized batch.

This command is offline-only. It reuses the exact calculation, commitment,
approval, allocation and reserve evidence from an existing production batch,
then binds one reserved maturity stage to a finalized activation scope
extension and a caller-supplied epoch-transition operation ID.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from aidn_hypervisor.reward.development_activation import (
    DevelopmentRewardActivationApproval,
    DevelopmentRewardActivationScopeExtension,
    verify_development_reward_activation_scope_extension,
)
from aidn_hypervisor.reward.development_distribution import DevelopmentRewardCalculation
from aidn_hypervisor.reward.development_operations import (
    DevelopmentRewardOperationRequest,
    build_development_reward_operation,
)
from aidn_hypervisor.reward.development_production import DevelopmentRewardProductionBatch


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", required=True, type=Path)
    parser.add_argument("--extension", required=True, type=Path)
    parser.add_argument("--extension-operation-id", required=True)
    parser.add_argument("--stage", choices=["MATURITY_STAGE_ONE", "MATURITY_STAGE_TWO"], required=True)
    parser.add_argument("--source-epoch-transition-operation-id", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def _require_operation_id(value: str, *, option: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{option} must be a 64-character lowercase hex operation ID")
    return value


def main() -> int:
    args = _parser().parse_args()
    extension_operation_id = _require_operation_id(
        args.extension_operation_id,
        option="--extension-operation-id",
    )
    source_epoch_transition_operation_id = _require_operation_id(
        args.source_epoch_transition_operation_id,
        option="--source-epoch-transition-operation-id",
    )
    batch = DevelopmentRewardProductionBatch.model_validate_json(
        args.batch.read_text(encoding="utf-8")
    )
    extension = DevelopmentRewardActivationScopeExtension.model_validate_json(
        args.extension.read_text(encoding="utf-8")
    )
    calc_envelope = batch.plan.envelopes[0]
    allocation_envelope = next(
        item for item in batch.plan.envelopes if item.operation_type == "DEVELOPMENT_POOL_ALLOCATE"
    )
    reserve_envelope = next(
        item for item in batch.plan.envelopes if item.operation_type == "DEVELOPMENT_REWARD_RESERVE"
    )
    calculation = DevelopmentRewardCalculation.model_validate(calc_envelope.payload["calculation"])
    approval = DevelopmentRewardActivationApproval.model_validate(
        calc_envelope.payload["activation_approval"]
    )
    verify_development_reward_activation_scope_extension(extension, base_approval=approval)
    if "DEVELOPMENT_REWARD_PAY_MATURITY" not in extension.additional_operation_types:
        raise ValueError("DEVELOPMENT_REWARD_MATURITY_SCOPE_REQUIRED")
    payment = next(
        (
            item
            for item in calculation.payments
            if item.payment_stage == args.stage and item.state == "RESERVED" and item.amount_q_atoms > 0
        ),
        None,
    )
    if payment is None:
        raise ValueError("DEVELOPMENT_REWARD_MATURITY_STAGE_NOT_RESERVED")
    allocation = allocation_envelope.payload.get("pool_allocation") or {}
    reserve = reserve_envelope.payload.get("reward_reserve") or {}
    envelope = build_development_reward_operation(
        DevelopmentRewardOperationRequest(
            operation_type="DEVELOPMENT_REWARD_PAY_MATURITY",
            created_at=args.created_at,
            commitment=batch.plan.commitment,
            activation_approval=approval,
            calculation=calculation,
            activation_scope_extension=extension,
            activation_scope_extension_operation_id=extension_operation_id,
            calculation_operation_id=calc_envelope.operation_id,
            pool_allocation_id=allocation.get("allocation_id"),
            pool_allocation_operation_id=allocation_envelope.operation_id,
            reserve_id=reserve.get("reserve_id"),
            reserve_operation_id=reserve_envelope.operation_id,
            source_epoch_transition_operation_id=source_epoch_transition_operation_id,
            reward_id=payment.reward_id,
            contributor_id=payment.contributor_id,
            recipient_wallet=payment.wallet_address,
            role=payment.role,
            payment_hash=payment.payment_hash,
            payment_stage=payment.payment_stage,
            amount_q_atoms=payment.amount_q_atoms,
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "CREATED",
                "operation_id": envelope.operation_id,
                "operation_type": envelope.operation_type,
                "payment_stage": payment.payment_stage,
                "amount_q_atoms": payment.amount_q_atoms,
                "recipient_wallet": payment.wallet_address,
                "extension_operation_id": extension_operation_id,
                "source_epoch_transition_operation_id": source_epoch_transition_operation_id,
                "output": str(args.output),
                "broadcast": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, StopIteration) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        raise SystemExit(2) from error
