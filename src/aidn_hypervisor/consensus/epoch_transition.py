"""Build and sign protocol-authorized epoch transition envelopes.

This module is intentionally offline-only. It creates a canonical envelope
and verifies the authority quorum, but it never submits a transaction or
mutates a Ledger.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.protocol_authority import (
    ProtocolAuthorityPolicy,
    normalize_ed25519_public_key,
)
from aidn_hypervisor.ledger.service import LedgerOperationService


def load_protocol_authority_private_key(path: Path) -> Ed25519PrivateKey:
    """Load one external Ed25519 key without emitting its private material."""
    raw = path.read_bytes()
    if raw.startswith(b"-----BEGIN"):
        key = serialization.load_pem_private_key(raw, password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("protocol authority private key must be Ed25519")
        return key

    value = raw.decode("ascii").strip()
    if value.startswith("ed25519:"):
        value = value.removeprefix("ed25519:")
    try:
        seed = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError(
            "protocol authority private key must be a PEM key or 32-byte hex seed"
        ) from error
    if len(seed) != 32:
        raise ValueError("protocol authority private key hex seed must contain 32 bytes")
    return Ed25519PrivateKey.from_private_bytes(seed)


def _public_key_for_private_key(key: Ed25519PrivateKey) -> str:
    return normalize_ed25519_public_key(
        "ed25519:"
        + key.public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        .hex()
    )


def sign_epoch_transition(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    signers: Mapping[str, Ed25519PrivateKey],
) -> LedgerOperationEnvelope:
    """Return an envelope signed by distinct policy authorities.

    The signer mapping is keyed by authority ID. Every supplied signer must be
    present in the policy and control the public key registered for that ID.
    Signatures are emitted in authority-ID order so the public artifact is
    reproducible regardless of CLI argument order.
    """
    if envelope.operation_type != "EPOCH_TRANSITION":
        raise ValueError("protocol authority signing requires EPOCH_TRANSITION")
    if not signers:
        raise ValueError("at least one protocol authority signer is required")

    authority_keys = dict(policy.authorities)
    unknown = sorted(set(signers) - set(authority_keys))
    if unknown:
        raise ValueError(f"protocol authority signer is not in policy: {unknown[0]}")
    if len(signers) < policy.threshold:
        raise ValueError("protocol authority signer quorum is not met")

    for authority_id, key in signers.items():
        if _public_key_for_private_key(key) != authority_keys[authority_id]:
            raise ValueError(f"protocol authority private key does not match: {authority_id}")

    signatures = [
        "ed25519:" + signers[authority_id].sign(envelope.signing_bytes()).hex()
        for authority_id in sorted(signers)
    ]
    signed = envelope.model_copy(update={"signatures": signatures})
    policy.verify_epoch_transition(signed)
    return signed


def build_signed_epoch_transition(
    *,
    policy: ProtocolAuthorityPolicy,
    payload: Mapping[str, object],
    signers: Mapping[str, Ed25519PrivateKey],
    created_at: str,
    expires_at: str | None = None,
    initiator_id: str = "epoch-engine",
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
) -> LedgerOperationEnvelope:
    """Build, Ledger-validate and authority-sign one epoch transition."""
    transition_payload = dict(payload)
    declared_hash = transition_payload.get("protocol_authority_policy_hash")
    if declared_hash is not None and declared_hash != policy.policy_hash:
        raise ValueError("epoch transition policy hash does not match policy")
    transition_payload["protocol_authority_policy_hash"] = policy.policy_hash

    closing_epoch = transition_payload.get("closing_epoch")
    if isinstance(closing_epoch, bool) or not isinstance(closing_epoch, int) or closing_epoch < 0:
        raise ValueError("epoch transition closing epoch is invalid")
    target_epoch = str(closing_epoch)
    unsigned = LedgerOperationEnvelope(
        operation_type="EPOCH_TRANSITION",
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="protocol",
        initiator_id=initiator_id,
        fee_class="protocol_sponsored",
        created_at=created_at,
        expires_at=expires_at,
        target_epoch=target_epoch,
        payload=transition_payload,
    )

    # Reuse the canonical Ledger validator before private-key signing. This
    # keeps the offline artifact subject to the same payload rules as ABCI.
    LedgerOperationService().validate_consensus_epoch_transition(unsigned)
    return sign_epoch_transition(unsigned, policy=policy, signers=signers)


def restrict_private_key_file(path: Path) -> None:
    """Best-effort owner-only permissions for Unix operator key files."""
    if os.name != "nt":
        path.chmod(0o600)


__all__ = [
    "build_signed_epoch_transition",
    "load_protocol_authority_private_key",
    "restrict_private_key_file",
    "sign_epoch_transition",
]
