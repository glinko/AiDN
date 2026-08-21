from __future__ import annotations

from aidn_hypervisor.event_bus import (
    EventDataClass,
    EventSeverity,
    InternalEventBus,
)


def test_internal_event_bus_normalizes_order_identity_hash_and_redaction() -> None:
    bus = InternalEventBus(hypervisor_id="gpu-3090", network_id="chain-test")

    event = bus.publish(
        event_type="aidn.provider.failed",
        message="provider exited",
        bundle_id="bundle-qwen",
        details={
            "provider_instance_id": "pi-1",
            "token": "must-not-leak",
            "revision": 3,
        },
        correlation_id="incident-1",
        causation_id="action-1",
    )

    assert event.sequence == 1
    assert event.hypervisor_id == "gpu-3090"
    assert event.network_id == "chain-test"
    assert event.resource_type == "bundle"
    assert event.resource_id == "bundle-qwen"
    assert event.resource_revision == "3"
    assert event.severity is EventSeverity.ERROR
    assert event.data_class is EventDataClass.SECRET
    assert event.requires_attention is True
    assert event.requires_action is True
    assert event.payload == {"redacted": True}
    assert event.event_id.startswith("evt_")
    assert event.event_hash.startswith("sha256:")
    assert len(event.event_hash.removeprefix("sha256:")) == 64


def test_internal_event_bus_subscriber_failure_does_not_break_producer() -> None:
    bus = InternalEventBus(hypervisor_id="node-1")
    delivered = []

    def broken(_event) -> None:
        raise RuntimeError("observer unavailable")

    bus.subscribe(broken, subscription_id="broken")
    bus.subscribe(delivered.append, subscription_id="healthy")

    first = bus.publish(event_type="aidn.node.ready", message="ready")
    second = bus.publish(event_type="aidn.node.degraded", message="degraded")

    assert [item.sequence for item in delivered] == [1, 2]
    assert bus.last_sequence == 2
    assert bus.events(limit=1) == [second]
    assert first.requires_attention is False
    assert second.severity is EventSeverity.WARNING


def test_internal_event_bus_accepts_explicit_policy_fields() -> None:
    bus = InternalEventBus(hypervisor_id="node-1")

    event = bus.publish(
        event_type="aidn.custom.notice",
        message="operator review",
        source="test-producer",
        severity="notice",
        data_class="public",
        resource_type="custom",
        resource_id="custom-1",
        requires_attention=True,
        requires_action=False,
    )

    assert event.source == "test-producer"
    assert event.severity is EventSeverity.NOTICE
    assert event.data_class is EventDataClass.PUBLIC
    assert event.resource_type == "custom"
    assert event.resource_id == "custom-1"
    assert event.requires_attention is True
    assert event.requires_action is False


def test_internal_event_bus_allocates_unique_generated_subscription_ids() -> None:
    bus = InternalEventBus(hypervisor_id="node-1")

    first = bus.subscribe(lambda _event: None)
    second = bus.subscribe(lambda _event: None)

    assert (first, second) == ("sub_1", "sub_2")
