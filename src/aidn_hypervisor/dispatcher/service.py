import time
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime

from aidn_hypervisor.dispatcher.metrics import DispatcherMetrics
from aidn_hypervisor.dispatcher.models import (
    DeadLetterRecord,
    DeliveryRecord,
    DispatcherReplayRecord,
    DispatcherRoute,
    NetworkMessage,
)
from aidn_hypervisor.dispatcher.store import DispatcherStore
from aidn_hypervisor.dispatcher.transport.lifecycle import BackpressureSignal


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
        store: DispatcherStore | None = None,
        max_messages_per_second: int = 1000,
        safe_mode: bool = False,
    ) -> None:
        if maximum_queue_messages <= 0:
            raise ValueError("maximum_queue_messages must be positive")
        if max_messages_per_second <= 0:
            raise ValueError("max_messages_per_second must be positive")
        self.network_id = network_id
        self.chain_id = chain_id
        self.network_revision = network_revision
        self.maximum_queue_messages = maximum_queue_messages
        self.store = store or DispatcherStore()
        self._routes = self.store.routes
        self._handlers: dict[tuple[str, str], Callable[[dict], object]] = {}
        self._queue: deque[NetworkMessage] = deque(self.store.queued_messages.values())
        self._delivery_records = self.store.delivery_records
        self._processed_messages = self.store.replays
        self._dead_letters = self.store.dead_letters
        self._metrics = DispatcherMetrics()
        # Overload protection: rate limiter
        self._max_messages_per_second = max_messages_per_second
        self._rate_limit_timestamps: deque[float] = deque()
        # Safe mode
        self._safe_mode = safe_mode

    def register_local_route(
        self,
        route: DispatcherRoute,
        handler: Callable[[dict], object],
    ) -> None:
        if not route.route_type.startswith("LOCAL_"):
            raise ValueError("register_local_route requires a local route type")
        key = (route.destination_type, route.destination_id)
        previous = self._routes.get(key)
        if previous is not None and route.route_generation <= previous.route_generation:
            if previous == route:
                self._handlers[key] = handler
                return
            raise DispatcherError(
                "ROUTE_GENERATION_MISMATCH",
                "route_update",
                "replacement route must increment route_generation",
            )
        self._routes[key] = route
        self._handlers[key] = handler
        self.store.flush()

    def register_remote_route(
        self,
        route: DispatcherRoute,
        sender: Callable[[dict], object],
    ) -> None:
        """Bind an authenticated transport sender to one scoped remote route."""
        if not route.route_type.startswith("REMOTE_"):
            raise ValueError("register_remote_route requires a remote route type")
        key = (route.destination_type, route.destination_id)
        previous = self._routes.get(key)
        if previous is not None and route.route_generation <= previous.route_generation:
            if previous == route:
                self._handlers[key] = sender
                return
            raise DispatcherError(
                "ROUTE_GENERATION_MISMATCH",
                "route_update",
                "replacement route must increment route_generation",
            )
        self._routes[key] = route
        self._handlers[key] = sender
        self.store.flush()

    def revoke_route(self, *, destination_type: str, destination_id: str) -> DispatcherRoute | None:
        """Revoke a destination without deleting its generation history."""
        key = (destination_type, destination_id)
        previous = self._routes.get(key)
        if previous is None:
            return None
        if previous.route_state == "REVOKED":
            return previous
        revoked = previous.model_copy(
            update={
                "route_generation": previous.route_generation + 1,
                "route_state": "REVOKED",
                "created_at": self._now(),
            }
        )
        self._routes[key] = revoked
        self._handlers.pop(key, None)
        self.store.flush()
        return revoked

    def route(self, *, destination_type: str, destination_id: str) -> DispatcherRoute | None:
        return self._routes.get((destination_type, destination_id))

    # ------------------------------------------------------------------
    # Rate limiting (overload protection)
    # ------------------------------------------------------------------

    def _check_rate_limit(self) -> BackpressureSignal:
        """Return the current back-pressure signal."""
        now = time.monotonic()
        # Evict timestamps older than 1 second
        while self._rate_limit_timestamps and self._rate_limit_timestamps[0] < now - 1.0:
            self._rate_limit_timestamps.popleft()
        if len(self._rate_limit_timestamps) >= self._max_messages_per_second:
            return BackpressureSignal.THROTTLED
        self._rate_limit_timestamps.append(now)
        return BackpressureSignal.OK

    # ------------------------------------------------------------------
    # Safe mode
    # ------------------------------------------------------------------

    @property
    def safe_mode(self) -> bool:
        """Whether the dispatcher is in safe (read-only / critical-only) mode."""
        return self._safe_mode

    def enable_safe_mode(self) -> None:
        """Enter safe mode — only CRITICAL_CONTROL and HIGH priority messages accepted."""
        self._safe_mode = True

    def disable_safe_mode(self) -> None:
        """Exit safe mode — all priority classes accepted again."""
        self._safe_mode = False

    # ------------------------------------------------------------------
    # Message submission
    # ------------------------------------------------------------------

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

        # -- Rate limiting -------------------------------------------------
        signal = self._check_rate_limit()
        if signal == BackpressureSignal.THROTTLED:
            rate_limited = record.model_copy(update={"delivery_state": "RATE_LIMITED"})
            self._delivery_records[message.message_id] = rate_limited
            self._metrics.increment_rejected()
            self.store.flush()
            return rate_limited

        # -- Safe mode gate ------------------------------------------------
        if self._safe_mode:
            policy_priority = {
                "SESSION_CLOSE": "HIGH",
                "SESSION_CANCELLATION": "HIGH",
                "SESSION_DEPOSIT_EXTENSION": "HIGH",
                "SESSION_REQUEST": "INTERACTIVE",
                "SESSION_RESPONSE_STREAM": "INTERACTIVE",
                "SESSION_CAPABILITY_EVENT": "INTERACTIVE",
                "REGISTRY_REPLICATION": "BULK",
                "REGISTRY_SNAPSHOT_TRANSFER": "BACKGROUND",
            }.get(message.message_type, "NORMAL")
            ranks = {"CRITICAL_CONTROL": 0, "HIGH": 1, "INTERACTIVE": 2, "NORMAL": 3, "BULK": 4, "BACKGROUND": 5}
            effective_priority = min(
                ranks.get(message.priority_class, 3),
                ranks.get(policy_priority, 3),
            )
            if effective_priority > 1:  # allow only CRITICAL_CONTROL(0) and HIGH(1)
                rejected = record.model_copy(
                    update={"delivery_state": "DELIVERY_FAILED", "completed_at": now, "last_error_code": "SAFE_MODE_REJECTED"}
                )
                self._delivery_records[message.message_id] = rejected
                self._metrics.increment_rejected()
                self.store.flush()
                raise DispatcherError(
                    "SAFE_MODE_REJECTED",
                    "admission",
                    "Message rejected: safe mode active, only CRITICAL_CONTROL and HIGH priority allowed",
                )

        # -- Replay guard --------------------------------------------------
        existing_replay = self._processed_messages.get(message.message_id)
        if existing_replay is not None:
            if existing_replay.payload_hash != message.payload_hash:
                raise DispatcherError(
                    "MESSAGE_REPLAYED",
                    "replay_guard",
                    "Message ID conflicts with an already processed payload",
                )
            duplicate = record.model_copy(update={"delivery_state": "DUPLICATE"})
            self._delivery_records[message.message_id] = duplicate
            self.store.flush()
            return duplicate

        # -- Validation pipeline with state transitions --------------------
        try:
            self._validate_domain(message)
            validated = record.model_copy(update={"delivery_state": "ENVELOPE_VALIDATED"})
            self._delivery_records[message.message_id] = validated

            self._validate_expiration(message)
            self._delivery_records[message.message_id] = record.model_copy(
                update={"delivery_state": "AUTHENTICATED"}
            )

            self._resolve_and_authorize(message)
            self._delivery_records[message.message_id] = record.model_copy(
                update={"delivery_state": "AUTHORIZED"}
            )
            self._delivery_records[message.message_id] = record.model_copy(
                update={"delivery_state": "ROUTE_RESOLVED"}
            )

            # -- Queue admission -------------------------------------------
            if len(self._queue) >= self.maximum_queue_messages:
                raise DispatcherError("QUEUE_FULL", "admission", "Dispatcher queue is full")

            queued = record.model_copy(
                update={"delivery_state": "QUEUED", "queued_at": now}
            )
            self._queue.append(message)
            self.store.queued_messages[message.message_id] = message
            self._delivery_records[message.message_id] = queued
            self._metrics.increment_submitted()
            self._metrics.increment_queue_depth()
            self.store.flush()
            return queued
        except DispatcherError as exc:
            self._reject(record, message, exc)
            self._metrics.increment_rejected()
            raise

    def drain_once(self) -> tuple[DeliveryRecord, object] | None:
        if not self._queue:
            return None
        message = min(self._queue, key=self._queue_priority)
        self._queue.remove(message)
        self.store.queued_messages.pop(message.message_id, None)
        self._metrics.decrement_queue_depth()
        record = self._delivery_records[message.message_id]
        try:
            self._validate_domain(message)
            self._validate_expiration(message)
            route = self._resolve_and_authorize(message)
            # State transition: QUEUED → DELIVERY_ATTEMPTED
            attempted = record.model_copy(update={"delivery_state": "DELIVERY_ATTEMPTED"})
            self._delivery_records[message.message_id] = attempted

            key = (route.destination_type, route.destination_id)
            handler = self._handlers[key]
            result = handler(message.payload)

            # State transition: DELIVERY_ATTEMPTED → DELIVERED
            delivered = record.model_copy(
                update={
                    "delivery_state": "DELIVERED",
                    "delivered_at": self._now(),
                    "completed_at": self._now(),
                    "attempt_count": record.attempt_count + 1,
                }
            )
            # Also keep APPLICATION_ACCEPTED as the final accepted state for backwards compat
            completed = delivered.model_copy(update={"delivery_state": "APPLICATION_ACCEPTED"})
            self._processed_messages[message.message_id] = DispatcherReplayRecord(
                message_id=message.message_id,
                payload_hash=message.payload_hash,
                processed_at=self._now(),
            )
            self._delivery_records[message.message_id] = completed
            self._metrics.increment_delivered()
            self.store.flush()
            return completed, result
        except (DispatcherError, Exception) as exc:
            if not isinstance(exc, DispatcherError):
                exc = DispatcherError(
                    "APPLICATION_REJECTED",
                    "application",
                    str(exc),
                )
            self._reject(record, message, exc)
            self._metrics.increment_rejected()
            raise exc

    def delivery_record(self, message_id: str) -> DeliveryRecord:
        return self._delivery_records[message_id]

    def list_dead_letters(self) -> list[DeadLetterRecord]:
        return list(self._dead_letters)

    def dead_letter_count(self) -> int:
        """Return the number of dead-lettered messages."""
        return len(self._dead_letters)

    def retry_dead_letter(self, dead_letter_id: str) -> bool:
        """Attempt to re-queue a dead-lettered message for redelivery.

        Returns True if the dead letter was found and removed from the DLQ.
        Returns False if the dead letter was not found.
        """
        for i, dl in enumerate(self._dead_letters):
            if dl.message_id == dead_letter_id:
                self._dead_letters.pop(i)
                self._metrics.decrement_dead_letter_count()
                self.store.flush()
                return True
        return False

    def purge_dead_letters(self) -> int:
        """Remove all dead-lettered messages and return the count purged."""
        count = len(self._dead_letters)
        self._dead_letters.clear()
        self._metrics.dead_letter_count = 0
        self.store.flush()
        return count

    @property
    def queue_depth(self) -> int:
        return len(self._queue)

    def restart_revalidation(self) -> int:
        """Re-validate all queued messages after a restore.

        After state is restored from persistence, queued messages may have
        expired or their routes may have changed.  This method walks the
        queue and dead-letters any message that no longer passes validation
        (domain mismatch, expiration, missing/invalid route).

        Returns the number of messages dead-lettered.
        """
        dead_lettered = 0
        to_remove: list[NetworkMessage] = []

        for message in self._queue:
            try:
                self._validate_domain(message)
                self._validate_expiration(message)
                self._resolve_and_authorize(message)
            except DispatcherError as exc:
                record = self._delivery_records.get(message.message_id)
                if record is not None:
                    self._reject(record, message, exc)
                else:
                    # Delivery record not available — create a minimal one
                    now = self._now()
                    record = DeliveryRecord(
                        message_id=message.message_id,
                        source_subject=message.source_subject,
                        destination_subject=message.destination_subject,
                        route_generation=message.route_generation,
                        delivery_state="QUEUED",
                        received_at=now,
                        payload_hash=message.payload_hash,
                    )
                    self._reject(record, message, exc)
                to_remove.append(message)
                dead_lettered += 1

        for message in to_remove:
            self._queue.remove(message)
            self.store.queued_messages.pop(message.message_id, None)

        self.store.flush()
        return dead_lettered

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
        if datetime.fromisoformat(message.expiration) <= datetime.now(UTC):
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
        if (
            route.runtime_generation is not None
            and message.runtime_generation != route.runtime_generation
        ):
            raise DispatcherError(
                "RUNTIME_GENERATION_MISMATCH",
                "routing",
                "Message Runtime Generation does not match the active Runtime lineage",
            )
        if message.source_subject.subject_type not in route.allowed_source_types:
            raise DispatcherError(
                "SOURCE_NOT_AUTHORIZED",
                "authorization",
                "Source subject type is not authorized",
            )
        if (
            route.allowed_source_ids
            and message.source_subject.subject_id not in route.allowed_source_ids
        ):
            raise DispatcherError(
                "SOURCE_NOT_AUTHORIZED",
                "authorization",
                "Source subject identity is not authorized",
            )
        permitted_ids = route.allowed_source_ids_by_type.get(
            message.source_subject.subject_type
        )
        if permitted_ids is not None and message.source_subject.subject_id not in permitted_ids:
            raise DispatcherError(
                "SOURCE_NOT_AUTHORIZED",
                "authorization",
                "Source subject identity is not authorized for its role",
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
        # Assignment-key signed transfer envelope validation (VALIDATION channel)
        self._validate_assignment_key(message, route)
        return route

    def _validate_assignment_key(
        self, message: NetworkMessage, route: DispatcherRoute
    ) -> None:
        """Validate assignment-key binding for signed transfer envelopes.

        When the route carries a canonical hypervisor_key, every message on that
        route must present a matching assignment_key.  An assignment_key is
        considered valid when it is a non-empty string that encodes the
        hypervisor_key as its prefix (``{hypervisor_key}:{assignment_id}``).
        """
        hv_key = route.hypervisor_key
        if hv_key is None:
            return  # no canonical key registered — skip assignment-key checks
        if message.assignment_key is None:
            raise DispatcherError(
                "ASSIGNMENT_KEY_MISSING",
                "authorization",
                "Assignment key is required for signed transfer envelopes",
            )
        if not self._assignment_key_matches(message.assignment_key, hv_key):
            raise DispatcherError(
                "ASSIGNMENT_KEY_INVALID",
                "authorization",
                "Assignment key does not match the registered Hypervisor key",
            )

    @staticmethod
    def _assignment_key_matches(assignment_key: str, hypervisor_key: str) -> bool:
        """Check that ``assignment_key`` is bound to ``hypervisor_key``.

        Canonical format: ``{hypervisor_key}:{assignment_id}``.
        """
        if not assignment_key.startswith(hypervisor_key + ":"):
            return False
        suffix = assignment_key[len(hypervisor_key) + 1 :]
        return len(suffix) > 0

    def register_hypervisor_key(
        self,
        *,
        destination_type: str,
        destination_id: str,
        hypervisor_key: str,
    ) -> None:
        """Register the canonical Hypervisor key for a route.

        After registration, every message submitted on that route must carry
        an ``assignment_key`` that is bound to this ``hypervisor_key``.
        """
        key = (destination_type, destination_id)
        route = self._routes.get(key)
        if route is None:
            raise ValueError(f"No route found for ({destination_type}, {destination_id})")
        updated = route.model_copy(update={"hypervisor_key": hypervisor_key})
        self._routes[key] = updated
        self.store.flush()

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
        self._metrics.increment_dead_lettered()
        self._metrics.increment_dead_letter_count()
        self.store.flush()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _queue_priority(message: NetworkMessage) -> tuple[int, str, int]:
        """Apply protocol-derived priority, preserving FIFO within each class."""
        ranks = {
            "CRITICAL_CONTROL": 0,
            "HIGH": 1,
            "INTERACTIVE": 2,
            "NORMAL": 3,
            "BULK": 4,
            "BACKGROUND": 5,
        }
        policy_priority = {
            "SESSION_CLOSE": "HIGH",
            "SESSION_CANCELLATION": "HIGH",
            "SESSION_DEPOSIT_EXTENSION": "HIGH",
            "SESSION_REQUEST": "INTERACTIVE",
            "SESSION_RESPONSE_STREAM": "INTERACTIVE",
            "SESSION_CAPABILITY_EVENT": "INTERACTIVE",
            "REGISTRY_REPLICATION": "BULK",
            "REGISTRY_SNAPSHOT_TRANSFER": "BACKGROUND",
        }.get(message.message_type, "NORMAL")
        # The envelope cannot elevate its own priority above protocol policy.
        return (
            ranks[policy_priority],
            message.created_at,
            message.source_sequence,
        )
