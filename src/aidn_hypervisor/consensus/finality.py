"""Verified consensus finality boundary.

Local submission state is useful for operations, but it is not proof that a
network finalized an operation.  Adapters such as a CometBFT RPC verifier feed
validated evidence through this narrow interface; consumers fail closed when
the adapter is absent, unavailable, or returns mismatched evidence.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
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
    # The transaction payload is already bound by operation_id. Keeping the
    # decoded operation type here lets consumers reject a valid proof for the
    # wrong protocol operation without trusting a caller-supplied label.
    operation_type: str = ""

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


class QuorumConsensusFinalitySource:
    """Require matching finality evidence from a bounded source quorum.

    Source identities are configuration labels, not proof of organizational
    independence. The class only establishes that the configured verifiers
    independently returned the same operation-bound evidence.
    """

    def __init__(
        self,
        *,
        sources: Sequence[ConsensusFinalitySource],
        quorum: int,
        source_ids: Sequence[str] | None = None,
    ) -> None:
        if len(sources) < 2:
            raise ValueError("finality quorum requires at least two sources")
        if not 1 <= quorum <= len(sources):
            raise ValueError("finality quorum must be within the source count")
        resolved_ids = tuple(source_ids or (f"source-{index}" for index in range(len(sources))))
        if len(resolved_ids) != len(sources) or any(not value.strip() for value in resolved_ids):
            raise ValueError("finality source IDs must match sources and be non-empty")
        if len(set(resolved_ids)) != len(resolved_ids):
            raise ValueError("finality source IDs must be unique")
        self._sources = tuple(sources)
        self._quorum = quorum
        self._source_ids = resolved_ids

    @property
    def quorum(self) -> int:
        return self._quorum

    @property
    def source_count(self) -> int:
        return len(self._sources)

    def finality_evidence(self, operation_id: str) -> ConsensusFinalityEvidence | None:
        evidence_groups: dict[tuple[object, ...], list[ConsensusFinalityEvidence]] = defaultdict(list)
        for source in self._sources:
            try:
                evidence = source.finality_evidence(operation_id)
            except Exception:
                evidence = None
            if evidence is None or evidence.operation_id != operation_id:
                continue
            evidence_groups[self._fingerprint(evidence)].append(evidence)

        winning_count = max(
            (len(group) for group in evidence_groups.values()),
            default=0,
        )
        winning_groups = [
            group for group in evidence_groups.values() if len(group) == winning_count
        ]
        if winning_count < self._quorum or len(winning_groups) != 1:
            return None
        return winning_groups[0][0]

    @staticmethod
    def _fingerprint(evidence: ConsensusFinalityEvidence) -> tuple[object, ...]:
        return (
            evidence.operation_id,
            evidence.chain_id,
            evidence.block_height,
            evidence.block_id,
            evidence.app_hash,
            evidence.commit_hash,
            evidence.finalized_at,
            evidence.proof_version,
            evidence.operation_type,
        )
