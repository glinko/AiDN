"""RFC-0047 §23 — Epoch management and transitions."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class EpochStatus(str, Enum):
    """Epoch lifecycle states."""

    ACTIVE = "active"
    CLOSING = "closing"
    FINALIZED = "finalized"


class EpochConfig(BaseModel, frozen=True):
    """Epoch configuration."""

    blocks_per_epoch: int = 100
    tasks_per_epoch: int = 5
    rotation_fraction: float = 0.1  # 10% validator rotation per epoch


class EpochState(BaseModel):
    """Current epoch state."""

    current_epoch: int = 0
    start_block: int = 0
    end_block: int = 0
    status: EpochStatus = EpochStatus.ACTIVE
    blocks_processed: int = 0
    tasks_completed: int = 0

    def is_complete(self) -> bool:
        """Return True if all blocks in the epoch have been processed."""
        return self.blocks_processed >= self.end_block - self.start_block

    def progress(self) -> float:
        """Return progress as a fraction between 0.0 and 1.0."""
        total = self.end_block - self.start_block
        if total == 0:
            return 0.0
        return min(self.blocks_processed / total, 1.0)


class EpochService:
    """
    RFC-0047 §23 — Epoch management and transitions.

    Tracks epoch lifecycle: active → closing → finalized,
    then starts the next epoch.
    """

    def __init__(self, config: EpochConfig | None = None) -> None:
        self.config = config or EpochConfig()
        self._current = EpochState()
        self._history: list[EpochState] = []
        self._tasks: dict[int, list[str]] = {}  # epoch -> task_ids

    def initialize(self, *, start_block: int) -> None:
        """Initialize the first epoch."""
        self._current = EpochState(
            current_epoch=0,
            start_block=start_block,
            end_block=start_block + self.config.blocks_per_epoch,
            status=EpochStatus.ACTIVE,
        )

    def process_block(self) -> bool:
        """Process a block, return True if epoch transition triggered."""
        self._current.blocks_processed += 1
        if self._current.is_complete():
            self._finalize_current()
            return True
        return False

    def _finalize_current(self) -> None:
        """Finalize current epoch and start next."""
        self._current.status = EpochStatus.FINALIZED
        self._history.append(self._current.model_copy(deep=True))

        self._current = EpochState(
            current_epoch=self._current.current_epoch + 1,
            start_block=self._current.end_block,
            end_block=self._current.end_block + self.config.blocks_per_epoch,
            status=EpochStatus.ACTIVE,
        )

    def get_current(self) -> EpochState:
        """Return a copy of the current epoch state."""
        return self._current.model_copy()

    def get_history(self) -> list[EpochState]:
        """Return copies of all finalized epochs."""
        return [e.model_copy() for e in self._history]

    def schedule_epoch_tasks(self, *, epoch: int, tasks: list[str]) -> None:
        """Schedule tasks for a specific epoch."""
        self._tasks[epoch] = tasks

    def get_epoch_tasks(self, epoch: int) -> list[str]:
        """Return tasks scheduled for a given epoch."""
        return list(self._tasks.get(epoch, []))
