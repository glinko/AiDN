from datetime import datetime, timedelta, timezone

import pytest

from aidn_hypervisor.dispatcher import (
    DispatcherError,
    DispatcherRoute,
    NetworkDispatcher,
    NetworkMessage,
    canonical_payload_hash,
)
from aidn_hypervisor.dispatcher.models import canonical_payload_bytes


def _message(
    *,
    message_id: str = "msg-1",
    route_generation: int = 1,
    network_revision: str = "rev-1",
    payload: dict | None = None,
) -> NetworkMessage:
    body = payload or {"value": "ok"}
    now = datetime.now(timezone.utc)
    return NetworkMessage(
        message_id=message_id,
        message_type="VALIDATION_REPORT_TRANSFER",
        network_id="aidn-test",
        chain_id="chain-test",
        network_revision=network_revision,
        channel_id="validation-1",
        channel_class="VALIDATION",
        source_subject={"subject_type": "SERVICE", "subject_id": "validator-1"},
        destination_subject={"subject_type": "ENDPOINT", "subject_id": "ep-1"},
        source_sequence=1,
        route_generation=route_generation,
        created_at=now.isoformat(),
        expiration=(now + timedelta(minutes=5)).isoformat(),
        payload_hash=canonical_payload_hash(body),
        payload_length=len(canonical_payload_bytes(body)),
        payload=body,
    )


def _dispatcher(*, maximum_queue_messages: int = 2):
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
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    dispatcher.register_local_route(route, lambda payload: received.append(payload) or {"ok": True})
    return dispatcher, received


def test_dispatcher_queues_delivers_and_deduplicates_message() -> None:
    dispatcher, received = _dispatcher()
    message = _message()

    queued = dispatcher.submit(message)
    delivered, result = dispatcher.drain_once()
    duplicate = dispatcher.submit(message)

    assert queued.delivery_state == "QUEUED"
    assert delivered.delivery_state == "APPLICATION_ACCEPTED"
    assert result == {"ok": True}
    assert received == [{"value": "ok"}]
    assert duplicate.delivery_state == "DUPLICATE"


def test_dispatcher_rejects_stale_route_generation_before_handler() -> None:
    dispatcher, received = _dispatcher()

    with pytest.raises(DispatcherError) as error:
        dispatcher.submit(_message(route_generation=2))

    assert error.value.code == "ROUTE_GENERATION_MISMATCH"
    assert received == []
    assert dispatcher.list_dead_letters()[0].failure_stage == "routing"


def test_dispatcher_revalidates_route_generation_before_delivery() -> None:
    dispatcher, received = _dispatcher()
    dispatcher.submit(_message())
    dispatcher.register_local_route(
        DispatcherRoute(
            destination_type="ENDPOINT",
            destination_id="ep-1",
            route_type="LOCAL_PROTOCOL_HANDLER",
            route_generation=2,
            allowed_source_types={"SERVICE"},
            allowed_channel_classes={"VALIDATION"},
            allowed_message_types={"VALIDATION_REPORT_TRANSFER"},
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
        lambda payload: received.append(payload),
    )

    with pytest.raises(DispatcherError) as error:
        dispatcher.drain_once()

    assert error.value.code == "ROUTE_GENERATION_MISMATCH"
    assert received == []


def test_dispatcher_enforces_domain_authorization_and_bounded_queue() -> None:
    dispatcher, _ = _dispatcher(maximum_queue_messages=1)

    with pytest.raises(DispatcherError) as revision_error:
        dispatcher.submit(_message(network_revision="rev-old"))
    assert revision_error.value.code == "NETWORK_REVISION_MISMATCH"

    dispatcher.submit(_message(message_id="msg-valid"))
    with pytest.raises(DispatcherError) as queue_error:
        dispatcher.submit(_message(message_id="msg-overflow"))
    assert queue_error.value.code == "QUEUE_FULL"


def test_dispatcher_rejects_conflicting_processed_replay() -> None:
    dispatcher, _ = _dispatcher()
    dispatcher.submit(_message())
    dispatcher.drain_once()

    with pytest.raises(DispatcherError) as error:
        dispatcher.submit(_message(payload={"value": "changed"}))

    assert error.value.code == "MESSAGE_REPLAYED"
