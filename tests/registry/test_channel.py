"""Tests for Registry Channel Configuration (M9-S2).

RFC-0042 §44-§49 — Channel multiplexing, priorities, authorization,
rate limiting for registry replication traffic.
"""

from __future__ import annotations

from aidn_hypervisor.registry.channel import (
    DEFAULT_REGISTRY_CHANNELS,
    RegistryChannelConfig,
    RegistryChannelManager,
)
from aidn_hypervisor.registry.messages import (
    RegistryChannelClass,
    RegistryMessageType,
)

# ─── RegistryChannelConfig ─────────────────────────────────────────────


class TestRegistryChannelConfig:

    def test_channel_config_defaults(self) -> None:
        """Default values are set correctly."""
        cfg = RegistryChannelConfig(channel_id="test:ch")
        assert cfg.channel_id == "test:ch"
        assert cfg.channel_class == RegistryChannelClass.REGISTRY_REPLICATION
        assert cfg.max_queue_size == 1000
        assert cfg.max_message_size_bytes == 10 * 1024 * 1024
        assert cfg.rate_limit_per_second == 100
        assert cfg.priority == 5
        assert cfg.allowed_message_types == []
        assert cfg.authorized_peers == []
        assert cfg.enabled is True
        assert cfg.created_at > 0

    def test_channel_config_frozen(self) -> None:
        """Config is not frozen; model_copy works for updates."""
        cfg = RegistryChannelConfig(channel_id="test:ch")
        updated = cfg.model_copy(update={"enabled": False})
        assert updated.enabled is False
        assert cfg.enabled is True  # original unchanged

    def test_channel_config_custom(self) -> None:
        """Custom values override defaults."""
        cfg = RegistryChannelConfig(
            channel_id="custom:ch",
            channel_class=RegistryChannelClass.REGISTRY_CONTROL,
            max_queue_size=50,
            rate_limit_per_second=10,
            priority=9,
            allowed_message_types=[RegistryMessageType.SYNC_STATUS],
            authorized_peers=["peer-1"],
            enabled=False,
        )
        assert cfg.channel_id == "custom:ch"
        assert cfg.channel_class == RegistryChannelClass.REGISTRY_CONTROL
        assert cfg.max_queue_size == 50
        assert cfg.rate_limit_per_second == 10
        assert cfg.priority == 9
        assert cfg.allowed_message_types == [RegistryMessageType.SYNC_STATUS]
        assert cfg.authorized_peers == ["peer-1"]
        assert cfg.enabled is False

    def test_channel_config_priority_range(self) -> None:
        """Priority is just an int; no enforced range at model level."""
        cfg_low = RegistryChannelConfig(channel_id="low", priority=1)
        cfg_high = RegistryChannelConfig(channel_id="high", priority=10)
        assert cfg_low.priority == 1
        assert cfg_high.priority == 10


# ─── RegistryChannelManager ────────────────────────────────────────────


class TestRegistryChannelManager:

    def _manager(self) -> RegistryChannelManager:
        return RegistryChannelManager()

    # --- create / get / list ---

    def test_create_channel(self) -> None:
        mgr = self._manager()
        cfg = mgr.create_channel(channel_id="test:ch")
        assert cfg.channel_id == "test:ch"
        assert cfg.channel_class == RegistryChannelClass.REGISTRY_REPLICATION

    def test_get_channel(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="x:1")
        ch = mgr.get_channel("x:1")
        assert ch is not None
        assert ch.channel_id == "x:1"

    def test_get_channel_missing(self) -> None:
        mgr = self._manager()
        assert mgr.get_channel("no:pe") is None

    def test_list_channels(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="a:1")
        mgr.create_channel(channel_id="b:2")
        channels = mgr.list_channels()
        assert len(channels) == 2
        ids = {c.channel_id for c in channels}
        assert ids == {"a:1", "b:2"}

    # --- enable / disable ---

    def test_enable_channel(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="e:1", enabled=False)
        assert mgr.enable_channel("e:1") is True
        assert mgr.get_channel("e:1").enabled is True

    def test_disable_channel(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="d:1", enabled=True)
        assert mgr.disable_channel("d:1") is True
        assert mgr.get_channel("d:1").enabled is False

    def test_enable_channel_missing(self) -> None:
        mgr = self._manager()
        assert mgr.enable_channel("no:pe") is False

    def test_disable_channel_missing(self) -> None:
        mgr = self._manager()
        assert mgr.disable_channel("no:pe") is False

    # --- authorization ---

    def test_authorize_peer(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="auth:1", authorized_peers=[])
        assert mgr.authorize_peer("auth:1", "peer-A") is True
        cfg = mgr.get_channel("auth:1")
        assert cfg is not None
        assert "peer-A" in cfg.authorized_peers

    def test_authorize_peer_idempotent(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="auth:1", authorized_peers=["peer-A"])
        assert mgr.authorize_peer("auth:1", "peer-A") is True
        cfg = mgr.get_channel("auth:1")
        assert cfg is not None
        assert cfg.authorized_peers.count("peer-A") == 1

    def test_authorize_peer_missing_channel(self) -> None:
        mgr = self._manager()
        assert mgr.authorize_peer("no:pe", "peer-X") is False

    def test_check_authorization_allowed(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="auth:1", authorized_peers=["peer-A"])
        assert mgr.check_authorization("auth:1", "peer-A") is True

    def test_check_authorization_denied(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="auth:1", authorized_peers=["peer-A"])
        assert mgr.check_authorization("auth:1", "peer-B") is False

    def test_check_authorization_empty_peers(self) -> None:
        """Empty authorized_peers means all peers allowed."""
        mgr = self._manager()
        mgr.create_channel(channel_id="open:1", authorized_peers=[])
        assert mgr.check_authorization("open:1", "any-peer") is True

    def test_check_authorization_disabled_channel(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="off:1", enabled=False)
        assert mgr.check_authorization("off:1", "peer-A") is False

    def test_check_authorization_missing_channel(self) -> None:
        mgr = self._manager()
        assert mgr.check_authorization("no:pe", "peer-A") is False

    # --- enqueue / dequeue ---

    def test_enqueue_message(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="q:1")
        msg = {"message_type": RegistryMessageType.SYNC_STATUS, "data": "x"}
        assert mgr.enqueue_message(channel_id="q:1", message=msg, source_peer="p1")
        assert mgr.get_queue_depth("q:1") == 1

    def test_enqueue_message_disabled_channel(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="q:1", enabled=False)
        msg = {"message_type": RegistryMessageType.SYNC_STATUS}
        assert mgr.enqueue_message(channel_id="q:1", message=msg, source_peer="p1") is False

    def test_enqueue_message_unauthorized(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="q:1", authorized_peers=["peer-A"])
        msg = {"message_type": RegistryMessageType.SYNC_STATUS}
        assert mgr.enqueue_message(channel_id="q:1", message=msg, source_peer="peer-B") is False

    def test_enqueue_message_queue_full(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="q:1", max_queue_size=1)
        msg = {"message_type": RegistryMessageType.SYNC_STATUS}
        assert mgr.enqueue_message(channel_id="q:1", message=msg, source_peer="p1") is True
        assert mgr.enqueue_message(channel_id="q:1", message=msg, source_peer="p1") is False

    def test_dequeue_message(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="q:1")
        msg = {"message_type": RegistryMessageType.SYNC_STATUS, "val": 42}
        mgr.enqueue_message(channel_id="q:1", message=msg, source_peer="p1")
        out = mgr.dequeue_message("q:1")
        assert out is not None
        assert out["message_type"] == RegistryMessageType.SYNC_STATUS
        assert out["val"] == 42

    def test_dequeue_message_empty(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="q:1")
        assert mgr.dequeue_message("q:1") is None

    def test_get_queue_depth(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="q:1")
        assert mgr.get_queue_depth("q:1") == 0
        msg = {"message_type": RegistryMessageType.SYNC_STATUS}
        mgr.enqueue_message(channel_id="q:1", message=msg, source_peer="p1")
        mgr.enqueue_message(channel_id="q:1", message=msg, source_peer="p1")
        assert mgr.get_queue_depth("q:1") == 2

    def test_get_message_count(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="q:1")
        assert mgr.get_message_count("q:1") == 0
        msg = {"message_type": RegistryMessageType.SYNC_STATUS}
        mgr.enqueue_message(channel_id="q:1", message=msg, source_peer="p1")
        mgr.enqueue_message(channel_id="q:1", message=msg, source_peer="p1")
        mgr.enqueue_message(channel_id="q:1", message=msg, source_peer="p1")
        assert mgr.get_message_count("q:1") == 3

    # --- rate limiting ---

    def test_rate_limit_enforced(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="rl:1", rate_limit_per_second=3)
        msg = {"message_type": RegistryMessageType.SYNC_STATUS}
        assert mgr.enqueue_message(channel_id="rl:1", message=msg, source_peer="p1") is True
        assert mgr.enqueue_message(channel_id="rl:1", message=msg, source_peer="p1") is True
        assert mgr.enqueue_message(channel_id="rl:1", message=msg, source_peer="p1") is True
        # 4th should fail (rate limited)
        assert mgr.enqueue_message(channel_id="rl:1", message=msg, source_peer="p1") is False

    def test_reset_rate_windows(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="rl:1", rate_limit_per_second=2)
        msg = {"message_type": RegistryMessageType.SYNC_STATUS}
        mgr.enqueue_message(channel_id="rl:1", message=msg, source_peer="p1")
        mgr.enqueue_message(channel_id="rl:1", message=msg, source_peer="p1")
        assert mgr.enqueue_message(channel_id="rl:1", message=msg, source_peer="p1") is False
        mgr.reset_rate_windows()
        # After reset, should succeed again
        assert mgr.enqueue_message(channel_id="rl:1", message=msg, source_peer="p1") is True

    # --- message type filter ---

    def test_channel_message_type_filter(self) -> None:
        mgr = self._manager()
        mgr.create_channel(
            channel_id="filter:1",
            allowed_message_types=[RegistryMessageType.SYNC_STATUS],
        )
        allowed_msg = {"message_type": RegistryMessageType.SYNC_STATUS}
        denied_msg = {"message_type": RegistryMessageType.ANNOUNCEMENT}
        assert mgr.enqueue_message(channel_id="filter:1", message=allowed_msg, source_peer="p1") is True
        assert mgr.enqueue_message(channel_id="filter:1", message=denied_msg, source_peer="p1") is False

    # --- priority ---

    def test_channel_priority(self) -> None:
        mgr = self._manager()
        ch_low = mgr.create_channel(channel_id="low", priority=1)
        ch_mid = mgr.create_channel(channel_id="mid", priority=5)
        ch_high = mgr.create_channel(channel_id="high", priority=10)
        assert ch_low.priority == 1
        assert ch_mid.priority == 5
        assert ch_high.priority == 10

    # --- config update ---

    def test_channel_config_update(self) -> None:
        mgr = self._manager()
        mgr.create_channel(channel_id="upd:1", enabled=True, priority=5)
        # disable
        assert mgr.disable_channel("upd:1") is True
        cfg = mgr.get_channel("upd:1")
        assert cfg is not None
        assert cfg.enabled is False
        assert cfg.priority == 5
        # re-enable
        assert mgr.enable_channel("upd:1") is True
        cfg = mgr.get_channel("upd:1")
        assert cfg is not None
        assert cfg.enabled is True


# ─── DEFAULT_REGISTRY_CHANNELS ─────────────────────────────────────────


class TestDefaultChannels:

    def test_default_channels(self) -> None:
        """DEFAULT_REGISTRY_CHANNELS has expected entries."""
        assert "registry_replication" in DEFAULT_REGISTRY_CHANNELS
        assert "registry_discovery" in DEFAULT_REGISTRY_CHANNELS
        assert "registry_control" in DEFAULT_REGISTRY_CHANNELS

    def test_default_replication_config(self) -> None:
        cfg = DEFAULT_REGISTRY_CHANNELS["registry_replication"]
        assert cfg["channel_id"] == "registry:replication"
        assert cfg["channel_class"] == RegistryChannelClass.REGISTRY_REPLICATION
        assert cfg["max_queue_size"] == 2000
        assert cfg["rate_limit_per_second"] == 200
        assert cfg["priority"] == 7
        assert len(cfg["allowed_message_types"]) == 10

    def test_default_discovery_config(self) -> None:
        cfg = DEFAULT_REGISTRY_CHANNELS["registry_discovery"]
        assert cfg["channel_id"] == "registry:discovery"
        assert cfg["channel_class"] == RegistryChannelClass.REGISTRY_DISCOVERY
        assert cfg["max_queue_size"] == 500
        assert cfg["priority"] == 5

    def test_default_control_config(self) -> None:
        cfg = DEFAULT_REGISTRY_CHANNELS["registry_control"]
        assert cfg["channel_id"] == "registry:control"
        assert cfg["channel_class"] == RegistryChannelClass.REGISTRY_CONTROL
        assert cfg["max_queue_size"] == 100
        assert cfg["rate_limit_per_second"] == 20
        assert cfg["priority"] == 9

    def test_create_default_registry_channels(self) -> None:
        """create_default_registry_channels builds from config."""
        from aidn_hypervisor.registry.routes import (
            create_default_registry_channels as create_defaults,
        )

        mgr = create_defaults()
        channels = mgr.list_channels()
        assert len(channels) == 3
        ids = {c.channel_id for c in channels}
        assert ids == {
            "registry:replication",
            "registry:discovery",
            "registry:control",
        }
