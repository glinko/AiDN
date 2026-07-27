"""RFC-0062 §30-§36 — Trust Anchor management, checkpoint validation, long-range attack resistance.

Trust anchors are trusted checkpoints that allow nodes to bootstrap without replaying
from genesis.  They encode the canonical state at a specific block height along with
chain identity metadata.

Checkpoint age limits (§35) enforce both block-distance and wall-clock constraints to
prevent long-range attacks where an adversary presents an ancient checkpoint as current.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

# ── Trust Anchor ───────────────────────────────────────────────────

class TrustAnchor(BaseModel, frozen=True):
    """RFC-0062 §30 — Trusted checkpoint anchor.

    A trust anchor represents a verified snapshot of canonical chain state at a
    specific block height.  It is the root of trust for checkpoint-based sync.
    """

    network_id: str
    chain_id: str
    network_revision: int = Field(ge=0)
    block_height: int = Field(ge=0)
    block_hash: str
    application_state_hash: str
    validator_set_hash: str
    protocol_version: str
    source: str
    """One of: local_state, software_release, operator_config, deployment_image."""
    created_at: str
    """ISO-8601 timestamp when this anchor was created."""
    expires_at: str | None = None
    """ISO-8601 expiry; None means no explicit expiry."""


# ── Trust Anchor Store ─────────────────────────────────────────────

class TrustAnchorStore:
    """In-memory collection of trust anchors.

    Anchors are stored in insertion order.  ``get_latest`` returns the one with the
    highest ``block_height``.  ``get_for_height`` returns the closest anchor whose
    height is **≤** the requested height.
    """

    def __init__(self) -> None:
        self._anchors: list[TrustAnchor] = []

    def add(self, anchor: TrustAnchor) -> None:
        """Add a trusted checkpoint anchor."""
        self._anchors.append(anchor)

    def get_latest(self) -> TrustAnchor | None:
        """Return the anchor with the highest *block_height*, or ``None``."""
        if not self._anchors:
            return None
        return max(self._anchors, key=lambda a: a.block_height)

    def get_for_height(self, height: int) -> TrustAnchor | None:
        """Return the closest anchor whose *block_height* ≤ *height*.

        Returns ``None`` when no anchor exists at or below the requested height.
        """
        candidates = [a for a in self._anchors if a.block_height <= height]
        if not candidates:
            return None
        return max(candidates, key=lambda a: a.block_height)

    def remove_expired(self, current_time: str) -> int:
        """Remove anchors whose ``expires_at`` is in the past.

        Anchors with ``expires_at=None`` are never removed.

        :returns: number of anchors removed.
        """
        before = len(self._anchors)
        self._anchors = [
            a
            for a in self._anchors
            if a.expires_at is None or a.expires_at >= current_time
        ]
        return before - len(self._anchors)

    def count(self) -> int:
        """Number of anchors in the store."""
        return len(self._anchors)

    def has_anchor_for(self, height: int) -> bool:
        """Whether any anchor exists at or below *height*."""
        return any(a.block_height <= height for a in self._anchors)


# ── Checkpoint Validation Result ───────────────────────────────────

class CheckpointValidationResult(BaseModel, frozen=True):
    """Result of validating a trust anchor checkpoint."""

    valid: bool
    reasons: list[str] = Field(default_factory=list)
    """Failure reasons (empty when *valid* is ``True``)."""
    anchor: TrustAnchor


# ── Checkpoint Validator ───────────────────────────────────────────

class CheckpointValidator:
    """RFC-0062 §35-§36 — Validate trust anchors against age and identity constraints.

    Enforces:
    - Chain identity non-empty (§83)
    - Block height > 0
    - Required hashes present
    - Block-distance trust period (default 10 000 blocks)
    - Wall-clock trust period (default 30 days)
    """

    def __init__(
        self,
        *,
        max_checkpoint_age_blocks: int = 10_000,
        max_checkpoint_age_seconds: int = 2_592_000,
    ) -> None:
        self.max_checkpoint_age_blocks = max_checkpoint_age_blocks
        self.max_checkpoint_age_seconds = max_checkpoint_age_seconds

    # ── public API ───────────────────────────────────────────────

    def validate(
        self,
        anchor: TrustAnchor,
        *,
        current_height: int,
        current_time: str,
    ) -> CheckpointValidationResult:
        """Validate a trust anchor.

        Checks:
        1. Chain identity present (network_id, chain_id)
        2. Block height > 0
        3. Required hashes non-empty
        4. Within block-distance trust period
        5. Within wall-clock trust period
        """
        reasons: list[str] = []

        # §83 — chain identity must be present
        if not anchor.network_id:
            reasons.append("network_id is empty")
        if not anchor.chain_id:
            reasons.append("chain_id is empty")

        # height must be > 0
        if anchor.block_height <= 0:
            reasons.append(f"block_height must be > 0, got {anchor.block_height}")

        # hashes must be present
        if not anchor.block_hash:
            reasons.append("block_hash is empty")
        if not anchor.application_state_hash:
            reasons.append("application_state_hash is empty")
        if not anchor.validator_set_hash:
            reasons.append("validator_set_hash is empty")

        # trust period — block distance
        block_distance = current_height - anchor.block_height
        if block_distance > self.max_checkpoint_age_blocks:
            reasons.append(
                f"checkpoint too old by block distance: "
                f"{block_distance} > {self.max_checkpoint_age_blocks}"
            )

        # trust period — wall-clock
        try:
            created = datetime.fromisoformat(anchor.created_at)
            now = datetime.fromisoformat(current_time)
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if now.tzinfo is None:
                now = now.replace(tzinfo=UTC)
            age_seconds = (now - created).total_seconds()
            if age_seconds > self.max_checkpoint_age_seconds:
                reasons.append(
                    f"checkpoint wall-clock age exceeded: "
                    f"{int(age_seconds)}s > {self.max_checkpoint_age_seconds}s"
                )
        except (ValueError, TypeError):
            reasons.append("unable to parse created_at timestamp")

        return CheckpointValidationResult(
            valid=len(reasons) == 0,
            reasons=reasons,
            anchor=anchor,
        )

    def validate_chain_identity(
        self,
        anchor: TrustAnchor,
        *,
        expected_network_id: str,
        expected_chain_id: str,
    ) -> bool:
        """RFC-0062 §83 — Verify chain identity matches expectations."""
        return (
            anchor.network_id == expected_network_id
            and anchor.chain_id == expected_chain_id
        )

    def is_within_trust_period(
        self,
        anchor: TrustAnchor,
        *,
        current_height: int,
        current_time: str,
    ) -> bool:
        """RFC-0062 §35 — Whether the anchor falls within the trust period.

        Both block-distance and wall-clock checks must pass.
        """
        # block distance check
        block_distance = current_height - anchor.block_height
        if block_distance > self.max_checkpoint_age_blocks:
            return False

        # wall-clock check
        try:
            created = datetime.fromisoformat(anchor.created_at)
            now = datetime.fromisoformat(current_time)
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if now.tzinfo is None:
                now = now.replace(tzinfo=UTC)
            age_seconds = (now - created).total_seconds()
            if age_seconds > self.max_checkpoint_age_seconds:
                return False
        except (ValueError, TypeError):
            return False

        return True
