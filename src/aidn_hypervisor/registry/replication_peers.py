"""Operator-managed lifecycle for authenticated Registry replication peers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .replicator import RegistryReplicator

if TYPE_CHECKING:
    from aidn_hypervisor.registry_service import RegistryService


class RegistryReplicationPeerController:
    """Apply locally approved peer identities to a strict RegistryReplicator.

    This controller deliberately manages identity only. Physical transport is
    configured separately, so discovery cannot turn an arbitrary network peer
    into a trusted replication source.
    """

    def __init__(
        self,
        *,
        registry_service: RegistryService,
        replicator: RegistryReplicator,
    ) -> None:
        if not replicator.requires_authenticated_peers:
            raise ValueError("Registry replication peer controller requires strict peer auth")
        self._registry_service = registry_service
        self._replicator = replicator
        self._configured_public_keys: dict[str, str] = {}
        self.reload_configured_peers()

    @property
    def replicator(self) -> RegistryReplicator:
        """Strict replicator controlled by this peer-identity lifecycle."""
        return self._replicator

    def reload_configured_peers(self) -> int:
        """Reload local peer approval records and revoke changed identities."""
        configured = {
            peer["peer_id"]: peer
            for peer in self._registry_service.list_replication_peers()
        }
        for peer_id, old_key in tuple(self._configured_public_keys.items()):
            current = configured.get(peer_id)
            if (
                current is None
                or not current["enabled"]
                or current["public_key"] != old_key
            ):
                self._replicator.revoke_peer_authentication(peer_id)
                self._configured_public_keys.pop(peer_id, None)

        loaded = 0
        for peer_id, peer in configured.items():
            if not peer["enabled"]:
                continue
            self._replicator.register_peer_identity(
                peer_id=peer_id,
                public_key=peer["public_key"],
            )
            self._configured_public_keys[peer_id] = peer["public_key"]
            loaded += 1
        return loaded

    def authenticate_peer(
        self,
        *,
        peer_id: str,
        claimed_public_key: str,
        signature: str,
        nonce: str,
        timestamp: float,
    ) -> bool:
        """Authenticate only an enabled, locally configured peer identity."""
        self.reload_configured_peers()
        configured = next(
            (
                peer
                for peer in self._registry_service.list_replication_peers()
                if peer["peer_id"] == peer_id
            ),
            None,
        )
        if (
            configured is None
            or not configured["enabled"]
            or configured["public_key"] != claimed_public_key
        ):
            self._replicator.revoke_peer_authentication(peer_id)
            if configured is not None:
                self._registry_service.record_replication_peer_authentication(
                    peer_id=peer_id,
                    authenticated=False,
                    error="peer_identity_not_approved",
                )
            return False

        authenticated = self._replicator.authenticate_peer(
            peer_id=peer_id,
            claimed_public_key=claimed_public_key,
            signature=signature,
            nonce=nonce,
            timestamp=timestamp,
        )
        self._registry_service.record_replication_peer_authentication(
            peer_id=peer_id,
            authenticated=authenticated,
            error=None if authenticated else "peer_authentication_failed",
        )
        return authenticated

    def disconnect_peer(self, peer_id: str) -> None:
        """Forget one transport session while retaining its local approval."""
        self._replicator.revoke_peer_authentication(peer_id)
