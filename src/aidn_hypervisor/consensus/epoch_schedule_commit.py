"""Offline construction and threshold signing for the canonical epoch schedule."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.epoch_schedule import EpochSchedule
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.protocol_authority import (
    EPOCH_SCHEDULE_COMMIT_AUTHORITY_HASH_FIELD,
    ProtocolAuthorityPolicy,
)
from aidn_hypervisor.ledger.service import LedgerOperationService

EPOCH_SCHEDULE_COMMIT_OPERATION = "EPOCH_SCHEDULE_COMMIT"


def _public_key_for_private_key(key: Ed25519PrivateKey) -> str:
    return "ed25519:" + key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    ).hex()


def load_protocol_authority_private_key(path: Path) -> Ed25519PrivateKey:
    """Load one external Ed25519 private key without exporting it."""
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


def build_unsigned_epoch_schedule_commit(
    *,
    policy: ProtocolAuthorityPolicy,
    schedule: EpochSchedule,
    created_at: str,
    expires_at: str | None = None,
    initiator_id: str = "epoch-engine",
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
    evidence_references: list[str] | None = None,
) -> LedgerOperationEnvelope:
    """Build the one unsigned, policy-bound schedule commitment."""
    if not isinstance(schedule, EpochSchedule):
        schedule = EpochSchedule.model_validate(schedule)
    payload = schedule.model_dump(mode="json")
    envelope = LedgerOperationEnvelope(
        operation_type=EPOCH_SCHEDULE_COMMIT_OPERATION,
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="protocol",
        initiator_id=initiator_id,
        fee_class="protocol_sponsored",
        created_at=created_at,
        expires_at=expires_at,
        target_epoch="0",
        payload={
            "epoch_schedule": payload,
            EPOCH_SCHEDULE_COMMIT_AUTHORITY_HASH_FIELD: policy.policy_hash,
        },
        evidence_references=sorted(set(evidence_references or [])),
    )
    LedgerOperationService().validate_consensus_epoch_schedule_commit(envelope)
    return envelope


def sign_epoch_schedule_commit_signature(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    authority_id: str,
    private_key: Ed25519PrivateKey,
) -> str:
    """Sign one unsigned schedule commitment as one declared authority."""
    if envelope.operation_type != EPOCH_SCHEDULE_COMMIT_OPERATION:
        raise ValueError("protocol authority signing requires EPOCH_SCHEDULE_COMMIT")
    if envelope.signatures:
        raise ValueError("protocol authority signer input must be unsigned")
    LedgerOperationService().validate_consensus_epoch_schedule_commit(envelope)
    expected_key = dict(policy.authorities).get(authority_id)
    if expected_key is None:
        raise ValueError(f"protocol authority signer is not in policy: {authority_id}")
    if envelope.payload.get(EPOCH_SCHEDULE_COMMIT_AUTHORITY_HASH_FIELD) != policy.policy_hash:
        raise ValueError("epoch schedule commit policy hash does not match policy")
    if _public_key_for_private_key(private_key) != expected_key:
        raise ValueError(f"protocol authority private key does not match: {authority_id}")
    return "ed25519:" + private_key.sign(envelope.signing_bytes()).hex()


def combine_epoch_schedule_commit_signatures(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    signatures: Mapping[str, str],
) -> LedgerOperationEnvelope:
    """Attach independently produced signatures and verify the threshold."""
    if envelope.operation_type != EPOCH_SCHEDULE_COMMIT_OPERATION:
        raise ValueError("protocol authority signing requires EPOCH_SCHEDULE_COMMIT")
    if envelope.signatures:
        raise ValueError("protocol authority combiner input must be unsigned")
    if not signatures:
        raise ValueError("at least one protocol authority signature is required")
    LedgerOperationService().validate_consensus_epoch_schedule_commit(envelope)
    unknown = sorted(set(signatures) - {authority_id for authority_id, _ in policy.authorities})
    if unknown:
        raise ValueError(f"protocol authority signer is not in policy: {unknown[0]}")
    signed = envelope.model_copy(
        update={"signatures": [signatures[authority_id] for authority_id in sorted(signatures)]}
    )
    policy.verify_epoch_schedule_commit(signed)
    return signed


def sign_epoch_schedule_commit(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    signers: Mapping[str, Ed25519PrivateKey],
) -> LedgerOperationEnvelope:
    """Sign one schedule commitment with the declared authority quorum."""
    if len(signers) < policy.threshold:
        raise ValueError("protocol authority signer quorum is not met")
    signatures = {
        authority_id: sign_epoch_schedule_commit_signature(
            envelope,
            policy=policy,
            authority_id=authority_id,
            private_key=private_key,
        )
        for authority_id, private_key in signers.items()
    }
    return combine_epoch_schedule_commit_signatures(
        envelope,
        policy=policy,
        signatures=signatures,
    )


def build_signed_epoch_schedule_commit(
    *,
    policy: ProtocolAuthorityPolicy,
    schedule: EpochSchedule,
    signers: Mapping[str, Ed25519PrivateKey],
    created_at: str,
    expires_at: str | None = None,
    initiator_id: str = "epoch-engine",
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
) -> LedgerOperationEnvelope:
    """Build and threshold-sign one canonical schedule commitment."""
    unsigned = build_unsigned_epoch_schedule_commit(
        policy=policy,
        schedule=schedule,
        created_at=created_at,
        expires_at=expires_at,
        initiator_id=initiator_id,
        operation_version=operation_version,
        protocol_version=protocol_version,
    )
    return sign_epoch_schedule_commit(unsigned, policy=policy, signers=signers)


__all__ = [
    "EPOCH_SCHEDULE_COMMIT_OPERATION",
    "build_signed_epoch_schedule_commit",
    "build_unsigned_epoch_schedule_commit",
    "combine_epoch_schedule_commit_signatures",
    "load_protocol_authority_private_key",
    "sign_epoch_schedule_commit",
    "sign_epoch_schedule_commit_signature",
]
