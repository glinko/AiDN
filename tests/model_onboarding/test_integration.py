"""M6-P3: Onboarding Integration — TDD tests.

Tests wiring OnboardingCapabilityPublisher into HypervisorService
lifecycle: auto-publish on config changes, capability derivation from
service state, and registry query integration.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_registry():
    """Mock RegistryService for integration tests."""
    registry = MagicMock()
    registry.get_registry_object.return_value = None
    registry.upsert_registry_object.return_value = {
        "object_id": "onboarding_capability:test-node",
        "object_type": "onboarding_capability",
        "object_version": 1,
    }
    registry.list_registry_objects.return_value = []
    return registry


def _make_service(
    *,
    can_host_custom_model: bool = True,
    tmp_path: Path | None = None,
    with_resources: bool = True,
):
    """Helper to create a HypervisorService for testing."""
    from aidn_hypervisor.service import HypervisorService
    from aidn_hypervisor.scheduler import Scheduler
    from aidn_hypervisor.queue import InMemoryTaskQueue
    from aidn_hypervisor.model_store import FileModelStore
    from aidn_hypervisor.resources import ResourceOrchestrator
    from aidn_hypervisor.domain.models import NodeCapacity

    resources = None
    if with_resources:
        capacity = NodeCapacity(
            cpu_cores=4.0,
            ram_mb=16384,
            vram_mb={"gpu0": 8192},
        )
        resources = ResourceOrchestrator(capacity)

    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        can_host_custom_model=can_host_custom_model,
        resources=resources,
    )
    if tmp_path is not None:
        service.model_store = FileModelStore(tmp_path)
    return service


class TestCapabilityDerivation:
    """Test deriving onboarding capability from HypervisorService state."""

    def test_derive_capability_from_service(self, tmp_path, mock_registry):
        from aidn_hypervisor.model_onboarding.service import (
            OnboardingService,
        )

        service = _make_service(
            can_host_custom_model=True,
            tmp_path=tmp_path,
        )

        onboarding = OnboardingService(service, registry=mock_registry)
        capability = onboarding.derive_capability()

        assert capability.node_id == service.node_id
        assert capability.can_host_custom_model is True

    def test_derive_disabled_capability(self, tmp_path, mock_registry):
        from aidn_hypervisor.model_onboarding.service import (
            OnboardingService,
        )

        service = _make_service(
            can_host_custom_model=False,
            tmp_path=tmp_path,
        )

        onboarding = OnboardingService(service, registry=mock_registry)
        capability = onboarding.derive_capability()

        assert capability.can_host_custom_model is False

    def test_derive_with_installed_models(self, tmp_path, mock_registry):
        from aidn_hypervisor.model_onboarding.service import (
            OnboardingService,
        )

        service = _make_service(
            can_host_custom_model=True,
            tmp_path=tmp_path,
        )

        # Simulate an installed model
        service._model_installs["install-001"] = {
            "install_id": "install-001",
            "provider_type": "llama.cpp",
            "model_id": "phi-4-mini.gguf",
            "status": "completed",
            "bundle_id": "bundle-phi",
            "target_path": str(tmp_path / "llama.cpp" / "phi-4-mini.gguf"),
        }

        onboarding = OnboardingService(service, registry=mock_registry)
        capability = onboarding.derive_capability()

        assert len(capability.installed_models) == 1
        assert capability.installed_models[0].model_id == "phi-4-mini.gguf"

    def test_derive_with_resource_limits(self, tmp_path, mock_registry):
        from aidn_hypervisor.model_onboarding.service import (
            OnboardingService,
        )

        service = _make_service(
            can_host_custom_model=True,
            tmp_path=tmp_path,
        )

        onboarding = OnboardingService(service, registry=mock_registry)
        capability = onboarding.derive_capability()

        # Resource limits should be derived from service resources
        assert capability.resource_limits is not None


class TestAutoPublish:
    """Test automatic publication on lifecycle events."""

    def test_publish_on_init(self, tmp_path, mock_registry):
        from aidn_hypervisor.model_onboarding.service import (
            OnboardingService,
        )

        service = _make_service(
            can_host_custom_model=True,
            tmp_path=tmp_path,
        )

        _ = OnboardingService(
            service, registry=mock_registry, auto_publish=True
        )

        # Should have published on init
        mock_registry.upsert_registry_object.assert_called_once()

    def test_publish_on_install_complete(self, tmp_path, mock_registry):
        from aidn_hypervisor.model_onboarding.service import (
            OnboardingService,
        )

        service = _make_service(
            can_host_custom_model=True,
            tmp_path=tmp_path,
        )

        onboarding = OnboardingService(
            service, registry=mock_registry, auto_publish=True
        )

        # Reset the mock to clear the init publish
        mock_registry.upsert_registry_object.reset_mock()

        # Simulate an install completing
        service._model_installs["install-001"] = {
            "install_id": "install-001",
            "provider_type": "llama.cpp",
            "model_id": "phi-4-mini.gguf",
            "status": "completed",
            "bundle_id": None,
            "target_path": str(tmp_path / "llama.cpp" / "phi-4-mini.gguf"),
        }

        # Trigger re-publish
        onboarding.publish_current()

        mock_registry.upsert_registry_object.assert_called_once()

    def test_publish_on_flag_change(self, tmp_path, mock_registry):
        from aidn_hypervisor.model_onboarding.service import (
            OnboardingService,
        )

        service = _make_service(
            can_host_custom_model=True,
            tmp_path=tmp_path,
        )

        onboarding = OnboardingService(
            service, registry=mock_registry, auto_publish=True
        )

        # Reset the mock
        mock_registry.upsert_registry_object.reset_mock()

        # Change the flag
        service.can_host_custom_model = False
        onboarding.publish_current()

        # Verify the published capability reflects the change
        call_record = mock_registry.upsert_registry_object.call_args[0][0]
        assert call_record["payload"]["can_host_custom_model"] is False


class TestRegistryQueryIntegration:
    """Test querying onboarding capabilities via the registry."""

    def test_query_node_capability(self, mock_registry):
        from aidn_hypervisor.model_onboarding.service import (
            OnboardingService,
        )

        service = _make_service()

        mock_registry.get_registry_object.return_value = {
            "object_id": "onboarding_capability:node-001",
            "payload": {
                "node_id": "node-001",
                "can_host_custom_model": True,
                "supported_providers": [],
                "installed_models": [],
            },
        }

        onboarding = OnboardingService(service, registry=mock_registry)
        result = onboarding.query_node_capability("node-001")

        assert result is not None
        assert result["can_host_custom_model"] is True

    def test_list_capable_nodes(self, mock_registry):
        from aidn_hypervisor.model_onboarding.service import (
            OnboardingService,
        )

        service = _make_service()

        mock_registry.list_registry_objects.return_value = [
            {
                "object_id": "onboarding_capability:node-A",
                "payload": {
                    "node_id": "node-A",
                    "can_host_custom_model": True,
                },
            },
            {
                "object_id": "onboarding_capability:node-B",
                "payload": {
                    "node_id": "node-B",
                    "can_host_custom_model": False,
                },
            },
        ]

        onboarding = OnboardingService(service, registry=mock_registry)
        capable = onboarding.list_capable_nodes()

        assert len(capable) == 1
        assert capable[0]["node_id"] == "node-A"
