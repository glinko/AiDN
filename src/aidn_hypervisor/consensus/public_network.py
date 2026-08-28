"""Signed deployment and acceptance boundary for public multi-validator networks.

CometBFT light-client verification proves cryptographic finality.  It does not
prove that four RPC URLs belong to four independent operators.  This module
keeps those claims separate and makes the operator-provided public rollout
profile explicit, signed, hash-bound, and fail-closed.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aidn_hypervisor.consensus.deployment import (
    CometBftDeploymentCheckpoint,
    CometBftFinalityDeploymentConfig,
)

PUBLIC_MULTIVALIDATOR_PROFILE_VERSION = "aidn-public-multivalidator.v1"
PUBLIC_MULTIVALIDATOR_REPORT_VERSION = "aidn-public-multivalidator-report.v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _decode_hex(value: str, *, prefix: str, size: int, error: str) -> bytes:
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError(error)
    try:
        decoded = bytes.fromhex(value.removeprefix(prefix))
    except ValueError as exc:
        raise ValueError(error) from exc
    if len(decoded) != size:
        raise ValueError(error)
    return decoded


def _decode_consensus_key(value: str) -> bytes:
    if not isinstance(value, str) or not value.startswith("ed25519:"):
        raise ValueError("public validator consensus key is invalid")
    try:
        decoded = base64.b64decode(value.removeprefix("ed25519:"), validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("public validator consensus key is invalid") from exc
    if len(decoded) != 32:
        raise ValueError("public validator consensus key is invalid")
    return decoded


def _verify_signature(*, public_key: str, signature: str, payload: bytes) -> bool:
    try:
        key = Ed25519PublicKey.from_public_bytes(
            _decode_hex(
                public_key,
                prefix="ed25519:",
                size=32,
                error="public network signer key is invalid",
            )
        )
        value = _decode_hex(
            signature,
            prefix="ed25519:",
            size=64,
            error="public network signature is invalid",
        )
        key.verify(value, payload)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


class PublicValidatorManifest(BaseModel, frozen=True):
    """One operator-attested validator and its public network endpoints."""

    model_config = ConfigDict(extra="forbid")

    validator_id: str = Field(min_length=1)
    operator_id: str = Field(min_length=1)
    control_group_id: str = Field(min_length=1)
    network_id: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    network_revision: int = Field(ge=0)
    consensus_address: str = Field(min_length=1)
    consensus_public_key: str = Field(min_length=1)
    rpc_endpoint: str = Field(min_length=1)
    # CometBFT uses this transport identity in ``persistent_peers`` and
    # ``seeds`` (``node-id@host:port``).  The consensus validator key above
    # cannot substitute for it, so a public deployment manifest must bind
    # both identities before it can be used to configure another node.
    comet_node_id: str = Field(pattern=r"^[0-9a-f]{40}$")
    p2p_endpoint: str = Field(min_length=1)
    app_version: str = Field(min_length=1)
    genesis_hash: str = Field(min_length=1)
    configuration_hash: str = Field(min_length=1)
    effective_epoch: int = Field(ge=0)
    operator_public_key: str = Field(min_length=1)
    operator_signature: str = Field(min_length=1)
    ownership_evidence: Literal["OUT_OF_BAND_VERIFIED", "NOT_PROVEN_BY_PROTOCOL"] = (
        "NOT_PROVEN_BY_PROTOCOL"
    )
    ownership_evidence_root: str | None = None

    @model_validator(mode="after")
    def validate_manifest(self) -> PublicValidatorManifest:
        consensus_key = _decode_consensus_key(self.consensus_public_key)
        expected_address = hashlib.sha256(consensus_key).digest()[:20].hex().upper()
        if self.consensus_address.upper() != expected_address:
            raise ValueError("PUBLIC_VALIDATOR_CONSENSUS_ADDRESS_MISMATCH")
        _decode_hex(
            self.operator_public_key,
            prefix="ed25519:",
            size=32,
            error="PUBLIC_VALIDATOR_OPERATOR_KEY_INVALID",
        )
        if not self.rpc_endpoint.startswith("https://"):
            raise ValueError("PUBLIC_VALIDATOR_RPC_ENDPOINT_INVALID")
        parsed = urlsplit(self.rpc_endpoint)
        if (
            not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("PUBLIC_VALIDATOR_RPC_ENDPOINT_INVALID")
        if self.ownership_evidence == "OUT_OF_BAND_VERIFIED" and not self.ownership_evidence_root:
            raise ValueError("PUBLIC_VALIDATOR_OWNERSHIP_EVIDENCE_REQUIRED")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"operator_signature"})

    @property
    def manifest_hash(self) -> str:
        return _digest(self.unsigned_payload())

    def verify_integrity(self) -> bool:
        return _verify_signature(
            public_key=self.operator_public_key,
            signature=self.operator_signature,
            payload=_canonical_json(self.unsigned_payload()).encode("utf-8"),
        )


class PublicProfileSignature(BaseModel, frozen=True):
    """Signature from a release or Governance authority trusted by the reader."""

    model_config = ConfigDict(extra="forbid")

    authority_id: str = Field(min_length=1)
    public_key: str = Field(min_length=1)
    signature: str = Field(min_length=1)


class PublicMultiValidatorNetworkProfile(BaseModel, frozen=True):
    """Complete, signed public deployment profile for one AiDN network."""

    model_config = ConfigDict(extra="forbid")

    profile_version: str = PUBLIC_MULTIVALIDATOR_PROFILE_VERSION
    profile_id: str = Field(min_length=1)
    network_id: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    network_revision: int = Field(ge=0)
    effective_epoch: int = Field(ge=0)
    minimum_rpc_agreement: int = Field(ge=2)
    minimum_distinct_operators: int = Field(default=4, ge=1)
    minimum_distinct_control_groups: int = Field(default=4, ge=1)
    validator_manifests: list[PublicValidatorManifest] = Field(min_length=4, max_length=256)
    trusted_checkpoint: CometBftDeploymentCheckpoint
    profile_signature_threshold: int = Field(default=2, ge=1)
    independence_evidence: Literal["OUT_OF_BAND_VERIFIED", "NOT_PROVEN_BY_PROTOCOL"] = (
        "NOT_PROVEN_BY_PROTOCOL"
    )
    independence_evidence_root: str | None = None
    profile_hash: str = Field(min_length=1)
    profile_signatures: list[PublicProfileSignature] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_profile(self) -> PublicMultiValidatorNetworkProfile:
        manifests = self.validator_manifests
        if self.minimum_rpc_agreement > len(manifests):
            raise ValueError("PUBLIC_MULTIVALIDATOR_RPC_QUORUM_INVALID")
        if self.minimum_distinct_operators > len({item.operator_id for item in manifests}):
            raise ValueError("PUBLIC_MULTIVALIDATOR_OPERATOR_QUORUM_INVALID")
        if self.minimum_distinct_control_groups > len({item.control_group_id for item in manifests}):
            raise ValueError("PUBLIC_MULTIVALIDATOR_CONTROL_GROUP_QUORUM_INVALID")
        if len({item.app_version for item in manifests}) != 1:
            raise ValueError("PUBLIC_MULTIVALIDATOR_APP_VERSION_MISMATCH")
        for field_name, values in (
            ("validator_id", [item.validator_id for item in manifests]),
            ("consensus_public_key", [item.consensus_public_key for item in manifests]),
            ("rpc_endpoint", [item.rpc_endpoint.rstrip("/") for item in manifests]),
            ("comet_node_id", [item.comet_node_id for item in manifests]),
            ("p2p_endpoint", [item.p2p_endpoint for item in manifests]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"PUBLIC_MULTIVALIDATOR_{field_name.upper()}_DUPLICATE")
        for manifest in manifests:
            if (
                manifest.network_id != self.network_id
                or manifest.chain_id != self.chain_id
                or manifest.network_revision != self.network_revision
                or manifest.effective_epoch > self.effective_epoch
            ):
                raise ValueError("PUBLIC_MULTIVALIDATOR_MANIFEST_BINDING_INVALID")
            if not manifest.verify_integrity():
                raise ValueError("PUBLIC_MULTIVALIDATOR_MANIFEST_SIGNATURE_INVALID")
        if self.independence_evidence == "OUT_OF_BAND_VERIFIED" and not self.independence_evidence_root:
            raise ValueError("PUBLIC_MULTIVALIDATOR_INDEPENDENCE_EVIDENCE_REQUIRED")
        if self.profile_hash != public_multivalidator_profile_hash(self):
            raise ValueError("PUBLIC_MULTIVALIDATOR_PROFILE_HASH_INVALID")
        return self

    def unsigned_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"profile_hash", "profile_signatures"})

    def signing_payload(self) -> bytes:
        return _canonical_json(
            {
                "profile_id": self.profile_id,
                "profile_hash": self.profile_hash,
                "network_id": self.network_id,
                "chain_id": self.chain_id,
                "network_revision": self.network_revision,
            }
        ).encode("utf-8")

    def verify_profile_signatures(
        self,
        trusted_profile_signers: Mapping[str, str],
    ) -> tuple[str, ...]:
        valid: list[str] = []
        seen: set[str] = set()
        for signature in self.profile_signatures:
            if signature.authority_id in seen:
                continue
            trusted_key = trusted_profile_signers.get(signature.authority_id)
            if trusted_key is None or trusted_key != signature.public_key:
                continue
            if _verify_signature(
                public_key=signature.public_key,
                signature=signature.signature,
                payload=self.signing_payload(),
            ):
                seen.add(signature.authority_id)
                valid.append(signature.authority_id)
        return tuple(sorted(valid))

    def finality_deployment_config(self) -> CometBftFinalityDeploymentConfig:
        """Project the accepted profile into the existing light-client config."""
        return CometBftFinalityDeploymentConfig(
            rpc_endpoints=[item.rpc_endpoint.rstrip("/") for item in self.validator_manifests],
            minimum_agreement=self.minimum_rpc_agreement,
            chain_id=self.chain_id,
            verifier_id=self.profile_id,
            trusted_checkpoint=self.trusted_checkpoint,
            trust_period_seconds=1_209_600,
        )


def public_multivalidator_profile_hash(
    profile: PublicMultiValidatorNetworkProfile,
) -> str:
    return _digest(profile.unsigned_payload())


def build_public_multivalidator_profile(
    *,
    profile_id: str,
    network_id: str,
    chain_id: str,
    network_revision: int,
    effective_epoch: int,
    minimum_rpc_agreement: int,
    validator_manifests: list[PublicValidatorManifest],
    trusted_checkpoint: CometBftDeploymentCheckpoint,
    minimum_distinct_operators: int = 4,
    minimum_distinct_control_groups: int = 4,
    profile_signature_threshold: int = 2,
    independence_evidence: Literal["OUT_OF_BAND_VERIFIED", "NOT_PROVEN_BY_PROTOCOL"] = (
        "NOT_PROVEN_BY_PROTOCOL"
    ),
    independence_evidence_root: str | None = None,
    profile_signatures: list[PublicProfileSignature] | None = None,
) -> PublicMultiValidatorNetworkProfile:
    unsigned = {
        "profile_version": PUBLIC_MULTIVALIDATOR_PROFILE_VERSION,
        "profile_id": profile_id,
        "network_id": network_id,
        "chain_id": chain_id,
        "network_revision": network_revision,
        "effective_epoch": effective_epoch,
        "minimum_rpc_agreement": minimum_rpc_agreement,
        "minimum_distinct_operators": minimum_distinct_operators,
        "minimum_distinct_control_groups": minimum_distinct_control_groups,
        "validator_manifests": [item.model_dump(mode="json") for item in validator_manifests],
        "trusted_checkpoint": trusted_checkpoint.model_dump(mode="json"),
        "profile_signature_threshold": profile_signature_threshold,
        "independence_evidence": independence_evidence,
        "independence_evidence_root": independence_evidence_root,
    }
    return PublicMultiValidatorNetworkProfile(
        **unsigned,
        profile_hash=_digest(unsigned),
        profile_signatures=profile_signatures or [],
    )


class PublicMultiValidatorAcceptanceReport(BaseModel, frozen=True):
    """Machine-readable release-gate result for a public profile."""

    model_config = ConfigDict(extra="forbid")

    report_version: str = PUBLIC_MULTIVALIDATOR_REPORT_VERSION
    profile_id: str
    profile_hash: str
    valid: bool
    cryptographic_finality_ready: bool
    operator_independence_ready: bool
    validator_count: int
    rpc_endpoint_count: int
    distinct_operator_count: int
    distinct_control_group_count: int
    valid_profile_signer_ids: list[str]
    failure_reasons: list[str]
    report_hash: str


def inspect_public_multivalidator_profile(
    profile: PublicMultiValidatorNetworkProfile,
    *,
    trusted_profile_signers: Mapping[str, str],
    require_independence_evidence: bool = True,
) -> PublicMultiValidatorAcceptanceReport:
    failures: list[str] = []
    try:
        profile.validate_profile()
    except ValueError as error:
        failures.append(str(error))
    valid_signers = list(profile.verify_profile_signatures(trusted_profile_signers))
    if len(valid_signers) < profile.profile_signature_threshold:
        failures.append("PUBLIC_MULTIVALIDATOR_PROFILE_SIGNATURE_QUORUM_INVALID")
    cryptographic_ready = not failures
    independence_ready = (
        profile.independence_evidence == "OUT_OF_BAND_VERIFIED"
        and bool(profile.independence_evidence_root)
        and len({item.operator_id for item in profile.validator_manifests})
        >= profile.minimum_distinct_operators
        and len({item.control_group_id for item in profile.validator_manifests})
        >= profile.minimum_distinct_control_groups
    )
    if require_independence_evidence and not independence_ready:
        failures.append("PUBLIC_MULTIVALIDATOR_INDEPENDENCE_NOT_VERIFIED")
    report_payload = {
        "profile_id": profile.profile_id,
        "profile_hash": profile.profile_hash,
        "cryptographic_finality_ready": cryptographic_ready,
        "operator_independence_ready": independence_ready,
        "valid_profile_signer_ids": valid_signers,
        "failure_reasons": sorted(set(failures)),
    }
    return PublicMultiValidatorAcceptanceReport(
        profile_id=profile.profile_id,
        profile_hash=profile.profile_hash,
        valid=not failures,
        cryptographic_finality_ready=cryptographic_ready,
        operator_independence_ready=independence_ready,
        validator_count=len(profile.validator_manifests),
        rpc_endpoint_count=len({item.rpc_endpoint.rstrip("/") for item in profile.validator_manifests}),
        distinct_operator_count=len({item.operator_id for item in profile.validator_manifests}),
        distinct_control_group_count=len({item.control_group_id for item in profile.validator_manifests}),
        valid_profile_signer_ids=valid_signers,
        failure_reasons=sorted(set(failures)),
        report_hash=_digest(report_payload),
    )


def assert_public_multivalidator_profile(
    profile: PublicMultiValidatorNetworkProfile,
    *,
    trusted_profile_signers: Mapping[str, str],
) -> PublicMultiValidatorAcceptanceReport:
    report = inspect_public_multivalidator_profile(
        profile,
        trusted_profile_signers=trusted_profile_signers,
        require_independence_evidence=True,
    )
    if not report.valid:
        raise ValueError("PUBLIC_MULTIVALIDATOR_PROFILE_INVALID:" + ",".join(report.failure_reasons))
    return report


__all__ = [
    "PUBLIC_MULTIVALIDATOR_PROFILE_VERSION",
    "PUBLIC_MULTIVALIDATOR_REPORT_VERSION",
    "PublicMultiValidatorAcceptanceReport",
    "PublicMultiValidatorNetworkProfile",
    "PublicProfileSignature",
    "PublicValidatorManifest",
    "assert_public_multivalidator_profile",
    "build_public_multivalidator_profile",
    "inspect_public_multivalidator_profile",
    "public_multivalidator_profile_hash",
]
