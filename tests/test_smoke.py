from fastapi.testclient import TestClient
import pytest

from aidn_hypervisor.bundle_registry import FileBundleRegistry
from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile
from aidn_hypervisor.main import build_app, build_registry_app


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


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_routes_are_not_exposed(path: str) -> None:
    client = TestClient(build_app())

    response = client.get(path)

    assert response.status_code == 404


def test_default_app_exposes_builtin_plugins() -> None:
    client = TestClient(build_app())

    response = client.get("/plugins")

    assert response.status_code == 200
    assert response.json() == [
        {
            "plugin_id": "llama.cpp",
            "workload_types": ["llm_text"],
            "usage_contract": {
                "supports_exact": True,
                "supports_estimated": True,
                "default_measurement_source": "provider_api",
                "fallback_measurement_source": "provider_api_partial",
                "fallback_policy": "partial_response_estimate",
                "missing_usage_behavior": "skip",
            },
        },
        {
            "plugin_id": "ollama",
            "workload_types": ["llm_text"],
            "usage_contract": {
                "supports_exact": True,
                "supports_estimated": True,
                "default_measurement_source": "provider_api",
                "fallback_measurement_source": "provider_api_partial",
                "fallback_policy": "partial_response_estimate",
                "missing_usage_behavior": "skip",
            },
        },
        {
            "plugin_id": "whisper",
            "workload_types": ["speech_to_text"],
            "usage_contract": {
                "supports_exact": False,
                "supports_estimated": True,
                "default_measurement_source": "provider_request",
                "fallback_measurement_source": "provider_request",
                "fallback_policy": "fixed_request_estimate",
                "missing_usage_behavior": "skip",
            },
        }
    ]


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
