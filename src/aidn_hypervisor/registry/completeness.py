"""Registry Completeness Tracking (RFC-0061 §§59–62)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from .storage import ImmutableObjectStore, StorageStats
from .manifest import SegmentManifest, InventoryRoot
from .profile import RequiredRegistryProfile, RegistryProfileService


# ---------------------------------------------------------------------------
# CompletenessScore
# ---------------------------------------------------------------------------

class CompletenessScore(BaseModel, frozen=True):
    """RFC-0061 §59 — Registry completeness assessment."""

    overall: float = Field(default=0.0, ge=0.0, le=1.0)
    object_type_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    epoch_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    object_count: int = 0
    expected_objects: int = 0
    assessed_at: float = 0.0


# ---------------------------------------------------------------------------
# CompletenessTracker
# ---------------------------------------------------------------------------

class CompletenessTracker:
    """
    RFC-0061 §§59–62 — Track and assess registry completeness.

    Monitors how complete a registry is relative to expected state.
    """

    def __init__(
        self,
        store: ImmutableObjectStore,
        profile_service: RegistryProfileService | None = None,
    ) -> None:
        self._store = store
        self._profile_service = profile_service
        self._history: list[CompletenessScore] = []
        self._expected_epochs: set[int] = set()
        self._expected_object_counts: dict[str, int] = {}

    # -- configuration --------------------------------------------------

    def set_expected_epochs(self, epochs: list[int]) -> None:
        """Set the expected epoch range."""
        self._expected_epochs = set(epochs)

    def set_expected_object_counts(self, counts: dict[str, int]) -> None:
        """Set expected object counts by type."""
        self._expected_object_counts.update(counts)

    # -- assessment -----------------------------------------------------

    def assess(self) -> CompletenessScore:
        """
        Assess current completeness of the registry.

        Returns a CompletenessScore with overall, type, and epoch
        coverage metrics.
        """
        stats = self._store.stats()

        # --- object-type coverage ---
        type_coverage = 1.0
        if self._expected_object_counts:
            present_types = len(stats.objects_by_type)
            expected_types = len(self._expected_object_counts)
            type_coverage = min(1.0, present_types / max(expected_types, 1))

        # --- epoch coverage ---
        epoch_coverage = 1.0
        if self._expected_epochs:
            if stats.earliest_epoch is not None and stats.latest_epoch is not None:
                local_epochs = set(range(stats.earliest_epoch, stats.latest_epoch + 1))
                present = local_epochs.intersection(self._expected_epochs)
                epoch_coverage = len(present) / max(len(self._expected_epochs), 1)
            else:
                epoch_coverage = 0.0

        # --- object-count score ---
        count_score = 1.0
        if self._expected_object_counts:
            total_expected = sum(self._expected_object_counts.values())
            count_score = min(1.0, stats.total_objects / max(total_expected, 1))

        # --- overall: weighted average ---
        overall = (
            type_coverage * 0.4
            + epoch_coverage * 0.4
            + count_score * 0.2
        )

        score = CompletenessScore(
            overall=round(overall, 4),
            object_type_coverage=round(type_coverage, 4),
            epoch_coverage=round(epoch_coverage, 4),
            object_count=stats.total_objects,
            expected_objects=(
                sum(self._expected_object_counts.values())
                if self._expected_object_counts
                else 0
            ),
            assessed_at=time.time(),
        )
        self._history.append(score)
        return score

    # -- history --------------------------------------------------------

    def get_history(self) -> list[CompletenessScore]:
        """Return the full assessment history."""
        return list(self._history)

    def get_latest(self) -> CompletenessScore | None:
        """Return the most recent score, or None."""
        return self._history[-1] if self._history else None

    # -- convenience ----------------------------------------------------

    def is_complete(self, threshold: float = 0.95) -> bool:
        """Check if the registry meets the given completeness threshold."""
        latest = self.get_latest()
        if latest is None:
            return False
        return latest.overall >= threshold

    def gaps(self) -> dict[str, Any]:
        """Identify specific gaps in the registry."""
        stats = self._store.stats()
        result: dict[str, Any] = {
            "missing_types": [],
            "missing_epochs": [],
            "underfilled_types": [],
        }

        # Missing / underfilled types
        if self._expected_object_counts:
            for otype in self._expected_object_counts:
                if otype not in stats.objects_by_type:
                    result["missing_types"].append(otype)
                elif stats.objects_by_type[otype] < self._expected_object_counts[otype]:
                    result["underfilled_types"].append(
                        {
                            "type": otype,
                            "have": stats.objects_by_type[otype],
                            "expected": self._expected_object_counts[otype],
                        }
                    )

        # Missing epochs
        if self._expected_epochs and stats.earliest_epoch is not None:
            if stats.latest_epoch is not None:
                local_epochs = set(
                    range(stats.earliest_epoch, stats.latest_epoch + 1)
                )
                result["missing_epochs"] = sorted(
                    self._expected_epochs - local_epochs
                )
            else:
                result["missing_epochs"] = sorted(self._expected_epochs)

        return result
