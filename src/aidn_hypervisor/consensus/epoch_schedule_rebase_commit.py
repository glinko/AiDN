"""Offline construction and threshold signing for controlled schedule recovery."""

from __future__ import annotations

from collections.abc import Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.epoch_schedule_commit import load_protocol_authority_private_key
from aidn_hypervisor.consensus.epoch_schedule_rebase import (
    EPOCH_SCHEDULE_REBASE_OPERATION,
    EpochScheduleRebase,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.protocol_authority import (
    EPOCH_SCHEDULE_REBASE_AUTHORITY_HASH_FIELD,
    ProtocolAuthorityPolicy,
    normalize_ed25519_public_key,
)


def _public_key(key: Ed25519PrivateKey) -> str:
    return normalize_ed25519_public_key(
        "ed25519:" + key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    )


def build_unsigned_epoch_schedule_rebase(
    *,
    policy: ProtocolAuthorityPolicy,
    rebase: EpochScheduleRebase,
    created_at: str,
    expires_at: str | None = None,
    initiator_id: str = "epoch-engine-recovery",
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
) -> LedgerOperationEnvelope:
    return LedgerOperationEnvelope(
        operation_type=EPOCH_SCHEDULE_REBASE_OPERATION,
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="protocol",
        initiator_id=initiator_id,
        fee_class="protocol_sponsored",
        created_at=created_at,
        expires_at=expires_at,
        target_epoch="0",
        payload={
            "epoch_schedule_rebase": rebase.model_dump(mode="json"),
            EPOCH_SCHEDULE_REBASE_AUTHORITY_HASH_FIELD: policy.policy_hash,
        },
        evidence_references=[rebase.schedule_hash, rebase.rebase_hash],
    )


def sign_epoch_schedule_rebase_signature(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    authority_id: str,
    private_key: Ed25519PrivateKey,
) -> str:
    if envelope.operation_type != EPOCH_SCHEDULE_REBASE_OPERATION or envelope.signatures:
        raise ValueError("protocol authority signer requires an unsigned EPOCH_SCHEDULE_REBASE")
    if envelope.payload.get(EPOCH_SCHEDULE_REBASE_AUTHORITY_HASH_FIELD) != policy.policy_hash:
        raise ValueError("epoch schedule rebase policy hash does not match policy")
    if dict(policy.authorities).get(authority_id) != _public_key(private_key):
        raise ValueError(f"protocol authority private key does not match: {authority_id}")
    return "ed25519:" + private_key.sign(envelope.signing_bytes()).hex()


def combine_epoch_schedule_rebase_signatures(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    signatures: Mapping[str, str],
) -> LedgerOperationEnvelope:
    if envelope.operation_type != EPOCH_SCHEDULE_REBASE_OPERATION or envelope.signatures:
        raise ValueError("protocol authority combiner requires an unsigned EPOCH_SCHEDULE_REBASE")
    unknown = sorted(set(signatures) - {authority_id for authority_id, _ in policy.authorities})
    if unknown:
        raise ValueError(f"protocol authority signer is not in policy: {unknown[0]}")
    signed = envelope.model_copy(
        update={"signatures": [signatures[authority_id] for authority_id in sorted(signatures)]}
    )
    policy.verify_epoch_schedule_rebase(signed)
    return signed


def sign_epoch_schedule_rebase(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    signers: Mapping[str, Ed25519PrivateKey],
) -> LedgerOperationEnvelope:
    return combine_epoch_schedule_rebase_signatures(
        envelope,
        policy=policy,
        signatures={
            authority_id: sign_epoch_schedule_rebase_signature(
                envelope,
                policy=policy,
                authority_id=authority_id,
                private_key=private_key,
            )
            for authority_id, private_key in signers.items()
        },
    )


__all__ = [
    "build_unsigned_epoch_schedule_rebase",
    "combine_epoch_schedule_rebase_signatures",
    "load_protocol_authority_private_key",
    "sign_epoch_schedule_rebase",
    "sign_epoch_schedule_rebase_signature",
]
