"""M6-P2: Onboarding Capability Registry Publisher — TDD tests.

Tests the OnboardingCapabilityPublisher that publishes onboarding
capability objects to the Registry service.
"""

import hashlib
import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_registry():
    """Mock RegistryService for testing."""
    registry = MagicMock()
    registry.get_registry_object.return_value = None
    registry.upsert_registry_object.return_value = {
        "object_id": "onboarding-node-001",
        "object_type": "onboarding_capability",
        "object_version": 1,
    }
    return registry


@pytest.fixture
def sample_capability():
    """Create a sample OnboardingCapability for testing."""
    from aidn_hypervisor.model_onboarding.models import (
        InstalledModelInfo,
        OnboardingCapability,
        ProviderCapability,
        ResourceLimits,
    )

    return OnboardingCapability(
        node_id="node-001",
        operator_id="op-001",
        can_host_custom_model=True,
        supported_providers=[
            ProviderCapability(
                provider_type="llama.cpp",
                max_models=5,
                max_model_size_mb=4096,
            ),
        ],
        installed_models=[
            InstalledModelInfo(
                model_id="phi-4-mini.gguf",
                provider_type="llama.cpp",
                bundle_id="bundle-phi",
                size_mb=2048,
            ),
        ],
        resource_limits=ResourceLimits(
            max_total_model_size_mb=16384,
            max_concurrent_models=10,
            available_vram_mb=4096,
        ),
    )


class TestCapabilitySerialization:
    """Test serializing OnboardingCapability to registry format."""

    def test_serialize_produces_required_fields(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        record = publisher._serialize_capability(sample_capability)

        assert "object_id" in record
        assert "object_type" in record
        assert "object_version" in record
        assert "payload" in record
        assert "payload_hash" in record
        assert "created_at" in record
        assert "updated_at" in record

    def test_serialize_sets_correct_object_type(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        record = publisher._serialize_capability(sample_capability)

        assert record["object_type"] == "onboarding_capability"

    def test_serialize_sets_correct_object_id(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        record = publisher._serialize_capability(sample_capability)

        assert record["object_id"] == "onboarding_capability:node-001"

    def test_serialize_includes_can_host_flag(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        record = publisher._serialize_capability(sample_capability)

        assert record["payload"]["can_host_custom_model"] is True

    def test_serialize_includes_provider_capabilities(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        record = publisher._serialize_capability(sample_capability)

        providers = record["payload"]["supported_providers"]
        assert len(providers) == 1
        assert providers[0]["provider_type"] == "llama.cpp"
        assert providers[0]["max_models"] == 5

    def test_serialize_includes_installed_models(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        record = publisher._serialize_capability(sample_capability)

        models = record["payload"]["installed_models"]
        assert len(models) == 1
        assert models[0]["model_id"] == "phi-4-mini.gguf"
        assert models[0]["bundle_id"] == "bundle-phi"

    def test_serialize_includes_resource_limits(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        record = publisher._serialize_capability(sample_capability)

        limits = record["payload"]["resource_limits"]
        assert limits["max_total_model_size_mb"] == 16384
        assert limits["max_concurrent_models"] == 10

    def test_serialize_payload_hash_matches_content(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        record = publisher._serialize_capability(sample_capability)

        expected_hash = hashlib.sha256(
            json.dumps(record["payload"], sort_keys=True, default=str).encode()
        ).hexdigest()
        assert record["payload_hash"] == expected_hash

    def test_serialize_disabled_capability(self, mock_registry):
        from aidn_hypervisor.model_onboarding.models import OnboardingCapability
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        cap = OnboardingCapability(
            node_id="node-002",
            operator_id="op-002",
            can_host_custom_model=False,
            supported_providers=[],
            installed_models=[],
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        record = publisher._serialize_capability(cap)

        assert record["payload"]["can_host_custom_model"] is False
        assert record["object_id"] == "onboarding_capability:node-002"


class TestCapabilityPublication:
    """Test publishing capabilities to the registry."""

    def test_publish_upserts_to_registry(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        result = publisher.publish(sample_capability)

        mock_registry.upsert_registry_object.assert_called_once()
        assert result is not None

    def test_publish_returns_record(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        result = publisher.publish(sample_capability)

        assert result["object_type"] == "onboarding_capability"
        assert result["object_version"] == 1

    def test_publish_increments_version_on_update(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)

        # First publish — version 1
        mock_registry.get_registry_object.return_value = None
        publisher.publish(sample_capability)

        # Second publish — version should be incremented
        mock_registry.get_registry_object.return_value = {
            "object_id": "onboarding_capability:node-001",
            "object_version": 1,
            "payload_hash": "old_hash",
        }
        mock_registry.upsert_registry_object.reset_mock()
        publisher.publish(sample_capability)

        # Check the record sent to upsert has version 2
        call_record = mock_registry.upsert_registry_object.call_args[0][0]
        assert call_record["object_version"] == 2

    def test_publish_skips_if_no_changes(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        record = publisher._serialize_capability(sample_capability)

        # Mock registry returns same payload hash
        mock_registry.get_registry_object.return_value = {
            "object_id": record["object_id"],
            "object_version": 5,
            "payload_hash": record["payload_hash"],
        }

        result = publisher.publish(sample_capability)
        assert result is None

    def test_publish_different_node_different_record(
        self, mock_registry
    ):
        from aidn_hypervisor.model_onboarding.models import OnboardingCapability
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        cap_a = OnboardingCapability(
            node_id="node-A",
            operator_id="op-A",
            can_host_custom_model=True,
            supported_providers=[],
            installed_models=[],
        )
        cap_b = OnboardingCapability(
            node_id="node-B",
            operator_id="op-B",
            can_host_custom_model=False,
            supported_providers=[],
            installed_models=[],
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        mock_registry.get_registry_object.return_value = None

        rec_a = publisher._serialize_capability(cap_a)
        rec_b = publisher._serialize_capability(cap_b)

        assert rec_a["object_id"] != rec_b["object_id"]
        assert rec_a["object_id"] == "onboarding_capability:node-A"
        assert rec_b["object_id"] == "onboarding_capability:node-B"


class TestCapabilityQuery:
    """Test querying onboarding capabilities from the registry."""

    def test_query_by_node_id(self, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        mock_registry.get_registry_object.return_value = {
            "object_id": "onboarding_capability:node-001",
            "object_type": "onboarding_capability",
            "payload": {
                "node_id": "node-001",
                "can_host_custom_model": True,
            },
        }

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        result = publisher.query_capability("node-001")

        assert result is not None
        assert result["node_id"] == "node-001"

    def test_query_returns_none_when_not_found(self, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        mock_registry.get_registry_object.return_value = None

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        result = publisher.query_capability("nonexistent")

        assert result is None

    def test_query_filters_by_can_host(self, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        mock_registry.list_registry_objects.return_value = [
            {
                "object_id": "onboarding_capability:node-A",
                "payload": {"can_host_custom_model": True, "node_id": "node-A"},
            },
            {
                "object_id": "onboarding_capability:node-B",
                "payload": {"can_host_custom_model": False, "node_id": "node-B"},
            },
            {
                "object_id": "onboarding_capability:node-C",
                "payload": {"can_host_custom_model": True, "node_id": "node-C"},
            },
        ]

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        result = publisher.list_capable_nodes()

        assert len(result) == 2
        assert result[0]["node_id"] == "node-A"
        assert result[1]["node_id"] == "node-C"


class TestCapabilitySubscription:
    """Test subscribing to onboarding capability changes."""

    def test_subscribe_registers_callback(self, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        callback = MagicMock()

        publisher.subscribe("node-001", callback)

        # Verify callback is registered
        assert "node-001" in publisher._subscribers
        assert callback in publisher._subscribers["node-001"]

    def test_publish_notifies_subscribers(self, sample_capability, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        callback = MagicMock()

        publisher.subscribe("node-001", callback)
        publisher.publish(sample_capability)

        callback.assert_called_once()
        assert callback.call_args[0][0]["node_id"] == "node-001"

    def test_unsubscribe_removes_callback(self, mock_registry):
        from aidn_hypervisor.model_onboarding.publisher import (
            OnboardingCapabilityPublisher,
        )

        publisher = OnboardingCapabilityPublisher(registry=mock_registry)
        callback = MagicMock()

        publisher.subscribe("node-001", callback)
        publisher.unsubscribe("node-001", callback)

        assert "node-001" not in publisher._subscribers or callback not in publisher._subscribers.get(
            "node-001", []
        )
