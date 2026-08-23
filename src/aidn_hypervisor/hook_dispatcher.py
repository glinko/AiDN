"""RFC-0072 Hook subscriptions and bounded event delivery.

The canonical Event Store remains the source of truth for event payloads and
acknowledgement cursors.  This module owns the smaller delivery projection:
which agent subscribed to which event, retry timing, dead letters, and the
operator-visible counters needed to diagnose a disconnected agent.

Delivery is deliberately pull-friendly.  A live MCP callback can be bound by
an embedding runtime, while every durable Hook is also written to the target
agent Inbox.  No background thread is used: publication and explicit
``dispatch_due`` calls make progress, keeping tests and restart recovery
deterministic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aidn_hypervisor.event_bus import (
    CanonicalEventEnvelope,
    EventSeverity,
    InternalEventBus,
)
from aidn_hypervisor.event_store import EventStore, EventStoreError

HookDeliveryMode = Literal["DURABLE_INBOX", "MCP_LIVE"]
HookDeliveryState = Literal[
    "PENDING",
    "DELIVERING",
    "DELIVERED",
    "RETRYING",
    "FAILED",
    "DEAD_LETTER",
    "EXPIRED",
]

_SEVERITY_RANK = {
    EventSeverity.DEBUG: 0,
    EventSeverity.INFO: 1,
    EventSeverity.NOTICE: 2,
    EventSeverity.WARNING: 3,
    EventSeverity.ERROR: 4,
    EventSeverity.CRITICAL: 5,
}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Hook timestamps must include a timezone")
    return parsed.astimezone(UTC)


class HookEventFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_types: set[str] = Field(default_factory=set)
    resource_ids: set[str] = Field(default_factory=set)
    severity_minimum: EventSeverity | None = None

    @model_validator(mode="after")
    def _validate_filter(self) -> HookEventFilter:
        if not self.event_types and not self.resource_ids and self.severity_minimum is None:
            raise ValueError("Hook event_filter must constrain event type, resource, or severity")
        return self


class HookDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hook_id: str = Field(min_length=1, max_length=128)
    owner_operator_id: str = Field(min_length=1, max_length=128)
    target_agent_id: str = Field(min_length=1, max_length=256)
    enabled: bool = True
    event_filter: HookEventFilter
    delivery_mode: HookDeliveryMode = "DURABLE_INBOX"
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff_seconds: float = Field(default=1.0, ge=0, le=3600)
    created_at: str
    expires_at: str | None = None
    hook_revision: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _validate_timestamps(self) -> HookDefinition:
        _parse(self.created_at)
        if self.expires_at is not None:
            _parse(self.expires_at)
        return self


class HookDeliveryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_id: str = Field(min_length=1)
    hook_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    target_agent_id: str = Field(min_length=1)
    delivery_mode: HookDeliveryMode
    status: HookDeliveryState
    attempt_count: int = Field(default=0, ge=0)
    next_attempt_at: str | None = None
    last_error: str | None = None
    created_at: str
    updated_at: str
    delivered_at: str | None = None
    replayed: bool = False


class HookMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events_matched: int = 0
    deliveries_created: int = 0
    deliveries_attempted: int = 0
    events_delivered: int = 0
    events_retried: int = 0
    events_failed: int = 0
    events_dead_lettered: int = 0
    events_replayed: int = 0
    queue_depth: int = 0
    dead_letter_count: int = 0


LiveHandler = Callable[[dict[str, Any], CanonicalEventEnvelope], object]


class HookDispatcherError(ValueError):
    """Stable operator-facing errors for Hook lifecycle operations."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class HookDispatcher:
    """Deterministic Hook delivery projection over the local Event Bus."""

    def __init__(
        self,
        event_bus: InternalEventBus,
        event_store: EventStore,
        *,
        on_change: Callable[[], None] | None = None,
        hooks: Iterable[HookDefinition] = (),
        deliveries: Iterable[HookDeliveryRecord] = (),
        dead_letters: Iterable[HookDeliveryRecord] = (),
        metrics: HookMetrics | None = None,
    ) -> None:
        self._bus = event_bus
        self._store = event_store
        self._on_change = on_change
        self._hooks: dict[str, HookDefinition] = {item.hook_id: item for item in hooks}
        self._deliveries: dict[str, HookDeliveryRecord] = {
            item.delivery_id: item for item in deliveries
        }
        self._dead_letters: list[HookDeliveryRecord] = list(dead_letters)
        self._metrics = metrics.model_copy(deep=True) if metrics is not None else HookMetrics()
        self._live_handlers: dict[str, LiveHandler] = {}
        self._lock = RLock()
        self._bus.subscribe(self._on_event, subscription_id="hook-dispatcher")
        self._reconcile_metrics()

    def _changed(self) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change()
        except Exception:
            # Hook observability must not break the event producer.
            return

    @staticmethod
    def _delivery_id(hook_id: str, event_id: str, *, replayed: bool = False) -> str:
        suffix = ":replay" if replayed else ""
        digest = hashlib.sha256(f"{hook_id}:{event_id}{suffix}".encode()).hexdigest()[:32]
        return f"hook-delivery-{digest}"

    def _matches(self, hook: HookDefinition, event: CanonicalEventEnvelope) -> bool:
        event_filter = hook.event_filter
        if event_filter.event_types and event.event_type not in event_filter.event_types:
            return False
        if event_filter.resource_ids and event.resource_id not in event_filter.resource_ids:
            return False
        if (
            event_filter.severity_minimum is not None
            and _SEVERITY_RANK[event.severity] < _SEVERITY_RANK[event_filter.severity_minimum]
        ):
            return False
        return True

    def _expired(self, hook: HookDefinition, now: datetime) -> bool:
        return bool(hook.expires_at and _parse(hook.expires_at) <= now)

    def _on_event(self, event: CanonicalEventEnvelope) -> None:
        created = 0
        with self._lock:
            now = _now()
            for hook in self._hooks.values():
                if not hook.enabled or self._expired(hook, now) or not self._matches(hook, event):
                    continue
                delivery_id = self._delivery_id(hook.hook_id, event.event_id)
                if delivery_id in self._deliveries:
                    continue
                self._deliveries[delivery_id] = HookDeliveryRecord(
                    delivery_id=delivery_id,
                    hook_id=hook.hook_id,
                    event_id=event.event_id,
                    target_agent_id=hook.target_agent_id,
                    delivery_mode=hook.delivery_mode,
                    status="PENDING",
                    created_at=_iso(now),
                    updated_at=_iso(now),
                )
                self._metrics.events_matched += 1
                self._metrics.deliveries_created += 1
                created += 1
            self._reconcile_metrics()
        if created:
            self.dispatch_due()
            self._changed()

    def _reconcile_metrics(self) -> None:
        self._metrics.queue_depth = sum(
            record.status in {"PENDING", "RETRYING", "DELIVERING"}
            for record in self._deliveries.values()
        )
        self._metrics.dead_letter_count = len(self._dead_letters)

    def create_hook(
        self,
        *,
        hook_id: str,
        owner_operator_id: str,
        target_agent_id: str,
        event_filter: HookEventFilter | dict[str, Any],
        delivery_mode: HookDeliveryMode = "DURABLE_INBOX",
        max_attempts: int = 3,
        retry_backoff_seconds: float = 1.0,
        expires_at: str | None = None,
    ) -> HookDefinition:
        with self._lock:
            if hook_id in self._hooks:
                raise HookDispatcherError("MCP_HOOK_EXISTS", f"Hook already exists: {hook_id}")
            hook = HookDefinition(
                hook_id=hook_id,
                owner_operator_id=owner_operator_id,
                target_agent_id=target_agent_id,
                event_filter=(
                    event_filter
                    if isinstance(event_filter, HookEventFilter)
                    else HookEventFilter.model_validate(event_filter)
                ),
                delivery_mode=delivery_mode,
                max_attempts=max_attempts,
                retry_backoff_seconds=retry_backoff_seconds,
                created_at=_iso(_now()),
                expires_at=expires_at,
            )
            self._hooks[hook.hook_id] = hook
            self._store.scope_inbox(hook.target_agent_id)
        self._changed()
        return hook.model_copy(deep=True)

    def list_hooks(self, *, owner_operator_id: str | None = None) -> list[HookDefinition]:
        with self._lock:
            hooks = list(self._hooks.values())
        if owner_operator_id is not None:
            hooks = [item for item in hooks if item.owner_operator_id == owner_operator_id]
        return [item.model_copy(deep=True) for item in hooks]

    def get_hook(self, hook_id: str) -> HookDefinition:
        with self._lock:
            hook = self._hooks.get(hook_id)
            if hook is None:
                raise HookDispatcherError("MCP_HOOK_NOT_FOUND", f"Unknown Hook: {hook_id}")
            return hook.model_copy(deep=True)

    def update_hook(self, hook_id: str, **updates: Any) -> HookDefinition:
        with self._lock:
            current = self._hooks.get(hook_id)
            if current is None:
                raise HookDispatcherError("MCP_HOOK_NOT_FOUND", f"Unknown Hook: {hook_id}")
            updates = dict(updates)
            if "event_filter" in updates and not isinstance(updates["event_filter"], HookEventFilter):
                updates["event_filter"] = HookEventFilter.model_validate(updates["event_filter"])
            updates["hook_revision"] = current.hook_revision + 1
            payload = current.model_dump(mode="python")
            payload.update(updates)
            updated = HookDefinition.model_validate(payload)
            self._hooks[hook_id] = updated
            self._store.scope_inbox(updated.target_agent_id)
        self._changed()
        return updated.model_copy(deep=True)

    def delete_hook(self, hook_id: str) -> bool:
        with self._lock:
            if hook_id not in self._hooks:
                raise HookDispatcherError("MCP_HOOK_NOT_FOUND", f"Unknown Hook: {hook_id}")
            self._hooks.pop(hook_id)
        self._changed()
        return True

    def test_hook(self, hook_id: str) -> dict[str, Any]:
        """Validate a Hook delivery target without creating an operational event.

        A test must not advance the Event Store cursor, create a durable inbox
        entry, or increment delivery counters.  It is intentionally a small
        readiness probe: live Hooks report whether an adapter is connected and
        durable Hooks report that the target inbox is available.
        """

        hook = self.get_hook(hook_id)
        if not hook.enabled:
            return {
                "hook_id": hook.hook_id,
                "target_agent_id": hook.target_agent_id,
                "delivery_mode": hook.delivery_mode,
                "status": "PAUSED",
                "synthetic": True,
            }
        if hook.delivery_mode == "MCP_LIVE":
            with self._lock:
                connected = hook.target_agent_id in self._live_handlers
            return {
                "hook_id": hook.hook_id,
                "target_agent_id": hook.target_agent_id,
                "delivery_mode": hook.delivery_mode,
                "status": "READY" if connected else "NOT_CONNECTED",
                "synthetic": True,
            }
        return {
            "hook_id": hook.hook_id,
            "target_agent_id": hook.target_agent_id,
            "delivery_mode": hook.delivery_mode,
            "status": "READY",
            "synthetic": True,
        }

    def register_live_agent(self, agent_id: str, handler: LiveHandler) -> None:
        with self._lock:
            self._live_handlers[str(agent_id)] = handler

    def unregister_live_agent(self, agent_id: str) -> None:
        with self._lock:
            self._live_handlers.pop(str(agent_id), None)

    def _event_by_id(self, event_id: str) -> CanonicalEventEnvelope:
        for event in self._store.events():
            if event.event_id == event_id:
                return event
        raise HookDispatcherError("MCP_EVENT_NOT_FOUND", f"Unknown event: {event_id}")

    def _deliver(self, record: HookDeliveryRecord, event: CanonicalEventEnvelope) -> None:
        if record.delivery_mode == "DURABLE_INBOX":
            self._store.deliver_to_inbox(
                record.target_agent_id,
                record.event_id,
                replay=record.replayed,
            )
            return
        handler = self._live_handlers.get(record.target_agent_id)
        if handler is None:
            raise HookDispatcherError(
                "MCP_HOOK_DELIVERY_FAILED",
                f"No MCP live target is connected for agent {record.target_agent_id}",
            )
        handler(event.model_dump(mode="json"), event)

    def dispatch_due(self, *, now: datetime | None = None) -> int:
        """Attempt due deliveries once, applying bounded exponential backoff."""

        current_time = (now or _now()).astimezone(UTC)
        delivered = 0
        changed = False
        with self._lock:
            due = [
                item
                for item in self._deliveries.values()
                if item.status in {"PENDING", "RETRYING"}
                and (item.next_attempt_at is None or _parse(item.next_attempt_at) <= current_time)
            ]
            for record in due:
                hook = self._hooks.get(record.hook_id)
                if hook is None or not hook.enabled or self._expired(hook, current_time):
                    updated = record.model_copy(
                        update={"status": "EXPIRED", "updated_at": _iso(current_time)}
                    )
                    self._deliveries[record.delivery_id] = updated
                    changed = True
                    continue
                try:
                    event = self._event_by_id(record.event_id)
                except HookDispatcherError as error:
                    updated = record.model_copy(
                        update={
                            "status": "DEAD_LETTER",
                            "last_error": str(error)[:512],
                            "updated_at": _iso(current_time),
                        }
                    )
                    self._deliveries[record.delivery_id] = updated
                    self._dead_letters.append(updated)
                    self._metrics.events_failed += 1
                    self._metrics.events_dead_lettered += 1
                    changed = True
                    continue
                attempts = record.attempt_count + 1
                in_flight = record.model_copy(
                    update={
                        "status": "DELIVERING",
                        "attempt_count": attempts,
                        "updated_at": _iso(current_time),
                    }
                )
                self._deliveries[record.delivery_id] = in_flight
                self._metrics.deliveries_attempted += 1
                try:
                    self._deliver(in_flight, event)
                except (HookDispatcherError, EventStoreError, Exception) as error:
                    message = str(error) or type(error).__name__
                    if attempts < hook.max_attempts:
                        retry_at = current_time + timedelta(
                            seconds=hook.retry_backoff_seconds * (2 ** (attempts - 1))
                        )
                        updated = in_flight.model_copy(
                            update={
                                "status": "RETRYING",
                                "next_attempt_at": _iso(retry_at),
                                "last_error": message[:512],
                                "updated_at": _iso(current_time),
                            }
                        )
                        self._metrics.events_retried += 1
                    else:
                        updated = in_flight.model_copy(
                            update={
                                "status": "DEAD_LETTER",
                                "next_attempt_at": None,
                                "last_error": message[:512],
                                "updated_at": _iso(current_time),
                            }
                        )
                        self._dead_letters.append(updated)
                        self._metrics.events_dead_lettered += 1
                        self._metrics.events_failed += 1
                    self._deliveries[record.delivery_id] = updated
                    changed = True
                    continue
                updated = in_flight.model_copy(
                    update={
                        "status": "DELIVERED",
                        "next_attempt_at": None,
                        "last_error": None,
                        "delivered_at": _iso(current_time),
                        "updated_at": _iso(current_time),
                    }
                )
                self._deliveries[record.delivery_id] = updated
                self._metrics.events_delivered += 1
                delivered += 1
                changed = True
            self._reconcile_metrics()
        if changed:
            self._changed()
        return delivered

    def list_deliveries(
        self,
        *,
        hook_id: str | None = None,
        status: HookDeliveryState | None = None,
        limit: int = 100,
    ) -> list[HookDeliveryRecord]:
        with self._lock:
            records = list(self._deliveries.values())
        if hook_id is not None:
            records = [item for item in records if item.hook_id == hook_id]
        if status is not None:
            records = [item for item in records if item.status == status]
        records.sort(key=lambda item: item.created_at, reverse=True)
        return [item.model_copy(deep=True) for item in records[: max(1, min(int(limit), 500))]]

    def dead_letters(self, *, limit: int = 100) -> list[HookDeliveryRecord]:
        with self._lock:
            records = list(self._dead_letters)
        return [item.model_copy(deep=True) for item in records[-max(1, min(int(limit), 500)) :]]

    def retry_dead_letter(self, delivery_id: str) -> HookDeliveryRecord:
        with self._lock:
            index = next(
                (index for index, item in enumerate(self._dead_letters) if item.delivery_id == delivery_id),
                None,
            )
            if index is None:
                raise HookDispatcherError("MCP_HOOK_REPLAY_UNAVAILABLE", f"Unknown dead letter: {delivery_id}")
            record = self._dead_letters.pop(index)
            queued = record.model_copy(
                update={
                    "status": "PENDING",
                    "attempt_count": 0,
                    "next_attempt_at": None,
                    "last_error": None,
                    "updated_at": _iso(_now()),
                }
            )
            self._deliveries[delivery_id] = queued
            self._reconcile_metrics()
        self.dispatch_due()
        self._changed()
        return self._deliveries[delivery_id].model_copy(deep=True)

    def replay_event(
        self,
        event_id: str,
        *,
        owner_operator_id: str | None = None,
        target_agent_id: str | None = None,
    ) -> list[HookDeliveryRecord]:
        event = self._event_by_id(event_id)
        created: list[HookDeliveryRecord] = []
        with self._lock:
            for hook in self._hooks.values():
                if owner_operator_id is not None and hook.owner_operator_id != owner_operator_id:
                    continue
                if target_agent_id is not None and hook.target_agent_id != target_agent_id:
                    continue
                if not hook.enabled or self._expired(hook, _now()) or not self._matches(hook, event):
                    continue
                digest = hashlib.sha256(
                    f"{hook.hook_id}:{event.event_id}:replay:{_now().timestamp()}".encode()
                ).hexdigest()[:32]
                delivery_id = f"hook-delivery-replay-{digest}"
                record = HookDeliveryRecord(
                    delivery_id=delivery_id,
                    hook_id=hook.hook_id,
                    event_id=event.event_id,
                    target_agent_id=hook.target_agent_id,
                    delivery_mode=hook.delivery_mode,
                    status="PENDING",
                    created_at=_iso(_now()),
                    updated_at=_iso(_now()),
                    replayed=True,
                )
                self._deliveries[delivery_id] = record
                created.append(record)
            self._metrics.events_replayed += 1
            self._metrics.deliveries_created += len(created)
            self._reconcile_metrics()
        self.dispatch_due()
        self._changed()
        return [self._deliveries[item.delivery_id].model_copy(deep=True) for item in created]

    def metrics(self) -> dict[str, Any]:
        with self._lock:
            self._reconcile_metrics()
            return self._metrics.model_dump(mode="json")

    def snapshot(self) -> dict[str, list[Any] | dict[str, Any]]:
        with self._lock:
            return {
                "hooks": [item.model_copy(deep=True) for item in self._hooks.values()],
                "deliveries": [item.model_copy(deep=True) for item in self._deliveries.values()],
                "dead_letters": [item.model_copy(deep=True) for item in self._dead_letters],
                "metrics": self._metrics.model_copy(deep=True),
            }

    def restore(
        self,
        *,
        hooks: Iterable[HookDefinition] = (),
        deliveries: Iterable[HookDeliveryRecord] = (),
        dead_letters: Iterable[HookDeliveryRecord] = (),
        metrics: HookMetrics | None = None,
    ) -> None:
        with self._lock:
            self._hooks = {item.hook_id: item.model_copy(deep=True) for item in hooks}
            self._deliveries = {item.delivery_id: item.model_copy(deep=True) for item in deliveries}
            self._dead_letters = [item.model_copy(deep=True) for item in dead_letters]
            self._metrics = metrics.model_copy(deep=True) if metrics is not None else HookMetrics()
            for hook in self._hooks.values():
                self._store.scope_inbox(hook.target_agent_id, persist=False)
            self._reconcile_metrics()
