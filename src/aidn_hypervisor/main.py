import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aidn_hypervisor.api import build_api_router
from aidn_hypervisor.bundle_registry import FileBundleRegistry
from aidn_hypervisor.consensus.cometbft_finality import (
    build_cometbft_multi_rpc_finality_source,
)
from aidn_hypervisor.consensus.deployment import (
    load_cometbft_finality_deployment_config,
)
from aidn_hypervisor.consensus.service import (
    ConsensusMode,
    ConsensusService,
    ConsensusServiceConfig,
)
from aidn_hypervisor.contribution_api import build_contribution_router
from aidn_hypervisor.contributions.service import ContributionAccountingService
from aidn_hypervisor.contributions.store import ContributionEvidenceStore
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.api import build_endpoint_router
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.mcp import (
    McpPersistentStateStore,
    McpRemoteGateway,
    build_mcp_remote_router,
    build_mcp_server,
)
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.plugins.ollama import OllamaPlugin
from aidn_hypervisor.plugins.proxy_openai import ProxyOpenAIPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.plugins.vllm import VllmPlugin
from aidn_hypervisor.plugins.whisper import WhisperPlugin
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.queue import InMemoryTaskQueue
from aidn_hypervisor.registry.deployment import (
    build_registry_replication_runtime,
    load_file_secret_manager_from_environment,
    load_registry_replication_deployment_config,
)
from aidn_hypervisor.registry.runtime import RegistryReplicationRuntime
from aidn_hypervisor.registry_api import build_registry_router
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.remote_endpoints.service import RemoteEndpointService
from aidn_hypervisor.remote_endpoints.store import RemoteEndpointStore
from aidn_hypervisor.resource_probe import load_resource_probe_from_environment
from aidn_hypervisor.resources import ResourceOrchestrator
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.service import HypervisorService
from aidn_hypervisor.session_failure.service import SessionFailureHandler
from aidn_hypervisor.sessions.service import SessionService
from aidn_hypervisor.sessions.store import SessionStore
from aidn_hypervisor.snapshot.deployment import (
    RemoteTrustAnchorRuntime,
    load_remote_trust_anchor_deployment_config,
)
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
    contribution_service: ContributionAccountingService | None = None,
    consensus_service: ConsensusService | None = None,
    consensus_finality_source=None,
    registry_replication_runtime: RegistryReplicationRuntime | None = None,
    remote_trust_anchor_runtime: RemoteTrustAnchorRuntime | None = None,
) -> FastAPI:
    state_store = _default_state_store()
    resolved_registry_service = registry_service or _build_default_registry_service(state_store=state_store)
    resolved_service = service or _build_default_service(
        state_store=state_store,
        registry_service=resolved_registry_service,
    )
    resolved_registry_service.bind_ledger_operation_service(resolved_service.ledger_operation_service)
    bound_endpoint_publication_service = getattr(resolved_service, "endpoint_publication_service", None)
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
    resolved_remote_endpoint_service = remote_endpoint_service or _build_default_remote_endpoint_service(
        state_store=state_store
    )
    resolved_session_service = session_service or _build_default_session_service(
        state_store=state_store,
        registry_service=resolved_registry_service,
    )
    resolved_validation_service = validation_service or _build_default_validation_service(state_store=state_store)
    resolved_contribution_service = contribution_service or _build_default_contribution_service(state_store=state_store)
    resolved_service.bind_external_services(
        registry_service=resolved_registry_service,
        endpoint_service=resolved_endpoint_service,
        endpoint_publication_service=resolved_endpoint_publication_service,
        remote_endpoint_service=resolved_remote_endpoint_service,
        session_service=resolved_session_service,
        validation_service=resolved_validation_service,
    )
    resolved_consensus_service = consensus_service or getattr(resolved_service, "consensus_service", None)
    if resolved_consensus_service is None:
        resolved_consensus_service = _build_default_consensus_service(
            hypervisor_service=resolved_service,
            state_store=state_store,
        )
    elif getattr(resolved_service, "consensus_service", None) not in {
        None,
        resolved_consensus_service,
    }:
        raise ValueError("Hypervisor is already bound to another ConsensusService")
    if resolved_consensus_service is not None:
        resolved_service.consensus_service = resolved_consensus_service
    resolved_finality_source = consensus_finality_source or getattr(resolved_service, "consensus_finality_source", None)
    if resolved_finality_source is None:
        resolved_finality_source = _build_default_consensus_finality_source(
            hypervisor_service=resolved_service,
            consensus_service=resolved_consensus_service,
        )
    if resolved_finality_source is not None:
        resolved_service.bind_consensus_finality_source(resolved_finality_source)
    resolved_registry_replication_runtime = registry_replication_runtime or _build_default_registry_replication_runtime(
        registry_service=resolved_registry_service
    )
    resolved_remote_trust_anchor_runtime = remote_trust_anchor_runtime or _build_default_remote_trust_anchor_runtime()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if resolved_remote_trust_anchor_runtime is not None:
            resolved_remote_trust_anchor_runtime.refresh()
        if resolved_registry_replication_runtime is not None:
            resolved_registry_replication_runtime.start()
        if resolved_consensus_service is not None and resolved_consensus_service.is_validator:
            resolved_consensus_service.start_validator_abci_server()
        try:
            yield
        finally:
            if resolved_consensus_service is not None:
                resolved_consensus_service.stop_validator_abci_server()
            if resolved_registry_replication_runtime is not None:
                resolved_registry_replication_runtime.stop()

    app = FastAPI(
        title="AiDN Hypervisor",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.hypervisor_service = resolved_service
    app.state.consensus_service = resolved_consensus_service
    app.state.consensus_finality_source = resolved_finality_source
    app.state.registry_replication_runtime = resolved_registry_replication_runtime
    app.state.remote_trust_anchor_runtime = resolved_remote_trust_anchor_runtime
    app.state.contribution_service = resolved_contribution_service
    app.state.endpoint_service = resolved_endpoint_service
    app.state.endpoint_publication_service = resolved_endpoint_publication_service
    app.state.remote_endpoint_service = resolved_remote_endpoint_service
    app.state.session_service = resolved_session_service
    app.state.validation_service = resolved_validation_service
    app.state.registry_service = resolved_registry_service
    mcp_state_store = McpPersistentStateStore.from_hypervisor_state_store(state_store)
    app.state.state_store = state_store
    app.state.mcp_state_store = mcp_state_store
    app.state.mcp_server = build_mcp_server(
        resolved_service,
        endpoint_service=resolved_endpoint_service,
        endpoint_publication_service=resolved_endpoint_publication_service,
        validation_service=resolved_validation_service,
        registry_service=resolved_registry_service,
        mcp_state_store=mcp_state_store,
    )
    mcp_remote_enabled = _env_bool("AIDN_MCP_REMOTE_ENABLED", default=False)
    mcp_remote_token = os.getenv("AIDN_MCP_REMOTE_TOKEN") if mcp_remote_enabled else None
    if mcp_remote_enabled and not mcp_remote_token:
        raise ValueError("AIDN_MCP_REMOTE_ENABLED requires AIDN_MCP_REMOTE_TOKEN")
    mcp_remote_tls_required = _env_bool("AIDN_MCP_REMOTE_TLS_REQUIRED", default=False)
    mcp_remote_gateway = McpRemoteGateway(
        app.state.mcp_server.control,
        agent_token=mcp_remote_token,
        operator_token=os.getenv("AIDN_MCP_OPERATOR_TOKEN") if mcp_remote_enabled else None,
        require_tls=mcp_remote_tls_required,
    )
    app.state.mcp_remote_gateway = mcp_remote_gateway
    if mcp_remote_gateway.enabled:
        app.include_router(build_mcp_remote_router(mcp_remote_gateway))

    @app.middleware("http")
    async def validator_write_boundary(request: Request, call_next):
        consensus = app.state.consensus_service
        if (
            consensus is not None
            and consensus.is_validator
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and not _is_validator_consensus_write_path(request.url.path)
        ):
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "validator_consensus_required",
                        "message": (
                            "Validator-mode writes must enter through the canonical consensus transaction path"
                        ),
                        "method": request.method,
                        "path": request.url.path,
                    }
                },
            )
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/registry/replication/status")
    async def registry_replication_status() -> dict:
        """Expose sanitized replication lifecycle diagnostics to operators."""
        runtime = app.state.registry_replication_runtime
        if runtime is None:
            return {"enabled": False, "running": False}
        return {"enabled": True, **runtime.status()}

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
    app.include_router(build_contribution_router(resolved_contribution_service))
    # Keep Registry mutation and repair APIs available on the Hypervisor
    # process. The API router is registered first so its signed wallet-identity
    # export remains the handler for the overlapping read-only route.
    app.include_router(build_registry_router(resolved_registry_service))

    return app


def _is_validator_consensus_write_path(path: str) -> bool:
    """Allow canonical transactions and explicitly bounded local operations."""
    parts = path.strip("/").split("/")
    if parts and parts[0] == "mcp":
        # MCP remote control is a separately authenticated local operator
        # boundary; it does not submit consensus transactions directly.
        return True
    if parts == ["operators", "wallet", "bootstrap", "create"]:
        return True
    if parts == ["operators", "wallet", "bootstrap", "import"]:
        return True
    if parts == ["operators", "resources", "probe"]:
        # This bounded local operation accepts no caller-provided capacity and
        # only refreshes host measurements. It has no Ledger effect.
        return True
    if (
        len(parts) == 4
        and parts[:2] == ["operators", "provider-plugins"]
        and parts[3]
        in {"installation-plan", "installation-approvals", "installation-diagnostics"}
    ):
        # Provider installation plans, diagnostics and approvals affect only
        # local operational inventory. They cannot publish an Endpoint, move Q
        # or execute arbitrary host mutations through this bounded executor.
        return True
    if (
        len(parts) == 4
        and parts[:2] == ["operators", "provider-installation-approvals"]
        and parts[3] == "apply"
    ):
        return True
    if (
        len(parts) == 4
        and parts[:2] == ["operators", "provider-installation-jobs"]
        and parts[3] == "rollback"
    ):
        return True
    if (
        len(parts) == 5
        and parts[:3] == ["api", "v1", "endpoints"]
        and parts[4] in {"mvp-sessions", "public-mvp-sessions"}
    ):
        return True
    return (
        len(parts) == 7
        and parts[:3] == ["api", "v1", "endpoints"]
        and parts[4] == "mvp-sessions"
        and parts[6] == "force-finalize"
    )


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
    plugin_host_secret_manager = load_file_secret_manager_from_environment()
    resource_probe = load_resource_probe_from_environment()
    service = HypervisorService(
        queue=InMemoryTaskQueue(),
        scheduler=Scheduler(),
        resources=ResourceOrchestrator(
            resource_probe.capacity,
            probe=resource_probe.metadata(),
        ),
        bundles=bundles,
        plugins=plugins,
        runtimes=ProviderProcessManager(enable_subprocesses=True),
        state_store=state_store,
        bundle_registry=_default_bundle_registry(plugins),
        registry_service=registry_service,
        plugin_host_secret_manager=plugin_host_secret_manager,
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


def _build_default_registry_replication_runtime(
    *,
    registry_service: RegistryService,
) -> RegistryReplicationRuntime | None:
    config_path = os.getenv("AIDN_REGISTRY_REPLICATION_CONFIG")
    if not config_path:
        return None
    secret_manager = load_file_secret_manager_from_environment()
    if secret_manager is None:
        raise ValueError("Registry replication configuration requires the local Secret Manager")
    config = load_registry_replication_deployment_config(Path(config_path))
    return build_registry_replication_runtime(
        config=config,
        registry_service=registry_service,
        secret_manager=secret_manager,
    )


def _build_default_remote_trust_anchor_runtime() -> RemoteTrustAnchorRuntime | None:
    config_path = os.getenv("AIDN_REMOTE_TRUST_ANCHOR_CONFIG")
    if not config_path:
        return None
    return RemoteTrustAnchorRuntime(config=load_remote_trust_anchor_deployment_config(Path(config_path)))


def _build_default_consensus_finality_source(
    *,
    hypervisor_service: HypervisorService,
    consensus_service: ConsensusService | None,
):
    config_path = os.getenv("AIDN_COMETBFT_FINALITY_CONFIG")
    if not config_path:
        return None
    if consensus_service is None or not consensus_service.is_enabled:
        raise ValueError("AIDN_COMETBFT_FINALITY_CONFIG requires an enabled ConsensusService")
    if consensus_service.is_validator and (
        consensus_service.abci is None
        or consensus_service.abci.ledger is not hypervisor_service.ledger_operation_service
    ):
        raise ValueError("validator finality configuration requires the Hypervisor-bound ABCI Ledger")
    config = load_cometbft_finality_deployment_config(Path(config_path))
    return build_cometbft_multi_rpc_finality_source(
        config=config.runtime_config(),
        transaction_hash_for_operation=consensus_service.transaction_hash_for_operation,
        abci_application=(consensus_service.abci if consensus_service.is_validator else None),
    )


def _build_default_session_service(
    *,
    state_store: FileStateStore | None = None,
    registry_service: RegistryService | None = None,
) -> SessionService:
    if state_store is None:
        state_store = _default_state_store()
    failure_handler = SessionFailureHandler()
    if state_store is not None:
        persisted_snapshot = state_store.load()
        failure_handler.restore_evidence(
            evidence=persisted_snapshot.session_failure_evidence,
            reports=persisted_snapshot.session_failure_reports,
        )
    return SessionService(
        SessionStore(state_store),
        registry_service=registry_service,
        failure_handler=failure_handler,
        recovery_config=failure_handler.recovery_config,
    )


def _build_default_validation_service(
    *,
    state_store: FileStateStore | None = None,
) -> ValidationService:
    if state_store is None:
        state_store = _default_state_store()
    custody_store = (
        ValidationReportCustodyStore(state_store.path.parent / "validation-report-custody")
        if state_store is not None
        else None
    )
    custody_signing_key = os.getenv("AIDN_HYPERVISOR_CUSTODY_SIGNING_KEY")
    custody_signer = Ed25519ValidationReportCustodySigner(custody_signing_key) if custody_signing_key else None
    return ValidationService(
        ValidationStore(state_store),
        custody_store=custody_store,
        custody_signer=custody_signer,
    )


def _build_default_contribution_service(
    *,
    state_store: FileStateStore | None = None,
) -> ContributionAccountingService:
    evidence_store = (
        ContributionEvidenceStore(state_store.path.parent / "contribution-evidence.json")
        if state_store is not None
        else ContributionEvidenceStore()
    )
    return ContributionAccountingService(evidence_store)


def _default_state_store() -> FileStateStore | None:
    state_path = os.getenv("AIDN_HYPERVISOR_STATE_PATH")
    if not state_path:
        return None
    return FileStateStore(state_path)


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


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
        managed_service_name=os.getenv("AIDN_COMETBFT_SERVICE") or None,
        abci_state_path=os.getenv("AIDN_COMETBFT_ABCI_STATE_PATH"),
        abci_listen_host=os.getenv("AIDN_COMETBFT_ABCI_HOST", "127.0.0.1"),
        abci_listen_port=int(os.getenv("AIDN_COMETBFT_ABCI_PORT", "26658")),
        abci_retained_snapshots=int(
            os.getenv(
                "AIDN_COMETBFT_ABCI_RETAINED_SNAPSHOTS",
                "8",
            )
        ),
        abci_snapshot_lease_seconds=int(
            os.getenv(
                "AIDN_COMETBFT_ABCI_SNAPSHOT_LEASE_SECONDS",
                "1800",
            )
        ),
        strict_operation_coverage=_env_bool(
            "AIDN_CONSENSUS_STRICT_OPERATION_COVERAGE",
            default=mode == ConsensusMode.VALIDATOR,
        ),
    )
    consensus = ConsensusService(config)
    if mode != ConsensusMode.VALIDATOR:
        return consensus
    if state_store is None:
        raise ValueError("validator mode requires AIDN_HYPERVISOR_STATE_PATH")
    if not config.abci_state_path:
        raise ValueError("validator mode requires AIDN_COMETBFT_ABCI_STATE_PATH")

    genesis_accounts = _consensus_genesis_accounts()
    # Hypervisor state is restored before ABCI bootstrap.  Never reapply the
    # disposable test genesis over an already populated local Ledger during a
    # validator restart.
    if hypervisor_service.ledger_operation_service.snapshot_operations():
        genesis_accounts = None

    consensus.bootstrap_validator_abci(
        ledger_service=hypervisor_service.ledger_operation_service,
        genesis_accounts=genesis_accounts,
        restore_state_from_store=False,
        state_checkpoint_callback=hypervisor_service._persist_state,
    )
    consensus.restore_validator_abci_state_if_matching_ledger()
    return consensus


def _consensus_genesis_accounts() -> dict[str, int] | None:
    """Parse opt-in disposable validator genesis balances.

    Production deployments leave this unset.  The isolated acceptance drill
    uses it to fund a test Consumer without adding a minting operation to the
    protocol surface.
    """
    raw = os.getenv("AIDN_CONSENSUS_GENESIS_ACCOUNTS_JSON")
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("AIDN_CONSENSUS_GENESIS_ACCOUNTS_JSON must be valid JSON") from error
    if not isinstance(parsed, dict):
        raise ValueError("AIDN_CONSENSUS_GENESIS_ACCOUNTS_JSON must be an object")
    accounts: dict[str, int] = {}
    for wallet_id, amount in parsed.items():
        if (
            not isinstance(wallet_id, str)
            or not wallet_id.strip()
            or isinstance(amount, bool)
            or not isinstance(amount, int)
            or amount < 0
        ):
            raise ValueError("AIDN_CONSENSUS_GENESIS_ACCOUNTS_JSON contains invalid account")
        accounts[wallet_id] = amount
    return accounts


def _default_bundle_registry(plugins: PluginRegistry) -> FileBundleRegistry:
    bundle_path = os.getenv("AIDN_HYPERVISOR_BUNDLES_PATH")
    if not bundle_path:
        bundle_path = os.path.join(os.getcwd(), "bundles.json")
    return FileBundleRegistry(bundle_path)
