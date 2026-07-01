import hashlib
import json
from datetime import datetime, timezone
import time
from urllib import error as urllib_error, request as urllib_request
from uuid import uuid4

from pydantic import ValidationError

from aidn_hypervisor.domain.models import AllocationRequest, BundleConfig, ResourceProfile, TaskRequest
from aidn_hypervisor.process_manager import RuntimeHandle
from aidn_hypervisor.queue import InMemoryTaskQueue, QueuedTask
from aidn_hypervisor.registry_models import (
    RegistryBundleAdvertisement,
    RegistryNodeAdvertisement,
    RegistryPricing,
    RegistryPublishedEndpointSummary,
    RegistryRating,
)
from aidn_hypervisor.scheduler import Scheduler
from aidn_hypervisor.state import (
    AllocationSnapshot,
    BundleStateSnapshot,
    HypervisorStateSnapshot,
    JournalEvent,
    ModelInstallSnapshot,
    OwnerWalletSnapshot,
    RuntimeSnapshot,
    TaskSnapshot,
    WalletAllocationActivationSnapshot,
    WalletAllocationDisputeSnapshot,
    WalletAllocationSnapshot,
    WalletSessionSnapshot,
    WalletUsageSnapshot,
)
from aidn_hypervisor.wallet import quote_usage_q
from aidn_hypervisor.wallet_models import (
    WalletAllocationActivationEvent,
    WalletAllocationDisputeEvent,
    WalletAllocationEvent,
    WalletSessionEvent,
    WalletUsageEvent,
    WalletUsageMeasurement,
)

_CANCELLABLE_TASK_STATUSES = {"queued", "admitted", "starting"}
_ACTIVE_EXECUTION_STATUSES = {"admitted", "starting", "running"}
_TERMINAL_FAILED_STATUSES = {"failed"}
_TERMINAL_COMPLETED_STATUSES = {"completed"}
_AGING_PRIORITY_STEP = 10
_AGING_PRIORITY_INTERVAL_SECONDS = 60
_AGING_PRIORITY_MAX_BONUS = 100
_ALLOCATION_RETRY_INTERVAL_SECONDS = 5
_DEFAULT_OPERATOR_REQUESTS_POLICY = {
    "allow_spillover": False,
    "dispatch_strategy": "local_first",
    "ready_endpoint_only": True,
}


def _empty_resource_summary() -> dict[str, dict[str, float | int]]:
    zeroes = {"cpu": 0.0, "ram_mb": 0, "vram_mb": 0}
    return {
        "total": dict(zeroes),
        "reserved": dict(zeroes),
        "free": dict(zeroes),
    }


class AllocationUnavailableError(ValueError):
    def __init__(
        self,
        *,
        reason: str,
        message: str,
        bundle_id: str | None,
        retryable: bool,
        retry_after_seconds: int | None = None,
        next_attempt_at: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.bundle_id = bundle_id
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.next_attempt_at = next_attempt_at

    def as_detail(self) -> dict[str, str | bool | None]:
        detail = {
            "reason": self.reason,
            "retryable": self.retryable,
            "bundle_id": self.bundle_id,
            "message": self.message,
        }
        if self.retry_after_seconds is not None:
            detail["retry_after_seconds"] = self.retry_after_seconds
        if self.next_attempt_at is not None:
            detail["next_attempt_at"] = self.next_attempt_at
        return detail


class HypervisorService:
    def __init__(
        self,
        queue: InMemoryTaskQueue,
        scheduler: Scheduler,
        resources=None,
        bundles=None,
        plugins=None,
        runtimes=None,
        state_store=None,
        bundle_registry=None,
        model_store=None,
        max_active_allocations_per_owner: int = 2,
        max_pending_allocations_per_owner: int = 4,
        node_id: str = "node-local",
        operator_id: str = "operator-local",
        base_url: str = "http://127.0.0.1:8000",
        can_host_custom_model: bool = False,
        pricing: dict | None = None,
        rating: dict | None = None,
        heartbeat_ttl_seconds: int = 30,
        wallet_usage_retention_limit: int | None = None,
        wallet_allocation_grace_period_seconds: int = 300,
    ) -> None:
        self.queue = queue
        self.scheduler = scheduler
        self.resources = resources
        self.bundles = bundles or []
        self.plugins = plugins or []
        self.runtimes = runtimes or []
        self.state_store = state_store
        self.bundle_registry = bundle_registry
        self.model_store = model_store
        self.max_active_allocations_per_owner = max_active_allocations_per_owner
        self.max_pending_allocations_per_owner = max_pending_allocations_per_owner
        self.node_id = node_id
        self.operator_id = operator_id
        self.base_url = base_url
        self.can_host_custom_model = can_host_custom_model
        self.pricing = pricing or {
            "unit": "q_per_1kk_tokens",
            "input": 0,
            "output": 0,
            "fixed_request": None,
        }
        self.rating = rating or {
            "score": 0.0,
            "tier": "unrated",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.heartbeat_ttl_seconds = heartbeat_ttl_seconds
        self.wallet_usage_retention_limit = (
            max(1, int(wallet_usage_retention_limit))
            if wallet_usage_retention_limit is not None
            else None
        )
        self.wallet_allocation_grace_period_seconds = max(
            0, int(wallet_allocation_grace_period_seconds)
        )
        self._selected_bundles: dict[str, str] = {}
        self._task_results: dict[str, dict] = {}
        self._task_recovery_reasons: dict[str, str] = {}
        self._allocations: dict[str, dict] = {}
        self._model_installs: dict[str, dict] = {}
        self._operator_requests_policy = dict(_DEFAULT_OPERATOR_REQUESTS_POLICY)
        self._owner_wallet: dict | None = None
        self._runtime_reservations: set[str] = set()
        self._bundle_states: dict[str, dict] = {}
        self._wallet_usage_events: list[dict] = []
        self._next_wallet_usage_sequence = 1
        self._wallet_session_events: list[dict] = []
        self._next_wallet_session_sequence = 1
        self._wallet_allocation_activation_events: list[dict] = []
        self._next_wallet_allocation_activation_sequence = 1
        self._wallet_allocation_dispute_events: list[dict] = []
        self._next_wallet_allocation_dispute_sequence = 1
        self._wallet_allocation_events: list[dict] = []
        self._next_wallet_allocation_sequence = 1
        self._events: list[JournalEvent] = []

    @property
    def pricing(self) -> dict:
        return self._pricing.model_dump(mode="json")

    @pricing.setter
    def pricing(self, value: RegistryPricing | dict) -> None:
        if isinstance(value, RegistryPricing):
            self._pricing = value
            return
        self._pricing = RegistryPricing(**value)

    @property
    def rating(self) -> dict:
        return self._rating.model_dump(mode="json")

    @rating.setter
    def rating(self, value: RegistryRating | dict) -> None:
        if isinstance(value, RegistryRating):
            self._rating = value
            return
        self._rating = RegistryRating(**value)

    def submit(self, request: TaskRequest):
        effective_request = self._task_request_with_allocation_context(request)
        effective_request = self._task_request_with_endpoint_context(effective_request)
        bundle = self.scheduler.select_bundle(effective_request, self.bundles)
        task = self.queue.enqueue(effective_request)
        self._selected_bundles[task.task_id] = bundle.bundle_id
        self.record_event(
            event_type="task.submitted",
            message="task accepted into queue",
            task_id=task.task_id,
            bundle_id=bundle.bundle_id,
            details={
                "task_type": effective_request.task_type,
                "mode": effective_request.mode,
            },
        )
        self.process_pending()
        return task

    def selected_bundle_id(self, task_id: str) -> str | None:
        return self._selected_bundles.get(task_id)

    def task_result(self, task_id: str) -> dict | None:
        return self._task_results.get(task_id)

    def task_recovery_reason(self, task_id: str) -> str | None:
        return self._task_recovery_reasons.get(task_id)

    def task_proxy_trace(self, task_id: str) -> dict | None:
        result = self.task_result(task_id) or {}
        proxy_result = result.get("proxy") if isinstance(result, dict) else None
        dispatch_event = next(
            (
                event
                for event in reversed(self.task_history(task_id))
                if event.event_type == "task.proxy_dispatched"
            ),
            None,
        )
        if proxy_result is None and dispatch_event is None:
            return None
        task = self.queue.get(task_id)
        details = dispatch_event.details if dispatch_event is not None else {}
        return {
            "strategy": "proxy",
            "status": task.status,
            "remote_task_id": (
                str(proxy_result.get("remote_task_id"))
                if proxy_result and proxy_result.get("remote_task_id") is not None
                else None
            ),
            "remote_endpoint_id": (
                str(proxy_result.get("remote_endpoint_id"))
                if proxy_result and proxy_result.get("remote_endpoint_id") is not None
                else details.get("remote_endpoint_id")
            ),
            "remote_node_id": (
                str(proxy_result.get("remote_node_id"))
                if proxy_result and proxy_result.get("remote_node_id") is not None
                else details.get("remote_node_id")
            ),
            "source_base_url": (
                str(proxy_result.get("source_base_url"))
                if proxy_result and proxy_result.get("source_base_url") is not None
                else details.get("source_base_url")
            ),
            "dispatched_at": dispatch_event.timestamp if dispatch_event is not None else None,
        }

    def event_journal(self, *, limit: int | None = None) -> list[JournalEvent]:
        events = list(self._events)
        if limit is None or limit >= len(events):
            return events
        return events[-limit:]

    def list_wallet_usage_events(self, *, limit: int | None = None) -> list[dict]:
        events = list(self._wallet_usage_events)
        if limit is None or limit >= len(events):
            return events
        return events[-limit:]

    def list_wallet_session_events(self, *, limit: int | None = None) -> list[dict]:
        events = list(self._wallet_session_events)
        if limit is None or limit >= len(events):
            return events
        return events[-limit:]

    def list_wallet_allocation_events(self, *, limit: int | None = None) -> list[dict]:
        self._reconcile_wallet_allocation_events()
        events = list(self._wallet_allocation_events)
        if limit is None or limit >= len(events):
            return events
        return events[-limit:]

    def list_wallet_allocation_activation_events(
        self, *, limit: int | None = None
    ) -> list[dict]:
        events = list(self._wallet_allocation_activation_events)
        if limit is None or limit >= len(events):
            return events
        return events[-limit:]

    def list_wallet_allocation_dispute_events(
        self, *, limit: int | None = None
    ) -> list[dict]:
        events = list(self._wallet_allocation_dispute_events)
        if limit is None or limit >= len(events):
            return events
        return events[-limit:]

    def export_wallet_usage_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._export_wallet_event_stream(
            self._wallet_usage_events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_session_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._export_wallet_event_stream(
            self._wallet_session_events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_allocation_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        self._reconcile_wallet_allocation_events()
        return self._export_wallet_event_stream(
            self._wallet_allocation_events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_allocation_activation_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._export_wallet_event_stream(
            self._wallet_allocation_activation_events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def export_wallet_allocation_dispute_events(
        self,
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        return self._export_wallet_event_stream(
            self._wallet_allocation_dispute_events,
            after_event_id=after_event_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def reopen_wallet_allocation_event(
        self, event_id: str, *, reason: str | None = None
    ) -> dict:
        self._reconcile_wallet_allocation_events()
        event = next(
            (
                item
                for item in self._wallet_allocation_events
                if item["event_id"] == event_id
            ),
            None,
        )
        if event is None:
            raise KeyError(event_id)
        if event.get("settlement_status") != "closed":
            raise ValueError(f"Wallet allocation event is not closed: {event_id}")
        if event.get("dispute_status") == "open":
            raise ValueError(f"Wallet allocation event is disputed: {event_id}")

        current_time = time.time()
        timestamp = datetime.fromtimestamp(current_time, timezone.utc).isoformat()
        normalized_reason = reason.strip() if isinstance(reason, str) else None
        closed_immediately = self.wallet_allocation_grace_period_seconds == 0
        event["settlement_status"] = "closed" if closed_immediately else "grace"
        event["grace_expires_at"] = (
            None
            if closed_immediately
            else datetime.fromtimestamp(
                current_time + self.wallet_allocation_grace_period_seconds,
                timezone.utc,
            ).isoformat()
        )
        event["closed_at"] = timestamp if closed_immediately else None
        event["reopened_at"] = timestamp
        event["reopen_reason"] = normalized_reason or None
        event["reopen_count"] = int(event.get("reopen_count", 0)) + 1
        self.record_event(
            event_type="wallet.allocation_reopened",
            message="wallet allocation settlement reopened",
            bundle_id=event["bundle_id"],
            details={
                "event_id": event["event_id"],
                "sequence_id": event["sequence_id"],
                "allocation_id": event["allocation_id"],
                "owner_id": event["owner_id"],
                "reopen_count": event["reopen_count"],
                "reopen_reason": event["reopen_reason"],
                "settlement_status": event["settlement_status"],
            },
        )
        self._persist_state()
        return dict(event)

    def dispute_wallet_allocation_event(self, event_id: str, *, reason: str) -> dict:
        self._reconcile_wallet_allocation_events()
        event = next(
            (
                item
                for item in self._wallet_allocation_events
                if item["event_id"] == event_id
            ),
            None,
        )
        if event is None:
            raise KeyError(event_id)
        if event.get("dispute_status") == "open":
            raise ValueError(f"Wallet allocation event is already disputed: {event_id}")

        timestamp = datetime.fromtimestamp(time.time(), timezone.utc).isoformat()
        dispute_id = str(uuid4())
        event["dispute_id"] = dispute_id
        event["dispute_opened_at"] = timestamp
        event["dispute_reason"] = reason
        event["dispute_status"] = "open"
        event["dispute_opened_by"] = self.operator_id
        event["dispute_resolved_at"] = None
        event["dispute_resolution"] = None
        event["dispute_resolution_reason"] = None
        self._wallet_allocation_dispute_events.append(
            WalletAllocationDisputeEvent(
                sequence_id=self._next_wallet_allocation_dispute_sequence,
                event_id=str(uuid4()),
                dispute_id=dispute_id,
                allocation_event_id=event["event_id"],
                allocation_id=event["allocation_id"],
                owner_id=event["owner_id"],
                node_id=self.node_id,
                operator_id=self.operator_id,
                bundle_id=event["bundle_id"],
                workload_type=event["workload_type"],
                event_type="opened",
                occurred_at=timestamp,
                reason=reason,
                opened_by=self.operator_id,
            ).model_dump(mode="json")
        )
        self._next_wallet_allocation_dispute_sequence += 1
        self.record_event(
            event_type="wallet.allocation_disputed",
            message="wallet allocation settlement disputed",
            bundle_id=event["bundle_id"],
            details={
                "event_id": event["event_id"],
                "sequence_id": event["sequence_id"],
                "dispute_id": dispute_id,
                "allocation_id": event["allocation_id"],
                "owner_id": event["owner_id"],
                "dispute_reason": event["dispute_reason"],
                "settlement_status": event["settlement_status"],
                "dispute_status": event["dispute_status"],
            },
        )
        self._persist_state()
        return dict(event)

    def resolve_wallet_allocation_dispute(
        self,
        event_id: str,
        *,
        resolution: str,
        reason: str | None = None,
    ) -> dict:
        self._reconcile_wallet_allocation_events()
        event = next(
            (
                item
                for item in self._wallet_allocation_events
                if item["event_id"] == event_id
            ),
            None,
        )
        if event is None:
            raise KeyError(event_id)
        if event.get("dispute_status") != "open":
            raise ValueError(f"Wallet allocation event is not disputed: {event_id}")

        current_time = time.time()
        timestamp = datetime.fromtimestamp(current_time, timezone.utc).isoformat()
        normalized_reason = reason.strip() if isinstance(reason, str) else None
        event["dispute_status"] = "resolved"
        event["dispute_resolved_at"] = timestamp
        event["dispute_resolution"] = resolution
        event["dispute_resolution_reason"] = normalized_reason or None
        if resolution == "accepted":
            closed_immediately = self.wallet_allocation_grace_period_seconds == 0
            event["settlement_status"] = "closed" if closed_immediately else "grace"
            event["grace_expires_at"] = (
                None
                if closed_immediately
                else datetime.fromtimestamp(
                    current_time + self.wallet_allocation_grace_period_seconds,
                    timezone.utc,
                ).isoformat()
            )
            event["closed_at"] = timestamp if closed_immediately else None
            event["reopened_at"] = timestamp
            event["reopen_reason"] = normalized_reason or event.get("dispute_reason")
            event["reopen_count"] = int(event.get("reopen_count", 0)) + 1
        elif resolution in {"rejected", "withdrawn"}:
            event["settlement_status"] = "closed"
            event["grace_expires_at"] = None
            event["closed_at"] = timestamp
        else:
            raise ValueError(f"Unsupported dispute resolution: {resolution}")
        self._wallet_allocation_dispute_events.append(
            WalletAllocationDisputeEvent(
                sequence_id=self._next_wallet_allocation_dispute_sequence,
                event_id=str(uuid4()),
                dispute_id=str(event["dispute_id"]),
                allocation_event_id=event["event_id"],
                allocation_id=event["allocation_id"],
                owner_id=event["owner_id"],
                node_id=self.node_id,
                operator_id=self.operator_id,
                bundle_id=event["bundle_id"],
                workload_type=event["workload_type"],
                event_type="resolved",
                occurred_at=timestamp,
                resolution=resolution,
                resolution_reason=normalized_reason or None,
            ).model_dump(mode="json")
        )
        self._next_wallet_allocation_dispute_sequence += 1
        self.record_event(
            event_type="wallet.allocation_dispute_resolved",
            message="wallet allocation dispute resolved",
            bundle_id=event["bundle_id"],
            details={
                "event_id": event["event_id"],
                "sequence_id": event["sequence_id"],
                "dispute_id": event["dispute_id"],
                "allocation_id": event["allocation_id"],
                "owner_id": event["owner_id"],
                "dispute_resolution": event["dispute_resolution"],
                "dispute_resolution_reason": event["dispute_resolution_reason"],
                "settlement_status": event["settlement_status"],
            },
        )
        self._persist_state()
        return dict(event)

    def _export_wallet_event_stream(
        self,
        events: list[dict],
        *,
        after_event_id: str | None = None,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict:
        events = list(events)
        retained_from_sequence = events[0]["sequence_id"] if events else None
        retained_through_sequence = events[-1]["sequence_id"] if events else None
        cursor_status = "ok"
        start_index = 0

        if after_sequence is not None:
            if (
                retained_from_sequence is not None
                and after_sequence < retained_from_sequence - 1
            ):
                cursor_status = "stale"
            else:
                start_index = len(events)
                for index, event in enumerate(events):
                    if event["sequence_id"] > after_sequence:
                        start_index = index
                        break
        elif after_event_id is not None:
            start_index = len(events)
            found = False
            for index, event in enumerate(events):
                if event["event_id"] == after_event_id:
                    start_index = index + 1
                    found = True
                    break
            if not found and events:
                cursor_status = "stale"
                start_index = 0

        items = events[start_index : start_index + limit]
        has_more = start_index + limit < len(events)
        return {
            "items": items,
            "next_after_event_id": items[-1]["event_id"] if items else after_event_id,
            "next_after_sequence": items[-1]["sequence_id"] if items else after_sequence,
            "retained_from_sequence": retained_from_sequence,
            "retained_through_sequence": retained_through_sequence,
            "watermark_sequence": retained_through_sequence,
            "has_more": has_more,
            "cursor_status": cursor_status,
        }

    def task_history(self, task_id: str) -> list[JournalEvent]:
        return [event for event in self._events if event.task_id == task_id]

    def quote_wallet_usage(
        self,
        *,
        input_tokens: int,
        output_tokens: int,
        fixed_request_count: int = 1,
    ) -> dict:
        return quote_usage_q(
            pricing=self._pricing,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            fixed_request_count=fixed_request_count,
        )

    def record_wallet_usage(
        self,
        *,
        owner_id: str,
        bundle_id: str,
        workload_type: str,
        task_id: str | None = None,
        allocation_id: str | None = None,
        input_tokens: int,
        output_tokens: int,
        fixed_request_count: int = 1,
        measurement_kind: str = "exact",
        measurement_source: str = "manual",
        source: str = "manual",
    ) -> dict:
        event = WalletUsageEvent(
            sequence_id=self._next_wallet_usage_sequence,
            event_id=str(uuid4()),
            owner_id=owner_id,
            node_id=self.node_id,
            operator_id=self.operator_id,
            task_id=task_id,
            allocation_id=allocation_id,
            bundle_id=bundle_id,
            workload_type=workload_type,
            measurement_kind=measurement_kind,
            measurement_source=measurement_source,
            source=source,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            quote=self.quote_wallet_usage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                fixed_request_count=fixed_request_count,
            ),
        )
        payload = event.model_dump(mode="json")
        self._wallet_usage_events.append(payload)
        self._next_wallet_usage_sequence += 1
        self._prune_wallet_usage_events()
        self.record_event(
            event_type="wallet.usage_recorded",
            message="wallet usage event recorded",
            bundle_id=bundle_id,
            details={
                "sequence_id": payload["sequence_id"],
                "event_id": payload["event_id"],
                "owner_id": owner_id,
                "source": source,
                "measurement_kind": measurement_kind,
                "measurement_source": measurement_source,
                "task_id": task_id,
                "total_q": payload["quote"]["charges"]["total_q"],
            },
        )
        self._persist_state()
        return payload

    def _record_wallet_allocation_event(self, allocation: dict, *, status: str) -> dict:
        request = allocation["request"]
        matching_usage_events = [
            event
            for event in self._wallet_usage_events
            if event.get("allocation_id") == allocation["allocation_id"]
        ]
        closed_immediately = self.wallet_allocation_grace_period_seconds == 0
        current_time = time.time()
        event = WalletAllocationEvent(
            sequence_id=self._next_wallet_allocation_sequence,
            event_id=str(uuid4()),
            allocation_id=str(allocation["allocation_id"]),
            owner_id=str(request["owner_id"]),
            node_id=self.node_id,
            operator_id=self.operator_id,
            bundle_id=str(allocation["bundle_id"]),
            workload_type=str(allocation["workload_type"]),
            status=status,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            settlement_status="closed" if closed_immediately else "grace",
            grace_expires_at=(
                None
                if closed_immediately
                else datetime.fromtimestamp(
                    current_time + self.wallet_allocation_grace_period_seconds,
                    timezone.utc,
                ).isoformat()
            ),
            closed_at=(
                datetime.fromtimestamp(current_time, timezone.utc).isoformat()
                if closed_immediately
                else None
            ),
            reopened_at=None,
            reopen_reason=None,
            reopen_count=0,
            dispute_id=None,
            dispute_opened_at=None,
            dispute_reason=None,
            dispute_status="none",
            dispute_opened_by=None,
            dispute_resolved_at=None,
            dispute_resolution=None,
            dispute_resolution_reason=None,
            usage_event_count=len(matching_usage_events),
            usage_total_q=sum(
                float(item["quote"]["charges"]["total_q"])
                for item in matching_usage_events
            ),
        )
        payload = event.model_dump(mode="json")
        self._wallet_allocation_events.append(payload)
        self._next_wallet_allocation_sequence += 1
        self.record_event(
            event_type="wallet.allocation_finalized",
            message="wallet allocation finalization recorded",
            bundle_id=str(allocation["bundle_id"]),
            runtime_id=allocation.get("runtime_id"),
            details={
                "event_id": payload["event_id"],
                "sequence_id": payload["sequence_id"],
                "allocation_id": payload["allocation_id"],
                "owner_id": payload["owner_id"],
                "status": payload["status"],
                "settlement_status": payload["settlement_status"],
                "usage_event_count": payload["usage_event_count"],
                "usage_total_q": payload["usage_total_q"],
            },
        )
        return payload

    def _record_wallet_allocation_activation_hook(
        self, allocation: dict, *, activation_source: str
    ) -> None:
        request = allocation["request"]
        event = WalletAllocationActivationEvent(
            sequence_id=self._next_wallet_allocation_activation_sequence,
            event_id=str(uuid4()),
            allocation_id=allocation["allocation_id"],
            owner_id=request["owner_id"],
            node_id=self.node_id,
            operator_id=self.operator_id,
            bundle_id=allocation["bundle_id"],
            workload_type=allocation["workload_type"],
            runtime_id=allocation.get("runtime_id"),
            endpoint=allocation.get("endpoint"),
            activation_source=activation_source,
            lease_seconds=request["lease_seconds"],
            occurred_at=datetime.now(timezone.utc).isoformat(),
        )
        payload = event.model_dump(mode="json")
        self._wallet_allocation_activation_events.append(payload)
        self._next_wallet_allocation_activation_sequence += 1
        self.record_event(
            event_type="wallet.allocation_activated",
            message="wallet allocation activation recorded",
            bundle_id=allocation["bundle_id"],
            runtime_id=allocation.get("runtime_id"),
            details={
                "sequence_id": payload["sequence_id"],
                "event_id": payload["event_id"],
                "activation_source": payload["activation_source"],
                "allocation_id": payload["allocation_id"],
                "owner_id": payload["owner_id"],
                "bundle_id": payload["bundle_id"],
                "workload_type": payload["workload_type"],
                "runtime_id": payload["runtime_id"],
                "endpoint": payload["endpoint"],
                "lease_seconds": payload["lease_seconds"],
            },
        )

    def _reconcile_wallet_allocation_events(self) -> None:
        changed = False
        current_time = time.time()
        for event in self._wallet_allocation_events:
            dispute_open = event.get("dispute_status") == "open"
            if event.get("settlement_status") == "closed" and not dispute_open:
                continue

            matching_usage_events = [
                usage_event
                for usage_event in self._wallet_usage_events
                if usage_event.get("allocation_id") == event["allocation_id"]
            ]
            next_usage_event_count = len(matching_usage_events)
            next_usage_total_q = sum(
                float(item["quote"]["charges"]["total_q"])
                for item in matching_usage_events
            )
            if event["usage_event_count"] != next_usage_event_count:
                event["usage_event_count"] = next_usage_event_count
                changed = True
            if event["usage_total_q"] != next_usage_total_q:
                event["usage_total_q"] = next_usage_total_q
                changed = True

            if dispute_open:
                continue

            grace_expires_at = event.get("grace_expires_at")
            if grace_expires_at is None:
                continue
            try:
                expires_at_ts = datetime.fromisoformat(grace_expires_at).timestamp()
            except ValueError:
                expires_at_ts = current_time
            if expires_at_ts > current_time:
                continue
            event["settlement_status"] = "closed"
            event["closed_at"] = datetime.fromtimestamp(
                current_time, timezone.utc
            ).isoformat()
            changed = True

        if changed:
            self._persist_state()

    def list_allocations(self) -> list[dict]:
        self._cleanup_expired_allocations()
        self._reconcile_pending_allocations()
        return [self._public_allocation(allocation) for allocation in self._allocations.values()]

    def get_allocation(self, allocation_id: str) -> dict:
        self._cleanup_expired_allocations()
        self._reconcile_pending_allocations()
        return self._public_allocation(self._allocations[allocation_id])

    def reconcile_allocation(self, allocation_id: str) -> dict:
        self._cleanup_expired_allocations()
        self._reconcile_pending_allocations()
        return self.get_allocation(allocation_id)

    def create_allocation(self, request: AllocationRequest) -> dict:
        self._cleanup_expired_allocations()
        self._reconcile_pending_allocations()
        bundle = self._select_allocation_bundle(request)
        runtime = self._runtime_for_bundle(bundle.bundle_id)
        unavailability = self._allocation_unavailability(bundle=bundle, runtime=runtime)
        if unavailability is not None:
            if request.policy == "wait" and unavailability["retryable"]:
                owner_quota = self._owner_quota_unavailability(
                    owner_id=request.owner_id,
                    status="pending",
                    bundle_id=bundle.bundle_id,
                )
                if owner_quota is not None:
                    raise AllocationUnavailableError(**owner_quota)
                return self._create_pending_allocation(
                    request=request,
                    bundle=bundle,
                    reason=unavailability["reason"],
                )
            retry_hint = self._allocation_retry_hint(
                bundle_id=bundle.bundle_id,
                reason=str(unavailability["reason"]),
            )
            raise AllocationUnavailableError(
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
        owner_quota = self._owner_quota_unavailability(
            owner_id=request.owner_id,
            status="active",
            bundle_id=bundle.bundle_id,
        )
        if owner_quota is not None:
            raise AllocationUnavailableError(**owner_quota)
        allocation_id = str(uuid4())
        created_at = datetime.fromtimestamp(time.time(), timezone.utc).isoformat()
        expires_at = datetime.fromtimestamp(
            time.time() + request.lease_seconds,
            timezone.utc,
        ).isoformat()
        reservation_id = self._reserve_allocation_residency(
            allocation_id=allocation_id,
            bundle=bundle,
            runtime=runtime,
        )
        if runtime is None:
            runtime = self.start_bundle(bundle.bundle_id)
        allocation = {
            "allocation_id": allocation_id,
            "request": request.model_dump(mode="json"),
            "workload_type": request.workload_type,
            "bundle_id": bundle.bundle_id,
            "runtime_id": runtime.runtime_id,
            "endpoint": self._resolve_runtime_endpoint(bundle, runtime),
            "status": "active",
            "created_at": created_at,
            "expires_at": expires_at,
            "reservation_id": reservation_id,
            "reason": None,
        }
        self._allocations[allocation_id] = allocation
        self._record_wallet_allocation_activation_hook(
            allocation, activation_source="create"
        )
        self.record_event(
            event_type="allocation.created",
            message="allocation created for agent client",
            bundle_id=bundle.bundle_id,
            runtime_id=runtime.runtime_id,
            details={"allocation_id": allocation_id, "workload_type": request.workload_type},
        )
        self._persist_state()
        return self.get_allocation(allocation_id)

    def release_allocation(self, allocation_id: str) -> dict:
        self._cleanup_expired_allocations()
        allocation = self._allocations[allocation_id]
        self._release_allocation_resources(allocation)
        allocation["status"] = "released"
        self._record_wallet_allocation_event(allocation, status="released")
        self.record_event(
            event_type="allocation.released",
            message="allocation released by client",
            bundle_id=allocation["bundle_id"],
            runtime_id=allocation["runtime_id"],
            details={"allocation_id": allocation_id},
        )
        self._persist_state()
        return self.get_allocation(allocation_id)

    def capability_inventory(self) -> list[dict]:
        return [
            {
                "bundle_id": bundle.bundle_id,
                "workload_type": bundle.workload_type,
                "enabled": bundle.enabled,
                "status": self._bundle_inventory_status(bundle),
                "endpoint": bundle.endpoint,
            }
            for bundle in self.bundles
        ]

    def node_advertisement(self, *, heartbeat_at: str | None = None) -> dict:
        timestamp = heartbeat_at or datetime.now(timezone.utc).isoformat()
        resources = (
            self.resources.summary()
            if self.resources is not None
            else _empty_resource_summary()
        )
        publication_service = getattr(self, "endpoint_publication_service", None)
        current_publication_records = []
        if publication_service is not None:
            current_publication_records = [
                record
                for record in publication_service.list_publications()
                if record.status == "published"
            ]
        advertisement = RegistryNodeAdvertisement(
            node_id=self.node_id,
            operator_id=self.operator_id,
            base_url=self.base_url,
            heartbeat_at=timestamp,
            heartbeat_ttl_seconds=self.heartbeat_ttl_seconds,
            status="ready",
            resources=resources,
            providers=sorted({bundle.provider_type for bundle in self.bundles}),
            can_host_custom_model=self.can_host_custom_model,
            pricing=self._pricing,
            rating=self._rating,
            bundles=[
                RegistryBundleAdvertisement(
                    bundle_id=bundle.bundle_id,
                    plugin_id=bundle.plugin_id,
                    workload_type=bundle.workload_type,
                    provider_type=bundle.provider_type,
                    model_id=bundle.model_id,
                    endpoint=bundle.endpoint,
                    enabled=bundle.enabled,
                    status=self._bundle_registry_status(bundle),
                    launch_mode=bundle.launch_mode,
                    device_affinity=bundle.device_affinity,
                    max_parallel_requests=bundle.max_parallel_requests,
                    supports_allocation=True,
                    supports_queue=True,
                )
                for bundle in self.bundles
            ],
            published_endpoints=[
                RegistryPublishedEndpointSummary(
                    endpoint_id=record.endpoint_id,
                    owner_wallet=record.owner_wallet,
                    node_id=record.node_id,
                    current_publication_id=record.publication_id,
                    current_configuration_hash=record.configuration_hash,
                    published_at=record.published_at,
                    status=record.status,
                    visibility=record.publication.get("visibility", "private"),
                    model_class=record.model_class,
                )
                for record in current_publication_records
            ],
        )
        return advertisement.model_dump(mode="json")

    def capability_catalog(
        self,
        *,
        owner_id: str,
        workload_type: str | None = None,
        bundle_id: str | None = None,
        include_disabled: bool = False,
    ) -> dict:
        self._cleanup_expired_allocations()
        self._reconcile_pending_allocations()
        bundles = self._filtered_catalog_bundles(
            workload_type=workload_type,
            bundle_id=bundle_id,
            include_disabled=include_disabled,
        )
        return {
            "node": {
                "node_id": self.node_id,
                "operator_id": self.operator_id,
                "can_host_custom_model": self.can_host_custom_model,
                "pricing": self.pricing,
            },
            "resources": (
                self.resources.summary()
                if self.resources is not None
                else _empty_resource_summary()
            ),
            "bundles": [
                self._catalog_entry(bundle, owner_id=owner_id)
                for bundle in bundles
            ],
        }

    def owner_wallet_state(self) -> dict:
        if self._owner_wallet is None:
            return {
                "configured": False,
                "wallet_id": None,
                "public_key": None,
                "label": None,
                "created_at": None,
                "imported": False,
            }
        return {
            "configured": True,
            "wallet_id": self._owner_wallet["wallet_id"],
            "public_key": self._owner_wallet["public_key"],
            "label": self._owner_wallet.get("label"),
            "created_at": self._owner_wallet["created_at"],
            "imported": bool(self._owner_wallet.get("imported", False)),
        }

    def owner_wallet_private_key(self) -> str:
        if self._owner_wallet is None:
            raise ValueError("Owner wallet is not configured")
        return self._owner_wallet["private_key"]

    def node_identity(self) -> dict:
        owner = self.owner_wallet_state()
        return {
            "node_id": self.node_id,
            "operator_id": self.operator_id,
            "base_url": self.base_url,
            "owner_wallet_id": owner["wallet_id"],
            "ownership_configured": owner["configured"],
            "can_host_custom_model": self.can_host_custom_model,
        }

    def configure_owner_wallet(
        self,
        *,
        mode: str,
        label: str | None = None,
        private_key: str | None = None,
    ) -> dict:
        if mode not in {"create", "import"}:
            raise ValueError(f"Unsupported wallet bootstrap mode: {mode}")
        if mode == "import" and not private_key:
            raise ValueError("Private key is required for wallet import")

        resolved_private_key = private_key or f"sk-{uuid4().hex}{uuid4().hex}"
        digest = hashlib.sha256(resolved_private_key.encode("utf-8")).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()
        self._owner_wallet = {
            "wallet_id": f"wallet-{digest[:12]}",
            "public_key": f"pk-{digest[:24]}",
            "private_key": resolved_private_key,
            "label": label,
            "created_at": created_at,
            "imported": mode == "import",
        }
        self._persist_state()
        return {
            "wallet": self.owner_wallet_state(),
            "private_key": resolved_private_key if mode == "create" else None,
        }

    def operator_dashboard_home(self) -> dict:
        fleet = self.operator_dashboard_fleet()
        enabled_bundles = [bundle for bundle in fleet["bundles"] if bundle["enabled"]]
        pending_installs = [
            install
            for install in fleet["installs"]
            if install["install_status"] in {"pending", "running"}
        ]
        bootstrap = self._operator_dashboard_bootstrap(fleet)
        return {
            "bootstrap": bootstrap,
            "publish": {
                "draft_offer_count": len(fleet["bundles"]),
                "install_pending_count": len(pending_installs),
                "live_offer_count": len(enabled_bundles),
            },
            "market_visibility": {
                "local_offer_count": len(fleet["bundles"]),
                "live_offer_count": len(enabled_bundles),
            },
            "fleet_capacity": {
                "node_count": 1,
                "queued": fleet["queue"]["queued"],
                "active": fleet["queue"]["active"],
                "free": fleet["resources"]["free"],
            },
            "operator_controls": {
                "actions": [
                    "Create Wallet",
                    "Install Model",
                    "Create Endpoint",
                    "Publish Offer",
                    "Attach Endpoint",
                    "Pause Queue",
                    "Raise Limits",
                    "Connect Remote Node",
                ]
            },
        }

    def operator_dashboard_fleet(self) -> dict:
        resources = (
            self.resources.summary()
            if self.resources is not None
            else _empty_resource_summary()
        )
        return {
            "node": {
                "node_id": self.node_id,
                "operator_id": self.operator_id,
                "base_url": self.base_url,
                "can_host_custom_model": self.can_host_custom_model,
                "pricing": self.pricing,
                "rating": self.rating,
            },
            "resources": resources,
            "queue": self.queue_summary(),
            "installs": [
                {
                    "install_id": install["install_id"],
                    "provider_type": install["provider_type"],
                    "model_id": install["model_id"],
                    "requested_by": install["requested_by"],
                    "install_status": self._operator_dashboard_install_status(
                        str(install["status"])
                    ),
                    "bundle_id": install["bundle_id"],
                    "last_error": install["last_error"],
                }
                for install in self.list_model_installs()
            ],
            "bundles": [
                self._operator_dashboard_bundle_entry(bundle)
                for bundle in self.bundles
            ],
            "owner_wallet": self.owner_wallet_state(),
            "node_identity": self.node_identity(),
        }

    def operator_dashboard_endpoints(self) -> dict:
        items: list[dict] = []
        return {
            "owner_wallet": self.owner_wallet_state(),
            "node_identity": self.node_identity(),
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

    def operator_requests_policy(self) -> dict[str, bool | str]:
        return dict(self._operator_requests_policy)

    def update_operator_requests_policy(
        self,
        *,
        allow_spillover: bool,
        dispatch_strategy: str,
        ready_endpoint_only: bool,
    ) -> dict[str, bool | str]:
        if dispatch_strategy not in {"local_first", "balanced", "market_first"}:
            raise ValueError(f"Unsupported dispatch strategy: {dispatch_strategy}")
        self._operator_requests_policy = {
            "allow_spillover": bool(allow_spillover),
            "dispatch_strategy": dispatch_strategy,
            "ready_endpoint_only": bool(ready_endpoint_only),
        }
        self._persist_state()
        return self.operator_requests_policy()

    def operator_dashboard_requests(
        self,
        *,
        market_candidates: list[dict] | None = None,
    ) -> dict:
        tasks = self.queue.snapshot()
        queue = [
            self._operator_dashboard_task_entry(task)
            for task in tasks
            if task.status in {"queued", "admitted", "starting"}
        ]
        active = [
            self._operator_dashboard_task_entry(task)
            for task in tasks
            if task.status == "running"
        ]
        recent = sorted(
            [
                self._operator_dashboard_task_entry(task)
                for task in tasks
                if task.status in {"completed", "failed", "cancelled"}
            ],
            key=lambda item: datetime.fromisoformat(
                item["terminal_at"] or item["created_at"]
            ),
            reverse=True,
        )[:12]
        preview = self._operator_spillover_preview(market_candidates or [])
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
            "admission": self.admission_telemetry(),
            "policy": self.operator_requests_policy(),
            "market_spillover_preview": preview,
        }

    def request_model_install(
        self,
        *,
        provider_type: str,
        model_id: str,
        source_url: str,
        requested_by: str,
    ) -> dict:
        if self.model_store is None:
            raise ValueError("Model store is not configured")
        install_id = str(uuid4())
        target_path = str(self.model_store.reserve_target_path(provider_type, model_id))
        job = {
            "install_id": install_id,
            "provider_type": provider_type,
            "model_id": model_id,
            "source_url": source_url,
            "target_path": target_path,
            "requested_by": requested_by,
            "status": "queued",
            "bundle_id": None,
            "last_error": None,
        }
        self._model_installs[install_id] = job
        self.record_event(
            event_type="model.install.requested",
            message="model install requested by operator",
            details={"install_id": install_id, "provider_type": provider_type},
        )
        self._persist_state()
        return dict(job)

    def list_model_installs(self) -> list[dict]:
        return [dict(job) for job in self._model_installs.values()]

    def process_model_installs(self, *, limit: int | None = None) -> list[dict]:
        if self.model_store is None:
            raise ValueError("Model store is not configured")
        processed: list[dict] = []
        queued_jobs = [
            job for job in self._model_installs.values() if job["status"] == "queued"
        ]
        if limit is not None:
            queued_jobs = queued_jobs[:limit]

        for job in queued_jobs:
            job["status"] = "running"
            job["last_error"] = None
            self.record_event(
                event_type="model.install.started",
                message="model install started",
                details={"install_id": job["install_id"], "provider_type": job["provider_type"]},
            )
            self._persist_state()
            try:
                self.model_store.materialize_artifact(
                    str(job["source_url"]),
                    str(job["target_path"]),
                )
            except Exception as error:
                job["status"] = "failed"
                job["last_error"] = str(error)
                self.record_event(
                    event_type="model.install.failed",
                    message="model install failed",
                    details={"install_id": job["install_id"], "provider_type": job["provider_type"]},
                )
            else:
                job["status"] = "completed"
                job["last_error"] = None
                self.record_event(
                    event_type="model.install.completed",
                    message="model install completed",
                    details={"install_id": job["install_id"], "provider_type": job["provider_type"]},
                )
            self._persist_state()
            processed.append(dict(job))

        return processed

    def mark_model_install_completed(self, install_id: str) -> dict:
        job = self._model_installs[install_id]
        job["status"] = "completed"
        job["last_error"] = None
        self.record_event(
            event_type="model.install.completed",
            message="model install marked completed",
            details={"install_id": install_id},
        )
        self._persist_state()
        return dict(job)

    def register_bundle_from_install(
        self,
        *,
        install_id: str,
        bundle_id: str,
        workload_type: str,
        endpoint: str,
    ) -> dict:
        if any(bundle.bundle_id == bundle_id for bundle in self.bundles):
            raise ValueError(f"Bundle already exists: {bundle_id}")
        job = self._model_installs[install_id]
        if job["status"] != "completed":
            raise ValueError(f"Model install is not completed: {install_id}")

        plugin = self._get_plugin(job["provider_type"])
        defaults = plugin.bundle_defaults_from_install(
            model_id=str(job["model_id"]),
            target_path=str(job["target_path"]),
        )
        bundle = BundleConfig(
            bundle_id=bundle_id,
            plugin_id=plugin.plugin_id,
            provider_type=str(job["provider_type"]),
            workload_type=workload_type,
            model_id=str(defaults["model_id"]),
            launch_mode=str(defaults["launch_mode"]),
            endpoint=endpoint,
            device_affinity=str(defaults["device_affinity"]),
            resource_profile=ResourceProfile(),
            warm_policy="auto",
            priority_class=50,
            max_parallel_requests=1,
            enabled=True,
        )
        plugin.validate_bundle(bundle)
        self.bundles.append(bundle)
        job["status"] = "registered"
        job["bundle_id"] = bundle_id
        self.record_event(
            event_type="bundle.registered_from_install",
            message="bundle registered from installed model artifact",
            bundle_id=bundle.bundle_id,
            details={"install_id": install_id, "provider_type": job["provider_type"]},
        )
        self._persist_bundle_config_if_available()
        self._persist_state()
        return bundle.model_dump(mode="json")

    def get_runtime(self, runtime_id: str) -> RuntimeHandle:
        for runtime in self.list_runtimes():
            if runtime.runtime_id == runtime_id:
                return runtime
        raise KeyError(runtime_id)

    def runtime_history(self, runtime_id: str) -> list[JournalEvent]:
        return [event for event in self._events if event.runtime_id == runtime_id]

    def bundle_state(self, bundle_id: str) -> dict:
        return dict(self._current_bundle_state(bundle_id))

    def record_event(
        self,
        *,
        event_type: str,
        message: str,
        task_id: str | None = None,
        bundle_id: str | None = None,
        runtime_id: str | None = None,
        details: dict | None = None,
    ) -> JournalEvent:
        event = JournalEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type=event_type,
            message=message,
            task_id=task_id,
            bundle_id=bundle_id,
            runtime_id=runtime_id,
            details=dict(details or {}),
        )
        self._events.append(event)
        if self._record_wallet_session_event_from_journal(event):
            self._persist_state()
        return event

    def _record_wallet_session_event_from_journal(self, event: JournalEvent) -> bool:
        event_type_map = {
            "session.deposit_locked": "deposit_locked",
            "session.usage_charged": "usage_charged",
            "session.settled": "settled",
        }
        normalized_type = event_type_map.get(event.event_type)
        if normalized_type is None:
            return False
        session_id = event.details.get("session_id")
        endpoint_id = event.details.get("endpoint_id")
        if session_id is None or endpoint_id is None:
            return False
        session_result = None
        session_service = getattr(self, "session_service", None)
        if session_service is not None:
            try:
                session_result = session_service.get_session(str(session_id))
            except KeyError:
                session_result = None
        session = session_result.session if session_result is not None else None
        deposit = session_result.deposit if session_result is not None else None
        locked_q = float(
            event.details.get(
                "locked_q",
                deposit.locked_q if deposit is not None else 0.0,
            )
        )
        usage_charged_q = float(
            event.details.get(
                "usage_charged_q",
                deposit.consumed_q if deposit is not None else 0.0,
            )
        )
        charged_q = float(
            event.details.get(
                "charged_q",
                event.details.get(
                    "amount_q",
                    deposit.consumed_q if deposit is not None else 0.0,
                ),
            )
        )
        refunded_q = float(
            event.details.get(
                "refunded_q",
                deposit.refunded_q if deposit is not None else 0.0,
            )
        )
        remaining_q = float(
            event.details.get(
                "remaining_q",
                max(0.0, locked_q - (deposit.consumed_q if deposit is not None else charged_q)),
            )
        )
        session_event = WalletSessionEvent(
            sequence_id=self._next_wallet_session_sequence,
            event_id=str(uuid4()),
            session_id=str(session_id),
            endpoint_id=str(endpoint_id),
            owner_id=str(
                event.details.get(
                    "client_wallet",
                    session.client_wallet if session is not None else "",
                )
            ),
            provider_wallet=str(
                event.details.get(
                    "provider_wallet",
                    session.provider_wallet if session is not None else "",
                )
            ),
            node_id=self.node_id,
            operator_id=self.operator_id,
            event_type=normalized_type,
            occurred_at=event.timestamp,
            task_id=event.task_id,
            status=str(
                event.details.get(
                    "status",
                    session.status if session is not None else "unknown",
                )
            ),
            settlement_status="closed" if normalized_type == "settled" else "open",
            locked_q=locked_q,
            charged_q=charged_q,
            refunded_q=refunded_q,
            remaining_q=remaining_q,
            usage_charged_q=usage_charged_q,
            idle_fee_charged_q=float(event.details.get("idle_fee_charged_q", 0.0)),
            minimum_session_fee_q=float(
                event.details.get("minimum_session_fee_q", 0.0)
            ),
            close_reason=(
                str(event.details["close_reason"])
                if event.details.get("close_reason") is not None
                else None
            ),
        ).model_dump(mode="json")
        self._wallet_session_events.append(session_event)
        self._next_wallet_session_sequence += 1
        return True

    def snapshot_state(self) -> HypervisorStateSnapshot:
        return HypervisorStateSnapshot(
            tasks=[
                TaskSnapshot(
                    task_id=task.task_id,
                    priority=task.priority,
                    enqueue_index=task.enqueue_index,
                    created_at=task.created_at,
                    status=task.status,
                    request=task.request.model_copy(deep=True),
                    bundle_id=self.selected_bundle_id(task.task_id),
                    result=self._task_results.get(task.task_id),
                    recovery_reason=self.task_recovery_reason(task.task_id),
                )
                for task in self.queue.snapshot()
            ],
            runtimes=[
                RuntimeSnapshot(
                    runtime_id=runtime.runtime_id,
                    command=list(runtime.command),
                    status=runtime.status,
                    bundle_id=runtime.bundle_id,
                    health_status=runtime.health_status,
                    last_error=runtime.last_error,
                    metadata=dict(runtime.metadata),
                )
                for runtime in self.list_runtimes()
            ],
            bundle_states=[
                BundleStateSnapshot(**self._current_bundle_state(bundle.bundle_id))
                for bundle in self.bundles
                if self._bundle_state_is_non_default(bundle.bundle_id)
            ],
            allocations=[
                AllocationSnapshot(
                    allocation_id=allocation["allocation_id"],
                    request=AllocationRequest(**allocation["request"]),
                    bundle_id=allocation["bundle_id"],
                    runtime_id=allocation["runtime_id"],
                    endpoint=allocation["endpoint"],
                    status=allocation["status"],
                    created_at=allocation["created_at"],
                    expires_at=allocation["expires_at"],
                    reservation_id=allocation.get("reservation_id"),
                    reason=allocation.get("reason"),
                )
                for allocation in self._allocations.values()
            ],
            model_installs=[
                ModelInstallSnapshot(**job)
                for job in self._model_installs.values()
            ],
            operator_requests_policy=dict(self._operator_requests_policy),
            owner_wallet=(
                OwnerWalletSnapshot(**self._owner_wallet)
                if self._owner_wallet is not None
                else None
            ),
            wallet_usage_events=[
                WalletUsageSnapshot(**event)
                for event in self._wallet_usage_events
            ],
            wallet_session_events=[
                WalletSessionSnapshot(**event)
                for event in self._wallet_session_events
            ],
            wallet_allocation_activation_events=[
                WalletAllocationActivationSnapshot(**event)
                for event in self._wallet_allocation_activation_events
            ],
            wallet_allocation_dispute_events=[
                WalletAllocationDisputeSnapshot(**event)
                for event in self._wallet_allocation_dispute_events
            ],
            wallet_allocation_events=[
                WalletAllocationSnapshot(**event)
                for event in self._wallet_allocation_events
            ],
            events=[event.model_copy(deep=True) for event in self._events],
        )

    def restore_state(self, snapshot: HypervisorStateSnapshot) -> dict[str, int]:
        self._selected_bundles = {}
        self._task_results = {}
        self._task_recovery_reasons = {}
        self._allocations = {}
        self._model_installs = {}
        self._operator_requests_policy = dict(snapshot.operator_requests_policy)
        self._owner_wallet = (
            snapshot.owner_wallet.model_dump(mode="json")
            if snapshot.owner_wallet is not None
            else None
        )
        self._wallet_usage_events = []
        self._wallet_session_events = []
        self._wallet_allocation_activation_events = []
        self._wallet_allocation_dispute_events = []
        self._wallet_allocation_events = []
        self._bundle_states = {
            state.bundle_id: state.model_dump(mode="json")
            for state in snapshot.bundle_states
        }
        self._events = [event.model_copy(deep=True) for event in snapshot.events]
        for allocation in snapshot.allocations:
            self._allocations[allocation.allocation_id] = {
                "allocation_id": allocation.allocation_id,
                "request": allocation.request.model_dump(mode="json"),
                "workload_type": allocation.request.workload_type,
                "bundle_id": allocation.bundle_id,
                "runtime_id": allocation.runtime_id,
                "endpoint": allocation.endpoint,
                "status": allocation.status,
                "created_at": allocation.created_at,
                "expires_at": allocation.expires_at,
                "reservation_id": allocation.reservation_id,
                "reason": allocation.reason,
            }
        for job in snapshot.model_installs:
            self._model_installs[job.install_id] = job.model_dump(mode="json")
        self._wallet_usage_events = [
            event.model_dump(mode="json") for event in snapshot.wallet_usage_events
        ]
        self._next_wallet_usage_sequence = (
            max((event["sequence_id"] for event in self._wallet_usage_events), default=0)
            + 1
        )
        self._wallet_session_events = [
            event.model_dump(mode="json") for event in snapshot.wallet_session_events
        ]
        self._next_wallet_session_sequence = (
            max(
                (event["sequence_id"] for event in self._wallet_session_events),
                default=0,
            )
            + 1
        )
        self._wallet_allocation_activation_events = [
            event.model_dump(mode="json")
            for event in snapshot.wallet_allocation_activation_events
        ]
        self._next_wallet_allocation_activation_sequence = (
            max(
                (
                    event["sequence_id"]
                    for event in self._wallet_allocation_activation_events
                ),
                default=0,
            )
            + 1
        )
        self._wallet_allocation_dispute_events = [
            event.model_dump(mode="json")
            for event in snapshot.wallet_allocation_dispute_events
        ]
        self._next_wallet_allocation_dispute_sequence = (
            max(
                (
                    event["sequence_id"]
                    for event in self._wallet_allocation_dispute_events
                ),
                default=0,
            )
            + 1
        )
        self._wallet_allocation_events = [
            event.model_dump(mode="json")
            for event in snapshot.wallet_allocation_events
        ]
        self._next_wallet_allocation_sequence = (
            max(
                (event["sequence_id"] for event in self._wallet_allocation_events),
                default=0,
            )
            + 1
        )

        restored_tasks: list[QueuedTask] = []
        for task in snapshot.tasks:
            restored_status = self._restored_task_status(task)
            restored_tasks.append(
                QueuedTask(
                    priority=task.priority,
                    enqueue_index=task.enqueue_index,
                    created_at=task.created_at,
                    task_id=task.task_id,
                    request=task.request.model_copy(deep=True),
                    status=restored_status,
                )
            )
            if task.bundle_id is not None:
                self._selected_bundles[task.task_id] = task.bundle_id
            if task.recovery_reason is not None:
                self._task_recovery_reasons[task.task_id] = task.recovery_reason
            if task.status in _ACTIVE_EXECUTION_STATUSES:
                recovery_reason = self._recovery_reason_for_task(task)
                self._task_recovery_reasons[task.task_id] = recovery_reason
                self.record_event(
                    event_type="task.recovered",
                    message=self._recovery_message(recovery_reason),
                    task_id=task.task_id,
                    bundle_id=task.bundle_id,
                    details={
                        "previous_status": task.status,
                        "restored_status": restored_status,
                        "recovery_reason": recovery_reason,
                    },
                )
            if restored_status == "completed" and task.result is not None:
                self._task_results[task.task_id] = dict(task.result)

        self.queue.restore(restored_tasks)
        self._restore_runtimes(snapshot.runtimes)
        summary = self.queue_summary()
        self._persist_state()
        return summary

    def get_task(self, task_id: str):
        return self.queue.get(task_id)

    def bundle_config(self) -> list[BundleConfig]:
        return [bundle.model_copy(deep=True) for bundle in self.bundles]

    def replace_bundle_config(self, bundles: list[BundleConfig]) -> int:
        registry = self._require_bundle_registry()
        self._validate_bundles(bundles)
        registry.save(bundles)
        self.bundles = [bundle.model_copy(deep=True) for bundle in bundles]
        self.record_event(
            event_type="bundles.replaced",
            message="bundle configuration replaced by operator",
            details={"bundle_count": len(self.bundles)},
        )
        self._persist_state()
        return len(self.bundles)

    def reload_bundle_config(self) -> int:
        registry = self._require_bundle_registry()
        self.bundles = registry.load(self.plugins)
        self.record_event(
            event_type="bundles.reloaded",
            message="bundle configuration reloaded from registry",
            details={"bundle_count": len(self.bundles)},
        )
        self._persist_state()
        return len(self.bundles)

    def reset_bundle_cooldown(self, bundle_id: str) -> dict:
        bundle = self._get_bundle(bundle_id)
        runtime = self._runtime_for_bundle(bundle.bundle_id)
        self._set_bundle_state(
            bundle.bundle_id,
            failure_streak=0,
            cooldown_until=None,
            cooldown_reason=None,
            drain_mode=self._current_bundle_state(bundle.bundle_id)["drain_mode"],
            drain_reason=self._current_bundle_state(bundle.bundle_id)["drain_reason"],
        )
        if runtime is not None and runtime.health_status == "cooldown":
            runtime.health_status = "healthy"
            runtime.last_error = None
        self.record_event(
            event_type="bundle.cooldown_reset",
            message="bundle cooldown reset by operator",
            bundle_id=bundle.bundle_id,
            runtime_id=runtime.runtime_id if runtime is not None else None,
        )
        self._persist_state()
        return {
            "bundle_id": bundle.bundle_id,
            "status": "ready",
            "cooldown_until": None,
            "cooldown_reason": None,
            "failure_streak": 0,
        }

    def retry_bundle(self, bundle_id: str) -> dict[str, int]:
        self.reset_bundle_cooldown(bundle_id)
        self.record_event(
            event_type="bundle.retry_requested",
            message="bundle retry requested by operator",
            bundle_id=bundle_id,
        )
        return self.process_pending()

    def set_bundle_enabled(self, bundle_id: str, enabled: bool) -> dict[str, str | bool]:
        bundle = self._get_bundle(bundle_id)
        self._replace_bundle(
            bundle.model_copy(update={"enabled": enabled})
        )
        self._persist_bundle_config_if_available()
        self.record_event(
            event_type="bundle.enabled" if enabled else "bundle.disabled",
            message=(
                "bundle enabled by operator"
                if enabled
                else "bundle disabled by operator"
            ),
            bundle_id=bundle_id,
        )
        self._persist_state()
        return {
            "bundle_id": bundle_id,
            "enabled": enabled,
            "status": "enabled" if enabled else "disabled",
        }

    def drain_runtime(self, runtime_id: str) -> dict[str, str | bool]:
        runtime = self.get_runtime(runtime_id)
        bundle_id = runtime.bundle_id
        if bundle_id is None:
            raise KeyError(runtime_id)
        state = self._current_bundle_state(bundle_id)
        self._set_bundle_state(
            bundle_id,
            failure_streak=state["failure_streak"],
            cooldown_until=state["cooldown_until"],
            cooldown_reason=state["cooldown_reason"],
            drain_mode=True,
            drain_reason="operator_requested",
        )
        self.record_event(
            event_type="runtime.draining",
            message="runtime drain requested by operator",
            bundle_id=bundle_id,
            runtime_id=runtime_id,
        )
        self._persist_state()
        return {
            "runtime_id": runtime_id,
            "bundle_id": bundle_id,
            "drain_mode": True,
            "status": "draining",
        }

    def force_stop_runtime(self, runtime_id: str) -> dict[str, str]:
        runtime = self.get_runtime(runtime_id)
        bundle_id = runtime.bundle_id
        if bundle_id is None:
            raise KeyError(runtime_id)
        bundle = self._get_bundle(bundle_id)
        self._stop_runtime_for_bundle(bundle)
        self.record_event(
            event_type="runtime.force_stopped",
            message="runtime force-stopped by operator",
            bundle_id=bundle_id,
            runtime_id=runtime_id,
        )
        self._persist_state()
        return {
            "runtime_id": runtime_id,
            "bundle_id": bundle_id,
            "status": "force_stopped",
        }

    def restart_runtime(self, runtime_id: str) -> dict[str, str]:
        runtime = self.get_runtime(runtime_id)
        bundle_id = runtime.bundle_id
        if bundle_id is None:
            raise KeyError(runtime_id)
        bundle = self._get_bundle(bundle_id)
        if not bundle.enabled:
            raise ValueError(f"Bundle is disabled: {bundle_id}")
        if self._bundle_in_cooldown(bundle_id):
            raise ValueError(f"Bundle is in cooldown: {bundle_id}")

        state = self._current_bundle_state(bundle_id)
        self._set_bundle_state(
            bundle_id,
            failure_streak=state["failure_streak"],
            cooldown_until=state["cooldown_until"],
            cooldown_reason=state["cooldown_reason"],
            drain_mode=False,
            drain_reason=None,
        )
        self._stop_runtime_for_bundle(bundle)
        restarted = self.start_bundle(bundle_id)
        self.record_event(
            event_type="runtime.restarted",
            message="runtime restarted by operator",
            bundle_id=bundle_id,
            runtime_id=restarted.runtime_id,
        )
        self.process_pending()
        return {
            "runtime_id": restarted.runtime_id,
            "bundle_id": bundle_id,
            "status": "restarted",
        }

    def cancel_task(self, task_id: str):
        task = self.queue.get(task_id)
        if task.status not in _CANCELLABLE_TASK_STATUSES:
            raise ValueError(f"Task is not cancellable: {task_id}")
        cancelled_task = self.queue.transition_status(task_id, "cancelled")
        self.record_event(
            event_type="task.cancelled",
            message="task cancelled before execution",
            task_id=task_id,
            bundle_id=self.selected_bundle_id(task_id),
        )
        self.process_pending()
        return cancelled_task

    def start_bundle(self, bundle_id: str) -> RuntimeHandle:
        bundle = self._get_bundle(bundle_id)
        if not bundle.enabled:
            raise ValueError(f"Bundle is disabled: {bundle_id}")
        if self._runtime_for_bundle(bundle_id) is not None:
            raise ValueError(f"Bundle already has an active runtime: {bundle_id}")

        plugin = self._get_plugin(bundle.plugin_id)
        launch_spec = dict(plugin.build_launch_spec(bundle))
        launch_spec["bundle_id"] = bundle.bundle_id
        launch_spec["launch_mode"] = bundle.launch_mode

        if hasattr(self.runtimes, "start_runtime"):
            runtime = self.runtimes.start_runtime(launch_spec)
            self.record_event(
                event_type="runtime.started",
                message="runtime started",
                bundle_id=bundle.bundle_id,
                runtime_id=runtime.runtime_id,
            )
            self._persist_state()
            return runtime

        handle = RuntimeHandle(
            runtime_id=f"rt-{len(self.runtimes) + 1}",
            command=launch_spec["command"],
            status="starting",
            bundle_id=bundle.bundle_id,
            metadata=dict(launch_spec.get("metadata", {})),
        )
        self.runtimes.append(handle)
        self.record_event(
            event_type="runtime.started",
            message="runtime started",
            bundle_id=bundle.bundle_id,
            runtime_id=handle.runtime_id,
        )
        self._persist_state()
        return handle

    def stop_bundle(self, bundle_id: str) -> dict[str, str]:
        bundle = self._get_bundle(bundle_id)
        runtime = self._runtime_for_bundle(bundle_id)
        if runtime is None:
            raise KeyError(bundle_id)

        plugin = self._get_plugin(bundle.plugin_id)
        plugin.stop(runtime)

        if hasattr(self.runtimes, "stop_runtime"):
            self.runtimes.stop_runtime(runtime.runtime_id)
        else:
            self.runtimes = [
                item for item in self.runtimes if item.runtime_id != runtime.runtime_id
            ]

        self._release_runtime_reservation(bundle.bundle_id)
        self.record_event(
            event_type="runtime.stopped",
            message="runtime stopped by operator",
            bundle_id=bundle.bundle_id,
            runtime_id=runtime.runtime_id,
        )
        self.process_pending()
        return {"bundle_id": bundle.bundle_id, "status": "stopped"}

    def list_runtimes(self) -> list[RuntimeHandle]:
        if hasattr(self.runtimes, "list_runtimes"):
            return list(self.runtimes.list_runtimes())
        return list(self.runtimes or [])

    def process_pending(self) -> dict[str, int]:
        if self.resources is None or not self._has_plugins():
            summary = self.queue_summary()
            self._persist_state()
            return summary

        while True:
            progressed = False
            admission_plan = self._pending_task_plan()
            self._record_admission_events(admission_plan)
            for item in admission_plan:
                task_id = str(item["task_id"])
                task_before = self.queue.get(task_id)
                if task_before.status != "queued":
                    continue
                previous_status = task_before.status
                try:
                    result = self._attempt_task(task_id)
                    current_status = self.queue.get(task_id).status
                    if result or current_status != previous_status:
                        progressed = True
                except Exception:
                    if self.queue.get(task_id).status != previous_status:
                        progressed = True
                    continue
            if not progressed:
                break
        summary = self.queue_summary()
        self._persist_state()
        return summary

    def queue_summary(self) -> dict[str, int]:
        summary = {"queued": 0, "active": 0, "completed": 0, "failed": 0}
        for task in self.queue.snapshot():
            if task.status == "queued":
                summary["queued"] += 1
            elif task.status in _ACTIVE_EXECUTION_STATUSES:
                summary["active"] += 1
            elif task.status in _TERMINAL_COMPLETED_STATUSES:
                summary["completed"] += 1
            elif task.status in _TERMINAL_FAILED_STATUSES:
                summary["failed"] += 1
        return summary

    def queue_diagnostics(self) -> list[dict[str, str]]:
        diagnostics: list[dict[str, str]] = []
        for task in self.queue.snapshot():
            if task.status != "queued":
                continue
            diagnostics.append(self._diagnose_queued_task(task.task_id))
        return diagnostics

    def admission_telemetry(self) -> list[dict[str, int | str]]:
        return self._pending_task_plan()

    def _get_bundle(self, bundle_id: str) -> BundleConfig:
        for bundle in self.bundles:
            if bundle.bundle_id == bundle_id:
                return bundle
        raise KeyError(bundle_id)

    def _get_plugin(self, plugin_id: str):
        if hasattr(self.plugins, "get"):
            return self.plugins.get(plugin_id)

        for plugin in self.plugins or []:
            if plugin.plugin_id == plugin_id:
                return plugin
        raise KeyError(plugin_id)

    def _runtime_for_bundle(self, bundle_id: str) -> RuntimeHandle | None:
        for runtime in self.list_runtimes():
            if runtime.bundle_id == bundle_id:
                return runtime
        return None

    def _filtered_catalog_bundles(
        self,
        *,
        workload_type: str | None,
        bundle_id: str | None,
        include_disabled: bool,
    ) -> list[BundleConfig]:
        bundles: list[BundleConfig] = []
        for bundle in self.bundles:
            if bundle_id is not None and bundle.bundle_id != bundle_id:
                continue
            if workload_type is not None and bundle.workload_type != workload_type:
                continue
            if not include_disabled and not bundle.enabled:
                continue
            bundles.append(bundle)
        return bundles

    def _catalog_entry(self, bundle: BundleConfig, *, owner_id: str) -> dict:
        runtime = self._runtime_for_bundle(bundle.bundle_id)
        endpoint = self._catalog_endpoint(bundle, runtime)
        required = self._catalog_required_resources(bundle, runtime)
        payload = {
            "bundle_id": bundle.bundle_id,
            "plugin_id": bundle.plugin_id,
            "provider_type": bundle.provider_type,
            "model_id": bundle.model_id,
            "workload_type": bundle.workload_type,
            "enabled": bundle.enabled,
            "status": self._bundle_inventory_status(bundle),
            "endpoint": endpoint,
            "can_allocate_now": False,
            "can_queue": False,
            "allocation_mode": "unavailable",
            "reason": None,
            "required": required,
            "requires_runtime_start": runtime is None,
            "fit": self._catalog_fit(required),
        }

        if not bundle.enabled:
            payload["reason"] = "bundle_disabled"
            return payload

        unavailability = self._allocation_unavailability(bundle=bundle, runtime=runtime)
        if unavailability is None:
            owner_quota = self._owner_quota_unavailability(
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

        owner_quota = self._owner_quota_unavailability(
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

    def _operator_dashboard_bundle_entry(self, bundle: BundleConfig) -> dict:
        runtime = self._runtime_for_bundle(bundle.bundle_id)
        state = self._current_bundle_state(bundle.bundle_id)
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
            "inventory_status": self._bundle_inventory_status(bundle),
            "registry_status": self._bundle_registry_status(bundle),
            "cooldown_until": state["cooldown_until"],
            "drain_mode": state["drain_mode"],
        }

    def _operator_dashboard_task_entry(self, task: QueuedTask) -> dict:
        created_at = datetime.fromisoformat(task.created_at)
        age_seconds = max(
            0,
            int((datetime.now(timezone.utc) - created_at).total_seconds()),
        )
        terminal_at = self._task_terminal_timestamp(task.task_id)
        return {
            "task_id": task.task_id,
            "status": task.status,
            "priority": task.priority,
            "task_type": task.request.task_type,
            "bundle_id": self.selected_bundle_id(task.task_id),
            "created_at": task.created_at,
            "terminal_at": terminal_at,
            "age_seconds": age_seconds,
            "recovery_reason": self.task_recovery_reason(task.task_id),
            "result": self.task_result(task.task_id),
            "proxy_trace": self.task_proxy_trace(task.task_id),
        }

    def _task_terminal_timestamp(self, task_id: str) -> str | None:
        terminal_events = {"task.completed", "task.failed", "task.cancelled"}
        for event in reversed(self.task_history(task_id)):
            if event.event_type in terminal_events:
                return event.timestamp
        return None

    def _operator_spillover_preview(self, market_candidates: list[dict]) -> list[dict]:
        policy = self.operator_requests_policy()
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
                    self._operator_candidate_price(candidate),
                    -self._operator_candidate_rating(candidate),
                    str(candidate.get("bundle_id") or ""),
                )
            )
        elif strategy == "balanced":
            candidates.sort(
                key=lambda candidate: (
                    self._operator_balanced_candidate_score(candidate),
                    str(candidate.get("bundle_id") or ""),
                )
            )
        else:
            candidates.sort(
                key=lambda candidate: (
                    -self._operator_candidate_rating(candidate),
                    self._operator_candidate_price(candidate),
                    str(candidate.get("bundle_id") or ""),
                )
            )
        return candidates[:5]

    def _operator_candidate_price(self, candidate: dict) -> float:
        pricing = candidate.get("pricing") or {}
        return float(pricing.get("input") or 0)

    def _operator_candidate_rating(self, candidate: dict) -> float:
        rating = candidate.get("rating") or {}
        return float(rating.get("score") or 0)

    def _operator_balanced_candidate_score(self, candidate: dict) -> float:
        return self._operator_candidate_price(candidate) / 2000 - self._operator_candidate_rating(
            candidate
        )

    def _operator_dashboard_bootstrap(self, fleet: dict) -> dict:
        candidate = next(
            (
                bundle
                for bundle in fleet["bundles"]
                if bundle["enabled"]
            ),
            None,
        )
        wallet = self.owner_wallet_state()
        if not wallet["configured"]:
            next_step = "Create or import a wallet"
        elif candidate is not None:
            next_step = f"Create your first endpoint from {candidate['bundle_id']}"
        else:
            next_step = "Attach a provider or install a model"
        return {
            "wallet_ready": wallet["configured"],
            "owner_wallet": wallet,
            "node_identity": self.node_identity(),
            "provider_count": len(self.plugins.list()) if hasattr(self.plugins, "list") else len(self.plugins or []),
            "bundle_count": len(fleet["bundles"]),
            "endpoint_count": 0,
            "first_endpoint_candidate": candidate,
            "next_step": next_step,
        }

    def _operator_dashboard_install_status(self, status: str) -> str:
        if status == "queued":
            return "pending"
        return status

    def _catalog_endpoint(
        self,
        bundle: BundleConfig,
        runtime: RuntimeHandle | None,
    ) -> str | None:
        if runtime is None:
            return bundle.endpoint
        return runtime.metadata.get("endpoint") or bundle.endpoint

    def _catalog_required_resources(
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

    def _catalog_fit(
        self,
        required: dict[str, float | int],
    ) -> dict[str, float | int | bool]:
        if self.resources is None:
            return {
                "fits": True,
                "cpu_shortfall": 0.0,
                "ram_mb_shortfall": 0,
                "vram_mb_shortfall": 0,
            }
        return self.resources.fit_report(
            float(required["cpu"]),
            int(required["ram_mb"]),
            int(required["vram_mb"]),
        )

    def _select_allocation_bundle(self, request: AllocationRequest) -> BundleConfig:
        if request.bundle_id is not None:
            bundle = self._get_bundle(request.bundle_id)
            if not bundle.enabled:
                raise AllocationUnavailableError(
                    reason="bundle_disabled",
                    message=f"Bundle is disabled: {bundle.bundle_id}",
                    bundle_id=bundle.bundle_id,
                    retryable=False,
                )
            if bundle.workload_type != request.workload_type:
                raise AllocationUnavailableError(
                    reason="workload_mismatch",
                    message=(
                        f"Bundle workload mismatch: {bundle.bundle_id} != {request.workload_type}"
                    ),
                    bundle_id=bundle.bundle_id,
                    retryable=False,
                )
            return bundle

        for bundle in self.bundles:
            if bundle.enabled and bundle.workload_type == request.workload_type:
                return bundle
        raise AllocationUnavailableError(
            reason="no_compatible_bundle",
            message=f"No compatible bundle for workload_type: {request.workload_type}",
            bundle_id=request.bundle_id,
            retryable=False,
        )

    def _resolve_runtime_endpoint(
        self,
        bundle: BundleConfig,
        runtime: RuntimeHandle,
    ) -> str:
        endpoint = runtime.metadata.get("endpoint") or bundle.endpoint
        if endpoint is None:
            raise ValueError(f"Bundle has no resolved endpoint: {bundle.bundle_id}")
        return endpoint

    def _allocation_unavailability(
        self,
        *,
        bundle: BundleConfig,
        runtime: RuntimeHandle | None,
    ) -> dict[str, str | bool] | None:
        if self._current_bundle_state(bundle.bundle_id)["drain_mode"]:
            return {
                "reason": "bundle_draining",
                "message": f"Bundle is draining: {bundle.bundle_id}",
                "retryable": True,
            }
        if self._bundle_in_cooldown(bundle.bundle_id):
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
        if self.resources is not None:
            if runtime is None and not self.resources.can_fit(
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
            if not self.resources.can_fit(
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

    def _reserve_allocation_residency(
        self,
        *,
        allocation_id: str,
        bundle: BundleConfig,
        runtime: RuntimeHandle | None,
    ) -> str | None:
        if self.resources is None:
            return None
        if runtime is not None:
            if self._runtime_reservation_id(bundle.bundle_id) in self._runtime_reservations:
                return None
            if self._bundle_has_active_allocation_reservation(bundle.bundle_id):
                return None

        profile = bundle.resource_profile
        reservation_id = f"allocation:{allocation_id}"
        self.resources.reserve(
            reservation_id,
            cpu=profile.steady_cpu,
            ram_mb=profile.steady_ram_mb,
            vram_mb=profile.steady_vram_mb,
        )
        return reservation_id

    def _bundle_has_active_allocation_reservation(self, bundle_id: str) -> bool:
        for allocation in self._allocations.values():
            if allocation["bundle_id"] != bundle_id:
                continue
            if allocation["status"] != "active":
                continue
            if allocation.get("reservation_id") is None:
                continue
            return True
        return False

    def _release_allocation_resources(self, allocation: dict) -> None:
        reservation_id = allocation.get("reservation_id")
        if reservation_id is not None and self.resources is not None:
            self.resources.release(reservation_id)
            allocation["reservation_id"] = None

    def _owner_allocation_count(self, owner_id: str, *, status: str) -> int:
        count = 0
        for allocation in self._allocations.values():
            if allocation["status"] != status:
                continue
            request = allocation.get("request", {})
            if request.get("owner_id") != owner_id:
                continue
            count += 1
        return count

    def _owner_quota_unavailability(
        self,
        *,
        owner_id: str,
        status: str,
        bundle_id: str,
    ) -> dict[str, str | bool | int | None] | None:
        if status == "active":
            limit = self.max_active_allocations_per_owner
            count = self._owner_allocation_count(owner_id, status="active")
        elif status == "pending":
            limit = self.max_pending_allocations_per_owner
            count = self._owner_allocation_count(owner_id, status="pending")
        else:
            raise ValueError(f"unsupported allocation quota status: {status}")

        if count < limit:
            return None

        retry_hint = self._allocation_retry_hint(
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

    def _cleanup_expired_allocations(self) -> None:
        expired_any = False
        now = time.time()
        for allocation in self._allocations.values():
            if allocation["status"] not in {"active", "pending"}:
                continue
            try:
                expires_at = datetime.fromisoformat(allocation["expires_at"]).timestamp()
            except ValueError:
                continue
            if expires_at > now:
                continue
            self._release_allocation_resources(allocation)
            allocation["status"] = "expired"
            self._record_wallet_allocation_event(allocation, status="expired")
            self.record_event(
                event_type="allocation.expired",
                message="allocation lease expired",
                bundle_id=allocation["bundle_id"],
                runtime_id=allocation["runtime_id"],
                details={"allocation_id": allocation["allocation_id"]},
            )
            expired_any = True
        if expired_any:
            self._persist_state()

    def _public_allocation(self, allocation: dict) -> dict:
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
            retry_hint = self._allocation_retry_hint(
                bundle_id=str(allocation["bundle_id"]),
                reason=str(allocation["reason"]),
            )
            payload["retry_after_seconds"] = retry_hint["retry_after_seconds"]
            payload["next_attempt_at"] = retry_hint["next_attempt_at"]
        return payload

    def _create_pending_allocation(
        self,
        *,
        request: AllocationRequest,
        bundle: BundleConfig,
        reason: str,
    ) -> dict:
        allocation_id = str(uuid4())
        created_at = datetime.fromtimestamp(time.time(), timezone.utc).isoformat()
        expires_at = datetime.fromtimestamp(
            time.time() + request.lease_seconds,
            timezone.utc,
        ).isoformat()
        self._allocations[allocation_id] = {
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
        self.record_event(
            event_type="allocation.pending",
            message="allocation queued in wait mode",
            bundle_id=bundle.bundle_id,
            details={"allocation_id": allocation_id, "reason": reason},
        )
        self._persist_state()
        return self.get_allocation(allocation_id)

    def _reconcile_pending_allocations(self) -> None:
        changed = False
        for allocation in self._allocations.values():
            if allocation["status"] != "pending":
                continue
            request = AllocationRequest(**allocation["request"])
            try:
                bundle = self._select_allocation_bundle(request)
            except AllocationUnavailableError as error:
                allocation["reason"] = error.reason
                continue

            runtime = self._runtime_for_bundle(bundle.bundle_id)
            unavailability = self._allocation_unavailability(bundle=bundle, runtime=runtime)
            if unavailability is not None:
                allocation["reason"] = str(unavailability["reason"])
                continue
            owner_quota = self._owner_quota_unavailability(
                owner_id=request.owner_id,
                status="active",
                bundle_id=bundle.bundle_id,
            )
            if owner_quota is not None:
                allocation["reason"] = str(owner_quota["reason"])
                continue

            reservation_id = self._reserve_allocation_residency(
                allocation_id=str(allocation["allocation_id"]),
                bundle=bundle,
                runtime=runtime,
            )
            if runtime is None:
                runtime = self.start_bundle(bundle.bundle_id)
            allocation["bundle_id"] = bundle.bundle_id
            allocation["runtime_id"] = runtime.runtime_id
            allocation["endpoint"] = self._resolve_runtime_endpoint(bundle, runtime)
            allocation["status"] = "active"
            allocation["reservation_id"] = reservation_id
            allocation["reason"] = None
            self._record_wallet_allocation_activation_hook(
                allocation, activation_source="pending_reconcile"
            )
            self.record_event(
                event_type="allocation.activated",
                message="pending allocation activated",
                bundle_id=bundle.bundle_id,
                runtime_id=runtime.runtime_id,
                details={"allocation_id": allocation["allocation_id"]},
            )
            changed = True
        if changed:
            self._persist_state()

    def _allocation_retry_hint(
        self,
        *,
        bundle_id: str,
        reason: str,
    ) -> dict[str, int | str]:
        if reason == "provider_cooldown":
            cooldown_until = self._current_bundle_state(bundle_id)["cooldown_until"]
            if cooldown_until is not None:
                retry_after_seconds = max(0, int(cooldown_until - time.time()))
                return {
                    "retry_after_seconds": retry_after_seconds,
                    "next_attempt_at": datetime.fromtimestamp(
                        cooldown_until,
                        timezone.utc,
                    ).isoformat(),
                }
        next_attempt_ts = time.time() + _ALLOCATION_RETRY_INTERVAL_SECONDS
        return {
            "retry_after_seconds": _ALLOCATION_RETRY_INTERVAL_SECONDS,
            "next_attempt_at": datetime.fromtimestamp(
                next_attempt_ts,
                timezone.utc,
            ).isoformat(),
        }

    def _bundle_inventory_status(self, bundle: BundleConfig) -> str:
        if not bundle.enabled:
            return "disabled"
        if self._current_bundle_state(bundle.bundle_id)["cooldown_until"] is not None:
            return "cooldown"
        if self._current_bundle_state(bundle.bundle_id)["drain_mode"]:
            return "draining"
        runtime = self._runtime_for_bundle(bundle.bundle_id)
        if runtime is None:
            return "stopped"
        return runtime.status

    def _bundle_registry_status(self, bundle: BundleConfig) -> str:
        status = self._bundle_inventory_status(bundle)
        if status == "stopped" and bundle.enabled:
            return "ready"
        return status

    def _attempt_task(self, task_id: str) -> bool:
        task = self.queue.get(task_id)
        bundle_id = self.selected_bundle_id(task_id)
        if bundle_id is None:
            return False

        bundle = self._get_bundle(bundle_id)
        if not bundle.enabled:
            return False
        endpoint_manifest = self._endpoint_manifest_for_request(task.request)
        if (
            endpoint_manifest is not None
            and endpoint_manifest.execution_strategy == "proxy"
            and endpoint_manifest.proxy_target is not None
        ):
            return self._attempt_proxy_task(task_id, task, bundle, endpoint_manifest)
        plugin = self._get_plugin(bundle.plugin_id)
        runtime = self._runtime_for_bundle(bundle.bundle_id)

        if self._current_bundle_state(bundle.bundle_id)["drain_mode"]:
            return False
        if self._bundle_in_cooldown(bundle.bundle_id):
            if runtime is not None:
                runtime.health_status = "cooldown"
                runtime.last_error = self._current_bundle_state(bundle.bundle_id)[
                    "cooldown_reason"
                ]
            return False

        if runtime is not None and not self._health_check_with_retry(
            plugin,
            runtime,
            bundle.bundle_id,
        ):
            self._register_bundle_failure(
                bundle_id=bundle.bundle_id,
                plugin=plugin,
                runtime=runtime,
                reason=runtime.last_error or f"Runtime health check failed: {bundle.bundle_id}",
            )
            self._stop_runtime_for_bundle(bundle)
            runtime = None
        if runtime is not None:
            runtime.status = "running"
        estimate = plugin.estimate_resources(task.request, bundle, runtime)
        concurrency_limit = estimate.get("concurrency_limit")
        effective_concurrency_limit = bundle.max_parallel_requests
        if concurrency_limit is not None:
            effective_concurrency_limit = min(
                bundle.max_parallel_requests,
                concurrency_limit,
            )
        active_tasks = self._active_bundle_task_count(
            bundle.bundle_id,
            exclude_task_id=task_id,
        )
        if active_tasks >= effective_concurrency_limit:
            return False

        startup = estimate.get("startup_transient", {})
        resident = estimate.get("runtime_resident", {})
        request = estimate.get("request_active", {})

        startup_cpu = startup.get("cpu", 0.0)
        startup_ram = startup.get("ram_mb", 0)
        startup_vram = startup.get("vram_mb", 0)
        resident_cpu = resident.get("cpu", 0.0)
        resident_ram = resident.get("ram_mb", 0)
        resident_vram = resident.get("vram_mb", 0)
        request_cpu = request.get("cpu", 0.0)
        request_ram = request.get("ram_mb", 0)
        request_vram = request.get("vram_mb", 0)

        needed_cpu = request_cpu + (0.0 if runtime else startup_cpu + resident_cpu)
        needed_ram = request_ram + (0 if runtime else startup_ram + resident_ram)
        needed_vram = request_vram + (0 if runtime else startup_vram + resident_vram)
        if not self.resources.can_fit(needed_cpu, needed_ram, needed_vram):
            self._evict_idle_runtimes_for_task(
                task=task,
                requested_bundle=bundle,
                cpu=needed_cpu,
                ram_mb=needed_ram,
                vram_mb=needed_vram,
            )
        if not self.resources.can_fit(needed_cpu, needed_ram, needed_vram):
            return False

        startup_reservation_id = f"startup:{task_id}"
        request_reservation_id = f"request:{task_id}"
        started_runtime = False
        entered_running = False
        self.queue.transition_status(task_id, "admitted")

        try:
            if runtime is None:
                if startup_cpu or startup_ram or startup_vram:
                    self.resources.reserve(
                        startup_reservation_id,
                        cpu=startup_cpu,
                        ram_mb=startup_ram,
                        vram_mb=startup_vram,
                    )

                self.queue.transition_status(task_id, "starting")
                runtime = self.start_bundle(bundle.bundle_id)
                started_runtime = True
                if startup_cpu or startup_ram or startup_vram:
                    self.resources.release(startup_reservation_id)

                self._reserve_runtime_residency(
                    bundle.bundle_id,
                    cpu=resident_cpu,
                    ram_mb=resident_ram,
                    vram_mb=resident_vram,
                )
                runtime.status = "running"
                runtime.health_status = "healthy"
                runtime.last_error = None
                if not self._health_check_with_retry(
                    plugin,
                    runtime,
                    bundle.bundle_id,
                ):
                    self._register_bundle_failure(
                        bundle_id=bundle.bundle_id,
                        plugin=plugin,
                        runtime=runtime,
                        reason=runtime.last_error
                        or f"Runtime health check failed: {bundle.bundle_id}",
                    )
                    raise RuntimeError(runtime.last_error or bundle.bundle_id)

            if request_cpu or request_ram or request_vram:
                self.resources.reserve(
                    request_reservation_id,
                    cpu=request_cpu,
                    ram_mb=request_ram,
                    vram_mb=request_vram,
                )

            self.queue.transition_status(task_id, "running")
            entered_running = True
            self._touch_task_session(task.request)
            self._task_results[task_id] = self._invoke_with_retry(
                plugin,
                bundle,
                task.request,
                runtime,
            )
            self._register_bundle_success(bundle.bundle_id, runtime)
            runtime.health_status = "healthy"
            runtime.last_error = None
            self.queue.transition_status(task_id, "completed")
            self.record_event(
                event_type="task.completed",
                message="task completed successfully",
                task_id=task_id,
                bundle_id=bundle.bundle_id,
                runtime_id=runtime.runtime_id if runtime is not None else None,
            )
            self._auto_record_wallet_usage_for_task(
                task_id=task_id,
                bundle=bundle,
                task=task.request,
            )
            return True
        except Exception as error:
            self.queue.transition_status(task_id, "failed")
            if runtime is not None:
                runtime.last_error = str(error)
            self.record_event(
                event_type="task.failed",
                message=str(error),
                task_id=task_id,
                bundle_id=bundle.bundle_id,
                runtime_id=runtime.runtime_id if runtime is not None else None,
            )
            if started_runtime and not entered_running and runtime is not None:
                self._stop_runtime_for_bundle(bundle)
            raise
        finally:
            self.resources.release(startup_reservation_id)
            self.resources.release(request_reservation_id)
            if runtime is not None and bundle.warm_policy == "never":
                self._stop_runtime_for_bundle(bundle)

    def _reserve_runtime_residency(
        self, bundle_id: str, *, cpu: float, ram_mb: int, vram_mb: int
    ) -> None:
        reservation_id = self._runtime_reservation_id(bundle_id)
        if reservation_id in self._runtime_reservations:
            return
        if cpu or ram_mb or vram_mb:
            self.resources.reserve(
                reservation_id,
                cpu=cpu,
                ram_mb=ram_mb,
                vram_mb=vram_mb,
            )
        self._runtime_reservations.add(reservation_id)

    def _release_runtime_reservation(self, bundle_id: str) -> None:
        reservation_id = self._runtime_reservation_id(bundle_id)
        self.resources.release(reservation_id)
        self._runtime_reservations.discard(reservation_id)

    def _stop_runtime_for_bundle(self, bundle: BundleConfig) -> None:
        runtime = self._runtime_for_bundle(bundle.bundle_id)
        if runtime is None:
            return

        plugin = self._get_plugin(bundle.plugin_id)
        plugin.stop(runtime)
        if hasattr(self.runtimes, "stop_runtime"):
            self.runtimes.stop_runtime(runtime.runtime_id)
        else:
            self.runtimes = [
                item for item in self.runtimes if item.runtime_id != runtime.runtime_id
            ]
        self._release_runtime_reservation(bundle.bundle_id)

    def _runtime_reservation_id(self, bundle_id: str) -> str:
        return f"runtime:{bundle_id}"

    def _circuit_breaker_policy_for(self, plugin) -> dict:
        policy = plugin.circuit_breaker_policy()
        return {
            "failure_threshold": max(0, int(policy.get("failure_threshold", 0))),
            "cooldown_seconds": max(0.0, float(policy.get("cooldown_seconds", 0.0))),
        }

    def _current_bundle_state(self, bundle_id: str) -> dict:
        state = self._bundle_states.get(bundle_id)
        if state is None:
            return {
                "bundle_id": bundle_id,
                "failure_streak": 0,
                "cooldown_until": None,
                "cooldown_reason": None,
                "drain_mode": False,
                "drain_reason": None,
            }
        return {
            "bundle_id": bundle_id,
            "failure_streak": int(state.get("failure_streak", 0)),
            "cooldown_until": state.get("cooldown_until"),
            "cooldown_reason": state.get("cooldown_reason"),
            "drain_mode": bool(state.get("drain_mode", False)),
            "drain_reason": state.get("drain_reason"),
        }

    def _bundle_state_is_non_default(self, bundle_id: str) -> bool:
        state = self._current_bundle_state(bundle_id)
        return bool(
            state["failure_streak"]
            or state["cooldown_until"] is not None
            or state["cooldown_reason"] is not None
            or state["drain_mode"]
            or state["drain_reason"] is not None
        )

    def _bundle_state_is_empty(self, state: dict) -> bool:
        return (
            not state["failure_streak"]
            and state["cooldown_until"] is None
            and state["cooldown_reason"] is None
            and not state["drain_mode"]
            and state["drain_reason"] is None
        )

    def _set_bundle_state(
        self,
        bundle_id: str,
        *,
        failure_streak: int,
        cooldown_until: float | None,
        cooldown_reason: str | None,
        drain_mode: bool,
        drain_reason: str | None,
    ) -> dict:
        state = {
            "bundle_id": bundle_id,
            "failure_streak": failure_streak,
            "cooldown_until": cooldown_until,
            "cooldown_reason": cooldown_reason,
            "drain_mode": drain_mode,
            "drain_reason": drain_reason,
        }
        if self._bundle_state_is_empty(state):
            self._bundle_states.pop(bundle_id, None)
            return self._current_bundle_state(bundle_id)
        self._bundle_states[bundle_id] = state
        return dict(state)

    def _register_bundle_failure(
        self,
        *,
        bundle_id: str,
        plugin,
        runtime: RuntimeHandle | None,
        reason: str,
    ) -> None:
        policy = self._circuit_breaker_policy_for(plugin)
        if policy["failure_threshold"] <= 0:
            return

        state = self._current_bundle_state(bundle_id)
        failure_streak = state["failure_streak"] + 1
        cooldown_until = state["cooldown_until"]
        cooldown_reason = reason
        if (
            failure_streak >= policy["failure_threshold"]
            and policy["cooldown_seconds"] > 0.0
        ):
            cooldown_until = time.time() + policy["cooldown_seconds"]
            if runtime is not None:
                runtime.health_status = "cooldown"
                runtime.last_error = reason
            self.record_event(
                event_type="bundle.cooldown_started",
                message="bundle entered provider cooldown",
                bundle_id=bundle_id,
                runtime_id=runtime.runtime_id if runtime is not None else None,
                details={
                    "failure_streak": failure_streak,
                    "cooldown_until": cooldown_until,
                    "cooldown_reason": cooldown_reason,
                },
            )
        self._set_bundle_state(
            bundle_id,
            failure_streak=failure_streak,
            cooldown_until=cooldown_until,
            cooldown_reason=cooldown_reason,
            drain_mode=state["drain_mode"],
            drain_reason=state["drain_reason"],
        )

    def _register_bundle_success(
        self,
        bundle_id: str,
        runtime: RuntimeHandle | None = None,
    ) -> None:
        if not self._bundle_state_is_non_default(bundle_id):
            return
        had_cooldown = self._current_bundle_state(bundle_id)["cooldown_until"] is not None
        self._set_bundle_state(
            bundle_id,
            failure_streak=0,
            cooldown_until=None,
            cooldown_reason=None,
            drain_mode=self._current_bundle_state(bundle_id)["drain_mode"],
            drain_reason=self._current_bundle_state(bundle_id)["drain_reason"],
        )
        if had_cooldown:
            self.record_event(
                event_type="bundle.cooldown_cleared",
                message="bundle provider cooldown cleared",
                bundle_id=bundle_id,
                runtime_id=runtime.runtime_id if runtime is not None else None,
            )

    def _bundle_in_cooldown(self, bundle_id: str) -> bool:
        state = self._current_bundle_state(bundle_id)
        cooldown_until = state["cooldown_until"]
        if cooldown_until is None:
            return False
        if cooldown_until <= time.time():
            self._set_bundle_state(
                bundle_id,
                failure_streak=0,
                cooldown_until=None,
                cooldown_reason=None,
                drain_mode=state["drain_mode"],
                drain_reason=state["drain_reason"],
            )
            self.record_event(
                event_type="bundle.cooldown_expired",
                message="bundle provider cooldown expired",
                bundle_id=bundle_id,
            )
            return False
        return True

    def _health_check_with_retry(
        self,
        plugin,
        runtime: RuntimeHandle,
        bundle_id: str,
    ) -> bool:
        policy = self._retry_policy_for(plugin, "health_check")
        for attempt in range(1, policy["max_attempts"] + 1):
            if plugin.health_check(runtime):
                runtime.health_status = "healthy"
                runtime.last_error = None
                return True
            if attempt < policy["max_attempts"]:
                time.sleep(policy["backoff_seconds"])

        runtime.health_status = "unhealthy"
        runtime.last_error = (
            f"Runtime health check failed after {policy['max_attempts']} attempts: "
            f"{bundle_id}"
        )
        return False

    def _invoke_with_retry(
        self,
        plugin,
        bundle: BundleConfig,
        task: TaskRequest,
        runtime: RuntimeHandle,
    ) -> dict:
        policy = self._retry_policy_for(plugin, "invoke")
        retry_exceptions = policy["retry_exceptions"]
        last_error: Exception | None = None

        for attempt in range(1, policy["max_attempts"] + 1):
            try:
                return plugin.invoke(task, runtime)
            except Exception as error:
                last_error = error
                retryable = isinstance(error, retry_exceptions)
                if not retryable or attempt >= policy["max_attempts"]:
                    if retryable:
                        runtime.health_status = "unhealthy"
                        runtime.last_error = str(error)
                        self._register_bundle_failure(
                            bundle_id=bundle.bundle_id,
                            plugin=plugin,
                            runtime=runtime,
                            reason=str(error),
                        )
                    raise
                time.sleep(policy["backoff_seconds"])

        if last_error is None:
            raise RuntimeError("invoke failed without an error")
        raise last_error

    def _auto_record_wallet_usage_for_task(
        self,
        *,
        task_id: str,
        bundle: BundleConfig,
        task: TaskRequest,
    ) -> None:
        owner_id, allocation_id = self._wallet_usage_attribution_for_task(task)
        result = self._task_results.get(task_id)
        if not isinstance(result, dict):
            return
        usage_contract = self._provider_usage_contract_for_bundle(bundle)
        usage = result.get("usage")
        if not isinstance(usage, dict):
            if owner_id is None:
                return
            if usage_contract.get("missing_usage_behavior") == "strict_accounting":
                self._mark_task_wallet_accounting_blocked(
                    task_id=task_id,
                    bundle_id=bundle.bundle_id,
                    owner_id=str(owner_id),
                    reason="missing_provider_usage",
                )
            return
        try:
            measurement = WalletUsageMeasurement(**usage)
        except ValidationError as error:
            if owner_id is None:
                return
            self._record_wallet_usage_skipped(
                task_id=task_id,
                bundle_id=bundle.bundle_id,
                owner_id=str(owner_id),
                source=str(usage.get("source", "task_auto")),
                reason="invalid_provider_usage_contract",
                validation_errors=error.errors(),
                strict_accounting=(
                    usage_contract.get("missing_usage_behavior") == "strict_accounting"
                ),
            )
            return
        usage_quote = self.quote_wallet_usage(
            input_tokens=measurement.input_tokens,
            output_tokens=measurement.output_tokens,
            fixed_request_count=measurement.fixed_request_count,
        )
        self._record_session_usage_charge_for_task(
            task_id=task_id,
            task=task,
            amount_q=float(usage_quote["charges"]["total_q"]),
        )
        if owner_id is None:
            return
        self.record_wallet_usage(
            owner_id=str(owner_id),
            task_id=task_id,
            allocation_id=allocation_id,
            bundle_id=bundle.bundle_id,
            workload_type=bundle.workload_type,
            input_tokens=measurement.input_tokens,
            output_tokens=measurement.output_tokens,
            fixed_request_count=measurement.fixed_request_count,
            measurement_kind=measurement.measurement_kind,
            measurement_source=measurement.measurement_source,
            source=str(usage.get("source", "task_auto")),
        )

    def _record_session_usage_charge_for_task(
        self,
        *,
        task_id: str,
        task: TaskRequest,
        amount_q: float,
    ) -> None:
        session_id = task.constraints.get("session_id")
        if session_id is None:
            return
        session_service = getattr(self, "session_service", None)
        if session_service is None:
            return
        try:
            session_service.record_usage_charge(
                str(session_id),
                amount_q=amount_q,
            )
        except ValueError as error:
            result = self._task_results.get(task_id)
            if isinstance(result, dict):
                result["session_accounting"] = {
                    "status": "blocked",
                    "reason": str(error),
                    "charged_q": amount_q,
                }
            self.record_event(
                event_type="session.charge_blocked",
                message="session usage charge blocked",
                task_id=task_id,
                bundle_id=self.selected_bundle_id(task_id),
                details={
                    "session_id": str(session_id),
                    "charged_q": amount_q,
                    "reason": str(error),
                },
            )

    def _provider_usage_contract_for_bundle(self, bundle: BundleConfig) -> dict:
        plugin = self.plugins.get(bundle.plugin_id)
        return plugin.usage_contract()

    def _mark_task_wallet_accounting_blocked(
        self,
        *,
        task_id: str,
        bundle_id: str,
        owner_id: str,
        reason: str,
        source: str = "task_auto",
        validation_errors=None,
    ) -> None:
        result = self._task_results.get(task_id)
        if isinstance(result, dict):
            result["wallet_accounting"] = {
                "status": "unbillable",
                "settlement_status": "blocked",
                "reason": reason,
            }
        details = {
            "owner_id": owner_id,
            "source": source,
            "billing_status": "unbillable",
            "settlement_status": "blocked",
            "reason": reason,
        }
        if validation_errors is not None:
            details["validation_errors"] = validation_errors
        self.record_event(
            event_type="wallet.usage_skipped",
            message="wallet usage skipped and settlement blocked by strict accounting",
            task_id=task_id,
            bundle_id=bundle_id,
            details=details,
        )

    def _record_wallet_usage_skipped(
        self,
        *,
        task_id: str,
        bundle_id: str,
        owner_id: str,
        source: str,
        reason: str,
        strict_accounting: bool,
        validation_errors=None,
    ) -> None:
        if strict_accounting:
            self._mark_task_wallet_accounting_blocked(
                task_id=task_id,
                bundle_id=bundle_id,
                owner_id=owner_id,
                source=source,
                reason=reason,
                validation_errors=validation_errors,
            )
            return
        details = {
            "owner_id": owner_id,
            "source": source,
        }
        if validation_errors is not None:
            details["validation_errors"] = validation_errors
        self.record_event(
            event_type="wallet.usage_skipped",
            message="wallet usage skipped due to invalid provider usage contract",
            task_id=task_id,
            bundle_id=bundle_id,
            details=details,
        )

    def _wallet_usage_attribution_for_task(
        self,
        task: TaskRequest,
    ) -> tuple[str | None, str | None]:
        owner_id = task.constraints.get("wallet_owner_id")
        allocation_id = (
            str(task.constraints["allocation_id"])
            if "allocation_id" in task.constraints
            else None
        )
        if owner_id is not None:
            return str(owner_id), allocation_id
        if allocation_id is None:
            return None, None

        allocation = self._allocations.get(allocation_id)
        if allocation is None:
            return None, allocation_id

        request = allocation.get("request", {})
        derived_owner_id = request.get("owner_id")
        if derived_owner_id is None:
            return None, allocation_id
        return str(derived_owner_id), allocation_id

    def _task_request_with_endpoint_context(self, request: TaskRequest) -> TaskRequest:
        endpoint_id = request.constraints.get("endpoint_id")
        if endpoint_id is None:
            return request
        endpoint_service = getattr(self, "endpoint_service", None)
        if endpoint_service is None:
            raise ValueError("Endpoint service is not configured")
        manifest = endpoint_service.get_endpoint(str(endpoint_id)).endpoint
        if manifest.execution_strategy == "proxy" and manifest.proxy_target is None:
            raise ValueError(f"Proxy endpoint has no target: {manifest.endpoint_id}")
        if (
            request.bundle_override is not None
            and request.bundle_override != manifest.bundle_id
        ):
            raise ValueError(
                "Endpoint bundle conflicts with requested bundle_override: "
                f"{manifest.endpoint_id}"
            )
        self._validate_task_session(manifest, request)
        return request.model_copy(
            update={
                "mode": "manual",
                "bundle_override": manifest.bundle_id,
            }
        )

    def _endpoint_requires_session(self, manifest) -> bool:
        session_policy = manifest.session
        return any(
            (
                session_policy.minimum_deposit > 0,
                session_policy.minimum_session_fee > 0,
                session_policy.idle_fee_per_minute > 0,
            )
        )

    def _validate_task_session(self, manifest, request: TaskRequest) -> None:
        session_id = request.constraints.get("session_id")
        if not self._endpoint_requires_session(manifest) and session_id is None:
            return
        if session_id is None:
            raise ValueError(
                f"Active session required for paid endpoint: {manifest.endpoint_id}"
            )
        session_service = getattr(self, "session_service", None)
        if session_service is None:
            raise ValueError("Session service is not configured")
        try:
            session_service.require_active_session(
                endpoint_id=manifest.endpoint_id,
                session_id=str(session_id),
            )
        except KeyError as error:
            raise ValueError(f"Unknown session: {session_id}") from error

    def _touch_task_session(self, request: TaskRequest) -> None:
        session_id = request.constraints.get("session_id")
        if session_id is None:
            return
        session_service = getattr(self, "session_service", None)
        if session_service is None:
            raise RuntimeError("Session service is not configured")
        try:
            session_service.touch_session(str(session_id))
        except KeyError as error:
            raise RuntimeError(f"Unknown session: {session_id}") from error

    def _endpoint_manifest_for_request(self, request: TaskRequest):
        endpoint_id = request.constraints.get("endpoint_id")
        if endpoint_id is None:
            return None
        endpoint_service = getattr(self, "endpoint_service", None)
        if endpoint_service is None:
            return None
        return endpoint_service.get_endpoint(str(endpoint_id)).endpoint

    def _attempt_proxy_task(self, task_id: str, task: QueuedTask, bundle: BundleConfig, endpoint_manifest) -> bool:
        self.queue.transition_status(task_id, "admitted")
        self.record_event(
            event_type="task.proxy_dispatched",
            message="task dispatched through proxy endpoint",
            task_id=task_id,
            bundle_id=bundle.bundle_id,
            details={
                "endpoint_id": endpoint_manifest.endpoint_id,
                "remote_endpoint_id": endpoint_manifest.proxy_target.source_endpoint_id,
                "remote_node_id": endpoint_manifest.proxy_target.source_node_id,
                "source_base_url": endpoint_manifest.proxy_target.source_base_url,
            },
        )
        try:
            self.queue.transition_status(task_id, "running")
            self._touch_task_session(task.request)
            self._task_results[task_id] = self._invoke_proxy_endpoint(
                endpoint_manifest,
                task.request,
            )
            self.queue.transition_status(task_id, "completed")
            self.record_event(
                event_type="task.completed",
                message="task completed successfully",
                task_id=task_id,
                bundle_id=bundle.bundle_id,
            )
            self._auto_record_wallet_usage_for_task(
                task_id=task_id,
                bundle=bundle,
                task=task.request,
            )
            return True
        except Exception as error:
            self.queue.transition_status(task_id, "failed")
            self.record_event(
                event_type="task.failed",
                message=str(error),
                task_id=task_id,
                bundle_id=bundle.bundle_id,
            )
            raise

    def _invoke_proxy_endpoint(self, endpoint_manifest, task_request: TaskRequest) -> dict:
        proxy_target = endpoint_manifest.proxy_target
        if proxy_target is None:
            raise RuntimeError(f"Proxy endpoint has no target: {endpoint_manifest.endpoint_id}")
        remote_constraints = {
            key: value
            for key, value in task_request.constraints.items()
            if key not in {"endpoint_id", "allocation_id"}
        }
        remote_constraints["endpoint_id"] = proxy_target.source_endpoint_id
        remote_request = task_request.model_copy(
            update={
                "mode": "auto",
                "bundle_override": None,
                "constraints": remote_constraints,
            }
        )
        submit_payload = remote_request.model_dump(mode="json")
        submit_response = self._remote_request_json(
            "POST",
            f"{proxy_target.source_base_url.rstrip('/')}/tasks",
            submit_payload,
        )
        remote_task_id = str(submit_response["task_id"])
        attempts = max(1, int(getattr(self, "proxy_poll_attempts", 5)))
        interval_seconds = max(0.0, float(getattr(self, "proxy_poll_interval_seconds", 0.0)))
        detail = None
        for attempt in range(attempts):
            detail = self._remote_request_json(
                "GET",
                f"{proxy_target.source_base_url.rstrip('/')}/tasks/{remote_task_id}",
            )
            if detail.get("status") == "completed":
                result = dict(detail.get("result") or {})
                result["proxy"] = {
                    "remote_task_id": remote_task_id,
                    "remote_endpoint_id": proxy_target.source_endpoint_id,
                    "remote_node_id": proxy_target.source_node_id,
                    "source_base_url": proxy_target.source_base_url,
                }
                return result
            if detail.get("status") == "failed":
                raise RuntimeError(
                    str((detail.get("result") or {}).get("error") or f"Remote proxy task failed: {remote_task_id}")
                )
            if attempt < attempts - 1 and interval_seconds > 0.0:
                time.sleep(interval_seconds)
        raise RuntimeError(
            f"Remote proxy task did not complete within {attempts} poll attempts: {remote_task_id}"
        )

    def _remote_request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
    ) -> dict:
        transport = getattr(self, "remote_transport", None)
        if transport is not None:
            return transport.request_json(method, url, payload)
        return self._default_remote_request_json(method, url, payload)

    def _default_remote_request_json(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
    ) -> dict:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib_request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                body = response.read().decode("utf-8")
        except urllib_error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"Remote proxy request failed: {method} {url} [{error.code}] {body}"
            ) from error
        except urllib_error.URLError as error:
            raise RuntimeError(f"Remote proxy request failed: {method} {url} [{error.reason}]") from error
        return json.loads(body) if body else {}

    def _task_request_with_allocation_context(self, request: TaskRequest) -> TaskRequest:
        allocation_id = request.constraints.get("allocation_id")
        if allocation_id is None:
            return request

        self._cleanup_expired_allocations()
        self._reconcile_pending_allocations()
        allocation = self._allocations.get(str(allocation_id))
        if allocation is None:
            raise ValueError(f"Unknown allocation: {allocation_id}")
        if allocation["status"] != "active":
            raise ValueError(f"Allocation is not active: {allocation_id}")

        allocation_bundle_id = str(allocation["bundle_id"])
        if (
            request.bundle_override is not None
            and request.bundle_override != allocation_bundle_id
        ):
            raise ValueError(
                "Allocation bundle conflicts with requested bundle_override: "
                f"{allocation_id}"
            )

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

    def _retry_policy_for(self, plugin, operation: str) -> dict:
        policy = plugin.retry_policy()
        operation_policy = dict(policy.get(operation, {}))
        retry_exceptions = tuple(
            operation_policy.get("retry_exceptions", (RuntimeError,))
        )
        return {
            "max_attempts": max(1, int(operation_policy.get("max_attempts", 1))),
            "backoff_seconds": max(
                0.0,
                float(operation_policy.get("backoff_seconds", 0.0)),
            ),
            "retry_exceptions": retry_exceptions,
        }

    def _restored_task_status(self, task: TaskSnapshot) -> str:
        if task.status not in _ACTIVE_EXECUTION_STATUSES:
            return task.status
        if self._can_retry_after_restart(task):
            return "queued"
        return "failed"

    def _recovery_reason_for_task(self, task: TaskSnapshot) -> str:
        if self._can_retry_after_restart(task):
            return "restart_retry_queued"
        return "restart_failed_unknown_inflight"

    def _recovery_message(self, recovery_reason: str) -> str:
        if recovery_reason == "restart_retry_queued":
            return "in-flight task requeued during restart recovery"
        return "unknown in-flight task failed during restart recovery"

    def _can_retry_after_restart(self, task: TaskSnapshot) -> bool:
        if not task.request.constraints.get("retry_on_restart"):
            return False
        if task.bundle_id is None:
            return False

        try:
            bundle = self._get_bundle(task.bundle_id)
            plugin = self._get_plugin(bundle.plugin_id)
        except KeyError:
            return False
        return plugin.supports_restart_retry(task.request, bundle)

    def _restore_runtimes(self, runtimes: list[RuntimeSnapshot]) -> None:
        self._clear_runtime_reservations()
        recovered_runtimes: list[RuntimeHandle] = []

        for runtime in runtimes:
            if runtime.status != "running" or runtime.bundle_id is None:
                continue

            try:
                bundle = self._get_bundle(runtime.bundle_id)
                plugin = self._get_plugin(bundle.plugin_id)
            except KeyError:
                continue

            recovered_runtime = RuntimeHandle(
                runtime_id=runtime.runtime_id,
                command=list(runtime.command),
                status=runtime.status,
                bundle_id=runtime.bundle_id,
                health_status=runtime.health_status,
                last_error=runtime.last_error,
                metadata=dict(runtime.metadata),
            )
            if self._bundle_in_cooldown(runtime.bundle_id):
                recovered_runtime.health_status = "cooldown"
                recovered_runtime.last_error = self._current_bundle_state(
                    runtime.bundle_id
                )["cooldown_reason"]
                recovered_runtimes.append(recovered_runtime)
                continue
            if not self._health_check_with_retry(
                plugin,
                recovered_runtime,
                runtime.bundle_id,
            ):
                self.record_event(
                    event_type="runtime.recovery_skipped",
                    message="runtime health check failed during restart recovery",
                    bundle_id=runtime.bundle_id,
                    runtime_id=runtime.runtime_id,
                )
                continue

            profile = bundle.resource_profile
            if self.resources is not None and not self.resources.can_fit(
                profile.steady_cpu,
                profile.steady_ram_mb,
                profile.steady_vram_mb,
            ):
                self.record_event(
                    event_type="runtime.recovery_skipped",
                    message="runtime recovery skipped due to insufficient resources",
                    bundle_id=runtime.bundle_id,
                    runtime_id=runtime.runtime_id,
                )
                continue

            recovered_runtime.health_status = "healthy"
            recovered_runtime.last_error = None
            if self.resources is not None:
                self._reserve_runtime_residency(
                    bundle.bundle_id,
                    cpu=profile.steady_cpu,
                    ram_mb=profile.steady_ram_mb,
                    vram_mb=profile.steady_vram_mb,
                )
            self.record_event(
                event_type="runtime.recovered",
                message="runtime reconnected during restart recovery",
                bundle_id=runtime.bundle_id,
                runtime_id=runtime.runtime_id,
            )
            recovered_runtimes.append(recovered_runtime)

        self._replace_runtimes(recovered_runtimes)

    def _clear_runtime_reservations(self) -> None:
        if self.resources is None:
            self._runtime_reservations.clear()
            return

        for reservation_id in list(self._runtime_reservations):
            self.resources.release(reservation_id)
        self._runtime_reservations.clear()

    def _replace_runtimes(self, runtimes: list[RuntimeHandle]) -> None:
        if hasattr(self.runtimes, "replace_runtimes"):
            self.runtimes.replace_runtimes(runtimes)
            return
        self.runtimes = list(runtimes)

    def _persist_state(self) -> None:
        if self.state_store is None:
            return
        self.state_store.save(self.snapshot_state())

    def _prune_wallet_usage_events(self) -> None:
        if self.wallet_usage_retention_limit is None:
            return
        if len(self._wallet_usage_events) <= self.wallet_usage_retention_limit:
            return
        self._wallet_usage_events = self._wallet_usage_events[
            -self.wallet_usage_retention_limit :
        ]

    def _replace_bundle(self, updated_bundle: BundleConfig) -> None:
        self.bundles = [
            updated_bundle if bundle.bundle_id == updated_bundle.bundle_id else bundle
            for bundle in self.bundles
        ]

    def _persist_bundle_config_if_available(self) -> None:
        if self.bundle_registry is None:
            return
        self.bundle_registry.save(self.bundles)

    def _require_bundle_registry(self):
        if self.bundle_registry is None:
            raise ValueError("Bundle registry is not configured")
        return self.bundle_registry

    def _validate_bundles(self, bundles: list[BundleConfig]) -> None:
        for bundle in bundles:
            plugin = self._get_plugin(bundle.plugin_id)
            plugin.validate_bundle(bundle)

    def _has_plugins(self) -> bool:
        if hasattr(self.plugins, "list"):
            return bool(self.plugins.list())
        return bool(self.plugins)

    def _active_bundle_task_count(
        self, bundle_id: str, *, exclude_task_id: str | None = None
    ) -> int:
        count = 0
        for task in self.queue.snapshot():
            if exclude_task_id is not None and task.task_id == exclude_task_id:
                continue
            if task.status not in _ACTIVE_EXECUTION_STATUSES:
                continue
            if self.selected_bundle_id(task.task_id) == bundle_id:
                count += 1
        return count

    def runtime_active_task_count(self, bundle_id: str) -> int:
        return self._active_bundle_task_count(bundle_id)

    def _pending_task_order(self) -> list[str]:
        return [item["task_id"] for item in self._pending_task_plan()]

    def _record_admission_events(self, admission_plan: list[dict[str, int | str]]) -> None:
        for item in admission_plan:
            self.record_event(
                event_type="admission.selected",
                message="task selected for admission attempt",
                task_id=str(item["task_id"]),
                bundle_id=str(item["bundle_id"]),
                details={
                    "base_priority": item["base_priority"],
                    "aging_bonus": item["aging_bonus"],
                    "effective_priority": item["effective_priority"],
                    "fair_share_round": item["fair_share_round"],
                    "admission_rank": item["admission_rank"],
                    "selection_reason": item["selection_reason"],
                },
            )

    def _pending_task_plan(self) -> list[dict[str, int | str]]:
        queued_tasks = [task for task in self.queue.snapshot() if task.status == "queued"]
        if not queued_tasks:
            return []

        tasks_by_bundle: dict[str, list[QueuedTask]] = {}
        for task in queued_tasks:
            bundle_id = self.selected_bundle_id(task.task_id) or ""
            tasks_by_bundle.setdefault(bundle_id, []).append(task)

        for bundle_id in tasks_by_bundle:
            tasks_by_bundle[bundle_id].sort(
                key=lambda task: (
                    -self._effective_task_priority(task),
                    task.enqueue_index,
                )
            )

        bundle_dispatch_counts = {bundle_id: 0 for bundle_id in tasks_by_bundle}
        admission_plan: list[dict[str, int | str]] = []
        while tasks_by_bundle:
            min_dispatch_count = min(
                bundle_dispatch_counts[bundle_id] for bundle_id in tasks_by_bundle
            )
            dispatch_candidates = [
                bundle_id
                for bundle_id in tasks_by_bundle
                if bundle_dispatch_counts[bundle_id] == min_dispatch_count
            ]
            next_bundle_id = min(
                dispatch_candidates,
                key=lambda bundle_id: (
                    -self._effective_task_priority(tasks_by_bundle[bundle_id][0]),
                    tasks_by_bundle[bundle_id][0].enqueue_index,
                ),
            )
            selection_reason = self._selection_reason(
                tasks_by_bundle=tasks_by_bundle,
                dispatch_candidates=dispatch_candidates,
                next_bundle_id=next_bundle_id,
            )
            next_task = tasks_by_bundle[next_bundle_id].pop(0)
            aging_bonus = self._aging_bonus(next_task)
            admission_plan.append(
                {
                    "task_id": next_task.task_id,
                    "bundle_id": self.selected_bundle_id(next_task.task_id) or "",
                    "base_priority": next_task.priority,
                    "aging_bonus": aging_bonus,
                    "effective_priority": next_task.priority + aging_bonus,
                    "fair_share_round": min_dispatch_count,
                    "admission_rank": len(admission_plan) + 1,
                    "selection_reason": selection_reason,
                }
            )
            bundle_dispatch_counts[next_bundle_id] += 1
            if not tasks_by_bundle[next_bundle_id]:
                del tasks_by_bundle[next_bundle_id]
        return admission_plan

    def _effective_task_priority(self, task: QueuedTask) -> int:
        return task.priority + self._aging_bonus(task)

    def _aging_bonus(self, task: QueuedTask) -> int:
        try:
            created_at = datetime.fromisoformat(task.created_at)
        except ValueError:
            return 0
        waiting_seconds = max(0.0, time.time() - created_at.timestamp())
        return min(
            _AGING_PRIORITY_MAX_BONUS,
            int(waiting_seconds // _AGING_PRIORITY_INTERVAL_SECONDS)
            * _AGING_PRIORITY_STEP,
        )

    def _selection_reason(
        self,
        *,
        tasks_by_bundle: dict[str, list[QueuedTask]],
        dispatch_candidates: list[str],
        next_bundle_id: str,
    ) -> str:
        if len(tasks_by_bundle) == 1:
            return "only_remaining_bundle"
        if len(dispatch_candidates) == 1:
            return "lowest_dispatch_count"

        max_priority = max(
            self._effective_task_priority(tasks_by_bundle[bundle_id][0])
            for bundle_id in dispatch_candidates
        )
        highest_priority_candidates = [
            bundle_id
            for bundle_id in dispatch_candidates
            if self._effective_task_priority(tasks_by_bundle[bundle_id][0]) == max_priority
        ]
        if len(highest_priority_candidates) == 1:
            return "highest_effective_priority"
        if next_bundle_id in highest_priority_candidates:
            return "fifo_tiebreak"
        return "highest_effective_priority"

    def _evict_idle_runtimes_for_task(
        self,
        *,
        task: TaskRequest,
        requested_bundle: BundleConfig,
        cpu: float,
        ram_mb: int,
        vram_mb: int,
    ) -> None:
        for bundle in self._eviction_candidates(waiting_task=task):
            if bundle.bundle_id == requested_bundle.bundle_id:
                continue
            if self._runtime_for_bundle(bundle.bundle_id) is None:
                continue
            if self._active_bundle_task_count(bundle.bundle_id) > 0:
                continue

            self._stop_runtime_for_bundle(bundle)
            if self.resources.can_fit(cpu, ram_mb, vram_mb):
                return

    def _eviction_candidates(self, *, waiting_task: TaskRequest) -> list[BundleConfig]:
        auto_bundles = [
            bundle
            for bundle in self.bundles
            if bundle.warm_policy == "auto"
        ]
        always_bundles = [
            bundle
            for bundle in self.bundles
            if bundle.warm_policy == "always"
            and waiting_task.priority > bundle.priority_class
        ]
        return auto_bundles + always_bundles

    def _diagnose_queued_task(self, task_id: str) -> dict[str, str]:
        task = self.queue.get(task_id)
        bundle_id = self.selected_bundle_id(task_id)
        if bundle_id is None:
            return {"task_id": task_id, "bundle_id": "", "reason": "unrouted"}

        bundle = self._get_bundle(bundle_id)
        if not bundle.enabled:
            return {
                "task_id": task_id,
                "bundle_id": bundle.bundle_id,
                "reason": "bundle_disabled",
            }
        plugin = self._get_plugin(bundle.plugin_id)
        runtime = self._runtime_for_bundle(bundle.bundle_id)
        if self._current_bundle_state(bundle.bundle_id)["drain_mode"]:
            return {
                "task_id": task_id,
                "bundle_id": bundle.bundle_id,
                "reason": "runtime_draining",
            }
        if self._bundle_in_cooldown(bundle.bundle_id):
            return {
                "task_id": task_id,
                "bundle_id": bundle.bundle_id,
                "reason": "provider_cooldown",
            }
        if runtime is not None and not plugin.health_check(runtime):
            runtime = None

        estimate = plugin.estimate_resources(task.request, bundle, runtime)
        concurrency_limit = estimate.get("concurrency_limit")
        effective_concurrency_limit = bundle.max_parallel_requests
        if concurrency_limit is not None:
            effective_concurrency_limit = min(
                bundle.max_parallel_requests,
                concurrency_limit,
            )
        active_tasks = self._active_bundle_task_count(
            bundle.bundle_id,
            exclude_task_id=task_id,
        )
        if active_tasks >= effective_concurrency_limit:
            return {
                "task_id": task_id,
                "bundle_id": bundle.bundle_id,
                "reason": "concurrency_limit",
            }

        startup = estimate.get("startup_transient", {})
        resident = estimate.get("runtime_resident", {})
        request = estimate.get("request_active", {})
        needed_cpu = request.get("cpu", 0.0) + (
            0.0 if runtime else startup.get("cpu", 0.0) + resident.get("cpu", 0.0)
        )
        needed_ram = request.get("ram_mb", 0) + (
            0 if runtime else startup.get("ram_mb", 0) + resident.get("ram_mb", 0)
        )
        needed_vram = request.get("vram_mb", 0) + (
            0 if runtime else startup.get("vram_mb", 0) + resident.get("vram_mb", 0)
        )

        if self.resources.can_fit(needed_cpu, needed_ram, needed_vram):
            reason = "ready"
        elif self._eviction_blocked(task.request, bundle):
            reason = "eviction_policy_blocked"
        else:
            reason = "insufficient_resources"

        return {
            "task_id": task_id,
            "bundle_id": bundle.bundle_id,
            "reason": reason,
        }

    def _eviction_blocked(
        self,
        waiting_task: TaskRequest,
        requested_bundle: BundleConfig,
    ) -> bool:
        if self.resources is None:
            return False

        has_auto_runtime = False
        has_blocking_always_runtime = False
        for bundle in self.bundles:
            if bundle.bundle_id == requested_bundle.bundle_id:
                continue
            if self._runtime_for_bundle(bundle.bundle_id) is None:
                continue
            if self._active_bundle_task_count(bundle.bundle_id) > 0:
                continue

            if bundle.warm_policy == "auto":
                has_auto_runtime = True
            elif (
                bundle.warm_policy == "always"
                and waiting_task.priority <= bundle.priority_class
            ):
                has_blocking_always_runtime = True

        return has_blocking_always_runtime and not has_auto_runtime
