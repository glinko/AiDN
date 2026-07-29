"""Bind externally verified CometBFT evidence to the local ABCI state root."""

from __future__ import annotations

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.finality import (
    ConsensusFinalityEvidence,
    ConsensusFinalitySource,
)


class ABCICommittedFinalitySource:
    """Expose evidence only when the local ABCI commitment exactly agrees.

    The external source establishes consensus inclusion and commit validity. The
    ABCI application establishes that this Hypervisor's Ledger state committed
    the same block and application root. Neither input is sufficient alone.
    """

    def __init__(
        self,
        *,
        source: ConsensusFinalitySource,
        abci_application: AIDNABCIApplication,
    ) -> None:
        self._source = source
        self._abci_application = abci_application

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        try:
            evidence = self._source.finality_evidence(operation_id)
            if evidence is None or evidence.operation_id != operation_id:
                return None
            commitment = self._abci_application.commitment_at(evidence.block_height)
            if commitment is None:
                return None
            if commitment.block_hash != evidence.block_id or commitment.app_hash != evidence.app_hash:
                return None
            return evidence
        except Exception:
            return None
