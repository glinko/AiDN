"""Opt-in smoke profile for an attached live vLLM OpenAI-compatible server."""

import os
from datetime import UTC, datetime, timedelta

import pytest

from aidn_hypervisor.plugins.vllm import VllmPlugin
from aidn_hypervisor.runtime_protocol import RuntimeExecuteRequest, VllmOpenAIAdapter, canonical_hash

VLLM_ENDPOINT = os.getenv("AIDN_VLLM_ENDPOINT")
VLLM_MODEL = os.getenv("AIDN_VLLM_MODEL")
pytestmark = pytest.mark.skipif(
    not VLLM_ENDPOINT or not VLLM_MODEL,
    reason="set AIDN_VLLM_ENDPOINT and AIDN_VLLM_MODEL to run live vLLM smoke",
)


def _request() -> RuntimeExecuteRequest:
    payload = {"prompt": "Reply with the word AiDN."}
    return RuntimeExecuteRequest(
        runtime_id="vllm-live",
        runtime_generation=1,
        runtime_configuration_hash="vllm-live-config",
        route_generation=1,
        endpoint_id="vllm-live-endpoint",
        endpoint_configuration_hash="vllm-live-endpoint-config",
        session_id="vllm-live-session",
        session_contract_hash="vllm-live-session-contract",
        request_id="vllm-live-request",
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="vllm-live-capability",
        request_payload_hash=canonical_hash(payload),
        request_payload=payload,
        request_charge_ceiling=1,
        accounting_contract_hash="vllm-live-accounting",
        idempotency_key="vllm-live-request",
        request_deadline=(datetime.now(UTC) + timedelta(minutes=2)).isoformat(),
    )


def test_live_vllm_attach_discovery_completion_and_streaming() -> None:
    plugin = VllmPlugin()
    attached = plugin.attach_existing_provider({"endpoint": VLLM_ENDPOINT})
    models = plugin.discover_models({"configuration": attached["configuration"]})
    assert any(item["provider_model_reference"] == VLLM_MODEL for item in models)

    adapter = VllmOpenAIAdapter(endpoint=VLLM_ENDPOINT, model=VLLM_MODEL, runtime_signature="live")
    completion = adapter._completion(_request())
    assert completion["choices"]
    assert isinstance(completion["choices"][0]["text"], str)

    events = list(adapter._stream_completion(_request()))
    assert events
    assert all("choices" in event for event in events)
