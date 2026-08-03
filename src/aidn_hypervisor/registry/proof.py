"""Proof of Registry challenge and response primitives (RFC-0061 sections 62-66).

The MVP proof is intentionally small and independently verifiable. It proves
that a Registry can serve one deterministically selected object from the
inventory root supplied in the challenge. It does not claim consensus finality
or prove that an operator is independent from another operator.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, Field

from .manifest import (
    RegistryInventoryManifest,
    SegmentManifest,
    SegmentMerkleProof,
    verify_segment_merkle_proof,
)
from .object_envelope import RegistryObjectEnvelope
from .storage import ImmutableObjectStore


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


class RegistryChallenge(BaseModel, frozen=True):
    """A deterministic request for retrievability evidence."""

    challenge_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1)
    challenge_type: str = "completeness"
    target_registry_id: str = Field(min_length=1)
    target_inventory_root: str = Field(min_length=1)
    target_segment_id: str | None = None
    object_selector: str = Field(min_length=1)
    required_proof: list[str] = Field(
        default_factory=lambda: ["segment_manifest", "object"]
    )
    issued_at: float = Field(default_factory=time.time)
    response_deadline: float = Field(default_factory=lambda: time.time() + 300)
    challenger_id: str = Field(min_length=1)
    challenge_nonce: str = Field(min_length=1)
    challenger_signature: str = ""


class RegistryChallengeResponse(BaseModel, frozen=True):
    """Evidence returned by the challenged Registry."""

    challenge_id: str = Field(min_length=1)
    registry_id: str = Field(min_length=1)
    inventory_root: str = Field(min_length=1)
    target_segment_id: str = Field(min_length=1)
    selected_object_id: str = Field(min_length=1)
    object_hash: str = Field(min_length=1)
    object_or_reference: dict[str, Any] | None = None
    segment_manifest: dict[str, Any]
    segment_inclusion_proof: dict[str, Any]
    ledger_commitment_proof: dict[str, Any] | None = None
    response_timestamp: float = Field(default_factory=time.time)
    registry_signature: str = ""


class ProofVerificationResult(BaseModel, frozen=True):
    """Stable result of challenge-response verification."""

    valid: bool
    challenge_id: str
    registry_id: str
    selected_object_id: str | None = None
    reason: str = ""


def challenge_signing_bytes(challenge: RegistryChallenge) -> bytes:
    """Canonical bytes signed by the challenger when a signature is used."""
    return _canonical_bytes(challenge.model_dump(mode="json", exclude={"challenger_signature"}))


def response_signing_bytes(response: RegistryChallengeResponse) -> bytes:
    """Canonical bytes signed by the challenged Registry."""
    return _canonical_bytes(response.model_dump(mode="json", exclude={"registry_signature"}))


def verify_ed25519_signature(
    *,
    public_key: str,
    signature: str,
    payload: bytes,
) -> bool:
    """Verify the same ``ed25519:<hex>`` format used by peer authentication."""
    try:
        if not public_key.startswith("ed25519:") or not signature.startswith("ed25519:"):
            return False
        Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(public_key.removeprefix("ed25519:"))
        ).verify(
            bytes.fromhex(signature.removeprefix("ed25519:")),
            payload,
        )
    except (InvalidSignature, ValueError):
        return False
    return True


class ProofOfRegistryEngine:
    """Create, answer and verify deterministic Registry challenges."""

    def __init__(
        self,
        *,
        registry_id: str,
        store: ImmutableObjectStore,
        manifest_provider: Callable[[], RegistryInventoryManifest],
        signer: Callable[[bytes], str] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not registry_id:
            raise ValueError("registry_id is required")
        self._registry_id = registry_id
        self._store = store
        self._manifest_provider = manifest_provider
        self._signer = signer
        self._clock = clock

    def create_challenge(
        self,
        *,
        target_registry_id: str,
        inventory_root: str,
        challenger_id: str,
        target_segment_id: str | None = None,
        challenge_type: str = "completeness",
        response_timeout_seconds: float = 300.0,
        challenge_nonce: str | None = None,
        challenger_signature: str = "",
    ) -> RegistryChallenge:
        if response_timeout_seconds <= 0:
            raise ValueError("response_timeout_seconds must be positive")
        nonce = challenge_nonce or uuid.uuid4().hex
        selector = _digest(
            {
                "inventory_root": inventory_root,
                "segment_id": target_segment_id,
                "nonce": nonce,
            }
        )
        challenge = RegistryChallenge(
            challenge_type=challenge_type,
            target_registry_id=target_registry_id,
            target_inventory_root=inventory_root,
            target_segment_id=target_segment_id,
            object_selector=selector,
            issued_at=self._clock(),
            response_deadline=self._clock() + response_timeout_seconds,
            challenger_id=challenger_id,
            challenge_nonce=nonce,
            challenger_signature=challenger_signature,
        )
        return challenge

    def answer_challenge(
        self,
        challenge: RegistryChallenge,
    ) -> RegistryChallengeResponse:
        now = self._clock()
        if challenge.target_registry_id != self._registry_id:
            raise ValueError("challenge target registry does not match local Registry")
        if now > challenge.response_deadline:
            raise ValueError("Registry challenge response deadline has expired")

        manifest = self._manifest_provider()
        if not manifest.verify():
            raise ValueError("local inventory manifest is invalid")
        if manifest.inventory_root.root_hash != challenge.target_inventory_root:
            raise ValueError("challenge inventory root is no longer current")
        segment = self._select_segment(manifest, challenge)
        object_id = self._select_object(segment, challenge)
        expected_hash = self._manifest_hash_for_object(segment, object_id)
        if expected_hash is None:
            raise ValueError("challenge selected object is absent from segment")
        envelope = self._store.get(object_id, include_expired=True)
        if envelope is None:
            raise ValueError("challenged Registry object is not retrievable")
        if envelope.content_hash != expected_hash:
            raise ValueError("local object does not match inventory manifest")

        response = RegistryChallengeResponse(
            challenge_id=challenge.challenge_id,
            registry_id=self._registry_id,
            inventory_root=manifest.inventory_root.root_hash,
            target_segment_id=segment.segment_id,
            selected_object_id=object_id,
            object_hash=envelope.content_hash,
            object_or_reference=envelope.model_dump(mode="json"),
            segment_manifest=segment.model_dump(mode="json"),
            segment_inclusion_proof={
                "inventory_id": manifest.inventory_root.inventory_id,
                "inventory_root": manifest.inventory_root.root_hash,
                "segment_id": segment.segment_id,
                "manifest_id": segment.manifest_id,
                "manifest_hash": segment.manifest_hash,
                "merkle_proof": segment.build_merkle_proof(object_id).model_dump(mode="json"),
            },
            response_timestamp=now,
        )
        if self._signer is not None:
            signature = self._signer(response_signing_bytes(response))
            if not isinstance(signature, str) or not signature.startswith("ed25519:"):
                raise ValueError("Registry proof signer must return an ed25519 signature")
            response = response.model_copy(update={"registry_signature": signature})
        return response

    def verify_response(
        self,
        *,
        challenge: RegistryChallenge,
        response: RegistryChallengeResponse,
        expected_inventory_manifest: RegistryInventoryManifest | None = None,
        expected_registry_public_key: str | None = None,
        require_signature: bool = True,
    ) -> ProofVerificationResult:
        def failure(reason: str) -> ProofVerificationResult:
            return ProofVerificationResult(
                valid=False,
                challenge_id=challenge.challenge_id,
                registry_id=response.registry_id,
                selected_object_id=response.selected_object_id,
                reason=reason,
            )
        if response.challenge_id != challenge.challenge_id:
            return failure("challenge_id_mismatch")
        if response.registry_id != challenge.target_registry_id:
            return failure("registry_id_mismatch")
        if response.inventory_root != challenge.target_inventory_root:
            return failure("inventory_root_mismatch")
        if expected_inventory_manifest is None:
            return failure("inventory_manifest_reference_missing")
        if not expected_inventory_manifest.verify():
            return failure("expected_inventory_manifest_invalid")
        if expected_inventory_manifest.inventory_root.root_hash != challenge.target_inventory_root:
            return failure("expected_inventory_root_mismatch")
        if response.response_timestamp > challenge.response_deadline:
            return failure("response_deadline_exceeded")
        if require_signature:
            if expected_registry_public_key is None or not response.registry_signature:
                return failure("registry_signature_missing")
            if not verify_ed25519_signature(
                public_key=expected_registry_public_key,
                signature=response.registry_signature,
                payload=response_signing_bytes(response),
            ):
                return failure("registry_signature_invalid")

        try:
            segment = SegmentManifest.model_validate(response.segment_manifest)
            if not _verify_segment_structure(segment):
                return failure("segment_manifest_invalid")
        except (TypeError, ValueError):
            return failure("segment_manifest_invalid")
        if response.target_segment_id != segment.segment_id:
            return failure("segment_id_mismatch")
        expected_segment = next(
            (
                candidate
                for candidate in expected_inventory_manifest.segments
                if candidate.segment_id == segment.segment_id
            ),
            None,
        )
        if expected_segment is None or expected_segment.model_dump(mode="json") != segment.model_dump(mode="json"):
            return failure("segment_inventory_binding_invalid")
        if response.segment_inclusion_proof.get("manifest_hash") != segment.manifest_hash:
            return failure("segment_inclusion_proof_invalid")
        try:
            merkle_proof = SegmentMerkleProof.model_validate(
                response.segment_inclusion_proof.get("merkle_proof")
            )
        except (TypeError, ValueError):
            return failure("merkle_proof_invalid")
        try:
            expected_leaf_index = segment.object_ids.index(response.selected_object_id)
        except ValueError:
            return failure("merkle_proof_invalid")
        if (
            merkle_proof.object_id != response.selected_object_id
            or merkle_proof.content_hash != response.object_hash
            or merkle_proof.root_hash != segment.content_merkle_root
            or merkle_proof.leaf_count != segment.object_count
            or merkle_proof.leaf_index != expected_leaf_index
            or not verify_segment_merkle_proof(merkle_proof)
        ):
            return failure("merkle_proof_invalid")

        object_data = response.object_or_reference
        if object_data is None:
            return failure("object_payload_missing")
        try:
            envelope = RegistryObjectEnvelope.model_validate(object_data)
        except (TypeError, ValueError):
            return failure("object_envelope_invalid")
        if envelope.object_id != response.selected_object_id:
            return failure("object_id_mismatch")
        if (
            not envelope.verify_integrity()
            or envelope.content_hash != response.object_hash
            or envelope.content_size != merkle_proof.content_size
        ):
            return failure("object_integrity_invalid")
        expected_object_id = self._select_object(segment, challenge)
        if envelope.object_id != expected_object_id:
            return failure("challenge_selector_mismatch")
        expected_hash = self._manifest_hash_for_object(segment, envelope.object_id)
        if expected_hash is None:
            return failure("object_not_in_segment")
        if expected_hash != envelope.content_hash:
            return failure("object_manifest_mismatch")
        return ProofVerificationResult(
            valid=True,
            challenge_id=challenge.challenge_id,
            registry_id=response.registry_id,
            selected_object_id=envelope.object_id,
            reason="verified",
        )

    @staticmethod
    def _select_segment(
        manifest: RegistryInventoryManifest,
        challenge: RegistryChallenge,
    ) -> SegmentManifest:
        if not manifest.segments:
            raise ValueError("inventory has no segments")
        if challenge.target_segment_id:
            for segment in manifest.segments:
                if segment.segment_id == challenge.target_segment_id:
                    return segment
            raise ValueError("challenge segment is not present in inventory")
        index = int(challenge.object_selector[:16], 16) % len(manifest.segments)
        return sorted(manifest.segments, key=lambda item: item.segment_id)[index]

    @staticmethod
    def _select_object(segment: SegmentManifest, challenge: RegistryChallenge) -> str:
        if not segment.object_ids:
            raise ValueError("challenge segment has no objects")
        selector = _digest(
            {
                "object_selector": challenge.object_selector,
                "segment_id": segment.segment_id,
            }
        )
        return segment.object_ids[int(selector[:16], 16) % len(segment.object_ids)]

    @staticmethod
    def _manifest_hash_for_object(
        segment: SegmentManifest,
        object_id: str,
    ) -> str | None:
        for candidate_id, content_hash in _segment_hash_entries(segment):
            if candidate_id == object_id:
                return content_hash
        return None


def _segment_hash_entries(segment: SegmentManifest) -> list[tuple[str, str]]:
    """Return object/hash pairs when the manifest carries enough evidence.

    ``content_hashes`` is a payload-free parallel array added by the MVP
    manifest profile. Older manifests without it cannot satisfy a retrievability
    challenge and must be regenerated before being challenged.
    """
    if len(segment.object_ids) != len(segment.content_hashes):
        return []
    return list(zip(segment.object_ids, segment.content_hashes, strict=True))


def _verify_segment_structure(segment: SegmentManifest) -> bool:
    return segment.verify_self()
