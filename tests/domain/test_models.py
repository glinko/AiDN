import pytest
from pydantic import ValidationError

from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile, TaskRequest


def test_task_request_defaults_to_auto_mode() -> None:
    task = TaskRequest(task_type="llm_text.generate", payload={"prompt": "hi"})
    assert task.mode == "auto"


def test_bundle_config_rejects_missing_resource_profile() -> None:
    with pytest.raises(ValidationError) as exc_info:
        BundleConfig.model_validate(
            {
                "bundle_id": "phi4-ollama",
                "plugin_id": "ollama",
                "provider_type": "ollama",
                "workload_type": "llm_text",
                "model_id": "phi4",
                "launch_mode": "attached_service",
                "endpoint": "http://localhost:11434",
                "device_affinity": "cpu",
                "warm_policy": "auto",
                "priority_class": 50,
                "max_parallel_requests": 2,
                "enabled": True,
            }
        )

    assert "resource_profile" in str(exc_info.value)


def test_resource_profile_rejects_negative_values() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ResourceProfile(steady_ram_mb=-1)

    assert "steady_ram_mb" in str(exc_info.value)


def test_node_capacity_defaults_and_validates_resources() -> None:
    node = NodeCapacity(cpu_cores=4.0, ram_mb=8192)

    assert node.gpu_devices == []
    assert node.vram_mb == {}

    with pytest.raises(ValidationError):
        NodeCapacity(cpu_cores=-1.0, ram_mb=8192)
