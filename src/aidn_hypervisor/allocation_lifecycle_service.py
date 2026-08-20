from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from aidn_hypervisor.domain.models import AllocationRequest, BundleConfig
from aidn_hypervisor.resources import ResourceAdmissionError


class AllocationLifecycleService:
    """Allocation lifecycle orchestration extracted from HypervisorService."""

    def __init__(self, host) -> None:
        self._host = host

    def list_allocations(self) -> list[dict]:
        self._host._cleanup_expired_allocations()
        self._host._reconcile_pending_allocations()
        return [
            self._host._public_allocation(allocation)
            for allocation in self._host._allocations.values()
        ]

    def get_allocation(self, allocation_id: str) -> dict:
        self._host._cleanup_expired_allocations()
        self._host._reconcile_pending_allocations()
        return self._host._public_allocation(self._host._allocations[allocation_id])

    def reconcile_allocation(self, allocation_id: str) -> dict:
        self._host._cleanup_expired_allocations()
        self._host._reconcile_pending_allocations()
        return self.get_allocation(allocation_id)

    def create_allocation(self, request: AllocationRequest) -> dict:
        self._host._cleanup_expired_allocations()
        self._host._reconcile_pending_allocations()
        bundle = self._host._select_allocation_bundle(request)
        runtime = self._host._runtime_for_bundle(bundle.bundle_id)
        unavailability = self._host._allocation_unavailability(
            bundle=bundle,
            runtime=runtime,
        )
        if unavailability is not None:
            if request.policy == "wait" and unavailability["retryable"]:
                owner_quota = self._host._owner_quota_unavailability(
                    owner_id=request.owner_id,
                    status="pending",
                    bundle_id=bundle.bundle_id,
                )
                if owner_quota is not None:
                    raise self._host._allocation_unavailable_error(**owner_quota)
                return self.create_pending_allocation(
                    request=request,
                    bundle=bundle,
                    reason=str(unavailability["reason"]),
                )
            retry_hint = self._host._allocation_retry_hint(
                bundle_id=bundle.bundle_id,
                reason=str(unavailability["reason"]),
            )
            raise self._host._allocation_unavailable_error(
                reason=str(unavailability["reason"]),
                message=str(unavailability["message"]),
                bundle_id=bundle.bundle_id,
                retryable=bool(unavailability["retryable"]),
                retry_after_seconds=retry_hint["retry_after_seconds"]
                if unavailability["retryable"]
                else None,
                next_attempt_at=retry_hint["next_attempt_at"]
                if unavailability["retryable"]
                else None,
            )
        owner_quota = self._host._owner_quota_unavailability(
            owner_id=request.owner_id,
            status="active",
            bundle_id=bundle.bundle_id,
        )
        if owner_quota is not None:
            raise self._host._allocation_unavailable_error(**owner_quota)
        allocation_id = str(uuid4())
        now_ts = self._host._current_time_seconds()
        created_at = datetime.fromtimestamp(now_ts, UTC).isoformat()
        expires_at = datetime.fromtimestamp(
            now_ts + request.lease_seconds,
            UTC,
        ).isoformat()
        reservation_id = None
        try:
            reservation_id = self._host._reserve_allocation_residency(
                allocation_id=allocation_id,
                bundle=bundle,
                runtime=runtime,
            )
            if runtime is None:
                runtime = self._host.start_bundle(
                    bundle.bundle_id,
                    reserve_resources=False,
                )
        except ResourceAdmissionError as error:
            if reservation_id is not None:
                self._host.resources.release(reservation_id)
            if request.policy == "wait":
                return self.create_pending_allocation(
                    request=request,
                    bundle=bundle,
                    reason="insufficient_resources",
                )
            retry_hint = self._host._allocation_retry_hint(
                bundle_id=bundle.bundle_id,
                reason="insufficient_resources",
            )
            raise self._host._allocation_unavailable_error(
                reason="insufficient_resources",
                message=str(error),
                bundle_id=bundle.bundle_id,
                retryable=True,
                retry_after_seconds=retry_hint["retry_after_seconds"],
                next_attempt_at=retry_hint["next_attempt_at"],
            ) from error
        except Exception:
            if reservation_id is not None:
                self._host.resources.release(reservation_id)
            raise
        allocation = {
            "allocation_id": allocation_id,
            "request": request.model_dump(mode="json"),
            "workload_type": request.workload_type,
            "bundle_id": bundle.bundle_id,
            "runtime_id": runtime.runtime_id,
            "endpoint": self._host._runtime_boundary._resolve_runtime_endpoint(bundle, runtime),
            "status": "active",
            "created_at": created_at,
            "expires_at": expires_at,
            "reservation_id": reservation_id,
            "reason": None,
        }
        self._host._allocations[allocation_id] = allocation
        self._host._record_wallet_allocation_activation_hook(
            allocation,
            activation_source="create",
        )
        self._host.record_event(
            event_type="allocation.created",
            message="allocation created for agent client",
            bundle_id=bundle.bundle_id,
            runtime_id=runtime.runtime_id,
            details={
                "allocation_id": allocation_id,
                "workload_type": request.workload_type,
            },
        )
        self._host._persist_state()
        return self.get_allocation(allocation_id)

    def release_allocation(self, allocation_id: str) -> dict:
        self._host._cleanup_expired_allocations()
        allocation = self._host._allocations[allocation_id]
        self._host._release_allocation_resources(allocation)
        allocation["status"] = "released"
        self._host._record_wallet_allocation_event(allocation, status="released")
        self._host.record_event(
            event_type="allocation.released",
            message="allocation released by client",
            bundle_id=allocation["bundle_id"],
            runtime_id=allocation["runtime_id"],
            details={"allocation_id": allocation_id},
        )
        self._host._persist_state()
        reconcile = getattr(self._host, "reconcile_scheduler", None)
        if callable(reconcile):
            reconcile(trigger="allocation_released")
        return self.get_allocation(allocation_id)

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
        return self.get_allocation(allocation_id)
