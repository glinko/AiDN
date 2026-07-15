from aidn_hypervisor.plugins.fake import FakeManagedPlugin


def test_fake_plugin_exposes_attach_schema_and_discovers_models() -> None:
    plugin = FakeManagedPlugin()

    attach_schema = plugin.attach_provider_schema()
    models = plugin.discover_models(
        {
            "provider_instance_id": "pi-fake",
            "display_name": "Local Fake",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
        }
    )

    assert attach_schema["fields"] == [
        {"id": "display_name", "type": "text", "required": True},
        {"id": "base_url", "type": "text", "required": True},
    ]
    assert models[0]["provider_model_reference"] == "fake-model"
    assert models[0]["capability_bindings"] == ["llm.chat"]
    assert models[0]["operational_state"] == "ready"


def test_fake_plugin_discovery_uses_provider_specific_model_deployment_ids() -> None:
    plugin = FakeManagedPlugin()

    first_models = plugin.discover_models(
        {
            "provider_instance_id": "pi-fake-a",
            "display_name": "Local Fake A",
            "configuration": {"base_url": "http://127.0.0.1:9999"},
        }
    )
    second_models = plugin.discover_models(
        {
            "provider_instance_id": "pi-fake-b",
            "display_name": "Local Fake B",
            "configuration": {"base_url": "http://127.0.0.1:9998"},
        }
    )

    assert first_models[0]["model_deployment_id"] != second_models[0]["model_deployment_id"]
    assert first_models[0]["provider_instance_id"] == "pi-fake-a"
    assert second_models[0]["provider_instance_id"] == "pi-fake-b"


def test_base_plugin_attach_existing_provider_passes_configuration_through() -> None:
    plugin = FakeManagedPlugin()

    attached = plugin.attach_existing_provider({"base_url": "http://127.0.0.1:9999"})

    assert attached == {
        "configuration": {"base_url": "http://127.0.0.1:9999"},
        "connection_mode": "attached",
        "operational_state": "ready",
    }


def test_fake_plugin_creates_runtime_binding_projection() -> None:
    plugin = FakeManagedPlugin()

    binding = plugin.create_runtime_binding(
        model_deployment={
            "model_deployment_id": "md-fake",
            "provider_instance_id": "pi-fake",
            "provider_model_reference": "fake-model",
        },
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    assert binding["model_deployment_id"] == "md-fake"
    assert binding["capability_id"] == "llm.chat"
    assert binding["compatibility_bundle"]["plugin_id"] == "fake-managed"
    assert binding["compatibility_bundle"]["provider_type"] == "fake"
    assert binding["compatibility_bundle"]["model_id"] == "fake-model"
