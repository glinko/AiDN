from collections.abc import Callable

import pytest

from aidn_hypervisor.registry.reconnect import RegistryReplicationReconnectSupervisor


class _Session:
    def __init__(self, *, reconnect_error: Exception | None = None) -> None:
        self.authenticated = False
        self.reconnect_error = reconnect_error
        self.reconnect_count = 0
        self.disconnect_count = 0
        self.handshakes: list[tuple[str, str]] = []
        self.incoming: list[dict | None] = []
        self.transport_connected = True

    @property
    def is_authenticated(self) -> bool:
        return self.authenticated

    @property
    def is_transport_connected(self) -> bool:
        return self.transport_connected

    def reconnect(self) -> None:
        self.reconnect_count += 1
        if self.reconnect_error is not None:
            raise self.reconnect_error

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
        self.handshakes.append((local_public_key, signer(b"registry-handshake")))
        return object()

    def receive_once(self) -> dict | None:
        result = self.incoming.pop(0) if self.incoming else None
        if result == {"event": "peer_handshake", "authenticated": True}:
            self.authenticated = True
        return result

    def flush_outbox(self) -> int:
        return 0


def test_reconnect_supervisor_uses_bounded_backoff_and_handshake_timeout() -> None:
    now = [0.0]
    session = _Session(reconnect_error=ConnectionError("network down"))
    supervisor = RegistryReplicationReconnectSupervisor(
        sessions={"peer-b": session},
        local_public_key="ed25519:local",
        signer=lambda _: "ed25519:signature",
        initial_backoff_seconds=2,
        maximum_backoff_seconds=8,
        handshake_timeout_seconds=3,
        clock=lambda: now[0],
    )

    assert supervisor.tick() == ["peer-b"]
    assert supervisor.status()[0]["next_attempt_at"] == 2
    now[0] = 1
    assert supervisor.tick() == []

    now[0] = 2
    session.reconnect_error = None
    assert supervisor.tick() == ["peer-b"]
    assert supervisor.status()[0]["handshake_pending"] is True

    now[0] = 5
    assert supervisor.tick() == []
    state = supervisor.status()[0]
    assert session.disconnect_count == 1
    assert state["failure_count"] == 2
    assert state["next_attempt_at"] == 9
    assert state["last_error"] == "handshake_timeout"


def test_reconnect_supervisor_resets_only_after_authenticated_handshake() -> None:
    now = [0.0]
    session = _Session()
    supervisor = RegistryReplicationReconnectSupervisor(
        sessions={"peer-b": session},
        local_public_key="ed25519:local",
        signer=lambda _: "ed25519:signature",
        clock=lambda: now[0],
    )

    assert supervisor.tick() == ["peer-b"]
    assert session.handshakes == [("ed25519:local", "ed25519:signature")]
    session.incoming.append({"event": "peer_handshake", "authenticated": True})

    assert supervisor.receive_once(peer_id="peer-b") == {
        "event": "peer_handshake",
        "authenticated": True,
    }
    assert supervisor.status() == [
        {
            "peer_id": "peer-b",
            "authenticated": True,
            "handshake_pending": False,
            "failure_count": 0,
            "next_attempt_at": 0.0,
            "last_error": None,
        }
    ]


def test_reconnect_supervisor_preserves_receive_failure_for_backoff() -> None:
    now = [10.0]

    class _FailingSession(_Session):
        def receive_once(self) -> dict | None:
            raise PermissionError("bad peer frame")

    session = _FailingSession()
    supervisor = RegistryReplicationReconnectSupervisor(
        sessions={"peer-b": session},
        local_public_key="ed25519:local",
        signer=lambda _: "ed25519:signature",
        initial_backoff_seconds=4,
        clock=lambda: now[0],
    )

    with pytest.raises(PermissionError, match="bad peer frame"):
        supervisor.receive_once(peer_id="peer-b")
    assert session.disconnect_count == 1
    assert supervisor.status()[0]["next_attempt_at"] == 14


def test_reconnect_supervisor_flushes_only_authenticated_peers() -> None:
    class _FlushingSession(_Session):
        def flush_outbox(self) -> int:
            return 3

    authenticated = _FlushingSession()
    authenticated.authenticated = True
    pending = _FlushingSession()
    supervisor = RegistryReplicationReconnectSupervisor(
        sessions={"peer-a": authenticated, "peer-b": pending},
        local_public_key="ed25519:local",
        signer=lambda _: "ed25519:signature",
    )

    assert supervisor.flush_authenticated_outboxes() == {"peer-a": 3}
    supervisor.disconnect_all()
    assert authenticated.disconnect_count == 1
    assert pending.disconnect_count == 1


def test_reconnect_supervisor_retries_when_transport_closes_without_a_frame() -> None:
    now = [10.0]
    session = _Session()
    session.authenticated = True
    session.transport_connected = False
    supervisor = RegistryReplicationReconnectSupervisor(
        sessions={"peer-b": session},
        local_public_key="ed25519:local",
        signer=lambda _: "ed25519:signature",
        initial_backoff_seconds=4,
        clock=lambda: now[0],
    )

    assert supervisor.receive_once(peer_id="peer-b") is None
    assert session.disconnect_count == 1
    assert supervisor.status()[0]["last_error"] == "transport_closed"
    assert supervisor.status()[0]["next_attempt_at"] == 14
