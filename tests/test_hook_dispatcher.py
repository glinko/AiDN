from datetime import UTC, datetime, timedelta

from aidn_hypervisor.event_bus import InternalEventBus
from aidn_hypervisor.event_store import EventStore
from aidn_hypervisor.hook_dispatcher import HookDispatcher, HookEventFilter


def _event(bus: InternalEventBus, event_type: str, *, resource_id: str = "provider-1"):
    return bus.publish(
        event_type=event_type,
        message=event_type,
        source="provider",
        resource_type="provider",
        resource_id=resource_id,
    )


def test_durable_hook_filters_and_delivers_to_scoped_inbox():
    bus = InternalEventBus(hypervisor_id="node-1")
    store = EventStore(bus)
    dispatcher = HookDispatcher(bus, store)
    dispatcher.create_hook(
        hook_id="provider-watch",
        owner_operator_id="operator-1",
        target_agent_id="agent-1",
        event_filter=HookEventFilter(event_types={"aidn.provider.failed"}),
    )

    ignored = _event(bus, "aidn.provider.ready")
    matched = _event(bus, "aidn.provider.failed")

    inbox = store.inbox("agent-1")
    assert [item["event_id"] for item in inbox["items"]] == [matched.event_id]
    assert ignored.event_id not in {item["event_id"] for item in inbox["items"]}
    assert dispatcher.metrics()["events_delivered"] == 1
    assert dispatcher.list_deliveries(status="DELIVERED")[0].event_id == matched.event_id


def test_live_delivery_retries_then_dead_letters_and_can_replay():
    bus = InternalEventBus(hypervisor_id="node-1")
    store = EventStore(bus)
    dispatcher = HookDispatcher(bus, store)
    dispatcher.create_hook(
        hook_id="live-watch",
        owner_operator_id="operator-1",
        target_agent_id="agent-1",
        event_filter=HookEventFilter(event_types={"aidn.node.failed"}),
        delivery_mode="MCP_LIVE",
        max_attempts=2,
        retry_backoff_seconds=0,
    )

    event = _event(bus, "aidn.node.failed", resource_id="node-1")
    assert dispatcher.list_deliveries(status="RETRYING")[0].attempt_count == 1
    dispatcher.dispatch_due(now=datetime.now(UTC) + timedelta(seconds=1))
    dead_letters = dispatcher.dead_letters()
    assert len(dead_letters) == 1
    assert dead_letters[0].event_id == event.event_id
    assert dispatcher.metrics()["events_dead_lettered"] == 1

    received: list[str] = []
    dispatcher.register_live_agent("agent-1", lambda _payload, envelope: received.append(envelope.event_id))
    replayed = dispatcher.replay_event(event.event_id)
    assert len(replayed) == 1
    assert replayed[0].replayed is True
    assert received == [event.event_id]
    assert dispatcher.metrics()["events_replayed"] == 1


def test_durable_replay_is_visible_after_original_acknowledgement():
    bus = InternalEventBus(hypervisor_id="node-1")
    store = EventStore(bus)
    dispatcher = HookDispatcher(bus, store)
    dispatcher.create_hook(
        hook_id="watch",
        owner_operator_id="operator-1",
        target_agent_id="agent-1",
        event_filter=HookEventFilter(event_types={"aidn.node.ready"}),
    )
    event = _event(bus, "aidn.node.ready", resource_id="node-1")
    store.acknowledge("agent-1", [event.event_id])
    assert store.inbox("agent-1")["items"] == []

    dispatcher.replay_event(event.event_id)
    replayed = store.inbox("agent-1")
    assert [item["event_id"] for item in replayed["items"]] == [event.event_id]


def test_hook_snapshot_restores_definitions_and_delivery_metrics():
    bus = InternalEventBus(hypervisor_id="node-1")
    store = EventStore(bus)
    dispatcher = HookDispatcher(bus, store)
    dispatcher.create_hook(
        hook_id="watch",
        owner_operator_id="operator-1",
        target_agent_id="agent-1",
        event_filter=HookEventFilter(severity_minimum="WARNING"),
    )
    _event(bus, "aidn.provider.failed")
    snapshot = dispatcher.snapshot()

    restored = HookDispatcher(bus, store)
    restored.restore(
        hooks=snapshot["hooks"],
        deliveries=snapshot["deliveries"],
        dead_letters=snapshot["dead_letters"],
        metrics=snapshot["metrics"],
    )
    assert restored.get_hook("watch").target_agent_id == "agent-1"
    assert restored.metrics()["events_delivered"] == 1
