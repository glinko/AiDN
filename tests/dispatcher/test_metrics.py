"""Tests for DispatcherMetrics counters, gauges, and integration with NetworkDispatcher."""

from datetime import UTC, datetime, timedelta

import pytest

from aidn_hypervisor.dispatcher import (
    DispatcherError,
    DispatcherMetrics,
    DispatcherRoute,
    NetworkDispatcher,
    NetworkMessage,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.models import canonical_payload_bytes

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_message(*, message_id: str = "msg-1", route_generation: int = 1) -> NetworkMessage:
    body = {"value": "ok"}
    now = datetime.now(UTC)
    return NetworkMessage(
        message_id=message_id,
        message_type="VALIDATION_REPORT_TRANSFER",
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
        channel_id="validation-1",
        channel_class="VALIDATION",
        source_subject={"subject_type": "SERVICE", "subject_id": "validator-1"},
        destination_subject={"subject_type": "ENDPOINT", "subject_id": "ep-1"},
        source_sequence=1,
        route_generation=route_generation,
        runtime_generation=None,
        created_at=now.isoformat(),
        expiration=(now + timedelta(minutes=5)).isoformat(),
        payload_hash=canonical_payload_hash(body),
        payload_length=len(canonical_payload_bytes(body)),
        payload=body,
    )


def _make_dispatcher(*, maximum_queue_messages: int = 8) -> NetworkDispatcher:
    received: list[dict] = []
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
        maximum_queue_messages=maximum_queue_messages,
    )
    route = DispatcherRoute(
        destination_type="ENDPOINT",
        destination_id="ep-1",
        route_type="LOCAL_PROTOCOL_HANDLER",
        route_generation=1,
        allowed_source_types={"SERVICE"},
        allowed_channel_classes={"VALIDATION"},
        allowed_message_types={"VALIDATION_REPORT_TRANSFER"},
        created_at=datetime.now(UTC).isoformat(),
    )
    dispatcher.register_local_route(route, lambda p: received.append(p))
    return dispatcher


# ------------------------------------------------------------------
# Unit tests for DispatcherMetrics class
# ------------------------------------------------------------------

class TestDispatcherMetricsUnit:
    """Pure unit tests on the DispatcherMetrics class itself."""

    def test_initial_values_are_zero(self) -> None:
        m = DispatcherMetrics()
        assert m.messages_submitted == 0
        assert m.messages_delivered == 0
        assert m.messages_rejected == 0
        assert m.messages_dead_lettered == 0
        assert m.queue_depth == 0
        assert m.dead_letter_count == 0
        assert m.active_connections == 0

    def test_counter_increments(self) -> None:
        m = DispatcherMetrics()
        m.increment_submitted()
        m.increment_submitted()
        assert m.messages_submitted == 2
        m.increment_delivered()
        assert m.messages_delivered == 1
        m.increment_rejected()
        assert m.messages_rejected == 1
        m.increment_dead_lettered()
        assert m.messages_dead_lettered == 1

    def test_gauge_queue_depth(self) -> None:
        m = DispatcherMetrics()
        m.increment_queue_depth()
        m.increment_queue_depth()
        assert m.queue_depth == 2
        m.decrement_queue_depth()
        assert m.queue_depth == 1
        m.decrement_queue_depth()
        assert m.queue_depth == 0
        # floor at 0
        m.decrement_queue_depth()
        assert m.queue_depth == 0

    def test_gauge_dead_letter_count(self) -> None:
        m = DispatcherMetrics()
        m.increment_dead_letter_count()
        m.increment_dead_letter_count()
        assert m.dead_letter_count == 2
        m.decrement_dead_letter_count()
        assert m.dead_letter_count == 1

    def test_gauge_active_connections(self) -> None:
        m = DispatcherMetrics()
        m.increment_active_connections()
        assert m.active_connections == 1
        m.increment_active_connections()
        m.increment_active_connections()
        assert m.active_connections == 3
        m.decrement_active_connections()
        assert m.active_connections == 2

    def test_snapshot_returns_all_keys(self) -> None:
        m = DispatcherMetrics()
        m.increment_submitted()
        m.increment_delivered()
        m.increment_queue_depth()
        snap = m.snapshot()
        assert snap["messages_submitted"] == 1
        assert snap["messages_delivered"] == 1
        assert snap["messages_rejected"] == 0
        assert snap["messages_dead_lettered"] == 0
        assert snap["queue_depth"] == 1
        assert snap["dead_letter_count"] == 0
        assert snap["active_connections"] == 0

    def test_snapshot_is_isolated(self) -> None:
        """snapshot() returns a plain dict, not a live reference."""
        m = DispatcherMetrics()
        snap = m.snapshot()
        m.increment_submitted()
        assert snap["messages_submitted"] == 0  # snapshot is stale


# ------------------------------------------------------------------
# Integration tests: metrics wired into NetworkDispatcher
# ------------------------------------------------------------------

class TestDispatcherMetricsIntegration:
    """Metrics counters increment correctly during submit / drain_once."""

    def test_submit_increments_submitted_and_queue_depth(self) -> None:
        d = _make_dispatcher()
        msg = _make_message(message_id="m-1")
        d.submit(msg)
        assert d._metrics.messages_submitted == 1
        assert d._metrics.queue_depth == 1

    def test_drain_once_increments_delivered_and_decrements_queue_depth(self) -> None:
        d = _make_dispatcher()
        msg = _make_message(message_id="m-1")
        d.submit(msg)
        d.drain_once()
        assert d._metrics.messages_delivered == 1
        assert d._metrics.queue_depth == 0

    def test_submit_then_drain_full_lifecycle(self) -> None:
        d = _make_dispatcher()
        for i in range(3):
            d.submit(_make_message(message_id=f"m-{i}"))
        assert d._metrics.messages_submitted == 3
        assert d._metrics.queue_depth == 3

        for _ in range(3):
            d.drain_once()

        assert d._metrics.messages_delivered == 3
        assert d._metrics.queue_depth == 0

    def test_rejected_submit_increments_rejected_and_dead_letter(self) -> None:
        """A message with wrong channel_class should be rejected."""
        d = _make_dispatcher()
        bad = _make_message(message_id="bad-1")
        bad.channel_class = "UNKNOWN"
        with pytest.raises(DispatcherError):
            d.submit(bad)
        assert d._metrics.messages_rejected == 1
        assert d._metrics.messages_dead_lettered == 1
        assert d._metrics.dead_letter_count == 1

    def test_rejected_drain_increments_rejected(self) -> None:
        """A message whose route is revoked after submit should fail during drain."""
        d = _make_dispatcher()
        msg = _make_message(message_id="rev-1")
        d.submit(msg)
        # revoke the route so drain fails
        d.revoke_route(destination_type="ENDPOINT", destination_id="ep-1")
        with pytest.raises(DispatcherError):
            d.drain_once()
        assert d._metrics.messages_rejected == 1
        assert d._metrics.messages_dead_lettered == 1

    def test_dead_letter_retry_decrements_dead_letter_count(self) -> None:
        d = _make_dispatcher()
        bad = _make_message(message_id="dl-1")
        bad.channel_class = "UNKNOWN"
        with pytest.raises(DispatcherError):
            d.submit(bad)
        assert d._metrics.dead_letter_count == 1
        d.retry_dead_letter("dl-1")
        assert d._metrics.dead_letter_count == 0

    def test_purge_dead_letters_resets_dead_letter_count(self) -> None:
        d = _make_dispatcher()
        for i in range(3):
            bad = _make_message(message_id=f"dl-{i}")
            bad.channel_class = "UNKNOWN"
            with pytest.raises(DispatcherError):
                d.submit(bad)
        assert d._metrics.dead_letter_count == 3
        purged = d.purge_dead_letters()
        assert purged == 3
        assert d._metrics.dead_letter_count == 0

    def test_snapshot_reflects_dispatcher_state(self) -> None:
        d = _make_dispatcher()
        d.submit(_make_message(message_id="s1"))
        d.submit(_make_message(message_id="s2"))
        d.drain_once()
        snap = d._metrics.snapshot()
        assert snap["messages_submitted"] == 2
        assert snap["messages_delivered"] == 1
        assert snap["queue_depth"] == 1
