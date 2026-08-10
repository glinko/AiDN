"""Bind externally verified CometBFT evidence to the local ABCI state root."""

from __future__ import annotations

from aidn_hypervisor.consensus.abci import AIDNABCIApplication
from aidn_hypervisor.consensus.finality import (
    ConsensusFinalityEvidence,
    ConsensusFinalitySource,
)


class ABCICommittedFinalitySource:
    """Expose evidence only when the local ABCI commitment agrees.

    The external source establishes consensus inclusion and commit validity. The
    ABCI application establishes that this Hypervisor's Ledger state was at the
    pre-block application root and committed the same block. CometBFT places
    the pre-block root in ``header.app_hash`` for block H, while the local
    commitment recorded for H contains the post-block root. Neither input is
    sufficient alone.
    """

    def __init__(
        self,
        *,
        source: ConsensusFinalitySource,
        abci_application: AIDNABCIApplication,
    ) -> None:
        self._source = source
        self._abci_application = abci_application

    @property
    def quorum(self) -> int:
        """Expose the wrapped source quorum for activation evidence."""

        return int(getattr(self._source, "quorum", 1))

    @property
    def source_count(self) -> int:
        """Expose the wrapped source count for activation evidence."""

        return int(getattr(self._source, "source_count", 1))

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        try:
            evidence = self._source.finality_evidence(operation_id)
            if evidence is None or evidence.operation_id != operation_id:
                return None
            block_commitment = self._abci_application.commitment_at(evidence.block_height)
            if block_commitment is None or block_commitment.block_hash != evidence.block_id:
                return None

            # Tendermint/CometBFT header AppHash is the application root before
            # the transactions in that block.  The local commitment at H is
            # the root after H, so bind the external pre-state to H - 1.
            if evidence.block_height == 1:
                if evidence.app_hash:
                    return None
            else:
                previous_commitment = self._abci_application.commitment_at(evidence.block_height - 1)
                if previous_commitment is None or previous_commitment.app_hash != evidence.app_hash:
                    return None
            return evidence
        except Exception:
            return None
