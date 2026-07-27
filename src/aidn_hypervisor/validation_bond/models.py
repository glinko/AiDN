"""M11-S2: Validation Bond models — lock, active, recovery, forfeit lifecycle."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field

# ── Constants ────────────────────────────────────────────────────────

# ECO-0003: Validation Bond = 500Q = 500_000_000 q-atoms
VALIDATION_BOND_Q_ATOMS: int = 500_000_000

# ECO-0003 §8: Recovery rate (exponential decay)
RECOVERY_DECAY_FACTOR: float = 0.5


# ── Enums ────────────────────────────────────────────────────────────


class BondStatus(str, Enum):
    """Bond lifecycle status."""

    LOCKED = "locked"
    ACTIVE = "active"
    RECOVERING = "recovering"
    FORFEITED = "forfeited"
    RECOVERED = "recovered"


class BondEventType(str, Enum):
    """Bond event types for audit trail."""

    LOCK = "lock"
    ACTIVATE = "activate"
    RECOVER = "recover"
    FORFEIT = "forfeit"
    REFUND = "refund"


# ── Recovery / Forfeit records ──────────────────────────────────────


class BondRecoveryRecord(BaseModel, frozen=True):
    """Single recovery event (exponential decay step)."""

    recovery_id: str
    bond_id: str
    recovery_amount: int  # q-atoms recovered this step
    remaining_after: int  # q-atoms still locked after recovery
    step_number: int  # which recovery step (1-based)
    epoch: int
    timestamp: str

    @computed_field  # type: ignore[misc]
    @property
    def recovery_percentage(self) -> float:
        """Percentage of original remaining that was recovered."""
        if self.remaining_after + self.recovery_amount == 0:
            return 0.0
        return (
            self.recovery_amount
            / (self.remaining_after + self.recovery_amount)
        ) * 100.0


class BondForfeitRecord(BaseModel, frozen=True):
    """Forfeit event — bond destroyed, proceeds to recycling."""

    forfeit_id: str
    bond_id: str
    forfeited_amount: int  # q-atoms forfeited
    reason: str
    epoch: int
    timestamp: str


# ── Bond Event ──────────────────────────────────────────────────────


class BondEvent(BaseModel, frozen=True):
    """Immutable audit event for bond lifecycle."""

    event_id: str
    bond_id: str
    event_type: BondEventType
    amount_delta: int  # positive = locked more, negative = released
    metadata: dict[str, Any] = Field(default_factory=dict)
    epoch: int
    timestamp: str


# ── Validation Bond ─────────────────────────────────────────────────


class ValidationBond(BaseModel, frozen=True):
    """Core bond model. Immutable after creation; updates produce new instances."""

    bond_id: str
    endpoint_id: str
    operator_wallet: str
    initial_amount: int = Field(default=VALIDATION_BOND_Q_ATOMS)
    remaining_amount: int = Field(default=VALIDATION_BOND_Q_ATOMS)
    status: BondStatus = BondStatus.LOCKED
    created_at: str
    recovery_count: int = 0
    recovery_records: list[BondRecoveryRecord] = Field(default_factory=list)
    forfeit_records: list[BondForfeitRecord] = Field(default_factory=list)
    events: list[BondEvent] = Field(default_factory=list)

    @computed_field  # type: ignore[misc]
    @property
    def forfeited_total(self) -> int:
        """Total amount forfeited across all forfeit events."""
        return sum(r.forfeited_amount for r in self.forfeit_records)

    @computed_field  # type: ignore[misc]
    @property
    def recovered_total(self) -> int:
        """Total amount recovered (released back to operator)."""
        return sum(r.recovery_amount for r in self.recovery_records)

    @computed_field  # type: ignore[misc]
    @property
    def is_active(self) -> bool:
        """Whether the bond is in an active or recovering state."""
        return self.status in (
            BondStatus.ACTIVE,
            BondStatus.RECOVERING,
        )

    @computed_field  # type: ignore[misc]
    @property
    def is_terminal(self) -> bool:
        """Whether the bond reached a terminal state."""
        return self.status in (
            BondStatus.FORFEITED,
            BondStatus.RECOVERED,
        )

    @computed_field  # type: ignore[misc]
    @property
    def bond_health(self) -> float:
        """Ratio of remaining to initial (0.0 - 1.0)."""
        if self.initial_amount == 0:
            return 0.0
        return self.remaining_amount / self.initial_amount

    # ── State transitions ────────────────────────────────────────

    def activate(self) -> ValidationBond:
        """Transition LOCKED → ACTIVE."""
        if self.status != BondStatus.LOCKED:
            raise ValueError(
                f"Cannot activate bond in status {self.status}"
            )
        now = datetime.now(UTC).isoformat()
        event = BondEvent(
            event_id=_make_id("evt", self.bond_id, "activate"),
            bond_id=self.bond_id,
            event_type=BondEventType.ACTIVATE,
            amount_delta=0,
            epoch=0,
            timestamp=now,
        )
        return self.model_copy(
            update={
                "status": BondStatus.ACTIVE,
                "events": [*self.events, event],
            }
        )

    def start_recovery(self) -> ValidationBond:
        """Transition ACTIVE → RECOVERING."""
        if self.status not in (BondStatus.ACTIVE, BondStatus.RECOVERING):
            raise ValueError(
                f"Cannot start recovery from status {self.status}"
            )
        return self.model_copy(
            update={"status": BondStatus.RECOVERING}
        )


def _make_id(prefix: str, bond_id: str, action: str) -> str:
    """Generate a deterministic event ID."""
    raw = f"{prefix}:{bond_id}:{action}:{uuid.uuid4()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
