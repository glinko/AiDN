from aidn_hypervisor import canonical_projection
from aidn_hypervisor.canonical_projection import (
    project_capability_runtimes,
    project_compute_compatibility,
    project_protocol_services,
)
from aidn_hypervisor.endpoint_publications.models import (
    PublishedEndpointConfiguration,
    canonical_configuration_payload,
    configuration_hash_for_publication,
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


def _publication(
    publication_id: str,
    *,
    status: str = "published",
    capabilities: list[str] | None = None,
    publication: dict | None = None,
) -> PublishedEndpointConfiguration:
    capabilities = capabilities or []
    publication = publication or {}
    payload = canonical_configuration_payload(
        bundle_hash="bundle-hash-a",
        model_class="llm.chat",
        capabilities=capabilities,
        runtime={"streaming": True},
        publication=publication,
        pricing={"billing_unit": "request"},
    )
    return PublishedEndpointConfiguration(
        schema_version="epcfg.v1",
        publication_id=publication_id,
        endpoint_id=f"ep-{publication_id}",
        owner_wallet="wallet-1",
        node_id="node-1",
        configuration_hash=configuration_hash_for_publication(payload),
        previous_configuration_hash=None,
        bundle_id="bundle-a",
        bundle_hash="bundle-hash-a",
        model_class="llm.chat",
        capabilities=capabilities,
        profile={"summary": "Operator endpoint"},
        runtime={"streaming": True},
        publication=publication,
        pricing={"billing_unit": "request"},
        validation_requirement={"enabled": False},
        published_at="2026-07-01T00:00:00+00:00",
        sequence=1,
        status=status,
        wallet_signature=f"sig-{publication_id}",
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


def test_project_canonical_advertisements_maps_published_records() -> None:
    records = canonical_projection.project_canonical_advertisements(
        [
            _publication(
                "pub-1",
                capabilities=["llm.chat", "llm.embed"],
                publication={"visibility": "public", "discoverable": True},
            )
        ]
    )

    assert [record.model_dump() for record in records] == [
        {
            "advertisement_id": "adv-pub-1",
            "resource_type": "endpoint",
            "owner_wallet": "wallet-1",
            "hypervisor_id": "node-1",
            "capability_id": "llm.chat",
            "visibility": "public",
            "signature_scope": "configuration_publication",
        }
    ]


def test_project_canonical_advertisements_filters_unpublished_and_defaults_visibility() -> None:
    records = canonical_projection.project_canonical_advertisements(
        [
            _publication("pub-1", publication={"visibility": "shared"}),
            _publication("pub-2", status="superseded", capabilities=["speech.stt"]),
            _publication("pub-3"),
        ]
    )

    assert [record.advertisement_id for record in records] == ["adv-pub-1", "adv-pub-3"]
    assert records[0].visibility == "shared"
    assert records[1].visibility == "private"
    assert records[1].capability_id is None


def test_project_canonical_advertisements_uses_first_stored_capability_as_primary() -> None:
    records = canonical_projection.project_canonical_advertisements(
        [
            _publication(
                "pub-ordered",
                capabilities=["speech.translate", "speech.stt"],
            )
        ]
    )

    assert len(records) == 1
    assert records[0].capability_id == "speech.translate"
