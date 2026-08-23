import pytest

from aidn_hypervisor.event_bus import InternalEventBus
from aidn_hypervisor.event_store import EventStore, EventStoreError


def _publish(bus: InternalEventBus, name: str):
    return bus.publish(event_type=f"aidn.node.{name}", message=name)


def test_event_store_retains_bounded_window_and_reports_stale_cursor() -> None:
    bus = InternalEventBus(hypervisor_id="node-1")
    store = EventStore(bus, retention_limit=2)

    _publish(bus, "one")
    _publish(bus, "two")
    _publish(bus, "three")

    result = store.query(after_sequence=0)

    assert [item["sequence"] for item in result["items"]] == [2, 3]
    assert result["oldest_sequence"] == 2
    assert result["head_sequence"] == 3
    assert result["cursor_status"] == "stale"


def test_event_store_inbox_is_at_least_once_until_acknowledged() -> None:
    bus = InternalEventBus(hypervisor_id="node-1")
    store = EventStore(bus)
    first = _publish(bus, "one")
    second = _publish(bus, "two")

    initial = store.inbox("agent-1")
    repeated = store.inbox("agent-1")
    assert [item["event_id"] for item in initial["items"]] == [first.event_id, second.event_id]
    assert [item["event_id"] for item in repeated["items"]] == [first.event_id, second.event_id]

    store.acknowledge("agent-1", [first.event_id])
    after_first_ack = store.inbox("agent-1")
    assert [item["event_id"] for item in after_first_ack["items"]] == [second.event_id]

    completed = store.acknowledge("agent-1", [second.event_id])
    assert completed["ack_sequence"] == 2
    assert store.inbox("agent-1")["items"] == []


def test_event_store_ack_is_idempotent_and_supports_out_of_order_delivery() -> None:
    bus = InternalEventBus(hypervisor_id="node-1")
    store = EventStore(bus)
    first = _publish(bus, "one")
    second = _publish(bus, "two")

    assert store.acknowledge("agent-1", [second.event_id])["ack_sequence"] == 0
    assert store.acknowledge("agent-1", [first.event_id])["ack_sequence"] == 2
    assert store.acknowledge("agent-1", [first.event_id])["ack_sequence"] == 2


def test_event_store_restores_events_and_inbox_cursor() -> None:
    bus = InternalEventBus(hypervisor_id="node-1")
    store = EventStore(bus)
    first = _publish(bus, "one")
    store.inbox("agent-1")
    store.acknowledge("agent-1", [first.event_id])
    snapshot_events = store.events()
    snapshot_inboxes = store.snapshot_inboxes()

    restored_bus = InternalEventBus(hypervisor_id="node-1")
    restored = EventStore(restored_bus)
    restored.restore(
        events=snapshot_events,
        sequence=bus.last_sequence,
        inboxes=snapshot_inboxes,
    )

    assert restored_bus.last_sequence == 1
    assert restored.inbox("agent-1")["ack_sequence"] == 1
    assert restored.inbox("agent-1")["items"] == []


def test_scoped_inbox_rejects_acknowledging_undelivered_events() -> None:
    bus = InternalEventBus(hypervisor_id="node-1")
    store = EventStore(bus)
    first = _publish(bus, "one")
    second = _publish(bus, "two")
    store.scope_inbox("agent-1")
    store.deliver_to_inbox("agent-1", second.event_id)

    with pytest.raises(EventStoreError, match="unknown event_id"):
        store.acknowledge("agent-1", [first.event_id])
    result = store.acknowledge("agent-1", [second.event_id])
    # The hidden first event is intentionally not part of this Inbox's
    # contiguous cursor, so acknowledging sequence 2 cannot skip it.
    assert result["ack_sequence"] == 0
