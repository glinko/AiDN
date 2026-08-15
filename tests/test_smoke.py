import pytest
from fastapi.testclient import TestClient

from aidn_hypervisor.bundle_registry import FileBundleRegistry
from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile
from aidn_hypervisor.main import build_app, build_registry_app


class _RegistryReplicationRuntime:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(build_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_registry_app_health_endpoint_returns_ok() -> None:
    client = TestClient(build_registry_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_lifecycle_manages_an_explicit_registry_replication_runtime() -> None:
    runtime = _RegistryReplicationRuntime()
    app = build_app(registry_replication_runtime=runtime)  # type: ignore[arg-type]

    with TestClient(app):
        assert runtime.started is True
        assert runtime.stopped is False

    assert runtime.stopped is True


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_routes_are_not_exposed(path: str) -> None:
    client = TestClient(build_app())

    response = client.get(path)

    assert response.status_code == 404


def test_default_app_exposes_builtin_plugins(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "AIDN_HYPERVISOR_BUNDLES_PATH",
        str(tmp_path / "bundles.json"),
    )
    client = TestClient(build_app())

    response = client.get("/plugins")

    assert response.status_code == 200
    plugins = response.json()
    assert [plugin["plugin_id"] for plugin in plugins] == [
        "llama.cpp",
        "ollama",
        "proxy-openai",
        "vllm",
        "whisper",
    ]
    for plugin in plugins:
        if plugin["plugin_id"] in {"llama.cpp", "ollama", "vllm", "whisper"}:
            assert plugin["plugin_version"] == "0.2.0"
            assert plugin["plugin_capability_flags"] == [
                "CAN_ATTACH_EXISTING",
                "CAN_INSTALL_PROVIDER",
                "CAN_DISCOVER_MODELS",
            ]
            assert plugin["runtime_installers"][0]["installer_id"] == (
                "aidn-provider-runtime-ubuntu.v1"
            )
            assert plugin["runtime_installers"][0]["actions"] == [
                "install",
                "start",
                "status",
                "stop",
                "remove",
            ]
        else:
            assert plugin["plugin_version"] == "0.1.0"
            assert plugin["plugin_capability_flags"] == [
                "CAN_ATTACH_EXISTING",
                "CAN_DISCOVER_MODELS",
            ]
    whisper = plugins[-1]
    assert whisper["plugin_version"] == "0.2.0"
    assert whisper["display_name"] == "Whisper HTTP Provider"
    assert whisper["plugin_capability_flags"] == [
        "CAN_ATTACH_EXISTING",
        "CAN_INSTALL_PROVIDER",
        "CAN_DISCOVER_MODELS",
    ]
    assert whisper["required_permissions"] == [
        {
            "permission_id": "network.private",
            "label": "Private provider network",
            "risk_level": "low",
            "reason": "Connect to the operator-selected Whisper HTTP endpoint",
        },
        {
            "permission_id": "host.container_runtime",
            "label": "Manage reviewed Provider container",
            "risk_level": "high",
            "reason": "Pull and supervise the reviewed Whisper ASR container",
        },
        {
            "permission_id": "network.egress",
            "label": "Download reviewed runtime",
            "risk_level": "medium",
            "reason": "Pull the reviewed Whisper ASR image and model cache",
        },
    ]
    assert whisper["installation_recipes"][0]["recipe_id"] == "whisper-local-http"
    assert whisper["supported_aidn_capabilities"] == ["speech_to_text"]
    assert whisper["workload_types"] == ["speech_to_text"]
    assert whisper["usage_contract"] == {
        "supports_exact": False,
        "supports_estimated": True,
        "supported_billing_units": ["audio_input_seconds"],
        "supported_accounting_modes": ["fixed_price", "observable"],
        "default_measurement_source": "provider_request",
        "fallback_measurement_source": "provider_request",
        "fallback_policy": "fixed_request_estimate",
        "missing_usage_behavior": "skip",
    }


def test_default_app_exposes_bundles_loaded_from_configured_registry(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "bundles.json"
    FileBundleRegistry(path).save(
        [
            BundleConfig(
                bundle_id="whisper-local",
                plugin_id="whisper",
                provider_type="whisper",
                workload_type="speech_to_text",
                model_id="large-v3",
                launch_mode="attached_service",
                endpoint="http://127.0.0.1:9000",
                device_affinity="cpu",
                resource_profile=ResourceProfile(),
                warm_policy="auto",
            )
        ]
    )
    monkeypatch.setenv("AIDN_HYPERVISOR_BUNDLES_PATH", str(path))
    client = TestClient(build_app())

    response = client.get("/bundles")

    assert response.status_code == 200
    assert response.json()[0]["bundle_id"] == "whisper-local"
    assert response.json()[0]["plugin_id"] == "whisper"
