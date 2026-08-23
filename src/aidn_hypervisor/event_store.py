"""Durable RFC-0072 event retention and per-agent inbox state.

The store deliberately sits on top of :class:`InternalEventBus`.  The bus is
the live ordering boundary; this module adds bounded retention and the
restart-safe acknowledgement cursor needed by disconnected agents. Hook
delivery can scope an Inbox to explicitly delivered event identities; signed
webhooks and external transports remain separate adapters.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aidn_hypervisor.event_bus import CanonicalEventEnvelope, InternalEventBus


class EventInboxSnapshot(BaseModel):
    """Persisted cursor state for one authorized agent identity."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(min_length=1)
    ack_sequence: int = Field(default=0, ge=0)
    last_read_sequence: int = Field(default=0, ge=0)
    acknowledged_event_ids: list[str] = Field(default_factory=list)
    # An agent without Hook subscriptions keeps the backwards-compatible
    # complete canonical stream.  Once a Hook targets it, the dispatcher
    # scopes the inbox and records only matching event identities here.
    scoped: bool = False
    delivered_event_ids: list[str] = Field(default_factory=list)
    replay_event_ids: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class EventStoreError(ValueError):
    """Raised for invalid cursor, inbox or acknowledgement requests."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class EventStore:
    """Bounded durable projection over the local canonical event bus.

    Events are retained by count.  An inbox does not advance its ack cursor on
    read, so a disconnected or crashed agent receives the same event again
    until it acknowledges it.  Acknowledgement is idempotent and advances the
    contiguous cursor only when all preceding retained events are acknowledged.
    """

    def __init__(
        self,
        event_bus: InternalEventBus,
        *,
        retention_limit: int = 10_000,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        if int(retention_limit) < 1:
            raise ValueError("retention_limit must be positive")
        self._bus = event_bus
        self.retention_limit = int(retention_limit)
        self._on_change = on_change
        self._inboxes: dict[str, EventInboxSnapshot] = {}
        self._lock = RLock()
        self._subscription_id = self._bus.subscribe(
            self._on_event,
            subscription_id="durable-event-store",
        )

    @property
    def subscription_id(self) -> str:
        return self._subscription_id

    def _changed(self) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change()
        except Exception:
            # A persistence observer must never make an authoritative event
            # producer fail.  The next state write remains a safe retry path.
            return

    def _on_event(self, _event: CanonicalEventEnvelope) -> None:
        self._bus.prune(max_events=self.retention_limit)
        with self._lock:
            self._prune_acknowledged_ids_locked()
        self._changed()

    def events(self, *, limit: int | None = None) -> list[CanonicalEventEnvelope]:
        return self._bus.events(limit=limit)

    def snapshot_inboxes(self) -> list[EventInboxSnapshot]:
        with self._lock:
            return [item.model_copy(deep=True) for item in self._inboxes.values()]

    def restore(
        self,
        *,
        events: Iterable[CanonicalEventEnvelope],
        sequence: int = 0,
        inboxes: Iterable[EventInboxSnapshot] = (),
    ) -> None:
        restored_events = [event.model_copy(deep=True) for event in events]
        restored_events.sort(key=lambda event: event.sequence)
        self._bus.restore_events(restored_events, sequence=sequence)
        self._bus.prune(max_events=self.retention_limit)
        with self._lock:
            self._inboxes = {
                item.agent_id: item.model_copy(deep=True) for item in inboxes
            }
            self._prune_acknowledged_ids_locked()

    def _prune_acknowledged_ids_locked(self) -> None:
        retained_ids = {event.event_id for event in self._bus.events()}
        for agent_id, state in list(self._inboxes.items()):
            state.acknowledged_event_ids = [
                event_id
                for event_id in state.acknowledged_event_ids
                if event_id in retained_ids
            ]
            state.delivered_event_ids = [
                event_id
                for event_id in state.delivered_event_ids
                if event_id in retained_ids
            ]
            state.replay_event_ids = [
                event_id
                for event_id in state.replay_event_ids
                if event_id in retained_ids
            ]
            self._inboxes[agent_id] = state

    def _inbox_locked(self, agent_id: str) -> EventInboxSnapshot:
        normalized = str(agent_id).strip()
        if not normalized:
            raise EventStoreError("agent_id is required")
        state = self._inboxes.get(normalized)
        if state is None:
            state = EventInboxSnapshot(agent_id=normalized, updated_at=_now())
            self._inboxes[normalized] = state
        return state

    def scope_inbox(self, agent_id: str, *, persist: bool = True) -> EventInboxSnapshot:
        """Limit one agent Inbox to events explicitly delivered by Hooks."""

        with self._lock:
            state = self._inbox_locked(agent_id)
            if not state.scoped:
                state.scoped = True
                state.updated_at = _now()
                self._inboxes[state.agent_id] = state
                result = state.model_copy(deep=True)
            else:
                result = state.model_copy(deep=True)
        if persist:
            self._changed()
        return result

    def deliver_to_inbox(
        self,
        agent_id: str,
        event_id: str,
        *,
        replay: bool = False,
    ) -> dict[str, Any]:
        """Record one Hook delivery in an agent's durable, scoped Inbox.

        The operation is idempotent.  The canonical event must still be in
        retention; a delivery cannot manufacture an event that was pruned.
        """

        normalized_agent = str(agent_id).strip()
        normalized_event = str(event_id).strip()
        if not normalized_agent or not normalized_event:
            raise EventStoreError("agent_id and event_id are required")
        with self._lock:
            retained = {event.event_id: event for event in self._bus.events()}
            if normalized_event not in retained:
                raise EventStoreError(f"unknown event_id: {normalized_event}")
            state = self._inbox_locked(normalized_agent)
            state.scoped = True
            if normalized_event not in state.delivered_event_ids:
                state.delivered_event_ids.append(normalized_event)
            if replay:
                # A replay must be visible even when the normal contiguous
                # acknowledgement cursor already passed the original event.
                if normalized_event in state.acknowledged_event_ids:
                    state.acknowledged_event_ids.remove(normalized_event)
                if normalized_event not in state.replay_event_ids:
                    state.replay_event_ids.append(normalized_event)
            state.updated_at = _now()
            self._inboxes[state.agent_id] = state
            response = {
                "agent_id": state.agent_id,
                "event_id": normalized_event,
                "delivered": True,
                "scoped": state.scoped,
            }
        self._changed()
        return response

    def query(
        self,
        *,
        after_sequence: int = 0,
        limit: int = 100,
        event_types: set[str] | None = None,
        resource_id: str | None = None,
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 500))
        cursor = max(0, int(after_sequence))
        retained = self._bus.events()
        oldest = retained[0].sequence if retained else self._bus.last_sequence + 1
        head = self._bus.last_sequence
        cursor_status = "stale" if retained and cursor < oldest - 1 else "ok"
        filtered = [
            event
            for event in retained
            if event.sequence > cursor
            and (event_types is None or event.event_type in event_types)
            and (resource_id is None or event.resource_id == resource_id)
        ]
        items = filtered[:bounded_limit]
        next_cursor = items[-1].sequence if items else cursor
        return {
            "items": [event.model_dump(mode="json") for event in items],
            "next_cursor": next_cursor,
            "head_sequence": head,
            "oldest_sequence": oldest if retained else None,
            "cursor_status": cursor_status,
            "retention_limit": self.retention_limit,
        }

    def inbox(
        self,
        agent_id: str,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        bounded_limit = max(1, min(int(limit), 500))
        with self._lock:
            state = self._inbox_locked(agent_id)
            retained = self._bus.events()
            oldest = retained[0].sequence if retained else self._bus.last_sequence + 1
            baseline_changed = False
            cursor_was_stale = bool(retained and state.ack_sequence < oldest - 1)
            if after_sequence is None and retained and state.ack_sequence < oldest - 1:
                # Events older than the retention window can no longer be
                # delivered.  Advance the durable baseline while surfacing
                # the loss as cursor_status=stale to the agent.
                state.ack_sequence = oldest - 1
                state.updated_at = _now()
                baseline_changed = True
            cursor = state.ack_sequence if after_sequence is None else max(0, int(after_sequence))
            acknowledged = set(state.acknowledged_event_ids)
            replay_ids = set(state.replay_event_ids)
            cursor_status = "stale" if cursor_was_stale or (retained and cursor < oldest - 1) else "ok"
            items = [
                event
                for event in retained
                if (event.sequence > cursor or event.event_id in replay_ids)
                and event.event_id not in acknowledged
                and (not state.scoped or event.event_id in state.delivered_event_ids)
            ][:bounded_limit]
            if items:
                state.last_read_sequence = max(
                    state.last_read_sequence,
                    items[-1].sequence,
                )
                state.updated_at = _now()
                self._inboxes[state.agent_id] = state
                changed = True
            else:
                changed = baseline_changed
            response = {
                "agent_id": state.agent_id,
                "items": [event.model_dump(mode="json") for event in items],
                "ack_sequence": state.ack_sequence,
                "last_read_sequence": state.last_read_sequence,
                "next_cursor": items[-1].sequence if items else cursor,
                "head_sequence": self._bus.last_sequence,
                "oldest_sequence": oldest if retained else None,
                "cursor_status": cursor_status,
                "retention_limit": self.retention_limit,
            }
        if changed:
            self._changed()
        return response

    def acknowledge(self, agent_id: str, event_ids: Iterable[str]) -> dict[str, Any]:
        ids = [str(event_id).strip() for event_id in event_ids if str(event_id).strip()]
        if not ids:
            raise EventStoreError("at least one event_id is required")
        if len(ids) > 500:
            raise EventStoreError("at most 500 event_ids may be acknowledged")
        with self._lock:
            state = self._inbox_locked(agent_id)
            retained = self._bus.events()
            by_id = {event.event_id: event for event in retained}
            already_known = set(state.acknowledged_event_ids)
            visible_ids = (
                set(state.delivered_event_ids) | set(state.replay_event_ids)
                if state.scoped
                else set(by_id)
            )
            unknown = [
                event_id
                for event_id in ids
                if event_id not in visible_ids and event_id not in already_known
            ]
            if unknown:
                raise EventStoreError(f"unknown event_id: {unknown[0]}")
            already_known.update(ids)
            state.acknowledged_event_ids = sorted(already_known)
            state.replay_event_ids = [
                event_id for event_id in state.replay_event_ids if event_id not in ids
            ]
            by_sequence = {
                event.sequence: event
                for event in retained
                if event.event_id in visible_ids
            }
            ack_sequence = state.ack_sequence
            while (
                ack_sequence + 1 in by_sequence
                and by_sequence[ack_sequence + 1].event_id in already_known
            ):
                ack_sequence += 1
            state.ack_sequence = ack_sequence
            state.last_read_sequence = max(
                state.last_read_sequence,
                max((by_id[event_id].sequence for event_id in ids if event_id in by_id), default=0),
            )
            state.updated_at = _now()
            self._inboxes[state.agent_id] = state
            response = {
                "agent_id": state.agent_id,
                "acknowledged_event_ids": ids,
                "ack_sequence": state.ack_sequence,
                "head_sequence": self._bus.last_sequence,
            }
        self._changed()
        return response
