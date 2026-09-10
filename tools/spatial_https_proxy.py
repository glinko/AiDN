#!/usr/bin/env python3
"""Small TLS reverse proxy for the LAN Spatial calibration page.

The Hypervisor intentionally keeps its existing HTTP listener for backwards
compatibility. Browser microphone APIs require a secure origin, so this proxy
adds an HTTPS listener without starting a second Hypervisor or touching its
state files.
"""

from __future__ import annotations

import http.client
import os
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final


BACKEND_HOST: Final = os.environ.get("AIDN_SPATIAL_PROXY_BACKEND_HOST", "127.0.0.1")
BACKEND_PORT: Final = int(os.environ.get("AIDN_SPATIAL_PROXY_BACKEND_PORT", "8766"))
LISTEN_HOST: Final = os.environ.get("AIDN_SPATIAL_HTTPS_HOST", "0.0.0.0")
LISTEN_PORT: Final = int(os.environ.get("AIDN_SPATIAL_HTTPS_PORT", "8767"))
CERT_FILE: Final = os.environ.get(
    "AIDN_SPATIAL_HTTPS_CERT",
    "/home/user/.local/share/aidn/gpu-3090/spatial-https/server.crt",
)
KEY_FILE: Final = os.environ.get(
    "AIDN_SPATIAL_HTTPS_KEY",
    "/home/user/.local/share/aidn/gpu-3090/spatial-https/server.key",
)
HOP_BY_HOP_HEADERS: Final = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class SpatialProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._proxy()

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._proxy()

    def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._proxy()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._proxy()

    def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._proxy()

    def _proxy(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in HOP_BY_HOP_HEADERS
        }
        headers["Host"] = f"{BACKEND_HOST}:{BACKEND_PORT}"
        headers["Connection"] = "close"

        connection: http.client.HTTPConnection | None = None
        try:
            connection = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=30)
            connection.request(self.command, self.path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_response(response.status, response.reason)
            for key, value in response.getheaders():
                if key.lower() in HOP_BY_HOP_HEADERS:
                    continue
                self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                while chunk := response.read(64 * 1024):
                    self.wfile.write(chunk)
        except (OSError, http.client.HTTPException) as error:
            self.send_error(502, f"Spatial backend unavailable: {error}")
        finally:
            if connection is not None:
                connection.close()

    def log_message(self, format: str, *args: object) -> None:
        # Keep the user service journal useful without logging request bodies.
        super().log_message(format, *args)


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)
    server = ReusableThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), SpatialProxyHandler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(f"Spatial HTTPS proxy listening on {LISTEN_HOST}:{LISTEN_PORT} → {BACKEND_HOST}:{BACKEND_PORT}", flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
