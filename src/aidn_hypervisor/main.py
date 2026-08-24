import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from aidn_hypervisor.api import build_api_router
from aidn_hypervisor.bundle_registry import FileBundleRegistry
from aidn_hypervisor.config import load_operator_config
from aidn_hypervisor.consensus.cometbft import (
    HttpCometBftRpcTransport,
    HttpCometBftWalletBalanceProvider,
    HttpCometBftWalletIdentityProvider,
    HttpCometBftWalletSequenceProvider,
)
from aidn_hypervisor.consensus.cometbft_finality import (
    build_cometbft_multi_rpc_finality_source,
)
from aidn_hypervisor.consensus.deployment import (
    load_cometbft_finality_deployment_config,
)
from aidn_hypervisor.consensus.epoch_schedule import EpochSchedule, build_epoch_schedule
from aidn_hypervisor.consensus.protocol_authority import ProtocolAuthorityPolicy
from aidn_hypervisor.consensus.service import (
    ConsensusMode,
    ConsensusService,
    ConsensusServiceConfig,
)
from aidn_hypervisor.consensus.state_store import ABCIStateStore, ABCIStateStoreError
from aidn_hypervisor.contribution_api import build_contribution_router
from aidn_hypervisor.contributions.service import ContributionAccountingService
from aidn_hypervisor.contributions.store import ContributionEvidenceStore
from aidn_hypervisor.dashboard_network_access import DashboardNetworkAccessService
from aidn_hypervisor.endpoint_publications.service import EndpointPublicationService
from aidn_hypervisor.endpoint_publications.store import EndpointPublicationStore
from aidn_hypervisor.endpoints.api import build_endpoint_router
from aidn_hypervisor.endpoints.service import EndpointService
from aidn_hypervisor.endpoints.store import EndpointStore
from aidn_hypervisor.faucet_treasury import (
    FaucetTreasuryManifest,
    validate_faucet_treasury_manifest,
)
from aidn_hypervisor.inference_gateway import build_inference_router
from aidn_hypervisor.mcp import (
    McpPersistentStateStore,
    McpRemoteGateway,
    build_mcp_remote_router,
    build_mcp_server,
)
from aidn_hypervisor.mcp.credentials import McpCredentialStore
from aidn_hypervisor.mcp.enrollment import McpEnrollmentService
from aidn_hypervisor.model_store import FileModelStore
from aidn_hypervisor.operator_access import DashboardAccessService
from aidn_hypervisor.operator_access_api import build_operator_access_router
from aidn_hypervisor.operator_cometbft_install import (
    UnixSocketConsensusRuntimeExecutor,
    load_active_cometbft_configuration,
)
from aidn_hypervisor.operator_config_service import OperatorConfigService
from aidn_hypervisor.persistence import FileStateStore
from aidn_hypervisor.plugins.llamacpp import LlamaCppPlugin
from aidn_hypervisor.plugins.ollama import OllamaPlugin
from aidn_hypervisor.plugins.proxy_openai import ProxyOpenAIPlugin
from aidn_hypervisor.plugins.registry import PluginRegistry
from aidn_hypervisor.plugins.vllm import VllmPlugin
from aidn_hypervisor.plugins.whisper import WhisperPlugin
from aidn_hypervisor.process_manager import ProviderProcessManager
from aidn_hypervisor.providers.executor import AllowlistedProviderRuntimeInstallationExecutor
from aidn_hypervisor.providers.runtime_broker import (
    AllowlistedProviderRuntimeBroker,
    UnixSocketProviderRuntimeCommandRunner,
)
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
from aidn_hypervisor.resources import ResourceOrchestrator, ResourceSafetyPolicy
from aidn_hypervisor.runtime_port_allocator import RuntimePortAllocator
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
from aidn_hypervisor.wallet_reconciliation import reconcile_pending_wallet_transfers


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
    # Load the optional TOML profile before any default service or MCP session
    # is constructed. Existing process environment values remain authoritative.
    load_operator_config()
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
        if resolved_consensus_service.is_enabled:
            # Local drafts and pending Session metadata must not mutate the
            # consensus Ledger/AppHash before their canonical transactions
            # reach finality. Their durable projections remain available to
            # the operator and are reconciled after consensus confirmation.
            resolved_endpoint_service.record_creation_operation = False
            resolved_endpoint_service.record_update_operation = False
            resolved_session_service.record_open_operation = False
    # The dashboard wizard uses the same UID-restricted root broker as Provider
    # runtime installation. Keep this capability explicit and absent in tests
    # or development processes unless the Ubuntu bootstrap opted in.
    consensus_installation_executor = _build_default_consensus_installation_executor()
    if consensus_installation_executor is not None:
        resolved_service.consensus_installation_executor = consensus_installation_executor
    resolved_finality_source = consensus_finality_source or getattr(resolved_service, "consensus_finality_source", None)
    if resolved_finality_source is None:
        resolved_finality_source = _build_default_consensus_finality_source(
            hypervisor_service=resolved_service,
            consensus_service=resolved_consensus_service,
        )
    if resolved_finality_source is not None:
        resolved_service.bind_consensus_finality_source(resolved_finality_source)
    if resolved_service.canonical_wallet_balance_provider is None:
        resolved_service.canonical_wallet_balance_provider = (
            _build_default_canonical_wallet_balance_provider()
        )
    if resolved_service.canonical_wallet_identity_provider is None:
        resolved_service.canonical_wallet_identity_provider = (
            _build_default_canonical_wallet_identity_provider()
        )
    if resolved_service.canonical_wallet_sequence_provider is None:
        resolved_service.canonical_wallet_sequence_provider = (
            _build_default_canonical_wallet_sequence_provider()
        )
    # Restore and retry durable Wallet transfers before serving the dashboard.
    # Each envelope is handled fail-closed, so a temporarily unavailable
    # external CometBFT quorum cannot prevent the Hypervisor from starting.
    reconcile_pending_wallet_transfers(resolved_service)
    reconciled_publications = resolved_endpoint_publication_service.reconcile_canonical_publications(
        resolved_service.ledger_operation_service.list_operations()
    )
    reconciled_sessions = resolved_session_service.reconcile_canonical_settlement_projections(
        resolved_service.ledger_operation_service
    )
    if reconciled_publications or reconciled_sessions:
        # SessionStore owns the local projection; persist only after the
        # canonical Ledger transition has passed all reconciliation checks.
        resolved_service._persist_state()
    resolved_registry_replication_runtime = registry_replication_runtime or _build_default_registry_replication_runtime(
        registry_service=resolved_registry_service
    )
    resolved_remote_trust_anchor_runtime = remote_trust_anchor_runtime or _build_default_remote_trust_anchor_runtime()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        steward_worker_enabled = _env_bool(
            "AIDN_STEWARD_WORKER_ENABLED",
            default=_env_bool("AIDN_STEWARD_ENABLED", default=False),
        )
        steward_worker_interval = _env_int(
            "AIDN_STEWARD_WORKER_INTERVAL_SECONDS",
            default=15,
            minimum=1,
            maximum=300,
        )
        configure_steward_worker = getattr(
            resolved_service, "configure_resident_worker", None
        )
        start_steward_worker = getattr(resolved_service, "start_resident_worker", None)
        stop_steward_worker = getattr(resolved_service, "stop_resident_worker", None)
        if callable(configure_steward_worker):
            configure_steward_worker(
                enabled=steward_worker_enabled,
                interval_seconds=steward_worker_interval,
            )
        if steward_worker_enabled and callable(start_steward_worker):
            start_steward_worker()
        if resolved_remote_trust_anchor_runtime is not None:
            resolved_remote_trust_anchor_runtime.refresh()
        if resolved_registry_replication_runtime is not None:
            resolved_registry_replication_runtime.start()
        if resolved_consensus_service is not None and resolved_consensus_service.is_validator:
            resolved_consensus_service.start_validator_abci_server()
        try:
            yield
        finally:
            if callable(stop_steward_worker):
                stop_steward_worker()
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
    mcp_operator_token = os.getenv("AIDN_MCP_OPERATOR_TOKEN") if mcp_remote_enabled else None
    if mcp_remote_token and mcp_operator_token and hmac.compare_digest(
        mcp_remote_token,
        mcp_operator_token,
    ):
        raise ValueError("MCP agent and operator tokens must be different")
    mcp_secret_manager = load_file_secret_manager_from_environment() if mcp_remote_enabled else None
    mcp_credential_store = (
        McpCredentialStore(secret_manager=mcp_secret_manager)
        if mcp_secret_manager is not None
        else None
    )
    if mcp_credential_store is not None and mcp_remote_token:
        mcp_credential_store.import_legacy_token(
            token=mcp_remote_token,
            label="Legacy MCP agent token",
            scopes=tuple(sorted(app.state.mcp_server.control.session.scopes)),
        )
    if mcp_remote_enabled and not mcp_remote_token and mcp_credential_store is None:
        raise ValueError(
            "AIDN_MCP_REMOTE_ENABLED requires AIDN_MCP_REMOTE_TOKEN or the configured secret manager"
        )
    mcp_remote_tls_required = _env_bool("AIDN_MCP_REMOTE_TLS_REQUIRED", default=False)
    dashboard_access_insecure_lan = _env_bool(
        "AIDN_DASHBOARD_ACCESS_ALLOW_INSECURE_LAN",
        default=False,
    )
    mcp_remote_gateway = McpRemoteGateway(
        app.state.mcp_server.control,
        agent_token=None if mcp_credential_store is not None else mcp_remote_token,
        credential_resolver=mcp_credential_store,
        operator_token=mcp_operator_token,
        require_tls=mcp_remote_tls_required,
        max_body_bytes=_env_int(
            "AIDN_MCP_MAX_BODY_BYTES",
            default=1_048_576,
            minimum=1_024,
            maximum=64 * 1_024 * 1_024,
        ),
        max_transport_sessions=_env_int(
            "AIDN_MCP_MAX_TRANSPORT_SESSIONS",
            default=128,
            minimum=1,
            maximum=4_096,
        ),
    )
    dashboard_access_service = (
        DashboardAccessService(store=mcp_credential_store)
        if mcp_credential_store is not None
        else None
    )
    dashboard_network_access_service = DashboardNetworkAccessService()

    def sync_dashboard_config(values: dict[str, str]) -> None:
        configured_host = values.get("AIDN_HYPERVISOR_API_HOST")
        if configured_host in {"127.0.0.1", "0.0.0.0"}:
            dashboard_network_access_service.set_mode(
                "lan" if configured_host == "0.0.0.0" else "loopback"
            )

    dashboard_config_service = OperatorConfigService(
        restart_callback=dashboard_network_access_service.schedule_restart,
        apply_callback=sync_dashboard_config,
        restart_supported=dashboard_network_access_service.restart_supported,
    )
    mcp_enrollment_service = (
        McpEnrollmentService(
            secret_manager=mcp_secret_manager,
            credential_store=mcp_credential_store,
        )
        if mcp_secret_manager is not None and mcp_credential_store is not None
        else None
    )
    app.state.mcp_remote_gateway = mcp_remote_gateway
    app.state.mcp_credential_store = mcp_credential_store
    app.state.dashboard_access_service = dashboard_access_service
    app.state.dashboard_network_access_service = dashboard_network_access_service
    app.state.operator_config_service = dashboard_config_service
    app.state.mcp_enrollment_service = mcp_enrollment_service
    app.state.inference_gateway_enabled = mcp_credential_store is not None
    if mcp_remote_gateway.enabled:
        app.include_router(build_mcp_remote_router(mcp_remote_gateway))
    app.include_router(
        build_inference_router(
            hypervisor_service=resolved_service,
            endpoint_service=resolved_endpoint_service,
            session_service=resolved_session_service,
            credential_store=mcp_credential_store,
        )
    )
    app.include_router(
        build_operator_access_router(
            access_service=dashboard_access_service,
            credential_store=mcp_credential_store,
            allow_insecure_lan=dashboard_access_insecure_lan,
            enrollment_service=mcp_enrollment_service,
            operator_fingerprint=mcp_remote_gateway.operator_fingerprint,
            invalidate_credential_sessions=mcp_remote_gateway.invalidate_credential_sessions,
            hypervisor_service=resolved_service,
            endpoint_service=resolved_endpoint_service,
            endpoint_publication_service=resolved_endpoint_publication_service,
            remote_endpoint_service=resolved_remote_endpoint_service,
            validation_service=resolved_validation_service,
            network_access_service=dashboard_network_access_service,
            config_service=dashboard_config_service,
            session_service=resolved_session_service,
        )
    )

    @app.middleware("http")
    async def hook_operator_boundary(request: Request, call_next):
        """Keep Hook definitions and delivery records inside the paired UI.

        The canonical MCP surface has its own token and scope checks.  The
        dashboard HTTP surface must enforce the equivalent browser session
        boundary; otherwise a LAN caller could mutate Hooks by calling the
        generic operator API directly.
        """

        if request.url.path == "/operators/hooks" or request.url.path.startswith(
            "/operators/hooks/"
        ):
            access_service = app.state.dashboard_access_service
            if access_service is not None and not access_service.authorize(
                request.cookies.get("aidn_dashboard_access"),
                browser_key=request.headers.get("X-AiDN-Browser-Key"),
            ):
                return JSONResponse(
                    status_code=401,
                    content={"error": {"code": "DASHBOARD_ACCESS_REQUIRED"}},
                )
            if (
                access_service is not None
                and not dashboard_access_insecure_lan
                and request.url.scheme != "https"
            ):
                return JSONResponse(
                    status_code=426,
                    content={"error": {"code": "DASHBOARD_ACCESS_TLS_REQUIRED"}},
                )
        return await call_next(request)

    @app.middleware("http")
    async def validator_write_boundary(request: Request, call_next):
        consensus = app.state.consensus_service
        if (
            consensus is not None
            and consensus.is_validator
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and not _is_validator_consensus_write_path(
                request.url.path,
                request.method,
            )
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


def _is_validator_consensus_write_path(path: str, method: str | None = None) -> bool:
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
    if len(parts) >= 2 and parts[:2] == ["operators", "hooks"]:
        # Hook subscriptions and delivery recovery are local event-plane
        # state. They do not submit a consensus transaction.
        return True
    if (
        len(parts) == 5
        and parts[:3] == ["operators", "events", "inbox"]
        and parts[4] == "ack"
        and (method is None or method == "POST")
    ):
        # Inbox acknowledgments advance local delivery state only.
        return True
    if (
        parts == ["operators", "dashboard", "access", "pair"]
        and (method is None or method == "POST")
    ):
        # Pairing only creates a short-lived local browser session. The code is
        # minted from the host terminal and never reaches consensus state.
        return True
    if (
        len(parts) == 5
        and parts[:4] == ["operators", "dashboard", "access", "agent-enrollment"]
        and parts[4] == "requests"
        and (method is None or method == "POST")
    ):
        # An agent may only submit its public-key enrollment request here;
        # no credential leaves the node until a dashboard operator approves it.
        return True
    if (
        len(parts) == 6
        and parts[:4] == ["operators", "dashboard", "access", "agent-enrollment"]
        and parts[4] == "requests"
        and (method is None or method == "GET")
    ):
        return True
    if (
        len(parts) == 6
        and parts[:4] == ["operators", "dashboard", "access", "enrollment-requests"]
        and parts[5] in {"approve", "reject"}
        and (method is None or method == "POST")
    ):
        return True
    if (
        parts == ["operators", "dashboard", "access", "logout"]
        and (method is None or method == "POST")
    ):
        return True
    if parts == ["operators", "dashboard", "access", "operations", "resources", "probe"]:
        return True
    if (
        parts == ["v1", "chat", "completions"]
        and (method is None or method == "POST")
    ):
        # OpenAI-compatible inference is a separately bearer-authenticated,
        # endpoint-scoped data-plane request. It never mutates consensus state.
        return True
    if tuple(parts) in {
        ("operators", "dashboard", "steward", "enabled"),
        ("operators", "dashboard", "steward", "action-policy"),
        ("operators", "dashboard", "steward", "action-execute"),
        ("operators", "dashboard", "steward", "inference", "prepare"),
        ("operators", "dashboard", "steward", "inference", "start"),
        ("operators", "dashboard", "steward", "inference", "stop"),
        ("operators", "dashboard", "steward", "inference", "model", "prepare"),
        ("operators", "dashboard", "steward", "inference", "model", "verify"),
        ("operators", "dashboard", "steward", "inference", "invoke"),
        ("operators", "dashboard", "steward", "chat"),
    } and (method is None or method == "POST"):
        # Resident Steward controls and inference stay on this node. They
        # update local policy/enablement, prepare or verify a local artifact,
        # reserve or release a Resource Broker lease, execute allow-listed
        # local actions, and invoke the local runtime; none writes Ledger state.
        return True
    if parts == ["operators", "dashboard", "access", "operations", "network"]:
        # The Dashboard listener is constrained to the two reviewed host
        # boundaries and is persisted for the bootstrap service wrapper.
        return True
    if (
        len(parts) == 6
        and parts[:5] == ["operators", "dashboard", "access", "operations", "cometbft"]
        and parts[5] in {"start", "stop", "restart", "install", "apply", "reconnect"}
        and (method is None or method == "POST")
    ):
        # CometBFT control is limited to the user-systemd unit declared by the
        # node's own ConsensusService. The Dashboard cannot submit arbitrary
        # shell commands or choose a different service.
        return True
    if tuple(parts) in {
        ("operators", "dashboard", "access", "operations", "wallet", "create"),
        ("operators", "dashboard", "access", "operations", "wallet", "import"),
        ("operators", "dashboard", "access", "operations", "wallet", "transfer"),
        ("operators", "dashboard", "access", "operations", "wallet", "transfer", "preview"),
    }:
        # Wallet bootstrap enters the same canonical bind path as the terminal
        # flow. Transfers use the same consensus boundary and may not bypass
        # canonical finality.
        return True
    if (
        len(parts) == 7
        and parts[:5] == ["operators", "dashboard", "access", "operations", "bundles"]
        and parts[6] in {"enable", "disable", "retry", "reset-cooldown"}
    ):
        return True
    if (
        len(parts) == 7
        and parts[:5] == ["operators", "dashboard", "access", "operations", "bundles"]
        and parts[6] == "revisions"
        and (method is None or method == "POST")
    ):
        return True
    if (
        (
            len(parts) == 6
            and parts[:5] == ["operators", "dashboard", "access", "operations", "lifecycle"]
            and parts[5] in {"transition-plan", "removal-plan"}
        )
        or (
            len(parts) == 8
            and parts[:6] == ["operators", "dashboard", "access", "operations", "lifecycle", "transition-plans"]
            and parts[7] == "apply"
        )
        or (
            len(parts) == 8
            and parts[:6] == ["operators", "dashboard", "access", "operations", "lifecycle", "removal-plans"]
            and parts[7] == "apply"
        )
        or (
            len(parts) == 7
            and parts[:6] == ["operators", "dashboard", "access", "operations", "lifecycle", "runtime-reset"]
            and parts[6] in {"plan", "apply"}
        )
    ) and (method is None or method == "POST"):
        # Lifecycle plans and applies are destructive-capable local controls,
        # but remain behind the paired dashboard session and exact plan hash.
        return True
    if parts == ["operators", "dashboard", "access", "operations", "providers", "attach"]:
        return True
    if (
        len(parts) == 7
        and parts[:5] == ["operators", "dashboard", "access", "operations", "providers"]
        and parts[6] in {"probe", "discover-models"}
    ):
        # Dashboard operations are browser-paired local controls. Their
        # handlers only expose bounded resource, provider and Bundle lifecycle
        # actions and cannot publish an Endpoint or transfer Q.
        return True
    if parts == ["operators", "dashboard", "access", "operations", "models", "install"]:
        return True
    if parts == ["operators", "dashboard", "access", "operations", "models", "install", "process"]:
        return True
    if (
        len(parts) == 7
        and parts[:5] == ["operators", "dashboard", "access", "operations", "models"]
        and parts[6] == "register-bundle"
    ):
        return True
    if (
        parts == ["operators", "dashboard", "access", "operations", "model-artifact-sets"]
        or (
            len(parts) == 7
            and parts[:5] == ["operators", "dashboard", "access", "operations", "model-deployments"]
            and parts[6] == "artifact-set"
        )
        or (
            len(parts) == 8
            and parts[:5] == ["operators", "dashboard", "access", "operations", "provider-instances"]
            and parts[6:8] == ["artifact-sets", "materialize"]
        )
        or (
            len(parts) == 7
            and parts[:5] == ["operators", "dashboard", "access", "operations", "model-deployments"]
            and parts[6] == "runtime-bindings"
        )
    ):
        return True
    if parts == ["operators", "dashboard", "access", "operations", "endpoints"]:
        return True
    if (
        len(parts) == 7
        and parts[:5] == ["operators", "dashboard", "access", "operations", "endpoints"]
        and parts[6] in {"publish", "validation", "revoke"}
        and (method is None or method == "POST")
    ):
        return True
    if (
        len(parts) == 6
        and parts[:5] == ["operators", "dashboard", "access", "operations", "endpoints"]
        and (method is None or method == "PATCH")
    ):
        return True
    if (
        parts == ["operators", "dashboard", "access", "credentials"]
        and (method is None or method == "POST")
    ):
        # Credential lifecycle records are encrypted local operator secrets;
        # they cannot create a Ledger effect or alter network ownership.
        return True
    if (
        parts == ["operators", "dashboard", "access", "inference-credentials"]
        and (method is None or method == "POST")
    ):
        # Personal inference tokens are encrypted local credentials; issuing
        # one does not create a consensus or payment obligation.
        return True
    if (
        len(parts) == 6
        and parts[:4] == ["operators", "dashboard", "access", "inference-credentials"]
        and parts[5] == "rotate"
        and (method is None or method == "POST")
    ):
        return True
    if (
        len(parts) == 5
        and parts[:4] == ["operators", "dashboard", "access", "inference-credentials"]
        and (method is None or method == "DELETE")
    ):
        return True
    if (
        len(parts) == 6
        and parts[:4] == ["operators", "dashboard", "access", "credentials"]
        and parts[5] == "rotate"
        and (method is None or method == "POST")
    ):
        return True
    if (
        len(parts) == 5
        and parts[:4] == ["operators", "dashboard", "access", "credentials"]
        and (method is None or method == "DELETE")
    ):
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
        len(parts) == 4
        and parts[:2] == ["operators", "provider-instances"]
        and parts[3] in {"discover-models", "health"}
    ):
        # Provider discovery and health checks record bounded local runtime
        # observations. They do not publish a model, move Q or create a
        # Consumer-facing economic obligation.
        return True
    if (
        len(parts) == 4
        and parts[:2] == ["operators", "model-deployments"]
        and parts[3] == "runtime-bindings"
    ):
        # A binding is local compatibility metadata. Endpoint publication stays
        # behind the canonical consensus transaction path.
        return True
    if (
        len(parts) == 5
        and parts[:3] == ["api", "v1", "endpoints"]
        and parts[4] in {"mvp-sessions", "public-mvp-sessions"}
    ):
        return True
    if parts == ["api", "v1", "endpoints"]:
        # Creating an Endpoint draft only records local operator inventory. It
        # does not publish an advertisement, move Q, or create a Session.
        return True
    if (
        len(parts) == 4
        and parts[:3] == ["api", "v1", "endpoints"]
        and (method is None or method == "PATCH")
    ):
        # Draft policy edits are local-only until the Endpoint has a current
        # publication. EndpointApplicationService rejects edits after that
        # boundary so published state cannot bypass consensus.
        return True
    if (
        len(parts) == 5
        and parts[:3] == ["api", "v1", "endpoints"]
        and parts[4] == "publish-configuration"
        and (method is None or method == "POST")
    ):
        # The route below constructs and submits ENDPOINT_PUBLISH; it is not a
        # local publication write despite being exposed through HTTP.
        return True
    if parts == ["tasks"]:
        # Runtime task submission is a local execution operation. Its Session
        # and Settlement effects still use their own consensus-bound routes.
        return True
    return (
        len(parts) == 7
        and parts[:3] == ["api", "v1", "endpoints"]
        and parts[4] == "mvp-sessions"
        and parts[6] in {"settlement-preview", "finalize", "force-finalize"}
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
            safety=ResourceSafetyPolicy.from_environment(),
        ),
        bundles=bundles,
        plugins=plugins,
        runtimes=ProviderProcessManager(
            enable_subprocesses=True,
            log_dir=os.getenv(
                "AIDN_RUNTIME_LOG_DIR",
                str(Path.home() / ".local" / "share" / "aidn" / "runtimes" / "logs"),
            ),
            port_allocator=RuntimePortAllocator(
                start_port=int(os.getenv("AIDN_RUNTIME_PORT_START", "8000")),
                end_port=int(os.getenv("AIDN_RUNTIME_PORT_END", "8999")),
            ),
        ),
        state_store=state_store,
        bundle_registry=_default_bundle_registry(plugins),
        model_store=_build_default_model_store(state_store=state_store),
        registry_service=registry_service,
        plugin_host_secret_manager=plugin_host_secret_manager,
        provider_installation_executor=_build_default_provider_installation_executor(),
        node_id=os.getenv("AIDN_NODE_ID", os.getenv("AIDN_CONSENSUS_NODE_ID", "node-local")),
        operator_id=os.getenv("AIDN_OPERATOR_ID", os.getenv("AIDN_CONSENSUS_NODE_ID", "operator-local")),
    )
    if state_store is not None:
        service.restore_state(state_store.load())
    # Explicit environment values are operator configuration.  They may
    # override a persisted enablement flag, but an absent value leaves a
    # restored state untouched for embedded/test callers.
    if os.getenv("AIDN_STEWARD_ENABLED") is not None:
        service.resident_agent.set_enabled(
            _env_bool("AIDN_STEWARD_ENABLED", default=False), persist=False
        )
    model_path = os.getenv("AIDN_STEWARD_MODEL_PATH")
    if model_path:
        service.resident_agent.configure_model(
            model_path=model_path,
            model_repo=os.getenv(
                "AIDN_STEWARD_MODEL_REPO", "Qwen/Qwen2.5-0.5B-Instruct-GGUF"
            ),
            model_file=os.getenv(
                "AIDN_STEWARD_MODEL_FILE",
                "qwen2.5-0.5b-instruct-q4_k_m.gguf",
            ),
            quantization=os.getenv("AIDN_STEWARD_MODEL_QUANT", "Q4_K_M"),
            ram_budget_mb=_env_int(
                "AIDN_STEWARD_RAM_BUDGET_MB", default=1024, minimum=128, maximum=131072
            ),
            persist=False,
        )
    return service


def _build_default_provider_installation_executor():
    """Enable live provider installs only when the host broker opts in.

    Development and test processes retain the recorded/sandbox executor by
    default.  A production Ubuntu bootstrap explicitly enables this path and
    points it at the root-owned dispatcher plus Unix socket broker.
    """

    enabled = os.getenv("AIDN_ENABLE_PROVIDER_RUNTIME_INSTALL", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return None
    dispatcher_path = Path(
        os.getenv(
            "AIDN_PROVIDER_RUNTIME_DISPATCHER",
            "/usr/libexec/aidn-provider-runtime/aidn-provider-runtime-ubuntu.sh",
        )
    )
    socket_path = os.getenv(
        "AIDN_PROVIDER_RUNTIME_BROKER_SOCKET",
        "@aidn-provider-runtime",
    )
    broker = AllowlistedProviderRuntimeBroker(
        dispatcher_path=dispatcher_path,
        runner=UnixSocketProviderRuntimeCommandRunner(socket_path=socket_path),
    )
    return AllowlistedProviderRuntimeInstallationExecutor(broker)


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


def _build_default_model_store(*, state_store: FileStateStore | None) -> FileModelStore | None:
    """Resolve the node-local model store for the production service.

    A persistent Hypervisor state path is the boundary used by the Ubuntu
    bootstrap, so keeping model bytes in its sibling ``models`` directory
    gives a fresh installation a usable store without another manual step.
    Operators may point the store at a larger disk with the explicit
    ``AIDN_HYPERVISOR_MODEL_STORE_PATH`` override.  In-memory/test services
    (which have no state store) retain their opt-in model-store behavior.
    """

    configured_path = os.getenv("AIDN_HYPERVISOR_MODEL_STORE_PATH", "").strip()
    if configured_path:
        return FileModelStore(configured_path)
    if state_store is None:
        return None
    return FileModelStore(state_store.path.parent / "models")


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


def _env_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _build_default_consensus_service(
    *,
    hypervisor_service: HypervisorService,
    state_store: FileStateStore | None,
) -> ConsensusService | None:
    active_config = load_active_cometbft_configuration(hypervisor_service)
    raw_mode = str(
        (active_config or {}).get("mode")
        or os.getenv("AIDN_CONSENSUS_MODE", ConsensusMode.DISABLED.value)
    ).lower()
    try:
        mode = ConsensusMode(raw_mode)
    except ValueError as error:
        raise ValueError("AIDN_CONSENSUS_MODE must be disabled, non_validator, or validator") from error
    if mode == ConsensusMode.DISABLED:
        return None

    protocol_authority_policy = (
        _load_protocol_authority_policy()
        if mode == ConsensusMode.VALIDATOR
        else None
    )

    def configured(name: str, environment: str, default):
        # An applied dashboard configuration is authoritative, including an
        # explicit null/empty value.  Falling back to the bootstrap environment
        # here resurrected a retired local CometBFT unit after an external-RPC
        # non-validator reconnect.
        if active_config is not None and name in active_config:
            return active_config[name]
        return os.getenv(environment, default)

    def configured_optional_string(name: str, environment: str) -> str | None:
        value = configured(name, environment, "")
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    config = ConsensusServiceConfig(
        node_id=str(configured("node_id", "AIDN_CONSENSUS_NODE_ID", hypervisor_service.node_id)),
        mode=mode,
        cometbft_endpoint=str(configured("cometbft_endpoint", "AIDN_COMETBFT_ENDPOINT", "tcp://localhost:26657")),
        validator_pubkey=os.getenv("AIDN_CONSENSUS_VALIDATOR_PUBKEY", ""),
        chain_id=str(configured("chain_id", "AIDN_COMETBFT_CHAIN_ID", "aidn-localnet-1")),
        managed_service_name=configured_optional_string("managed_service_name", "AIDN_COMETBFT_SERVICE"),
        abci_state_path=configured_optional_string("abci_state_path", "AIDN_COMETBFT_ABCI_STATE_PATH"),
        abci_listen_host=str(configured("abci_host", "AIDN_COMETBFT_ABCI_HOST", "127.0.0.1")),
        abci_listen_port=int(configured("abci_port", "AIDN_COMETBFT_ABCI_PORT", "26658")),
        abci_query_timeout_seconds=int(
            os.getenv(
                "AIDN_COMETBFT_ABCI_QUERY_TIMEOUT_SECONDS",
                "10",
            )
        ),
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
        protocol_authority_policy=protocol_authority_policy,
        epoch_schedule=_load_epoch_schedule(),
    )
    consensus = ConsensusService(config)
    if mode != ConsensusMode.VALIDATOR:
        removed_operation_ids = hypervisor_service.ledger_operation_service.remove_noncanonical_operations(
            {"ENDPOINT_UPDATE"}
        )
        if removed_operation_ids:
            hypervisor_service._persist_state()
        return consensus
    if state_store is None:
        raise ValueError("validator mode requires AIDN_HYPERVISOR_STATE_PATH")
    if not config.abci_state_path:
        raise ValueError("validator mode requires AIDN_COMETBFT_ABCI_STATE_PATH")

    # Remove legacy draft updates that were incorrectly recorded as wallet
    # operations before validator writes were made consensus-bound. This must
    # happen before ABCI bootstrap so local and canonical wallet sequences
    # start from the same state.
    durable_snapshot = ABCIStateStore(config.abci_state_path).load_current()
    durable_operations = [
        operation
        for operation in (durable_snapshot or {}).get("ledger_operations", [])
        if isinstance(operation, dict)
    ]
    durable_operation_ids = {
        str(operation.get("operation_id"))
        for operation in durable_operations
        if operation.get("operation_id")
    }
    legacy_operation_ids = {
        str(operation.get("operation_id"))
        for operation in hypervisor_service.ledger_operation_service.snapshot_operations()
        if operation.get("operation_type") == "ENDPOINT_UPDATE"
        and operation.get("operation_id")
    }
    missing_legacy_operation_ids = legacy_operation_ids - durable_operation_ids
    local_operation_ids = {
        str(operation.get("operation_id"))
        for operation in hypervisor_service.ledger_operation_service.snapshot_operations()
        if operation.get("operation_id")
    }
    unexpected_durable_legacy_operations = [
        operation
        for operation in durable_operations
        if operation.get("operation_type") == "ENDPOINT_UPDATE"
        and operation.get("operation_id") not in local_operation_ids
    ]
    if missing_legacy_operation_ids and unexpected_durable_legacy_operations:
        raise ValueError(
            "validator legacy Endpoint migration found changes on both sides"
        )
    if unexpected_durable_legacy_operations:
        raise ValueError(
            "validator durable ABCI state contains a local-only Endpoint update; "
            "refusing to restore a non-canonical operation"
        )
    state_migrated = False
    if missing_legacy_operation_ids:
        if missing_legacy_operation_ids != legacy_operation_ids:
            raise ValueError(
                "validator legacy Endpoint migration found a partially committed operation set"
            )
        removed_operation_ids = hypervisor_service.ledger_operation_service.remove_noncanonical_operations(
            {"ENDPOINT_UPDATE"}
        )
        if set(removed_operation_ids) != legacy_operation_ids:
            raise ValueError(
                "validator legacy Endpoint migration did not remove the expected operations"
            )
        state_migrated = True

    genesis_accounts = _consensus_genesis_accounts()
    genesis_treasury_manifest = _consensus_genesis_treasury_manifest(chain_id=config.chain_id)
    # Hypervisor state is restored before ABCI bootstrap.  Never reapply the
    # disposable test genesis over an already populated local Ledger during a
    # validator restart.
    if hypervisor_service.ledger_operation_service.snapshot_operations():
        genesis_accounts = None

    consensus.bootstrap_validator_abci(
        ledger_service=hypervisor_service.ledger_operation_service,
        genesis_accounts=genesis_accounts,
        genesis_treasury_manifest=genesis_treasury_manifest,
        restore_state_from_store=False,
        state_checkpoint_callback=hypervisor_service._persist_state,
    )

    try:
        consensus.restore_validator_abci_state_if_matching_ledger()
    except ABCIStateStoreError as error:
        if "durable ABCI state does not match the restored Hypervisor Ledger" not in str(error):
            raise
        # A previous release could persist the same operation history without
        # consensus-owned derived fields. Reconcile only from a verified ABCI
        # snapshot; unsafe local-only operations still fail closed there.
        try:
            consensus.reconcile_validator_abci_state_to_canonical_ledger()
        except ABCIStateStoreError as reconciliation_error:
            raise ABCIStateStoreError(
                f"{error}; safe reconciliation refused: {reconciliation_error}"
            ) from reconciliation_error
        state_migrated = True
    if state_migrated:
        hypervisor_service._persist_state()
    return consensus


def _build_default_consensus_installation_executor():
    """Enable the dashboard CometBFT installer only on a bootstrapped host."""

    enabled = os.getenv("AIDN_ENABLE_PROVIDER_RUNTIME_INSTALL", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return None
    socket_path = os.getenv("AIDN_PROVIDER_RUNTIME_BROKER_SOCKET", "").strip()
    if not socket_path:
        return None
    return UnixSocketConsensusRuntimeExecutor(
        UnixSocketProviderRuntimeCommandRunner(socket_path=socket_path)
    )


def _load_epoch_schedule() -> EpochSchedule | None:
    """Load an explicit canonical-time schedule; absent means fail-closed."""
    raw_duration = os.getenv("AIDN_EPOCH_DURATION_SECONDS")
    if raw_duration is None or not raw_duration.strip():
        return None
    try:
        duration = int(raw_duration)
    except ValueError as error:
        raise ValueError("AIDN_EPOCH_DURATION_SECONDS must be an integer") from error
    start_time = os.getenv("AIDN_EPOCH_START_TIME")
    if not start_time:
        raise ValueError("AIDN_EPOCH_START_TIME is required with AIDN_EPOCH_DURATION_SECONDS")
    return build_epoch_schedule(
        genesis_start_time=start_time,
        epoch_duration_seconds=duration,
        parameter_version=os.getenv("AIDN_EPOCH_PARAMETER_VERSION", "genesis"),
        task_set_version=os.getenv("AIDN_EPOCH_TASK_SET_VERSION", "genesis"),
        protocol_version=os.getenv("AIDN_EPOCH_PROTOCOL_VERSION", "0.1"),
    )


def _load_protocol_authority_policy() -> ProtocolAuthorityPolicy:
    """Load public epoch-transition authority config; absent means fail closed."""
    path = os.getenv("AIDN_PROTOCOL_AUTHORITY_POLICY_PATH")
    raw = os.getenv("AIDN_PROTOCOL_AUTHORITY_POLICY_JSON")
    if path and raw:
        raise ValueError(
            "configure only one of AIDN_PROTOCOL_AUTHORITY_POLICY_PATH or "
            "AIDN_PROTOCOL_AUTHORITY_POLICY_JSON"
        )
    if path:
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except OSError as error:
            raise ValueError("could not read AIDN_PROTOCOL_AUTHORITY_POLICY_PATH") from error
    if not raw:
        return ProtocolAuthorityPolicy.empty()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("AIDN_PROTOCOL_AUTHORITY_POLICY_JSON must be valid JSON") from error
    return ProtocolAuthorityPolicy.from_mapping(payload)


def _build_default_canonical_wallet_balance_provider():
    """Build the dashboard wallet read source from finality RPC configuration."""
    config_path = os.getenv("AIDN_COMETBFT_FINALITY_CONFIG")
    if not config_path:
        return None
    config = load_cometbft_finality_deployment_config(Path(config_path))
    return HttpCometBftWalletBalanceProvider(
        [
            HttpCometBftRpcTransport(
                endpoint,
                max_response_bytes=config.max_response_bytes,
            )
            for endpoint in config.rpc_endpoints
        ],
        quorum=config.minimum_agreement,
        timeout_seconds=config.timeout_seconds,
    )


def _build_default_canonical_wallet_identity_provider():
    """Build the Wallet identity read source from finality RPC configuration."""
    config_path = os.getenv("AIDN_COMETBFT_FINALITY_CONFIG")
    if not config_path:
        return None
    config = load_cometbft_finality_deployment_config(Path(config_path))
    return HttpCometBftWalletIdentityProvider(
        [
            HttpCometBftRpcTransport(
                endpoint,
                max_response_bytes=config.max_response_bytes,
            )
            for endpoint in config.rpc_endpoints
        ],
        quorum=config.minimum_agreement,
        timeout_seconds=config.timeout_seconds,
    )


def _build_default_canonical_wallet_sequence_provider():
    """Build the Wallet nonce read source from finality RPC configuration."""
    config_path = os.getenv("AIDN_COMETBFT_FINALITY_CONFIG")
    if not config_path:
        return None
    config = load_cometbft_finality_deployment_config(Path(config_path))
    return HttpCometBftWalletSequenceProvider(
        [
            HttpCometBftRpcTransport(
                endpoint,
                max_response_bytes=config.max_response_bytes,
            )
            for endpoint in config.rpc_endpoints
        ],
        quorum=config.minimum_agreement,
        timeout_seconds=config.timeout_seconds,
    )


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


def _consensus_genesis_treasury_manifest(*, chain_id: str) -> dict | None:
    """Load the secret-free Faucet Treasury Genesis declaration.

    The Faucet policy service and its signer remain external to this process;
    only the initial ordinary Wallet balance is projected into the Ledger.
    """

    raw_path = os.getenv("AIDN_FAUCET_TREASURY_GENESIS_MANIFEST")
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError("AIDN_FAUCET_TREASURY_GENESIS_MANIFEST cannot be read") from error
    except json.JSONDecodeError as error:
        raise ValueError("AIDN_FAUCET_TREASURY_GENESIS_MANIFEST must contain valid JSON") from error
    if not isinstance(raw, dict):
        raise ValueError("AIDN_FAUCET_TREASURY_GENESIS_MANIFEST must contain an object")
    manifest = FaucetTreasuryManifest.model_validate(raw)
    return validate_faucet_treasury_manifest(
        manifest,
        expected_network_id=os.getenv("AIDN_NETWORK_ID") or None,
        expected_chain_id=chain_id,
    ).model_dump(mode="json")


def _default_bundle_registry(plugins: PluginRegistry) -> FileBundleRegistry:
    bundle_path = os.getenv("AIDN_HYPERVISOR_BUNDLES_PATH")
    if not bundle_path:
        bundle_path = os.path.join(os.getcwd(), "bundles.json")
    return FileBundleRegistry(bundle_path)
