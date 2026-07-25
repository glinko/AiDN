"""Integration tests: Validator Selection + Reputation Engine (M5 Phase 2).

Tests that the selection policy can consume reputation scores
from the ReputationEngine and use them for validator qualification
and ranking.
"""

import pytest

from aidn_hypervisor.reputation_engine.store import ReputationStore
from aidn_hypervisor.reputation_engine.engine import ReputationEngine
from aidn_hypervisor.reputation_engine.models import ReputationEvent
from aidn_hypervisor.validation.selection import (
    ValidatorQualificationCriteria,
    ValidatorCandidate,
    ValidatorSelectionPolicy,
)


class TestSelectionWithReputationEngine:
    """Selection policy integrated with reputation engine."""

    def setup_method(self):
        self.rep_store = ReputationStore()
        self.rep_engine = ReputationEngine(self.rep_store)
        self.criteria = ValidatorQualificationCriteria(
            minimum_bond_q=50.0,
            minimum_reputation_score=0.55,
            minimum_reputation_confidence=0.4,
        )
        self.policy = ValidatorSelectionPolicy(self.criteria)

    def _build_history(self, validator_id: str, positive: int, negative: int):
        """Build reputation history for a validator."""
        for _ in range(positive):
            self.rep_engine.ingest_event(ReputationEvent(
                subject_type="HYPERVISOR",
                subject_id=validator_id,
                profile_dimension="AVAILABILITY",
                event_class="AVAILABILITY_EVENT",
                direction="POSITIVE",
                severity="MODERATE",
                evidence_confidence="MULTI_SOURCE",
            ))
        for _ in range(negative):
            self.rep_engine.ingest_event(ReputationEvent(
                subject_type="HYPERVISOR",
                subject_id=validator_id,
                profile_dimension="AVAILABILITY",
                event_class="PROTOCOL_EVENT",
                direction="NEGATIVE",
                severity="MODERATE",
                evidence_confidence="MULTI_SOURCE",
            ))

    def test_reputation_score_from_engine(self):
        """Reputation engine produces usable scores."""
        self._build_history("validator-1", positive=30, negative=2)
        profile = self.rep_engine.get_profile("HYPERVISOR", "validator-1")
        avail = profile.accumulators.get("AVAILABILITY")
        assert avail is not None
        assert avail.effective_score > 0.5
        assert avail.confidence > 0.3

    def test_candidate_with_reputation_beats_without(self):
        """Validator with good reputation ranks higher."""
        # Build reputation for v1
        self._build_history("v1", positive=25, negative=1)
        profile1 = self.rep_engine.get_profile("HYPERVISOR", "v1")
        score1 = profile1.accumulators["AVAILABILITY"].effective_score
        conf1 = profile1.accumulators["AVAILABILITY"].confidence

        candidates = [
            ValidatorCandidate(
                validator_id="v1", bond_q=100.0,
                reputation_score=score1,
                reputation_confidence=conf1,
            ),
            ValidatorCandidate(
                validator_id="v2", bond_q=100.0,
                # no reputation data
            ),
        ]

        result = self.policy.select(
            candidates, seed="test", required_count=1,
            weight_by_reputation=True,
        )
        assert result.selected[0].validator_id == "v1"

    def test_bad_reputation_disqualifies(self):
        """Validator with bad reputation is disqualified."""
        self._build_history("bad-validator", positive=2, negative=25)
        profile = self.rep_engine.get_profile("HYPERVISOR", "bad-validator")
        score = profile.accumulators["AVAILABILITY"].effective_score
        conf = profile.accumulators["AVAILABILITY"].confidence

        candidates = [
            ValidatorCandidate(
                validator_id="good-validator", bond_q=100.0,
                reputation_score=0.8, reputation_confidence=0.7,
            ),
            ValidatorCandidate(
                validator_id="bad-validator", bond_q=100.0,
                reputation_score=score, reputation_confidence=conf,
            ),
        ]

        result = self.policy.select(
            candidates, seed="test", required_count=1,
        )
        assert result.selected[0].validator_id == "good-validator"
        assert any(
            d.validator_id == "bad-validator" for d in result.disqualified
        )

    def test_multi_dimension_reputation(self):
        """Selection can use multi-dimensional reputation scores."""
        # Build reputation across multiple dimensions
        self._build_history("multi-v", positive=20, negative=1)

        # Also add protocol compliance events
        for _ in range(15):
            self.rep_engine.ingest_event(ReputationEvent(
                subject_type="HYPERVISOR",
                subject_id="multi-v",
                profile_dimension="PROTOCOL_COMPLIANCE",
                event_class="PROTOCOL_EVENT",
                direction="POSITIVE",
                severity="MODERATE",
                evidence_confidence="MULTI_SOURCE",
            ))

        profile = self.rep_engine.get_profile("HYPERVISOR", "multi-v")
        avail_score = profile.accumulators["AVAILABILITY"].effective_score
        proto_score = profile.accumulators["PROTOCOL_COMPLIANCE"].effective_score

        # Use average of dimensions as overall score
        overall_score = (avail_score + proto_score) / 2
        overall_conf = max(
            profile.accumulators["AVAILABILITY"].confidence,
            profile.accumulators["PROTOCOL_COMPLIANCE"].confidence,
        )

        candidates = [
            ValidatorCandidate(
                validator_id="multi-v", bond_q=100.0,
                reputation_score=overall_score,
                reputation_confidence=overall_conf,
            ),
            ValidatorCandidate(
                validator_id="single-v", bond_q=100.0,
                reputation_score=0.6, reputation_confidence=0.5,
            ),
        ]

        result = self.policy.select(
            candidates, seed="test", required_count=1,
            weight_by_reputation=True,
        )
        assert result.selected[0].validator_id == "multi-v"

    def test_insufficient_confidence_disqualifies(self):
        """New validator with no history is disqualified by confidence gate."""
        # New validator — profile exists but has low confidence
        self.rep_engine.get_or_create_profile("HYPERVISOR", "new-v")
        profile = self.rep_engine.get_profile("HYPERVISOR", "new-v")
        avail = profile.accumulators.get("AVAILABILITY")

        candidates = [
            ValidatorCandidate(
                validator_id="experienced-v", bond_q=100.0,
                reputation_score=0.7, reputation_confidence=0.7,
            ),
            ValidatorCandidate(
                validator_id="new-v", bond_q=100.0,
                reputation_score=avail.effective_score if avail else 0.5,
                reputation_confidence=avail.confidence if avail else 0.0,
            ),
        ]

        result = self.policy.select(
            candidates, seed="test", required_count=1,
        )
        assert result.selected[0].validator_id == "experienced-v"
        assert any(
            d.validator_id == "new-v" for d in result.disqualified
        )

    def test_reputation_recovery_allows_re_selection(self):
        """Validator who improved reputation can be re-selected."""
        # Start with bad reputation
        self._build_history("recovering-v", positive=2, negative=20)
        bad_profile = self.rep_engine.get_profile("HYPERVISOR", "recovering-v")
        bad_score = bad_profile.accumulators["AVAILABILITY"].effective_score
        bad_conf = bad_profile.accumulators["AVAILABILITY"].confidence

        # Should be disqualified
        candidates = [
            ValidatorCandidate(
                validator_id="good-v", bond_q=100.0,
                reputation_score=0.7, reputation_confidence=0.7,
            ),
            ValidatorCandidate(
                validator_id="recovering-v", bond_q=100.0,
                reputation_score=bad_score,
                reputation_confidence=bad_conf,
            ),
        ]
        result = self.policy.select(candidates, seed="test", required_count=1)
        assert result.selected[0].validator_id == "good-v"

        # Now add lots of positive events (recovery)
        self._build_history("recovering-v", positive=50, negative=0)
        good_profile = self.rep_engine.get_profile("HYPERVISOR", "recovering-v")
        good_score = good_profile.accumulators["AVAILABILITY"].effective_score
        good_conf = good_profile.accumulators["AVAILABILITY"].confidence

        # Now should qualify
        candidates[1] = ValidatorCandidate(
            validator_id="recovering-v", bond_q=100.0,
            reputation_score=good_score,
            reputation_confidence=good_conf,
        )
        result = self.policy.select(
            candidates, seed="test", required_count=1,
            weight_by_reputation=True,
        )
        # recovering-v should now rank higher due to improved score
        assert result.selected[0].validator_id == "recovering-v"
