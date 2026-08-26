"""Endpoint, session, and allocation context validation for task requests."""

from __future__ import annotations

from aidn_hypervisor.domain.models import TaskRequest


class EndpointExecutionContextService:
    """Apply execution constraints before a task is admitted to a bundle."""

    def __init__(self, host) -> None:
        self._host = host

    def task_request_with_endpoint_context(self, request: TaskRequest) -> TaskRequest:
        endpoint_id = request.constraints.get("endpoint_id")
        if endpoint_id is None:
            return request
        endpoint_service = getattr(self._host, "endpoint_service", None)
        if endpoint_service is None:
            raise ValueError("Endpoint service is not configured")
        manifest = endpoint_service.get_endpoint(str(endpoint_id)).endpoint
        if manifest.execution_strategy == "proxy" and manifest.proxy_target is None:
            raise ValueError(f"Proxy endpoint has no target: {manifest.endpoint_id}")
        if request.bundle_override is not None and request.bundle_override != manifest.bundle_id:
            raise ValueError(f"Endpoint bundle conflicts with requested bundle_override: {manifest.endpoint_id}")
        self.validate_task_session(manifest, request)
        return request.model_copy(
            update={
                "mode": "manual",
                "bundle_override": manifest.bundle_id,
            }
        )

    def endpoint_requires_session(self, manifest) -> bool:
        session_policy = manifest.session
        return any(
            (
                manifest.pricing.is_paid(),
                session_policy.minimum_deposit > 0,
                session_policy.minimum_session_fee > 0,
                session_policy.idle_fee_per_minute > 0,
            )
        )

    def validate_task_session(self, manifest, request: TaskRequest) -> None:
        session_id = request.constraints.get("session_id")
        if not self.endpoint_requires_session(manifest) and session_id is None:
            return
        if session_id is None:
            raise ValueError(f"Active session required for paid endpoint: {manifest.endpoint_id}")
        session_service = getattr(self._host, "session_service", None)
        if session_service is None:
            raise ValueError("Session service is not configured")
        try:
            session_service.require_active_session(
                endpoint_id=manifest.endpoint_id,
                session_id=str(session_id),
            )
            session_service.require_request_budget(
                endpoint_id=manifest.endpoint_id,
                session_id=str(session_id),
            )
            session = session_service.store.get_session(str(session_id))
            if (
                session.economic_profile == "MVP-0001"
                and session.canonical_funding_status != "FINALIZED"
            ):
                raise ValueError(
                    "MVP Session is awaiting canonical funding finality"
                )
            if session.economic_profile == "MVP-0001" and any(
                item.request.session_id == str(session_id)
                for item in self._host.runtime_protocol_store.requests.values()
            ):
                raise ValueError("MVP-0001 supports exactly one Runtime Request per Session")
        except KeyError as error:
            raise ValueError(f"Unknown session: {session_id}") from error

    def task_request_with_allocation_context(self, request: TaskRequest) -> TaskRequest:
        allocation_id = request.constraints.get("allocation_id")
        if allocation_id is None:
            return request

        self._host._cleanup_expired_allocations()
        self._host._reconcile_pending_allocations()
        allocation = self._host._allocations.get(str(allocation_id))
        if allocation is None:
            raise ValueError(f"Unknown allocation: {allocation_id}")
        if allocation["status"] != "active":
            raise ValueError(f"Allocation is not active: {allocation_id}")

        allocation_bundle_id = str(allocation["bundle_id"])
        if request.bundle_override is not None and request.bundle_override != allocation_bundle_id:
            raise ValueError(f"Allocation bundle conflicts with requested bundle_override: {allocation_id}")

        constraints = dict(request.constraints)
        owner_id = allocation["request"].get("owner_id")
        if owner_id is not None and "wallet_owner_id" not in constraints:
            constraints["wallet_owner_id"] = owner_id

        return request.model_copy(
            update={
                "mode": "manual",
                "bundle_override": allocation_bundle_id,
                "constraints": constraints,
            }
        )
