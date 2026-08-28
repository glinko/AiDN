"""Fail-closed bridge from finalized consensus operations to reward evidence."""

from __future__ import annotations

from aidn_hypervisor.consensus.finality import ConsensusFinalitySource
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.testnet_participation import (
    TESTNET_PARTICIPATION_HEARTBEAT_OPERATION,
    TestnetHeartbeatEvidence,
)
from aidn_hypervisor.testnet_participation_evidence import (
    TestnetParticipationEvidenceStore,
)


class ParticipationFinalityBridge:
    """Ingest only an exact finalized heartbeat operation from the active chain.

    The caller may obtain the envelope from a local Ledger projection or a
    CometBFT query, but this class does not trust the caller's ``finalized``
    label.  It independently asks the configured verified finality source for
    the exact operation ID and checks the active chain and operation type.
    """

    def __init__(
        self,
        *,
        active_chain_id: str,
        finality_source: ConsensusFinalitySource,
        evidence_store: TestnetParticipationEvidenceStore,
    ) -> None:
        if not active_chain_id.strip():
            raise ValueError("PARTICIPATION_ACTIVE_CHAIN_REQUIRED")
        self.active_chain_id = active_chain_id
        self.finality_source = finality_source
        self.evidence_store = evidence_store

    def ingest(self, envelope: LedgerOperationEnvelope) -> TestnetHeartbeatEvidence:
        """Verify finality and atomically write the corresponding evidence."""

        if envelope.operation_type != TESTNET_PARTICIPATION_HEARTBEAT_OPERATION:
            raise ValueError("PARTICIPATION_FINALITY_OPERATION_TYPE_INVALID")
        if set(envelope.payload) != {"heartbeat"}:
            raise ValueError("PARTICIPATION_FINALITY_PAYLOAD_INVALID")
        try:
            heartbeat = TestnetHeartbeatEvidence.model_validate(envelope.payload["heartbeat"])
        except ValueError as error:
            raise ValueError("PARTICIPATION_FINALITY_HEARTBEAT_INVALID") from error
        if heartbeat.chain_id != self.active_chain_id:
            raise ValueError("PARTICIPATION_FINALITY_CHAIN_MISMATCH")
        if envelope.initiator_id != heartbeat.node_id:
            raise ValueError("PARTICIPATION_FINALITY_NODE_MISMATCH")

        finality = self.finality_source.finality_evidence(envelope.operation_id)
        if finality is None:
            raise ValueError("PARTICIPATION_FINALITY_NOT_VERIFIED")
        if (
            finality.operation_id != envelope.operation_id
            or finality.chain_id != self.active_chain_id
            or finality.operation_type != TESTNET_PARTICIPATION_HEARTBEAT_OPERATION
        ):
            raise ValueError("PARTICIPATION_FINALITY_RECEIPT_MISMATCH")
        return self.evidence_store.record_finalized_heartbeat(
            heartbeat,
            source_operation_id=envelope.operation_id,
            finality=finality,
        )


__all__ = ["ParticipationFinalityBridge"]
