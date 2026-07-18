from pathlib import Path

import pytest

from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.models import CreateEndpointCommand, UpdateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.model_store import FileModelStore
from aidn_hypervisor.operator_views import (
    build_operator_bundles_payload,
    build_operator_endpoints_payload,
    build_operator_home_payload,
    build_operator_installs_payload,
    build_operator_market_payload,
    build_operator_providers_payload,
    build_operator_remote_endpoints_payload,
)
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import ProviderProcessManager, RuntimeHandle
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.registry_models import RegistryNodeAdvertisement
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.remote_endpoints.service import RemoteEndpointService
from aidn_hypervisor.remote_endpoints.store import RemoteEndpointStore
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


def _empty_service() -> HypervisorService:
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
        bundles=[],
        plugins=PluginRegistry(),
        runtimes=ProviderProcessManager(),
    )


def _provider_only_service() -> HypervisorService:
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
        bundles=[],
        plugins=_registry(),
        runtimes=ProviderProcessManager(),
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
    assert payload["endpoint_pipeline"]["state"] == "no_endpoint"
    assert payload["endpoint_pipeline"]["primary_endpoint_id"] is None
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "create"


def test_home_payload_endpoint_pipeline_aligns_with_provider_setup_when_wallet_ready_but_no_inventory(
) -> None:
    service = _empty_service()
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    payload = build_operator_home_payload(
        service=service,
        endpoint_service=EndpointService(EndpointStore()),
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["bootstrap"]["next_step"] == "Attach a provider or install a model"
    assert payload["onboarding"]["current_step"] == "attach_provider"
    assert payload["endpoint_pipeline"]["state"] == "no_endpoint"
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "providers"
    assert payload["endpoint_pipeline"]["recommended_action"]["workspace"] == "providers"


def test_home_payload_endpoint_pipeline_aligns_with_bundle_setup_when_provider_exists_but_no_bundles(
) -> None:
    service = _provider_only_service()
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    payload = build_operator_home_payload(
        service=service,
        endpoint_service=EndpointService(EndpointStore()),
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["onboarding"]["current_step"] == "prepare_bundle"
    assert payload["endpoint_pipeline"]["state"] == "no_endpoint"
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "bundles"
    assert payload["endpoint_pipeline"]["recommended_action"]["workspace"] == "bundles"


def test_home_payload_endpoint_pipeline_ignores_persisted_completed_onboarding_when_no_endpoints_exist(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    service.sync_operator_onboarding_state(
        endpoint_items=[{"publication_status": "published"}]
    )

    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["onboarding"]["completed"] is True
    assert payload["onboarding"]["completed_at"] is not None
    assert payload["onboarding"]["completed_via"] == "first_local_endpoint_published"
    assert payload["endpoint_pipeline"]["state"] == "no_endpoint"
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] != "open-home"
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "create"
    assert payload["onboarding"]["current_step"] == "create_endpoint"
    assert payload["onboarding"]["workspace"] == "bundles"
    assert payload["onboarding"]["recommended_action"]["action"] == "create"


def test_home_payload_surfaces_endpoint_pipeline_for_first_draft(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["endpoint_pipeline"]["state"] == "draft_exists"
    assert (
        payload["endpoint_pipeline"]["primary_endpoint_id"]
        == created.endpoint.endpoint_id
    )
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "endpoints"
    assert (
        payload["bootstrap"]["next_step"]
        == "Review your configured endpoint and publish it"
    )


def test_home_payload_surfaces_drifted_publication_as_the_primary_attention_state(
    service: HypervisorService,
    endpoint_service: EndpointService,
    endpoint_publication_service: EndpointPublicationService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Published Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    endpoint_publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    endpoint_service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={"streaming": True},
        )
    )

    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["endpoint_pipeline"]["state"] == "published_drifted"
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "endpoints"
    assert (
        payload["endpoint_pipeline"]["recommended_action"]["workspace"]
        == "endpoints"
    )
    assert (
        payload["endpoint_pipeline"]["publication_sync_status"]
        == "local_changes_not_published"
    )
    assert (
        payload["bootstrap"]["next_step"]
        == "Publish your updated endpoint configuration to sync the live endpoint"
    )
    assert payload["onboarding"]["current_step"] == "publish_endpoint"
    assert payload["onboarding"]["workspace"] == "endpoints"
    assert payload["onboarding"]["recommended_action"]["action"] == "endpoints"


def test_home_payload_surfaces_in_sync_publication_as_operating_state(
    service: HypervisorService,
    endpoint_service: EndpointService,
    endpoint_publication_service: EndpointPublicationService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Published Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    endpoint_publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )

    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["endpoint_pipeline"]["state"] == "published_in_sync"
    assert (
        payload["endpoint_pipeline"]["primary_endpoint_id"]
        == created.endpoint.endpoint_id
    )
    assert payload["endpoint_pipeline"]["recommended_action"]["action"] == "endpoints"
    assert payload["onboarding"]["recommended_action"]["action"] == "endpoints"


def test_home_payload_prioritizes_drifted_endpoint_over_in_sync_endpoint(
    service: HypervisorService,
    endpoint_service: EndpointService,
    endpoint_publication_service: EndpointPublicationService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    drifted = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Drifted Text",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
        )
    )
    endpoint_publication_service.publish_configuration(
        endpoint_id=drifted.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    endpoint_service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=drifted.endpoint.endpoint_id,
            runtime={"streaming": True},
        )
    )
    in_sync = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="In Sync STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )
    endpoint_publication_service.publish_configuration(
        endpoint_id=in_sync.endpoint.endpoint_id,
        owner_wallet=service.owner_wallet_state()["wallet_id"],
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )

    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["endpoint_pipeline"]["state"] == "published_drifted"
    assert payload["endpoint_pipeline"]["primary_endpoint_id"] == drifted.endpoint.endpoint_id


def test_home_payload_exposes_onboarding_progress(
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

    assert payload["onboarding"]["current_step"] == "configure_wallet"
    assert payload["onboarding"]["recommended_action"]["action"] == "create-wallet"


def test_home_payload_exposes_canonical_service_overlay(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    service.runtimes = [
        RuntimeHandle(
            runtime_id="rt-1",
            command=["whisper"],
            status="running",
            bundle_id="whisper-a",
            health_status="healthy",
        )
    ]

    payload = build_operator_home_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
        market_candidates=[],
    )

    assert payload["canonical_overlay"]["services"][0]["kind"] == "compute"
    assert payload["canonical_overlay"]["runtimes"][0]["capability_id"] == "speech.stt"
    assert (
        payload["canonical_overlay"]["compatibility"][0]["legacy_bundle_id"]
        == "whisper-a"
    )


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


def test_endpoints_payload_includes_certification_status_and_legacy_validation_status(
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
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-1",
        validated_at="2026-07-10T00:00:00+00:00",
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
        payload["items"][0]["validation_summary"]["certification_status"]
        == "certified"
    )
    assert (
        payload["items"][0]["validation_summary"]["validation_status"]
        == "validated"
    )
    assert (
        payload["items"][0]["validation_summary"]["bond_state"]["bond_id"]
        == requested.bond.bond_id
    )


def test_endpoints_payload_marks_workspace_as_primary_control_plane(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    payload = build_operator_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
    )

    assert payload["workspace_role"] == "primary_control_plane"
    assert payload["recommended_action"]["workspace"] == "endpoints"
    assert payload["policy"]["validation_optional"] is True


def test_providers_payload_summarizes_plugins_and_bundle_state(
    service: HypervisorService,
) -> None:
    payload = build_operator_providers_payload(service=service)

    assert payload["summary"]["total"] == 1
    assert payload["summary"]["bundles"] == 2
    assert payload["items"][0]["plugin_id"] == "fake-managed"
    assert payload["items"][0]["bundle_count"] == 2
    assert payload["items"][0]["install_count"] == 0


def test_providers_payload_uses_plugin_first_empty_state() -> None:
    service = _empty_service()
    service.plugins.register(FakeManagedPlugin())

    payload = build_operator_providers_payload(service=service)

    assert payload["summary"]["total_plugins"] == 1
    assert payload["summary"]["total_provider_instances"] == 0
    assert payload["plugin_directory"][0]["plugin_id"] == "fake-managed"
    assert payload["provider_instances"] == []
    assert payload["model_deployments"] == []
    assert payload["runtime_bindings"] == []
    assert payload["empty_state"]["title"] == "No providers installed"
    assert payload["empty_state"]["primary_action"]["action"] == "browse_provider_plugins"
    assert payload["empty_state"]["secondary_action"]["action"] == "attach_provider"


def test_providers_payload_exposes_plugin_directory_install_metadata() -> None:
    service = _empty_service()
    service.plugins.register(FakeManagedPlugin())

    payload = build_operator_providers_payload(service=service)
    plugin = payload["plugin_directory"][0]

    assert plugin["trust_status"] == "CONFORMANCE_TESTED"
    assert plugin["package_verification"]["status"] == "VERIFIED"
    assert plugin["package_verification"]["verification_mode"] == "ED25519"
    assert plugin["sandbox_policy"]["execution_mode"] == "RECORDED_ONLY"
    assert plugin["required_permissions"][0]["permission_id"] == "network.private"
    assert plugin["install_ui_schema"]["schema_id"] == "fake.install.v1"
    assert plugin["secret_requirements"][0]["secret_type"] == "API_KEY"
    assert plugin["installation_recipes"][0]["recipe_id"] == "fake-managed-local"
    assert payload["installation_executor"]["executor_id"] == "sandbox-enforced-declarative-v1"
    assert (
        payload["installation_executor"]["sandbox_capabilities"]["supported_execution_modes"]
        == ["RECORDED_ONLY", "SANDBOX_REQUIRED"]
    )
    assert payload["summary"]["installable_plugin_count"] == 1


def test_provider_workspace_payload_includes_installation_apply_summary() -> None:
    service = _provider_only_service()
    approval = service.approve_provider_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
    )
    job = service.apply_provider_installation_approval(approval["approval_id"])

    payload = build_operator_providers_payload(service=service)

    assert payload["summary"]["approved_installation_count"] == 1
    assert payload["summary"]["installation_job_count"] == 1
    assert (
        payload["installation_approvals"][0]["status_label"]
        == "Applied with controlled executor"
    )
    assert (
        payload["installation_approvals"][0]["acknowledged_sandbox_policy"]["execution_mode"]
        == "RECORDED_ONLY"
    )
    assert (
        payload["installation_approvals"][0]["acknowledged_package_verification"]["status"]
        == "VERIFIED"
    )
    assert payload["installation_approvals"][0]["upgrade_review"]["status"] == "INITIAL_APPROVAL"
    assert payload["installation_approvals"][0]["upgrade_acknowledged"] is False
    assert payload["installation_jobs"][0]["job_id"] == job["job_id"]
    assert payload["installation_jobs"][0]["status"] == "SUCCEEDED"


def test_provider_workspace_payload_exposes_installation_rollback_state() -> None:
    service = _provider_only_service()
    approval = service.approve_provider_installation_plan(
        plugin_id="fake-managed",
        configuration={
            "display_name": "Local Fake",
            "base_url": "http://127.0.0.1:9999",
        },
    )
    job = service.apply_provider_installation_approval(approval["approval_id"])
    service.rollback_provider_installation_job(job["job_id"])

    payload = build_operator_providers_payload(service=service)

    assert payload["installation_jobs"][0]["job_id"] == job["job_id"]
    assert payload["installation_jobs"][0]["rollback_status"] == "COMPLETED"
    assert payload["installation_jobs"][0]["rollback_step_results"][-1]["step_id"] == (
        "rollback-delete-local-provider-instance"
    )


def test_providers_payload_exposes_models_and_runtime_binding_readiness() -> None:
    service = _provider_only_service()
    attached = service.attach_provider_instance(
        plugin_id="fake-managed",
        display_name="Local Fake",
        configuration={"base_url": "http://127.0.0.1:9999"},
    )
    models = service.discover_provider_models(attached["provider_instance_id"])
    binding = service.create_runtime_binding(
        model_deployment_id=models[0]["model_deployment_id"],
        capability_id="llm.chat",
        capability_version="1.0.0",
        capability_definition_hash="cap-hash",
    )

    payload = build_operator_providers_payload(service=service)

    instance = payload["provider_instances"][0]
    assert instance["provider_instance_id"] == attached["provider_instance_id"]
    assert instance["model_count"] == 1
    assert instance["runtime_binding_ready_count"] == 1
    assert payload["model_deployments"][0]["provider_instance_id"] == attached["provider_instance_id"]
    assert payload["runtime_bindings"][0]["runtime_binding_id"] == binding["runtime_binding_id"]
    assert payload["summary"]["total_provider_instances"] == 1
    assert payload["summary"]["total_model_deployments"] == 1
    assert payload["summary"]["total_runtime_bindings"] == 1
    assert payload["recommended_action"]["action"] == "create_endpoint"


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


def test_providers_payload_prefers_endpoint_handoff_once_local_supply_is_usable(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")

    payload = build_operator_providers_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
    )

    assert payload["summary"]["endpoint_ready_bundles"] == 2
    assert payload["recommended_action"]["action"] == "create_endpoint"
    assert payload["recommended_action"]["workspace"] == "endpoints"


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


def test_bundles_payload_marks_current_onboarding_workspace(
    service: HypervisorService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")

    payload = build_operator_bundles_payload(service=service)

    assert payload["onboarding"]["workspace"] == "bundles"
    assert payload["onboarding"]["current_step"] == "create_endpoint"
    assert "steps" in payload["onboarding"]


def test_bundles_payload_exposes_endpoint_relationship_states(
    service: HypervisorService,
    endpoint_service: EndpointService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Primary Wallet")
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="whisper-a",
            bundle_hash="whisper-a",
            display_name="Operator STT",
            model_class="speech.stt",
            capabilities=["speech.stt"],
        )
    )

    payload = build_operator_bundles_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=None,
        validation_service=None,
    )

    whisper = next(item for item in payload["items"] if item["bundle_id"] == "whisper-a")
    text = next(item for item in payload["items"] if item["bundle_id"] == "text-a")
    assert whisper["endpoint_relationship"]["state"] == "draft_endpoint"
    assert (
        whisper["endpoint_relationship"]["recommended_action"]["endpoint_id"]
        == created.endpoint.endpoint_id
    )
    assert whisper["endpoint_action"]["recommended"] == "open_endpoint"
    assert text["endpoint_relationship"]["state"] == "no_endpoint"
    assert text["endpoint_action"]["recommended"] == "create_endpoint"


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


def test_market_payload_builder_preserves_candidate_surfaces(
    service: HypervisorService,
) -> None:
    payload = build_operator_market_payload(service=service, registry_service=None)

    assert "nodes" in payload
    assert "candidates" in payload
    assert "canonical_candidates" in payload
    assert "canonical_summary" in payload
    assert payload["recommended_action"]["workspace"] == "endpoints"


def test_remote_endpoints_payload_summarizes_attached_and_discovered_routes(
    service: HypervisorService,
) -> None:
    registry = RegistryService()
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-remote",
            operator_id="operator-remote",
            base_url="https://remote.example",
            heartbeat_at="2026-07-06T12:00:00+00:00",
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
                "free": {"cpu": 10.0, "ram_mb": 28672, "vram_mb": 12288},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={"unit": "q_per_1kk_tokens", "input": 7, "output": 11, "fixed_request": 1},
            rating={"score": 0.98, "tier": "A", "updated_at": "2026-07-06T11:55:00+00:00"},
            bundles=[],
            published_endpoints=[
                {
                    "endpoint_id": "endpoint-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-remote",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-07-06T11:50:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                    "publication_sync_status": "in_sync",
                    "published_validation_summary": {"validation_status": "validated"},
                    "live_validation_summary": {"validation_status": "validated"},
                }
            ],
        )
    )
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    remote_endpoint_service.attach_remote_endpoint(
        source_node_id="node-remote",
        source_endpoint_id="endpoint-remote",
        source_owner_wallet="wallet-remote",
        source_publication_id="pub-remote",
        source_configuration_hash="cfg-remote",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://remote.example",
        operator_id="operator-remote",
        pricing={"unit": "q_per_1kk_tokens", "input": 7, "output": 11},
        rating={"score": 0.98, "tier": "A", "updated_at": "2026-07-06T11:55:00+00:00"},
    )

    payload = build_operator_remote_endpoints_payload(
        service=service,
        registry_service=registry,
        remote_endpoint_service=remote_endpoint_service,
    )

    assert payload["summary"]["attached"] == 1
    assert payload["summary"]["discovered"] == 1
    assert payload["policy"]["proxy_ready"] is True
    assert payload["discovered"][0]["publication_sync_status"] == "in_sync"
    assert payload["recommended_action"]["action"] == "stage_proxy_route"
    assert payload["recommended_action"]["workspace"] == "endpoints"


def test_remote_endpoints_payload_prefers_attachment_when_only_discovered_routes_exist(
    service: HypervisorService,
) -> None:
    registry = RegistryService()
    registry.upsert_node(
        RegistryNodeAdvertisement(
            node_id="node-remote",
            operator_id="operator-remote",
            base_url="https://remote.example",
            heartbeat_at="2026-07-06T12:00:00+00:00",
            resources={
                "total": {"cpu": 12.0, "ram_mb": 32768, "vram_mb": 16384},
                "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
                "free": {"cpu": 10.0, "ram_mb": 28672, "vram_mb": 12288},
            },
            providers=["fake"],
            can_host_custom_model=True,
            pricing={"unit": "q_per_1kk_tokens", "input": 7, "output": 11, "fixed_request": 1},
            rating={"score": 0.98, "tier": "A", "updated_at": "2026-07-06T11:55:00+00:00"},
            bundles=[],
            published_endpoints=[
                {
                    "endpoint_id": "endpoint-remote",
                    "owner_wallet": "wallet-remote",
                    "node_id": "node-remote",
                    "current_publication_id": "pub-remote",
                    "current_configuration_hash": "cfg-remote",
                    "published_at": "2026-07-06T11:50:00+00:00",
                    "status": "published",
                    "visibility": "public",
                    "model_class": "llm_text",
                }
            ],
        )
    )

    payload = build_operator_remote_endpoints_payload(
        service=service,
        registry_service=registry,
        remote_endpoint_service=RemoteEndpointService(RemoteEndpointStore()),
    )

    assert payload["summary"]["attached"] == 0
    assert payload["summary"]["discovered"] == 1
    assert payload["recommended_action"]["action"] == "attach_remote_endpoint"
    assert payload["recommended_action"]["workspace"] == "remote"


def test_api_uses_only_public_operator_view_builders() -> None:
    api_source = Path("src/aidn_hypervisor/api.py").read_text(encoding="utf-8")

    assert "_build_operator_home_bootstrap_payload" not in api_source
    assert "return build_operator_home_payload(" in api_source
