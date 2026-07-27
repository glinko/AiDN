"""Restart-revalidation tests for the dispatcher service.

After a restore from persisted state, queued messages may have expired or
their routes may have changed.  restart_revalidation() walks the queue and
dead-letters any message that no longer passes validation.
"""
from datetime import UTC, datetime, timedelta

from aidn_hypervisor.dispatcher import (
    DispatcherRoute,
    NetworkDispatcher,
    NetworkMessage,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.models import (
    DeliveryRecord,
    canonical_payload_bytes,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _message(
    *,
    message_id: str = "msg-1",
    route_generation: int = 1,
    network_revision: str = "rev-1",
    payload: dict | None = None,
    channel_class: str = "VALIDATION",
    message_type: str = "VALIDATION_REPORT_TRANSFER",
    source_subject: dict | None = None,
    destination_subject: dict | None = None,
    expiration_offset: timedelta = timedelta(minutes=5),
    runtime_generation: int | None = None,
) -> NetworkMessage:
    """Build a NetworkMessage with sensible defaults."""
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
        runtime_generation=runtime_generation,
        created_at=now.isoformat(),
        expiration=(now + expiration_offset).isoformat(),
        payload_hash=canonical_payload_hash(body),
        payload_length=len(canonical_payload_bytes(body)),
        payload=body,
    )


def _expired_message(message_id: str = "msg-expired") -> NetworkMessage:
    """Build a message whose expiration is already in the past."""
    return _message(
        message_id=message_id,
        expiration_offset=timedelta(seconds=-60),
    )


def _dispatcher(*, maximum_queue_messages: int = 16) -> NetworkDispatcher:
    """Create a dispatcher with a single active route for ep-1."""
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
    dispatcher.register_local_route(route, lambda payload: payload)
    return dispatcher


def _queue_message(
    dispatcher: NetworkDispatcher,
    message: NetworkMessage,
    *,
    with_delivery_record: bool = True,
) -> None:
    """Directly place a message in the queue (simulates restore scenario)."""
    dispatcher._queue.append(message)
    dispatcher.store.queued_messages[message.message_id] = message
    if with_delivery_record:
        dispatcher._delivery_records[message.message_id] = DeliveryRecord(
            message_id=message.message_id,
            source_subject=message.source_subject,
            destination_subject=message.destination_subject,
            route_generation=message.route_generation,
            delivery_state="QUEUED",
            received_at=datetime.now(UTC).isoformat(),
            payload_hash=message.payload_hash,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRestartRevalidation:
    """restart_revalidation() dead-letters invalid queued messages."""

    def test_noop_when_queue_empty(self) -> None:
        dispatcher = _dispatcher()
        assert dispatcher.restart_revalidation() == 0
        assert dispatcher.queue_depth == 0

    def test_noop_when_all_messages_valid(self) -> None:
        dispatcher = _dispatcher()
        m1 = _message(message_id="valid-1")
        m2 = _message(message_id="valid-2")
        dispatcher.submit(m1)
        dispatcher.submit(m2)

        dead = dispatcher.restart_revalidation()
        assert dead == 0
        assert dispatcher.queue_depth == 2

    def test_expired_messages_dead_lettered(self) -> None:
        dispatcher = _dispatcher()
        valid = _message(message_id="valid-1")
        expired = _expired_message(message_id="expired-1")
        dispatcher.submit(valid)
        _queue_message(dispatcher, expired)

        dead = dispatcher.restart_revalidation()
        assert dead == 1
        assert dispatcher.queue_depth == 1
        dl = dispatcher.list_dead_letters()
        assert any(dlr.message_id == "expired-1" for dlr in dl)

    def test_stale_route_generation_dead_lettered(self) -> None:
        dispatcher = _dispatcher()
        valid = _message(message_id="valid-1", route_generation=1)
        stale = _message(message_id="stale-1", route_generation=2)
        dispatcher.submit(valid)
        _queue_message(dispatcher, stale)

        dead = dispatcher.restart_revalidation()
        assert dead == 1
        assert dispatcher.queue_depth == 1
        dl = dispatcher.list_dead_letters()
        assert any(dlr.message_id == "stale-1" for dlr in dl)

    def test_revoked_route_dead_letters_queued_messages(self) -> None:
        dispatcher = _dispatcher()
        msg = _message(message_id="msg-revoked")
        dispatcher.submit(msg)

        # Revoke the route
        dispatcher.revoke_route(destination_type="ENDPOINT", destination_id="ep-1")

        dead = dispatcher.restart_revalidation()
        assert dead == 1
        assert dispatcher.queue_depth == 0
        dl = dispatcher.list_dead_letters()
        assert any(dlr.message_id == "msg-revoked" for dlr in dl)
        assert any(dlr.error_code == "ROUTE_REVOKED" for dlr in dl)

    def test_mixed_valid_and_invalid(self) -> None:
        dispatcher = _dispatcher()
        v1 = _message(message_id="v1")
        v2 = _message(message_id="v2")
        expired = _expired_message(message_id="exp-1")
        stale = _message(message_id="stale-1", route_generation=2)

        dispatcher.submit(v1)
        _queue_message(dispatcher, expired)
        dispatcher.submit(v2)
        _queue_message(dispatcher, stale)

        dead = dispatcher.restart_revalidation()
        assert dead == 2
        assert dispatcher.queue_depth == 2

    def test_domain_mismatch_dead_lettered(self) -> None:
        dispatcher = _dispatcher()
        bad_domain = _message(
            message_id="bad-domain",
            network_revision="rev-wrong",
        )
        _queue_message(dispatcher, bad_domain)

        dead = dispatcher.restart_revalidation()
        assert dead == 1
        assert dispatcher.queue_depth == 0
        dl = dispatcher.list_dead_letters()
        assert any(dlr.message_id == "bad-domain" for dlr in dl)
        assert any(dlr.error_code == "NETWORK_REVISION_MISMATCH" for dlr in dl)

    def test_missing_delivery_record_handled(self) -> None:
        """Messages in the queue without a delivery record are still handled."""
        dispatcher = _dispatcher()
        orphan = _message(message_id="orphan-1")
        _queue_message(dispatcher, orphan, with_delivery_record=False)

        dead = dispatcher.restart_revalidation()
        # Message is valid so it should NOT be dead-lettered
        assert dead == 0
        assert dispatcher.queue_depth == 1

    def test_returns_count_of_dead_lettered(self) -> None:
        dispatcher = _dispatcher()
        expired1 = _expired_message(message_id="exp-1")
        expired2 = _expired_message(message_id="exp-2")
        _queue_message(dispatcher, expired1)
        _queue_message(dispatcher, expired2)

        dead = dispatcher.restart_revalidation()
        assert dead == 2
        assert dispatcher.queue_depth == 0
