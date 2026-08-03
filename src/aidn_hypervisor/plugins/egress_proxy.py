"""Small allowlist HTTP proxy used by the Docker Plugin Host supervisor.

The proxy intentionally supports only HTTP absolute-form requests and HTTP
CONNECT.  It is mounted into a separate, non-privileged container; the Plugin
Host is attached to an internal Docker network and cannot route to the
Internet without passing through this process.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import select
import socket
import socketserver
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_MAX_HEADER_BYTES = 64 * 1024
_SOCKET_TIMEOUT_SECONDS = 10.0
_RELAY_IDLE_TIMEOUT_SECONDS = 300.0


class EgressProxyError(ValueError):
    """A request or policy cannot be handled by the proxy."""


@dataclass(frozen=True)
class EgressRule:
    host: str
    port: int
    protocol: str = "TCP"


def _normalize_host(value: object) -> str:
    if not isinstance(value, str):
        raise EgressProxyError("egress host must be text")
    host = value.strip().rstrip(".").lower()
    if not host or len(host) > 253:
        raise EgressProxyError("egress host must be a bounded DNS name")
    if any(character.isspace() for character in host):
        raise EgressProxyError("egress host must not contain whitespace")
    if any(character in host for character in ("*", "/", "\\", ":")):
        raise EgressProxyError("egress host must be an exact DNS name")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise EgressProxyError("egress rules cannot contain IP literals")
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise EgressProxyError("egress host is not a valid DNS name") from error
    labels = ascii_host.split(".")
    if any(
        not label
        or len(label) > 63
        or label[0] == "-"
        or label[-1] == "-"
        or re.fullmatch(r"[a-z0-9-]+", label) is None
        for label in labels
    ):
        raise EgressProxyError("egress host is not a valid DNS name")
    return ascii_host


class EgressPolicy:
    """Exact, non-wildcard destination policy for outbound TCP connections."""

    def __init__(self, rules: list[dict]) -> None:
        normalized: set[tuple[str, int, str]] = set()
        for raw_rule in rules:
            if not isinstance(raw_rule, dict):
                raise EgressProxyError("egress rule must be an object")
            host = _normalize_host(raw_rule.get("host"))
            port = raw_rule.get("port")
            protocol = str(raw_rule.get("protocol") or "TCP").strip().upper()
            if (
                protocol != "TCP"
                or isinstance(port, bool)
                or not isinstance(port, int)
                or not 1 <= port <= 65535
            ):
                raise EgressProxyError("invalid exact egress rule")
            normalized.add((host, port, protocol))
        if len(normalized) != len(rules):
            raise EgressProxyError("egress rules must be unique")
        self._rules = frozenset(normalized)

    def allows(self, host: str, port: int) -> bool:
        try:
            normalized_host = _normalize_host(host)
        except EgressProxyError:
            return False
        return (normalized_host, port, "TCP") in self._rules


def _read_headers(connection: socket.socket) -> tuple[bytes, bytes]:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > _MAX_HEADER_BYTES:
            raise EgressProxyError("proxy request headers are too large")
    if b"\r\n\r\n" not in data:
        raise EgressProxyError("proxy request headers are incomplete")
    header_end = data.index(b"\r\n\r\n") + 4
    return bytes(data[:header_end]), bytes(data[header_end:])


def _parse_host_port(value: str) -> tuple[str, int]:
    value = value.strip()
    if not value or ":" not in value or value.count(":") != 1:
        raise EgressProxyError("proxy target must use an exact host:port")
    host, port_text = value.rsplit(":", 1)
    if not host or not port_text.isdigit():
        raise EgressProxyError("proxy target must use an exact host:port")
    port = int(port_text)
    if not 1 <= port <= 65535:
        raise EgressProxyError("proxy target port is outside the allowed range")
    return host.lower().rstrip("."), port


def _parse_request_target(request_line: str) -> tuple[str, int, str | None]:
    parts = request_line.split(" ", 2)
    if len(parts) != 3:
        raise EgressProxyError("proxy request line is invalid")
    method, target, version = parts
    if version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise EgressProxyError("proxy HTTP version is unsupported")
    if method.upper() == "CONNECT":
        host, port = _parse_host_port(target)
        return host, port, None
    parsed = urlsplit(target)
    if parsed.scheme.lower() != "http" or not parsed.hostname:
        raise EgressProxyError("non-CONNECT proxy requests require an absolute HTTP URL")
    if parsed.username or parsed.password:
        raise EgressProxyError("proxy request URL contains unsupported credentials")
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as error:
        raise EgressProxyError("proxy request URL has an invalid port") from error
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return parsed.hostname.lower().rstrip("."), port, path


def _resolve_public_target(host: str, port: int) -> tuple[socket.socket, str]:
    """Resolve once and connect only to a public address from that result."""
    last_error: OSError | None = None
    for family, socktype, protocol, _, address in socket.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
    ):
        ip = ipaddress.ip_address(address[0])
        if not ip.is_global:
            continue
        connection = socket.socket(family, socktype, protocol)
        connection.settimeout(_SOCKET_TIMEOUT_SECONDS)
        try:
            connection.connect(address)
        except OSError as error:
            last_error = error
            connection.close()
            continue
        connection.settimeout(None)
        return connection, str(ip)
    if last_error is not None:
        raise last_error
    raise EgressProxyError("egress target did not resolve to a public address")


def _relay(left: socket.socket, right: socket.socket) -> None:
    sockets = [left, right]
    while True:
        readable, _, _ = select.select(
            sockets,
            [],
            [],
            _RELAY_IDLE_TIMEOUT_SECONDS,
        )
        if not readable:
            return
        for source in readable:
            data = source.recv(64 * 1024)
            if not data:
                return
            destination = right if source is left else left
            destination.sendall(data)


class _ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        connection: socket.socket = self.request
        connection.settimeout(_SOCKET_TIMEOUT_SECONDS)
        upstream: socket.socket | None = None
        try:
            header_block, initial_body = _read_headers(connection)
            request_line, *header_lines = header_block.decode("iso-8859-1").split("\r\n")[:-2]
            host, port, forward_path = _parse_request_target(request_line)
            if not self.server.policy.allows(host, port):  # type: ignore[attr-defined]
                self._respond(connection, 403, "destination is not declared")
                return
            upstream, _ = _resolve_public_target(host, port)
            if forward_path is None:
                connection.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if initial_body:
                    upstream.sendall(initial_body)
            else:
                method, _, version = request_line.split(" ", 2)
                forwarded_headers = []
                for line in header_lines:
                    lowered_line = line.lower()
                    if not line or lowered_line.startswith(
                        ("proxy-connection:", "proxy-authorization:", "proxy-authenticate:")
                    ):
                        continue
                    if lowered_line.startswith("connection:"):
                        continue
                    forwarded_headers.append(line)
                forwarded_headers.append("Connection: close")
                forwarded = (
                    f"{method} {forward_path} {version}\r\n"
                    + "\r\n".join(forwarded_headers)
                    + "\r\n\r\n"
                ).encode("iso-8859-1")
                upstream.sendall(forwarded + initial_body)
            connection.settimeout(None)
            _relay(connection, upstream)
        except (EgressProxyError, OSError, UnicodeError):
            try:
                self._respond(connection, 502, "egress request rejected")
            except OSError:
                pass
        finally:
            if upstream is not None:
                upstream.close()

    @staticmethod
    def _respond(connection: socket.socket, status: int, message: str) -> None:
        body = (message + "\n").encode("ascii", "replace")
        connection.sendall(
            (
                f"HTTP/1.1 {status} Proxy Error\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            + body
        )


class _ThreadingProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, policy: EgressPolicy):
        self.policy = policy
        super().__init__(server_address, _ProxyHandler)


def serve(*, policy_path: Path, listen_host: str, listen_port: int) -> None:
    policy = EgressPolicy(json.loads(policy_path.read_text(encoding="utf-8")))
    with _ThreadingProxyServer((listen_host, listen_port), policy) as server:
        server.serve_forever(poll_interval=0.2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", required=True)
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--listen-port", type=int, default=3128)
    args = parser.parse_args()
    try:
        serve(
            policy_path=Path(args.policy),
            listen_host=args.listen_host,
            listen_port=args.listen_port,
        )
    except Exception as error:
        print(f"egress proxy stopped: {error}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
