"""Operator-selected network profile with a fail-closed trust boundary.

The TOML document combines two deliberately different kinds of data:

* consensus-bound identity, which is hash-bound and cannot be overridden by
  an environment variable; and
* host-local CometBFT connectivity, which may differ between operators.

The signed public multi-validator profile remains the authority for a public
network.  This module only selects it and verifies that the local profile is
bound to the same network and chain.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import tomllib
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NETWORK_PROFILE_ENV = "AIDN_NETWORK_PROFILE_PATH"
NETWORK_PROFILE_SIGNERS_ENV = "AIDN_NETWORK_PROFILE_SIGNERS_PATH"
NETWORK_PROFILE_VERSION = "aidn.network-profile.v1"
MAX_NETWORK_PROFILE_BYTES = 128 * 1024


class NetworkProfileError(ValueError):
    """Raised when a network profile is unsafe, inconsistent, or incomplete."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class NetworkCometBftConfig(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    p2p_host: str = "0.0.0.0"
    p2p_port: int = Field(default=26656, ge=1, le=65535)
    rpc_host: str = "127.0.0.1"
    rpc_port: int = Field(default=26657, ge=1, le=65535)
    persistent_peers: list[str] = Field(default_factory=list)
    seeds: list[str] = Field(default_factory=list)
    max_num_inbound_peers: int = Field(default=40, ge=0, le=1_000)
    max_num_outbound_peers: int = Field(default=10, ge=0, le=1_000)
    pex: bool = True
    addr_book_strict: bool = True

    @model_validator(mode="after")
    def validate_ports(self) -> NetworkCometBftConfig:
        if self.p2p_port == self.rpc_port:
            raise ValueError("NETWORK_PROFILE_PORT_CONFLICT")
        return self


class NetworkConsensusTiming(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    timeout_propose: str = "3s"
    timeout_prevote: str = "1s"
    timeout_precommit: str = "1s"
    timeout_commit: str = "3s"


class NetworkStateSyncConfig(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    rpc_servers: list[str] = Field(default_factory=list)
    trust_height: int = Field(default=0, ge=0)
    trust_hash: str = ""

    @model_validator(mode="after")
    def validate_trust_pair(self) -> NetworkStateSyncConfig:
        if bool(self.trust_height) != bool(self.trust_hash):
            raise ValueError("NETWORK_PROFILE_STATE_SYNC_TRUST_PAIR_INCOMPLETE")
        if self.enabled and len(self.rpc_servers) == 1:
            raise ValueError("NETWORK_PROFILE_STATE_SYNC_REQUIRES_TWO_RPC_SERVERS")
        return self


class NetworkDiscoveryConfig(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    bootstrap: list[str] = Field(default_factory=list)


class NetworkProfileBody(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=96)
    network_id: str = Field(min_length=1, max_length=96)
    chain_id: str = Field(min_length=1, max_length=96)
    environment: Literal["development", "testnet", "mainnet", "custom"]
    protocol_version: str = Field(min_length=1, max_length=96)
    genesis_file: str = Field(min_length=1)
    genesis_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    public_profile_file: str | None = None
    public_profile_sha256: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    cometbft: NetworkCometBftConfig = Field(default_factory=NetworkCometBftConfig)
    consensus: NetworkConsensusTiming = Field(default_factory=NetworkConsensusTiming)
    state_sync: NetworkStateSyncConfig = Field(default_factory=NetworkStateSyncConfig)
    discovery: NetworkDiscoveryConfig = Field(default_factory=NetworkDiscoveryConfig)

    @model_validator(mode="after")
    def validate_public_binding(self) -> NetworkProfileBody:
        public_values = (self.public_profile_file, self.public_profile_sha256)
        if any(public_values) and not all(public_values):
            raise ValueError("NETWORK_PROFILE_PUBLIC_BINDING_INCOMPLETE")
        if self.environment in {"testnet", "mainnet"} and not all(public_values):
            raise ValueError("NETWORK_PROFILE_PUBLIC_BINDING_REQUIRED")
        return self


class NetworkProfile(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = NETWORK_PROFILE_VERSION
    network: NetworkProfileBody

    @model_validator(mode="after")
    def validate_version(self) -> NetworkProfile:
        if self.schema_version != NETWORK_PROFILE_VERSION:
            raise ValueError("NETWORK_PROFILE_VERSION_UNSUPPORTED")
        return self

    @property
    def consensus_binding(self) -> dict[str, str]:
        return {
            "network_id": self.network.network_id,
            "chain_id": self.network.chain_id,
            "protocol_version": self.network.protocol_version,
            "genesis_sha256": self.network.genesis_sha256,
            "public_profile_sha256": self.network.public_profile_sha256 or "",
        }

    @property
    def consensus_binding_hash(self) -> str:
        return _canonical_hash(self.consensus_binding)


class NetworkProfileVerification(BaseModel, frozen=True):
    profile_path: str
    profile_name: str
    network_id: str
    chain_id: str
    environment: str
    consensus_binding_hash: str
    valid: bool
    errors: list[str] = Field(default_factory=list)


def load_network_profile(path: str | Path) -> NetworkProfile:
    target = Path(path).expanduser()
    try:
        if target.stat().st_size > MAX_NETWORK_PROFILE_BYTES:
            raise NetworkProfileError("NETWORK_PROFILE_TOO_LARGE")
        with target.open("rb") as stream:
            document = tomllib.load(stream)
    except FileNotFoundError as exc:
        raise NetworkProfileError(f"network profile does not exist: {target}") from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise NetworkProfileError(f"could not load network profile {target}: {exc}") from exc
    try:
        return NetworkProfile.model_validate(document)
    except ValueError as exc:
        raise NetworkProfileError(f"invalid network profile {target}: {exc}") from exc


def load_network_profile_signers(path: str | Path | None) -> dict[str, str]:
    if path is None or not str(path).strip():
        return {}
    target = Path(path).expanduser()
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NetworkProfileError(
            f"could not load trusted network profile signers {target}: {exc}"
        ) from exc
    if not isinstance(document, dict) or not all(
        isinstance(key, str) and key and isinstance(value, str) and value
        for key, value in document.items()
    ):
        raise NetworkProfileError("NETWORK_PROFILE_SIGNER_REGISTRY_INVALID")
    return dict(document)


def verify_network_profile(
    path: str | Path,
    *,
    trusted_profile_signers: Mapping[str, str] | None = None,
) -> NetworkProfileVerification:
    target = Path(path).expanduser().resolve()
    profile = load_network_profile(target)
    errors: list[str] = []
    root = target.parent

    genesis = (root / profile.network.genesis_file).resolve()
    try:
        if _sha256_file(genesis) != profile.network.genesis_sha256:
            errors.append("NETWORK_PROFILE_GENESIS_HASH_MISMATCH")
    except OSError:
        errors.append("NETWORK_PROFILE_GENESIS_UNAVAILABLE")

    if profile.network.public_profile_file:
        public_path = (root / profile.network.public_profile_file).resolve()
        try:
            if _sha256_file(public_path) != profile.network.public_profile_sha256:
                errors.append("NETWORK_PROFILE_PUBLIC_PROFILE_HASH_MISMATCH")
            else:
                from aidn_hypervisor.consensus.public_network import (
                    PublicMultiValidatorNetworkProfile,
                )

                public = PublicMultiValidatorNetworkProfile.model_validate_json(
                    public_path.read_text(encoding="utf-8")
                )
                trusted = dict(trusted_profile_signers or {})
                if not trusted:
                    errors.append("NETWORK_PROFILE_TRUSTED_SIGNERS_REQUIRED")
                elif len(public.verify_profile_signatures(trusted)) < (
                    public.profile_signature_threshold
                ):
                    errors.append("NETWORK_PROFILE_PUBLIC_PROFILE_SIGNATURE_INVALID")
                if (
                    public.network_id != profile.network.network_id
                    or public.chain_id != profile.network.chain_id
                ):
                    errors.append("NETWORK_PROFILE_PUBLIC_PROFILE_BINDING_MISMATCH")
        except (OSError, ValueError):
            errors.append("NETWORK_PROFILE_PUBLIC_PROFILE_INVALID")

    return NetworkProfileVerification(
        profile_path=str(target),
        profile_name=profile.network.name,
        network_id=profile.network.network_id,
        chain_id=profile.network.chain_id,
        environment=profile.network.environment,
        consensus_binding_hash=profile.consensus_binding_hash,
        valid=not errors,
        errors=sorted(set(errors)),
    )


def apply_network_profile_environment(
    profile: NetworkProfile,
    *,
    environ: MutableMapping[str, str] | None = None,
) -> tuple[str, ...]:
    """Project one verified profile into existing runtime environment keys.

    Consensus-bound values fail closed on a conflicting explicit value. Local
    values preserve explicit process configuration and only fill gaps.
    """

    values = os.environ if environ is None else environ
    consensus_values = {
        "AIDN_NETWORK_ID": profile.network.network_id,
        "AIDN_COMETBFT_CHAIN_ID": profile.network.chain_id,
        "AIDN_PROTOCOL_VERSION": profile.network.protocol_version,
        "AIDN_NETWORK_GENESIS_SHA256": profile.network.genesis_sha256,
        "AIDN_NETWORK_PROFILE_BINDING_HASH": profile.consensus_binding_hash,
    }
    for key, expected in consensus_values.items():
        current = values.get(key)
        if current is not None and current != expected:
            raise NetworkProfileError(f"NETWORK_PROFILE_CONSENSUS_OVERRIDE:{key}")

    local_values = {
        "AIDN_COMETBFT_ENDPOINT": (
            f"tcp://{profile.network.cometbft.rpc_host}:"
            f"{profile.network.cometbft.rpc_port}"
        ),
        "AIDN_COMETBFT_P2P_HOST": profile.network.cometbft.p2p_host,
        "AIDN_COMETBFT_P2P_PORT": str(profile.network.cometbft.p2p_port),
        "AIDN_COMETBFT_SEEDS": ",".join(profile.network.cometbft.seeds),
        "AIDN_COMETBFT_PERSISTENT_PEERS": ",".join(
            profile.network.cometbft.persistent_peers
        ),
    }
    applied: list[str] = []
    for key, value in {**consensus_values, **local_values}.items():
        if key not in values:
            values[key] = value
            applied.append(key)
    return tuple(sorted(applied))


def activate_network_profile(
    source: str | Path,
    destination: str | Path,
    *,
    trusted_profile_signers: Mapping[str, str] | None = None,
) -> NetworkProfileVerification:
    """Verify and atomically activate a profile without rewriting its content."""

    source_path = Path(source).expanduser().resolve()
    verification = verify_network_profile(
        source_path, trusted_profile_signers=trusted_profile_signers
    )
    if not verification.valid:
        raise NetworkProfileError(
            "network profile verification failed: " + ",".join(verification.errors)
        )
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{target.name}-", dir=target.parent
        )
        os.close(descriptor)
        shutil.copyfile(source_path, temporary)
        os.chmod(temporary, 0o600)
        staged = verify_network_profile(
            temporary, trusted_profile_signers=trusted_profile_signers
        )
        if not staged.valid:
            raise NetworkProfileError(
                "network profile cannot be activated at its destination: "
                + ",".join(staged.errors)
            )
        os.replace(temporary, target)
        temporary = None
    except BaseException:
        if temporary:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
        raise
    return verify_network_profile(
        target, trusted_profile_signers=trusted_profile_signers
    )


def resolve_network_profile_path(
    path: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    values = os.environ if environ is None else environ
    selected = path if path is not None else values.get(NETWORK_PROFILE_ENV)
    if selected is None or not str(selected).strip():
        return None
    return Path(str(selected)).expanduser()


__all__ = [
    "MAX_NETWORK_PROFILE_BYTES",
    "NETWORK_PROFILE_ENV",
    "NETWORK_PROFILE_SIGNERS_ENV",
    "NETWORK_PROFILE_VERSION",
    "NetworkProfile",
    "NetworkProfileError",
    "NetworkProfileVerification",
    "activate_network_profile",
    "apply_network_profile_environment",
    "load_network_profile",
    "load_network_profile_signers",
    "resolve_network_profile_path",
    "verify_network_profile",
]
