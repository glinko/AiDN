from pathlib import Path

import pytest

from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.models import CreateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.model_store import FileModelStore
from aidn_hypervisor.operator_views import (
    build_operator_bundles_payload,
    build_operator_endpoints_payload,
    build_operator_home_payload,
    build_operator_installs_payload,
    build_operator_providers_payload,
)
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


def _bundle(
    bundle_id: str,
    workload_type: str,
    *,
    resource_profile: ResourceProfile | None = None,
    priority_class: int = 50,
    enabled: bool = True,
    endpoint: str | None = None,
) -> BundleConfig:
    return BundleConfig(
        bundle_id=bundle_id,
        plugin_id="fake-managed",
        provider_type="fake",
        workload_type=workload_type,
        model_id=f"{bundle_id}-model",
        launch_mode="managed_process",
        endpoint=endpoint,
        device_affinity="cpu",
        resource_profile=resource_profile or ResourceProfile(),
        warm_policy="auto",
        priority_class=priority_class,
        enabled=enabled,
    )


def _registry() -> PluginRegistry:
    registry = PluginRegistry()
    registry.register(FakeManagedPlugin())
    return registry


def _service_with_model_store(tmp_path: Path) -> HypervisorService:
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(
                cpu_cores=8.0,
                ram_mb=16384,
                gpu_devices=["gpu0"],
                vram_mb={"gpu0": 8192},
            )
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(steady_vram_mb=1024),
                priority_class=80,
                endpoint="http://127.0.0.1:9000",
            ),
            _bundle("text-a", "llm_text", priority_class=60),
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
        model_store=FileModelStore(tmp_path),
    )


@pytest.fixture
def service() -> HypervisorService:
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            NodeCapacity(
                cpu_cores=8.0,
                ram_mb=16384,
                gpu_devices=["gpu0"],
                vram_mb={"gpu0": 8192},
            )
        ),
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                resource_profile=ResourceProfile(steady_vram_mb=1024),
                priority_class=80,
                endpoint="http://127.0.0.1:9000",
            ),
            _bundle("text-a", "llm_text", priority_class=60),
        ],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
    )


@pytest.fixture
def endpoint_service() -> EndpointService:
    return EndpointService(EndpointStore())


@pytest.fixture
def endpoint_publication_service(
    endpoint_service: EndpointService,
) -> EndpointPublicationService:
    return EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )


@pytest.fixture
def validation_service() -> ValidationService:
    return ValidationService(ValidationStore())


def test_home_payload_requires_wallet_before_network_actions(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["bootstrap"]["wallet_ready"] is False
    assert payload["bootstrap"]["next_step"] == "Create or import a wallet"


def test_home_payload_prefers_first_endpoint_candidate_after_wallet_setup(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")

    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["bootstrap"]["wallet_ready"] is True
    assert payload["bootstrap"]["first_endpoint_candidate"]["bundle_id"] == "whisper-a"
    assert payload["bootstrap"]["next_step"] == "Create your first endpoint from whisper-a"


def test_home_payload_rebuilds_operator_shell_blocks_from_factual_service_summary(
    tmp_path: Path,
) -> None:
    service = _service_with_model_store(tmp_path)
    service.request_model_install(
        provider_type="fake",
        model_id="phi4-gguf",
        source_url="https://example.invalid/models/phi4.gguf",
        requested_by="operator-a",
    )

    payload = build_operator_home_payload(
        service=service,
        endpoint_service=EndpointService(EndpointStore()),
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["publish"]["draft_offer_count"] == 2
    assert payload["publish"]["install_pending_count"] == 1
    assert payload["publish"]["live_offer_count"] == 2
    assert payload["market_visibility"]["local_offer_count"] == 2
    assert payload["fleet_capacity"]["node_count"] == 1
    assert "Publish Offer" in payload["operator_controls"]["actions"]


def test_endpoints_payload_includes_publication_sync_and_validation_summary(
    service: HypervisorService,
    endpoint_service: EndpointService,
    endpoint_publication_service: EndpointPublicationService,
    validation_service: ValidationService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Validated Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            session={"minimum_deposit": 25.0},
        )
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )

    payload = build_operator_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
    )

    assert payload["summary"]["total"] == 1
    assert payload["items"][0]["publication_sync_status"] == "never_published"
    assert (
        payload["items"][0]["validation_summary"]["validation_status"]
        == "pending_initial"
    )
    assert (
        payload["items"][0]["validation_summary"]["bond_state"]["bond_id"]
        == requested.bond.bond_id
    )


def test_providers_payload_summarizes_plugins_and_bundle_state(
    service: HypervisorService,
) -> None:
    payload = build_operator_providers_payload(service=service)

    assert payload["summary"]["total"] == 1
    assert payload["summary"]["bundles"] == 2
    assert payload["items"][0]["plugin_id"] == "fake-managed"
    assert payload["items"][0]["bundle_count"] == 2
    assert payload["items"][0]["install_count"] == 0


def test_providers_payload_matches_install_aliases_from_bundle_provider_type(
    tmp_path: Path,
) -> None:
    service = _service_with_model_store(tmp_path)
    service.request_model_install(
        provider_type="fake",
        model_id="qwen-2.5",
        source_url="https://example.com/models/qwen-2.5.gguf",
        requested_by="wallet-operator",
    )

    payload = build_operator_providers_payload(service=service)

    assert payload["items"][0]["plugin_id"] == "fake-managed"
    assert payload["items"][0]["install_count"] == 1


def test_bundles_payload_marks_first_endpoint_candidate(
    service: HypervisorService,
) -> None:
    payload = build_operator_bundles_payload(service=service)

    assert payload["summary"]["total"] == 2
    assert any(item["is_first_endpoint_candidate"] for item in payload["items"])
    candidate = next(
        item for item in payload["items"] if item["is_first_endpoint_candidate"]
    )
    assert candidate["bundle_id"] == "whisper-a"
    assert candidate["endpoint_action"]["recommended"] == "create_endpoint"


def test_installs_payload_exposes_ready_to_register_completed_jobs(
    tmp_path: Path,
) -> None:
    service = _service_with_model_store(tmp_path)
    install = service.request_model_install(
        provider_type="fake",
        model_id="llama-3.1-8b",
        source_url="https://example.com/models/llama-3.1-8b.gguf",
        requested_by="wallet-operator",
    )
    service.mark_model_install_completed(install["install_id"])

    payload = build_operator_installs_payload(service=service)

    assert payload["summary"]["total"] == 1
    assert payload["summary"]["ready_to_register"] == 1
    assert payload["items"][0]["install_id"] == install["install_id"]
    assert payload["items"][0]["can_register_bundle"] is True
    assert payload["items"][0]["next_action"] == "register_bundle"


def test_api_uses_only_public_operator_view_builders() -> None:
    api_source = Path("src/aidn_hypervisor/api.py").read_text(encoding="utf-8")

    assert "_build_operator_home_bootstrap_payload" not in api_source
    assert "return build_operator_home_payload(" in api_source
