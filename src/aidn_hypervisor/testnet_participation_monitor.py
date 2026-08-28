"""Observation loop for finalized Testnet participation settlement triggers.

The monitor may poll a local canonical Ledger projection, but all positive
decisions are delegated to :mod:`testnet_participation_dispatch`: the exact
transition must still have independently verified network finality.  Polling
therefore provides delivery/recovery, never time authority.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.testnet_participation_dispatch import (
    TestnetParticipationDispatchResult,
    TestnetParticipationSettlementDispatcher,
)


class TestnetParticipationMonitorStatus(BaseModel, frozen=True):
    """Bounded, non-secret status that a future dashboard endpoint can expose."""

    model_config = ConfigDict(extra="forbid")

    scan_count: int = Field(ge=0)
    transition_count: int = Field(ge=0)
    processed_count: int = Field(ge=0)
    last_result: TestnetParticipationDispatchResult | None = None
    last_error: str | None = None


class TestnetParticipationSettlementMonitor:
    """Reconcile projected Epoch transitions without trusting the projection."""

    def __init__(self, *, dispatcher: TestnetParticipationSettlementDispatcher) -> None:
        self.dispatcher = dispatcher
        self._lock = threading.RLock()
        self._scan_count = 0
        self._transition_count = 0
        self._processed_count = 0
        self._last_result: TestnetParticipationDispatchResult | None = None
        self._last_error: str | None = None

    def reconcile(self, operations: Iterable[dict[str, Any]]) -> TestnetParticipationMonitorStatus:
        """Observe every projected transition once; failures remain visible.

        A malformed local record is ignored rather than permitted to block
        delivery of later finalized records.  The sanitized error is retained
        for operator diagnostics and a later scan retries any transition for
        which finality was temporarily unavailable.
        """

        last_result: TestnetParticipationDispatchResult | None = None
        last_error: str | None = None
        transition_count = 0
        processed_count = 0
        for raw in operations:
            if raw.get("operation_type") != "EPOCH_TRANSITION":
                continue
            transition_count += 1
            try:
                envelope = LedgerOperationEnvelope.model_validate(raw)
                result = self.dispatcher.dispatch(envelope)
                last_result = result
                if result.status == "processed":
                    processed_count += 1
            except Exception as error:
                last_error = f"{type(error).__name__}: {error}"

        with self._lock:
            self._scan_count += 1
            self._transition_count += transition_count
            self._processed_count += processed_count
            if last_result is not None:
                self._last_result = last_result
            self._last_error = last_error
            return self.status()

    def status(self) -> TestnetParticipationMonitorStatus:
        with self._lock:
            return TestnetParticipationMonitorStatus(
                scan_count=self._scan_count,
                transition_count=self._transition_count,
                processed_count=self._processed_count,
                last_result=self._last_result,
                last_error=self._last_error,
            )


__all__ = [
    "TestnetParticipationMonitorStatus",
    "TestnetParticipationSettlementMonitor",
]
