"""M11-S3: KCG Manager — unit tests."""

from __future__ import annotations

from aidn_hypervisor.eligibility.kcg import KCGManager


# ── Group Creation ──────────────────────────────────────────────

class TestKCGCreation:
    def test_create_first_service(self):
        mgr = KCGManager()
        gid = mgr.register_service("s1", "0xW1", 500_000_000, 1)
        assert gid is not None
        assert mgr.group_count == 1

    def test_same_wallet_same_group(self):
        mgr = KCGManager()
        g1 = mgr.register_service("s1", "0xW1", 500_000_000, 1)
        g2 = mgr.register_service("s2", "0xW1", 500_000_000, 2)
        assert g1 == g2

    def test_different_wallet_different_group(self):
        mgr = KCGManager()
        g1 = mgr.register_service("s1", "0xW1", 500_000_000, 1)
        g2 = mgr.register_service("s2", "0xW2", 500_000_000, 1)
        assert g1 != g2

    def test_stake_accumulates(self):
        mgr = KCGManager()
        mgr.register_service("s1", "0xW1", 500_000_000, 1)
        mgr.register_service("s2", "0xW1", 300_000_000, 2)
        group = mgr.get_group_for_wallet("0xW1")
        assert group is not None
        assert group.total_stake == 800_000_000
        assert group.member_count == 2


# ── Queries ─────────────────────────────────────────────────────

class TestKCGQueries:
    def test_get_group(self):
        mgr = KCGManager()
        gid = mgr.register_service("s1", "0xW1", 500_000_000, 1)
        group = mgr.get_group(gid)
        assert group is not None
        assert group.group_id == gid

    def test_get_group_for_service(self):
        mgr = KCGManager()
        mgr.register_service("s1", "0xW1", 500_000_000, 1)
        group = mgr.get_group_for_service("s1")
        assert group is not None

    def test_get_group_for_service_none(self):
        mgr = KCGManager()
        assert mgr.get_group_for_service("unknown") is None

    def test_get_all_groups(self):
        mgr = KCGManager()
        mgr.register_service("s1", "0xW1", 500_000_000, 1)
        mgr.register_service("s2", "0xW2", 500_000_000, 1)
        groups = mgr.get_all_groups()
        assert len(groups) == 2

    def test_service_group_id(self):
        mgr = KCGManager()
        gid = mgr.register_service("s1", "0xW1", 500_000_000, 1)
        assert mgr.get_service_group_id("s1") == gid


# ── Concentration ───────────────────────────────────────────────

class TestConcentration:
    def test_update_concentration(self):
        mgr = KCGManager()
        gid = mgr.register_service("s1", "0xW1", 500_000_000, 1)
        mgr.update_concentration(gid, 1_000_000_000)
        group = mgr.get_group(gid)
        assert group is not None
        assert group.concentration_percentage == 50.0

    def test_zero_network_stake(self):
        mgr = KCGManager()
        gid = mgr.register_service("s1", "0xW1", 500_000_000, 1)
        mgr.update_concentration(gid, 0)
        group = mgr.get_group(gid)
        assert group is not None
        assert group.concentration_percentage == 0.0

    def test_exceeds_cap(self):
        mgr = KCGManager()
        gid = mgr.register_service("s1", "0xW1", 900_000_000, 1)
        mgr.update_concentration(gid, 1_000_000_000)
        group = mgr.get_group(gid)
        assert group is not None
        assert group.exceeds_concentration_cap is True

    def test_within_cap(self):
        mgr = KCGManager()
        gid = mgr.register_service("s1", "0xW1", 100_000_000, 1)
        mgr.update_concentration(gid, 1_000_000_000)
        group = mgr.get_group(gid)
        assert group is not None
        assert group.exceeds_concentration_cap is False

    def test_update_aggregate_weight(self):
        mgr = KCGManager()
        gid = mgr.register_service("s1", "0xW1", 500_000_000, 1)
        mgr.update_aggregate_weight(gid, 0.75)
        group = mgr.get_group(gid)
        assert group is not None
        assert group.aggregate_weight == 0.75


# ── Removal ─────────────────────────────────────────────────────

class TestKCGRemoval:
    def test_remove_service(self):
        mgr = KCGManager()
        mgr.register_service("s1", "0xW1", 500_000_000, 1)
        mgr.register_service("s2", "0xW1", 300_000_000, 2)
        mgr.remove_service("s2", 3)
        group = mgr.get_group_for_service("s1")
        assert group is not None
        assert "s2" not in group.member_service_ids

    def test_remove_last_service_clears_group(self):
        mgr = KCGManager()
        mgr.register_service("s1", "0xW1", 500_000_000, 1)
        mgr.remove_service("s1", 2)
        assert mgr.group_count == 0

    def test_remove_nonexistent(self):
        mgr = KCGManager()
        mgr.remove_service("unknown", 1)  # should not raise

    def test_group_count(self):
        mgr = KCGManager()
        mgr.register_service("s1", "0xW1", 500_000_000, 1)
        mgr.register_service("s2", "0xW2", 500_000_000, 1)
        assert mgr.group_count == 2
