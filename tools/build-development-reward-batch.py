#!/usr/bin/env python3
"""Build a production-bound ECO-0007 batch from finalized evidence.

The output is an ordered consensus plan. It is intentionally not submitted by
this tool; a deployment-specific consensus service must submit the exact
envelopes and reconcile finality before the next envelope is sent.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aidn_hypervisor.contributions.service import ContributionAccountingService
from aidn_hypervisor.contributions.store import ContributionEvidenceStore
from aidn_hypervisor.reward.development_activation import DevelopmentRewardActivationApproval
from aidn_hypervisor.reward.development_contribution_service import DevelopmentContributionRewardService
from aidn_hypervisor.reward.development_distribution import DevelopmentPoolInput
from aidn_hypervisor.reward.development_preflight_quorum import (
    DEVELOPMENT_REWARD_PREFLIGHT_QUORUM_VERSION,
    DevelopmentRewardPreflightQuorum,
    build_development_reward_preflight_quorum,
)
from aidn_hypervisor.reward.development_production import (
    DevelopmentRewardProductionProfile,
    build_development_reward_production_batch,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-store", required=True, type=Path)
    parser.add_argument("--pool-input", required=True, type=Path)
    parser.add_argument("--production-profile", required=True, type=Path)
    parser.add_argument("--activation-approval", required=True, type=Path)
    parser.add_argument("--preflight-quorum", required=True, type=Path)
    parser.add_argument("--current-epoch", required=True, type=int)
    parser.add_argument("--source-epoch-transition-operation-id", required=True)
    parser.add_argument("--pool-budget-reference", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--contribution-id", action="append", dest="contribution_ids")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    profile = DevelopmentRewardProductionProfile.model_validate_json(
        args.production_profile.read_text(encoding="utf-8")
    )
    approval = DevelopmentRewardActivationApproval.model_validate_json(
        args.activation_approval.read_text(encoding="utf-8")
    )
    # PowerShell's default UTF-8 output includes a BOM on Windows.
    preflight_payload = json.loads(args.preflight_quorum.read_text(encoding="utf-8-sig"))
    if not isinstance(preflight_payload, dict):
        raise ValueError("preflight quorum input must be a JSON object")
    if preflight_payload.get("schema_version") == DEVELOPMENT_REWARD_PREFLIGHT_QUORUM_VERSION:
        preflight_quorum = DevelopmentRewardPreflightQuorum.model_validate(preflight_payload)
    else:
        preflight_quorum = build_development_reward_preflight_quorum(preflight_payload)
    pool = DevelopmentPoolInput.model_validate_json(args.pool_input.read_text(encoding="utf-8"))
    service = ContributionAccountingService(ContributionEvidenceStore(args.evidence_store))
    planner = DevelopmentContributionRewardService(service)
    preview = planner.preview(
        pool_input=pool,
        contribution_ids=args.contribution_ids,
        policy=profile.policy,
    )
    plan = planner.build_consensus_plan(
        preview,
        activation_approval=approval,
        current_epoch=args.current_epoch,
        source_epoch_transition_operation_id=args.source_epoch_transition_operation_id,
        pool_budget_reference=args.pool_budget_reference,
        created_at=args.created_at,
        require_production_authority=True,
    )
    batch = build_development_reward_production_batch(
        profile=profile,
        activation_approval=approval,
        plan=plan,
        preflight_quorum=preflight_quorum,
        source_epoch_transition_operation_id=args.source_epoch_transition_operation_id,
        pool_budget_reference=args.pool_budget_reference,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(batch.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    args.output.write_text(encoded, encoding="utf-8")
    print(
        json.dumps(
            {"batch_id": batch.batch_id, "batch_hash": batch.batch_hash, "output": str(args.output)},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
