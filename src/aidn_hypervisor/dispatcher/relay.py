"""Relay communication (RFC-0042 §37-43).

Relay forwards opaque authenticated messages between peers unable to
connect directly. Relay SHALL NOT become the logical sender.
"""

import hashlib
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# ── Relay defaults (RFC-0042 §40) ────────────────────────────────────────

DEFAULT_MAX_RELAY_HOPS: int = 2
DEFAULT_RELAY_RATE_LIMIT: int = 50  # messages per second per source
DEFAULT_RELAY_EXPIRATION_SECS: int = 300


# ── Relay envelope (RFC-0042 §38) ────────────────────────────────────────

class RelayEnvelope(BaseModel):
    """Authenticated relay envelope for indirect peer communication."""

    relay_message_id: str
    source_hypervisor_id: str
    destination_hypervisor_id: str
    inner_message_hash: str  # SHA-256 of the actual payload
    relay_path: list[str] = Field(default_factory=list)  # relay IDs visited
    hop_count: int = 0
    hop_limit: int = DEFAULT_MAX_RELAY_HOPS
    expiration: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source_signature: str = ""  # end-to-end signature
    payload: bytes = b""  # encrypted payload (relay cannot read)
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def is_expired(self) -> bool:
        """Check if envelope has expired."""
        now = datetime.now(timezone.utc)
        exp = datetime.fromisoformat(self.expiration)
        # Normalize to both aware or both naive
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return now >= exp

    def has_hops_remaining(self) -> bool:
        """Check if envelope can still be relayed."""
        return self.hop_count < self.hop_limit

    def would_form_loop(self, next_relay_id: str) -> bool:
        """Check if forwarding to next_relay_id would form a loop."""
        return next_relay_id in self.relay_path

    def record_hop(self, relay_id: str) -> None:
        """Record a relay hop."""
        self.relay_path.append(relay_id)
        self.hop_count += 1

    def compute_integrity_hash(self) -> str:
        """Compute integrity hash for path verification."""
        data = f"{self.relay_message_id}:{self.source_hypervisor_id}:{self.destination_hypervisor_id}:{self.inner_message_hash}:{','.join(self.relay_path)}"
        return hashlib.sha256(data.encode()).hexdigest()


# ── Relay rate limiter ───────────────────────────────────────────────────

class RateLimiter:
    """Token bucket rate limiter for relay messages."""

    def __init__(self, rate: int = DEFAULT_RELAY_RATE_LIMIT, window_secs: float = 1.0) -> None:
        self.rate = rate
        self.window_secs = window_secs
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._max_tokens = rate

    def allow(self, source_id: str) -> bool:
        """Check if a message from source_id is allowed."""
        now = time.monotonic()
        timestamps = self._buckets[source_id]

        # Remove expired timestamps
        cutoff = now - self.window_secs
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)

        if len(timestamps) >= self._max_tokens:
            return False

        timestamps.append(now)
        return True


# ── Relay router ─────────────────────────────────────────────────────────

class RelayRouter:
    """Handles relay message forwarding (RFC-0042 §37-43).

    Responsibilities:
    - Enforce hop limits
    - Prevent relay loops
    - Rate limit relay traffic
    - Track relay paths
    - Preserve end-to-end encryption boundaries
    """

    def __init__(
        self,
        *,
        local_relay_id: str,
        max_hops: int = DEFAULT_MAX_RELAY_HOPS,
        rate_limit: int = DEFAULT_RELAY_RATE_LIMIT,
    ) -> None:
        self.local_relay_id = local_relay_id
        self.max_hops = max_hops
        self.rate_limiter = RateLimiter(rate=rate_limit)
        self._forward_targets: dict[str, str] = {}  # dest_hypervisor_id -> next_hop_relay_id
        self._processed_ids: set[str] = set()
        self._stats = RelayStats()

    @property
    def stats(self) -> "RelayStats":
        return self._stats

    def register_forward_target(self, destination_hypervisor_id: str, next_hop_relay_id: str) -> None:
        """Register a relay target for a destination hypervisor."""
        self._forward_targets[destination_hypervisor_id] = next_hop_relay_id

    def validate_envelope(self, envelope: RelayEnvelope) -> bool:
        """Validate a relay envelope before processing."""
        # Check expiration
        if envelope.is_expired():
            logger.warning("Relay envelope expired: %s", envelope.relay_message_id)
            self._stats.expired += 1
            return False

        # Check hop limit
        if not envelope.has_hops_remaining():
            logger.warning("Relay envelope hop limit reached: %s", envelope.relay_message_id)
            self._stats.hop_limit_exceeded += 1
            return False

        # Check for loops
        if envelope.would_form_loop(self.local_relay_id):
            logger.warning(
                "Relay loop detected: %s already visited %s",
                envelope.relay_message_id,
                self.local_relay_id,
            )
            self._stats.loops_detected += 1
            return False

        # Rate limit check
        if not self.rate_limiter.allow(envelope.source_hypervisor_id):
            logger.warning(
                "Relay rate limit exceeded for source: %s",
                envelope.source_hypervisor_id,
            )
            self._stats.rate_limited += 1
            return False

        # Check for duplicate processing
        if envelope.relay_message_id in self._processed_ids:
            logger.info("Duplicate relay message: %s", envelope.relay_message_id)
            self._stats.duplicates += 1
            return False

        # Mark as seen so repeated validate calls catch duplicates
        self._processed_ids.add(envelope.relay_message_id)
        return True

    def resolve_forward_target(self, envelope: RelayEnvelope) -> str | None:
        """Determine the next hop for forwarding."""
        dest = envelope.destination_hypervisor_id

        # Direct delivery if destination is local
        # (caller should check this before creating relay envelope)

        # Look up relay target
        next_hop = self._forward_targets.get(dest)
        if next_hop is None:
            logger.warning("No relay target for destination: %s", dest)
            self._stats.no_route += 1
            return None

        return next_hop

    def process_inbound(self, envelope: RelayEnvelope) -> RelayEnvelope | None:
        """Process an inbound relay envelope.

        Returns the envelope ready for forwarding, or None if rejected.
        """
        if not self.validate_envelope(envelope):
            return None

        # Record this message as processed
        self._processed_ids.add(envelope.relay_message_id)
        self._stats.forwarded += 1

        # Record hop
        envelope.record_hop(self.local_relay_id)

        # Determine forward target
        next_hop = self.resolve_forward_target(envelope)
        if next_hop is None:
            return None

        logger.info(
            "Relay forwarding: %s -> %s (hop %d/%d)",
            envelope.relay_message_id,
            next_hop,
            envelope.hop_count,
            envelope.hop_limit,
        )

        return envelope

    def create_relay_envelope(
        self,
        *,
        source_hypervisor_id: str,
        destination_hypervisor_id: str,
        inner_message_hash: str,
        payload: bytes,
        hop_limit: int = DEFAULT_MAX_RELAY_HOPS,
        source_signature: str = "",
    ) -> RelayEnvelope:
        """Create a new relay envelope for outbound relayed messages."""
        import uuid

        # Calculate expiration
        from datetime import timedelta

        expiration = datetime.now(timezone.utc) + timedelta(seconds=DEFAULT_RELAY_EXPIRATION_SECS)

        return RelayEnvelope(
            relay_message_id=str(uuid.uuid4()),
            source_hypervisor_id=source_hypervisor_id,
            destination_hypervisor_id=destination_hypervisor_id,
            inner_message_hash=inner_message_hash,
            hop_limit=hop_limit,
            source_signature=source_signature,
            payload=payload,
            expiration=expiration.isoformat(),
        )

    def cleanup_processed(self, max_age_secs: float = 3600) -> int:
        """Clean up old processed message IDs."""
        # Simple implementation — in production would use TTL cache
        count = len(self._processed_ids)
        self._processed_ids.clear()
        self._stats.cleaned_up = count
        return count


class RelayStats:
    """Relay router statistics."""

    def __init__(self) -> None:
        self.forwarded: int = 0
        self.expired: int = 0
        self.hop_limit_exceeded: int = 0
        self.loops_detected: int = 0
        self.rate_limited: int = 0
        self.duplicates: int = 0
        self.no_route: int = 0
        self.cleaned_up: int = 0

    def __repr__(self) -> str:
        return (
            f"RelayStats(forwarded={self.forwarded}, expired={self.expired}, "
            f"hop_limit={self.hop_limit_exceeded}, loops={self.loops_detected}, "
            f"rate_limited={self.rate_limited}, duplicates={self.duplicates})"
        )
