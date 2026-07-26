"""Registry Rewards + Participation (RFC-0061 §§63–68)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# RewardEntry / PenaltyEntry
# ---------------------------------------------------------------------------

class RewardEntry(BaseModel, frozen=True):
    """Single reward entry."""

    peer_id: str
    reward_type: str  # storage | serving | verification | sync
    amount: float = 0.0
    epoch: int = 0
    reason: str = ""
    recorded_at: float = 0.0


class PenaltyEntry(BaseModel, frozen=True):
    """Single penalty entry."""

    peer_id: str
    penalty_type: str  # incomplete | stale | inconsistent | unresponsive
    amount: float = 0.0
    epoch: int = 0
    reason: str = ""
    recorded_at: float = 0.0


# ---------------------------------------------------------------------------
# ParticipantLedger
# ---------------------------------------------------------------------------

class ParticipantLedger:
    """
    RFC-0061 §65 — Track rewards and penalties per participant.
    """

    def __init__(self) -> None:
        self._rewards: dict[str, list[RewardEntry]] = {}
        self._penalties: dict[str, list[PenaltyEntry]] = {}

    def add_reward(self, entry: RewardEntry) -> None:
        self._rewards.setdefault(entry.peer_id, []).append(entry)

    def add_penalty(self, entry: PenaltyEntry) -> None:
        self._penalties.setdefault(entry.peer_id, []).append(entry)

    def get_rewards(self, peer_id: str) -> list[RewardEntry]:
        return list(self._rewards.get(peer_id, []))

    def get_penalties(self, peer_id: str) -> list[PenaltyEntry]:
        return list(self._penalties.get(peer_id, []))

    def get_balance(self, peer_id: str) -> float:
        """Net balance (rewards − penalties)."""
        rewards = sum(r.amount for r in self._rewards.get(peer_id, []))
        penalties = sum(p.amount for p in self._penalties.get(peer_id, []))
        return rewards - penalties

    def get_total_rewards(self, peer_id: str) -> float:
        return sum(r.amount for r in self._rewards.get(peer_id, []))

    def get_total_penalties(self, peer_id: str) -> float:
        return sum(p.amount for p in self._penalties.get(peer_id, []))

    def get_participants(self) -> list[str]:
        all_ids = set(self._rewards.keys()) | set(self._penalties.keys())
        return sorted(all_ids)

    def get_epoch_rewards(self, peer_id: str, epoch: int) -> list[RewardEntry]:
        return [r for r in self._rewards.get(peer_id, []) if r.epoch == epoch]

    def clear(self) -> None:
        self._rewards.clear()
        self._penalties.clear()


# ---------------------------------------------------------------------------
# RewardConfig
# ---------------------------------------------------------------------------

class RewardConfig(BaseModel):
    """Configuration for reward/penalty rates."""

    storage_rate_per_object: float = 0.01
    serving_rate_per_object: float = 0.02
    verification_rate_per_object: float = 0.005
    sync_rate_per_epoch: float = 0.1
    incomplete_penalty_rate: float = 1.0
    min_completeness_threshold: float = 0.95
    stale_penalty_per_epoch: float = 0.05
    max_lag_epochs: int = 3
    inconsistent_penalty_per_discrepancy: float = 0.1


# ---------------------------------------------------------------------------
# SettlementResult
# ---------------------------------------------------------------------------

class SettlementResult(BaseModel, frozen=True):
    """Result of epoch settlement."""

    peer_id: str
    epoch: int
    total_rewards: float
    total_penalties: float
    net_balance: float
    settled_at: float = 0.0


# ---------------------------------------------------------------------------
# RewardEngine
# ---------------------------------------------------------------------------

class RewardEngine:
    """
    RFC-0061 §§63–68 — Registry participation rewards engine.

    Awards rewards for storage, serving, verification, and sync
    contributions.  Applies penalties for incomplete, stale, or
    inconsistent state.
    """

    def __init__(self) -> None:
        self._ledger = ParticipantLedger()
        self._config = RewardConfig()

    @property
    def ledger(self) -> ParticipantLedger:
        return self._ledger

    # -- rewards --------------------------------------------------------

    def reward_storage(
        self,
        *,
        peer_id: str,
        objects_stored: int,
        epoch: int,
    ) -> RewardEntry:
        """Reward for storing registry objects."""
        amount = objects_stored * self._config.storage_rate_per_object
        entry = RewardEntry(
            peer_id=peer_id,
            reward_type="storage",
            amount=amount,
            epoch=epoch,
            reason=f"Stored {objects_stored} objects",
            recorded_at=time.time(),
        )
        self._ledger.add_reward(entry)
        return entry

    def reward_serving(
        self,
        *,
        peer_id: str,
        objects_served: int,
        epoch: int,
    ) -> RewardEntry:
        """Reward for serving objects to other peers."""
        amount = objects_served * self._config.serving_rate_per_object
        entry = RewardEntry(
            peer_id=peer_id,
            reward_type="serving",
            amount=amount,
            epoch=epoch,
            reason=f"Served {objects_served} objects",
            recorded_at=time.time(),
        )
        self._ledger.add_reward(entry)
        return entry

    def reward_verification(
        self,
        *,
        peer_id: str,
        objects_verified: int,
        epoch: int,
    ) -> RewardEntry:
        """Reward for verifying object integrity."""
        amount = objects_verified * self._config.verification_rate_per_object
        entry = RewardEntry(
            peer_id=peer_id,
            reward_type="verification",
            amount=amount,
            epoch=epoch,
            reason=f"Verified {objects_verified} objects",
            recorded_at=time.time(),
        )
        self._ledger.add_reward(entry)
        return entry

    def reward_sync(
        self,
        *,
        peer_id: str,
        epochs_synced: int,
        epoch: int,
    ) -> RewardEntry:
        """Reward for synchronization contributions."""
        amount = epochs_synced * self._config.sync_rate_per_epoch
        entry = RewardEntry(
            peer_id=peer_id,
            reward_type="sync",
            amount=amount,
            epoch=epoch,
            reason=f"Synced {epochs_synced} epochs",
            recorded_at=time.time(),
        )
        self._ledger.add_reward(entry)
        return entry

    # -- penalties ------------------------------------------------------

    def penalty_incomplete(
        self,
        *,
        peer_id: str,
        completeness: float,
        epoch: int,
    ) -> PenaltyEntry:
        """Penalty for incomplete registry state."""
        if completeness >= self._config.min_completeness_threshold:
            return PenaltyEntry(
                peer_id=peer_id,
                penalty_type="incomplete",
                amount=0.0,
                epoch=epoch,
                reason="Completeness above threshold",
                recorded_at=time.time(),
            )

        gap = 1.0 - completeness
        amount = gap * self._config.incomplete_penalty_rate
        entry = PenaltyEntry(
            peer_id=peer_id,
            penalty_type="incomplete",
            amount=amount,
            epoch=epoch,
            reason=(
                f"Completeness {completeness:.2f} below "
                f"{self._config.min_completeness_threshold}"
            ),
            recorded_at=time.time(),
        )
        self._ledger.add_penalty(entry)
        return entry

    def penalty_stale(
        self,
        *,
        peer_id: str,
        epochs_behind: int,
        epoch: int,
    ) -> PenaltyEntry:
        """Penalty for stale registry state."""
        if epochs_behind <= self._config.max_lag_epochs:
            return PenaltyEntry(
                peer_id=peer_id,
                penalty_type="stale",
                amount=0.0,
                epoch=epoch,
                reason="Within acceptable lag",
                recorded_at=time.time(),
            )

        excess = epochs_behind - self._config.max_lag_epochs
        amount = excess * self._config.stale_penalty_per_epoch
        entry = PenaltyEntry(
            peer_id=peer_id,
            penalty_type="stale",
            amount=amount,
            epoch=epoch,
            reason=(
                f"{epochs_behind} epochs behind (max "
                f"{self._config.max_lag_epochs})"
            ),
            recorded_at=time.time(),
        )
        self._ledger.add_penalty(entry)
        return entry

    def penalty_inconsistent(
        self,
        *,
        peer_id: str,
        discrepancy_count: int,
        epoch: int,
    ) -> PenaltyEntry:
        """Penalty for inconsistent registry state."""
        amount = (
            discrepancy_count
            * self._config.inconsistent_penalty_per_discrepancy
        )
        entry = PenaltyEntry(
            peer_id=peer_id,
            penalty_type="inconsistent",
            amount=amount,
            epoch=epoch,
            reason=f"{discrepancy_count} discrepancies found",
            recorded_at=time.time(),
        )
        self._ledger.add_penalty(entry)
        return entry

    # -- settlement -----------------------------------------------------

    def epoch_settlement(
        self,
        *,
        peer_id: str,
        epoch: int,
        objects_stored: int = 0,
        objects_served: int = 0,
        objects_verified: int = 0,
        epochs_synced: int = 0,
        completeness: float = 1.0,
        epochs_behind: int = 0,
        discrepancy_count: int = 0,
    ) -> SettlementResult:
        """
        RFC-0061 §68 — Full epoch settlement for a participant.
        """
        # Calculate rewards
        self.reward_storage(
            peer_id=peer_id,
            objects_stored=objects_stored,
            epoch=epoch,
        )
        self.reward_serving(
            peer_id=peer_id,
            objects_served=objects_served,
            epoch=epoch,
        )
        self.reward_verification(
            peer_id=peer_id,
            objects_verified=objects_verified,
            epoch=epoch,
        )
        self.reward_sync(
            peer_id=peer_id,
            epochs_synced=epochs_synced,
            epoch=epoch,
        )

        # Calculate penalties
        self.penalty_incomplete(
            peer_id=peer_id,
            completeness=completeness,
            epoch=epoch,
        )
        self.penalty_stale(
            peer_id=peer_id,
            epochs_behind=epochs_behind,
            epoch=epoch,
        )
        if discrepancy_count > 0:
            self.penalty_inconsistent(
                peer_id=peer_id,
                discrepancy_count=discrepancy_count,
                epoch=epoch,
            )

        balance = self._ledger.get_balance(peer_id)
        total_rewards = self._ledger.get_total_rewards(peer_id)
        total_penalties = self._ledger.get_total_penalties(peer_id)

        return SettlementResult(
            peer_id=peer_id,
            epoch=epoch,
            total_rewards=total_rewards,
            total_penalties=total_penalties,
            net_balance=balance,
            settled_at=time.time(),
        )
