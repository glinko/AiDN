#!/usr/bin/env python3
"""Create the signed, secret-free artifacts for a four-validator launch.

The founding Genesis is produced separately by ``public-testnet-genesis.py``.
This program deliberately starts only after that immutable Genesis exists:

* each validator signs its own public deployment manifest locally; and
* the coordinator turns an already accepted public network profile into one
  host-local Network Profile bundle per validator.

No command prints, copies, or writes an operator private key into a release
bundle.  The signed deployment manifest carries both the consensus validator
identity and the distinct CometBFT node identity required by persistent peers.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from aidn_hypervisor.consensus.deployment import CometBftDeploymentCheckpoint
from aidn_hypervisor.consensus.public_network import (
    PublicMultiValidatorNetworkProfile,
    PublicProfileSignature,
    PublicValidatorManifest,
    build_public_multivalidator_profile,
    inspect_public_multivalidator_profile,
)
from aidn_hypervisor.network_profile import (
    NetworkProfile,
    load_network_profile_signers,
    verify_network_profile,
)

GENESIS_MANIFEST_VERSION = "aidn.public-validator-genesis-manifest.v1"


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _write_new(path: Path, content: bytes, *, mode: int = 0o644) -> None:
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to replace existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_raw_ed25519_key(path: Path) -> Ed25519PrivateKey:
    payload = path.expanduser().resolve().read_bytes()
    if len(payload) != 32:
        raise ValueError("operator attestation key must contain exactly 32 raw bytes")
    return Ed25519PrivateKey.from_private_bytes(payload)


def _public_key(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "ed25519:" + raw.hex()


def _load_genesis_manifest(path: Path) -> dict[str, str]:
    document = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != GENESIS_MANIFEST_VERSION:
        raise ValueError("invalid public validator Genesis manifest")
    values = {
        name: document.get(name)
        for name in ("validator_id", "consensus_address", "consensus_public_key")
    }
    if not all(isinstance(value, str) and value for value in values.values()):
        raise ValueError("public validator Genesis manifest is incomplete")
    if not values["consensus_public_key"].startswith("ed25519:"):
        raise ValueError("public validator Genesis consensus key is invalid")
    try:
        consensus_key = base64.b64decode(
            values["consensus_public_key"].removeprefix("ed25519:"), validate=True
        )
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError("public validator Genesis consensus key is invalid") from error
    if len(consensus_key) != 32:
        raise ValueError("public validator Genesis consensus key is invalid")
    expected_address = hashlib.sha256(consensus_key).digest()[:20].hex().upper()
    if values["consensus_address"].upper() != expected_address:
        raise ValueError("public validator Genesis consensus address does not match key")
    return {
        "validator_id": values["validator_id"],
        "consensus_address": expected_address,
        "consensus_public_key": values["consensus_public_key"],
    }


def _load_operator_identity(path: Path, private_key: Ed25519PrivateKey) -> dict[str, str]:
    document = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("operator identity must be a JSON object")
    required = ("operator_id", "control_group_id", "operator_public_key")
    if not all(isinstance(document.get(field), str) and document[field] for field in required):
        raise ValueError("operator identity is incomplete")
    if document["operator_public_key"] != _public_key(private_key):
        raise ValueError("operator identity does not match the local attestation key")
    return {field: document[field] for field in required}


def _parse_p2p_endpoint(value: str) -> tuple[str, int]:
    parsed = urlsplit("//" + value)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("P2P endpoint must be host:port without a scheme or path")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("P2P endpoint port is invalid") from error
    if port is None or not 1 <= port <= 65535:
        raise ValueError("P2P endpoint must include a valid port")
    return parsed.hostname, port


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _network_profile_toml(
    *,
    name: str,
    profile: PublicMultiValidatorNetworkProfile,
    genesis_hash: str,
    public_profile_hash: str,
    local_p2p_port: int,
    local_rpc_port: int,
    peers: list[str],
    bootstrap: list[str],
) -> str:
    return "\n".join(
        (
            'schema_version = "aidn.network-profile.v1"',
            "",
            "[network]",
            f"name = {_toml_string(name)}",
            f"network_id = {_toml_string(profile.network_id)}",
            f"chain_id = {_toml_string(profile.chain_id)}",
            'environment = "testnet"',
            f"protocol_version = {_toml_string(profile.validator_manifests[0].app_version)}",
            'genesis_file = "genesis.json"',
            f"genesis_sha256 = {_toml_string(genesis_hash)}",
            'public_profile_file = "public-multivalidator-profile.json"',
            f"public_profile_sha256 = {_toml_string(public_profile_hash)}",
            "",
            "[network.cometbft]",
            'p2p_host = "0.0.0.0"',
            f"p2p_port = {local_p2p_port}",
            'rpc_host = "127.0.0.1"',
            f"rpc_port = {local_rpc_port}",
            f"persistent_peers = {_toml_array(peers)}",
            "seeds = []",
            "max_num_inbound_peers = 40",
            "max_num_outbound_peers = 10",
            "pex = true",
            "addr_book_strict = true",
            "",
            "[network.consensus]",
            'timeout_propose = "3s"',
            'timeout_prevote = "1s"',
            'timeout_precommit = "1s"',
            'timeout_commit = "3s"',
            "",
            "[network.state_sync]",
            "enabled = false",
            "rpc_servers = []",
            "trust_height = 0",
            'trust_hash = ""',
            "",
            "[network.discovery]",
            "enabled = true",
            f"bootstrap = {_toml_array(bootstrap)}",
            "",
        )
    )


def create_validator_manifest(args: argparse.Namespace) -> int:
    private_key = _load_raw_ed25519_key(args.operator_attestation_key)
    identity = _load_operator_identity(args.operator_identity, private_key)
    genesis_manifest = _load_genesis_manifest(args.genesis_manifest)
    if genesis_manifest["validator_id"] != args.validator_id:
        raise ValueError("--validator-id does not match the public validator Genesis manifest")
    _, _ = _parse_p2p_endpoint(args.p2p_endpoint)
    genesis = args.genesis.expanduser().resolve()
    configuration = args.configuration.expanduser().resolve()
    if not genesis.is_file() or genesis.is_symlink():
        raise ValueError("--genesis must be a regular file")
    if not configuration.is_file() or configuration.is_symlink():
        raise ValueError("--configuration must be a regular file")
    draft = PublicValidatorManifest(
        validator_id=args.validator_id,
        operator_id=identity["operator_id"],
        control_group_id=identity["control_group_id"],
        network_id=args.network_id,
        chain_id=args.chain_id,
        network_revision=args.network_revision,
        consensus_address=genesis_manifest["consensus_address"],
        consensus_public_key=genesis_manifest["consensus_public_key"],
        rpc_endpoint=args.rpc_endpoint,
        comet_node_id=args.comet_node_id.lower(),
        p2p_endpoint=args.p2p_endpoint,
        app_version=args.app_version,
        genesis_hash=_sha256_file(genesis),
        configuration_hash=_sha256_file(configuration),
        effective_epoch=args.effective_epoch,
        operator_public_key=identity["operator_public_key"],
        operator_signature="ed25519:" + "00" * 64,
        ownership_evidence=args.ownership_evidence,
        ownership_evidence_root=args.ownership_evidence_root,
    )
    signed = draft.model_copy(
        update={
            "operator_signature": "ed25519:"
            + private_key.sign(_canonical_json(draft.unsigned_payload())).hex()
        }
    )
    _write_new(
        args.output.expanduser().resolve(),
        signed.model_dump_json(indent=2).encode("utf-8") + b"\n",
    )
    print(
        json.dumps(
            {
                "status": "SIGNED",
                "validator_id": signed.validator_id,
                "comet_node_id": signed.comet_node_id,
                "genesis_hash": signed.genesis_hash,
                "manifest_hash": signed.manifest_hash,
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


def build_public_profile_draft(args: argparse.Namespace) -> int:
    checkpoint_path = args.trusted_checkpoint.expanduser().resolve()
    if not checkpoint_path.is_file() or checkpoint_path.is_symlink():
        raise ValueError("--trusted-checkpoint must be a regular file")
    manifest_paths = [path.expanduser().resolve() for path in args.validator_manifest]
    if not all(path.is_file() and not path.is_symlink() for path in manifest_paths):
        raise ValueError("every --validator-manifest must be a regular file")
    manifests = [
        PublicValidatorManifest.model_validate_json(path.read_text(encoding="utf-8"))
        for path in manifest_paths
    ]
    checkpoint = CometBftDeploymentCheckpoint.model_validate_json(
        checkpoint_path.read_text(encoding="utf-8")
    )
    profile = build_public_multivalidator_profile(
        profile_id=args.profile_id,
        network_id=args.network_id,
        chain_id=args.chain_id,
        network_revision=args.network_revision,
        effective_epoch=args.effective_epoch,
        minimum_rpc_agreement=args.minimum_rpc_agreement,
        validator_manifests=manifests,
        trusted_checkpoint=checkpoint,
        minimum_distinct_operators=args.minimum_distinct_operators,
        minimum_distinct_control_groups=args.minimum_distinct_control_groups,
        profile_signature_threshold=args.profile_signature_threshold,
        independence_evidence=args.independence_evidence,
        independence_evidence_root=args.independence_evidence_root,
    )
    _write_new(
        args.output.expanduser().resolve(),
        profile.model_dump_json(indent=2).encode("utf-8") + b"\n",
    )
    print(
        json.dumps(
            {
                "status": "PROFILE_DRAFT_READY",
                "profile_id": profile.profile_id,
                "profile_hash": profile.profile_hash,
                "signature_threshold": profile.profile_signature_threshold,
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


def sign_public_profile(args: argparse.Namespace) -> int:
    source = args.profile_draft.expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise ValueError("--profile-draft must be a regular file")
    profile = PublicMultiValidatorNetworkProfile.model_validate_json(source.read_text(encoding="utf-8"))
    key = _load_raw_ed25519_key(args.authority_signing_key)
    signature = PublicProfileSignature(
        authority_id=args.authority_id,
        public_key=_public_key(key),
        signature="ed25519:" + key.sign(profile.signing_payload()).hex(),
    )
    _write_new(
        args.output.expanduser().resolve(),
        signature.model_dump_json(indent=2).encode("utf-8") + b"\n",
    )
    print(
        json.dumps(
            {
                "status": "PROFILE_SIGNATURE_CREATED",
                "authority_id": signature.authority_id,
                "profile_id": profile.profile_id,
                "profile_hash": profile.profile_hash,
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


def assemble_public_profile(args: argparse.Namespace) -> int:
    source = args.profile_draft.expanduser().resolve()
    if not source.is_file() or source.is_symlink():
        raise ValueError("--profile-draft must be a regular file")
    profile = PublicMultiValidatorNetworkProfile.model_validate_json(source.read_text(encoding="utf-8"))
    signature_paths = [path.expanduser().resolve() for path in args.profile_signature]
    if not all(path.is_file() and not path.is_symlink() for path in signature_paths):
        raise ValueError("every --profile-signature must be a regular file")
    signatures = [
        PublicProfileSignature.model_validate_json(path.read_text(encoding="utf-8"))
        for path in signature_paths
    ]
    if len({item.authority_id for item in signatures}) != len(signatures):
        raise ValueError("profile signatures must use distinct authority IDs")
    if len(signatures) < profile.profile_signature_threshold:
        raise ValueError("profile signature threshold has not been collected")
    final = profile.model_copy(update={"profile_signatures": signatures})
    _write_new(
        args.output.expanduser().resolve(),
        final.model_dump_json(indent=2).encode("utf-8") + b"\n",
    )
    print(
        json.dumps(
            {
                "status": "PROFILE_ASSEMBLED",
                "profile_id": final.profile_id,
                "profile_hash": final.profile_hash,
                "signature_count": len(signatures),
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )
    return 0


def build_node_bundle(args: argparse.Namespace) -> int:
    profile_path = args.public_profile.expanduser().resolve()
    genesis = args.genesis.expanduser().resolve()
    signer_path = args.trusted_profile_signers.expanduser().resolve()
    if not all(path.is_file() and not path.is_symlink() for path in (profile_path, genesis, signer_path)):
        raise ValueError("profile, Genesis and trusted signer registry must be regular files")
    profile = PublicMultiValidatorNetworkProfile.model_validate_json(
        profile_path.read_text(encoding="utf-8")
    )
    trusted_signers = load_network_profile_signers(signer_path)
    report = inspect_public_multivalidator_profile(
        profile,
        trusted_profile_signers=trusted_signers,
        require_independence_evidence=True,
    )
    if not report.valid:
        raise ValueError("public network profile is not accepted: " + ",".join(report.failure_reasons))
    genesis_hash = _sha256_file(genesis)
    if any(item.genesis_hash != genesis_hash for item in profile.validator_manifests):
        raise ValueError("public validator manifest Genesis hash does not match --genesis")
    local_node_id = args.local_comet_node_id.lower()
    local = next(
        (item for item in profile.validator_manifests if item.comet_node_id == local_node_id),
        None,
    )
    if local is None:
        raise ValueError("--local-comet-node-id is not present in the accepted public profile")
    _, local_p2p_port = _parse_p2p_endpoint(local.p2p_endpoint)
    ordered = sorted(profile.validator_manifests, key=lambda item: item.comet_node_id)
    peers = [
        f"{item.comet_node_id}@{item.p2p_endpoint}"
        for item in ordered
        if item.comet_node_id != local_node_id
    ]
    bootstrap = [item.rpc_endpoint.rstrip("/") for item in ordered]
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists() or output_dir.is_symlink():
        raise ValueError(f"refusing to replace existing bundle directory: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}-", dir=output_dir.parent))
    try:
        bundle_profile = temporary / "network-profile.toml"
        bundle_genesis = temporary / "genesis.json"
        bundle_public = temporary / "public-multivalidator-profile.json"
        bundle_signers = temporary / "trusted-profile-signers.json"
        shutil.copyfile(genesis, bundle_genesis)
        shutil.copyfile(profile_path, bundle_public)
        bundle_signers.write_text(
            json.dumps(trusted_signers, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        bundle_profile.write_text(
            _network_profile_toml(
                name=args.name,
                profile=profile,
                genesis_hash=genesis_hash,
                public_profile_hash=_sha256_file(bundle_public),
                local_p2p_port=local_p2p_port,
                local_rpc_port=args.local_rpc_port,
                peers=peers,
                bootstrap=bootstrap,
            ),
            encoding="utf-8",
        )
        verified_profile = NetworkProfile.model_validate(
            __import__("tomllib").loads(bundle_profile.read_text(encoding="utf-8"))
        )
        if verified_profile.network.network_id != profile.network_id:
            raise ValueError("generated network profile is not bound to the public profile")
        verification = verify_network_profile(bundle_profile, trusted_profile_signers=trusted_signers)
        if not verification.valid:
            raise ValueError("generated network profile did not verify: " + ",".join(verification.errors))
        os.replace(temporary, output_dir)
        temporary = None  # type: ignore[assignment]
    finally:
        if temporary is not None and temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
    print(
        json.dumps(
            {
                "status": "BUNDLE_READY",
                "local_comet_node_id": local_node_id,
                "network_id": profile.network_id,
                "chain_id": profile.chain_id,
                "genesis_sha256": genesis_hash,
                "persistent_peer_count": len(peers),
                "output_dir": str(output_dir),
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    manifest = commands.add_parser("create-validator-manifest", help="sign one public validator deployment manifest")
    manifest.add_argument("--validator-id", required=True)
    manifest.add_argument("--operator-identity", type=Path, required=True)
    manifest.add_argument("--operator-attestation-key", type=Path, required=True)
    manifest.add_argument("--genesis-manifest", type=Path, required=True)
    manifest.add_argument("--network-id", required=True)
    manifest.add_argument("--chain-id", required=True)
    manifest.add_argument("--network-revision", type=int, required=True)
    manifest.add_argument("--comet-node-id", required=True)
    manifest.add_argument("--rpc-endpoint", required=True)
    manifest.add_argument("--p2p-endpoint", required=True)
    manifest.add_argument("--app-version", required=True)
    manifest.add_argument("--genesis", type=Path, required=True)
    manifest.add_argument("--configuration", type=Path, required=True)
    manifest.add_argument("--effective-epoch", type=int, default=0)
    manifest.add_argument(
        "--ownership-evidence",
        choices=("OUT_OF_BAND_VERIFIED", "NOT_PROVEN_BY_PROTOCOL"),
        default="NOT_PROVEN_BY_PROTOCOL",
    )
    manifest.add_argument("--ownership-evidence-root")
    manifest.add_argument("--output", type=Path, required=True)
    manifest.set_defaults(handler=create_validator_manifest)

    draft = commands.add_parser("build-public-profile-draft", help="build an unsigned public profile after a checkpoint")
    draft.add_argument("--profile-id", required=True)
    draft.add_argument("--network-id", required=True)
    draft.add_argument("--chain-id", required=True)
    draft.add_argument("--network-revision", type=int, required=True)
    draft.add_argument("--effective-epoch", type=int, required=True)
    draft.add_argument("--minimum-rpc-agreement", type=int, default=3)
    draft.add_argument("--minimum-distinct-operators", type=int, default=4)
    draft.add_argument("--minimum-distinct-control-groups", type=int, default=4)
    draft.add_argument("--profile-signature-threshold", type=int, default=2)
    draft.add_argument("--validator-manifest", type=Path, required=True, action="append")
    draft.add_argument("--trusted-checkpoint", type=Path, required=True)
    draft.add_argument(
        "--independence-evidence",
        choices=("OUT_OF_BAND_VERIFIED", "NOT_PROVEN_BY_PROTOCOL"),
        required=True,
    )
    draft.add_argument("--independence-evidence-root")
    draft.add_argument("--output", type=Path, required=True)
    draft.set_defaults(handler=build_public_profile_draft)

    sign = commands.add_parser("sign-public-profile", help="sign a profile draft locally with one release authority")
    sign.add_argument("--profile-draft", type=Path, required=True)
    sign.add_argument("--authority-id", required=True)
    sign.add_argument("--authority-signing-key", type=Path, required=True)
    sign.add_argument("--output", type=Path, required=True)
    sign.set_defaults(handler=sign_public_profile)

    assemble = commands.add_parser("assemble-public-profile", help="combine threshold authority signatures into the final profile")
    assemble.add_argument("--profile-draft", type=Path, required=True)
    assemble.add_argument("--profile-signature", type=Path, required=True, action="append")
    assemble.add_argument("--output", type=Path, required=True)
    assemble.set_defaults(handler=assemble_public_profile)

    bundle = commands.add_parser("build-node-bundle", help="build one verified validator Network Profile bundle")
    bundle.add_argument("--name", default="AiDN Public Testnet")
    bundle.add_argument("--public-profile", type=Path, required=True)
    bundle.add_argument("--trusted-profile-signers", type=Path, required=True)
    bundle.add_argument("--genesis", type=Path, required=True)
    bundle.add_argument("--local-comet-node-id", required=True)
    bundle.add_argument("--local-rpc-port", type=int, default=26657)
    bundle.add_argument("--output-dir", type=Path, required=True)
    bundle.set_defaults(handler=build_node_bundle)

    args = parser.parse_args()
    try:
        return args.handler(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
