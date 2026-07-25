"""Tests for Validator Selection Policy (M5 Phase 2).

Covers:
- Validator qualification criteria (bond, reputation, uptime)
- Deterministic selection algorithm (seeded, reproducible)
- Reputation-weighted selection
- Price-aware selection
- Disqualification of unqualified validators
"""

import pytest
from aidn_hypervisor.validation.selection import (
    ValidatorQualificationCriteria,
    ValidatorCandidate,
    ValidatorSelectionPolicy,
    SelectionResult,
)


class TestValidatorQualificationCriteria:
    """Qualification criteria model."""

    def test_default_criteria(self):
        c = ValidatorQualificationCriteria()
        assert c.minimum_bond_q > 0
        assert c.minimum_reputation_score >= 0.0
        assert c.minimum_reputation_confidence >= 0.0

    def test_custom_thresholds(self):
        c = ValidatorQualificationCriteria(
            minimum_bond_q=500.0,
            minimum_reputation_score=0.7,
            minimum_reputation_confidence=0.5,
        )
        assert c.minimum_bond_q == 500.0
        assert c.minimum_reputation_score == 0.7
        assert c.minimum_reputation_confidence == 0.5

    def test_zero_bond_threshold(self):
        """Bond threshold of 0 means no bond requirement."""
        c = ValidatorQualificationCriteria(minimum_bond_q=0.0)
        assert c.minimum_bond_q == 0.0

    def test_requires_positive_bond(self):
        with pytest.raises(Exception):
            ValidatorQualificationCriteria(minimum_bond_q=-1.0)


class TestValidatorCandidate:
    """Candidate model."""

    def test_minimal_candidate(self):
        c = ValidatorCandidate(
            validator_id="v1",
            bond_q=100.0,
        )
        assert c.validator_id == "v1"
        assert c.bond_q == 100.0
        assert c.reputation_score is None
        assert c.reputation_confidence is None

    def test_full_candidate(self):
        c = ValidatorCandidate(
            validator_id="v1",
            bond_q=100.0,
            reputation_score=0.85,
            reputation_confidence=0.7,
            price_q=10.0,
        )
        assert c.reputation_score == 0.85
        assert c.price_q == 10.0


class TestValidatorSelectionPolicy:
    """Deterministic selection with qualification gates."""

    def setup_method(self):
        self.criteria = ValidatorQualificationCriteria(
            minimum_bond_q=50.0,
            minimum_reputation_score=0.5,
            minimum_reputation_confidence=0.3,
        )
        self.policy = ValidatorSelectionPolicy(self.criteria)

    # ── Qualification gates ──

    def test_disqualifies_low_bond(self):
        candidates = [
            ValidatorCandidate(validator_id="v1", bond_q=100.0),
            ValidatorCandidate(validator_id="v2", bond_q=10.0),  # below 50
        ]
        result = self.policy.select(candidates, seed="test", required_count=1)
        assert "v1" in [v.validator_id for v in result.selected]
        assert "v2" not in [v.validator_id for v in result.selected]
        assert "v2" in [v.validator_id for v in result.disqualified]

    def test_disqualifies_low_reputation(self):
        candidates = [
            ValidatorCandidate(
                validator_id="v1", bond_q=100.0,
                reputation_score=0.8, reputation_confidence=0.7,
            ),
            ValidatorCandidate(
                validator_id="v2", bond_q=100.0,
                reputation_score=0.3, reputation_confidence=0.7,  # below 0.5
            ),
        ]
        result = self.policy.select(candidates, seed="test", required_count=1)
        assert "v1" in [v.validator_id for v in result.selected]
        assert "v2" in [v.validator_id for v in result.disqualified]

    def test_disqualifies_low_confidence(self):
        """Low confidence reputation = insufficient data → disqualified."""
        candidates = [
            ValidatorCandidate(
                validator_id="v1", bond_q=100.0,
                reputation_score=0.8, reputation_confidence=0.7,
            ),
            ValidatorCandidate(
                validator_id="v2", bond_q=100.0,
                reputation_score=0.9, reputation_confidence=0.1,  # low confidence
            ),
        ]
        result = self.policy.select(candidates, seed="test", required_count=1)
        assert "v1" in [v.validator_id for v in result.selected]
        assert "v2" in [v.validator_id for v in result.disqualified]

    def test_passes_candidate_without_reputation(self):
        """No reputation data = passes bond check only (neutral prior)."""
        candidates = [
            ValidatorCandidate(validator_id="v1", bond_q=100.0),
        ]
        result = self.policy.select(candidates, seed="test", required_count=1)
        assert len(result.selected) == 1
        assert result.selected[0].validator_id == "v1"

    # ── Deterministic selection ──

    def test_deterministic_with_seed(self):
        candidates = [
            ValidatorCandidate(validator_id=f"v{i}", bond_q=100.0)
            for i in range(10)
        ]
        r1 = self.policy.select(candidates, seed="fixed-seed", required_count=3)
        r2 = self.policy.select(candidates, seed="fixed-seed", required_count=3)
        assert [v.validator_id for v in r1.selected] == [
            v.validator_id for v in r2.selected
        ]

    def test_different_seed_different_order(self):
        candidates = [
            ValidatorCandidate(validator_id=f"v{i}", bond_q=100.0)
            for i in range(10)
        ]
        r1 = self.policy.select(candidates, seed="seed-a", required_count=5)
        r2 = self.policy.select(candidates, seed="seed-b", required_count=5)
        # All 10 qualified, 5 selected each; different seeds → different subsets
        assert len(r1.selected) == 5
        assert len(r2.selected) == 5
        assert r1.qualified_count == 10
        assert r2.qualified_count == 10
        # Subsets should differ (different shuffle order)
        set1 = {v.validator_id for v in r1.selected}
        set2 = {v.validator_id for v in r2.selected}
        assert set1 != set2

    # ── Reputation-weighted selection ──

    def test_higher_reputation_ranked_first(self):
        candidates = [
            ValidatorCandidate(
                validator_id="good", bond_q=100.0,
                reputation_score=0.9, reputation_confidence=0.8,
            ),
            ValidatorCandidate(
                validator_id="avg", bond_q=100.0,
                reputation_score=0.6, reputation_confidence=0.7,
            ),
            ValidatorCandidate(
                validator_id="bad", bond_q=100.0,
                reputation_score=0.4, reputation_confidence=0.7,
            ),
        ]
        result = self.policy.select(
            candidates, seed="test", required_count=2,
            weight_by_reputation=True,
        )
        # "good" should be first, "bad" disqualified
        assert result.selected[0].validator_id == "good"
        assert "bad" in [v.validator_id for v in result.disqualified]

    # ── Price-aware selection ──

    def test_price_sorting(self):
        candidates = [
            ValidatorCandidate(
                validator_id="expensive", bond_q=100.0,
                reputation_score=0.8, reputation_confidence=0.7,
                price_q=50.0,
            ),
            ValidatorCandidate(
                validator_id="cheap", bond_q=100.0,
                reputation_score=0.8, reputation_confidence=0.7,
                price_q=10.0,
            ),
        ]
        result = self.policy.select(
            candidates, seed="test", required_count=2,
            weight_by_price=True,
        )
        # Cheap should be ranked first when price-weighted
        assert result.selected[0].validator_id == "cheap"

    # ── Combined reputation + price ──

    def test_combined_reputation_and_price(self):
        candidates = [
            ValidatorCandidate(
                validator_id="best_value", bond_q=100.0,
                reputation_score=0.85, reputation_confidence=0.8,
                price_q=15.0,
            ),
            ValidatorCandidate(
                validator_id="good_expensive", bond_q=100.0,
                reputation_score=0.80, reputation_confidence=0.7,
                price_q=40.0,
            ),
            ValidatorCandidate(
                validator_id="ok_cheap", bond_q=100.0,
                reputation_score=0.55, reputation_confidence=0.6,
                price_q=5.0,
            ),
        ]
        result = self.policy.select(
            candidates, seed="test", required_count=3,
            weight_by_reputation=True,
            weight_by_price=True,
        )
        # Best value should rank highest
        assert result.selected[0].validator_id == "best_value"

    # ── Edge cases ──

    def test_empty_candidates(self):
        result = self.policy.select([], seed="test", required_count=5)
        assert len(result.selected) == 0
        assert result.insufficient_capacity is True

    def test_all_disqualified(self):
        candidates = [
            ValidatorCandidate(validator_id="v1", bond_q=1.0),
            ValidatorCandidate(validator_id="v2", bond_q=2.0),
        ]
        result = self.policy.select(candidates, seed="test", required_count=3)
        assert len(result.selected) == 0
        assert len(result.disqualified) == 2
        assert result.insufficient_capacity is True

    def test_selects_up_to_required(self):
        candidates = [
            ValidatorCandidate(validator_id=f"v{i}", bond_q=100.0)
            for i in range(20)
        ]
        result = self.policy.select(candidates, seed="test", required_count=5)
        assert len(result.selected) == 5

    def test_selects_all_when_fewer_than_required(self):
        candidates = [
            ValidatorCandidate(validator_id="v1", bond_q=100.0),
            ValidatorCandidate(validator_id="v2", bond_q=100.0),
        ]
        result = self.policy.select(candidates, seed="test", required_count=10)
        assert len(result.selected) == 2
        assert result.insufficient_capacity is True

    # ── SelectionResult metadata ──

    def test_result_includes_seed(self):
        candidates = [
            ValidatorCandidate(validator_id="v1", bond_q=100.0),
        ]
        result = self.policy.select(candidates, seed="my-seed", required_count=1)
        assert result.seed == "my-seed"

    def test_result_includes_selection_rationale(self):
        candidates = [
            ValidatorCandidate(validator_id="v1", bond_q=10.0),
            ValidatorCandidate(
                validator_id="v2", bond_q=100.0,
                reputation_score=0.3, reputation_confidence=0.7,
            ),
        ]
        result = self.policy.select(candidates, seed="test", required_count=1)
        # Both should be disqualified
        assert len(result.disqualified) == 2
        assert all(r is not None for r in [d.disqualification_reason for d in result.disqualified])
