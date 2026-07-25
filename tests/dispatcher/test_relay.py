"""Tests for relay communication (RFC-0042 §37-43)."""

import pytest
from datetime import datetime, timedelta, timezone

from aidn_hypervisor.dispatcher.relay import (
    DEFAULT_MAX_RELAY_HOPS,
    RateLimiter,
    RelayEnvelope,
    RelayRouter,
    RelayStats,
)


def _future(secs: int = 300) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=secs)).isoformat()


# ── RelayEnvelope tests ──────────────────────────────────────────────────

class TestRelayEnvelope:
    def test_create_envelope(self):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            hop_limit=3,
            expiration=_future(),
        )
        assert env.hop_count == 0
        assert env.hop_limit == 3
        assert env.has_hops_remaining()
        assert not env.is_expired()

    def test_hop_limit_enforcement(self):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            hop_limit=2,
            expiration=_future(),
        )
        assert env.has_hops_remaining()
        env.record_hop("relay-1")
        assert env.hop_count == 1
        assert env.has_hops_remaining()
        env.record_hop("relay-2")
        assert env.hop_count == 2
        assert not env.has_hops_remaining()

    def test_loop_prevention(self):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            relay_path=["relay-1", "relay-2"],
            hop_count=2,
            hop_limit=4,
            expiration=_future(),
        )
        assert env.would_form_loop("relay-1")
        assert env.would_form_loop("relay-2")
        assert not env.would_form_loop("relay-3")

    def test_record_hop_updates_path(self):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            expiration=_future(),
        )
        env.record_hop("relay-1")
        assert "relay-1" in env.relay_path
        assert env.hop_count == 1

    def test_integrity_hash_is_deterministic(self):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            relay_path=["relay-1"],
            expiration=_future(),
        )
        h1 = env.compute_integrity_hash()
        h2 = env.compute_integrity_hash()
        assert h1 == h2
        assert len(h1) == 64

    def test_default_hop_limit(self):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            expiration=_future(),
        )
        assert env.hop_limit == DEFAULT_MAX_RELAY_HOPS


# ── RelayRouter tests ────────────────────────────────────────────────────

class TestRelayRouter:
    @pytest.fixture
    def router(self):
        return RelayRouter(
            local_relay_id="relay-local",
            max_hops=2,
            rate_limit=100,
        )

    def test_validate_valid_envelope(self, router):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            hop_limit=2,
            expiration=_future(),
        )
        assert router.validate_envelope(env) is True

    def test_validate_rejects_expired_envelope(self, router):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            expiration="2020-01-01T00:00:00+00:00",
        )
        assert router.validate_envelope(env) is False
        assert router.stats.expired == 1

    def test_validate_rejects_hop_limit_exceeded(self, router):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            hop_count=2,
            hop_limit=2,
            expiration=_future(),
        )
        assert router.validate_envelope(env) is False
        assert router.stats.hop_limit_exceeded == 1

    def test_validate_rejects_loop(self, router):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            relay_path=["relay-local"],
            hop_count=1,
            hop_limit=3,
            expiration=_future(),
        )
        assert router.validate_envelope(env) is False
        assert router.stats.loops_detected == 1

    def test_validate_rejects_duplicate(self, router):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            expiration=_future(),
        )
        assert router.validate_envelope(env) is True
        assert router.validate_envelope(env) is False
        assert router.stats.duplicates == 1

    def test_process_inbound_valid(self, router):
        router.register_forward_target("hv-dest", "relay-next")
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            expiration=_future(),
        )
        result = router.process_inbound(env)
        assert result is not None
        assert result.hop_count == 1
        assert "relay-local" in result.relay_path
        assert router.stats.forwarded == 1

    def test_process_inbound_rejected(self, router):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            expiration="2020-01-01T00:00:00+00:00",
        )
        result = router.process_inbound(env)
        assert result is None

    def test_process_inbound_no_route(self, router):
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-unknown",
            inner_message_hash="abc123",
            expiration=_future(),
        )
        result = router.process_inbound(env)
        assert result is None
        assert router.stats.no_route == 1

    def test_resolve_forward_target(self, router):
        router.register_forward_target("hv-dest", "relay-next-hop")
        env = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            expiration=_future(),
        )
        target = router.resolve_forward_target(env)
        assert target == "relay-next-hop"

    def test_create_relay_envelope(self, router):
        env = router.create_relay_envelope(
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            payload=b"encrypted payload",
        )
        assert env.source_hypervisor_id == "hv-source"
        assert env.destination_hypervisor_id == "hv-dest"
        assert env.inner_message_hash == "abc123"
        assert env.payload == b"encrypted payload"
        assert env.hop_count == 0

    def test_cleanup_processed(self, router):
        env1 = RelayEnvelope(
            relay_message_id="rm-001",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="abc123",
            expiration=_future(),
        )
        env2 = RelayEnvelope(
            relay_message_id="rm-002",
            source_hypervisor_id="hv-source",
            destination_hypervisor_id="hv-dest",
            inner_message_hash="def456",
            expiration=_future(),
        )
        router.process_inbound(env1)
        router.process_inbound(env2)
        cleaned = router.cleanup_processed()
        assert cleaned >= 2


# ── RateLimiter tests ────────────────────────────────────────────────────

class TestRateLimiter:
    def test_allows_within_limit(self):
        limiter = RateLimiter(rate=5, window_secs=1.0)
        for _ in range(5):
            assert limiter.allow("source-1") is True

    def test_blocks_over_limit(self):
        limiter = RateLimiter(rate=3, window_secs=1.0)
        assert limiter.allow("source-1") is True
        assert limiter.allow("source-1") is True
        assert limiter.allow("source-1") is True
        assert limiter.allow("source-1") is False

    def test_different_sources_independent(self):
        limiter = RateLimiter(rate=2, window_secs=1.0)
        assert limiter.allow("source-1") is True
        assert limiter.allow("source-1") is True
        assert limiter.allow("source-1") is False
        assert limiter.allow("source-2") is True


# ── RelayStats tests ─────────────────────────────────────────────────────

class TestRelayStats:
    def test_stats_repr(self):
        stats = RelayStats()
        stats.forwarded = 10
        stats.expired = 2
        stats.loops_detected = 1
        repr_str = repr(stats)
        assert "forwarded=10" in repr_str
        assert "expired=2" in repr_str
        assert "loops=1" in repr_str
