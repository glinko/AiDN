"""Install-scoped identity checks for a future isolated Provider Plugin Host."""

from collections.abc import Callable
import hashlib
import hmac
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


def build_plugin_host_activation_proof(
    *,
    activation_secret: bytes,
    identity: PluginHostIdentity,
    host_nonce: str,
) -> str:
    """Create the local Host proof without exposing its activation secret."""
    payload = json.dumps(
        {
            "activation_credential_key_id": identity.activation_credential_key_id,
            "host_nonce": host_nonce,
            "installation_generation": identity.installation_generation,
            "installed_plugin_id": identity.installed_plugin_id,
            "plugin_id": identity.plugin_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hmac.new(activation_secret, payload, hashlib.sha256).hexdigest()


class PluginHostActivationCredentialStore:
    """Ephemeral activation secrets for locally launched Plugin Hosts."""

    def __init__(self) -> None:
        self._secrets: dict[str, bytes] = {}

    def save(self, *, credential_key_id: str, activation_secret: bytes) -> None:
        if not credential_key_id:
            raise ValueError("Plugin Host credential key ID is required")
        if not activation_secret:
            raise ValueError("Plugin Host activation secret is required")
        self._secrets[credential_key_id] = activation_secret

    def get(self, credential_key_id: str) -> bytes | None:
        return self._secrets.get(credential_key_id)

    def remove(self, credential_key_id: str) -> None:
        self._secrets.pop(credential_key_id, None)


class HmacPluginHostActivationProofVerifier:
    """Verify that a Host possesses its install-scoped activation secret."""

    def __init__(self, secret_resolver: Callable[[str], bytes | None]) -> None:
        self.secret_resolver = secret_resolver

    def __call__(self, hello: PluginHostHello) -> bool:
        activation_secret = self.secret_resolver(hello.activation_credential_key_id)
        if activation_secret is None:
            return False
        expected = build_plugin_host_activation_proof(
            activation_secret=activation_secret,
            identity=PluginHostIdentity.model_validate(hello.model_dump()),
            host_nonce=hello.host_nonce,
        )
        return hmac.compare_digest(expected, hello.activation_proof)


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
    display_name: str | None = None
    provider_instance_id: str | None = None
    model_deployment_id: str | None = None
    capability_id: str | None = None
    capability_version: str | None = None
    capability_definition_hash: str | None = None
    runtime_binding_id: str | None = None


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
        self._used_nonces: set[tuple[str, int, str]] = set()

    def accept(self, hello: PluginHostHello) -> PluginHostConnection:
        installed = self.authenticator.authenticate(hello)
        if not self.activation_proof_verifier(hello):
            raise PluginHostAuthenticationError("Plugin Host activation proof is invalid")
        nonce_key = (
            installed.installed_plugin_id,
            installed.installation_generation,
            hello.host_nonce,
        )
        if nonce_key in self._used_nonces:
            raise PluginHostAuthenticationError("Plugin Host activation nonce was already used")
        self._used_nonces.add(nonce_key)
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
        attach_existing_provider: Callable[[str, str, dict], dict] | None = None,
        model_discoverer: Callable[[str, str], list[dict]] | None = None,
        runtime_binding_creator: Callable[[str, str, str, str, str], dict] | None = None,
        runtime_binding_admission: Callable[[str, str], dict] | None = None,
        connection_store: PluginHostConnectionStore | None = None,
    ) -> None:
        self.handshake_service = handshake_service
        self.manifest_resolver = manifest_resolver
        self.configuration_validator = configuration_validator
        self.installation_plan_builder = installation_plan_builder
        self.attach_existing_provider = attach_existing_provider
        self.model_discoverer = model_discoverer
        self.runtime_binding_creator = runtime_binding_creator
        self.runtime_binding_admission = runtime_binding_admission
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
            if command.command == "ATTACH_EXISTING_PROVIDER":
                if self.attach_existing_provider is None:
                    raise PluginHostAuthenticationError("Plugin Host provider attach is not configured")
                if command.configuration is None or not command.display_name:
                    raise PluginHostAuthenticationError("Plugin Host attach configuration and display name are required")
                return {
                    "status": "OK", "command": "ATTACH_EXISTING_PROVIDER",
                    "plugin_host_connection_id": connection.plugin_host_connection_id,
                    "provider_instance": self.attach_existing_provider(
                        connection.plugin_id, command.display_name, command.configuration
                    ),
                }
            if command.command == "DISCOVER_MODELS":
                if self.model_discoverer is None:
                    raise PluginHostAuthenticationError("Plugin Host model discovery is not configured")
                if not command.provider_instance_id:
                    raise PluginHostAuthenticationError("Plugin Host provider instance is required")
                return {
                    "status": "OK", "command": "DISCOVER_MODELS",
                    "plugin_host_connection_id": connection.plugin_host_connection_id,
                    "model_deployments": self.model_discoverer(
                        connection.plugin_id, command.provider_instance_id
                    ),
                }
            if command.command == "CREATE_RUNTIME_BINDING":
                fields = (command.model_deployment_id, command.capability_id, command.capability_version, command.capability_definition_hash)
                if self.runtime_binding_creator is None or not all(fields):
                    raise PluginHostAuthenticationError("Plugin Host Runtime Binding parameters are required")
                return {"status": "OK", "command": "CREATE_RUNTIME_BINDING",
                    "plugin_host_connection_id": connection.plugin_host_connection_id,
                    "runtime_binding": self.runtime_binding_creator(connection.plugin_id, *fields)}
            if command.command == "GET_RUNTIME_BINDING_ADMISSION":
                if self.runtime_binding_admission is None or not command.runtime_binding_id:
                    raise PluginHostAuthenticationError("Plugin Host Runtime Binding ID is required")
                return {"status": "OK", "command": "GET_RUNTIME_BINDING_ADMISSION",
                    "plugin_host_connection_id": connection.plugin_host_connection_id,
                    "admission": self.runtime_binding_admission(connection.plugin_id, command.runtime_binding_id)}
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
