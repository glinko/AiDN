from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.cometbft_crypto import Zip215CometBftEd25519Backend
from aidn_hypervisor.consensus.deployment import (
    CometBftDeploymentCheckpoint,
    CometBftDeploymentValidator,
)
from aidn_hypervisor.consensus.light_client import CometBftValidator, CometBftValidatorSet
from aidn_hypervisor.consensus.public_network import PublicValidatorManifest
from aidn_hypervisor.network_profile import verify_network_profile

_SCRIPT_PATH = Path(__file__).parents[1] / "tools" / "public-testnet-ceremony.py"
_SPEC = importlib.util.spec_from_file_location("public_testnet_ceremony", _SCRIPT_PATH)
assert _SPEC and _SPEC.loader
ceremony = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ceremony)


def _public_key(key: Ed25519PrivateKey) -> str:
    return "ed25519:" + key.public_key().public_bytes_raw().hex()


def _manifest(index: int, key: Ed25519PrivateKey, genesis_hash: str) -> PublicValidatorManifest:
    consensus = Ed25519PrivateKey.generate()
    raw = consensus.public_key().public_bytes_raw()
    draft = PublicValidatorManifest(
        validator_id=f"validator-{index}",
        operator_id=f"operator-{index}",
        control_group_id=f"control-{index}",
        network_id="aidn-testnet",
        chain_id="aidn-testnet-1",
        network_revision=1,
        consensus_address=hashlib.sha256(raw).digest()[:20].hex().upper(),
        consensus_public_key="ed25519:" + base64.b64encode(raw).decode(),
        rpc_endpoint=f"https://rpc-{index}.example.net",
        comet_node_id=f"{index + 1:040x}",
        p2p_endpoint=f"validator-{index}.example.net:26656",
        app_version="1",
        genesis_hash=genesis_hash,
        configuration_hash=f"sha256:{index:064x}",
        effective_epoch=0,
        operator_public_key=_public_key(key),
        operator_signature="ed25519:" + "00" * 64,
        ownership_evidence="OUT_OF_BAND_VERIFIED",
        ownership_evidence_root=f"sha256:ownership-{index}",
    )
    return draft.model_copy(
        update={"operator_signature": "ed25519:" + key.sign(ceremony._canonical_json(draft.unsigned_payload())).hex()}
    )


def test_create_validator_manifest_uses_local_operator_identity(tmp_path: Path) -> None:
    operator_key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "operator-attestation-key.raw"
    key_path.write_bytes(operator_key.private_bytes_raw())
    identity = tmp_path / "operator-identity.json"
    identity.write_text(
        json.dumps(
            {
                "operator_id": "operator-a",
                "control_group_id": "control-a",
                "operator_public_key": _public_key(operator_key),
            }
        ),
        encoding="utf-8",
    )
    consensus_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    genesis_manifest = tmp_path / "validator-a.genesis.json"
    genesis_manifest.write_text(
        json.dumps(
            {
                "schema_version": "aidn.public-validator-genesis-manifest.v1",
                "validator_id": "validator-a",
                "consensus_address": hashlib.sha256(consensus_key).digest()[:20].hex().upper(),
                "consensus_public_key": "ed25519:" + base64.b64encode(consensus_key).decode(),
            }
        ),
        encoding="utf-8",
    )
    genesis = tmp_path / "genesis.json"
    configuration = tmp_path / "comet-config.json"
    genesis.write_text('{"chain_id":"aidn-testnet-1"}\n', encoding="utf-8")
    configuration.write_text('{"persistent_peers":[]}\n', encoding="utf-8")
    output = tmp_path / "validator-a.public.json"

    assert (
        ceremony.create_validator_manifest(
            argparse.Namespace(
                validator_id="validator-a",
                operator_identity=identity,
                operator_attestation_key=key_path,
                genesis_manifest=genesis_manifest,
                network_id="aidn-testnet",
                chain_id="aidn-testnet-1",
                network_revision=1,
                comet_node_id="a" * 40,
                rpc_endpoint="https://rpc-a.example.net",
                p2p_endpoint="validator-a.example.net:26656",
                app_version="1",
                genesis=genesis,
                configuration=configuration,
                effective_epoch=0,
                ownership_evidence="NOT_PROVEN_BY_PROTOCOL",
                ownership_evidence_root=None,
                output=output,
            )
        )
        == 0
    )
    manifest = PublicValidatorManifest.model_validate_json(output.read_text(encoding="utf-8"))
    assert manifest.verify_integrity() is True
    assert manifest.comet_node_id == "a" * 40


def test_build_node_bundle_binds_genesis_and_excludes_local_peer(tmp_path: Path) -> None:
    genesis = tmp_path / "genesis.json"
    genesis.write_text('{"chain_id":"aidn-testnet-1"}\n', encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(genesis.read_bytes()).hexdigest()
    operator_keys = [Ed25519PrivateKey.generate() for _ in range(4)]
    manifests = [_manifest(index, key, digest) for index, key in enumerate(operator_keys)]
    validators = CometBftValidatorSet(tuple(CometBftValidator(address=item.consensus_address, public_key=item.consensus_public_key, voting_power=1) for item in manifests))
    validator_hash = Zip215CometBftEd25519Backend().validator_set_hash(validators)
    checkpoint = CometBftDeploymentCheckpoint(
        height=10, block_id="A" * 64, app_hash="B" * 64, header_time="2030-01-01T00:00:00Z", validator_set_hash=validator_hash, next_validator_set_hash=validator_hash,
        validators=[CometBftDeploymentValidator(address=item.consensus_address, public_key=item.consensus_public_key, voting_power=1) for item in manifests],
    )
    manifest_paths = []
    for manifest in manifests:
        path = tmp_path / f"{manifest.validator_id}.json"
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        manifest_paths.append(path)
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")
    draft = tmp_path / "public.draft.json"
    assert (
        ceremony.build_public_profile_draft(
            argparse.Namespace(
                profile_id="aidn-testnet-profile-v1",
                network_id="aidn-testnet",
                chain_id="aidn-testnet-1",
                network_revision=1,
                effective_epoch=1,
                minimum_rpc_agreement=3,
                minimum_distinct_operators=4,
                minimum_distinct_control_groups=4,
                profile_signature_threshold=2,
                validator_manifest=manifest_paths,
                trusted_checkpoint=checkpoint_path,
                independence_evidence="OUT_OF_BAND_VERIFIED",
                independence_evidence_root="sha256:independence",
                output=draft,
            )
        )
        == 0
    )
    authority_keys = {"release-a": Ed25519PrivateKey.generate(), "release-b": Ed25519PrivateKey.generate()}
    signature_paths = []
    for authority_id, authority_key in authority_keys.items():
        key_path = tmp_path / f"{authority_id}.raw"
        key_path.write_bytes(authority_key.private_bytes_raw())
        signature_path = tmp_path / f"{authority_id}.signature.json"
        assert (
            ceremony.sign_public_profile(
                argparse.Namespace(
                    profile_draft=draft,
                    authority_id=authority_id,
                    authority_signing_key=key_path,
                    output=signature_path,
                )
            )
            == 0
        )
        signature_paths.append(signature_path)
    profile_path = tmp_path / "public.json"
    assert (
        ceremony.assemble_public_profile(
            argparse.Namespace(
                profile_draft=draft,
                profile_signature=signature_paths,
                output=profile_path,
            )
        )
        == 0
    )
    signers = tmp_path / "signers.json"
    trusted = {authority_id: _public_key(key) for authority_id, key in authority_keys.items()}
    signers.write_text(json.dumps(trusted), encoding="utf-8")

    args = __import__("argparse").Namespace(
        name="AiDN Testnet",
        public_profile=profile_path,
        trusted_profile_signers=signers,
        genesis=genesis,
        local_comet_node_id=manifests[0].comet_node_id,
        local_rpc_port=26657,
        output_dir=tmp_path / "bundle",
    )
    assert ceremony.build_node_bundle(args) == 0
    profile_result = verify_network_profile(
        tmp_path / "bundle" / "network-profile.toml",
        trusted_profile_signers=trusted,
    )
    assert profile_result.valid is True
    text = (tmp_path / "bundle" / "network-profile.toml").read_text(encoding="utf-8")
    assert manifests[0].comet_node_id not in text
    assert text.count("@validator-") == 3
