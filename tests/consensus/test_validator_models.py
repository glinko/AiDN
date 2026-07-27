"""Tests for consensus/validator.py — Models (ConsensusValidator, StakeRecord, EpochValidatorSet)."""

import hashlib

import pytest
from pydantic import ValidationError
from pydantic_core import ValidationError as PydanticCoreValidationError

from aidn_hypervisor.consensus.validator import (
    ConsensusValidator,
    Consequence,
    EpochValidatorSet,
    StakeRecord,
    ValidatorStatus,
)

# ── Helpers ──────────────────────────────────────────────────────────

_TS = "2025-06-01T00:00:00Z"


def _make_validator(**overrides):
    defaults = dict(
        node_id="node-1",
        operator_id="op-1",
        consensus_address=hashlib.sha256(b"node-1").hexdigest(),
        stake=100_000,
        voting_power=100_000,
        status=ValidatorStatus.CANDIDATE,
        registered_at=_TS,
        last_active_at=_TS,
        downtime_count=0,
        consequence=Consequence.NONE,
    )
    defaults.update(overrides)
    return ConsensusValidator(**defaults)


# ── 1. Basic creation ────────────────────────────────────────────────


def test_validator_creation():
    v = _make_validator()
    assert v.node_id == "node-1"
    assert v.operator_id == "op-1"
    assert v.stake == 100_000
    assert v.voting_power == 100_000
    assert v.status == ValidatorStatus.CANDIDATE
    assert v.downtime_count == 0
    assert v.consequence == Consequence.NONE


def test_validator_is_active():
    v_active = _make_validator(status=ValidatorStatus.ACTIVE)
    assert v_active.is_active is True

    v_candidate = _make_validator(status=ValidatorStatus.CANDIDATE)
    assert v_candidate.is_active is False

    v_suspended = _make_validator(status=ValidatorStatus.SUSPENDED)
    assert v_suspended.is_active is False


def test_validator_is_eligible():
    for status in (
        ValidatorStatus.CANDIDATE,
        ValidatorStatus.ACTIVE,
        ValidatorStatus.DOWNTIME,
    ):
        v = _make_validator(status=status)
        assert v.is_eligible is True, f"{status} should be eligible"

    for status in (ValidatorStatus.SUSPENDED, ValidatorStatus.UNBONDING):
        v = _make_validator(status=status)
        assert v.is_eligible is False, f"{status} should NOT be eligible"


def test_validator_cannot_modify():
    v = _make_validator()
    with pytest.raises(PydanticCoreValidationError):
        v.stake = 999  # type: ignore


def test_validator_status_enum():
    assert ValidatorStatus.CANDIDATE.value == "candidate"
    assert ValidatorStatus.ACTIVE.value == "active"
    assert ValidatorStatus.DOWNTIME.value == "downtime"
    assert ValidatorStatus.SUSPENDED.value == "suspended"
    assert ValidatorStatus.UNBONDING.value == "unbonding"


def test_validator_consequence_enum():
    assert Consequence.NONE.value == "none"
    assert Consequence.WARNING.value == "warning"
    assert Consequence.SUSPENSION.value == "suspension"
    assert Consequence.UNBONDING.value == "unbonding"


# ── Stake Record ─────────────────────────────────────────────────────


def test_stake_record_creation():
    r = StakeRecord(
        validator_node_id="node-1",
        amount=500,
        action="lock",
        epoch=5,
        timestamp=_TS,
    )
    assert r.validator_node_id == "node-1"
    assert r.amount == 500
    assert r.action == "lock"
    assert r.epoch == 5


def test_stake_record_frozen():
    r = StakeRecord(
        validator_node_id="node-1",
        amount=100,
        action="lock",
        epoch=1,
        timestamp=_TS,
    )
    with pytest.raises(PydanticCoreValidationError):
        r.amount = 200  # type: ignore


# ── Epoch Validator Set ──────────────────────────────────────────────


def test_epoch_validator_set():
    v = _make_validator()
    eps = EpochValidatorSet(
        epoch=3,
        validators=[v],
        total_stake=100_000,
        total_voting_power=100_000,
        start_block=300,
        snapshot_time=_TS,
    )
    assert eps.epoch == 3
    assert len(eps.validators) == 1
    assert eps.total_stake == 100_000


def test_epoch_set_total_stake():
    v1 = _make_validator(stake=100_000, voting_power=100_000)
    v2 = _make_validator(
        node_id="node-2",
        consensus_address=hashlib.sha256(b"node-2").hexdigest(),
        stake=200_000,
        voting_power=200_000,
    )
    eps = EpochValidatorSet(
        epoch=1,
        validators=[v1, v2],
        total_stake=300_000,
        total_voting_power=300_000,
        start_block=100,
        snapshot_time=_TS,
    )
    assert eps.total_stake == 300_000
    assert eps.total_voting_power == 300_000


# ── Constraints ──────────────────────────────────────────────────────


def test_validator_min_stake():
    v = _make_validator(stake=0)
    assert v.stake == 0
    with pytest.raises(ValidationError):
        _make_validator(stake=-1)


def test_validator_downtime_count():
    v = _make_validator(downtime_count=5)
    assert v.downtime_count == 5


def test_consensus_address_computed():
    expected = hashlib.sha256(b"node-1").hexdigest()
    v = _make_validator()
    assert v.consensus_address == expected


def test_validator_registered_at():
    v = _make_validator()
    assert v.registered_at == _TS


def test_validator_last_active():
    v = _make_validator(last_active_at="2025-07-01T12:00:00Z")
    assert v.last_active_at == "2025-07-01T12:00:00Z"

    v_none = _make_validator(last_active_at=None)
    assert v_none.last_active_at is None
