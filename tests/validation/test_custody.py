"""M5 Phase 3: Validation Report Custody — grace periods, retention, challenges.

RFC-0041 §69A: Endpoint custody Reputation SHALL distinguish:
- one temporary retrieval outage (affects Health only)
- repeated unavailability (reduces report availability confidence)
- report loss after migration (reduces retention reliability)
- deliberate withholding (strong negative disclosure event)
- content hash failure (critical integrity event)
- successful restoration (repairs availability without erasing history)

RFC-0041 §102: Event Finalization Delay — confirmation/challenge period.
RFC-0041 §103: Event Challenge — participant may challenge processing errors.
RFC-0041 §104: Corrections — new correction event, not silent rewrite.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from aidn_hypervisor.validation.custody import (
    CustodyConfig,
    CustodyCheckResult,
    CustodyStatus,
    CustodyState,
    CustodyStore,
    CustodyService,
    Challenge,
    ChallengeOutcome,
    ChallengeState,
    Correction,
    EventFinalizationState,
    ReputationEventRecord,
    FinalizationStore,
    FinalizationService,
)


# ---------------------------------------------------------------------------
# CustodyConfig
# ---------------------------------------------------------------------------

class TestCustodyConfig:
    def test_defaults(self):
        cfg = CustodyConfig()
        assert cfg.grace_period_seconds > 0
        assert cfg.minimum_retention_seconds > 0
        assert cfg.max_failure_streak > 0
        assert cfg.check_interval_seconds > 0

    def test_custom_values(self):
        cfg = CustodyConfig(
            grace_period_seconds=600,
            minimum_retention_seconds=86400,
            max_failure_streak=10,
            check_interval_seconds=300,
        )
        assert cfg.grace_period_seconds == 600
        assert cfg.minimum_retention_seconds == 86400
        assert cfg.max_failure_streak == 10

    def test_rejects_negative_grace(self):
        with pytest.raises(ValueError):
            CustodyConfig(grace_period_seconds=-1)

    def test_rejects_zero_retention(self):
        with pytest.raises(ValueError):
            CustodyConfig(minimum_retention_seconds=0)


# ---------------------------------------------------------------------------
# CustodyState
# ---------------------------------------------------------------------------

class TestCustodyState:
    def test_initial_state(self):
        state = CustodyState(
            report_hash="sha256:" + "ab" * 32,
            endpoint_id="ep-1",
            stored_at=datetime.now(timezone.utc),
        )
        assert state.status == "available"
        assert state.failure_streak == 0
        assert state.grace_expires_at is None

    def test_mark_unavailable_starts_grace(self):
        state = CustodyState(
            report_hash="sha256:" + "ab" * 32,
            endpoint_id="ep-1",
            stored_at=datetime.now(timezone.utc),
        )
        state.mark_unavailable()
        assert state.status == "grace_period"
        assert state.grace_expires_at is not None
        assert state.failure_streak == 1

    def test_mark_unavailable_during_grace_increases_streak(self):
        state = CustodyState(
            report_hash="sha256:" + "ab" * 32,
            endpoint_id="ep-1",
            stored_at=datetime.now(timezone.utc),
        )
        state.mark_unavailable()
        # Simulate grace still active
        state.grace_expires_at = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()
        state.mark_unavailable()
        assert state.status == "grace_period"
        assert state.failure_streak == 2

    def test_mark_available_resets_streak(self):
        state = CustodyState(
            report_hash="sha256:" + "ab" * 32,
            endpoint_id="ep-1",
            stored_at=datetime.now(timezone.utc),
        )
        state.mark_unavailable()
        state.mark_unavailable()
        assert state.failure_streak == 2
        state.mark_available()
        assert state.failure_streak == 0
        assert state.status == "available"

    def test_grace_expired_detected(self):
        state = CustodyState(
            report_hash="sha256:" + "ab" * 32,
            endpoint_id="ep-1",
            stored_at=datetime.now(timezone.utc),
        )
        state.mark_unavailable()
        # Force grace expiry
        state.grace_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        assert state.check_grace_expired()

    def test_restoration_preserves_history(self):
        state = CustodyState(
            report_hash="sha256:" + "ab" * 32,
            endpoint_id="ep-1",
            stored_at=datetime.now(timezone.utc),
        )
        state.mark_unavailable()
        state.mark_unavailable()
        state._status = CustodyStatus.CUSTODY_FAILED  # simulate grace expiry
        total_failures = state.total_failure_count
        state.mark_available()
        assert state.status == CustodyStatus.AVAILABLE
        assert state.failure_streak == 0
        # total failures preserved
        assert state.total_failure_count == total_failures


# ---------------------------------------------------------------------------
# CustodyStore
# ---------------------------------------------------------------------------

class TestCustodyStore:
    def test_add_and_get(self):
        store = CustodyStore()
        state = CustodyState(
            report_hash="sha256:" + "ab" * 32,
            endpoint_id="ep-1",
            stored_at=datetime.now(timezone.utc),
        )
        store.add(state)
        retrieved = store.get("sha256:" + "ab" * 32)
        assert retrieved is state

    def test_get_missing(self):
        store = CustodyStore()
        assert store.get("sha256:" + "cd" * 32) is None

    def test_list_by_endpoint(self):
        store = CustodyStore()
        store.add(CustodyState(
            report_hash="sha256:" + "aa" * 32,
            endpoint_id="ep-1",
            stored_at=datetime.now(timezone.utc),
        ))
        store.add(CustodyState(
            report_hash="sha256:" + "bb" * 32,
            endpoint_id="ep-2",
            stored_at=datetime.now(timezone.utc),
        ))
        store.add(CustodyState(
            report_hash="sha256:" + "cc" * 32,
            endpoint_id="ep-1",
            stored_at=datetime.now(timezone.utc),
        ))
        ep1_reports = store.list_by_endpoint("ep-1")
        assert len(ep1_reports) == 2

    def test_remove(self):
        store = CustodyStore()
        store.add(CustodyState(
            report_hash="sha256:" + "ab" * 32,
            endpoint_id="ep-1",
            stored_at=datetime.now(timezone.utc),
        ))
        store.remove("sha256:" + "ab" * 32)
        assert store.get("sha256:" + "ab" * 32) is None

    def test_clear(self):
        store = CustodyStore()
        store.add(CustodyState(
            report_hash="sha256:" + "ab" * 32,
            endpoint_id="ep-1",
            stored_at=datetime.now(timezone.utc),
        ))
        store.clear()
        assert store.get("sha256:" + "ab" * 32) is None


# ---------------------------------------------------------------------------
# CustodyService
# ---------------------------------------------------------------------------

class TestCustodyService:
    def _make_cfg(self, **kw):
        defaults = {
            "grace_period_seconds": 60,
            "minimum_retention_seconds": 3600,
            "max_failure_streak": 5,
            "check_interval_seconds": 10,
        }
        defaults.update(kw)
        return CustodyConfig(**defaults)

    def setup_method(self):
        self.store = CustodyStore()
        self.cfg = self._make_cfg()
        self.svc = CustodyService(self.store, self.cfg)

    def _add_report(self, report_hash, endpoint_id="ep-1"):
        self.store.add(CustodyState(
            report_hash=report_hash,
            endpoint_id=endpoint_id,
            stored_at=datetime.now(timezone.utc),
        ))

    def test_check_available_report(self):
        self._add_report("sha256:" + "ab" * 32)
        result = self.svc.check_custody("sha256:" + "ab" * 32, available=True)
        assert result.status == "available"
        assert result.action == "none"

    def test_check_unavailable_starts_grace(self):
        self._add_report("sha256:" + "ab" * 32)
        result = self.svc.check_custody("sha256:" + "ab" * 32, available=False)
        assert result.status == "grace_period"
        assert result.action == "start_grace"

    def test_check_during_grace_returns_grace(self):
        self._add_report("sha256:" + "ab" * 32)
        self.svc.check_custody("sha256:" + "ab" * 32, available=False)
        result = self.svc.check_custody("sha256:" + "ab" * 32, available=False)
        assert result.status == "grace_period"
        assert result.action == "continue_grace"

    def test_check_after_grace_expiry_returns_failed(self):
        self._add_report("sha256:" + "ab" * 32)
        self.svc.check_custody("sha256:" + "ab" * 32, available=False)
        # Force grace expiry
        state = self.store.get("sha256:" + "ab" * 32)
        state.grace_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        result = self.svc.check_custody("sha256:" + "ab" * 32, available=False)
        assert result.status == "custody_failed"
        assert result.action == "emit_penalty"

    def test_check_restoration_after_failure(self):
        self._add_report("sha256:" + "ab" * 32)
        self.svc.check_custody("sha256:" + "ab" * 32, available=False)
        state = self.store.get("sha256:" + "ab" * 32)
        state.grace_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        self.svc.check_custody("sha256:" + "ab" * 32, available=False)
        # Now restore
        result = self.svc.check_custody("sha256:" + "ab" * 32, available=True)
        assert result.status == "available"
        assert result.action == "restore"

    def test_sweep_expires_grace_periods(self):
        self._add_report("sha256:" + "ab" * 32)
        self.svc.check_custody("sha256:" + "ab" * 32, available=False)
        state = self.store.get("sha256:" + "ab" * 32)
        state.grace_expires_at = (
            datetime.now(timezone.utc) - timedelta(seconds=1)
        ).isoformat()
        swept = self.svc.sweep()
        assert swept >= 1

    def test_sweep_respects_active_grace(self):
        self._add_report("sha256:" + "ab" * 32)
        self.svc.check_custody("sha256:" + "ab" * 32, available=False)
        # Grace still active
        swept = self.svc.sweep()
        assert swept == 0

    def test_retention_violation(self):
        self._add_report("sha256:" + "ab" * 32)
        state = self.store.get("sha256:" + "ab" * 32)
        # Store report long ago
        state.stored_at = (
            datetime.now(timezone.utc) - timedelta(days=10)
        ).isoformat()
        result = self.svc.check_retention("sha256:" + "ab" * 32)
        # Should be OK since we stored long ago and retention is 3600s
        assert result.ok

    def test_max_streak_cap(self):
        self._add_report("sha256:" + "ab" * 32)
        for _ in range(10):
            self.svc.check_custody("sha256:" + "ab" * 32, available=False)
            state = self.store.get("sha256:" + "ab" * 32)
            state.grace_expires_at = (
                datetime.now(timezone.utc) - timedelta(seconds=1)
            ).isoformat()
        state = self.store.get("sha256:" + "ab" * 32)
        assert state.failure_streak <= self.cfg.max_failure_streak


# ---------------------------------------------------------------------------
# Challenge models
# ---------------------------------------------------------------------------

class TestChallenge:
    def test_create_challenge(self):
        c = Challenge(
            challenge_id="ch-1",
            event_id="evt-1",
            challenger_id="node-1",
            reason="wrong_subject",
        )
        assert c.state == "pending"
        assert c.outcome is None

    def test_resolve_challenge_accepted(self):
        c = Challenge(
            challenge_id="ch-1",
            event_id="evt-1",
            challenger_id="node-1",
            reason="wrong_subject",
        )
        c.resolve(ChallengeOutcome.ACCEPTED, "Subject was indeed wrong")
        assert c.state == "resolved"
        assert c.outcome == ChallengeOutcome.ACCEPTED

    def test_resolve_challenge_rejected(self):
        c = Challenge(
            challenge_id="ch-1",
            event_id="evt-1",
            challenger_id="node-1",
            reason="wrong_subject",
        )
        c.resolve(ChallengeOutcome.REJECTED, "Evidence confirms original event")
        assert c.state == "resolved"
        assert c.outcome == ChallengeOutcome.REJECTED


# ---------------------------------------------------------------------------
# Correction models
# ---------------------------------------------------------------------------

class TestCorrection:
    def test_create_correction(self):
        corr = Correction(
            correction_id="corr-1",
            original_event_id="evt-1",
            error_class="wrong_subject",
            corrected_values={"subject_id": "correct-subject"},
        )
        assert corr.created_at is not None

    def test_correction_references_original(self):
        corr = Correction(
            correction_id="corr-1",
            original_event_id="evt-1",
            error_class="duplicate",
            corrected_values={},
        )
        assert corr.original_event_id == "evt-1"


# ---------------------------------------------------------------------------
# Event Finalization
# ---------------------------------------------------------------------------

class TestEventFinalizationState:
    def test_new_event_is_pending(self):
        evt = ReputationEventRecord(
            event_id="evt-1",
            subject_id="ep-1",
            dimension="AVAILABILITY",
            direction="NEGATIVE",
            score_delta=-0.1,
        )
        assert evt.finalization_state == EventFinalizationState.PENDING

    def test_pending_can_finalize(self):
        evt = ReputationEventRecord(
            event_id="evt-1",
            subject_id="ep-1",
            dimension="AVAILABILITY",
            direction="NEGATIVE",
            score_delta=-0.1,
        )
        evt.finalize()
        assert evt.finalization_state == EventFinalizationState.FINALIZED

    def test_pending_can_be_challenged(self):
        evt = ReputationEventRecord(
            event_id="evt-1",
            subject_id="ep-1",
            dimension="AVAILABILITY",
            direction="NEGATIVE",
            score_delta=-0.1,
        )
        evt.challenge("ch-1")
        assert evt.finalization_state == EventFinalizationState.CHALLENGED

    def test_finalized_cannot_be_challenged(self):
        evt = ReputationEventRecord(
            event_id="evt-1",
            subject_id="ep-1",
            dimension="AVAILABILITY",
            direction="NEGATIVE",
            score_delta=-0.1,
        )
        evt.finalize()
        with pytest.raises(ValueError):
            evt.challenge("ch-1")


class TestFinalizationService:
    def setup_method(self):
        self.store = FinalizationStore()
        self.svc = FinalizationService(self.store)

    def test_add_event(self):
        evt = ReputationEventRecord(
            event_id="evt-1",
            subject_id="ep-1",
            dimension="AVAILABILITY",
            direction="NEGATIVE",
            score_delta=-0.1,
        )
        self.svc.add_event(evt)
        assert self.svc.get_event("evt-1") is evt

    def test_finalize_event(self):
        evt = ReputationEventRecord(
            event_id="evt-1",
            subject_id="ep-1",
            dimension="AVAILABILITY",
            direction="NEGATIVE",
            score_delta=-0.1,
        )
        self.svc.add_event(evt)
        self.svc.finalize_event("evt-1")
        assert self.svc.get_event("evt-1").finalization_state == EventFinalizationState.FINALIZED

    def test_challenge_event(self):
        evt = ReputationEventRecord(
            event_id="evt-1",
            subject_id="ep-1",
            dimension="AVAILABILITY",
            direction="NEGATIVE",
            score_delta=-0.1,
        )
        self.svc.add_event(evt)
        self.svc.challenge_event("evt-1", "ch-1")
        assert self.svc.get_event("evt-1").finalization_state == EventFinalizationState.CHALLENGED

    def test_correct_event(self):
        evt = ReputationEventRecord(
            event_id="evt-1",
            subject_id="ep-1",
            dimension="AVAILABILITY",
            direction="NEGATIVE",
            score_delta=-0.1,
        )
        self.svc.add_event(evt)
        corr = Correction(
            correction_id="corr-1",
            original_event_id="evt-1",
            error_class="wrong_subject",
            corrected_values={"subject_id": "correct-subject"},
        )
        self.svc.apply_correction(corr)
        assert self.svc.get_correction("evt-1") is corr

    def test_sweep_finalizes_old_pending(self):
        evt = ReputationEventRecord(
            event_id="evt-1",
            subject_id="ep-1",
            dimension="AVAILABILITY",
            direction="NEGATIVE",
            score_delta=-0.1,
        )
        evt.created_at = (
            datetime.now(timezone.utc) - timedelta(hours=48)
        ).isoformat()
        self.svc.add_event(evt)
        swept = self.svc.sweep()
        assert swept >= 1
        assert self.svc.get_event("evt-1").finalization_state == EventFinalizationState.FINALIZED
