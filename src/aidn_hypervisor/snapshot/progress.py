"""RFC-0062 §88-§89 — Sync progress tracking and metrics.

SyncProgressTracker records phase transitions and progress snapshots
throughout a full state-sync lifecycle.

SyncMetricsCollector aggregates production statistics for availability
and reliability reporting.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ── SyncPhase ─────────────────────────────────────────────────────

class SyncPhase(str, Enum):
    """Lifecycle phases of a snapshot-based state sync."""

    DISCOVERY = "discovery"
    SELECTION = "selection"
    DOWNLOAD = "download"
    VERIFICATION = "verification"
    RESTORATION = "restoration"
    ACTIVATION = "activation"
    REPLAY = "replay"
    COMPLETED = "completed"
    FAILED = "failed"


# ── SyncProgress ──────────────────────────────────────────────────

class SyncProgress(BaseModel, frozen=True):
    """Immutable snapshot of sync progress at a point in time."""

    phase: SyncPhase
    snapshot_id: str | None = None
    selected_height: int | None = None
    chunks_downloaded: int = 0
    chunks_total: int = 0
    bytes_downloaded: int = 0
    providers_active: int = 0
    chunks_rejected: int = 0
    restoration_progress: float = 0.0
    current_replay_height: int | None = None
    estimated_lag_blocks: int | None = None
    updated_at: str
    """ISO-8601 timestamp of this progress snapshot."""


# ── SyncMetrics ───────────────────────────────────────────────────

class SyncMetrics(BaseModel, frozen=True):
    """Aggregated metrics for snapshot sync operations."""

    production_success_count: int = 0
    availability_count: int = 0
    independent_provider_count: int = 0
    completion_rate: float = 0.0
    average_download_seconds: float = 0.0
    average_restoration_seconds: float = 0.0
    invalid_chunk_rate: float = 0.0
    defective_report_count: int = 0
    replay_duration_seconds: float = 0.0
    snapshot_age_blocks: int | None = None
    failure_count_by_version: dict[str, int] = Field(default_factory=dict)


# ── SyncProgressTracker ──────────────────────────────────────────

class SyncProgressTracker:
    """Tracks progress through a sync lifecycle.

    Usage::

        tracker = SyncProgressTracker()
        tracker.update_phase(SyncPhase.DOWNLOAD)
        tracker.update_download(downloaded=5, total=20, bytes_count=50_000,
                               providers=3, rejected=0)
        tracker.complete("snapshot-abc")
    """

    # Canonical phase order (excluding terminal states)
    _PHASE_ORDER: list[SyncPhase] = [
        SyncPhase.DISCOVERY,
        SyncPhase.SELECTION,
        SyncPhase.DOWNLOAD,
        SyncPhase.VERIFICATION,
        SyncPhase.RESTORATION,
        SyncPhase.ACTIVATION,
        SyncPhase.REPLAY,
    ]

    def __init__(self) -> None:
        self._phase = SyncPhase.DISCOVERY
        self._snapshot_id: str | None = None
        self._selected_height: int | None = None
        self._chunks_downloaded = 0
        self._chunks_total = 0
        self._bytes_downloaded = 0
        self._providers_active = 0
        self._chunks_rejected = 0
        self._restoration_progress = 0.0
        self._current_replay_height: int | None = None
        self._target_replay_height: int | None = None
        self._history: list[SyncProgress] = []

    @property
    def current_phase(self) -> SyncPhase:
        return self._phase

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _emit(self) -> SyncProgress:
        lag: int | None = None
        if self._target_replay_height is not None and self._current_replay_height is not None:
            lag = self._target_replay_height - self._current_replay_height
        entry = SyncProgress(
            phase=self._phase,
            snapshot_id=self._snapshot_id,
            selected_height=self._selected_height,
            chunks_downloaded=self._chunks_downloaded,
            chunks_total=self._chunks_total,
            bytes_downloaded=self._bytes_downloaded,
            providers_active=self._providers_active,
            chunks_rejected=self._chunks_rejected,
            restoration_progress=self._restoration_progress,
            current_replay_height=self._current_replay_height,
            estimated_lag_blocks=lag,
            updated_at=self._now(),
        )
        self._history.append(entry)
        return entry

    # ── phase transitions ──────────────────────────────────────

    def update_phase(self, phase: SyncPhase) -> None:
        """Advance to the next sync phase."""
        self._phase = phase
        self._emit()

    def update_download(
        self,
        downloaded: int,
        total: int,
        bytes_count: int,
        providers: int,
        rejected: int,
    ) -> SyncProgress:
        """Update download progress counters."""
        self._chunks_downloaded = downloaded
        self._chunks_total = total
        self._bytes_downloaded = bytes_count
        self._providers_active = providers
        self._chunks_rejected = rejected
        return self._emit()

    def update_restoration(self, progress: float) -> SyncProgress:
        """Update restoration progress (0.0 → 1.0)."""
        self._restoration_progress = max(0.0, min(1.0, progress))
        return self._emit()

    def update_replay(
        self,
        current_height: int,
        target_height: int,
    ) -> SyncProgress:
        """Update block replay progress."""
        self._current_replay_height = current_height
        self._target_replay_height = target_height
        return self._emit()

    def complete(self, snapshot_id: str) -> SyncProgress:
        """Mark sync as completed."""
        self._phase = SyncPhase.COMPLETED
        self._snapshot_id = snapshot_id
        return self._emit()

    def fail(self, error: str) -> SyncProgress:
        """Mark sync as failed (error is logged in history via metadata)."""
        self._phase = SyncPhase.FAILED
        return self._emit()

    # ── queries ────────────────────────────────────────────────

    def get_progress(self) -> SyncProgress:
        """Return the current progress snapshot (without appending to history)."""
        lag: int | None = None
        if self._target_replay_height is not None and self._current_replay_height is not None:
            lag = self._target_replay_height - self._current_replay_height
        return SyncProgress(
            phase=self._phase,
            snapshot_id=self._snapshot_id,
            selected_height=self._selected_height,
            chunks_downloaded=self._chunks_downloaded,
            chunks_total=self._chunks_total,
            bytes_downloaded=self._bytes_downloaded,
            providers_active=self._providers_active,
            chunks_rejected=self._chunks_rejected,
            restoration_progress=self._restoration_progress,
            current_replay_height=self._current_replay_height,
            estimated_lag_blocks=lag,
            updated_at=self._now(),
        )

    def get_history(self) -> list[SyncProgress]:
        """Return all recorded progress snapshots."""
        return list(self._history)


# ── SyncMetricsCollector ─────────────────────────────────────────

class SyncMetricsCollector:
    """Collects and aggregates sync metrics over time."""

    def __init__(self) -> None:
        self._success_count = 0
        self._failure_count = 0
        self._download_durations: list[float] = []
        self._restoration_durations: list[float] = []
        self._replay_durations: list[float] = []
        self._invalid_chunks = 0
        self._total_chunks = 0
        self._defective_reports = 0
        self._failure_by_version: dict[str, int] = {}

    # ── recorders ──────────────────────────────────────────────

    def record_production_success(self) -> None:
        self._success_count += 1

    def record_production_failure(self) -> None:
        self._failure_count += 1

    def record_download(
        self,
        duration_seconds: float,
        invalid_chunks: int,
        total_chunks: int,
    ) -> None:
        self._download_durations.append(duration_seconds)
        self._invalid_chunks += invalid_chunks
        self._total_chunks += total_chunks

    def record_restoration(self, duration_seconds: float) -> None:
        self._restoration_durations.append(duration_seconds)

    def record_replay(self, duration_seconds: float) -> None:
        self._replay_durations.append(duration_seconds)

    def record_defective_report(self) -> None:
        self._defective_reports += 1

    def record_failure(self, version: str) -> None:
        self._failure_by_version[version] = (
            self._failure_by_version.get(version, 0) + 1
        )

    # ── aggregation ────────────────────────────────────────────

    def get_metrics(self) -> SyncMetrics:
        """Compute aggregated metrics from collected data."""
        total_attempts = self._success_count + self._failure_count
        completion_rate = (
            self._success_count / total_attempts if total_attempts else 0.0
        )

        avg_download = (
            sum(self._download_durations) / len(self._download_durations)
            if self._download_durations
            else 0.0
        )
        avg_restoration = (
            sum(self._restoration_durations) / len(self._restoration_durations)
            if self._restoration_durations
            else 0.0
        )
        total_replay = sum(self._replay_durations)
        invalid_rate = (
            self._invalid_chunks / self._total_chunks
            if self._total_chunks
            else 0.0
        )

        return SyncMetrics(
            production_success_count=self._success_count,
            availability_count=0,
            independent_provider_count=0,
            completion_rate=completion_rate,
            average_download_seconds=avg_download,
            average_restoration_seconds=avg_restoration,
            invalid_chunk_rate=invalid_rate,
            defective_report_count=self._defective_reports,
            replay_duration_seconds=total_replay,
            snapshot_age_blocks=None,
            failure_count_by_version=dict(self._failure_by_version),
        )

    def reset(self) -> None:
        """Clear all collected metrics."""
        self.__init__()
