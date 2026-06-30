import os

from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi import FastAPI

from aidn_hypervisor.api import build_api_router
from aidn_hypervisor.bundle_registry import FileBundleRegistry
from aidn_hypervisor.endpoints.api import (
    ENDPOINT_API_PREFIX,
    build_endpoint_router,
    validation_error,
)
from aidn_hypervisor.endpoints.runtime_adapter import EndpointRuntimeAdapter
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.plugins.ollama import OllamaPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.plugins.whisper import WhisperPlugin
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.registry_api import build_registry_router
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService


def build_app(
    service: HypervisorService | None = None,
    registry_service: RegistryService | None = None,
    endpoint_service: EndpointService | None = None,
) -> FastAPI:
    shared_state_store = _default_state_store()
    resolved_service = service or _build_default_service(shared_state_store)
    endpoint_state_store = getattr(resolved_service, "state_store", None)
    if endpoint_state_store is None:
        endpoint_state_store = shared_state_store
    resolved_endpoint_service = endpoint_service or _build_default_endpoint_service(
        endpoint_state_store,
        hypervisor_service=resolved_service,
    )
    app = FastAPI(
        title="AiDN Hypervisor",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(request, exc):
        if request.url.path.startswith(ENDPOINT_API_PREFIX):
            return validation_error(request)
        return await request_validation_exception_handler(request, exc)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(
        build_api_router(
            resolved_service,
            registry_service=registry_service,
        )
    )
    app.include_router(build_endpoint_router(resolved_endpoint_service))

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


def _build_default_endpoint_service(
    state_store: FileStateStore | None = None,
    hypervisor_service: HypervisorService | None = None,
) -> EndpointService:
    runtime_adapter = (
        EndpointRuntimeAdapter(hypervisor_service)
        if hypervisor_service is not None
        else None
    )
    if state_store is not None:
        return EndpointService(
            EndpointStore(state_store),
            runtime_adapter=runtime_adapter,
        )
    return EndpointService(
        EndpointStore(allow_in_memory=True),
        runtime_adapter=runtime_adapter,
    )
