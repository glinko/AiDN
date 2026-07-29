import json
import os
from uuid import uuid4

import pytest

from aidn_hypervisor.plugins.host import (
    HmacPluginHostActivationProofVerifier,
    PluginHostActivationCredentialStore,
    PluginHostAuthenticationError,
    PluginHostAuthenticator,
    PluginHostConnection,
    PluginHostConnectionStore,
    PluginHostHandshakeService,
    PluginHostHello,
    PluginHostIdentity,
    PluginHostJsonWireAdapter,
    PluginHostLocalIpcIngress,
    build_plugin_host_activation_proof,
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


def test_plugin_host_connection_store_removes_only_one_plugin_installation() -> None:
    store = PluginHostConnectionStore()
    connection = PluginHostConnection(
        plugin_host_connection_id="phc-revoked",
        installed_plugin_id="installed-revoked",
        plugin_id="aidn.provider.fake",
        installation_generation=1,
        activation_credential_key_id="credential-revoked",
        established_at="2026-07-28T00:00:00Z",
    )
    other_connection = connection.model_copy(
        update={
            "plugin_host_connection_id": "phc-active",
            "installed_plugin_id": "installed-active",
        }
    )
    store.save(connection)
    store.save(other_connection)

    assert store.remove_for_installed_plugin("installed-revoked") == 1
    assert store.get("phc-revoked") is None
    assert store.get("phc-active") == other_connection


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


def test_hmac_activation_proof_binds_identity_and_rejects_nonce_replay() -> None:
    installed = _installed_plugin()
    identity = PluginHostIdentity(
        installed_plugin_id=installed.installed_plugin_id,
        plugin_id=installed.plugin_id,
        installation_generation=installed.installation_generation,
        activation_credential_key_id=installed.activation_credential_key_id,
    )
    activation_secret = b"hmac-activation-secret"
    credentials = PluginHostActivationCredentialStore()
    credentials.save(
        credential_key_id=identity.activation_credential_key_id,
        activation_secret=activation_secret,
    )
    hello = PluginHostHello(
        **identity.model_dump(),
        host_nonce="host-nonce",
        activation_proof=build_plugin_host_activation_proof(
            activation_secret=activation_secret,
            identity=identity,
            host_nonce="host-nonce",
        ),
    )
    handshake = PluginHostHandshakeService(
        authenticator=PluginHostAuthenticator(lambda _: installed),
        activation_proof_verifier=HmacPluginHostActivationProofVerifier(credentials.get),
        now=lambda: "2026-07-19T00:00:00Z",
    )

    assert handshake.accept(hello).installed_plugin_id == installed.installed_plugin_id
    with pytest.raises(PluginHostAuthenticationError, match="nonce was already used"):
        handshake.accept(hello)
    with pytest.raises(PluginHostAuthenticationError, match="activation proof"):
        handshake.accept(hello.model_copy(update={"host_nonce": "different-nonce"}))


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
            None
            if plugin_id == installed.plugin_id and configuration == {"base_url": "http://localhost"}
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
    assert (
        ingress.receive(
            {
                "event_type": "PLUGIN_CONTROL",
                "event": {
                    "plugin_host_connection_id": response["plugin_host_connection_id"],
                    "installed_plugin_id": installed.installed_plugin_id,
                    "installation_generation": installed.installation_generation,
                    "command": "PING",
                },
            }
        )["status"]
        == "OK"
    )
    assert (
        ingress.receive(
            {
                "event_type": "PLUGIN_CONTROL",
                "event": {
                    "plugin_host_connection_id": response["plugin_host_connection_id"],
                    "installed_plugin_id": installed.installed_plugin_id,
                    "installation_generation": installed.installation_generation,
                    "command": "GET_MANIFEST",
                },
            }
        )["manifest"]["plugin_id"]
        == installed.plugin_id
    )
    assert (
        ingress.receive(
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
        )["status"]
        == "OK"
    )
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


def test_plugin_host_control_connection_is_revoked_after_generation_change() -> None:
    installed = _installed_plugin()
    current = {"plugin": installed}
    ingress = PluginHostLocalIpcIngress(
        PluginHostHandshakeService(
            authenticator=PluginHostAuthenticator(lambda _: current["plugin"]),
            activation_proof_verifier=lambda _: True,
            now=lambda: "2026-07-19T00:00:00Z",
        )
    )
    event = {
        "installed_plugin_id": installed.installed_plugin_id,
        "plugin_id": installed.plugin_id,
        "installation_generation": installed.installation_generation,
        "activation_credential_key_id": installed.activation_credential_key_id,
        "host_nonce": "nonce",
        "activation_proof": "proof",
    }
    connection = ingress.receive({"event_type": "PLUGIN_HOST_HELLO", "event": event})
    current["plugin"] = installed.model_copy(update={"installation_generation": 3})

    with pytest.raises(PluginHostAuthenticationError, match="generation is stale"):
        ingress.receive(
            {
                "event_type": "PLUGIN_CONTROL",
                "event": {
                    "plugin_host_connection_id": connection["plugin_host_connection_id"],
                    "installed_plugin_id": installed.installed_plugin_id,
                    "installation_generation": installed.installation_generation,
                    "command": "PING",
                },
            }
        )


def test_plugin_host_connection_store_restores_snapshot() -> None:
    installed = _installed_plugin()
    ingress = PluginHostLocalIpcIngress(
        PluginHostHandshakeService(
            authenticator=PluginHostAuthenticator(lambda _: installed),
            activation_proof_verifier=lambda _: True,
            now=lambda: "2026-07-19T00:00:00Z",
        )
    )
    connection = ingress.receive(
        {
            "event_type": "PLUGIN_HOST_HELLO",
            "event": {
                "installed_plugin_id": installed.installed_plugin_id,
                "plugin_id": installed.plugin_id,
                "installation_generation": installed.installation_generation,
                "activation_credential_key_id": installed.activation_credential_key_id,
                "host_nonce": "nonce",
                "activation_proof": "proof",
            },
        }
    )
    restored = PluginHostConnectionStore(ingress.connection_store.snapshot())

    assert restored.get(connection["plugin_host_connection_id"]).plugin_id == installed.plugin_id


def test_plugin_host_disconnect_revokes_connection() -> None:
    installed = _installed_plugin()
    ingress = PluginHostLocalIpcIngress(
        PluginHostHandshakeService(
            authenticator=PluginHostAuthenticator(lambda _: installed),
            activation_proof_verifier=lambda _: True,
            now=lambda: "2026-07-19T00:00:00Z",
        )
    )
    connection = ingress.receive(
        {
            "event_type": "PLUGIN_HOST_HELLO",
            "event": {
                "installed_plugin_id": installed.installed_plugin_id,
                "plugin_id": installed.plugin_id,
                "installation_generation": installed.installation_generation,
                "activation_credential_key_id": installed.activation_credential_key_id,
                "host_nonce": "nonce",
                "activation_proof": "proof",
            },
        }
    )
    control = {
        "plugin_host_connection_id": connection["plugin_host_connection_id"],
        "installed_plugin_id": installed.installed_plugin_id,
        "installation_generation": installed.installation_generation,
    }
    assert (
        ingress.receive({"event_type": "PLUGIN_CONTROL", "event": {**control, "command": "DISCONNECT"}})["status"]
        == "OK"
    )
    with pytest.raises(PluginHostAuthenticationError, match="not known"):
        ingress.receive({"event_type": "PLUGIN_CONTROL", "event": {**control, "command": "PING"}})


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


@pytest.mark.skipif(os.name != "nt", reason="Windows Named Pipe transport only")
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
    payload = json.dumps(
        {
            "event_type": "PLUGIN_HOST_HELLO",
            "event": {
                "installed_plugin_id": installed.installed_plugin_id,
                "plugin_id": installed.plugin_id,
                "installation_generation": installed.installation_generation,
                "activation_credential_key_id": installed.activation_credential_key_id,
                "host_nonce": "nonce",
                "activation_proof": "proof",
            },
        }
    ).encode()
    listener.start()
    try:
        response = json.loads(
            WindowsNamedPipePluginHostClient(address=listener.address, authkey=b"plugin-host-test-key").send(payload)
        )
    finally:
        listener.stop()

    assert response["ok"] is True
    assert response["result"]["installed_plugin_id"] == installed.installed_plugin_id


def test_unix_socket_plugin_host_rejects_windows() -> None:
    if os.name != "nt":
        pytest.skip("Windows-specific guard")
    with pytest.raises(RuntimeError, match="unavailable on Windows"):
        UnixSocketPluginHostListener(address="/tmp/aidn-plugin.sock", wire_adapter=None)
