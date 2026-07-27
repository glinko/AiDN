"""RFC-0062 §52-§54 — Later-Block Replay after snapshot activation.

BlockReplayer replays finalized blocks that arrived after the snapshot
was taken, verifying state hashes and validator-set transitions.
"""

from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from collections.abc import Callable

from pydantic import BaseModel, Field

# ── Data models ───────────────────────────────────────────────────


class ReplayBlock(BaseModel, frozen=True):
    """Single block to be replayed over the restored snapshot state."""

    block_height: int
    block_hash: str
    application_state_hash: str
    """Expected hash of the application state after executing this block."""

    validator_set_hash: str | None = None
    timestamp: str
    """ISO-8601 block time."""


class ReplayConfig(BaseModel, frozen=True):
    """Replay configuration per §52."""

    start_height: int
    """First block to replay (snapshot height + 1)."""

    target_height: int
    """Current finalized height — last block to replay."""

    max_replay_time_seconds: int = 3600
    verify_state_hash: bool = True
    """Verify each resulting state hash per §52."""
    verify_validator_set: bool = True
    """Verify validator-set transitions per §53."""


class ReplayResult(BaseModel, frozen=True):
    """Outcome of a replay run."""

    success: bool
    start_height: int
    end_height: int
    blocks_replayed: int
    final_state_hash: str
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0


# ── Block source protocol ─────────────────────────────────────────


class BlockSource(ABC):
    """Interface for fetching blocks and executing them against state."""

    @abstractmethod
    def get_block(self, height: int) -> ReplayBlock | None:
        """Return the block at *height*, or None if unavailable."""

    @abstractmethod
    def get_finalized_height(self) -> int:
        """Return the current finalized block height."""

    @abstractmethod
    def get_state_at_height(self, height: int) -> dict | None:
        """Return a state snapshot at *height*, if available."""

    @abstractmethod
    def execute_block(self, state: dict, block: ReplayBlock) -> dict:
        """Apply *block* to *state*, returning the new state."""


# ── State hash helper ─────────────────────────────────────────────


def _compute_state_hash(state: dict) -> str:
    """Deterministic hash of a state dict."""
    raw = str(sorted(state.items()))
    return hashlib.sha256(raw.encode()).hexdigest()


# ── BlockReplayer ─────────────────────────────────────────────────


class BlockReplayer:
    """Replays finalized blocks over a restored snapshot state.

    Per §52:
    1. Start from snapshot height + 1
    2. Execute each block against current state
    3. Optionally verify state hash after each block
    4. Optionally verify validator-set transitions (§53)
    5. Return result
    """

    def __init__(self, config: ReplayConfig, block_source: BlockSource):
        self._config = config
        self._source = block_source

    # ── public API ──────────────────────────────────────────────

    def get_replay_range(self) -> tuple[int, int]:
        """Return (start_height, target_height)."""
        return (self._config.start_height, self._config.target_height)

    def replay(self, initial_state: dict) -> ReplayResult:
        """Full replay per §52."""
        return self._do_replay(initial_state, callback=None)

    def replay_with_callback(
        self,
        initial_state: dict,
        callback: Callable[[int, str], None],
    ) -> ReplayResult:
        """Same as :meth:`replay` but invokes *callback(height, state_hash)*
        after each successfully applied block."""
        return self._do_replay(initial_state, callback=callback)

    # ── internals ───────────────────────────────────────────────

    def _do_replay(
        self,
        initial_state: dict,
        callback: Callable[[int, str], None] | None,
    ) -> ReplayResult:
        t0 = time.perf_counter()
        errors: list[str] = []
        state = dict(initial_state)
        count = 0

        # When start == target, snapshot is already at target — nothing to replay.
        replay_range = (
            range(
                self._config.start_height,
                self._config.target_height + 1,
            )
            if self._config.start_height < self._config.target_height
            else ()
        )

        for height in replay_range:
            block = self._source.get_block(height)
            if block is None:
                errors.append(f"Block at height {height} not available")
                break

            # Execute block
            state = self._source.execute_block(state, block)

            # Verify state hash (§52)
            if self._config.verify_state_hash:
                actual_hash = block.application_state_hash
                # The source's execute_block should produce a state whose
                # state_hash field matches the expected application_state_hash.
                computed = state.get("state_hash", "")
                if computed != actual_hash:
                    errors.append(f"State hash mismatch at height {height}: expected {actual_hash}, got {computed}")
                    break

            count += 1

            # Callback for progress reporting
            if callback is not None:
                callback(height, block.application_state_hash)

        # Validator-set verification (§53)
        if not errors and self._config.verify_validator_set:
            last_block = self._source.get_block(self._config.target_height)
            if last_block and last_block.validator_set_hash:
                computed_val = state.get("validator_set_hash", "")
                if computed_val != last_block.validator_set_hash:
                    errors.append(
                        f"Validator set mismatch at height {self._config.target_height}: "
                        f"expected {last_block.validator_set_hash}, got {computed_val}"
                    )

        end_height = self._config.start_height + count - 1 if count else self._config.start_height
        final_hash = state.get("state_hash", _compute_state_hash(state))
        duration = time.perf_counter() - t0

        return ReplayResult(
            success=len(errors) == 0,
            start_height=self._config.start_height,
            end_height=end_height,
            blocks_replayed=count,
            final_state_hash=final_hash,
            errors=errors,
            duration_seconds=duration,
        )
