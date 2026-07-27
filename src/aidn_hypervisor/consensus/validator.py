"""RFC-0047 §17-§22, ECO-0006 — Validator Set + Stake Management."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


# ── Enumerations ─────────────────────────────────────────────────────


class ValidatorStatus(str, Enum):
    """Validator lifecycle states."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    DOWNTIME = "downtime"
    SUSPENDED = "suspended"
    UNBONDING = "unbonding"


class DowntimeType(str, Enum):
    """Classification of validator downtime."""

    ORDINARY = "ordinary"
    PERSISTENT = "persistent"
    ABANDONMENT = "abandonment"


class Consequence(str, Enum):
    """Applied consequence for downtime."""

    NONE = "none"
    WARNING = "warning"
    SUSPENSION = "suspension"
    UNBONDING = "unbonding"


# ── Pydantic models (frozen / immutable) ────────────────────────────


class ConsensusValidator(BaseModel, frozen=True):
    """RFC-0047 §17 — Validator registration and state."""

    node_id: str
    operator_id: str
    consensus_address: str  # SHA-256 of node_id
    stake: int = Field(ge=0)  # in q-atoms
    voting_power: int = Field(ge=0)
    status: ValidatorStatus = ValidatorStatus.CANDIDATE
    registered_at: str  # ISO-8601
    last_active_at: str | None = None
    downtime_count: int = 0
    consequence: Consequence = Consequence.NONE

    @property
    def is_active(self) -> bool:
        return self.status == ValidatorStatus.ACTIVE

    @property
    def is_eligible(self) -> bool:
        return self.status in (
            ValidatorStatus.CANDIDATE,
            ValidatorStatus.ACTIVE,
            ValidatorStatus.DOWNTIME,
        )


class StakeRecord(BaseModel, frozen=True):
    """Records a stake operation."""

    validator_node_id: str
    amount: int = Field(ge=1)
    action: str  # "lock" | "unlock" | "slash"
    epoch: int
    timestamp: str  # ISO-8601
    reason: str | None = None


class EpochValidatorSet(BaseModel, frozen=True):
    """Snapshot of the active validator set for an epoch."""

    epoch: int
    validators: list[ConsensusValidator]
    total_stake: int
    total_voting_power: int
    start_block: int
    snapshot_time: str  # ISO-8601


# ── Validator Set Manager ───────────────────────────────────────────


@dataclass
class ValidatorSetConfig:
    """Configuration for validator set management."""

    target_validator_count: int = 100
    min_stake: int = 100_000  # q-atoms
    unbonding_epochs: int = 5
    downtime_warning_threshold: int = 3
    downtime_suspension_threshold: int = 10
    downtime_unbonding_threshold: int = 20
    participation_rate_window: int = 100  # blocks


class ValidatorSetManager:
    """
    RFC-0047 §17-§22, ECO-0006 — Validator set management.

    Handles validator registration, stake management, active set
    selection, and participation tracking.
    """

    def __init__(self, config: ValidatorSetConfig | None = None):
        self.config = config or ValidatorSetConfig()
        self._validators: dict[str, ConsensusValidator] = {}
        self._stake_records: list[StakeRecord] = []
        self._participation: dict[str, list[int]] = {}  # node_id -> [block_heights]
        self._epoch_sets: dict[int, EpochValidatorSet] = {}
        self._current_epoch: int = 0
        self._block_height: int = 0

    # ── Registration ──────────────────────────────────────────────

    def register_candidate(
        self,
        *,
        node_id: str,
        operator_id: str,
        stake: int,
        timestamp: str,
    ) -> ConsensusValidator | None:
        """Register a new validator candidate.

        Returns None if stake is below minimum or node_id already exists.
        """
        if stake < self.config.min_stake:
            return None
        if node_id in self._validators:
            return None

        validator = ConsensusValidator(
            node_id=node_id,
            operator_id=operator_id,
            consensus_address=self._compute_address(node_id),
            stake=stake,
            voting_power=stake,  # equal voting power = stake (MVP)
            status=ValidatorStatus.CANDIDATE,
            registered_at=timestamp,
            last_active_at=timestamp,
        )
        self._validators[node_id] = validator
        return validator

    # ── Stake management ──────────────────────────────────────────

    def lock_stake(
        self, *, node_id: str, amount: int, epoch: int, timestamp: str
    ) -> StakeRecord | None:
        """Lock additional stake for a validator."""
        validator = self._validators.get(node_id)
        if not validator:
            return None

        record = StakeRecord(
            validator_node_id=node_id,
            amount=amount,
            action="lock",
            epoch=epoch,
            timestamp=timestamp,
        )
        self._stake_records.append(record)

        # Update validator stake
        updated = validator.model_copy(
            update={
                "stake": validator.stake + amount,
                "voting_power": validator.stake + amount,
            }
        )
        self._validators[node_id] = updated
        return record

    def unlock_stake(
        self, *, node_id: str, amount: int, epoch: int, timestamp: str
    ) -> StakeRecord | None:
        """Unlock stake (begins unbonding process)."""
        validator = self._validators.get(node_id)
        if not validator or validator.stake < amount:
            return None

        record = StakeRecord(
            validator_node_id=node_id,
            amount=amount,
            action="unlock",
            epoch=epoch,
            timestamp=timestamp,
        )
        self._stake_records.append(record)

        new_stake = validator.stake - amount
        new_status = (
            ValidatorStatus.UNBONDING
            if new_stake < self.config.min_stake
            else validator.status
        )

        updated = validator.model_copy(
            update={
                "stake": new_stake,
                "voting_power": new_stake,
                "status": new_status,
            }
        )
        self._validators[node_id] = updated
        return record

    def slash_stake(
        self, *, node_id: str, amount: int, epoch: int, timestamp: str, reason: str
    ) -> StakeRecord | None:
        """Slash stake for misconduct."""
        validator = self._validators.get(node_id)
        if not validator:
            return None

        actual = min(amount, validator.stake)
        record = StakeRecord(
            validator_node_id=node_id,
            amount=actual,
            action="slash",
            epoch=epoch,
            timestamp=timestamp,
            reason=reason,
        )
        self._stake_records.append(record)

        new_stake = validator.stake - actual
        updated = validator.model_copy(
            update={
                "stake": new_stake,
                "voting_power": new_stake,
            }
        )
        self._validators[node_id] = updated
        return record

    # ── Active set selection ──────────────────────────────────────

    def select_active_set(
        self, *, epoch: int, timestamp: str
    ) -> EpochValidatorSet:
        """Select the active validator set for an epoch."""
        self._current_epoch = epoch

        eligible = [
            v
            for v in self._validators.values()
            if v.is_eligible and v.stake >= self.config.min_stake
        ]

        # Sort by stake descending, take top N
        eligible.sort(key=lambda v: v.voting_power, reverse=True)
        selected = eligible[: self.config.target_validator_count]

        # Update status to ACTIVE
        for v in selected:
            updated = v.model_copy(
                update={
                    "status": ValidatorStatus.ACTIVE,
                    "last_active_at": timestamp,
                }
            )
            self._validators[v.node_id] = updated

        total_stake = sum(v.stake for v in selected)
        total_vp = sum(v.voting_power for v in selected)

        epoch_set = EpochValidatorSet(
            epoch=epoch,
            validators=selected,
            total_stake=total_stake,
            total_voting_power=total_vp,
            start_block=epoch * 100,  # placeholder
            snapshot_time=timestamp,
        )
        self._epoch_sets[epoch] = epoch_set
        return epoch_set

    # ── Participation tracking ────────────────────────────────────

    def record_participation(
        self, *, node_id: str, block_height: int, signed: bool = True
    ) -> None:
        """Record validator participation in a block."""
        if node_id not in self._participation:
            self._participation[node_id] = []
        self._participation[node_id].append(block_height)
        self._block_height = max(self._block_height, block_height)

        # Update last_active_at for the validator
        validator = self._validators.get(node_id)
        if validator and signed:
            updated = validator.model_copy(
                update={"last_active_at": self._timestamp_for_block(block_height)}
            )
            self._validators[node_id] = updated

    def record_miss(self, *, node_id: str, block_height: int) -> None:
        """Record validator miss (did not sign a block)."""
        self._block_height = max(self._block_height, block_height)

        validator = self._validators.get(node_id)
        if not validator:
            return

        new_count = validator.downtime_count + 1

        # Determine new status based on downtime count
        new_status = validator.status
        new_consequence = validator.consequence

        if new_count >= self.config.downtime_unbonding_threshold:
            new_status = ValidatorStatus.UNBONDING
            new_consequence = Consequence.UNBONDING
        elif new_count >= self.config.downtime_suspension_threshold:
            new_status = ValidatorStatus.SUSPENDED
            new_consequence = Consequence.SUSPENSION
        elif new_count >= self.config.downtime_warning_threshold:
            new_status = ValidatorStatus.DOWNTIME
            new_consequence = Consequence.WARNING
        else:
            new_consequence = Consequence.NONE

        updated = validator.model_copy(
            update={
                "downtime_count": new_count,
                "status": new_status,
                "consequence": new_consequence,
            }
        )
        self._validators[node_id] = updated

    def get_participation_rate(
        self, *, node_id: str, window: int | None = None
    ) -> float:
        """Calculate participation rate over a window."""
        window = window or self.config.participation_rate_window
        blocks = self._participation.get(node_id, [])
        if not blocks:
            return 0.0

        current_height = self._block_height
        if current_height == 0:
            return 1.0 if len(blocks) > 0 else 0.0

        recent = [b for b in blocks if b > current_height - window]
        return len(recent) / window if window > 0 else 0.0

    # ── Downtime classification ───────────────────────────────────

    def classify_downtime(self, *, node_id: str) -> DowntimeType:
        """Classify validator downtime based on miss count."""
        validator = self._validators.get(node_id)
        if not validator:
            return DowntimeType.ABANDONMENT

        count = validator.downtime_count
        if count < self.config.downtime_warning_threshold:
            return DowntimeType.ORDINARY
        elif count < self.config.downtime_unbonding_threshold:
            return DowntimeType.PERSISTENT
        else:
            return DowntimeType.ABANDONMENT

    def apply_consequence(self, *, node_id: str) -> Consequence:
        """Apply consequence based on downtime classification."""
        dtype = self.classify_downtime(node_id=node_id)

        if dtype == DowntimeType.ORDINARY:
            return Consequence.WARNING
        elif dtype == DowntimeType.PERSISTENT:
            return Consequence.SUSPENSION
        else:
            return Consequence.UNBONDING

    # ── Reward eligibility ────────────────────────────────────────

    def is_reward_eligible(self, *, node_id: str) -> bool:
        """Check if a validator is eligible for consensus rewards."""
        validator = self._validators.get(node_id)
        if not validator:
            return False
        return validator.status in (
            ValidatorStatus.ACTIVE,
            ValidatorStatus.CANDIDATE,
        )

    # ── Queries ───────────────────────────────────────────────────

    def get_validator(self, node_id: str) -> ConsensusValidator | None:
        return self._validators.get(node_id)

    def get_active_set(self, epoch: int) -> EpochValidatorSet | None:
        return self._epoch_sets.get(epoch)

    def get_all_validators(self) -> list[ConsensusValidator]:
        return list(self._validators.values())

    def get_stake_records(self, node_id: str | None = None) -> list[StakeRecord]:
        if node_id:
            return [
                r for r in self._stake_records if r.validator_node_id == node_id
            ]
        return list(self._stake_records)

    def get_current_epoch(self) -> int:
        return self._current_epoch

    def get_block_height(self) -> int:
        return self._block_height

    # ── Internal ──────────────────────────────────────────────────

    @staticmethod
    def _compute_address(node_id: str) -> str:
        return hashlib.sha256(node_id.encode()).hexdigest()

    @staticmethod
    def _timestamp_for_block(block_height: int) -> str:
        """Return a deterministic timestamp for a block height."""
        return datetime.fromtimestamp(block_height, tz=UTC).isoformat()
