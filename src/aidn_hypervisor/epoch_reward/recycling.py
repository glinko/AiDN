"""M11-S5: Recycling Engine — recyclable Q tracking."""

from __future__ import annotations

from aidn_hypervisor.epoch_reward.models import (
    RecyclableRecord,
    RecyclingSource,
    RecyclingStatus,
)


class RecyclingEngine:
    """Manages recyclable Q tracking and backlog.

    Recyclable sources:
    - Network fees
    - Validator penalties
    - Bond forfeitures
    - Consensus slashes
    - Unused rewards

    ECO-0005 §10: Unused recyclable Q returns to backlog.
    """

    def __init__(self, max_recycle_lag: int = 3) -> None:
        self._max_lag = max_recycle_lag
        # list of RecyclableRecord
        self._records: list[RecyclableRecord] = []
        # epoch → list of record indices recycled
        self._recycled_by_epoch: dict[int, set[int]] = {}

    def add_source(
        self,
        source: RecyclingSource,
        amount: int,
        epoch: int,
    ) -> RecyclableRecord:
        """Add recyclable Q from a source.

        Args:
            source: Recycling source.
            amount: Amount in q-atoms.
            epoch: Epoch when Q was removed.

        Returns:
            RecyclableRecord for tracking.
        """
        record = RecyclableRecord(
            source=source,
            amount=amount,
            epoch_removed=epoch,
        )
        self._records.append(record)
        return record

    def get_pending_amount(self, current_epoch: int) -> int:
        """Get total pending recyclable Q available for current epoch.

        Args:
            current_epoch: Current epoch number.

        Returns:
            Total q-atoms available for recycling.
        """
        total = 0
        for record in self._records:
            if record.status == RecyclingStatus.PENDING:
                # Check if within recycle window
                age = current_epoch - record.epoch_removed
                if age <= self._max_lag:
                    total += record.amount
        return total

    def recycle_eligible(
        self, current_epoch: int
    ) -> list[RecyclableRecord]:
        """Mark eligible pending records as recycled.

        Args:
            current_epoch: Current epoch number.

        Returns:
            List of newly recycled records.
        """
        recycled: list[RecyclableRecord] = []
        recycled_indices: set[int] = set()

        for i, record in enumerate(self._records):
            if record.status != RecyclingStatus.PENDING:
                continue
            age = current_epoch - record.epoch_removed
            if age <= self._max_lag:
                # Mark as recycled
                updated = record.model_copy(
                    update={
                        "status": RecyclingStatus.RECYCLED,
                        "epoch_recycled": current_epoch,
                    }
                )
                self._records[i] = updated
                recycled.append(updated)
                recycled_indices.add(i)

        self._recycled_by_epoch[current_epoch] = recycled_indices
        return recycled

    def expire_overdue(self, current_epoch: int) -> list[RecyclableRecord]:
        """Expire records that exceeded the recycle window.

        Args:
            current_epoch: Current epoch number.

        Returns:
            List of newly expired records.
        """
        expired: list[RecyclableRecord] = []

        for i, record in enumerate(self._records):
            if record.status != RecyclingStatus.PENDING:
                continue
            age = current_epoch - record.epoch_removed
            if age > self._max_lag:
                updated = record.model_copy(
                    update={"status": RecyclingStatus.EXPIRED}
                )
                self._records[i] = updated
                expired.append(updated)

        return expired

    def get_backlog(self) -> int:
        """Get total amount in the recycling backlog (pending)."""
        return sum(
            r.amount for r in self._records
            if r.status == RecyclingStatus.PENDING
        )

    def get_total_recycled(self) -> int:
        """Get total amount already recycled."""
        return sum(
            r.amount for r in self._records
            if r.status == RecyclingStatus.RECYCLED
        )

    def get_records_by_source(
        self, source: RecyclingSource
    ) -> list[RecyclableRecord]:
        """Get records filtered by source."""
        return [r for r in self._records if r.source == source]

    def get_records_for_epoch(
        self, epoch: int
    ) -> list[RecyclableRecord]:
        """Get records removed in a specific epoch."""
        return [r for r in self._records if r.epoch_removed == epoch]

    @property
    def record_count(self) -> int:
        """Total number of records."""
        return len(self._records)
