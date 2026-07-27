"""M11-S2: Validation Bond Manager — lock, activate, recover, forfeit lifecycle."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from math import floor

from aidn_hypervisor.validation_bond.models import (
    RECOVERY_DECAY_FACTOR,
    VALIDATION_BOND_Q_ATOMS,
    BondEvent,
    BondEventType,
    BondForfeitRecord,
    BondRecoveryRecord,
    BondStatus,
    ValidationBond,
)
from aidn_hypervisor.validation_bond.store import BondStore


class BondManagerError(Exception):
    """Base error for bond operations."""


class BondNotFoundError(BondManagerError):
    pass


class BondInsufficientFunds(BondManagerError):
    pass


class BondInvalidTransition(BondManagerError):
    pass


class ValidationBondManager:
    """Manages the full validation bond lifecycle.

    Responsibilities:
    - Lock bonds (enforce minimum amount)
    - Activate bonds for validation duty
    - Recover bonds via exponential decay
    - Forfeit bonds on validation failure
    - Refund bonds on retirement
    - Track audit events
    """

    def __init__(self, store: BondStore | None = None) -> None:
        self._store = store or BondStore()
        self._min_bond = VALIDATION_BOND_Q_ATOMS

    # ── Lock ─────────────────────────────────────────────────────

    def lock_bond(
        self,
        *,
        endpoint_id: str,
        operator_wallet: str,
        amount: int | None = None,
        epoch: int = 0,
    ) -> ValidationBond:
        """Lock a validation bond.

        Args:
            endpoint_id: The endpoint/bond subject.
            operator_wallet: Wallet holding the bond.
            amount: Bond amount in q-atoms (default: 500Q).
            epoch: Current epoch number.

        Returns:
            The created ValidationBond.

        Raises:
            BondInsufficientFunds: If amount < minimum.
            BondInvalidTransition: If endpoint already has a bond.
        """
        amount = amount or self._min_bond

        if amount < self._min_bond:
            raise BondInsufficientFunds(
                f"Bond amount {amount} below minimum {self._min_bond}"
            )

        if self._store.has_endpoint_bond(endpoint_id):
            existing = self._store.get_for_endpoint(endpoint_id)
            if existing and not existing.is_terminal:
                raise BondInvalidTransition(
                    f"Endpoint {endpoint_id} already has an active bond"
                )

        now = datetime.now(UTC).isoformat()
        bond_id = self._generate_bond_id(endpoint_id, operator_wallet)

        event = BondEvent(
            event_id=self._event_id(bond_id, "lock"),
            bond_id=bond_id,
            event_type=BondEventType.LOCK,
            amount_delta=amount,
            epoch=epoch,
            timestamp=now,
        )

        bond = ValidationBond(
            bond_id=bond_id,
            endpoint_id=endpoint_id,
            operator_wallet=operator_wallet,
            initial_amount=amount,
            remaining_amount=amount,
            status=BondStatus.LOCKED,
            created_at=now,
            events=[event],
        )

        self._store.upsert(bond)
        return bond

    # ── Activate ─────────────────────────────────────────────────

    def activate_bond(self, bond_id: str, epoch: int = 0) -> ValidationBond:
        """Activate a locked bond for validation duty.

        Returns:
            The activated ValidationBond.

        Raises:
            BondNotFoundError: If bond doesn't exist.
            BondInvalidTransition: If bond is not in LOCKED state.
        """
        bond = self._get_bond(bond_id)

        try:
            new_bond = bond.activate()
        except ValueError as exc:
            raise BondInvalidTransition(str(exc)) from exc

        now = datetime.now(UTC).isoformat()
        event = BondEvent(
            event_id=self._event_id(bond_id, "activate"),
            bond_id=bond_id,
            event_type=BondEventType.ACTIVATE,
            amount_delta=0,
            epoch=epoch,
            timestamp=now,
        )
        new_bond = new_bond.model_copy(
            update={"events": [*new_bond.events, event]}
        )

        self._store.upsert(new_bond)
        return new_bond

    # ── Recovery ─────────────────────────────────────────────────

    def recover_step(
        self, bond_id: str, epoch: int = 0
    ) -> ValidationBond:
        """Perform one exponential decay recovery step.

        Recovery(n) = remaining × 0.5  (released to operator)
        Remaining(n) = remaining × 0.5  (still locked)

        Returns:
            The updated ValidationBond.

        Raises:
            BondNotFoundError: If bond doesn't exist.
            BondInvalidTransition: If bond is not ACTIVE or RECOVERING.
        """
        bond = self._get_bond(bond_id)

        if bond.status not in (BondStatus.ACTIVE, BondStatus.RECOVERING):
            raise BondInvalidTransition(
                f"Cannot recover bond in status {bond.status}"
            )

        if bond.remaining_amount == 0:
            raise BondInvalidTransition("No remaining amount to recover")

        # Ensure bond is in RECOVERING state
        if bond.status == BondStatus.ACTIVE:
            bond = bond.start_recovery()

        recovery_amount = floor(bond.remaining_amount * RECOVERY_DECAY_FACTOR)

        # Prevent infinite loop: if decay rounds to 0, sweep the remainder
        if recovery_amount == 0 and bond.remaining_amount > 0:
            recovery_amount = bond.remaining_amount

        new_remaining = bond.remaining_amount - recovery_amount

        now = datetime.now(UTC).isoformat()
        step = bond.recovery_count + 1

        record = BondRecoveryRecord(
            recovery_id=self._event_id(bond_id, f"recover_{step}"),
            bond_id=bond_id,
            recovery_amount=recovery_amount,
            remaining_after=new_remaining,
            step_number=step,
            epoch=epoch,
            timestamp=now,
        )

        event = BondEvent(
            event_id=self._event_id(bond_id, f"recover_{step}"),
            bond_id=bond_id,
            event_type=BondEventType.RECOVER,
            amount_delta=-recovery_amount,
            epoch=epoch,
            timestamp=now,
        )

        new_bond = bond.model_copy(
            update={
                "remaining_amount": new_remaining,
                "recovery_count": step,
                "recovery_records": [*bond.recovery_records, record],
                "events": [*bond.events, event],
            }
        )

        # If fully recovered, transition to RECOVERED
        if new_remaining == 0:
            new_bond = new_bond.model_copy(update={"status": BondStatus.RECOVERED})

        self._store.upsert(new_bond)
        return new_bond

    # ── Forfeit ──────────────────────────────────────────────────

    def forfeit_bond(
        self,
        bond_id: str,
        *,
        reason: str = "validation_failure",
        epoch: int = 0,
    ) -> ValidationBond:
        """Forfeit a bond (destroy remaining, send to recycling).

        Returns:
            The forfeited ValidationBond.

        Raises:
            BondNotFoundError: If bond doesn't exist.
            BondInvalidTransition: If already forfeited.
        """
        bond = self._get_bond(bond_id)

        if bond.status == BondStatus.FORFEITED:
            raise BondInvalidTransition("Bond already forfeited")

        now = datetime.now(UTC).isoformat()

        record = BondForfeitRecord(
            forfeit_id=self._event_id(bond_id, "forfeit"),
            bond_id=bond_id,
            forfeited_amount=bond.remaining_amount,
            reason=reason,
            epoch=epoch,
            timestamp=now,
        )

        event = BondEvent(
            event_id=self._event_id(bond_id, "forfeit"),
            bond_id=bond_id,
            event_type=BondEventType.FORFEIT,
            amount_delta=-bond.remaining_amount,
            epoch=epoch,
            timestamp=now,
        )

        new_bond = bond.model_copy(
            update={
                "status": BondStatus.FORFEITED,
                "forfeit_records": [*bond.forfeit_records, record],
                "events": [*bond.events, event],
            }
        )

        self._store.upsert(new_bond)
        return new_bond

    # ── Refund ───────────────────────────────────────────────────

    def refund_bond(self, bond_id: str, epoch: int = 0) -> ValidationBond:
        """Refund a terminal bond (release remaining to operator).

        Returns:
            The refunded ValidationBond.

        Raises:
            BondNotFoundError: If bond doesn't exist.
            BondInvalidTransition: If bond is not in a terminal state.
        """
        bond = self._get_bond(bond_id)

        if not bond.is_terminal:
            raise BondInvalidTransition(
                f"Cannot refund bond in status {bond.status}"
            )

        now = datetime.now(UTC).isoformat()

        event = BondEvent(
            event_id=self._event_id(bond_id, "refund"),
            bond_id=bond_id,
            event_type=BondEventType.REFUND,
            amount_delta=-bond.remaining_amount,
            epoch=epoch,
            timestamp=now,
        )

        new_bond = bond.model_copy(
            update={"events": [*bond.events, event]}
        )

        self._store.upsert(new_bond)
        return new_bond

    # ── Queries ──────────────────────────────────────────────────

    def get_bond(self, bond_id: str) -> ValidationBond | None:
        """Get a bond by ID."""
        return self._store.get(bond_id)

    def get_bond_for_endpoint(
        self, endpoint_id: str
    ) -> ValidationBond | None:
        """Get the bond for an endpoint."""
        return self._store.get_for_endpoint(endpoint_id)

    def get_bonds_for_wallet(
        self, wallet: str
    ) -> list[ValidationBond]:
        """Get all bonds for a wallet."""
        return self._store.get_for_wallet(wallet)

    def get_active_bonds(self) -> list[ValidationBond]:
        """Get all active bonds."""
        return self._store.get_by_status(BondStatus.ACTIVE)

    def get_total_locked(self) -> int:
        """Total q-atoms currently locked across all bonds."""
        return sum(
            b.remaining_amount for b in self._store.get_all() if b.is_active
        )

    # ── Internal ─────────────────────────────────────────────────

    def _get_bond(self, bond_id: str) -> ValidationBond:
        bond = self._store.get(bond_id)
        if bond is None:
            raise BondNotFoundError(f"Bond {bond_id} not found")
        return bond

    @staticmethod
    def _generate_bond_id(endpoint_id: str, wallet: str) -> str:
        raw = f"bond:{endpoint_id}:{wallet}:{uuid.uuid4()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _event_id(bond_id: str, action: str) -> str:
        raw = f"evt:{bond_id}:{action}:{uuid.uuid4()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @property
    def store(self) -> BondStore:
        """Access the underlying store."""
        return self._store
