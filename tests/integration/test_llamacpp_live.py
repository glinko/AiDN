"""Opt-in smoke profile for a real OpenAI-compatible llama.cpp server."""

import json
import os
from urllib import request

import pytest

from aidn_hypervisor.runtime_protocol import RuntimeProtocolConformanceHarness


pytestmark = pytest.mark.integration


def _live_configuration() -> tuple[str, str]:
    if os.environ.get("AIDN_LLAMACPP_LIVE") != "1":
        pytest.skip("set AIDN_LLAMACPP_LIVE=1 to run against a real llama.cpp server")
    endpoint = os.environ.get("AIDN_LLAMACPP_ENDPOINT", "").rstrip("/")
    model = os.environ.get("AIDN_LLAMACPP_MODEL", "")
    if not endpoint or not model:
        pytest.skip("set AIDN_LLAMACPP_ENDPOINT and AIDN_LLAMACPP_MODEL")
    return endpoint, model


def _get_json(url: str) -> dict:
    with request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, payload: dict) -> dict:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    http_request = request.Request(
        url=url,
        method="POST",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(http_request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def test_llamacpp_live_openai_completion_profile() -> None:
    endpoint, model = _live_configuration()
    harness = RuntimeProtocolConformanceHarness()

    health = harness.assert_success("llamacpp.health", lambda: _get_json(f"{endpoint}/health"))
    models = harness.assert_success(
        "llamacpp.model_discovery", lambda: _get_json(f"{endpoint}/v1/models")
    )
    completion = harness.assert_success(
        "llamacpp.completion",
        lambda: _post_json(
            f"{endpoint}/v1/completions",
            {
                "model": model,
                "prompt": "Reply with one short word.",
                "max_tokens": 8,
                "temperature": 0,
            },
        ),
    )

    assert health["status"] == "ok"
    assert any(item["id"] == model for item in models["data"])
    assert completion["model"] == model
    assert completion["choices"]
    assert completion["usage"]["prompt_tokens"] > 0
    assert completion["usage"]["completion_tokens"] > 0
    assert completion["usage"]["total_tokens"] == (
        completion["usage"]["prompt_tokens"]
        + completion["usage"]["completion_tokens"]
    )
    assert completion["timings"]["predicted_n"] == completion["usage"]["completion_tokens"]
    assert harness.report().passed is True
