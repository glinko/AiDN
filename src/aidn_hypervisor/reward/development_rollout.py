"""Signed rollout limits for the ECO-0007 development reward path."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from aidn_hypervisor.reward.development_distribution import DevelopmentRewardCalculation

DEVELOPMENT_REWARD_ROLLOUT_VERSION = "eco-0007-rollout.v1"


def _hash_payload(domain: str, payload: Any) -> str:
    encoded = json.dumps(
        {"domain": domain, "payload": payload},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class DevelopmentRewardRolloutProfile(BaseModel, frozen=True):
    """A bounded, future-effective reward rollout policy."""

    rollout_version: str = DEVELOPMENT_REWARD_ROLLOUT_VERSION
    rollout_id: str = Field(min_length=1)
    effective_epoch: int = Field(ge=0)
    max_epoch_reward_q_atoms: int = Field(gt=0)
    max_contributions: int = Field(gt=0)
    max_contributor_reward_q_atoms: int | None = Field(default=None, gt=0)
    state: Literal["CAP_LIMITED"] = "CAP_LIMITED"
    profile_hash: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_integrity(self) -> DevelopmentRewardRolloutProfile:
        if self.rollout_version != DEVELOPMENT_REWARD_ROLLOUT_VERSION:
            raise ValueError("DEVELOPMENT_REWARD_ROLLOUT_VERSION_INVALID")
        if self.state != "CAP_LIMITED":
            raise ValueError("DEVELOPMENT_REWARD_ROLLOUT_STATE_INVALID")
        expected_id = development_reward_rollout_id(
            effective_epoch=self.effective_epoch,
            max_epoch_reward_q_atoms=self.max_epoch_reward_q_atoms,
            max_contributions=self.max_contributions,
            max_contributor_reward_q_atoms=self.max_contributor_reward_q_atoms,
        )
        if self.rollout_id != expected_id:
            raise ValueError("DEVELOPMENT_REWARD_ROLLOUT_ID_INVALID")
        if self.profile_hash != development_reward_rollout_profile_hash(self):
            raise ValueError("DEVELOPMENT_REWARD_ROLLOUT_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"profile_hash"})

    def verify_integrity(self) -> bool:
        return self.profile_hash == development_reward_rollout_profile_hash(self)


def development_reward_rollout_id(
    *,
    effective_epoch: int,
    max_epoch_reward_q_atoms: int,
    max_contributions: int,
    max_contributor_reward_q_atoms: int | None,
) -> str:
    return _hash_payload(
        "aidn.eco-0007.rollout-id.v1",
        {
            "rollout_version": DEVELOPMENT_REWARD_ROLLOUT_VERSION,
            "effective_epoch": effective_epoch,
            "max_epoch_reward_q_atoms": max_epoch_reward_q_atoms,
            "max_contributions": max_contributions,
            "max_contributor_reward_q_atoms": max_contributor_reward_q_atoms,
        },
    )


def development_reward_rollout_profile_hash(
    profile: DevelopmentRewardRolloutProfile,
) -> str:
    return _hash_payload(
        "aidn.eco-0007.rollout-profile.v1",
        profile.unsigned_payload(),
    )


def build_development_reward_rollout_profile(
    *,
    effective_epoch: int,
    max_epoch_reward_q_atoms: int,
    max_contributions: int,
    max_contributor_reward_q_atoms: int | None = None,
) -> DevelopmentRewardRolloutProfile:
    payload = {
        "rollout_version": DEVELOPMENT_REWARD_ROLLOUT_VERSION,
        "rollout_id": development_reward_rollout_id(
            effective_epoch=effective_epoch,
            max_epoch_reward_q_atoms=max_epoch_reward_q_atoms,
            max_contributions=max_contributions,
            max_contributor_reward_q_atoms=max_contributor_reward_q_atoms,
        ),
        "effective_epoch": effective_epoch,
        "max_epoch_reward_q_atoms": max_epoch_reward_q_atoms,
        "max_contributions": max_contributions,
        "max_contributor_reward_q_atoms": max_contributor_reward_q_atoms,
        "state": "CAP_LIMITED",
    }
    return DevelopmentRewardRolloutProfile(
        **payload,
        profile_hash=development_reward_rollout_profile_hash(
            DevelopmentRewardRolloutProfile.model_construct(
                **payload,
                profile_hash="pending",
            )
        ),
    )


def validate_development_reward_rollout(
    calculation: DevelopmentRewardCalculation,
    profile: DevelopmentRewardRolloutProfile | None,
) -> None:
    """Reject a calculation that exceeds its signed rollout boundary."""

    if profile is None or calculation.epoch < profile.effective_epoch:
        return
    if calculation.accepted_gross_reward_q_atoms > profile.max_epoch_reward_q_atoms:
        raise ValueError("DEVELOPMENT_REWARD_ROLLOUT_EPOCH_CAP_EXCEEDED")
    if len(calculation.allocations) > profile.max_contributions:
        raise ValueError("DEVELOPMENT_REWARD_ROLLOUT_CONTRIBUTION_COUNT_EXCEEDED")
    if profile.max_contributor_reward_q_atoms is None:
        return

    contributor_totals: dict[str, int] = {}
    for allocation in calculation.allocations:
        for role_reward in allocation.role_rewards:
            contributor_totals[role_reward.contributor_id] = (
                contributor_totals.get(role_reward.contributor_id, 0)
                + role_reward.accepted_gross_q_atoms
            )
    if any(
        amount > profile.max_contributor_reward_q_atoms
        for amount in contributor_totals.values()
    ):
        raise ValueError("DEVELOPMENT_REWARD_ROLLOUT_CONTRIBUTOR_CAP_EXCEEDED")


__all__ = [
    "DEVELOPMENT_REWARD_ROLLOUT_VERSION",
    "DevelopmentRewardRolloutProfile",
    "build_development_reward_rollout_profile",
    "development_reward_rollout_id",
    "development_reward_rollout_profile_hash",
    "validate_development_reward_rollout",
]
