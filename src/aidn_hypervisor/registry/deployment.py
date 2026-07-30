"""Operator configuration and secure composition for Registry replication."""

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, Field, field_validator, model_validator

from aidn_hypervisor.dispatcher.transport.tls import TlsListener, TlsTransport
from aidn_hypervisor.secrets import FileSecretManager, SecretManagerError

from .bridge import RegistryServiceAdapter, envelope_to_legacy_record
from .listener import RegistryReplicationTlsListener
from .reconnect import RegistryReplicationReconnectSupervisor
from .replication_peers import RegistryReplicationPeerController
from .replicator import RegistryReplicator
from .runtime import RegistryReplicationRuntime
from .transport_session import RegistryReplicationTransportSession


class RegistryReplicationTlsSecretConfig(BaseModel, frozen=True):
    certificate_handle: str
    private_key_handle: str
    certificate_authority_handle: str

    @field_validator(
        "certificate_handle", "private_key_handle", "certificate_authority_handle"
    )
    @classmethod
    def _secret_handle(cls, value: str) -> str:
        if not value.startswith("secret://"):
            raise ValueError("Registry replication TLS values must be secret handles")
        return value


class RegistryReplicationListenerConfig(BaseModel, frozen=True):
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    tls: RegistryReplicationTlsSecretConfig
    maximum_active_peers: int = Field(default=32, ge=1, le=1024)


class RegistryReplicationOutboundPeerConfig(BaseModel, frozen=True):
    peer_id: str = Field(min_length=1)
    host: str = Field(min_length=1)
    port: int = Field(ge=1, le=65535)
    tls: RegistryReplicationTlsSecretConfig


class RegistryReplicationDeploymentConfig(BaseModel, frozen=True):
    local_peer_id: str = Field(min_length=1)
    signing_key_handle: str
    listener: RegistryReplicationListenerConfig | None = None
    outbound_peers: list[RegistryReplicationOutboundPeerConfig] = Field(default_factory=list)
    network_id: str = Field(default="aidn", min_length=1)
    chain_id: str = Field(default="main", min_length=1)
    network_revision: str = Field(default="1.0", min_length=1)
    poll_interval_seconds: float = Field(default=0.1, gt=0, le=60)
    initial_backoff_seconds: float = Field(default=1, gt=0, le=3600)
    maximum_backoff_seconds: float = Field(default=60, gt=0, le=3600)
    handshake_timeout_seconds: float = Field(default=15, gt=0, le=300)

    @field_validator("signing_key_handle")
    @classmethod
    def _signing_handle(cls, value: str) -> str:
        if not value.startswith("secret://"):
            raise ValueError("Registry replication signing key must be a secret handle")
        return value

    @model_validator(mode="after")
    def _requires_transport(self):
        if self.listener is None and not self.outbound_peers:
            raise ValueError("Registry replication deployment requires a listener or outbound peer")
        peer_ids = [peer.peer_id for peer in self.outbound_peers]
        if len(peer_ids) != len(set(peer_ids)):
            raise ValueError("Registry replication outbound peer IDs must be unique")
        if self.maximum_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("Registry replication backoff maximum must not be below initial")
        return self


class RegistryReplicationSecretMaterializer:
    """Materialize TLS inputs as short-lived mode-0600 files for ssl.SSLContext."""

    def __init__(self, secret_manager: FileSecretManager) -> None:
        self._secret_manager = secret_manager
        self._directory = Path(tempfile.mkdtemp(prefix="aidn-registry-tls-"))
        os.chmod(self._directory, 0o700)
        self._next_file = 0

    def tls_paths(self, config: RegistryReplicationTlsSecretConfig) -> tuple[str, str, str]:
        return (
            str(self._write(config.certificate_handle, "certificate.pem")),
            str(self._write(config.private_key_handle, "private-key.pem")),
            str(self._write(config.certificate_authority_handle, "ca.pem")),
        )

    def close(self) -> None:
        shutil.rmtree(self._directory, ignore_errors=True)

    def _write(self, handle: str, suffix: str) -> Path:
        self._next_file += 1
        path = self._directory / f"{self._next_file}-{suffix}"
        path.write_bytes(self._secret_manager.get(handle))
        os.chmod(path, 0o600)
        return path


def load_file_secret_manager_from_environment() -> FileSecretManager | None:
    """Build the local encrypted store only when both deployment variables exist."""
    path = os.getenv("AIDN_SECRET_MANAGER_PATH")
    encoded_key = os.getenv("AIDN_SECRET_MANAGER_MASTER_KEY")
    if path is None and encoded_key is None:
        return None
    if not path or not encoded_key:
        raise ValueError(
            "AIDN_SECRET_MANAGER_PATH and AIDN_SECRET_MANAGER_MASTER_KEY are both required"
        )
    try:
        master_key = base64.b64decode(encoded_key, validate=True)
    except ValueError as exc:
        raise ValueError("AIDN_SECRET_MANAGER_MASTER_KEY must be base64-encoded") from exc
    return FileSecretManager(path=Path(path), master_key=master_key)


def load_registry_replication_deployment_config(path: Path) -> RegistryReplicationDeploymentConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Registry replication configuration cannot be loaded") from exc
    return RegistryReplicationDeploymentConfig.model_validate(raw)


def build_registry_replication_runtime(
    *,
    config: RegistryReplicationDeploymentConfig,
    registry_service,
    secret_manager: FileSecretManager,
) -> RegistryReplicationRuntime:
    """Compose one opt-in mTLS replication runtime from operator-held secrets."""
    materializer = RegistryReplicationSecretMaterializer(secret_manager)
    try:
        signer, local_public_key = _ed25519_signer(
            secret_manager.get(config.signing_key_handle)
        )
        registry_adapter = RegistryServiceAdapter(legacy_service=registry_service)
        registry_adapter.sync_from_legacy()
        replicator = RegistryReplicator(
            node_id=config.local_peer_id,
            store=registry_adapter.store,
            network_id=config.network_id,
            chain_id=config.chain_id,
            network_revision=config.network_revision,
            require_authenticated_peers=True,
        )

        def persist_replicated_object(peer_id, envelope) -> None:
            registry_service.upsert_registry_object(
                envelope_to_legacy_record(envelope, source_node_id=peer_id)
            )

        # The in-memory replication store is an execution cache. Persist every
        # newly verified inbound object before reporting the replication cycle.
        replicator.register_object_handler("*", persist_replicated_object)
        controller = RegistryReplicationPeerController(
            registry_service=registry_service,
            replicator=replicator,
        )
        listener = None
        if config.listener is not None:
            certificate, private_key, authority = materializer.tls_paths(config.listener.tls)
            listener = RegistryReplicationTlsListener(
                acceptor=TlsListener(
                    host=config.listener.host,
                    port=config.listener.port,
                    certfile=certificate,
                    keyfile=private_key,
                    ca_certs=authority,
                    verify_client=True,
                ),
                local_peer_id=config.local_peer_id,
                local_public_key=local_public_key,
                signer=signer,
                peer_controller=controller,
                maximum_active_peers=config.listener.maximum_active_peers,
                network_id=config.network_id,
                chain_id=config.chain_id,
                network_revision=config.network_revision,
            )
        sessions = {}
        approved_peer_ids = {
            peer["peer_id"]
            for peer in registry_service.list_replication_peers()
            if peer["enabled"]
        }
        for peer in config.outbound_peers:
            if peer.peer_id not in approved_peer_ids:
                raise ValueError(f"Registry replication peer is not locally approved: {peer.peer_id}")
            certificate, private_key, authority = materializer.tls_paths(peer.tls)
            sessions[peer.peer_id] = RegistryReplicationTransportSession(
                local_peer_id=config.local_peer_id,
                peer_id=peer.peer_id,
                transport=TlsTransport(
                    peer.host,
                    peer.port,
                    certfile=certificate,
                    keyfile=private_key,
                    ca_certs=authority,
                    verify=True,
                ),
                peer_controller=controller,
                network_id=config.network_id,
                chain_id=config.chain_id,
                network_revision=config.network_revision,
            )
        supervisor = None
        if sessions:
            supervisor = RegistryReplicationReconnectSupervisor(
                sessions=sessions,
                local_public_key=local_public_key,
                signer=signer,
                initial_backoff_seconds=config.initial_backoff_seconds,
                maximum_backoff_seconds=config.maximum_backoff_seconds,
                handshake_timeout_seconds=config.handshake_timeout_seconds,
            )
        return RegistryReplicationRuntime(
            listener=listener,
            reconnect_supervisor=supervisor,
            poll_interval_seconds=config.poll_interval_seconds,
            cleanup=materializer.close,
            replicator=replicator,
        )
    except Exception:
        materializer.close()
        raise


def _ed25519_signer(private_key: bytes) -> tuple[Callable[[bytes], str], str]:
    try:
        key = Ed25519PrivateKey.from_private_bytes(private_key)
    except ValueError as exc:
        raise SecretManagerError("Registry replication signing key is not Ed25519") from exc
    public_key = "ed25519:" + key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    return lambda payload: "ed25519:" + key.sign(payload).hex(), public_key
