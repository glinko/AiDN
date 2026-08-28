"""Canonical-time dispatcher for Testnet participation settlements.

The payout runtime must never decide that a day has ended from the clock of
one Hypervisor.  This boundary accepts a *finalized* ``EPOCH_TRANSITION`` and
uses the committed :class:`EpochSchedule` to decide whether that transition
closed a participation settlement period.  A periodic service may poll this
dispatcher for newly projected operations, but its interval is observation
only; it cannot create or advance a settlement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from aidn_hypervisor.consensus.epoch_schedule import EpochSchedule
from aidn_hypervisor.consensus.finality import ConsensusFinalitySource
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.testnet_participation import TestnetParticipationProgram
from aidn_hypervisor.testnet_participation_runtime import (
    TestnetParticipationManagedRuntime,
    TestnetParticipationRuntimeResult,
)


def _timestamp(value: str, *, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be RFC3339") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _as_rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class TestnetParticipationDispatchResult(BaseModel, frozen=True):
    """Read-only outcome of examining one canonical Epoch transition."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["disabled", "not_due", "processed"]
    source_epoch_transition_operation_id: str
    closing_epoch: int
    period_start: str | None = None
    runtime: TestnetParticipationRuntimeResult | None = None
    detail: str | None = None


class TestnetParticipationSettlementDispatcher:
    """Permit participation settlement only at a finalized schedule boundary."""

    def __init__(
        self,
        *,
        runtime: TestnetParticipationManagedRuntime,
        epoch_schedule: EpochSchedule,
        finality_source: ConsensusFinalitySource,
    ) -> None:
        self.runtime = runtime
        self.epoch_schedule = epoch_schedule
        self.finality_source = finality_source

        program = runtime.program
        if program is not None and (
            program.settlement_period_seconds % epoch_schedule.epoch_duration_seconds
        ):
            raise ValueError(
                "PARTICIPATION_SETTLEMENT_PERIOD_MUST_DIVIDE_EPOCH_SCHEDULE"
            )

    def dispatch(
        self,
        envelope: LedgerOperationEnvelope,
    ) -> TestnetParticipationDispatchResult:
        """Process an exact finalized transition, or report that it is not due.

        This method is intentionally idempotent.  The durable payout batch is
        keyed by the settlement calculation; observing the same final
        transition again can neither create a second period nor a replacement
        transfer.
        """

        closing_epoch = self._validate_transition(envelope)
        if not self.runtime.config.enabled:
            return TestnetParticipationDispatchResult(
                status="disabled",
                source_epoch_transition_operation_id=envelope.operation_id,
                closing_epoch=closing_epoch,
                detail="PARTICIPATION_RUNTIME_DISABLED",
            )

        program = self.runtime.program
        if program is None:
            raise RuntimeError("participation runtime was not initialized")
        if not self._within_program_epoch_range(program, closing_epoch):
            return TestnetParticipationDispatchResult(
                status="not_due",
                source_epoch_transition_operation_id=envelope.operation_id,
                closing_epoch=closing_epoch,
                detail="PARTICIPATION_PROGRAM_NOT_ACTIVE_FOR_EPOCH",
            )
        if envelope.protocol_version not in program.compatible_protocol_versions:
            raise ValueError("PARTICIPATION_SETTLEMENT_PROTOCOL_VERSION_UNSUPPORTED")

        period_start = self._period_start_if_due(program, closing_epoch)
        if period_start is None:
            return TestnetParticipationDispatchResult(
                status="not_due",
                source_epoch_transition_operation_id=envelope.operation_id,
                closing_epoch=closing_epoch,
                detail="PARTICIPATION_SETTLEMENT_NOT_DUE",
            )

        runtime_result = self.runtime.process_finalized_epoch(
            protocol_epoch=closing_epoch,
            source_epoch_transition_operation_id=envelope.operation_id,
            period_start=period_start,
        )
        return TestnetParticipationDispatchResult(
            status="processed",
            source_epoch_transition_operation_id=envelope.operation_id,
            closing_epoch=closing_epoch,
            period_start=period_start,
            runtime=runtime_result,
        )

    def _validate_transition(self, envelope: LedgerOperationEnvelope) -> int:
        if envelope.operation_type != "EPOCH_TRANSITION":
            raise ValueError("PARTICIPATION_SETTLEMENT_TRANSITION_TYPE_INVALID")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ValueError("PARTICIPATION_SETTLEMENT_TRANSITION_ORIGIN_INVALID")
        payload = envelope.payload
        closing_epoch = payload.get("closing_epoch")
        opening_epoch = payload.get("opening_epoch")
        if (
            isinstance(closing_epoch, bool)
            or not isinstance(closing_epoch, int)
            or closing_epoch < 0
            or opening_epoch != closing_epoch + 1
            or envelope.target_epoch != str(closing_epoch)
        ):
            raise ValueError("PARTICIPATION_SETTLEMENT_TRANSITION_EPOCH_INVALID")
        if payload.get("epoch_schedule_hash") != self.epoch_schedule.schedule_hash:
            raise ValueError("PARTICIPATION_SETTLEMENT_SCHEDULE_MISMATCH")
        expected_end = self._epoch_end(closing_epoch)
        if payload.get("scheduled_end_time") != _as_rfc3339(expected_end):
            raise ValueError("PARTICIPATION_SETTLEMENT_SCHEDULE_BOUNDARY_INVALID")

        finality = self.finality_source.finality_evidence(envelope.operation_id)
        if (
            finality is None
            or finality.operation_id != envelope.operation_id
            or finality.chain_id != self.runtime.config.active_chain_id
            or finality.operation_type != "EPOCH_TRANSITION"
        ):
            raise ValueError("PARTICIPATION_SETTLEMENT_TRANSITION_NOT_FINALIZED")
        return closing_epoch

    def _epoch_end(self, closing_epoch: int) -> datetime:
        genesis = _timestamp(
            self.epoch_schedule.genesis_start_time,
            field_name="epoch_schedule.genesis_start_time",
        )
        return genesis + timedelta(
            seconds=(closing_epoch + 1) * self.epoch_schedule.epoch_duration_seconds
        )

    def _period_start_if_due(
        self,
        program: TestnetParticipationProgram,
        closing_epoch: int,
    ) -> str | None:
        elapsed_seconds = (closing_epoch + 1) * self.epoch_schedule.epoch_duration_seconds
        if elapsed_seconds <= 0 or elapsed_seconds % program.settlement_period_seconds:
            return None
        return _as_rfc3339(
            self._epoch_end(closing_epoch)
            - timedelta(seconds=program.settlement_period_seconds)
        )

    @staticmethod
    def _within_program_epoch_range(
        program: TestnetParticipationProgram,
        closing_epoch: int,
    ) -> bool:
        return (
            closing_epoch >= program.active_from_epoch
            and (
                program.active_until_epoch is None
                or closing_epoch <= program.active_until_epoch
            )
        )


__all__ = [
    "TestnetParticipationDispatchResult",
    "TestnetParticipationSettlementDispatcher",
]
