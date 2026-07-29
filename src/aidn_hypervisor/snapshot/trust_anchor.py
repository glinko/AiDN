"""RFC-0062 §30-§36 — Trust Anchor management, checkpoint validation, long-range attack resistance.

Trust anchors are trusted checkpoints that allow nodes to bootstrap without replaying
from genesis.  They encode the canonical state at a specific block height along with
chain identity metadata.

Checkpoint age limits (§35) enforce both block-distance and wall-clock constraints to
prevent long-range attacks where an adversary presents an ancient checkpoint as current.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, Field


class TrustAnchorError(ValueError):
    """A trust anchor is untrusted, malformed, conflicting, or unavailable."""

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


def _canonical_anchor_payload(*, anchor: TrustAnchor, signer_id: str, issued_at: str) -> bytes:
    return json.dumps(
        {
            "anchor": anchor.model_dump(mode="json"),
            "issued_at": issued_at,
            "signer_id": signer_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


class SignedTrustAnchor(BaseModel, frozen=True):
    """A remote checkpoint anchor signed by one locally trusted authority."""

    anchor: TrustAnchor
    signer_id: str = Field(min_length=1)
    issued_at: str = Field(min_length=1)
    signature: str = Field(min_length=1)

    def signing_payload(self) -> bytes:
        return _canonical_anchor_payload(
            anchor=self.anchor,
            signer_id=self.signer_id,
            issued_at=self.issued_at,
        )


def sign_trust_anchor(
    *,
    anchor: TrustAnchor,
    signer_id: str,
    issued_at: str,
    private_key: bytes,
) -> SignedTrustAnchor:
    """Create a test or operator envelope from a raw 32-byte Ed25519 key."""
    try:
        key = Ed25519PrivateKey.from_private_bytes(private_key)
    except ValueError as error:
        raise TrustAnchorError("trust anchor signing key is invalid") from error
    payload = _canonical_anchor_payload(anchor=anchor, signer_id=signer_id, issued_at=issued_at)
    return SignedTrustAnchor(
        anchor=anchor,
        signer_id=signer_id,
        issued_at=issued_at,
        signature="ed25519:" + key.sign(payload).hex(),
    )


def verify_signed_trust_anchor(
    *, envelope: SignedTrustAnchor,
    trusted_signers: dict[str, str],
) -> None:
    """Verify an envelope strictly against the operator's configured keyring."""
    public_key = trusted_signers.get(envelope.signer_id)
    if public_key is None:
        raise TrustAnchorError("trust anchor signer is not locally trusted")
    if not public_key.startswith("ed25519:") or not envelope.signature.startswith("ed25519:"):
        raise TrustAnchorError("trust anchor signature encoding is invalid")
    try:
        key_bytes = bytes.fromhex(public_key.removeprefix("ed25519:"))
        signature = bytes.fromhex(envelope.signature.removeprefix("ed25519:"))
        if len(key_bytes) != 32 or len(signature) != 64:
            raise ValueError("unexpected Ed25519 key or signature length")
        Ed25519PublicKey.from_public_bytes(key_bytes).verify(signature, envelope.signing_payload())
    except (InvalidSignature, ValueError) as error:
        raise TrustAnchorError("trust anchor signature is invalid") from error


class PersistentTrustAnchorStore:
    """Durably retain only signatures verified against a local trust keyring."""

    _FORMAT_VERSION = 1

    def __init__(self, *, path: Path, trusted_signers: dict[str, str]) -> None:
        if not trusted_signers:
            raise TrustAnchorError("persistent trust anchor store requires trusted signers")
        self._path = path
        self._trusted_signers = dict(trusted_signers)
        self._anchors = self._load()

    def add(self, envelope: SignedTrustAnchor) -> None:
        verify_signed_trust_anchor(envelope=envelope, trusted_signers=self._trusted_signers)
        for existing in self._anchors:
            if existing.anchor == envelope.anchor:
                if existing != envelope:
                    raise TrustAnchorError("trust anchor identity has conflicting signature evidence")
                return
            if (
                existing.anchor.network_id == envelope.anchor.network_id
                and existing.anchor.chain_id == envelope.anchor.chain_id
                and existing.anchor.network_revision == envelope.anchor.network_revision
                and existing.anchor.block_height == envelope.anchor.block_height
            ):
                raise TrustAnchorError("conflicting trust anchor exists at this block height")
        self._anchors.append(envelope)
        self._persist()

    def latest(self) -> SignedTrustAnchor | None:
        if not self._anchors:
            return None
        return max(self._anchors, key=lambda item: item.anchor.block_height)

    def all(self) -> list[SignedTrustAnchor]:
        return sorted(self._anchors, key=lambda item: item.anchor.block_height)

    def _load(self) -> list[SignedTrustAnchor]:
        if not self._path.exists():
            return []
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if payload.get("format_version") != self._FORMAT_VERSION:
                raise ValueError("unsupported trust anchor store format")
            entries = payload["anchors"]
            if not isinstance(entries, list):
                raise ValueError("trust anchors must be a list")
            envelopes = [SignedTrustAnchor.model_validate(entry) for entry in entries]
            for envelope in envelopes:
                verify_signed_trust_anchor(
                    envelope=envelope, trusted_signers=self._trusted_signers
                )
            return envelopes
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise TrustAnchorError("persistent trust anchor store is invalid") from error

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            {
                "format_version": self._FORMAT_VERSION,
                "anchors": [item.model_dump(mode="json") for item in self.all()],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        descriptor, temporary_path = tempfile.mkstemp(
            dir=self._path.parent, prefix=f".{self._path.name}."
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self._path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)


class RemoteTrustAnchorClient:
    """Fetch one signed trust anchor over bounded HTTPS without redirects."""

    def __init__(self, *, timeout_seconds: float = 15, maximum_bytes: int = 128 * 1024) -> None:
        if timeout_seconds <= 0 or maximum_bytes <= 0:
            raise ValueError("remote trust anchor bounds must be positive")
        self._timeout_seconds = timeout_seconds
        self._maximum_bytes = maximum_bytes
        self._opener = urllib_request.build_opener(_RejectRedirect())

    def fetch(self, source_url: str) -> SignedTrustAnchor:
        parsed = urllib_parse.urlparse(source_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise TrustAnchorError("remote trust anchor source must use credential-free HTTPS")
        request = urllib_request.Request(source_url, method="GET", headers={"Accept": "application/json"})
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                raw = response.read(self._maximum_bytes + 1)
        except (OSError, urllib_error.URLError, urllib_error.HTTPError) as error:
            raise TrustAnchorError("remote trust anchor cannot be fetched") from error
        if len(raw) > self._maximum_bytes:
            raise TrustAnchorError("remote trust anchor exceeds size limit")
        try:
            return SignedTrustAnchor.model_validate_json(raw)
        except ValueError as error:
            raise TrustAnchorError("remote trust anchor response is invalid") from error


class _RejectRedirect(urllib_request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise TrustAnchorError("remote trust anchor redirects are not permitted")


class TrustedAnchorSyncAdvisor:
    """Project one verified persistent anchor into checkpoint-sync eligibility."""

    def __init__(
        self,
        *,
        store: PersistentTrustAnchorStore,
        validator: CheckpointValidator,
        expected_network_id: str,
        expected_chain_id: str,
        expected_network_revision: int,
    ) -> None:
        self._store = store
        self._validator = validator
        self._expected_network_id = expected_network_id
        self._expected_chain_id = expected_chain_id
        self._expected_network_revision = expected_network_revision

    def eligibility(self, *, current_height: int, current_time: str) -> tuple[bool, int]:
        envelope = self._store.latest()
        if envelope is None:
            return False, 0
        result = self._validator.validate(
            envelope.anchor, current_height=current_height, current_time=current_time
        )
        if not result.valid or not self._validator.validate_chain_identity(
            envelope.anchor,
            expected_network_id=self._expected_network_id,
            expected_chain_id=self._expected_chain_id,
        ):
            return False, 0
        if envelope.anchor.network_revision != self._expected_network_revision:
            return False, 0
        return True, envelope.anchor.block_height

    def apply_to_sync_mode_config(self, config, *, current_height: int, current_time: str):
        """Return a SyncModeConfig whose checkpoint eligibility is evidence-derived."""
        eligible, height = self.eligibility(
            current_height=current_height, current_time=current_time
        )
        return config.model_copy(
            update={
                "trust_anchor_available": eligible,
                "trust_anchor_valid": eligible,
                "trust_anchor_height": height,
            }
        )


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

        if anchor.expires_at is not None:
            try:
                expires = datetime.fromisoformat(anchor.expires_at)
                now = datetime.fromisoformat(current_time)
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=UTC)
                if now.tzinfo is None:
                    now = now.replace(tzinfo=UTC)
                if now > expires:
                    reasons.append("checkpoint explicit expiry exceeded")
            except (ValueError, TypeError):
                reasons.append("unable to parse expires_at timestamp")

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

        if anchor.expires_at is not None:
            try:
                expires = datetime.fromisoformat(anchor.expires_at)
                now = datetime.fromisoformat(current_time)
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=UTC)
                if now.tzinfo is None:
                    now = now.replace(tzinfo=UTC)
                if now > expires:
                    return False
            except (ValueError, TypeError):
                return False

        return True
