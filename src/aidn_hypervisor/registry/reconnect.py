"""Bounded reconnect supervision for authenticated Registry replication links."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


class _ReplicationSession(Protocol):
    @property
    def is_authenticated(self) -> bool: ...

    def reconnect(self) -> None: ...

    def disconnect(self) -> None: ...

    def send_handshake(
        self,
        *,
        local_public_key: str,
        signer: Callable[[bytes], str],
    ) -> object: ...

    def receive_once(self) -> dict | None: ...


@dataclass
class RegistryReplicationReconnectState:
    peer_id: str
    failure_count: int = 0
    next_attempt_at: float = 0.0
    handshake_sent_at: float | None = None
    last_error: str | None = None

    @property
    def handshake_pending(self) -> bool:
        return self.handshake_sent_at is not None


class RegistryReplicationReconnectSupervisor:
    """Reconnect approved outbound peers without bypassing their handshake gate."""

    def __init__(
        self,
        *,
        sessions: dict[str, _ReplicationSession],
        local_public_key: str,
        signer: Callable[[bytes], str],
        initial_backoff_seconds: float = 1.0,
        maximum_backoff_seconds: float = 60.0,
        handshake_timeout_seconds: float = 15.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not local_public_key:
            raise ValueError("Registry replication local public key is required")
        if initial_backoff_seconds <= 0 or maximum_backoff_seconds < initial_backoff_seconds:
            raise ValueError("Registry replication backoff bounds are invalid")
        if handshake_timeout_seconds <= 0:
            raise ValueError("Registry replication handshake timeout must be positive")
        self._sessions = dict(sessions)
        self._local_public_key = local_public_key
        self._signer = signer
        self._initial_backoff_seconds = initial_backoff_seconds
        self._maximum_backoff_seconds = maximum_backoff_seconds
        self._handshake_timeout_seconds = handshake_timeout_seconds
        self._clock = clock
        self._states = {
            peer_id: RegistryReplicationReconnectState(peer_id=peer_id)
            for peer_id in sessions
        }

    def tick(self) -> list[str]:
        """Start due reconnects and expire incomplete handshakes without blocking."""
        attempted: list[str] = []
        now = self._clock()
        for peer_id in sorted(self._sessions):
            session = self._sessions[peer_id]
            state = self._states[peer_id]
            if session.is_authenticated:
                self._mark_authenticated(state)
                continue
            if state.handshake_sent_at is not None:
                if now - state.handshake_sent_at >= self._handshake_timeout_seconds:
                    session.disconnect()
                    self._record_failure(state, now, "handshake_timeout")
                continue
            if now < state.next_attempt_at:
                continue
            attempted.append(peer_id)
            try:
                session.reconnect()
                session.send_handshake(
                    local_public_key=self._local_public_key,
                    signer=self._signer,
                )
                state.handshake_sent_at = now
                state.last_error = None
            except (ConnectionError, OSError, ValueError) as exc:
                self._record_failure(state, now, str(exc))
        return attempted

    def receive_once(self, *, peer_id: str) -> dict | None:
        """Process a caller-delivered inbound frame and update reconnect state."""
        session = self._sessions[peer_id]
        state = self._states[peer_id]
        now = self._clock()
        try:
            result = session.receive_once()
        except (ConnectionError, OSError, PermissionError, ValueError) as exc:
            session.disconnect()
            self._record_failure(state, now, str(exc))
            raise
        if session.is_authenticated:
            self._mark_authenticated(state)
        return result

    def status(self) -> list[dict]:
        return [
            {
                "peer_id": state.peer_id,
                "authenticated": self._sessions[state.peer_id].is_authenticated,
                "handshake_pending": state.handshake_pending,
                "failure_count": state.failure_count,
                "next_attempt_at": state.next_attempt_at,
                "last_error": state.last_error,
            }
            for state in sorted(self._states.values(), key=lambda item: item.peer_id)
        ]

    def _mark_authenticated(self, state: RegistryReplicationReconnectState) -> None:
        state.failure_count = 0
        state.next_attempt_at = 0.0
        state.handshake_sent_at = None
        state.last_error = None

    def _record_failure(
        self,
        state: RegistryReplicationReconnectState,
        now: float,
        error: str,
    ) -> None:
        state.failure_count += 1
        delay = min(
            self._initial_backoff_seconds * (2 ** (state.failure_count - 1)),
            self._maximum_backoff_seconds,
        )
        state.next_attempt_at = now + delay
        state.handshake_sent_at = None
        state.last_error = error
