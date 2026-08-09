"""Short-lived browser access sessions for local operator credential management."""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from aidn_hypervisor.mcp.credentials import McpCredentialStore, McpPairingCode

DEFAULT_DASHBOARD_SESSION_TTL_SECONDS = 900


@dataclass(frozen=True)
class DashboardAccessSession:
    """Opaque in-memory session returned only to the HTTP adapter."""

    session_id: str
    expires_at: str


class DashboardAccessService:
    """Exchange one local pairing code for a bounded dashboard session."""

    def __init__(
        self,
        *,
        store: McpCredentialStore,
        now: Callable[[], datetime] | None = None,
        session_ttl_seconds: int = DEFAULT_DASHBOARD_SESSION_TTL_SECONDS,
        max_sessions: int = 32,
    ) -> None:
        if session_ttl_seconds <= 0:
            raise ValueError("dashboard access session TTL must be positive")
        if max_sessions < 1:
            raise ValueError("dashboard access session limit must be positive")
        self._store = store
        self._now = now or (lambda: datetime.now(UTC))
        self._session_ttl_seconds = session_ttl_seconds
        self._max_sessions = max_sessions
        self._sessions: dict[str, datetime] = {}
        self._lock = threading.RLock()

    def create_pairing(self, *, ttl_seconds: int) -> McpPairingCode:
        return self._store.create_pairing_code(ttl_seconds=ttl_seconds)

    def exchange_pairing_code(self, code: str | None) -> DashboardAccessSession | None:
        if not self._store.consume_pairing_code(code):
            return None
        with self._lock:
            self._prune_expired()
            if len(self._sessions) >= self._max_sessions:
                return None
            session_id = "das-" + secrets.token_urlsafe(24)
            expires_at = self._current_time() + timedelta(seconds=self._session_ttl_seconds)
            self._sessions[session_id] = expires_at
            return DashboardAccessSession(
                session_id=session_id,
                expires_at=self._format_timestamp(expires_at),
            )

    def authorize(self, session_id: str | None) -> bool:
        if not isinstance(session_id, str) or not session_id:
            return False
        with self._lock:
            self._prune_expired()
            return session_id in self._sessions

    def revoke_session(self, session_id: str | None) -> bool:
        if not isinstance(session_id, str) or not session_id:
            return False
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def session_expiry(self, session_id: str | None) -> str | None:
        if not isinstance(session_id, str) or not session_id:
            return None
        with self._lock:
            self._prune_expired()
            expires_at = self._sessions.get(session_id)
            return self._format_timestamp(expires_at) if expires_at is not None else None

    def _prune_expired(self) -> None:
        current = self._current_time()
        for session_id, expires_at in tuple(self._sessions.items()):
            if expires_at <= current:
                del self._sessions[session_id]

    def _current_time(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("dashboard access clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _format_timestamp(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
