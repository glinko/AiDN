"""Install-scoped identity checks for a future isolated Provider Plugin Host."""

from collections.abc import Callable
from uuid import uuid4

from pydantic import BaseModel, Field

from aidn_hypervisor.providers.models import InstalledPlugin


class PluginHostAuthenticationError(ValueError):
    """Raised when a Plugin Host identity is no longer authorized locally."""


class PluginHostIdentity(BaseModel):
    installed_plugin_id: str = Field(min_length=1)
    plugin_id: str = Field(min_length=1)
    installation_generation: int = Field(ge=1)
    activation_credential_key_id: str = Field(min_length=1)


class PluginHostHello(PluginHostIdentity):
    host_nonce: str = Field(min_length=1)
    activation_proof: str = Field(min_length=1)


class PluginHostConnection(BaseModel):
    plugin_host_connection_id: str = Field(min_length=1)
    installed_plugin_id: str = Field(min_length=1)
    plugin_id: str = Field(min_length=1)
    installation_generation: int = Field(ge=1)
    established_at: str = Field(min_length=1)


class PluginHostAuthenticator:
    """Authorize one Host identity against immutable installed-plugin state."""

    def __init__(self, installed_plugin_resolver: Callable[[str], InstalledPlugin]) -> None:
        self.installed_plugin_resolver = installed_plugin_resolver

    def authenticate(self, identity: PluginHostIdentity) -> InstalledPlugin:
        try:
            installed = self.installed_plugin_resolver(identity.installed_plugin_id)
        except KeyError as exc:
            raise PluginHostAuthenticationError("installed plugin is not known") from exc
        if installed.state not in {"INSTALLED", "ACTIVE"}:
            raise PluginHostAuthenticationError("installed plugin is not host-authorized")
        if installed.plugin_id != identity.plugin_id:
            raise PluginHostAuthenticationError("Plugin Host plugin identity does not match installation")
        if installed.installation_generation != identity.installation_generation:
            raise PluginHostAuthenticationError("Plugin Host installation generation is stale")
        if installed.activation_credential_key_id != identity.activation_credential_key_id:
            raise PluginHostAuthenticationError("Plugin Host activation credential is invalid")
        return installed


class PluginHostHandshakeService:
    """Transport-neutral local IPC admission for one isolated Plugin Host."""

    def __init__(
        self,
        *,
        authenticator: PluginHostAuthenticator,
        activation_proof_verifier: Callable[[PluginHostHello], bool],
        now: Callable[[], str],
    ) -> None:
        self.authenticator = authenticator
        self.activation_proof_verifier = activation_proof_verifier
        self.now = now

    def accept(self, hello: PluginHostHello) -> PluginHostConnection:
        installed = self.authenticator.authenticate(hello)
        if not self.activation_proof_verifier(hello):
            raise PluginHostAuthenticationError("Plugin Host activation proof is invalid")
        return PluginHostConnection(
            plugin_host_connection_id=f"phc-{uuid4().hex}",
            installed_plugin_id=installed.installed_plugin_id,
            plugin_id=installed.plugin_id,
            installation_generation=installed.installation_generation,
            established_at=self.now(),
        )


class PluginHostLocalIpcIngress:
    """Strict control-envelope ingress shared by Plugin Host local transports."""

    def __init__(self, handshake_service: PluginHostHandshakeService) -> None:
        self.handshake_service = handshake_service

    def receive(self, envelope: dict) -> dict:
        if envelope.get("event_type") != "PLUGIN_HOST_HELLO":
            raise PluginHostAuthenticationError("Plugin Host event type is not permitted")
        hello = PluginHostHello.model_validate(envelope.get("event"))
        return self.handshake_service.accept(hello).model_dump(mode="json")
