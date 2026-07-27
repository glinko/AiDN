"""Integration: Custody failures → Reputation Engine events (M5 Phase 3).

Validates that custody failures, restorations, and challenges properly
generate reputation events consumed by the ReputationEngine.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aidn_hypervisor.reputation_engine.engine import ReputationEngine
from aidn_hypervisor.reputation_engine.models import ReputationEvent
from aidn_hypervisor.reputation_engine.store import ReputationStore
from aidn_hypervisor.validation.custody import (
    Correction,
    CustodyConfig,
    CustodyService,
    CustodyState,
    CustodyStatus,
    CustodyStore,
    EventFinalizationState,
    FinalizationService,
    FinalizationStore,
    ReputationEventRecord,
)


class CustodyReputationBridge:
    """Bridge: Custody events → Reputation events.

    Maps custody state changes to reputation dimension events
    for the ReputationEngine.
    """

    CUSTODY_DIMENSION = "RELIABILITY"

    def __init__(
        self,
        engine: ReputationEngine,
        custody_service: CustodyService,
        finalization_service: FinalizationService,
    ):
        self.engine = engine
        self.custody = custody_service
        self.finalization = finalization_service

    def on_custody_failure(self, report_hash: str, endpoint_id: str, failure_streak: int):
        """Emit a negative reputation event for a custody failure."""
        event = ReputationEvent(
            subject_type="ENDPOINT",
            subject_id=endpoint_id,
            profile_dimension=self.CUSTODY_DIMENSION,
            event_class="PROTOCOL_EVENT",
            direction="NEGATIVE",
            severity="CRITICAL" if failure_streak >= 3 else "MODERATE",
            evidence_confidence="MULTI_SOURCE",
            source_reference=report_hash,
        )
        self.engine.ingest_event(event)

        # Track for finalization
        record = ReputationEventRecord(
            event_id=f"custody-{report_hash[:16]}-{datetime.now(UTC).timestamp()}",
            subject_id=endpoint_id,
            dimension=self.CUSTODY_DIMENSION,
            direction="NEGATIVE",
            score_delta=-0.05 * min(failure_streak, 5),
        )
        self.finalization.add_event(record)

    def on_custody_restoration(self, report_hash: str, endpoint_id: str):
        """Emit a positive reputation event for a custody restoration."""
        event = ReputationEvent(
            subject_type="ENDPOINT",
            subject_id=endpoint_id,
            profile_dimension=self.CUSTODY_DIMENSION,
            event_class="RECOVERY_EVENT",
            direction="POSITIVE",
            severity="MINOR",
            evidence_confidence="MULTI_SOURCE",
            source_reference=report_hash,
        )
        self.engine.ingest_event(event)

    def on_challenge_accepted(self, event_id: str, correction: Correction):
        """Apply correction when a challenge is accepted."""
        self.finalization.apply_correction(correction)

    def on_challenge_rejected(self, event_id: str):
        """Finalize event when challenge is rejected."""
        self.finalization.finalize_event(event_id)


class TestCustodyReputationIntegration:
    """Custody failures affect endpoint reputation."""

    def setup_method(self):
        self.rep_store = ReputationStore()
        self.rep_engine = ReputationEngine(self.rep_store)
        self.custody_store = CustodyStore()
        self.custody_cfg = CustodyConfig(
            grace_period_seconds=60,
            minimum_retention_seconds=3600,
            max_failure_streak=5,
            check_interval_seconds=10,
        )
        self.custody_svc = CustodyService(self.custody_store, self.custody_cfg)
        self.final_store = FinalizationStore()
        self.final_svc = FinalizationService(self.final_store)
        self.bridge = CustodyReputationBridge(
            self.rep_engine, self.custody_svc, self.final_svc
        )

    def _register_report(self, endpoint_id="ep-1"):
        self.custody_store.add(CustodyState(
            report_hash="sha256:" + "ab" * 32,
            endpoint_id=endpoint_id,
            stored_at=datetime.now(UTC),
        ))

    def test_custody_failure_reduces_reliability(self):
        """Custody failure emits negative reliability event."""
        self._register_report()
        result = self.custody_svc.check_custody("sha256:" + "ab" * 32, available=False)

        # Force grace expiry to trigger failure
        state = self.custody_store.get("sha256:" + "ab" * 32)
        state.grace_expires_at = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
        result = self.custody_svc.check_custody("sha256:" + "ab" * 32, available=False)

        assert result.status == CustodyStatus.CUSTODY_FAILED
        assert result.action == "emit_penalty"

        # Bridge emits reputation event
        self.bridge.on_custody_failure(
            "sha256:" + "ab" * 32, "ep-1", result.failure_streak
        )

        profile = self.rep_engine.get_profile("ENDPOINT", "ep-1")
        rel = profile.accumulators.get("RELIABILITY")
        assert rel is not None
        assert rel.effective_score < 0.5  # negative event lowered score

    def test_custody_restoration_improves_reliability(self):
        """Restoration emits positive event."""
        self._register_report()

        # Simulate failure then restoration
        self.bridge.on_custody_failure("sha256:" + "ab" * 32, "ep-1", 2)
        self.bridge.on_custody_restoration("sha256:" + "ab" * 32, "ep-1")

        profile = self.rep_engine.get_profile("ENDPOINT", "ep-1")
        rel = profile.accumulators.get("RELIABILITY")
        assert rel is not None
        # Positive event should partially recover
        assert rel.effective_score > 0.3

    def test_repeated_failures_compound_penalty(self):
        """Multiple failures stack up in reputation."""
        self._register_report()

        for i in range(3):
            hash_suffix = f"{0xaa00 + i:064x}".ljust(64, "0")[:64]
            self.bridge.on_custody_failure(
                f"sha256:{hash_suffix}", "ep-1", i + 1
            )

        profile = self.rep_engine.get_profile("ENDPOINT", "ep-1")
        rel = profile.accumulators.get("RELIABILITY")
        assert rel is not None
        assert rel.effective_score < 0.5  # negative events lowered score
        assert rel.event_count >= 3

    def test_challenge_accepted_applies_correction(self):
        """Accepted challenge corrects the reputation event."""
        self._register_report()

        # Emit failure
        self.bridge.on_custody_failure("sha256:" + "ab" * 32, "ep-1", 1)

        # Get the event record
        records = self.final_store.list_pending()
        assert len(records) >= 1
        event_id = records[-1].event_id

        # Challenge and accept
        correction = Correction(
            correction_id="corr-1",
            original_event_id=event_id,
            error_class="wrong_subject",
            corrected_values={"subject_id": "correct-ep"},
            resulting_score_adjustment=0.05,
        )
        self.bridge.on_challenge_accepted(event_id, correction)

        # Event should be corrected
        event = self.final_store.get_event(event_id)
        assert event.finalization_state == EventFinalizationState.CORRECTED
        assert event.correction_id == "corr-1"

    def test_challenge_rejected_finalizes_event(self):
        """Rejected challenge finalizes the event."""
        self._register_report()

        self.bridge.on_custody_failure("sha256:" + "ab" * 32, "ep-1", 1)

        records = self.final_store.list_pending()
        event_id = records[-1].event_id

        self.bridge.on_challenge_rejected(event_id)

        event = self.final_store.get_event(event_id)
        assert event.finalization_state == EventFinalizationState.FINALIZED

    def test_different_endpoints_isolated(self):
        """Custody failures for one endpoint don't affect another."""
        self._register_report("ep-1")
        self._register_report("ep-2")

        self.bridge.on_custody_failure("sha256:" + "ab" * 32, "ep-1", 3)

        profile1 = self.rep_engine.get_profile("ENDPOINT", "ep-1")
        profile2 = self.rep_engine.get_profile("ENDPOINT", "ep-2")

        rel1 = profile1.accumulators.get("RELIABILITY")

        assert rel1 is not None
        assert rel1.effective_score < 0.5  # ep-1 penalized

        # ep-2 has no reputation events → profile is empty / None
        assert profile2 is None or profile2.accumulators.get("RELIABILITY") is None

    def test_severity_escalates_with_streak(self):
        """Higher failure streaks produce CRITICAL severity events."""
        self._register_report()

        # Low streak → MODERATE
        self.bridge.on_custody_failure("sha256:" + "ab" * 32, "ep-1", 1)
        self.bridge.on_custody_failure("sha256:" + "cd" * 32, "ep-1", 2)

        # High streak → CRITICAL
        self.bridge.on_custody_failure("sha256:" + "ef" * 32, "ep-1", 3)

        profile = self.rep_engine.get_profile("ENDPOINT", "ep-1")
        rel = profile.accumulators.get("RELIABILITY")
        assert rel is not None
        assert rel.event_count == 3
        # CRITICAL events should weigh more heavily
        assert rel.effective_score < 0.5
