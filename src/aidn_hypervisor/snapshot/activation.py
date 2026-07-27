"""RFC-0062 §51 — Atomic activation.

AtomicActivator performs atomic state switch with crash recovery.
ActivationState tracks the state machine for the activation process.
"""

from __future__ import annotations

import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from aidn_hypervisor.snapshot.encoding import PortableSnapshotEncoder
from aidn_hypervisor.snapshot.staging import StagingStateStore

# ── ActivationState ───────────────────────────────────────────────


class ActivationState(StrEnum):
    """State machine for atomic activation."""

    IDLE = "idle"
    """No activation in progress."""

    VERIFYING = "verifying"
    """Staging verification in progress."""

    READY = "ready"
    """Staging verified, ready to activate."""

    ACTIVATING = "activating"
    """Atomic switch in progress."""

    ACTIVATED = "activated"
    """Activation completed."""

    FAILED = "failed"
    """Activation failed, rolled back."""


# ── ActivationResult ──────────────────────────────────────────────


@dataclass
class ActivationResult:
    """Result of an activation operation."""

    success: bool
    previous_state_hash: str
    new_state_hash: str
    snapshot_id: str
    activated_at: str  # ISO-8601
    error: str | None = None


# ── ActivationRecord (frozen) ─────────────────────────────────────


@dataclass(frozen=True)
class ActivationRecord:
    """Immutable record of a completed activation attempt."""

    previous_state_hash: str
    new_state_hash: str
    snapshot_id: str
    activated_at: str
    success: bool


# ── AtomicActivator ───────────────────────────────────────────────


class AtomicActivator:
    """Atomic state switch per RFC-0062 §51.

    State machine:
    IDLE → VERIFYING → READY → ACTIVATING → ACTIVATED
                                              ↘ FAILED (on error)

    On failure: transition to FAILED, preserve old state.
    Rollback: revert to previous active state (crash recovery per §87).
    """

    def __init__(self) -> None:
        self._state = ActivationState.IDLE
        self._active_state_hash: str = ""
        self._previous_state_hash: str = ""
        self._staging_data: dict[str, Any] | None = None
        self._active_state_data: dict[str, Any] | None = None
        self._previous_state_data: dict[str, Any] | None = None
        self._history: list[ActivationRecord] = []

    @property
    def state(self) -> ActivationState:
        """Current activation state."""
        return self._state

    @property
    def active_state_hash(self) -> str:
        """Hash of currently active state."""
        return self._active_state_hash

    @property
    def active_state_data(self) -> dict[str, Any] | None:
        """A defensive copy of the active state for recovery integration."""
        return deepcopy(self._active_state_data)

    def prepare(self, staging: StagingStateStore, expected_state_hash: str) -> bool:
        """Verify staging and set state to READY.

        Args:
            staging: The staging store with loaded snapshot data.
            expected_state_hash: The hash the staging state should match.

        Returns:
            True if staging is verified and ready, False otherwise.
        """
        # Transition to VERIFYING
        self._state = ActivationState.VERIFYING

        # Verify staging is not empty
        if staging.is_empty():
            self._state = ActivationState.FAILED
            return False

        # Verify hash
        actual_hash = staging.calculate_state_hash()
        if actual_hash != expected_state_hash:
            self._state = ActivationState.FAILED
            return False

        # Capture staging data
        # The staging store remains independently mutable until activation.
        # Copy it here so the verified data is the data later activated.
        self._staging_data = deepcopy(staging._get_raw())

        # Transition to READY
        self._state = ActivationState.READY
        return True

    def activate(self) -> ActivationResult:
        """Perform atomic switch.

        1. Stop writes (briefly) — in MVP, this is a reference swap
        2. Switch active state reference to staging data
        3. Record activated snapshot ID
        4. Transition to ACTIVATED
        5. On failure: transition to FAILED, preserve old state
        """
        now = datetime.now(UTC).isoformat()
        snapshot_id = str(uuid.uuid4())

        # Validate state transition
        if self._state != ActivationState.READY:
            error_msg = f"Cannot activate from state {self._state.value}. Expected READY."
            # An invalid command must leave the active state recoverable.
            self._previous_state_hash = self._active_state_hash
            self._previous_state_data = deepcopy(self._active_state_data)
            self._state = ActivationState.FAILED
            return ActivationResult(
                success=False,
                previous_state_hash=self._active_state_hash,
                new_state_hash="",
                snapshot_id="",
                activated_at=now,
                error=error_msg,
            )

        # Transition to ACTIVATING
        self._state = ActivationState.ACTIVATING

        try:
            # Preserve previous state for rollback
            self._previous_state_hash = self._active_state_hash
            self._previous_state_data = deepcopy(self._active_state_data)

            # Build the replacement before changing the active reference so a
            # failure cannot leave a half-activated state behind.
            new_state_data = deepcopy(self._staging_data)
            new_hash = self._compute_hash_from_data(new_state_data)

            # Atomic switch: replace both state data and its committed hash.
            self._active_state_data = new_state_data
            self._active_state_hash = new_hash

            # Record in history
            record = ActivationRecord(
                previous_state_hash=self._previous_state_hash,
                new_state_hash=new_hash,
                snapshot_id=snapshot_id,
                activated_at=now,
                success=True,
            )
            self._history.append(record)

            # Transition to ACTIVATED
            self._state = ActivationState.ACTIVATED

            # Clear staging (data is now active)
            self._staging_data = None

            return ActivationResult(
                success=True,
                previous_state_hash=self._previous_state_hash,
                new_state_hash=new_hash,
                snapshot_id=snapshot_id,
                activated_at=now,
                error=None,
            )

        except Exception as e:
            # A hash alone cannot restore a previously active state.
            self._active_state_hash = self._previous_state_hash
            self._active_state_data = deepcopy(self._previous_state_data)
            self._state = ActivationState.FAILED
            return ActivationResult(
                success=False,
                previous_state_hash=self._active_state_hash,
                new_state_hash="",
                snapshot_id="",
                activated_at=now,
                error=str(e),
            )

    def rollback(self) -> None:
        """Revert to previous active state (crash recovery per §87)."""
        if self._state == ActivationState.IDLE:
            return  # Nothing to rollback

        # Restore previous state, including the actual state data.
        self._active_state_hash = self._previous_state_hash
        self._active_state_data = deepcopy(self._previous_state_data)
        self._previous_state_hash = ""
        self._previous_state_data = None
        self._staging_data = None

        # Reset to IDLE
        self._state = ActivationState.IDLE

    def get_activation_history(self) -> list[ActivationRecord]:
        """History of activations."""
        return list(self._history)

    @staticmethod
    def _compute_hash_from_data(data: dict[str, Any]) -> str:
        """Compute the same canonical state hash used by producer and staging."""
        return PortableSnapshotEncoder().compute_content_hash(data)
