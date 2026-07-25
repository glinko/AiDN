"""Tests for consensus/validator.py — Participation, Downtime, Consequences."""

import hashlib
import pytest

from aidn_hypervisor.consensus.validator import (
    ValidatorSetManager,
    ValidatorSetConfig,
    ValidatorStatus,
    Consequence,
    DowntimeType,
)


# ── Helpers ──────────────────────────────────────────────────────────

_TS = "2025-06-01T00:00:00Z"


def _make_manager(config=None):
    return ValidatorSetManager(config=config)


def _register(mgr, node_id, stake=100_000, operator_id=None, ts=_TS):
    if operator_id is None:
        operator_id = f"op-{node_id}"
    return mgr.register_candidate(
        node_id=node_id,
        operator_id=operator_id,
        stake=stake,
        timestamp=ts,
    )


# ── 1. Participation recording ──────────────────────────────────────


def test_record_participation():
    mgr = _make_manager()
    _register(mgr, "node-1")
    mgr.record_participation(node_id="node-1", block_height=42)
    blocks = mgr._participation.get("node-1", [])
    assert 42 in blocks


def test_record_miss():
    mgr = _make_manager()
    _register(mgr, "node-1")
    mgr.record_miss(node_id="node-1", block_height=10)
    v = mgr.get_validator("node-1")
    assert v.downtime_count == 1


# ── 2. Downtime classification ──────────────────────────────────────


def test_downtime_ordinary():
    mgr = _make_manager()
    _register(mgr, "node-1")
    for _ in range(2):
        mgr.record_miss(node_id="node-1", block_height=1)
    dtype = mgr.classify_downtime(node_id="node-1")
    assert dtype == DowntimeType.ORDINARY


def test_downtime_persistent():
    mgr = _make_manager()
    _register(mgr, "node-1")
    for _ in range(5):
        mgr.record_miss(node_id="node-1", block_height=1)
    dtype = mgr.classify_downtime(node_id="node-1")
    assert dtype == DowntimeType.PERSISTENT


def test_downtime_abandonment():
    mgr = _make_manager()
    _register(mgr, "node-1")
    for _ in range(25):
        mgr.record_miss(node_id="node-1", block_height=1)
    dtype = mgr.classify_downtime(node_id="node-1")
    assert dtype == DowntimeType.ABANDONMENT


# ── 3. Consequences ─────────────────────────────────────────────────


def test_consequence_warning():
    mgr = _make_manager()
    _register(mgr, "node-1")
    for _ in range(2):
        mgr.record_miss(node_id="node-1", block_height=1)
    c = mgr.apply_consequence(node_id="node-1")
    assert c == Consequence.WARNING


def test_consequence_suspension():
    mgr = _make_manager()
    _register(mgr, "node-1")
    for _ in range(12):
        mgr.record_miss(node_id="node-1", block_height=1)
    c = mgr.apply_consequence(node_id="node-1")
    assert c == Consequence.SUSPENSION


def test_consequence_unbonding():
    mgr = _make_manager()
    _register(mgr, "node-1")
    for _ in range(25):
        mgr.record_miss(node_id="node-1", block_height=1)
    c = mgr.apply_consequence(node_id="node-1")
    assert c == Consequence.UNBONDING


# ── 4. Participation rate ───────────────────────────────────────────


def test_participation_rate_calculation():
    mgr = _make_manager(config=ValidatorSetConfig(participation_rate_window=10))
    _register(mgr, "node-1")
    # Participate in 7 out of 10 recent blocks
    for h in range(100, 107):
        mgr.record_participation(node_id="node-1", block_height=h)
    rate = mgr.get_participation_rate(node_id="node-1")
    assert abs(rate - 0.7) < 0.01


def test_participation_rate_zero():
    mgr = _make_manager()
    _register(mgr, "node-1")
    rate = mgr.get_participation_rate(node_id="node-1")
    assert rate == 0.0


def test_participation_rate_window():
    mgr = _make_manager(config=ValidatorSetConfig(participation_rate_window=5))
    _register(mgr, "node-1")
    for h in range(100, 105):
        mgr.record_participation(node_id="node-1", block_height=h)
    rate = mgr.get_participation_rate(node_id="node-1")
    assert abs(rate - 1.0) < 0.01


# ── 5. Downtime classification updates ──────────────────────────────


def test_downtime_classification_updates():
    mgr = _make_manager()
    _register(mgr, "node-1")
    # Initially ordinary
    assert mgr.classify_downtime(node_id="node-1") == DowntimeType.ORDINARY
    # After 5 misses → persistent
    for _ in range(5):
        mgr.record_miss(node_id="node-1", block_height=1)
    assert mgr.classify_downtime(node_id="node-1") == DowntimeType.PERSISTENT
    # After 25 misses → abandonment
    for _ in range(20):
        mgr.record_miss(node_id="node-1", block_height=1)
    assert mgr.classify_downtime(node_id="node-1") == DowntimeType.ABANDONMENT


def test_consequence_applied_updates_validator():
    mgr = _make_manager()
    _register(mgr, "node-1")
    # Trigger suspension via misses
    for _ in range(12):
        mgr.record_miss(node_id="node-1", block_height=1)
    v = mgr.get_validator("node-1")
    assert v.status == ValidatorStatus.SUSPENDED
    assert v.consequence == Consequence.SUSPENSION


# ── 6. Reward eligibility ───────────────────────────────────────────


def test_reward_eligibility_active():
    mgr = _make_manager()
    _register(mgr, "node-1")
    mgr.select_active_set(epoch=1, timestamp=_TS)
    assert mgr.is_reward_eligible(node_id="node-1") is True


def test_reward_eligibility_downtime():
    mgr = _make_manager()
    _register(mgr, "node-1")
    v = mgr.get_validator("node-1")
    mgr._validators["node-1"] = v.model_copy(
        update={"status": ValidatorStatus.DOWNTIME}
    )
    assert mgr.is_reward_eligible(node_id="node-1") is False


def test_reward_eligibility_suspended():
    mgr = _make_manager()
    _register(mgr, "node-1")
    v = mgr.get_validator("node-1")
    mgr._validators["node-1"] = v.model_copy(
        update={"status": ValidatorStatus.SUSPENDED}
    )
    assert mgr.is_reward_eligible(node_id="node-1") is False


# ── 7. Validator set snapshot ───────────────────────────────────────


def test_validator_set_snapshot():
    mgr = _make_manager()
    for i in range(5):
        _register(mgr, f"node-{i}")
    eps = mgr.select_active_set(epoch=1, timestamp=_TS)
    assert len(eps.validators) == 5
    assert eps.total_stake == 5 * 100_000
    assert eps.total_voting_power == 5 * 100_000


def test_epoch_validator_set_persistence():
    mgr = _make_manager()
    _register(mgr, "node-1")
    eps = mgr.select_active_set(epoch=1, timestamp=_TS)
    stored = mgr.get_active_set(1)
    assert stored is not None
    assert stored.epoch == eps.epoch
    assert stored.total_stake == eps.total_stake


# ── 8. Multiple validators independent ──────────────────────────────


def test_multiple_validators_independent():
    mgr = _make_manager()
    _register(mgr, "a")
    _register(mgr, "b")
    mgr.record_participation(node_id="a", block_height=10)
    mgr.record_miss(node_id="b", block_height=10)
    va = mgr.get_validator("a")
    vb = mgr.get_validator("b")
    assert va.downtime_count == 0
    assert vb.downtime_count == 1


# ── 9. Config thresholds ────────────────────────────────────────────


def test_config_thresholds():
    cfg = ValidatorSetConfig(
        downtime_warning_threshold=2,
        downtime_suspension_threshold=5,
        downtime_unbonding_threshold=8,
    )
    mgr = _make_manager(cfg)
    _register(mgr, "node-1")

    # 1 miss → still ordinary
    mgr.record_miss(node_id="node-1", block_height=1)
    assert mgr.classify_downtime(node_id="node-1") == DowntimeType.ORDINARY

    # 2 misses → persistent (reached warning threshold)
    mgr.record_miss(node_id="node-1", block_height=2)
    assert mgr.classify_downtime(node_id="node-1") == DowntimeType.PERSISTENT

    # 5 misses → still persistent (not yet unbonding)
    for _ in range(3):
        mgr.record_miss(node_id="node-1", block_height=3)
    assert mgr.classify_downtime(node_id="node-1") == DowntimeType.PERSISTENT

    # 8 misses → abandonment
    for _ in range(3):
        mgr.record_miss(node_id="node-1", block_height=4)
    assert mgr.classify_downtime(node_id="node-1") == DowntimeType.ABANDONMENT
