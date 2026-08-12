#!/usr/bin/env python3
"""Build a hash-bound production ECO-0007 reward profile.

This command does not create keys, mint Q, or submit a transaction. The input
activation approval must already carry the Governance signatures required by
the active policy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aidn_hypervisor.reward.development_activation import DevelopmentRewardActivationApproval
from aidn_hypervisor.reward.development_distribution import DevelopmentRewardPolicy
from aidn_hypervisor.reward.development_production import build_development_reward_production_profile


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network-id", required=True)
    parser.add_argument("--chain-id", required=True)
    parser.add_argument("--effective-epoch", required=True, type=int)
    parser.add_argument("--activation-approval", required=True, type=Path)
    parser.add_argument("--policy", type=Path, help="Optional JSON DevelopmentRewardPolicy; defaults to launch policy")
    parser.add_argument("--max-batch-q-atoms", required=True, type=int)
    parser.add_argument("--max-contributions", required=True, type=int)
    parser.add_argument("--max-operations", required=True, type=int)
    parser.add_argument("--pool-id", default="GENERAL_DEVELOPMENT")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    approval = DevelopmentRewardActivationApproval.model_validate_json(
        args.activation_approval.read_text(encoding="utf-8")
    )
    policy = (
        DevelopmentRewardPolicy.model_validate_json(args.policy.read_text(encoding="utf-8"))
        if args.policy is not None
        else DevelopmentRewardPolicy()
    )
    profile = build_development_reward_production_profile(
        network_id=args.network_id,
        chain_id=args.chain_id,
        effective_epoch=args.effective_epoch,
        activation_approval=approval,
        policy=policy,
        max_batch_q_atoms=args.max_batch_q_atoms,
        max_contributions=args.max_contributions,
        max_operations=args.max_operations,
        pool_id=args.pool_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(profile.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {"profile_id": profile.profile_id, "profile_hash": profile.profile_hash, "output": str(args.output)},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
