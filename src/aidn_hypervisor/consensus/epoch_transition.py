"""Build and sign protocol-authorized epoch transition envelopes.

This module is intentionally offline-only. It creates a canonical envelope
and verifies the authority quorum, but it never submits a transaction or
mutates a Ledger.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.epoch_transition_quorum import (
    EpochTransitionQuorumReport,
)
from aidn_hypervisor.consensus.models import LedgerOperationEnvelope
from aidn_hypervisor.consensus.protocol_authority import (
    EPOCH_TRANSITION_AUTHORITY_HASH_FIELD,
    ProtocolAuthorityPolicy,
    normalize_ed25519_public_key,
)
from aidn_hypervisor.ledger.service import LedgerOperationService

_QUORUM_BOUND_FIELDS = frozenset(
    {
        "epoch_transition_quorum_version",
        "epoch_transition_quorum_hash",
        "epoch_result_manifest_sequence_id",
        "epoch_result_manifest_record_digest",
    }
)
_MANIFEST_BINDING_FIELDS = frozenset(
    {
        "epoch_result_manifest_hash",
        "epoch_result_manifest_operation_id",
        "epoch_result_manifest_sequence_id",
        "epoch_result_manifest_record_digest",
    }
)
_SCHEDULE_BINDING_FIELDS = frozenset(
    {
        "epoch_schedule_commit_operation_id",
        "epoch_schedule_commit_sequence_id",
        "epoch_schedule_commit_record_digest",
    }
)


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
    quorum_report: EpochTransitionQuorumReport | Mapping[str, Any] | None = None,
    expected_chain_id: str | None = None,
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

    if len(signers) < policy.threshold:
        raise ValueError("protocol authority signer quorum is not met")
    signatures = {
        authority_id: sign_epoch_transition_signature(
            envelope,
            policy=policy,
            authority_id=authority_id,
            private_key=key,
            quorum_report=quorum_report,
            expected_chain_id=expected_chain_id,
        )
        for authority_id, key in signers.items()
    }
    return combine_epoch_transition_signatures(
        envelope,
        policy=policy,
        signatures=signatures,
        quorum_report=quorum_report,
        expected_chain_id=expected_chain_id,
    )


def build_unsigned_epoch_transition(
    *,
    policy: ProtocolAuthorityPolicy,
    payload: Mapping[str, object],
    created_at: str,
    expires_at: str | None = None,
    initiator_id: str = "epoch-engine",
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
    evidence_references: list[str] | None = None,
) -> LedgerOperationEnvelope:
    """Build the exact unsigned envelope that independent signers receive."""
    transition_payload = dict(payload)
    declared_hash = transition_payload.get("protocol_authority_policy_hash")
    if declared_hash is not None and declared_hash != policy.policy_hash:
        raise ValueError("epoch transition policy hash does not match policy")
    transition_payload["protocol_authority_policy_hash"] = policy.policy_hash

    closing_epoch = transition_payload.get("closing_epoch")
    if isinstance(closing_epoch, bool) or not isinstance(closing_epoch, int) or closing_epoch < 0:
        raise ValueError("epoch transition closing epoch is invalid")
    unsigned = LedgerOperationEnvelope(
        operation_type="EPOCH_TRANSITION",
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="protocol",
        initiator_id=initiator_id,
        fee_class="protocol_sponsored",
        created_at=created_at,
        expires_at=expires_at,
        target_epoch=str(closing_epoch),
        payload=transition_payload,
        evidence_references=sorted(set(evidence_references or [])),
    )
    LedgerOperationService().validate_consensus_epoch_transition(unsigned)
    return unsigned


def build_unsigned_epoch_transition_from_quorum(
    *,
    policy: ProtocolAuthorityPolicy,
    quorum_report: EpochTransitionQuorumReport | Mapping[str, Any],
    created_at: str,
    expires_at: str | None = None,
    initiator_id: str = "epoch-engine",
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
    expected_chain_id: str | None = None,
) -> LedgerOperationEnvelope:
    """Build a transition only from a finalized, hash-bound READY quorum.

    The quorum report is an external read-only evidence artifact. This helper
    copies the typed transition payload from it and binds the quorum hash plus
    the manifest's finalized operation reference into the signed envelope. It
    never queries, signs or broadcasts a transaction.
    """
    quorum = (
        quorum_report
        if isinstance(quorum_report, EpochTransitionQuorumReport)
        else EpochTransitionQuorumReport.model_validate(quorum_report)
    )
    if not quorum.verify_integrity():
        raise ValueError("epoch transition quorum report integrity is invalid")
    if quorum.status != "READY" or quorum.report is None:
        raise ValueError("epoch transition quorum report is not READY")
    if expected_chain_id is not None and quorum.chain_id != expected_chain_id:
        raise ValueError("epoch transition quorum chain ID does not match expected chain")
    if quorum.manifest_sequence_id is None or not quorum.manifest_record_digest:
        raise ValueError("epoch transition quorum finality reference is incomplete")

    payload = quorum.report.transition_payload(
        protocol_authority_policy_hash=policy.policy_hash,
    )
    payload.update(
        {
            "epoch_transition_quorum_version": quorum.schema_version,
            "epoch_transition_quorum_hash": quorum.quorum_hash,
            "epoch_result_manifest_sequence_id": quorum.manifest_sequence_id,
            "epoch_result_manifest_record_digest": quorum.manifest_record_digest,
        }
    )
    evidence_references = {
        quorum.manifest_operation_id,
        quorum.quorum_hash,
    }
    if quorum.schedule_operation_id and quorum.schedule_record_digest:
        evidence_references.update(
            {
                quorum.schedule_operation_id,
                quorum.schedule_record_digest,
            }
        )
    envelope = LedgerOperationEnvelope(
        operation_type="EPOCH_TRANSITION",
        operation_version=operation_version,
        protocol_version=protocol_version,
        origin_type="protocol",
        initiator_id=initiator_id,
        fee_class="protocol_sponsored",
        created_at=created_at,
        expires_at=expires_at,
        target_epoch=str(quorum.report.closing_epoch),
        payload=payload,
        evidence_references=sorted(evidence_references),
    )
    validate_quorum_bound_epoch_transition(
        envelope,
        policy=policy,
        quorum_report=quorum,
        expected_chain_id=expected_chain_id,
    )
    return envelope


def _coerce_quorum_report(
    quorum_report: EpochTransitionQuorumReport | Mapping[str, Any],
) -> EpochTransitionQuorumReport:
    return (
        quorum_report
        if isinstance(quorum_report, EpochTransitionQuorumReport)
        else EpochTransitionQuorumReport.model_validate(quorum_report)
    )


def _is_quorum_bound(envelope: LedgerOperationEnvelope) -> bool:
    return bool(_QUORUM_BOUND_FIELDS & set(envelope.payload))


def validate_quorum_bound_epoch_transition(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    quorum_report: EpochTransitionQuorumReport | Mapping[str, Any],
    expected_chain_id: str | None = None,
) -> None:
    """Validate an unsigned transition against one exact READY quorum report.

    This is an offline evidence check. It does not claim that the manifest is
    present in a local Ledger; the receiving ABCI application performs that
    independent local-finality check before admission.
    """
    quorum = _coerce_quorum_report(quorum_report)
    if not quorum.verify_integrity():
        raise ValueError("epoch transition quorum report integrity is invalid")
    if quorum.status != "READY" or quorum.report is None:
        raise ValueError("epoch transition quorum report is not READY")
    if expected_chain_id is not None and quorum.chain_id != expected_chain_id:
        raise ValueError("epoch transition quorum chain ID does not match expected chain")
    if not _is_quorum_bound(envelope):
        raise ValueError("epoch transition envelope is not quorum-bound")
    if envelope.signatures:
        raise ValueError("epoch transition quorum input must be unsigned")

    expected_payload = quorum.report.transition_payload(
        protocol_authority_policy_hash=policy.policy_hash,
    )
    expected_payload.update(
        {
            "epoch_transition_quorum_version": quorum.schema_version,
            "epoch_transition_quorum_hash": quorum.quorum_hash,
            "epoch_result_manifest_sequence_id": quorum.manifest_sequence_id,
            "epoch_result_manifest_record_digest": quorum.manifest_record_digest,
        }
    )
    if envelope.payload != expected_payload:
        raise ValueError("epoch transition payload does not match quorum report")

    expected_references = {
        quorum.manifest_operation_id,
        quorum.quorum_hash,
    }
    if quorum.schedule_operation_id and quorum.schedule_record_digest:
        expected_references.update(
            {
                quorum.schedule_operation_id,
                quorum.schedule_record_digest,
            }
        )
    expected_references = sorted(expected_references)
    if envelope.evidence_references != expected_references:
        raise ValueError("epoch transition evidence references do not match quorum report")

    # Reuse the canonical Ledger checks that do not require looking up the
    # external manifest. The ABCI application repeats those checks with the
    # local finalized operation registry and validates the manifest binding.
    # Schedule and manifest finality are verified against the external quorum
    # report above.  Remove those state references from the detached syntax
    # check; a fresh LedgerOperationService has no local finalized snapshot
    # and would otherwise reject a valid external schedule as unavailable.
    detached_payload = {
        key: value
        for key, value in envelope.payload.items()
        if key not in (_MANIFEST_BINDING_FIELDS | _QUORUM_BOUND_FIELDS | _SCHEDULE_BINDING_FIELDS)
    }
    detached_values = envelope.model_dump(mode="json")
    detached_values.update(
        {
            "payload": detached_payload,
            "evidence_references": [],
            "signatures": [],
            "operation_id": "",
        }
    )
    detached = LedgerOperationEnvelope.model_validate(detached_values)
    LedgerOperationService().validate_consensus_epoch_transition(detached)


def sign_epoch_transition_signature(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    authority_id: str,
    private_key: Ed25519PrivateKey,
    quorum_report: EpochTransitionQuorumReport | Mapping[str, Any] | None = None,
    expected_chain_id: str | None = None,
) -> str:
    """Sign one unsigned transition for exactly one declared authority."""
    if envelope.operation_type != "EPOCH_TRANSITION":
        raise ValueError("protocol authority signing requires EPOCH_TRANSITION")
    if envelope.signatures:
        raise ValueError("protocol authority signer input must be unsigned")
    if _is_quorum_bound(envelope):
        if quorum_report is None:
            raise ValueError("quorum report is required for quorum-bound transition")
        validate_quorum_bound_epoch_transition(
            envelope,
            policy=policy,
            quorum_report=quorum_report,
            expected_chain_id=expected_chain_id,
        )
    elif quorum_report is not None:
        raise ValueError("quorum report supplied for non-quorum-bound transition")
    else:
        LedgerOperationService().validate_consensus_epoch_transition(envelope)
    authority_keys = dict(policy.authorities)
    expected_key = authority_keys.get(authority_id)
    if expected_key is None:
        raise ValueError(f"protocol authority signer is not in policy: {authority_id}")
    if envelope.payload.get(EPOCH_TRANSITION_AUTHORITY_HASH_FIELD) != policy.policy_hash:
        raise ValueError("epoch transition policy hash does not match policy")
    if _public_key_for_private_key(private_key) != expected_key:
        raise ValueError(f"protocol authority private key does not match: {authority_id}")
    return "ed25519:" + private_key.sign(envelope.signing_bytes()).hex()


def combine_epoch_transition_signatures(
    envelope: LedgerOperationEnvelope,
    *,
    policy: ProtocolAuthorityPolicy,
    signatures: Mapping[str, str],
    quorum_report: EpochTransitionQuorumReport | Mapping[str, Any] | None = None,
    expected_chain_id: str | None = None,
) -> LedgerOperationEnvelope:
    """Attach independently produced signatures and verify the full quorum."""
    if envelope.operation_type != "EPOCH_TRANSITION":
        raise ValueError("protocol authority signing requires EPOCH_TRANSITION")
    if envelope.signatures:
        raise ValueError("protocol authority combiner input must be unsigned")
    if not signatures:
        raise ValueError("at least one protocol authority signature is required")
    if _is_quorum_bound(envelope):
        if quorum_report is None:
            raise ValueError("quorum report is required for quorum-bound transition")
        validate_quorum_bound_epoch_transition(
            envelope,
            policy=policy,
            quorum_report=quorum_report,
            expected_chain_id=expected_chain_id,
        )
    elif quorum_report is not None:
        raise ValueError("quorum report supplied for non-quorum-bound transition")
    else:
        LedgerOperationService().validate_consensus_epoch_transition(envelope)
    unknown = sorted(set(signatures) - {authority_id for authority_id, _ in policy.authorities})
    if unknown:
        raise ValueError(f"protocol authority signer is not in policy: {unknown[0]}")
    ordered = [signatures[authority_id] for authority_id in sorted(signatures)]
    signed = envelope.model_copy(update={"signatures": ordered})
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
    unsigned = build_unsigned_epoch_transition(
        policy=policy,
        payload=payload,
        created_at=created_at,
        expires_at=expires_at,
        initiator_id=initiator_id,
        operation_version=operation_version,
        protocol_version=protocol_version,
    )
    return sign_epoch_transition(unsigned, policy=policy, signers=signers)


def build_signed_epoch_transition_from_quorum(
    *,
    policy: ProtocolAuthorityPolicy,
    quorum_report: EpochTransitionQuorumReport | Mapping[str, Any],
    signers: Mapping[str, Ed25519PrivateKey],
    created_at: str,
    expires_at: str | None = None,
    initiator_id: str = "epoch-engine",
    operation_version: str = "1.0.0",
    protocol_version: str = "0.1",
    expected_chain_id: str | None = None,
) -> LedgerOperationEnvelope:
    """Build and sign a transition derived exclusively from a READY quorum."""
    unsigned = build_unsigned_epoch_transition_from_quorum(
        policy=policy,
        quorum_report=quorum_report,
        created_at=created_at,
        expires_at=expires_at,
        initiator_id=initiator_id,
        operation_version=operation_version,
        protocol_version=protocol_version,
        expected_chain_id=expected_chain_id,
    )
    return sign_epoch_transition(
        unsigned,
        policy=policy,
        signers=signers,
        quorum_report=quorum_report,
        expected_chain_id=expected_chain_id,
    )


def restrict_private_key_file(path: Path) -> None:
    """Best-effort owner-only permissions for Unix operator key files."""
    if os.name != "nt":
        path.chmod(0o600)


__all__ = [
    "build_unsigned_epoch_transition",
    "build_unsigned_epoch_transition_from_quorum",
    "build_signed_epoch_transition",
    "build_signed_epoch_transition_from_quorum",
    "combine_epoch_transition_signatures",
    "load_protocol_authority_private_key",
    "restrict_private_key_file",
    "sign_epoch_transition_signature",
    "sign_epoch_transition",
    "validate_quorum_bound_epoch_transition",
]
