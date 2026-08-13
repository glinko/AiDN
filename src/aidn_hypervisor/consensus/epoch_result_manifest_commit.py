"""Offline construction and threshold signing for Epoch Result Manifests.

The manifest is a consensus commitment to roots calculated elsewhere.  This
module intentionally does not collect evidence, calculate rewards or submit a
transaction.  It gives independent authorities one exact immutable envelope to
review and sign.
"""

from __future__ import annotations

from collections.abc import Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.epoch_result_manifest import (
    EPOCH_RESULT_MANIFEST_OPERATION,
    EpochResultManifest,
)
from aidn_hypervisor.consensus.epoch_schedule_commit import (
    load_protocol_authority_private_key,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.protocol_authority import (
    EPOCH_RESULT_MANIFEST_AUTHORITY_HASH_FIELD,
    ProtocolAuthorityPolicy,
    normalize_ed25519_public_key,
)
from aidn_hypervisor.ledger.service import LedgerOperationService


def _public_key_for_private_key(key: Ed25519PrivateKey) -> str:
    return normalize_ed25519_public_key(
        "ed25519:"
        + key.public_key()
        .public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        .hex()
    )


def build_unsigned_epoch_result_manifest_commit(
    *,
    policy: ProtocolAuthorityPolicy,
    manifest: EpochResultManifest,
    created_at: str,
    expires_at: str | None = None,
    initiator_id: str = "epoch-engine",
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
    evidence_references: list[str] | None = None,
) -> LedgerOperationEnvelope:
    """Build the exact unsigned commitment accepted by independent signers."""
    if not isinstance(manifest, EpochResultManifest):
        manifest = EpochResultManifest.model_validate(manifest)
    envelope = LedgerOperationEnvelope(
        operation_type=EPOCH_RESULT_MANIFEST_OPERATION,
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="protocol",
        initiator_id=initiator_id,
        fee_class="protocol_sponsored",
        created_at=created_at,
        expires_at=expires_at,
        target_epoch=str(manifest.epoch_number),
        payload={
            "manifest": manifest.model_dump(mode="json"),
            EPOCH_RESULT_MANIFEST_AUTHORITY_HASH_FIELD: policy.policy_hash,
        },
        evidence_references=sorted(set(evidence_references or [])),
    )
    LedgerOperationService().validate_consensus_epoch_result_manifest(envelope)
    return envelope


def sign_epoch_result_manifest_commit_signature(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    authority_id: str,
    private_key: Ed25519PrivateKey,
) -> str:
    """Sign one unsigned manifest commitment as one declared authority."""
    if envelope.operation_type != EPOCH_RESULT_MANIFEST_OPERATION:
        raise ValueError("protocol authority signing requires EPOCH_RESULT_MANIFEST_COMMIT")
    if envelope.signatures:
        raise ValueError("protocol authority signer input must be unsigned")
    LedgerOperationService().validate_consensus_epoch_result_manifest(envelope)
    expected_key = dict(policy.authorities).get(authority_id)
    if expected_key is None:
        raise ValueError(f"protocol authority signer is not in policy: {authority_id}")
    if envelope.payload.get(EPOCH_RESULT_MANIFEST_AUTHORITY_HASH_FIELD) != policy.policy_hash:
        raise ValueError("epoch result manifest policy hash does not match policy")
    if _public_key_for_private_key(private_key) != expected_key:
        raise ValueError(f"protocol authority private key does not match: {authority_id}")
    return "ed25519:" + private_key.sign(envelope.signing_bytes()).hex()


def combine_epoch_result_manifest_commit_signatures(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    signatures: Mapping[str, str],
) -> LedgerOperationEnvelope:
    """Attach independent signatures and verify the configured threshold."""
    if envelope.operation_type != EPOCH_RESULT_MANIFEST_OPERATION:
        raise ValueError("protocol authority signing requires EPOCH_RESULT_MANIFEST_COMMIT")
    if envelope.signatures:
        raise ValueError("protocol authority combiner input must be unsigned")
    if not signatures:
        raise ValueError("at least one protocol authority signature is required")
    LedgerOperationService().validate_consensus_epoch_result_manifest(envelope)
    unknown = sorted(set(signatures) - {authority_id for authority_id, _ in policy.authorities})
    if unknown:
        raise ValueError(f"protocol authority signer is not in policy: {unknown[0]}")
    signed = envelope.model_copy(
        update={"signatures": [signatures[authority_id] for authority_id in sorted(signatures)]}
    )
    policy.verify_epoch_result_manifest_commit(signed)
    return signed


def sign_epoch_result_manifest_commit(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    signers: Mapping[str, Ed25519PrivateKey],
) -> LedgerOperationEnvelope:
    """Threshold-sign one manifest commitment without broadcasting it."""
    if len(signers) < policy.threshold:
        raise ValueError("protocol authority signer quorum is not met")
    signatures = {
        authority_id: sign_epoch_result_manifest_commit_signature(
            envelope,
            policy=policy,
            authority_id=authority_id,
            private_key=private_key,
        )
        for authority_id, private_key in signers.items()
    }
    return combine_epoch_result_manifest_commit_signatures(
        envelope,
        policy=policy,
        signatures=signatures,
    )


def build_signed_epoch_result_manifest_commit(
    *,
    policy: ProtocolAuthorityPolicy,
    manifest: EpochResultManifest,
    signers: Mapping[str, Ed25519PrivateKey],
    created_at: str,
    expires_at: str | None = None,
    initiator_id: str = "epoch-engine",
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
) -> LedgerOperationEnvelope:
    """Build and threshold-sign one immutable manifest commitment."""
    unsigned = build_unsigned_epoch_result_manifest_commit(
        policy=policy,
        manifest=manifest,
        created_at=created_at,
        expires_at=expires_at,
        initiator_id=initiator_id,
        operation_version=operation_version,
        protocol_version=protocol_version,
    )
    return sign_epoch_result_manifest_commit(unsigned, policy=policy, signers=signers)


__all__ = [
    "build_signed_epoch_result_manifest_commit",
    "build_unsigned_epoch_result_manifest_commit",
    "combine_epoch_result_manifest_commit_signatures",
    "load_protocol_authority_private_key",
    "sign_epoch_result_manifest_commit",
    "sign_epoch_result_manifest_commit_signature",
]
