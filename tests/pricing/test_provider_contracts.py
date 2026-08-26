import pytest

from aidn_hypervisor.accounting.llamacpp import build_llamacpp_usage_profile
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.plugins.ollama import OllamaPlugin
from aidn_hypervisor.plugins.proxy_openai import ProxyOpenAIPlugin
from aidn_hypervisor.plugins.vllm import VllmPlugin


@pytest.mark.parametrize(("plugin_type", "expected_units"), [
    (LlamaCppPlugin, ["input_tokens", "cached_input_tokens", "output_tokens"]),
    (VllmPlugin, ["input_tokens", "cached_input_tokens", "output_tokens"]),
    (OllamaPlugin, ["input_tokens", "output_tokens"]),
])
def test_native_llm_provider_declares_exact_token_billing_units(plugin_type, expected_units) -> None:
    contract = plugin_type().usage_contract()

    assert contract["supported_billing_units"] == expected_units
    assert "provider_metered" in contract["supported_accounting_modes"]


def test_opaque_proxy_explicitly_declares_no_metered_billing_units() -> None:
    contract = ProxyOpenAIPlugin().usage_contract()

    assert contract["supported_billing_units"] == []
    assert "proxy_opaque" in contract["supported_accounting_modes"]


def test_llamacpp_usage_separates_cached_input_tokens() -> None:
    usage = LlamaCppPlugin()._usage_from_response({"usage": {
        "prompt_tokens": 100,
        "completion_tokens": 25,
        "prompt_tokens_details": {"cached_tokens": 40},
    }})

    assert usage["input_tokens"] == 60
    assert usage["cached_input_tokens"] == 40
    assert usage["output_tokens"] == 25


def test_vllm_usage_separates_cached_input_tokens() -> None:
    usage = VllmPlugin()._usage_from_response({
        "prompt_tokens": 100,
        "completion_tokens": 25,
        "prompt_tokens_details": {"cached_tokens": 40},
    })

    assert usage["input_tokens"] == 60
    assert usage["cached_input_tokens"] == 40
    assert usage["output_tokens"] == 25


def test_llamacpp_runtime_profile_declares_cached_tokens_as_partial() -> None:
    profile = build_llamacpp_usage_profile(
        runtime_id="runtime-1",
        runtime_generation=1,
        runtime_configuration_hash="sha256:runtime",
    )

    cached = profile.dimension("cached_input_tokens")
    assert cached is not None
    assert cached.expected_availability == "PARTIAL"
    assert cached.authority == "AUTHORITATIVE_PROVIDER"
