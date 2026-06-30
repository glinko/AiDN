from collections.abc import Iterable

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from aidn_hypervisor.dashboard import build_market_payload, load_dashboard_html
from aidn_hypervisor.domain.models import (
    AllocationRequest,
    BundleConfig,
    ModelInstallRequest,
    RegisterBundleFromInstallRequest,
    TaskRequest,
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


class OperatorRequestsPolicyRequest(BaseModel):
    allow_spillover: bool
    dispatch_strategy: str
    ready_endpoint_only: bool


def build_api_router(
    service: HypervisorService,
    *,
    registry_service=None,
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

        return _serialize_task(
            task_id=task.task_id,
            status=task.status,
            priority=task.priority,
            task_type=task.request.task_type,
            bundle_id=service.selected_bundle_id(task.task_id),
            result=service.task_result(task.task_id),
            recovery_reason=service.task_recovery_reason(task.task_id),
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
        payload["market_preview"] = {
            "candidate_count": len(market["candidates"]),
        }
        return payload

    @router.get("/operators/dashboard/fleet")
    async def operator_dashboard_fleet() -> dict:
        return service.operator_dashboard_fleet()

    @router.get("/operators/dashboard/market")
    async def operator_dashboard_market() -> dict:
        return build_market_payload(
            service=service,
            registry_service=registry_service,
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

    @router.get("/operators/dashboard", response_class=HTMLResponse)
    async def operator_dashboard() -> str:
        return load_dashboard_html()

    @router.post("/operators/wallet/quote")
    async def wallet_quote(request: WalletQuoteRequest) -> dict:
        return service.quote_wallet_usage(**request.model_dump(mode="json"))

    @router.get("/operators/wallet/usage")
    async def wallet_usage_events(limit: int = 100) -> list[dict]:
        return service.list_wallet_usage_events(limit=limit)

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
