"""Idempotent consensus execution for an ECO-0007 production batch."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from aidn_hypervisor.consensus.finality import ConsensusFinalitySource
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.service import ConsensusService, SubmissionRecord, SubmissionStatus
from aidn_hypervisor.reward.development_distribution import canonical_hash
from aidn_hypervisor.reward.development_production import (
    PRODUCTION_REWARD_OPERATION_TYPES,
    DevelopmentRewardProductionBatch,
    DevelopmentRewardProductionProfile,
)


class DevelopmentRewardBatchStage(BaseModel, frozen=True):
    """Observed lifecycle of one ordered batch envelope."""

    index: int = Field(ge=0)
    operation_id: str = Field(min_length=1)
    operation_type: str = Field(min_length=1)
    status: Literal[
        "FINALIZED",
        "ADMITTED",
        "INCLUDED",
        "PENDING",
        "FAILED",
        "AWAITING_VERIFIED_FINALITY",
    ]
    transaction_hash: str | None = None
    block_height: int | None = Field(default=None, ge=1)
    error: str | None = None


class DevelopmentRewardBatchExecution(BaseModel, frozen=True):
    """Resumable result of one production batch execution attempt."""

    batch_id: str = Field(min_length=1)
    status: Literal["FINALIZED", "AWAITING_VERIFIED_FINALITY", "FAILED"]
    finalized_operation_ids: list[str] = Field(default_factory=list)
    blocked_on: str | None = None
    stages: list[DevelopmentRewardBatchStage] = Field(default_factory=list)
    execution_hash: str = Field(min_length=1)

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"execution_hash"})

    def verify_integrity(self) -> bool:
        return self.execution_hash == canonical_hash(self.unsigned_payload())


class DevelopmentRewardBatchExecutor:
    """Submit a signed batch strictly one finalized predecessor at a time.

    This class does not create envelopes, sign operations, or apply local Q
    credits. The canonical validator transition remains the sole payment
    authority; a verified finality source is required before the next envelope
    is submitted when consensus is enabled.
    """

    def __init__(
        self,
        consensus_service: ConsensusService,
        *,
        finality_source: ConsensusFinalitySource | None = None,
        pending_envelope_store: Any | None = None,
    ) -> None:
        self._consensus = consensus_service
        self._finality_source = finality_source
        self._pending_envelope_store = pending_envelope_store

    def execute(
        self,
        batch: DevelopmentRewardProductionBatch,
        *,
        profile: DevelopmentRewardProductionProfile,
    ) -> DevelopmentRewardBatchExecution:
        self._validate_batch(batch, profile)
        stages: list[DevelopmentRewardBatchStage] = []
        finalized_ids: list[str] = []

        for index, envelope in enumerate(batch.plan.envelopes):
            stage, finalized = self._execute_one(index, envelope)
            stages.append(stage)
            if finalized:
                finalized_ids.append(envelope.operation_id)
                continue
            status = "FAILED" if stage.status == "FAILED" else "AWAITING_VERIFIED_FINALITY"
            return self._result(
                batch_id=batch.batch_id,
                status=status,
                finalized_operation_ids=finalized_ids,
                blocked_on=envelope.operation_id,
                stages=stages,
            )

        return self._result(
            batch_id=batch.batch_id,
            status="FINALIZED",
            finalized_operation_ids=finalized_ids,
            blocked_on=None,
            stages=stages,
        )

    def _execute_one(
        self,
        index: int,
        envelope: LedgerOperationEnvelope,
    ) -> tuple[DevelopmentRewardBatchStage, bool]:
        if not self._consensus.is_enabled:
            record = self._consensus.submit_operation(envelope, retry_existing=True)
            finalized = record.status == SubmissionStatus.FINALIZED
            return self._stage(
                index,
                envelope,
                record,
                status="FINALIZED" if finalized else "FAILED",
            ), finalized

        self._stage_pending(envelope)
        record = self._consensus.restore_submission(envelope)
        finalized = self._reconcile(envelope.operation_id)
        if finalized:
            self._discard_pending(envelope.operation_id)
            return self._stage(index, envelope, record, status="FINALIZED"), True

        if self._finality_source is None:
            return self._stage(
                index,
                envelope,
                record,
                status="AWAITING_VERIFIED_FINALITY",
                error="DEVELOPMENT_REWARD_FINALITY_SOURCE_REQUIRED",
            ), False

        record = self._consensus.submit_operation(envelope, retry_existing=True)
        finalized = self._reconcile(envelope.operation_id)
        if finalized:
            self._discard_pending(envelope.operation_id)
            return self._stage(index, envelope, record, status="FINALIZED"), True

        if record.status == SubmissionStatus.FAILED:
            return self._stage(index, envelope, record, status="FAILED"), False
        return self._stage(
            index,
            envelope,
            record,
            status="AWAITING_VERIFIED_FINALITY",
            error="DEVELOPMENT_REWARD_FINALITY_PENDING",
        ), False

    def _reconcile(self, operation_id: str) -> bool:
        if not self._consensus.is_enabled:
            record = self._consensus.get_submission(operation_id)
            return record is not None and record.status == SubmissionStatus.FINALIZED
        if self._finality_source is None:
            return False
        record = self._consensus.reconcile_finality(
            operation_id,
            finality_source=self._finality_source,
        )
        return record is not None and record.status == SubmissionStatus.FINALIZED

    def _validate_batch(
        self,
        batch: DevelopmentRewardProductionBatch,
        profile: DevelopmentRewardProductionProfile,
    ) -> None:
        if not batch.verify_integrity():
            raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_HASH_INVALID")
        if not profile.verify_integrity():
            raise ValueError("DEVELOPMENT_PRODUCTION_PROFILE_HASH_INVALID")
        if batch.profile_id != profile.profile_id or batch.profile_hash != profile.profile_hash:
            raise ValueError("DEVELOPMENT_PRODUCTION_EXECUTION_PROFILE_MISMATCH")
        if batch.network_id != profile.network_id or batch.chain_id != profile.chain_id:
            raise ValueError("DEVELOPMENT_PRODUCTION_EXECUTION_NETWORK_MISMATCH")
        if self._consensus.config.chain_id != batch.chain_id:
            raise ValueError("DEVELOPMENT_PRODUCTION_EXECUTION_CHAIN_MISMATCH")
        if len(batch.plan.envelopes) > profile.max_operations:
            raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_OPERATION_CAP_EXCEEDED")
        allowed = set(profile.authorized_operation_types)
        if any(item not in allowed for item in (envelope.operation_type for envelope in batch.plan.envelopes)):
            raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_OPERATION_NOT_AUTHORIZED")
        if any(envelope.operation_type not in PRODUCTION_REWARD_OPERATION_TYPES for envelope in batch.plan.envelopes):
            raise ValueError("DEVELOPMENT_PRODUCTION_BATCH_OPERATION_INVALID")

    def _stage_pending(self, envelope: LedgerOperationEnvelope) -> None:
        if self._pending_envelope_store is not None:
            self._pending_envelope_store.stage_pending_consensus_envelope(envelope)

    def _discard_pending(self, operation_id: str) -> None:
        if self._pending_envelope_store is not None:
            self._pending_envelope_store.discard_pending_consensus_envelopes(operation_id)

    @staticmethod
    def _stage(
        index: int,
        envelope: LedgerOperationEnvelope,
        record: SubmissionRecord,
        *,
        status: str,
        error: str | None = None,
    ) -> DevelopmentRewardBatchStage:
        return DevelopmentRewardBatchStage(
            index=index,
            operation_id=envelope.operation_id,
            operation_type=envelope.operation_type,
            status=status,
            transaction_hash=record.transaction_hash,
            block_height=record.block_height,
            error=error or record.error,
        )

    @staticmethod
    def _result(
        *,
        batch_id: str,
        status: Literal["FINALIZED", "AWAITING_VERIFIED_FINALITY", "FAILED"],
        finalized_operation_ids: list[str],
        blocked_on: str | None,
        stages: list[DevelopmentRewardBatchStage],
    ) -> DevelopmentRewardBatchExecution:
        payload = {
            "batch_id": batch_id,
            "status": status,
            "finalized_operation_ids": finalized_operation_ids,
            "blocked_on": blocked_on,
            "stages": [item.model_dump(mode="json") for item in stages],
        }
        return DevelopmentRewardBatchExecution(
            **payload,
            execution_hash=canonical_hash(payload),
        )


__all__ = [
    "DevelopmentRewardBatchExecution",
    "DevelopmentRewardBatchExecutor",
    "DevelopmentRewardBatchStage",
]
