"""Managed process lifecycle for authenticated Registry replication transport."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from .listener import RegistryReplicationTlsListener
from .reconnect import RegistryReplicationReconnectSupervisor


@dataclass(frozen=True)
class RegistryReplicationRuntimeError:
    """Sanitized operational error retained for operator diagnostics."""

    component: str
    peer_id: str | None
    message: str


class RegistryReplicationRuntime:
    """Run approved Registry peer links under a bounded application lifecycle.

    The caller constructs all transports and supplies the signer before this
    runtime starts. This object deliberately does not load private keys or
    discover peers from the network: operator approval remains the trust gate.
    """

    def __init__(
        self,
        *,
        listener: RegistryReplicationTlsListener | None = None,
        reconnect_supervisor: RegistryReplicationReconnectSupervisor | None = None,
        poll_interval_seconds: float = 0.1,
        maximum_recorded_errors: int = 100,
    ) -> None:
        if listener is None and reconnect_supervisor is None:
            raise ValueError("Registry replication runtime requires a listener or reconnect supervisor")
        if poll_interval_seconds <= 0:
            raise ValueError("Registry replication poll interval must be positive")
        if maximum_recorded_errors <= 0:
            raise ValueError("Registry replication error limit must be positive")
        self._listener = listener
        self._reconnect_supervisor = reconnect_supervisor
        self._poll_interval_seconds = poll_interval_seconds
        self._maximum_recorded_errors = maximum_recorded_errors
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._threads: list[threading.Thread] = []
        self._inbound_workers: dict[str, threading.Thread] = {}
        self._errors: deque[RegistryReplicationRuntimeError] = deque(
            maxlen=maximum_recorded_errors
        )
        self._running = False

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self) -> None:
        """Bind configured inbound transport and start bounded worker loops."""
        with self._lock:
            if self._running:
                return
            self._stop_event.clear()
            if self._listener is not None:
                self._listener.bind()
            self._running = True
            if self._listener is not None:
                self._start_worker("registry-replication-accept", self._accept_loop)
            if self._reconnect_supervisor is not None:
                self._start_worker("registry-replication-outbound", self._outbound_loop)
                for peer_id in self._reconnect_supervisor.peer_ids:
                    self._start_worker(
                        f"registry-replication-receive-{peer_id}",
                        lambda peer_id=peer_id: self._outbound_receive_loop(peer_id),
                    )

    def stop(self, *, join_timeout_seconds: float = 6.0) -> None:
        """Stop workers, invalidate auth state, and close the listener."""
        if join_timeout_seconds <= 0:
            raise ValueError("Registry replication join timeout must be positive")
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_event.set()
            threads = list(self._threads)
        if self._listener is not None:
            self._listener.close()
        if self._reconnect_supervisor is not None:
            self._reconnect_supervisor.disconnect_all()
        for worker in threads:
            worker.join(timeout=join_timeout_seconds)
        with self._lock:
            self._threads.clear()
            self._inbound_workers.clear()

    def status(self) -> dict:
        """Return bounded operator diagnostics without exposing transport secrets."""
        with self._lock:
            errors = [
                {
                    "component": error.component,
                    "peer_id": error.peer_id,
                    "message": error.message,
                }
                for error in self._errors
            ]
            running = self._running
        return {
            "running": running,
            "inbound_active_peer_ids": (
                self._listener.active_peer_ids() if self._listener is not None else []
            ),
            "outbound_peers": (
                self._reconnect_supervisor.status()
                if self._reconnect_supervisor is not None
                else []
            ),
            "recent_errors": errors,
        }

    def _start_worker(self, name: str, target) -> None:
        worker = threading.Thread(name=name, target=target, daemon=True)
        self._threads.append(worker)
        worker.start()

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stop_event.is_set():
            try:
                peer_id = self._listener.accept_once()
            except (ConnectionError, OSError, PermissionError, ValueError) as exc:
                if not self._stop_event.is_set():
                    self._record_error("listener", None, exc)
                continue
            with self._lock:
                if peer_id in self._inbound_workers:
                    continue
                if self._stop_event.is_set():
                    self._listener.disconnect_peer(peer_id=peer_id)
                    continue
                worker = threading.Thread(
                    name=f"registry-replication-inbound-{peer_id}",
                    target=lambda peer_id=peer_id: self._inbound_receive_loop(peer_id),
                    daemon=True,
                )
                self._inbound_workers[peer_id] = worker
                self._threads.append(worker)
                worker.start()

    def _inbound_receive_loop(self, peer_id: str) -> None:
        assert self._listener is not None
        try:
            while not self._stop_event.is_set():
                result = self._listener.receive_once(peer_id=peer_id)
                if result is None:
                    return
        except (ConnectionError, OSError, PermissionError, ValueError, KeyError) as exc:
            if not self._stop_event.is_set():
                self._record_error("inbound_receive", peer_id, exc)
        finally:
            self._listener.disconnect_peer(peer_id=peer_id)
            with self._lock:
                self._inbound_workers.pop(peer_id, None)

    def _outbound_loop(self) -> None:
        assert self._reconnect_supervisor is not None
        while not self._stop_event.is_set():
            self._reconnect_supervisor.tick()
            self._reconnect_supervisor.flush_authenticated_outboxes()
            self._stop_event.wait(self._poll_interval_seconds)

    def _outbound_receive_loop(self, peer_id: str) -> None:
        assert self._reconnect_supervisor is not None
        while not self._stop_event.is_set():
            status = next(
                (
                    item
                    for item in self._reconnect_supervisor.status()
                    if item["peer_id"] == peer_id
                ),
                None,
            )
            if status is None or not (
                status["authenticated"] or status["handshake_pending"]
            ):
                self._stop_event.wait(self._poll_interval_seconds)
                continue
            try:
                result = self._reconnect_supervisor.receive_once(peer_id=peer_id)
                if result is None:
                    self._stop_event.wait(self._poll_interval_seconds)
            except (ConnectionError, OSError, PermissionError, ValueError) as exc:
                if not self._stop_event.is_set():
                    self._record_error("outbound_receive", peer_id, exc)

    def _record_error(self, component: str, peer_id: str | None, error: Exception) -> None:
        with self._lock:
            self._errors.append(
                RegistryReplicationRuntimeError(
                    component=component,
                    peer_id=peer_id,
                    message=str(error),
                )
            )
