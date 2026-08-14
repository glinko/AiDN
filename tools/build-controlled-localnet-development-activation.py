#!/usr/bin/env python3
"""Build a bounded ECO-0007 activation approval for the controlled localnet.

The controlled localnet may reuse its published protocol authority set for a
temporary development-reward gate. This command makes that reuse explicit,
checks every external seed against the public policy, and writes only public
signatures. It never broadcasts, mints Q, or creates a Ledger operation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aidn_hypervisor.consensus.epoch_transition import (  # noqa: E402
    load_protocol_authority_private_key,
)
from aidn_hypervisor.consensus.protocol_authority import (  # noqa: E402
    ProtocolAuthorityPolicy,
    normalize_ed25519_public_key,
)
from aidn_hypervisor.reward.development_activation import (  # noqa: E402
    DevelopmentRewardApprovalSignature,
    DevelopmentRewardAuthority,
    activation_authorization_payload,
    build_development_reward_activation_approval,
    development_reward_policy_hash,
    verify_development_reward_activation_approval,
)
from aidn_hypervisor.reward.development_distribution import (  # noqa: E402
    Q_ATOMS_PER_Q,
    DevelopmentRewardPolicy,
)
from aidn_hypervisor.reward.development_rollout import (  # noqa: E402
    build_development_reward_rollout_profile,
)

_PRODUCTION_OPERATIONS = [
    "DEVELOPMENT_REWARD_CALCULATE",
    "DEVELOPMENT_POOL_ALLOCATE",
    "DEVELOPMENT_REWARD_RESERVE",
    "DEVELOPMENT_REWARD_PAY_IMMEDIATE",
    "DEVELOPMENT_REWARD_PAY_MATURITY",
    "DEVELOPMENT_REWARD_MARK_UNCLAIMED",
]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", required=True, type=Path, help="public protocol authority policy")
    parser.add_argument(
        "--signer",
        action="append",
        required=True,
        metavar="AUTHORITY_ID=PRIVATE_KEY_FILE",
        help="repeat for each authority signer; seeds stay outside the repository",
    )
    parser.add_argument("--effective-epoch", required=True, type=int)
    parser.add_argument("--max-epoch-reward-q-atoms", type=int, default=250 * Q_ATOMS_PER_Q)
    parser.add_argument("--max-contributions", type=int, default=8)
    parser.add_argument("--max-contributor-reward-q-atoms", type=int, default=50 * Q_ATOMS_PER_Q)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def _object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


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


def main() -> int:
    args = _parser().parse_args()
    if args.effective_epoch < 0:
        raise ValueError("--effective-epoch must be non-negative")
    if args.max_epoch_reward_q_atoms <= 0:
        raise ValueError("--max-epoch-reward-q-atoms must be positive")
    if args.max_contributions <= 0:
        raise ValueError("--max-contributions must be positive")
    if args.max_contributor_reward_q_atoms <= 0:
        raise ValueError("--max-contributor-reward-q-atoms must be positive")

    protocol_policy = ProtocolAuthorityPolicy.from_mapping(_object(args.policy))
    signer_paths = _parse_signers(args.signer)
    unknown = set(signer_paths) - {authority_id for authority_id, _ in protocol_policy.authorities}
    if unknown:
        raise ValueError(f"signer authority is not in public policy: {sorted(unknown)}")
    if len(signer_paths) < protocol_policy.threshold:
        raise ValueError("controlled localnet activation signer quorum is not met")

    authorities = [
        DevelopmentRewardAuthority(
            authority_id=authority_id,
            public_key=normalize_ed25519_public_key(public_key),
        )
        for authority_id, public_key in protocol_policy.authorities
    ]
    development_policy = DevelopmentRewardPolicy()
    policy_hash = development_reward_policy_hash(development_policy)
    rollout = build_development_reward_rollout_profile(
        effective_epoch=args.effective_epoch,
        max_epoch_reward_q_atoms=args.max_epoch_reward_q_atoms,
        max_contributions=args.max_contributions,
        max_contributor_reward_q_atoms=args.max_contributor_reward_q_atoms,
    )
    unsigned = build_development_reward_activation_approval(
        policy_hash=policy_hash,
        effective_epoch=args.effective_epoch,
        eligible_authorities=authorities,
        quorum_threshold=protocol_policy.threshold,
        approvals=[],
        authorized_operation_types=_PRODUCTION_OPERATIONS,
        economic_effect_profile="DEVELOPMENT_PAYMENTS",
        rollout_profile=rollout,
    )

    approvals: list[DevelopmentRewardApprovalSignature] = []
    authority_by_id = {item.authority_id: item for item in authorities}
    for authority_id in sorted(signer_paths):
        private_key = load_protocol_authority_private_key(signer_paths[authority_id])
        public_key = normalize_ed25519_public_key(
            "ed25519:" + private_key.public_key().public_bytes_raw().hex()
        )
        if public_key != authority_by_id[authority_id].public_key:
            raise ValueError(f"private key does not match public policy for {authority_id}")
        signature = private_key.sign(
            activation_authorization_payload(
                activation_id=unsigned.activation_id,
                policy_hash=policy_hash,
                effective_epoch=args.effective_epoch,
                eligible_authorities=authorities,
                quorum_threshold=protocol_policy.threshold,
                authority_id=authority_id,
                authorized_operation_types=_PRODUCTION_OPERATIONS,
                economic_effect_profile="DEVELOPMENT_PAYMENTS",
                rollout_profile=rollout,
            )
        )
        approvals.append(
            DevelopmentRewardApprovalSignature(
                authority_id=authority_id,
                signature="ed25519:" + signature.hex(),
                approval_note="controlled-localnet development payments rollout",
            )
        )

    approval = build_development_reward_activation_approval(
        policy_hash=policy_hash,
        effective_epoch=args.effective_epoch,
        eligible_authorities=authorities,
        quorum_threshold=protocol_policy.threshold,
        approvals=approvals,
        authorized_operation_types=_PRODUCTION_OPERATIONS,
        economic_effect_profile="DEVELOPMENT_PAYMENTS",
        rollout_profile=rollout,
    )
    verify_development_reward_activation_approval(approval)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(approval.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "CREATED",
                "activation_id": approval.activation_id,
                "approval_hash": approval.approval_hash,
                "development_policy_hash": policy_hash,
                "protocol_authority_policy_hash": protocol_policy.policy_hash,
                "effective_epoch": approval.effective_epoch,
                "signer_ids": sorted(signer_paths),
                "rollout_id": rollout.rollout_id,
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
