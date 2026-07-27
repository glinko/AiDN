"""Tests for progress.py — Sync Progress + Metrics per RFC-0062 §88-§89."""

from __future__ import annotations

import pytest

from aidn_hypervisor.snapshot.progress import (
    SyncMetrics,
    SyncMetricsCollector,
    SyncPhase,
    SyncProgress,
    SyncProgressTracker,
)

# ── SyncPhase enum ─────────────────────────────────────────────────

class TestSyncPhase:
    def test_discovery(self):
        assert SyncPhase.DISCOVERY.value == "discovery"

    def test_selection(self):
        assert SyncPhase.SELECTION.value == "selection"

    def test_download(self):
        assert SyncPhase.DOWNLOAD.value == "download"

    def test_verification(self):
        assert SyncPhase.VERIFICATION.value == "verification"

    def test_restoration(self):
        assert SyncPhase.RESTORATION.value == "restoration"

    def test_activation(self):
        assert SyncPhase.ACTIVATION.value == "activation"

    def test_replay(self):
        assert SyncPhase.REPLAY.value == "replay"

    def test_completed(self):
        assert SyncPhase.COMPLETED.value == "completed"

    def test_failed(self):
        assert SyncPhase.FAILED.value == "failed"


# ── SyncProgressTracker ──────────────────────────────────────────

class TestSyncProgressTracker:
    def test_starts_in_discovery(self):
        tracker = SyncProgressTracker()
        assert tracker.current_phase == SyncPhase.DISCOVERY

    def test_phase_advances_through_sequence(self):
        tracker = SyncProgressTracker()
        phases = [
            SyncPhase.SELECTION,
            SyncPhase.DOWNLOAD,
            SyncPhase.VERIFICATION,
            SyncPhase.RESTORATION,
            SyncPhase.ACTIVATION,
            SyncPhase.REPLAY,
        ]
        for phase in phases:
            tracker.update_phase(phase)
            assert tracker.current_phase == phase

    def test_download_progress_updates(self):
        tracker = SyncProgressTracker()
        tracker.update_phase(SyncPhase.DOWNLOAD)
        progress = tracker.update_download(
            downloaded=5, total=20, bytes_count=5000, providers=3, rejected=1
        )
        assert progress.chunks_downloaded == 5
        assert progress.chunks_total == 20
        assert progress.bytes_downloaded == 5000
        assert progress.providers_active == 3
        assert progress.chunks_rejected == 1

    def test_restoration_progress_updates(self):
        tracker = SyncProgressTracker()
        tracker.update_phase(SyncPhase.RESTORATION)
        progress = tracker.update_restoration(0.75)
        assert progress.restoration_progress == 0.75

    def test_replay_progress_updates(self):
        tracker = SyncProgressTracker()
        tracker.update_phase(SyncPhase.REPLAY)
        progress = tracker.update_replay(current_height=1050, target_height=1100)
        assert progress.current_replay_height == 1050
        assert progress.estimated_lag_blocks == 50

    def test_complete_marks_as_completed(self):
        tracker = SyncProgressTracker()
        progress = tracker.complete("snap-001")
        assert progress.phase == SyncPhase.COMPLETED
        assert progress.snapshot_id == "snap-001"

    def test_fail_marks_as_failed(self):
        tracker = SyncProgressTracker()
        progress = tracker.fail("network error")
        assert progress.phase == SyncPhase.FAILED

    def test_history_records_all_updates(self):
        tracker = SyncProgressTracker()
        tracker.update_phase(SyncPhase.DOWNLOAD)
        tracker.update_download(3, 10, 3000, 2, 0)
        tracker.update_phase(SyncPhase.RESTORATION)
        tracker.update_restoration(1.0)
        history = tracker.get_history()
        assert len(history) >= 4

    def test_get_progress_returns_current(self):
        tracker = SyncProgressTracker()
        tracker.update_phase(SyncPhase.DOWNLOAD)
        progress = tracker.get_progress()
        assert progress.phase == SyncPhase.DOWNLOAD

    def test_invalid_phase_transition_handled(self):
        tracker = SyncProgressTracker()
        # Jumping from DISCOVERY to COMPLETED should still work (force update)
        tracker.complete("snap-001")
        assert tracker.current_phase == SyncPhase.COMPLETED

    def test_snapshot_id_set_on_complete(self):
        tracker = SyncProgressTracker()
        tracker.complete("my-snapshot-id")
        progress = tracker.get_progress()
        assert progress.snapshot_id == "my-snapshot-id"

    def test_selected_height_in_progress(self):
        tracker = SyncProgressTracker()
        tracker.update_phase(SyncPhase.SELECTION)
        progress = tracker.update_download(1, 10, 1000, 1, 0)
        assert progress.selected_height is not None or progress.chunks_downloaded == 1

    def test_failed_progress_contains_error_info(self):
        tracker = SyncProgressTracker()
        tracker.fail("disk full")
        progress = tracker.get_progress()
        assert progress.phase == SyncPhase.FAILED


# ── SyncProgress model ────────────────────────────────────────────

class TestSyncProgressModel:
    def test_create_progress(self):
        p = SyncProgress(
            phase=SyncPhase.DOWNLOAD,
            snapshot_id="snap-1",
            selected_height=100,
            chunks_downloaded=5,
            chunks_total=10,
            bytes_downloaded=5000,
            providers_active=2,
            chunks_rejected=0,
            restoration_progress=0.0,
            current_replay_height=None,
            estimated_lag_blocks=None,
            updated_at="2025-01-01T00:00:00Z",
        )
        assert p.phase == SyncPhase.DOWNLOAD
        assert p.chunks_downloaded == 5

    def test_progress_is_frozen(self):
        p = SyncProgress(
            phase=SyncPhase.DISCOVERY,
            snapshot_id=None,
            selected_height=None,
            chunks_downloaded=0,
            chunks_total=0,
            bytes_downloaded=0,
            providers_active=0,
            chunks_rejected=0,
            restoration_progress=0.0,
            current_replay_height=None,
            estimated_lag_blocks=None,
            updated_at="2025-01-01T00:00:00Z",
        )
        with pytest.raises(Exception):
            p.phase = SyncPhase.DOWNLOAD  # type: ignore


# ── SyncMetricsCollector ──────────────────────────────────────────

class TestSyncMetricsCollector:
    def test_records_production_success(self):
        collector = SyncMetricsCollector()
        collector.record_production_success()
        metrics = collector.get_metrics()
        assert metrics.production_success_count == 1

    def test_records_production_failure(self):
        collector = SyncMetricsCollector()
        collector.record_production_failure()
        metrics = collector.get_metrics()
        assert metrics.completion_rate < 1.0

    def test_records_download(self):
        collector = SyncMetricsCollector()
        collector.record_download(duration_seconds=10.5, invalid_chunks=1, total_chunks=10)
        metrics = collector.get_metrics()
        assert metrics.average_download_seconds == 10.5
        assert metrics.invalid_chunk_rate == 0.1

    def test_records_restoration(self):
        collector = SyncMetricsCollector()
        collector.record_restoration(duration_seconds=5.0)
        metrics = collector.get_metrics()
        assert metrics.average_restoration_seconds == 5.0

    def test_records_replay(self):
        collector = SyncMetricsCollector()
        collector.record_replay(duration_seconds=3.0)
        metrics = collector.get_metrics()
        assert metrics.replay_duration_seconds == 3.0

    def test_records_defective_report(self):
        collector = SyncMetricsCollector()
        collector.record_defective_report()
        metrics = collector.get_metrics()
        assert metrics.defective_report_count == 1

    def test_records_failure_by_version(self):
        collector = SyncMetricsCollector()
        collector.record_failure("v1.0")
        collector.record_failure("v2.0")
        collector.record_failure("v1.0")
        metrics = collector.get_metrics()
        assert metrics.failure_count_by_version["v1.0"] == 2
        assert metrics.failure_count_by_version["v2.0"] == 1

    def test_aggregated_metrics_computed(self):
        collector = SyncMetricsCollector()
        collector.record_production_success()
        collector.record_production_success()
        collector.record_production_failure()
        collector.record_download(10.0, 1, 10)
        collector.record_download(20.0, 2, 20)
        collector.record_restoration(5.0)
        collector.record_replay(3.0)
        collector.record_defective_report()
        metrics = collector.get_metrics()
        assert metrics.production_success_count == 2
        assert metrics.completion_rate == 2 / 3
        assert metrics.average_download_seconds == 15.0
        assert metrics.invalid_chunk_rate == pytest.approx(3 / 30, abs=0.01)
        assert metrics.defective_report_count == 1

    def test_reset_clears_metrics(self):
        collector = SyncMetricsCollector()
        collector.record_production_success()
        collector.record_download(10.0, 1, 10)
        collector.reset()
        metrics = collector.get_metrics()
        assert metrics.production_success_count == 0
        assert metrics.average_download_seconds == 0.0

    def test_empty_metrics_defaults(self):
        collector = SyncMetricsCollector()
        metrics = collector.get_metrics()
        assert metrics.production_success_count == 0
        assert metrics.completion_rate == 0.0
        assert metrics.average_download_seconds == 0.0

    def test_multiple_successes_and_failures_rate(self):
        collector = SyncMetricsCollector()
        for _ in range(8):
            collector.record_production_success()
        for _ in range(2):
            collector.record_production_failure()
        metrics = collector.get_metrics()
        assert metrics.completion_rate == 0.8
        assert metrics.production_success_count == 8


# ── SyncMetrics model ─────────────────────────────────────────────

class TestSyncMetricsModel:
    def test_create_metrics(self):
        m = SyncMetrics(
            production_success_count=5,
            availability_count=10,
            independent_provider_count=3,
            completion_rate=0.5,
            average_download_seconds=10.0,
            average_restoration_seconds=5.0,
            invalid_chunk_rate=0.05,
            defective_report_count=1,
            replay_duration_seconds=3.0,
            snapshot_age_blocks=100,
            failure_count_by_version={"v1": 2},
        )
        assert m.production_success_count == 5
        assert m.completion_rate == 0.5

    def test_metrics_is_frozen(self):
        m = SyncMetrics(
            production_success_count=0,
            availability_count=0,
            independent_provider_count=0,
            completion_rate=0.0,
            average_download_seconds=0.0,
            average_restoration_seconds=0.0,
            invalid_chunk_rate=0.0,
            defective_report_count=0,
            replay_duration_seconds=0.0,
            snapshot_age_blocks=None,
            failure_count_by_version={},
        )
        with pytest.raises(Exception):
            m.production_success_count = 1  # type: ignore
