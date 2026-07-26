"""RFC-0062 §32-§34 — Sync mode selection.

Determines the best strategy for syncing chain state based on available local state,
trust anchors, and genesis availability.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── Sync Mode ──────────────────────────────────────────────────────

class SyncMode(str, Enum):
    """RFC-0062 §32 — Synchronisation strategy."""

    GENESIS_REPLAY = "genesis_replay"
    """Verify the entire chain from genesis. Minimal trust assumption."""

    CHECKPOINT_STATE_SYNC = "checkpoint_state_sync"
    """Fast bootstrap from a trusted checkpoint + snapshot."""

    LOCAL_RECOVERY = "local_recovery"
    """Repair from previously trusted local state."""


# ── Sync Mode Config ──────────────────────────────────────────────

class SyncModeConfig(BaseModel):
    """Configuration for sync mode selection."""

    preferred_mode: SyncMode = SyncMode.CHECKPOINT_STATE_SYNC
    has_local_state: bool = True
    local_state_height: int = 0
    local_state_trusted: bool = True
    trust_anchor_available: bool = False
    trust_anchor_valid: bool = False
    trust_anchor_height: int = 0
    genesis_available: bool = True
    max_lag_blocks: int = 1000


# ── Sync Mode Selection ───────────────────────────────────────────

class SyncModeSelection(BaseModel, frozen=True):
    """Result of sync mode selection."""

    mode: SyncMode
    reason: str
    recommended_snapshot_height: Optional[int] = None


# ── Sync Mode Selector ────────────────────────────────────────────

class SyncModeSelector:
    """RFC-0062 §32 — Determines the best sync mode based on available resources.

    Selection priority:
    1. LOCAL_RECOVERY — if local state exists, is trusted, and lag < max_lag_blocks
    2. CHECKPOINT_STATE_SYNC — if a valid trust anchor is available
    3. GENESIS_REPLAY — if genesis data is available
    4. GENESIS_REPLAY — fallback when nothing else works (prefer genesis over failure)
    """

    def __init__(self, config: SyncModeConfig) -> None:
        self.config = config

    def select(self, *, current_height: int = 0) -> SyncModeSelection:
        """Select the best sync mode.

        :param current_height: the current chain height (used to compute lag).
            Defaults to 0 (unknown).
        """
        cfg = self.config

        # 1. LOCAL_RECOVERY — local state trusted and close enough
        if (
            cfg.has_local_state
            and cfg.local_state_trusted
            and current_height > 0
        ):
            lag = current_height - cfg.local_state_height
            if lag <= cfg.max_lag_blocks:
                return SyncModeSelection(
                    mode=SyncMode.LOCAL_RECOVERY,
                    reason=(
                        f"Local state trusted at height {cfg.local_state_height}, "
                        f"lag {lag} blocks ≤ {cfg.max_lag_blocks}"
                    ),
                    recommended_snapshot_height=None,
                )

        # 2. CHECKPOINT_STATE_SYNC — valid trust anchor
        if cfg.trust_anchor_available and cfg.trust_anchor_valid:
            return SyncModeSelection(
                mode=SyncMode.CHECKPOINT_STATE_SYNC,
                reason="Valid trust anchor available for checkpoint sync",
                recommended_snapshot_height=cfg.trust_anchor_height
                if cfg.trust_anchor_height > 0
                else None,
            )

        # 3. GENESIS_REPLAY — genesis available
        if cfg.genesis_available:
            return SyncModeSelection(
                mode=SyncMode.GENESIS_REPLAY,
                reason="Falling back to genesis replay",
                recommended_snapshot_height=None,
            )

        # 4. Nothing available — still return genesis as safest fallback
        return SyncModeSelection(
            mode=SyncMode.GENESIS_REPLAY,
            reason="No sync resources available; attempting genesis replay as last resort",
            recommended_snapshot_height=None,
        )

    def select_for_recovery(
        self,
        *,
        local_corrupted: bool,
        current_height: int = 0,
    ) -> SyncModeSelection:
        """Select a sync mode for recovery scenarios.

        When local state is corrupted, LOCAL_RECOVERY is skipped regardless of
        configuration.

        :param local_corrupted: whether local state is known to be corrupted.
        :param current_height: current chain height (0 = unknown).
        """
        cfg = self.config

        if local_corrupted:
            # Skip local state entirely — prefer checkpoint, then genesis
            if cfg.trust_anchor_available and cfg.trust_anchor_valid:
                return SyncModeSelection(
                    mode=SyncMode.CHECKPOINT_STATE_SYNC,
                    reason="Local state corrupted; recovering from trusted checkpoint",
                    recommended_snapshot_height=cfg.trust_anchor_height
                    if cfg.trust_anchor_height > 0
                    else None,
                )
            return SyncModeSelection(
                mode=SyncMode.GENESIS_REPLAY,
                reason="Local state corrupted; no checkpoint — full genesis replay",
                recommended_snapshot_height=None,
            )

        # Local state not corrupted — use normal selection.
        # When current_height is unknown, fall back to local_state_height
        # so LOCAL_RECOVERY can still be selected.
        effective_height = current_height if current_height > 0 else cfg.local_state_height
        return self.select(current_height=effective_height)
