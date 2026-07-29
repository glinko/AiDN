import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from aidn_hypervisor.api import build_api_router
from aidn_hypervisor.bundle_registry import FileBundleRegistry
from aidn_hypervisor.consensus.service import (
    ConsensusMode,
    ConsensusService,
    ConsensusServiceConfig,
)
from aidn_hypervisor.domain.models import NodeCapacity
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.api import build_endpoint_router
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.plugins.ollama import OllamaPlugin
from aidn_hypervisor.plugins.proxy_openai import ProxyOpenAIPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.plugins.vllm import VllmPlugin
from aidn_hypervisor.plugins.whisper import WhisperPlugin
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.registry.runtime import RegistryReplicationRuntime
from aidn_hypervisor.registry_api import build_registry_router
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.remote_endpoints.service import RemoteEndpointService
from aidn_hypervisor.remote_endpoints.store import RemoteEndpointStore
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore
from aidn_hypervisor.validation.custody_signing import (
    Ed25519ValidationReportCustodySigner,
)
from aidn_hypervisor.validation.custody_store import ValidationReportCustodyStore
from aidn_hypervisor.validation.service import ValidationService
from aidn_hypervisor.validation.store import ValidationStore


def build_app(
    service: HypervisorService | None = None,
    registry_service: RegistryService | None = None,
    endpoint_service: EndpointService | None = None,
    endpoint_publication_service: EndpointPublicationService | None = None,
    remote_endpoint_service: RemoteEndpointService | None = None,
    session_service: SessionService | None = None,
    validation_service: ValidationService | None = None,
    consensus_service: ConsensusService | None = None,
    registry_replication_runtime: RegistryReplicationRuntime | None = None,
) -> FastAPI:
    state_store = _default_state_store()
    resolved_registry_service = registry_service or _build_default_registry_service(
        state_store=state_store
    )
    resolved_service = service or _build_default_service(
        state_store=state_store,
        registry_service=resolved_registry_service,
    )
    resolved_registry_service.bind_ledger_operation_service(
        resolved_service.ledger_operation_service
    )
    bound_endpoint_publication_service = getattr(
        resolved_service, "endpoint_publication_service", None
    )
    resolved_endpoint_service = (
        endpoint_service
        or getattr(resolved_service, "endpoint_service", None)
        or getattr(bound_endpoint_publication_service, "endpoint_service", None)
        or _build_default_endpoint_service(state_store=state_store)
    )
    resolved_endpoint_publication_service = (
        endpoint_publication_service
        or bound_endpoint_publication_service
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
        session_service
        or _build_default_session_service(
            state_store=state_store,
            registry_service=resolved_registry_service,
        )
    )
    resolved_validation_service = (
        validation_service
        or _build_default_validation_service(state_store=state_store)
    )
    resolved_service.bind_external_services(
        registry_service=resolved_registry_service,
        endpoint_service=resolved_endpoint_service,
        endpoint_publication_service=resolved_endpoint_publication_service,
        remote_endpoint_service=resolved_remote_endpoint_service,
        session_service=resolved_session_service,
        validation_service=resolved_validation_service,
    )
    resolved_consensus_service = consensus_service or getattr(
        resolved_service, "consensus_service", None
    )
    if resolved_consensus_service is None:
        resolved_consensus_service = _build_default_consensus_service(
            hypervisor_service=resolved_service,
            state_store=state_store,
        )
    elif (
        getattr(resolved_service, "consensus_service", None) not in {
            None,
            resolved_consensus_service,
        }
    ):
        raise ValueError("Hypervisor is already bound to another ConsensusService")
    if resolved_consensus_service is not None:
        resolved_service.consensus_service = resolved_consensus_service

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if registry_replication_runtime is not None:
            registry_replication_runtime.start()
        if (
            resolved_consensus_service is not None
            and resolved_consensus_service.is_validator
        ):
            resolved_consensus_service.start_validator_abci_server()
        try:
            yield
        finally:
            if resolved_consensus_service is not None:
                resolved_consensus_service.stop_validator_abci_server()
            if registry_replication_runtime is not None:
                registry_replication_runtime.stop()

    app = FastAPI(
        title="AiDN Hypervisor",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.hypervisor_service = resolved_service
    app.state.consensus_service = resolved_consensus_service
    app.state.registry_replication_runtime = registry_replication_runtime

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(
        build_api_router(
            resolved_service,
            registry_service=resolved_registry_service,
            endpoint_service=resolved_endpoint_service,
            endpoint_publication_service=resolved_endpoint_publication_service,
            remote_endpoint_service=resolved_remote_endpoint_service,
            session_service=resolved_session_service,
            validation_service=resolved_validation_service,
        )
    )
    app.include_router(
        build_endpoint_router(
            resolved_endpoint_service,
            hypervisor_service=resolved_service,
            endpoint_publication_service=resolved_endpoint_publication_service,
            remote_endpoint_service=resolved_remote_endpoint_service,
            session_service=resolved_session_service,
            validation_service=resolved_validation_service,
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
    registry_service: RegistryService | None = None,
) -> HypervisorService:
    if state_store is None:
        state_store = _default_state_store()
    plugins = PluginRegistry()
    plugins.register(LlamaCppPlugin())
    plugins.register(OllamaPlugin())
    plugins.register(ProxyOpenAIPlugin())
    plugins.register(VllmPlugin())
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
        registry_service=registry_service,
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


def _build_default_registry_service(
    *,
    state_store: FileStateStore | None = None,
) -> RegistryService:
    if state_store is None:
        return RegistryService()
    registry_snapshot_path = state_store.path.parent / "registry-objects.json"
    return RegistryService(snapshot_path=registry_snapshot_path)


def _build_default_session_service(
    *,
    state_store: FileStateStore | None = None,
    registry_service: RegistryService | None = None,
) -> SessionService:
    if state_store is None:
        state_store = _default_state_store()
    return SessionService(
        SessionStore(state_store),
        registry_service=registry_service,
    )


def _build_default_validation_service(
    *,
    state_store: FileStateStore | None = None,
) -> ValidationService:
    if state_store is None:
        state_store = _default_state_store()
    custody_store = (
        ValidationReportCustodyStore(
            state_store.path.parent / "validation-report-custody"
        )
        if state_store is not None
        else None
    )
    custody_signing_key = os.getenv("AIDN_HYPERVISOR_CUSTODY_SIGNING_KEY")
    custody_signer = (
        Ed25519ValidationReportCustodySigner(custody_signing_key)
        if custody_signing_key
        else None
    )
    return ValidationService(
        ValidationStore(state_store),
        custody_store=custody_store,
        custody_signer=custody_signer,
    )


def _default_state_store() -> FileStateStore | None:
    state_path = os.getenv("AIDN_HYPERVISOR_STATE_PATH")
    if not state_path:
        return None
    return FileStateStore(state_path)


def _build_default_consensus_service(
    *,
    hypervisor_service: HypervisorService,
    state_store: FileStateStore | None,
) -> ConsensusService | None:
    raw_mode = os.getenv("AIDN_CONSENSUS_MODE", ConsensusMode.DISABLED.value).lower()
    try:
        mode = ConsensusMode(raw_mode)
    except ValueError as error:
        raise ValueError("AIDN_CONSENSUS_MODE must be disabled, non_validator, or validator") from error
    if mode == ConsensusMode.DISABLED:
        return None

    config = ConsensusServiceConfig(
        node_id=os.getenv("AIDN_CONSENSUS_NODE_ID", hypervisor_service.node_id),
        mode=mode,
        cometbft_endpoint=os.getenv("AIDN_COMETBFT_ENDPOINT", "tcp://localhost:26657"),
        validator_pubkey=os.getenv("AIDN_CONSENSUS_VALIDATOR_PUBKEY", ""),
        chain_id=os.getenv("AIDN_COMETBFT_CHAIN_ID", "aidn-localnet-1"),
        abci_state_path=os.getenv("AIDN_COMETBFT_ABCI_STATE_PATH"),
        abci_listen_host=os.getenv("AIDN_COMETBFT_ABCI_HOST", "127.0.0.1"),
        abci_listen_port=int(os.getenv("AIDN_COMETBFT_ABCI_PORT", "26658")),
    )
    consensus = ConsensusService(config)
    if mode != ConsensusMode.VALIDATOR:
        return consensus
    if state_store is None:
        raise ValueError("validator mode requires AIDN_HYPERVISOR_STATE_PATH")
    if not config.abci_state_path:
        raise ValueError("validator mode requires AIDN_COMETBFT_ABCI_STATE_PATH")

    consensus.bootstrap_validator_abci(
        ledger_service=hypervisor_service.ledger_operation_service,
        restore_state_from_store=False,
        state_checkpoint_callback=hypervisor_service._persist_state,
    )
    consensus.restore_validator_abci_state_if_matching_ledger()
    return consensus


def _default_bundle_registry(plugins: PluginRegistry) -> FileBundleRegistry:
    bundle_path = os.getenv("AIDN_HYPERVISOR_BUNDLES_PATH")
    if not bundle_path:
        bundle_path = os.path.join(os.getcwd(), "bundles.json")
    return FileBundleRegistry(bundle_path)
