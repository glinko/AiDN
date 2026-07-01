import os

from fastapi import FastAPI

from aidn_hypervisor.api import build_api_router
from aidn_hypervisor.bundle_registry import FileBundleRegistry
from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.api import build_endpoint_router
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.plugins.ollama import OllamaPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.plugins.whisper import WhisperPlugin
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.registry_api import build_registry_router
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.remote_endpoints.service import RemoteEndpointService
from aidn_hypervisor.remote_endpoints.store import RemoteEndpointStore
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore


def build_app(
    service: HypervisorService | None = None,
    registry_service: RegistryService | None = None,
    endpoint_service: EndpointService | None = None,
    endpoint_publication_service: EndpointPublicationService | None = None,
    remote_endpoint_service: RemoteEndpointService | None = None,
    session_service: SessionService | None = None,
) -> FastAPI:
    app = FastAPI(
        title="AiDN Hypervisor",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    state_store = _default_state_store()
    resolved_service = service or _build_default_service(state_store=state_store)
    resolved_endpoint_service = endpoint_service or _build_default_endpoint_service(
        state_store=state_store
    )
    resolved_endpoint_publication_service = (
        endpoint_publication_service
        or _build_default_endpoint_publication_service(
            state_store=state_store,
            endpoint_service=resolved_endpoint_service,
        )
    )
    resolved_remote_endpoint_service = (
        remote_endpoint_service
        or _build_default_remote_endpoint_service(state_store=state_store)
    )
    resolved_session_service = (
        session_service or _build_default_session_service(state_store=state_store)
    )
    resolved_service.endpoint_publication_service = (
        resolved_endpoint_publication_service
    )
    resolved_service.endpoint_service = resolved_endpoint_service
    resolved_service.remote_endpoint_service = resolved_remote_endpoint_service
    resolved_service.session_service = resolved_session_service
    resolved_session_service.event_recorder = resolved_service.record_event

    app.include_router(
        build_api_router(
            resolved_service,
            registry_service=registry_service,
            endpoint_service=resolved_endpoint_service,
            endpoint_publication_service=resolved_endpoint_publication_service,
            remote_endpoint_service=resolved_remote_endpoint_service,
            session_service=resolved_session_service,
        )
    )
    app.include_router(
        build_endpoint_router(
            resolved_endpoint_service,
            remote_endpoint_service=resolved_remote_endpoint_service,
            session_service=resolved_session_service,
        )
    )

    return app


def build_registry_app(service: RegistryService | None = None) -> FastAPI:
    app = FastAPI(
        title="AiDN Registry",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(build_registry_router(service or RegistryService()))

    return app


def _build_default_service(
    state_store: FileStateStore | None = None,
) -> HypervisorService:
    if state_store is None:
        state_store = _default_state_store()
    plugins = PluginRegistry()
    plugins.register(LlamaCppPlugin())
    plugins.register(OllamaPlugin())
    plugins.register(WhisperPlugin())
    bundles = _default_bundle_registry(plugins).load(plugins)
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(NodeCapacity(cpu_cores=0.0, ram_mb=0)),
        bundles=bundles,
        plugins=plugins,
        runtimes=ProviderProcessManager(enable_subprocesses=True),
        state_store=state_store,
        bundle_registry=_default_bundle_registry(plugins),
    )
    if state_store is not None:
        service.restore_state(state_store.load())
    return service


def _build_default_endpoint_service(
    state_store: FileStateStore | None = None,
) -> EndpointService:
    if state_store is None:
        state_store = _default_state_store()
    return EndpointService(EndpointStore(state_store))


def _build_default_endpoint_publication_service(
    *,
    state_store: FileStateStore | None = None,
    endpoint_service: EndpointService,
) -> EndpointPublicationService:
    if state_store is None:
        state_store = _default_state_store()
    return EndpointPublicationService(
        store=EndpointPublicationStore(state_store),
        endpoint_service=endpoint_service,
    )


def _build_default_remote_endpoint_service(
    *,
    state_store: FileStateStore | None = None,
) -> RemoteEndpointService:
    if state_store is None:
        state_store = _default_state_store()
    return RemoteEndpointService(RemoteEndpointStore(state_store))


def _build_default_session_service(
    *,
    state_store: FileStateStore | None = None,
) -> SessionService:
    if state_store is None:
        state_store = _default_state_store()
    return SessionService(SessionStore(state_store))


def _default_state_store() -> FileStateStore | None:
    state_path = os.getenv("AIDN_HYPERVISOR_STATE_PATH")
    if not state_path:
        return None
    return FileStateStore(state_path)


def _default_bundle_registry(plugins: PluginRegistry) -> FileBundleRegistry:
    bundle_path = os.getenv("AIDN_HYPERVISOR_BUNDLES_PATH")
    if not bundle_path:
        bundle_path = os.path.join(os.getcwd(), "bundles.json")
    return FileBundleRegistry(bundle_path)
