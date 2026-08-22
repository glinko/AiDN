"""Always-on Resident Steward worker and optional systemd watchdog bridge.

The Resident Steward is deliberately kept out of the request path.  This
worker owns only the small amount of periodic work needed to keep the local
control plane truthful: it refreshes the lease-gated inference adapter,
records a bounded heartbeat, and reports failures without ever starting a
model or mutating a Hypervisor object on its own.

When the Hypervisor runs under systemd, ``NOTIFY_SOCKET`` is used for the
standard ``READY=1``/``WATCHDOG=1`` protocol.  The implementation remains
usable on Windows, containers, and tests where systemd is absent.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ResidentWorker:
    """Threaded, restart-safe maintenance loop for one Hypervisor service."""

    def __init__(
        self,
        service,
        *,
        interval_seconds: float = 15.0,
        enabled: bool = True,
        worker_id: str | None = None,
    ) -> None:
        self.service = service
        self.interval_seconds = max(1.0, min(300.0, float(interval_seconds)))
        self.enabled = bool(enabled)
        self.worker_id = str(worker_id or f"resident-worker:{getattr(service, 'node_id', 'node-local')}")
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._started_at: str | None = None
        self._last_tick_at: str | None = None
        self._last_success_at: str | None = None
        self._last_error: str | None = None
        self._consecutive_failures = 0
        self._ticks = 0
        self._last_inference: dict[str, Any] = {}

    @property
    def running(self) -> bool:
        thread = self._thread
        return bool(thread is not None and thread.is_alive())

    def start(self) -> dict[str, Any]:
        if not self.enabled:
            return self.status()
        with self._lock:
            if self.running:
                return self._status_unlocked()
            self._stop.clear()
            self._wake.clear()
            self._started_at = _now()
            self._thread = threading.Thread(
                target=self._run,
                name=f"aidn-{self.worker_id}",
                daemon=True,
            )
            self._thread.start()
        self._systemd_notify("READY=1\nSTATUS=Resident Steward worker running")
        return self.status()

    def stop(self, *, timeout_seconds: float = 5.0) -> dict[str, Any]:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=max(0.1, float(timeout_seconds)))
        self._systemd_notify("STOPPING=1\nSTATUS=Resident Steward worker stopping")
        return self.status()

    def wake(self) -> None:
        """Ask the worker to run one reconciliation pass immediately."""

        self._wake.set()

    def run_once(self) -> dict[str, Any]:
        """Run one bounded maintenance pass synchronously.

        This method is intentionally public so startup probes, tests, and a
        future supervisor can exercise the exact same recovery path as the
        background worker.
        """

        started = time.monotonic()
        with self._lock:
            self._ticks += 1
            self._last_tick_at = _now()
        inference: dict[str, Any] = {}
        try:
            agent = getattr(self.service, "resident_agent", None)
            if agent is not None:
                agent.heartbeat(action="resident_worker_tick")

            # Refresh observes process exit and lease loss.  It may perform a
            # bounded GPU_BURST -> CPU fallback, but it never launches a
            # previously stopped runtime.
            refresh = getattr(self.service, "resident_inference_status", None)
            if callable(refresh):
                inference = dict(refresh() or {})

            with self._lock:
                self._last_inference = inference
                self._last_success_at = _now()
                self._last_error = None
                self._consecutive_failures = 0
            self._systemd_notify(
                "WATCHDOG=1\nSTATUS=Resident Steward healthy"
                f"; inference={inference.get('state', 'NOT_CONFIGURED')}"
            )
            return {
                "ok": True,
                "worker_id": self.worker_id,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "inference": inference,
            }
        except Exception as error:  # pragma: no cover - defensive boundary
            message = str(error)[:512]
            with self._lock:
                self._last_error = message
                self._consecutive_failures += 1
            # Do not turn an observability failure into a process crash.  The
            # next tick retries and the dashboard exposes the error.
            try:
                record = getattr(self.service, "record_event", None)
                if callable(record):
                    record(
                        event_type="aidn.steward.worker_failed",
                        message="Resident Steward maintenance pass failed",
                        details={"worker_id": self.worker_id, "error": message},
                        source="resident-worker",
                        severity="WARNING",
                        resource_type="steward",
                        resource_id=self.worker_id,
                        requires_attention=True,
                    )
            except Exception:
                pass
            return {
                "ok": False,
                "worker_id": self.worker_id,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "error": message,
                "consecutive_failures": self._consecutive_failures,
            }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_unlocked()

    def _status_unlocked(self) -> dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "enabled": self.enabled,
            "running": self.running,
            "interval_seconds": self.interval_seconds,
            "started_at": self._started_at,
            "last_tick_at": self._last_tick_at,
            "last_success_at": self._last_success_at,
            "last_error": self._last_error,
            "consecutive_failures": self._consecutive_failures,
            "ticks": self._ticks,
            "inference_state": self._last_inference.get("state", "NOT_CONFIGURED"),
            "systemd_watchdog": bool(os.getenv("NOTIFY_SOCKET")),
        }

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._wake.wait(timeout=self.interval_seconds)
            self._wake.clear()

    @staticmethod
    def _systemd_notify(message: str) -> None:
        address = os.getenv("NOTIFY_SOCKET")
        if not address:
            return
        # systemd uses an abstract Unix socket when the value starts with @.
        target: str = "\0" + address[1:] if address.startswith("@") else address
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
                sock.connect(target)
                sock.sendall(message.encode("utf-8"))
        except (OSError, ValueError):
            # Watchdog integration is advisory; the worker must remain useful
            # when systemd's notification socket is unavailable.
            return

