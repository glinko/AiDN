"""Tests for Reputation Engine models (RFC-0041 Phase 1)."""

import pytest
from datetime import datetime, timezone

from aidn_hypervisor.reputation_engine.models import (
    ReputationProfileType,
    ReputationDimension,
    ReputationEventDirection,
    ReputationEventSeverity,
    EvidenceConfidenceClass,
    ReputationEventClass,
    ReputationProfileState,
    ReputationSubject,
    ReputationDimensionAccumulator,
    ReputationDimensionScore,
    ReputationProfile,
    ReputationEvent,
    ProfileDimensionWeight,
)


class TestReputationProfileType:
    def test_all_profile_types_exist(self):
        assert "HYPERVISOR" in ReputationProfileType.__args__
        assert "ENDPOINT" in ReputationProfileType.__args__
        assert "CONSENSUS_SERVICE" in ReputationProfileType.__args__
        assert "REGISTRY_SERVICE" in ReputationProfileType.__args__
        assert "VALIDATION_SERVICE" in ReputationProfileType.__args__

    def test_hypervisor_profile_type(self):
        assert "HYPERVISOR" == ReputationProfileType.__args__[0]


class TestReputationDimension:
    def test_common_dimensions_exist(self):
        expected = {
            "AVAILABILITY",
            "RELIABILITY",
            "PROTOCOL_COMPLIANCE",
            "ACCOUNTING_CONSISTENCY",
            "EVIDENCE_INTEGRITY",
            "RECOVERY_RELIABILITY",
        }
        assert expected.issubset({d for d in ReputationDimension.__args__})

    def test_endpoint_dimensions_exist(self):
        assert "CERTIFICATION_HISTORY" in ReputationDimension.__args__
        assert "VALIDATION_REPORT_AVAILABILITY" in ReputationDimension.__args__


class TestReputationEventDirection:
    def test_directions_exist(self):
        assert "POSITIVE" in ReputationEventDirection.__args__
        assert "NEGATIVE" in ReputationEventDirection.__args__
        assert "NEUTRAL" in ReputationEventDirection.__args__


class TestReputationEventSeverity:
    def test_severity_levels_exist(self):
        expected = {
            "INFORMATIONAL",
            "MINOR",
            "MODERATE",
            "MAJOR",
            "CRITICAL",
        }
        assert expected.issubset({s for s in ReputationEventSeverity.__args__})


class TestEvidenceConfidenceClass:
    def test_confidence_classes_exist(self):
        expected = {
            "FINALIZED_PROTOCOL",
            "CRYPTOGRAPHIC",
            "REPRODUCIBLE",
            "MULTI_SOURCE",
            "STATISTICAL",
            "OBSERVATIONAL",
            "SUBJECTIVE",
        }
        assert expected.issubset({c for c in EvidenceConfidenceClass.__args__})


class TestReputationEventClass:
    def test_event_classes_exist(self):
        expected = {
            "AVAILABILITY_EVENT",
            "EXECUTION_EVENT",
            "PROTOCOL_EVENT",
            "ACCOUNTING_EVENT",
            "EVIDENCE_EVENT",
            "RECOVERY_EVENT",
            "CERTIFICATION_EVENT",
            "SECURITY_EVENT",
        }
        assert expected.issubset({e for e in ReputationEventClass.__args__})


class TestReputationProfileState:
    def test_states_exist(self):
        expected = {
            "INSUFFICIENT_DATA",
            "ESTABLISHING",
            "NORMAL",
            "WATCH",
            "DEGRADED",
            "CRITICAL",
            "DISQUALIFIED",
            "RETIRED",
        }
        assert expected.issubset({s for s in ReputationProfileState.__args__})


class TestReputationSubject:
    def test_create_hypervisor_subject(self):
        subj = ReputationSubject(
            subject_type="HYPERVISOR",
            subject_id="node-1",
            owner_reference="wallet-1",
        )
        assert subj.subject_type == "HYPERVISOR"
        assert subj.subject_id == "node-1"

    def test_create_endpoint_subject(self):
        subj = ReputationSubject(
            subject_type="ENDPOINT",
            subject_id="ep-1",
            owner_reference="wallet-1",
        )
        assert subj.subject_type == "ENDPOINT"

    def test_default_profile_version(self):
        subj = ReputationSubject(
            subject_type="HYPERVISOR",
            subject_id="node-1",
        )
        assert subj.profile_version == "reputation.v1"


class TestReputationDimensionAccumulator:
    def test_new_accumulator_has_prior(self):
        acc = ReputationDimensionAccumulator(dimension="AVAILABILITY")
        assert acc.positive_mass == 0.0
        assert acc.negative_mass == 0.0
        assert acc.event_count == 0

    def test_add_positive_mass(self):
        acc = ReputationDimensionAccumulator(dimension="AVAILABILITY")
        acc.add_mass(positive=0.5)
        assert acc.positive_mass == 0.5
        assert acc.negative_mass == 0.0
        assert acc.event_count == 1

    def test_add_negative_mass(self):
        acc = ReputationDimensionAccumulator(dimension="AVAILABILITY")
        acc.add_mass(negative=0.3)
        assert acc.positive_mass == 0.0
        assert acc.negative_mass == 0.3
        assert acc.event_count == 1

    def test_add_both_masses(self):
        acc = ReputationDimensionAccumulator(dimension="AVAILABILITY")
        acc.add_mass(positive=0.4, negative=0.2)
        assert acc.positive_mass == 0.4
        assert acc.negative_mass == 0.2
        assert acc.event_count == 1

    def test_total_mass(self):
        acc = ReputationDimensionAccumulator(dimension="AVAILABILITY")
        acc.add_mass(positive=0.5)
        acc.add_mass(negative=0.3)
        assert acc.total_mass == 0.8

    def test_raw_score_no_evidence(self):
        """Prior = 0.5 when no evidence."""
        acc = ReputationDimensionAccumulator(dimension="AVAILABILITY")
        assert acc.raw_score == pytest.approx(0.5, abs=0.01)

    def test_raw_score_all_positive(self):
        acc = ReputationDimensionAccumulator(dimension="AVAILABILITY")
        acc.add_mass(positive=1.0)
        assert acc.raw_score > 0.5

    def test_raw_score_all_negative(self):
        acc = ReputationDimensionAccumulator(dimension="AVAILABILITY")
        acc.add_mass(negative=1.0)
        assert acc.raw_score < 0.5

    def test_raw_score_balanced(self):
        acc = ReputationDimensionAccumulator(dimension="AVAILABILITY")
        acc.add_mass(positive=0.5)
        acc.add_mass(negative=0.5)
        assert acc.raw_score == pytest.approx(0.5, abs=0.01)


class TestReputationDimensionScore:
    def test_new_score_is_neutral_prior(self):
        ds = ReputationDimensionScore(dimension="AVAILABILITY")
        assert ds.effective_score == pytest.approx(0.5, abs=0.01)
        assert ds.confidence == 0.0
        assert ds.state == "INSUFFICIENT_DATA"

    def test_score_clamped_0_1(self):
        ds = ReputationDimensionScore(dimension="AVAILABILITY")
        assert 0.0 <= ds.effective_score <= 1.0

    def test_confidence_clamped_0_1(self):
        ds = ReputationDimensionScore(dimension="AVAILABILITY")
        assert 0.0 <= ds.confidence <= 1.0


class TestReputationProfile:
    def test_new_profile_state(self):
        profile = ReputationProfile(
            subject=ReputationSubject(
                subject_type="HYPERVISOR",
                subject_id="node-1",
            ),
            profile_type="HYPERVISOR",
        )
        assert profile.state == "INSUFFICIENT_DATA"
        assert profile.profile_version == "reputation.v1"

    def test_profile_has_dimensions(self):
        profile = ReputationProfile(
            subject=ReputationSubject(
                subject_type="HYPERVISOR",
                subject_id="node-1",
            ),
            profile_type="HYPERVISOR",
        )
        assert len(profile.dimension_scores) > 0

    def test_profile_created_at(self):
        profile = ReputationProfile(
            subject=ReputationSubject(
                subject_type="HYPERVISOR",
                subject_id="node-1",
            ),
            profile_type="HYPERVISOR",
        )
        assert profile.created_at is not None
        assert profile.last_updated_at is not None


class TestReputationEvent:
    def test_create_positive_event(self):
        evt = ReputationEvent(
            subject_type="HYPERVISOR",
            subject_id="node-1",
            profile_dimension="AVAILABILITY",
            event_class="AVAILABILITY_EVENT",
            direction="POSITIVE",
            severity="MINOR",
            evidence_confidence="OBSERVATIONAL",
            source_type="session_failure",
            source_reference="sess-1",
        )
        assert evt.direction == "POSITIVE"
        assert evt.event_id is not None

    def test_event_has_timestamp(self):
        evt = ReputationEvent(
            subject_type="ENDPOINT",
            subject_id="ep-1",
            profile_dimension="RELIABILITY",
            event_class="EXECUTION_EVENT",
            direction="NEGATIVE",
            severity="MODERATE",
            evidence_confidence="CRYPTOGRAPHIC",
        )
        assert evt.observed_at is not None

    def test_event_neutral_direction(self):
        evt = ReputationEvent(
            subject_type="HYPERVISOR",
            subject_id="node-1",
            profile_dimension="AVAILABILITY",
            event_class="AVAILABILITY_EVENT",
            direction="NEUTRAL",
            severity="INFORMATIONAL",
            evidence_confidence="OBSERVATIONAL",
        )
        assert evt.direction == "NEUTRAL"


class TestProfileDimensionWeight:
    def test_hypervisor_weights_exist(self):
        weights = ProfileDimensionWeight.get_weights("HYPERVISOR")
        assert len(weights) > 0
        # All weights should be positive
        for w in weights.values():
            assert w > 0

    def test_endpoint_weights_exist(self):
        weights = ProfileDimensionWeight.get_weights("ENDPOINT")
        assert len(weights) > 0

    def test_default_weights_exist(self):
        weights = ProfileDimensionWeight.get_weights("UNKNOWN_TYPE")
        assert len(weights) > 0

    def test_availability_weight_positive(self):
        weights = ProfileDimensionWeight.get_weights("HYPERVISOR")
        assert "AVAILABILITY" in weights
        assert weights["AVAILABILITY"] > 0

    def test_evidence_integrity_is_critical(self):
        """Evidence Integrity must be a critical dimension (RFC-0041 §12)."""
        weights = ProfileDimensionWeight.get_weights("HYPERVISOR")
        assert "EVIDENCE_INTEGRITY" in weights
        # Critical dimension should have meaningful weight
        assert weights["EVIDENCE_INTEGRITY"] >= weights.get("AVAILABILITY", 1.0)
