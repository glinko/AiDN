import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from aidn_hypervisor.accounting.ollama import build_ollama_usage_profile
from aidn_hypervisor.runtime_protocol import OllamaGenerateAdapter, RuntimeExecuteRequest, canonical_hash
from aidn_hypervisor.runtime_protocol.approved_dispatch import ApprovedRuntimeDispatcher


def _request() -> RuntimeExecuteRequest:
    payload = {"prompt": "hello"}
    return RuntimeExecuteRequest(
        runtime_id="runtime-1",
        runtime_generation=1,
        runtime_configuration_hash="runtime-config-1",
        route_generation=1,
        endpoint_id="endpoint-1",
        endpoint_configuration_hash="endpoint-config-1",
        session_id="session-1",
        session_contract_hash="session-contract-1",
        request_id="request-1",
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="capability-definition-1",
        request_payload_hash=canonical_hash(payload),
        request_payload=payload,
        request_charge_ceiling=1,
        accounting_contract_hash="accounting-contract-1",
        idempotency_key="key-request-1",
        request_deadline=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
    )


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body

    def __iter__(self):
        return iter(self._body.splitlines(keepends=True))


def test_ollama_adapter_normalizes_generate_response_and_usage(monkeypatch) -> None:
    adapter = OllamaGenerateAdapter(
        endpoint="http://provider",
        model="qwen",
        runtime_signature="runtime-signed",
    )
    payload = {
        "model": "qwen",
        "response": "ok",
        "done": True,
        "prompt_eval_count": 3,
        "eval_count": 2,
    }
    monkeypatch.setattr(
        "aidn_hypervisor.runtime_protocol.adapters.ollama.urllib_request.urlopen",
        lambda request, timeout: _Response(json.dumps(payload).encode("utf-8")),
    )

    response = adapter._completion(_request())
    dimensions = adapter._usage_dimensions(response["usage"])

    assert response["choices"] == [{"text": "ok", "finish_reason": "stop"}]
    assert [(item.dimension_id, item.value, item.authority) for item in dimensions] == [
        ("input_tokens", 3, "AUTHORITATIVE_PROVIDER"),
        ("output_tokens", 2, "AUTHORITATIVE_PROVIDER"),
    ]


def test_ollama_adapter_normalizes_jsonl_stream(monkeypatch) -> None:
    adapter = OllamaGenerateAdapter(
        endpoint="http://provider",
        model="qwen",
        runtime_signature="runtime-signed",
    )
    body = b'{"response":"hel","done":false}\n{"response":"lo","done":true}\n'
    monkeypatch.setattr(
        "aidn_hypervisor.runtime_protocol.adapters.ollama.urllib_request.urlopen",
        lambda request, timeout: _Response(body),
    )

    events = list(adapter._stream_completion(_request()))

    assert [event["choices"][0]["text"] for event in events] == ["hel", "lo"]
    assert events[-1]["choices"][0]["finish_reason"] == "stop"


def test_ollama_usage_profile_uses_provider_tokens_and_observable_stream_bytes() -> None:
    profile = build_ollama_usage_profile(
        runtime_id="runtime-1",
        runtime_generation=1,
        runtime_configuration_hash="runtime-config-1",
    )

    assert {item.dimension_id: item.authority for item in profile.dimensions} == {
        "input_tokens": "AUTHORITATIVE_PROVIDER",
        "output_tokens": "AUTHORITATIVE_PROVIDER",
        "output_bytes": "OBSERVABLE_LOCAL",
    }


def test_approved_dispatch_selects_ollama_usage_profile() -> None:
    binding = SimpleNamespace(
        adapter_id="ollama-generate",
        runtime_id="runtime-1",
        runtime_generation=1,
        runtime_configuration_hash="runtime-config-1",
        adapter_version="ollama-generate.v1",
    )

    profile = ApprovedRuntimeDispatcher._usage_profile(binding)

    assert profile.adapter_version == "ollama-generate.v1"
    assert profile.profile_hash == build_ollama_usage_profile(
        runtime_id="runtime-1",
        runtime_generation=1,
        runtime_configuration_hash="runtime-config-1",
    ).profile_hash
