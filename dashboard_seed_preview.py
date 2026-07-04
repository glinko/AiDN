from datetime import datetime, timezone

from aidn_hypervisor.api import _registry_published_endpoint_summaries
from aidn_hypervisor.domain.models import BundleConfig, NodeCapacity, ResourceProfile
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.models import CreateEndpointCommand, UpdateEndpointCommand
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.main import build_app
from aidn_hypervisor.plugins.fake import FakeManagedPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.process_manager import RuntimeHandle
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
    endpoint: str | None = None,
    enabled: bool = True,
    priority_class: int = 50,
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
        resource_profile=ResourceProfile(),
        warm_policy="auto",
        priority_class=priority_class,
        enabled=enabled,
    )


def _build_service() -> HypervisorService:
    plugins = PluginRegistry()
    plugins.register(FakeManagedPlugin())
    resources = ResourceOrchestrator(
        NodeCapacity(
            cpu_cores=12.0,
            ram_mb=32768,
            gpu_devices=["gpu0"],
            vram_mb={"gpu0": 24576},
        )
    )
    resources.reserve("runtime-whisper-a", cpu=1.5, ram_mb=2048, vram_mb=1024)
    return HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=resources,
        bundles=[
            _bundle(
                "whisper-a",
                "speech_to_text",
                endpoint="http://127.0.0.1:9000/infer",
                priority_class=80,
            ),
            _bundle("text-a", "llm_text", priority_class=70),
            _bundle("vision-a", "llm_text", priority_class=60),
        ],
        plugins=plugins,
        runtimes=[
            RuntimeHandle(
                runtime_id="rt-1",
                bundle_id="whisper-a",
                command=["python", "-m", "http.server", "0"],
                status="running",
                health_status="healthy",
            )
        ],
        node_id="orion-7",
        operator_id="operator-orion",
        base_url="https://orion-7.local",
    )


def _seed_local_trust(
    *,
    service: HypervisorService,
    endpoint_service: EndpointService,
    publication_service: EndpointPublicationService,
    validation_service: ValidationService,
) -> None:
    service.configure_owner_wallet(mode="create", label="Orion Wallet")
    created = endpoint_service.create_endpoint(
        CreateEndpointCommand(
            owner_wallet=service.owner_wallet_state()["wallet_id"],
            bundle_id="text-a",
            bundle_hash="text-a",
            display_name="Legal Draft Copilot",
            model_class="llm_text",
            capabilities=["llm_text.generate"],
            publication={
                "visibility": "public",
                "discoverable": True,
                "accepts_external_requests": True,
            },
            session={"minimum_deposit": 25.0},
        )
    )
    publication_service.publish_configuration(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        node_id=service.node_id,
        wallet_private_key=service.owner_wallet_private_key(),
    )
    requested = validation_service.request_validation(
        endpoint_id=created.endpoint.endpoint_id,
        owner_wallet=created.endpoint.owner_wallet,
        configuration_hash=created.endpoint.configuration_hash,
        minimum_session_deposit_q=created.endpoint.session.minimum_deposit,
    )
    validation_service.force_mark_validated(
        request_id=requested.request.request_id,
        report_id="report-local-validated",
        validated_at="2026-07-03T00:00:00+00:00",
    )
    endpoint_service.update_endpoint(
        UpdateEndpointCommand(
            endpoint_id=created.endpoint.endpoint_id,
            runtime={"streaming": True, "timeout": 45},
        )
    )


def _seed_remote_registry(
    *,
    registry_service: RegistryService,
    remote_endpoint_service: RemoteEndpointService,
) -> None:
    heartbeat = datetime.now(timezone.utc).isoformat()
    registry_service.upsert_node(_remote_registry_advertisement(heartbeat))
    remote_endpoint_service.attach_remote_endpoint(
        source_node_id="aurora-compute",
        source_endpoint_id="ep-aurora-validated",
        source_owner_wallet="wallet-aurora",
        source_publication_id="pub-aurora-1",
        source_configuration_hash="cfg-aurora-1",
        source_visibility="public",
        source_model_class="llm_text",
        source_status="published",
        source_base_url="https://aurora.example",
        operator_id="operator-aurora",
        pricing={
            "unit": "q_per_1kk_tokens",
            "input": 392,
            "output": 518,
            "fixed_request": 2,
        },
        rating={
            "score": 0.98,
            "tier": "A+",
            "updated_at": heartbeat,
        },
        alias="Aurora Trusted Route",
    )


def _remote_registry_advertisement(heartbeat: str) -> RegistryNodeAdvertisement:
    return RegistryNodeAdvertisement(
        node_id="aurora-compute",
        operator_id="operator-aurora",
        base_url="https://aurora.example",
        heartbeat_at=heartbeat,
        resources={
            "total": {"cpu": 24.0, "ram_mb": 65536, "vram_mb": 81920},
            "free": {"cpu": 16.0, "ram_mb": 49152, "vram_mb": 65536},
        },
        providers=["fake"],
        can_host_custom_model=True,
        pricing={
            "unit": "q_per_1kk_tokens",
            "input": 392,
            "output": 518,
            "fixed_request": 2,
        },
        rating={
            "score": 0.98,
            "tier": "A+",
            "updated_at": heartbeat,
        },
        bundles=[
            {
                "bundle_id": "remote-text",
                "plugin_id": "fake-managed",
                "workload_type": "llm_text",
                "provider_type": "fake",
                "model_id": "llama-3.1-70b",
                "endpoint": "https://aurora.example/runtimes/remote-text",
                "enabled": True,
                "status": "ready",
                "launch_mode": "attached_service",
                "device_affinity": "gpu",
                "max_parallel_requests": 8,
                "supports_allocation": True,
                "supports_queue": True,
            }
        ],
        published_endpoints=[
            {
                "endpoint_id": "ep-aurora-validated",
                "owner_wallet": "wallet-aurora",
                "node_id": "aurora-compute",
                "current_publication_id": "pub-aurora-1",
                "current_configuration_hash": "cfg-aurora-1",
                "published_at": "2026-07-01T00:00:00+00:00",
                "status": "published",
                "visibility": "public",
                "model_class": "llm_text",
                "publication_sync_status": "in_sync",
                "published_validation_summary": {
                    "validation_status": "validated",
                    "configuration_hash": "cfg-aurora-1",
                },
            },
            {
                "endpoint_id": "ep-aurora-drift",
                "owner_wallet": "wallet-aurora",
                "node_id": "aurora-compute",
                "current_publication_id": "pub-aurora-2",
                "current_configuration_hash": "cfg-aurora-2",
                "published_at": "2026-07-02T00:00:00+00:00",
                "status": "published",
                "visibility": "public",
                "model_class": "llm_text",
                "publication_sync_status": "published_configuration_not_served",
                "published_validation_summary": {
                    "validation_status": "superseded",
                    "configuration_hash": "cfg-aurora-2",
                },
            },
        ],
    )


def _refresh_registry_projection(
    *,
    service: HypervisorService,
    endpoint_service: EndpointService,
    validation_service: ValidationService,
    registry_service: RegistryService,
) -> None:
    heartbeat = datetime.now(timezone.utc).isoformat()
    local_advertisement = service.node_advertisement(heartbeat_at=heartbeat)
    local_advertisement["published_endpoints"] = _registry_published_endpoint_summaries(
        advertisement=local_advertisement,
        endpoint_service=endpoint_service,
        validation_service=validation_service,
    )
    registry_service.upsert_node(RegistryNodeAdvertisement(**local_advertisement))
    registry_service.upsert_node(_remote_registry_advertisement(heartbeat))


def create_app():
    service = _build_service()
    endpoint_service = EndpointService(EndpointStore())
    publication_service = EndpointPublicationService(
        store=EndpointPublicationStore(),
        endpoint_service=endpoint_service,
    )
    validation_service = ValidationService(ValidationStore())
    remote_endpoint_service = RemoteEndpointService(RemoteEndpointStore())
    registry_service = RegistryService()

    _seed_local_trust(
        service=service,
        endpoint_service=endpoint_service,
        publication_service=publication_service,
        validation_service=validation_service,
    )

    local_advertisement = service.node_advertisement()
    local_advertisement["published_endpoints"] = _registry_published_endpoint_summaries(
        advertisement=local_advertisement,
        endpoint_service=endpoint_service,
        validation_service=validation_service,
    )
    registry_service.upsert_node(RegistryNodeAdvertisement(**local_advertisement))
    _seed_remote_registry(
        registry_service=registry_service,
        remote_endpoint_service=remote_endpoint_service,
    )

    app = build_app(
        service=service,
        registry_service=registry_service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=publication_service,
        remote_endpoint_service=remote_endpoint_service,
        validation_service=validation_service,
    )
    
    @app.middleware("http")
    async def refresh_seeded_registry(request, call_next):
        _refresh_registry_projection(
            service=service,
            endpoint_service=endpoint_service,
            validation_service=validation_service,
            registry_service=registry_service,
        )
        return await call_next(request)

    return app


app = create_app()
