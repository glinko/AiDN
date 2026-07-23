"""Dispatcher metrics: counters and gauges for queue depth, delivery rates, error rates, dead letter counts."""


class DispatcherMetrics:
    """Thread-unsafe, in-process metrics collector for the dispatcher.

    Counters
    --------
    messages_submitted   — every message accepted into the queue (QUEUED)
    messages_delivered   — every message successfully delivered (APPLICATION_ACCEPTED)
    messages_rejected    — every message rejected at admission or during delivery
    messages_dead_lettered — every message appended to the dead-letter queue

    Gauges
    ------
    queue_depth          — current number of messages waiting in the queue
    dead_letter_count    — current number of dead-letter entries
    active_connections   — number of active transport connections (managed by transport layer)
    """

    # -- counters ----------------------------------------------------------
    messages_submitted: int = 0
    messages_delivered: int = 0
    messages_rejected: int = 0
    messages_dead_lettered: int = 0

    # -- gauges -----------------------------------------------------------
    queue_depth: int = 0
    dead_letter_count: int = 0
    active_connections: int = 0

    # ------------------------------------------------------------------
    # Counter helpers
    # ------------------------------------------------------------------
    def increment_submitted(self) -> None:
        self.messages_submitted += 1

    def increment_delivered(self) -> None:
        self.messages_delivered += 1

    def increment_rejected(self) -> None:
        self.messages_rejected += 1

    def increment_dead_lettered(self) -> None:
        self.messages_dead_lettered += 1

    # ------------------------------------------------------------------
    # Gauge helpers
    # ------------------------------------------------------------------
    def increment_queue_depth(self) -> None:
        self.queue_depth += 1

    def decrement_queue_depth(self) -> None:
        self.queue_depth = max(0, self.queue_depth - 1)

    def increment_dead_letter_count(self) -> None:
        self.dead_letter_count += 1

    def decrement_dead_letter_count(self) -> None:
        self.dead_letter_count = max(0, self.dead_letter_count - 1)

    def increment_active_connections(self) -> None:
        self.active_connections += 1

    def decrement_active_connections(self) -> None:
        self.active_connections = max(0, self.active_connections - 1)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        """Return a point-in-time copy of all metric values."""
        return {
            # counters
            "messages_submitted": self.messages_submitted,
            "messages_delivered": self.messages_delivered,
            "messages_rejected": self.messages_rejected,
            "messages_dead_lettered": self.messages_dead_lettered,
            # gauges
            "queue_depth": self.queue_depth,
            "dead_letter_count": self.dead_letter_count,
            "active_connections": self.active_connections,
        }
