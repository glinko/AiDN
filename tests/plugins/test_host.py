import pytest

from aidn_hypervisor.plugins.host import (
    PluginHostAuthenticationError,
    PluginHostAuthenticator,
    PluginHostHandshakeService,
    PluginHostHello,
    PluginHostLocalIpcIngress,
    PluginHostIdentity,
)
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

    response = ingress.receive({"event_type": "PLUGIN_HOST_HELLO", "event": event})

    assert response["installed_plugin_id"] == installed.installed_plugin_id
    with pytest.raises(PluginHostAuthenticationError, match="not permitted"):
        ingress.receive({"event_type": "PLUGIN_EXECUTE", "event": event})
