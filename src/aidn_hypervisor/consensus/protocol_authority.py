"""Threshold authorization for protocol-owned consensus operations.

CometBFT finality proves that validators agreed on a block.  It does not by
itself prove that an epoch transition was produced by an authorized protocol
controller.  This module provides the separate, hash-bound Ed25519 quorum
proof used by the strict validator path.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope

PROTOCOL_AUTHORITY_POLICY_VERSION = "aidn.protocol-authority.v1"
PROTOCOL_AUTHORITY_POLICY_HASH_FIELD = "protocol_authority_policy_hash"
EPOCH_TRANSITION_AUTHORITY_HASH_FIELD = PROTOCOL_AUTHORITY_POLICY_HASH_FIELD
EPOCH_SCHEDULE_COMMIT_AUTHORITY_HASH_FIELD = PROTOCOL_AUTHORITY_POLICY_HASH_FIELD
MAX_PROTOCOL_AUTHORITY_SIGNATURES = 8


class ProtocolAuthorityError(ValueError):
    """Raised when a protocol operation lacks a valid authority proof."""


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _decode_ed25519(value: str, *, label: str, expected_size: int) -> bytes:
    if not isinstance(value, str) or not value.startswith("ed25519:"):
        raise ProtocolAuthorityError(f"{label} must use ed25519 encoding")
    encoded = value.removeprefix("ed25519:")
    try:
        raw = bytes.fromhex(encoded)
    except ValueError:
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as error:
            raise ProtocolAuthorityError(f"{label} is invalid") from error
    if len(raw) != expected_size:
        raise ProtocolAuthorityError(f"{label} must contain {expected_size} bytes")
    return raw


def normalize_ed25519_public_key(value: str) -> str:
    """Normalize hex or base64 public-key input to canonical hex encoding."""
    return "ed25519:" + _decode_ed25519(
        value,
        label="protocol authority public key",
        expected_size=32,
    ).hex()


@dataclass(frozen=True)
class ProtocolAuthorityPolicy:
    """Hash-bound public-key set and threshold for protocol transitions."""

    threshold: int
    authorities: tuple[tuple[str, str], ...]
    version: str = PROTOCOL_AUTHORITY_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.version != PROTOCOL_AUTHORITY_POLICY_VERSION:
            raise ProtocolAuthorityError("unsupported protocol authority policy version")
        if isinstance(self.threshold, bool) or self.threshold < 1:
            raise ProtocolAuthorityError("protocol authority threshold must be positive")
        if self.threshold > MAX_PROTOCOL_AUTHORITY_SIGNATURES:
            raise ProtocolAuthorityError(
                "protocol authority threshold exceeds envelope signature capacity"
            )
        if not self.authorities:
            if self.threshold != 1:
                raise ProtocolAuthorityError("empty protocol authority policy must use threshold one")
            return
        if len({authority_id for authority_id, _ in self.authorities}) != len(self.authorities):
            raise ProtocolAuthorityError("protocol authority IDs must be unique")
        if len({public_key for _, public_key in self.authorities}) != len(self.authorities):
            raise ProtocolAuthorityError("protocol authority public keys must be unique")
        if self.threshold > len(self.authorities):
            raise ProtocolAuthorityError("protocol authority threshold exceeds authority set")
        for authority_id, public_key in self.authorities:
            if not isinstance(authority_id, str) or not authority_id.strip():
                raise ProtocolAuthorityError("protocol authority ID is required")
            _decode_ed25519(
                public_key,
                label=f"protocol authority public key for {authority_id}",
                expected_size=32,
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> ProtocolAuthorityPolicy:
        """Build a policy from the public JSON deployment representation."""
        if not isinstance(value, Mapping):
            raise ProtocolAuthorityError("protocol authority policy must be an object")
        version = value.get("version", PROTOCOL_AUTHORITY_POLICY_VERSION)
        threshold = value.get("threshold")
        raw_authorities = value.get("authorities")
        if isinstance(threshold, bool) or not isinstance(threshold, int):
            raise ProtocolAuthorityError("protocol authority threshold must be an integer")
        if not isinstance(raw_authorities, Mapping):
            raise ProtocolAuthorityError("protocol authority authorities must be an object")
        authorities = tuple(
            sorted(
                (
                    str(authority_id),
                    normalize_ed25519_public_key(str(public_key)),
                )
                for authority_id, public_key in raw_authorities.items()
            )
        )
        policy = cls(threshold=threshold, authorities=authorities, version=str(version))
        declared_hash = value.get("policy_hash")
        if declared_hash is not None and declared_hash != policy.policy_hash:
            raise ProtocolAuthorityError("protocol authority policy hash is invalid")
        return policy

    @classmethod
    def empty(cls) -> ProtocolAuthorityPolicy:
        """Return a fail-closed policy used when a validator is unconfigured."""
        return cls(threshold=1, authorities=())

    @property
    def policy_hash(self) -> str:
        payload = {
            "authorities": [
                {"authority_id": authority_id, "public_key": public_key}
                for authority_id, public_key in self.authorities
            ],
            "threshold": self.threshold,
            "version": self.version,
        }
        return "sha256:" + hashlib.sha256(_canonical_json(payload)).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "threshold": self.threshold,
            "authorities": {authority_id: public_key for authority_id, public_key in self.authorities},
            "policy_hash": self.policy_hash,
        }

    def verify_epoch_transition(self, envelope: LedgerOperationEnvelope) -> None:
        """Verify the exact quorum proof required by ``EPOCH_TRANSITION``."""
        self._verify_protocol_operation(
            envelope,
            operation_type="EPOCH_TRANSITION",
            operation_label="epoch transition",
            policy_hash_field=EPOCH_TRANSITION_AUTHORITY_HASH_FIELD,
        )

    def verify_epoch_schedule_commit(self, envelope: LedgerOperationEnvelope) -> None:
        """Verify the authority quorum for the canonical initial schedule."""
        self._verify_protocol_operation(
            envelope,
            operation_type="EPOCH_SCHEDULE_COMMIT",
            operation_label="epoch schedule commit",
            policy_hash_field=EPOCH_SCHEDULE_COMMIT_AUTHORITY_HASH_FIELD,
        )

    def _verify_protocol_operation(
        self,
        envelope: LedgerOperationEnvelope,
        *,
        operation_type: str,
        operation_label: str,
        policy_hash_field: str,
    ) -> None:
        if envelope.operation_type != operation_type:
            raise ProtocolAuthorityError(f"protocol authority requires {operation_type}")
        if envelope.origin_type != "protocol" or envelope.sender_wallet is not None:
            raise ProtocolAuthorityError(f"{operation_label} requires protocol origin")
        if not self.authorities:
            raise ProtocolAuthorityError(f"{operation_type}_AUTHORITY_POLICY_REQUIRED")
        if envelope.payload.get(policy_hash_field) != self.policy_hash:
            raise ProtocolAuthorityError(f"{operation_type}_AUTHORITY_POLICY_HASH_MISMATCH")
        if len(envelope.signatures) < self.threshold:
            raise ProtocolAuthorityError(f"{operation_type}_AUTHORITY_SIGNATURE_REQUIRED")

        signing_bytes = envelope.signing_bytes()
        matched: set[str] = set()
        for signature in envelope.signatures:
            signature_bytes = _decode_ed25519(
                signature,
                label="protocol authority signature",
                expected_size=64,
            )
            for authority_id, public_key in self.authorities:
                if authority_id in matched:
                    continue
                try:
                    Ed25519PublicKey.from_public_bytes(
                        bytes.fromhex(public_key.removeprefix("ed25519:"))
                    ).verify(signature_bytes, signing_bytes)
                except (InvalidSignature, ValueError):
                    continue
                matched.add(authority_id)
                break

        if len(matched) < self.threshold:
            raise ProtocolAuthorityError(f"{operation_type}_AUTHORITY_QUORUM_NOT_MET")


__all__ = [
    "EPOCH_TRANSITION_AUTHORITY_HASH_FIELD",
    "EPOCH_SCHEDULE_COMMIT_AUTHORITY_HASH_FIELD",
    "MAX_PROTOCOL_AUTHORITY_SIGNATURES",
    "PROTOCOL_AUTHORITY_POLICY_VERSION",
    "PROTOCOL_AUTHORITY_POLICY_HASH_FIELD",
    "ProtocolAuthorityError",
    "ProtocolAuthorityPolicy",
    "normalize_ed25519_public_key",
]
