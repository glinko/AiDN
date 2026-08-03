from __future__ import annotations

import http.server
import socket
import threading
import urllib.error
import urllib.request

import pytest

from aidn_hypervisor.plugins import egress_proxy


class _EchoHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args) -> None:
        return None


def test_allowlist_proxy_forwards_allowed_body_and_rejects_other_host(monkeypatch) -> None:
    upstream = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _EchoHandler)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()

    def connect_to_test_upstream(_host: str, _port: int):
        return socket.create_connection(upstream.server_address, timeout=2), "127.0.0.1"

    monkeypatch.setattr(egress_proxy, "_resolve_public_target", connect_to_test_upstream)
    proxy = egress_proxy._ThreadingProxyServer(
        ("127.0.0.1", 0),
        egress_proxy.EgressPolicy(
            [{"host": "allowed.example", "port": 80, "protocol": "TCP"}]
        ),
    )
    proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    proxy_thread.start()
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    )
    try:
        request = urllib.request.Request(
            "http://allowed.example/echo",
            data=b"provider-payload",
            method="POST",
        )
        with opener.open(request, timeout=3) as response:
            assert response.status == 200
            assert response.read() == b"provider-payload"

        with pytest.raises(urllib.error.HTTPError) as error:
            opener.open("http://denied.example/", timeout=3)
        assert error.value.code == 403
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()


def test_egress_policy_requires_exact_rule_match() -> None:
    policy = egress_proxy.EgressPolicy(
        [{"host": "api.example.com", "port": 443, "protocol": "TCP"}]
    )
    assert policy.allows("api.example.com", 443)
    assert policy.allows("API.EXAMPLE.COM.", 443)
    assert not policy.allows("other.example.com", 443)
    assert not policy.allows("api.example.com", 80)
