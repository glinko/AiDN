from __future__ import annotations

import time
from datetime import UTC, datetime
from uuid import uuid4

from aidn_hypervisor.bundle_hash import bundle_config_hash
from aidn_hypervisor.domain.models import AllocationRequest, BundleConfig
from aidn_hypervisor.process_manager import RuntimeHandle

_ALLOCATION_RETRY_INTERVAL_SECONDS = 5


class AllocationCatalogService:
    """Catalog, allocation-fit, and allocation-state helpers for HypervisorService."""

    def __init__(self, host) -> None:
        self._host = host

    def filtered_catalog_bundles(
        self,
        *,
        workload_type: str | None,
        bundle_id: str | None,
        include_disabled: bool,
    ) -> list[BundleConfig]:
        bundles: list[BundleConfig] = []
        for bundle in self._host.bundles:
            if bundle_id is not None and bundle.bundle_id != bundle_id:
                continue
            if workload_type is not None and bundle.workload_type != workload_type:
                continue
            if not include_disabled and not bundle.enabled:
                continue
            bundles.append(bundle)
        return bundles

    def catalog_entry(self, bundle: BundleConfig, *, owner_id: str) -> dict:
        runtime = self._host._runtime_for_bundle(bundle.bundle_id)
        endpoint = self.catalog_endpoint(bundle, runtime)
        required = self.catalog_required_resources(bundle, runtime)
        payload = {
            "bundle_id": bundle.bundle_id,
            "plugin_id": bundle.plugin_id,
            "provider_type": bundle.provider_type,
            "model_id": bundle.model_id,
            "workload_type": bundle.workload_type,
            "enabled": bundle.enabled,
            "status": self._host._bundle_inventory_status(bundle),
            "endpoint": endpoint,
            "can_allocate_now": False,
            "can_queue": False,
            "allocation_mode": "unavailable",
            "reason": None,
            "required": required,
            "requires_runtime_start": runtime is None,
            "fit": self.catalog_fit(required),
        }

        if not bundle.enabled:
            payload["reason"] = "bundle_disabled"
            return payload

        unavailability = self.allocation_unavailability(bundle=bundle, runtime=runtime)
        if unavailability is None:
            owner_quota = self.owner_quota_unavailability(
                owner_id=owner_id,
                status="active",
                bundle_id=bundle.bundle_id,
            )
            if owner_quota is None:
                payload["can_allocate_now"] = True
                payload["allocation_mode"] = "active"
                return payload
            payload["reason"] = str(owner_quota["reason"])
            return payload

        payload["reason"] = str(unavailability["reason"])
        if not bool(unavailability["retryable"]):
            return payload

        owner_quota = self.owner_quota_unavailability(
            owner_id=owner_id,
            status="pending",
            bundle_id=bundle.bundle_id,
        )
        if owner_quota is not None:
            payload["reason"] = str(owner_quota["reason"])
            return payload

        payload["can_queue"] = True
        payload["allocation_mode"] = "wait"
        return payload

    def operator_dashboard_bundle_entry(self, bundle: BundleConfig) -> dict:
        runtime = self._host._runtime_for_bundle(bundle.bundle_id)
        state = self._host._current_bundle_state(bundle.bundle_id)
        return {
            "bundle_id": bundle.bundle_id,
            "revision": bundle.revision,
            "revision_of": bundle.revision_of,
            "bundle_hash": bundle.bundle_hash or bundle_config_hash(bundle),
            "plugin_id": bundle.plugin_id,
            "provider_type": bundle.provider_type,
            "workload_type": bundle.workload_type,
            "model_id": bundle.model_id,
            "launch_mode": bundle.launch_mode,
            "provider_api_format": bundle.provider_api_format,
            "device_affinity": bundle.device_affinity,
            "resource_profile": bundle.resource_profile.model_dump(mode="json"),
            "warm_policy": bundle.warm_policy,
            "priority_class": bundle.priority_class,
            "max_parallel_requests": bundle.max_parallel_requests,
            "enabled": bundle.enabled,
            "endpoint": bundle.endpoint,
            "runtime_id": runtime.runtime_id if runtime is not None else None,
            "runtime_status": runtime.status if runtime is not None else "stopped",
            "runtime_health_status": runtime.health_status if runtime is not None else "unknown",
            "runtime_last_error": runtime.last_error if runtime is not None else None,
            "publish_status": "ready_to_publish" if bundle.enabled else "disabled",
            "inventory_status": self._host._bundle_inventory_status(bundle),
            "registry_status": self._host._bundle_registry_status(bundle),
            "cooldown_until": state["cooldown_until"],
            "drain_mode": state["drain_mode"],
        }

    def catalog_endpoint(
        self,
        bundle: BundleConfig,
        runtime: RuntimeHandle | None,
    ) -> str | None:
        if runtime is None:
            return bundle.endpoint
        return runtime.metadata.get("endpoint") or bundle.endpoint

    def catalog_required_resources(
        self,
        bundle: BundleConfig,
        runtime: RuntimeHandle | None,
    ) -> dict[str, float | int]:
        profile = bundle.resource_profile
        if runtime is None:
            return {
                "cpu": profile.cold_start_cpu + profile.steady_cpu,
                "ram_mb": profile.cold_start_ram_mb + profile.steady_ram_mb,
                "vram_mb": profile.cold_start_vram_mb + profile.steady_vram_mb,
            }
        return {
            "cpu": profile.steady_cpu,
            "ram_mb": profile.steady_ram_mb,
            "vram_mb": profile.steady_vram_mb,
        }

    def catalog_fit(
        self,
        required: dict[str, float | int],
    ) -> dict[str, float | int | bool]:
        if self._host.resources is None:
            return {
                "fits": True,
                "cpu_shortfall": 0.0,
                "ram_mb_shortfall": 0,
                "vram_mb_shortfall": 0,
            }
        return self._host.resources.fit_report(
            float(required["cpu"]),
            int(required["ram_mb"]),
            int(required["vram_mb"]),
        )

    def select_allocation_bundle(self, request: AllocationRequest) -> BundleConfig:
        if request.bundle_id is not None:
            bundle = self._host._get_bundle(request.bundle_id)
            if not bundle.enabled:
                raise self._host._allocation_unavailable_error(
                    reason="bundle_disabled",
                    message=f"Bundle is disabled: {bundle.bundle_id}",
                    bundle_id=bundle.bundle_id,
                    retryable=False,
                )
            if bundle.workload_type != request.workload_type:
                raise self._host._allocation_unavailable_error(
                    reason="workload_mismatch",
                    message=(
                        f"Bundle workload mismatch: {bundle.bundle_id} != {request.workload_type}"
                    ),
                    bundle_id=bundle.bundle_id,
                    retryable=False,
                )
            return bundle

        for bundle in self._host.bundles:
            if bundle.enabled and bundle.workload_type == request.workload_type:
                return bundle
        raise self._host._allocation_unavailable_error(
            reason="no_compatible_bundle",
            message=f"No compatible bundle for workload_type: {request.workload_type}",
            bundle_id=request.bundle_id,
            retryable=False,
        )

    def resolve_runtime_endpoint(
        self,
        bundle: BundleConfig,
        runtime: RuntimeHandle,
    ) -> str:
        endpoint = runtime.metadata.get("endpoint") or bundle.endpoint
        if endpoint is None:
            raise ValueError(f"Bundle has no resolved endpoint: {bundle.bundle_id}")
        return endpoint

    def allocation_unavailability(
        self,
        *,
        bundle: BundleConfig,
        runtime: RuntimeHandle | None,
    ) -> dict[str, str | bool] | None:
        if self._host._current_bundle_state(bundle.bundle_id)["drain_mode"]:
            return {
                "reason": "bundle_draining",
                "message": f"Bundle is draining: {bundle.bundle_id}",
                "retryable": True,
            }
        if self._host._bundle_in_cooldown(bundle.bundle_id):
            return {
                "reason": "provider_cooldown",
                "message": f"Bundle is in cooldown: {bundle.bundle_id}",
                "retryable": True,
            }
        if bundle.endpoint is None and runtime is None:
            return {
                "reason": "endpoint_unresolved",
                "message": f"Bundle has no resolved endpoint: {bundle.bundle_id}",
                "retryable": False,
            }
        profile = bundle.resource_profile
        if self._host.resources is not None:
            if runtime is None and not self._host.resources.can_fit(
                profile.cold_start_cpu + profile.steady_cpu,
                profile.cold_start_ram_mb + profile.steady_ram_mb,
                profile.cold_start_vram_mb + profile.steady_vram_mb,
            ):
                return {
                    "reason": "insufficient_resources",
                    "message": (
                        f"insufficient resources for allocation runtime residency: {bundle.bundle_id}"
                    ),
                    "retryable": True,
                }
            if not self._host.resources.can_fit(
                profile.steady_cpu,
                profile.steady_ram_mb,
                profile.steady_vram_mb,
            ):
                return {
                    "reason": "insufficient_resources",
                    "message": (
                        f"insufficient resources for allocation runtime residency: {bundle.bundle_id}"
                    ),
                    "retryable": True,
                }
        return None

    def reserve_allocation_residency(
        self,
        *,
        allocation_id: str,
        bundle: BundleConfig,
        runtime: RuntimeHandle | None,
    ) -> str | None:
        if self._host.resources is None:
            return None
        if runtime is not None:
            if self._host._runtime_reservation_id(bundle.bundle_id) in self._host._runtime_reservations:
                return None
            if self.bundle_has_active_allocation_reservation(bundle.bundle_id):
                return None

        profile = bundle.resource_profile
        reservation_id = f"allocation:{allocation_id}"
        self._host.resources.reserve(
            reservation_id,
            cpu=profile.steady_cpu,
            ram_mb=profile.steady_ram_mb,
            vram_mb=profile.steady_vram_mb,
        )
        return reservation_id

    def bundle_has_active_allocation_reservation(self, bundle_id: str) -> bool:
        for allocation in self._host._allocations.values():
            if allocation["bundle_id"] != bundle_id:
                continue
            if allocation["status"] != "active":
                continue
            if allocation.get("reservation_id") is None:
                continue
            return True
        return False

    def release_allocation_resources(self, allocation: dict) -> None:
        reservation_id = allocation.get("reservation_id")
        if reservation_id is not None and self._host.resources is not None:
            self._host.resources.release(reservation_id)
            allocation["reservation_id"] = None

    def owner_allocation_count(self, owner_id: str, *, status: str) -> int:
        count = 0
        for allocation in self._host._allocations.values():
            if allocation["status"] != status:
                continue
            request = allocation.get("request", {})
            if request.get("owner_id") != owner_id:
                continue
            count += 1
        return count

    def owner_quota_unavailability(
        self,
        *,
        owner_id: str,
        status: str,
        bundle_id: str,
    ) -> dict[str, str | bool | int | None] | None:
        if status == "active":
            limit = self._host.max_active_allocations_per_owner
            count = self.owner_allocation_count(owner_id, status="active")
        elif status == "pending":
            limit = self._host.max_pending_allocations_per_owner
            count = self.owner_allocation_count(owner_id, status="pending")
        else:
            raise ValueError(f"unsupported allocation quota status: {status}")

        if count < limit:
            return None

        retry_hint = self.allocation_retry_hint(
            bundle_id=bundle_id,
            reason="owner_quota_exceeded",
        )
        return {
            "reason": "owner_quota_exceeded",
            "message": f"owner {status} allocation quota exceeded: {owner_id}",
            "bundle_id": bundle_id,
            "retryable": True,
            "retry_after_seconds": retry_hint["retry_after_seconds"],
            "next_attempt_at": retry_hint["next_attempt_at"],
        }

    def cleanup_expired_allocations(self) -> None:
        expired_any = False
        now = time.time()
        for allocation in self._host._allocations.values():
            if allocation["status"] not in {"active", "pending"}:
                continue
            try:
                expires_at = datetime.fromisoformat(allocation["expires_at"]).timestamp()
            except ValueError:
                continue
            if expires_at > now:
                continue
            self.release_allocation_resources(allocation)
            allocation["status"] = "expired"
            self._host._record_wallet_allocation_event(allocation, status="expired")
            self._host.record_event(
                event_type="allocation.expired",
                message="allocation lease expired",
                bundle_id=allocation["bundle_id"],
                runtime_id=allocation["runtime_id"],
                details={"allocation_id": allocation["allocation_id"]},
            )
            expired_any = True
        if expired_any:
            self._host._persist_state()

    def public_allocation(self, allocation: dict) -> dict:
        request = allocation["request"]
        payload = {
            "allocation_id": allocation["allocation_id"],
            "owner_id": request["owner_id"],
            "workload_type": allocation["workload_type"],
            "bundle_id": allocation["bundle_id"],
            "runtime_id": allocation["runtime_id"],
            "endpoint": allocation["endpoint"],
            "status": allocation["status"],
        }
        if allocation.get("reason") is not None:
            payload["reason"] = allocation["reason"]
        if allocation["status"] == "pending" and allocation.get("reason") is not None:
            retry_hint = self.allocation_retry_hint(
                bundle_id=str(allocation["bundle_id"]),
                reason=str(allocation["reason"]),
            )
            payload["retry_after_seconds"] = retry_hint["retry_after_seconds"]
            payload["next_attempt_at"] = retry_hint["next_attempt_at"]
        return payload

    def create_pending_allocation(
        self,
        *,
        request: AllocationRequest,
        bundle: BundleConfig,
        reason: str,
    ) -> dict:
        allocation_id = str(uuid4())
        now_ts = self._host._current_time_seconds()
        created_at = datetime.fromtimestamp(now_ts, UTC).isoformat()
        expires_at = datetime.fromtimestamp(
            now_ts + request.lease_seconds,
            UTC,
        ).isoformat()
        self._host._allocations[allocation_id] = {
            "allocation_id": allocation_id,
            "request": request.model_dump(mode="json"),
            "workload_type": request.workload_type,
            "bundle_id": bundle.bundle_id,
            "runtime_id": None,
            "endpoint": None,
            "status": "pending",
            "created_at": created_at,
            "expires_at": expires_at,
            "reservation_id": None,
            "reason": reason,
        }
        self._host.record_event(
            event_type="allocation.pending",
            message="allocation queued in wait mode",
            bundle_id=bundle.bundle_id,
            details={"allocation_id": allocation_id, "reason": reason},
        )
        self._host._persist_state()
        return self._host.get_allocation(allocation_id)

    def reconcile_pending_allocations(self) -> None:
        changed = False
        for allocation in self._host._allocations.values():
            if allocation["status"] != "pending":
                continue
            request = AllocationRequest(**allocation["request"])
            try:
                bundle = self.select_allocation_bundle(request)
            except ValueError as error:
                if hasattr(error, "reason"):
                    allocation["reason"] = error.reason
                continue

            runtime = self._host._runtime_for_bundle(bundle.bundle_id)
            unavailability = self.allocation_unavailability(bundle=bundle, runtime=runtime)
            if unavailability is not None:
                allocation["reason"] = str(unavailability["reason"])
                continue
            owner_quota = self.owner_quota_unavailability(
                owner_id=request.owner_id,
                status="active",
                bundle_id=bundle.bundle_id,
            )
            if owner_quota is not None:
                allocation["reason"] = str(owner_quota["reason"])
                continue

            reservation_id = self.reserve_allocation_residency(
                allocation_id=str(allocation["allocation_id"]),
                bundle=bundle,
                runtime=runtime,
            )
            if runtime is None:
                runtime = self._host.start_bundle(bundle.bundle_id)
            allocation["bundle_id"] = bundle.bundle_id
            allocation["runtime_id"] = runtime.runtime_id
            allocation["endpoint"] = self.resolve_runtime_endpoint(bundle, runtime)
            allocation["status"] = "active"
            allocation["reservation_id"] = reservation_id
            allocation["reason"] = None
            self._host._record_wallet_allocation_activation_hook(
                allocation, activation_source="pending_reconcile"
            )
            self._host.record_event(
                event_type="allocation.activated",
                message="pending allocation activated",
                bundle_id=bundle.bundle_id,
                runtime_id=runtime.runtime_id,
                details={"allocation_id": allocation["allocation_id"]},
            )
            changed = True
        if changed:
            self._host._persist_state()

    def allocation_retry_hint(
        self,
        *,
        bundle_id: str,
        reason: str,
    ) -> dict[str, int | str]:
        if reason == "provider_cooldown":
            cooldown_until = self._host._current_bundle_state(bundle_id)["cooldown_until"]
            if cooldown_until is not None:
                retry_after_seconds = max(0, int(cooldown_until - time.time()))
                return {
                    "retry_after_seconds": retry_after_seconds,
                    "next_attempt_at": datetime.fromtimestamp(
                        cooldown_until,
                        UTC,
                    ).isoformat(),
                }
        next_attempt_ts = time.time() + _ALLOCATION_RETRY_INTERVAL_SECONDS
        return {
            "retry_after_seconds": _ALLOCATION_RETRY_INTERVAL_SECONDS,
            "next_attempt_at": datetime.fromtimestamp(
                next_attempt_ts,
                UTC,
            ).isoformat(),
        }
