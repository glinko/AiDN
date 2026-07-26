"""Tests for registry/rewards — Registry Rewards + Participation (RFC-0061 §§63–68)."""

from __future__ import annotations

import pytest

from aidn_hypervisor.registry import (
    ParticipantLedger,
    PenaltyEntry,
    RewardConfig,
    RewardEngine,
    RewardEntry,
    SettlementResult,
)


# ---------------------------------------------------------------------------
# RewardEntry — frozen model
# ---------------------------------------------------------------------------

def test_reward_entry_frozen():
    entry = RewardEntry(peer_id="p1", reward_type="storage", amount=1.0)
    with pytest.raises(Exception):
        entry.amount = 2.0  # type: ignore


# ---------------------------------------------------------------------------
# PenaltyEntry — frozen model
# ---------------------------------------------------------------------------

def test_penalty_entry_frozen():
    entry = PenaltyEntry(peer_id="p1", penalty_type="stale", amount=0.5)
    with pytest.raises(Exception):
        entry.amount = 1.0  # type: ignore


# ---------------------------------------------------------------------------
# ParticipantLedger — add reward
# ---------------------------------------------------------------------------

def test_ledger_add_reward():
    ledger = ParticipantLedger()
    entry = RewardEntry(
        peer_id="p1",
        reward_type="storage",
        amount=1.0,
        epoch=1,
    )
    ledger.add_reward(entry)
    assert len(ledger.get_rewards("p1")) == 1
    assert ledger.get_rewards("p1")[0].amount == 1.0


# ---------------------------------------------------------------------------
# ParticipantLedger — add penalty
# ---------------------------------------------------------------------------

def test_ledger_add_penalty():
    ledger = ParticipantLedger()
    entry = PenaltyEntry(
        peer_id="p1",
        penalty_type="stale",
        amount=0.5,
        epoch=1,
    )
    ledger.add_penalty(entry)
    assert len(ledger.get_penalties("p1")) == 1
    assert ledger.get_penalties("p1")[0].amount == 0.5


# ---------------------------------------------------------------------------
# ParticipantLedger — get rewards
# ---------------------------------------------------------------------------

def test_ledger_get_rewards():
    ledger = ParticipantLedger()
    assert ledger.get_rewards("p1") == []

    ledger.add_reward(
        RewardEntry(peer_id="p1", reward_type="storage", amount=1.0, epoch=1)
    )
    rewards = ledger.get_rewards("p1")
    assert len(rewards) == 1
    assert rewards[0].amount == 1.0


# ---------------------------------------------------------------------------
# ParticipantLedger — get penalties
# ---------------------------------------------------------------------------

def test_ledger_get_penalties():
    ledger = ParticipantLedger()
    assert ledger.get_penalties("p1") == []

    ledger.add_penalty(
        PenaltyEntry(peer_id="p1", penalty_type="stale", amount=0.5, epoch=1)
    )
    penalties = ledger.get_penalties("p1")
    assert len(penalties) == 1
    assert penalties[0].amount == 0.5


# ---------------------------------------------------------------------------
# ParticipantLedger — get balance
# ---------------------------------------------------------------------------

def test_ledger_get_balance():
    ledger = ParticipantLedger()
    ledger.add_reward(
        RewardEntry(peer_id="p1", reward_type="storage", amount=10.0, epoch=1)
    )
    ledger.add_penalty(
        PenaltyEntry(peer_id="p1", penalty_type="stale", amount=3.0, epoch=1)
    )
    assert ledger.get_balance("p1") == 7.0


# ---------------------------------------------------------------------------
# ParticipantLedger — get participants
# ---------------------------------------------------------------------------

def test_ledger_get_participants():
    ledger = ParticipantLedger()
    ledger.add_reward(
        RewardEntry(peer_id="p1", reward_type="storage", amount=1.0, epoch=1)
    )
    ledger.add_penalty(
        PenaltyEntry(peer_id="p2", penalty_type="stale", amount=0.5, epoch=1)
    )
    participants = ledger.get_participants()
    assert participants == ["p1", "p2"]


# ---------------------------------------------------------------------------
# ParticipantLedger — get epoch rewards
# ---------------------------------------------------------------------------

def test_ledger_get_epoch_rewards():
    ledger = ParticipantLedger()
    ledger.add_reward(
        RewardEntry(peer_id="p1", reward_type="storage", amount=1.0, epoch=1)
    )
    ledger.add_reward(
        RewardEntry(peer_id="p1", reward_type="serving", amount=2.0, epoch=2)
    )
    epoch1 = ledger.get_epoch_rewards("p1", 1)
    assert len(epoch1) == 1
    assert epoch1[0].amount == 1.0


# ---------------------------------------------------------------------------
# ParticipantLedger — clear
# ---------------------------------------------------------------------------

def test_ledger_clear():
    ledger = ParticipantLedger()
    ledger.add_reward(
        RewardEntry(peer_id="p1", reward_type="storage", amount=1.0, epoch=1)
    )
    ledger.add_penalty(
        PenaltyEntry(peer_id="p1", penalty_type="stale", amount=0.5, epoch=1)
    )
    ledger.clear()
    assert ledger.get_rewards("p1") == []
    assert ledger.get_penalties("p1") == []
    assert ledger.get_participants() == []


# ---------------------------------------------------------------------------
# RewardEngine — reward storage
# ---------------------------------------------------------------------------

def test_reward_storage():
    engine = RewardEngine()
    entry = engine.reward_storage(peer_id="p1", objects_stored=100, epoch=1)
    assert entry.reward_type == "storage"
    assert entry.amount == 1.0  # 100 * 0.01
    assert entry.epoch == 1


# ---------------------------------------------------------------------------
# RewardEngine — reward serving
# ---------------------------------------------------------------------------

def test_reward_serving():
    engine = RewardEngine()
    entry = engine.reward_serving(peer_id="p1", objects_served=50, epoch=1)
    assert entry.reward_type == "serving"
    assert entry.amount == 1.0  # 50 * 0.02


# ---------------------------------------------------------------------------
# RewardEngine — reward verification
# ---------------------------------------------------------------------------

def test_reward_verification():
    engine = RewardEngine()
    entry = engine.reward_verification(peer_id="p1", objects_verified=200, epoch=1)
    assert entry.reward_type == "verification"
    assert entry.amount == 1.0  # 200 * 0.005


# ---------------------------------------------------------------------------
# RewardEngine — reward sync
# ---------------------------------------------------------------------------

def test_reward_sync():
    engine = RewardEngine()
    entry = engine.reward_sync(peer_id="p1", epochs_synced=5, epoch=1)
    assert entry.reward_type == "sync"
    assert entry.amount == 0.5  # 5 * 0.1


# ---------------------------------------------------------------------------
# RewardEngine — penalty incomplete below threshold
# ---------------------------------------------------------------------------

def test_penalty_incomplete_below():
    engine = RewardEngine()
    entry = engine.penalty_incomplete(peer_id="p1", completeness=0.7, epoch=1)
    assert entry.penalty_type == "incomplete"
    gap = 1.0 - 0.7  # 0.3
    assert entry.amount == pytest.approx(gap * 1.0, abs=0.001)


# ---------------------------------------------------------------------------
# RewardEngine — penalty incomplete above threshold
# ---------------------------------------------------------------------------

def test_penalty_incomplete_above():
    engine = RewardEngine()
    entry = engine.penalty_incomplete(peer_id="p1", completeness=0.96, epoch=1)
    assert entry.penalty_type == "incomplete"
    assert entry.amount == 0.0


# ---------------------------------------------------------------------------
# RewardEngine — penalty stale within acceptable lag
# ---------------------------------------------------------------------------

def test_penalty_stale_within():
    engine = RewardEngine()
    entry = engine.penalty_stale(peer_id="p1", epochs_behind=2, epoch=1)
    assert entry.penalty_type == "stale"
    assert entry.amount == 0.0  # within max_lag_epochs=3


# ---------------------------------------------------------------------------
# RewardEngine — penalty stale excess
# ---------------------------------------------------------------------------

def test_penalty_stale_excess():
    engine = RewardEngine()
    entry = engine.penalty_stale(peer_id="p1", epochs_behind=5, epoch=1)
    assert entry.penalty_type == "stale"
    excess = 5 - 3  # 2 epochs over max_lag
    assert entry.amount == pytest.approx(excess * 0.05, abs=0.001)


# ---------------------------------------------------------------------------
# RewardEngine — penalty inconsistent
# ---------------------------------------------------------------------------

def test_penalty_inconsistent():
    engine = RewardEngine()
    entry = engine.penalty_inconsistent(
        peer_id="p1", discrepancy_count=4, epoch=1
    )
    assert entry.penalty_type == "inconsistent"
    assert entry.amount == 0.4  # 4 * 0.1


# ---------------------------------------------------------------------------
# RewardEngine — epoch settlement
# ---------------------------------------------------------------------------

def test_epoch_settlement():
    engine = RewardEngine()
    result = engine.epoch_settlement(
        peer_id="p1",
        epoch=1,
        objects_stored=100,
        objects_served=50,
        objects_verified=200,
        epochs_synced=5,
        completeness=1.0,
        epochs_behind=0,
        discrepancy_count=0,
    )
    assert isinstance(result, SettlementResult)
    assert result.peer_id == "p1"
    assert result.epoch == 1
    # rewards: 1.0 + 1.0 + 1.0 + 0.5 = 3.5
    assert result.total_rewards == pytest.approx(3.5, abs=0.001)
    # no penalties (completeness=1.0, epochs_behind=0, no discrepancies)
    assert result.total_penalties == 0.0
    assert result.net_balance == pytest.approx(3.5, abs=0.001)


# ---------------------------------------------------------------------------
# SettlementResult — frozen model
# ---------------------------------------------------------------------------

def test_settlement_result_frozen():
    result = SettlementResult(
        peer_id="p1",
        epoch=1,
        total_rewards=10.0,
        total_penalties=2.0,
        net_balance=8.0,
    )
    with pytest.raises(Exception):
        result.net_balance = 0.0  # type: ignore


# ---------------------------------------------------------------------------
# RewardConfig — defaults
# ---------------------------------------------------------------------------

def test_reward_config_defaults():
    cfg = RewardConfig()
    assert cfg.storage_rate_per_object == 0.01
    assert cfg.serving_rate_per_object == 0.02
    assert cfg.verification_rate_per_object == 0.005
    assert cfg.sync_rate_per_epoch == 0.1
    assert cfg.incomplete_penalty_rate == 1.0
    assert cfg.min_completeness_threshold == 0.95
    assert cfg.stale_penalty_per_epoch == 0.05
    assert cfg.max_lag_epochs == 3
    assert cfg.inconsistent_penalty_per_discrepancy == 0.1


# ---------------------------------------------------------------------------
# RewardEngine — epoch settlement with penalties
# ---------------------------------------------------------------------------

def test_epoch_settlement_full():
    engine = RewardEngine()
    result = engine.epoch_settlement(
        peer_id="p1",
        epoch=1,
        objects_stored=100,
        objects_served=50,
        objects_verified=200,
        epochs_synced=5,
        completeness=0.7,
        epochs_behind=5,
        discrepancy_count=3,
    )
    # rewards: 1.0 + 1.0 + 1.0 + 0.5 = 3.5
    assert result.total_rewards == pytest.approx(3.5, abs=0.001)
    # penalties:
    #   incomplete: (1.0 - 0.7) * 1.0 = 0.3
    #   stale: (5 - 3) * 0.05 = 0.1
    #   inconsistent: 3 * 0.1 = 0.3
    #   total = 0.7
    assert result.total_penalties == pytest.approx(0.7, abs=0.001)
    assert result.net_balance == pytest.approx(2.8, abs=0.001)


# ---------------------------------------------------------------------------
# ParticipantLedger — multiple participants
# ---------------------------------------------------------------------------

def test_ledger_multiple_participants():
    ledger = ParticipantLedger()
    ledger.add_reward(
        RewardEntry(peer_id="p1", reward_type="storage", amount=1.0, epoch=1)
    )
    ledger.add_reward(
        RewardEntry(peer_id="p2", reward_type="serving", amount=2.0, epoch=1)
    )
    ledger.add_penalty(
        PenaltyEntry(peer_id="p3", penalty_type="stale", amount=0.5, epoch=1)
    )

    assert ledger.get_balance("p1") == 1.0
    assert ledger.get_balance("p2") == 2.0
    assert ledger.get_balance("p3") == -0.5
    assert ledger.get_participants() == ["p1", "p2", "p3"]


# ---------------------------------------------------------------------------
# RewardEngine — init
# ---------------------------------------------------------------------------

def test_reward_engine_init():
    engine = RewardEngine()
    assert engine.ledger is not None
    assert isinstance(engine.ledger, ParticipantLedger)
