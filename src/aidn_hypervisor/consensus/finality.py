"""Verified consensus finality boundary.

Local submission state is useful for operations, but it is not proof that a
network finalized an operation.  Adapters such as a CometBFT RPC verifier feed
validated evidence through this narrow interface; consumers fail closed when
the adapter is absent, unavailable, or returns mismatched evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ConsensusFinalityEvidence:
    """Immutable evidence that one operation is included in a finalized block."""

    operation_id: str
    chain_id: str
    block_height: int
    block_id: str
    app_hash: str
    commit_hash: str
    finalized_at: str
    verifier_id: str
    proof_version: str = "consensus-finality-evidence.v1"

    def __post_init__(self) -> None:
        required_text = {
            "operation_id": self.operation_id,
            "chain_id": self.chain_id,
            "block_id": self.block_id,
            "commit_hash": self.commit_hash,
            "finalized_at": self.finalized_at,
            "verifier_id": self.verifier_id,
        }
        if any(not value.strip() for value in required_text.values()):
            raise ValueError("Consensus finality evidence has an empty required field")
        if not isinstance(self.app_hash, str):
            raise ValueError("Consensus finality evidence app_hash is invalid")
        if self.block_height < 1:
            raise ValueError("Consensus finality evidence block_height must be positive")
        if self.proof_version != "consensus-finality-evidence.v1":
            raise ValueError("Consensus finality evidence version is unsupported")

    def model_dump(self) -> dict:
        return asdict(self)


@runtime_checkable
class ConsensusFinalitySource(Protocol):
    """Supplies only evidence already verified against the active network."""

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        """Return verified finality evidence for an exact operation, if available."""


class VerifiedConsensusFinalitySource:
    """Fail-closed adapter shell for a network-specific finality verifier.

    ``load`` may fetch a CometBFT commit proof from any transport.  ``verify``
    must validate its signatures, validator set, block commitment and operation
    inclusion before returning ``True``.  This class also checks that evidence
    remains bound to the requested operation.
    """

    def __init__(
        self,
        *,
        load: Callable[[str], ConsensusFinalityEvidence | None],
        verify: Callable[[ConsensusFinalityEvidence], bool],
    ) -> None:
        self._load = load
        self._verify = verify

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        try:
            evidence = self._load(operation_id)
            if evidence is None or evidence.operation_id != operation_id:
                return None
            return evidence if self._verify(evidence) else None
        except Exception:
            return None
