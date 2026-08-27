"""Short-lived browser access sessions for local operator credential management."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from aidn_hypervisor.mcp.credentials import (
    DashboardFirstBrowserClaim,
    McpCredentialStore,
    McpPairingCode,
)

DEFAULT_DASHBOARD_SESSION_TTL_SECONDS = 900
_DURATION_SECONDS = {
    "ten_minutes": 10 * 60,
    "one_day": 24 * 60 * 60,
    "thirty_days": 30 * 24 * 60 * 60,
    "forever": None,
}


@dataclass(frozen=True)
class DashboardAccessSession:
    """Opaque in-memory session returned only to the HTTP adapter."""

    session_id: str
    expires_at: str
    duration: str


class DashboardAccessService:
    """Exchange one local pairing code for a persistent browser-bound session."""

    def __init__(
        self,
        *,
        store: McpCredentialStore,
        now: Callable[[], datetime] | None = None,
        max_sessions: int = 32,
    ) -> None:
        if max_sessions < 1:
            raise ValueError("dashboard access session limit must be positive")
        self._store = store
        self._now = now or (lambda: datetime.now(UTC))
        self._max_sessions = max_sessions

    def create_pairing(self, *, ttl_seconds: int) -> McpPairingCode:
        return self._store.create_pairing_code(ttl_seconds=ttl_seconds)

    def open_first_browser_claim(self, *, ttl_seconds: int) -> DashboardFirstBrowserClaim:
        return self._store.open_first_dashboard_browser_claim(ttl_seconds=ttl_seconds)

    def first_browser_claim_expiry(self) -> str | None:
        return self._store.first_dashboard_browser_claim_expiry()

    def exchange_pairing_code(
        self, code: str | None, *, browser_key: str | None, duration: str = "one_day"
    ) -> DashboardAccessSession | None:
        if duration not in _DURATION_SECONDS or not isinstance(browser_key, str) or not (32 <= len(browser_key) <= 128):
            return None
        if not self._store.consume_pairing_code(code):
            return None
        session_id = "das-" + secrets.token_urlsafe(24)
        seconds = _DURATION_SECONDS[duration]
        expires_at = None if seconds is None else self._current_time() + timedelta(seconds=seconds)
        expiry_text = None if expires_at is None else self._format_timestamp(expires_at)
        if not self._store.create_dashboard_browser_session(
            session_id=session_id,
            browser_key=browser_key,
            expires_at=expiry_text,
            max_sessions=self._max_sessions,
        ):
            return None
        return DashboardAccessSession(
            session_id=session_id,
            expires_at=expiry_text or "never",
            duration=duration,
        )

    def claim_first_browser(
        self, *, browser_key: str | None, duration: str = "one_day"
    ) -> DashboardAccessSession | None:
        if duration not in _DURATION_SECONDS or not isinstance(browser_key, str) or not (32 <= len(browser_key) <= 128):
            return None
        session_id = "das-" + secrets.token_urlsafe(24)
        seconds = _DURATION_SECONDS[duration]
        expires_at = None if seconds is None else self._current_time() + timedelta(seconds=seconds)
        expiry_text = None if expires_at is None else self._format_timestamp(expires_at)
        if not self._store.claim_first_dashboard_browser(
            session_id=session_id,
            browser_key=browser_key,
            expires_at=expiry_text,
            max_sessions=self._max_sessions,
        ):
            return None
        return DashboardAccessSession(
            session_id=session_id,
            expires_at=expiry_text or "never",
            duration=duration,
        )

    def authorize(self, session_id: str | None, *, browser_key: str | None) -> bool:
        return self._store.authorize_dashboard_browser_session(
            session_id=session_id,
            browser_key=browser_key,
        )

    def revoke_session(self, session_id: str | None, *, browser_key: str | None) -> bool:
        return self._store.revoke_dashboard_browser_session(session_id=session_id, browser_key=browser_key)

    def session_expiry(self, session_id: str | None, *, browser_key: str | None) -> str | None:
        return self._store.dashboard_browser_session_expiry(
            session_id=session_id,
            browser_key=browser_key,
        )

    def _current_time(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("dashboard access clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _format_timestamp(value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
