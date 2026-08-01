from __future__ import annotations

import time
from collections.abc import Callable

from aidn_hypervisor.registry.reconnect import RegistryReplicationReconnectSupervisor
from aidn_hypervisor.registry.replicator import RegistryReplicator
from aidn_hypervisor.registry.runtime import RegistryReplicationRuntime


class _Session:
    def __init__(self) -> None:
        self.authenticated = False
        self.reconnect_count = 0
        self.disconnect_count = 0
        self.flush_count = 0
        self._handshake_received = False
        self.transport_connected = True

    @property
    def is_authenticated(self) -> bool:
        return self.authenticated

    @property
    def is_transport_connected(self) -> bool:
        return self.transport_connected

    def reconnect(self) -> None:
        self.reconnect_count += 1

    def disconnect(self) -> None:
        self.disconnect_count += 1
        self.authenticated = False
        self.transport_connected = False

    def send_handshake(
        self,
        *,
        local_public_key: str,
        signer: Callable[[bytes], str],
    ) -> object:
        assert local_public_key == "ed25519:local"
        assert signer(b"registry-handshake") == "ed25519:signature"
        return object()

    def receive_once(self) -> dict | None:
        if not self._handshake_received:
            self._handshake_received = True
            self.authenticated = True
            return {"event": "peer_handshake", "authenticated": True}
        return None

    def flush_outbox(self) -> int:
        self.flush_count += 1
        return 0


def _wait_until(predicate, *, timeout_seconds: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def test_runtime_reconnects_flushes_and_stops_outbound_peer() -> None:
    session = _Session()
    supervisor = RegistryReplicationReconnectSupervisor(
        sessions={"registry-b": session},
        local_public_key="ed25519:local",
        signer=lambda _: "ed25519:signature",
    )
    runtime = RegistryReplicationRuntime(
        reconnect_supervisor=supervisor,
        poll_interval_seconds=0.01,
    )

    runtime.start()
    _wait_until(lambda: session.authenticated and session.flush_count > 0)

    assert runtime.is_running is True
    assert runtime.status()["outbound_peers"][0]["authenticated"] is True
    assert runtime.status()["replication_peers"] == []

    runtime.stop()

    assert runtime.is_running is False
    assert session.reconnect_count == 1
    assert session.disconnect_count >= 1


def test_runtime_status_exposes_sanitized_replication_peer_state() -> None:
    session = _Session()
    supervisor = RegistryReplicationReconnectSupervisor(
        sessions={"registry-b": session},
        local_public_key="ed25519:local",
        signer=lambda _: "ed25519:signature",
    )
    replicator = RegistryReplicator(node_id="registry-local")
    replicator.on_peer_connected("registry-b")
    runtime = RegistryReplicationRuntime(
        reconnect_supervisor=supervisor,
        replicator=replicator,
        poll_interval_seconds=0.01,
    )

    state = runtime.status()["replication_peers"]
    assert len(state) == 1
    assert state[0]["peer_id"] == "registry-b"
    assert state[0]["connected"] is True
    assert state[0]["inventory_exchanged"] is False
    assert state[0]["last_activity_at"] > 0


def test_runtime_starts_inventory_exchange_after_outbound_authentication() -> None:
    session = _Session()
    supervisor = RegistryReplicationReconnectSupervisor(
        sessions={"registry-b": session},
        local_public_key="ed25519:local",
        signer=lambda _: "ed25519:signature",
    )
    replicator = RegistryReplicator(node_id="registry-local")
    runtime = RegistryReplicationRuntime(
        reconnect_supervisor=supervisor,
        replicator=replicator,
        poll_interval_seconds=0.01,
    )

    runtime.start()
    try:
        _wait_until(
            lambda: any(
                message["message_type"] == "registry_inventory_request"
                for message in replicator.get_outbox()
            )
        )
    finally:
        runtime.stop()
