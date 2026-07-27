"""Validator Selection Policy — M5 Phase 2.

Deterministic, reproducible validator selection based on:
- Bond qualification (minimum bond threshold)
- Reputation qualification (minimum score + confidence)
- Seeded shuffle for reproducibility
- Optional reputation-weighted and price-weighted ranking
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Qualification Criteria
# ---------------------------------------------------------------------------

class ValidatorQualificationCriteria(BaseModel):
    """Thresholds for validator eligibility."""

    minimum_bond_q: float = Field(default=100.0, ge=0.0)
    minimum_reputation_score: float = Field(default=0.5, ge=0.0, le=1.0)
    minimum_reputation_confidence: float = Field(default=0.3, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Validator Candidate
# ---------------------------------------------------------------------------

class ValidatorCandidate(BaseModel):
    """A validator candidate for selection."""

    validator_id: str
    bond_q: float = Field(ge=0.0)
    reputation_score: float | None = None
    reputation_confidence: float | None = None
    price_q: float | None = None
    capability_profiles: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Selection Result
# ---------------------------------------------------------------------------

class SelectionEntry(BaseModel):
    """A selected (or disqualified) validator with rationale."""

    validator_id: str
    bond_q: float
    reputation_score: float | None = None
    reputation_confidence: float | None = None
    price_q: float | None = None
    selection_rank: int | None = None
    selection_score: float | None = None
    disqualification_reason: str | None = None


class SelectionResult(BaseModel):
    """Outcome of a validator selection run."""

    seed: str
    selected: list[SelectionEntry] = Field(default_factory=list)
    disqualified: list[SelectionEntry] = Field(default_factory=list)
    insufficient_capacity: bool = False
    total_candidates: int = 0
    qualified_count: int = 0
    selected_count: int = 0


# ---------------------------------------------------------------------------
# Selection Policy
# ---------------------------------------------------------------------------

class ValidatorSelectionPolicy:
    """Deterministic validator selection with qualification gates.

    Pipeline:
    1. Qualification filter (bond, reputation, confidence)
    2. Scoring (reputation-weighted, price-weighted, or neutral)
    3. Deterministic shuffle (seeded)
    4. Selection (top N by score, or shuffled if no weighting)
    """

    def __init__(self, criteria: ValidatorQualificationCriteria) -> None:
        self.criteria = criteria

    def select(
        self,
        candidates: list[ValidatorCandidate],
        *,
        seed: str,
        required_count: int = 1,
        weight_by_reputation: bool = False,
        weight_by_price: bool = False,
    ) -> SelectionResult:
        """Select validators deterministically.

        Args:
            candidates: Pool of validator candidates.
            seed: Deterministic seed for reproducibility.
            required_count: Number of validators to select.
            weight_by_reputation: Rank by reputation score (higher = better).
            weight_by_price: Rank by price (lower = better).

        Returns:
            SelectionResult with selected/disqualified validators.
        """
        result = SelectionResult(
            seed=seed,
            total_candidates=len(candidates),
        )

        if not candidates:
            result.insufficient_capacity = required_count > 0
            return result

        # Step 1: Qualification filter
        qualified: list[ValidatorCandidate] = []
        for candidate in candidates:
            reason = self._check_qualification(candidate)
            if reason is None:
                qualified.append(candidate)
            else:
                entry = self._to_entry(candidate)
                entry.disqualification_reason = reason
                result.disqualified.append(entry)

        result.qualified_count = len(qualified)

        if not qualified:
            result.insufficient_capacity = required_count > 0
            return result

        # Step 2: Score candidates
        scored: list[tuple[float, ValidatorCandidate]] = []
        for candidate in qualified:
            score = self._compute_score(
                candidate,
                weight_by_reputation=weight_by_reputation,
                weight_by_price=weight_by_price,
            )
            scored.append((score, candidate))

        # Step 3: Sort by score (descending), deterministic shuffle among ties
        scored = self._score_and_shuffle(scored, seed)

        # Step 4: Select top N
        selected_count = min(required_count, len(scored))
        result.selected_count = selected_count

        for rank, (score, candidate) in enumerate(scored[:selected_count], 1):
            entry = self._to_entry(candidate)
            entry.selection_rank = rank
            entry.selection_score = round(score, 4)
            result.selected.append(entry)

        result.insufficient_capacity = selected_count < required_count
        return result

    def _check_qualification(
        self, candidate: ValidatorCandidate
    ) -> str | None:
        """Check if a candidate meets qualification criteria.

        Returns:
            None if qualified, or a disqualification reason string.
        """
        # Bond check
        if candidate.bond_q < self.criteria.minimum_bond_q:
            return (
                f"bond {candidate.bond_q:.2f}Q < minimum "
                f"{self.criteria.minimum_bond_q:.2f}Q"
            )

        # Reputation check (only if reputation data is available)
        if candidate.reputation_score is not None:
            if candidate.reputation_score < self.criteria.minimum_reputation_score:
                return (
                    f"reputation {candidate.reputation_score:.3f} < minimum "
                    f"{self.criteria.minimum_reputation_score:.3f}"
                )

        # Confidence check (only if confidence data is available)
        if candidate.reputation_confidence is not None:
            if (
                candidate.reputation_confidence
                < self.criteria.minimum_reputation_confidence
            ):
                return (
                    f"confidence {candidate.reputation_confidence:.3f} < minimum "
                    f"{self.criteria.minimum_reputation_confidence:.3f}"
                )

        return None

    def _compute_score(
        self,
        candidate: ValidatorCandidate,
        *,
        weight_by_reputation: bool,
        weight_by_price: bool,
    ) -> float:
        """Compute selection score for a candidate.

        Returns a score in [0.0, 1.0]. Higher = more likely to be selected.

        Formula:
        - Base: 0.5 (neutral prior)
        - Reputation delta: (score - 0.5) * 0.4  → [-0.2, +0.2]
        - Price bonus: (1 - price/100) * 0.2    → [0, +0.2]
        - Bond bonus: min(1, bond/(min*3)) * 0.1 → [0, +0.1]

        This ensures scores stay in a useful range without excessive clamping.
        """
        score = 0.5  # neutral prior

        if weight_by_reputation:
            rep = candidate.reputation_score
            if rep is not None:
                # Reputation contributes [-0.2, +0.2]
                score += (rep - 0.5) * 0.4

        if weight_by_price:
            price = candidate.price_q
            if price is not None and price > 0:
                # Lower price = higher score, contributes [0, +0.2]
                price_factor = max(0.0, 1.0 - (price / 100.0))
                score += price_factor * 0.2

        # Bond contribution (higher bond = slightly better, up to +0.1)
        bond_factor = min(1.0, candidate.bond_q / (self.criteria.minimum_bond_q * 3))
        score += bond_factor * 0.1

        return max(0.0, min(1.0, score))

    def _score_and_shuffle(
        self,
        items: list[tuple[float, ValidatorCandidate]],
        seed: str,
    ) -> list[tuple[float, ValidatorCandidate]]:
        """Sort by score descending, then deterministically shuffle ties.

        Items with equal (within 3 decimal places) scores are shuffled
        among themselves using the seed. Items with different scores
        maintain their relative ordering.
        """
        if len(items) <= 1:
            return items

        # Sort by score descending
        sorted_items = sorted(items, key=lambda x: -x[0])

        # Group consecutive items by score bucket
        buckets: dict[float, list[tuple[float, ValidatorCandidate]]] = {}
        bucket_order: list[float] = []
        for item in sorted_items:
            bucket_key = round(item[0], 3)
            if bucket_key not in buckets:
                bucket_order.append(bucket_key)
                buckets[bucket_key] = []
            buckets[bucket_key].append(item)

        result: list[tuple[float, ValidatorCandidate]] = []
        for bucket_key in bucket_order:
            bucket_items = buckets[bucket_key]
            if len(bucket_items) > 1:
                shuffled = self._seeded_shuffle(bucket_items, seed, bucket_key)
                result.extend(shuffled)
            else:
                result.extend(bucket_items)

        return result

    def _seeded_shuffle(
        self,
        items: list[tuple[float, ValidatorCandidate]],
        seed: str,
        bucket_key: float,
    ) -> list[tuple[float, ValidatorCandidate]]:
        """Fisher-Yates shuffle with deterministic seed."""
        import random

        # Derive a deterministic seed from the main seed + bucket key
        seed_str = f"{seed}:{bucket_key}"
        seed_bytes = hashlib.sha256(seed_str.encode()).digest()
        seed_int = int.from_bytes(seed_bytes[:8], "big")

        rng = random.Random(seed_int)
        result = list(items)
        rng.shuffle(result)
        return result

    @staticmethod
    def _to_entry(candidate: ValidatorCandidate) -> SelectionEntry:
        """Convert a candidate to a selection entry."""
        return SelectionEntry(
            validator_id=candidate.validator_id,
            bond_q=candidate.bond_q,
            reputation_score=candidate.reputation_score,
            reputation_confidence=candidate.reputation_confidence,
            price_q=candidate.price_q,
        )
