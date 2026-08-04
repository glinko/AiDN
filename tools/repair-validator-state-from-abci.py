#!/usr/bin/env python3
"""Plan or apply fail-closed validator state reconciliation from an ABCI snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aidn_hypervisor.consensus.recovery import (
    ValidatorRecoveryError,
    apply_validator_recovery_plan,
    build_validator_recovery_plan,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hypervisor-state", required=True, type=Path)
    parser.add_argument("--abci-state", required=True, type=Path)
    parser.add_argument("--discard-operation-id", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm-offline",
        action="store_true",
        help="confirm that CometBFT and the ABCI process are stopped before applying",
    )
    parser.add_argument("--backup-path", type=Path)
    args = parser.parse_args()
    if args.apply and not args.confirm_offline:
        raise SystemExit("--apply requires --confirm-offline; reconcile validator state offline")
    try:
        plan = build_validator_recovery_plan(
            hypervisor_state_path=args.hypervisor_state,
            abci_state_path=args.abci_state,
            discard_operation_ids=args.discard_operation_id,
        )
        result = {
            "status": "plan_ready",
            "source_snapshot_id": plan.source_snapshot_id,
            "source_height": plan.source_height,
            "source_app_hash": plan.source_app_hash,
            "discarded_operation_ids": plan.discarded_operation_ids,
            "changed_fields": plan.changed_fields,
        }
        if args.apply:
            backup = apply_validator_recovery_plan(
                plan=plan,
                hypervisor_state_path=args.hypervisor_state,
                backup_path=args.backup_path,
            )
            result.update(
                {
                    "status": "applied",
                    "backup_path": str(backup),
                    "offline_confirmation": "OPERATOR_CONFIRMED_VALIDATOR_OFFLINE",
                }
            )
        print(json.dumps(result, sort_keys=True))
    except ValidatorRecoveryError as error:
        raise SystemExit(f"validator recovery rejected: {error}") from error


if __name__ == "__main__":
    main()
