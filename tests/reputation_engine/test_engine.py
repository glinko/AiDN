"""Tests for ReputationEngine (RFC-0041 Phase 1)."""

import pytest

from aidn_hypervisor.reputation_engine.models import (
    ReputationEvent,
    ReputationProfile,
)
from aidn_hypervisor.reputation_engine.store import ReputationStore
from aidn_hypervisor.reputation_engine.engine import ReputationEngine


def _make_event(
    *,
    subject_id: str = "node-1",
    dimension: str = "AVAILABILITY",
    direction: str = "POSITIVE",
    severity: str = "MINOR",
    evidence_confidence: str = "OBSERVATIONAL",
    event_class: str = "AVAILABILITY_EVENT",
    source_type: str = "test",
    source_reference: str = "test-ref",
) -> ReputationEvent:
    return ReputationEvent(
        subject_type="HYPERVISOR",
        subject_id=subject_id,
        profile_dimension=dimension,
        event_class=event_class,
        direction=direction,
        severity=severity,
        evidence_confidence=evidence_confidence,
        source_type=source_type,
        source_reference=source_reference,
    )


class TestReputationEngineBasics:
    def _engine(self) -> ReputationEngine:
        return ReputationEngine(ReputationStore())

    def test_new_engine_creates_profile(self):
        engine = self._engine()
        profile = engine.get_or_create_profile("HYPERVISOR", "node-1")
        assert profile is not None
        assert profile.profile_type == "HYPERVISOR"

    def test_profile_starts_insufficient_data(self):
        engine = self._engine()
        profile = engine.get_or_create_profile("HYPERVISOR", "node-1")
        assert profile.state == "INSUFFICIENT_DATA"

    def test_ingest_positive_event(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")
        evt = _make_event(direction="POSITIVE")
        engine.ingest_event(evt)

        profile = engine.get_profile("HYPERVISOR", "node-1")
        assert profile is not None
        # Positive event should increase availability score above prior
        avail = profile.accumulators["AVAILABILITY"]
        assert avail.effective_score > 0.5

    def test_ingest_negative_event(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")
        evt = _make_event(direction="NEGATIVE")
        engine.ingest_event(evt)

        profile = engine.get_profile("HYPERVISOR", "node-1")
        avail = profile.accumulators["AVAILABILITY"]
        assert avail.effective_score < 0.5

    def test_ingest_auto_creates_profile(self):
        engine = self._engine()
        evt = _make_event()
        engine.ingest_event(evt)

        profile = engine.get_profile("HYPERVISOR", "node-1")
        assert profile is not None


class TestScoringProgression:
    def _engine(self) -> ReputationEngine:
        return ReputationEngine(ReputationStore())

    def test_many_positive_events_increase_score(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        for _ in range(20):
            engine.ingest_event(_make_event(direction="POSITIVE", severity="MODERATE", evidence_confidence="MULTI_SOURCE"))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        avail = profile.accumulators["AVAILABILITY"]
        assert avail.effective_score > 0.6
        assert avail.confidence > 0.3

    def test_many_negative_events_decrease_score(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        for _ in range(20):
            engine.ingest_event(_make_event(direction="NEGATIVE", severity="MODERATE", evidence_confidence="MULTI_SOURCE"))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        avail = profile.accumulators["AVAILABILITY"]
        assert avail.effective_score < 0.35

    def test_mixed_events_balance(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        for _ in range(10):
            engine.ingest_event(_make_event(direction="POSITIVE"))
        for _ in range(10):
            engine.ingest_event(_make_event(direction="NEGATIVE"))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        avail = profile.accumulators["AVAILABILITY"]
        # Should be near 0.5 (balanced)
        assert 0.4 < avail.effective_score < 0.6

    def test_critical_event_has_more_impact(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        engine.ingest_event(_make_event(direction="NEGATIVE", severity="CRITICAL", evidence_confidence="CRYPTOGRAPHIC"))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        avail = profile.accumulators["AVAILABILITY"]
        # Critical + cryptographic should have significant negative impact
        assert avail.negative_mass >= 1.5  # 2.0 * 0.9 = 1.8


class TestProfileStateDerivation:
    def _engine(self) -> ReputationEngine:
        return ReputationEngine(ReputationStore())

    def test_insufficient_data_initial(self):
        engine = self._engine()
        profile = engine.get_or_create_profile("HYPERVISOR", "node-1")
        assert profile.state == "INSUFFICIENT_DATA"

    def test_establishing_after_few_events(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        for _ in range(3):
            engine.ingest_event(_make_event(direction="POSITIVE"))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        # Low confidence = ESTABLISHING
        assert profile.state in {"INSUFFICIENT_DATA", "ESTABLISHING"}

    def test_normal_after_many_positive(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        # Feed all 6 hypervisor dimensions with strong positive evidence
        for dim in ["AVAILABILITY", "RELIABILITY", "PROTOCOL_COMPLIANCE",
                    "ACCOUNTING_CONSISTENCY", "EVIDENCE_INTEGRITY", "RECOVERY_RELIABILITY"]:
            for _ in range(15):
                engine.ingest_event(_make_event(
                    dimension=dim,
                    direction="POSITIVE",
                    severity="MODERATE",
                    evidence_confidence="MULTI_SOURCE",
                    event_class="AVAILABILITY_EVENT",
                ))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        assert profile.state == "NORMAL"

    def test_degraded_after_critical_events(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        for _ in range(25):
            engine.ingest_event(_make_event(direction="NEGATIVE", severity="CRITICAL", evidence_confidence="FINALIZED_PROTOCOL"))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        assert profile.state in {"DEGRADED", "CRITICAL"}


class TestAdvisoryScore:
    def _engine(self) -> ReputationEngine:
        return ReputationEngine(ReputationStore())

    def test_advisory_score_initial(self):
        engine = self._engine()
        profile = engine.get_or_create_profile("HYPERVISOR", "node-1")
        assert profile.advisory_overall_score == pytest.approx(0.5, abs=0.05)

    def test_advisory_score_increases_with_positive(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        for _ in range(20):
            engine.ingest_event(_make_event(direction="POSITIVE", severity="MODERATE"))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        assert profile.advisory_overall_score > 0.5

    def test_advisory_score_decreases_with_negative(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        for _ in range(20):
            engine.ingest_event(_make_event(direction="NEGATIVE", severity="MODERATE"))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        assert profile.advisory_overall_score < 0.5

    def test_tier_a_for_high_score(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        # Feed all dimensions with strong, high-confidence evidence
        for dim in ["AVAILABILITY", "RELIABILITY", "PROTOCOL_COMPLIANCE",
                    "ACCOUNTING_CONSISTENCY", "EVIDENCE_INTEGRITY", "RECOVERY_RELIABILITY"]:
            for _ in range(40):
                engine.ingest_event(_make_event(
                    dimension=dim,
                    direction="POSITIVE",
                    severity="MODERATE",
                    evidence_confidence="REPRODUCIBLE",
                    event_class="AVAILABILITY_EVENT",
                ))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        # Reproducible (0.75) × 40 events × 0.6 severity = 18 mass → high confidence
        assert profile.tier == "A"

    def test_tier_d_for_low_score(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        for _ in range(50):
            engine.ingest_event(_make_event(direction="NEGATIVE", severity="MODERATE"))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        assert profile.tier == "D"


class TestMultiDimension:
    def _engine(self) -> ReputationEngine:
        return ReputationEngine(ReputationStore())

    def test_different_dimensions_independent(self):
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        # Positive for availability (use higher confidence for measurable effect)
        for _ in range(20):
            engine.ingest_event(_make_event(dimension="AVAILABILITY", direction="POSITIVE", severity="MODERATE", evidence_confidence="MULTI_SOURCE"))

        # Negative for reliability
        for _ in range(20):
            engine.ingest_event(_make_event(dimension="RELIABILITY", direction="NEGATIVE", severity="MODERATE", evidence_confidence="MULTI_SOURCE", event_class="EXECUTION_EVENT"))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        avail = profile.accumulators["AVAILABILITY"]
        reliab = profile.accumulators["RELIABILITY"]

        # MULTI_SOURCE (0.6) × MODERATE (0.6) × 20 = 7.2 mass → confidence 0.72
        assert avail.effective_score > 0.6
        assert reliab.effective_score < 0.4

    def test_critical_dimension_caps_overall(self):
        """RFC-0041 §16: low Evidence Integrity should cap overall score."""
        engine = self._engine()
        engine.get_or_create_profile("HYPERVISOR", "node-1")

        # All dimensions positive
        for dim in ["AVAILABILITY", "RELIABILITY", "PROTOCOL_COMPLIANCE", "ACCOUNTING_CONSISTENCY", "RECOVERY_RELIABILITY"]:
            for _ in range(20):
                engine.ingest_event(_make_event(dimension=dim, direction="POSITIVE", severity="MODERATE"))

        # But Evidence Integrity is terrible
        for _ in range(30):
            engine.ingest_event(_make_event(dimension="EVIDENCE_INTEGRITY", direction="NEGATIVE", severity="CRITICAL", evidence_confidence="FINALIZED_PROTOCOL", event_class="EVIDENCE_EVENT"))

        profile = engine.get_profile("HYPERVISOR", "node-1")
        # Overall should be capped despite other dimensions being good
        assert profile.advisory_overall_score < 0.7
