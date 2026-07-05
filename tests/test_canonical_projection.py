from aidn_hypervisor.canonical_projection import (
    project_capability_runtimes,
    project_compute_compatibility,
    project_protocol_services,
)
from aidn_hypervisor.domain.models import BundleConfig, ResourceProfile
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


def _bundle(bundle_id: str, workload_type: str) -> BundleConfig:
    return BundleConfig(
        bundle_id=bundle_id,
        plugin_id="fake-managed",
        provider_type="fake",
        workload_type=workload_type,
        model_id=f"{bundle_id}-model",
        launch_mode="managed_process",
        device_affinity="cpu",
        resource_profile=ResourceProfile(),
        warm_policy="auto",
    )


def _service() -> HypervisorService:
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        bundles=[
            _bundle("text-a", "llm_text"),
            _bundle("whisper-a", "speech_to_text"),
        ],
        runtimes=[
            RuntimeHandle(
                runtime_id="rt-whisper",
                command=["whisper"],
                status="running",
                bundle_id="whisper-a",
                health_status="healthy",
            )
        ],
    )


def test_project_protocol_services_marks_compute_enabled_by_default() -> None:
    records = project_protocol_services(_service())

    assert [record.kind for record in records] == [
        "compute",
        "registry",
        "validation",
        "consensus",
    ]
    assert records[0].enabled is True
    assert "endpoint_hosting" in records[0].responsibilities


def test_project_capability_runtimes_maps_bundle_runtime_to_canonical_runtime() -> None:
    records = project_capability_runtimes(_service())

    whisper = next(record for record in records if record.capability_id == "speech.stt")
    assert whisper.runtime_id == "runtime-whisper-a"
    assert whisper.location_kind == "local_process"


def test_project_compute_compatibility_preserves_legacy_bundle_identity() -> None:
    records = project_compute_compatibility(_service())

    whisper = next(record for record in records if record.legacy_bundle_id == "whisper-a")
    assert whisper.legacy_plugin_id == "fake-managed"
    assert whisper.canonical_runtime_id == "runtime-whisper-a"
