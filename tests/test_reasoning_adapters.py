import json

from aidn_hypervisor.reasoning_adapters import ReasoningAdapterError, ReasoningAdapterRegistry, ReasoningInvocation
from aidn_hypervisor.reasoning_router import ReasoningProvider


def _provider(provider_id: str = "local") -> ReasoningProvider:
    return ReasoningProvider(
        provider_id=provider_id,
        kind="LOCAL_MODEL",
        model_id="steward",
        capabilities=("general",),
        context_limit=131_072,
        allowed_data_classes=("OPERATOR",),
        available=True,
        enabled=True,
        trusted=True,
    )


def test_registered_adapter_is_explicit_and_preserves_invocation_metadata():
    registry = ReasoningAdapterRegistry()
    seen = {}

    def adapter(provider, invocation):
        seen["provider"] = provider.provider_id
        seen["prompt"] = invocation.prompt
        seen["stream"] = invocation.stream
        return {"output_text": "ready"}

    registry.register("local", adapter)
    result = registry.invoke(_provider(), ReasoningInvocation("check node", stream=True, parameters={"temperature": 0.1}))

    assert result == {"output_text": "ready"}
    assert seen == {"provider": "local", "prompt": "check node", "stream": True}


def test_unconfigured_provider_fails_closed():
    registry = ReasoningAdapterRegistry()
    provider = _provider("unconfigured")
    provider = ReasoningProvider(**{**provider.__dict__, "metadata": {}})

    try:
        registry.invoke(provider, ReasoningInvocation("hello"))
    except ReasoningAdapterError as error:
        assert error.details["code"] == "REASONING_ADAPTER_NOT_CONFIGURED"
    else:
        raise AssertionError("unconfigured reasoning provider must fail closed")


def test_external_provider_requires_tls():
    registry = ReasoningAdapterRegistry()
    provider = ReasoningProvider(**{**_provider("external").__dict__, "kind": "EXTERNAL_API", "metadata": {"endpoint": "http://example.invalid"}})

    try:
        registry.invoke(provider, ReasoningInvocation("hello"))
    except ReasoningAdapterError as error:
        assert error.details["code"] == "REASONING_EXTERNAL_TLS_REQUIRED"
    else:
        raise AssertionError("external HTTP reasoning endpoint must be rejected")


def test_chat_adapter_sends_system_prompt_as_a_separate_message(monkeypatch):
    registry = ReasoningAdapterRegistry()
    provider = ReasoningProvider(
        **{
            **_provider("chat").__dict__,
            "metadata": {"endpoint": "http://127.0.0.1:8080"},
        }
    )
    seen = {}

    def request(req, _timeout):
        seen.update(json.loads(req.data.decode("utf-8")))
        return {"choices": [{"message": {"content": "ready"}}]}

    monkeypatch.setattr(registry, "_request", request)
    result = registry.invoke(provider, ReasoningInvocation("check node", system_prompt="safety rules"))

    assert result["output_text"] == "ready"
    assert seen["messages"] == [
        {"role": "system", "content": "safety rules"},
        {"role": "user", "content": "check node"},
    ]


def test_completion_adapter_prepends_system_prompt(monkeypatch):
    registry = ReasoningAdapterRegistry()
    provider = ReasoningProvider(
        **{
            **_provider("completion").__dict__,
            "metadata": {"endpoint": "http://127.0.0.1:8080/completion"},
        }
    )
    seen = {}

    def request(req, _timeout):
        seen.update(json.loads(req.data.decode("utf-8")))
        return {"content": "ready"}

    monkeypatch.setattr(registry, "_request", request)
    registry.invoke(provider, ReasoningInvocation("check node", system_prompt="safety rules"))

    assert seen["prompt"].startswith("<SYSTEM>\nsafety rules\n</SYSTEM>")
    assert "<USER>\ncheck node\n</USER>" in seen["prompt"]
