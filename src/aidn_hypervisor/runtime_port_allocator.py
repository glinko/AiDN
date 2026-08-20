"""Collision-safe loopback port allocation for managed runtimes.

Provider bundles describe an endpoint because that is part of their immutable
configuration.  The endpoint is not, however, a promise that the requested
port is still free when the runtime is activated.  This module keeps the
requested port as a preference, probes the real socket, and records the
selected port for the lifetime of the runtime (including warm/idle runtimes).

The allocator is deliberately local and synchronous.  It is an admission
primitive used by the process manager; it is not a network dispatcher and it
does not expose ports outside the host's configured endpoint.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from threading import RLock
from urllib.parse import SplitResult, urlsplit, urlunsplit


class RuntimePortAllocationError(ValueError):
    """Raised when a managed runtime cannot obtain a listening port."""

    code = "RUNTIME_PORT_UNAVAILABLE"

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


@dataclass(frozen=True)
class RuntimePortLease:
    runtime_id: str
    host: str
    port: int
    requested_port: int | None = None


class RuntimePortAllocator:
    """Allocate and release endpoint ports for local managed processes."""

    _LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1", "::"}

    def __init__(
        self,
        *,
        start_port: int = 8000,
        end_port: int = 8999,
    ) -> None:
        if not (1 <= start_port <= end_port <= 65535):
            raise ValueError("runtime port range is invalid")
        self.start_port = start_port
        self.end_port = end_port
        self._lock = RLock()
        self._leases_by_runtime: dict[str, RuntimePortLease] = {}
        self._leases_by_port: dict[tuple[str, int], str] = {}

    def reserve(
        self,
        runtime_id: str,
        *,
        host: str,
        requested_port: int | None = None,
        check_available: bool = True,
    ) -> RuntimePortLease:
        """Reserve one port, preferring the bundle's configured port."""

        if not runtime_id:
            raise ValueError("runtime_id is required")
        if not host:
            raise ValueError("runtime host is required")
        if requested_port is not None and not (1 <= requested_port <= 65535):
            raise ValueError("requested runtime port is invalid")

        with self._lock:
            existing = self._leases_by_runtime.get(runtime_id)
            if existing is not None:
                return existing

            candidates: list[int] = []
            if requested_port is not None:
                candidates.append(requested_port)
                # Keep a colliding configured port close to its original
                # endpoint (8080 -> 8081) before falling back to the beginning
                # of the allocator range.
                candidates.extend(
                    port
                    for port in range(max(self.start_port, requested_port + 1), self.end_port + 1)
                    if port not in candidates
                )
            candidates.extend(
                port
                for port in range(self.start_port, self.end_port + 1)
                if port not in candidates
            )
            for port in candidates:
                key = (host, port)
                if key in self._leases_by_port:
                    continue
                if check_available and not self._is_available(host, port):
                    continue
                lease = RuntimePortLease(
                    runtime_id=runtime_id,
                    host=host,
                    port=port,
                    requested_port=requested_port,
                )
                self._leases_by_runtime[runtime_id] = lease
                self._leases_by_port[key] = runtime_id
                return lease

        raise RuntimePortAllocationError(
            f"no free runtime port for {host}:{requested_port or self.start_port}",
            details={
                "host": host,
                "requested_port": requested_port,
                "range": [self.start_port, self.end_port],
            },
        )

    def release(self, runtime_id: str) -> RuntimePortLease | None:
        with self._lock:
            lease = self._leases_by_runtime.pop(runtime_id, None)
            if lease is not None:
                self._leases_by_port.pop((lease.host, lease.port), None)
            return lease

    def restore(self, runtime_id: str, *, host: str, port: int) -> RuntimePortLease | None:
        """Restore a persisted lease without probing a port after a restart.

        The process manager will perform a live readiness check after startup.
        This preserves warm-runtime identity while avoiding a false failure when
        the restored process is itself the listener that owns the port.
        """

        try:
            return self.reserve(
                runtime_id,
                host=host,
                requested_port=port,
                check_available=False,
            )
        except RuntimePortAllocationError:
            # A duplicate persisted port should not prevent the node from
            # restoring its snapshot.  The next activation will choose another
            # free port and report the conflict through readiness diagnostics.
            return None

    def prepare_launch_spec(self, runtime_id: str, launch_spec: dict) -> dict:
        """Return a launch spec with a collision-free local endpoint."""

        if launch_spec.get("launch_mode") != "managed_process":
            return launch_spec
        metadata = dict(launch_spec.get("metadata") or {})
        endpoint = metadata.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint.strip():
            return launch_spec

        parsed = urlsplit(endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return launch_spec
        host = parsed.hostname
        if host.lower() not in self._LOCAL_HOSTS:
            return launch_spec
        requested_port = parsed.port
        port_argument = launch_spec.get("port_argument")
        if not isinstance(port_argument, str) or not port_argument:
            command = list(launch_spec.get("command") or [])
            if "--port" in command or any(
                isinstance(token, str) and token.startswith("--port=")
                for token in command
            ):
                port_argument = "--port"
        if not isinstance(port_argument, str) or not port_argument:
            # Runtimes such as ``ollama serve`` use a process-global listener
            # and must be managed by their own service.  Do not pretend that an
            # endpoint port was allocated when the command cannot accept one.
            return launch_spec

        lease = self.reserve(
            runtime_id,
            host=host,
            requested_port=requested_port,
        )
        metadata["endpoint"] = _replace_endpoint_port(parsed, lease.port)
        metadata["port"] = str(lease.port)
        metadata["requested_port"] = str(requested_port or "")
        metadata["port_lease_id"] = runtime_id

        command = list(launch_spec.get("command") or [])
        _replace_command_port(command, port_argument, lease.port)
        prepared = dict(launch_spec)
        prepared["command"] = command
        prepared["metadata"] = metadata
        return prepared

    def leases(self) -> list[RuntimePortLease]:
        with self._lock:
            return list(self._leases_by_runtime.values())

    @classmethod
    def _is_available(cls, host: str, port: int) -> bool:
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        probe_host = host
        if host == "localhost":
            probe_host = "127.0.0.1"
            family = socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((probe_host, port))
        except OSError:
            return False
        return True


def _replace_endpoint_port(parsed: SplitResult, port: int) -> str:
    host = parsed.hostname or "127.0.0.1"
    host_part = f"[{host}]" if ":" in host and not host.startswith("[") else host
    netloc = host_part
    if parsed.username or parsed.password:
        # Provider validation rejects credentials, but retaining this branch
        # keeps the URL transformation lossless for future adapters.
        userinfo = parsed.username or ""
        if parsed.password is not None:
            userinfo += f":{parsed.password}"
        netloc = f"{userinfo}@{netloc}"
    netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _replace_command_port(command: list[str], port_argument: str, port: int) -> None:
    """Replace a ``--port VALUE``/``--port=VALUE`` pair in place."""

    for index, token in enumerate(command):
        if token == port_argument:
            if index + 1 < len(command):
                command[index + 1] = str(port)
            else:
                command.append(str(port))
            return
        if token.startswith(f"{port_argument}="):
            command[index] = f"{port_argument}={port}"
            return
    command.extend([port_argument, str(port)])
