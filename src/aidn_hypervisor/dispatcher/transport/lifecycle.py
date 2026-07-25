"""Connection-pool and back-pressure primitives for the dispatcher transport layer.

Minimal synchronous implementation — no async, no keep-alive daemon.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Optional

from aidn_hypervisor.dispatcher.transport.tcp import TcpTransport


# ---------------------------------------------------------------------------
# BackpressureSignal
# ---------------------------------------------------------------------------

class BackpressureSignal(str, Enum):
    """Signal emitted by the pool when it cannot satisfy a request."""

    OK = "ok"
    THROTTLED = "throttled"
    QUEUE_FULL = "queue_full"


# ---------------------------------------------------------------------------
# ConnectionPool
# ---------------------------------------------------------------------------

class ConnectionPool:
    """Thread-safe pool of ``TcpTransport`` connections.

    Parameters
    ----------
    max_size : int
        Upper bound on total connections (idle + active).  Default ``10``.
    """

    def __init__(self, max_size: int = 10) -> None:
        self._max_size = max_size
        self._idle: list[TcpTransport] = []
        self._active: set[TcpTransport] = set()
        self._lock = threading.Lock()

    # -- public API ---------------------------------------------------------

    def get(self, host: str, port: int) -> Optional[TcpTransport]:
        """Return a ``TcpTransport`` for *(host, port)*.

        Reuses an idle connection if available; otherwise creates a new one
        (up to *max_size*).  Returns ``None`` when the pool is exhausted.
        """
        with self._lock:
            # Try to recycle an idle connection matching the target
            for i, conn in enumerate(self._idle):
                if conn.host == host and conn.port == port:
                    self._idle.pop(i)
                    self._active.add(conn)
                    return conn

            # If no matching idle conn but we have *any* idle conn, reuse it
            if self._idle:
                conn = self._idle.pop(0)
                self._active.add(conn)
                return conn

            # No idle connections — check active limit
            if len(self._active) >= self._max_size:
                return None

            conn = TcpTransport(host, port)
            self._active.add(conn)
            return conn

    def release(self, conn: TcpTransport) -> None:
        """Return *conn* to the idle pool."""
        with self._lock:
            self._active.discard(conn)
            self._idle.append(conn)

    def close_all(self) -> None:
        """Disconnect every connection tracked by the pool."""
        with self._lock:
            for conn in self._active:
                conn.disconnect()
            for conn in self._idle:
                conn.disconnect()
            self._active.clear()
            self._idle.clear()

    # -- properties ---------------------------------------------------------

    @property
    def active_count(self) -> int:
        """Number of connections currently in use."""
        with self._lock:
            return len(self._active)

    @property
    def idle_count(self) -> int:
        """Number of connections sitting in the idle pool."""
        with self._lock:
            return len(self._idle)
