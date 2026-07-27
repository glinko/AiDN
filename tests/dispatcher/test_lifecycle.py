"""Tests for ConnectionPool and BackpressureSignal."""

from __future__ import annotations

from aidn_hypervisor.dispatcher.transport.lifecycle import (
    BackpressureSignal,
    ConnectionPool,
)
from aidn_hypervisor.dispatcher.transport.tcp import TcpTransport

# ---------------------------------------------------------------------------
# BackpressureSignal
# ---------------------------------------------------------------------------

class TestBackpressureSignal:
    def test_values(self) -> None:
        assert BackpressureSignal.OK.value == "ok"
        assert BackpressureSignal.THROTTLED.value == "throttled"
        assert BackpressureSignal.QUEUE_FULL.value == "queue_full"

    def test_enum_members_count(self) -> None:
        assert len(BackpressureSignal) == 3


# ---------------------------------------------------------------------------
# ConnectionPool — basic get / release
# ---------------------------------------------------------------------------

class TestConnectionPoolBasic:
    def test_get_creates_connection(self) -> None:
        pool = ConnectionPool(max_size=5)
        conn = pool.get("127.0.0.1", 9999)
        assert conn is not None
        assert isinstance(conn, TcpTransport)
        assert pool.active_count == 1
        assert pool.idle_count == 0

    def test_release_returns_to_idle(self) -> None:
        pool = ConnectionPool(max_size=5)
        conn = pool.get("127.0.0.1", 9999)
        assert conn is not None
        pool.release(conn)
        assert pool.active_count == 0
        assert pool.idle_count == 1

    def test_get_reuses_idle_connection(self) -> None:
        pool = ConnectionPool(max_size=5)
        conn1 = pool.get("127.0.0.1", 9999)
        assert conn1 is not None
        pool.release(conn1)
        conn2 = pool.get("127.0.0.1", 9999)
        assert conn2 is conn1


# ---------------------------------------------------------------------------
# ConnectionPool — max-size limit
# ---------------------------------------------------------------------------

class TestConnectionPoolMaxSize:
    def test_max_size_enforced(self) -> None:
        pool = ConnectionPool(max_size=2)
        c1 = pool.get("127.0.0.1", 9999)
        c2 = pool.get("127.0.0.1", 9998)
        assert c1 is not None
        assert c2 is not None
        c3 = pool.get("127.0.0.1", 9997)
        assert c3 is None

    def test_release_frees_slot(self) -> None:
        pool = ConnectionPool(max_size=2)
        c1 = pool.get("127.0.0.1", 9999)
        pool.get("127.0.0.1", 9998)
        assert c1 is not None
        pool.release(c1)
        c3 = pool.get("127.0.0.1", 9997)
        assert c3 is not None
        assert pool.active_count == 2  # c2 + c3


# ---------------------------------------------------------------------------
# ConnectionPool — close_all
# ---------------------------------------------------------------------------

class TestConnectionPoolCloseAll:
    def test_close_all_clears_everything(self) -> None:
        pool = ConnectionPool(max_size=5)
        c1 = pool.get("127.0.0.1", 9999)
        assert c1 is not None
        pool.release(c1)
        pool.close_all()
        assert pool.active_count == 0
        assert pool.idle_count == 0

    def test_close_all_disconnects_connections(self) -> None:
        pool = ConnectionPool(max_size=5)
        c1 = pool.get("127.0.0.1", 9999)
        assert c1 is not None
        pool.close_all()
        from aidn_hypervisor.dispatcher.transport.abc import TransportStatus
        assert c1.status == TransportStatus.DISCONNECTED
