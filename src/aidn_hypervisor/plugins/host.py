"""Install-scoped identity checks for a future isolated Provider Plugin Host."""

from collections.abc import Callable
import json
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
    activation_credential_key_id: str = Field(min_length=1)
    established_at: str = Field(min_length=1)


class PluginHostConnectionStore:
    """Snapshot-capable local state for authenticated Plugin Host connections."""

    def __init__(self, connections: list[dict] | None = None) -> None:
        self._connections = {
            item["plugin_host_connection_id"]: PluginHostConnection.model_validate(item)
            for item in (connections or [])
        }

    def save(self, connection: PluginHostConnection) -> None:
        self._connections[connection.plugin_host_connection_id] = connection

    def get(self, connection_id: str) -> PluginHostConnection | None:
        return self._connections.get(connection_id)

    def remove(self, connection_id: str) -> None:
        self._connections.pop(connection_id, None)

    def snapshot(self) -> list[dict]:
        return [item.model_dump(mode="json") for item in self._connections.values()]


class PluginHostControlCommand(BaseModel):
    plugin_host_connection_id: str = Field(min_length=1)
    installed_plugin_id: str = Field(min_length=1)
    installation_generation: int = Field(ge=1)
    command: str = Field(min_length=1)
    configuration: dict | None = None


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
            activation_credential_key_id=hello.activation_credential_key_id,
            established_at=self.now(),
        )


class PluginHostLocalIpcIngress:
    """Strict control-envelope ingress shared by Plugin Host local transports."""

    def __init__(
        self,
        handshake_service: PluginHostHandshakeService,
        *,
        manifest_resolver: Callable[[str], dict] | None = None,
        configuration_validator: Callable[[str, dict], None] | None = None,
        installation_plan_builder: Callable[[str, dict], dict] | None = None,
        connection_store: PluginHostConnectionStore | None = None,
    ) -> None:
        self.handshake_service = handshake_service
        self.manifest_resolver = manifest_resolver
        self.configuration_validator = configuration_validator
        self.installation_plan_builder = installation_plan_builder
        self.connection_store = connection_store or PluginHostConnectionStore()

    def receive(self, envelope: dict) -> dict:
        event_type = envelope.get("event_type")
        if event_type == "PLUGIN_HOST_HELLO":
            hello = PluginHostHello.model_validate(envelope.get("event"))
            connection = self.handshake_service.accept(hello)
            self.connection_store.save(connection)
            return connection.model_dump(mode="json")
        if event_type == "PLUGIN_CONTROL":
            command = PluginHostControlCommand.model_validate(envelope.get("event"))
            return self._receive_control(command)
        raise PluginHostAuthenticationError("Plugin Host event type is not permitted")

    def _receive_control(self, command: PluginHostControlCommand) -> dict:
        connection = self.connection_store.get(command.plugin_host_connection_id)
        if connection is None:
            raise PluginHostAuthenticationError("Plugin Host connection is not known")
        if (
            connection.installed_plugin_id != command.installed_plugin_id
            or connection.installation_generation != command.installation_generation
        ):
            raise PluginHostAuthenticationError("Plugin Host control identity does not match connection")
        self.handshake_service.authenticator.authenticate(
            PluginHostIdentity(
                installed_plugin_id=connection.installed_plugin_id,
                plugin_id=connection.plugin_id,
                installation_generation=connection.installation_generation,
                activation_credential_key_id=connection.activation_credential_key_id,
            )
        )
        if command.command == "DISCONNECT":
            self.connection_store.remove(connection.plugin_host_connection_id)
            return {
                "status": "OK",
                "command": "DISCONNECT",
                "plugin_host_connection_id": connection.plugin_host_connection_id,
            }
        if command.command != "PING":
            if command.command == "GET_MANIFEST":
                if self.manifest_resolver is None:
                    raise PluginHostAuthenticationError("Plugin Host manifest access is not configured")
                return {
                    "status": "OK",
                    "command": "GET_MANIFEST",
                    "plugin_host_connection_id": connection.plugin_host_connection_id,
                    "manifest": self.manifest_resolver(connection.plugin_id),
                }
            if command.command == "VALIDATE_CONFIGURATION":
                if self.configuration_validator is None:
                    raise PluginHostAuthenticationError("Plugin Host configuration validation is not configured")
                if command.configuration is None:
                    raise PluginHostAuthenticationError("Plugin Host configuration is required")
                self.configuration_validator(connection.plugin_id, command.configuration)
                return {
                    "status": "OK",
                    "command": "VALIDATE_CONFIGURATION",
                    "plugin_host_connection_id": connection.plugin_host_connection_id,
                }
            if command.command == "BUILD_INSTALLATION_PLAN":
                if self.installation_plan_builder is None:
                    raise PluginHostAuthenticationError("Plugin Host installation planning is not configured")
                if command.configuration is None:
                    raise PluginHostAuthenticationError("Plugin Host configuration is required")
                return {
                    "status": "OK",
                    "command": "BUILD_INSTALLATION_PLAN",
                    "plugin_host_connection_id": connection.plugin_host_connection_id,
                    "installation_plan": self.installation_plan_builder(
                        connection.plugin_id, command.configuration
                    ),
                }
            raise PluginHostAuthenticationError("Plugin Host control command is not permitted")
        return {
            "status": "OK",
            "command": "PING",
            "plugin_host_connection_id": connection.plugin_host_connection_id,
        }


class PluginHostJsonWireAdapter:
    """Bounded JSON adapter for Plugin Host local transports."""

    def __init__(self, ingress: PluginHostLocalIpcIngress, *, maximum_message_bytes: int = 1_048_576) -> None:
        if maximum_message_bytes <= 0:
            raise ValueError("maximum_message_bytes must be positive")
        self.ingress = ingress
        self.maximum_message_bytes = maximum_message_bytes

    def receive_bytes(self, payload: bytes) -> bytes:
        if len(payload) > self.maximum_message_bytes:
            return self._response(False, error="MESSAGE_TOO_LARGE")
        try:
            envelope = json.loads(payload.decode("utf-8"))
            if not isinstance(envelope, dict):
                raise ValueError("Plugin Host envelope must be an object")
            result = self.ingress.receive(envelope)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            return self._response(False, error="PLUGIN_HOST_IPC_INVALID", message=str(exc))
        return self._response(True, result=result)

    @staticmethod
    def _response(ok: bool, **payload: object) -> bytes:
        return json.dumps({"ok": ok, **payload}, separators=(",", ":")).encode("utf-8")
