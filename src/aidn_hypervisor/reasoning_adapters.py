"""Execution adapters for the RFC-0075 Reasoning Router.

Routing remains a read-only deterministic decision.  This module is the
separate execution boundary used only after a caller explicitly asks to
invoke the selected provider.  Provider metadata never carries credentials;
external credentials are resolved from an operator-controlled environment
variable named by the provider metadata.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from aidn_hypervisor.reasoning_router import ReasoningProvider


class ReasoningAdapterError(ValueError):
    code = "REASONING_ADAPTER_FAILED"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = dict(details or {})


@dataclass(frozen=True)
class ReasoningInvocation:
    prompt: str
    timeout_seconds: float = 90.0
    stream: bool = False
    parameters: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        text = str(self.prompt or "")
        if not text or len(text) > 131_072:
            raise ReasoningAdapterError("prompt must contain 1..131072 characters", details={"code": "REASONING_PROMPT_INVALID"})
        object.__setattr__(self, "prompt", text)
        object.__setattr__(self, "timeout_seconds", max(0.1, min(3600.0, float(self.timeout_seconds))))
        object.__setattr__(self, "parameters", dict(self.parameters or {}))


class ReasoningAdapterRegistry:
    """Maps provider IDs to bounded invocation functions."""

    def __init__(self) -> None:
        self._adapters: dict[str, Callable[[ReasoningProvider, ReasoningInvocation], dict[str, Any]]] = {}

    def register(self, provider_id: str, adapter: Callable[[ReasoningProvider, ReasoningInvocation], dict[str, Any]]) -> None:
        key = str(provider_id or "").strip()
        if not key or not callable(adapter):
            raise ValueError("provider_id and adapter are required")
        self._adapters[key] = adapter

    def unregister(self, provider_id: str) -> None:
        self._adapters.pop(str(provider_id or "").strip(), None)

    def invoke(self, provider: ReasoningProvider, invocation: ReasoningInvocation) -> dict[str, Any]:
        adapter = self._adapters.get(provider.provider_id)
        if adapter is None:
            adapter = self._default_adapter
        try:
            result = adapter(provider, invocation)
        except ReasoningAdapterError:
            raise
        except Exception as error:
            raise ReasoningAdapterError(
                "reasoning provider invocation failed",
                details={"code": "REASONING_PROVIDER_FAILED", "provider_id": provider.provider_id, "message": str(error)[:256]},
            ) from error
        if not isinstance(result, dict):
            raise ReasoningAdapterError("reasoning adapter returned an invalid result", details={"code": "REASONING_RESULT_INVALID"})
        return result

    def _default_adapter(self, provider: ReasoningProvider, invocation: ReasoningInvocation) -> dict[str, Any]:
        metadata = provider.metadata
        endpoint = metadata.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ReasoningAdapterError("reasoning provider has no execution adapter", details={"code": "REASONING_ADAPTER_NOT_CONFIGURED", "provider_id": provider.provider_id})
        endpoint = endpoint.strip().rstrip("/")
        parsed = urlsplit(endpoint)
        if provider.kind == "EXTERNAL_API" and parsed.scheme != "https":
            raise ReasoningAdapterError("external reasoning providers require HTTPS", details={"code": "REASONING_EXTERNAL_TLS_REQUIRED"})
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ReasoningAdapterError("reasoning provider endpoint is invalid", details={"code": "REASONING_ENDPOINT_INVALID"})
        path = parsed.path.rstrip("/")
        if path.endswith("/completion"):
            url = endpoint
            payload = {"prompt": invocation.prompt, "stream": invocation.stream, **dict(invocation.parameters or {})}
        else:
            url = f"{endpoint}/v1/chat/completions"
            payload = {
                "model": provider.model_id or "resident-steward",
                "messages": [{"role": "user", "content": invocation.prompt}],
                "stream": invocation.stream,
                **dict(invocation.parameters or {}),
            }
        headers = {"Content-Type": "application/json", "User-Agent": "AiDN-Resident-Steward/1"}
        env_name = metadata.get("api_key_env")
        if isinstance(env_name, str) and env_name and env_name.isidentifier():
            secret = os.getenv(env_name)
            if secret:
                headers["Authorization"] = f"Bearer {secret}"
        request = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aidn-reasoning")
        future = executor.submit(self._request, request, invocation.timeout_seconds)
        try:
            response = future.result(timeout=invocation.timeout_seconds)
        except FutureTimeoutError as error:
            future.cancel()
            raise ReasoningAdapterError("reasoning provider timed out", details={"code": "REASONING_PROVIDER_TIMEOUT", "timeout_seconds": invocation.timeout_seconds}) from error
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        output = response.get("content") or response.get("response")
        if not output and isinstance(response.get("choices"), list) and response["choices"]:
            choice = response["choices"][0]
            if isinstance(choice, Mapping):
                message = choice.get("message")
                output = message.get("content") if isinstance(message, Mapping) else choice.get("text")
        if output is None:
            raise ReasoningAdapterError("reasoning provider returned empty content", details={"code": "REASONING_EMPTY_RESULT"})
        return {"ok": True, "provider_id": provider.provider_id, "model_id": provider.model_id, "output_text": str(output), "stream": invocation.stream, "raw": response}

    @staticmethod
    def _request(req: Request, timeout: float) -> dict[str, Any]:
        with urlopen(req, timeout=timeout) as response:
            body = response.read(4 * 1024 * 1024)
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReasoningAdapterError("reasoning provider returned invalid JSON", details={"code": "REASONING_RESPONSE_INVALID"}) from error
        if not isinstance(decoded, dict):
            raise ReasoningAdapterError("reasoning provider returned a non-object response", details={"code": "REASONING_RESPONSE_INVALID"})
        return decoded
