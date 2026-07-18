from collections import deque
from datetime import datetime, timezone
from typing import Callable

from aidn_hypervisor.dispatcher.models import (
    DeadLetterRecord,
    DeliveryRecord,
    DispatcherRoute,
    NetworkMessage,
)


class DispatcherError(ValueError):
    def __init__(self, code: str, stage: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


class NetworkDispatcher:
    """Transport-independent RFC-0042 v0.3 dispatcher core."""

    def __init__(
        self,
        *,
        network_id: str,
        chain_id: str,
        network_revision: str,
        maximum_queue_messages: int = 256,
    ) -> None:
        if maximum_queue_messages <= 0:
            raise ValueError("maximum_queue_messages must be positive")
        self.network_id = network_id
        self.chain_id = chain_id
        self.network_revision = network_revision
        self.maximum_queue_messages = maximum_queue_messages
        self._routes: dict[tuple[str, str], DispatcherRoute] = {}
        self._handlers: dict[tuple[str, str], Callable[[dict], object]] = {}
        self._queue: deque[NetworkMessage] = deque()
        self._delivery_records: dict[str, DeliveryRecord] = {}
        self._processed_messages: dict[str, str] = {}
        self._dead_letters: list[DeadLetterRecord] = []

    def register_local_route(
        self,
        route: DispatcherRoute,
        handler: Callable[[dict], object],
    ) -> None:
        key = (route.destination_type, route.destination_id)
        previous = self._routes.get(key)
        if previous is not None and route.route_generation <= previous.route_generation:
            raise DispatcherError(
                "ROUTE_GENERATION_MISMATCH",
                "route_update",
                "replacement route must increment route_generation",
            )
        if not route.route_type.startswith("LOCAL_"):
            raise ValueError("register_local_route requires a local route type")
        self._routes[key] = route
        self._handlers[key] = handler

    def submit(self, message: NetworkMessage) -> DeliveryRecord:
        now = self._now()
        record = DeliveryRecord(
            message_id=message.message_id,
            source_subject=message.source_subject,
            destination_subject=message.destination_subject,
            route_generation=message.route_generation,
            delivery_state="RECEIVED",
            received_at=now,
            payload_hash=message.payload_hash,
        )
        existing_hash = self._processed_messages.get(message.message_id)
        if existing_hash is not None:
            if existing_hash != message.payload_hash:
                raise DispatcherError(
                    "MESSAGE_REPLAYED",
                    "replay_guard",
                    "Message ID conflicts with an already processed payload",
                )
            duplicate = record.model_copy(update={"delivery_state": "DUPLICATE"})
            self._delivery_records[message.message_id] = duplicate
            return duplicate
        try:
            self._validate_domain(message)
            self._validate_expiration(message)
            route = self._resolve_and_authorize(message)
            if len(self._queue) >= self.maximum_queue_messages:
                raise DispatcherError("QUEUE_FULL", "admission", "Dispatcher queue is full")
            queued = record.model_copy(
                update={"delivery_state": "QUEUED", "queued_at": now}
            )
            self._queue.append(message)
            self._delivery_records[message.message_id] = queued
            return queued
        except DispatcherError as exc:
            self._reject(record, message, exc)
            raise

    def drain_once(self) -> tuple[DeliveryRecord, object] | None:
        if not self._queue:
            return None
        message = self._queue.popleft()
        record = self._delivery_records[message.message_id]
        try:
            self._validate_expiration(message)
            route = self._resolve_and_authorize(message)
            key = (route.destination_type, route.destination_id)
            handler = self._handlers[key]
            result = handler(message.payload)
            completed = record.model_copy(
                update={
                    "delivery_state": "APPLICATION_ACCEPTED",
                    "delivered_at": self._now(),
                    "completed_at": self._now(),
                    "attempt_count": record.attempt_count + 1,
                }
            )
            self._processed_messages[message.message_id] = message.payload_hash
            self._delivery_records[message.message_id] = completed
            return completed, result
        except (DispatcherError, Exception) as exc:
            if not isinstance(exc, DispatcherError):
                exc = DispatcherError(
                    "APPLICATION_REJECTED",
                    "application",
                    str(exc),
                )
            self._reject(record, message, exc)
            raise exc

    def delivery_record(self, message_id: str) -> DeliveryRecord:
        return self._delivery_records[message_id]

    def list_dead_letters(self) -> list[DeadLetterRecord]:
        return list(self._dead_letters)

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    def _validate_domain(self, message: NetworkMessage) -> None:
        if message.network_id != self.network_id:
            raise DispatcherError("NETWORK_ID_MISMATCH", "domain", "Network ID mismatch")
        if message.chain_id != self.chain_id:
            raise DispatcherError("CHAIN_ID_MISMATCH", "domain", "Chain ID mismatch")
        if message.network_revision != self.network_revision:
            raise DispatcherError(
                "NETWORK_REVISION_MISMATCH",
                "domain",
                "Network Revision mismatch",
            )

    def _validate_expiration(self, message: NetworkMessage) -> None:
        if datetime.fromisoformat(message.expiration) <= datetime.now(timezone.utc):
            raise DispatcherError("MESSAGE_EXPIRED", "expiration", "Message expired")

    def _resolve_and_authorize(self, message: NetworkMessage) -> DispatcherRoute:
        key = (
            message.destination_subject.subject_type,
            message.destination_subject.subject_id,
        )
        route = self._routes.get(key)
        if route is None:
            raise DispatcherError("ROUTE_NOT_FOUND", "routing", "No destination route")
        if route.route_state != "ACTIVE":
            code = {
                "STALE": "ROUTE_STALE",
                "DRAINING": "ROUTE_DRAINING",
                "REVOKED": "ROUTE_REVOKED",
            }.get(route.route_state, "ROUTE_NOT_FOUND")
            raise DispatcherError(code, "routing", f"Route is {route.route_state}")
        if route.route_generation != message.route_generation:
            raise DispatcherError(
                "ROUTE_GENERATION_MISMATCH",
                "routing",
                "Message Route Generation is stale",
            )
        if message.source_subject.subject_type not in route.allowed_source_types:
            raise DispatcherError(
                "SOURCE_NOT_AUTHORIZED",
                "authorization",
                "Source subject type is not authorized",
            )
        if message.channel_class not in route.allowed_channel_classes:
            raise DispatcherError(
                "CHANNEL_NOT_AUTHORIZED",
                "authorization",
                "Channel is not authorized for route",
            )
        if message.message_type not in route.allowed_message_types:
            raise DispatcherError(
                "MESSAGE_PROFILE_UNSUPPORTED",
                "authorization",
                "Message type is not authorized for route",
            )
        return route

    def _reject(
        self,
        record: DeliveryRecord,
        message: NetworkMessage,
        error: DispatcherError,
    ) -> None:
        failed_at = self._now()
        state = "APPLICATION_REJECTED" if error.stage == "application" else "ROUTE_FAILED"
        if error.code == "MESSAGE_EXPIRED":
            state = "EXPIRED"
        rejected = record.model_copy(
            update={
                "delivery_state": state,
                "completed_at": failed_at,
                "last_error_code": error.code,
            }
        )
        self._delivery_records[message.message_id] = rejected
        self._dead_letters.append(
            DeadLetterRecord(
                message_id=message.message_id,
                source_subject=message.source_subject,
                destination_subject=message.destination_subject,
                message_type=message.message_type,
                route_generation=message.route_generation,
                failure_stage=error.stage,
                error_code=error.code,
                received_at=record.received_at,
                failed_at=failed_at,
                payload_hash=message.payload_hash,
            )
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
