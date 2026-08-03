from __future__ import annotations

import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.cometbft_crypto import Zip215CometBftEd25519Backend
from aidn_hypervisor.consensus.deployment import CometBftDeploymentCheckpoint, CometBftDeploymentValidator
from aidn_hypervisor.consensus.light_client import CometBftValidator, CometBftValidatorSet
from aidn_hypervisor.consensus.public_network import (
    PublicMultiValidatorNetworkProfile,
    PublicProfileSignature,
    PublicValidatorManifest,
    build_public_multivalidator_profile,
    inspect_public_multivalidator_profile,
)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _hex_public_key(key: Ed25519PrivateKey) -> str:
    return "ed25519:" + key.public_key().public_bytes_raw().hex()


def _manifest(index: int, operator_key: Ed25519PrivateKey) -> PublicValidatorManifest:
    consensus_key = Ed25519PrivateKey.generate()
    raw_consensus_key = consensus_key.public_key().public_bytes_raw()
    public_key = "ed25519:" + base64.b64encode(raw_consensus_key).decode()
    manifest = PublicValidatorManifest(
        validator_id=f"validator-{index}",
        operator_id=f"operator-{index}",
        control_group_id=f"control-group-{index}",
        network_id="aidn-public-testnet",
        chain_id="aidn-public-testnet-1",
        network_revision=1,
        consensus_address=hashlib.sha256(raw_consensus_key).digest()[:20].hex().upper(),
        consensus_public_key=public_key,
        rpc_endpoint=f"https://rpc-{index}.example.net",
        p2p_endpoint=f"validator-{index}.example.net:26656",
        app_version="0.2.0",
        genesis_hash="sha256:genesis-public-testnet",
        configuration_hash=f"sha256:validator-config-{index}",
        effective_epoch=0,
        operator_public_key=_hex_public_key(operator_key),
        operator_signature="ed25519:" + "00" * 64,
        ownership_evidence="OUT_OF_BAND_VERIFIED",
        ownership_evidence_root=f"sha256:ownership-{index}",
    )
    signature = operator_key.sign(_canonical(manifest.unsigned_payload()))
    return manifest.model_copy(update={"operator_signature": "ed25519:" + signature.hex()})


def _profile() -> tuple[
    PublicMultiValidatorNetworkProfile,
    dict[str, str],
    list[Ed25519PrivateKey],
    dict[str, Ed25519PrivateKey],
]:
    operator_keys = [Ed25519PrivateKey.generate() for _ in range(4)]
    manifests = [_manifest(index, key) for index, key in enumerate(operator_keys)]
    checkpoint_validators = CometBftValidatorSet(
        tuple(
            CometBftValidator(
                address=manifest.consensus_address,
                public_key=manifest.consensus_public_key,
                voting_power=1,
            )
            for manifest in manifests
        )
    )
    checkpoint_hash = Zip215CometBftEd25519Backend().validator_set_hash(checkpoint_validators)
    checkpoint = CometBftDeploymentCheckpoint(
        height=10,
        block_id="A" * 64,
        app_hash="B" * 64,
        header_time="2030-01-01T00:00:00Z",
        validator_set_hash=checkpoint_hash,
        next_validator_set_hash=checkpoint_hash,
        validators=[
            CometBftDeploymentValidator(
                address=manifest.consensus_address,
                public_key=manifest.consensus_public_key,
                voting_power=1,
            )
            for manifest in manifests
        ],
    )
    profile = build_public_multivalidator_profile(
        profile_id="public-testnet-profile-v1",
        network_id="aidn-public-testnet",
        chain_id="aidn-public-testnet-1",
        network_revision=1,
        effective_epoch=1,
        minimum_rpc_agreement=3,
        validator_manifests=manifests,
        trusted_checkpoint=checkpoint,
        independence_evidence="OUT_OF_BAND_VERIFIED",
        independence_evidence_root="sha256:independence-attestation",
    )
    authority_keys = {f"release-authority-{index}": Ed25519PrivateKey.generate() for index in range(2)}
    signatures = [
        PublicProfileSignature(
            authority_id=authority_id,
            public_key=_hex_public_key(key),
            signature="ed25519:" + key.sign(profile.signing_payload()).hex(),
        )
        for authority_id, key in authority_keys.items()
    ]
    profile = profile.model_copy(update={"profile_signatures": signatures})
    trusted_signers = {
        authority_id: _hex_public_key(key) for authority_id, key in authority_keys.items()
    }
    return profile, trusted_signers, operator_keys, authority_keys


def _resign_profile(
    profile: PublicMultiValidatorNetworkProfile,
    authority_keys: dict[str, Ed25519PrivateKey],
    *,
    independence_evidence: str,
    independence_evidence_root: str | None,
) -> PublicMultiValidatorNetworkProfile:
    rebuilt = build_public_multivalidator_profile(
        profile_id=profile.profile_id,
        network_id=profile.network_id,
        chain_id=profile.chain_id,
        network_revision=profile.network_revision,
        effective_epoch=profile.effective_epoch,
        minimum_rpc_agreement=profile.minimum_rpc_agreement,
        validator_manifests=list(profile.validator_manifests),
        trusted_checkpoint=profile.trusted_checkpoint,
        minimum_distinct_operators=profile.minimum_distinct_operators,
        minimum_distinct_control_groups=profile.minimum_distinct_control_groups,
        profile_signature_threshold=profile.profile_signature_threshold,
        independence_evidence=independence_evidence,  # type: ignore[arg-type]
        independence_evidence_root=independence_evidence_root,
    )
    signatures = [
        PublicProfileSignature(
            authority_id=authority_id,
            public_key=_hex_public_key(key),
            signature="ed25519:" + key.sign(rebuilt.signing_payload()).hex(),
        )
        for authority_id, key in authority_keys.items()
    ]
    return rebuilt.model_copy(update={"profile_signatures": signatures})


def _rehashed_profile(
    profile: PublicMultiValidatorNetworkProfile,
    **updates: object,
) -> PublicMultiValidatorNetworkProfile:
    payload = profile.model_dump(mode="json")
    payload.update(updates)
    if "validator_manifests" in updates:
        payload["validator_manifests"] = [
            item.model_dump(mode="json") if isinstance(item, PublicValidatorManifest) else item
            for item in payload["validator_manifests"]
        ]
    unsigned = {key: value for key, value in payload.items() if key not in {"profile_hash", "profile_signatures"}}
    payload["profile_hash"] = "sha256:" + hashlib.sha256(_canonical(unsigned)).hexdigest()
    return PublicMultiValidatorNetworkProfile.model_validate(payload)


def test_public_profile_requires_signed_manifests_and_profile_quorum():
    profile, trusted_signers, _, _ = _profile()

    report = inspect_public_multivalidator_profile(
        profile,
        trusted_profile_signers=trusted_signers,
    )

    assert report.valid is True
    assert report.cryptographic_finality_ready is True
    assert report.operator_independence_ready is True
    assert report.validator_count == 4
    assert report.rpc_endpoint_count == 4
    assert report.distinct_operator_count == 4
    assert report.distinct_control_group_count == 4
    assert len(report.valid_profile_signer_ids) == 2
    assert profile.finality_deployment_config().minimum_agreement == 3


def test_public_profile_does_not_turn_rpc_quorum_into_independence_proof():
    profile, trusted_signers, _, authority_keys = _profile()
    profile = _resign_profile(
        profile,
        authority_keys,
        independence_evidence="NOT_PROVEN_BY_PROTOCOL",
        independence_evidence_root=None,
    )

    cryptographic_report = inspect_public_multivalidator_profile(
        profile,
        trusted_profile_signers=trusted_signers,
        require_independence_evidence=False,
    )
    public_report = inspect_public_multivalidator_profile(
        profile,
        trusted_profile_signers=trusted_signers,
        require_independence_evidence=True,
    )

    assert cryptographic_report.valid is True
    assert cryptographic_report.operator_independence_ready is False
    assert public_report.valid is False
    assert "PUBLIC_MULTIVALIDATOR_INDEPENDENCE_NOT_VERIFIED" in public_report.failure_reasons


def test_public_profile_rejects_tampered_manifest_signature():
    profile, trusted_signers, _, _ = _profile()
    tampered = profile.validator_manifests[0].model_copy(
        update={"configuration_hash": "sha256:tampered"}
    )

    with pytest.raises(ValueError, match="PUBLIC_VALIDATOR_OPERATOR_KEY_INVALID|PUBLIC_MULTIVALIDATOR"):
        _rehashed_profile(profile, validator_manifests=[tampered, *profile.validator_manifests[1:]])


def test_public_profile_rejects_duplicate_rpc_and_invalid_profile_signer():
    profile, trusted_signers, _, _ = _profile()
    duplicate_rpc = profile.validator_manifests[1].model_copy(
        update={"rpc_endpoint": profile.validator_manifests[0].rpc_endpoint}
    )
    with pytest.raises(ValueError, match="PUBLIC_MULTIVALIDATOR_RPC_ENDPOINT_DUPLICATE"):
        _rehashed_profile(
            profile,
            validator_manifests=[profile.validator_manifests[0], duplicate_rpc, *profile.validator_manifests[2:]],
        )

    invalid_report = inspect_public_multivalidator_profile(
        profile,
        trusted_profile_signers={"release-authority-0": trusted_signers["release-authority-0"]},
    )
    assert invalid_report.valid is False
    assert "PUBLIC_MULTIVALIDATOR_PROFILE_SIGNATURE_QUORUM_INVALID" in invalid_report.failure_reasons
