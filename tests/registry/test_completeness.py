"""Tests for registry/completeness — Completeness Tracking (RFC-0061 §§59–62)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aidn_hypervisor.registry import (
    CompletenessScore,
    CompletenessTracker,
    ImmutableObjectStore,
    RegistryObjectEnvelope,
    RegistryProfileService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_envelope(
    obj_type: str = "test",
    payload: dict | None = None,
    object_id: str | None = None,
    created_epoch: int | None = None,
) -> RegistryObjectEnvelope:
    return RegistryObjectEnvelope.create(
        object_type=obj_type,
        payload=payload or {"key": "value"},
        object_id=object_id,
        created_epoch=created_epoch,
    )


def _make_store() -> ImmutableObjectStore:
    return ImmutableObjectStore()


# ---------------------------------------------------------------------------
# CompletenessScore — frozen model
# ---------------------------------------------------------------------------

def test_completeness_score_frozen():
    score = CompletenessScore(overall=0.5)
    with pytest.raises(ValidationError):
        score.overall = 0.8  # type: ignore


# ---------------------------------------------------------------------------
# CompletenessTracker — assess empty store
# ---------------------------------------------------------------------------

def test_tracker_assess_empty():
    store = _make_store()
    tracker = CompletenessTracker(store)
    score = tracker.assess()
    assert score.overall == 1.0  # no expectations = fully complete
    assert score.object_count == 0
    assert score.expected_objects == 0


# ---------------------------------------------------------------------------
# CompletenessTracker — assess full
# ---------------------------------------------------------------------------

def test_tracker_assess_full():
    store = _make_store()
    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))
    store.put(_make_envelope(obj_type="A", object_id="a2", created_epoch=2))
    store.put(_make_envelope(obj_type="B", object_id="b1", created_epoch=3))

    tracker = CompletenessTracker(store)
    tracker.set_expected_object_counts({"A": 2, "B": 1})
    tracker.set_expected_epochs([1, 2, 3])

    score = tracker.assess()
    assert score.overall == 1.0
    assert score.object_type_coverage == 1.0
    assert score.epoch_coverage == 1.0
    assert score.object_count == 3


# ---------------------------------------------------------------------------
# CompletenessTracker — assess partial
# ---------------------------------------------------------------------------

def test_tracker_assess_partial():
    store = _make_store()
    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))

    tracker = CompletenessTracker(store)
    tracker.set_expected_object_counts({"A": 2, "B": 1})
    tracker.set_expected_epochs([1, 2, 3])

    score = tracker.assess()
    assert score.overall < 1.0
    assert score.object_type_coverage == 0.5  # 1 type present out of 2
    assert score.epoch_coverage == pytest.approx(1.0 / 3, abs=0.001)
    assert score.object_count == 1


# ---------------------------------------------------------------------------
# CompletenessTracker — history
# ---------------------------------------------------------------------------

def test_tracker_history():
    store = _make_store()
    tracker = CompletenessTracker(store)

    s1 = tracker.assess()
    s2 = tracker.assess()

    history = tracker.get_history()
    assert len(history) == 2
    assert history[0] is s1
    assert history[1] is s2


# ---------------------------------------------------------------------------
# CompletenessTracker — get_latest
# ---------------------------------------------------------------------------

def test_tracker_get_latest():
    store = _make_store()
    tracker = CompletenessTracker(store)
    assert tracker.get_latest() is None

    score = tracker.assess()
    assert tracker.get_latest() is score


# ---------------------------------------------------------------------------
# CompletenessTracker — is_complete pass
# ---------------------------------------------------------------------------

def test_is_complete_pass():
    store = _make_store()
    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))
    store.put(_make_envelope(obj_type="B", object_id="b1", created_epoch=2))

    tracker = CompletenessTracker(store)
    tracker.set_expected_object_counts({"A": 1, "B": 1})
    tracker.set_expected_epochs([1, 2])

    tracker.assess()
    assert tracker.is_complete(0.95) is True


# ---------------------------------------------------------------------------
# CompletenessTracker — is_complete fail
# ---------------------------------------------------------------------------

def test_is_complete_fail():
    store = _make_store()
    tracker = CompletenessTracker(store)
    tracker.set_expected_object_counts({"A": 10, "B": 10})
    tracker.set_expected_epochs([1, 2, 3, 4, 5])

    tracker.assess()
    assert tracker.is_complete(0.95) is False


# ---------------------------------------------------------------------------
# CompletenessTracker — gaps empty
# ---------------------------------------------------------------------------

def test_gaps_empty():
    store = _make_store()
    tracker = CompletenessTracker(store)
    gaps = tracker.gaps()
    assert gaps["missing_types"] == []
    assert gaps["missing_epochs"] == []
    assert gaps["underfilled_types"] == []


# ---------------------------------------------------------------------------
# CompletenessTracker — gaps missing types
# ---------------------------------------------------------------------------

def test_gaps_missing_types():
    store = _make_store()
    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))

    tracker = CompletenessTracker(store)
    tracker.set_expected_object_counts({"A": 1, "B": 1, "C": 1})

    gaps = tracker.gaps()
    assert "B" in gaps["missing_types"]
    assert "C" in gaps["missing_types"]
    assert "A" not in gaps["missing_types"]


# ---------------------------------------------------------------------------
# CompletenessTracker — gaps missing epochs
# ---------------------------------------------------------------------------

def test_gaps_missing_epochs():
    store = _make_store()
    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))
    store.put(_make_envelope(obj_type="A", object_id="a2", created_epoch=2))

    tracker = CompletenessTracker(store)
    tracker.set_expected_epochs([1, 2, 3, 4, 5])

    gaps = tracker.gaps()
    # epochs 1-2 present, 3/4/5 missing
    assert 3 in gaps["missing_epochs"]
    assert 4 in gaps["missing_epochs"]
    assert 5 in gaps["missing_epochs"]


# ---------------------------------------------------------------------------
# CompletenessTracker — gaps underfilled
# ---------------------------------------------------------------------------

def test_gaps_underfilled():
    store = _make_store()
    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))

    tracker = CompletenessTracker(store)
    tracker.set_expected_object_counts({"A": 5})

    gaps = tracker.gaps()
    assert len(gaps["underfilled_types"]) == 1
    assert gaps["underfilled_types"][0]["type"] == "A"
    assert gaps["underfilled_types"][0]["have"] == 1
    assert gaps["underfilled_types"][0]["expected"] == 5


# ---------------------------------------------------------------------------
# CompletenessTracker — epoch coverage
# ---------------------------------------------------------------------------

def test_epoch_coverage():
    store = _make_store()
    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))
    store.put(_make_envelope(obj_type="A", object_id="a2", created_epoch=2))
    store.put(_make_envelope(obj_type="A", object_id="a3", created_epoch=3))

    tracker = CompletenessTracker(store)
    tracker.set_expected_epochs([1, 2, 3, 4])

    score = tracker.assess()
    assert score.epoch_coverage == pytest.approx(3 / 4, abs=0.001)


# ---------------------------------------------------------------------------
# CompletenessTracker — type coverage
# ---------------------------------------------------------------------------

def test_type_coverage():
    store = _make_store()
    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))
    store.put(_make_envelope(obj_type="B", object_id="b1", created_epoch=1))

    tracker = CompletenessTracker(store)
    tracker.set_expected_object_counts({"A": 1, "B": 1, "C": 1, "D": 1})

    score = tracker.assess()
    assert score.object_type_coverage == pytest.approx(2 / 4, abs=0.001)


# ---------------------------------------------------------------------------
# CompletenessTracker — assess multiple times
# ---------------------------------------------------------------------------

def test_assess_multiple():
    store = _make_store()
    tracker = CompletenessTracker(store)
    tracker.set_expected_object_counts({"A": 1})
    tracker.set_expected_epochs([1])

    s1 = tracker.assess()
    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))
    s2 = tracker.assess()

    assert s1.object_count == 0
    assert s2.object_count == 1
    assert len(tracker.get_history()) == 2


# ---------------------------------------------------------------------------
# CompletenessTracker — init with profile service
# ---------------------------------------------------------------------------

def test_tracker_init_with_profile():
    store = _make_store()
    profile_svc = RegistryProfileService()
    tracker = CompletenessTracker(store, profile_service=profile_svc)
    score = tracker.assess()
    assert score.overall == 1.0


# ---------------------------------------------------------------------------
# CompletenessTracker — threshold
# ---------------------------------------------------------------------------

def test_completeness_threshold():
    store = _make_store()
    tracker = CompletenessTracker(store)
    tracker.set_expected_object_counts({"A": 2})
    tracker.set_expected_epochs([1])

    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))
    tracker.assess()

    # With 1 of 2 objects, should not be complete at 0.95
    assert tracker.is_complete(0.95) is False
    # But should be complete at 0.5
    assert tracker.is_complete(0.5) is True


# ---------------------------------------------------------------------------
# CompletenessTracker — combined gaps
# ---------------------------------------------------------------------------

def test_gaps_combined():
    store = _make_store()
    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))

    tracker = CompletenessTracker(store)
    tracker.set_expected_object_counts({"A": 3, "B": 2})
    tracker.set_expected_epochs([1, 2, 3])

    gaps = tracker.gaps()
    # B is missing entirely
    assert "B" in gaps["missing_types"]
    # A is underfilled (1 < 3)
    assert any(g["type"] == "A" for g in gaps["underfilled_types"])
    # epochs 2, 3 missing
    assert 2 in gaps["missing_epochs"]
    assert 3 in gaps["missing_epochs"]


# ---------------------------------------------------------------------------
# CompletenessTracker — no expectations = fully complete
# ---------------------------------------------------------------------------

def test_assess_no_expected():
    store = _make_store()
    store.put(_make_envelope(obj_type="X", object_id="x1", created_epoch=5))

    tracker = CompletenessTracker(store)
    # No expected counts or epochs set
    score = tracker.assess()
    assert score.overall == 1.0
    assert score.expected_objects == 0


# ---------------------------------------------------------------------------
# CompletenessTracker — score rounding
# ---------------------------------------------------------------------------

def test_score_rounding():
    store = _make_store()
    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))

    tracker = CompletenessTracker(store)
    tracker.set_expected_object_counts({"A": 3, "B": 3})
    tracker.set_expected_epochs([1, 2, 3])

    score = tracker.assess()
    # type_coverage = 1/2 = 0.5
    # epoch_coverage = 1/3 ≈ 0.3333
    # count_score = 1/6 ≈ 0.1667
    # overall = 0.5*0.4 + 0.3333*0.4 + 0.1667*0.2
    #         = 0.20 + 0.1333 + 0.0333 = 0.3667
    assert score.overall == pytest.approx(0.3667, abs=0.001)
    assert isinstance(score.overall, float)


# ---------------------------------------------------------------------------
# CompletenessTracker — overall formula
# ---------------------------------------------------------------------------

def test_completeness_overall_formula():
    store = _make_store()
    store.put(_make_envelope(obj_type="A", object_id="a1", created_epoch=1))
    store.put(_make_envelope(obj_type="B", object_id="b1", created_epoch=2))

    tracker = CompletenessTracker(store)
    tracker.set_expected_object_counts({"A": 1, "B": 1})
    tracker.set_expected_epochs([1, 2])

    score = tracker.assess()
    # type_coverage = 1.0, epoch_coverage = 1.0, count_score = 1.0
    # overall = 1.0 * 0.4 + 1.0 * 0.4 + 1.0 * 0.2 = 1.0
    assert score.overall == 1.0
    assert score.object_type_coverage == 1.0
    assert score.epoch_coverage == 1.0
