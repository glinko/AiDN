#!/usr/bin/env python3
"""Build an authority-signed additive ECO-0007 scope-extension envelope.

The command reads a public base approval and external private seed files. It
never broadcasts, prints private key material, or changes the base approval.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from aidn_hypervisor.consensus.epoch_transition import load_protocol_authority_private_key
from aidn_hypervisor.reward.development_activation import (
    DevelopmentRewardActivationApproval,
    DevelopmentRewardApprovalSignature,
    activation_scope_extension_authorization_payload,
    build_development_reward_activation_scope_extension,
)
from aidn_hypervisor.reward.development_activation_operations import (
    build_development_reward_activation_scope_extension_operation,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-approval", required=True, type=Path)
    parser.add_argument(
        "--signer",
        action="append",
        required=True,
        metavar="AUTHORITY_ID=PRIVATE_KEY_FILE",
    )
    parser.add_argument("--effective-epoch", required=True, type=int)
    parser.add_argument(
        "--operation-type",
        action="append",
        dest="operation_types",
        default=None,
    )
    parser.add_argument("--base-calculation-operation-id", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--extension-output", type=Path)
    return parser


def _parse_signers(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        authority_id, separator, raw_path = value.partition("=")
        if not separator or not authority_id.strip() or not raw_path.strip():
            raise ValueError("--signer must use AUTHORITY_ID=PRIVATE_KEY_FILE")
        if authority_id in result:
            raise ValueError(f"duplicate signer authority ID: {authority_id}")
        result[authority_id] = Path(raw_path)
    return result


def _require_operation_id(value: str, *, option: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{option} must be a 64-character lowercase hex operation ID")
    return value


def main() -> int:
    args = _parser().parse_args()
    if args.effective_epoch < 0:
        raise ValueError("--effective-epoch must be non-negative")
    base_calculation_operation_id = _require_operation_id(
        args.base_calculation_operation_id,
        option="--base-calculation-operation-id",
    )
    base_approval = DevelopmentRewardActivationApproval.model_validate_json(
        args.base_approval.read_text(encoding="utf-8-sig")
    )
    signer_paths = _parse_signers(args.signer)
    authority_by_id = {item.authority_id: item for item in base_approval.eligible_authorities}
    unknown = set(signer_paths) - set(authority_by_id)
    if unknown:
        raise ValueError(f"signer authority is not in base approval: {sorted(unknown)}")
    if len(signer_paths) < base_approval.quorum_threshold:
        raise ValueError("scope extension signer quorum is not met")

    operation_types = sorted(
        {
            item.strip()
            for item in (args.operation_types or ["DEVELOPMENT_REWARD_PAY_MATURITY"])
            if item.strip()
        }
    )
    if not operation_types:
        raise ValueError("at least one operation type is required")
    unsigned = build_development_reward_activation_scope_extension(
        base_approval=base_approval,
        effective_epoch=args.effective_epoch,
        additional_operation_types=operation_types,
        approvals=[],
    )
    approvals: list[DevelopmentRewardApprovalSignature] = []
    for authority_id in sorted(signer_paths):
        private_key = load_protocol_authority_private_key(signer_paths[authority_id])
        public_key = "ed25519:" + private_key.public_key().public_bytes_raw().hex()
        if public_key != authority_by_id[authority_id].public_key:
            raise ValueError(f"private key does not match base approval for {authority_id}")
        signature = private_key.sign(
            activation_scope_extension_authorization_payload(
                extension_id=unsigned.extension_id,
                base_activation_id=unsigned.base_activation_id,
                base_approval_hash=unsigned.base_approval_hash,
                policy_hash=unsigned.policy_hash,
                base_effective_epoch=unsigned.base_effective_epoch,
                effective_epoch=unsigned.effective_epoch,
                base_authorized_operation_types=unsigned.base_authorized_operation_types,
                additional_operation_types=unsigned.additional_operation_types,
                eligible_authorities=unsigned.eligible_authorities,
                quorum_threshold=unsigned.quorum_threshold,
                authority_id=authority_id,
                economic_effect_profile=unsigned.economic_effect_profile,
            )
        )
        approvals.append(
            DevelopmentRewardApprovalSignature(
                authority_id=authority_id,
                signature="ed25519:" + signature.hex(),
                approval_note="controlled-localnet ECO-0007 maturity scope extension",
            )
        )
    extension = build_development_reward_activation_scope_extension(
        base_approval=base_approval,
        effective_epoch=args.effective_epoch,
        additional_operation_types=operation_types,
        approvals=approvals,
    )
    envelope = build_development_reward_activation_scope_extension_operation(
        base_approval=base_approval,
        extension=extension,
        base_calculation_operation_id=base_calculation_operation_id,
        created_at=args.created_at,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.extension_output is not None:
        args.extension_output.parent.mkdir(parents=True, exist_ok=True)
        args.extension_output.write_text(
            json.dumps(extension.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "status": "CREATED",
                "operation_id": envelope.operation_id,
                "extension_id": extension.extension_id,
                "extension_hash": extension.extension_hash,
                "base_activation_id": extension.base_activation_id,
                "additional_operation_types": extension.additional_operation_types,
                "effective_epoch": extension.effective_epoch,
                "output": str(args.output),
                "broadcast": False,
                "private_keys_exported": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        raise SystemExit(2) from error
