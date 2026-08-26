"""One managed step for a finalized daily Testnet participation Epoch."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from aidn_hypervisor.testnet_participation import (
    TestnetParticipationCalculator,
    TestnetParticipationProgram,
    TestnetParticipationSettlement,
    TestnetParticipationTransferBatch,
)
from aidn_hypervisor.testnet_participation_evidence import (
    TestnetParticipationEvidenceStore,
)
from aidn_hypervisor.testnet_participation_payout import (
    TestnetParticipationPayoutService,
)


class TestnetParticipationWorkerResult(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    settlement: TestnetParticipationSettlement
    batch: TestnetParticipationTransferBatch
    batch_status: Literal["PENDING", "FINALIZED", "BLOCKED"]
    processed_operation_id: str | None = None


class TestnetParticipationWorker:
    """Join finalized evidence, calculation and durable treasury settlement.

    The service manager invokes this only after a canonical 24-hour Epoch
    transition has finalized. It never uses a host-local timer as authority.
    """

    def __init__(
        self,
        *,
        program: TestnetParticipationProgram,
        active_network_id: str,
        active_chain_id: str,
        evidence_store: TestnetParticipationEvidenceStore,
        payout_service: TestnetParticipationPayoutService,
        calculator: TestnetParticipationCalculator | None = None,
    ) -> None:
        if (
            program.network_id != active_network_id
            or program.chain_id != active_chain_id
        ):
            raise ValueError("PARTICIPATION_PROGRAM_NETWORK_PROFILE_MISMATCH")
        self.program = program
        self.evidence_store = evidence_store
        self.payout_service = payout_service
        self.calculator = calculator or TestnetParticipationCalculator()

    def process_finalized_epoch(
        self,
        *,
        protocol_epoch: int,
        source_epoch_transition_operation_id: str,
        period_start: str,
        reconcile: bool = False,
    ) -> TestnetParticipationWorkerResult:
        """Calculate/freeze a day and submit or reconcile one ordered payout."""

        enrollments, heartbeats = self.evidence_store.settlement_inputs(
            self.program,
            period_start=period_start,
        )
        settlement = self.calculator.calculate(
            self.program,
            protocol_epoch=protocol_epoch,
            source_epoch_transition_operation_id=source_epoch_transition_operation_id,
            period_start=period_start,
            enrollments=enrollments,
            heartbeats=heartbeats,
        )
        batch = self.payout_service.schedule(settlement)
        processed = self.payout_service.process_next(
            settlement.settlement_id,
            reconcile=reconcile,
        )
        batch_record = self.payout_service.store.get_batch(settlement.settlement_id)
        if batch_record is None:
            raise RuntimeError("participation payout batch disappeared")
        return TestnetParticipationWorkerResult(
            settlement=settlement,
            batch=batch,
            batch_status=str(batch_record["status"]),
            processed_operation_id=(
                str(processed["operation_id"]) if processed is not None else None
            ),
        )


__all__ = ["TestnetParticipationWorker", "TestnetParticipationWorkerResult"]
