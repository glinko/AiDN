"""Tests for consensus/validator.py — ValidatorSetManager (registration, stake, active set)."""


from aidn_hypervisor.consensus.validator import (
    ValidatorSetConfig,
    ValidatorSetManager,
    ValidatorStatus,
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


# ── 1. Registration ─────────────────────────────────────────────────


def test_register_candidate():
    mgr = _make_manager()
    v = _register(mgr, "node-1")
    assert v is not None
    assert v.node_id == "node-1"
    assert v.status == ValidatorStatus.CANDIDATE
    assert v.stake == 100_000


def test_register_candidate_below_min_stake():
    mgr = _make_manager()
    v = _register(mgr, "node-1", stake=50)
    assert v is None


def test_register_duplicate_candidate():
    mgr = _make_manager()
    v1 = _register(mgr, "node-1")
    assert v1 is not None
    v2 = _register(mgr, "node-1")
    assert v2 is None


# ── 2. Stake management ─────────────────────────────────────────────


def test_lock_stake():
    mgr = _make_manager()
    _register(mgr, "node-1", stake=100_000)
    rec = mgr.lock_stake(node_id="node-1", amount=50_000, epoch=1, timestamp=_TS)
    assert rec is not None
    assert rec.action == "lock"
    assert rec.amount == 50_000

    v = mgr.get_validator("node-1")
    assert v is not None
    assert v.stake == 150_000


def test_lock_stake_unknown_validator():
    mgr = _make_manager()
    rec = mgr.lock_stake(node_id="ghost", amount=100, epoch=1, timestamp=_TS)
    assert rec is None


def test_unlock_stake():
    mgr = _make_manager()
    _register(mgr, "node-1", stake=200_000)
    rec = mgr.unlock_stake(node_id="node-1", amount=50_000, epoch=1, timestamp=_TS)
    assert rec is not None
    assert rec.action == "unlock"

    v = mgr.get_validator("node-1")
    assert v.stake == 150_000


def test_unlock_stake_exceeds_balance():
    mgr = _make_manager()
    _register(mgr, "node-1", stake=100_000)
    rec = mgr.unlock_stake(node_id="node-1", amount=200_000, epoch=1, timestamp=_TS)
    assert rec is None


# ── 3. Active set selection ─────────────────────────────────────────


def test_select_active_set():
    mgr = _make_manager()
    _register(mgr, "node-1")
    _register(mgr, "node-2")
    eps = mgr.select_active_set(epoch=1, timestamp=_TS)
    assert eps.epoch == 1
    assert len(eps.validators) == 2


def test_select_active_set_limits_count():
    mgr = _make_manager(config=ValidatorSetConfig(target_validator_count=3))
    for i in range(10):
        _register(mgr, f"node-{i}")
    eps = mgr.select_active_set(epoch=1, timestamp=_TS)
    assert len(eps.validators) == 3


def test_select_active_set_by_stake():
    mgr = _make_manager(config=ValidatorSetConfig(target_validator_count=2))
    _register(mgr, "rich", stake=500_000)
    _register(mgr, "poor", stake=100_000)
    _register(mgr, "middle", stake=300_000)
    eps = mgr.select_active_set(epoch=1, timestamp=_TS)
    names = [v.node_id for v in eps.validators]
    assert names == ["rich", "middle"]


def test_select_active_set_skips_suspended():
    mgr = _make_manager()
    _register(mgr, "good")
    # Manually set one validator to SUSPENDED
    bad = mgr.register_candidate(
        node_id="bad", operator_id="op-bad", stake=100_000, timestamp=_TS
    )
    updated = bad.model_copy(update={"status": ValidatorStatus.SUSPENDED})
    mgr._validators["bad"] = updated

    eps = mgr.select_active_set(epoch=1, timestamp=_TS)
    names = [v.node_id for v in eps.validators]
    assert "bad" not in names


def test_select_active_set_eligible_only():
    mgr = _make_manager()
    _register(mgr, "ok")
    un = mgr.register_candidate(
        node_id="unbonding", operator_id="op-un", stake=100_000, timestamp=_TS
    )
    mgr._validators["unbonding"] = un.model_copy(
        update={"status": ValidatorStatus.UNBONDING}
    )
    eps = mgr.select_active_set(epoch=1, timestamp=_TS)
    names = [v.node_id for v in eps.validators]
    assert "unbonding" not in names


def test_select_active_set_sets_active_status():
    mgr = _make_manager()
    _register(mgr, "node-1")
    mgr.select_active_set(epoch=1, timestamp=_TS)
    v = mgr.get_validator("node-1")
    assert v.status == ValidatorStatus.ACTIVE


def test_select_active_set_creates_epoch_set():
    mgr = _make_manager()
    _register(mgr, "node-1")
    eps = mgr.select_active_set(epoch=5, timestamp=_TS)
    assert mgr.get_active_set(5) is not None
    assert mgr.get_active_set(5).epoch == 5


def test_get_active_set_by_epoch():
    mgr = _make_manager()
    _register(mgr, "node-1")
    mgr.select_active_set(epoch=1, timestamp=_TS)
    eps = mgr.get_active_set(1)
    assert eps is not None
    assert eps.epoch == 1


def test_get_all_validators():
    mgr = _make_manager()
    _register(mgr, "a")
    _register(mgr, "b")
    assert len(mgr.get_all_validators()) == 2


def test_get_stake_records():
    mgr = _make_manager()
    _register(mgr, "node-1")
    mgr.lock_stake(node_id="node-1", amount=1000, epoch=1, timestamp=_TS)
    records = mgr.get_stake_records("node-1")
    assert len(records) == 1
    assert records[0].action == "lock"


def test_get_stake_records_filtered():
    mgr = _make_manager()
    _register(mgr, "a")
    _register(mgr, "b")
    mgr.lock_stake(node_id="a", amount=100, epoch=1, timestamp=_TS)
    mgr.lock_stake(node_id="b", amount=200, epoch=1, timestamp=_TS)
    recs_a = mgr.get_stake_records("a")
    assert len(recs_a) == 1
    assert recs_a[0].validator_node_id == "a"


def test_validator_config_defaults():
    cfg = ValidatorSetConfig()
    assert cfg.target_validator_count == 100
    assert cfg.min_stake == 100_000
    assert cfg.unbonding_epochs == 5
    assert cfg.downtime_warning_threshold == 3
    assert cfg.downtime_suspension_threshold == 10
    assert cfg.downtime_unbonding_threshold == 20


def test_multiple_epochs():
    mgr = _make_manager()
    for i in range(5):
        _register(mgr, f"node-{i}")
    eps1 = mgr.select_active_set(epoch=1, timestamp=_TS)
    eps2 = mgr.select_active_set(epoch=2, timestamp=_TS)
    assert eps1.epoch == 1
    assert eps2.epoch == 2
    assert mgr.get_active_set(1) is not None
    assert mgr.get_active_set(2) is not None


def test_unlock_below_min_stake_triggers_unbonding():
    mgr = _make_manager()
    _register(mgr, "node-1", stake=200_000)
    mgr.unlock_stake(node_id="node-1", amount=150_000, epoch=1, timestamp=_TS)
    v = mgr.get_validator("node-1")
    assert v.stake == 50_000
    assert v.status == ValidatorStatus.UNBONDING


# ── 4. Participation ────────────────────────────────────────────────


def test_participation_tracking():
    mgr = _make_manager()
    _register(mgr, "node-1")
    mgr.record_participation(node_id="node-1", block_height=10)
    mgr.record_participation(node_id="node-1", block_height=20)
    blocks = mgr._participation.get("node-1", [])
    assert 10 in blocks
    assert 20 in blocks


def test_participation_rate():
    mgr = _make_manager(config=ValidatorSetConfig(participation_rate_window=10))
    _register(mgr, "node-1")
    for h in range(1, 11):
        mgr.record_participation(node_id="node-1", block_height=h)
    rate = mgr.get_participation_rate(node_id="node-1")
    assert rate == 1.0


def test_miss_tracking():
    mgr = _make_manager()
    _register(mgr, "node-1")
    mgr.record_miss(node_id="node-1", block_height=5)
    v = mgr.get_validator("node-1")
    assert v.downtime_count == 1


# ── 5. Epoch transition ─────────────────────────────────────────────


def test_epoch_transition():
    mgr = _make_manager()
    for i in range(5):
        _register(mgr, f"node-{i}")
    mgr.select_active_set(epoch=1, timestamp=_TS)
    assert mgr.get_current_epoch() == 1
    mgr.select_active_set(epoch=2, timestamp=_TS)
    assert mgr.get_current_epoch() == 2
