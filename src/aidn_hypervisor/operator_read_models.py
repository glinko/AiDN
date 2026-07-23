from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from aidn_hypervisor.domain.models import BundleConfig
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.queue import QueuedTask

if TYPE_CHECKING:
    from aidn_hypervisor.service import HypervisorService


class OperatorReadModelService:
    """Builds operator-facing dashboard/read-model payloads.

    This keeps presentation-oriented aggregation out of HypervisorService while
    preserving the existing service API surface through delegation.
    """

    def __init__(self, service: HypervisorService) -> None:
        self._service = service

    def fleet(self) -> dict:
        service = self._service
        resources = (
            service.resources.summary()
            if service.resources is not None
            else service._empty_resource_summary()
            if hasattr(service, "_empty_resource_summary")
            else {
                "total": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
                "reserved": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
                "free": {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0},
            }
        )
        return {
            "node": {
                "node_id": service.node_id,
                "operator_id": service.operator_id,
                "base_url": service.base_url,
                "can_host_custom_model": service.can_host_custom_model,
                "pricing": service.pricing,
                "rating": service.rating,
            },
            "resources": resources,
            "queue": service.queue_summary(),
            "installs": [
                {
                    "install_id": install["install_id"],
                    "provider_type": install["provider_type"],
                    "model_id": install["model_id"],
                    "requested_by": install["requested_by"],
                    "install_status": self._install_status(str(install["status"])),
                    "bundle_id": install["bundle_id"],
                    "last_error": install["last_error"],
                }
                for install in service.list_model_installs()
            ],
            "bundles": [self._bundle_entry(bundle) for bundle in service.bundles],
            "owner_wallet": service.owner_wallet_state(),
            "node_identity": service.node_identity(),
        }

    def home(self) -> dict:
        fleet = self.fleet()
        enabled_bundles = [bundle for bundle in fleet["bundles"] if bundle["enabled"]]
        pending_installs = [
            install
            for install in fleet["installs"]
            if install["install_status"] in {"pending", "running"}
        ]
        bootstrap = self._bootstrap(fleet)
        return {
            "bootstrap": bootstrap,
            "summary": {
                "bundle_total": len(fleet["bundles"]),
                "enabled_bundle_total": len(enabled_bundles),
                "pending_install_total": len(pending_installs),
                "queue": fleet["queue"],
                "free_resources": fleet["resources"]["free"],
            },
        }

    def endpoints(self) -> dict:
        items: list[dict] = []
        service = self._service
        return {
            "owner_wallet": service.owner_wallet_state(),
            "node_identity": service.node_identity(),
            "summary": {
                "total": len(items),
                "configured": sum(
                    1 for item in items if item["publication_status"] == "configured"
                ),
                "published": sum(
                    1 for item in items if item["publication_status"] == "published"
                ),
                "validation_requested": sum(
                    1 for item in items if item["validation_mode"] == "requested"
                ),
                "private": sum(1 for item in items if item["visibility"] == "private"),
                "shared": sum(1 for item in items if item["visibility"] == "shared"),
                "public": sum(1 for item in items if item["visibility"] == "public"),
            },
            "policy": {
                "publish_requires_validation": False,
                "validation_optional": True,
                "execution_privacy": "endpoint implementation remains private",
            },
            "items": items,
        }

    def requests(self, *, market_candidates: list[dict] | None = None) -> dict:
        service = self._service
        tasks = service.queue.snapshot()
        queue = [
            self._task_entry(task)
            for task in tasks
            if task.status in {"queued", "admitted", "starting"}
        ]
        active = [self._task_entry(task) for task in tasks if task.status == "running"]
        recent = sorted(
            [
                self._task_entry(task)
                for task in tasks
                if task.status in {"completed", "failed", "cancelled"}
            ],
            key=lambda item: datetime.fromisoformat(
                item["terminal_at"] or item["created_at"]
            ),
            reverse=True,
        )[:12]
        preview = self.spillover_preview(market_candidates or [])
        return {
            "summary": {
                "queued": len(queue),
                "active": len(active),
                "completed_recent": len(
                    [item for item in recent if item["status"] == "completed"]
                ),
                "failed_recent": len(
                    [item for item in recent if item["status"] == "failed"]
                ),
                "admission_blocked": len(queue),
                "spillover_ready": len(preview),
            },
            "queue": queue,
            "active": active,
            "recent": recent,
            "admission": service.admission_telemetry(),
            "policy": service.operator_requests_policy(),
            "market_spillover_preview": preview,
        }

    def _bundle_entry(self, bundle: BundleConfig) -> dict:
        service = self._service
        runtime: RuntimeHandle | None = service._runtime_for_bundle(bundle.bundle_id)
        state = service._current_bundle_state(bundle.bundle_id)
        return {
            "bundle_id": bundle.bundle_id,
            "plugin_id": bundle.plugin_id,
            "provider_type": bundle.provider_type,
            "workload_type": bundle.workload_type,
            "model_id": bundle.model_id,
            "enabled": bundle.enabled,
            "endpoint": bundle.endpoint,
            "runtime_status": runtime.status if runtime is not None else "stopped",
            "publish_status": "ready_to_publish" if bundle.enabled else "disabled",
            "inventory_status": service._bundle_inventory_status(bundle),
            "registry_status": service._bundle_registry_status(bundle),
            "cooldown_until": state["cooldown_until"],
            "drain_mode": state["drain_mode"],
        }

    def _task_entry(self, task: QueuedTask) -> dict:
        service = self._service
        created_at = datetime.fromisoformat(task.created_at)
        age_seconds = max(
            0,
            int((datetime.now(timezone.utc) - created_at).total_seconds()),
        )
        terminal_at = self.task_terminal_timestamp(task.task_id)
        return {
            "task_id": task.task_id,
            "status": task.status,
            "priority": task.priority,
            "task_type": task.request.task_type,
            "bundle_id": service.selected_bundle_id(task.task_id),
            "created_at": task.created_at,
            "terminal_at": terminal_at,
            "age_seconds": age_seconds,
            "recovery_reason": service.task_recovery_reason(task.task_id),
            "result": service.task_result(task.task_id),
            "proxy_trace": service.task_proxy_trace(task.task_id),
        }

    def _bootstrap(self, fleet: dict) -> dict:
        return self.bootstrap(fleet)

    def task_terminal_timestamp(self, task_id: str) -> str | None:
        terminal_events = {"task.completed", "task.failed", "task.cancelled"}
        for event in reversed(self._service.task_history(task_id)):
            if event.event_type in terminal_events:
                return event.timestamp
        return None

    def spillover_preview(self, market_candidates: list[dict]) -> list[dict]:
        service = self._service
        policy = service.operator_requests_policy()
        if not bool(policy["allow_spillover"]):
            return []
        candidates = [
            candidate
            for candidate in market_candidates
            if candidate.get("origin") != "own"
        ]
        candidates = [
            candidate for candidate in candidates if bool(candidate.get("supports_queue"))
        ]
        if bool(policy["ready_endpoint_only"]):
            candidates = [
                candidate
                for candidate in candidates
                if bool(candidate.get("endpoint_ready"))
            ]
        strategy = str(policy["dispatch_strategy"])
        if strategy == "market_first":
            candidates.sort(
                key=lambda candidate: (
                    self.candidate_price(candidate),
                    -self.candidate_rating(candidate),
                    str(candidate.get("bundle_id") or ""),
                )
            )
        elif strategy == "balanced":
            candidates.sort(
                key=lambda candidate: (
                    self.balanced_candidate_score(candidate),
                    str(candidate.get("bundle_id") or ""),
                )
            )
        else:
            candidates.sort(
                key=lambda candidate: (
                    -self.candidate_rating(candidate),
                    self.candidate_price(candidate),
                    str(candidate.get("bundle_id") or ""),
                )
            )
        return candidates[:5]

    def candidate_price(self, candidate: dict) -> float:
        pricing = candidate.get("pricing") or {}
        return float(pricing.get("input") or 0)

    def candidate_rating(self, candidate: dict) -> float:
        reputation = candidate.get("reputation") or {}
        if reputation.get("score") is not None:
            return float(reputation.get("score") or 0)
        rating = candidate.get("rating") or {}
        return float(rating.get("score") or 0)

    def balanced_candidate_score(self, candidate: dict) -> float:
        return self.candidate_price(candidate) / 2000 - self.candidate_rating(candidate)

    def bootstrap(self, fleet: dict) -> dict:
        service = self._service
        candidate = next((bundle for bundle in fleet["bundles"] if bundle["enabled"]), None)
        wallet = service.owner_wallet_state()
        if not wallet["configured"]:
            next_step = "Create or import a wallet"
        elif candidate is not None:
            next_step = f"Create your first endpoint from {candidate['bundle_id']}"
        else:
            next_step = "Attach a provider or install a model"
        provider_count = (
            len(service.plugins.list())
            if hasattr(service.plugins, "list")
            else len(service.plugins or [])
        )
        return {
            "wallet_ready": wallet["configured"],
            "owner_wallet": wallet,
            "node_identity": service.node_identity(),
            "provider_count": provider_count,
            "bundle_count": len(fleet["bundles"]),
            "endpoint_count": 0,
            "first_endpoint_candidate": candidate,
            "next_step": next_step,
        }

    def _install_status(self, status: str) -> str:
        return self.install_status(status)

    def install_status(self, status: str) -> str:
        if status == "queued":
            return "pending"
        return status
