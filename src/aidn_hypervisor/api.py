from collections.abc import Iterable
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from aidn_hypervisor.dashboard import build_market_payload, load_dashboard_html
from aidn_hypervisor.domain.models import (
    AllocationRequest,
    BundleConfig,
    ModelInstallRequest,
    RegisterBundleFromInstallRequest,
    TaskRequest,
)
from aidn_hypervisor.endpoint_publications.models import (
    canonical_configuration_payload,
    configuration_hash_for_publication,
)
from aidn_hypervisor.domain.types import TaskStatus
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.service import AllocationUnavailableError, HypervisorService
from aidn_hypervisor.state import HypervisorStateSnapshot
from aidn_hypervisor.wallet_models import (
    WalletAllocationDisputeRequest,
    WalletAllocationDisputeResolveRequest,
    WalletAllocationReopenRequest,
    WalletQuoteRequest,
    WalletUsageRecordRequest,
)

_ACTIVE_TASK_STATUSES: set[TaskStatus] = {"queued", "admitted", "starting", "running"}


def _ok(data: dict, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "data": data,
            "error": None,
            "correlation_id": str(uuid4()),
        },
    )


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "data": None,
            "error": {"code": code, "message": message},
            "correlation_id": str(uuid4()),
        },
    )


def _operator_dashboard_home_bootstrap_payload(
    *,
    service: HypervisorService,
    endpoint_service,
    endpoint_publication_service=None,
    fallback_bootstrap: dict,
) -> dict:
    items = _operator_dashboard_endpoints_payload(
        service=service,
        endpoint_service=endpoint_service,
        endpoint_publication_service=endpoint_publication_service,
    )["items"]
    configured = [
        item for item in items if item["publication_status"] in {"configured", "draft"}
    ]
    if not service.owner_wallet_state()["configured"]:
        next_step = "Create or import a wallet"
    elif configured:
        next_step = "Review your configured endpoint and publish it"
    elif items:
        next_step = "Manage your published endpoint and request validation when ready"
    else:
        next_step = fallback_bootstrap.get("next_step") or "Attach a provider or install a model"
    return {
        "wallet_ready": service.owner_wallet_state()["configured"],
        "owner_wallet": service.owner_wallet_state(),
        "node_identity": service.node_identity(),
        "provider_count": fallback_bootstrap.get("provider_count", 0),
        "bundle_count": fallback_bootstrap.get("bundle_count", 0),
        "endpoint_count": len(items),
        "first_endpoint_candidate": fallback_bootstrap.get("first_endpoint_candidate"),
        "items": items,
        "next_step": next_step,
    }


def _operator_dashboard_endpoints_payload(
    *,
    service: HypervisorService,
    endpoint_service,
    endpoint_publication_service=None,
) -> dict:
    def execution_payload_for_manifest(manifest) -> dict:
        if manifest.execution_strategy != "proxy" or manifest.proxy_target is None:
            return {"strategy": manifest.execution_strategy}
        return {
            "strategy": manifest.execution_strategy,
            "target_fingerprint": configuration_hash_for_publication(
                {
                    "remote_endpoint_id": manifest.proxy_target.remote_endpoint_id,
                    "source_publication_id": manifest.proxy_target.source_publication_id,
                    "source_configuration_hash": manifest.proxy_target.source_configuration_hash,
                }
            ),
        }

    items = []
    for manifest in endpoint_service.list_endpoints():
        local_publication_payload = canonical_configuration_payload(
            bundle_hash=manifest.bundle_hash,
            model_class=manifest.model_class,
            capabilities=manifest.capabilities,
            runtime=manifest.runtime.model_dump(mode="json"),
            publication=manifest.publication.model_dump(mode="json"),
            pricing=manifest.pricing.model_dump(mode="json"),
            session=manifest.session.model_dump(mode="json"),
            execution=execution_payload_for_manifest(manifest),
        )
        local_configuration_hash = configuration_hash_for_publication(
            local_publication_payload
        )
        current_publication = (
            endpoint_publication_service.current_publication(manifest.endpoint_id)
            if endpoint_publication_service is not None
            else None
        )
        publication_history = (
            endpoint_publication_service.list_publications(endpoint_id=manifest.endpoint_id)
            if endpoint_publication_service is not None
            else []
        )
        configuration_snapshots = [
            snapshot.model_dump(mode="json")
            for snapshot in endpoint_service.list_configuration_snapshots(
                manifest.endpoint_id
            )
        ]
        published = current_publication is not None
        validation_requested = bool(
            manifest.validation.enabled
            or manifest.publication.validation == "enabled"
        )
        items.append(
            {
                "endpoint_id": manifest.endpoint_id,
                "display_name": manifest.display_name,
                "bundle_id": manifest.bundle_id,
                "configuration_hash": manifest.configuration_hash,
                "local_configuration_hash": local_configuration_hash,
                "published_configuration_hash": (
                    current_publication.configuration_hash
                    if current_publication is not None
                    else None
                ),
                "publication_sync_status": (
                    "in_sync"
                    if current_publication is not None
                    and current_publication.configuration_hash
                    == local_configuration_hash
                    else "local_changes_not_published"
                    if current_publication is not None
                    else "never_published"
                ),
                "model_class": manifest.model_class,
                "capabilities": list(manifest.capabilities),
                "profile": manifest.profile.model_dump(mode="json"),
                "runtime": manifest.runtime.model_dump(mode="json"),
                "session": manifest.session.model_dump(mode="json"),
                "execution_strategy": manifest.execution_strategy,
                "proxy_target": (
                    manifest.proxy_target.model_dump(mode="json")
                    if manifest.proxy_target is not None
                    else None
                ),
                "visibility": manifest.publication.visibility,
                "publication_status": "published" if published else "configured",
                "validation_mode": "requested" if validation_requested else "disabled",
                "runtime_status": manifest.status,
                "publication": manifest.publication.model_dump(mode="json"),
                "validation": manifest.validation.model_dump(mode="json"),
                "current_publication": (
                    current_publication.model_dump(mode="json")
                    if current_publication is not None
                    else None
                ),
                "publication_history": [
                    record.model_dump(mode="json")
                    for record in publication_history
                ],
                "shared_with_wallet_ids": list(
                    manifest.publication.shared_with_wallet_ids
                ),
                "configuration_snapshots": configuration_snapshots,
                "endpoint_url": None,
                "created_at": manifest.created_at,
                "published_at": (
                    current_publication.published_at
                    if current_publication is not None
                    else None
                ),
            }
        )

    summary = {
        "total": len(items),
        "published": sum(1 for item in items if item["publication_status"] == "published"),
        "configured": sum(
            1 for item in items if item["publication_status"] == "configured"
        ),
        "validation_requested": sum(
            1 for item in items if item["validation_mode"] == "requested"
        ),
        "private": sum(1 for item in items if item["visibility"] == "private"),
        "shared": sum(1 for item in items if item["visibility"] == "shared"),
        "public": sum(1 for item in items if item["visibility"] == "public"),
    }
    return {
        "owner_wallet": service.owner_wallet_state(),
        "node_identity": service.node_identity(),
        "summary": summary,
        "policy": {
            "publish_requires_validation": False,
            "validation_optional": True,
            "execution_privacy": "endpoint implementation remains private",
        },
        "items": items,
    }


def _operator_dashboard_sessions_payload(
    *,
    service: HypervisorService,
    endpoint_service=None,
    session_service=None,
) -> dict:
    current_time = datetime.now().astimezone()
    session_tasks: dict[str, list[dict]] = {}
    session_activity: dict[str, list[dict]] = {}

    def _task_input_preview(task_request: TaskRequest) -> str | None:
        payload = task_request.payload if isinstance(task_request.payload, dict) else {}
        if "prompt" in payload:
            return str(payload["prompt"])
        if "audio_ref" in payload:
            return str(payload["audio_ref"])
        if payload:
            first_key = next(iter(payload))
            return str(payload[first_key])
        return None

    def _settlement_preview(session, deposit) -> dict:
        minimum_session_fee = float(
            session.session_policy_snapshot.get("minimum_session_fee", 0.0) or 0.0
        )
        idle_fee_per_minute = float(
            session.session_policy_snapshot.get("idle_fee_per_minute", 0.0) or 0.0
        )
        usage_charged_q = float(deposit.consumed_q)
        minimum_session_fee_q = (
            min(float(deposit.locked_q), minimum_session_fee)
            if int(session.request_count or 0) == 0
            else 0.0
        )
        idle_elapsed_seconds = 0
        idle_exposure_q = 0.0
        if (
            session.status == "active"
            and int(session.request_count or 0) > 0
            and idle_fee_per_minute > 0.0
            and session.last_activity_at
        ):
            try:
                last_activity_at = datetime.fromisoformat(session.last_activity_at)
                idle_elapsed_seconds = max(
                    0,
                    int((current_time - last_activity_at).total_seconds()),
                )
            except ValueError:
                idle_elapsed_seconds = 0
            idle_exposure_q = min(
                max(0.0, float(deposit.locked_q) - usage_charged_q),
                (idle_elapsed_seconds / 60.0) * idle_fee_per_minute,
            )
        projected_charged_q = min(
            float(deposit.locked_q),
            max(minimum_session_fee_q, usage_charged_q + idle_exposure_q),
        )
        projected_refundable_q = max(
            0.0,
            float(deposit.locked_q) - projected_charged_q,
        )
        seconds_until_idle_timeout = 0
        if session.idle_deadline_at:
            try:
                idle_deadline_at = datetime.fromisoformat(session.idle_deadline_at)
                seconds_until_idle_timeout = max(
                    0,
                    int((idle_deadline_at - current_time).total_seconds()),
                )
            except ValueError:
                seconds_until_idle_timeout = 0
        return {
            "usage_charged_q": usage_charged_q,
            "minimum_session_fee_q": minimum_session_fee_q,
            "idle_exposure_q": idle_exposure_q,
            "projected_charged_q": projected_charged_q,
            "projected_refundable_q": projected_refundable_q,
            "idle_elapsed_seconds": idle_elapsed_seconds,
            "seconds_until_idle_timeout": seconds_until_idle_timeout,
        }

    for task in service.queue.snapshot():
        session_id = task.request.constraints.get("session_id")
        if session_id is None:
            continue
        task_id = str(task.task_id)
        serialized = {
            "task_id": task_id,
            "created_at": task.created_at,
            "status": task.status,
            "task_type": task.request.task_type,
            "bundle_id": service.selected_bundle_id(task_id),
            "session_id": str(session_id),
            "endpoint_id": task.request.constraints.get("endpoint_id"),
            "input_preview": _task_input_preview(task.request),
            "usage": (
                service.task_result(task_id).get("usage")
                if isinstance(service.task_result(task_id), dict)
                else None
            ),
            "session_accounting": (
                service.task_result(task_id).get("session_accounting")
                if isinstance(service.task_result(task_id), dict)
                else None
            ),
        }
        session_tasks.setdefault(str(session_id), []).append(serialized)
        history = [
            {
                "timestamp": event.timestamp,
                "event_type": event.event_type,
                "message": event.message,
                "task_id": event.task_id,
                "details": dict(event.details or {}),
            }
            for event in service.task_history(task_id)
        ]
        session_activity.setdefault(str(session_id), []).extend(history)

    for event in service.event_journal():
        event_session_id = event.details.get("session_id")
        if event_session_id is None:
            continue
        session_activity.setdefault(str(event_session_id), []).append(
            {
                "timestamp": event.timestamp,
                "event_type": event.event_type,
                "message": event.message,
                "task_id": event.task_id,
                "details": dict(event.details or {}),
            }
        )

    for session_id in session_tasks:
        session_tasks[session_id] = sorted(
            session_tasks[session_id],
            key=lambda item: item["created_at"],
            reverse=True,
        )[:8]
    for session_id in session_activity:
        session_activity[session_id] = sorted(
            session_activity[session_id],
            key=lambda item: item["timestamp"],
            reverse=True,
        )[:12]

    if session_service is None:
        return {
            "owner_wallet": service.owner_wallet_state(),
            "node_identity": service.node_identity(),
            "summary": {"total": 0, "active": 0, "queued": 0, "closed": 0},
            "items": [],
        }
    endpoint_names: dict[str, str] = {}
    if endpoint_service is not None:
        for manifest in endpoint_service.list_endpoints():
            endpoint_names[manifest.endpoint_id] = manifest.display_name
    items = []
    for session in sorted(
        session_service.list_sessions(),
        key=lambda item: (item.status != "active", item.status != "queued", item.created_at),
    ):
        result = session_service.get_session(session.session_id)
        items.append(
            {
                "session": result.session.model_dump(mode="json"),
                "deposit": result.deposit.model_dump(mode="json"),
                "settlement": (
                    result.settlement.model_dump(mode="json")
                    if result.settlement is not None
                    else None
                ),
                "display_name": endpoint_names.get(session.endpoint_id, session.endpoint_id),
                "remaining_q": max(
                    0.0, result.deposit.locked_q - result.deposit.consumed_q
                ),
                "settlement_preview": _settlement_preview(
                    result.session,
                    result.deposit,
                ),
                "related_tasks": session_tasks.get(session.session_id, []),
                "activity": session_activity.get(session.session_id, []),
            }
        )
    return {
        "owner_wallet": service.owner_wallet_state(),
        "node_identity": service.node_identity(),
        "summary": {
            "total": len(items),
            "active": sum(1 for item in items if item["session"]["status"] == "active"),
            "queued": sum(1 for item in items if item["session"]["status"] == "queued"),
            "closed": sum(1 for item in items if item["session"]["status"] == "closed"),
        },
        "items": items,
    }


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


def _operator_dashboard_remote_endpoints_payload(
    *,
    service: HypervisorService,
    registry_service=None,
    remote_endpoint_service=None,
) -> dict:
    attached = (
        [
            record.model_dump(mode="json")
            for record in remote_endpoint_service.list_remote_endpoints()
        ]
        if remote_endpoint_service is not None
        else []
    )
    attached_keys = {
        (item["source_node_id"], item["source_endpoint_id"]) for item in attached
    }
    discovered: list[dict] = []
    if registry_service is not None:
        for node in registry_service.list_nodes():
            if node["node_id"] == service.node_id:
                continue
            for endpoint in node.get("published_endpoints", []):
                discovered.append(
                    {
                        "node_id": node["node_id"],
                        "operator_id": node["operator_id"],
                        "base_url": node["base_url"],
                        "status": node["status"],
                        "pricing": node["pricing"],
                        "rating": node["rating"],
                        "can_host_custom_model": node["can_host_custom_model"],
                        "endpoint_id": endpoint["endpoint_id"],
                        "owner_wallet": endpoint["owner_wallet"],
                        "publication_id": endpoint["current_publication_id"],
                        "configuration_hash": endpoint["current_configuration_hash"],
                        "published_at": endpoint["published_at"],
                        "visibility": endpoint["visibility"],
                        "model_class": endpoint["model_class"],
                        "already_attached": (
                            (node["node_id"], endpoint["endpoint_id"]) in attached_keys
                        ),
                    }
                )
    discovered.sort(
        key=lambda item: (
            -float(item["rating"].get("score", 0.0)),
            float(item["pricing"].get("input", 0)),
            item["node_id"],
            item["endpoint_id"],
        )
    )
    return {
        "owner_wallet": service.owner_wallet_state(),
        "node_identity": service.node_identity(),
        "summary": {
            "attached": len(attached),
            "discovered": len(discovered),
            "remote_nodes": len({item["node_id"] for item in discovered}),
            "model_classes": len({item["model_class"] for item in discovered}),
        },
        "policy": {
            "local_catalogue": True,
            "proxy_ready": True,
            "execution_privacy": "underlying execution topology remains private",
        },
        "attached": attached,
        "discovered": discovered,
    }


def build_api_router(
    service: HypervisorService,
    *,
    registry_service=None,
    endpoint_service=None,
    endpoint_publication_service=None,
    remote_endpoint_service=None,
    session_service=None,
) -> APIRouter:
    router = APIRouter()

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
            "items": service.admission_telemetry(),
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
                "active_task_count": service.runtime_active_task_count(
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
            "active_task_count": service.runtime_active_task_count(
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
        return service.node_advertisement()

    @router.get("/operators/dashboard/home")
    async def operator_dashboard_home() -> dict:
        market = build_market_payload(
            service=service,
            registry_service=registry_service,
        )
        payload = service.operator_dashboard_home()
        if endpoint_service is not None and endpoint_service.list_endpoints():
            payload["bootstrap"] = _operator_dashboard_home_bootstrap_payload(
                service=service,
                endpoint_service=endpoint_service,
                endpoint_publication_service=endpoint_publication_service,
                fallback_bootstrap=payload.get("bootstrap", {}),
            )
        payload["market_preview"] = {
            "candidate_count": len(market["candidates"]),
        }
        return payload

    @router.get("/operators/dashboard/fleet")
    async def operator_dashboard_fleet() -> dict:
        return service.operator_dashboard_fleet()

    @router.get("/operators/dashboard/endpoints")
    async def operator_dashboard_endpoints() -> dict:
        if endpoint_service is not None and endpoint_service.list_endpoints():
            return _operator_dashboard_endpoints_payload(
                service=service,
                endpoint_service=endpoint_service,
                endpoint_publication_service=endpoint_publication_service,
            )
        return service.operator_dashboard_endpoints()

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
        if session_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        try:
            result = session_service.close_session(request.session_id)
        except KeyError:
            return _error(
                404,
                "session_not_found",
                f"Unknown session: {request.session_id}",
            )
        return _ok(
            {
                "session": result.session.model_dump(mode="json"),
                "deposit": result.deposit.model_dump(mode="json"),
                "settlement": (
                    result.settlement.model_dump(mode="json")
                    if result.settlement is not None
                    else None
                ),
            }
        )

    @router.post("/operators/dashboard/sessions/actions/sweep-idle")
    async def operator_dashboard_sweep_idle_sessions(
        request: OperatorSessionSweepIdleActionRequest,
    ) -> JSONResponse:
        if session_service is None:
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
        results = session_service.sweep_idle_sessions(now=current_time)
        return _ok(
            {
                "closed_count": len(results),
                "items": [
                    {
                        "session": result.session.model_dump(mode="json"),
                        "deposit": result.deposit.model_dump(mode="json"),
                        "settlement": (
                            result.settlement.model_dump(mode="json")
                            if result.settlement is not None
                            else None
                        ),
                    }
                    for result in results
                ],
            }
        )

    @router.get("/api/v1/sessions")
    async def list_sessions() -> JSONResponse:
        if session_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        return _ok(
            {
                "items": [
                    session.model_dump(mode="json")
                    for session in session_service.list_sessions()
                ]
            }
        )

    @router.get("/api/v1/sessions/{session_id}")
    async def get_session(session_id: str) -> JSONResponse:
        if session_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        try:
            result = session_service.get_session(session_id)
        except KeyError:
            return _error(
                404,
                "session_not_found",
                f"Unknown session: {session_id}",
            )
        return _ok(
            {
                "session": result.session.model_dump(mode="json"),
                "deposit": result.deposit.model_dump(mode="json"),
                "settlement": (
                    result.settlement.model_dump(mode="json")
                    if result.settlement is not None
                    else None
                ),
            }
        )

    @router.post("/api/v1/sessions/{session_id}/close")
    async def close_session(session_id: str) -> JSONResponse:
        if session_service is None:
            return _error(
                503,
                "session_service_unavailable",
                "Session service is not configured",
            )
        try:
            result = session_service.close_session(session_id)
        except KeyError:
            return _error(
                404,
                "session_not_found",
                f"Unknown session: {session_id}",
            )
        return _ok(
            {
                "session": result.session.model_dump(mode="json"),
                "deposit": result.deposit.model_dump(mode="json"),
                "settlement": (
                    result.settlement.model_dump(mode="json")
                    if result.settlement is not None
                    else None
                ),
            }
        )

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
        except ValueError as error:
            return _error(409, "publication_conflict", str(error))
        return _ok({"publication": record.model_dump(mode="json")})

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
        return _ok(
            {
                "proof": {
                    "endpoint_id": endpoint.endpoint_id,
                    "node_id": service.node_id,
                    "configuration_hash": endpoint.configuration_hash,
                    "bundle_hash": endpoint.bundle_hash,
                    "runtime_status": endpoint.status,
                    "publication": endpoint.publication.model_dump(mode="json"),
                    "current_publication": (
                        current_publication.model_dump(mode="json")
                        if current_publication is not None
                        else None
                    ),
                }
            }
        )

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
        return build_market_payload(
            service=service,
            registry_service=registry_service,
        )

    @router.get("/operators/dashboard/remote-endpoints")
    async def operator_dashboard_remote_endpoints() -> dict:
        return _operator_dashboard_remote_endpoints_payload(
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

    @router.get("/operators/node/identity")
    async def operator_node_identity() -> dict:
        return service.node_identity()

    @router.get("/operators/dashboard", response_class=HTMLResponse)
    async def operator_dashboard() -> str:
        return load_dashboard_html()

    @router.post("/operators/wallet/quote")
    async def wallet_quote(request: WalletQuoteRequest) -> dict:
        return service.quote_wallet_usage(**request.model_dump(mode="json"))

    @router.get("/operators/wallet/usage")
    async def wallet_usage_events(limit: int = 100) -> list[dict]:
        return service.list_wallet_usage_events(limit=limit)

    @router.get("/operators/wallet/endpoints/publications")
    async def wallet_endpoint_publications(endpoint_id: str | None = None) -> dict:
        if endpoint_publication_service is None:
            return {"items": []}
        records = endpoint_publication_service.list_publications(endpoint_id=endpoint_id)
        return {"items": [record.model_dump(mode="json") for record in records]}

    @router.get("/operators/wallet/endpoints/publications/export")
    async def export_wallet_endpoint_publications(
        endpoint_id: str | None = None,
        limit: int = 100,
    ) -> dict:
        if endpoint_publication_service is None:
            return {"items": [], "count": 0}
        records = endpoint_publication_service.list_publications(endpoint_id=endpoint_id)
        items = [record.model_dump(mode="json") for record in records[: max(0, limit)]]
        return {"items": items, "count": len(items)}

    @router.get("/operators/wallet/allocations")
    async def wallet_allocation_events(limit: int = 100) -> list[dict]:
        return service.list_wallet_allocation_events(limit=limit)

    @router.get("/operators/wallet/allocations/activations")
    async def wallet_allocation_activation_events(limit: int = 100) -> list[dict]:
        return service.list_wallet_allocation_activation_events(limit=limit)

    @router.get("/operators/wallet/allocations/disputes")
    async def wallet_allocation_dispute_events(limit: int = 100) -> list[dict]:
        return service.list_wallet_allocation_dispute_events(limit=limit)

    @router.get("/operators/wallet/usage/export")
    async def export_wallet_usage_events(
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return service.export_wallet_usage_events(
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
        return service.export_wallet_allocation_events(
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
        return service.export_wallet_allocation_activation_events(
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
        return service.export_wallet_allocation_dispute_events(
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
