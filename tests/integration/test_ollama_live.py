"""Opt-in smoke profile for an attached live Ollama service."""

import os

import pytest

from aidn_hypervisor.domain.models import TaskRequest
from aidn_hypervisor.plugins.ollama import OllamaPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.providers.service import ProviderInventoryService
from aidn_hypervisor.providers.store import InMemoryProviderInventoryStore

OLLAMA_ENDPOINT = os.getenv("AIDN_OLLAMA_ENDPOINT")
OLLAMA_MODEL = os.getenv("AIDN_OLLAMA_MODEL")
pytestmark = pytest.mark.skipif(
    not OLLAMA_ENDPOINT or not OLLAMA_MODEL,
    reason="set AIDN_OLLAMA_ENDPOINT and AIDN_OLLAMA_MODEL to run live Ollama smoke",
)


def test_live_ollama_attach_discovery_and_execution() -> None:
    plugin = OllamaPlugin()
    plugins = PluginRegistry()
    plugins.register(plugin)
    inventory = ProviderInventoryService(
        plugins=plugins,
        store=InMemoryProviderInventoryStore(),
    )
    provider = inventory.attach_provider_instance(
        plugin_id="ollama",
        display_name="Live Ollama",
        configuration={"endpoint": OLLAMA_ENDPOINT},
    )
    deployments = inventory.discover_models(provider.provider_instance_id)
    deployment = next(
        item
        for item in deployments
        if item.provider_model_reference in {OLLAMA_MODEL, f"{OLLAMA_MODEL}:latest"}
    )
    runtime = RuntimeHandle(
        runtime_id="ollama-live",
        command=["ollama", "serve"],
        status="running",
        bundle_id="ollama-live-bundle",
        metadata={"endpoint": OLLAMA_ENDPOINT, "model_id": deployment.provider_model_reference},
    )

    result = plugin.invoke(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "Reply with one word."}),
        runtime,
    )

    assert provider.connection_mode == "attached"
    assert plugin.health_check(runtime) is True
    assert result["ok"] is True
    assert result["output_text"]
    assert result["usage"]["measurement_kind"] == "exact"
    assert result["usage"]["input_tokens"] > 0
    assert result["usage"]["output_tokens"] > 0
