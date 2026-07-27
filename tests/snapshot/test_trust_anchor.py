"""RFC-0062 §30-§36 — Trust Anchor + Checkpoint Validation tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from aidn_hypervisor.snapshot.trust_anchor import (
    CheckpointValidator,
    TrustAnchor,
    TrustAnchorStore,
)

# ── helpers ────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _future_iso(offset_days: int = 30) -> str:
    return (datetime.now(UTC) + timedelta(days=offset_days)).isoformat()


def _past_iso(offset_days: int = 1) -> str:
    return (datetime.now(UTC) - timedelta(days=offset_days)).isoformat()


def _make_anchor(
    *,
    network_id: str = "aidn-mainnet",
    chain_id: str = "aidn-chain-1",
    network_revision: int = 1,
    block_height: int = 100_000,
    block_hash: str = "0xabc123",
    application_state_hash: str = "0xdef456",
    validator_set_hash: str = "0xval789",
    protocol_version: str = "1.0.0",
    source: str = "local_state",
    created_at: str | None = None,
    expires_at: str | None = None,
) -> TrustAnchor:
    return TrustAnchor(
        network_id=network_id,
        chain_id=chain_id,
        network_revision=network_revision,
        block_height=block_height,
        block_hash=block_hash,
        application_state_hash=application_state_hash,
        validator_set_hash=validator_set_hash,
        protocol_version=protocol_version,
        source=source,
        created_at=created_at or _now_iso(),
        expires_at=expires_at,
    )


# ── TrustAnchor creation ───────────────────────────────────────────

class TestTrustAnchorCreation:
    def test_create_anchor(self):
        a = _make_anchor()
        assert a.network_id == "aidn-mainnet"
        assert a.block_height == 100_000

    def test_create_anchor_no_expiry(self):
        a = _make_anchor(expires_at=None)
        assert a.expires_at is None

    def test_create_anchor_with_expiry(self):
        exp = _future_iso()
        a = _make_anchor(expires_at=exp)
        assert a.expires_at == exp

    def test_anchor_is_frozen(self):
        a = _make_anchor()
        with pytest.raises(ValidationError):
            a.network_id = "other"

    def test_all_sources(self):
        for src in ("local_state", "software_release", "operator_config", "deployment_image"):
            a = _make_anchor(source=src)
            assert a.source == src


# ── TrustAnchorStore ───────────────────────────────────────────────

class TestTrustAnchorStore:
    def test_empty_store(self):
        store = TrustAnchorStore()
        assert store.count() == 0
        assert store.get_latest() is None

    def test_add_anchor(self):
        store = TrustAnchorStore()
        a = _make_anchor()
        store.add(a)
        assert store.count() == 1

    def test_add_multiple_anchors(self):
        store = TrustAnchorStore()
        store.add(_make_anchor(block_height=100))
        store.add(_make_anchor(block_height=200))
        store.add(_make_anchor(block_height=300))
        assert store.count() == 3

    def test_get_latest_returns_highest_height(self):
        store = TrustAnchorStore()
        store.add(_make_anchor(block_height=500))
        store.add(_make_anchor(block_height=100))
        store.add(_make_anchor(block_height=999))
        latest = store.get_latest()
        assert latest is not None
        assert latest.block_height == 999

    def test_get_for_height_exact_match(self):
        store = TrustAnchorStore()
        store.add(_make_anchor(block_height=500))
        a = store.get_for_height(500)
        assert a is not None
        assert a.block_height == 500

    def test_get_for_height_closest_below(self):
        store = TrustAnchorStore()
        store.add(_make_anchor(block_height=100))
        store.add(_make_anchor(block_height=500))
        store.add(_make_anchor(block_height=1000))
        a = store.get_for_height(750)
        assert a is not None
        assert a.block_height == 500

    def test_get_for_height_no_anchor_below(self):
        store = TrustAnchorStore()
        store.add(_make_anchor(block_height=500))
        a = store.get_for_height(100)
        assert a is None

    def test_has_anchor_for_true(self):
        store = TrustAnchorStore()
        store.add(_make_anchor(block_height=500))
        assert store.has_anchor_for(500) is True
        assert store.has_anchor_for(750) is True

    def test_has_anchor_for_false(self):
        store = TrustAnchorStore()
        store.add(_make_anchor(block_height=500))
        assert store.has_anchor_for(100) is False

    def test_remove_expired(self):
        store = TrustAnchorStore()
        store.add(_make_anchor(block_height=100, expires_at=_future_iso()))
        store.add(_make_anchor(block_height=200, expires_at=_past_iso()))
        store.add(_make_anchor(block_height=300, expires_at=_past_iso()))
        removed = store.remove_expired(_now_iso())
        assert removed == 2
        assert store.count() == 1

    def test_remove_expired_nothing_to_remove(self):
        store = TrustAnchorStore()
        store.add(_make_anchor(expires_at=_future_iso()))
        removed = store.remove_expired(_now_iso())
        assert removed == 0

    def test_anchors_without_expiry_not_removed(self):
        store = TrustAnchorStore()
        store.add(_make_anchor(expires_at=None))
        removed = store.remove_expired(_now_iso())
        assert removed == 0
        assert store.count() == 1


# ── CheckpointValidator ───────────────────────────────────────────

class TestCheckpointValidator:
    def _validator(self, **kw) -> CheckpointValidator:
        return CheckpointValidator(**kw)

    def test_validate_good_anchor(self):
        v = self._validator()
        a = _make_anchor()
        result = v.validate(a, current_height=100_500, current_time=_now_iso())
        assert result.valid is True
        assert result.reasons == []

    def test_validate_expired_by_blocks(self):
        v = self._validator(max_checkpoint_age_blocks=1000)
        a = _make_anchor(block_height=1_000)
        result = v.validate(a, current_height=10_000, current_time=_now_iso())
        assert result.valid is False
        assert any("age" in r.lower() or "block" in r.lower() for r in result.reasons)

    def test_validate_expired_by_time(self):
        # created 31 days ago → exceeds default 30-day window
        old_time = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        v = self._validator()
        a = _make_anchor(created_at=old_time)
        result = v.validate(a, current_height=100_000, current_time=_now_iso())
        assert result.valid is False
        assert any("age" in r.lower() for r in result.reasons)

    def test_validate_empty_block_hash(self):
        v = self._validator()
        a = _make_anchor(block_hash="")
        result = v.validate(a, current_height=100_500, current_time=_now_iso())
        assert result.valid is False

    def test_validate_empty_application_state_hash(self):
        v = self._validator()
        a = _make_anchor(application_state_hash="")
        result = v.validate(a, current_height=100_500, current_time=_now_iso())
        assert result.valid is False

    def test_validate_empty_chain_id(self):
        v = self._validator()
        a = _make_anchor(chain_id="")
        result = v.validate(a, current_height=100_500, current_time=_now_iso())
        assert result.valid is False

    def test_validate_zero_height(self):
        v = self._validator()
        a = _make_anchor(block_height=0)
        result = v.validate(a, current_height=100_500, current_time=_now_iso())
        assert result.valid is False

    def test_validate_chain_identity_match(self):
        v = self._validator()
        a = _make_anchor(network_id="aidn-mainnet", chain_id="aidn-chain-1")
        ok = v.validate_chain_identity(a, expected_network_id="aidn-mainnet", expected_chain_id="aidn-chain-1")
        assert ok is True

    def test_validate_chain_identity_mismatch_network(self):
        v = self._validator()
        a = _make_anchor(network_id="aidn-mainnet", chain_id="aidn-chain-1")
        ok = v.validate_chain_identity(a, expected_network_id="other-net", expected_chain_id="aidn-chain-1")
        assert ok is False

    def test_validate_chain_identity_mismatch_chain(self):
        v = self._validator()
        a = _make_anchor(network_id="aidn-mainnet", chain_id="aidn-chain-1")
        ok = v.validate_chain_identity(a, expected_network_id="aidn-mainnet", expected_chain_id="other-chain")
        assert ok is False

    def test_is_within_trust_period_true(self):
        v = self._validator()
        a = _make_anchor()
        assert v.is_within_trust_period(a, current_height=100_500, current_time=_now_iso()) is True

    def test_is_within_trust_period_false_by_blocks(self):
        v = self._validator(max_checkpoint_age_blocks=500)
        a = _make_anchor(block_height=1_000)
        assert v.is_within_trust_period(a, current_height=10_000, current_time=_now_iso()) is False

    def test_is_within_trust_period_false_by_time(self):
        old_time = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        v = self._validator()
        a = _make_anchor(created_at=old_time)
        assert v.is_within_trust_period(a, current_height=100_000, current_time=_now_iso()) is False

    def test_long_range_attack_old_checkpoint_rejected(self):
        # Very old checkpoint — should be rejected
        ancient = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        v = self._validator()
        a = _make_anchor(block_height=100, created_at=ancient)
        result = v.validate(a, current_height=500_000, current_time=_now_iso())
        assert result.valid is False

    def test_validation_result_contains_anchor(self):
        v = self._validator()
        a = _make_anchor()
        result = v.validate(a, current_height=100_500, current_time=_now_iso())
        assert result.anchor is a

    def test_validation_result_reasons_populated_on_failure(self):
        v = self._validator()
        a = _make_anchor(block_hash="", application_state_hash="", chain_id="", block_height=0)
        result = v.validate(a, current_height=100_500, current_time=_now_iso())
        assert result.valid is False
        assert len(result.reasons) >= 1
