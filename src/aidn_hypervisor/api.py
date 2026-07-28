import base64
from collections.abc import Iterable
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from aidn_hypervisor.accounting.models import UsageAcknowledgement, UsageReport
from aidn_hypervisor.dashboard import build_market_payload, load_dashboard_html
from aidn_hypervisor.domain.models import (
    AllocationRequest,
    BundleConfig,
    ModelInstallRequest,
    RegisterBundleFromInstallRequest,
    TaskRequest,
)
from aidn_hypervisor.domain.types import TaskStatus
from aidn_hypervisor.endpoint_publications.models import (
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
from aidn_hypervisor.endpoint_publications.service import (
    EndpointPublicationReadinessError,
)
from aidn_hypervisor.operator_views import (
    build_operator_bundles_payload,
    build_operator_endpoints_payload,
    build_operator_home_payload,
    build_operator_installs_payload,
    build_operator_market_payload,
    build_operator_providers_payload,
    build_operator_remote_endpoints_payload,
)
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.registry_models import (
    RegistryNodeAdvertisement,
    RegistryObjectQuery,
    RegistryWalletIdentityGovernancePolicyUpdateRequest,
    RegistryWalletIdentityGovernanceRevocationRequest,
    RegistryWalletIdentityQuorumApprovalRequest,
    RegistryWalletIdentityQuorumProposalRequest,
    RegistryWalletIdentityResolutionRequest,
)
from aidn_hypervisor.registry_service import RegistryService
from aidn_hypervisor.remote_endpoints.service import RemoteEndpointDependencyError
from aidn_hypervisor.service import AllocationUnavailableError, HypervisorService
from aidn_hypervisor.session_application_service import SessionApplicationService
from aidn_hypervisor.session_read_models import (
    build_operator_sessions_payload,
)
from aidn_hypervisor.state import HypervisorStateSnapshot
from aidn_hypervisor.validation_read_models import (
    build_endpoint_proof_payload,
    build_endpoint_validation_history_payload,
    build_endpoint_validation_summary_payload,
    build_publication_validation_payload,
    build_validation_epoch_payload,
    build_validation_maintenance_payload,
    build_validation_report_payload,
    build_validation_request_payload,
    validation_summary_for,
)
from aidn_hypervisor.wallet_models import (
    WalletAllocationCorrectionRequest,
    WalletAllocationDisputeRequest,
    WalletAllocationDisputeResolveRequest,
    WalletAllocationHoldRequest,
    WalletAllocationReleaseRequest,
    WalletAllocationReopenRequest,
    WalletQuoteRequest,
    WalletUsageRecordRequest,
)
from aidn_hypervisor.wallet_read_models import (
    build_ledger_operations_export_payload,
    build_ledger_operations_payload,
    build_operator_wallet_payload,
    build_wallet_allocation_activation_events_payload,
    build_wallet_allocation_activation_export_payload,
    build_wallet_allocation_dispute_events_payload,
    build_wallet_allocation_dispute_export_payload,
    build_wallet_allocation_events_payload,
    build_wallet_allocation_export_payload,
    build_wallet_economics_export_payload,
    build_wallet_economics_summary_payload,
    build_wallet_endpoint_publications_export_payload,
    build_wallet_endpoint_publications_payload,
    build_wallet_faucet_preview_payload,
    build_wallet_ledger_events_payload,
    build_wallet_ledger_export_payload,
    build_wallet_session_events_payload,
    build_wallet_session_export_payload,
    build_wallet_usage_events_payload,
    build_wallet_usage_export_payload,
)

_ACTIVE_TASK_STATUSES: set[TaskStatus] = {"queued", "admitted", "starting", "running"}


class AttachProviderInstanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    display_name: str
    configuration: dict


class WalletIdentityRegistrationRequest(BaseModel):
    wallet_id: str = Field(min_length=1)
    public_key: str = Field(min_length=1)
    registration_nonce: str = Field(min_length=1)
    signature: str = Field(min_length=1)


class CreateRuntimeBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    capability_version: str
    capability_definition_hash: str


class BuildProviderInstallationPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configuration: dict = Field(default_factory=dict)


class ApproveProviderInstallationPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configuration: dict = Field(default_factory=dict)
    approved_permissions: list[str] = Field(default_factory=list)
    upgrade_acknowledged: bool = False
    selected_secret_handles: list[dict] = Field(default_factory=list)
    operator_note: str | None = None


class ProviderInstallationDiagnosticsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    configuration: dict = Field(default_factory=dict)
    approved_permissions: list[str] = Field(default_factory=list)
    upgrade_acknowledged: bool = False
    selected_secret_handles: list[dict] = Field(default_factory=list)


class RegisterProviderPluginReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: dict
    source_reference: str | None = None
    release_status: Literal[
        "AVAILABLE",
        "DEPRECATED",
        "SECURITY_WARNING",
        "SECURITY_BLOCKED",
        "REVOKED",
    ] = "AVAILABLE"


class InstallProviderPluginReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    granted_permissions: list[str] = Field(default_factory=list)
    installation_source: Literal["PACKAGE", "LEGACY_BUILTIN"] = "PACKAGE"


class ApplyProviderInstallationApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RollbackProviderInstallationJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StageProviderInstallationArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relative_path: str
    content_base64: str


class DeleteProviderInstallationArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relative_path: str


class ExtractProviderInstallationArtifactArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archive_relative_path: str
    destination_directory: str


class PromoteProviderInstallationArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    relative_path: str


class DeleteModelArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str


class CreateModelArtifactSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str
    files: list[dict] = Field(default_factory=list)


class DeleteModelArtifactSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_set_id: str


class BindModelArtifactSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_set_id: str


class MaterializeModelArtifactSetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_set_id: str
    destination: str


def _ok(data: dict, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "data": data,
            "error": None,
            "correlation_id": str(uuid4()),
        },
    )


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    details: dict | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "data": None,
            "error": {
                "code": code,
                "message": message,
                **({"details": details} if details is not None else {}),
            },
            "correlation_id": str(uuid4()),
        },
    )


def _execution_payload_for_manifest(manifest) -> dict:
    runtime_binding = {"runtime_binding_id": manifest.runtime_binding_id}
    if manifest.execution_strategy != "proxy" or manifest.proxy_target is None:
        return {"strategy": manifest.execution_strategy, **runtime_binding}
    return {
        "strategy": manifest.execution_strategy,
        "target_fingerprint": configuration_hash_for_publication(
            {
                "remote_endpoint_id": manifest.proxy_target.remote_endpoint_id,
                "source_publication_id": manifest.proxy_target.source_publication_id,
                "source_configuration_hash": manifest.proxy_target.source_configuration_hash,
            }
        ),
        **runtime_binding,
    }


def _local_publication_configuration_hash(manifest) -> str:
    payload = canonical_configuration_payload(
        bundle_hash=manifest.bundle_hash,
        model_class=manifest.model_class,
        capabilities=manifest.capabilities,
        runtime=manifest.runtime.model_dump(mode="json"),
        publication=manifest.publication.model_dump(mode="json"),
        pricing=manifest.pricing.model_dump(mode="json"),
        session=manifest.session.model_dump(mode="json"),
        execution=_execution_payload_for_manifest(manifest),
    )
    return configuration_hash_for_publication(payload)


def _publication_sync_status(
    *,
    local_configuration_hash: str | None,
    published_configuration_hash: str | None,
) -> str:
    if published_configuration_hash is None:
        return "never_published"
    if local_configuration_hash == published_configuration_hash:
        return "in_sync"
    return "local_changes_not_published"


def _snapshot_publication_configuration_hash(manifest, snapshot) -> str:
    snapshot_manifest = manifest.model_copy(
        update={
            "bundle_hash": snapshot.bundle_hash,
            "runtime": snapshot.runtime,
            "publication": snapshot.publication,
            "session": snapshot.session,
            "execution_strategy": snapshot.execution_config.get(
                "execution_strategy",
                manifest.execution_strategy,
            ),
            "proxy_target": snapshot.proxy_target,
        }
    )
    return _local_publication_configuration_hash(snapshot_manifest)


def _configuration_hash_for_publication_record(
    *,
    endpoint_service,
    manifest,
    publication_configuration_hash: str | None,
) -> str | None:
    if (
        endpoint_service is None
        or manifest is None
        or publication_configuration_hash is None
    ):
        return None
    for snapshot in reversed(
        endpoint_service.list_configuration_snapshots(manifest.endpoint_id)
    ):
        if (
            _snapshot_publication_configuration_hash(manifest, snapshot)
            == publication_configuration_hash
        ):
            return snapshot.configuration_hash
    return None


def _registry_published_endpoint_summaries(
    *,
    advertisement: dict,
    endpoint_service,
    validation_service=None,
) -> list[dict]:
    manifests = {}
    if endpoint_service is not None:
        manifests = {
            manifest.endpoint_id: manifest
            for manifest in endpoint_service.list_endpoints()
        }

    items: list[dict] = []
    for entry in advertisement.get("published_endpoints", []):
        item = dict(entry)
        manifest = manifests.get(item["endpoint_id"])
        local_configuration_hash = (
            _local_publication_configuration_hash(manifest)
            if manifest is not None
            else None
        )
        live_configuration_hash = (
            manifest.configuration_hash if manifest is not None else None
        )
        item["publication_sync_status"] = item.get("publication_sync_status") or _publication_sync_status(
            local_configuration_hash=local_configuration_hash,
            published_configuration_hash=item.get("current_configuration_hash"),
        )
        published_endpoint_configuration_hash = _configuration_hash_for_publication_record(
            endpoint_service=endpoint_service,
            manifest=manifest,
            publication_configuration_hash=item.get("current_configuration_hash"),
        )
        item["published_validation_summary"] = item.get(
            "published_validation_summary"
        ) or validation_summary_for(
            validation_service,
            endpoint_id=item["endpoint_id"],
            configuration_hash=published_endpoint_configuration_hash,
        )
        item["live_validation_summary"] = item.get("live_validation_summary") or validation_summary_for(
            validation_service,
            endpoint_id=item["endpoint_id"],
            configuration_hash=live_configuration_hash,
        )
        items.append(item)
    return items


def _operator_dashboard_endpoints_payload(
    *,
    service: HypervisorService,
    endpoint_service,
    endpoint_publication_service=None,
    validation_service=None,
) -> dict:
    return build_operator_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
        validation_service=validation_service,
    )


def _operator_dashboard_sessions_payload(
    *,
    service: HypervisorService,
    endpoint_service=None,
    session_service=None,
) -> dict:
    return build_operator_sessions_payload(
        service=service,
        endpoint_service=endpoint_service,
        session_service=session_service,
    )


class OperatorRequestsPolicyRequest(BaseModel):
    allow_spillover: bool
    dispatch_strategy: str
    ready_endpoint_only: bool


class WalletBootstrapCreateRequest(BaseModel):
    label: str | None = None


class WalletBootstrapImportRequest(BaseModel):
    private_key: str
    label: str | None = None


class RemoteEndpointAttachRequest(BaseModel):
    node_id: str
    endpoint_id: str
    alias: str | None = None
    routing_mode: str = "preferred"


class OperatorSessionCloseActionRequest(BaseModel):
    session_id: str


class OperatorSessionSweepIdleActionRequest(BaseModel):
    now: str | None = None


class SessionUsageReportRecordRequest(BaseModel):
    usage_report: UsageReport
    acknowledgement_timeout_seconds: int = Field(ge=0)


class SessionUsageAcknowledgementRecordRequest(BaseModel):
    usage_acknowledgement: UsageAcknowledgement
    accepted_charge_q: float = Field(ge=0.0)


class ValidationEpochCreateRequest(BaseModel):
    epoch_id: str
    seed: str
    validator_entries: list[dict]


class ValidationReportSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: str | None = None
    outcome: Literal["pass", "fail"] | None = None
    validator_label: str
    evidence_summary: str
    detected_issues: list[dict] = Field(default_factory=list)


class ValidationMaintenanceSubmitRequest(ValidationReportSubmitRequest):
    pass


def _recommendation_from_request(
    request: ValidationReportSubmitRequest,
) -> str | None:
    recommendation = request.recommendation
    if recommendation is None and request.outcome is not None:
        if request.outcome == "pass":
            recommendation = "certify"
        elif request.outcome == "fail":
            recommendation = "do_not_certify"
    return recommendation


def build_api_router(
    service: HypervisorService,
    *,
    registry_service=None,
    endpoint_service=None,
    endpoint_publication_service=None,
    remote_endpoint_service=None,
    session_service=None,
    validation_service=None,
) -> APIRouter:
    router = APIRouter()
    session_application_service = (
        SessionApplicationService(
            hypervisor_service=service,
            session_service=session_service,
        )
        if session_service is not None
        else None
    )

    def _effective_registry_service() -> RegistryService:
        if registry_service is not None:
            local_registry = registry_service
        else:
            session_registry = getattr(session_service, "registry_service", None)
            local_registry = (
                session_registry
                if isinstance(session_registry, RegistryService)
                else RegistryService()
            )
        advertisement = RegistryNodeAdvertisement(**service.node_advertisement())
        local_registry.upsert_node(advertisement)
        local_source = local_registry.get_node(advertisement.node_id)
        ingest_registry_objects = getattr(local_registry, "ingest_registry_objects", None)
        if callable(ingest_registry_objects):
            ingest_registry_objects(
                [
                    {
                        **record.model_dump(mode="json"),
                        "_source": {
                            "node_id": local_source["node_id"],
                            "operator_id": local_source["operator_id"],
                            "status": local_source["status"],
                        },
                    }
                    for record in advertisement.canonical_registry_objects
                ]
            )
        return local_registry

    def _task_proxy_session_payload(task_request: TaskRequest) -> dict | None:
        if session_service is None:
            return None
        session_id = task_request.constraints.get("session_id")
        if session_id is None:
            return None
        binding = session_service.try_get_proxy_session_binding(str(session_id))
        if binding is None:
            return None
        return binding.model_dump(mode="json")

    @router.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
    async def submit_task(request: TaskRequest) -> dict:
        try:
            task = service.submit(request)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return _serialize_task(
            task_id=task.task_id,
            status=task.status,
            priority=task.priority,
            task_type=task.request.task_type,
            bundle_id=service.selected_bundle_id(task.task_id),
        )

    @router.get("/tasks/{task_id}")
    async def get_task(task_id: str) -> dict:
        try:
            task = service.get_task(task_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}") from error
        proxy_trace = service.task_proxy_trace(task.task_id)

        return _serialize_task(
            task_id=task.task_id,
            status=task.status,
            priority=task.priority,
            task_type=task.request.task_type,
            bundle_id=service.selected_bundle_id(task.task_id),
            result=service.task_result(task.task_id),
            recovery_reason=service.task_recovery_reason(task.task_id),
            proxy_trace=proxy_trace if proxy_trace is not None else ...,
            proxy_session=(
                _task_proxy_session_payload(task.request)
                if _task_proxy_session_payload(task.request) is not None
                else ...
            ),
            history=[
                event.model_dump(mode="json")
                for event in service.task_history(task.task_id)
            ],
        )

    @router.post("/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str) -> dict:
        try:
            task = service.cancel_task(task_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown task: {task_id}") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

        return _serialize_task(
            task_id=task.task_id,
            status=task.status,
            priority=task.priority,
            task_type=task.request.task_type,
            bundle_id=service.selected_bundle_id(task.task_id),
            result=service.task_result(task.task_id),
        )

    @router.get("/queue")
    async def queue_snapshot() -> list[dict]:
        return [
            _serialize_task(
                task_id=task.task_id,
                status=task.status,
                priority=task.priority,
                task_type=task.request.task_type,
                bundle_id=service.selected_bundle_id(task.task_id),
            )
            for task in service.queue.snapshot()
            if task.status in _ACTIVE_TASK_STATUSES
        ]

    @router.post("/allocations", status_code=status.HTTP_201_CREATED)
    async def create_allocation(request: AllocationRequest) -> dict:
        try:
            return service.create_allocation(request)
        except AllocationUnavailableError as error:
            raise HTTPException(status_code=409, detail=error.as_detail()) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/allocations")
    async def list_allocations() -> list[dict]:
        return service.list_allocations()

    @router.get("/allocations/{allocation_id}")
    async def get_allocation(allocation_id: str) -> dict:
        try:
            return service.get_allocation(allocation_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown allocation: {allocation_id}",
            ) from error

    @router.post("/allocations/{allocation_id}/reconcile")
    async def reconcile_allocation(allocation_id: str) -> dict:
        try:
            return service.reconcile_allocation(allocation_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown allocation: {allocation_id}",
            ) from error

    @router.delete("/allocations/{allocation_id}")
    async def release_allocation(allocation_id: str) -> dict:
        try:
            return service.release_allocation(allocation_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown allocation: {allocation_id}",
            ) from error

    @router.get("/capabilities")
    async def list_capabilities() -> list[dict]:
        return service.capability_inventory()

    @router.get("/agent/capabilities")
    async def agent_capabilities(
        owner_id: str,
        workload_type: str | None = None,
        bundle_id: str | None = None,
        include_disabled: bool = False,
    ) -> dict:
        return service.capability_catalog(
            owner_id=owner_id,
            workload_type=workload_type,
            bundle_id=bundle_id,
            include_disabled=include_disabled,
        )

    @router.get("/diagnostics/queue")
    async def queue_diagnostics() -> dict:
        return {
            "summary": service.queue_summary(),
            "items": service.queue_diagnostics(),
        }

    @router.get("/diagnostics/admission")
    async def admission_diagnostics() -> dict:
        return {
            "summary": service.queue_summary(),
            "items": service._runtime_boundary.admission_telemetry(),
        }

    @router.get("/bundles")
    async def list_bundles() -> list[dict]:
        runtimes = service.list_runtimes()
        return [
            {
                "bundle_id": bundle.bundle_id,
                "plugin_id": bundle.plugin_id,
                "provider_type": bundle.provider_type,
                "workload_type": bundle.workload_type,
                "model_id": bundle.model_id,
                "launch_mode": bundle.launch_mode,
                "enabled": bundle.enabled,
                "priority_class": bundle.priority_class,
                "status": _bundle_status(
                    bundle,
                    runtimes,
                    service.bundle_state(bundle.bundle_id),
                ),
            }
            for bundle in service.bundles
        ]

    @router.get("/runtimes")
    async def list_runtimes() -> list[dict]:
        return [
            {
                "runtime_id": runtime.runtime_id,
                "bundle_id": runtime.bundle_id,
                "command": runtime.command,
                "status": runtime.status,
                "health_status": runtime.health_status,
                "active_task_count": service._runtime_boundary.runtime_active_task_count(
                    runtime.bundle_id or ""
                ),
                "failure_streak": service.bundle_state(runtime.bundle_id or "")[
                    "failure_streak"
                ],
                "cooldown_until": service.bundle_state(runtime.bundle_id or "")[
                    "cooldown_until"
                ],
                "cooldown_reason": service.bundle_state(runtime.bundle_id or "")[
                    "cooldown_reason"
                ],
                "drain_mode": service.bundle_state(runtime.bundle_id or "")[
                    "drain_mode"
                ],
                "drain_reason": service.bundle_state(runtime.bundle_id or "")[
                    "drain_reason"
                ],
            }
            for runtime in service.list_runtimes()
        ]

    @router.get("/runtimes/{runtime_id}")
    async def get_runtime(runtime_id: str) -> dict:
        try:
            runtime = service.get_runtime(runtime_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown runtime: {runtime_id}") from error

        return {
            "runtime_id": runtime.runtime_id,
            "bundle_id": runtime.bundle_id,
            "command": runtime.command,
            "status": runtime.status,
            "health_status": runtime.health_status,
            "active_task_count": service._runtime_boundary.runtime_active_task_count(
                runtime.bundle_id or ""
            ),
            "failure_streak": service.bundle_state(runtime.bundle_id or "")[
                "failure_streak"
            ],
            "cooldown_until": service.bundle_state(runtime.bundle_id or "")[
                "cooldown_until"
            ],
            "cooldown_reason": service.bundle_state(runtime.bundle_id or "")[
                "cooldown_reason"
            ],
            "drain_mode": service.bundle_state(runtime.bundle_id or "")[
                "drain_mode"
            ],
            "drain_reason": service.bundle_state(runtime.bundle_id or "")[
                "drain_reason"
            ],
            "history": [
                event.model_dump(mode="json")
                for event in service.runtime_history(runtime.runtime_id)
            ],
        }

    @router.post("/bundles/{bundle_id}/start")
    async def start_bundle(bundle_id: str) -> dict:
        try:
            runtime = service.start_bundle(bundle_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown bundle: {bundle_id}") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

        return {
            "runtime_id": runtime.runtime_id,
            "bundle_id": runtime.bundle_id,
            "command": runtime.command,
            "status": runtime.status,
        }

    @router.post("/bundles/{bundle_id}/stop")
    async def stop_bundle(bundle_id: str) -> dict:
        try:
            return service.stop_bundle(bundle_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown bundle: {bundle_id}") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/process-pending")
    async def process_pending() -> dict:
        return service.process_pending()

    @router.get("/operators/state")
    async def export_state() -> dict:
        return service.snapshot_state().model_dump(mode="json")

    @router.post("/operators/state/restore")
    async def restore_state(snapshot: HypervisorStateSnapshot) -> dict:
        return service.restore_state(snapshot)

    @router.get("/operators/events")
    async def event_journal(limit: int = 100) -> list[dict]:
        return [event.model_dump(mode="json") for event in service.event_journal(limit=limit)]

    @router.get("/operators/registry/advertisement")
    async def registry_advertisement() -> dict:
        advertisement = service.node_advertisement()
        advertisement["published_endpoints"] = _registry_published_endpoint_summaries(
            advertisement=advertisement,
            endpoint_service=endpoint_service,
            validation_service=validation_service,
        )
        return advertisement

    @router.get("/operators/registry/objects")
    async def registry_objects(
        object_type: str | None = None,
        namespace: str | None = None,
        source_reference: str | None = None,
        node_id: str | None = None,
        include_stale: bool = False,
        include_payload: bool = False,
        limit: int = 50,
    ) -> dict:
        query = RegistryObjectQuery(
            object_type=object_type,
            namespace=namespace,
            source_reference=source_reference,
            node_id=node_id,
            include_stale=include_stale,
            include_payload=include_payload,
            limit=limit,
        )
        registry = _effective_registry_service()
        return {
            "query": query.model_dump(mode="json"),
            "objects": registry.list_registry_objects(query),
        }

    @router.get("/operators/registry/objects/{object_id}")
    async def registry_object(object_id: str, include_payload: bool = False) -> dict:
        registry = _effective_registry_service()
        try:
            return registry.get_registry_object(
                object_id,
                include_payload=include_payload,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404, detail=f"Unknown registry object: {object_id}"
            ) from error

    @router.get("/operators/registry/conflicts")
    async def registry_conflicts(
        conflict_class: str | None = None,
        object_type: str | None = None,
        logical_key: str | None = None,
        limit: int = 100,
    ) -> dict:
        registry = _effective_registry_service()
        return {
            "conflicts": registry.list_conflicts(
                conflict_class=conflict_class,
                object_type=object_type,
                logical_key=logical_key,
                limit=limit,
            )
        }

    @router.get("/operators/registry/wallet-identities/reconciliation")
    async def operator_wallet_identity_reconciliation(limit: int = 500) -> dict:
        registry = _effective_registry_service()
        return registry.wallet_identity_reconciliation_report(limit=limit)

    @router.get("/operators/registry/wallet-identities/governance-policy")
    async def operator_wallet_identity_governance_policy() -> dict:
        registry = _effective_registry_service()
        return registry.wallet_identity_governance_policy()

    @router.get("/operators/registry/wallet-identities/governance-certificates")
    async def operator_wallet_identity_governance_certificates(limit: int = 500) -> dict:
        registry = _effective_registry_service()
        return {"items": registry.list_wallet_identity_governance_certificates(limit=limit)}

    @router.get(
        "/operators/registry/wallet-identities/governance-certificates/{certificate_id}/ledger-proof"
    )
    async def operator_wallet_identity_governance_certificate_ledger_proof(
        certificate_id: str,
    ) -> dict:
        registry = _effective_registry_service()
        proof = registry.wallet_identity_governance_certificate_ledger_proof(certificate_id)
        if proof is None:
            raise HTTPException(status_code=404, detail="Ledger proof is unavailable")
        return proof

    @router.get(
        "/operators/registry/wallet-identities/governance-certificates/{certificate_id}/peer-proof-report"
    )
    async def operator_wallet_identity_governance_certificate_peer_proof_report(
        certificate_id: str,
        timeout_seconds: int = 10,
    ) -> dict:
        registry = _effective_registry_service()
        try:
            return registry.wallet_identity_governance_certificate_peer_proof_report(
                certificate_id,
                timeout_seconds=timeout_seconds,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown certificate: {error.args[0]}") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get(
        "/operators/registry/wallet-identities/governance-revocations/{certificate_id}/ledger-proof"
    )
    async def operator_wallet_identity_governance_revocation_ledger_proof(
        certificate_id: str,
    ) -> dict:
        registry = _effective_registry_service()
        proof = registry.wallet_identity_governance_revocation_ledger_proof(certificate_id)
        if proof is None:
            raise HTTPException(status_code=404, detail="Ledger proof is unavailable")
        return proof

    @router.get(
        "/operators/registry/wallet-identities/governance-revocations/{certificate_id}/peer-proof-report"
    )
    async def operator_wallet_identity_governance_revocation_peer_proof_report(
        certificate_id: str,
        timeout_seconds: int = 10,
    ) -> dict:
        registry = _effective_registry_service()
        try:
            return registry.wallet_identity_governance_revocation_peer_proof_report(
                certificate_id,
                timeout_seconds=timeout_seconds,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown revocation: {error.args[0]}") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/registry/wallet-identities/governance-revocations")
    async def operator_wallet_identity_governance_revocations(limit: int = 500) -> dict:
        registry = _effective_registry_service()
        return {"items": registry.list_wallet_identity_governance_revocations(limit=limit)}

    @router.post("/operators/registry/wallet-identities/governance-revocations")
    async def operator_revoke_wallet_identity_governance_certificate(
        payload: RegistryWalletIdentityGovernanceRevocationRequest,
    ) -> dict:
        registry = _effective_registry_service()
        try:
            return registry.revoke_wallet_identity_governance_certificate(
                certificate_id=payload.certificate_id,
                reason=payload.reason,
                approvals=payload.approvals,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown certificate: {error.args[0]}") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/registry/wallet-identities/governance-policy")
    async def update_operator_wallet_identity_governance_policy(
        payload: RegistryWalletIdentityGovernancePolicyUpdateRequest,
    ) -> dict:
        registry = _effective_registry_service()
        try:
            return registry.update_wallet_identity_governance_policy(
                authorized_voter_statuses=payload.authorized_voter_statuses,
                threshold_mode=payload.threshold_mode,
                minimum_eligible_voter_count=payload.minimum_eligible_voter_count,
                minimum_quorum_threshold=payload.minimum_quorum_threshold,
                quorum_resolution_required=payload.quorum_resolution_required,
                ledger_authorization_required=payload.ledger_authorization_required,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/registry/wallet-identities/resolve-conflict")
    async def operator_resolve_wallet_identity_conflict(
        payload: RegistryWalletIdentityResolutionRequest,
    ) -> dict:
        registry = _effective_registry_service()
        try:
            return registry.resolve_wallet_identity_conflict(
                wallet_id=payload.wallet_id,
                chosen_object_id=payload.chosen_object_id,
                chosen_payload_hash=payload.chosen_payload_hash,
                operator_note=payload.operator_note,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown wallet identity: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/registry/wallet-identities/quorum-proposals")
    async def operator_wallet_identity_quorum_proposals() -> dict:
        registry = _effective_registry_service()
        return {"items": registry.list_wallet_identity_resolution_proposals()}

    @router.post("/operators/registry/wallet-identities/quorum-proposals")
    async def operator_propose_wallet_identity_quorum_resolution(
        payload: RegistryWalletIdentityQuorumProposalRequest,
    ) -> dict:
        registry = _effective_registry_service()
        try:
            return registry.propose_wallet_identity_quorum_resolution(
                wallet_id=payload.wallet_id,
                chosen_object_id=payload.chosen_object_id,
                chosen_payload_hash=payload.chosen_payload_hash,
                proposer_node_id=payload.proposer_node_id,
                proposer_signature=payload.proposer_signature,
                eligible_voter_node_ids=payload.eligible_voter_node_ids,
                quorum_threshold=payload.quorum_threshold,
                operator_note=payload.operator_note,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown wallet identity: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post(
        "/operators/registry/wallet-identities/quorum-proposals/{resolution_id}/approvals"
    )
    async def operator_approve_wallet_identity_quorum_resolution(
        resolution_id: str,
        payload: RegistryWalletIdentityQuorumApprovalRequest,
    ) -> dict:
        if payload.resolution_id != resolution_id:
            raise HTTPException(
                status_code=409,
                detail="resolution_id in path and body must match",
            )
        registry = _effective_registry_service()
        try:
            return registry.approve_wallet_identity_quorum_resolution(
                resolution_id=payload.resolution_id,
                approver_node_id=payload.approver_node_id,
                approval_signature=payload.approval_signature,
                approval_note=payload.approval_note,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown resolution proposal: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/dashboard/home")
    async def operator_dashboard_home() -> dict:
        market = build_market_payload(
            service=service,
            registry_service=registry_service,
        )
        return build_operator_home_payload(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=endpoint_publication_service,
            validation_service=validation_service,
            market_candidates=market["candidates"],
        )

    @router.get("/operators/dashboard/fleet")
    async def operator_dashboard_fleet() -> dict:
        return service.operator_dashboard_fleet()

    @router.get("/operators/services")
    async def operator_services() -> dict:
        return service.canonical_overlay_inventory()

    @router.get("/operators/dashboard/providers")
    async def operator_dashboard_providers() -> dict:
        return build_operator_providers_payload(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=endpoint_publication_service,
            validation_service=validation_service,
        )

    @router.get("/operators/provider-plugins")
    async def list_provider_plugins() -> dict:
        return {"items": service.provider_inventory.list_plugin_manifests()}

    @router.get("/operators/provider-plugin-releases")
    async def list_provider_plugin_releases() -> dict:
        return {"items": service.list_provider_plugin_releases()}

    @router.get("/operators/installed-provider-plugins")
    async def list_installed_provider_plugins() -> dict:
        return {"items": service.list_installed_provider_plugins()}

    @router.get("/operators/plugin-host/status")
    async def provider_plugin_host_status() -> dict:
        return service.plugin_host_status()

    @router.post("/operators/provider-plugin-releases")
    async def register_provider_plugin_release(
        payload: RegisterProviderPluginReleaseRequest,
    ) -> dict:
        try:
            return service.register_provider_plugin_release(
                manifest=payload.manifest,
                source_reference=payload.source_reference,
                release_status=payload.release_status,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/provider-plugin-releases/{release_id}/install")
    async def install_provider_plugin_release(
        release_id: str,
        payload: InstallProviderPluginReleaseRequest,
    ) -> dict:
        try:
            return service.install_provider_plugin_release(
                release_id=release_id,
                granted_permissions=payload.granted_permissions,
                installation_source=payload.installation_source,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown plugin release: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/provider-plugins/{plugin_id}/installation-plan")
    async def build_provider_installation_plan(
        plugin_id: str,
        payload: BuildProviderInstallationPlanRequest,
    ) -> dict:
        try:
            return service.build_provider_installation_plan(
                plugin_id=plugin_id,
                configuration=payload.configuration,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown plugin: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/provider-plugins/{plugin_id}/installation-approvals")
    async def approve_provider_installation_plan(
        plugin_id: str,
        payload: ApproveProviderInstallationPlanRequest,
    ) -> dict:
        try:
            return service.approve_provider_installation_plan(
                plugin_id=plugin_id,
                configuration=payload.configuration,
                approved_permissions=payload.approved_permissions,
                upgrade_acknowledged=payload.upgrade_acknowledged,
                selected_secret_handles=payload.selected_secret_handles,
                operator_note=payload.operator_note,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown plugin: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/provider-plugins/{plugin_id}/installation-diagnostics")
    async def run_provider_installation_diagnostics(
        plugin_id: str,
        payload: ProviderInstallationDiagnosticsRequest,
    ) -> dict:
        try:
            return service.run_provider_installation_diagnostics(
                plugin_id=plugin_id,
                configuration=payload.configuration,
                approved_permissions=payload.approved_permissions,
                upgrade_acknowledged=payload.upgrade_acknowledged,
                selected_secret_handles=payload.selected_secret_handles,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown plugin: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/provider-installation-approvals")
    async def list_provider_installation_approvals() -> dict:
        return {"items": service.list_provider_installation_approvals()}

    @router.post("/operators/provider-installation-approvals/{approval_id}/apply")
    async def apply_provider_installation_approval(
        approval_id: str,
        payload: ApplyProviderInstallationApprovalRequest,
    ) -> dict:
        del payload
        try:
            return service.apply_provider_installation_approval(approval_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown approval: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/provider-installation-jobs")
    async def list_provider_installation_jobs() -> dict:
        return {"items": service.list_provider_installation_jobs()}

    @router.get("/operators/provider-installation-artifacts")
    async def list_provider_installation_artifacts() -> dict:
        return service.list_provider_installation_artifacts()

    @router.post("/operators/provider-installation-artifacts")
    async def stage_provider_installation_artifact(
        payload: StageProviderInstallationArtifactRequest,
    ) -> dict:
        try:
            content_bytes = base64.b64decode(payload.content_base64, validate=True)
        except Exception as error:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid base64 artifact content: {error}",
            ) from error
        try:
            return service.stage_provider_installation_artifact(
                relative_path=payload.relative_path,
                content_bytes=content_bytes,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/provider-installation-artifacts/remove")
    async def delete_provider_installation_artifact(
        payload: DeleteProviderInstallationArtifactRequest,
    ) -> dict:
        try:
            return service.delete_provider_installation_artifact(
                relative_path=payload.relative_path,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown installation artifact: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/provider-installation-artifacts/extract")
    async def extract_provider_installation_artifact_archive(
        payload: ExtractProviderInstallationArtifactArchiveRequest,
    ) -> dict:
        try:
            return service.extract_provider_installation_artifact_archive(
                archive_relative_path=payload.archive_relative_path,
                destination_directory=payload.destination_directory,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown installation artifact: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/model-artifacts")
    async def list_model_artifacts() -> dict:
        return service.list_model_artifacts()

    @router.post("/operators/model-artifacts/promote")
    async def promote_provider_installation_artifact(
        payload: PromoteProviderInstallationArtifactRequest,
    ) -> dict:
        try:
            return service.promote_provider_installation_artifact_to_model_store(
                relative_path=payload.relative_path,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown installation artifact: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/model-artifacts/remove")
    async def delete_model_artifact(
        payload: DeleteModelArtifactRequest,
    ) -> dict:
        try:
            return service.delete_model_artifact(artifact_id=payload.artifact_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown model artifact: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/model-artifacts/collect")
    async def collect_model_artifact_garbage() -> dict:
        try:
            return service.collect_model_artifact_garbage()
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/model-artifact-sets")
    async def list_model_artifact_sets() -> dict:
        return {"items": service.list_model_artifact_sets()}

    @router.post("/operators/model-artifact-sets")
    async def create_model_artifact_set(
        payload: CreateModelArtifactSetRequest,
    ) -> dict:
        try:
            return service.create_model_artifact_set(
                display_name=payload.display_name,
                files=payload.files,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown model artifact: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/model-artifact-sets/remove")
    async def delete_model_artifact_set(
        payload: DeleteModelArtifactSetRequest,
    ) -> dict:
        try:
            return service.delete_model_artifact_set(artifact_set_id=payload.artifact_set_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown model artifact set: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/model-deployments/{model_deployment_id}/artifact-set")
    async def bind_model_artifact_set(
        model_deployment_id: str,
        payload: BindModelArtifactSetRequest,
    ) -> dict:
        try:
            return service.bind_model_artifact_set(
                model_deployment_id=model_deployment_id,
                artifact_set_id=payload.artifact_set_id,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown model deployment or artifact set: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/model-artifact-materializations")
    async def list_model_artifact_materializations() -> dict:
        return {"items": service.list_model_artifact_materializations()}

    @router.post("/operators/provider-instances/{provider_instance_id}/artifact-sets/materialize")
    async def materialize_model_artifact_set(
        provider_instance_id: str,
        payload: MaterializeModelArtifactSetRequest,
    ) -> dict:
        try:
            return service.materialize_model_artifact_set(
                provider_instance_id=provider_instance_id,
                artifact_set_id=payload.artifact_set_id,
                destination=payload.destination,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown provider or artifact set: {error.args[0]}") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/provider-installation-jobs/{job_id}/rollback")
    async def rollback_provider_installation_job(
        job_id: str,
        payload: RollbackProviderInstallationJobRequest,
    ) -> dict:
        del payload
        try:
            return service.rollback_provider_installation_job(job_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown installation job: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/provider-instances/attach")
    async def attach_provider_instance(payload: AttachProviderInstanceRequest) -> dict:
        try:
            return service.attach_provider_instance(**payload.model_dump(mode="json"))
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown plugin: {error.args[0]}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/provider-instances/{provider_instance_id}/discover-models")
    async def discover_provider_models(provider_instance_id: str) -> dict:
        try:
            return {"items": service.discover_provider_models(provider_instance_id)}
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown provider instance: {provider_instance_id}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/model-deployments/{model_deployment_id}/runtime-bindings")
    async def create_runtime_binding(
        model_deployment_id: str,
        payload: CreateRuntimeBindingRequest,
    ) -> dict:
        try:
            return service.create_runtime_binding(
                model_deployment_id=model_deployment_id,
                **payload.model_dump(mode="json"),
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown model deployment: {model_deployment_id}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/dashboard/bundles")
    async def operator_dashboard_bundles() -> dict:
        return build_operator_bundles_payload(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=endpoint_publication_service,
            validation_service=validation_service,
        )

    @router.get("/operators/dashboard/installs")
    async def operator_dashboard_installs() -> dict:
        return build_operator_installs_payload(service=service)

    @router.get("/operators/dashboard/endpoints")
    async def operator_dashboard_endpoints() -> dict:
        return _operator_dashboard_endpoints_payload(
            service=service,
            endpoint_service=endpoint_service,
            endpoint_publication_service=endpoint_publication_service,
            validation_service=validation_service,
        )

    @router.get("/operators/dashboard/sessions")
    async def operator_dashboard_sessions() -> dict:
        return _operator_dashboard_sessions_payload(
            service=service,
            endpoint_service=endpoint_service,
            session_service=session_service,
        )

    @router.post("/operators/dashboard/sessions/actions/close")
    async def operator_dashboard_close_session(
        request: OperatorSessionCloseActionRequest,
    ) -> JSONResponse:
        if session_application_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        try:
            result = session_application_service.close_session(request.session_id)
        except KeyError:
            return _error(
                404,
                "session_not_found",
                f"Unknown session: {request.session_id}",
            )
        return _ok(result["payload"])

    @router.post("/operators/dashboard/sessions/actions/sweep-idle")
    async def operator_dashboard_sweep_idle_sessions(
        request: OperatorSessionSweepIdleActionRequest,
    ) -> JSONResponse:
        if session_application_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        current_time = None
        if request.now:
            try:
                current_time = datetime.fromisoformat(request.now)
            except ValueError:
                return _error(
                    422,
                    "invalid_timestamp",
                    "Expected ISO-8601 timestamp for now",
                )
        result = session_application_service.sweep_idle_sessions(now=current_time)
        return _ok(result["payload"])

    @router.get("/operators/validation/reports/{report_id}/custody")
    async def operator_validation_report_custody(report_id: str) -> JSONResponse:
        if validation_service is None:
            return _error(503, "validation_unavailable", "Validation service is not configured")
        try:
            return _ok(validation_service.report_custody_metadata(report_id=report_id))
        except KeyError:
            return _error(404, "validation_report_not_found", f"Unknown validation report: {report_id}")

    @router.post("/operators/validation/reports/{report_id}/custody/check")
    async def operator_check_validation_report_custody(report_id: str) -> JSONResponse:
        if validation_service is None:
            return _error(503, "validation_unavailable", "Validation service is not configured")
        try:
            state = validation_service.check_report_custody(report_id=report_id)
        except KeyError:
            return _error(404, "validation_report_not_found", f"Unknown validation report: {report_id}")
        except ValueError as error:
            return _error(409, "validation_custody_unavailable", str(error))
        return _ok({"custody_state": state.model_dump(mode="json")})

    @router.get("/api/v1/sessions")
    async def list_sessions() -> JSONResponse:
        if session_application_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        return _ok(session_application_service.list_sessions())

    @router.get("/api/v1/sessions/{session_id}")
    async def get_session(session_id: str) -> JSONResponse:
        if session_application_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        try:
            result = session_application_service.get_session_detail(
                session_id=session_id
            )
        except KeyError:
            return _error(
                404,
                "session_not_found",
                f"Unknown session: {session_id}",
            )
        return _ok(result["payload"])

    @router.post("/api/v1/sessions/{session_id}/usage-reports")
    async def record_session_usage_report(
        session_id: str,
        request: SessionUsageReportRecordRequest,
    ) -> JSONResponse:
        if session_application_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        try:
            result = session_application_service.record_usage_report(
                session_id=session_id,
                usage_report=request.usage_report.model_dump(mode="json"),
                acknowledgement_timeout_seconds=request.acknowledgement_timeout_seconds,
            )
        except KeyError:
            return _error(
                404,
                "session_not_found",
                f"Unknown session: {session_id}",
            )
        except ValueError as error:
            return _error(
                409,
                "session_accounting_conflict",
                str(error),
            )
        if result["conflicted"]:
            return _error(
                409,
                "session_accounting_conflict",
                "Session accounting mismatch recorded",
                details={"session_accounting": result["session_accounting"]},
            )
        return _ok({"session_accounting": result["session_accounting"]})

    @router.post("/api/v1/sessions/{session_id}/usage-acknowledgements")
    async def record_session_usage_acknowledgement(
        session_id: str,
        request: SessionUsageAcknowledgementRecordRequest,
    ) -> JSONResponse:
        if session_application_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        try:
            result = session_application_service.record_usage_acknowledgement(
                session_id=session_id,
                usage_acknowledgement=request.usage_acknowledgement.model_dump(mode="json"),
                accepted_charge_q=request.accepted_charge_q,
            )
        except KeyError:
            return _error(
                404,
                "session_not_found",
                f"Unknown session: {session_id}",
            )
        except ValueError as error:
            return _error(
                409,
                "session_accounting_conflict",
                str(error),
            )
        if result["conflicted"]:
            return _error(
                409,
                "session_accounting_conflict",
                "Session accounting mismatch recorded",
                details={"session_accounting": result["session_accounting"]},
            )
        return _ok({"session_accounting": result["session_accounting"]})

    @router.get("/api/v1/sessions/{session_id}/accounting")
    async def get_session_accounting(session_id: str) -> JSONResponse:
        if session_application_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        try:
            session_accounting = session_application_service.get_session_accounting(
                session_id=session_id
            )
        except KeyError:
            return _error(
                404,
                "session_not_found",
                f"Unknown session: {session_id}",
            )
        return _ok({"session_accounting": session_accounting})

    @router.post("/api/v1/sessions/{session_id}/close")
    async def close_session(session_id: str) -> JSONResponse:
        if session_application_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        try:
            result = session_application_service.close_session(session_id)
        except KeyError:
            return _error(
                404,
                "session_not_found",
                f"Unknown session: {session_id}",
            )
        return _ok(result["payload"])

    @router.post("/api/v1/endpoints/{endpoint_id}/publish-configuration")
    async def publish_endpoint_configuration(endpoint_id: str) -> JSONResponse:
        if endpoint_service is None or endpoint_publication_service is None:
            return _error(
                503,
                "endpoint_publication_unavailable",
                "Endpoint publication service is not configured",
            )
        wallet = service.owner_wallet_state()
        if not wallet["configured"]:
            return _error(
                409,
                "wallet_not_configured",
                "Owner wallet must be configured before publishing endpoint configuration",
            )
        try:
            record = endpoint_publication_service.publish_configuration(
                endpoint_id=endpoint_id,
                owner_wallet=wallet["wallet_id"],
                node_id=service.node_id,
                wallet_private_key=service.owner_wallet_private_key(),
            )
        except KeyError:
            return _error(
                404,
                "endpoint_not_found",
                f"Unknown endpoint: {endpoint_id}",
            )
        except EndpointPublicationReadinessError as error:
            return _error(
                409,
                "endpoint_publication_blocked",
                str(error),
                details=error.readiness,
            )
        except ValueError as error:
            return _error(409, "publication_conflict", str(error))
        endpoint = endpoint_service.get_endpoint(endpoint_id).endpoint
        onboarding = service.sync_operator_onboarding_state(
            endpoint_items=_operator_dashboard_endpoints_payload(
                service=service,
                endpoint_service=endpoint_service,
                endpoint_publication_service=endpoint_publication_service,
                validation_service=validation_service,
            )["items"]
        )
        return _ok(
            build_publication_validation_payload(
                record=record,
                endpoint_id=endpoint_id,
                endpoint_configuration_hash=endpoint.configuration_hash,
                validation_service=validation_service,
                onboarding=onboarding,
            )
        )

    @router.post("/api/v1/endpoints/{endpoint_id}/request-validation")
    async def request_endpoint_validation(endpoint_id: str) -> JSONResponse:
        if validation_service is None or endpoint_service is None:
            return _error(
                503,
                "validation_unavailable",
                "Validation service is not configured",
            )
        try:
            endpoint = endpoint_service.get_endpoint(endpoint_id).endpoint
        except KeyError:
            return _error(
                404,
                "endpoint_not_found",
                f"Unknown endpoint: {endpoint_id}",
            )
        result = validation_service.request_validation(
            endpoint_id=endpoint.endpoint_id,
            owner_wallet=endpoint.owner_wallet,
            configuration_hash=endpoint.configuration_hash,
            minimum_session_deposit_q=endpoint.session.minimum_deposit,
        )
        return _ok(build_validation_request_payload(result))

    @router.post("/api/v1/validation/epochs")
    async def create_validation_epoch(
        request: ValidationEpochCreateRequest,
    ) -> JSONResponse:
        if validation_service is None:
            return _error(
                503,
                "validation_unavailable",
                "Validation service is not configured",
            )
        try:
            result = validation_service.create_validation_epoch(
                epoch_id=request.epoch_id,
                seed=request.seed,
                validator_entries=request.validator_entries,
            )
        except ValueError as error:
            return _error(409, "validation_conflict", str(error))
        return _ok(build_validation_epoch_payload(result))

    @router.get("/api/v1/endpoints/{endpoint_id}/validation")
    async def endpoint_validation_summary(endpoint_id: str) -> JSONResponse:
        if validation_service is None:
            return _error(
                503,
                "validation_unavailable",
                "Validation service is not configured",
            )
        if endpoint_service is not None:
            try:
                endpoint_service.get_endpoint(endpoint_id)
            except KeyError:
                return _error(
                    404,
                    "endpoint_not_found",
                    f"Unknown endpoint: {endpoint_id}",
                )
            return _ok(
                build_endpoint_validation_summary_payload(
                    endpoint_id=endpoint_id,
                    validation_service=validation_service,
                    endpoint_service=endpoint_service,
                )
            )
        return _ok(
            build_endpoint_validation_summary_payload(
                endpoint_id=endpoint_id,
                validation_service=validation_service,
            )
        )

    @router.get("/api/v1/endpoints/{endpoint_id}/validation/history")
    async def endpoint_validation_history(endpoint_id: str) -> JSONResponse:
        if validation_service is None:
            return _error(
                503,
                "validation_unavailable",
                "Validation service is not configured",
            )
        return _ok(
            build_endpoint_validation_history_payload(
                endpoint_id=endpoint_id,
                validation_service=validation_service,
            )
        )

    @router.get("/api/v1/endpoints/{endpoint_id}/proof")
    async def endpoint_proof(endpoint_id: str) -> JSONResponse:
        if endpoint_service is None:
            return _error(
                503,
                "endpoint_service_unavailable",
                "Endpoint service is not configured",
            )
        try:
            endpoint = endpoint_service.get_endpoint(endpoint_id).endpoint
        except KeyError:
            return _error(
                404,
                "endpoint_not_found",
                f"Unknown endpoint: {endpoint_id}",
            )
        current_publication = (
            endpoint_publication_service.current_publication(endpoint_id)
            if endpoint_publication_service is not None
            else None
        )
        local_publication_configuration_hash = _local_publication_configuration_hash(
            endpoint
        )
        published_endpoint_configuration_hash = _configuration_hash_for_publication_record(
            endpoint_service=endpoint_service,
            manifest=endpoint,
            publication_configuration_hash=(
                current_publication.configuration_hash
                if current_publication is not None
                else None
            ),
        )
        validation_summary = (
            validation_summary_for(
                validation_service,
                endpoint_id=endpoint_id,
                configuration_hash=endpoint.configuration_hash,
            )
        )
        published_validation_summary = (
            validation_summary_for(
                validation_service,
                endpoint_id=endpoint_id,
                configuration_hash=published_endpoint_configuration_hash,
            )
        )
        return _ok(
            build_endpoint_proof_payload(
                endpoint=endpoint,
                node_id=service.node_id,
                local_publication_configuration_hash=local_publication_configuration_hash,
                publication_sync_status=_publication_sync_status(
                    local_configuration_hash=local_publication_configuration_hash,
                    published_configuration_hash=(
                        current_publication.configuration_hash
                        if current_publication is not None
                        else None
                    ),
                ),
                validation_summary=validation_summary,
                published_validation_summary=published_validation_summary,
                current_publication=current_publication,
            )
        )

    @router.post("/api/v1/validation/requests/{request_id}/reports")
    async def submit_validation_report(
        request_id: str,
        request: ValidationReportSubmitRequest,
    ) -> JSONResponse:
        if validation_service is None:
            return _error(
                503,
                "validation_unavailable",
                "Validation service is not configured",
            )
        try:
            result = validation_service.submit_validation_report(
                request_id=request_id,
                recommendation=_recommendation_from_request(request),
                outcome=request.outcome,
                validator_label=request.validator_label,
                evidence_summary=request.evidence_summary,
                detected_issues=request.detected_issues,
            )
        except KeyError:
            return _error(
                404,
                "validation_request_not_found",
                f"Unknown validation request: {request_id}",
            )
        except ValueError as error:
            return _error(409, "validation_conflict", str(error))
        return _ok(build_validation_report_payload(result))

    @router.post("/api/v1/validation/requests/{request_id}/maintenance")
    async def resolve_validation_maintenance(
        request_id: str,
        request: ValidationMaintenanceSubmitRequest,
    ) -> JSONResponse:
        if validation_service is None:
            return _error(
                503,
                "validation_unavailable",
                "Validation service is not configured",
            )
        try:
            result = validation_service.resolve_maintenance_by_request(
                request_id=request_id,
                recommendation=_recommendation_from_request(request),
                outcome=request.outcome,
                validator_label=request.validator_label,
                evidence_summary=request.evidence_summary,
                detected_issues=request.detected_issues,
            )
        except KeyError:
            return _error(
                404,
                "validation_request_not_found",
                f"Unknown validation request: {request_id}",
            )
        except ValueError as error:
            return _error(409, "validation_conflict", str(error))
        return _ok(build_validation_maintenance_payload(result))

    @router.post("/api/v1/endpoints/{endpoint_id}/revoke-publication")
    async def revoke_endpoint_publication(endpoint_id: str) -> JSONResponse:
        if endpoint_publication_service is None:
            return _error(
                503,
                "endpoint_publication_unavailable",
                "Endpoint publication service is not configured",
            )
        try:
            record = endpoint_publication_service.revoke_publication(endpoint_id)
        except ValueError as error:
            return _error(409, "publication_conflict", str(error))
        return _ok({"publication": record.model_dump(mode="json")})

    @router.get("/operators/dashboard/market")
    async def operator_dashboard_market() -> dict:
        return build_operator_market_payload(
            service=service,
            registry_service=registry_service,
        )

    @router.get("/operators/dashboard/remote-endpoints")
    async def operator_dashboard_remote_endpoints() -> dict:
        return build_operator_remote_endpoints_payload(
            service=service,
            registry_service=registry_service,
            remote_endpoint_service=remote_endpoint_service,
        )

    @router.get("/operators/dashboard/requests")
    async def operator_dashboard_requests() -> dict:
        market = build_market_payload(
            service=service,
            registry_service=registry_service,
        )
        return service.operator_dashboard_requests(
            market_candidates=market["candidates"],
        )

    @router.post("/operators/dashboard/requests/policy")
    async def update_operator_dashboard_requests_policy(
        request: OperatorRequestsPolicyRequest,
    ) -> dict:
        try:
            return service.update_operator_requests_policy(
                **request.model_dump(mode="json")
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/wallet/bootstrap")
    async def owner_wallet_bootstrap_state() -> dict:
        return service.owner_wallet_state()

    @router.get("/wallets/{wallet_id}/identity")
    async def wallet_identity(wallet_id: str) -> dict:
        try:
            identity = service.resolve_wallet_identity(wallet_id)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if identity is None:
            raise HTTPException(status_code=404, detail="Wallet identity is not registered")
        return identity

    @router.post("/wallets/identity", status_code=201)
    async def register_wallet_identity(request: WalletIdentityRegistrationRequest) -> dict:
        try:
            return service.register_wallet_identity(**request.model_dump(mode="json"))
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/wallet/bootstrap/create")
    async def create_owner_wallet(
        request: WalletBootstrapCreateRequest,
    ) -> dict:
        try:
            return service.configure_owner_wallet(
                mode="create",
                label=request.label,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/wallet/bootstrap/import")
    async def import_owner_wallet(
        request: WalletBootstrapImportRequest,
    ) -> dict:
        try:
            return service.configure_owner_wallet(
                mode="import",
                private_key=request.private_key,
                label=request.label,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/remote-endpoints/attach")
    async def attach_remote_endpoint(
        request: RemoteEndpointAttachRequest,
    ) -> JSONResponse:
        if registry_service is None or remote_endpoint_service is None:
            return _error(
                status.HTTP_409_CONFLICT,
                "registry_unavailable",
                "registry-backed remote endpoint discovery is not configured",
            )
        try:
            node = registry_service.get_node(request.node_id)
        except KeyError:
            return _error(
                status.HTTP_404_NOT_FOUND,
                "remote_node_not_found",
                f"unknown remote node: {request.node_id}",
            )
        discovered = next(
            (
                item
                for item in node.get("published_endpoints", [])
                if item["endpoint_id"] == request.endpoint_id
            ),
            None,
        )
        if discovered is None:
            return _error(
                status.HTTP_404_NOT_FOUND,
                "remote_endpoint_not_found",
                f"unknown published endpoint: {request.endpoint_id}",
            )
        attached = remote_endpoint_service.attach_remote_endpoint(
            source_node_id=node["node_id"],
            source_endpoint_id=discovered["endpoint_id"],
            source_owner_wallet=discovered["owner_wallet"],
            source_publication_id=discovered["current_publication_id"],
            source_configuration_hash=discovered["current_configuration_hash"],
            source_visibility=discovered["visibility"],
            source_model_class=discovered["model_class"],
            source_status=discovered["status"],
            source_base_url=node["base_url"],
            operator_id=node["operator_id"],
            pricing=node["pricing"],
            rating=node["rating"],
            alias=request.alias,
            routing_mode=request.routing_mode,
        )
        return _ok(
            {"remote_endpoint": attached.model_dump(mode="json")},
            status_code=201,
        )

    @router.delete("/operators/remote-endpoints/{remote_endpoint_id}")
    async def detach_remote_endpoint(remote_endpoint_id: str) -> JSONResponse:
        if remote_endpoint_service is None:
            return _error(
                status.HTTP_409_CONFLICT,
                "registry_unavailable",
                "registry-backed remote endpoint discovery is not configured",
            )
        try:
            detached = remote_endpoint_service.detach_remote_endpoint(
                remote_endpoint_id,
                endpoint_service=endpoint_service,
            )
        except KeyError:
            return _error(
                status.HTTP_404_NOT_FOUND,
                "remote_endpoint_not_found",
                f"unknown remote endpoint: {remote_endpoint_id}",
            )
        except RemoteEndpointDependencyError as error:
            return _error(
                status.HTTP_409_CONFLICT,
                "remote_endpoint_in_use",
                f"remote endpoint {remote_endpoint_id} is still used by local endpoints",
                details={
                    "dependent_endpoint_ids": error.dependent_endpoint_ids,
                },
            )
        return _ok({"remote_endpoint": detached.model_dump(mode="json")})

    @router.get("/operators/node/identity")
    async def operator_node_identity() -> dict:
        return service.node_identity()

    @router.get("/operators/dashboard", response_class=HTMLResponse)
    async def operator_dashboard() -> str:
        return load_dashboard_html()

    @router.post("/operators/wallet/quote")
    async def wallet_quote(request: WalletQuoteRequest) -> dict:
        return service.quote_wallet_usage(**request.model_dump(mode="json"))

    @router.get("/operators/dashboard/wallet")
    async def operator_dashboard_wallet(
        usage_limit: int = 100,
        allocation_limit: int = 100,
        dispute_limit: int = 100,
        economics_recent_limit: int = 8,
        economics_history_limit: int = 12,
    ) -> dict:
        return build_operator_wallet_payload(
            service,
            usage_limit=usage_limit,
            allocation_limit=allocation_limit,
            dispute_limit=dispute_limit,
            economics_recent_limit=economics_recent_limit,
            economics_history_limit=economics_history_limit,
        )

    @router.get("/operators/wallet/usage")
    async def wallet_usage_events(limit: int = 100) -> list[dict]:
        return build_wallet_usage_events_payload(service, limit=limit)

    @router.get("/operators/wallet/sessions")
    async def wallet_session_events(limit: int = 100) -> list[dict]:
        return build_wallet_session_events_payload(service, limit=limit)

    @router.get("/operators/wallet/ledger")
    async def wallet_ledger_events(limit: int = 100) -> list[dict]:
        return build_wallet_ledger_events_payload(service, limit=limit)

    @router.get("/operators/ledger/operations")
    async def ledger_operations(limit: int = 100) -> list[dict]:
        return build_ledger_operations_payload(service, limit=limit)

    @router.get("/operators/ledger/operations/export")
    async def export_ledger_operations(
        after_operation_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return build_ledger_operations_export_payload(
            service,
            after_operation_id=after_operation_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    @router.get("/operators/wallet/economics")
    async def wallet_economics_summary(recent_limit: int = 10) -> dict:
        return build_wallet_economics_summary_payload(
            service,
            recent_limit=recent_limit,
        )

    @router.get("/operators/wallet/economics/export")
    async def export_wallet_economics_events(
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return build_wallet_economics_export_payload(
            service,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    @router.get("/operators/wallet/economics/faucet")
    async def wallet_faucet_preview() -> dict:
        return build_wallet_faucet_preview_payload(service)

    @router.post("/operators/wallet/economics/faucet/claim")
    async def claim_wallet_faucet_share() -> dict:
        try:
            return service.claim_faucet_share()
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/wallet/endpoints/publications")
    async def wallet_endpoint_publications(endpoint_id: str | None = None) -> dict:
        return build_wallet_endpoint_publications_payload(
            endpoint_publication_service,
            endpoint_id=endpoint_id,
        )

    @router.get("/operators/wallet/endpoints/publications/export")
    async def export_wallet_endpoint_publications(
        endpoint_id: str | None = None,
        limit: int = 100,
    ) -> dict:
        return build_wallet_endpoint_publications_export_payload(
            endpoint_publication_service,
            endpoint_id=endpoint_id,
            limit=limit,
        )

    @router.get("/operators/wallet/allocations")
    async def wallet_allocation_events(limit: int = 100) -> list[dict]:
        return build_wallet_allocation_events_payload(service, limit=limit)

    @router.get("/operators/wallet/allocations/activations")
    async def wallet_allocation_activation_events(limit: int = 100) -> list[dict]:
        return build_wallet_allocation_activation_events_payload(service, limit=limit)

    @router.get("/operators/wallet/allocations/disputes")
    async def wallet_allocation_dispute_events(limit: int = 100) -> list[dict]:
        return build_wallet_allocation_dispute_events_payload(service, limit=limit)

    @router.get("/operators/wallet/usage/export")
    async def export_wallet_usage_events(
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return build_wallet_usage_export_payload(
            service,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    @router.get("/operators/wallet/sessions/export")
    async def export_wallet_session_events(
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return build_wallet_session_export_payload(
            service,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    @router.get("/operators/wallet/ledger/export")
    async def export_wallet_ledger_events(
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return build_wallet_ledger_export_payload(
            service,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    @router.get("/operators/wallet/allocations/export")
    async def export_wallet_allocation_events(
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return build_wallet_allocation_export_payload(
            service,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    @router.get("/operators/wallet/allocations/activations/export")
    async def export_wallet_allocation_activation_events(
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return build_wallet_allocation_activation_export_payload(
            service,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    @router.get("/operators/wallet/allocations/disputes/export")
    async def export_wallet_allocation_dispute_events(
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return build_wallet_allocation_dispute_export_payload(
            service,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    @router.post("/operators/wallet/allocations/{event_id}/reopen")
    async def reopen_wallet_allocation_event(
        event_id: str, request: WalletAllocationReopenRequest
    ) -> dict:
        try:
            return service.reopen_wallet_allocation_event(event_id, reason=request.reason)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown wallet allocation event: {event_id}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/wallet/allocations/{event_id}/dispute")
    async def dispute_wallet_allocation_event(
        event_id: str, request: WalletAllocationDisputeRequest
    ) -> dict:
        try:
            return service.dispute_wallet_allocation_event(event_id, reason=request.reason)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown wallet allocation event: {event_id}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/wallet/allocations/{event_id}/dispute/resolve")
    async def resolve_wallet_allocation_dispute(
        event_id: str, request: WalletAllocationDisputeResolveRequest
    ) -> dict:
        try:
            return service.resolve_wallet_allocation_dispute(
                event_id,
                resolution=request.resolution,
                reason=request.reason,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown wallet allocation event: {event_id}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/wallet/allocations/corrections")
    async def list_wallet_allocation_correction_events(limit: int = 100) -> list[dict]:
        return service.list_wallet_allocation_correction_events(limit=limit)

    @router.get("/operators/wallet/allocations/corrections/export")
    async def export_wallet_allocation_correction_events(
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return service.export_wallet_allocation_correction_events(
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    @router.post("/operators/wallet/allocations/{event_id}/hold")
    async def hold_wallet_allocation_event(
        event_id: str, request: WalletAllocationHoldRequest
    ) -> dict:
        try:
            return service.hold_wallet_allocation_event(event_id, reason=request.reason)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown wallet allocation event: {event_id}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/wallet/allocations/{event_id}/release")
    async def release_wallet_allocation_event(
        event_id: str, request: WalletAllocationReleaseRequest
    ) -> dict:
        try:
            return service.release_wallet_allocation_event(
                event_id,
                reason=request.reason,
                target_status=request.target_status,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown wallet allocation event: {event_id}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/wallet/allocations/{event_id}/corrections")
    async def apply_wallet_allocation_correction(
        event_id: str, request: WalletAllocationCorrectionRequest
    ) -> dict:
        try:
            kwargs = request.model_dump(mode="json")
            kwargs.pop("release_after_apply", None)
            kwargs.pop("release_target_status", None)
            return service.apply_wallet_allocation_correction(
                event_id,
                **kwargs,
            )
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown wallet allocation event: {event_id}",
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/wallet/usage", status_code=status.HTTP_201_CREATED)
    async def record_wallet_usage(request: WalletUsageRecordRequest) -> dict:
        return service.record_wallet_usage(**request.model_dump(mode="json"))

    @router.post("/operators/models/install", status_code=status.HTTP_202_ACCEPTED)
    async def request_model_install(request: ModelInstallRequest) -> dict:
        try:
            return service.request_model_install(**request.model_dump(mode="json"))
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/models/install")
    async def list_model_installs() -> list[dict]:
        return service.list_model_installs()

    @router.post("/operators/models/install/process")
    async def process_model_installs() -> list[dict]:
        try:
            return service.process_model_installs()
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.post("/operators/models/{install_id}/register-bundle")
    async def register_bundle_from_install(
        install_id: str,
        request: RegisterBundleFromInstallRequest,
    ) -> dict:
        try:
            return service.register_bundle_from_install(
                install_id=install_id,
                **request.model_dump(mode="json"),
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown install job: {install_id}") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/operators/bundles/config")
    async def export_bundle_config() -> list[dict]:
        return [bundle.model_dump(mode="json") for bundle in service.bundle_config()]

    @router.put("/operators/bundles/config")
    async def replace_bundle_config(bundles: list[BundleConfig]) -> dict:
        try:
            count = service.replace_bundle_config(bundles)
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown plugin: {error.args[0]}") from error
        return {"bundle_count": count, "status": "reloaded"}

    @router.post("/operators/bundles/reload")
    async def reload_bundle_config() -> dict:
        try:
            count = service.reload_bundle_config()
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown plugin: {error.args[0]}") from error
        return {"bundle_count": count, "status": "reloaded"}

    @router.post("/operators/bundles/{bundle_id}/cooldown/reset")
    async def reset_bundle_cooldown(bundle_id: str) -> dict:
        try:
            return service.reset_bundle_cooldown(bundle_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown bundle: {bundle_id}") from error

    @router.post("/operators/bundles/{bundle_id}/retry")
    async def retry_bundle(bundle_id: str) -> dict:
        try:
            summary = service.retry_bundle(bundle_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown bundle: {bundle_id}") from error
        return {"bundle_id": bundle_id, "status": "retried", "summary": summary}

    @router.post("/operators/bundles/{bundle_id}/disable")
    async def disable_bundle(bundle_id: str) -> dict:
        try:
            return service.set_bundle_enabled(bundle_id, False)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown bundle: {bundle_id}") from error

    @router.post("/operators/bundles/{bundle_id}/enable")
    async def enable_bundle(bundle_id: str) -> dict:
        try:
            return service.set_bundle_enabled(bundle_id, True)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown bundle: {bundle_id}") from error

    @router.post("/operators/runtimes/{runtime_id}/drain")
    async def drain_runtime(runtime_id: str) -> dict:
        try:
            return service.drain_runtime(runtime_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown runtime: {runtime_id}") from error

    @router.post("/operators/runtimes/{runtime_id}/force-stop")
    async def force_stop_runtime(runtime_id: str) -> dict:
        try:
            return service.force_stop_runtime(runtime_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown runtime: {runtime_id}") from error

    @router.post("/operators/runtimes/{runtime_id}/restart")
    async def restart_runtime(runtime_id: str) -> dict:
        try:
            return service.restart_runtime(runtime_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=f"Unknown runtime: {runtime_id}") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @router.get("/resources")
    async def resource_summary() -> dict:
        if service.resources is None:
            return _empty_resource_summary()
        return service.resources.summary()

    @router.get("/plugins")
    async def list_plugins() -> list[dict]:
        return _plugin_descriptions(service.plugins)

    return router


def _serialize_task(
    *,
    task_id: str,
    status: str,
    priority: int,
    task_type: str,
    bundle_id: str | None,
    result=...,
    recovery_reason=...,
    proxy_trace=...,
    proxy_session=...,
    history=...,
) -> dict:
    payload = {
        "task_id": task_id,
        "status": status,
        "priority": priority,
        "task_type": task_type,
        "bundle_id": bundle_id,
    }
    if result is not ...:
        payload["result"] = result
    if recovery_reason is not ...:
        payload["recovery_reason"] = recovery_reason
    if proxy_trace is not ...:
        payload["proxy_trace"] = proxy_trace
    if proxy_session is not ...:
        payload["proxy_session"] = proxy_session
    if history is not ...:
        payload["history"] = history
    return payload


def _bundle_status(
    bundle: BundleConfig,
    runtimes: Iterable[RuntimeHandle],
    bundle_state: dict,
) -> str:
    if not bundle.enabled:
        return "disabled"

    if bundle_state.get("cooldown_until") is not None:
        return "cooldown"

    if bundle_state.get("drain_mode"):
        return "draining"

    for runtime in runtimes:
        if runtime.bundle_id == bundle.bundle_id:
            return runtime.status

    return "stopped"


def _plugin_descriptions(plugins) -> list[dict]:
    if hasattr(plugins, "list"):
        return [plugin.describe() for plugin in plugins.list()]
    return [plugin.describe() for plugin in (plugins or [])]


def _empty_resource_summary() -> dict[str, dict[str, float | int]]:
    zeroes = {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0}
    return {
        "total": dict(zeroes),
        "reserved": dict(zeroes),
        "free": dict(zeroes),
    }
