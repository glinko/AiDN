"""Bounded Dashboard listener configuration for the operator control plane.

The Dashboard has only two supported network boundaries: loopback and the
local network bind.  The value is persisted as a single host string so the
bootstrap-generated service wrapper can consume it before Uvicorn starts.
"""

from __future__ import annotations

import os
import signal
import tempfile
import threading
from pathlib import Path
from typing import Literal

LOOPBACK_HOST = "127.0.0.1"
LAN_HOST = "0.0.0.0"
BindMode = Literal["loopback", "lan"]
_VALID_HOSTS = {LOOPBACK_HOST, LAN_HOST}


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _default_path() -> Path | None:
    configured = os.getenv("AIDN_HYPERVISOR_BIND_HOST_PATH")
    if configured:
        return Path(configured)
    state_path = os.getenv("AIDN_HYPERVISOR_STATE_PATH")
    if state_path:
        return Path(state_path).with_name("hypervisor-bind-host")
    return None


def _mode_for_host(host: str) -> BindMode:
    return "lan" if host == LAN_HOST else "loopback"


class DashboardNetworkAccessService:
    """Read and update the fixed loopback/LAN Dashboard listener boundary."""

    def __init__(
        self,
        *,
        path: str | Path | None = None,
        current_host: str | None = None,
        restart_on_change: bool | None = None,
    ) -> None:
        self._path = Path(path) if path is not None else _default_path()
        self._current_host = self._normalize_host(
            current_host or os.getenv("AIDN_HYPERVISOR_API_HOST") or LOOPBACK_HOST
        )
        self._restart_on_change = (
            _env_bool("AIDN_HYPERVISOR_RESTART_ON_BIND_CHANGE")
            if restart_on_change is None
            else restart_on_change
        )
        self._restart_scheduled = False
        self._lock = threading.Lock()

    @staticmethod
    def _normalize_host(host: str) -> str:
        value = host.strip()
        if value not in _VALID_HOSTS:
            raise ValueError("Dashboard bind host must be 127.0.0.1 or 0.0.0.0")
        return value

    def _read_configured_host(self) -> str:
        if self._path is None:
            return self._current_host
        try:
            value = self._path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return self._current_host
        except OSError as error:
            raise ValueError(f"Dashboard bind configuration could not be read: {error}") from error
        try:
            return self._normalize_host(value)
        except ValueError:
            return self._current_host

    def status(self) -> dict[str, object]:
        configured_host = self._read_configured_host()
        current_host = self._current_host
        return {
            "mode": _mode_for_host(configured_host),
            "configured_mode": _mode_for_host(configured_host),
            "effective_mode": _mode_for_host(current_host),
            "configured_host": configured_host,
            "effective_host": current_host,
            "restart_required": configured_host != current_host,
            "restart_scheduled": self._restart_scheduled,
            "apply_supported": self._path is not None,
            "port": int(os.getenv("AIDN_HYPERVISOR_API_PORT", "8766")),
        }

    @property
    def apply_supported(self) -> bool:
        return self._path is not None

    @property
    def restart_supported(self) -> bool:
        return self._path is not None and self._restart_on_change

    def set_mode(self, mode: BindMode) -> dict[str, object]:
        if mode not in {"loopback", "lan"}:
            raise ValueError("Dashboard access mode must be loopback or lan")
        host = LOOPBACK_HOST if mode == "loopback" else LAN_HOST
        if self._path is None:
            raise ValueError("Dashboard bind configuration is unavailable for this process")
        with self._lock:
            self._write_host(host)
            restart_required = host != self._current_host
            if restart_required and self._restart_on_change:
                self._schedule_restart()
        result = self.status()
        result.update(
            {
                "status": "accepted",
                "restart_required": restart_required,
                "restart_scheduled": self._restart_scheduled,
            }
        )
        return result

    def schedule_restart(self) -> bool:
        """Schedule the bootstrap-managed process restart after a config apply."""

        with self._lock:
            if self._restart_on_change:
                self._schedule_restart()
        return self._restart_scheduled

    def _write_host(self, host: str) -> None:
        assert self._path is not None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self._path.name}-",
            dir=self._path.parent,
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(f"{host}\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise

    def _schedule_restart(self) -> None:
        if self._restart_scheduled:
            return
        self._restart_scheduled = True

        def terminate_after_response() -> None:
            # The bootstrap-generated systemd unit has Restart=always.  A
            # delayed self-termination applies the new bind without granting
            # the HTTP process a generic systemctl or shell capability.
            os.kill(os.getpid(), signal.SIGTERM)

        timer = threading.Timer(0.35, terminate_after_response)
        timer.daemon = True
        timer.start()

