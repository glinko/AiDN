import pytest

from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.plugins.proxy_openai import ProxyOpenAIPlugin


def _bundle() -> BundleConfig:
    return BundleConfig(
        bundle_id="opaque-proxy",
        plugin_id="proxy-openai",
        provider_type="proxy-openai",
        workload_type="llm_text",
        model_id="opaque-model",
        launch_mode="attached_service",
        endpoint="https://upstream.example",
        device_affinity="external",
        resource_profile=ResourceProfile(steady_cpu=0.2, steady_ram_mb=256),
        warm_policy="auto",
    )


def test_proxy_plugin_projects_opaque_runtime_without_legacy_execution() -> None:
    plugin = ProxyOpenAIPlugin()
    bundle = _bundle()

    plugin.validate_bundle(bundle)
    with pytest.raises(ValueError, match="does not manage an upstream process"):
        plugin.build_launch_spec(bundle)
    with pytest.raises(RuntimeError, match="RFC-0054"):
        plugin.invoke(TaskRequest(task_type="llm_text.generate", payload={}), None)
    assert plugin.estimate_resources(
        TaskRequest(task_type="llm_text.generate", payload={"prompt": "hi"}),
        bundle,
        None,
    )["concurrency_limit"] == 2
    binding = plugin.create_runtime_binding(
        model_deployment={
            "model_deployment_id": "model-1",
            "provider_instance_id": "provider-1",
            "provider_model_reference": "opaque-model",
        },
        capability_id="llm.chat",
        capability_version="1.0",
        capability_definition_hash="hash",
    )
    assert binding["adapter_id"] == "proxy-openai"
    assert binding["supported_accounting_modes"] == [
        "proxy_opaque",
        "fixed_price",
        "observable",
    ]


def test_proxy_plugin_rejects_credentials_in_endpoint() -> None:
    with pytest.raises(ValueError, match="credential-free"):
        ProxyOpenAIPlugin().validate_provider_configuration(
            {"endpoint": "https://token@example.com"}
        )
