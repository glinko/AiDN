"""Opt-in smoke profile for a real OpenAI-compatible llama.cpp server."""

import json
import os
from datetime import datetime, timedelta, timezone
from urllib import request

import pytest

from aidn_hypervisor.accounting.models import (
    AccountingContract,
    AccountingUnitContract,
    RuntimeUsageProfile,
    RuntimeUsageProfileDimension,
)
from aidn_hypervisor.dispatcher.models import DispatcherRoute
from aidn_hypervisor.providers.models import RuntimeBinding
from aidn_hypervisor.runtime_protocol import (
    LlamaCppOpenAIAdapter,
    RuntimeExecuteRequest,
    RuntimeHello,
    RuntimeHelloComplete,
    RuntimeProtocolConformanceHarness,
    RuntimeProtocolService,
    canonical_hash,
)


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


def test_llamacpp_live_adapter_records_rfc0054_terminal_evidence() -> None:
    endpoint, model = _live_configuration()
    profile = RuntimeUsageProfile(
        runtime_id="live-runtime",
        runtime_generation=1,
        runtime_configuration_hash="live-config",
        adapter_version="llamacpp-openai.v1",
        dimensions=[
            RuntimeUsageProfileDimension(
                dimension_id="input_tokens",
                unit="token",
                expected_availability="AVAILABLE",
                authority="AUTHORITATIVE_PROVIDER",
                billing_eligible=True,
            ),
            RuntimeUsageProfileDimension(
                dimension_id="output_tokens",
                unit="token",
                expected_availability="AVAILABLE",
                authority="AUTHORITATIVE_PROVIDER",
                billing_eligible=False,
            ),
        ],
    )
    binding = RuntimeBinding(
        runtime_binding_id="live-binding",
        runtime_id="live-runtime",
        runtime_generation=1,
        implementation_class="EXTERNAL_DIRECT",
        provider_instance_id="live-provider",
        model_deployment_id="live-model",
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="live-capability-definition",
        plugin_id="llama.cpp",
        plugin_version="live",
        adapter_id="llamacpp-openai",
        adapter_version="llamacpp-openai.v1",
        supported_accounting_modes=["provider_metered"],
        usage_reporting_profile_hash=profile.profile_hash,
        dispatcher_route_scope={"channel_class": "RUNTIME", "runtime_id": "live-runtime"},
        compatibility_bundle_id="live-bundle",
        status="ready",
    )
    profile = profile.model_copy(
        update={"runtime_configuration_hash": binding.runtime_configuration_hash}
    )
    contract = AccountingContract(
        contract_version="live-contract",
        accounting_mode="provider_metered",
        capability_id="llm.chat",
        endpoint_id="live-endpoint",
        pricing_version="live-pricing",
        billable_units=[
            AccountingUnitContract(
                unit="input_tokens",
                mode="provider_metered",
                price=0,
                measurement_source="llamacpp-v1-completions",
                verification_method="provider_report",
                required_authority="AUTHORITATIVE_PROVIDER",
            )
        ],
        checkpoint_policy="per_request",
    )
    route = DispatcherRoute(
        destination_type="RUNTIME",
        destination_id=binding.runtime_id,
        route_type="REMOTE_RUNTIME",
        route_generation=1,
        runtime_generation=binding.runtime_generation,
        allowed_source_types={"HYPERVISOR"},
        allowed_channel_classes={"RUNTIME"},
        allowed_message_types={"RUNTIME_EXECUTE"},
        runtime_binding_hash=binding.binding_hash(),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    protocol = RuntimeProtocolService(
        hypervisor_id="live-hypervisor",
        network_revision="live-revision",
        binding_resolver=lambda _: binding,
        route_resolver=lambda _: route,
        runtime_authenticator=lambda item: getattr(item, "runtime_signature", None) == "live-signed",
        hypervisor_signer=lambda _: "hypervisor-signed",
        request_authorizer=lambda _: True,
        accounting_contract_resolver=lambda _: contract,
        usage_profile_resolver=lambda _: profile,
    )
    hello = RuntimeHello(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        instance_id="live-instance",
        runtime_configuration_hash=binding.runtime_configuration_hash,
        capability_id=binding.capability_id,
        supported_capability_versions=[binding.capability_version],
        supported_definition_hashes=[binding.capability_definition_hash],
        supported_runtime_protocol_versions=["1.0"],
        adapter_id=binding.adapter_id,
        adapter_version=binding.adapter_version,
        runtime_nonce="live-nonce",
        runtime_challenge="live-challenge",
        runtime_signature="live-signed",
    )
    hello_response = protocol.begin_handshake(hello)
    connection = protocol.complete_handshake(
        RuntimeHelloComplete(
            handshake_id=hello_response.handshake_id,
            runtime_id=binding.runtime_id,
            runtime_generation=binding.runtime_generation,
            route_generation=route.route_generation,
            hypervisor_challenge_response=protocol.challenge_response(
                hello_response.hypervisor_challenge
            ),
            current_operational_state="READY",
            runtime_signature="live-signed",
        )
    )
    payload = {"prompt": "Reply with one short word."}
    execution_request = RuntimeExecuteRequest(
        runtime_id=binding.runtime_id,
        runtime_generation=binding.runtime_generation,
        runtime_configuration_hash=binding.runtime_configuration_hash,
        route_generation=route.route_generation,
        endpoint_id="live-endpoint",
        endpoint_configuration_hash="live-endpoint-config",
        session_id="live-session",
        session_contract_hash="live-session-contract",
        request_id="live-request-1",
        capability_id=binding.capability_id,
        capability_version=binding.capability_version,
        capability_definition_hash=binding.capability_definition_hash,
        request_payload_hash=canonical_hash(payload),
        request_payload=payload,
        request_charge_ceiling=1,
        accounting_contract_hash=contract.payload_hash,
        idempotency_key="live-request-1",
        request_deadline=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(),
    )

    adapter = LlamaCppOpenAIAdapter(
        endpoint=endpoint,
        model=model,
        runtime_signature="live-signed",
    )
    result = adapter.execute(protocol, connection.runtime_connection_id, execution_request)

    assert result.terminal_state == "COMPLETED"
    assert result.result_payload is not None
    assert protocol.store.requests[execution_request.request_id].request_state == "COMPLETED"
    report = protocol.store.usage_reports[result.final_usage_report_id]
    assert report.terminal is True
    assert {item.dimension_id for item in report.dimensions} == {"input_tokens", "output_tokens"}
    assert adapter.execute(protocol, connection.runtime_connection_id, execution_request) == result
