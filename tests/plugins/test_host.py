import pytest
import json
import os
from uuid import uuid4

from aidn_hypervisor.plugins.host import (
    PluginHostAuthenticationError,
    PluginHostAuthenticator,
    PluginHostHandshakeService,
    PluginHostHello,
    PluginHostLocalIpcIngress,
    PluginHostJsonWireAdapter,
    PluginHostIdentity,
)
from aidn_hypervisor.plugins.host_named_pipe import (
    WindowsNamedPipePluginHostClient,
    WindowsNamedPipePluginHostListener,
)
from aidn_hypervisor.plugins.host_unix_socket import UnixSocketPluginHostListener
from aidn_hypervisor.providers.models import InstalledPlugin


def _installed_plugin() -> InstalledPlugin:
    return InstalledPlugin(
        installed_plugin_id="installed-1",
        release_id="release-1",
        plugin_id="aidn.provider.fake",
        plugin_version="1.0.0",
        package_digest="sha256:" + "a" * 64,
        installation_generation=2,
        activation_credential_key_id="sha256:" + "b" * 64,
        installation_source="PACKAGE",
        installed_at="2026-07-19T00:00:00Z",
    )


def test_plugin_host_authenticator_rejects_stale_installation_generation() -> None:
    installed = _installed_plugin()
    identity = PluginHostIdentity(
        installed_plugin_id=installed.installed_plugin_id,
        plugin_id=installed.plugin_id,
        installation_generation=1,
        activation_credential_key_id=installed.activation_credential_key_id,
    )

    with pytest.raises(PluginHostAuthenticationError, match="generation is stale"):
        PluginHostAuthenticator(lambda _: installed).authenticate(identity)


def test_plugin_host_authenticator_accepts_exact_installation_identity() -> None:
    installed = _installed_plugin()
    identity = PluginHostIdentity(
        installed_plugin_id=installed.installed_plugin_id,
        plugin_id=installed.plugin_id,
        installation_generation=installed.installation_generation,
        activation_credential_key_id=installed.activation_credential_key_id,
    )

    assert PluginHostAuthenticator(lambda _: installed).authenticate(identity) == installed


def test_plugin_host_handshake_requires_activation_proof() -> None:
    installed = _installed_plugin()
    hello = PluginHostHello(
        installed_plugin_id=installed.installed_plugin_id,
        plugin_id=installed.plugin_id,
        installation_generation=installed.installation_generation,
        activation_credential_key_id=installed.activation_credential_key_id,
        host_nonce="host-nonce",
        activation_proof="proof",
    )
    handshake = PluginHostHandshakeService(
        authenticator=PluginHostAuthenticator(lambda _: installed),
        activation_proof_verifier=lambda candidate: candidate.activation_proof == "proof",
        now=lambda: "2026-07-19T00:00:00Z",
    )

    connection = handshake.accept(hello)

    assert connection.installed_plugin_id == installed.installed_plugin_id
    assert connection.installation_generation == installed.installation_generation

    with pytest.raises(PluginHostAuthenticationError, match="activation proof"):
        handshake.accept(hello.model_copy(update={"activation_proof": "invalid"}))


def test_plugin_host_local_ipc_ingress_accepts_only_handshake_envelopes() -> None:
    installed = _installed_plugin()
    ingress = PluginHostLocalIpcIngress(
        PluginHostHandshakeService(
            authenticator=PluginHostAuthenticator(lambda _: installed),
            activation_proof_verifier=lambda _: True,
            now=lambda: "2026-07-19T00:00:00Z",
        ),
        manifest_resolver=lambda plugin_id: {"plugin_id": plugin_id, "version": "1.0.0"},
        configuration_validator=lambda plugin_id, configuration: (
            None if plugin_id == installed.plugin_id and configuration == {"base_url": "http://localhost"}
            else (_ for _ in ()).throw(ValueError("unexpected configuration"))
        ),
    )
    event = {
        "installed_plugin_id": installed.installed_plugin_id,
        "plugin_id": installed.plugin_id,
        "installation_generation": installed.installation_generation,
        "activation_credential_key_id": installed.activation_credential_key_id,
        "host_nonce": "nonce",
        "activation_proof": "proof",
    }

    response = ingress.receive({"event_type": "PLUGIN_HOST_HELLO", "event": event})

    assert response["installed_plugin_id"] == installed.installed_plugin_id
    assert ingress.receive(
        {
            "event_type": "PLUGIN_CONTROL",
            "event": {
                "plugin_host_connection_id": response["plugin_host_connection_id"],
                "installed_plugin_id": installed.installed_plugin_id,
                "installation_generation": installed.installation_generation,
                "command": "PING",
            },
        }
    )["status"] == "OK"
    assert ingress.receive(
        {
            "event_type": "PLUGIN_CONTROL",
            "event": {
                "plugin_host_connection_id": response["plugin_host_connection_id"],
                "installed_plugin_id": installed.installed_plugin_id,
                "installation_generation": installed.installation_generation,
                "command": "GET_MANIFEST",
            },
        }
    )["manifest"]["plugin_id"] == installed.plugin_id
    assert ingress.receive(
        {
            "event_type": "PLUGIN_CONTROL",
            "event": {
                "plugin_host_connection_id": response["plugin_host_connection_id"],
                "installed_plugin_id": installed.installed_plugin_id,
                "installation_generation": installed.installation_generation,
                "command": "VALIDATE_CONFIGURATION",
                "configuration": {"base_url": "http://localhost"},
            },
        }
    )["status"] == "OK"
    with pytest.raises(PluginHostAuthenticationError, match="command is not permitted"):
        ingress.receive(
            {
                "event_type": "PLUGIN_CONTROL",
                "event": {
                    "plugin_host_connection_id": response["plugin_host_connection_id"],
                    "installed_plugin_id": installed.installed_plugin_id,
                    "installation_generation": installed.installation_generation,
                    "command": "EXECUTE_ANYTHING",
                },
            }
        )
    with pytest.raises(PluginHostAuthenticationError, match="not permitted"):
        ingress.receive({"event_type": "PLUGIN_EXECUTE", "event": event})


def test_plugin_host_json_wire_adapter_is_bounded_and_fail_closed() -> None:
    installed = _installed_plugin()
    ingress = PluginHostLocalIpcIngress(
        PluginHostHandshakeService(
            authenticator=PluginHostAuthenticator(lambda _: installed),
            activation_proof_verifier=lambda _: True,
            now=lambda: "2026-07-19T00:00:00Z",
        )
    )
    adapter = PluginHostJsonWireAdapter(ingress, maximum_message_bytes=128)

    invalid = json.loads(adapter.receive_bytes(b"not-json"))
    oversized = json.loads(adapter.receive_bytes(b"x" * 129))

    assert invalid["error"] == "PLUGIN_HOST_IPC_INVALID"
    assert oversized == {"ok": False, "error": "MESSAGE_TOO_LARGE"}


def test_windows_named_pipe_plugin_host_routes_hello() -> None:
    installed = _installed_plugin()
    ingress = PluginHostLocalIpcIngress(
        PluginHostHandshakeService(
            authenticator=PluginHostAuthenticator(lambda _: installed),
            activation_proof_verifier=lambda _: True,
            now=lambda: "2026-07-19T00:00:00Z",
        )
    )
    listener = WindowsNamedPipePluginHostListener(
        address=rf"\\.\pipe\aidn-plugin-host-{uuid4().hex}",
        authkey=b"plugin-host-test-key",
        wire_adapter=PluginHostJsonWireAdapter(ingress),
    )
    payload = json.dumps({"event_type": "PLUGIN_HOST_HELLO", "event": {
        "installed_plugin_id": installed.installed_plugin_id, "plugin_id": installed.plugin_id,
        "installation_generation": installed.installation_generation,
        "activation_credential_key_id": installed.activation_credential_key_id,
        "host_nonce": "nonce", "activation_proof": "proof",
    }}).encode()
    listener.start()
    try:
        response = json.loads(WindowsNamedPipePluginHostClient(
            address=listener.address, authkey=b"plugin-host-test-key"
        ).send(payload))
    finally:
        listener.stop()

    assert response["ok"] is True
    assert response["result"]["installed_plugin_id"] == installed.installed_plugin_id


def test_unix_socket_plugin_host_rejects_windows() -> None:
    if os.name != "nt":
        pytest.skip("Windows-specific guard")
    with pytest.raises(RuntimeError, match="unavailable on Windows"):
        UnixSocketPluginHostListener(address="/tmp/aidn-plugin.sock", wire_adapter=None)
