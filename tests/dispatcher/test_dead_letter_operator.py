"""Dead Letter operator surface — retry, purge, count."""

from datetime import UTC, datetime, timedelta

import pytest

from aidn_hypervisor.dispatcher import (
    DispatcherError,
    DispatcherRoute,
    NetworkDispatcher,
    NetworkMessage,
)
from aidn_hypervisor.dispatcher.models import (
    canonical_payload_bytes,
    canonical_payload_hash,
)

# ---------------------------------------------------------------------------
# Helpers — reuse the same message/dispatcher factory as test_service.py
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
        runtime_generation=None,
        created_at=now.isoformat(),
        expiration=(now + expiration_offset).isoformat(),
        payload_hash=canonical_payload_hash(body),
        payload_length=len(canonical_payload_bytes(body)),
        payload=body,
    )


def _dispatcher() -> NetworkDispatcher:
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
        allowed_message_types={"VALIDATION_REPORT_TRANSFER"},
        created_at=datetime.now(UTC).isoformat(),
    )
    dispatcher.register_local_route(route, lambda p: p)
    return dispatcher


def _create_dead_letter(dispatcher: NetworkDispatcher, message_id: str) -> None:
    """Submit a message that fails validation, creating a dead letter."""
    bad = _message(message_id=message_id, route_generation=99)
    with pytest.raises(DispatcherError) as exc_info:
        dispatcher.submit(bad)
    assert exc_info.value.code == "ROUTE_GENERATION_MISMATCH"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDeadLetterCount:
    def test_dead_letter_count_starts_at_zero(self) -> None:
        dispatcher = _dispatcher()
        assert dispatcher.dead_letter_count() == 0

    def test_dead_letter_count_increments_on_failure(self) -> None:
        dispatcher = _dispatcher()
        _create_dead_letter(dispatcher, "dl-1")
        assert dispatcher.dead_letter_count() == 1

    def test_dead_letter_count_accurate_for_multiple(self) -> None:
        dispatcher = _dispatcher()
        _create_dead_letter(dispatcher, "dl-a")
        _create_dead_letter(dispatcher, "dl-b")
        _create_dead_letter(dispatcher, "dl-c")
        assert dispatcher.dead_letter_count() == 3


class TestRetryDeadLetter:
    def test_retry_removes_dead_letter_and_returns_true(self) -> None:
        dispatcher = _dispatcher()
        _create_dead_letter(dispatcher, "retry-me")
        assert dispatcher.dead_letter_count() == 1

        ok = dispatcher.retry_dead_letter("retry-me")
        assert ok is True
        assert dispatcher.dead_letter_count() == 0

    def test_retry_returns_false_for_missing_dead_letter(self) -> None:
        dispatcher = _dispatcher()
        assert dispatcher.dead_letter_count() == 0
        ok = dispatcher.retry_dead_letter("does-not-exist")
        assert ok is False

    def test_retry_removes_correct_entry_among_many(self) -> None:
        dispatcher = _dispatcher()
        _create_dead_letter(dispatcher, "first")
        _create_dead_letter(dispatcher, "second")
        _create_dead_letter(dispatcher, "third")
        assert dispatcher.dead_letter_count() == 3

        ok = dispatcher.retry_dead_letter("second")
        assert ok is True
        assert dispatcher.dead_letter_count() == 2

        remaining_ids = {dl.message_id for dl in dispatcher.list_dead_letters()}
        assert remaining_ids == {"first", "third"}

    def test_retry_expired_dead_letter(self) -> None:
        """An expired message creates a non-retryable dead letter — retry_dead_letter
        still removes it from the DLQ (operator-driven removal)."""
        dispatcher = _dispatcher()
        expired = _message(
            message_id="expired-msg",
            expiration_offset=timedelta(seconds=-10),
        )
        with pytest.raises(DispatcherError) as exc_info:
            dispatcher.submit(expired)
        assert exc_info.value.code == "MESSAGE_EXPIRED"

        assert dispatcher.dead_letter_count() == 1
        dl = dispatcher.list_dead_letters()[0]
        assert dl.error_code == "MESSAGE_EXPIRED"
        assert dl.retryable is False

        ok = dispatcher.retry_dead_letter("expired-msg")
        assert ok is True
        assert dispatcher.dead_letter_count() == 0


class TestPurgeDeadLetters:
    def test_purge_clears_all_and_returns_count(self) -> None:
        dispatcher = _dispatcher()
        _create_dead_letter(dispatcher, "purge-a")
        _create_dead_letter(dispatcher, "purge-b")
        assert dispatcher.dead_letter_count() == 2

        purged = dispatcher.purge_dead_letters()
        assert purged == 2
        assert dispatcher.dead_letter_count() == 0

    def test_purge_on_empty_returns_zero(self) -> None:
        dispatcher = _dispatcher()
        purged = dispatcher.purge_dead_letters()
        assert purged == 0
        assert dispatcher.dead_letter_count() == 0
