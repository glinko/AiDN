from pathlib import Path

import pytest

from aidn_hypervisor.bundle_registry import FileBundleRegistry
from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile
from aidn_hypervisor.main import _build_default_service
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.plugins.whisper import WhisperPlugin


def _bundle() -> BundleConfig:
    return BundleConfig(
        bundle_id="whisper-local",
        plugin_id="whisper",
        provider_type="whisper",
        workload_type="speech_to_text",
        model_id="large-v3",
        launch_mode="attached_service",
        endpoint="http://127.0.0.1:9000",
        device_affinity="cpu",
        resource_profile=ResourceProfile(
            steady_cpu=1.0,
            steady_ram_mb=1024,
            per_request_cpu=0.5,
            per_request_ram_mb=256,
        ),
        warm_policy="auto",
        priority_class=80,
    )


def _plugins() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(WhisperPlugin())
    return registry


def test_file_bundle_registry_round_trips_bundles(tmp_path: Path) -> None:
    path = tmp_path / "bundles.json"
    registry = FileBundleRegistry(path)
    bundles = [_bundle()]

    registry.save(bundles)
    restored = registry.load(_plugins())

    assert restored == bundles


def test_file_bundle_registry_returns_empty_when_file_missing(tmp_path: Path) -> None:
    registry = FileBundleRegistry(tmp_path / "missing-bundles.json")

    assert registry.load(_plugins()) == []


def test_file_bundle_registry_validates_bundles_via_plugin(tmp_path: Path) -> None:
    path = tmp_path / "bundles.json"
    registry = FileBundleRegistry(path)
    invalid_bundle = _bundle().model_copy(update={"workload_type": "llm_text"})

    registry.save([invalid_bundle])

    with pytest.raises(ValueError, match="speech_to_text"):
        registry.load(_plugins())


def test_default_service_loads_bundles_from_configured_file(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "bundles.json"
    FileBundleRegistry(path).save([_bundle()])
    monkeypatch.setenv("AIDN_HYPERVISOR_BUNDLES_PATH", str(path))

    service = _build_default_service()

    assert [bundle.bundle_id for bundle in service.bundles] == ["whisper-local"]


def test_default_service_raises_for_invalid_bundle_configuration(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "bundles.json"
    invalid_bundle = _bundle().model_copy(update={"workload_type": "llm_text"})
    FileBundleRegistry(path).save([invalid_bundle])
    monkeypatch.setenv("AIDN_HYPERVISOR_BUNDLES_PATH", str(path))

    with pytest.raises(ValueError, match="speech_to_text"):
        _build_default_service()
