from __future__ import annotations

import json
from urllib import error as urllib_error, request as urllib_request


class RemoteTransportService:
    """Proxy/remote HTTP transport boundary for HypervisorService."""

    def __init__(self, host) -> None:
        self._host = host

    def remote_request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
    ) -> dict:
        transport = getattr(self._host, "remote_transport", None)
        if transport is not None:
            return transport.request_json(method, url, payload)
        return self.default_remote_request_json(method, url, payload)

    def default_remote_request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
    ) -> dict:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib_request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8")
        except urllib_error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"Remote proxy request failed: {method} {url} [{error.code}] {body}"
            ) from error
        except urllib_error.URLError as error:
            raise RuntimeError(
                f"Remote proxy request failed: {method} {url} [{error.reason}]"
            ) from error
        return json.loads(body) if body else {}
