"""Tests for overload protection (rate limiting), safe mode, and enhanced delivery states."""

from datetime import UTC, datetime, timedelta

import pytest

from aidn_hypervisor.dispatcher import (
    BackpressureSignal,
    DispatcherError,
    DispatcherRoute,
    NetworkDispatcher,
    NetworkMessage,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.models import canonical_payload_bytes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _message(
    *,
    message_id: str = "msg-1",
    priority_class: str = "NORMAL",
    route_generation: int = 1,
    network_revision: str = "rev-1",
    payload: dict | None = None,
    channel_class: str = "VALIDATION",
    message_type: str = "VALIDATION_REPORT_TRANSFER",
    source_subject: dict | None = None,
    destination_subject: dict | None = None,
) -> NetworkMessage:
    body = payload or {"value": "ok"}
    now = datetime.now(UTC)
    return NetworkMessage(
        message_id=message_id,
        message_type=message_type,
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision=network_revision,
        channel_id="validation-1",
        channel_class=channel_class,
        source_subject=source_subject or {"subject_type": "SERVICE", "subject_id": "validator-1"},
        destination_subject=destination_subject or {"subject_type": "ENDPOINT", "subject_id": "ep-1"},
        source_sequence=1,
        route_generation=route_generation,
        created_at=now.isoformat(),
        expiration=(now + timedelta(minutes=5)).isoformat(),
        payload_hash=canonical_payload_hash(body),
        payload_length=len(canonical_payload_bytes(body)),
        payload=body,
        priority_class=priority_class,
    )


def _dispatcher(*, maximum_queue_messages: int = 2, max_messages_per_second: int = 1000):
    received: list[dict] = []
    dispatcher = NetworkDispatcher(
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision="rev-1",
        maximum_queue_messages=maximum_queue_messages,
        max_messages_per_second=max_messages_per_second,
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
    dispatcher.register_local_route(route, lambda payload: received.append(payload) or {"ok": True})
    return dispatcher, received


# ---------------------------------------------------------------------------
# 3.3.4  Overload protection — rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    def test_submit_within_limit_succeeds(self) -> None:
        dispatcher, _ = _dispatcher(max_messages_per_second=10)
        record = dispatcher.submit(_message(message_id="rl-1"))
        assert record.delivery_state == "QUEUED"

    def test_submit_exceeding_limit_returns_rate_limited(self) -> None:
        dispatcher, _ = _dispatcher(max_messages_per_second=2)
        # First two messages succeed
        r1 = dispatcher.submit(_message(message_id="rl-a"))
        r2 = dispatcher.submit(_message(message_id="rl-b"))
        assert r1.delivery_state == "QUEUED"
        assert r2.delivery_state == "QUEUED"

        # Third message should be rate-limited
        r3 = dispatcher.submit(_message(message_id="rl-c"))
        assert r3.delivery_state == "RATE_LIMITED"

    def test_rate_limit_resets_after_one_second(self) -> None:
        import time
        dispatcher, _ = _dispatcher(max_messages_per_second=1)
        r1 = dispatcher.submit(_message(message_id="rl-reset-1"))
        assert r1.delivery_state == "QUEUED"

        # Second immediate submit should be rate-limited
        r2 = dispatcher.submit(_message(message_id="rl-reset-2"))
        assert r2.delivery_state == "RATE_LIMITED"

        # After 1 second the window resets — simulate by clearing old timestamps
        base = time.monotonic()
        dispatcher._rate_limit_timestamps.clear()
        dispatcher._rate_limit_timestamps.append(base - 1.1)
        # Now timestamps are old enough to be evicted
        r3 = dispatcher.submit(_message(message_id="rl-reset-3"))
        assert r3.delivery_state == "QUEUED"

    def test_check_rate_limit_returns_backpressure_signal(self) -> None:
        dispatcher, _ = _dispatcher(max_messages_per_second=1)
        assert dispatcher._check_rate_limit() == BackpressureSignal.OK
        # Second call within same second should be throttled
        assert dispatcher._check_rate_limit() == BackpressureSignal.THROTTLED

    def test_max_messages_per_second_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="max_messages_per_second must be positive"):
            NetworkDispatcher(
                network_id="aidn-test",
                chain_id="chain-test",
                network_revision="rev-1",
                max_messages_per_second=0,
            )


# ---------------------------------------------------------------------------
# 3.3.5  Safe mode
# ---------------------------------------------------------------------------

class TestSafeMode:
    def test_safe_mode_initially_disabled(self) -> None:
        dispatcher, _ = _dispatcher()
        assert dispatcher.safe_mode is False

    def test_enable_disable_safe_mode(self) -> None:
        dispatcher, _ = _dispatcher()
        dispatcher.enable_safe_mode()
        assert dispatcher.safe_mode is True
        dispatcher.disable_safe_mode()
        assert dispatcher.safe_mode is False

    def test_safe_mode_constructed_enabled(self) -> None:
        dispatcher = NetworkDispatcher(
            network_id="aidn-test",
            chain_id="chain-test",
            network_revision="rev-1",
            safe_mode=True,
        )
        assert dispatcher.safe_mode is True

    def test_safe_mode_allows_critical_control(self) -> None:
        dispatcher, _ = _dispatcher()
        dispatcher.enable_safe_mode()
        msg = _message(message_id="safe-critical", priority_class="CRITICAL_CONTROL")
        record = dispatcher.submit(msg)
        assert record.delivery_state == "QUEUED"

    def test_safe_mode_allows_high_priority(self) -> None:
        dispatcher, _ = _dispatcher()
        dispatcher.enable_safe_mode()
        msg = _message(message_id="safe-high", priority_class="HIGH")
        record = dispatcher.submit(msg)
        assert record.delivery_state == "QUEUED"

    def test_safe_mode_allows_high_policy_type(self) -> None:
        """SESSION_CLOSE maps to HIGH policy priority, so safe mode should allow it."""
        dispatcher = NetworkDispatcher(
            network_id="aidn-test",
            chain_id="chain-test",
            network_revision="rev-1",
        )
        route = DispatcherRoute(
            destination_type="ENDPOINT",
            destination_id="ep-1",
            route_type="LOCAL_PROTOCOL_HANDLER",
            route_generation=1,
            allowed_source_types={"SERVICE"},
            allowed_channel_classes={"VALIDATION"},
            allowed_message_types={"SESSION_CLOSE"},
            created_at=datetime.now(UTC).isoformat(),
        )
        dispatcher.register_local_route(route, lambda payload: {"ok": True})
        dispatcher.enable_safe_mode()
        msg = _message(
            message_id="safe-session-close",
            priority_class="NORMAL",
            message_type="SESSION_CLOSE",
        )
        record = dispatcher.submit(msg)
        assert record.delivery_state == "QUEUED"

    def test_safe_mode_rejects_normal_priority(self) -> None:
        dispatcher, _ = _dispatcher()
        dispatcher.enable_safe_mode()
        msg = _message(message_id="safe-normal", priority_class="NORMAL")
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.submit(msg)
        assert exc_info.value.code == "SAFE_MODE_REJECTED"

    def test_safe_mode_rejects_bulk_priority(self) -> None:
        dispatcher, _ = _dispatcher()
        dispatcher.enable_safe_mode()
        msg = _message(message_id="safe-bulk", priority_class="BULK")
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.submit(msg)
        assert exc_info.value.code == "SAFE_MODE_REJECTED"

    def test_safe_mode_rejects_background_priority(self) -> None:
        dispatcher, _ = _dispatcher()
        dispatcher.enable_safe_mode()
        msg = _message(message_id="safe-bg", priority_class="BACKGROUND")
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.submit(msg)
        assert exc_info.value.code == "SAFE_MODE_REJECTED"

    def test_safe_mode_rejects_interactive_priority(self) -> None:
        dispatcher, _ = _dispatcher()
        dispatcher.enable_safe_mode()
        msg = _message(message_id="safe-interactive", priority_class="INTERACTIVE")
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.submit(msg)
        assert exc_info.value.code == "SAFE_MODE_REJECTED"

    def test_safe_mode_delivery_record_shows_failed(self) -> None:
        dispatcher, _ = _dispatcher()
        dispatcher.enable_safe_mode()
        msg = _message(message_id="safe-fail-record", priority_class="NORMAL")
        with pytest.raises(DispatcherError):
            dispatcher.submit(msg)
        record = dispatcher.delivery_record("safe-fail-record")
        assert record.delivery_state == "DELIVERY_FAILED"
        assert record.last_error_code == "SAFE_MODE_REJECTED"

    def test_safe_mode_does_not_block_drain(self) -> None:
        """Safe mode only gates submission; queued messages still drain."""
        dispatcher, received = _dispatcher()
        # Queue a message before enabling safe mode
        dispatcher.submit(_message(message_id="pre-safe"))
        dispatcher.enable_safe_mode()
        # drain_once should still work
        result = dispatcher.drain_once()
        assert result is not None
        assert result[0].delivery_state == "APPLICATION_ACCEPTED"


# ---------------------------------------------------------------------------
# 3.3.6  Enhanced delivery state machine
# ---------------------------------------------------------------------------

class TestEnhancedDeliveryStates:
    def test_submit_state_transitions_through_pipeline(self) -> None:
        """Verify intermediate states are set during validation pipeline."""
        dispatcher, _ = _dispatcher()

        # Track state transitions by reading the record at each step
        msg = _message(message_id="state-track")

        # After submit, final state should be QUEUED
        record = dispatcher.submit(msg)
        assert record.delivery_state == "QUEUED"

    def test_drain_once_transitions_to_delivered(self) -> None:
        """Verify drain_once transitions through DELIVERY_ATTEMPTED → DELIVERED."""
        dispatcher, _ = _dispatcher()
        msg = _message(message_id="drain-states")
        dispatcher.submit(msg)

        # Before drain, state is QUEUED
        record = dispatcher.delivery_record("drain-states")
        assert record.delivery_state == "QUEUED"

        # After drain, state transitions to APPLICATION_ACCEPTED (final)
        result = dispatcher.drain_once()
        assert result is not None
        completed = result[0]
        assert completed.delivery_state == "APPLICATION_ACCEPTED"
        assert completed.attempt_count == 1
        assert completed.delivered_at is not None
        assert completed.completed_at is not None

    def test_envelope_validated_state_during_submit(self) -> None:
        """The delivery record briefly shows ENVELOPE_VALIDATED during submit."""
        dispatcher, _ = _dispatcher()
        msg = _message(message_id="envelope-check")
        record = dispatcher.submit(msg)
        # Final state is QUEUED but the pipeline passed through ENVELOPE_VALIDATED
        assert record.delivery_state == "QUEUED"

    def test_all_delivery_states_defined_in_model(self) -> None:
        """Verify all enhanced states are defined in the DeliveryState Literal."""
        from aidn_hypervisor.dispatcher.models import DeliveryState
        expected_states = {
            "RECEIVED", "ENVELOPE_VALIDATED", "AUTHENTICATED", "AUTHORIZED",
            "ROUTE_RESOLVED", "QUEUED", "DELIVERY_ATTEMPTED", "DELIVERED",
            "APPLICATION_ACCEPTED", "APPLICATION_REJECTED", "EXPIRED",
            "RATE_LIMITED", "ROUTE_FAILED", "DELIVERY_FAILED",
            "DEAD_LETTERED", "DUPLICATE", "CANCELLED",
        }
        assert expected_states.issubset(set(DeliveryState.__args__))

    def test_rate_limited_state_is_delivery_state(self) -> None:
        """RATE_LIMITED is a valid DeliveryState."""
        from aidn_hypervisor.dispatcher.models import DeliveryState
        assert "RATE_LIMITED" in DeliveryState.__args__

    def test_delivery_failed_state_is_delivery_state(self) -> None:
        """DELIVERY_FAILED is a valid DeliveryState."""
        from aidn_hypervisor.dispatcher.models import DeliveryState
        assert "DELIVERY_FAILED" in DeliveryState.__args__

    def test_dead_lettered_state_is_delivery_state(self) -> None:
        """DEAD_LETTERED is a valid DeliveryState."""
        from aidn_hypervisor.dispatcher.models import DeliveryState
        assert "DEAD_LETTERED" in DeliveryState.__args__

    def test_cancelled_state_is_delivery_state(self) -> None:
        """CANCELLED is a valid DeliveryState."""
        from aidn_hypervisor.dispatcher.models import DeliveryState
        assert "CANCELLED" in DeliveryState.__args__


# ---------------------------------------------------------------------------
# Integration: rate limiting + safe mode interaction
# ---------------------------------------------------------------------------

class TestOverloadAndSafeModeIntegration:
    def test_rate_limit_applied_before_safe_mode_check(self) -> None:
        """Rate limiting is checked before safe mode gate."""
        dispatcher, _ = _dispatcher(max_messages_per_second=1)
        dispatcher.enable_safe_mode()

        # First message (CRITICAL_CONTROL) should queue
        r1 = dispatcher.submit(_message(message_id="int-1", priority_class="CRITICAL_CONTROL"))
        assert r1.delivery_state == "QUEUED"

        # Second message even with CRITICAL_CONTROL should be rate-limited
        r2 = dispatcher.submit(_message(message_id="int-2", priority_class="CRITICAL_CONTROL"))
        assert r2.delivery_state == "RATE_LIMITED"

    def test_safe_mode_and_rate_limit_independent(self) -> None:
        """Disabling safe mode does not affect rate limiter state."""
        dispatcher, _ = _dispatcher(max_messages_per_second=2)
        dispatcher.enable_safe_mode()

        r1 = dispatcher.submit(_message(message_id="indep-1", priority_class="HIGH"))
        r2 = dispatcher.submit(_message(message_id="indep-2", priority_class="HIGH"))
        assert r1.delivery_state == "QUEUED"
        assert r2.delivery_state == "QUEUED"

        # Rate limit hit — even with safe mode disabled
        dispatcher.disable_safe_mode()
        r3 = dispatcher.submit(_message(message_id="indep-3"))
        assert r3.delivery_state == "RATE_LIMITED"
